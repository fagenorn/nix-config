# Task 6: Delivery proof, the `succeeded` seals and receipt supplements

A complete delivery seals its transaction `succeeded` on the contract's required postconditions; every unsealed custody transaction of that issue then seals `succeeded` citing the delivery receipt; and what arrives for a sealed transaction becomes a post-terminal observation of its receipt. Seals run after the ledger is published. Decisions: D5–D7, D18, D19, D22, D24, D27.

**Files:**
- Modify: `python/agent_tools/attempt_custody.py`, `python/agent_tools/attempt_store.py`, `python/agent_tools/attempt_delivery_store.py`
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (`commit_state`, the unchanged-repeat path of `transact`, `command_migrate`)
- Modify: `tests/test_attempt_custody.py`
- Create: `home/common/agent-skills/tests/test_delivery_sealing.py`
- Modify: `justfile` (the new file after `test_control_decisions.py` in `agent-workflow-tests`)
- Modify (floor, D22 only): `home/common/agent-skills/tests/test_attempt_custody.py`

**Interfaces:**
- Consumes: Task 1's planner and constants; Task 4's `reading`, `writing`, `delivery_of`, `settle_delivery`; the core's `collect_obligation`, `start_cohort`, `settle_proof`, `record_post_terminal`, `post_terminal_observations`.
- Produces:
  - `attempt_custody`: `RECONCILED_MERGE = "reconciled_merge"`; `OPERATIONS` gains `"supplement"`; `settle_plan` returns `(Operation("supplement", reason="reconciled_merge", reference=telemetry_digest(result)),)` for an `abandoned` transaction whose record is `merged` with `result_source` `superseded`, checked before the `delivered` rows; and `()` for a `delivered` record parked `proof_did_not_converge` (D27)
  - `attempt_store.PendingSeal(transaction_id, reason, reap=None, issue=None, executor=None)`: a `succeeded` seal carries `issue` and `executor`, and `settle_custody` returns one per `seal_succeeded` operation
  - `attempt_store.seal_custody(store, pending, *, now_ms, receipts: Mapping[int, str] = MappingProxyType({})) -> None`
  - `attempt_store.pending_seals(store, state, *, now_ms, delivered: frozenset[int] = frozenset()) -> list[PendingSeal]`
  - `attempt_delivery_store.seal_delivery(store, state, *, now_ms, delivered: frozenset[int]) -> dict[int, str]` (issue → delivery receipt digest) and `delivery_pending(store, state, delivered) -> bool` (lock-free)
  - `attempt_store.migration_report(..., pending: Callable[[str], bool])`: `pending(handle)` replaces `_seals_pending`, which is deleted

**Invariants:**
- **Order in `commit_state`:** `settle_custody` → `settle_delivery` → `atomic_write_state` → `receipts = seal_delivery(...)` → `seal_custody(..., receipts=receipts)`. Each takes the store lock for itself, and none when it has nothing to do.
- **Delivery seal.** For each delivered issue whose delivery transaction of this run is not terminal: take the delivery span (reuse or acquire as in Task 4), advance through the `FORWARD_STATES` it has not reached (reason `delivered`), collect each obligation whose latest observation is not an admissible `satisfied` with an observer that returns `{"outcome": "satisfied", "reason": "observed", "reference": <observation id>}` from `collections(delivery)`, then `start_cohort`, then `settle_proof`. The order is collect, cohort, settle: the core refuses a cohort before every required obligation is satisfied (D19). A `ProofRefused` from `start_cohort` whose `reason` is `cohort_open` means a cut seal left one open under this span, and is passed over; `convergence_exhausted` is settled per D27 (`settle_proof` parks it); any other refusal propagates. `seal_delivery` returns the receipt digest of every delivered issue whose transaction is `succeeded` when it returns.
- **Custody seal.** A pending seal with an `issue` is applied only when `receipts` has that issue; otherwise it stays pending. A terminal transaction is skipped. One parked `proof_did_not_converge` is skipped too (D27); any other `attention_required` one is first advanced to its `parked_from` (reason `delivered`, no custody). The seal span (`executor`, the subject's worktree, `HELPER_TTL_MS`) is reused when open and unlapsed, else acquired; a `LeaseUnavailable` leaves this seal pending without failing the others. One `event` evidence entry `delivery-receipt` with the receipt digest is recorded unless present, the transaction is advanced through the `FORWARD_STATES` it has not reached, and `start_cohort` (the same `cohort_open` and `convergence_exhausted` rules) and `settle_proof` seal it. Package 2's `abandoned` seals are applied as before.
- A seal cut after any of its core operations is completed by a later call from the state it reached, inside the core's convergence limits (D27); `pending_seals` and `delivery_pending` leave out what D27 calls not pending. `pending_seals` also returns the `succeeded` seal of a record whose whole plan is one `seal_succeeded`. `transact`'s unchanged-repeat path computes `delivered` and calls `pending_seals`, `seal_delivery` and `seal_custody`; it writes nothing when nothing is pending.
- `command_migrate`'s `pending` reads the stored document as `_seals_pending` did and answers `pending_seals(..., delivered=…)` non-empty or `delivery_pending(...)`. A schema-9 ledger that is already delivery-complete seals at its bind.
- **Supplements** are `record_post_terminal(receipt_digest, observation={"outcome", "reason", "reference"}, contradicts_ground=False)`; one with the same reason and reference is never recorded twice:
  - a journal entry a *terminal* delivery transaction lacks (`settle_delivery`, by `journaled(transaction, post_terminal_observations(...))`): outcome `satisfied`, reason the entry's evidence id, reference its text;
  - an owner report `retain_result` is handed for a terminal custody transaction: outcome `unknown`, reason `owner_result:<launch id>`, reference `telemetry_digest(report)`; it then returns True;
  - the planner's `supplement` operation: outcome `satisfied`, with the operation's reason and reference. The read phase drops one already recorded, so a settled ledger plans nothing.
- No receipt file changes after it is written, and no late object is refused for being late. A `merged` attempt of an issue with no contract stays unsealed.

- [ ] **Step 1: Write the failing tests**

Create `home/common/agent-skills/tests/test_delivery_sealing.py`:

```python
"""Delivery proof, the `succeeded` seals and receipt supplements (#339 D5, D6), through the
CLI from source.

Run: just agent-workflow-tests
"""

import unittest

from agent_tools import attempt_custody as ac
from agent_tools import attempt_delivery as ad
from agent_tools.canonical import telemetry_digest

from .test_attempt_custody import LifecycleCustody, T
from .test_control_cutover import MATCHING, MERGED, Cutover
from .test_delivered_control import DELIVERED, at

ABSENT = {DELIVERED: "absent"}


class SealingTest(Cutover, unittest.TestCase):
    def receipt(self, transaction):
        return self.core().read_receipt(transaction.terminal["receipt_digest"])

    def supplements(self, transaction):
        return [(s["outcome"], s["reason"], s["reference"]) for s in
                self.core().post_terminal_observations(transaction.terminal["receipt_digest"])]

    def receipts(self):
        return {path: content for path, content in self.tree().items()
                if "/receipts/" in path and "/observations" not in path}

    def assert_sealed(self):
        delivery = self.delivery(DELIVERED)
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.state, "succeeded")
        digest, post = delivery.terminal["receipt_digest"], self.ledger_document()[
            "issues"][str(DELIVERED)]["delivery"]["postconditions"]
        self.assertEqual((self.receipt(delivery)["outcome"],
                          [e["obligation_id"] for e in self.receipt(delivery)["evaluations"]]),
                         ("succeeded", list(ad.POSTCONDITIONS)))
        self.assertEqual(
            {e["obligation_id"]: (e["outcome"], e["reason"], e["reference"])
             for e in delivery.events if e["type"] == "obligation_observed"},
            {name: ("satisfied", "observed", post[name]["observation_id"])
             for name in ad.POSTCONDITIONS})
        for held in (self.custody(DELIVERED), self.remainder(DELIVERED)):
            self.assertEqual((held.state, held.custody, self.receipt(held)["outcome"]),
                             ("succeeded", None, "succeeded"))
            self.assertIn(("delivery-receipt", digest),
                          [(e["evidence_id"], e["reference"]) for e in held.evidence])
        self.assertIsNone(self.lease(self.worktrees[DELIVERED])["holder"])
        return digest

    def test_ac4_a_delivery_through_a_remainder_seals_its_proof_then_its_custody(self):
        self.delivered()
        digest = self.assert_sealed()
        (stop,) = self.receipt(self.custody(DELIVERED))["stops"]
        self.assertEqual((stop["reason"], stop["executor_id"]), ("expiry", f"{DELIVERED}:1:1"))
        self.assertEqual(self.records(DELIVERED)[1][0]["state"], "active")
        sealed = self.receipts()
        self.assertEqual(len(sealed), 3)
        late = self.observed(self.built[DELIVERED]["contract"], at(40), "worktree_absent")
        self.sweep(40, recorded=ABSENT, closed={DELIVERED}, contracts=True,
                   observations={DELIVERED: [late]})
        self.assertEqual(
            [(s["outcome"], s["reason"], s["reference"], s["contradicts_ground"])
             for s in self.core().post_terminal_observations(digest)],
            [("satisfied", f"delivery_observations:{late['id']}",
              self.model.canonical_bytes(late).decode(), False)])
        self.sweep(41, recorded=ABSENT, closed={DELIVERED})
        self.assertEqual((len(self.core().post_terminal_observations(digest)), self.receipts()),
                         (1, sealed))

    def cut(self, *reached, cohort=False):
        """A delivered schema-9 ledger whose attempt's custody seal was cut at the last of
        `reached` (after opening its cohort, with `cohort`)."""
        self.generation = "base"
        self.delivered()
        self.generation = "head"
        attempt = self.custody(DELIVERED)
        core = self.core(at(33))
        core.advance(attempt.transaction_id, "created", reason="delivered")
        held = core.acquire(attempt.transaction_id, executor_id=f"{DELIVERED}:1:seal",
                            subject_path=attempt.subject["worktree"],
                            ttl_ms=ad.HELPER_TTL_MS).custody
        for target in reached:
            core.advance(attempt.transaction_id, target, reason="delivered", custody=held)
        if cohort:
            core.start_cohort(held)

    def test_a_schema_9_ledger_that_is_already_delivered_seals_at_its_bind(self):
        self.cut("awaiting_verification", "ready")
        self.cli("migrate", "--repo-root", self.root, "--apply")
        self.assertEqual(self.ledger_document()["schema_version"], 10)
        self.assert_sealed()
        self.assertEqual(self.remainder(DELIVERED).subject["bound_launch"], 1)
        bound = self.tree()
        self.cli("migrate", "--repo-root", self.root, "--apply")
        self.assertEqual(self.tree(), bound)

    def test_a_seal_cut_after_its_cohort_resumes(self):
        self.cut(*ac.FORWARD_STATES, cohort=True)
        self.cli("migrate", "--repo-root", self.root, "--apply")
        self.assert_sealed()

    def test_a_seal_past_the_window_parks(self):
        self.cut(*ac.FORWARD_STATES)
        late = self.observed(self.built[DELIVERED]["contract"], at(70), "worktree_absent")
        self.sweep(70, recorded=ABSENT, closed={DELIVERED}, contracts=True,
                   observations={DELIVERED: [late]})
        attempt = self.custody(DELIVERED)
        self.assertEqual(
            (attempt.state, attempt.custody, self.reason(attempt),
             self.delivery(DELIVERED).state, self.remainder(DELIVERED).state),
            ("attention_required", None, "proof_did_not_converge", "succeeded", "succeeded"))
        parked = self.tree()
        self.cli("migrate", "--repo-root", self.root, "--apply")
        self.assertEqual(self.tree(), parked)

    def test_a_merge_reconciled_after_an_abandoned_seal_is_a_supplement(self):
        self.spawn(DELIVERED)
        self.failing(f"{DELIVERED}:1:1", 3)
        sealed = self.custody(DELIVERED)
        self.assertEqual(sealed.state, "abandoned")
        receipt = self.receipts()
        self.sweep(4, recorded=MATCHING, forge={DELIVERED: MERGED})
        attempt = self.records(DELIVERED)[0][0]
        self.assertEqual((attempt["state"], attempt["result_source"]), ("merged", "superseded"))
        expected = [("satisfied", "reconciled_merge", telemetry_digest(attempt["result"]))]
        self.assertEqual(self.supplements(sealed), expected)
        self.sweep(5, recorded=MATCHING)
        self.assertEqual(self.supplements(sealed), expected)
        self.assertEqual({path: content for path, content in self.receipts().items()
                          if path in receipt}, receipt)


class LateResultTest(LifecycleCustody, unittest.TestCase):
    def test_an_owner_result_after_the_seal_is_a_supplement(self):
        self.spawn_14()
        self.contractless()
        self.finish_raw(1, self.stopped(), now=T(5), action_id="14:1:1")
        sealed = self.custody(14)
        self.assertEqual(sealed.state, "abandoned")
        late, ledger = self.stopped("a different report"), self.state_path.read_bytes()
        for minute in (6, 7):  # the same report twice is one supplement
            refused = self.finish_raw(1, late, now=T(minute), action_id="14:1:1", ok=False)
            self.assertIn("conflicting terminal result", refused.stderr)
        self.assertEqual(
            [(s["outcome"], s["reason"], s["reference"]) for s in
             self.core().post_terminal_observations(sealed.terminal["receipt_digest"])],
            [("unknown", "owner_result:14:1:1", telemetry_digest(late))])
        self.assertEqual(self.state_path.read_bytes(), ledger)
```

In `tests/test_attempt_custody.py`, `SettlePlanTest.test_a_sealed_transaction_is_final` replaces `self.assertEqual(self.plan(merged), ())` (package 2 planned nothing over a reconciled merge; D6 replaces that) with:

```python
        self.assertEqual(self.plan(merged), (Op(
            "supplement", reason="reconciled_merge",
            reference=telemetry_digest(merged["result"])),))
        self.assertEqual(self.plan(merged, delivered=True), self.plan(merged))
        self.assertEqual(self.plan(attempt("failed", source="owner", result=result("failed"))),
                         ())
```

- [ ] **Step 2: Run them and watch them fail**

Run: `PYTEST T/test_delivery_sealing.py tests/test_attempt_custody.py`
Expected: FAIL. The delivered `SealingTest` cases fail on a state that is not `succeeded` or not parked; the two supplement cases with `[] != [...]`; `test_a_sealed_transaction_is_final` with `() != (Operation(kind='supplement', …),)`.

- [ ] **Step 3: Implement the seals**

The delivery seal, the custody seal, their pending readers and the three engine sites. The observer passed to `collect_obligation` is a small object whose `observe(request)` reads nothing but what `collections` returned.

- [ ] **Step 4: Implement the supplements**

The planner row; the read-phase filter and `_apply` branch in `attempt_store`; the terminal branches of `retain_result` and `settle_delivery`.

- [ ] **Step 5: Apply the declared floor change**

A package-2 CLI test that asserted an unsealed or silent core over a delivered issue or over a sealed transaction now reads the `succeeded` receipt or the supplement (D22).

- [ ] **Step 6: Verify**

Run: `PYTEST T/test_delivery_sealing.py T/test_control_cutover.py T/test_control_decisions.py T/test_attempt_custody.py T/test_attempt_migration.py T/test_delivered_control.py T/test_admission_replay.py tests/test_attempt_custody.py`
Expected: `OK`; `test_delivery_sealing.py` runs 6 tests.

Run: `PYTEST T/test_workflow_state.py T/test_delivery_workflow.py`
Expected: `OK`.

Run the root's review-package budget command for `python/agent_tools/attempt_store.py`, `python/agent_tools/attempt_delivery_store.py` and `home/common/agent-skills/scripts/workflow-state.py`.
Expected: each at most 60000.

- [ ] **Step 7: Commit**

```bash
git add python home tests justfile
launch-commit … -- -m "feat(attempt-delivery): seal a complete delivery and its custody, and keep late objects as supplements (#339)"
```
