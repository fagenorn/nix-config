"""The console's user service on each host as the configuration evaluates it (issue 856).

Evaluates the flake from this checkout's git tree, so new files must be `git add`-ed first.
Run: just agent-workflow-tests
"""
import re
import unittest

from agent_tools.console import service

from . import test_verify_pending_units as units

PORT = 27184
LAUNCHER = re.compile(r"^/nix/store/[0-9a-z]{32}-agent-tools-console$")


def check_command(case, command):
    words = command.split(" ")
    case.assertEqual(len(words), 3, command)
    case.assertRegex(words[0], LAUNCHER)
    case.assertEqual(words[1:], ["--port", str(PORT)])


class LinuxUnit(unittest.TestCase):
    HOST = "anis-desktop"
    APPLY = """c: u: {
      command = u.agentConsole.command;
      path = u.agentConsole.path;
      gh = "${u.programs.gh.package}";
      service = u.systemd.user.services.agent-console;
    }"""

    @classmethod
    def setUpClass(cls):
        cls.got = units.evaluate(f"nixosConfigurations.{cls.HOST}", cls.APPLY)

    def test_the_port_is_the_consoles_fixed_port(self):
        self.assertEqual(PORT, service.DEFAULT_PORT)
        check_command(self, self.got["command"])

    def test_the_service_runs_the_console_command_and_restarts_it_on_exit(self):
        # home-manager 25.11 normalizes ExecStart and Environment to lists.
        self.assertEqual(self.got["service"]["Service"], {
            "ExecStart": [self.got["command"]],
            "Environment": [f"PATH={self.got['path']}"],
            "Restart": "always",
        })

    def test_the_service_starts_with_the_users_session(self):
        self.assertEqual(self.got["service"]["Install"]["WantedBy"], ["default.target"])
        description = self.got["service"]["Unit"]["Description"]
        self.assertIsInstance(description, str)
        self.assertTrue(description.strip())

    def test_the_service_path_finds_gh_for_the_tracker(self):
        self.assertRegex(self.got["gh"], r"^/nix/store/[0-9a-z]{32}-gh-")
        self.assertEqual(self.got["path"], f"{self.got['gh']}/bin:/usr/bin:/bin")


if __name__ == "__main__":
    unittest.main()
