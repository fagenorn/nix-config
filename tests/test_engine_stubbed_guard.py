"""The stubbed world's pull-request forge and the real guard on the fixture's confirmed row.

The cases ran in tests/test_engine_stubbed_run.py; they live here to keep that module under the size budget
(rule B17). They run no `deliver` procedure, so the module's coverage scope is empty and its runs take their
fixtures from its own `FIXTURES`.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest

from agent_tools.project_contract import resolve_project
from tests.engine_fixture import AdoptedFixtures
from tests.engine_guards import payloads
from tests.engine_procedure_copies import PROCEDURES
from tests.engine_step_coverage import StepCoverage
from tests.engine_stubbed_world import StubbedRun
from tests.guard_policy_world import install_platform_manifest_in_environ
from tests.test_engine_stubbed_run import Scenario

TIER = "integration"  # every case builds a repository and runs the real guard and the fake forge as child processes

FIXTURES = AdoptedFixtures()
STEPS = StepCoverage(PROCEDURES, ())


def setUpModule() -> None:
    install_platform_manifest_in_environ()
    unittest.addModuleCleanup(FIXTURES.close)


def tearDownModule() -> None:
    STEPS.finish(sys.modules[__name__], Scenario)


class GuardWorldTest(Scenario):
    """The stubbed world's pull-request forge and the real guard on the fixture's confirmed row."""

    BRANCH = "issue-41-add-a-greeting"

    def pushed(self, run: StubbedRun, branch: str | None = None) -> str:
        """Commit one file on a new branch of the fixture, push it to the bare origin, return its tip."""
        branch = branch or self.BRANCH
        root = run.fixture.root
        git = run.world.git
        git(root, "switch", "--quiet", "-c", branch)
        (root / f"{branch}.txt").write_text("a greeting\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "--quiet", "-m", f"Work on {branch}")
        git(root, "switch", "--quiet", "main")
        git(root, "push", "--quiet", "origin", branch)
        return run.origin_tip(branch)

    def gh(self, run: StubbedRun, *argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(["gh", *argv], cwd=run.fixture.root, env=run.env, capture_output=True,
                              text=True, timeout=120)

    def create(self, run: StubbedRun, branch: str | None = None) -> subprocess.CompletedProcess:
        return self.gh(run, "pr", "create", "--repo", "example/fixture", "--base", "main", "--head",
                       branch or self.BRANCH, "--title", "Add a greeting", "--body", "Closes #41.")

    def merge_text(self, head: str, number: int = 1) -> str:
        return (f"gh pr merge {number} --repo example/fixture --merge --match-head-commit {head} "
                f"--delete-branch")

    def view(self, run: StubbedRun) -> dict:
        done = self.gh(run, "pr", "view", "1", "--repo", "example/fixture", "--json",
                       "headRefOid,statusCheckRollup")
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_the_real_guard_of_the_stubbed_world_allows_the_fixtures_push_creation_and_pinned_merge(self):
        run = self.stubbed()
        head = self.pushed(run)
        self.pushed(run, "issue-41-second")
        created = self.create(run)
        self.assertEqual(created.returncode, 0, created.stderr)
        root = run.fixture.root
        texts = [
            f"git -C {root} push origin {self.BRANCH}",
            "gh pr create --repo example/fixture --base main --head issue-41-second "
            '--title "Add a greeting" --body "Closes #41. Delivered by the engine."',
            self.merge_text(head),
        ]

        for text in texts:
            with self.subTest(text):
                done = run.guard(text, root)
                self.assertEqual(done.returncode, 0, done.stderr)

        self.assertEqual([line["payload"]["tool_input"]["command"] for line in payloads(run.guard_log)],
                         texts)

    def test_a_run_without_required_checks_resolves_with_the_member_absent(self):
        run = self.stubbed(required_checks=())

        snapshot = resolve_project.resolve(run.fixture.root)

        self.assertNotIn("required_checks", snapshot["bindings"]["vcs"]["merge"])

    def test_without_declared_required_checks_the_real_guard_refuses_the_merge(self):
        run = self.stubbed(required_checks=())
        head = self.pushed(run)
        self.assertEqual(self.create(run).returncode, 0)

        done = run.guard(self.merge_text(head), run.fixture.root)

        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("protection lookup failed", done.stderr)

    def test_the_fake_merge_lands_only_the_pinned_head_and_deletes_the_branch(self):
        run = self.stubbed()
        head = self.pushed(run)
        self.assertEqual(self.create(run).returncode, 0)
        args = ("pr", "merge", "1", "--repo", "example/fixture", "--merge", "--delete-branch",
                "--match-head-commit")

        wrong = self.gh(run, *args, "0" * 40)
        self.assertEqual(wrong.returncode, 1, wrong.stderr)
        self.assertEqual(run.pulls()[0]["state"], "OPEN")
        right = self.gh(run, *args, head)

        self.assertEqual(right.returncode, 0, right.stderr)
        self.assertEqual(run.pulls()[0]["state"], "MERGED")
        merge = run.origin_tip("main")
        parents = run.world.git(run.fixture.root, "--git-dir", run.bare, "log", "-1",
                                "--format=%P", merge).split()
        self.assertEqual(parents[1], head)
        self.assertEqual(len(parents), 2)
        self.assertIsNone(run.origin_tip(self.BRANCH))

    def test_a_move_head_event_moves_the_branch_on_the_first_rollup_read(self):
        run = self.stubbed(forge_events=("move-head",))
        head = self.pushed(run)
        self.assertEqual(self.create(run).returncode, 0)

        first = self.view(run)
        moved = run.origin_tip(self.BRANCH)
        second = self.view(run)

        self.assertEqual(first["headRefOid"], head)
        self.assertEqual(first["statusCheckRollup"][0]["name"], "Fixture Checks")
        self.assertNotEqual(moved, head)
        self.assertEqual(second["headRefOid"], moved)
        self.assertEqual(run.origin_tip(self.BRANCH), moved)

    def test_a_steal_lock_event_hands_the_lock_to_a_second_open_pull_request(self):
        run = self.stubbed(forge_events=("steal-lock",))
        self.pushed(run)
        self.assertEqual(self.create(run).returncode, 0)

        self.view(run)

        self.assertEqual(run.lock_refs(), {"refs/agent-locks/land/main": run.stolen_sha})
        done = self.gh(run, "api", f"repos/example/fixture/commits/{run.stolen_sha}/pulls?per_page=100")
        self.assertEqual(done.returncode, 0, done.stderr)
        listed = json.loads(done.stdout)
        self.assertEqual([(p["state"], p["number"] != 1) for p in listed], [("open", True)])


if __name__ == "__main__":
    unittest.main()
