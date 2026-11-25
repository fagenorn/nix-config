"""The post-deploy check of runner.log's interrupted lines: one re-run, then held, per pass.

Runs `agent_tools.verification.interrupted_reruns_check` and its committed wrapper as children against
scratch logs: when no interrupted line exists yet, when every check a signal ended was started once
more and then held, and when a pass ran a check a third time or held it with no re-run.
Run: just agent-workflow-tests
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_tools.verification import verify_interrupt, verify_run

TIER = "fast"

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/interrupted-reruns"
NOW = datetime(2026, 11, 24, 15, 29, 4, tzinfo=timezone.utc)
START = "2026-11-24T15:29:00Z pass start host=eleven-m5"
END = "2026-11-24T15:30:00Z pass end host=eleven-m5 verify=0 owner_actions=0 cleanup_fix=0"


def entry(check, then, at=NOW):
    return verify_interrupt.format_line(
        at, host="eleven-m5", repo="octo/widgets", issue=7, check=check, ac="AC4", signal=15,
        next_at=at + timedelta(seconds=60), then=then,
    )


def child(*argv, home=None, wrapper=False):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "python")}
    if home is not None:
        env["HOME"] = str(home)
    module = [sys.executable, "-m", "agent_tools.verification.interrupted_reruns_check"]
    command = [str(ROOT / WRAPPER)] if wrapper else module
    done = subprocess.run([*command, *argv], capture_output=True, text=True, env=env, cwd=ROOT if wrapper else None)
    return done.returncode, json.loads(done.stdout) if done.stdout else None, done.stderr


class InterruptedRerunsCheckTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.dir = Path(scratch.name)

    def log(self, *lines, name="runner.log", under=None):
        path = (under or self.dir) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{line}\n" for line in lines))
        return path

    def test_a_check_rerun_once_then_held_is_met(self):
        path = self.log(START, entry(0, "rerun"), entry(1, "rerun"), entry(0, "held"))
        code, out, _ = child("--log", path)
        self.assertEqual((code, out), (0, {"verdict": "met", "interrupted": 3, "checks": 2}))

    def test_no_interrupted_line_is_not_yet(self):
        for name, argv in {
            "quiet log": lambda: ["--log", self.log(START, END)],
            "missing file": lambda: ["--log", self.dir / "absent.log"],
        }.items():
            with self.subTest(name):
                code, out, _ = child(*argv())
                self.assertEqual((code, out), (75, {"verdict": "not_yet", "interrupted": 0}))

    def test_a_third_run_or_a_held_first_is_not_met(self):
        for then in (["rerun", "rerun"], ["rerun", "held", "rerun"], ["held"]):
            with self.subTest(then=then):
                path = self.log(START, *[entry(0, item) for item in then])
                code, out, _ = child("--log", path)
                self.assertEqual(code, 1)
                self.assertEqual(out["verdict"], "not_met")
                self.assertEqual(out["violations"], [
                    {"at": "2026-11-24T15:29:04Z", "repo": "octo/widgets", "issue": 7, "check": 0, "then": then},
                ])

    def test_passes_split_the_groups(self):
        path = self.log(START, entry(0, "rerun"), entry(0, "held"), START, entry(0, "rerun"), entry(0, "held"))
        code, out, _ = child("--log", path)
        self.assertEqual((code, out), (0, {"verdict": "met", "interrupted": 4, "checks": 2}))

    def test_the_rotated_log_is_read_first_from_home(self):
        state = self.dir / "home" / ".agents" / "state" / "verify-pending"
        self.log(START, entry(0, "rerun"), entry(1, "rerun"), name="runner.log.1", under=state)
        self.log(entry(0, "rerun"), under=state)
        code, out, _ = child(home=self.dir / "home")
        self.assertEqual(code, 1)
        self.assertEqual(out["interrupted"], 3)
        self.assertEqual([(v["check"], v["then"]) for v in out["violations"]], [(0, ["rerun", "rerun"])])

    def test_an_unreadable_log_is_exit_2(self):
        code, out, err = child("--log", self.dir)
        self.assertEqual(code, 2)
        self.assertIsNone(out)
        self.assertTrue(err)

    def test_the_wrapper_is_committed_executable_and_runs_the_module(self):
        listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", WRAPPER], capture_output=True, text=True)
        self.assertTrue(listed.stdout.startswith("100755 "), listed.stdout)
        path = self.log(START, entry(0, "rerun"), entry(0, "held"))
        code, out, _ = child("--log", path, wrapper=True)
        self.assertEqual((code, out["verdict"]), (0, "met"))
        self.assertIsNone(verify_run.LINUX_ONLY.search((ROOT / WRAPPER).read_text()))


if __name__ == "__main__":
    unittest.main()
