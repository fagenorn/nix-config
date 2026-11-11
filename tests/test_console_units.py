"""The console's user service on each host as the configuration evaluates it (issue 856).

Evaluates the flake from this checkout's git tree, so new files must be `git add`-ed first.
Run: just agent-workflow-tests
"""
import plistlib
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


class DarwinAgent(unittest.TestCase):
    HOSTS = units.DarwinHosts.HOSTS
    LABEL = "org.nixos.agent-console"
    # pure: the required CI job runs on Linux, where only a pure evaluation works.
    APPLY = """c: u: {
      command = u.agentConsole.command;
      path = u.agentConsole.path;
      home = u.home.homeDirectory;
      agentCommand = c.launchd.user.agents.agent-console.command;
      homeAgent = u.launchd.agents ? agent-console;
      plist = c.environment.userLaunchAgents."org.nixos.agent-console.plist".text;
    }"""

    @classmethod
    def setUpClass(cls):
        cls.got = {host: units.evaluate(f"darwinConfigurations.{host}", cls.APPLY, pure=True)
                   for host in cls.HOSTS}
        cls.plist = {host: plistlib.loads(cls.got[host]["plist"].encode()) for host in cls.HOSTS}

    def hosts(self):
        for host in self.HOSTS:
            with self.subTest(host=host):
                yield self.got[host], self.plist[host]

    def test_the_agent_runs_the_console_command_after_the_nix_volume_is_mounted(self):
        for got, plist in self.hosts():
            command = got["command"]
            check_command(self, command)
            self.assertEqual(got["agentCommand"], command)
            self.assertEqual(plist["ProgramArguments"],
                             ["/bin/sh", "-c", f"/bin/wait4path /nix/store && exec {command}"])
            self.assertNotIn("Program", plist)

    def test_the_agent_starts_at_login_and_is_restarted_on_exit(self):
        for _, plist in self.hosts():
            self.assertEqual(plist["Label"], self.LABEL)
            self.assertIs(plist["RunAtLoad"], True)
            self.assertIs(plist["KeepAlive"], True)

    def test_the_agent_finds_gh_and_home(self):
        for got, plist in self.hosts():
            self.assertEqual(plist["EnvironmentVariables"], {"PATH": got["path"], "HOME": got["home"]})

    def test_the_agent_logs_to_one_file_and_has_no_other_keys(self):
        for got, plist in self.hosts():
            log = f"{got['home']}/Library/Logs/agent-console.log"
            self.assertEqual(plist["StandardOutPath"], log)
            self.assertEqual(plist["StandardErrorPath"], log)
            self.assertEqual(set(plist), {"Label", "ProgramArguments", "RunAtLoad", "KeepAlive",
                                          "EnvironmentVariables", "StandardOutPath", "StandardErrorPath"})

    def test_home_manager_declares_no_second_console_agent(self):
        for got, _ in self.hosts():
            self.assertIs(got["homeAgent"], False)


if __name__ == "__main__":
    unittest.main()
