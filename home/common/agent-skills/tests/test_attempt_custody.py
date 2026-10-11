"""Epoch-fenced attempt custody and late-result receipts (#338), through the CLI from source.

Run: just agent-workflow-tests
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools import attempt_custody as ac
from agent_tools import attempt_store
from agent_tools.transaction_core import TransactionStore

from .test_delivered_control import DELIVERED, DISPATCH, LIVE, DeliveredControlHarness, at
from .test_workflow_state import LifecycleHarness

T = "2026-08-13T20:{:02d}:00Z".format
PREFIX = "workflow-state: fencing violation: "
REPO = Path(__file__).resolve().parents[4]
BASE_COMMIT = "5bd914e199f3e57217780596beefe69838f4efd4"


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

    def legacy_owner_resumed_to_launch_2(self):
        """A schema-8 ledger with a live owner on 14:1:1, bound by control's write, then
        expired, reaped and resumed to 14:1:2."""
        self.spawn_14()
        self.install_legacy(self.read_state(), "orchestrate-14", version=8)
        self.assertEqual(self.read_state()["schema_version"], 8)
        recorded = [self.worktree_fact(14, recorded={
            "path": os.path.abspath(self.worktree), "state": "matching_issue_branch"})]
        self.control(now="2026-08-13T20:00:30Z", issues=[14], max_parallel=100,
                     tracker=[self.tracker_fact(14)], worktrees=recorded)
        self.assertEqual(self.custody(14).subject["bound_launch"], 1)
        self.expire(issue=14, worktree=self.worktree, now=T(31))
        self.resume(issue=14, worktree=self.worktree, now=T(32))
        self.assertEqual(self.custody(14).custody.executor_id, "14:1:2")

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

    def finish_raw(self, attempt, result, *, issue=14, now, action_id=None, ok=True):
        """The legacy `finish` as an owner sends it. Unlike the harness's `finish`, it
        neither prepares the stored ledger nor restores it, so a test reads the bytes the
        command left (D26)."""
        path = self.root / f"result-{issue}-{attempt}.json"
        path.write_text(json.dumps(result), encoding="utf-8")
        completed = self.run_cli(
            "finish", "--repo-root", self.root, "--run-id", self.run_id, "--issue", issue,
            "--attempt", attempt, "--result-file", path, "--now", now,
            *self.launch_arguments(issue, attempt, action_id), ok=ok)
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
        self.assertEqual(self.read_state()["schema_version"], 10)

    def test_ac1_declare_lane_renews_in_place_and_reacquires_after_the_window(self):
        self.spawn_14()
        instance = self.lease(self.worktree)["holder"]["instance"]
        self.declare_lane(action_id="14:1:1", now=T(5), lane="light", budget_minutes=10,
                          reason="triage")
        holder = self.lease(self.worktree)["holder"]
        self.assertEqual((self.lease(self.worktree)["epoch"], holder["instance"],
                          holder["term"], holder["expires_at"]),
                         (1, instance, 2, ac.at_ms(T(10))))
        self.assertEqual(self.events(14), ["created", "lease_acquired", "evidence_recorded"])
        self.declare_lane(action_id="14:1:1", now=T(15), lane="full", budget_minutes=60,
                          reason="light_deadline")
        lease = self.lease(self.worktree)
        self.assertEqual((lease["epoch"], lease["holder"]["term"],
                          lease["holder"]["expires_at"]), (2, 1, ac.at_ms("2026-08-13T21:00:00Z")))
        self.assertNotEqual(lease["holder"]["instance"], instance)
        self.assertEqual(self.events(14)[3:], ["lease_lapse_detected", "lease_reacquired",
                                               "evidence_recorded"])
        self.assertEqual(self.custody(14).custody.executor_id, "14:1:1")

    def test_ac1_a_reap_then_a_resume_advance_the_epoch_and_void_snapshot_evidence(self):
        self.spawn_14()
        self.core(T(1)).record_evidence(self.custody(14).custody, evidence_id="probe",
                                        form="snapshot", reference="ref")
        self.assertTrue(self.custody(14).evidence[1]["admissible"])
        self.expire(issue=14, worktree=self.worktree, now=T(31))
        self.assertEqual(self.events(14)[4:], [
            "lease_lapse_detected", "stop_synthesized", "transitioned"])
        parked = self.custody(14)
        self.assertEqual((parked.state, parked.custody, parked.events[5]["reason"]),
                         ("attention_required", None, "expiry"))
        self.resume(issue=14, worktree=self.worktree, now=T(32))
        resumed = self.custody(14)
        reacquired = resumed.events[7]
        self.assertEqual((reacquired["type"], reacquired["reason"], reacquired["executor_id"]),
                         ("lease_reacquired", "expired", "14:1:2"))
        self.assertEqual((resumed.state, self.lease(self.worktree)["epoch"]), ("created", 2))
        evidence = resumed.evidence[1]
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

    def test_an_interrupted_spawn_is_not_repeated_into_another_worktree(self):
        self.init_run()
        first, other = (os.path.abspath(self.root / name) for name in ("wt-14", "wt-14b"))
        settle = attempt_store.settle_custody

        def sweep(path, **options):
            return self.control_raw(
                now=T(0), issues=[14], max_parallel=100, tracker=[self.tracker_fact(14)],
                worktrees=[self.worktree_fact(14, candidate={"path": path, "state": "absent"})],
                **options)

        def cut_before_the_ledger(*args, **options):
            settle(*args, **options)
            raise OSError("crash")

        with mock.patch.object(attempt_store, "settle_custody",
                               side_effect=cut_before_the_ledger):
            self.assertNotEqual(sweep(first, ok=False).returncode, 0)
        self.assertNotIn("14", self.read_state()["issues"])
        self.assertEqual(self.custody(14).subject["worktree"], os.path.realpath(first))
        before = self.tree()
        refused = sweep(other, ok=False)
        self.assertEqual(refused.returncode, 2, refused.stderr)
        self.assertTrue(refused.stderr.startswith(
            "workflow-state: custody projection mismatch: "), refused.stderr)
        self.assertEqual(self.tree(), before)
        sweep(first)
        attempt = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual((attempt["worktree"], self.custody(14).custody.executor_id,
                          self.lease(first)["epoch"], self.lease(other)),
                         (first, "14:1:1", 1, None))


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
        self.assertEqual(self.read_state()["schema_version"], 10)
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
        self.assertEqual(self.read_state()["schema_version"], 10)
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

    def taken_by_another_run(self):
        """The interrupted seal's window passes and another run takes the worktree, so
        the unsealed transaction's span has lapsed; returns the first ledger's bytes."""
        self.interrupted_seal()
        first = self.run_id
        self.init_run(creation_key="second-run")
        self.spawn(issue=30, worktree=self.worktree, now=T(31))
        self.run_id = first
        return self.state_path.read_bytes()

    def assert_reaped_then_sealed(self, ledger):
        self.assertEqual(self.state_path.read_bytes(), ledger)
        self.assert_sealed()
        receipt = self.core().read_receipt(self.custody(14).terminal["receipt_digest"])
        self.assertEqual([(stop["reason"], stop["executor_id"]) for stop in receipt["stops"]],
                         [("expiry", "14:1:1")])
        lease = self.lease(self.worktree)
        self.assertEqual((lease["epoch"], lease["holder"]["executor_id"]), (2, "30:1:1"))

    def test_the_identical_finish_reaps_a_lapsed_span_before_its_interrupted_seal(self):
        ledger = self.taken_by_another_run()
        self.assertEqual(self.finish_raw(1, self.failed(), now=T(32))["state"], "failed")
        self.assert_reaped_then_sealed(ledger)

    def test_migrate_apply_reaps_a_lapsed_span_before_an_interrupted_seal(self):
        ledger = self.taken_by_another_run()
        self.run_cli("migrate", "--repo-root", self.root, "--apply")
        self.assert_reaped_then_sealed(ledger)


class LaunchFenceTest(LifecycleCustody, unittest.TestCase):
    def test_ac5_attempt_keyed_progress_and_suspend_after_a_successor_launch(self):
        self.legacy_owner_resumed_to_launch_2()
        before = self.tree()
        self.assert_fenced(self.progress(phase=1, now=T(33), action_id=False, ok=False),
                           "superseded_launch", before)
        self.assert_fenced(self.suspend(issue=14, attempt=1, blocked_on="transport",
                                        now=T(33), action_id=False, ok=False),
                           "superseded_launch", before)
        self.progress(phase=1, now=T(33))  # the successor names its launch and is admitted

    def test_ac5_an_attempt_created_at_schema_9_needs_its_launch_named(self):
        self.spawn_14()
        self.expire(issue=14, worktree=self.worktree, now=T(31))
        self.resume(issue=14, worktree=self.worktree, now=T(32))
        before = self.tree()
        self.assert_fenced(self.progress(phase=1, now=T(33), action_id=False, ok=False),
                           "launch_identity_required", before)
        self.assert_fenced(self.progress(phase=1, now=T(33), action_id="14:1:1", ok=False),
                           "superseded_launch", before)
        self.assert_fenced(self.suspend(issue=14, attempt=1, blocked_on="transport",
                                        now=T(33), action_id="14:1:1", ok=False),
                           "superseded_launch", before)

    def test_an_attempt_terminal_before_the_bind_keeps_the_engines_answers(self):
        self.spawn_14()
        self.finish(1, self.stopped(), now=T(5))
        self.install_legacy(self.read_state(), "orchestrate-14", version=8)
        replayed = self.finish(1, self.stopped(), now=T(6), action_id=False)
        self.assertEqual(replayed["state"], "stopped")
        self.assertEqual(self.read_state()["schema_version"], 10)
        self.assertIsNone(self.custody(14))
        conflict = self.finish(1, self.stopped("another"), now=T(7), action_id=False, ok=False)
        self.assertEqual(conflict.returncode, 2)
        self.assertIn("conflicting terminal result for issue 14 attempt 1", conflict.stderr)
        self.assertIsNone(self.custody(14))

    def test_ac5_attempt_keyed_finish_is_refused_and_its_result_retained(self):
        self.legacy_owner_resumed_to_launch_2()
        self.contractless()
        ledger = self.state_path.read_bytes()
        launch_1 = ac.launch_fence(self.custody(14), "14:1:1")
        refused = self.finish_raw(1, self.stopped(), now=T(33), action_id=False, ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertTrue(refused.stderr.startswith(PREFIX + "superseded_launch: "),
                        refused.stderr)
        self.assertEqual(self.state_path.read_bytes(), ledger)
        results = self.events(14, "owner_result")
        self.assertEqual(len(results), 1)
        self.assertEqual((results[0]["executor_id"], results[0]["custody"],
                          results[0]["fence"], results[0]["result"]),
                         ("14:1:1", "stale", launch_1, self.stopped()))
        self.assertEqual(self.custody(14).custody.executor_id, "14:1:2")
        self.finish_raw(1, self.stopped(), now=T(33), action_id=False, ok=False)
        self.assertEqual(len(self.events(14, "owner_result")), 1)
        self.assertEqual(self.state_path.read_bytes(), ledger)

    def test_an_earlier_launch_cannot_replace_its_successors_stalled_stop(self):
        self.spawn_14(minutes=10)
        for index in range(3):
            self.suspend(issue=14, attempt=1, blocked_on="usage_limit", now=T(2 * index + 1))
            self.resume(issue=14, worktree=self.worktree, now=T(2 * index + 2))
        self.suspend(issue=14, attempt=1, blocked_on="usage_limit", now=T(8))
        self.contractless()
        attempt = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual((attempt["state"], attempt["result_source"], len(attempt["launches"])),
                         ("stopped", "stalled", 4))
        ledger = self.state_path.read_bytes()
        refused = self.finish_raw(1, self.stopped("from launch 1"), now=T(9),
                                  action_id="14:1:1", ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertTrue(refused.stderr.startswith(PREFIX + "superseded_launch: "),
                        refused.stderr)
        self.assertEqual(self.state_path.read_bytes(), ledger)
        (kept,) = self.events(14, "owner_result")
        self.assertEqual((kept["executor_id"], kept["custody"], kept["result"]),
                         ("14:1:1", "stale", self.stopped("from launch 1")))
        self.finish_raw(1, self.stopped("from launch 4"), now=T(9))
        attempt = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual((attempt["state"], attempt["result_source"]), ("stopped", "owner"))
        sealed = self.custody(14)
        receipt = self.core().read_receipt(sealed.terminal["receipt_digest"])
        self.assertEqual([result["executor_id"] for result in receipt["owner_results"]],
                         ["14:1:1", "14:1:4"])
        self.assertEqual(sealed.state, "abandoned")


class DeliveredCustody(CustodyReads, DeliveredControlHarness):
    def ledger_path(self):
        return self.ledger

    def observed_root(self):
        return Path(self.root)

    def spawn(self, *issues):
        """Spawn `issues` under contracts at minute 0; their implementation custodies."""
        self.setup_run()
        spawned = self.control(0, recorded=dict.fromkeys(issues), contracts=True)
        return {action["issue"]: action["custody"] for action in spawned["actions"]
                if action["kind"] in DISPATCH}

    def summary(self, custody, historical_state, observations=(), authority=(), **result):
        issue = custody["action_id"].partition(":")[0]
        contract = self.built[int(issue)]["contract"]
        historical = {"issue": int(issue), "state": historical_state, "pr_url": None,
                      "merge_sha": None, "issue_closed": False, "discussion_items": [],
                      "detail_state": "none", "report_path": None, "notes": "late", **result}
        return self.validated("ship-summary", {
            "interface_version": 2, "issue": int(issue), "state": "terminal_failed",
            "custody": custody, "historical_owner_result": historical,
            "delivery_contract_digest": self.model.canonical_digest(contract),
            "delivery_observations": sorted(observations, key=lambda item: item["id"]),
            "authority_observations": list(authority), "reevaluation_evidence": [],
            "detail_state": "none", "report_path": None, "notes": "late"})

    def reap(self, issue):
        """Minute 31: the launch has expired and its worktree no longer matches, so the
        sweep reaps without resuming."""
        self.control(31, recorded={issue: "mismatch"})
        attempt = self.records(issue)[0][0]
        self.assertEqual((attempt["state"], attempt["blocked_on"], len(attempt["launches"])),
                         ("suspended", "unknown", 1))

    def finish(self, summary, minute, **options):
        return self.cli("finish", *self.run_args, "--now", at(minute), "--summary-file", "-",
                        stdin=summary, **options)

    def merge_checkpoint(self, custody, minute):
        """Select, publish, open and reach the merge stage at `minute`; returns the
        observations and authority the finishing summary still has to carry."""
        issue, when = DELIVERED, at(minute)
        contract = self.built[issue]["contract"]
        url, head = f"https://github.com/fagenorn/nix-config/pull/{issue}", "a" * 40
        selection = self.build("selected-output", {
            "contract": contract, "head": head, "tree": "c" * 40,
            "acceptance_ref": f".claude/specs/issue-{issue}.md", "review_ref": "clean",
            "test_ref": "checks"})
        pending = [self.observed(contract, when, "selected_output", selection=selection),
                   self.observed(contract, when, "branch_published", head=head),
                   self.observed(contract, when, "pr_opened", pr_number=issue, pr_url=url,
                                 head=head)]
        scope = self.build("scope", {"contract": contract, "stage_id": "merge_pr"})
        self.cli("checkpoint-delivery", *self.run_args, "--now", when, "--checkpoint-file",
                 "-", stdin=self.validated("ship-checkpoint", {
                     "interface_version": 2, "issue": issue, "custody": custody,
                     "contract_digest": self.model.canonical_digest(contract),
                     "delivery_observations": sorted(pending, key=lambda item: item["id"]),
                     "authority_observations": [], "reevaluation_evidence": [],
                     "requested_scope": scope, "detail_state": "none", "report_path": None,
                     "notes": ""}))
        authority = self.build("authority-observation", {
            "contract": contract, "scope_id": scope["id"], "launch_id": custody["action_id"],
            "authority_kind": "native_guard", "verdict": "allowed",
            "reason_code": "guard_allowed", "observed_at": when, "evidence": "merge_pr"})
        merged = self.observed(contract, when, "pr_merged", pr_number=issue, pr_url=url,
                               head=head, merge_sha="b" * 40)
        return [merged], [authority], {"pr_url": url, "merge_sha": "b" * 40}

    def postconditions(self, issue):
        delivery = self.ledger_document()["issues"][str(issue)]["delivery"]
        return {name: item["state"] for name, item in delivery["postconditions"].items()}

    def core_files(self):
        return {path: content for path, content in self.tree().items()
                if path.startswith(".superpowers/attempt-transactions/")}


class MisbindingTest(DeliveredCustody, unittest.TestCase):
    def transports(self, custody):
        issue, action = DELIVERED, custody["action_id"]
        contract = self.built[issue]["contract"]
        checkpoint = self.validated("ship-checkpoint", {
            "interface_version": 2, "issue": issue, "custody": custody,
            "contract_digest": self.model.canonical_digest(contract),
            "delivery_observations": [], "authority_observations": [],
            "reevaluation_evidence": [],
            "requested_scope": self.build("scope", {"contract": contract,
                                                    "stage_id": "merge_pr"}),
            "detail_state": "none", "report_path": None, "notes": ""})
        result = self.root / "result.json"
        result.write_text(json.dumps({
            "issue": issue, "state": "stopped", "pr_url": None, "merge_sha": None,
            "issue_closed": False, "discussion_items": [], "detail_state": "none",
            "report_path": None, "notes": "stop"}), encoding="utf-8")
        keyed = ("--issue", issue, "--attempt", 1, "--action-id", action)
        return {
            "progress": (("progress", *self.run_args, *keyed, "--phase", 1, "--now", at(1),
                          "--turn-ceiling", 120, "--context-ceiling", 150000,
                          "--turn-headroom", 2, "--context-headroom", 10000,
                          "--next-needs-context", "true", "--artifacts-sufficient", "false",
                          "--remainder-self-contained", "false"), None),
            "suspend": (("suspend", *self.run_args, *keyed, "--blocked-on", "transport",
                         "--now", at(1)), None),
            "finish": (("finish", *self.run_args, *keyed, "--result-file", result,
                        "--now", at(1)), None),
            "finish-summary": (("finish", *self.run_args, "--now", at(1), "--summary-file",
                                "-"), self.summary(custody, "stopped")),
            "checkpoint-delivery": (("checkpoint-delivery", *self.run_args, "--now", at(1),
                                     "--checkpoint-file", "-"), checkpoint),
            "mark-progress": (("mark-progress", *self.run_args, "--now", at(1),
                               "--action-id", action), None),
            "declare-lane": (("declare-lane", *self.run_args, "--now", at(1), "--action-id",
                              action, "--lane", "light", "--budget-minutes", 20, "--reason",
                              "triage"), None),
            "register-worker": (("register-worker", *self.run_args, "--now", at(1),
                                 "--action-id", action), None),
            "release-worker": (("release-worker", *self.run_args, "--now", at(1),
                                "--worker-id", f"{action}:w1", "--event", "returned"), None)}

    def test_ac3_a_session_in_another_attempts_worktree_is_refused_before_any_write(self):
        custodies = self.spawn(DELIVERED, LIVE)
        for worktree in self.worktrees.values():
            (Path(worktree) / "nested").mkdir(parents=True)
        transports = self.transports(custodies[DELIVERED])
        before = self.tree()
        other = Path(self.worktrees[LIVE]) / "nested"
        for name, (argv, stdin) in transports.items():
            with self.subTest(transport=name):
                refused = self.cli(*argv, stdin=stdin, ok=False, cwd=other)
                self.assert_fenced(refused, "custody_misbound", before)
                for path in (self.worktrees[DELIVERED], self.worktrees[LIVE]):
                    self.assertIn(os.path.realpath(path).encode(), refused.stderr)
        for standing in (self.root, self.worktrees[DELIVERED]):
            for name in ("register-worker", "progress"):
                with self.subTest(transport=name, standing=standing):
                    argv, stdin = transports[name]
                    self.cli(*argv, stdin=stdin, cwd=standing)
        for name, (argv, stdin) in transports.items():
            with self.subTest(admitted=name):
                own = self.cli(*argv, stdin=stdin, ok=False, cwd=self.worktrees[DELIVERED])
                self.assertNotIn(b"fencing violation", own.stderr)

    def test_a_corrupt_ledger_keeps_the_engines_refusal_inside_an_attempt_worktree(self):
        custody = self.spawn(DELIVERED)[DELIVERED]
        Path(self.worktrees[DELIVERED]).mkdir(parents=True, exist_ok=True)
        transports = self.transports(custody)
        del transports["mark-progress"]  # it read the ledger unlocked before this fence
        self.ledger.write_bytes(b"{")
        with self.assertRaises(json.JSONDecodeError) as corrupt:
            json.loads("{")
        engine = f"workflow-state: invalid workflow state JSON: {corrupt.exception}\n"
        for name, (argv, stdin) in transports.items():
            with self.subTest(transport=name):
                refused = self.cli(*argv, stdin=stdin, ok=False, cwd=self.worktrees[DELIVERED])
                self.assertEqual((refused.returncode, refused.stderr),
                                 (2, engine.encode()))


class LateLegacyResultTest(LifecycleCustody, unittest.TestCase):
    def reaped(self):
        self.spawn_14()
        self.expire(issue=14, worktree=self.worktree, now=T(31))
        attempt = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual((attempt["state"], attempt["blocked_on"]), ("suspended", "unknown"))

    def test_ac2_a_late_finish_supersedes_the_reapers_stop_in_the_receipt(self):
        self.reaped()
        self.assertEqual(self.finish(1, self.stopped(), now=T(32))["state"], "stopped")
        attempt = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual((attempt["state"], attempt["result_source"]), ("stopped", "owner"))
        sealed = self.custody(14)
        self.assertEqual((sealed.state, sealed.terminal["outcome"]), ("abandoned", "abandoned"))
        receipt = self.core().read_receipt(sealed.terminal["receipt_digest"])
        (stop,), (result,) = receipt["stops"], receipt["owner_results"]
        self.assertEqual((receipt["outcome"], stop["reason"], stop["executor_id"]),
                         ("abandoned", "expiry", "14:1:1"))
        self.assertEqual((stop["superseded_by"], result["supersedes"], result["custody"]),
                         (result["seq"], stop["seq"], "stale"))

    def test_ac2_a_late_merged_finish_is_recorded_and_left_unsealed(self):
        self.reaped()
        self.finish(1, self.merged_result(), now=T(32))
        attempt = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual((attempt["state"], attempt["result_source"]), ("merged", "owner"))
        open_ = self.custody(14)
        (stop,) = self.events(14, "stop_synthesized")
        (result,) = self.events(14, "owner_result")
        self.assertEqual((result["supersedes"], result["custody"]), (stop["seq"], "stale"))
        self.assertEqual((open_.state, open_.terminal, open_.custody),
                         ("attention_required", None, None))

    def test_an_on_time_finish_is_recorded_current_and_sealed(self):
        self.spawn_14()
        self.finish(1, self.stopped("on time"), now=T(5))
        sealed = self.custody(14)
        receipt = self.core().read_receipt(sealed.terminal["receipt_digest"])
        (result,) = receipt["owner_results"]
        self.assertEqual((receipt["outcome"], receipt["stops"], result["custody"],
                          result["supersedes"]), ("abandoned", [], "current", None))
        self.assertEqual(sealed.events[-3]["reason"], "owner:stopped")

    def test_a_finish_refused_for_custody_is_retained_without_touching_the_ledger(self):
        self.spawn_14()
        self.progress(turn_count=118, context_tokens=20000, now=T(1),
                      handoff_path=self.write_handoff(14))
        self.contractless()
        ledger = self.state_path.read_bytes()
        refused = self.finish_raw(1, self.stopped(), now=T(2), ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("finish requires an active attempt", refused.stderr)
        self.assertEqual(self.state_path.read_bytes(), ledger)
        (result,) = self.events(14, "owner_result")
        self.assertEqual((result["custody"], result["supersedes"]), ("stale", None))

    def test_the_repeat_of_an_interrupted_finish_seals_one_result(self):
        self.spawn_14()
        self.contractless()
        with mock.patch.object(attempt_store, "seal_custody", side_effect=OSError("crash")):
            self.finish_raw(1, self.stopped(), now=T(5), ok=False)
        self.assertIsNone(self.custody(14).terminal)
        self.finish_raw(1, self.stopped(), now=T(6))
        sealed = self.custody(14)
        receipt = self.core().read_receipt(sealed.terminal["receipt_digest"])
        (result,) = receipt["owner_results"]
        self.assertEqual((sealed.state, result["custody"]), ("abandoned", "current"))


class LateSummaryTest(DeliveredCustody, unittest.TestCase):
    def test_ac2_a_late_summary_supersedes_the_reapers_stop_in_the_receipt(self):
        custody = self.spawn(DELIVERED)[DELIVERED]
        self.reap(DELIVERED)
        finished = json.loads(self.finish(self.summary(custody, "stopped"), 32).stdout)
        self.assertEqual(finished["kind"], "terminal_failed")
        attempt = self.records(DELIVERED)[0][0]
        self.assertEqual((attempt["state"], attempt["result_source"]), ("stopped", "owner"))
        sealed = self.custody(DELIVERED)
        receipt = self.core().read_receipt(sealed.terminal["receipt_digest"])
        (stop,), (result,) = receipt["stops"], receipt["owner_results"]
        self.assertEqual((receipt["outcome"], stop["reason"], result["custody"]),
                         ("abandoned", "expiry", "stale"))
        self.assertEqual((stop["superseded_by"], result["supersedes"]),
                         (result["seq"], stop["seq"]))

    def test_a_late_summary_without_a_reap_or_from_an_earlier_launch_is_not_adopted(self):
        custody = self.spawn(DELIVERED)[DELIVERED]
        self.control(31, recorded={DELIVERED: "matching_issue_branch"})  # reap and resume
        ledger = self.ledger.read_bytes()
        refused = self.finish(self.summary(custody, "stopped"), 32, ok=False)
        self.assertEqual((refused.returncode, refused.stderr),
                         (2, b"workflow-state: delivery finish refused\n"))
        self.assertEqual(self.ledger.read_bytes(), ledger)
        (result,) = self.events(DELIVERED, "owner_result")
        self.assertEqual((result["executor_id"], result["custody"]),
                         (f"{DELIVERED}:1:1", "stale"))

    def test_ac4_merged_and_closed_are_observed_apart_from_custody(self):
        custody = self.spawn(DELIVERED)[DELIVERED]
        observations, authority, merged = self.merge_checkpoint(custody, 5)
        self.reap(DELIVERED)
        self.finish(self.summary(custody, "merged", observations, authority, **merged), 32)
        attempt = self.records(DELIVERED)[0][0]
        self.assertEqual((attempt["state"], attempt["result_source"]), ("merged", "owner"))
        held = self.custody(DELIVERED)
        (stop,) = self.events(DELIVERED, "stop_synthesized")
        (result,) = self.events(DELIVERED, "owner_result")
        self.assertEqual((held.terminal, held.custody, result["supersedes"]),
                         (None, None, stop["seq"]))
        before = self.postconditions(DELIVERED)
        self.assertEqual((before["pr_merged"], before["tracker_closed"]),
                         ("observed", "pending"))
        core = self.core_files()
        contract = self.built[DELIVERED]["contract"]
        request = json.loads(self.request(40, recorded={DELIVERED: "matching_issue_branch"},
                                          contracts=True))
        request["delivery_observations"][str(DELIVERED)] = [self.observed(
            contract, at(40), "tracker_closed", close_reason="completed",
            observation_identity=f"github:issue:{DELIVERED}:closed")]
        self.cli("control", *self.run_args, "--request-file", "-",
                 stdin=json.dumps(request).encode())
        self.assertEqual(self.postconditions(DELIVERED),
                         {**before, "tracker_closed": "observed"})
        self.assertEqual(self.core_files(), core)


class CompatibilityTest(LifecycleCustody, unittest.TestCase):
    def base_helper(self, scratch):
        found = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e",
                                f"{BASE_COMMIT}^{{commit}}"], capture_output=True)
        if found.returncode != 0:
            self.fail(f"base commit {BASE_COMMIT} is missing; fetch it, do not skip (D14)")
        archive = subprocess.run(
            ["git", "-C", str(REPO), "archive", BASE_COMMIT, "python/agent_tools",
             "home/common/agent-skills/scripts",
             "home/common/agent-skills/artifact-budget-policy.json"],
            capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(scratch)], input=archive.stdout, check=True)
        script = scratch / "home/common/agent-skills/scripts/workflow-state.py"
        env = {**self.cli_env, "PYTHONPATH": str(scratch / "python")}
        return lambda command, *rest: subprocess.run(
            [sys.executable, str(script), command, "--repo-root", str(self.root),
             "--run-id", self.run_id, "--action-id", "14:1:1", *rest],
            env=env, cwd=scratch, capture_output=True, text=True, timeout=120)

    def test_ac6_the_base_helper_refuses_a_schema_9_ledger_without_writing(self):
        self.spawn_14()
        self.install_legacy(self.read_state(), "orchestrate-14", version=8)
        with tempfile.TemporaryDirectory() as scratch:
            base = self.base_helper(Path(scratch))
            control = base("check-launch")  # positive control: it reads schema 8
            self.assertEqual((control.returncode, json.loads(control.stdout)["reason"]),
                             (0, "current"), control.stderr)
            self.register_worker(action_id="14:1:1", now=T(1))
            self.assertEqual(self.read_state()["schema_version"], 10)
            before = self.tree()
            for command, rest in (("check-launch", ()),
                                  ("register-worker", ("--now", T(2)))):
                with self.subTest(command=command):
                    refused = base(command, *rest)
                    self.assertEqual(refused.returncode, 2, refused.stdout)
                    self.assertIn("unknown_schema", refused.stderr)
                    self.assertEqual(self.tree(), before)

    def test_ac6_launch_projections_print_the_same_bytes_across_the_bind(self):
        self.spawn_14()
        self.install_legacy(self.read_state(), "orchestrate-14", version=8)

        def projections():
            return [self.run_cli(command, "--repo-root", self.root, "--run-id", self.run_id,
                                 "--action-id", action).stdout
                    for command in ("check-launch", "current-launch")
                    for action in ("14:1:1", "14:1:2", "14:r1:1")]

        before = projections()
        self.register_worker(action_id="14:1:1", now=T(1))
        self.assertEqual(self.read_state()["schema_version"], 10)
        self.assertEqual(projections(), before)


if __name__ == "__main__":
    unittest.main()
