"""Contract tests for the engine's fixture project: it is built locally and adopted with the adoption command."""

from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from agent_tools.project_contract import resolve_project
from tests.engine_fixture import FixtureProject
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


if __name__ == "__main__":
    unittest.main()
