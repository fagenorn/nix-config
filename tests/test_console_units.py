"""The console's user service on each host as the configuration evaluates it (issue 856).

Evaluates the flake from this checkout's git tree, so new files must be `git add`-ed first.
Its evaluations run with the environment from before the accounts sandbox, so they read the
host's Nix cache, while the sandbox still covers the module (#1286).
Run: just agent-workflow-tests
"""
import os
import plistlib
import re
import shlex
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import manager, service

from . import accounts_sandbox, test_verify_pending_units as units
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

PORT = 27184
GUEST_PORT = 27185
LAUNCHER = re.compile(r"^/nix/store/[0-9a-z]{32}-agent-tools-console$")


def check_command(case, command, tailscale=None):
    """The command's words; `tailscale` is the Windows client path a host reads Serve status from (#1237)."""
    words = shlex.split(command)
    case.assertRegex(words[0], LAUNCHER)
    case.assertEqual(words[1:5], ["--port", str(PORT), "--guest-port", str(GUEST_PORT)])
    rest = words[5:]
    if tailscale is not None:
        case.assertEqual(rest[:2], ["--tailscale", tailscale], command)
        rest = rest[2:]
    case.assertEqual(len(rest), 2, command)
    # The one default screenshot folder a manual check's pictures may come from (issue 1112).
    case.assertEqual(rest[0], "--screenshots")
    case.assertRegex(rest[1], r"^/(home|Users)/[^/ ]+/tmp/clarity-screenshots$")


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
        check_command(self, self.got["command"], "/mnt/c/Program Files/Tailscale/tailscale.exe")

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
            f"{self.got['gh']}/bin", "/run/wrappers/bin", f"{self.got['profile']}/bin",
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
      profile = u.home.profileDirectory;
      user = u.home.username;
      atBoot = c.ownerServices.atBoot;
      agentCommand = if c.launchd.user.agents ? agent-console then c.launchd.user.agents.agent-console.command else null;
      daemonCommand = if c.launchd.daemons ? agent-console then c.launchd.daemons.agent-console.command else null;
      inUserAgents = c.environment.userLaunchAgents ? "org.nixos.agent-console.plist";
      inDaemons = c.environment.launchDaemons ? "org.nixos.agent-console.plist";
      homeAgent = u.launchd.agents ? agent-console;
      plist = (c.environment.userLaunchAgents // c.environment.launchDaemons)."org.nixos.agent-console.plist".text;
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
            self.assertEqual(got["daemonCommand" if got["atBoot"] else "agentCommand"], command)
            self.assertEqual(plist["ProgramArguments"],
                             ["/bin/sh", "-c", f"/bin/wait4path /nix/store && exec {command}"])
            self.assertNotIn("Program", plist)

    def test_a_boot_host_runs_the_console_as_a_daemon_of_the_owner(self):
        for got, plist in self.hosts():
            if not got["atBoot"]:
                continue
            self.assertIs(got["inDaemons"], True)
            self.assertIs(got["inUserAgents"], False)
            self.assertEqual(plist["UserName"], got["user"])

    def test_a_login_host_runs_the_console_as_a_user_agent(self):
        for got, plist in self.hosts():
            if got["atBoot"]:
                continue
            self.assertIs(got["inUserAgents"], True)
            self.assertIs(got["inDaemons"], False)
            self.assertNotIn("UserName", plist)

    def test_the_agent_starts_at_login_and_is_restarted_on_exit(self):
        for _, plist in self.hosts():
            self.assertEqual(plist["Label"], self.LABEL)
            self.assertIs(plist["RunAtLoad"], True)
            self.assertIs(plist["KeepAlive"], True)

    def test_the_agent_finds_gh_and_home(self):
        for got, plist in self.hosts():
            self.assertEqual(plist["EnvironmentVariables"], {"PATH": got["path"], "HOME": got["home"]})

    def test_the_agent_leaves_a_managers_process_group_alone(self):
        for _, plist in self.hosts():
            self.assertIs(plist["AbandonProcessGroup"], True)

    def test_the_agent_path_is_gh_the_owner_and_system_profiles_then_the_system_tools(self):
        for got, _ in self.hosts():
            segments = got["path"].split(":")
            self.assertRegex(segments[0], r"^/nix/store/[0-9a-z]{32}-gh-[^/]+/bin$")
            self.assertEqual(got["profile"], f"/etc/profiles/per-user/{got['user']}")
            self.assertEqual(segments[1:], [f"{got['profile']}/bin", "/run/current-system/sw/bin",
                                            "/usr/bin", "/bin"])

    def test_the_agent_logs_to_one_file_and_has_no_other_keys(self):
        for got, plist in self.hosts():
            log = f"{got['home']}/Library/Logs/agent-console.log"
            self.assertEqual(plist["StandardOutPath"], log)
            self.assertEqual(plist["StandardErrorPath"], log)
            keys = {"Label", "ProgramArguments", "RunAtLoad", "KeepAlive", "AbandonProcessGroup",
                    "EnvironmentVariables", "StandardOutPath", "StandardErrorPath"}
            self.assertEqual(set(plist), keys | ({"UserName"} if got["atBoot"] else set()))

    def test_home_manager_declares_no_second_console_agent(self):
        for got, _ in self.hosts():
            self.assertIs(got["homeAgent"], False)


class NixCacheTest(unittest.TestCase):
    """The environment this module's `nix eval` children start with (#1286); nothing here evaluates."""

    def test_the_modules_evaluations_run_outside_the_sandbox(self):
        root = accounts_sandbox.root()
        self.assertIsNotNone(root)
        calls = []

        def fake(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")

        with mock.patch.object(units.subprocess, "run", fake):
            units.evaluate("nixosConfigurations.anis-desktop", "c: u: {}")
            units.evaluate("darwinConfigurations.mbp", "c: u: {}", pure=True)
        self.assertEqual(len(calls), 4)
        variables = accounts_sandbox.VARIABLES
        for _, kwargs in calls:
            env = os.environ if kwargs.get("env") is None else kwargs["env"]
            self.assertIn("HOME", env)
            for v in variables:
                if v in env:
                    self.assertFalse(Path(env[v]).resolve().is_relative_to(root), v)
            self.assertEqual(
                {k: x for k, x in env.items() if k not in variables},
                {k: x for k, x in os.environ.items() if k not in variables},
            )


if __name__ == "__main__":
    unittest.main()
