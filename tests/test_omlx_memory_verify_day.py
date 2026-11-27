"""The eleven-m5 verify-tree check: the first full working day after the deploy holds a verify-tree peak.

Runs `agent_tools.hosts.omlx_memory_verify_day` and its committed wrapper as children against a scratch
state directory: which day decides, what makes it met, not met or not yet, and which state is unreadable.
Run: just agent-workflow-tests
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TIER = "fast"

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = "home/common/verify-pending/checks/omlx-memory-verify-day"


class VerifyDayCase(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.dir = Path(scratch.name)

    @property
    def peaks(self):
        return self.dir / "memory-peaks.jsonl"

    def put_state(self, since):
        (self.dir / "memory-watch.json").write_text(json.dumps({"day": "2026-11-27", "verify_records_since": since}))

    def write_day(self, day, runs, peak_gib, peak_at):
        line = {"day": day, "verify_runs": runs, "peak_verify_gib": peak_gib, "peak_verify_at": peak_at}
        with self.peaks.open("a") as peaks:
            peaks.write(json.dumps(line) + "\n")

    def deploy(self):
        self.write_day("2026-11-24", 0, None, None)
        self.write_day("2026-11-25", 4, 1.2, "2026-11-25T18:00:00+00:00")
        self.put_state("2026-11-25")

    def run_check(self):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "python"), "TZ": "UTC"}
        return subprocess.run([sys.executable, "-m", "agent_tools.hosts.omlx_memory_verify_day",
                               "--state-dir", str(self.dir)], capture_output=True, text=True, cwd=ROOT, env=env)

    def answer(self, result):
        return json.loads(result.stdout)


class VerifyDayTest(VerifyDayCase):
    def test_the_first_full_working_day_is_met_with_its_peak_and_time(self):
        self.deploy()
        self.write_day("2026-11-26", 9, 2.7, "2026-11-26T14:03:00+00:00")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.answer(result), {
            "verdict": "met", "day": "2026-11-26", "peak_verify_gib": 2.7,
            "peak_verify_at": "2026-11-26T14:03:00+00:00", "verify_runs": 9})

    def test_the_deploy_day_and_the_older_day_it_rolled_over_are_never_judged(self):
        self.deploy()
        result = self.run_check()
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(self.answer(result), {
            "verdict": "not_yet", "verify_records_since": "2026-11-25", "full_days": 0})

    def test_no_state_waits(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(self.answer(result), {"verdict": "not_yet", "verify_records_since": None, "full_days": 0})

    def test_a_full_day_without_runs_is_skipped_for_the_next(self):
        self.deploy()
        self.write_day("2026-11-26", 0, None, None)
        result = self.run_check()
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(self.answer(result), {
            "verdict": "not_yet", "verify_records_since": "2026-11-25", "full_days": 1})
        self.write_day("2026-11-27", 2, 0.9, "2026-11-27T09:00:00+00:00")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.answer(result)["day"], "2026-11-27")

    def test_a_working_day_without_a_peak_is_not_met(self):
        self.deploy()
        self.write_day("2026-11-26", 3, None, None)
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.answer(result), {
            "verdict": "not_met", "day": "2026-11-26", "reason": "no_peak", "verify_runs": 3})
        self.peaks.unlink()
        self.deploy()
        self.write_day("2026-11-26", 3, True, "2026-11-26T14:03:00+00:00")
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.answer(result)["reason"], "no_peak")

    def test_a_peak_without_its_time_on_the_day_is_not_met(self):
        self.deploy()
        self.write_day("2026-11-26", 3, 2.7, None)
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.answer(result)["reason"], "no_peak_time")
        self.peaks.unlink()
        self.deploy()
        self.write_day("2026-11-26", 3, 2.7, "2026-11-25T23:59:00+00:00")
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.answer(result)["reason"], "no_peak_time")

    def test_an_unreadable_state_or_line_exits_2(self):
        self.peaks.write_text("[1]\n")
        self.put_state("2026-11-25")
        result = self.run_check()
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith("omlx-memory-verify-day:"), result.stderr)
        self.assertEqual(result.stdout, "")
        self.put_state(5)
        result = self.run_check()
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith("omlx-memory-verify-day:"), result.stderr)
        self.assertEqual(result.stdout, "")

    def test_the_wrapper_is_committed_executable_and_runs_the_check(self):
        listing = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", WRAPPER],
                                 capture_output=True, text=True, check=True).stdout
        self.assertTrue(listing.startswith("100755"), listing)
        self.deploy()
        self.write_day("2026-11-26", 9, 2.7, "2026-11-26T14:03:00+00:00")
        env = {**os.environ, "TZ": "UTC"}
        result = subprocess.run([str(ROOT / WRAPPER), "--state-dir", str(self.dir)],
                                capture_output=True, text=True, cwd=ROOT, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.answer(result)["verdict"], "met")


if __name__ == "__main__":
    unittest.main()
