# Task 4: The cohort: `start_cohort`, `settle_proof` and the typed parkings

**Files:**
- Modify: `python/agent_tools/transaction_proof.py`
- Modify: `python/agent_tools/transaction_history.py` (the pairing check and the view)
- Modify: `python/agent_tools/transaction_core.py` (two operations and one write helper)
- Modify: `tests/test_transaction_proof.py` (append)

**Interfaces:**
- Consumes (Tasks 1–3): the plan's `cohort` (`members`, `makespan_ms`, `margin_ms`,
  `governing_window_ms`), `convergence_window_ms`, `MAX_COHORT_ATTEMPTS`, `evaluate`,
  `proof_refused`, `open_cohort`, `PROOF_EVENT_KEYS`, `ProofFold`, `proof_event_violation`,
  `apply_proof_event` and `proof_view`; `transaction_invocation.fold_actions`, `unresolved`
  and `status`; `transaction_storage.TransitionRefused` and `parse_at`; and the Task 3
  test helpers `ProofCase`, `Observer`, `FakeEffect` and `renumbered`.
- Produces (`agent_tools.transaction_proof`):
  - `COHORT_FAILURE_REASONS = ("fence_changed", "cohort_expired", "member_missing",
    "collection_bound_exceeded", "member_indeterminate")`,
    `RESERVED_REASONS = ("proof_rejected", "proof_did_not_converge")`,
    `SEAL_REASON = "proof_sealed"`.
  - `PROOF_EVENT_KEYS` gains the closed key sets (each with the `seq, type, at`
    envelope):
    - `proof_cohort_started {cohort, fence}`;
    - `proof_cohort_failed {cohort, reason, fence}`;
    - `proof_convergence_exhausted {cohorts, exhausted_by, fence}`;
    - `proof_rejected {obligations, fence}`;
    - `proof_sealed {cohort, proof_cutoff_at, makespan_ms, governing_window_ms,
      advisory_warnings, fence}`.
  - `cohorts(events) -> list[dict]`, one `{cohort, fence, started_ms, status, reason}` per
    started cohort, with `status` in `open | failed | sealed`. `open_cohort(events, fence)`
    now returns the open cohort's number when its fence equals `fence`, else None.
  - `convergence_start_ms(events) -> int | None`: the `at` of the first transition whose
    `to` is `proving`.
  - `cohort_start(document: dict, now_ms: int) -> list[dict]`: the events to append
    (without `seq`/`at`), or raises `ProofRefused`.
  - `settlement(document: dict, now_ms: int) -> list[dict]`: the events to append,
    including the `transitioned` event, or raises `ProofRefused`/`TransitionRefused`.
  - `pairing_violation(previous: Mapping | None, event: Mapping | None) -> str | None`.
- Produces (core): `TransactionStore.start_cohort(custody: Custody) -> Transaction` and
  `TransactionStore.settle_proof(custody: Custody) -> Transaction`.

**Invariants:**
- `collection_refusal` gains its sixth and last rule: `not_cohort_member` when
  `open_cohort(events, held fence)` is not None and the obligation is not one of the
  plan's cohort `members` (per D27). `open_cohort` now reads the cohort events.
- `cohort_start` refuses in this order (per D11):
  1. `state_not_proving`;
  2. `proof_incomplete`, unless every required obligation has an admissible `satisfied`
     observation, whatever its age;
  3. `cohort_open`, when `open_cohort(events, held fence)` is not None;
  4. `convergence_exhausted`, when `len(cohorts) >= MAX_COHORT_ATTEMPTS` or
     `convergence_start_ms + convergence_window_ms - now_ms < makespan_ms + margin_ms`.

  Otherwise it returns `[proof_cohort_failed {cohort: n, reason: "fence_changed"}]` when
  cohort n is open under an older fence, then `[proof_cohort_started {cohort:
  len(cohorts) + 1}]`. Every event carries the held fence.
- `settlement` reads the cutoff as `now_ms` and takes the first matching case (per D10,
  D11, D21, D28). `window_end = convergence_start_ms + convergence_window_ms`.
  0. `state_not_proving` outside `proving`.
  1. **Rejected.** If any required obligation evaluates `rejected`, the events are
     `proof_rejected {obligations: those ids in plan order}` and then `transitioned
     proving → attention_required`, reason `proof_rejected`, external state `known`.
  2. **Seal.** This case applies when all of the following hold:
     - cohort n is open under the held fence;
     - every member has an `obligation_observed` with `cohort == n`;
     - `governing_window_ms` is None or `now_ms - started_ms <= governing_window_ms`;
     - `now_ms <= window_end`;
     - every required obligation evaluates `accepted`.

     If `unresolved(fold_actions(events))` names an action, raise `TransitionRefused` with
     `f"{transaction_id}: settle_proof: seal over unresolved action {action_id}
     ({status})"`. Otherwise the events are `proof_sealed {cohort: n, proof_cutoff_at:
     format_at(now_ms), makespan_ms, governing_window_ms, advisory_warnings}` and then
     `transitioned proving → succeeded`, reason `proof_sealed`, external state `known`.
     `advisory_warnings` lists the advisory ids not evaluating `accepted`, in plan order.
  3. **Cohort failed.** When some cohort n is open, append `proof_cohort_failed {cohort: n,
     reason}`. The reason is the first that applies:
     - `fence_changed` (its fence is not the held one);
     - `cohort_expired` (past the governing window, `now_ms > window_end`, or a member's
       latest in-cohort snapshot has `now_ms > at + freshness_ms`);
     - `member_missing` (a member with no in-cohort observation);
     - `collection_bound_exceeded` (a member's latest in-cohort `latency_ms` is above its
       collector's `max_collection_latency_ms`);
     - `member_indeterminate`.

     Then continue to case 4.
  4. **Exhausted.** With no cohort left open, `exhausted_by` is `budget` when
     `len(cohorts) >= MAX_COHORT_ATTEMPTS`, else `window` when
     `window_end - now_ms < makespan_ms + margin_ms`. Either way, append
     `proof_convergence_exhausted {cohorts: len(cohorts), exhausted_by}` and then
     `transitioned proving → attention_required`, reason `proof_did_not_converge`, external
     state `known`.
  5. With no events (no cohort was open and nothing is exhausted), raise
     `no_open_cohort`. With case 3's event only, return it: the transaction stays in
     `proving`.

  Every non-transition event carries the held fence. `settlement` never produces
  `recovering`, `failed`, `rolled_back`, `abandoned` or any invocation.
- The validator rules, each a `StateInvalid` naming the event seq:
  - every cohort event is in `proving`, with a fence inside and equal to the open span;
  - `proof_cohort_started.cohort == len(cohorts) + 1 <= MAX_COHORT_ATTEMPTS`, with no
    cohort open;
  - `proof_cohort_failed` names the open cohort, its `reason` is in
    `COHORT_FAILURE_REASONS`, and the reason is `fence_changed` exactly when the cohort's
    fence differs from the event's;
  - `proof_convergence_exhausted` has no cohort open, `cohorts == len(cohorts)`,
    `exhausted_by` in `budget | window`, and `budget` only when `cohorts ==
    MAX_COHORT_ATTEMPTS`;
  - `proof_rejected.obligations` is a non-empty, duplicate-free list of required plan ids,
    in plan order;
  - `proof_sealed` names the cohort open under its fence, every plan member has an
    observation in that cohort, `proof_cutoff_at == at`, `makespan_ms` and
    `governing_window_ms` equal the plan's, and `advisory_warnings` is a duplicate-free
    list of advisory plan ids in plan order.
- `pairing_violation` (per D10, D27), called by `validate_state` before each event after the
  first with `(events[seq - 2], event)` and once after the loop with `(events[-1], None)`:
  - `proof_rejected` must be immediately followed by `transitioned proving →
    attention_required`, reason `proof_rejected`;
  - `proof_convergence_exhausted` must be immediately followed by the same edge, reason
    `proof_did_not_converge`;
  - `proof_sealed` must be immediately followed by `transitioned` to `succeeded`;
  - conversely, a `proving → attention_required` transition carrying a reserved reason
    must immediately follow its event.
- Core: `start_cohort` and `settle_proof` refuse a malformed credential before any lock
  (`require_custody_shape`), then run under `_fenced(..., writes=True)`, then append the
  pure function's events in one `state.json` write. A transition among them updates
  `state`/`parked_from`. Entering `succeeded` appends `lease_released` reason `terminal`
  with the held fence, clears `custody` and then clears the lease records under the lease
  lock, exactly as `_advance_locked` does; share that write path rather than copying it.
  Both operations refuse before any write, and neither calls an observer or effect.
- The view's `cohorts` becomes `[{cohort, status, reason}]` (`reason` None unless
  failed), and `proof_cutoff_at` becomes the seal's value, else None.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_transaction_proof.py`
  (above `ProofVocabularyTest`), and in `ProofVocabularyTest` replace
  `test_the_refusal_reasons_are_fixed` with the observed-set pin below:

```python
class CohortCase(ProofCase):
    def ready(self, observer=None):
        """Proving, with every required obligation accepted once, outside any cohort."""
        self.proving()
        return self.collect_required(observer)

    def start(self):
        return self.store.start_cohort(self.custody)

    def settle(self):
        return self.store.settle_proof(self.custody)

    def members(self, observer=None, only=None):
        for member in only or self.plan["cohort"]["members"]:
            after = self.collect(member, observer)
        return after

    def wait(self, ms):
        """Advance the clock by `ms`, renewing custody on the way so it never lapses."""
        while ms > 0:
            step = min(ms, 300_001)
            self.clock.advance(step)
            self.store.renew(self.custody)
            ms -= step

    def types(self):
        return [e["type"] for e in self.store.load(self.transaction_id).events]

    def last(self, event_type):
        return dict(next(e for e in reversed(self.store.load(self.transaction_id).events)
                         if e["type"] == event_type))

    def failed(self):
        self.assertEqual(self.settle().state, "proving")
        return self.last("proof_cohort_failed")["reason"]


class CohortTest(CohortCase):
    def test_a_cohort_starts_once_every_required_obligation_was_accepted(self):
        self.refused("state_not_proving", self.start)
        self.proving()
        self.collect(self.pub)
        self.refused("proof_incomplete", self.start)
        self.collect_required()
        after = self.start()
        self.assertEqual({k: v for k, v in after.events[-1].items() if k not in ("seq", "at")},
                         {"type": "proof_cohort_started", "cohort": 1,
                          "fence": plain(self.custody.fence)})
        self.refused("cohort_open", self.start)
        self.refused("not_cohort_member", lambda: self.collect("vibe", self.observer(step_ms=1)))
        self.assertEqual(self.collect(self.act).events[-1]["cohort"], 1)

    def test_a_cohort_that_opens_during_a_call_refuses_the_observation(self):
        store, custody = self.store, None

        class Starting(Observer):
            def observe(self, request):
                store.start_cohort(custody)
                return super().observe(request)

        self.ready()
        custody = self.custody
        with self.assertRaises(ProofRefused) as caught:
            self.collect("vibe", Starting(self.clock))
        self.assertEqual(caught.exception.reason, "not_cohort_member")
        self.assertNotIn("vibe", [e["obligation_id"] for e in self.observed()])
        self.assertEqual(self.types()[-1], "proof_cohort_started")

    def test_fresh_members_seal_success_at_one_cutoff(self):
        self.ready()
        self.clock.advance(1_000)
        self.start()
        self.members()
        after = self.settle()
        self.assertEqual((after.state, after.custody), ("succeeded", None))
        self.assertEqual([e["type"] for e in after.events[-3:]],
                         ["proof_sealed", "transitioned", "lease_released"])
        seal = dict(after.events[-3])
        self.assertEqual({k: v for k, v in seal.items() if k not in ("seq", "at", "fence")}, {
            "type": "proof_sealed", "cohort": 1, "proof_cutoff_at": seal["at"],
            "makespan_ms": 60_000, "governing_window_ms": 600_000,
            "advisory_warnings": ["vibe", "uptime"]})
        transition = after.events[-2]
        self.assertEqual((transition["to"], transition["reason"], transition["external_state"]),
                         ("succeeded", "proof_sealed", "known"))
        self.assertEqual(after.proof["cohorts"], [{"cohort": 1, "status": "sealed",
                                                   "reason": None}])
        self.assertEqual(after.proof["proof_cutoff_at"], seal["at"])
        self.assertTrue(all(self.store.inspect_lease(key)["holder"] is None for key in KEYS))

    def test_an_advisory_model_obligation_warns_but_never_blocks(self):
        self.ready()
        self.collect("vibe", self.observer({"vibe": "unsatisfied"}))
        self.start()
        self.members()
        after = self.settle()
        self.assertEqual(after.state, "succeeded")
        self.assertEqual(after.events[-3]["advisory_warnings"], ["vibe", "uptime"])

    def test_a_snapshot_collected_before_the_cohort_cannot_seal(self):
        self.ready()
        self.start()
        self.members(only=[self.act])
        self.assertEqual(self.failed(), "member_missing")
        view = self.store.load(self.transaction_id).proof
        self.assertEqual(view["cohorts"], [{"cohort": 1, "status": "failed",
                                            "reason": "member_missing"}])

    def test_a_member_older_than_its_freshness_fails_the_cohort(self):
        self.ready()
        self.start()
        self.members()
        self.wait(600_001)
        self.assertEqual(self.failed(), "cohort_expired")

    def test_a_cutoff_past_the_governing_window_fails_the_cohort(self):
        self.ready()
        self.start()
        self.wait(590_000)
        self.members(self.observer(step_ms=6_000))
        self.assertEqual(self.failed(), "cohort_expired")

    def test_an_observation_over_its_declared_latency_fails_the_cohort(self):
        self.ready()
        self.start()
        self.members(self.observer(step_ms=30_001))
        self.assertEqual(self.failed(), "collection_bound_exceeded")

    def test_an_indeterminate_member_fails_the_cohort(self):
        self.ready()
        self.start()
        self.members(self.observer({self.act: "unknown"},
                                   reasons={self.act: "identity_unobservable"}))
        self.assertEqual(self.failed(), "member_indeterminate")

    def test_authoritative_disproval_parks_proof_rejected(self):
        self.proving()
        self.collect(self.pub)
        after = self.collect(self.act, self.observer({self.act: "unsatisfied"}))
        after = self.settle()
        self.assertEqual((after.state, after.parked_from), ("attention_required", "proving"))
        self.assertEqual(after.custody, self.custody)
        rejected, transition = after.events[-2:]
        self.assertEqual((rejected["type"], rejected["obligations"]),
                         ("proof_rejected", [self.act]))
        self.assertEqual((transition["reason"], transition["external_state"]),
                         ("proof_rejected", "known"))
        self.assertNotIn("proof_cohort_started", self.types())

    def test_rejection_dominates_an_open_cohort(self):
        self.ready()
        self.start()
        self.members(self.observer({"health": "unsatisfied"}))
        self.assertEqual(self.settle().events[-1]["reason"], "proof_rejected")

    def test_a_spent_budget_parks_proof_did_not_converge(self):
        self.ready()
        for _ in range(3):
            self.start()
            self.members(only=[self.act])
            after = self.settle()
        self.assertEqual(after.state, "attention_required")
        failed, exhausted, transition = after.events[-3:]
        self.assertEqual((failed["type"], failed["cohort"], failed["reason"]),
                         ("proof_cohort_failed", 3, "member_missing"))
        self.assertEqual((exhausted["type"], exhausted["cohorts"], exhausted["exhausted_by"]),
                         ("proof_convergence_exhausted", 3, "budget"))
        self.assertEqual((transition["reason"], transition["external_state"]),
                         ("proof_did_not_converge", "known"))
        states = [e["to"] for e in after.events if e["type"] == "transitioned"]
        self.assertNotIn("recovering", states)
        self.to("proving")
        self.refused("convergence_exhausted", self.start)

    def test_the_window_runs_from_the_first_entry_into_proving(self):
        self.ready()
        self.wait(1_800_000 - 72_000 + 1)
        self.refused("convergence_exhausted", self.start)
        after = self.settle()
        self.assertEqual((after.events[-2]["cohorts"], after.events[-2]["exhausted_by"],
                          after.events[-1]["reason"]),
                         (0, "window", "proof_did_not_converge"))

    def test_settling_without_an_open_cohort_is_refused_while_budget_remains(self):
        self.ready()
        self.refused("no_open_cohort", self.settle)

    def test_reacquisition_fails_the_open_cohort_without_resetting_the_budget(self):
        self.ready()
        self.start()
        self.reacquired()
        self.assertIsNone(self.collect(self.act).events[-1]["cohort"])
        self.collect("health")
        self.collect("smoke")
        after = self.start()
        self.assertEqual([(e["type"], e["cohort"], e.get("reason")) for e in after.events[-2:]],
                         [("proof_cohort_failed", 1, "fence_changed"),
                          ("proof_cohort_started", 2, None)])

    def test_the_seal_is_refused_over_an_unresolved_action(self):
        self.ready()
        self.start()
        self.members()
        self.store.inspect_action(self.custody, name="build", parameters={"n": 1},
                                  effect=FakeEffect(self.world, inspect_outcome="in_progress"))
        error = self.assertRefusedUnchanged(TransitionRefused, self.settle)
        self.assertIn(action_id(self.transaction_id, "build", {"n": 1}), str(error))

    def test_a_parking_is_not_blocked_by_an_unresolved_action(self):
        self.proving()
        self.collect(self.act, self.observer({self.act: "unsatisfied"}))
        self.store.inspect_action(self.custody, name="build", parameters={"n": 1},
                                  effect=FakeEffect(self.world, inspect_outcome="in_progress"))
        self.assertEqual(self.settle().state, "attention_required")


class CohortValidatorTest(CohortCase):
    def sealed(self):
        self.ready()
        self.start()
        self.members()
        self.settle()
        return self.state_doc(self.transaction_id)

    def assertEditRefused(self, document):
        self.assertRuleRefuses(self.transaction_id, document, self.transaction_id)

    def test_hand_edited_cohorts_and_seals_are_state_invalid(self):
        pristine = self.sealed()
        index = {e["type"]: i for i, e in enumerate(pristine["events"])}

        def edit(change):
            document = copy.deepcopy(pristine)
            change(document["events"])
            return renumbered(document)

        cases = {
            "skipped number": lambda ev: ev[index["proof_cohort_started"]].update(cohort=2),
            "unobserved member": lambda ev: [e.update(cohort=None) for e in ev
                                             if e.get("obligation_id") == "health"],
            "wrong makespan": lambda ev: ev[index["proof_sealed"]].update(makespan_ms=1),
            "wrong cutoff": lambda ev: ev[index["proof_sealed"]].update(
                proof_cutoff_at="2000-01-01T00:00:00.000Z"),
            "second start": lambda ev: ev.insert(index["proof_cohort_started"] + 1,
                                                 copy.deepcopy(ev[index["proof_cohort_started"]])),
            "bad reason": lambda ev: ev.insert(index["proof_sealed"], {
                **copy.deepcopy(ev[index["proof_cohort_started"]]),
                "type": "proof_cohort_failed", "reason": "tired"}),
        }
        for name, change in cases.items():
            with self.subTest(edit=name):
                self.assertEditRefused(edit(change))

    def test_reserved_reasons_and_their_events_come_in_pairs(self):
        self.proving()
        self.collect(self.act, self.observer({self.act: "unsatisfied"}))
        self.settle()
        pristine = self.state_doc(self.transaction_id)
        unpaired_event = copy.deepcopy(pristine)
        unpaired_event["events"][-1]["reason"] = "operator looked"
        self.assertEditRefused(unpaired_event)
        unpaired_reason = copy.deepcopy(pristine)
        del unpaired_reason["events"][-2]
        self.assertEditRefused(renumbered(unpaired_reason))
        trailing = copy.deepcopy(pristine)
        del trailing["events"][-1]
        trailing.update(state="proving", parked_from=None)
        self.assertEditRefused(renumbered(trailing))


OBSERVED_PROOF_REASONS = {
    "state_not_proving", "unknown_obligation", "unsupported_obligation",
    "dependency_not_accepted", "already_accepted", "not_cohort_member", "proof_incomplete",
    "cohort_open", "convergence_exhausted", "no_open_cohort"}
```

  The replacement for `test_the_refusal_reasons_are_fixed` in `ProofVocabularyTest`:

```python
    def test_the_refusal_reasons_are_exactly_the_observed_ones(self):
        self.assertEqual(set(PROOF_REFUSAL_REASONS), OBSERVED_PROOF_REASONS)
```

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_proof.py 2>&1 | tail -3`.
  Expected: FAIL, `AttributeError: 'TransactionStore' object has no attribute
  'start_cohort'`.

- [ ] **Step 3: Implement** the invariants. In `validate_state`, call `pairing_violation`
  before the `match` for every event after the first, and once after the loop. Rewrite the
  docstrings of `transaction_proof`, `start_cohort` and `settle_proof` from the finished
  code; `settle_proof`'s names its five cases in order. Extend the `transaction_core`
  module docstring by one sentence on the cohort operations.

- [ ] **Step 4: Verify.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_proof.py tests/test_transaction_plan.py tests/test_transaction_core.py tests/test_transaction_custody.py tests/test_transaction_invocation.py tests/test_transaction_core_sweep.py 2>&1 | tail -3`.
  Expected: `OK`.

```bash
for word in recovering rolled_back abandoned; do
  if grep -n "\"$word\"" python/agent_tools/transaction_proof.py; then exit 1; fi
done
```

  Run: `just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.**

```bash
git add python/agent_tools/transaction_proof.py python/agent_tools/transaction_history.py \
  python/agent_tools/transaction_core.py tests/test_transaction_proof.py
git commit -m "feat(transaction-core): settle proof through one convergence cohort (#207)"
```

- [ ] **Step 6: Check the review budget** (after the commit): run the Task 3 Step 6 block
  unchanged. Here it is in full:

```bash
base=dd9f40b; fail=0
for f in python/agent_tools/transaction_*.py tests/test_transaction_proof.py \
    tests/test_transaction_plan.py tests/test_transaction_core.py; do
  n=$(git diff -U10 "$base" HEAD -- "$f" | wc -c); printf '%s %s\n' "$n" "$f"
  [ "$n" -lt 65536 ] || fail=1
done
[ "$(wc -c < python/agent_tools/transaction_core.py)" -le 55000 ] || fail=1
test "$fail" = 0
```

  Expected: exit 0.

Decisions: per D9–D11, D16, D21, D22, D27, D28.
