"""The console's engine run reader: one reading per run from the engine's own fold, read incrementally."""

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.console import console, engine_runs, guest, service, sprints, view
from agent_tools.console.engine_runs import NO_ENGINE, EngineRuns, SprintEngine
from agent_tools.delivery import engine, engine_ledger, procedure_check
from agent_tools.delivery.engine_ledger import RunState

from . import console_test_support as support
from . import test_console_page as page
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

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
            "need": None, "last_event_at": LAST_AT, "spend": None})

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
        self.assertEqual(engine_runs.WAIT_TEXT["checks"], sprints.NOW_CI_TEXT)
        state = bare_state(stage="building", engine_alive=True, last_event=LAST_AT,
                           wait={"wait": "usage-limit", "since": LAST_AT, "until": "2026-11-21T18:00:00Z"})
        entry = engine_runs.engine_entry(state, None)
        self.assertEqual(entry["wait_until"], "2026-11-21T18:00:00Z")
        self.assertEqual(entry["text"], "building, waiting out a usage limit")

    def test_an_open_ci_wait_reads_waiting_for_ci_on_its_pull_request(self):
        state = poll_state("sprint-checks.jsonl", LIVE)
        entry = engine_runs.engine_entry(state, None)
        self.assertEqual((entry["reading"], entry["text"]),
                         ("waiting", "building, waiting for CI on its pull request"))
        self.assertEqual(engine_runs.wait_text(state), sprints.NOW_CI_TEXT)

    def test_wait_text_names_the_open_wait_only_while_the_run_reads_waiting(self):
        self.assertEqual(engine_runs.wait_text(poll_state("sprint-host-slot.jsonl", LIVE)),
                         "waiting for a free session slot on this host")
        for fixture, probe in (("sprint-host-slot.jsonl", DEAD), ("sprint-moving.jsonl", LIVE),
                               ("stopped.jsonl", LIVE)):
            with self.subTest(fixture=fixture, live=probe is LIVE):
                self.assertIsNone(engine_runs.wait_text(poll_state(fixture, probe)))

    def test_a_waiting_lines_text_ends_with_its_wait_text(self):
        for wait in ("checks", "lock", "usage-limit", "host-slot"):
            with self.subTest(wait=wait):
                state = poll_state(f"sprint-{wait}.jsonl", LIVE)
                self.assertEqual(engine_runs.line_text(state), f"building, {engine_runs.wait_text(state)}")

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


class SprintEngineTest(unittest.TestCase):
    def read(self, fixture, probe, project="acme/app", issues=(41, 42), now_ms=None):
        return engine_runs.sprint_engine([poll_state(fixture, probe)], project, set(issues), now_ms)

    def test_a_moving_run_of_the_sprints_issue_moves_it_and_names_its_sessions(self):
        self.assertEqual(self.read("sprint-moving.jsonl", LIVE), SprintEngine(
            moving=True, waits=frozenset(), sessions=frozenset({"eng-s1"}), issues=frozenset({41})))

    def test_a_waiting_run_gives_its_wait_kind_and_does_not_read_moving(self):
        self.assertEqual(self.read("sprint-checks.jsonl", LIVE), SprintEngine(
            moving=False, waits=frozenset({"checks"}), sessions=frozenset({"eng-s1"}),
            issues=frozenset({41})))

    def test_a_gone_engine_moves_nothing_but_keeps_its_sessions_and_issue(self):
        self.assertEqual(self.read("sprint-moving.jsonl", DEAD), SprintEngine(
            sessions=frozenset({"eng-s1"}), issues=frozenset({41})))

    def test_a_run_of_another_project_or_issue_is_not_read(self):
        self.assertEqual(self.read("sprint-moving.jsonl", LIVE, project="other/app", issues=(41,)), NO_ENGINE)
        self.assertEqual(self.read("sprint-moving.jsonl", LIVE, issues=(7,)), NO_ENGINE)

    def test_a_run_hidden_a_day_after_it_ended_carries_no_issue(self):
        state = bare_state(stage="landing", done=True, last_event=LAST_AT, sessions=("eng-s9",))
        self.assertEqual(engine_runs.sprint_engine([state], "acme/app", {41}, LAST_MS + DAY_MS),
                         SprintEngine(sessions=frozenset({"eng-s9"})))

    def test_a_sprint_engine_reads_whether_it_moves_its_wait_sentences_and_its_json(self):
        self.assertIs(NO_ENGINE.moves, False)
        self.assertIs(SprintEngine(moving=True).moves, True)
        self.assertIs(SprintEngine(waits=frozenset({"checks"})).moves, True)
        both = SprintEngine(waits=frozenset({"checks", "lock"}))
        self.assertEqual(both.texts, {sprints.NOW_CI_TEXT, sprints.NOW_LOCK_TEXT})
        self.assertIsNone(both.later)
        self.assertEqual(SprintEngine(waits=frozenset({"host-slot", "usage-limit"})).later,
                         "waiting out a usage limit")
        self.assertEqual(SprintEngine(waits=frozenset({"host-slot"})).later,
                         "waiting for a free session slot on this host")
        self.assertEqual(SprintEngine(waits=frozenset({"lock", "checks"})).as_json(),
                         {"moving": False, "waits": ["checks", "lock"]})
        every = SprintEngine(waits=frozenset(engine_ledger.WAITS)).as_json()["waits"]
        self.assertEqual(every, ["checks", "host-slot", "lock", "usage-limit"])


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


def live_state(project="acme/app"):
    return RunState(run=RUN_ID, project=project, issue=41, stage="planning", step="plan", wait=None,
                    stop=None, done=False, last_event="2026-11-21T16:00:00Z", process=None, alive=False,
                    engine={"pid": 1, "started": "2026-11-21T16:00:00Z"}, engine_alive=True)


def project_entries(derived):
    return [project for entry in derived["entries"] for project in entry.get("projects", [entry])]


class ViewLineTest(unittest.TestCase):
    def derive(self, states, **kwargs):
        return view.derive_view(states=states, now_ms=START_MS + 40 * 60 * 1000, **kwargs)

    def test_an_engine_run_shows_under_its_project_and_makes_it_active(self):
        now_ms = START_MS + 40 * 60 * 1000
        state = live_state()
        derived = self.derive([view.ProjectState("acme/app", "/srv/app", 1, "2026-11-21T10:00:00Z", 0)],
                              engine_runs=[state])
        self.assertEqual([entry["type"] for entry in derived["entries"]], ["project"])
        entry = derived["entries"][0]
        self.assertEqual(entry["engine_runs"], [engine_runs.engine_entry(state, now_ms)])
        self.assertIs(entry["quiet"], False)

    def test_an_engine_runs_entry_carries_its_spend_figure(self):
        spend_view = {"approximate": False, "days": [
            {"day": "2026-11-20", "run": {RUN_ID: {"input": 100, "cache_write": 10, "cache_read": 1000,
                                                    "output": 5, "dollars": 0.25, "approximate": False}}},
            {"day": "2026-11-21", "run": {
                RUN_ID: {"input": 50, "cache_write": 0, "cache_read": 0, "output": 5,
                         "dollars": 0.5, "approximate": True},
                "wf_9": {"input": 7, "cache_write": 0, "cache_read": 0, "output": 0,
                         "dollars": 0.01, "approximate": False}}}]}
        derived = self.derive([view.ProjectState("acme/app", "/srv/app", 1, "2026-11-21T10:00:00Z", 0)],
                              engine_runs=[live_state()], spend=spend_view)
        self.assertEqual(derived["entries"][0]["engine_runs"][0]["spend"],
                         {"tokens": 1170, "dollars": 0.75, "approximate": True})

    def test_a_run_of_an_unregistered_project_shows_nowhere(self):
        derived = self.derive([view.ProjectState("acme/app", "/srv/app", 1, "2026-11-21T10:00:00Z", 0)],
                              engine_runs=[live_state("other/app")])
        self.assertNotIn(RUN_ID, json.dumps(derived))

    def test_no_engine_runs_gives_every_project_an_empty_list(self):
        states = [view.ProjectState(f"acme/{name}", f"/srv/{name}", n, "2026-11-21T10:00:00Z", work)
                  for n, (name, work) in enumerate([("app", 3)] + [(f"quiet{i}", 0) for i in range(view.FOLD_AFTER + 1)])]
        derived = self.derive(states)
        self.assertEqual([entry["type"] for entry in derived["entries"]], ["project", "quiet_group"])
        projects = project_entries(derived)
        self.assertEqual(len(projects), view.FOLD_AFTER + 2)
        for entry in projects:
            self.assertEqual(entry.pop("engine_runs"), [])


def stopped_state(need):
    return bare_state(stage="landing", stop={"name": "claim-lost", "need": need}, last_event=LAST_AT)


class NeedsYouTest(unittest.TestCase):
    """A stopped run that asks for the owner counts in the heading, so the page never disagrees with its line."""

    def derive(self, *states):
        projects = [view.ProjectState("acme/app", "/srv/app", 1, "2026-11-21T10:00:00Z", 0)]
        return view.derive_view(states=projects, now_ms=LAST_MS, engine_runs=list(states))

    def test_each_stop_that_asks_for_the_owner_counts_once_and_names_a_sentence(self):
        for need in ("owner-decision", "owner-look", "retry"):
            with self.subTest(need=need):
                statement = self.derive(stopped_state(need))["statement"]
                self.assertEqual((statement["inbox_items"], statement["headline"]),
                                 (1, "1 thing needs you"))
                self.assertEqual(statement["sentence"], view.ENGINE_SENTENCE)

    def test_stops_of_two_issues_count_twice(self):
        statement = self.derive(stopped_state("owner-decision"),
                                bare_state(run="42-20261121T160000Z-ab12", issue=42, stage="landing",
                                           stop={"name": "claim-lost", "need": "retry"}))["statement"]
        self.assertEqual((statement["inbox_items"], statement["headline"]), (2, "2 things need you"))

    def test_a_run_that_asks_nothing_of_the_owner_counts_none(self):
        states = (stopped_state("nothing"), live_state(), bare_state(stage="landing", done=True, last_event=LAST_AT),
                  bare_state(stage="landing", last_event=LAST_AT))
        for state in states:
            with self.subTest(reading=engine_runs.reading(state)):
                statement = self.derive(state)["statement"]
                self.assertEqual((statement["inbox_items"], statement["headline"]), (0, view.DONE_HEADLINE))

    def test_a_run_of_an_unregistered_project_counts_none(self):
        stopped = bare_state(project="other/app", stage="landing", last_event=LAST_AT,
                             stop={"name": "claim-lost", "need": "owner-decision"})
        self.assertEqual(self.derive(stopped)["statement"]["inbox_items"], 0)


class EnginePageTest(unittest.TestCase):
    def drawn(self, run):
        entry = {**page.project(0, []), "engine_runs": [run]}
        (snap,) = page.render([{"start": {"focused": False, "clock": page.NOW_MS}},
                               {"frame": page.view([entry])}, {"open": "line:owner/p00"},
                               {"snapshot": True}])
        (item,) = [n for n in page.nodes(snap["projects"]) if page.has_class(n, "run") and n["tag"] == "li"]
        return item

    def test_the_stage_of_an_open_run_is_one_member_beside_its_number(self):
        item = self.drawn({"issue": 42, "text": "stopped at claim lost, needs your decision", "wait_until": None})
        self.assertEqual([(c["cls"], page.full(c)) for c in item["children"]],
                         [("issue", "#42"), ("stage", "stopped at claim lost, needs your decision")])

    def test_an_engine_runs_spend_figure_links_to_its_spend_item(self):
        run = {"issue": 42, "run_id": RUN_ID, "text": "building, moving", "wait_until": None,
               "spend": {"tokens": 12345, "dollars": 1.5, "approximate": False}}
        item = self.drawn(run)
        self.assertEqual([c["cls"] for c in item["children"]], ["issue", "stage", "spend"])
        link = item["children"][2]
        self.assertEqual(page.full(link), "12.3k tokens, about $1.50")
        self.assertEqual(link["href"], "/spend#run=" + RUN_ID)
        for spend in ({**run["spend"], "tokens": 0}, None):
            with self.subTest(spend=spend):
                item = self.drawn({**run, "spend": spend})
                self.assertEqual([c["cls"] for c in item["children"]], ["issue", "stage"])

    def test_a_waiting_runs_until_is_part_of_its_one_sentence(self):
        until = "2026-11-24T22:04:00Z"
        item = self.drawn({"issue": 47, "text": "building, waiting out a usage limit", "wait_until": until})
        self.assertEqual([c["cls"] for c in item["children"]], ["issue", "stage"])
        stage = item["children"][1]
        self.assertEqual(len([n for n in page.nodes(stage) if n["tag"] == "time"]), 1)
        self.assertTrue(page.full(stage).startswith("building, waiting out a usage limit until "))

    def test_the_stage_wraps_inside_itself_rather_than_dropping_under_its_number(self):
        html = page.PAGE.read_text(encoding="utf-8")
        rule = re.search(r"\.outside li\.engine \.stage \{([^}]*)\}", html)
        self.assertIsNotNone(rule)
        self.assertIn("min-width: 0", rule.group(1))
        self.assertRegex(rule.group(1), r"flex: 1 1 0(px|%)?;")


class ServiceLineTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = self.root / "state/console/events.sqlite3"
        self.registry = self.root / "state/fleet/registry.json"
        items = support.entries(1)
        self.project = items[0]["project_id"]
        support.write_registry(self.registry, items)

    def holder(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        return child

    def make_run(self, runs, child):
        run_dir = make_run(runs, RUN_ID, None, project=self.project,
                           holder={"pid": child.pid, "started": "2026-11-21T16:00:00Z"})
        (run_dir / "events.jsonl").write_bytes(line(
            at="2026-11-21T16:00:00Z", event="step_entered", stage="planning", step="plan", visit=1))
        return run_dir

    def entry(self, svc):
        derived = json.loads(svc.view_bytes)
        return next(entry for entry in project_entries(derived) if entry["project_id"] == self.project)

    def test_ending_the_engine_process_turns_its_line_to_the_engine_is_not_running(self):
        runs = self.root / "runs"
        child = self.holder()
        self.make_run(runs, child)
        svc = support.service(self, self.store, self.registry, engine_runs_root=runs)
        svc.poll_engine_runs()
        self.assertEqual(self.entry(svc)["engine_runs"][0]["text"], "planning, moving")
        child.kill()
        child.wait()
        svc.poll_engine_runs()
        self.assertEqual(self.entry(svc)["engine_runs"][0]["text"], "planning, the engine is not running")
        rows = len(support.log_rows(self.store))
        svc.poll_engine_runs()
        self.assertEqual(len(support.log_rows(self.store)), rows)

    def test_an_unreadable_run_warns_once_and_keeps_its_line(self):
        runs = self.root / "runs"
        run_dir = self.make_run(runs, self.holder())
        svc = support.service(self, self.store, self.registry, engine_runs_root=runs)
        svc.poll_engine_runs()
        with run_dir.joinpath("events.jsonl").open("ab") as handle:
            handle.write(b'{"refused":1}\n')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            svc.poll_engine_runs()
            svc.poll_engine_runs()
        self.assertEqual(err.getvalue().count(f"console: engine_run_unreadable {RUN_ID} "), 1)
        self.assertEqual(self.entry(svc)["engine_runs"][0]["text"], "planning, moving")

    def test_an_unreadable_run_that_reads_again_warns_again(self):
        runs = self.root / "runs"
        run_dir = self.make_run(runs, self.holder())
        svc = support.service(self, self.store, self.registry, engine_runs_root=runs)
        events = run_dir / "events.jsonl"
        good = events.read_bytes()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            for refused in (True, False, True):
                events.write_bytes(good + b'{"refused":1}\n' if refused else good)
                svc.poll_engine_runs()
        self.assertEqual(err.getvalue().count("console: engine_run_unreadable"), 2)

    def test_the_poll_thread_reads_the_engine_runs_and_names_a_failure(self):
        svc = support.service(self, self.store, self.registry, engine_runs_root=self.root / "runs",
                              session_poll_seconds=3600)
        svc._session_poll_seconds = 0

        def fail():
            raise ValueError("boom")

        err = io.StringIO()
        with contextlib.ExitStack() as stack:
            for name in ("poll_sessions", "poll_deliveries", "renudge", "finish_stops", "revive"):
                stack.enter_context(mock.patch.object(svc, name))
            stack.enter_context(mock.patch.object(svc, "nudge_idle", side_effect=svc._stop.set))
            stack.enter_context(mock.patch.object(svc, "poll_engine_runs", side_effect=fail))
            stack.enter_context(contextlib.redirect_stderr(err))
            svc._poll_loop()
        self.assertIn("console: engine_poll_failed ValueError: boom", err.getvalue())

    def test_the_service_reads_the_engine_runs_at_startup(self):
        runs = self.root / "runs"
        self.make_run(runs, self.holder())
        svc = support.service(self, self.store, self.registry, engine_runs_root=runs)
        self.assertEqual(self.entry(svc)["engine_runs"][0]["text"], "planning, moving")

    def test_a_guest_scope_keeps_only_its_projects_engine_runs_and_no_line(self):
        scoped = guest.scoped({"engine_runs": [live_state(), live_state("other/app")], "states": []},
                              frozenset({"acme/app"}))
        self.assertEqual(scoped["engine_runs"], (live_state(),))
        self.assertIs(scoped["engine_lines"], False)
        self.assertIs(guest.scoped({"states": []}, frozenset({"acme/app"}))["engine_lines"], False)

    def test_without_a_runs_root_no_engine_run_is_read(self):
        home = self.root / "home"
        self.make_run(home / ".agents/state/engine/runs", self.holder())
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            svc = support.service(self, self.store, self.registry, engine_runs_root=None)
            svc.poll_engine_runs()
        self.assertEqual(self.entry(svc)["engine_runs"], [])

    def test_the_support_service_reads_a_fresh_empty_runs_root(self):
        home = self.root / "home"
        self.make_run(home / ".agents/state/engine/runs", self.holder())
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            svc = support.service(self, self.store, self.registry)
            svc.poll_engine_runs()
        self.assertIsNotNone(svc._engine)
        self.assertNotIn(home, Path(svc._engine._root).parents)
        self.assertEqual(self.entry(svc)["engine_runs"], [])


class ConsoleMainTest(unittest.TestCase):
    def test_the_console_passes_the_engines_runs_root(self):
        recorded = {}

        def stop(*args, **kwargs):
            recorded.update(kwargs)
            raise RuntimeError("stop")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"HOME": tmp}), \
                mock.patch.object(service, "ConsoleService", side_effect=stop):
            self.assertRaises(RuntimeError, console.main, ["--port", "0"])
            self.assertEqual(recorded["engine_runs_root"], engine_ledger.runs_root())


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
