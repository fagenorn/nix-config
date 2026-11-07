"""The verify-pending pass and kick scripts (issue 632). Run: just agent-workflow-tests"""
import os
import re
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

DIR = Path(__file__).resolve().parents[1] / "home/common/verify-pending"
STAMP = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
LIMIT = 1048576
WAIT = 2


class Scripts(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(os.path.realpath(scratch.name))
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls"
        self.state = self.home / ".agents/state/verify-pending"
        self.log = self.state / "runner.log"
        self.request = self.state / "switch-request"
        self.system_a = self.root / "system-a"
        self.system_b = self.root / "system-b"
        self.system_a.mkdir()
        self.system_b.mkdir()
        self.current = self.root / "current-system"
        self.current.symlink_to(self.system_a)

    def stub(self, name, status, extra=""):
        path = self.bin / name
        path.write_text(f'#!/bin/sh\necho "{name} $*" >> "{self.calls}"\n{extra}echo "{name} output"\nexit {status}\n')
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def render(self, name, values):
        text = (DIR / name).read_text()
        self.assertFalse(text.startswith("#!"), f"{name} carries no shebang; writeShellScript adds one")
        for token, value in values.items():
            self.assertIn(token, text)
            text = text.replace(token, value)
        self.assertIsNone(re.search(r"@[A-Za-z]+@", text), "an unknown placeholder is left")
        path = self.root / name
        path.write_text(text)
        return path

    def run_script(self, path, args, home):
        env = {"PATH": "/usr/bin:/bin"}
        if home:
            env["HOME"] = str(self.home)
        return subprocess.run(["bash", str(path), *args], env=env, capture_output=True, text=True, timeout=60)

    def calls_made(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []


class Pass(Scripts):
    def script(self, owner_actions=True, verify_status=0, owner_status=0, verify_extra=""):
        owner = str(self.stub("owner-actions", owner_status)) if owner_actions else ""
        verify = str(self.stub("verify-pending", verify_status, verify_extra))
        return self.render("pass.sh", {"@path@": "/usr/bin:/bin", "@caFile@": "/dev/null",
                                       "@verifyPending@": verify, "@ownerActions@": owner,
                                       "@currentSystem@": str(self.current), "@switchWait@": str(WAIT)})

    def run_pass(self, *args, home=True, **script):
        return self.run_script(self.script(**script), args, home)

    def lines(self):
        return self.log.read_text().splitlines()

    def test_a_pass_logs_start_and_end_and_runs_both_commands(self):
        done = self.run_pass("mbp")
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))
        self.assertEqual(self.calls_made(), ["verify-pending run --host mbp", "owner-actions refresh"])
        lines = self.lines()
        self.assertRegex(lines[0], rf"^{STAMP} pass start host=mbp$")
        self.assertEqual(lines[1:3], ["verify-pending output", "owner-actions output"])
        self.assertRegex(lines[3], rf"^{STAMP} pass end host=mbp verify=0 owner_actions=0$")
        self.assertEqual(len(lines), 4)

    def test_failing_children_never_fail_the_pass(self):
        done = self.run_pass("anis-desktop", verify_status=1, owner_status=3)
        self.assertEqual(done.returncode, 0)
        self.assertRegex(self.lines()[-1], rf"^{STAMP} pass end host=anis-desktop verify=1 owner_actions=3$")

    def test_no_owner_actions_launcher_skips_the_refresh(self):
        done = self.run_pass("eleven-m5", owner_actions=False)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(self.calls_made(), ["verify-pending run --host eleven-m5"])
        self.assertRegex(self.lines()[-1], rf"^{STAMP} pass end host=eleven-m5 verify=0 owner_actions=skipped$")

    def test_a_log_over_the_limit_is_rotated_once(self):
        self.state.mkdir(parents=True)
        (self.state / "runner.log.1").write_text("older\n")
        self.log.write_text("x" * (LIMIT + 1))
        self.assertEqual(self.run_pass("mbp").returncode, 0)
        self.assertEqual((self.state / "runner.log.1").stat().st_size, LIMIT + 1)
        self.assertRegex(self.lines()[0], rf"^{STAMP} pass start host=mbp$")
        self.assertEqual(sorted(p.name for p in self.state.iterdir()), ["runner.log", "runner.log.1"])

    def test_a_log_at_the_limit_is_kept(self):
        self.state.mkdir(parents=True)
        self.log.write_text("x" * LIMIT)
        self.assertEqual(self.run_pass("mbp").returncode, 0)
        self.assertFalse((self.state / "runner.log.1").exists())
        self.assertTrue(self.log.read_text().startswith("x" * LIMIT))

    def test_the_state_directory_is_private(self):
        self.run_pass("mbp")
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)

    def test_a_missing_home_exits_zero_without_running(self):
        done = self.run_pass("mbp", home=False)
        self.assertEqual(done.returncode, 0)
        self.assertIn("verify-pending-pass: HOME is unset", done.stderr)
        self.assertEqual(self.calls_made(), [])

    def test_a_wrong_argument_count_is_a_usage_error(self):
        for args in ((), ("mbp", "extra")):
            with self.subTest(args=args):
                done = self.run_pass(*args)
                self.assertEqual(done.returncode, 2)
                self.assertIn("verify-pending-pass: usage: verify-pending-pass HOST", done.stderr)
                self.assertFalse((self.home / ".agents").exists())
                self.assertEqual(self.calls_made(), [])

    def test_a_request_for_the_current_system_is_claimed_and_runs_one_round(self):
        self.state.mkdir(parents=True)
        self.request.write_text(f"{self.system_a}\n")
        self.assertEqual(self.run_pass("mbp").returncode, 0)
        lines = self.lines()
        self.assertRegex(lines[0], rf"^{STAMP} switch host=mbp target={re.escape(str(self.system_a))} current=yes$")
        self.assertRegex(lines[1], rf"^{STAMP} pass start host=mbp$")
        self.assertEqual(self.calls_made(), ["verify-pending run --host mbp", "owner-actions refresh"])
        self.assertEqual(sorted(p.name for p in self.state.iterdir()), ["runner.log"])

    def test_an_empty_request_runs_at_once_without_a_switch_line(self):
        self.state.mkdir(parents=True)
        self.request.write_text("\n")
        self.assertEqual(self.run_pass("anis-desktop").returncode, 0)
        self.assertRegex(self.lines()[0], rf"^{STAMP} pass start host=anis-desktop$")
        self.assertFalse(self.request.exists())

    def test_a_system_that_never_becomes_current_times_out_and_still_runs(self):
        self.state.mkdir(parents=True)
        self.request.write_text(f"{self.system_b}\n")
        began = time.monotonic()
        self.assertEqual(self.run_pass("mbp").returncode, 0)
        self.assertGreaterEqual(time.monotonic() - began, WAIT)
        lines = self.lines()
        self.assertRegex(lines[0], rf"^{STAMP} switch host=mbp target={re.escape(str(self.system_b))} current=timeout$")
        self.assertRegex(lines[1], rf"^{STAMP} pass start host=mbp$")
        self.assertEqual(self.calls_made()[0], "verify-pending run --host mbp")

    def test_a_request_landing_during_a_round_runs_another_round(self):
        marker = self.root / "kicked"
        extra = f'if [ ! -e "{marker}" ]; then : > "{marker}"; printf "%s\\n" "{self.system_a}" > "{self.request}"; fi\n'
        self.assertEqual(self.run_pass("mbp", verify_extra=extra).returncode, 0)
        self.assertEqual(self.calls_made(), ["verify-pending run --host mbp", "owner-actions refresh",
                                             "verify-pending run --host mbp", "owner-actions refresh"])
        starts = [line for line in self.lines() if " pass start " in line]
        self.assertEqual(len(starts), 2)
        self.assertTrue(any(line.endswith(" current=yes") for line in self.lines()))
        self.assertFalse(self.request.exists())


class Kick(Scripts):
    def script(self, start_status=0):
        start = self.stub("start", start_status)
        return self.render("kick.sh", {"@path@": "/usr/bin:/bin", "@start@": f"{start} --no-block job"})

    def run_kick(self, *args, home=True, **script):
        return self.run_script(self.script(**script), args, home)

    def test_a_kick_with_a_target_writes_the_request_then_starts_the_job(self):
        done = self.run_kick(str(self.system_b))
        self.assertEqual((done.returncode, done.stdout), (0, ""))
        self.assertEqual(self.request.read_text(), f"{self.system_b}\n")
        self.assertEqual(self.calls_made(), ["start --no-block job"])
        self.assertEqual(sorted(p.name for p in self.state.iterdir()), ["switch-request"])
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)

    def test_a_kick_without_a_target_writes_an_empty_request(self):
        self.assertEqual(self.run_kick().returncode, 0)
        self.assertEqual(self.request.read_text(), "\n")
        self.assertEqual(self.calls_made(), ["start --no-block job"])

    def test_a_failing_start_never_fails_the_kick(self):
        done = self.run_kick(str(self.system_a), start_status=5)
        self.assertEqual(done.returncode, 0)
        self.assertTrue(self.request.exists())

    def test_a_missing_home_exits_zero_without_starting(self):
        done = self.run_kick(str(self.system_a), home=False)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(self.calls_made(), [])

    def test_two_arguments_are_a_usage_error(self):
        done = self.run_kick("a", "b")
        self.assertEqual(done.returncode, 2)
        self.assertIn("verify-pending-kick: usage: verify-pending-kick [TARGET]", done.stderr)
        self.assertFalse((self.home / ".agents").exists())
        self.assertEqual(self.calls_made(), [])


if __name__ == "__main__":
    unittest.main()
