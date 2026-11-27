"""The eleven-m5 reactive restart day check: the first whole day after the deploy logged every due restart.

Runs `agent_tools.hosts.omlx_reactive_restart_day` and its committed wrapper as children against a scratch
state directory: what makes the watched day met, not met or not yet, how the sample lines are replayed
against the restart records, and how a floor kill is judged by its own time.
Run: just agent-workflow-tests
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

TIER = "fast"

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = "home/common/verify-pending/checks/omlx-reactive-restart-day"
GIB = 1024 ** 3
LIMITS = {"trigger_bytes": 25 * GIB, "samples": 3, "room_bytes": 16 * GIB, "min_interval_seconds": 1800}
SINCE = "2026-11-27T15:00:00+00:00"
PREVIOUS, TARGET, NEXT = "2026-11-27", "2026-11-28", "2026-11-29"


def minute_lines(day, n=1440, over=(), events=None, null=False, floor=0):
    """`n` sample lines, one per minute from midnight of `day`: a figure of 2 GiB, 30 GiB at the `over` minutes.

    `floor` is each line's `floor_kills`, the floor record's count (None when the record was not read)."""
    start = datetime.fromisoformat(f"{day}T00:00:00+00:00")
    lines = []
    for index in range(n):
        at = start + timedelta(minutes=index)
        hhmm = at.strftime("%H:%M")
        unowned = 29 * GIB if hhmm in over else GIB
        lines.append({"at": at.isoformat(), "unowned_bytes": None if null else unowned, "compressor_bytes": GIB,
                      "floor_kills": floor, "events": list((events or {}).get(hhmm, []))})
    return lines


def record(at, outcome="restarted", **more):
    line = {"id": at, "at": at, "outcome": outcome, "reason": "stayed over the line", "available_bytes": 20 * GIB,
            "unowned_bytes": 29 * GIB, "compressor_bytes": GIB, "figure_bytes": 30 * GIB, "streak": 3}
    line.update(more)
    return line


def kill(at):
    return {"kind": "floor_kill", "at": at, "reason": "floor", "owner": "owner"}


class RestartDayTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.dir = Path(scratch.name)

    def put_state(self, since_at=SINCE, limits=LIMITS, **more):
        """The restart state; `hold_since_at` (default `since_at`) is the first sample the hold rule saw."""
        state = {"since_at": since_at, "hold_since_at": since_at, "limits": limits, **more}
        (self.dir / "omlx-restart.json").write_text(json.dumps(state))

    def test_a_state_an_older_watcher_wrote_is_not_yet_whatever_its_since_at(self):
        old = {"since_at": "2026-11-20T15:00:00+00:00", "limits": LIMITS}
        (self.dir / "omlx-restart.json").write_text(json.dumps(old))
        for day in ("2026-11-20", "2026-11-21", PREVIOUS, TARGET):
            self.write_day(day)
        result = self.run_check()
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(self.verdict(result), {"verdict": "not_yet", "day": None})

    def test_the_target_day_follows_the_first_deploy_of_the_hold_rule_not_the_older_since_at(self):
        self.put_state(since_at="2026-11-20T15:00:00+00:00", hold_since_at=SINCE)
        self.write_day("2026-11-21")
        self.write_day(PREVIOUS)
        result = self.run_check()
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(self.verdict(result), {"verdict": "not_yet", "day": TARGET})

    def write_day(self, day, samples=1440):
        with (self.dir / "memory-peaks.jsonl").open("a") as peaks:
            peaks.write(json.dumps({"day": day, "samples": samples}) + "\n")

    def write_samples(self, day, lines):
        (self.dir / "samples").mkdir(exist_ok=True)
        (self.dir / "samples" / f"{day}.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))

    def write_records(self, lines):
        (self.dir / "omlx-restarts.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))

    def healthy_target(self, over=(), events=None, records=(), previous=None):
        shutil.rmtree(self.dir / "samples", ignore_errors=True)
        (self.dir / "memory-peaks.jsonl").unlink(missing_ok=True)
        self.put_state()
        self.write_day(PREVIOUS)
        self.write_day(TARGET)
        self.write_samples(TARGET, minute_lines(TARGET, over=over, events=events))
        self.write_samples(NEXT, minute_lines(NEXT, 1))
        if previous is not None:
            self.write_samples(PREVIOUS, previous)
        self.write_records(list(records))

    def run_check(self):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "python")}
        return subprocess.run([sys.executable, "-m", "agent_tools.hosts.omlx_reactive_restart_day",
                               "--state-dir", str(self.dir)], capture_output=True, text=True, cwd=ROOT, env=env)

    def verdict(self, result):
        return json.loads(result.stdout)

    def assertNotMet(self, reason, **more):
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        answer = self.verdict(result)
        self.assertEqual(answer["reason"], reason, answer)
        for key, value in more.items():
            self.assertEqual(answer[key], value, answer)

    def assertMet(self, **more):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        answer = self.verdict(result)
        for key, value in more.items():
            self.assertEqual(answer[key], value, answer)

    def test_a_watched_day_with_a_logged_restart_and_no_kill_over_the_line_is_met(self):
        self.healthy_target(over=("10:00", "10:01", "10:02", "10:03"),
                            events={"14:01": [kill("2026-11-28T14:00:20+00:00")]},
                            records=[record("2026-11-28T10:02:00+00:00")])
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.verdict(result), {
            "verdict": "met", "day": TARGET, "samples": 1440, "floor_kills": 1, "episodes": 1, "restarts": 1,
            "deferrals": 0, "failures": 0, "interruptions": 0})

    def test_no_reactive_watcher_yet_is_not_yet(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(self.verdict(result), {"verdict": "not_yet", "day": None})

    def test_a_day_not_yet_finished_is_not_yet(self):
        self.put_state()
        self.write_day(PREVIOUS)
        result = self.run_check()
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(self.verdict(result), {"verdict": "not_yet", "day": TARGET})

    def test_a_missing_day_line_with_a_later_one_is_not_met(self):
        self.put_state()
        self.write_day(PREVIOUS)
        self.write_day(NEXT)
        self.assertNotMet("missing_day")

    def test_a_day_without_its_sample_file_is_not_met(self):
        self.put_state()
        self.write_day(TARGET)
        self.assertNotMet("no_samples")

    def test_a_sample_file_that_does_not_hold_the_watched_day_is_not_met(self):
        full = minute_lines(TARGET)
        cases = {
            "truncated": (1440, full[:1300], "records_disagree", {"records": 1300, "samples": 1440}),
            "repeated": (1440, full[:1439] + [full[600]], "bad_timestamps", {"repeated": 1}),
            "next day": (1440, full[:1439] + minute_lines(NEXT, 1), "bad_timestamps", {"outside_day": 1}),
            "few": (1295, full[:1295], "few_samples", {}),
        }
        for name, (samples, lines, reason, more) in cases.items():
            with self.subTest(name):
                self.setUp()
                self.put_state()
                self.write_day(TARGET, samples)
                self.write_samples(TARGET, lines)
                self.assertNotMet(reason, **more)

    def test_an_episode_without_its_record_is_not_met(self):
        self.healthy_target(over=("10:00", "10:01", "10:02"))
        self.assertNotMet("episode_unlogged", missing=1)

    def blank_target(self, over, blank, records=()):
        """The target day with the minutes in `blank` lacking a census (null figures)."""
        self.healthy_target(over=over, records=records)
        lines = minute_lines(TARGET, over=over)
        for line in lines:
            if datetime.fromisoformat(line["at"]).strftime("%H:%M") in blank:
                line["unowned_bytes"] = None
        self.write_samples(TARGET, lines)

    def test_census_less_samples_hold_the_streak_for_fifteen_minutes(self):
        over = ("10:00", "10:05", "10:10")
        blank = ("10:01", "10:02", "10:03", "10:04", "10:06", "10:07", "10:08", "10:09")
        with self.subTest("three fresh samples within fifteen minutes need a record"):
            self.blank_target(over, blank)
            self.assertNotMet("episode_unlogged", missing=1)
        with self.subTest("and are met with one"):
            self.blank_target(over, blank, records=[record("2026-11-28T10:10:00+00:00")])
            self.assertMet(episodes=1, restarts=1)
        with self.subTest("a stretch over fifteen minutes zeroes the streak"):
            self.blank_target(("10:00", "10:01", "10:20", "10:21"), tuple(f"10:{m:02d}" for m in range(2, 20)))
            self.assertMet(episodes=0)
        with self.subTest("a fresh sample at the line ends the episode"):
            self.blank_target(("10:00", "10:01", "10:04", "10:05"), ("10:03",))
            self.assertMet(episodes=0)

    def test_every_retried_attempt_needs_its_own_record(self):
        over = ("10:00", "10:01", "10:02", "10:03", "10:04")
        deferred, restarted = "2026-11-28T10:02:00+00:00", "2026-11-28T10:03:00+00:00"
        with self.subTest("deferred then restarted"):
            self.healthy_target(over=over, records=[record(deferred, "deferred"), record(restarted)])
            self.assertMet(deferrals=1, restarts=1)
        with self.subTest("the retry has no record"):
            self.healthy_target(over=over, records=[record(deferred, "deferred")])
            self.assertNotMet("episode_unlogged", missing=2)
        with self.subTest("two records for one attempt"):
            self.healthy_target(over=over, records=[record(deferred, "deferred"), record(deferred, "deferred"),
                                                    record(restarted)])
            self.assertNotMet("episode_unlogged", duplicated=1)
        with self.subTest("a record for a sample that was not due"):
            self.healthy_target(over=over, records=[record("2026-11-28T10:30:00+00:00", "deferred")])
            self.assertNotMet("episode_unlogged", stray=1)
        with self.subTest("an interrupted attempt that lost its sample line"):
            self.healthy_target(over=over, records=[record(deferred, "deferred"),
                                                    record("2026-11-28T10:02:30+00:00", "interrupted")])
            self.assertMet(interruptions=1, deferrals=1)

    def test_an_episode_carried_over_midnight_is_judged_from_the_day_before(self):
        late = minute_lines(PREVIOUS)[23 * 60 + 57:]
        for line in late:
            line["unowned_bytes"] = 29 * GIB
        first = "2026-11-28T00:00:00+00:00"
        with self.subTest("carried and logged"):
            self.healthy_target(over=("00:00",), previous=late[1:], records=[record(first)])
            self.assertMet(episodes=1)
        with self.subTest("carried and not logged"):
            self.healthy_target(over=("00:00",), previous=late[1:])
            self.assertNotMet("episode_unlogged", missing=1)
        with self.subTest("a deferral the day before leaves the episode due"):
            self.healthy_target(over=("00:00", "00:01"), previous=late,
                                records=[record("2026-11-27T23:59:00+00:00", "deferred"), record(first)])
            self.assertMet()
            self.healthy_target(over=("00:00", "00:01"), previous=late,
                                records=[record("2026-11-27T23:59:00+00:00", "deferred")])
            self.assertNotMet("episode_unlogged", missing=2)
        with self.subTest("a restart the day before ends the episode"):
            self.healthy_target(over=("00:00", "00:01", "00:02", "00:03", "00:04", "00:05"), previous=late,
                                records=[record("2026-11-27T23:59:00+00:00")])
            self.assertMet()

    def test_a_floor_kill_is_judged_by_its_own_time(self):
        noon = {"12:01": [kill("2026-11-28T12:00:30+00:00")]}
        with self.subTest("the line before the kill is over"):
            self.healthy_target(over=("12:00",), events=noon)
            self.assertNotMet("kill_over_trigger", kills=1)
        with self.subTest("the line after the kill is over"):
            self.healthy_target(over=("12:01",), events=noon)
            self.assertNotMet("kill_over_trigger")
        with self.subTest("a kill before midnight delivered the day after"):
            self.healthy_target(over=("23:59",))
            self.write_samples(NEXT, [{**minute_lines(NEXT, 1)[0],
                                       "events": [kill("2026-11-28T23:59:50+00:00")]}])
            self.assertNotMet("kill_over_trigger", kills=1)
            (self.dir / "samples" / f"{NEXT}.jsonl").unlink()
            self.assertNotMet("no_next_samples")
        with self.subTest("a kill of the day before is not judged"):
            self.healthy_target(over=("00:00",), events={"00:00": [kill("2026-11-27T23:59:50+00:00")]})
            self.assertMet(floor_kills=0)

    def test_a_floor_kill_is_judged_against_the_criterions_trigger_not_the_saved_one(self):
        self.healthy_target(over=("12:00",), events={"12:01": [kill("2026-11-28T12:00:30+00:00")]})
        self.put_state(limits={**LIMITS, "trigger_bytes": 40 * GIB})
        self.assertNotMet("kill_over_trigger", kills=1)

    def test_the_next_day_needs_a_successful_floor_reading_before_the_day_is_judged(self):
        self.healthy_target(over=("23:59",))
        with self.subTest("the next day's file holds no floor reading yet"):
            self.write_samples(NEXT, minute_lines(NEXT, 2, floor=None))
            self.assertNotMet("no_next_floor_reading")
        with self.subTest("a later line read the floor record"):
            lines = minute_lines(NEXT, 2, floor=None)
            lines[1]["floor_kills"] = 4
            self.write_samples(NEXT, lines)
            self.assertMet()

    def test_a_floor_kill_with_no_figure_is_not_met(self):
        self.healthy_target(events={"12:01": [kill("2026-11-28T12:00:30+00:00")]})
        lines = minute_lines(TARGET, events={"12:01": [kill("2026-11-28T12:00:30+00:00")]})
        for line in lines[12 * 60:12 * 60 + 2]:
            line["unowned_bytes"] = None
        self.write_samples(TARGET, lines)
        self.assertNotMet("kill_unjudged")

    def test_a_malformed_restart_record_is_not_met(self):
        self.healthy_target(records=[record("2026-11-28T10:02:00+00:00", "done")])
        self.assertNotMet("bad_restart_record")

    def test_unreadable_input_exits_two(self):
        for name in ("state", "record"):
            with self.subTest(name):
                self.healthy_target(records=[record("noon")] if name == "record" else [])
                if name == "state":
                    (self.dir / "omlx-restart.json").write_text("[]")
                result = self.run_check()
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr.startswith("omlx-reactive-restart-day:"), result.stderr)

    def test_the_wrapper_is_committed_executable_and_runs_the_module(self):
        listing = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", WRAPPER],
                                 capture_output=True, text=True, check=True).stdout
        self.assertTrue(listing.startswith("100755"), listing)
        result = subprocess.run([str(ROOT / WRAPPER), "--state-dir", str(self.dir)],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(self.verdict(result), {"verdict": "not_yet", "day": None})


if __name__ == "__main__":
    unittest.main()
