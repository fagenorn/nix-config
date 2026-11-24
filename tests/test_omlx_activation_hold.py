"""The activation's launchd step installs a changed oMLX plist without unloading a loaded daemon.

The step run here is the real `system.activationScripts.launchd.text` of eleven-m5, read from a
pure evaluation so it runs on any machine; only `launchctl`, `sudo`, `diff` and `cp` are fakes,
and the paths the step writes are redirected into a scratch directory.
Run: just agent-workflow-tests
"""
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from . import host_readings

TIER = "integration"

GUIDE = Path(__file__).resolve().parents[1] / "hosts/darwin/eleven-m5/README.md"
REASON = "launchd plist changed: org.nixos.omlx"
OLD_SERVE = "/nix/store/" + "a" * 32 + "-omlx-serve"
OLD_PLIST = f"old <string>/bin/wait4path /nix/store &amp;&amp; exec {OLD_SERVE}</string>\n"
LOADED_SERVE = "/nix/store/" + "c" * 32 + "-omlx-serve"
NEW_PLIST = "new <string>/bin/wait4path /nix/store &amp;&amp; exec /nix/store/" + "b" * 32 + "-omlx-serve</string>\n"
LAUNCHCTL = """#!/bin/bash
echo "launchctl $*" >> "$CALLS"
if [ "$1" = print ]; then
  [ -n "$LOADED_SERVE" ] && printf '\t\t/bin/wait4path /nix/store && exec %s\n' "$LOADED_SERVE"
  exit "$PRINT_RC"
fi
exit 0
"""
SUDO = """#!/bin/bash
echo "sudo $*" >> "$CALLS"
[ "$SUDO_FAIL" = 1 ] && exit 1
while [ "$#" -gt 0 ]; do
  case "$1" in
    --) shift; break ;;
    *) shift ;;
  esac
done
exec "$@"
"""
DIFF = """#!/bin/bash
exit 1
"""
CP = f"""#!/bin/bash
for last; do :; done
printf '%s' '{NEW_PLIST}' > "$last"
"""


class ActivationHoldTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = host_readings.read("eleven-m5", "omlx")
        cls.user = host_readings.username()

    def block(self, target):
        found = re.search(
            r"^if ! diff '[^']*/Library/LaunchDaemons/" + re.escape(target) + r"' .*?^fi\n",
            self.got["launchd"], re.M | re.S,
        )
        self.assertIsNotNone(found, f"the launchd step has no block for {target}")
        return found.group(0)

    def scratch(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        return Path(os.path.realpath(scratch.name))

    def held_root(self, root):
        return root / "gcroots/omlx-held-serve"

    def marker(self, root):
        return root / "home/.omlx/.restart-needed"

    def plist(self, root, name="org.nixos.omlx.plist"):
        return root / "Library/LaunchDaemons" / name

    def run_snippet(self, snippet, root=None, print_rc=0, sudo_fails=False, tail="", held=False, loaded_serve=""):
        root = root or self.scratch()
        (root / "bin").mkdir(exist_ok=True)
        for name, body in (("launchctl", LAUNCHCTL), ("sudo", SUDO), ("diff", DIFF), ("cp", CP)):
            fake = root / "bin" / name
            fake.write_text(body)
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        (root / "Library/LaunchDaemons").mkdir(parents=True, exist_ok=True)
        for name in ("org.nixos.omlx.plist", "org.nixos.omlx-models.plist"):
            if not self.plist(root, name).exists():
                self.plist(root, name).write_text(OLD_PLIST)
        (root / "home/.omlx").mkdir(parents=True, exist_ok=True)
        (root / "gcroots").mkdir(exist_ok=True)
        if held and not os.path.lexists(self.held_root(root)):
            os.symlink(OLD_SERVE, self.held_root(root))
        text = re.sub(r"(?<![\w.-])/Library/LaunchDaemons/", f"{root}/Library/LaunchDaemons/", snippet)
        text = text.replace(f"/Users/{self.user}/", f"{root}/home/")
        text = text.replace("/nix/var/nix/gcroots/", f"{root}/gcroots/")
        calls = root / "calls"
        env = {"PATH": f"{root / 'bin'}:/usr/bin:/bin", "CALLS": str(calls), "PRINT_RC": str(print_rc),
               "SUDO_FAIL": "1" if sudo_fails else "0", "LOADED_SERVE": loaded_serve}
        done = subprocess.run(["/bin/bash", "-c", "set -e\n" + text + "\n" + tail], env=env,
                              capture_output=True, text=True, timeout=60)
        return done, (calls.read_text().splitlines() if calls.exists() else []), root

    def omlx_step(self, **kwargs):
        snippet = self.got["hold"] + self.block("org.nixos.omlx.plist") + self.got["unhold"]
        return self.run_snippet(snippet, **kwargs)

    def test_a_changed_omlx_plist_is_installed_while_the_loaded_daemon_keeps_running(self):
        for print_rc in (0, 1):
            with self.subTest(print_rc=print_rc):
                done, calls, root = self.omlx_step(print_rc=print_rc)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertIn("launchctl print system/org.nixos.omlx", calls)
                self.assertEqual([c for c in calls if c.startswith(("launchctl unload", "launchctl load"))], [])
                self.assertEqual(self.plist(root).read_text(), NEW_PLIST)
                self.assertEqual(self.marker(root).read_text().splitlines(), [REASON])
                self.assertIn(f"pending for omlx-restart: {REASON}", done.stderr)

    def test_two_held_activations_record_the_reason_once(self):
        done, _, root = self.omlx_step()
        self.assertEqual(done.returncode, 0, done.stderr)
        done, _, _ = self.omlx_step(root=root)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.marker(root).read_text().splitlines(), [REASON])

    def test_an_unloaded_omlx_reloads_as_nix_darwin_does(self):
        done, calls, root = self.omlx_step(print_rc=113, held=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        plist = f"{root}/Library/LaunchDaemons/org.nixos.omlx.plist"
        self.assertIn(f"launchctl unload {plist}", calls)
        self.assertIn(f"launchctl load -w {plist}", calls)
        self.assertFalse(self.marker(root).exists())
        self.assertFalse(os.path.lexists(self.held_root(root)))

    def test_another_daemon_reaches_launchctl_through_the_hold(self):
        snippet = self.got["hold"] + self.block("org.nixos.omlx-models.plist") + self.got["unhold"]
        done, calls, root = self.run_snippet(snippet, print_rc=0)
        self.assertEqual(done.returncode, 0, done.stderr)
        plist = f"{root}/Library/LaunchDaemons/org.nixos.omlx-models.plist"
        self.assertIn(f"launchctl unload {plist}", calls)
        self.assertIn(f"launchctl load -w {plist}", calls)
        self.assertEqual([c for c in calls if c.startswith("launchctl print")], [])
        self.assertFalse(os.path.lexists(self.held_root(root)))

    def test_an_unrecordable_reason_stops_before_the_plist_is_installed(self):
        done, calls, root = self.omlx_step(sudo_fails=True)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.plist(root).read_text(), OLD_PLIST)
        self.assertEqual([c for c in calls if c.startswith("launchctl load")], [])
        self.assertIn("activation stopped before the new plist was installed", done.stderr)

    def test_the_hold_wraps_every_daemon_block_and_is_gone_after_the_step(self):
        text, hold, unhold = self.got["launchd"], self.got["hold"], self.got["unhold"]
        self.assertEqual(text.count(hold), 1)
        self.assertLess(text.index(hold), text.index("if ! diff '"))
        self.assertGreater(text.rindex(unhold), text.rindex("launchctl load -w '/Library/LaunchDaemons/"))
        done, _, _ = self.run_snippet(hold + unhold, tail="type -t launchctl; type -t omlx_hold_root || echo gone")
        self.assertEqual(done.stdout.splitlines()[-2:], ["file", "gone"], done.stderr)

    def test_the_guide_names_the_held_daemon_and_how_verify_pending_reloads(self):
        text = GUIDE.read_text(encoding="utf-8")
        start = text.index("## What else an activation restarts")
        section = text[start:text.find("\n## ", start + 1)]
        for needle in ("`org.nixos.omlx`", REASON, "omlx-restart", "omlx-restart --now", "omlx-held-serve",
                       "`verify-pending`", "load -w", "booted out"):
            with self.subTest(needle=needle):
                self.assertIn(needle, section)

    def test_a_held_activation_keeps_the_running_serve_script_rooted_until_the_reload(self):
        done, _, root = self.omlx_step(print_rc=0, loaded_serve=OLD_SERVE)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(os.readlink(self.held_root(root)), OLD_SERVE)
        done, _, _ = self.omlx_step(root=root, print_rc=0, loaded_serve=OLD_SERVE)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(os.readlink(self.held_root(root)), OLD_SERVE)

    def test_a_stale_root_is_repointed_at_the_definition_launchd_holds(self):
        done, _, root = self.omlx_step(print_rc=0, held=True, loaded_serve=LOADED_SERVE)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(os.readlink(self.held_root(root)), LOADED_SERVE)
        self.assertEqual(self.plist(root).read_text(), NEW_PLIST)

    def test_the_hold_keeps_its_variables_and_functions_inside_its_eval_body(self):
        hold = self.got["hold"]
        outside = re.sub(r"eval '.*?'\n", "", hold, flags=re.S)
        self.assertEqual(hold.count("eval '"), 1)
        for line in outside.splitlines():
            if line.strip():
                self.assertTrue(line.strip().startswith("#"), line)
        for name in ("omlx_hold_root() {", "omlx_hold_record() {", "launchctl() {"):
            with self.subTest(name=name):
                self.assertIn(name, hold)


if __name__ == "__main__":
    unittest.main()
