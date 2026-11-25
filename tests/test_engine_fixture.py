"""Contract tests for the engine's fixture project: it is built locally and adopted with the adoption command."""

from __future__ import annotations

import ast
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.project_contract import resolve_project
from tests.engine_fixture import AdoptedFixtures, FixtureProject
from tests.guard_policy_world import GuardPolicyWorld, install_platform_manifest_in_environ

TIER = "integration"  # every case builds a repository and runs the adoption command

setUpModule = install_platform_manifest_in_environ


class FixtureTest(unittest.TestCase):
    def test_the_adoption_commits_on_a_host_that_guesses_no_git_identity(self):
        # A CI runner resolves no author from its account: git is told to take one from config only.
        refusing = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "user.useConfigOnly",
                    "GIT_CONFIG_VALUE_0": "true"}
        with mock.patch.dict("os.environ", refusing):
            world = GuardPolicyWorld(self)
            fixture = FixtureProject(self, world)

        self.assertRegex(fixture.adoption["commit"], r"^[0-9a-f]{40}$")

    def test_the_fixture_is_adopted_by_the_adoption_command_and_declares_its_checks(self):
        world = GuardPolicyWorld(self)

        fixture = FixtureProject(self, world)
        snapshot = resolve_project.resolve(str(fixture.root))

        self.assertEqual(snapshot["bindings"]["workflow"]["verification"], ["lint", "test"])
        self.assertIsNone(snapshot["bindings"]["workflow"].get("verification_before_pull_request"))
        self.assertEqual(snapshot["bindings"]["vcs"]["merge"]["required_checks"],
                         FixtureProject.REQUIRED_CHECKS)
        self.assertEqual(snapshot["project"]["id"], "example/fixture")
        for capability in ("review.code", "review.plan"):
            self.assertNotEqual(snapshot["capabilities"][capability]["state"], "blocked")
        # A publication-free release holds no host adapter, so the adoption's capability gate
        # passes on a Linux runner that has no codesign, security or launchctl.
        self.assertEqual(snapshot["capabilities"]["release"]["state"], "unsupported")
        self.assertEqual(world.git(fixture.root, "rev-parse", "main"),
                         world.git(fixture.root, "rev-parse", "origin/main"))
        subprocess.run(["git", "-C", str(fixture.root), "merge-base", "--is-ancestor",
                        fixture.adoption["commit"], "main"], check=True, timeout=60)

    def test_the_fixtures_verification_commands_pass_in_its_checkout(self):
        world = GuardPolicyWorld(self)
        fixture = FixtureProject(self, world)
        snapshot = resolve_project.resolve(str(fixture.root))

        for command_id in ("lint", "test"):
            with self.subTest(command=command_id):
                command = snapshot["bindings"]["commands"][command_id]
                done = subprocess.run(command["argv"], cwd=fixture.root / command["cwd"],
                                      capture_output=True, text=True, timeout=120)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_building_the_fixture_registers_no_project(self):
        world = GuardPolicyWorld(self)

        with mock.patch.object(GuardPolicyWorld, "register",
                               side_effect=AssertionError("registered")):
            FixtureProject(self, world)

        self.assertFalse((world.home / ".agents/state/fleet/registry.json").exists())


class AdoptedFixturesTest(unittest.TestCase):
    def fixtures(self) -> AdoptedFixtures:
        fixtures = AdoptedFixtures()
        self.addCleanup(fixtures.close)
        return fixtures

    def test_a_second_fixture_of_one_variant_is_copied_and_not_adopted_again(self):
        fixtures = self.fixtures()
        first = fixtures.project(self, GuardPolicyWorld(self))

        with mock.patch.object(FixtureProject, "_adopt", side_effect=AssertionError("adopted again")):
            second = fixtures.project(self, GuardPolicyWorld(self))
        snapshot = resolve_project.resolve(str(second.root))

        self.assertNotEqual(second.root, first.root)
        self.assertEqual(snapshot["project"]["id"], "example/fixture")
        self.assertEqual(snapshot["bindings"]["vcs"]["merge"]["required_checks"],
                         FixtureProject.REQUIRED_CHECKS)
        self.assertEqual(second.adoption, first.adoption)
        self.assertEqual(second.world.git(second.root, "rev-parse", "main").strip(),
                         first.adoption["commit"])

    @staticmethod
    def conditions() -> dict:
        return {"lint": {"when_changed": ["a"], "skip_reason": "nothing to lint"}}

    def test_a_test_that_changes_the_fixture_it_got_does_not_change_the_fixtures_copied_later(self):
        fixtures = self.fixtures()
        first = fixtures.project(self, GuardPolicyWorld(self), conditions=self.conditions())
        first.adoption["commit"] = "0" * 40
        first.conditions["lint"]["when_changed"].append("b")

        second = fixtures.project(self, GuardPolicyWorld(self), conditions=self.conditions())
        second.adoption["commit"] = "1" * 40
        third = fixtures.project(self, GuardPolicyWorld(self), conditions=self.conditions())

        self.assertEqual(third.adoption["commit"], third.world.git(third.root, "rev-parse", "main").strip())
        self.assertEqual(third.conditions, self.conditions())

    def test_a_copy_starts_clean_at_the_adoption_commit_on_its_own_origin(self):
        fixtures = self.fixtures()
        first = fixtures.project(self, GuardPolicyWorld(self))
        (first.root / "moved.txt").write_text("moved\n", encoding="utf-8")
        first.world.git(first.root, "add", "moved.txt")
        first.world.git(first.root, "commit", "--quiet", "-m", "moved")
        first.world.git(first.root, "push", "--quiet", "origin", "main")

        world = GuardPolicyWorld(self)
        second = fixtures.project(self, world)
        origin = Path(world.git(second.root, "remote", "get-url", "origin").strip())

        self.assertEqual(world.git(second.root, "rev-parse", "main").strip(), first.adoption["commit"])
        self.assertEqual(world.git(second.root, "status", "--porcelain"), "")
        self.assertFalse((second.root / "moved.txt").exists())
        self.assertTrue(origin.is_relative_to(world.tmp))
        self.assertEqual(world.git(second.root, "--git-dir", str(origin), "rev-parse", "main").strip(),
                         first.adoption["commit"])

    def test_fixtures_of_different_options_are_adopted_apart(self):
        fixtures = self.fixtures()
        fixtures.project(self, GuardPolicyWorld(self))

        bare = fixtures.project(self, GuardPolicyWorld(self), required_checks=())
        again = fixtures.project(self, GuardPolicyWorld(self))

        self.assertNotIn("required_checks",
                         resolve_project.resolve(str(bare.root))["bindings"]["vcs"]["merge"])
        self.assertEqual(resolve_project.resolve(str(again.root))["bindings"]["vcs"]["merge"]["required_checks"],
                         FixtureProject.REQUIRED_CHECKS)
        self.assertEqual(bare.required_checks, [])

    def test_closing_the_fixtures_leaves_no_copy_behind(self):
        fixtures = self.fixtures()
        fixtures.project(self, GuardPolicyWorld(self))
        directory = fixtures.directory
        self.assertTrue(directory.is_dir())

        fixtures.close()
        fixtures.close()

        self.assertFalse(directory.exists())
        self.assertIsNone(fixtures.directory)


class EntryPointTest(unittest.TestCase):
    def test_the_direct_run_entry_point_follows_every_test_class(self):
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))

        last = tree.body[-1]

        self.assertIsInstance(last, ast.If)
        self.assertEqual(ast.unparse(last.test), "__name__ == '__main__'")


if __name__ == "__main__":
    unittest.main()
