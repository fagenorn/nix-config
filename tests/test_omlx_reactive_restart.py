"""The eleven-m5 watcher's reactive oMLX restart: trigger, episode, gaps, durable state, records and alert.

`ReactiveRestartTest` runs `agent_tools.hosts.omlx_memory_watch sample` as a child with a stub
`omlx-restart`; `ReactiveStepTest` calls `omlx_reactive_restart.step` in process with stub gate,
delivery and clock, and interrupts its saves.
Run: just agent-workflow-tests
"""

import importlib
import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from tests.test_omlx_memory_records import RecordsCase, before, census
from tests.test_omlx_memory_watch import VM_STAT, VM_STAT_LOW

TIER = "fast"

GIB = 1024**3
COMP = 105539 * 16384
OVER = 25 * GIB + 1 - COMP
AT_LINE = 25 * GIB - COMP
UNDER = GIB
DAY = "2026-11-24"
MODULE = "agent_tools.hosts.omlx_reactive_restart"


def at(clock, day=DAY):
    return f"{day}T{clock}:00"


class ReactiveRestartTest(RecordsCase):
    def setUp(self):
        super().setUp()
        self.settings_on()
        self.restart_state = self.state_dir / "omlx-restart.json"
        self.records_file = self.state_dir / "omlx-restarts.jsonl"
        self.stub = self.restart_stub()

    def restart_stub(self):
        self.fake(
            "omlx-restart",
            f'echo "$@" >> "{self.d}/restart.calls"\n'
            f'if [ -e "{self.d}/reason" ]; then echo "oMLX: restart deferred ($(cat "{self.d}/reason"))" >&2; fi\n'
            f'rc=0; [ -e "{self.d}/restart.rc" ] && rc=$(cat "{self.d}/restart.rc")\n'
            'exit "$rc"\n')
        return self.d / "omlx-restart"

    def answer(self, code, reason=None):
        (self.d / "restart.rc").write_text(str(code))
        if reason is None:
            (self.d / "reason").unlink(missing_ok=True)
        else:
            (self.d / "reason").write_text(reason)

    def calls(self):
        path = self.d / "restart.calls"
        return path.read_text().splitlines() if path.exists() else []

    def put(self, now, unowned):
        self.put_census(census(at=before(now), unowned_bytes=unowned))

    def args(self):
        return (
            "--restart-command", str(self.stub), "--restart-trigger-gib", "25", "--restart-samples", "3",
            "--restart-room-gib", "16", "--restart-min-minutes", "30")

    def sample_at(self, now):
        result = self.sample(*self.args(), now=now)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def over_at(self, *nows, unowned=OVER):
        for now in nows:
            self.put(now, unowned)
            self.sample_at(now)

    def records(self):
        if not self.records_file.exists():
            return []
        return [json.loads(line) for line in self.records_file.read_text().splitlines()]

    def restart_alerts(self):
        texts = [request["body"]["text"] for request in self.bot.requests]
        return [text for text in texts if "oMLX was restarted" in text]

    def test_three_samples_over_the_line_with_an_idle_server_restart_once_and_alert_once(self):
        counts = []
        for now in (at("12:00"), at("12:01"), at("12:02"), at("12:03")):
            self.put(now, OVER)
            self.sample_at(now)
            counts.append((len(self.calls()), len(self.restart_alerts())))
        self.assertEqual(counts, [(0, 0), (0, 0), (1, 1), (1, 1)])
        self.assertEqual(self.calls(), ["--reactive"])
        [record] = self.records()
        self.assertEqual(record["outcome"], "restarted")
        self.assertEqual(record["unowned_bytes"], OVER)
        self.assertEqual(record["compressor_bytes"], COMP)
        self.assertEqual(record["figure_bytes"], 25 * GIB + 1)
        self.assertIsInstance(record["available_bytes"], int)
        self.assertTrue(record["reason"])
        self.assertEqual(record["at"], at("12:02"))

    def test_two_samples_over_the_line_restart_nothing(self):
        self.over_at(at("12:00"), at("12:01"))
        self.over_at(at("12:02"), unowned=UNDER)
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.records_file.exists())
        self.assertEqual(self.restart_alerts(), [])

    def test_a_busy_server_defers_logs_the_reason_and_is_retried(self):
        self.over_at(at("12:00"), at("12:01"))
        self.answer(75, "1 active, 0 waiting requests")
        self.put(at("12:02"), OVER)
        busy = self.sample_at(at("12:02"))
        self.over_at(at("12:03"))
        self.answer(0)
        self.over_at(at("12:04"))
        self.assertEqual(len(self.calls()), 3)
        records = self.records()
        self.assertEqual([record["outcome"] for record in records], ["deferred", "deferred", "restarted"])
        self.assertEqual([record["at"] for record in records], [at("12:02"), at("12:03"), at("12:04")])
        self.assertEqual(
            [record["reason"] for record in records[:2]], ["1 active, 0 waiting requests"] * 2)
        self.assertEqual(len(self.restart_alerts()), 1)
        self.assertIn("omlx_restart outcome=deferred", busy.stdout)

    def test_a_new_episode_inside_thirty_minutes_waits_for_the_gap(self):
        self.over_at(at("12:00"), at("12:01"), at("12:02"))
        self.over_at(at("12:03"), unowned=UNDER)
        self.over_at(at("12:04"), at("12:05"), at("12:06"), at("12:31"))
        self.assertEqual(len(self.calls()), 1)
        first, second = self.records()[1:]
        self.assertEqual((first["outcome"], first["at"]), ("deferred", at("12:06")))
        self.assertIn("4 minutes", first["reason"])
        self.assertEqual((second["outcome"], second["at"]), ("deferred", at("12:31")))
        self.assertIn("29 minutes", second["reason"])
        self.assertIn("under 30", second["reason"])
        self.over_at(at("12:33"))
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(len(self.restart_alerts()), 2)

    def test_available_memory_under_the_restart_room_defers(self):
        self.vm_stat(VM_STAT_LOW)
        self.over_at(at("12:00"), at("12:01"), at("12:02"))
        self.assertEqual(self.calls(), [])
        [record] = self.records()
        self.assertEqual(record["outcome"], "deferred")
        self.assertIn("under the 16 GiB restart room", record["reason"])
        self.vm_stat(VM_STAT)
        self.over_at(at("12:03"))
        self.assertEqual(len(self.calls()), 1)

    def test_a_sample_without_a_fresh_census_breaks_the_row(self):
        self.over_at(at("12:00"), at("12:01"))
        self.put_census(census(at="2026-11-24T11:50:00", unowned_bytes=OVER))
        self.sample_at(at("12:02"))
        self.over_at(at("12:03"))
        self.assertEqual(self.calls(), [])

    def test_a_figure_exactly_at_the_line_is_not_over_it(self):
        self.over_at(at("12:00"), at("12:01"), at("12:02"), unowned=AT_LINE)
        self.assertEqual(self.calls(), [])

    def test_a_failed_restart_is_logged_retried_and_not_alerted(self):
        self.over_at(at("12:00"), at("12:01"))
        self.answer(1)
        self.over_at(at("12:02"))
        self.assertEqual(self.restart_alerts(), [])
        self.answer(0)
        self.over_at(at("12:03"))
        failed, restarted = self.records()
        self.assertEqual((failed["outcome"], failed["reason"]), ("failed", "omlx-restart exited 1"))
        self.assertEqual(restarted["outcome"], "restarted")
        self.assertEqual(len(self.restart_alerts()), 1)

    def test_the_gap_holds_across_midnight(self):
        self.over_at(at("23:48"), at("23:49"), at("23:50"))
        self.over_at(at("23:51"), unowned=UNDER)
        self.over_at(*(at(clock, "2026-11-25") for clock in ("00:00", "00:01", "00:02")))
        self.assertEqual(len(self.calls()), 1)
        last = self.records()[-1]
        self.assertEqual((last["outcome"], last["at"]), ("deferred", at("00:02", "2026-11-25")))
        self.assertIn("12 minutes", last["reason"])
        held = json.loads(self.restart_state.read_text())["last_restart_at"]
        self.assertTrue(held.startswith(at("23:50")), held)

    def test_the_restart_command_needs_its_four_numbers(self):
        result = self.sample("--restart-command", str(self.stub))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.calls(), [])

    def test_without_the_restart_command_nothing_restarts(self):
        for now in (at("12:00"), at("12:01"), at("12:02"), at("00:00", "2026-11-25")):
            self.put(now, OVER)
            result = self.sample(now=now)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.records_file.exists())
        self.assertFalse(self.restart_state.exists())
        self.assertEqual([key for key in self.read_state() if key.startswith("restart")], [])

    def test_the_sample_line_and_state_carry_what_the_day_check_reads(self):
        self.sample_at(at("12:00"))
        self.assertEqual(self.sample_lines()[0]["compressor_bytes"], COMP)
        held = json.loads(self.restart_state.read_text())
        self.assertEqual(held["limits"], {
            "trigger_bytes": 25 * GIB, "samples": 3, "room_bytes": 16 * GIB, "min_interval_seconds": 1800})
        self.assertEqual(held["since_at"], at("12:00"))
        self.sample_at(at("12:01"))
        self.assertEqual(json.loads(self.restart_state.read_text())["since_at"], at("12:00"))

    def test_the_compressor_decides_a_figure_just_over_the_line(self):
        self.vm_stat(VM_STAT.replace("105539.", "0."))
        self.over_at(at("12:00"), at("12:01"), at("12:02"))
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.records_file.exists())
        self.vm_stat(VM_STAT)
        self.over_at(at("12:03"), at("12:04"))
        self.assertEqual(self.calls(), [])
        self.over_at(at("12:05"))
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual([record["at"] for record in self.records()], [at("12:05")])

    def test_an_unreadable_restart_state_makes_no_attempt(self):
        self.state_dir.mkdir(mode=0o700)
        self.restart_state.write_text("[]")
        for now in (at("12:00"), at("12:01"), at("12:02")):
            self.put(now, OVER)
            result = self.sample(*self.args(), now=now)
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertIn("the restart state is unreadable (", result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.restart_state.read_text(), "[]")
        self.assertEqual(len(self.sample_lines()), 3)


class Clock:
    def __init__(self):
        self.value = timedelta(0)

    def elapsed(self):
        return self.value


class ReactiveStepTest(unittest.TestCase):
    def setUp(self):
        self.m = importlib.import_module(MODULE)
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.dir = Path(scratch.name)
        self.limits = self.m.Limits("omlx-restart", 25 * GIB, 3, 16 * GIB, timedelta(minutes=30))
        self.reading = {"host": "eleven-m5", "available_bytes": 40 * GIB, "compressor_bytes": COMP}
        self.clock = Clock()
        self.gate_calls = []
        self.sent = []
        self.answers = []
        self.outcome = self.m.Gate("restarted", "omlx-restart restarted oMLX")

    def gate(self, argv):
        self.gate_calls.append(argv)
        return self.outcome

    def deliver(self, kind, text, logged):
        self.sent.append((kind, text, logged))
        return self.answers.pop(0) if self.answers else "sent"

    def go(self, clock, unowned=OVER, day=DAY, gate=None):
        found = None if unowned is None else {"unowned_bytes": unowned}
        return self.m.step(
            self.dir, found, self.reading, datetime.fromisoformat(at(clock, day)), self.limits,
            elapsed=self.clock.elapsed, gate=gate or self.gate, deliver=self.deliver)

    def records(self):
        path = self.dir / self.m.RESTARTS_NAME
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def held(self):
        return json.loads((self.dir / self.m.RESTART_STATE_NAME).read_text())

    def test_a_timed_out_gate_is_ended_with_its_children(self):
        script = self.dir / "slow"
        script.write_text('#!/bin/sh\n(sleep 2; echo late > "$1/late") &\nsleep 30\n')
        script.chmod(0o755)
        started = time.monotonic()
        found = self.m.run_gate([str(script), str(self.dir)], timeout=1)
        self.assertEqual(found, self.m.Gate("failed", "omlx-restart timed out"))
        self.assertLess(time.monotonic() - started, 5)
        time.sleep(3)
        self.assertFalse((self.dir / "late").exists())

    def test_the_gap_counts_from_when_the_gate_returned(self):
        def slow(argv):
            self.clock.value = timedelta(minutes=25)
            return self.gate(argv)

        for clock in ("12:00", "12:01"):
            self.go(clock)
        self.go("12:02", gate=slow)
        self.assertEqual(self.held()["last_restart_at"], at("12:27"))
        self.clock.value = timedelta(0)
        self.go("12:03", unowned=UNDER)
        for clock in ("12:38", "12:39", "12:40"):
            self.go(clock)
        self.assertEqual(len(self.gate_calls), 1)
        last = self.records()[-1]
        self.assertEqual((last["outcome"], last["at"]), ("deferred", at("12:40")))
        self.assertIn("13 minutes ago, under 30", last["reason"])

    def test_a_run_stopped_after_the_gate_signalled_does_not_signal_again(self):
        original = self.m._save
        armed = [True]

        def stops(path, document):
            if armed[0] and document["attempt"] is None and document["outbox"]:
                armed[0] = False
                raise OSError("disk full")
            original(path, document)

        for clock in ("12:00", "12:01"):
            self.go(clock)
        with mock.patch.object(self.m, "_save", stops):
            with self.assertRaises(OSError):
                self.go("12:02")
        started = self.held()["attempt"]["started_at"]
        self.go("12:03")
        self.assertEqual(len(self.gate_calls), 1)
        [record] = self.records()
        self.assertEqual((record["outcome"], record["at"]), ("interrupted", at("12:02")))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("may have been restarted", self.sent[0][1])
        self.assertEqual(self.held()["last_restart_at"], started)

    def test_a_run_stopped_after_its_success_record_records_and_alerts_once(self):
        original = self.m._save
        armed = [True]

        def stops(path, document):
            if armed[0] and any(entry["recorded"] for entry in document["outbox"]):
                armed[0] = False
                raise OSError("disk full")
            original(path, document)

        for clock in ("12:00", "12:01"):
            self.go(clock)
        with mock.patch.object(self.m, "_save", stops):
            with self.assertRaises(OSError):
                self.go("12:02")
        self.assertEqual(len(self.records()), 1)
        self.go("12:03")
        self.assertEqual(len(self.gate_calls), 1)
        [record] = self.records()
        self.assertEqual(record["outcome"], "restarted")
        self.assertEqual([kind for kind, _, _ in self.sent], ["omlx_restarted"])

    def test_an_alert_that_could_not_be_sent_is_kept_and_retried(self):
        self.answers = ["failed"]
        self.go("12:00")
        self.go("12:01")
        self.assertTrue(self.go("12:02"))
        self.assertEqual([entry["logged"] for entry in self.held()["outbox"]], [True])
        self.assertFalse(self.go("12:03"))
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.sent[0][1], self.sent[1][1])
        self.assertEqual((self.sent[0][2], self.sent[1][2]), (False, True))
        self.assertEqual(self.held()["outbox"], [])
