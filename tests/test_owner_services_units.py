"""The owner's secrets decryption and cache proxy on each darwin host, and the legacy cleanup (issue 1290).

On a boot host (`ownerServices.atBoot`) both are launchd daemons that run as the owner, and
nothing addresses the owner's gui/<uid> domain; the legacy login agents of an earlier
generation are booted out and removed at the start of nix-darwin's `launchd` step. A login
host keeps its login-session agents. The cleanup segment is run here with fake `launchctl`,
`id` and `sudo`.
Reads the host evaluations from `tests/host_readings.py`, which evaluates the flake from this
checkout's git tree, so new files must be `git add`-ed first.
Run: just agent-workflow-tests
"""
import os
import platform
import plistlib
import shlex
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from . import host_readings, test_verify_pending_units as units
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

WAIT = "/bin/wait4path /nix/store && exec "
BEGIN = "# ownerServices legacy login agents: begin"
END = "# ownerServices legacy login agents: end"
LABELS = ["org.nixos.agent-console", "org.nixos.verify-pending",
          "org.nix-community.home.sops-nix", "org.nix-community.home.claude-cache-proxy"]
KEYS = {"Label", "ProgramArguments", "UserName", "RunAtLoad", "KeepAlive", "EnvironmentVariables",
        "StandardOutPath", "StandardErrorPath"}
LAUNCHCTL = """#!/bin/bash
echo "launchctl $*" >> "$CALLS"
case "$1" in
  print)
    case "$2" in
      gui/502) [ "$HAS_DOMAIN" = 1 ] && exit 0; echo "Could not find domain" >&2; exit "${PROBE_RC:-125}" ;;
      gui/502/*) grep -qxF "${2#gui/502/}" "$LOADED_FILE" && exit 0; exit 113 ;;
    esac ;;
  bootout)
    label="${2#gui/502/}"
    [ "$label" = "$STUCK" ] && exit 5
    [ "$label" = "$SLOW" ] && exit 0
    grep -vxF "$label" "$LOADED_FILE" > "$LOADED_FILE.new"; mv "$LOADED_FILE.new" "$LOADED_FILE"
    exit 0 ;;
esac
exit 0
"""
SUDO = """#!/bin/bash
while [ "$1" != -- ]; do shift; done
shift
exec "$@"
"""
ID = """#!/bin/bash
echo 502
"""
# A clock that does not wait: each second "passes" at once, and a SLOW label finishes unloading by then.
SLEEP = """#!/bin/bash
echo "sleep $*" >> "$CALLS"
if [ -n "$SLOW" ]; then
  grep -vxF "$SLOW" "$LOADED_FILE" > "$LOADED_FILE.new"; mv "$LOADED_FILE.new" "$LOADED_FILE"
fi
exit 0
"""


class OwnerServices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user = host_readings.username()
        # Read from a pure evaluation: the required CI job runs on Linux, where only that works.
        cls.got = {host: host_readings.read(host, "owner-services") for host in units.DarwinHosts.HOSTS}

    def plist(self, got, label):
        return plistlib.loads(got["plists"][f"{label}.plist"].encode())

    def segment(self, got):
        text = got["launchdText"]
        self.assertEqual(text.count(BEGIN), 1, text)
        self.assertEqual(text.count(END), 1, text)
        return text[text.index(BEGIN):text.index(END) + len(END)]

    def run_segment(self, got, *, has_domain, loaded, stuck="", slow="", probe_rc=125, block_logs=False,
                    root=None, drop=()):
        if root is None:
            scratch = tempfile.TemporaryDirectory()
            self.addCleanup(scratch.cleanup)
            root = Path(os.path.realpath(scratch.name))
            (root / "bin").mkdir()
            for name, body in (("launchctl", LAUNCHCTL), ("sudo", SUDO), ("id", ID), ("sleep", SLEEP)):
                fake = root / "bin" / name
                fake.write_text(body)
                fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            agents = root / "home/Library/LaunchAgents"
            agents.mkdir(parents=True)
            for label in LABELS:
                (agents / f"{label}.plist").write_text("old")
            (agents / "org.example.keep.plist").write_text("keep")
            (root / "home/Library/Logs").mkdir()
            (root / "calls").write_text("")
            if block_logs:
                (root / "home/Library/Logs/SopsNix").write_text("a file, not a directory")
        for label in drop:
            (root / f"home/Library/LaunchAgents/{label}.plist").unlink()
        (root / "loaded").write_text("".join(f"{label}\n" for label in loaded))
        env = {"PATH": f"{root / 'bin'}:/usr/bin:/bin", "CALLS": str(root / "calls"), "LOADED_FILE": str(root / "loaded"),
               "HAS_DOMAIN": "1" if has_domain else "0", "STUCK": stuck, "SLOW": slow,
               "PROBE_RC": str(probe_rc), "FAKEHOME": str(root / "home")}
        script = "set -e\n" + self.segment(got).replace(f"~{self.user}", "$FAKEHOME") + "\necho finished"
        done = subprocess.run(["/bin/bash", "-c", script], env=env, capture_output=True, text=True, timeout=60)
        calls = (root / "calls").read_text().splitlines()
        remaining = sorted(p.name for p in (root / "home/Library/LaunchAgents").iterdir())
        return done, calls, remaining, root

    def test_a_boot_host_runs_all_four_services_as_daemons_of_the_owner(self):
        for host in units.DarwinHosts.BOOT_HOSTS:
            with self.subTest(host=host):
                got = self.got[host]
                home = got["home"]
                for label in ("org.nixos.agent-console", "org.nixos.verify-pending",
                              "org.nixos.claude-cache-proxy", "org.nixos.sops-nix"):
                    p = self.plist(got, label)
                    self.assertEqual(p["UserName"], got["user"], label)
                    self.assertIs(p["RunAtLoad"], True, label)
                    self.assertEqual(p["EnvironmentVariables"]["HOME"], home, label)
                    self.assertEqual(p["ProgramArguments"][:2], ["/bin/sh", "-c"], label)
                    self.assertTrue(p["ProgramArguments"][2].startswith(WAIT), label)
                proxy = self.plist(got, "org.nixos.claude-cache-proxy")
                self.assertEqual(shlex.split(proxy["ProgramArguments"][2][len(WAIT):]), got["proxyArgs"])
                self.assertIs(proxy["KeepAlive"], True)
                self.assertEqual(proxy["EnvironmentVariables"], {**got["proxyEnv"], "HOME": home})
                log = f"{home}/Library/Logs/claude-cache-proxy.log"
                self.assertEqual((proxy["StandardOutPath"], proxy["StandardErrorPath"]), (log, log))
                self.assertEqual(proxy["Label"], "org.nixos.claude-cache-proxy")
                self.assertEqual(set(proxy), KEYS)
                sops = self.plist(got, "org.nixos.sops-nix")
                self.assertEqual(sops["ProgramArguments"][2], WAIT + got["sopsProgram"])
                self.assertIs(sops["KeepAlive"], False)
                self.assertEqual(sops["EnvironmentVariables"], {**(got["sopsEnv"] or {}), "HOME": home})
                self.assertEqual(sops["StandardOutPath"], f"{home}/Library/Logs/SopsNix/stdout")
                self.assertEqual(sops["StandardErrorPath"], f"{home}/Library/Logs/SopsNix/stderr")
                self.assertEqual(sops["Label"], "org.nixos.sops-nix")
                self.assertEqual(set(sops), KEYS)

    def test_a_boot_host_declares_no_login_session_agent(self):
        for host in units.DarwinHosts.BOOT_HOSTS:
            with self.subTest(host=host):
                self.assertEqual(self.got[host]["homeAgents"], [])
                self.assertEqual(self.got[host]["userAgents"], [])

    def test_a_login_host_keeps_its_login_session_agents(self):
        for host in units.DarwinHosts.LOGIN_HOSTS:
            with self.subTest(host=host):
                got = self.got[host]
                self.assertLessEqual({"sops-nix", "claude-cache-proxy"}, set(got["homeAgents"]))
                self.assertEqual(sorted(got["userAgents"]), ["agent-console", "verify-pending"])
                self.assertEqual(got["plists"], {})

    def test_a_boot_host_has_no_gui_domain_secrets_step(self):
        for host in units.DarwinHosts.BOOT_HOSTS:
            with self.subTest(host=host):
                self.assertNotIn("launchctl", self.got[host]["sopsActivation"])
        for host in units.DarwinHosts.LOGIN_HOSTS:
            with self.subTest(host=host):
                self.assertIn("bootstrap gui/", self.got[host]["sopsActivation"])

    def test_with_no_owner_session_the_cleanup_removes_the_legacy_plists(self):
        for host in units.DarwinHosts.BOOT_HOSTS:
            with self.subTest(host=host):
                got = self.got[host]
                done, calls, remaining, root = self.run_segment(got, has_domain=False, loaded=[])
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(done.stdout.splitlines()[-1], "finished")
                self.assertEqual(remaining, ["org.example.keep.plist"])
                self.assertFalse([c for c in calls if " bootout " in c], calls)
                self.assertIn("ownerServices: the owner has no login session", done.stderr)
                self.assertNotIn("ownerServices: the owner has a login session", done.stderr)
                self.assertTrue((root / "home/Library/Logs/SopsNix").is_dir())
                again, _, _, _ = self.run_segment(got, has_domain=False, loaded=[], root=root)
                self.assertEqual(again.returncode, 0, again.stderr)

    def test_in_an_owner_session_the_cleanup_boots_out_each_loaded_agent(self):
        for host in units.DarwinHosts.BOOT_HOSTS:
            with self.subTest(host=host):
                done, calls, remaining, _ = self.run_segment(
                    self.got[host], has_domain=True, loaded=LABELS,
                    drop=("org.nixos.verify-pending", "org.nix-community.home.sops-nix"))
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(done.stdout.splitlines()[-1], "finished")
                for label in LABELS:
                    self.assertEqual(calls.count(f"launchctl bootout gui/502/{label}"), 1, calls)
                self.assertEqual(len([c for c in calls if " bootout " in c]), 4, calls)
                self.assertIn("ownerServices: the owner has a login session", done.stderr)
                self.assertEqual(remaining, ["org.example.keep.plist"])

    def test_a_bootout_that_fails_stops_the_activation_before_any_daemon_loads(self):
        for host in units.DarwinHosts.BOOT_HOSTS:
            with self.subTest(host=host):
                done, _, remaining, _ = self.run_segment(
                    self.got[host], has_domain=True, loaded=LABELS, stuck="org.nixos.agent-console")
                self.assertNotEqual(done.returncode, 0)
                self.assertNotIn("finished", done.stdout)
                self.assertIn("org.nixos.agent-console is still loaded", done.stderr)
                self.assertIn("org.nixos.agent-console.plist", remaining)

    def test_an_agent_that_takes_a_moment_to_exit_is_waited_for(self):
        for host in units.DarwinHosts.BOOT_HOSTS:
            with self.subTest(host=host):
                done, calls, remaining, _ = self.run_segment(
                    self.got[host], has_domain=True, loaded=LABELS, slow="org.nix-community.home.claude-cache-proxy")
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(done.stdout.splitlines()[-1], "finished")
                self.assertIn("sleep 1", calls)
                self.assertEqual(remaining, ["org.example.keep.plist"])

    def test_a_gui_domain_that_cannot_be_read_is_not_a_logout(self):
        for host in units.DarwinHosts.BOOT_HOSTS:
            for rc in (1, 64, 134):
                with self.subTest(host=host, rc=rc):
                    done, calls, remaining, _ = self.run_segment(
                        self.got[host], has_domain=False, loaded=LABELS, probe_rc=rc)
                    self.assertNotEqual(done.returncode, 0)
                    self.assertNotIn("finished", done.stdout)
                    self.assertFalse([c for c in calls if " bootout " in c], calls)
                    self.assertNotIn("the owner has no login session", done.stderr)
                    self.assertEqual(len(remaining), len(LABELS) + 1)
            for rc in (112, 113, 125):
                with self.subTest(host=host, missing=rc):
                    done, _, _, _ = self.run_segment(
                        self.got[host], has_domain=False, loaded=[], probe_rc=rc)
                    self.assertEqual(done.returncode, 0, done.stderr)
                    self.assertIn("the owner has no login session", done.stderr)

    def test_a_log_directory_that_cannot_be_made_stops_the_activation_before_any_agent_is_removed(self):
        for host in units.DarwinHosts.BOOT_HOSTS:
            with self.subTest(host=host):
                done, calls, remaining, _ = self.run_segment(
                    self.got[host], has_domain=True, loaded=LABELS, block_logs=True)
                self.assertNotEqual(done.returncode, 0)
                self.assertNotIn("finished", done.stdout)
                self.assertFalse([c for c in calls if " bootout " in c], calls)
                self.assertEqual(len(remaining), len(LABELS) + 1)

    def test_a_login_host_runs_no_legacy_cleanup(self):
        for host in units.DarwinHosts.LOGIN_HOSTS:
            with self.subTest(host=host):
                got = self.got[host]
                for text in (got["launchdText"], got["pre"]):
                    self.assertNotIn(BEGIN, text)
                    self.assertNotIn(END, text)
                    for label in LABELS:
                        self.assertNotIn(label, text)


@unittest.skipUnless(platform.system() == "Darwin", "the composed activation script needs a darwin builder")
class ActivationOrder(unittest.TestCase):
    """The composed script embeds the home-manager activation package, which a pure evaluation cannot build."""

    @classmethod
    def setUpClass(cls):
        cls.got = {host: host_readings.read(host, "owner-activation") for host in units.DarwinHosts.BOOT_HOSTS}

    def test_the_cleanup_runs_after_the_preflight_checks_and_before_any_daemon_loads(self):
        for host in units.DarwinHosts.BOOT_HOSTS:
            with self.subTest(host=host):
                got = self.got[host]
                self.assertNotIn(BEGIN, got["pre"])
                activate = got["activate"]
                self.assertLess(activate.index("checkActivation:-0"), activate.index(BEGIN))
                self.assertLess(activate.index(BEGIN),
                                activate.index("launchctl load -w '/Library/LaunchDaemons/org.nixos.agent-console.plist'"))


if __name__ == "__main__":
    unittest.main()
