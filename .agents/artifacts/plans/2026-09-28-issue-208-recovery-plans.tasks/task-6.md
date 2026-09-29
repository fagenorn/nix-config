# Task 6: `settle_recovery` and `rolled_back`

**Files:**
- Modify: `python/agent_tools/transaction_recovery.py` (settlement, two events, pairings)
- Modify: `python/agent_tools/transaction_history.py` (no new dispatch; the key sets grow)
- Modify: `python/agent_tools/transaction_core.py` (`settle_recovery`)
- Create: `tests/test_transaction_recovery_settle.py`
- Modify: `justfile` (add the new file after `tests/test_transaction_recovery.py`)

**Interfaces:**
- Consumes (Tasks 1–5): `_decide(custody, operation, decide)`, `recovery_refused`,
  `RECOVERY_EVENT_KEYS`, `recovery_event_violation`, `recovery_pairing_violation`,
  `recovery_advance_violation`, `RESERVED_RECOVERY_REASONS`, `selection`;
  `transaction_invocation.fold_actions`, `satisfied`, `status`, `refusal`, `unresolved`;
  `RecoveryCase` with `grant`, `begin`, `run`, `parked`, `published` and `refused`.
- Produces:
  - `transaction_recovery.recovery_settlement(document, now_ms: int) -> list[dict]`.
  - `transaction_recovery.settled_citations(plan, selected: list[str]) -> tuple[list[str],
    list[dict]]` returns `(restored, residue)`. Writer and validator share it.
  - `TransactionStore.settle_recovery(custody) -> Transaction`, defined as
    `self._decide(custody, "settle_recovery", recovery_settlement)`.
  - `tests/test_transaction_recovery_settle.py`: `SettleCase(RecoveryCase)` with
    `recovering()`, `edge(action, unit, outcome=None, results=())` and `settle()`. Task 7
    appends to this file.

**Invariants:**
- `recovery_settlement` refuses `state_not_recovering` outside `recovering`. It reads the
  latest `recovery_started`'s `selected`, then decides the first matching case (per D9):
  1. **Rolled back.** Every selected edge is `satisfied`. `TransitionRefused` while
     `unresolved(fold_actions(events))` names an action; the message names that action's id
     and status. Otherwise it returns `[{"type": "recovery_settled", "restored", "residue",
     "fence"}, {"type": "transitioned", "from": "recovering", "to": "rolled_back",
     "reason": "recovery_settled", "external_state": "known"}]`. `_append` adds the
     terminal `lease_released`.
  2. **Incomplete.** Some selected edge is `diverged` or `unknown`, or is `absent` with an
     inspection under the held fence and `refusal(...)` in `("not_retryable",
     "budget_exhausted", "window_closed")` at `now_ms`. It returns `[{"type":
     "recovery_incomplete", "actions": <those edges in selection order>, "fence"},
     {"type": "transitioned", "from": "recovering", "to": "attention_required", "reason":
     "recovery_incomplete", "external_state": "unknown" if any listed edge is unknown else
     "known"}]`.
  3. **Pending.** Otherwise it refuses `recovery_pending`, with nothing written.
- `settled_citations`: `restored` lists, in selection order, the unit action id of each
  selected `restore` edge. `residue` lists `{"unit": <unit action id>, "residue": <the
  edge's residue>}` for each selected `compensate` edge (per D4, D9).
- `RECOVERY_EVENT_KEYS` gains `recovery_settled` (`{restored, residue, fence}`) and
  `recovery_incomplete` (`{actions, fence}`). Both happen in `recovering`, fenced by the
  open span. `recovery_settled` needs every selected edge `satisfied` in the fold before
  it, and `restored` and `residue` equal to `settled_citations`, else rules containing
  `restored` or `residue`. `recovery_incomplete` needs `actions` to be a non-empty list of
  selected edges in selection order, none `satisfied`, else a rule containing `actions`.
  The retry window is not re-judged (per D10).
- `recovery_pairing_violation` gains two pairs. `recovery_settled` is immediately followed
  by `recovering → rolled_back` with reason `recovery_settled`, and every transition into
  `rolled_back` immediately follows `recovery_settled`. `recovery_incomplete` is
  immediately followed by `recovering → attention_required` with reason
  `recovery_incomplete`. Failure strings name the event.
- `recovery_advance_violation` gains target `rolled_back`, with a rule containing
  `settle_recovery`. The reserved reasons are already refused.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_transaction_recovery_settle.py`:

```python
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
        return self.run(action, {"unit": unit}, outcome, results)

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
```

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_recovery_settle.py 2>&1 | tail -3`.
  Expected: ERRORs, because `TransactionStore` has no `settle_recovery`.

- [ ] **Step 3: Implement** the invariants. Write the `settle_recovery` docstring and the
  module docstrings from the resulting code.

- [ ] **Step 4: Verify.**
  Run the slice unit command with all three recovery test files. Expected: `OK`.

```bash
grep -q "tests/test_transaction_recovery_settle.py" justfile || exit 1
grep -q "def settle_recovery" python/agent_tools/transaction_core.py || exit 1
```

  Run: `git add -A python tests justfile && just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.** Stage exactly this task's **Files**, then:

```bash
git commit -m "feat(transaction-core): judge recovery into rolled_back or recovery_incomplete (#208)"
```

- [ ] **Step 6: Check the review budget** with `FILES="python/agent_tools/transaction_recovery.py python/agent_tools/transaction_history.py python/agent_tools/transaction_core.py tests/test_transaction_recovery_settle.py"`.
  Expected: exit 0.

Decisions: per D4, D9, D10, D19, D20, D25.
