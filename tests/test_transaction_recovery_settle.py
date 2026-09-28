"""Transaction core slice 5: settling recovery and rolling forward (#208).

Run: just agent-workflow-tests
"""

import copy
import unittest

from agent_tools.transaction_core import RecoveryRefused, TransitionRefused

from .test_transaction_invocation import FakeEffect, renumbered
from .test_transaction_recovery import RecoveryCase
from .test_transaction_recovery_plan import RECOVERY


class SettleCase(RecoveryCase):
    def recovering(self, **parked):
        self.parked(**parked)
        self.grant()
        return self.begin()

    def edge(self, action, unit, outcome=None, results=()):
        return self.run_action(action, {"unit": unit}, outcome, results)

    def settle(self):
        return self.store.settle_recovery(self.custody)

    def all_edges(self):
        for action, unit in (("compensate", "build"), ("restore", "start"),
                             ("compensate", "start")):
            after = self.edge(action, unit)
        return after


class SettleTest(SettleCase):
    def test_every_selected_edge_satisfied_rolls_back_citing_restores_and_residue(self):
        self.recovering()
        self.all_edges()
        after = self.settle()
        settled = next(dict(e) for e in after.events if e["type"] == "recovery_settled")
        build, start = self.act("build", n=1), self.act("start", n=2)
        self.assertEqual(settled["restored"], [start])
        self.assertEqual(settled["residue"], [
            {"unit": build, "residue": "old build stays cached"},
            {"unit": start, "residue": "cache cleared"}])
        self.assertEqual([e["type"] for e in after.events[-3:]],
                         ["recovery_settled", "transitioned", "lease_released"])
        moved = after.events[-2]
        self.assertEqual((moved["from"], moved["to"], moved["reason"], moved["external_state"]),
                         ("recovering", "rolled_back", "recovery_settled", "known"))
        self.assertEqual((after.state, after.custody), ("rolled_back", None))

    def test_a_compensatable_unit_rolls_back_through_its_compensate_edge_alone(self):
        self.published()
        self.to("attention_required")
        self.grant()
        self.begin()
        self.edge("compensate", "build")
        after = self.settle()
        settled = next(dict(e) for e in after.events if e["type"] == "recovery_settled")
        self.assertEqual((settled["restored"], [r["unit"] for r in settled["residue"]]),
                         ([], [self.act("build", n=1)]))
        self.assertNotIn(self.act("restore", unit="build"),
                         [a["action_id"] for a in after.actions])
        self.assertEqual(after.state, "rolled_back")

    def test_settling_outside_recovering_or_before_the_edges_finish_is_refused(self):
        self.parked()
        self.refused("state_not_recovering", self.settle)
        self.grant()
        self.begin()
        self.refused("recovery_pending", self.settle)
        self.edge("compensate", "build")
        self.refused("recovery_pending", self.settle)
        self.edge("restore", "start", results=[("rejected", "provider_throttled")])
        self.refused("recovery_pending", self.settle)

    def test_rolled_back_is_refused_over_an_unresolved_action(self):
        self.recovering()
        self.all_edges()
        self.store.inspect_action(self.custody, name="start", parameters={"n": 2},
                                  effect=FakeEffect(self.world, inspect_outcome="unknown"))
        error = self.assertRefusedUnchanged(TransitionRefused, self.settle)
        self.assertIn(self.act("start", n=2), str(error))

    def test_a_diverged_unknown_or_unretryable_edge_parks_recovery_incomplete(self):
        for outcome, results, external in (("diverged", (), "known"), ("unknown", (), "unknown"),
                                           (None, [("rejected", "invalid_input")], "known")):
            with self.subTest(outcome=outcome, results=results):
                key = f"key:{outcome}:{len(results)}"
                self.start_with(RECOVERY, key=key, keys=(key,))
                self.recovering()
                self.edge("compensate", "build")
                self.edge("restore", "start", outcome, results)
                after = self.settle()
                incomplete, moved = (dict(e) for e in after.events[-2:])
                self.assertEqual((incomplete["type"], incomplete["actions"]),
                                 ("recovery_incomplete", [self.act("restore", unit="start")]))
                self.assertEqual((moved["to"], moved["reason"], moved["external_state"]),
                                 ("attention_required", "recovery_incomplete", external))
                self.assertEqual(after.custody, self.custody)

    def test_a_re_begun_recovery_needs_a_new_grant_and_keeps_its_satisfied_edge(self):
        self.recovering()
        self.edge("compensate", "build")
        self.edge("restore", "start", "diverged")
        self.settle()
        self.refused("grant_required", lambda: self.begin("g-1"))
        self.grant("g-2")
        again = self.begin("g-2")
        self.assertEqual(list(again.recovery["selected"])[0], self.act("compensate", unit="build"))
        kept = self.store.invoke_action(self.custody, name="compensate",
                                        parameters={"unit": "build"},
                                        effect=FakeEffect(self.world))
        self.assertEqual(kept.revision, again.revision)
        self.assertEqual(self.world.invokes[self.act("compensate", unit="build")], 1)

    def test_advance_never_enters_rolled_back_nor_writes_a_reserved_reason(self):
        self.recovering()
        self.all_edges()
        error = self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("rolled_back"))
        self.assertIn("settle_recovery", str(error))
        for reason in ("recovery_settled", "recovery_incomplete"):
            with self.subTest(reason=reason):
                self.assertRefusedUnchanged(TransitionRefused, lambda: self.to(
                    "attention_required", reason=reason))

    def test_rolled_back_is_terminal(self):
        self.recovering()
        self.all_edges()
        self.settle()
        for call in (self.settle, lambda: self.to("attention_required")):
            self.assertRefusedUnchanged(TransitionRefused, call)

    def test_hand_built_settlement_breaches_are_state_invalid(self):
        self.recovering()
        self.all_edges()
        self.settle()
        document = self.state_doc(self.transaction_id)
        index = next(i for i, e in enumerate(document["events"])
                     if e["type"] == "recovery_settled")
        for field, value in (("restored", []), ("residue", [])):
            with self.subTest(field=field):
                edited = copy.deepcopy(document)
                edited["events"][index][field] = value
                self.assertRuleRefuses(self.transaction_id, edited, field)
        dropped = copy.deepcopy(document)
        del dropped["events"][index]
        for seq, event in enumerate(dropped["events"], start=1):
            event["seq"] = seq
        dropped["revision"] = len(dropped["events"])
        self.assertRuleRefuses(self.transaction_id, dropped, "recovery_settled")

    def test_hand_built_incomplete_breaches_are_state_invalid(self):
        self.recovering()
        self.edge("compensate", "build")
        self.edge("restore", "start", "diverged")
        self.settle()
        document = self.state_doc(self.transaction_id)
        index = next(i for i, e in enumerate(document["events"])
                     if e["type"] == "recovery_incomplete")
        for name, actions in (("empty", []),
                              ("satisfied", [self.act("compensate", unit="build")])):
            with self.subTest(actions=name):
                edited = copy.deepcopy(document)
                edited["events"][index]["actions"] = actions
                self.assertRuleRefuses(self.transaction_id, edited, "actions")
        dropped = copy.deepcopy(document)
        del dropped["events"][index]
        self.assertRuleRefuses(self.transaction_id, renumbered(dropped), "recovery_incomplete")


if __name__ == "__main__":
    unittest.main()
