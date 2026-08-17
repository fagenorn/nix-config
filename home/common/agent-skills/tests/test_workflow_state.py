import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "workflow-state.py"
DEFAULT_NOW = "2026-08-13T20:00:00Z"


class WorkflowStateLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.run_id = "issue-14-test"

    @property
    def workflows_dir(self):
        return self.root / ".superpowers" / "workflows"

    @property
    def state_path(self):
        return self.workflows_dir / self.run_id / "state.json"

    def run_cli(self, *args, ok=True):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, args)],
            capture_output=True,
            text=True,
            check=False,
        )
        if ok and completed.returncode != 0:
            self.fail(
                f"command failed with {completed.returncode}: {completed.stderr}"
            )
        return completed

    def init_run(self, *, now=DEFAULT_NOW):
        completed = self.run_cli(
            "init-run",
            "--repo-root",
            self.root,
            "--run-id",
            self.run_id,
            "--now",
            now,
        )
        return json.loads(completed.stdout)

    def launch(
        self,
        *,
        issue,
        owner,
        worktree,
        now=DEFAULT_NOW,
        budget_minutes=30,
        ok=True,
    ):
        completed = self.run_cli(
            "launch",
            "--repo-root",
            self.root,
            "--run-id",
            self.run_id,
            "--issue",
            issue,
            "--owner",
            owner,
            "--worktree",
            worktree,
            "--now",
            now,
            "--budget-minutes",
            budget_minutes,
            ok=ok,
        )
        return json.loads(completed.stdout) if ok else completed

    def progress(
        self,
        *,
        issue=14,
        attempt=1,
        phase=1,
        now=DEFAULT_NOW,
        turn_count=10,
        context_tokens=20000,
        turn_ceiling=120,
        context_ceiling=150000,
        turn_headroom=2,
        context_headroom=10000,
        next_needs_context=True,
        artifacts_sufficient=False,
        remainder_self_contained=False,
        handoff_path=None,
        ok=True,
    ):
        args = [
            "progress",
            "--repo-root",
            self.root,
            "--run-id",
            self.run_id,
            "--issue",
            issue,
            "--attempt",
            attempt,
            "--phase",
            phase,
            "--now",
            now,
            "--turn-ceiling",
            turn_ceiling,
            "--context-ceiling",
            context_ceiling,
            "--turn-headroom",
            turn_headroom,
            "--context-headroom",
            context_headroom,
            "--next-needs-context",
            str(next_needs_context).lower(),
            "--artifacts-sufficient",
            str(artifacts_sufficient).lower(),
            "--remainder-self-contained",
            str(remainder_self_contained).lower(),
        ]
        if turn_count is not None:
            args.extend(("--turn-count", turn_count))
        if context_tokens is not None:
            args.extend(("--context-tokens", context_tokens))
        if handoff_path is not None:
            args.extend(("--handoff-path", handoff_path))
        completed = self.run_cli(*args, ok=ok)
        return json.loads(completed.stdout) if ok else completed

    def write_handoff(self, issue, contents="durable handoff\n"):
        handoffs = self.workflows_dir / self.run_id / "handoffs"
        handoffs.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=handoffs, delete=False
        ) as output:
            temporary_path = Path(output.name)
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        handoff_path = handoffs / f"issue-{issue}.md"
        os.replace(temporary_path, handoff_path)
        return handoff_path

    def finish(self, attempt, result, *, issue=14, now=DEFAULT_NOW, ok=True):
        result_path = self.root / f"result-{issue}-{attempt}.json"
        result_path.write_text(json.dumps(result), encoding="utf-8")
        completed = self.run_cli(
            "finish",
            "--repo-root",
            self.root,
            "--run-id",
            self.run_id,
            "--issue",
            issue,
            "--attempt",
            attempt,
            "--result-file",
            result_path,
            "--now",
            now,
            ok=ok,
        )
        return json.loads(completed.stdout) if ok else completed

    def reconcile(self, *, now=DEFAULT_NOW, ok=True):
        completed = self.run_cli(
            "reconcile",
            "--repo-root",
            self.root,
            "--run-id",
            self.run_id,
            "--now",
            now,
            ok=ok,
        )
        return json.loads(completed.stdout) if ok else completed

    def read_state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    @staticmethod
    def merged_result(issue=14):
        return {
            "issue": issue,
            "state": "merged",
            "pr_url": "https://github.com/fagenorn/nix-config/pull/15",
            "merge_sha": "abc123",
            "issue_closed": True,
            "discussion_items": [],
            "notes": "",
        }

    def test_delayed_notification_recovers_durable_terminal_result(self):
        self.init_run()
        first = self.launch(issue=14, owner="owner-a", worktree=self.root / "wt-a")
        result = self.merged_result()
        persisted = self.finish(first["attempt"], result)
        recovered = self.reconcile(now="2026-08-13T20:10:00Z")
        self.assertEqual(persisted, result)
        self.assertEqual(recovered["issues"]["14"]["outcome"], result)

    def test_same_owner_worktree_resume_keeps_attempt_and_deadline(self):
        self.init_run()
        worktree = self.root / "parent" / ".." / "wt-a"
        first = self.launch(issue=14, owner="owner-a", worktree=worktree)
        resumed = self.launch(
            issue=14,
            owner="owner-a",
            worktree=self.root / "wt-a",
            now="2026-08-13T20:20:00Z",
        )
        self.assertEqual((resumed["attempt"], resumed["launch_kind"]), (1, "resume"))
        self.assertEqual(resumed["deadline_at"], first["deadline_at"])
        self.assertEqual(resumed["started_at"], first["started_at"])

        persisted = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual(persisted["issue"], 14)
        self.assertEqual(
            persisted["launches"],
            [
                {
                    "kind": "fresh",
                    "owner": "owner-a",
                    "worktree": str((self.root / "wt-a").resolve()),
                    "at": DEFAULT_NOW,
                },
                {
                    "kind": "resume",
                    "owner": "owner-a",
                    "worktree": str((self.root / "wt-a").resolve()),
                    "at": "2026-08-13T20:20:00Z",
                },
            ],
        )

    def test_only_one_fresh_retry_and_refusal_links_prior_attempts(self):
        self.init_run()
        first = self.launch(issue=14, owner="owner-a", worktree=self.root / "wt-a")
        second = self.launch(issue=14, owner="owner-b", worktree=self.root / "wt-b")
        refused = self.launch(
            issue=14, owner="owner-c", worktree=self.root / "wt-c", ok=False
        )
        state = self.read_state()
        self.assertEqual((second["attempt"], second["prior_attempt"]), (2, 1))
        self.assertEqual(first["issue"], 14)
        self.assertEqual(second["issue"], 14)
        self.assertEqual(state["issues"]["14"]["outcome"]["state"], "failed")
        self.assertIn(str((self.root / "wt-a").resolve()), first["worktree"])
        self.assertIn(
            str((self.root / "wt-a").resolve()),
            state["issues"]["14"]["attempts"][0]["result"]["notes"],
        )
        self.assertIn(
            str((self.root / "wt-b").resolve()),
            state["issues"]["14"]["outcome"]["notes"],
        )
        self.assertEqual(refused.returncode, 3)
        self.assertIn("attempts 1 and 2", refused.stderr)

    def test_owner_death_expiry_stops_active_attempt_with_worktree(self):
        self.init_run()
        worktree = self.root / "silent-owner"
        launched = self.launch(
            issue=14, owner="owner-a", worktree=worktree, budget_minutes=10
        )
        reconciled = self.reconcile(now="2026-08-13T20:10:00Z")
        attempt = reconciled["issues"]["14"]["attempts"][0]
        outcome = reconciled["issues"]["14"]["outcome"]
        self.assertEqual(launched["deadline_at"], "2026-08-13T20:10:00Z")
        self.assertEqual((attempt["state"], outcome["state"]), ("stopped", "stopped"))
        self.assertIn(str(worktree.resolve()), outcome["notes"])
        self.assertLessEqual(len(outcome["notes"]), 500)
        self.assertEqual(attempt["result_source"], "expiry")
        self.assertEqual(attempt["finished_at"], "2026-08-13T20:10:00Z")
        self.assertGreaterEqual(attempt["finished_at"], attempt["deadline_at"])

    def test_superseding_retry_and_refusal_stamp_their_result_source(self):
        self.init_run()
        self.launch(issue=14, owner="owner-a", worktree=self.root / "wt-a")
        self.launch(
            issue=14,
            owner="owner-b",
            worktree=self.root / "wt-b",
            now="2026-08-13T20:10:00Z",
        )
        attempts = self.read_state()["issues"]["14"]["attempts"]
        self.assertEqual(attempts[0]["state"], "stopped")
        self.assertEqual(attempts[0]["result_source"], "superseded")
        self.assertEqual(attempts[0]["finished_at"], "2026-08-13T20:10:00Z")
        self.assertIsNone(attempts[1]["finished_at"])
        self.assertIsNone(attempts[1]["result_source"])

        refused = self.launch(
            issue=14,
            owner="owner-c",
            worktree=self.root / "wt-c",
            now="2026-08-13T20:20:00Z",
            ok=False,
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("attempts 1 and 2 already consumed", refused.stderr)
        attempts = self.read_state()["issues"]["14"]["attempts"]
        self.assertEqual(attempts[1]["state"], "failed")
        self.assertEqual(attempts[1]["result_source"], "refused")
        self.assertEqual(attempts[1]["finished_at"], "2026-08-13T20:20:00Z")

    def test_late_merged_finish_preserves_the_owner_result(self):
        self.init_run()
        worktree = self.root / "late-owner"
        launched = self.launch(
            issue=14, owner="owner-a", worktree=worktree, budget_minutes=10
        )
        reported = self.merged_result()
        stdout_json = self.finish(
            launched["attempt"],
            reported,
            now="2026-08-13T20:10:00Z",
        )
        state = self.read_state()
        attempt = state["issues"]["14"]["attempts"][0]
        outcome = state["issues"]["14"]["outcome"]
        self.assertEqual(attempt["state"], "merged")
        self.assertEqual(attempt["result"]["state"], "merged")
        self.assertEqual(attempt["result"]["pr_url"], reported["pr_url"])
        self.assertEqual(attempt["result"]["merge_sha"], reported["merge_sha"])
        self.assertIs(attempt["result"]["issue_closed"], True)
        self.assertEqual(attempt["result"]["notes"], "")
        self.assertEqual(attempt["finished_at"], "2026-08-13T20:10:00Z")
        self.assertGreaterEqual(attempt["finished_at"], attempt["deadline_at"])
        self.assertEqual(attempt["result_source"], "owner")
        self.assertEqual(outcome, attempt["result"])
        self.assertEqual(stdout_json, attempt["result"])

    def test_expiry_result_is_provisional_until_the_owner_reports(self):
        self.init_run()
        self.launch(
            issue=14,
            owner="owner-a",
            worktree=self.root / "wt-a",
            budget_minutes=10,
        )
        self.reconcile(now="2026-08-13T20:10:00Z")
        attempt = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual(attempt["state"], "stopped")
        self.assertEqual(attempt["result_source"], "expiry")

        merged = {
            **self.merged_result(),
            "notes": "merged after the deadline",
        }
        stdout_json = self.finish(1, merged, now="2026-08-13T20:20:00Z")
        state = self.read_state()
        attempt = state["issues"]["14"]["attempts"][0]
        self.assertEqual(attempt["state"], "merged")
        self.assertEqual(attempt["result_source"], "owner")
        self.assertEqual(attempt["finished_at"], "2026-08-13T20:20:00Z")
        self.assertEqual(attempt["result"]["notes"], "merged after the deadline")
        self.assertEqual(state["issues"]["14"]["outcome"], attempt["result"])
        self.assertEqual(stdout_json, attempt["result"])

        before = self.state_path.read_bytes()
        other = {
            **self.merged_result(),
            "state": "failed",
            "pr_url": None,
            "merge_sha": None,
            "issue_closed": False,
            "notes": "conflicting",
        }
        rejected = self.finish(1, other, now="2026-08-13T20:30:00Z", ok=False)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("conflicting terminal result", rejected.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_expired_older_attempt_cannot_supersede_after_a_fresh_retry(self):
        self.init_run()
        self.launch(
            issue=14,
            owner="owner-a",
            worktree=self.root / "wt-a",
            budget_minutes=10,
        )
        self.reconcile(now="2026-08-13T20:10:00Z")
        self.launch(
            issue=14,
            owner="owner-b",
            worktree=self.root / "wt-a",
            now="2026-08-13T20:15:00Z",
        )
        before = self.state_path.read_bytes()
        rejected = self.finish(
            1, self.merged_result(), now="2026-08-13T20:20:00Z", ok=False
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("conflicting terminal result", rejected.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_refused_third_attempt_result_is_not_supersedable(self):
        self.init_run()
        self.launch(issue=14, owner="owner-a", worktree=self.root / "wt-a")
        self.launch(
            issue=14,
            owner="owner-b",
            worktree=self.root / "wt-b",
            now="2026-08-13T20:10:00Z",
        )
        self.launch(
            issue=14,
            owner="owner-c",
            worktree=self.root / "wt-c",
            now="2026-08-13T20:20:00Z",
            ok=False,
        )
        before = self.state_path.read_bytes()
        rejected = self.finish(
            2, self.merged_result(), now="2026-08-13T20:25:00Z", ok=False
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("conflicting terminal result", rejected.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_finish_rejects_time_before_last_progress(self):
        self.init_run()
        self.launch(issue=14, owner="owner-a", worktree=self.root / "wt-a")
        self.progress(issue=14, attempt=1, phase=3, now="2026-08-13T20:05:00Z")
        before = self.state_path.read_bytes()
        rejected = self.finish(
            1, self.merged_result(), now="2026-08-13T20:02:00Z", ok=False
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("finish time must not move backward", rejected.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_handed_off_finish_rejects_without_changing_state(self):
        self.init_run()
        self.launch(issue=14, owner="owner-a", worktree=self.root / "wt-a")
        handoff_path = self.write_handoff(14)
        handed_off = self.progress(
            turn_count=118,
            context_tokens=20000,
            handoff_path=handoff_path,
        )
        self.assertEqual(handed_off["state"], "handed_off")
        before = self.state_path.read_bytes()
        rejected = self.finish(1, self.merged_result(), ok=False)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("active attempt", rejected.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_owner_death_expiry_can_use_the_single_fresh_retry(self):
        self.init_run()
        self.launch(
            issue=14,
            owner="owner-a",
            worktree=self.root / "silent-owner",
            budget_minutes=10,
        )
        self.reconcile(now="2026-08-13T20:10:00Z")
        retried = self.launch(
            issue=14,
            owner="owner-b",
            worktree=self.root / "retry-owner",
            now="2026-08-13T20:11:00Z",
        )
        self.assertEqual((retried["attempt"], retried["prior_attempt"]), (2, 1))
        state = self.read_state()["issues"]["14"]
        self.assertIsNone(state["outcome"])
        self.assertEqual(state["attempts"][0]["state"], "stopped")

    def test_fresh_retry_may_reuse_the_prior_attempt_worktree(self):
        self.init_run()
        shared = self.root / "wt-issue-14"
        resolved = str(shared.resolve())
        self.launch(issue=14, owner="owner-a", worktree=shared, budget_minutes=10)
        self.reconcile(now="2026-08-13T20:10:00Z")
        first = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual(first["state"], "stopped")
        self.assertEqual(first["result_source"], "expiry")
        self.assertEqual(first["worktree"], resolved)

        retried = self.launch(
            issue=14,
            owner="owner-b",
            worktree=shared,
            now="2026-08-13T20:15:00Z",
        )
        self.assertEqual(retried["attempt"], 2)
        self.assertEqual(retried["worktree"], resolved)
        self.assertEqual(retried["prior_attempt"], 1)
        self.assertEqual(retried["state"], "active")
        attempts = self.read_state()["issues"]["14"]["attempts"]
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[1]["worktree"], attempts[0]["worktree"])

        blocked = {
            **self.merged_result(),
            "state": "stopped",
            "pr_url": None,
            "merge_sha": None,
            "issue_closed": False,
            "notes": "blocked",
        }
        self.finish(2, blocked, now="2026-08-13T20:30:00Z")
        before = self.state_path.read_bytes()
        resumed = self.launch(
            issue=14,
            owner="owner-b",
            worktree=shared,
            now="2026-08-13T20:40:00Z",
        )
        self.assertEqual(resumed["state"], "stopped")
        self.assertEqual(len(self.read_state()["issues"]["14"]["attempts"]), 2)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_progress_action_precedence_and_complete_inputs_are_persisted(self):
        self.init_run()
        cases = [
            (
                {
                    "remainder_self_contained": True,
                    "turn_count": 119,
                    "context_tokens": 149000,
                },
                "handoff",
            ),
            (
                {
                    "next_needs_context": False,
                    "artifacts_sufficient": True,
                    "turn_count": 119,
                    "context_tokens": 149000,
                },
                "fresh_start",
            ),
            (
                {
                    "next_needs_context": True,
                    "turn_count": 10,
                    "context_tokens": 20000,
                },
                "continue",
            ),
            (
                {
                    "next_needs_context": True,
                    "turn_count": 118,
                    "context_tokens": 20000,
                },
                "handoff",
            ),
            (
                {
                    "next_needs_context": True,
                    "turn_count": 10,
                    "context_tokens": 140000,
                },
                "handoff",
            ),
            (
                {
                    "next_needs_context": True,
                    "turn_count": None,
                    "context_tokens": None,
                },
                "handoff",
            ),
        ]
        for index, (overrides, expected_action) in enumerate(cases, start=1):
            issue = 20 + index
            self.launch(
                issue=issue,
                owner=f"owner-{issue}",
                worktree=self.root / f"wt-{issue}",
            )
            result = self.progress(issue=issue, phase=index, **overrides)
            persisted = self.read_state()["issues"][str(issue)]["attempts"][0]
            expected_inputs = {
                "turn_count": overrides.get("turn_count", 10),
                "context_tokens": overrides.get("context_tokens", 20000),
                "turn_ceiling": 120,
                "context_ceiling": 150000,
                "turn_headroom": 2,
                "context_headroom": 10000,
                "next_needs_context": overrides.get("next_needs_context", True),
                "artifacts_sufficient": overrides.get("artifacts_sufficient", False),
                "remainder_self_contained": overrides.get(
                    "remainder_self_contained", False
                ),
            }
            with self.subTest(expected_action=expected_action):
                self.assertEqual(result["phase_action"], expected_action)
                self.assertEqual(persisted["phase_action"], expected_action)
                self.assertEqual(persisted["phase"], index)
                self.assertEqual(persisted["last_progress_at"], DEFAULT_NOW)
                self.assertEqual(persisted["phase_inputs"], expected_inputs)

    def test_delegate_requires_measured_usage_below_both_ceilings(self):
        self.init_run()
        self.launch(issue=14, owner="owner-a", worktree=self.root / "wt-a")
        delegated = self.progress(
            issue=14,
            attempt=1,
            phase=3,
            now="2026-08-13T20:05:00Z",
            turn_count=10,
            context_tokens=20000,
            next_needs_context=True,
            artifacts_sufficient=False,
            remainder_self_contained=True,
        )
        self.assertEqual(delegated["phase_action"], "delegate")

        unknown_usage = self.progress(
            issue=14,
            attempt=1,
            phase=4,
            now="2026-08-13T20:10:00Z",
            turn_count=None,
            context_tokens=None,
            next_needs_context=True,
            artifacts_sufficient=False,
            remainder_self_contained=True,
        )
        self.assertEqual(unknown_usage["phase_action"], "handoff")

        at_context_ceiling = self.progress(
            issue=14,
            attempt=1,
            phase=5,
            now="2026-08-13T20:15:00Z",
            turn_count=10,
            context_tokens=140000,
            next_needs_context=True,
            artifacts_sufficient=False,
            remainder_self_contained=True,
        )
        self.assertEqual(at_context_ceiling["phase_action"], "handoff")

        at_turn_ceiling = self.progress(
            issue=14,
            attempt=1,
            phase=6,
            now="2026-08-13T20:20:00Z",
            turn_count=118,
            context_tokens=20000,
            next_needs_context=True,
            artifacts_sufficient=False,
            remainder_self_contained=True,
        )
        self.assertEqual(at_turn_ceiling["phase_action"], "handoff")

    def test_durable_handoff_requires_safe_file_and_resumes_same_attempt(self):
        self.init_run()
        worktree = self.root / "wt-a"
        launched = self.launch(issue=14, owner="owner-a", worktree=worktree)
        decision = self.progress(turn_count=118, context_tokens=20000)
        self.assertEqual(
            (decision["phase_action"], decision["state"]), ("handoff", "active")
        )
        self.assertIsNone(decision["handoff_path"])

        nonexistent = self.workflows_dir / self.run_id / "handoffs" / "missing.md"
        before = self.state_path.read_bytes()
        rejected = self.progress(
            turn_count=118, context_tokens=20000, handoff_path=nonexistent, ok=False
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(self.state_path.read_bytes(), before)

        outside = self.root / "outside-handoff.md"
        outside.write_text("outside\n", encoding="utf-8")
        rejected = self.progress(
            turn_count=118, context_tokens=20000, handoff_path=outside, ok=False
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(self.state_path.read_bytes(), before)

        handoff_path = self.write_handoff(14)
        finalized = self.progress(
            turn_count=118, context_tokens=20000, handoff_path=handoff_path
        )
        self.assertEqual(finalized["state"], "handed_off")
        self.assertEqual(finalized["handoff_path"], str(handoff_path))

        wrong_path = str(handoff_path) + ".wrong"
        rejected = self.run_cli(
            "launch",
            "--repo-root",
            self.root,
            "--run-id",
            self.run_id,
            "--issue",
            14,
            "--owner",
            "owner-a",
            "--worktree",
            worktree,
            "--now",
            "2026-08-13T20:05:00Z",
            "--budget-minutes",
            30,
            "--resume-handoff",
            wrong_path,
            ok=False,
        )
        self.assertNotEqual(rejected.returncode, 0)

        resumed = self.run_cli(
            "launch",
            "--repo-root",
            self.root,
            "--run-id",
            self.run_id,
            "--issue",
            14,
            "--owner",
            "owner-a",
            "--worktree",
            worktree,
            "--now",
            "2026-08-13T20:05:00Z",
            "--budget-minutes",
            30,
            "--resume-handoff",
            handoff_path,
        )
        resumed = json.loads(resumed.stdout)
        self.assertEqual((resumed["attempt"], resumed["state"]), (1, "active"))
        self.assertEqual(resumed["deadline_at"], launched["deadline_at"])
        self.assertEqual(len(resumed["launches"]), 2)
        continued = self.progress(
            phase=2,
            now="2026-08-13T20:06:00Z",
            turn_count=10,
            context_tokens=20000,
        )
        self.assertEqual((continued["phase_action"], continued["state"]), ("continue", "active"))
        self.assertEqual(continued["handoff_path"], str(handoff_path))

    def test_late_handoff_resume_stops_and_permits_fresh_retry(self):
        self.init_run()
        worktree = self.root / "wt-a"
        self.launch(issue=14, owner="owner-a", worktree=worktree)
        handoff_path = self.write_handoff(14)
        self.progress(turn_count=118, context_tokens=20000, handoff_path=handoff_path)

        completed = self.run_cli(
            "launch",
            "--repo-root",
            self.root,
            "--run-id",
            self.run_id,
            "--issue",
            14,
            "--owner",
            "owner-a",
            "--worktree",
            worktree,
            "--now",
            "2026-08-13T20:31:00Z",
            "--budget-minutes",
            30,
            "--resume-handoff",
            handoff_path,
        )
        resumed = json.loads(completed.stdout)
        self.assertEqual((resumed["issue"], resumed["state"]), (14, "stopped"))
        self.assertIn(str(worktree.resolve()), resumed["notes"])
        persisted = self.read_state()["issues"]["14"]
        self.assertEqual(persisted["outcome"], resumed)
        self.assertEqual(persisted["attempts"][0]["state"], "stopped")
        self.assertEqual(len(persisted["attempts"][0]["launches"]), 1)

        retried = self.launch(
            issue=14,
            owner="owner-b",
            worktree=self.root / "wt-b",
            now="2026-08-13T20:32:00Z",
        )
        self.assertEqual((retried["attempt"], retried["prior_attempt"]), (2, 1))

    def test_reconcile_expires_unresumed_handoff_and_permits_fresh_retry(self):
        self.init_run()
        worktree = self.root / "wt-a"
        self.launch(issue=14, owner="owner-a", worktree=worktree)
        handoff_path = self.write_handoff(14)
        self.progress(turn_count=118, context_tokens=20000, handoff_path=handoff_path)

        reconciled = self.reconcile(now="2026-08-13T20:31:00Z")
        persisted = reconciled["issues"]["14"]
        attempt = persisted["attempts"][0]
        self.assertEqual((attempt["state"], persisted["outcome"]["state"]), ("stopped", "stopped"))
        self.assertEqual(attempt["handoff_path"], str(handoff_path))
        self.assertIn(str(worktree.resolve()), persisted["outcome"]["notes"])

        retried = self.launch(
            issue=14,
            owner="owner-b",
            worktree=self.root / "wt-b",
            now="2026-08-13T20:32:00Z",
        )
        self.assertEqual((retried["attempt"], retried["prior_attempt"]), (2, 1))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_handoff_symlink_escape_is_rejected_without_state_change(self):
        self.init_run()
        self.launch(issue=14, owner="owner-a", worktree=self.root / "wt-a")
        handoffs = self.workflows_dir / self.run_id / "handoffs"
        handoffs.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        external = outside / "handoff.md"
        external.write_text("external\n", encoding="utf-8")
        (handoffs / "escape").symlink_to(outside, target_is_directory=True)
        before = self.state_path.read_bytes()
        rejected = self.progress(
            turn_count=118,
            context_tokens=20000,
            handoff_path=handoffs / "escape" / "handoff.md",
            ok=False,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertEqual(external.read_text(encoding="utf-8"), "external\n")

    def test_progress_rejects_threshold_continue_invalid_inputs_and_transitions(self):
        self.init_run()
        self.launch(issue=14, owner="owner-a", worktree=self.root / "wt-a")
        at_turn_threshold = self.progress(turn_count=118, context_tokens=20000)
        self.assertEqual(at_turn_threshold["phase_action"], "handoff")
        at_context_threshold = self.progress(
            phase=2, turn_count=10, context_tokens=140000
        )
        self.assertEqual(at_context_threshold["phase_action"], "handoff")

        for args in (
            ("--next-needs-context", "yes"),
            ("--turn-count", "-1"),
            ("--turn-headroom", "120"),
        ):
            with self.subTest(args=args):
                command = [
                    "progress",
                    "--repo-root",
                    self.root,
                    "--run-id",
                    self.run_id,
                    "--issue",
                    14,
                    "--attempt",
                    1,
                    "--phase",
                    3,
                    "--now",
                    DEFAULT_NOW,
                    "--turn-ceiling",
                    120,
                    "--context-ceiling",
                    150000,
                    "--turn-headroom",
                    2,
                    "--context-headroom",
                    10000,
                    "--next-needs-context",
                    "true",
                    "--artifacts-sufficient",
                    "false",
                    "--remainder-self-contained",
                    "false",
                    *args,
                ]
                before = self.state_path.read_bytes()
                rejected = self.run_cli(*command, ok=False)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual(self.state_path.read_bytes(), before)

        backward = self.progress(phase=1, ok=False)
        self.assertNotEqual(backward.returncode, 0)
        terminal = self.finish(1, self.merged_result())
        self.assertEqual(terminal["state"], "merged")
        rejected = self.progress(phase=3, ok=False)
        self.assertNotEqual(rejected.returncode, 0)

    def test_combined_controller_demo_has_one_authoritative_outcome_per_issue(self):
        self.init_run()

        completed = self.launch(issue=14, owner="owner-a", worktree=self.root / "wt-a")
        durable_result = self.merged_result(14)
        self.finish(completed["attempt"], durable_result, issue=14)
        delayed_result = {
            **durable_result,
            "state": "failed",
            "pr_url": None,
            "merge_sha": None,
            "issue_closed": False,
            "notes": "delayed notification",
        }
        delayed = self.finish(1, delayed_result, issue=14, ok=False)
        self.assertNotEqual(delayed.returncode, 0)

        self.launch(
            issue=15,
            owner="silent-owner",
            worktree=self.root / "wt-15",
            budget_minutes=10,
        )
        self.reconcile(now="2026-08-13T20:10:00Z")

        self.launch(issue=16, owner="owner-c", worktree=self.root / "wt-16")
        decision = self.progress(
            issue=16,
            now="2026-08-13T20:05:00Z",
            turn_count=10,
            context_tokens=140000,
        )
        self.assertEqual(decision["phase_action"], "handoff")
        handoff_path = self.write_handoff(16)
        self.progress(
            issue=16,
            now="2026-08-13T20:05:00Z",
            turn_count=10,
            context_tokens=140000,
            handoff_path=handoff_path,
        )

        final_state = self.reconcile(now="2026-08-13T20:11:00Z")
        self.assertEqual(set(final_state["issues"]), {"14", "15", "16"})
        self.assertEqual(final_state["issues"]["14"]["outcome"], durable_result)
        self.assertEqual(final_state["issues"]["15"]["outcome"]["state"], "stopped")
        self.assertIsNone(final_state["issues"]["16"]["outcome"])
        self.assertEqual(
            final_state["issues"]["16"]["attempts"][-1]["state"], "handed_off"
        )
        for issue_state in final_state["issues"].values():
            self.assertLessEqual(len(issue_state["attempts"]), 2)
            self.assertTrue(
                all(attempt["attempt"] <= 2 for attempt in issue_state["attempts"])
            )
        resumable = Path(
            final_state["issues"]["16"]["attempts"][-1]["handoff_path"]
        )
        self.assertEqual(resumable, handoff_path)
        self.assertTrue(resumable.is_file())

    def test_matching_repeated_finish_is_idempotent(self):
        self.init_run()
        attempt = self.launch(
            issue=14, owner="owner-a", worktree=self.root / "wt-a"
        )["attempt"]
        result = self.merged_result()
        first = self.finish(attempt, result)
        before = self.state_path.read_bytes()
        repeated = self.finish(attempt, result, now="2026-08-13T20:05:00Z")
        self.assertEqual(repeated, first)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_conflicting_write_rejection_leaves_state_bytes_unchanged(self):
        self.init_run()
        attempt = self.launch(
            issue=14, owner="owner-a", worktree=self.root / "wt-a"
        )["attempt"]
        self.finish(attempt, self.merged_result())
        before = self.state_path.read_bytes()
        conflict = {
            **self.merged_result(),
            "state": "failed",
            "pr_url": None,
            "merge_sha": None,
            "issue_closed": False,
            "notes": "late conflicting result",
        }
        completed = self.finish(attempt, conflict, ok=False)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("conflicting terminal result", completed.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_terminal_resume_returns_stored_result_without_launching(self):
        self.init_run()
        worktree = self.root / "wt-a"
        attempt = self.launch(issue=14, owner="owner-a", worktree=worktree)["attempt"]
        result = self.merged_result()
        self.finish(attempt, result)
        before = self.state_path.read_bytes()
        resumed = self.launch(
            issue=14,
            owner="owner-a",
            worktree=worktree,
            now="2026-08-13T20:20:00Z",
        )
        self.assertEqual(resumed, result)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_invalid_schema_state_and_action_are_rejected_without_changes(self):
        corruptions = (
            ("schema", lambda state: state.__setitem__("schema_version", 99)),
            (
                "state",
                lambda state: state["issues"]["14"]["attempts"][0].__setitem__(
                    "state", "unknown"
                ),
            ),
            (
                "action",
                lambda state: state["issues"]["14"]["attempts"][0].__setitem__(
                    "phase_action", "unknown"
                ),
            ),
        )
        for label, corrupt in corruptions:
            with self.subTest(label=label):
                self.init_run()
                if label != "schema":
                    self.launch(
                        issue=14, owner="owner-a", worktree=self.root / "wt-a"
                    )
                state = self.read_state()
                corrupt(state)
                self.state_path.write_text(json.dumps(state), encoding="utf-8")
                before = self.state_path.read_bytes()
                completed = self.reconcile(ok=False)
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(self.state_path.read_bytes(), before)
                self.state_path.unlink()

    def test_cross_field_lifecycle_corruption_is_rejected_without_changes(self):
        terminal = self.merged_result()
        stopped = {
            **terminal,
            "state": "stopped",
            "pr_url": None,
            "merge_sha": None,
            "issue_closed": False,
            "notes": "stopped",
        }
        corruptions = (
            (
                "active-with-result",
                lambda attempt: attempt.__setitem__("result", terminal),
                None,
            ),
            (
                "terminal-without-result",
                lambda attempt: attempt.__setitem__("state", "merged"),
                None,
            ),
            (
                "terminal-state-mismatch",
                lambda attempt: attempt.update(
                    {"state": "failed", "result": terminal}
                ),
                None,
            ),
            (
                "launch-kind-mismatch",
                lambda attempt: attempt.__setitem__("launch_kind", "resume"),
                None,
            ),
            (
                "start-after-progress",
                lambda attempt: attempt.__setitem__(
                    "started_at", "2026-08-13T20:01:00Z"
                ),
                None,
            ),
            (
                "progress-after-deadline",
                lambda attempt: attempt.__setitem__(
                    "last_progress_at", "2026-08-13T20:31:00Z"
                ),
                None,
            ),
            (
                "launch-before-start",
                lambda attempt: attempt["launches"][0].__setitem__(
                    "at", "2026-08-13T19:59:00Z"
                ),
                None,
            ),
            (
                "launch-after-deadline",
                lambda attempt: attempt["launches"][0].__setitem__(
                    "at", "2026-08-13T20:31:00Z"
                ),
                None,
            ),
            (
                "terminal-without-finished-at",
                lambda attempt: attempt.update(
                    {
                        "state": "merged",
                        "result": terminal,
                        "finished_at": None,
                        "result_source": "owner",
                    }
                ),
                "must all be null or all be set",
            ),
            (
                "nonterminal-with-result-source",
                lambda attempt: attempt.__setitem__("result_source", "owner"),
                "must all be null or all be set",
            ),
            (
                "unknown-result-source",
                lambda attempt: attempt.update(
                    {
                        "state": "merged",
                        "result": terminal,
                        "finished_at": "2026-08-13T20:05:00Z",
                        "result_source": "reaper",
                    }
                ),
                "invalid attempt result source",
            ),
            (
                "finished-at-before-start",
                lambda attempt: attempt.update(
                    {
                        "state": "merged",
                        "result": terminal,
                        "finished_at": "2026-08-13T19:59:59Z",
                        "result_source": "owner",
                    }
                ),
                "invalid attempt finish time order",
            ),
            (
                "expiry-finished-before-deadline",
                lambda attempt: attempt.update(
                    {
                        "state": "stopped",
                        "result": stopped,
                        "finished_at": "2026-08-13T20:29:59Z",
                        "result_source": "expiry",
                    }
                ),
                "expiry finish time must not precede the attempt deadline",
            ),
        )
        for label, corrupt, message in corruptions:
            with self.subTest(label=label):
                self.init_run()
                self.launch(issue=14, owner="owner-a", worktree=self.root / "wt-a")
                state = self.read_state()
                attempt = state["issues"]["14"]["attempts"][0]
                corrupt(attempt)
                self.state_path.write_text(json.dumps(state), encoding="utf-8")
                before = self.state_path.read_bytes()
                completed = self.reconcile(ok=False)
                self.assertNotEqual(completed.returncode, 0)
                if message is not None:
                    self.assertIn(message, completed.stderr)
                self.assertEqual(self.state_path.read_bytes(), before)
                self.state_path.unlink()

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_repository_path_escapes_are_rejected_before_external_mutation(self):
        outside_temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(outside_temporary_directory.cleanup)
        outside = Path(outside_temporary_directory.name)

        missing_root = self.root / "missing-repository"
        missing = self.run_cli(
            "init-run",
            "--repo-root",
            missing_root,
            "--run-id",
            self.run_id,
            "--now",
            DEFAULT_NOW,
            ok=False,
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertFalse(missing_root.exists())

        symlink_root = self.root / "symlink-root"
        symlink_root.mkdir()
        (symlink_root / ".superpowers").symlink_to(
            outside, target_is_directory=True
        )
        escaped = self.run_cli(
            "init-run",
            "--repo-root",
            symlink_root,
            "--run-id",
            self.run_id,
            "--now",
            DEFAULT_NOW,
            ok=False,
        )
        self.assertNotEqual(escaped.returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlinked_stable_lock_and_state_are_rejected_without_external_mutation(self):
        outside_temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(outside_temporary_directory.cleanup)
        outside = Path(outside_temporary_directory.name)

        for stable_name in ("state.lock", "state.json"):
            with self.subTest(stable_name=stable_name):
                run_id = f"stable-{stable_name.replace('.', '-')}"
                self.run_cli(
                    "init-run",
                    "--repo-root",
                    self.root,
                    "--run-id",
                    run_id,
                    "--now",
                    DEFAULT_NOW,
                )
                run_dir = self.workflows_dir / run_id
                stable_path = run_dir / stable_name
                external_path = outside / stable_name
                if stable_name == "state.json":
                    external_path.write_bytes(stable_path.read_bytes())
                else:
                    external_path.write_bytes(b"external lock sentinel")
                before = external_path.read_bytes()
                stable_path.unlink()
                stable_path.symlink_to(external_path)

                rejected = self.run_cli(
                    "reconcile",
                    "--repo-root",
                    self.root,
                    "--run-id",
                    run_id,
                    "--now",
                    DEFAULT_NOW,
                    ok=False,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual(external_path.read_bytes(), before)

    def test_result_schema_note_length_and_nullable_url_sha_validation(self):
        self.init_run()
        attempt = self.launch(
            issue=14, owner="owner-a", worktree=self.root / "wt-a"
        )["attempt"]
        invalid_results = (
            {**self.merged_result(), "extra": "field"},
            {key: value for key, value in self.merged_result().items() if key != "notes"},
            {**self.merged_result(), "state": "active"},
            {**self.merged_result(), "notes": "x" * 501},
            {**self.merged_result(), "pr_url": 15},
            {**self.merged_result(), "merge_sha": False},
            {**self.merged_result(), "issue_closed": 1},
            {**self.merged_result(), "discussion_items": "none"},
            {**self.merged_result(), "issue": 15},
        )
        for index, result in enumerate(invalid_results):
            with self.subTest(index=index):
                before = self.state_path.read_bytes()
                completed = self.finish(attempt, result, ok=False)
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(self.state_path.read_bytes(), before)

        nullable = {
            **self.merged_result(),
            "state": "stopped",
            "pr_url": None,
            "merge_sha": None,
            "issue_closed": False,
            "notes": "stopped cleanly",
        }
        normalized = self.finish(attempt, nullable)
        self.assertEqual(
            {key: normalized[key] for key in nullable if key != "notes"},
            {key: nullable[key] for key in nullable if key != "notes"},
        )
        self.assertIn(nullable["notes"], normalized["notes"])
        self.assertIn(str((self.root / "wt-a").resolve()), normalized["notes"])
        self.assertLessEqual(len(normalized["notes"]), 500)

    def test_workflows_gitignore_contains_wildcard(self):
        self.init_run()
        self.assertEqual(
            (self.workflows_dir / ".gitignore").read_text(encoding="utf-8"), "*\n"
        )

    def test_invalid_time_run_id_and_identity_are_rejected(self):
        invalid_init_args = (
            ("--run-id", "../escape", "--now", DEFAULT_NOW),
            ("--run-id", self.run_id, "--now", "2026-08-13T20:00:00"),
            ("--run-id", self.run_id, "--now", "2026-08-13T21:00:00+01:00"),
        )
        for args in invalid_init_args:
            with self.subTest(args=args):
                completed = self.run_cli(
                    "init-run", "--repo-root", self.root, *args, ok=False
                )
                self.assertNotEqual(completed.returncode, 0)

        self.init_run()
        before = self.state_path.read_bytes()
        completed = self.run_cli(
            "finish",
            "--repo-root",
            self.root,
            "--run-id",
            self.run_id,
            "--issue",
            14,
            "--attempt",
            1,
            "--result-file",
            self.root / "missing.json",
            "--now",
            DEFAULT_NOW,
            ok=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(self.state_path.read_bytes(), before)

    @unittest.skipUnless(hasattr(os, "pipe") and os.name == "posix", "POSIX barrier")
    def test_concurrent_launches_for_distinct_issues_preserve_both_updates(self):
        self.init_run()
        wrapper = (
            "import os,sys; "
            "fd=int(sys.argv[1]); script=sys.argv[2]; args=sys.argv[3:]; "
            "os.read(fd,1); os.execv(sys.executable,[sys.executable,script,*args])"
        )
        processes = []
        write_fds = []
        for issue in (14, 15):
            read_fd, write_fd = os.pipe()
            args = [
                "launch",
                "--repo-root",
                str(self.root),
                "--run-id",
                self.run_id,
                "--issue",
                str(issue),
                "--owner",
                f"owner-{issue}",
                "--worktree",
                str(self.root / f"wt-{issue}"),
                "--now",
                DEFAULT_NOW,
                "--budget-minutes",
                "30",
            ]
            process = subprocess.Popen(
                [sys.executable, "-c", wrapper, str(read_fd), str(SCRIPT), *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                pass_fds=(read_fd,),
            )
            os.close(read_fd)
            processes.append(process)
            write_fds.append(write_fd)

        for write_fd in write_fds:
            os.write(write_fd, b"x")
            os.close(write_fd)

        for process in processes:
            stdout, stderr = process.communicate()
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(json.loads(stdout)["attempt"], 1)

        reopened = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(set(reopened["issues"]), {"14", "15"})
        for issue in (14, 15):
            attempt = reopened["issues"][str(issue)]["attempts"][0]
            self.assertEqual(attempt["issue"], issue)
            self.assertEqual(len(attempt["launches"]), 1)


if __name__ == "__main__":
    unittest.main()
