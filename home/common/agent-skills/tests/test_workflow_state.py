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
