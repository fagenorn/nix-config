"""The eleven-m5 census day check: the day after the deploy holds the unowned figure on every sample.

Runs `agent_tools.hosts.omlx_memory_census_day` and its committed wrapper as children against a scratch
state directory: what makes the day after the deploy met, not met or not yet, how a day line is
checked against the sample records, and which events are kept near the peak.
Run: just agent-workflow-tests
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

TIER = "fast"

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = "home/common/verify-pending/checks/omlx-memory-census-day"
GIB = 1024 ** 3


def minute_lines(day, n, unowned=GIB, peak=None, events=None):
    """`n` sample lines, one per minute from midnight of `day`, with the figure, peak and events given."""
    start = datetime.fromisoformat(f"{day}T00:00:00+00:00")
    lines = []
    for index in range(n):
        at = start + timedelta(minutes=index)
        hhmm = at.strftime("%H:%M")
        figure = peak[1] if peak is not None and peak[0] == hhmm else unowned
        lines.append({"at": at.isoformat(), "unowned_bytes": figure, "events": list((events or {}).get(hhmm, []))})
    return lines


class RecordsCase(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.dir = Path(scratch.name)

    def put_state(self, records_since, records_since_at=None):
        state = {"day": "2026-11-27", "records_since": records_since}
        if records_since_at is not None:
            state["records_since_at"] = records_since_at
        (self.dir / "memory-watch.json").write_text(json.dumps(state))

    def write_day(self, day, samples, census_samples, peak_gib, peak_at):
        line = {"day": day, "samples": samples, "census_samples": census_samples,
                "peak_unowned_gib": peak_gib, "peak_unowned_at": peak_at}
        with (self.dir / "memory-peaks.jsonl").open("a") as peaks:
            peaks.write(json.dumps(line) + "\n")

    def write_samples(self, day, lines):
        (self.dir / "samples").mkdir(exist_ok=True)
        (self.dir / "samples" / f"{day}.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))

    def healthy(self, day, events=None):
        self.write_day(day, 1440, 1440, 9.0, f"{day}T11:00:00+00:00")
        self.write_samples(day, minute_lines(day, 1440, peak=("11:00", 9 * GIB), events=events))

    def arrange_full_day(self):
        self.put_state("2026-11-26")
        self.write_day("2026-11-26", 1000, 700, 3.0, "2026-11-26T09:00:00+00:00")
        started = {"kind": "vm_started", "pid": 1}
        kill = {"kind": "floor_kill", "at": "2026-11-27T11:20:00+00:00"}
        self.healthy("2026-11-27", events={"10:45": [started], "13:00": [started], "12:00": [kill]})
        self.write_samples("2026-11-28", [{"at": "2026-11-28T00:05:00+00:00", "unowned_bytes": GIB, "events": [
            {"kind": "verify_run", "held_from": "2026-11-27T10:50:00+00:00", "held_until": "2026-11-28T00:04:00+00:00"},
            {"kind": "verify_run", "held_from": "2026-11-27T01:00:00+00:00", "held_until": "2026-11-27T02:00:00+00:00"}]}])

    def run_check(self):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "python")}
        return subprocess.run([sys.executable, "-m", "agent_tools.hosts.omlx_memory_census_day",
                               "--state-dir", str(self.dir)], capture_output=True, text=True, cwd=ROOT, env=env)

    def verdict(self, result):
        return json.loads(result.stdout)


class CensusDayTest(RecordsCase):
    def test_a_full_day_whose_records_show_the_figure_is_met(self):
        self.arrange_full_day()
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        answer = self.verdict(result)
        self.assertEqual({key: answer[key] for key in answer if key != "events_near_peak"}, {
            "verdict": "met", "day": "2026-11-27", "records_since": "2026-11-26", "samples": 1440,
            "census_samples": 1440, "peak_unowned_gib": 9.0, "peak_unowned_at": "2026-11-27T11:00:00+00:00"})
        near = answer["events_near_peak"]
        self.assertEqual(len(near), 3, near)
        self.assertEqual((near[0]["kind"], near[0]["sample_at"]), ("vm_started", "2026-11-27T10:45:00+00:00"))
        self.assertEqual((near[1]["kind"], near[1]["sample_at"]), ("floor_kill", "2026-11-27T12:00:00+00:00"))
        self.assertEqual((near[2]["kind"], near[2]["sample_at"]), ("verify_run", "2026-11-28T00:05:00+00:00"))
        self.assertEqual(near[2]["held_from"], "2026-11-27T10:50:00+00:00")

    def test_a_truncated_sample_file_is_not_met(self):
        self.put_state("2026-11-26")
        self.write_day("2026-11-27", 1440, 1440, 9.0, "2026-11-27T11:00:00+00:00")
        self.write_samples("2026-11-27", minute_lines("2026-11-27", 1440, peak=("11:00", 9 * GIB))[:1300])
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        answer = self.verdict(result)
        self.assertEqual((answer["reason"], answer["records"], answer["samples"]), ("records_disagree", 1300, 1440))

    def test_a_peak_the_records_do_not_reach_is_not_met(self):
        self.put_state("2026-11-26")
        self.write_day("2026-11-27", 1440, 1440, 9.0, "2026-11-27T11:00:00+00:00")
        self.write_samples("2026-11-27", minute_lines("2026-11-27", 1440))
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        answer = self.verdict(result)
        self.assertEqual(answer["reason"], "records_disagree")
        self.assertEqual(answer["records_peak_gib"], 1.0)
        self.assertEqual(answer["records_peak_at"], "2026-11-27T00:00:00+00:00")

    def test_a_legacy_day_before_the_deploy_is_not_judged(self):
        self.put_state("2026-11-26")
        self.write_day("2026-11-25", 1440, 0, None, None)
        self.write_day("2026-11-26", 400, 400, 2.0, "2026-11-26T20:00:00+00:00")
        result = self.run_check()
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(self.verdict(result), {"verdict": "not_yet", "records_since": "2026-11-26", "day": "2026-11-27"})

    def test_a_missing_target_day_is_not_met_even_when_a_later_day_is_healthy(self):
        self.put_state("2026-11-26")
        self.write_day("2026-11-26", 1000, 700, 3.0, "2026-11-26T09:00:00+00:00")
        self.healthy("2026-11-28")
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        answer = self.verdict(result)
        self.assertEqual((answer["reason"], answer["day"]), ("missing_day", "2026-11-27"))

    def test_a_sample_without_a_figure_is_not_met(self):
        self.put_state("2026-11-26")
        self.write_day("2026-11-27", 1440, 1439, 9.0, "2026-11-27T11:00:00+00:00")
        lines = minute_lines("2026-11-27", 1440, peak=("11:00", 9 * GIB))
        lines[5]["unowned_bytes"] = None
        self.write_samples("2026-11-27", lines)
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        answer = self.verdict(result)
        self.assertEqual((answer["reason"], answer["missing"]), ("missing_figure", 1))

    def test_a_day_with_few_samples_is_not_met(self):
        self.put_state("2026-11-26")
        self.write_day("2026-11-27", 1000, 1000, 9.0, "2026-11-27T11:00:00+00:00")
        self.write_samples("2026-11-27", minute_lines("2026-11-27", 1000, peak=("11:00", 9 * GIB)))
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.verdict(result)["reason"], "few_samples")

    def test_a_full_day_without_its_sample_file_is_not_met(self):
        self.put_state("2026-11-26")
        self.write_day("2026-11-27", 1440, 1440, 9.0, "2026-11-27T11:00:00+00:00")
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.verdict(result)["reason"], "no_samples")

    def test_no_state_is_not_yet(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(self.verdict(result), {"verdict": "not_yet", "records_since": None, "day": None})

    def test_a_line_that_is_not_json_is_unreadable(self):
        self.put_state("2026-11-26")
        (self.dir / "memory-peaks.jsonl").write_text("{\n")
        result = self.run_check()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("omlx-memory-census-day:", result.stderr)

    def test_the_wrapper_is_executable_and_runs_the_check(self):
        listing = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", WRAPPER],
                                 capture_output=True, text=True, check=True).stdout
        self.assertTrue(listing.startswith("100755"), listing)
        self.arrange_full_day()
        result = subprocess.run([str(ROOT / WRAPPER), "--state-dir", str(self.dir)],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.verdict(result)["verdict"], "met")

    def test_a_day_without_a_peak_time_is_not_met(self):
        self.put_state("2026-11-26")
        self.write_day("2026-11-27", 1440, 1440, 9.0, None)
        self.write_samples("2026-11-27", minute_lines("2026-11-27", 1440, peak=("11:00", 9 * GIB)))
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.verdict(result)["reason"], "no_peak")

    def test_an_event_near_the_peak_is_published_by_its_kind_and_timing_only(self):
        self.put_state("2026-11-26")
        run = {"kind": "verify_run", "repository": "o/r", "command": "env API_TOKEN=example just test", "exit": 0,
               "held_from": "2026-11-27T10:50:00+00:00", "held_until": "2026-11-27T11:10:00+00:00"}
        kill = {"kind": "floor_kill", "at": "2026-11-27T11:20:00+00:00", "reason": "floor", "owner": "secret-owner",
                "root_pid": 300, "signals": "term+kill", "tree_gib": 146.0}
        disk = {"kind": "ram_disk_attached", "dev": "/dev/disk5", "mount": "/Volumes/private-mount", "gib": 1.0}
        self.healthy("2026-11-27", events={"11:05": [run, kill, disk]})
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.verdict(result)["events_near_peak"], [
            {"kind": "verify_run", "sample_at": "2026-11-27T11:05:00+00:00",
             "held_from": "2026-11-27T10:50:00+00:00", "held_until": "2026-11-27T11:10:00+00:00"},
            {"kind": "floor_kill", "sample_at": "2026-11-27T11:05:00+00:00", "at": "2026-11-27T11:20:00+00:00"},
            {"kind": "ram_disk_attached", "sample_at": "2026-11-27T11:05:00+00:00"}])
        for secret in ("API_TOKEN", "secret-owner", "private-mount"):
            self.assertNotIn(secret, result.stdout)

    def test_a_deploy_whose_first_sample_came_just_after_midnight_judges_that_day(self):
        self.put_state("2026-11-26", "2026-11-26T00:00:30+00:00")
        self.healthy("2026-11-27")
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        answer = self.verdict(result)
        self.assertEqual((answer["reason"], answer["day"]), ("missing_day", "2026-11-26"))

    def test_a_deploy_whose_first_sample_came_late_in_its_day_judges_the_next_day(self):
        self.put_state("2026-11-26", "2026-11-26T09:00:30+00:00")
        self.healthy("2026-11-27")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.verdict(result)["day"], "2026-11-27")

    def test_a_day_of_copies_of_the_day_before_is_not_met(self):
        self.put_state("2026-11-26")
        self.write_day("2026-11-27", 1440, 1440, 9.0, "2026-11-26T11:00:00+00:00")
        self.write_samples("2026-11-27", minute_lines("2026-11-26", 1440, peak=("11:00", 9 * GIB)))
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        answer = self.verdict(result)
        self.assertEqual((answer["reason"], answer["outside_day"]), ("bad_timestamps", 1440))

    def test_a_day_of_one_reading_repeated_is_not_met(self):
        self.put_state("2026-11-26")
        self.write_day("2026-11-27", 1440, 1440, 9.0, "2026-11-27T11:00:00+00:00")
        lines = minute_lines("2026-11-27", 1440)
        for line in lines:
            line["at"] = "2026-11-27T11:00:00+00:00"
        lines[0]["unowned_bytes"] = 9 * GIB
        self.write_samples("2026-11-27", lines)
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        answer = self.verdict(result)
        self.assertEqual((answer["reason"], answer["repeated"]), ("bad_timestamps", 1439))

    def test_events_before_a_peak_just_after_midnight_come_from_the_day_before(self):
        self.put_state("2026-11-25")
        self.write_day("2026-11-26", 1440, 1440, 9.0, "2026-11-26T00:05:00+00:00")
        self.write_samples("2026-11-26", minute_lines("2026-11-26", 1440, peak=("00:05", 9 * GIB)))
        kill = {"kind": "floor_kill", "at": "2026-11-25T23:55:00+00:00", "owner": "o"}
        older = {"kind": "floor_kill", "at": "2026-11-25T22:00:00+00:00", "owner": "o"}
        self.write_samples("2026-11-25", [
            {"at": "2026-11-25T22:00:30+00:00", "unowned_bytes": GIB, "events": [older]},
            {"at": "2026-11-25T23:55:30+00:00", "unowned_bytes": GIB, "events": [kill]}])
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.verdict(result)["events_near_peak"], [
            {"kind": "floor_kill", "sample_at": "2026-11-25T23:55:30+00:00", "at": "2026-11-25T23:55:00+00:00"}])


if __name__ == "__main__":
    unittest.main()
