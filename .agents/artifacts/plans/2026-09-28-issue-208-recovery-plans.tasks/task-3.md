# Task 3: `verify_anchors` and the publication gate

**Files:**
- Modify: `python/agent_tools/transaction_recovery.py` (refusals, check requests, anchors)
- Modify: `python/agent_tools/transaction_history.py` (dispatch recovery events and the gate)
- Modify: `python/agent_tools/transaction_storage.py` (`RecoveryRefused`)
- Modify: `python/agent_tools/transaction_core.py` (`verify_anchors`, `_observed`, `advance`)
- Create: `tests/test_transaction_recovery.py`
- Modify: `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py`
- Modify: `justfile` (add `tests/test_transaction_recovery.py` after the plan test)

**Interfaces:**
- Consumes (Tasks 1–2): the stored `recovery_plan` and `proof_plan` (a proof unit's
  `collector`, matched by `action_id`), `Transaction.recovery_plan`, and the test constants
  `PROOF`, `RECOVERY`, `with_unit`.
- Produces (`agent_tools.transaction_storage`): `class RecoveryRefused(TransactionError)`,
  shaped like `ProofRefused` (keyword `reason`, `.reason`).
- Produces (`agent_tools.transaction_recovery`, re-exported by `transaction_core`:
  `RECOVERY_REFUSAL_REASONS`, `RecoveryRefused`):
  - `RECOVERY_REFUSAL_REASONS`, exactly the spec's thirteen reasons in the spec's order.
  - `recovery_refused(transaction_id, reason, detail) -> RecoveryRefused`, with the message
    `f"{transaction_id}: recovery refused: {reason}: {detail}"`; an unknown reason raises
    `ValueError`.
  - `CHECK_OUTCOMES = ("satisfied", "unsatisfied", "unknown")`.
  - `RECOVERY_EVENT_KEYS: Mapping[str, frozenset]`, holding `anchors_verified`: envelope
    plus `{anchors, fence}`. Later tasks add their events here.
  - `unit_label(document, identity: str) -> str` returns `f"{name} ({identity})"` for a
    recovery unit (per D23).
  - `check_requests(document, check: str, units: list[dict]) -> list[Mapping]` returns one
    `MappingProxyType` per unit: `transaction_id`, `unit` (its action id), `check`,
    `predicate`, `collector`, `parameters` (a deep copy) and `fence` (a deep copy of the
    held fence). `check` is `"anchor"` or `"compatibility"`, and it names the unit field
    read.
  - `check_result_violation(result: Any) -> str | None`: exactly `{outcome, reason,
    reference}`, `outcome` in `CHECK_OUTCOMES`, `reason` and `reference` non-empty strings
    (per D21).
  - `anchor_requests(document) -> list[Mapping]`: `state_not_ready` outside `ready`, else
    the anchor requests of every `restorable` unit, in plan order.
  - `anchors_events(document, requests, results) -> list[dict]`: `[]` when there are no
    requests. It raises `rollback_anchor_missing` with detail `f"unit {unit_label} anchor
    {outcome}"` for the first result that is not `satisfied`. Otherwise it returns
    `[{"type": "anchors_verified", "anchors": [{"unit", "reference"}...], "fence": held}]`.
  - `recovery_event_violation(event, events_before, document, *, keys, open_fence, state)
    -> str | None`.
  - `recovery_transition_violation(document, events_before, source, target, open_fence)
    -> str | None`.
  - `recovery_advance_violation(document, target, reason) -> str | None`.
- Produces (`TransactionStore`): `verify_anchors(custody, *, observer) -> Transaction`, and
  the private `_observed(custody, operation, observer, admit, conclude) -> Transaction`,
  which Task 4 reuses.

**Invariants:**
- `_observed` is the shared two-hold helper (per D20; #207 D6). Before any lock:
  `require_custody_shape`, and `StateInvalid` when `observer.observe` is not callable.
  - **First hold** (`_fenced`, writes=True): `requests = admit(prior)`, which may raise. With
    no requests it appends `conclude(prior, [], [])` when that is non-empty and returns the
    snapshot, all in this hold, with no call and, for an empty list, no write.
  - **The calls**: every request goes to `observer.observe` with no lock held. A result
    that fails `check_result_violation` is `EffectResultInvalid`. What the observer raises
    propagates.
  - **Second hold**: `history_changed` when `prior["revision"]` differs from the first
    hold's. Otherwise it appends `conclude(prior, requests, results)`.
- `verify_anchors = _observed(custody, "verify_anchors", observer, anchor_requests,
  anchors_events)` (per D7). Every refusal leaves `state.json` byte-identical.
- The gate (per D7): `recovery_transition_violation` refuses `ready → publishing` when the
  plan has a `restorable` unit and `events_before` holds no `anchors_verified` whose
  `fence == open_fence`. The rule string contains `anchors_verified`, and every other edge
  returns None. `recovery_advance_violation` calls it with the held custody's fence.
  `advance` applies it after the existing `unresolved` terminal check (per D22), and the
  validator applies it to every `transitioned` event, after the `unresolved` check, with
  the open span's fence.
- `recovery_event_violation` for `anchors_verified`: the state is `ready`; the event is
  inside an open span, with `fence_violation` clean and `fence == open_fence`; and `anchors`
  is exactly the restorable units' action ids in plan order, each with a non-empty string
  `reference`. Every failure string contains `anchors`. The history dispatches
  `RECOVERY_EVENT_KEYS` events with `_check_envelope` and then this rule.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_transaction_recovery.py`
  (Tasks 4, 5 and 6 build on `RecoveryCase` and `Checker`):

```python
"""Transaction core slice 5: rollback anchors, entering recovery and its edges (#208).

Run: just agent-workflow-tests
"""

import copy
import unittest

from agent_tools.transaction_core import (
    RECOVERY_REFUSAL_REASONS, EffectResultInvalid, RecoveryRefused, StaleCustody,
    TransactionError, TransitionRefused, action_id)

from .test_transaction_custody import KEYS, SUBJECT, TTL, CustodyCase, plain
from .test_transaction_invocation import FakeEffect, FakeWorld, renumbered
from .test_transaction_recovery_plan import PROOF, RECOVERY, with_unit


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

    def run(self, name, parameters, outcome=None, results=()):
        self.store.inspect_action(self.custody, name=name, parameters=parameters,
                                  effect=FakeEffect(self.world))
        return self.store.invoke_action(
            self.custody, name=name, parameters=parameters,
            effect=FakeEffect(self.world, inspect_outcome=outcome, results=results))

    def published(self):
        self.to("awaiting_verification", "ready")
        self.verify()
        self.to("publishing")
        self.run("build", {"n": 1})

    def parked(self, start="diverged", pin=None):
        self.published()
        self.to("published", "activating")
        self.run("start", {"n": 2}, start)
        if pin:
            self.run("pin", {"n": 3}, pin)
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
```

  In the sweep support, add a router observer, build it in `drive`, and verify anchors
  right after `acquire()` in `ready`:

```python
class _Router:
    """Every anchor or compatibility check goes to its collector binding's adapter hook; an
    adapter `absent` is `unsatisfied` with reason `anchor_absent` (#208)."""

    def __init__(self, adapters):
        self.adapters = adapters

    def observe(self, request):
        seen = self.adapters[request["collector"]].inspect(request["predicate"],
                                                           request["parameters"])
        outcome = {"absent": "unsatisfied"}.get(seen["outcome"], seen["outcome"])
        if outcome not in ("satisfied", "unsatisfied"):
            outcome = "unknown"
        reason = "anchor_absent" if seen["outcome"] == "absent" else outcome
        return {"outcome": outcome, "reason": reason, "reference": seen["payload_ref"]}
```

```python
        acquire()
        try:
            store.verify_anchors(held["custody"], observer=router)
        except RecoveryRefused as refused:
            world.notes.append(str(refused))
            raise _Parked(f"rollback anchors refused: {refused}") from None
        advance("publishing", "publication started")
```

  Here `router = _Router({alias: adapter(alias) for alias in effects})`, and
  `RecoveryRefused` is imported from `agent_tools.transaction_core`. Extend the module
  docstring with one sentence on the verification. In `tests/test_transaction_core_sweep.py`
  `test_every_cell_lands_where_the_table_says`, add
  `self.assertEqual(types.count("anchors_verified"), 0 if shape == "library" else 1)`
  after `types` is bound.

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_recovery.py 2>&1 | tail -3`.
  Expected: an `ImportError` naming `RECOVERY_REFUSAL_REASONS`.

- [ ] **Step 3: Implement** the invariants. `recovery_advance_violation` holds only the gate
  for now; Tasks 4 and 6 extend it. Write the `verify_anchors` and `advance` docstrings,
  the new-module docstring and the `transaction_core` module docstring from the resulting
  code.

- [ ] **Step 4: Verify.**
  Run the slice unit command with `tests/test_transaction_recovery_plan.py
  tests/test_transaction_recovery.py`. Expected: `OK`.

```bash
grep -q "tests/test_transaction_recovery.py" justfile || exit 1
grep -q "def _observed" python/agent_tools/transaction_core.py || exit 1
```

  Run: `git add -A python tests justfile && just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.** Stage exactly this task's **Files**, then:

```bash
git commit -m "feat(transaction-core): verify rollback anchors before publication (#208)"
```

- [ ] **Step 6: Check the review budget** with `FILES="python/agent_tools/transaction_recovery.py python/agent_tools/transaction_history.py python/agent_tools/transaction_core.py tests/test_transaction_recovery.py tests/transaction_core_sweep_support.py"`.
  Expected: exit 0.

Decisions: per D7, D12, D16, D20, D21, D22, D23.
