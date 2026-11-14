"""The console's user service on each host as the configuration evaluates it (issue 856).

Evaluates the flake from this checkout's git tree, so new files must be `git add`-ed first.
Run: just agent-workflow-tests
"""
import plistlib
import re
import unittest

from agent_tools.console import manager, service

from . import test_verify_pending_units as units
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

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
      profile = u.home.profileDirectory;
      system = map (p: p.pname or (builtins.parseDrvName p.name).name) c.environment.systemPackages;
      homePackages = map (p: p.name) u.home.packages;
      claude = u.programs.claude-code.package.name;
      agentBin = builtins.filter (n: n == ".agents/bin/sprint" || n == ".agents/bin/resolve-project") (builtins.attrNames u.home.file);
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
        service = {k: v for k, v in self.got["service"]["Service"].items() if k != "RestartSec"}
        self.assertEqual(service, {
            "ExecStart": [self.got["command"]],
            "Environment": [f"PATH={self.got['path']}"],
            "Restart": "always",
        })

    def test_the_service_retries_a_busy_port_without_limit(self):
        # Without these, five failed starts inside the default interval leave the unit failed for good.
        unit = self.got["service"]
        delay = unit["Service"]["RestartSec"]
        self.assertRegex(str(delay), r"^\d+$")
        self.assertGreaterEqual(int(delay), 2)
        self.assertEqual(unit["Service"]["Restart"], "always")
        self.assertEqual(str(unit["Unit"]["StartLimitIntervalSec"]), "0")

    def test_the_service_starts_with_the_users_session(self):
        self.assertEqual(self.got["service"]["Install"]["WantedBy"], ["default.target"])
        description = self.got["service"]["Unit"]["Description"]
        self.assertIsInstance(description, str)
        self.assertTrue(description.strip())

    def test_the_service_path_finds_gh_the_user_profile_and_the_system_tools(self):
        self.assertRegex(self.got["gh"], r"^/nix/store/[0-9a-z]{32}-gh-")
        self.assertEqual(self.got["path"].split(":"), [
            f"{self.got['gh']}/bin", f"{self.got['profile']}/bin",
            "/run/current-system/sw/bin", "/usr/bin", "/bin"])

    def test_the_unit_path_carries_every_launch_tool(self):
        packages = {"bash": "bash", "dirname": "coreutils", "mkdir": "coreutils",
                    "chmod": "coreutils", "ln": "coreutils", "systemd-run": "systemd"}
        self.assertEqual(set(packages), set(manager.LAUNCH_TOOLS))
        for tool, package in packages.items():
            with self.subTest(tool=tool):
                self.assertTrue(any(name.startswith(package) for name in self.got["system"]), package)
        self.assertIn(self.got["claude"], self.got["homePackages"])

    def test_the_manager_finds_the_sprint_command(self):
        self.assertEqual(sorted(self.got["agentBin"]),
                         [".agents/bin/resolve-project", ".agents/bin/sprint"])


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

    def test_the_agent_path_is_gh_then_the_system_tools(self):
        for got, _ in self.hosts():
            segments = got["path"].split(":")
            self.assertRegex(segments[0], r"^/nix/store/[0-9a-z]{32}-gh-[^/]+/bin$")
            self.assertEqual(segments[1:], ["/usr/bin", "/bin"])

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
