"""The nix-darwin user-agent reload step with and without a gui domain (issue 705).

On a host with nobody logged in at the console there is no gui/<uid> domain, and the
non-root `launchctl load` that nix-darwin's `launchctl asuser <uid> sudo ... launchctl load`
runs aborts the activation (exit 134 under a tty). The guard in
hosts/common/darwin-user-agent-reload-guard.sh turns that call into one log line.

The step run here is the real `system.activationScripts.userLaunchd.text` of each darwin host,
evaluated purely, so it runs on any machine (the required CI job runs on Linux); only
`launchctl`, `sudo` and `id` are fakes, and a regression in the wiring or in nix-darwin's
step text fails these tests.
Run: just agent-workflow-tests
"""
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from . import test_verify_pending_units as units

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "hosts/common/darwin-user-agent-reload-guard.sh"
SKIP_LINE = ("skipping user launchd reloads: there is no gui/502 domain (nobody is logged in at the console); "
             "the user agents load at the next login")
# Without a gui/<uid> domain: `asuser` itself works, `print gui/<uid>` returns 125 and the inner
# non-root `launchctl load`/`unload` returns 134 (the issue's diagnosis).
LAUNCHCTL = """#!/bin/bash
echo "launchctl $*" >> "$CALLS"
case "$1" in
  print) [ "$HAS_DOMAIN" = 1 ] && exit 0; echo "Could not find service" >&2; exit 125 ;;
  asuser) shift 2; exec "$@" ;;
  load|unload) [ "$HAS_DOMAIN" = 1 ] && exit 0; exit 134 ;;
esac
exit 0
"""
# `sudo --user=<u> -- cmd ...`: run launchctl, treat the file operations (mkdir, cp, rm) as done.
SUDO = """#!/bin/bash
echo "sudo $*" >> "$CALLS"
shift 2
[ "$1" = launchctl ] && exec "$@"
exit 0
"""
ID = """#!/bin/bash
echo 502
"""


class ReloadStep(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user = units.username()
        # pure: the required CI job runs on Linux, where only a pure evaluation works.
        cls.got = {host: units.evaluate(f"darwinConfigurations.{host}", """c: u: {
          text = c.system.activationScripts.userLaunchd.text;
        }""", pure=True)["text"] for host in units.DarwinHosts.HOSTS}

    def run_text(self, text, has_domain, tail=""):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        root = Path(os.path.realpath(scratch.name))
        (root / "bin").mkdir()
        for name, body in (("launchctl", LAUNCHCTL), ("sudo", SUDO), ("id", ID)):
            fake = root / "bin" / name
            fake.write_text(body)
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        agents = root / "home/Library/LaunchAgents"
        agents.mkdir(parents=True)
        (agents / "org.nixos.verify-pending.plist").write_text("old")  # a changed plist: the reload path
        calls = root / "calls"
        env = {"PATH": f"{root / 'bin'}:/usr/bin:/bin", "CALLS": str(calls),
               "HAS_DOMAIN": "1" if has_domain else "0", "FAKEHOME": str(root / "home")}
        script = "set -e\n" + text.replace(f"~{self.user}", "$FAKEHOME") + "\n" + tail
        done = subprocess.run(["/bin/bash", "-c", script], env=env, capture_output=True, text=True, timeout=60)
        return done, calls.read_text().splitlines() if calls.exists() else []

    def hosts(self):
        for host in units.DarwinHosts.HOSTS:
            with self.subTest(host=host):
                yield self.got[host]

    def test_the_guard_wraps_the_step_and_the_step_calls_bare_launchctl_asuser(self):
        guard = GUARD.read_text()
        for text in self.hosts():
            self.assertTrue(text.startswith(guard), text[:300])
            self.assertLess(text.index(guard), text.index("reloading user service"))
            self.assertTrue(text.rstrip().endswith("unset -f launchctl"), text[-300:])
            step = text[len(guard):]
            # the form the shell function shadows: never /bin/launchctl or `command launchctl`
            self.assertEqual(len(re.findall(r'^\s*launchctl asuser "\$\(id -u -- ', step, re.M)), 2, step)
            self.assertEqual(len(re.findall(r"launchctl asuser", step)), 2, step)

    def test_without_the_guard_a_missing_gui_domain_aborts_the_step(self):
        # The control: the fakes reproduce the failure the guard exists for.
        for text in self.hosts():
            done, calls = self.run_text(text.replace(GUARD.read_text(), "", 1), has_domain=False)
            self.assertEqual(done.returncode, 134, done.stderr)
            self.assertIn("launchctl load -w", "\n".join(calls))

    def test_without_a_gui_domain_the_reload_is_skipped_with_one_line_and_exit_zero(self):
        for text in self.hosts():
            done, calls = self.run_text(text, has_domain=False, tail="echo finished")
            self.assertEqual((done.returncode, done.stdout.splitlines()[-1]), (0, "finished"), done.stderr)
            self.assertEqual(done.stderr.splitlines().count(SKIP_LINE), 1, done.stderr)
            self.assertFalse([c for c in calls if c.startswith("launchctl asuser")], calls)
            self.assertFalse([c for c in calls if " load " in c], calls)

    def test_with_a_gui_domain_the_unload_and_load_reach_launchctl_and_nothing_is_skipped(self):
        for text in self.hosts():
            done, calls = self.run_text(text, has_domain=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertNotIn(SKIP_LINE, done.stderr)
            self.assertEqual(len([c for c in calls if c.startswith("launchctl asuser 502 sudo")]), 2, calls)
            self.assertTrue(any(" load -w " in c for c in calls), calls)

    def test_the_guard_is_gone_after_the_step(self):
        for text in self.hosts():
            done, _ = self.run_text(text, has_domain=False, tail="type -t launchctl")
            self.assertEqual(done.stdout.strip().splitlines()[-1], "file", done.stderr)

    def test_without_a_gui_domain_other_launchctl_calls_still_reach_launchctl(self):
        done, calls = self.run_text(GUARD.read_text(), has_domain=False, tail="launchctl setenv FOO bar")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("launchctl setenv FOO bar", calls)


if __name__ == "__main__":
    unittest.main()
