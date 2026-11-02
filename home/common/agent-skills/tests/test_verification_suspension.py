"""Ledger schema 11 and shared verification blockers (issue 544), through the CLI from source.

Run: just agent-workflow-tests
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .test_workflow_state import LifecycleHarness

# The delivery base: the schema-10 helper this change must not be read by (issue 544 D9).
BASE_COMMIT = "87d6065fc1749c0b7b6c427beb9b1d3051bc198d"
REPO = Path(__file__).resolve().parents[4]
HELPER = Path("home/common/agent-skills/scripts/workflow-state.py")
T = "2026-08-13T20:{:02d}:00Z".format


class LedgerHarness(LifecycleHarness):
    """Orchestrated attempts in a temporary ledger root, and the ledger at older schemas."""

    def worktree(self, issue):
        return str((self.root / f"wt-{issue}").resolve())

    def spawn_all(self, *issues):
        self.init_run()
        for issue in issues:
            self.spawn(issue=issue, worktree=self.worktree(issue))

    def migrate(self, *flags):
        completed = self.run_cli("migrate", "--repo-root", self.root, *flags)
        return json.loads(completed.stdout)["ledgers"]

    def assert_locked_refusal(self, state, line):
        """`state`, written as the ledger, is refused by a locked read with `line`; nothing
        under `.superpowers` changes."""
        self.write_state(state)
        before = self.tree_snapshot()
        done = self.run_cli("init-run", "--repo-root", self.root, "--run-id", self.run_id,
                            ok=False)
        self.assertEqual((done.returncode, done.stdout, done.stderr),
                         (2, "", f"workflow-state: {line}\n"))
        self.assertEqual(self.tree_snapshot(), before)


class SchemaElevenTest(LedgerHarness, unittest.TestCase):
    def test_a_new_ledger_is_schema_eleven_with_no_blockers(self):
        self.spawn_all(61)
        state = self.read_state()
        self.assertEqual((state["schema_version"], state["verification_blockers"]), (11, {}))
        self.assertIsNone(state["issues"]["61"]["attempts"][0]["verification_blocker"])

    def test_a_schema_ten_ledger_migrates_strictly(self):
        self.spawn_all(61)
        current = self.read_state()
        self.write_state(self._as_legacy(current, 10))
        before = self.tree_snapshot()
        self.assertEqual([(row["schema_version"], row["verdict"]) for row in self.migrate()],
                         [(10, "migrate")])
        self.assertEqual(self.tree_snapshot(), before)
        self.assertEqual([(row["schema_version"], row["verdict"])
                          for row in self.migrate("--apply")], [(11, "migrated")])
        self.assertEqual(self.read_state(), current)
        self.assertEqual([row["verdict"] for row in self.migrate()], ["current"])

    def test_a_schema_ten_ledger_holding_a_new_member_is_refused_unchanged(self):
        self.spawn_all(61)
        ten = self._as_legacy(self.read_state(), 10)
        pointed = json.loads(json.dumps(ten))
        pointed["issues"]["61"]["attempts"][0]["verification_blocker"] = None
        for label, document in (("blocker map", {**ten, "verification_blockers": {}}),
                                ("attempt pointer", pointed)):
            with self.subTest(member=label):
                self.write_state(document)
                before = self.tree_snapshot()
                (row,) = self.migrate("--apply")
                self.assertEqual((row["verdict"], row["reason"]), ("refused", "invalid_state"))
                done = self.run_cli("init-run", "--repo-root", self.root, "--run-id",
                                    self.run_id, ok=False)
                self.assertEqual(done.returncode, 2, done.stdout)
                self.assertIn("invalid_state", done.stderr)
                self.assertEqual(self.tree_snapshot(), before)


class PointerRuleTest(LedgerHarness, unittest.TestCase):
    """A pointer outside a verification suspension is refused, unchanged (issue 544 D5, D19)."""

    def test_a_pointer_outside_a_verification_suspension_is_refused(self):
        self.spawn_all(61, 62)
        self.suspend(issue=62, attempt=1, blocked_on="transport", now=T(5))
        good = self.read_state()
        for issue, label in ((61, "active"), (62, "suspended on transport")):
            with self.subTest(attempt=label):
                state = json.loads(json.dumps(good))
                state["issues"][str(issue)]["attempts"][0]["verification_blocker"] = (
                    "sha256:" + "0" * 64)
                self.assert_locked_refusal(state, "invalid attempt verification blocker")


class HelperGenerationTest(LedgerHarness, unittest.TestCase):
    """A helper older than the ledger's schema refuses it and writes nothing (#337 D10)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        found = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e",
                                f"{BASE_COMMIT}^{{commit}}"], capture_output=True)
        if found.returncode != 0:
            raise AssertionError(f"base commit {BASE_COMMIT} is missing; fetch it, do not skip")
        cls.base = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, cls.base, True)
        archive = subprocess.run(
            ["git", "-C", str(REPO), "archive", BASE_COMMIT, "python/agent_tools",
             str(HELPER.parent), "home/common/agent-skills/artifact-budget-policy.json"],
            capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(cls.base)], input=archive.stdout, check=True)

    def helper(self, generation, *argv):
        if generation == "head":
            return self.run_cli(*argv, ok=False)
        return subprocess.run(
            [sys.executable, str(self.base / HELPER), *map(str, argv)], capture_output=True,
            text=True, cwd=self.base, timeout=300,
            env={**self.cli_env, "PYTHONPATH": str(self.base / "python"),
                 "PYTHONDONTWRITEBYTECODE": "1"})

    def assert_refused_unchanged(self, generation):
        """Every ledger-reading command refuses `unknown_schema`; migrate reports it as a row."""
        control = self.root / "control-request.json"
        control.write_text(json.dumps(self.control_request(
            now=T(6), issues=[61], tracker=[self.tracker_fact(61)], worktrees=[])), "utf-8")
        direct = self.root / "direct-request.json"
        direct.write_text(json.dumps(self.direct_request(issue=61, now=T(6))), "utf-8")
        run = ("--repo-root", self.root, "--run-id", self.run_id)
        calls = {
            "check-launch": ("check-launch", *run, "--action-id", "61:1:1"),
            "suspend": ("suspend", *run, "--blocked-on", "transport", "--now", T(6),
                        "--action-id", "61:1:1"),
            "control": ("control", *run, "--request-file", control),
            "init-run": ("init-run", "--repo-root", self.root, "--run-id", self.run_id),
            "direct-owner": ("direct-owner", "--repo-root", self.root, "--request-file", direct),
            "migrate": ("migrate", "--repo-root", self.root),
            "migrate --apply": ("migrate", "--repo-root", self.root, "--apply"),
        }
        before = self.tree_snapshot()
        for name, argv in calls.items():
            with self.subTest(generation=generation, command=name):
                done = self.helper(generation, *argv)
                if name.startswith("migrate"):
                    (row,) = json.loads(done.stdout)["ledgers"]
                    self.assertEqual((done.returncode, row["verdict"], row["reason"]),
                                     (0, "refused", "unknown_schema"))
                else:
                    self.assertEqual(done.returncode, 2, done.stdout)
                    self.assertIn("unknown_schema", done.stderr)
                self.assertEqual(self.tree_snapshot(), before)

    def test_the_base_helper_refuses_a_schema_eleven_ledger(self):
        self.spawn_all(61)
        current = self.read_state()
        self.write_state(self._as_legacy(current, 10))
        before = self.tree_snapshot()
        done = self.helper("base", "migrate", "--repo-root", self.root)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([row["verdict"] for row in json.loads(done.stdout)["ledgers"]],
                         ["current"])
        self.assertEqual(self.tree_snapshot(), before)
        self.write_state(current)
        self.assert_refused_unchanged("base")

    def test_the_head_helper_refuses_schema_twelve(self):
        self.spawn_all(61)
        self.write_state({**self.read_state(), "schema_version": 12})
        self.assert_refused_unchanged("head")


if __name__ == "__main__":
    unittest.main()
