# Task 3: Schema 9: the custody settle step and the 8 → 9 bind

After this task every committed ledger write first makes the core agree: attempts hold their worktree under a lease, and a schema-8 ledger binds on its next write. Owner results and the launch fence come in Tasks 4 and 5. Read the root's Global Constraints first. Decisions: D1–D4, D11, D15–D19, D22, D24, D25.

**Files:**
- Modify: `python/agent_tools/attempt_store.py`, `python/agent_tools/attempt_identity.py`, `home/common/agent-skills/scripts/workflow-state.py`
- Create: `home/common/agent-skills/tests/test_attempt_custody.py`
- Modify: `justfile` (recipe `agent-workflow-tests`: add `    home/common/agent-skills/tests/test_attempt_custody.py \` after the `test_attempt_migration.py` line)
- Modify (floor fixtures, D22): `home/common/agent-skills/tests/test_workflow_state.py`, `test_attempt_migration.py`, `test_delivery_workflow.py`, `test_host_admission.py` in the same directory, and `tests/test_attempt_identity.py`

**Interfaces:**
- Consumes: Task 1's `TransactionStore.renew(custody, *, ttl_ms=None)`; Task 2's `agent_tools.attempt_custody` (`settle_plan`, `Operation`, `ProjectionMismatch`, `plan_custody_migration`, `subject`, `creation_key`, `creation_arguments`, `worktree_key`, `launch_fence`, `at_ms`, `FENCING_REASONS`); the core's `create`, `acquire`, `release`, `reap`, `advance`, `record_owner_result`, `lookup`, `load`, `inspect_lease`; `agent_tools.canonical.telemetry_digest`.
- Produces in `agent_tools.attempt_store`:
  - `CUSTODY_SCHEMA_VERSION = 9`. `BOUND_SCHEMA_VERSION` stays 8 and now means "bound to its run, custody not yet in the core".
  - `class FencingRefused(StoreRefused)`: `FencingRefused(reason, detail)` with message `fencing violation: <reason>: <detail>` and attribute `reason`; a reason outside `FENCING_REASONS` is a `ValueError`.
  - `class OwnerReport(NamedTuple)`: `issue: int`, `attempt: int`, `report: dict`.
  - `LockedRead` gains a fourth field, `bound_launches: dict[tuple[int, int], int]`: the 8 → 9 plan when `changed`, else `{}`.
  - `store_lock(store: Path)`: a context manager that runs `ensure_store` and holds the blocking exclusive lock on `<store>/attempt-runs.lock`. `mint_run` takes its lock through it.
  - `plan_custody(candidate: dict) -> dict`: `plan_custody_migration`, with `MigrationRefused` re-raised as `LedgerRefused` the way `plan_legacy_run` does.
  - `custody_of(store: Path, run: str, issue: int, attempt: int) -> Transaction | None`: lock-free `lookup` then `load`; `None` when the store directory or the index entry is missing; creates nothing; a core error is a `StoreFault`.
  - `settle_custody(store: Path, state: dict, *, now_ms: int, canonical: Callable[[str], str], bound_launches: Mapping, report: OwnerReport | None = None) -> list` and `seal_custody(store: Path, pending: list, *, now_ms: int) -> None`.
  - `pending_seals(store: Path, state: dict, *, now_ms: int) -> list`: the settle step's read phase with no report and no bound launches, lock-free, creating nothing; the seals, in `seal_custody`'s shape and in read order, of every attempt whose plan is exactly one `seal` (D24).
- Produces in `workflow-state.py`: `SCHEMA_VERSION = 9`; `commit_state(run_dir, state_path, state, *, run_id, identity, bound_launches=None, report=None)`.

**The settle step.** `settle_custody` is the only place `workflow-state` changes custody (D4).

1. Every core call of one settle reads one clock: `TransactionStore(store, clock=lambda: now_ms)` (D17).
2. Read phase, no lock: for each issue in ascending number and each of its attempts in order, find the custody transaction by `creation_key(state["transaction_id"], issue, attempt)` (none when the store directory does not exist), load it, read the lease of its subject's worktree key, and call `settle_plan` with `latest` true for the issue's last attempt, `bound=(issue, attempt) in bound_launches` (D25) and `report_digest=telemetry_digest(report.report)` only for the attempt `report` names. `ProjectionMismatch` becomes `StoreRefused("custody projection mismatch: <detail>")`.
3. When no attempt has an operation, return `[]`: no directory, lock file or store is created.
4. Write phase, under `store_lock`, in two passes. First, for every plan that starts with `create`, build the subject: `run` is `state["transaction_id"]`, `worktree` is `canonical(attempt["worktree"])`, `prior` is the `lookup` of the previous attempt's creation key (`None` for attempt 1), `bound_launch` is `bound_launches.get((issue, attempt))`. When that plan acquires and the worktree key's lease has a holder with `now_ms < expires_at`, raise `FencingRefused("custody_unavailable", …)` naming the worktree, the holder's `executor_id` and its `transaction_id`, before anything is created (D19). One holder is not a refusal: a transaction whose own plan, earlier in the read order of this settle, ends its span with a `seal`, `release` or `reap` (D24: a predecessor's interrupted seal is applied before the retry acquires). Any other live holder still refuses. Then apply the plans in the order read, each plan's operations in order.
5. Operations, each against the transaction's current snapshot: `create` → `create(creation key, subject, **creation_arguments(subject))`; `acquire` → `acquire(id, executor_id=…, subject_path=subject["worktree"], ttl_ms=…)`; `release` → `release(custody)`; `reap` → `reap(id, reason=…)`; `park` → `advance(id, "attention_required", reason=…, custody=custody)`; `unpark` → `advance(id, "created", reason=…, custody=custody)`; `renew` → `renew(custody, ttl_ms=…)`; `record_result` → `record_owner_result(id, executor_id=…, subject_path=subject["worktree"], fence=launch_fence(snapshot, executor_id), result=report.report)`; `seal` → `advance(id, "abandoned", reason=…, external_state="known", custody=custody)`. `custody` is the snapshot's held custody, or `None`.
6. A `seal` of an issue's latest attempt is not applied: it is returned, with its transaction id, for `seal_custody`. A `seal` of an earlier attempt is applied in the write phase (D18).
7. `LeaseUnavailable` becomes `FencingRefused("custody_unavailable", str(error))`; any other `TransactionError` becomes `StoreRefused(f"custody store: {error}")`. `seal_custody` applies the returned seals under `store_lock` with the same clock and error mapping and does nothing for `[]`.

`commit_state` runs, in order: `settle_admission`, `validate_state`, `settle_custody` with `now_ms=at_ms(state["updated_at"])` and `canonical=canonical_worktree_path`, `atomic_write_state`, `seal_custody`. A refusal from `settle_custody` leaves the ledger file untouched. It calls both through the module (`attempt_store.settle_custody(…)`, `attempt_store.seal_custody(…)`), which is how the tests interrupt a seal.

**Completing an interrupted seal** (D24). A seal that did not run after its ledger write is completed by three callers, none of which rewrites the ledger:

- the settle step of the run's next changed write (rule 6 above);
- `transact`, when the ledger exists and the mutation returned unchanged with no bind: `attempt_store.seal_custody(store, attempt_store.pending_seals(store, state, now_ms=at_ms(state["updated_at"])), now_ms=…)` with the same clock, so the identical repeat of the command that crashed seals;
- `migration_report` with `apply`: for each row whose dry-run verdict is `current`, it re-reads the document and, when `pending_seals` at that document's `updated_at` is not empty, calls the caller's `bind(handle)` (the locked no-op `transact` above). The row's verdict stays `current`; a `current` ledger with nothing pending is not opened, locked or written.

**The 8 → 9 read.** In `locked_read`: a schema-9 document is bound and validated as today and returns `bound_launches={}`. A schema-8 document is bound to its run (`bound_identity`), copied with `schema_version` 9, planned with `plan_custody` and returned with `changed=True`. A schema 1–7 document is upgraded as today, planned with `plan_custody` *before* `mint_run` (a refused ledger mints nothing), then stamped 9. `check_unlocked` makes the same checks and plans without writing. In `_row_verdict` a schema-8 row is checked the same way and answers `migrate` with its `transaction_id` (a refusal is `invalid_state`); schema 9 answers `current` or `migrated`; no report field or reason is added. `attempt_identity._MAX_SCHEMA_VERSION` becomes 9.

In `workflow-state.py`: `transact` unpacks the fourth field and passes it to `commit_state` (a run it creates has `{}`); `command_direct_owner`'s bind commit passes `read.bound_launches`; its other `commit_state` calls are unchanged. `validate_state`'s docstring names schema 9.

**Invariants:**
- After every committed write each issue's latest attempt and its custody transaction satisfy the spec's projection table, read with D18 and D19.
- A write the engine refuses changes no core file. A `custody_unavailable` refusal leaves the whole `.superpowers` tree unchanged.
- A lapse advances the worktree key's epoch on the next acquisition; a `declare-lane` on a live span keeps epoch and instance and adds one term.
- Lock order is the root's; `settle_custody` and `seal_custody` each take the store lock once and never while `mint_run` holds it.
- `migrate` without `--apply` writes nothing for a schema-8 ledger, and completes no seal.
- An attempt the 8 → 9 plan lists has a custody transaction after the binding write whatever that write made of it; one the write ended holds no span and no owner result (D25).
- An unchanged `transact` writes a core file only to complete a pending seal; with none pending it creates no file, directory or lock.

- [ ] **Step 1: Write the failing tests**

Create `home/common/agent-skills/tests/test_attempt_custody.py`:

```python
"""Epoch-fenced attempt custody and late-result receipts (#338), through the CLI from source.

Run: just agent-workflow-tests
"""

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from agent_tools import attempt_custody as ac
from agent_tools import attempt_store
from agent_tools.transaction_core import TransactionStore

from .test_workflow_state import LifecycleHarness

T = "2026-08-13T20:{:02d}:00Z".format
PREFIX = "workflow-state: fencing violation: "


class CustodyReads:
    """The core's public readers over a harness root, and a tree snapshot."""

    def core(self, now=None):
        clock = {} if now is None else {"clock": lambda: ac.at_ms(now)}
        return TransactionStore(Path(self.root) / ".superpowers/attempt-transactions", **clock)

    def ledger_document(self):
        return json.loads(self.ledger_path().read_text(encoding="utf-8"))

    def custody(self, issue, attempt=1):
        identity = self.core().lookup(
            ac.creation_key(self.ledger_document()["transaction_id"], issue, attempt))
        return None if identity is None else self.core().load(identity)

    def lease(self, worktree):
        return self.core().inspect_lease(ac.worktree_key(os.path.realpath(worktree)))

    def events(self, issue, kind=None):
        return [event if kind else event["type"] for event in self.custody(issue).events
                if kind in (None, event["type"])]

    def tree(self):
        """Every path under the harness's observed root, mapped to its bytes or "<dir>"."""
        root = self.observed_root()
        return {str(path.relative_to(root)): "<dir>" if path.is_dir() else path.read_bytes()
                for path in sorted(root.rglob("*"))}

    def assert_fenced(self, completed, reason, before):
        stderr = completed.stderr if isinstance(completed.stderr, str) \
            else completed.stderr.decode()
        self.assertEqual(completed.returncode, 2, stderr)
        self.assertTrue(stderr.startswith(PREFIX + reason + ": "), stderr)
        self.assertEqual(self.tree(), before)


class LifecycleCustody(CustodyReads, LifecycleHarness):
    def ledger_path(self):
        return self.state_path

    def observed_root(self):
        # The lifecycle harness keeps its request and result files beside `.superpowers`.
        return self.root / ".superpowers"

    def spawn_14(self, minutes=30):
        self.init_run()
        self.worktree = str(self.root / "wt-14")
        self.spawn(issue=14, worktree=self.worktree, budget_minutes=minutes)

    def stopped(self, notes="stopped late"):
        return {**self.merged_result(), "state": "stopped", "pr_url": None,
                "merge_sha": None, "issue_closed": False, "notes": notes}

    def contractless(self):
        """Strip every delivery from the stored ledger: the legacy `finish` is refused for
        a contracted issue. The schema number and the run binding stay."""
        stored = self.read_state()
        for issue_state in stored["issues"].values():
            issue_state["delivery"] = self.empty_delivery()
            issue_state["delivery_remainders"] = []
        self.write_state(stored)

    def finish_raw(self, attempt, result, *, issue=14, now, ok=True):
        """The legacy `finish` as an owner sends it. Unlike the harness's `finish`, it
        neither prepares the stored ledger nor restores it, so a test reads the bytes the
        command left (D26)."""
        path = self.root / f"result-{issue}-{attempt}.json"
        path.write_text(json.dumps(result), encoding="utf-8")
        completed = self.run_cli(
            "finish", "--repo-root", self.root, "--run-id", self.run_id, "--issue", issue,
            "--attempt", attempt, "--result-file", path, "--now", now, ok=ok)
        return json.loads(completed.stdout) if ok else completed


class CustodyLeaseTest(LifecycleCustody, unittest.TestCase):
    def test_ac1_a_spawn_holds_epoch_one_until_the_deadline(self):
        self.spawn_14()
        custody = self.custody(14)
        run = self.read_state()["transaction_id"]
        self.assertEqual(dict(custody.subject), {
            "schema": "attempt-custody/v1", "run": run, "issue": 14, "attempt": 1,
            "worktree": os.path.realpath(self.worktree), "prior": None, "bound_launch": None})
        self.assertEqual((custody.state, custody.custody.executor_id,
                          custody.custody.subject_path),
                         ("created", "14:1:1", os.path.realpath(self.worktree)))
        lease = self.lease(self.worktree)
        self.assertEqual((lease["epoch"], lease["holder"]["term"],
                          lease["holder"]["expires_at"]), (1, 1, ac.at_ms(T(30))))
        self.assertEqual(self.read_state()["schema_version"], 9)

    def test_ac1_declare_lane_renews_in_place_and_reacquires_after_the_window(self):
        self.spawn_14()
        instance = self.lease(self.worktree)["holder"]["instance"]
        self.declare_lane(action_id="14:1:1", now=T(5), lane="light", budget_minutes=10,
                          reason="triage")
        holder = self.lease(self.worktree)["holder"]
        self.assertEqual((self.lease(self.worktree)["epoch"], holder["instance"],
                          holder["term"], holder["expires_at"]),
                         (1, instance, 2, ac.at_ms(T(10))))
        self.assertEqual(self.events(14), ["created", "lease_acquired"])
        self.declare_lane(action_id="14:1:1", now=T(15), lane="full", budget_minutes=60,
                          reason="light_deadline")
        lease = self.lease(self.worktree)
        self.assertEqual((lease["epoch"], lease["holder"]["term"],
                          lease["holder"]["expires_at"]), (2, 1, ac.at_ms("2026-08-13T21:00:00Z")))
        self.assertNotEqual(lease["holder"]["instance"], instance)
        self.assertEqual(self.events(14)[2:], ["lease_lapse_detected", "lease_reacquired"])
        self.assertEqual(self.custody(14).custody.executor_id, "14:1:1")

    def test_ac1_a_reap_then_a_resume_advance_the_epoch_and_void_snapshot_evidence(self):
        self.spawn_14()
        self.core(T(1)).record_evidence(self.custody(14).custody, evidence_id="probe",
                                        form="snapshot", reference="ref")
        self.assertTrue(self.custody(14).evidence[0]["admissible"])
        self.expire(issue=14, worktree=self.worktree, now=T(31))
        self.assertEqual(self.events(14)[3:], [
            "lease_lapse_detected", "stop_synthesized", "transitioned"])
        parked = self.custody(14)
        self.assertEqual((parked.state, parked.custody, parked.events[4]["reason"]),
                         ("attention_required", None, "expiry"))
        self.resume(issue=14, worktree=self.worktree, now=T(32))
        resumed = self.custody(14)
        reacquired = resumed.events[6]
        self.assertEqual((reacquired["type"], reacquired["reason"], reacquired["executor_id"]),
                         ("lease_reacquired", "expired", "14:1:2"))
        self.assertEqual((resumed.state, self.lease(self.worktree)["epoch"]), ("created", 2))
        evidence = resumed.evidence[0]
        self.assertEqual((evidence["admissible"], evidence["void_reason"]),
                         (False, "fence_changed"))

    def test_a_handoff_and_a_suspension_give_custody_up(self):
        self.spawn_14()
        self.progress(turn_count=118, context_tokens=20000, now=T(1),
                      handoff_path=self.write_handoff(14))
        handed = self.custody(14)
        self.assertEqual((handed.state, handed.custody, handed.events[-1]["type"]),
                         ("created", None, "lease_released"))
        self.resume(issue=14, worktree=self.worktree, now=T(2))
        self.assertEqual(self.lease(self.worktree)["epoch"], 2)
        self.suspend(issue=14, attempt=1, blocked_on="human_gate", now=T(3))
        parked = self.custody(14)
        self.assertEqual((parked.state, parked.custody), ("attention_required", None))
        self.assertEqual(ac.blocked_on_of(parked.events[-2]["reason"]), "human_gate")
        self.assertIsNone(self.lease(self.worktree)["holder"])

    def test_a_live_worktree_lease_refuses_another_run(self):
        self.spawn_14()
        first = self.run_id
        self.init_run(creation_key="second-run")
        before = self.tree()
        refused = self.control_raw(ok=False, now=T(1), issues=[15], max_parallel=100,
                                   tracker=[self.tracker_fact(15)],
                                   worktrees=[self.worktree_fact(15, candidate={
                                       "path": os.path.abspath(self.worktree),
                                       "state": "absent"})])
        self.assert_fenced(refused, "custody_unavailable", before)
        self.run_id = first
        self.assertEqual(self.custody(14).custody.executor_id, "14:1:1")


class CustodyMigrationTest(LifecycleCustody, unittest.TestCase):
    def migrate(self, *flags):
        return json.loads(self.run_cli("migrate", "--repo-root", self.root, *flags).stdout)

    def row(self, report):
        return next(row for row in report["ledgers"] if row["ledger"] == self.run_id)

    def test_a_schema_8_ledger_is_a_migrate_row_and_binds_on_its_next_write(self):
        self.spawn_14()
        self.install_legacy(self.read_state(), "orchestrate-14", version=8)
        before = self.tree()
        row = self.row(self.migrate())
        self.assertEqual((row["verdict"], row["reason"], row["schema_version"]),
                         ("migrate", None, 8))
        self.assertEqual(self.tree(), before)
        self.register_worker(action_id="14:1:1", now=T(1))
        self.assertEqual(self.read_state()["schema_version"], 9)
        bound = self.custody(14)
        self.assertEqual((bound.subject["bound_launch"], bound.custody.executor_id),
                         (1, "14:1:1"))
        self.assertEqual(self.lease(self.worktree)["holder"]["expires_at"], ac.at_ms(T(30)))
        self.assertEqual(self.row(self.migrate())["verdict"], "current")

    def test_migrate_apply_parks_a_suspension_and_replays_no_history(self):
        self.spawn_14()
        self.suspend(issue=14, attempt=1, blocked_on="transport", now=T(1))
        self.resume(issue=14, worktree=self.worktree, now=T(2))
        self.suspend(issue=14, attempt=1, blocked_on="human_gate", now=T(3))
        self.install_legacy(self.read_state(), "orchestrate-14", version=8)
        self.assertEqual(self.row(self.migrate("--apply"))["verdict"], "migrated")
        bound = self.custody(14)
        self.assertEqual(self.events(14), ["created", "transitioned"])
        self.assertEqual((bound.state, bound.custody, bound.subject["bound_launch"],
                          bound.events[1]["reason"]),
                         ("attention_required", None, 2, "suspended:human_gate"))

    def test_a_finish_that_is_the_binding_write_still_binds_and_seals(self):
        self.spawn_14()
        self.install_legacy(self.read_state(), "orchestrate-14", version=8)
        self.contractless()
        self.assertEqual(self.finish_raw(1, self.stopped(), now=T(5))["state"], "stopped")
        self.assertEqual(self.read_state()["schema_version"], 9)
        bound = self.custody(14)
        self.assertEqual((bound.state, bound.custody, bound.subject["bound_launch"]),
                         ("abandoned", None, 1))
        self.assertNotIn("lease_acquired", self.events(14))
        self.assertEqual(self.events(14, "transitioned")[-1]["reason"], "owner:stopped")
        receipt = self.core().read_receipt(bound.terminal["receipt_digest"])
        self.assertEqual((receipt["outcome"], receipt["stops"], receipt["owner_results"]),
                         ("abandoned", [], []))


class CustodyRepairTest(LifecycleCustody, unittest.TestCase):
    def failed(self):
        return {**self.stopped("gave up"), "state": "failed"}

    def interrupted_seal(self):
        """An owner's failed verdict reaches the ledger and its deferred seal never runs."""
        self.spawn_14()
        self.contractless()
        with mock.patch.object(attempt_store, "seal_custody", side_effect=OSError("crash")):
            crashed = self.finish_raw(1, self.failed(), now=T(5), ok=False)
        self.assertNotEqual(crashed.returncode, 0)
        attempt = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual((attempt["state"], attempt["result_source"]), ("failed", "owner"))
        unsealed = self.custody(14)
        self.assertEqual((unsealed.state, unsealed.custody.executor_id),
                         ("created", "14:1:1"))

    def assert_sealed(self):
        sealed = self.custody(14)
        self.assertEqual((sealed.state, sealed.custody), ("abandoned", None))
        receipt = self.core().read_receipt(sealed.terminal["receipt_digest"])
        self.assertEqual(receipt["outcome"], "abandoned")

    def test_the_identical_finish_completes_an_interrupted_seal(self):
        self.interrupted_seal()
        ledger = self.state_path.read_bytes()
        self.assertEqual(self.finish_raw(1, self.failed(), now=T(6))["state"], "failed")
        self.assertEqual(self.state_path.read_bytes(), ledger)
        self.assert_sealed()
        before = self.tree()
        self.finish_raw(1, self.failed(), now=T(7))
        self.assertEqual(self.tree(), before)

    def test_migrate_apply_completes_an_interrupted_seal(self):
        self.interrupted_seal()
        ledger = self.state_path.read_bytes()
        self.run_cli("migrate", "--repo-root", self.root)
        self.assertEqual(self.custody(14).state, "created")
        report = json.loads(self.run_cli("migrate", "--repo-root", self.root, "--apply").stdout)
        row = next(row for row in report["ledgers"] if row["ledger"] == self.run_id)
        self.assertEqual(row["verdict"], "current")
        self.assertEqual(self.state_path.read_bytes(), ledger)
        self.assert_sealed()
        before = self.tree()
        self.run_cli("migrate", "--repo-root", self.root, "--apply")
        self.assertEqual(self.tree(), before)

    def test_a_retry_in_the_same_worktree_completes_the_predecessors_seal_first(self):
        self.interrupted_seal()
        self.retry(issue=14, worktree=self.worktree, now=T(6))
        first, second = self.custody(14, 1), self.custody(14, 2)
        self.assertEqual((first.state, first.custody), ("abandoned", None))
        self.assertEqual((second.subject["prior"], second.custody.executor_id),
                         (first.transaction_id, "14:2:1"))
        self.assertEqual(self.lease(self.worktree)["epoch"], 2)


if __name__ == "__main__":
    unittest.main()
```

`install_legacy(…, version=8)` is the fixture change of Step 3; write it first so these tests can run.

- [ ] **Step 2: Run them and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_custody.py`
Expected: all 11 fail or error: no custody transaction exists (`AttributeError: 'NoneType' object has no attribute …` from `self.custody(14)`), `attempt_store` has no `seal_custody` to patch, and the ledger is schema 8.

- [ ] **Step 3: Change the floor's fixtures (D22)**

In `LifecycleHarness` (`test_workflow_state.py`), replace `install_legacy` and add its two helpers:

```python
    def install_legacy(self, state, handle, version=7):
        """A retained legacy ledger: `state` as schema `version` under `handle`, beside its
        empty `state.lock` and the workflows `.gitignore` a retained ledger has (D21)."""
        run_dir = self.workflows_dir / handle
        run_dir.mkdir(parents=True, exist_ok=True)
        (self.workflows_dir / ".gitignore").write_text("*\n", encoding="utf-8")
        (run_dir / "state.lock").write_bytes(b"")
        self.run_id = handle
        self.release_custody()
        self.write_state(self._as_legacy(state, min(version, 7), handle=handle))
        if version == 8:
            self.bind_as_schema_8()

    def release_custody(self):
        """Give up every live core custody in this root: a legacy ledger about to be
        installed never held a lease, and lease records are never deleted (#338 D11)."""
        for path in sorted((self.store_root / "leases").glob("*.json")):
            holder = json.loads(path.read_text(encoding="utf-8"))["holder"]
            if holder is None:
                continue
            store = TransactionStore(self.store_root, clock=lambda: holder["acquired_at"])
            custody = store.load(holder["transaction_id"]).custody
            if custody is not None:
                store.release(custody)

    def bind_as_schema_8(self):
        """The stored schema-7 ledger as package 1 bound it: its run minted, schema 8."""
        document = json.loads(self.state_path.read_text(encoding="utf-8"))
        plan = attempt_store.plan_legacy_run(document)
        document["transaction_id"] = attempt_store.mint_run(self.store_root, plan)
        document["schema_version"] = 8
        self.write_state(document)
```

Then the schema number, wherever a pre-existing test states it: `assert_bound` and `_legacy_finish_input` in the harness, every `"schema_version": 8` literal, every assertion that a current ledger is version 8 (tuple forms such as `(8, None, 1, 0)`, `(8, self.base)`, `(8, first["run_id"])` included), `schema_version=8` keyword arguments, and `tests/test_attempt_identity.py::test_schema_refusal` (1, 7, 8 and 9 are known; 10 is not). The unknown-schema fixture in `test_attempt_migration.py` (`edit_ledger("orchestrate-90", schema_version=9)`) becomes 10. Find leftovers with `grep -nE 'schema_version[^0-9]*8\b|\(8, ' <the five files>`.

Two `test_host_admission.py` cases run a second run over the first run's worktrees at overlapping ledger times (`test_four_slots_admit_one_owner_and_seven_admit_both`, and each subtest of `test_a_reap_suspends_and_a_reap_resumed_in_one_sweep_supersedes`). Give each run its own worktrees: let `AdmissionSweeps.sweep` build its paths under `getattr(self, "worktree_base", self.root)` and set `self.worktree_base` to a per-run directory in those two tests.

- [ ] **Step 4: Implement**

Implement the interfaces, the settle step, the seal completion and the 8 → 9 read above. Docstrings and the `attempt_store` module docstring are written from the implemented code.

- [ ] **Step 5: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_custody.py tests/test_attempt_identity.py tests/test_attempt_custody.py`
Expected: `OK`.

Run, one command each, timeout 1800 s: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/<file>` for `test_workflow_state.py`, `test_attempt_migration.py`, `test_host_admission.py`, `test_admission_replay.py`, `test_delivery_workflow.py`, `test_delivered_control.py`.
Expected: `OK` for each. A remaining failure that is not a schema number, a legacy fixture or a shared worktree is a defect or a spec conflict (Global Constraints); `fixtures/admission-replay/baseline.json` is not edited.

Run: `git diff --stat 5bd914e199f3e57217780596beefe69838f4efd4..HEAD -- home/common/agent-skills/scripts/workflow_delivery.py home/common/agent-skills/scripts/workflow_delivery_build.py home/common/agent-skills/scripts/workflow_delivery_wire.py home/common/agent-skills/scripts/delivery_model home/common/agent-skills/tests/fixtures`
Expected: empty output.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/attempt_store.py python/agent_tools/attempt_identity.py home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests tests/test_attempt_identity.py justfile
launch-commit … -- -m "feat(workflow-state): hold attempt custody in the core at schema 9 (#338)"
```
