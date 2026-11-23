"""The console's engine run reader: one reading per run from the engine's own fold, read incrementally."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.console import engine_runs, sprints
from agent_tools.console.engine_runs import EngineRuns
from agent_tools.delivery import engine, engine_ledger, procedure_check
from agent_tools.delivery.engine_ledger import RunState

TIER = "fast"

FIXTURES = Path(__file__).parent / "fixtures/console/engine-runs"
HOLDER = {"pid": 4242, "started": "2026-11-21T16:00:00Z"}
RUN_ID = "41-20261121T160000Z-ab12"
START_MS = int(datetime(2026, 11, 21, 16, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
LAST_AT = "2026-11-21T16:00:01Z"
LAST_MS = START_MS + 1000
DAY_MS = 24 * 60 * 60 * 1000


def LIVE(pid, started):
    return True


def DEAD(pid, started):
    return False


def make_run(root, name, events_fixture, *, issue=41, project="acme/app", sequence=1, parent=None,
             holder=HOLDER):
    run_dir = Path(root) / name
    run_dir.mkdir(parents=True)
    document = {member: "x" for member in engine_ledger.RUN_MEMBERS}
    document.update(inputs={}, issue=issue, project=project, run=name, sequence=sequence,
                    started="2026-11-21T16:00:00Z")
    if parent is not None:
        document[engine_ledger.PARENT_MEMBER] = parent
    (run_dir / "run.json").write_text(json.dumps(document, separators=(",", ":")))
    if events_fixture is not None:
        shutil.copyfile(FIXTURES / events_fixture, run_dir / "events.jsonl")
    if holder is not None:
        (run_dir / "lock").write_text(json.dumps(holder, separators=(",", ":")))
    return run_dir


def poll_state(events_fixture, alive, **kwargs):
    with tempfile.TemporaryDirectory() as tmp:
        make_run(tmp, RUN_ID, events_fixture, **kwargs)
        return EngineRuns(Path(tmp), alive=alive).poll().states[0]


def bare_state(**members):
    values = dict(run=RUN_ID, project="acme/app", issue=41, stage=None, step=None, wait=None,
                  stop=None, done=False, last_event=None, process=None, alive=False)
    values.update(members)
    return RunState(**values)


def line(**event):
    return json.dumps(event, sort_keys=True, separators=(",", ":")).encode() + "\n".encode()


def step_line(at="2026-11-21T16:00:02Z"):
    return line(at=at, event="step_entered", stage="verifying", step="verify", visit=1)


class ReadingTest(unittest.TestCase):
    def test_each_recorded_file_reads_its_one_reading(self):
        cases = {
            "moving.jsonl": (LIVE, "moving", "planning, moving"),
            "waiting.jsonl": (LIVE, "waiting", "building, waiting for a free session slot on this host"),
            "stopped.jsonl": (LIVE, "stopped", "stopped at claim lost, needs your decision"),
            "not-running.jsonl": (DEAD, "not_running", "verifying, the engine is not running"),
            "done.jsonl": (LIVE, "done", "done"),
        }
        for fixture, (probe, reading, text) in cases.items():
            with self.subTest(fixture=fixture):
                entry = engine_runs.engine_entry(poll_state(fixture, probe), None)
                self.assertEqual((entry["reading"], entry["text"]), (reading, text))
                self.assertEqual(reading in engine_runs.READINGS, True)
                lowered = json.dumps(entry).lower()
                self.assertNotIn("quiet", lowered)
                self.assertNotIn("stuck", lowered)

    def test_the_entry_has_exactly_its_members(self):
        entry = engine_runs.engine_entry(poll_state("moving.jsonl", LIVE), None)
        self.assertEqual(entry, {
            "run_id": RUN_ID, "issue": 41, "stage": "planning", "stage_text": "planning",
            "reading": "moving", "text": "planning, moving", "wait_until": None,
            "last_event_at": LAST_AT})

    def test_a_live_engine_forty_minutes_into_a_step_reads_moving_and_no_line_says_quiet_or_stuck(self):
        state = poll_state("moving.jsonl", LIVE)
        entry = engine_runs.engine_entry(state, START_MS + 40 * 60 * 1000)
        self.assertEqual((entry["reading"], entry["text"]), ("moving", "planning, moving"))
        lowered = json.dumps(entry).lower()
        self.assertNotIn("quiet", lowered)
        self.assertNotIn("stuck", lowered)

    def test_each_stage_reads_in_its_own_words_and_a_fan_out_reads_its_task(self):
        self.assertEqual(procedure_check.STAGES, (
            "setup", "planning", "plan review", "building", "final review", "verifying",
            "awaiting look", "landing", "closing out", "done"))
        for stage in procedure_check.STAGES:
            with self.subTest(stage=stage):
                state = bare_state(stage=stage, engine_alive=True)
                self.assertEqual(engine_runs.stage_text(state), stage)
                self.assertEqual(engine_runs.line_text(state), f"{stage}, moving")
        self.assertIsNone(engine_runs.stage_text(bare_state()))
        fanned = poll_state("fanout.jsonl", LIVE)
        self.assertEqual(engine_runs.line_text(fanned), "building task 2 of 3, moving")
        self.assertEqual(engine_runs.stage_text(fanned), "building task 2 of 3")

    def test_wait_and_need_words_cover_every_ledger_value(self):
        self.assertEqual(set(engine_runs.WAIT_TEXT), set(engine_ledger.WAITS))
        self.assertEqual(set(engine_runs.NEED_TEXT), set(procedure_check.NEEDS))
        self.assertEqual(engine_runs.WAIT_TEXT["lock"], sprints.NOW_LOCK_TEXT)
        state = bare_state(stage="building", engine_alive=True, last_event=LAST_AT,
                           wait={"wait": "usage-limit", "since": LAST_AT, "until": "2026-11-21T18:00:00Z"})
        entry = engine_runs.engine_entry(state, None)
        self.assertEqual(entry["wait_until"], "2026-11-21T18:00:00Z")
        self.assertEqual(entry["text"], "building, waiting out a usage limit")

    def test_precedence_is_done_stop_not_running_wait_moving(self):
        for fixture, probe, reading in (("stopped.jsonl", DEAD, "stopped"), ("done.jsonl", DEAD, "done"),
                                        ("waiting.jsonl", DEAD, "not_running"),
                                        ("waiting.jsonl", LIVE, "waiting")):
            with self.subTest(fixture=fixture, live=probe is LIVE):
                self.assertEqual(engine_runs.reading(poll_state(fixture, probe)), reading)

    def test_a_run_with_no_step_or_ended_a_day_ago_is_not_shown(self):
        self.assertIsNone(engine_runs.engine_entry(poll_state(None, LIVE), None))
        with tempfile.TemporaryDirectory() as tmp:
            make_run(tmp, RUN_ID, None).joinpath("events.jsonl").write_bytes(b"")
            state = EngineRuns(Path(tmp), alive=LIVE).poll().states[0]
        self.assertIsNone(engine_runs.engine_entry(state, None))
        nothing = bare_state(stage="setup", last_event=LAST_AT,
                             stop={"name": "claim-lost", "need": "nothing"})
        for state in (poll_state("done.jsonl", LIVE), nothing):
            with self.subTest(reading=engine_runs.reading(state)):
                self.assertIsNone(engine_runs.engine_entry(state, LAST_MS + DAY_MS))
                self.assertIsNotNone(engine_runs.engine_entry(state, LAST_MS + DAY_MS - 1))
                self.assertIsNotNone(engine_runs.engine_entry(state, None))
        decision = poll_state("stopped.jsonl", LIVE)
        self.assertIsNotNone(engine_runs.engine_entry(decision, LAST_MS + 2 * DAY_MS))

    def test_project_lines_group_by_project_in_issue_order(self):
        def state(project, issue, stage="planning"):
            return bare_state(project=project, issue=issue, run=f"{issue}-20261121T160000Z-ab12",
                              stage=stage, last_event=LAST_AT, engine_alive=True)
        states = [state("acme/app", 7), state("acme/app", 3), state("other/app", 5),
                  state("acme/app", 9, stage=None), state("empty/app", 1, stage=None)]
        lines = engine_runs.project_lines(states, None)
        self.assertEqual(lines, {
            "acme/app": [engine_runs.engine_entry(states[1], None), engine_runs.engine_entry(states[0], None)],
            "other/app": [engine_runs.engine_entry(states[2], None)]})


class IncrementalTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.run_dir = make_run(self.root, RUN_ID, "moving.jsonl")
        self.events = self.run_dir / "events.jsonl"
        self.counter = CountingOpener()
        self.reader = EngineRuns(self.root, alive=LIVE, opener=self.counter)

    def append(self, data):
        with open(self.events, "ab") as handle:
            handle.write(data)

    def test_a_second_poll_reads_only_the_appended_bytes(self):
        self.assertEqual(self.reader.poll().states[0].stage, "planning")
        first = self.counter.bytes
        self.assertEqual(first, len((FIXTURES / "moving.jsonl").read_bytes()))
        added = step_line()
        self.append(added)
        self.assertEqual(self.reader.poll().states[0].stage, "verifying")
        self.assertEqual(self.counter.bytes - first, len(added))
        calls = self.counter.calls
        self.reader.poll()
        self.assertEqual(self.counter.calls, calls)

    def test_a_torn_tail_is_read_once_it_is_complete_or_rewritten(self):
        before = self.reader.poll().states[0]
        full = step_line()
        self.append(full[:30])
        self.assertEqual(self.reader.poll().states[0], before)
        self.append(full[30:])
        self.assertEqual(self.reader.poll().states[0].stage, "verifying")
        other = line(at="2026-11-21T16:00:03Z", event="step_entered", stage="landing", step="land", visit=1)
        self.append(other[:20])
        self.assertEqual(self.reader.poll().states[0].stage, "verifying")
        os.truncate(self.events, len((FIXTURES / "moving.jsonl").read_bytes()) + len(full))
        self.append(other)
        state = self.reader.poll().states[0]
        self.assertEqual((state.stage, state.step, state.last_event), ("landing", "land", "2026-11-21T16:00:03Z"))

    def test_a_replaced_file_is_read_from_its_start(self):
        self.reader.poll()
        replacement = self.root / "replacement"
        replacement.write_bytes((FIXTURES / "waiting.jsonl").read_bytes() + step_line() + step_line())
        os.replace(replacement, self.events)
        expected = engine_ledger.fold(engine_ledger.read_run(self.run_dir),
                                      engine_ledger.replay(self.events), LIVE, engine_ledger.read_holder(self.run_dir))
        self.assertEqual(self.reader.poll().states[0], expected)
        self.assertEqual(expected.stage, "verifying")

    def test_a_shorter_file_is_read_from_its_start(self):
        self.append(step_line())
        self.reader.poll()
        self.events.write_bytes((FIXTURES / "done.jsonl").read_bytes()[:-1])
        self.assertEqual(self.reader.poll().states[0].stage, "closing out")

    def test_a_refused_line_keeps_the_last_state_and_names_the_run(self):
        before = self.reader.poll()
        self.assertEqual(before.unreadable, ())
        self.append(b'{"event":"nope"}\n')
        after = self.reader.poll()
        self.assertEqual([name for name, _ in after.unreadable], [RUN_ID])
        self.assertTrue(after.unreadable[0][1])
        self.assertEqual(after.states, before.states)

    def test_a_run_json_that_read_run_refuses_is_named_and_the_rest_are_read(self):
        bad = make_run(self.root, "42-20261121T160000Z-ab12", "moving.jsonl", issue=42)
        (bad / "run.json").write_text("{}")
        polled = self.reader.poll()
        self.assertEqual([name for name, _ in polled.unreadable], ["42-20261121T160000Z-ab12"])
        self.assertEqual([state.run for state in polled.states], [RUN_ID])

    def test_an_absent_event_file_is_no_events_and_not_unreadable(self):
        self.events.unlink()
        polled = self.reader.poll()
        self.assertEqual((polled.unreadable, polled.states[0].stage), ((), None))


class SelectionTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_only_the_newest_root_run_of_an_issue_is_read(self):
        make_run(self.root, "41-20261121T160000Z-ab12", "moving.jsonl", sequence=1)
        make_run(self.root, "41-20261121T160100Z-ab12", "waiting.jsonl", sequence=2)
        make_run(self.root, "41-20261121T160200Z-ab12", "done.jsonl", sequence=3,
                 parent="41-20261121T160100Z-ab12")
        make_run(self.root, "41-20261121T160300Z-ab12", "stopped.jsonl", project="other/app", sequence=1)
        (self.root / ".41.deliver.lock").write_text("")
        (self.root / "not-a-run").mkdir()
        (self.root / "41-20261121T160400Z-ab12").write_text("a file, not a run")
        polled = EngineRuns(self.root, alive=LIVE).poll()
        self.assertEqual([(state.project, state.run) for state in polled.states],
                         [("acme/app", "41-20261121T160100Z-ab12"), ("other/app", "41-20261121T160300Z-ab12")])
        self.assertEqual(polled.unreadable, ())

    def test_the_name_breaks_a_tie_of_sequence(self):
        make_run(self.root, "41-20261121T160000Z-ab12", "moving.jsonl")
        make_run(self.root, "41-20261121T160000Z-ab13", "waiting.jsonl")
        self.assertEqual(EngineRuns(self.root, alive=LIVE).poll().states[0].run, "41-20261121T160000Z-ab13")

    def test_an_absent_root_gives_no_states(self):
        polled = EngineRuns(self.root / "absent", alive=LIVE).poll()
        self.assertEqual((polled.states, polled.unreadable), ((), ()))

    def test_a_vanished_run_leaves(self):
        run_dir = make_run(self.root, RUN_ID, "moving.jsonl")
        reader = EngineRuns(self.root, alive=LIVE)
        self.assertEqual(len(reader.poll().states), 1)
        shutil.rmtree(run_dir)
        self.assertEqual(reader.poll().states, ())

    def test_the_reader_takes_no_lock(self):
        make_run(self.root, RUN_ID, "moving.jsonl")
        with mock.patch("fcntl.flock", side_effect=AssertionError("locked")):
            self.assertEqual(len(EngineRuns(self.root, alive=LIVE).poll().states), 1)

    def test_a_run_json_is_read_once_per_name(self):
        make_run(self.root, RUN_ID, "moving.jsonl")
        reader = EngineRuns(self.root, alive=LIVE)
        with mock.patch.object(engine_ledger, "read_run", wraps=engine_ledger.read_run) as read:
            reader.poll()
            reader.poll()
        self.assertEqual(read.call_count, 1)

    def test_states_are_sorted_by_project_then_issue(self):
        for issue, project in ((9, "b/app"), (3, "b/app"), (5, "a/app")):
            make_run(self.root, f"{issue}-20261121T160000Z-ab12", "moving.jsonl", issue=issue, project=project)
        states = EngineRuns(self.root, alive=LIVE).poll().states
        self.assertEqual([(state.project, state.issue) for state in states],
                         [("a/app", 5), ("b/app", 3), ("b/app", 9)])


class StatusParityTest(unittest.TestCase):
    def test_the_console_state_equals_engine_status_for_the_same_directory(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        for fixture in sorted(path.name for path in FIXTURES.glob("*.jsonl")):
            for label, pid in (("alive", os.getpid()), ("dead", child.pid)):
                with self.subTest(fixture=fixture, engine=label), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp) / ".agents" / "state" / "engine" / "runs"
                    root.mkdir(parents=True)
                    make_run(root, RUN_ID, fixture, holder={"pid": pid, "started": "2026-11-21T16:00:00Z"})
                    out = io.StringIO()
                    with mock.patch.dict(os.environ, {"HOME": tmp}), contextlib.redirect_stdout(out):
                        self.assertEqual(engine.main(["status", "41"]), 0)
                    state = EngineRuns(root).poll().states[0]
                    self.assertEqual(state.as_json(), json.loads(out.getvalue()))
                    self.assertIs(state.engine_alive, label == "alive")


class CountingFile:
    def __init__(self, owner, handle):
        self._owner, self._handle = owner, handle

    def read(self, n=-1):
        data = self._handle.read(n)
        self._owner.bytes += len(data)
        return data

    def seek(self, *args):
        return self._handle.seek(*args)

    def __enter__(self):
        self._handle.__enter__()
        return self

    def __exit__(self, *exc):
        return self._handle.__exit__(*exc)


class CountingOpener:
    def __init__(self):
        self.calls = self.bytes = 0

    def __call__(self, path):
        self.calls += 1
        return CountingFile(self, open(path, "rb"))


if __name__ == "__main__":
    unittest.main()
