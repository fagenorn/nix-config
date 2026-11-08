"""The nix-darwin user-agent reload step with and without a gui domain (issue 705).

On a host with nobody logged in at the console there is no gui/<uid> domain, and
`launchctl asuser <uid> ...` aborts the activation (exit 134 under a tty). The guard
in hosts/common/darwin-user-agent-reload-guard.sh turns that call into one log line.
Run: just agent-workflow-tests
"""
import os
import platform
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
FAKE = """#!/bin/bash
echo "launchctl $*" >> "$CALLS"
if [ "$1" = print ]; then
  [ "$HAS_DOMAIN" = 1 ] && exit 0
  echo "Could not find domain for: $2" >&2
  exit 113
fi
if [ "$1" = asuser ] && [ "$HAS_DOMAIN" != 1 ]; then
  kill -ABRT $$
fi
exit 0
"""
# The two asuser calls nix-darwin's reload step makes for one agent, then a third for a second agent.
STEP = """set -e
source "$GUARD"
launchctl asuser 502 sudo --user=anis -- launchctl unload a.plist || true
launchctl asuser 502 sudo --user=anis -- launchctl load -w a.plist
launchctl asuser 502 sudo --user=anis -- launchctl load -w b.plist
launchctl setenv FOO bar
unset -f launchctl
echo finished
"""


class ReloadGuard(unittest.TestCase):
    def run_step(self, has_domain, script=STEP):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        root = Path(os.path.realpath(scratch.name))
        (root / "bin").mkdir()
        fake = root / "bin/launchctl"
        fake.write_text(FAKE)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        calls = root / "calls"
        env = {"PATH": f"{root / 'bin'}:/usr/bin:/bin", "CALLS": str(calls),
               "HAS_DOMAIN": "1" if has_domain else "0", "GUARD": str(GUARD)}
        done = subprocess.run(["/bin/bash", "-c", script], env=env, capture_output=True, text=True, timeout=60)
        return done, calls.read_text().splitlines() if calls.exists() else []

    def test_without_a_gui_domain_the_reload_is_skipped_with_one_line_and_exit_zero(self):
        done, calls = self.run_step(has_domain=False)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "finished"), done.stderr)
        self.assertEqual(done.stderr.splitlines(), [SKIP_LINE])
        self.assertFalse([c for c in calls if c.startswith("launchctl asuser")], calls)

    def test_without_a_gui_domain_other_launchctl_calls_still_run(self):
        done, calls = self.run_step(has_domain=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("launchctl setenv FOO bar", calls)

    def test_with_a_gui_domain_every_call_reaches_launchctl_and_nothing_is_logged(self):
        done, calls = self.run_step(has_domain=True)
        self.assertEqual((done.returncode, done.stderr), (0, ""), done.stderr)
        asuser = [c for c in calls if c.startswith("launchctl asuser 502 ")]
        self.assertEqual(len(asuser), 3, calls)

    def test_the_guard_is_gone_after_the_reload_step(self):
        done, _ = self.run_step(has_domain=False, script='source "$GUARD"; unset -f launchctl; type -t launchctl || echo none')
        self.assertEqual(done.stdout.strip(), "file", done.stderr)


@unittest.skipUnless(platform.system() == "Darwin", "the darwin activation text needs a darwin builder")
class ReloadWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = {host: units.evaluate(f"darwinConfigurations.{host}", """c: u: {
          text = c.system.activationScripts.userLaunchd.text;
        }""") for host in units.DarwinHosts.HOSTS}

    def test_the_guard_wraps_the_reload_step_on_every_host(self):
        guard = GUARD.read_text()
        for host in units.DarwinHosts.HOSTS:
            with self.subTest(host=host):
                text = self.got[host]["text"]
                self.assertTrue(text.startswith(guard), text[:300])
                self.assertLess(text.index(guard), text.index("reloading user service"))
                self.assertTrue(text.rstrip().endswith("unset -f launchctl"), text[-300:])


if __name__ == "__main__":
    unittest.main()
