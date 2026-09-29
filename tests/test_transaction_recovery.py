"""Transaction core slice 5: rollback anchors, entering recovery and its edges (#208).

Run: just agent-workflow-tests
"""

import copy
import unittest

from agent_tools.transaction_core import (
    RECOVERY_REFUSAL_REASONS, EffectResultInvalid, InvocationRefused, RecoveryRefused,
    StaleCustody, TransactionError, TransitionRefused, action_id)

from .test_transaction_custody import KEYS, SUBJECT, TTL, CustodyCase, plain, serialize
from .test_transaction_invocation import Crash, FakeEffect, FakeWorld, renumbered
from .test_transaction_recovery_plan import ANCHOR, COMPATIBLE, PROOF, RECOVERY, edge, with_unit


class Boom(Exception):
    """An observer that must never be reached."""


class Checker:
    """An in-memory anchor and compatibility observer. `outcomes` maps a check (`anchor`,
    `compatibility`) to its outcome, default `satisfied`; `result` replaces the reply;
    `fail` is raised; `during` runs first. The reference encodes the request."""

    def __init__(self, outcomes=None, *, result=None, fail=None, during=None):
        self.outcomes, self.result, self.fail, self.during = outcomes or {}, result, fail, during

    def observe(self, request):
        if self.during:
            self.during()
        if self.fail is not None:
            raise self.fail
        if self.result is not None:
            return self.result
        outcome = self.outcomes.get(request["check"], "satisfied")
        epoch = min(entry["epoch"] for entry in request["fence"].values())
        return {"outcome": outcome, "reason": "ok" if outcome == "satisfied" else "gone",
                "reference": "|".join((request["check"], request["predicate"],
                                       request["collector"], request["parameters"]["prior"],
                                       request["unit"], str(epoch)))}


class Reusing:
    """An observer that answers every call by refilling one dict, taking the outcomes in
    call order: a store must keep what it validated, not the observer's object."""

    def __init__(self, *outcomes):
        self.outcomes, self.calls, self.reply = list(outcomes), 0, {}

    def observe(self, request):
        outcome = self.outcomes[self.calls]
        self.calls += 1
        self.reply.clear()
        self.reply.update(outcome=outcome, reason="ok" if outcome == "satisfied" else "gone",
                          reference=f"ref-{self.calls}")
        return self.reply


TWO_RESTORABLE = with_unit(2, posture="restorable", anchor=ANCHOR, compatibility=COMPATIBLE,
                           edges=[edge("restore", "pin")])


class RecoveryCase(CustodyCase):
    def setUp(self):
        super().setUp()
        self.world = FakeWorld()
        self.start_with(RECOVERY)

    def start_with(self, recovery, key="recovery", keys=KEYS):
        self.transaction_id = self.store.create(key, SUBJECT, concurrency_keys=keys,
                                                proof=PROOF, recovery=recovery).transaction_id
        self.custody = self.acquire(self.transaction_id)

    def act(self, name, **parameters):
        return action_id(self.transaction_id, name, parameters)

    def to(self, *targets, reason="r"):
        for target in targets:
            after = self.store.advance(self.transaction_id, target, reason=reason,
                                       external_state="known", custody=self.custody)
        return after

    def verify(self, checker=None):
        return self.store.verify_anchors(self.custody, observer=checker or Checker())

    def grant(self, grant_id="g-1"):
        return self.store.issue_grant(self.custody, grant_id=grant_id, actor="operator")

    def begin(self, grant_id="g-1", checker=None):
        return self.store.begin_recovery(self.custody, grant_id=grant_id,
                                         observer=checker or Checker())

    def run_action(self, name, parameters, outcome=None, results=()):
        self.store.inspect_action(self.custody, name=name, parameters=parameters,
                                  effect=FakeEffect(self.world))
        return self.store.invoke_action(
            self.custody, name=name, parameters=parameters,
            effect=FakeEffect(self.world, inspect_outcome=outcome, results=results))

    def published(self):
        self.to("awaiting_verification", "ready")
        self.verify()
        self.to("publishing")
        self.run_action("build", {"n": 1})

    def parked(self, start="diverged", pin=None):
        self.published()
        self.to("published", "activating")
        self.run_action("start", {"n": 2}, start)
        if pin:
            self.run_action("pin", {"n": 3}, pin)
        return self.to("attention_required")

    def refused(self, reason, call):
        error = self.assertRefusedUnchanged(RecoveryRefused, call)
        self.assertEqual(error.reason, reason)
        self.assertIn(self.transaction_id, str(error))
        return error


class AnchorsTest(RecoveryCase):
    def test_verification_records_each_restorable_anchor_under_the_fence(self):
        self.to("awaiting_verification", "ready")
        after = self.verify()
        event = dict(after.events[-1])
        start = self.act("start", n=2)
        self.assertEqual((event["type"], event["fence"]),
                         ("anchors_verified", plain(self.custody.fence)))
        self.assertEqual(event["anchors"], [
            {"unit": start, "reference": f"anchor|rollback_anchor|c|gen-1|{start}|1"}])
        self.assertEqual(self.to("publishing").state, "publishing")

    def test_verification_outside_ready_is_refused_without_a_call(self):
        self.refused("state_not_ready", lambda: self.verify(Checker(fail=Boom())))

    def test_a_missing_or_unverifiable_anchor_refuses_before_publication(self):
        self.to("awaiting_verification", "ready")
        for outcome in ("unsatisfied", "unknown"):
            with self.subTest(outcome=outcome):
                error = self.refused("rollback_anchor_missing",
                                     lambda: self.verify(Checker({"anchor": outcome})))
                self.assertIn(f"start ({self.act('start', n=2)})", str(error))
        error = self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("publishing"))
        self.assertIn("anchors_verified", str(error))

    def test_a_reused_result_object_cannot_rewrite_an_earlier_outcome(self):
        self.start_with(TWO_RESTORABLE, key="two", keys=("key:two",))
        self.to("awaiting_verification", "ready")
        error = self.refused("rollback_anchor_missing",
                             lambda: self.verify(Reusing("unsatisfied", "satisfied")))
        self.assertIn(f"start ({self.act('start', n=2)})", str(error))
        self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("publishing"))

    def test_publication_needs_a_verification_under_the_entering_fence(self):
        self.to("awaiting_verification", "ready")
        self.verify()
        self.clock.advance(TTL)
        self.store.reap(self.transaction_id, reason="executor lost")
        self.custody = self.acquire(self.transaction_id)
        self.to("ready")
        self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("publishing"))
        self.verify()
        self.assertEqual(self.to("publishing").state, "publishing")

    def test_a_resume_to_publishing_is_ungated(self):
        self.published()
        self.clock.advance(TTL)
        self.store.reap(self.transaction_id, reason="executor lost")
        self.custody = self.acquire(self.transaction_id)
        self.assertEqual(self.to("publishing").state, "publishing")

    def test_no_restorable_unit_means_no_call_and_no_write(self):
        self.start_with(with_unit(1, posture="manual_only", anchor=None, compatibility=None,
                                  edges=[]), key="plain", keys=("key:plain",))
        self.to("awaiting_verification", "ready")
        before = self.files()
        self.verify(Checker(fail=Boom()))
        self.assertEqual(self.files(), before)
        self.assertEqual(self.to("publishing").state, "publishing")

    def test_a_malformed_result_or_a_raising_observer_records_nothing(self):
        self.to("awaiting_verification", "ready")
        for checker, error in (
                (Checker(result={"outcome": "satisfied"}), EffectResultInvalid),
                (Checker(result={"outcome": "maybe", "reason": "r", "reference": "x"}),
                 EffectResultInvalid),
                (Checker(result={"outcome": "satisfied", "reason": "", "reference": "x"}),
                 EffectResultInvalid),
                (Checker(fail=Boom()), Boom)):
            with self.subTest(checker=checker.result):
                self.assertRefusedUnchanged(error, lambda: self.verify(checker))

    def test_a_lapse_during_the_call_writes_nothing(self):
        self.to("awaiting_verification", "ready")
        self.assertRefusedUnchanged(StaleCustody, lambda: self.verify(
            Checker(during=lambda: self.clock.advance(TTL))))

    def test_a_history_grown_during_the_call_is_refused(self):
        self.to("awaiting_verification", "ready")
        grow = lambda: self.store.issue_grant(self.custody, grant_id="during", actor="op")
        with self.assertRaises(RecoveryRefused) as caught:
            self.verify(Checker(during=grow))
        self.assertEqual(caught.exception.reason, "history_changed")
        self.assertNotIn("anchors_verified", self.types(self.transaction_id))

    def test_hand_built_anchor_breaches_are_state_invalid(self):
        self.to("awaiting_verification", "ready")
        self.verify()
        document = self.state_doc(self.transaction_id)
        emptied = copy.deepcopy(document)
        emptied["events"][-1]["anchors"] = []
        self.assertRuleRefuses(self.transaction_id, emptied, "anchors")
        skipped = copy.deepcopy(document)
        skipped["events"][-1] = {
            "seq": 0, "type": "transitioned", "at": document["events"][-1]["at"],
            "from": "ready", "to": "publishing", "reason": "r", "external_state": "known"}
        skipped["state"] = "publishing"
        self.assertRuleRefuses(self.transaction_id, renumbered(skipped), "anchors_verified")


class BeginTest(RecoveryCase):
    def test_begin_freezes_the_snapshot_selects_every_edge_and_enters_recovering(self):
        self.parked()
        self.grant()
        after = self.begin()
        started, moved = (dict(e) for e in after.events[-2:])
        build, start, pin = self.act("build", n=1), self.act("start", n=2), self.act("pin", n=3)
        self.assertEqual(started["effect_snapshot"], {
            build: "target_satisfied", start: "diverged", pin: "no_effect"})
        self.assertEqual(started["selected"], [
            self.act("compensate", unit="build"), self.act("restore", unit="start"),
            self.act("compensate", unit="start")])
        self.assertEqual([check["unit"] for check in started["checks"]], [start])
        self.assertEqual((started["grant_id"], started["fence"]),
                         ("g-1", plain(self.custody.fence)))
        self.assertEqual((moved["from"], moved["to"], moved["reason"], moved["external_state"]),
                         ("attention_required", "recovering", "recovery_started", "known"))
        self.assertEqual(after.state, "recovering")
        self.assertEqual((dict(after.recovery["effect_snapshot"]), list(after.recovery["selected"])),
                         (started["effect_snapshot"], started["selected"]))

    def test_an_affected_compensatable_unit_alone_needs_no_check(self):
        self.published()
        self.to("attention_required")
        self.grant()
        after = self.begin(checker=Checker(fail=Boom()))
        self.assertEqual(list(after.recovery["selected"]), [self.act("compensate", unit="build")])
        self.assertEqual(after.events[-2]["checks"], [])

    def test_begin_outside_attention_or_without_a_fresh_grant_is_refused(self):
        self.to("awaiting_verification")
        self.grant("early")
        self.refused("state_not_attention", lambda: self.begin("early"))
        self.to("attention_required")
        self.refused("grant_required", lambda: self.begin("early"))
        self.refused("grant_required", lambda: self.begin("never-issued"))

    def test_an_action_inspected_under_an_older_fence_needs_reconciliation(self):
        self.parked()
        self.clock.advance(TTL)
        self.store.reap(self.transaction_id, reason="executor lost")
        self.custody = self.acquire(self.transaction_id)
        self.grant()
        self.refused("reconciliation_required", lambda: self.begin(checker=Checker(fail=Boom())))
        for name, parameters in (("build", {"n": 1}), ("start", {"n": 2})):
            self.store.inspect_action(self.custody, name=name, parameters=parameters,
                                      effect=FakeEffect(self.world))
        self.assertEqual(self.begin().state, "recovering")

    def test_an_open_attempt_needs_reconciliation(self):
        self.published()
        self.to("published", "activating")
        self.store.inspect_action(self.custody, name="start", parameters={"n": 2},
                                  effect=FakeEffect(self.world))
        with self.assertRaises(Crash):
            self.store.invoke_action(self.custody, name="start", parameters={"n": 2},
                                     effect=FakeEffect(self.world, crash="before"))
        self.to("attention_required")
        self.grant()
        self.refused("reconciliation_required", lambda: self.begin(checker=Checker(fail=Boom())))

    def test_an_undeclared_effect_or_an_uncertain_unit_is_refused(self):
        self.published()
        self.run_action("extra", {"n": 9})
        self.to("attention_required")
        self.grant()
        self.refused("undeclared_effect", lambda: self.begin(checker=Checker(fail=Boom())))
        for outcome in ("unknown", "in_progress"):
            with self.subTest(outcome=outcome):
                self.start_with(RECOVERY, key=outcome, keys=(f"key:{outcome}",))
                self.parked(start=outcome)
                self.grant()
                error = self.refused("effect_uncertain",
                                     lambda: self.begin(checker=Checker(fail=Boom())))
                self.assertIn(self.act("start", n=2), str(error))

    def test_no_affected_unit_is_refused_no_effect(self):
        self.to("awaiting_verification", "ready")
        self.verify()
        self.to("attention_required")
        self.grant()
        self.refused("no_effect", lambda: self.begin(checker=Checker(fail=Boom())))

    def test_an_affected_non_restorable_unit_is_refused_before_any_check(self):
        self.parked(pin="diverged")
        self.grant()
        error = self.refused("unit_not_restorable",
                             lambda: self.begin(checker=Checker(fail=Boom())))
        self.assertIn(f"pin ({self.act('pin', n=3)})", str(error))
        self.start_with(with_unit(1, posture="supersedable_only", anchor=None,
                                  compatibility=None, edges=[]),
                        key="forward-only", keys=("key:forward-only",))
        self.parked()
        self.grant()
        error = self.refused("unit_not_restorable",
                             lambda: self.begin(checker=Checker(fail=Boom())))
        self.assertIn("start (", str(error))

    def test_an_incompatible_restore_is_refused_after_the_check(self):
        self.parked()
        self.grant()
        for outcome in ("unsatisfied", "unknown"):
            with self.subTest(outcome=outcome):
                error = self.refused("restore_incompatible", lambda: self.begin(
                    checker=Checker({"compatibility": outcome})))
                self.assertIn("start (", str(error))

    def test_a_reused_result_object_cannot_hide_an_incompatible_restore(self):
        self.start_with(TWO_RESTORABLE, key="two", keys=("key:two",))
        self.parked(pin="diverged")
        self.grant()
        error = self.refused("restore_incompatible",
                             lambda: self.begin(checker=Reusing("unsatisfied", "satisfied")))
        self.assertIn("start (", str(error))

    def test_a_history_grown_during_the_check_is_refused(self):
        self.parked()
        self.grant()
        grow = lambda: self.store.issue_grant(self.custody, grant_id="during", actor="op")
        with self.assertRaises(RecoveryRefused) as caught:
            self.begin(checker=Checker(during=grow))
        self.assertEqual(caught.exception.reason, "history_changed")
        self.assertEqual(self.store.load(self.transaction_id).state, "attention_required")

    def test_moving_into_recovering_does_not_restart_the_quiescence_window(self):
        self.parked()
        self.grant()
        self.clock.advance(400_000)
        self.store.renew(self.custody)
        self.begin()
        self.clock.advance(400_000)
        self.store.renew(self.custody)
        self.clock.advance(100_001)
        self.assertIsNone(self.store.renew(self.custody).custody)


class AbandonAndReservedTest(RecoveryCase):
    def test_abandoned_needs_every_action_without_effect(self):
        self.parked()
        error = self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("abandoned"))
        self.assertIn(self.act("build", n=1), str(error))

    def test_an_inspected_but_never_invoked_action_has_no_effect(self):
        self.to("awaiting_verification", "ready")
        self.verify()
        self.to("publishing")
        self.store.inspect_action(self.custody, name="build", parameters={"n": 1},
                                  effect=FakeEffect(self.world, inspect_outcome="satisfied"))
        self.to("attention_required")
        self.assertEqual(self.to("abandoned").state, "abandoned")

    def test_advance_never_enters_recovering_nor_writes_recovery_started(self):
        self.parked()
        error = self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("recovering"))
        self.assertIn("begin_recovery", str(error))
        self.assertRefusedUnchanged(TransitionRefused,
                                    lambda: self.to("activating", reason="recovery_started"))

    def test_hand_built_recovery_breaches_are_state_invalid(self):
        self.parked()
        parked = self.state_doc(self.transaction_id)
        at = parked["events"][-1]["at"]

        def moved(document, target):
            document = copy.deepcopy(document)
            document["events"].append({"seq": 0, "type": "transitioned", "at": at,
                                       "from": "attention_required", "to": target,
                                       "reason": "r", "external_state": "known"})
            document.update(state=target, parked_from=None)
            return renumbered(document)

        self.assertRuleRefuses(self.transaction_id, moved(parked, "abandoned"),
                               self.act("build", n=1))
        self.assertRuleRefuses(self.transaction_id, moved(parked, "recovering"),
                               "recovery_started")
        (self.root / self.transaction_id / "state.json").write_text(serialize(parked))
        self.grant()
        self.begin()
        begun = self.state_doc(self.transaction_id)
        pin = self.act("pin", n=3)
        for field, value, fragment in (
                ("effect_snapshot", {**begun["events"][-2]["effect_snapshot"], pin: "diverged"},
                 "effect_snapshot"),
                ("selected", begun["events"][-2]["selected"][:1], "selected"),
                ("checks", [], "checks"),
                ("grant_id", "never-issued", "grant_required")):
            with self.subTest(field=field):
                edited = copy.deepcopy(begun)
                edited["events"][-2][field] = value
                self.assertRuleRefuses(self.transaction_id, edited, fragment)


class EdgeTest(RecoveryCase):
    def recovering(self):
        self.parked()
        self.grant()
        return self.begin()

    def invoke(self, name, parameters):
        return self.store.invoke_action(self.custody, name=name, parameters=parameters,
                                        effect=FakeEffect(self.world))

    def not_selected(self, call):
        error = self.assertRefusedUnchanged(InvocationRefused, call)
        self.assertEqual(error.reason, "not_selected")

    def test_a_selected_edge_runs_through_intent_and_inspection(self):
        self.recovering()
        after = self.run_action("restore", {"unit": "start"})
        view = next(v for v in after.actions if v["action_id"] == self.act("restore", unit="start"))
        self.assertEqual((view["status"], view["attempts"]), ("satisfied", 1))
        again = self.invoke("restore", {"unit": "start"})
        self.assertEqual(again.revision, after.revision)

    def test_forward_or_unselected_actions_are_refused_in_recovering(self):
        self.recovering()
        for name, parameters in (("build", {"n": 1}), ("pin", {"n": 3}),
                                 ("extra", {"n": 9})):
            with self.subTest(name=name):
                self.store.inspect_action(self.custody, name=name, parameters=parameters,
                                          effect=FakeEffect(self.world))
                self.not_selected(lambda: self.invoke(name, parameters))

    def test_a_plan_edge_is_refused_outside_recovering(self):
        self.published()
        self.store.inspect_action(self.custody, name="compensate",
                                  parameters={"unit": "build"}, effect=FakeEffect(self.world))
        self.not_selected(lambda: self.invoke("compensate", {"unit": "build"}))
        self.store.inspect_action(self.custody, name="extra", parameters={"n": 9},
                                  effect=FakeEffect(self.world))
        self.assertEqual(self.invoke("extra", {"n": 9}).state, "publishing")

    def test_a_hand_built_intent_of_an_unselected_edge_is_state_invalid(self):
        self.published()
        self.store.inspect_action(self.custody, name="compensate",
                                  parameters={"unit": "build"}, effect=FakeEffect(self.world))
        document = self.state_doc(self.transaction_id)
        document["events"].append({
            "seq": 0, "type": "invocation_intended", "at": document["events"][-1]["at"],
            "action_id": self.act("compensate", unit="build"), "attempt": 1,
            "fence": plain(self.custody.fence)})
        self.assertRuleRefuses(self.transaction_id, renumbered(document), "not_selected")

    def test_a_hand_built_intent_of_an_unselected_action_in_recovering_is_state_invalid(self):
        self.recovering()
        self.store.inspect_action(self.custody, name="pin", parameters={"n": 3},
                                  effect=FakeEffect(self.world))
        document = self.state_doc(self.transaction_id)
        document["events"].append({
            "seq": 0, "type": "invocation_intended", "at": document["events"][-1]["at"],
            "action_id": self.act("pin", n=3), "attempt": 1,
            "fence": plain(self.custody.fence)})
        self.assertRuleRefuses(self.transaction_id, renumbered(document),
                               "is not_selected in recovering")


class RecoveryVocabularyTest(unittest.TestCase):
    def test_the_refusal_reasons_are_closed(self):
        self.assertEqual(RECOVERY_REFUSAL_REASONS, (
            "state_not_ready", "state_not_attention", "state_not_recovering",
            "history_changed", "rollback_anchor_missing", "grant_required",
            "reconciliation_required", "undeclared_effect", "effect_uncertain", "no_effect",
            "unit_not_restorable", "restore_incompatible", "recovery_pending"))
        self.assertTrue(issubclass(RecoveryRefused, TransactionError))


if __name__ == "__main__":
    unittest.main()
