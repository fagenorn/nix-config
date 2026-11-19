"""The console's user service on each host as the configuration evaluates it (issue 856).

Evaluates the flake from this checkout's git tree, so new files must be `git add`-ed first.
Its evaluations run with the environment from before the accounts sandbox, so they read the
host's Nix cache, while the sandbox still covers the module (#1286).
On a host whose nix cannot build x86_64-linux (its `system`, `extra-platforms` and `builders`),
`LinuxUnit` skips and says so; CI's Agent Workflow Tests runs it on Linux (#1286).
Run: just agent-workflow-tests
"""
import json
import os
import plistlib
import re
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import manager, service

from . import accounts_sandbox, test_verify_pending_units as units
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

PORT = 27184
LAUNCHER = re.compile(r"^/nix/store/[0-9a-z]{32}-agent-tools-console$")


def check_command(case, command, home, tailscale=None):
    """The command's words; `tailscale` is the client path a host reads Serve status from (#1237, #1299)."""
    words = shlex.split(command)
    case.assertRegex(words[0], LAUNCHER)
    case.assertEqual(words[1:5], ["--port", str(PORT), "--guest-socket",
                                  f"{home}/.agents/state/console/guest/guest.sock"])
    rest = words[5:]
    if tailscale is not None:
        case.assertEqual(rest[:2], ["--tailscale", tailscale], command)
        rest = rest[2:]
    case.assertEqual(len(rest), 2, command)
    # The one default screenshot folder a manual check's pictures may come from (issue 1112).
    case.assertEqual(rest[0], "--screenshots")
    case.assertRegex(rest[1], r"^/(home|Users)/[^/ ]+/tmp/clarity-screenshots$")


def assert_outside_sandbox(case, env):
    """`env` is the one from before the sandbox. A failure names variables, never prints the environment (it holds credentials)."""
    if env is None:
        env = os.environ
    for name in accounts_sandbox.VARIABLES:
        # `.get`: a variable unset before the sandbox must be unset here, not a KeyError.
        case.assertEqual(env.get(name), accounts_sandbox.ORIGINAL[name], name)
    root = str(accounts_sandbox.root())
    case.assertEqual(sorted(k for k, v in env.items() if root in v), [])  # no variable points into the sandbox
    others = set(env) | set(os.environ)
    case.assertEqual(
        sorted(k for k in others if k not in accounts_sandbox.VARIABLES and env.get(k) != os.environ.get(k)), [])


NIX_CONFIG = ["nix", "--extra-experimental-features", "nix-command flakes", "config", "show", "--json"]
NO_LINUX_BUILDER = (
    "no x86_64-linux builder: nix's system, extra-platforms and builders name none, and evaluating "
    "nixosConfigurations.anis-desktop builds x86_64-linux derivations; "
    "CI's Agent Workflow Tests runs these on Linux (#1286)"
)


def builder_entries(text):
    """The entries of a `builders` value or machines file, as Nix 2.31.5 expands them (`expandBuilderLines`)."""
    for line in text.split("\n"):
        for entry in line.split("#", 1)[0].split(";"):
            entry = entry.strip()
            if not entry:
                continue
            if entry.startswith("@"):
                try:
                    yield from builder_entries(Path(entry[1:].strip()).read_text())
                except FileNotFoundError:
                    pass
            else:
                yield entry


def can_build(system):
    """Whether this host's nix names `system` in its `system`, `extra-platforms` or `builders` settings."""
    done = subprocess.run(NIX_CONFIG, cwd=units.ROOT, capture_output=True, text=True, timeout=60,
                          env=accounts_sandbox.unsandboxed_environment())
    if done.returncode != 0:
        raise AssertionError(f"nix config show failed:\n{done.stderr[-4000:]}")
    settings = json.loads(done.stdout)
    local = settings["system"]["value"]
    if system == local or system in settings["extra-platforms"]["value"]:
        return True
    for entry in builder_entries(settings["builders"]["value"]):
        fields = entry.split()
        systems = fields[1] if len(fields) > 1 and fields[1] != "-" else local
        if system in systems.split(","):
            return True
    return False


class LinuxUnit(unittest.TestCase):
    HOST = "anis-desktop"
    APPLY = """c: u: {
      command = u.agentConsole.command;
      home = u.home.homeDirectory;
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
        if not can_build("x86_64-linux"):
            raise unittest.SkipTest(NO_LINUX_BUILDER)
        cls.got = units.evaluate(f"nixosConfigurations.{cls.HOST}", cls.APPLY)

    def test_the_port_is_the_consoles_fixed_port(self):
        self.assertEqual(PORT, service.DEFAULT_PORT)
        check_command(self, self.got["command"], self.got["home"],
                      "/mnt/c/Program Files/Tailscale/tailscale.exe")

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
      tailscaleClient = if c.services.tailscale.enable then "${c.services.tailscale.package}/bin/tailscale" else null;
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
            check_command(self, command, got["home"], got["tailscaleClient"])
            self.assertEqual(got["daemonCommand" if got["atBoot"] else "agentCommand"], command)
            self.assertEqual(plist["ProgramArguments"],
                             ["/bin/sh", "-c", f"/bin/wait4path /nix/store && exec {command}"])
            self.assertNotIn("Program", plist)

    def test_only_a_mac_with_the_tailscale_daemon_reads_its_client(self):
        daemon = self.got["eleven-m5"]
        self.assertRegex(daemon["tailscaleClient"],
                         r"^/nix/store/[0-9a-z]{32}-tailscale-[^/]+/bin/tailscale$")
        words = shlex.split(daemon["command"])
        pairs = [words[i:i + 2] for i in range(len(words) - 1)]
        self.assertIn(["--tailscale", daemon["tailscaleClient"]], pairs)
        menu_bar = self.got["mbp"]
        self.assertIsNone(menu_bar["tailscaleClient"])
        self.assertNotIn("--tailscale", shlex.split(menu_bar["command"]))

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


class LinuxBuilderTest(unittest.TestCase):
    """Whether this host's nix can build x86_64-linux decides the Linux unit (#1286); nothing here evaluates."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = self.tmp.name
        self.machines = Path(self.t) / "machines"

    @staticmethod
    def config(system="aarch64-darwin", extra=(), builders=""):
        return json.dumps({
            "system": {"value": system},
            "extra-platforms": {"value": list(extra)},
            "builders": {"value": builders},
        })

    @staticmethod
    def act(stdout, returncode=0):
        calls = []

        def fake(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="broken nix")

        raised = None
        with mock.patch.object(subprocess, "run", fake), \
                mock.patch.object(units, "evaluate", return_value={"marker": 1}) as evaluate, \
                mock.patch.object(LinuxUnit, "got", None, create=True):
            try:
                LinuxUnit.setUpClass()
            except BaseException as exc:  # noqa: BLE001 -- the case under test inspects it
                raised = exc
            got = LinuxUnit.got
        return calls, evaluate, raised, got

    def test_a_host_with_no_x86_64_linux_builder_skips_the_linux_unit(self):
        self.machines.write_text("ssh://b aarch64-linux # x86_64-linux\n")
        cases = {
            "a": {},
            "b": {"extra": ("x86_64-darwin",)},
            "c": {"builders": "ssh://b aarch64-linux,aarch64-darwin - 4"},
            "d": {"builders": "ssh://b - /key 4"},
            "e": {"builders": "ssh://b"},
            "f": {"builders": f"@{self.t}/missing"},
            "g": {"builders": f"@{self.machines}"},
        }
        for name, settings in cases.items():
            with self.subTest(name):
                calls, evaluate, raised, _ = self.act(self.config(**settings))
                self.assertTrue(isinstance(raised, unittest.SkipTest), repr(raised))
                self.assertIn("x86_64-linux builder", str(raised))
                evaluate.assert_not_called()
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][0][-3:], ["config", "show", "--json"])
                self.assertIsNotNone(accounts_sandbox.root())
                assert_outside_sandbox(self, calls[0][1].get("env"))

    def test_a_host_that_builds_x86_64_linux_runs_the_linux_unit(self):
        self.machines.write_text("# linux builders\nssh://b x86_64-linux /key\n")
        cases = {
            "a": {"system": "x86_64-linux"},
            "b": {"extra": ("x86_64-darwin", "x86_64-linux")},
            "c": {"builders": "ssh://a aarch64-linux ; ssh://b aarch64-linux,x86_64-linux - 4"},
            "d": {"builders": f"@{self.machines}"},
        }
        for name, settings in cases.items():
            with self.subTest(name):
                _, evaluate, raised, got = self.act(self.config(**settings))
                self.assertIsNone(raised, repr(raised))
                evaluate.assert_called_once_with("nixosConfigurations.anis-desktop", LinuxUnit.APPLY)
                self.assertEqual(got, {"marker": 1})

    def test_a_failing_nix_config_errors_instead_of_skipping(self):
        _, evaluate, raised, _ = self.act("", returncode=1)
        self.assertIs(type(raised), AssertionError)
        self.assertIn("nix config show failed", str(raised))
        self.assertIn("broken nix", str(raised))
        evaluate.assert_not_called()


class NixCacheTest(unittest.TestCase):
    """The environment this module's `nix` children start with (#1286); nothing here evaluates."""

    def test_the_modules_setup_methods_run_nix_outside_the_sandbox(self):
        self.assertIsNotNone(accounts_sandbox.root())
        calls = []

        def fake(argv, **kwargs):
            calls.append((argv, kwargs))
            if argv[-3:] == ["config", "show", "--json"]:
                out = LinuxBuilderTest.config(system="x86_64-linux")
            else:
                out = json.dumps({"plist": plistlib.dumps({}).decode()})
            return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

        outputs = {LinuxUnit: [f"nixosConfigurations.{LinuxUnit.HOST}"],
                   DarwinAgent: [f"darwinConfigurations.{h}" for h in DarwinAgent.HOSTS]}
        with mock.patch.object(subprocess, "run", fake), \
                mock.patch.object(LinuxUnit, "got", None, create=True), \
                mock.patch.object(DarwinAgent, "got", None, create=True), \
                mock.patch.object(DarwinAgent, "plist", None, create=True):
            for case, wanted in outputs.items():
                with self.subTest(case.__name__):
                    before = len(calls)
                    case.setUpClass()
                    mine = calls[before:]
                    for output in wanted:
                        self.assertTrue(any(output in " ".join(argv) for argv, _ in mine), output)
                    for _, kwargs in mine:
                        assert_outside_sandbox(self, kwargs.get("env"))
        self.assertTrue(any(argv[-3:] == ["config", "show", "--json"] for argv, _ in calls))


if __name__ == "__main__":
    unittest.main()
