"""The eleven-m5 memory floor's post-deploy verify check: a quiet week and the held oMLX priority.

Runs `agent_tools.hosts.memory_floor_check` and its committed wrapper as children against scratch
record, state and reports directories: when the week is not yet, met or not met (a panic report or
an oMLX jetsam exit after the floor started), and when the priority record shows the declared
value held without a reset.
Run: just agent-workflow-tests
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

TIER = "fast"

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = "home/common/verify-pending/checks/memory-floor"
SINCE = "2026-11-25T12:00:00+00:00"
DAYS = ["2026-11-25", "2026-11-26", "2026-11-27", "2026-11-28", "2026-11-29", "2026-11-30", "2026-12-01"]
PANIC = "panic-full-2026-11-24-045716.0002.panic"
LATER_PANIC = "panic-full-2026-11-28-101500.0002.panic"


def stamp(day):
    return datetime.fromisoformat(f"{day}T12:00:00+00:00").timestamp()


class Scratch(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)
        self.record = self.scratch / "floor.json"
        self.state = self.scratch / "state"
        self.reports = self.scratch / "reports"
        self.state.mkdir()
        self.reports.mkdir()

    def child(self, *argv, wrapper=False):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "python"), "TZ": "UTC"}
        command = ([str(ROOT / WRAPPER)] if wrapper
                   else [sys.executable, "-m", "agent_tools.hosts.memory_floor_check"])
        return subprocess.run([*command, *argv], capture_output=True, text=True, env=env, cwd=ROOT if wrapper else self.scratch)


class WeekTest(Scratch):
    def arrange(self, jetsam=None, state_jetsam=0, panics=None):
        self.record.write_text(json.dumps({"since": SINCE}))
        lines = [{"day": day, "jetsam_exits": (jetsam or {}).get(day, 0)} for day in DAYS]
        (self.state / "memory-peaks.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
        (self.state / "memory-watch.json").write_text(json.dumps({"day": "2026-12-02", "jetsam_exits": state_jetsam}))
        for name, day in {PANIC: "2026-11-24", **(panics or {})}.items():
            path = self.reports / name
            path.write_text("panic")
            os.utime(path, (stamp(day), stamp(day)))

    def week(self, now="2026-12-02T13:00:00+00:00"):
        return self.child("week", "--record", str(self.record), "--state-dir", str(self.state),
                          "--reports-dir", str(self.reports), "--now", now)

    def test_a_quiet_week_after_the_floor_started_is_met(self):
        self.arrange()
        result = self.week()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         {"verdict": "met", "since": SINCE, "panics": [], "jetsam_exits": 0})

    def test_the_week_is_not_yet_before_seven_days(self):
        self.arrange()
        result = self.week(now="2026-11-30T13:00:00+00:00")
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"verdict": "not_yet", "since": SINCE})

    def test_a_panic_after_the_floor_started_is_not_met(self):
        self.arrange(panics={LATER_PANIC: "2026-11-28"})
        result = self.week()
        self.assertEqual(result.returncode, 1, result.stderr)
        answer = json.loads(result.stdout)
        self.assertEqual(answer["verdict"], "not_met")
        self.assertEqual(answer["panics"], [LATER_PANIC])

    def test_an_omlx_jetsam_exit_is_not_met(self):
        rows = {"a_peaks_line": {"jetsam": {"2026-11-27": 1}, "state_jetsam": 0},
                "todays_state": {"jetsam": None, "state_jetsam": 1}}
        for name, row in rows.items():
            with self.subTest(name):
                self.arrange(**row)
                result = self.week()
                self.assertEqual(result.returncode, 1, result.stderr)
                answer = json.loads(result.stdout)
                self.assertEqual(answer["verdict"], "not_met")
                self.assertEqual(answer["jetsam_exits"], 1)
                self.assertEqual(answer["panics"], [])

    def assert_unreadable(self, result):
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr)

    def test_a_reports_dir_that_cannot_be_listed_is_unreadable_not_met(self):
        for name in ("missing", "not_a_directory"):
            with self.subTest(name):
                self.arrange(panics={LATER_PANIC: "2026-11-28"})
                shutil.rmtree(self.reports)
                if name == "not_a_directory":
                    self.reports.write_text("x")
                self.assert_unreadable(self.week())
                if self.reports.is_file():
                    self.reports.unlink()
                self.reports.mkdir(exist_ok=True)

    def test_a_missing_peaks_file_or_state_file_is_unreadable_not_met(self):
        for name in ("memory-peaks.jsonl", "memory-watch.json"):
            with self.subTest(name):
                self.arrange()
                (self.state / name).unlink()
                self.assert_unreadable(self.week())


class PriorityTest(Scratch):
    def priority(self):
        return self.child("priority", "--record", str(self.record))

    def test_the_priority_check_reads_the_record(self):
        def record(kernel, declared, reads, resets, error=None, pid=73552):
            return {"since": SINCE, "omlx_pid": pid, "omlx_kernel_priority": kernel,
                    "omlx_priority_reads": reads, "omlx_priority_resets": resets,
                    "declared_priority": declared, "omlx_priority_error": error}

        rows = {
            "held": (record(100, 100, 5, 0), 0),
            "above_declared": (record(200, 190, 5, 0), 0),
            "refused": (record(40, 100, 5, 0, "EPERM"), 1),
            "put_back_each_sample": (record(40, 100, 5, 4), 1),
            "put_back_once": (record(100, 100, 5, 1), 1),
            "first_read": (record(40, 100, 1, 0), 75),
            "no_pid": (record(None, 100, 5, 0, pid=None), 75),
            "no_record": (None, 75),
        }
        for name, (content, code) in rows.items():
            with self.subTest(name):
                self.record.unlink(missing_ok=True)
                if content is not None:
                    self.record.write_text(json.dumps(content))
                result = self.priority()
                self.assertEqual(result.returncode, code, result.stderr)
                answer = json.loads(result.stdout)
                if name == "put_back_each_sample":
                    self.assertEqual(answer["verdict"], "not_met")
                    self.assertEqual(answer["omlx_priority_resets"], 4)
                if name == "refused":
                    self.assertEqual(answer["omlx_priority_error"], "EPERM")


class UnreadableTest(Scratch):
    def test_a_record_that_is_not_json_is_unreadable(self):
        self.record.write_text("{")
        result = self.child("priority", "--record", str(self.record))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr)


class WrapperTest(Scratch):
    def test_the_wrapper_is_committed_executable_and_runs_the_check(self):
        listed = subprocess.run(["git", "ls-files", "-s", WRAPPER], capture_output=True, text=True,
                                cwd=ROOT, check=True).stdout
        self.assertTrue(listed.startswith("100755"), listed)
        self.record.write_text(json.dumps({"since": SINCE, "omlx_pid": 7, "omlx_kernel_priority": 100,
                                           "omlx_priority_reads": 5, "omlx_priority_resets": 0,
                                           "declared_priority": 100, "omlx_priority_error": None}))
        result = self.child("priority", "--record", str(self.record), wrapper=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["verdict"], "met")


if __name__ == "__main__":
    unittest.main()
