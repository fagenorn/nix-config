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


    def test_a_resume_into_a_taken_worktree_refuses_the_whole_sweep_before_any_write(self):
        self.init_run()
        taken = str(self.root / "wt-20")
        self.spawn(issue=20, worktree=taken)
        self.suspend(issue=20, attempt=1, blocked_on="transport", now=T(1))
        first = self.run_id
        self.init_run(creation_key="second-run")
        self.spawn(issue=30, worktree=taken, now=T(2))
        self.run_id = first
        before = self.tree()
        refused = self.control_raw(
            ok=False, now=T(3), issues=[14, 20], max_parallel=100,
            tracker=[self.tracker_fact(14), self.tracker_fact(20)],
            worktrees=[
                self.worktree_fact(14, candidate={
                    "path": os.path.abspath(self.root / "wt-14"), "state": "absent"}),
                self.worktree_fact(20, recorded={
                    "path": os.path.abspath(taken), "state": "matching_issue_branch"})])
        self.assert_fenced(refused, "custody_unavailable", before)
        self.assertIsNone(self.custody(14))


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

    def test_migrate_apply_reports_a_refused_bind_as_a_row_and_binds_the_rest(self):
        self.spawn_14()
        stored = self.read_state()
        self.install_legacy(stored, "orchestrate-14", version=8)
        self.install_legacy(stored, "orchestrate-14-r2", version=8)
        completed = self.run_cli("migrate", "--repo-root", self.root, "--apply")
        rows = {row["ledger"]: row for row in json.loads(completed.stdout)["ledgers"]}
        self.assertEqual(
            [(rows[name]["verdict"], rows[name]["reason"])
             for name in ("orchestrate-14", "orchestrate-14-r2")],
            [("migrated", None), ("refused", "invalid_state")])
        self.run_id = "orchestrate-14-r2"
        self.assertEqual(self.read_state()["schema_version"], 8)

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
