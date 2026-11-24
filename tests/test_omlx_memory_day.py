"""The eleven-m5 memory day check: a loaded full day under budget with two verify runs and a CI job.

Runs `agent_tools.hosts.omlx_memory_day` and its committed wrapper as children against a scratch
state directory and a scratch verify-slot history: what makes a day full, loaded, met, not met or
not yet, and how the verify runs of the local day are counted.
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
WRAPPER = "home/common/verify-pending/checks/omlx-memory-day"


def LINE(day, over=False, jetsam=0, ci=1, loaded=1440, min_loaded=26.0, others=40.0, priority=100):
    return {
        "day": day, "peak_used_gib": 230.0, "peak_others_gib": others, "peak_omlx_gib": 174.5,
        "min_available_gib": 26.0, "others_budget_gib": 46, "over_budget": over,
        "jetsam_exits": jetsam, "peak_ci_jobs": ci, "samples": 1440, "loaded_samples": loaded,
        "min_loaded_available_gib": min_loaded, "floor_gib": 16, "omlx_jetsam_priority": priority,
        "declared_jetsam_priority": 100, "peak_fseventsd_gib": 0.1, "fseventsd_restarts": 0,
    }


def RUN(started, held):
    return {"command": "just test", "exit": 0, "held_seconds": held, "repository": "o/r",
            "started": started, "waited_seconds": 0.0}


TWO_RUNS = [RUN("2026-11-25T10:00:00Z", 600.0), RUN("2026-11-25T10:05:00Z", 600.0)]


def dump(record):
    return json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"


class CheckTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)
        self.state = self.scratch / "state"
        self.state.mkdir()
        self.history = self.scratch / "history.jsonl"

    def write(self, lines, runs, since="2026-11-24"):
        (self.state / "memory-watch.json").write_text(json.dumps({"since": since, "day": "2026-11-26"}))
        (self.state / "memory-peaks.jsonl").write_text("".join(dump(line) for line in lines))
        self.history.write_text("".join(dump(run) for run in runs))

    def run_check(self, tz="UTC", extra_env=None, history_args=True, argv=None):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "python"), "TZ": tz, **(extra_env or {})}
        if argv is None:
            argv = ["--state-dir", str(self.state)]
            if history_args:
                argv += ["--slot-history", str(self.history)]
        return subprocess.run([sys.executable, "-m", "agent_tools.hosts.omlx_memory_day", *argv],
                              capture_output=True, text=True, env=env, cwd=self.scratch)

    def verdict(self, result):
        return json.loads(result.stdout)

    def test_a_loaded_day_under_budget_is_met(self):
        self.write([LINE("2026-11-24"), LINE("2026-11-25")], TWO_RUNS)
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        answer = self.verdict(result)
        self.assertEqual(answer["verdict"], "met")
        self.assertEqual(answer["day"], "2026-11-25")
        self.assertEqual(answer["peak_verify_runs"], 2)
        self.assertEqual(answer["peak_ci_jobs"], 1)
        self.assertEqual(answer["omlx_jetsam_priority"], 100)

    def test_the_first_partial_day_never_counts(self):
        self.write([LINE("2026-11-24")], [RUN("2026-11-24T10:00:00Z", 600.0), RUN("2026-11-24T10:05:00Z", 600.0)])
        result = self.run_check()
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(self.verdict(result)["full_days"], 0)

    def test_a_jetsam_exit_is_not_met(self):
        self.write([LINE("2026-11-25", jetsam=1)], TWO_RUNS)
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.verdict(result)["reason"], "jetsam")

    def test_a_day_over_budget_is_not_met(self):
        self.write([LINE("2026-11-25", over=True)], [])
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.verdict(result)["reason"], "over_budget")

    def test_a_day_without_two_verify_runs_at_once_waits(self):
        self.write([LINE("2026-11-25")], [RUN("2026-11-25T10:00:00Z", 600.0), RUN("2026-11-25T11:00:00Z", 600.0)])
        self.assertEqual(self.run_check().returncode, 75)

    def test_a_day_without_a_ci_job_waits(self):
        self.write([LINE("2026-11-25", ci=0)], TWO_RUNS)
        self.assertEqual(self.run_check().returncode, 75)

    def test_no_state_is_not_yet(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(self.verdict(result), {"verdict": "not_yet", "full_days": 0})

    def test_the_wrapper_is_executable_and_runs_the_check(self):
        listing = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", WRAPPER],
                                 capture_output=True, text=True, check=True).stdout
        self.assertTrue(listing.startswith("100755"), listing)
        self.write([LINE("2026-11-24"), LINE("2026-11-25")], TWO_RUNS)
        result = subprocess.run(
            [str(ROOT / WRAPPER), "--state-dir", str(self.state), "--slot-history", str(self.history)],
            capture_output=True, text=True, cwd=ROOT, env={**os.environ, "TZ": "UTC"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.verdict(result)["verdict"], "met")

    def test_a_day_the_model_was_never_loaded_waits(self):
        self.write([LINE("2026-11-25", loaded=0, min_loaded=None)], TWO_RUNS)
        result = self.run_check()
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(self.verdict(result)["full_days"], 1)
        self.write([{**LINE("2026-11-25", loaded=0, min_loaded=None), "samples": 0}], TWO_RUNS)
        self.assertEqual(self.run_check().returncode, 75)

    def test_a_day_loaded_under_nine_tenths_waits(self):
        self.write([LINE("2026-11-25", loaded=1295)], TWO_RUNS)
        self.assertEqual(self.run_check().returncode, 75)
        self.write([LINE("2026-11-25", loaded=1296)], TWO_RUNS)
        self.assertEqual(self.run_check().returncode, 0)

    def test_a_loaded_day_under_the_floor_is_not_met(self):
        self.write([LINE("2026-11-25", min_loaded=10.0)], TWO_RUNS)
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.verdict(result)["reason"], "floor")

    def test_the_default_history_is_the_slot_directory(self):
        slots = self.scratch / "slots"
        slots.mkdir()
        self.write([LINE("2026-11-25")], TWO_RUNS)
        self.history.rename(slots / "history.jsonl")
        result = self.run_check(extra_env={"VERIFY_SLOT_DIR": str(slots)}, history_args=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_an_unreadable_state_exits_2(self):
        (self.state / "memory-watch.json").write_text("{")
        result = self.run_check()
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.strip())
        self.assertEqual(result.stdout, "")

    def test_a_loaded_day_without_an_others_reading_waits(self):
        self.write([LINE("2026-11-25", others=None)], TWO_RUNS)
        result = self.run_check()
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(self.verdict(result)["full_days"], 1)

    def test_a_run_that_held_no_slot_is_not_counted(self):
        self.write([LINE("2026-11-25")], [RUN("2026-11-25T10:00:00Z", 600.0), RUN("2026-11-25T10:05:00Z", None)])
        result = self.run_check()
        self.assertEqual(result.returncode, 75)
        self.assertEqual(result.stderr, "")

    def test_runs_count_on_the_local_day(self):
        self.write([LINE("2026-11-25")], [RUN("2026-11-26T03:00:00Z", 600.0), RUN("2026-11-26T03:05:00Z", 600.0)])
        result = self.run_check(tz="EST5")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.verdict(result)["day"], "2026-11-25")

    def test_omlx_below_its_declared_jetsam_priority_is_not_met(self):
        self.write([LINE("2026-11-25", priority=40)], TWO_RUNS)
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.verdict(result)["reason"], "jetsam_priority")

    def test_an_unread_jetsam_priority_waits(self):
        self.write([LINE("2026-11-25", priority=None)], TWO_RUNS)
        result = self.run_check()
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(self.verdict(result)["full_days"], 1)


if __name__ == "__main__":
    unittest.main()
