"""A sprint reads its engine runs' movement and waits from their events.

Run: just agent-workflow-tests
"""

import json
import tempfile
import unittest
from pathlib import Path

from agent_tools.console import engine_runs, guest, view
from agent_tools.console.engine_runs import EngineRuns
from agent_tools.console.movement import ProjectMovement, PullMovement, SessionMovement
from agent_tools.console.sprints import NOW_CI_TEXT, NOW_LOCK_TEXT

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_engine_runs import DEAD, LIVE, make_run
from .test_console_view import (
    A, MIN, R, entry, idle_session, line, moving, reported, started, state, with_manager)

TIER = "fast"

BASE = reported(with_manager(started(A)), R)
NOW = R + 40 * MIN


def engine_state(fixture, probe, issue=4, project="p00"):
    with tempfile.TemporaryDirectory() as tmp:
        make_run(tmp, f"{issue}-20261112T100100Z-ab12", fixture, issue=issue, project=project)
        return EngineRuns(Path(tmp), alive=probe).poll().states[0]


ROOT = "4-20261112T100100Z-ab12"
CHILD = "4-20261112T100200Z-c0a1"
GRANDCHILD = "4-20261112T100300Z-c0a2"


def engine_state_with_children(root_fixture, probe, *children):
    """The root run's state, polled with child runs `(name, parent)` whose ledger is sprint-child.jsonl."""
    with tempfile.TemporaryDirectory() as tmp:
        make_run(tmp, ROOT, root_fixture, issue=4, project="p00")
        for name, parent in children:
            make_run(tmp, name, "sprint-child.jsonl", issue=4, project="p00", parent=parent, holder=None)
        return EngineRuns(Path(tmp), alive=probe).poll().states[0]


def shown(engine_runs=(), movement=None, sprint_state=BASE, now=NOW):
    extra = {} if movement is None else {"movement": movement}
    return entry(line(sprint_state, now, sessions=[idle_session], engine_runs=list(engine_runs), **extra))


def session_movement(*sessions):
    return {"p00": ProjectMovement(sessions=tuple(sessions))}


class SprintEngineMovementTest(unittest.TestCase):
    def test_a_sprint_whose_only_signal_is_an_engine_run_forty_minutes_into_its_step_reads_moving(self):
        live = engine_state("sprint-moving.jsonl", LIVE)
        got = shown(engine_runs=[live])
        self.assertEqual((got["state"], got["ball"], got["ball_text"], got["now_text"]),
                         ("on_track", "manager", "manager working", "building 1 of 7: Importer resumes"))
        self.assertNotIn("stuck", json.dumps(got))
        with self.subTest("no engine run"):
            self.assertEqual(shown()["state"], "quiet")

    def test_a_run_whose_engine_is_gone_stops_moving_its_sprint_at_once_whatever_its_sessions_wrote(self):
        dead = engine_state("sprint-moving.jsonl", DEAD)
        movement = session_movement(SessionMovement("eng-s1", A, NOW - MIN, NOW - MIN, None, read_ms=NOW - MIN))
        got = shown(engine_runs=[dead], movement=movement)
        alive = shown(engine_runs=[engine_state("sprint-moving.jsonl", LIVE)])
        self.assertEqual(alive["state"], "on_track")
        self.assertEqual((got["state"], got["state_text"], got["ball"]),
                         ("quiet", "quiet for 40 min — may be stuck", "nobody"))
        self.assertTrue(got["now_text"].startswith("last seen "))

    def test_a_gone_engines_call_step_sessions_in_a_child_run_do_not_move_its_sprint(self):
        movement = session_movement(SessionMovement("c1", A, NOW - MIN, NOW - MIN, None, read_ms=NOW - MIN))
        for label, fixture, children in (
                ("fan-out", "fanout.jsonl", ((CHILD, ROOT),)),
                ("direct lane", "moving.jsonl", ((CHILD, ROOT),)),
                ("a child of a child", "fanout.jsonl", ((CHILD, ROOT), (GRANDCHILD, CHILD)))):
            with self.subTest(label):
                dead = engine_state_with_children(fixture, DEAD, *children)
                self.assertIn("c1", dead.sessions)
                got = shown(engine_runs=[dead], movement=movement)
                self.assertEqual((got["state"], got["ball"]), ("quiet", "nobody"))
        with self.subTest("a child of no shown run"):
            dead = engine_state_with_children("fanout.jsonl", DEAD, (CHILD, "4-20261112T100000Z-ffff"))
            self.assertNotIn("c1", dead.sessions)

    def test_a_managers_own_session_output_still_moves_its_sprint_beside_a_gone_engine(self):
        dead = engine_state("sprint-moving.jsonl", DEAD)
        movement = session_movement(SessionMovement("s1", A, NOW - MIN, None, None, read_ms=NOW - MIN))
        got = shown(engine_runs=[dead], movement=movement)
        self.assertEqual((got["state"], got["ball"]), ("on_track", "manager"))

    def test_a_stopped_run_moves_its_sprint_no_more(self):
        self.assertEqual(shown(engine_runs=[engine_state("stopped.jsonl", LIVE)])["state"], "quiet")

    def test_an_engine_run_of_another_issue_or_project_moves_nothing(self):
        for label, state in (("issue", engine_state("sprint-moving.jsonl", LIVE, issue=99)),
                             ("project", engine_state("sprint-moving.jsonl", LIVE, project="other"))):
            with self.subTest(label):
                self.assertEqual(shown(engine_runs=[state])["state"], "quiet")

    def test_with_no_clock_the_sprint_reads_as_before(self):
        dead = engine_state("sprint-moving.jsonl", DEAD)
        got = entry(line(BASE, None, sessions=[idle_session], engine_runs=[dead]))
        self.assertEqual(got["ball"], "manager")

    def test_an_engine_runs_iterator_feeds_both_the_run_line_and_the_sprint(self):
        live = engine_state("sprint-moving.jsonl", LIVE)
        derived = line(BASE, NOW, sessions=[idle_session], engine_runs=iter([live]))
        self.assertEqual(len(derived["entries"][0]["engine_runs"]), 1)
        self.assertEqual(entry(derived)["ball"], "manager")


class SprintEngineEntryTest(unittest.TestCase):
    def test_the_sprint_entry_publishes_its_engine_reading(self):
        for label, runs, reading in (
                ("moving", [engine_state("sprint-moving.jsonl", LIVE)], {"moving": True, "waits": []}),
                ("ci", [engine_state("sprint-ci.jsonl", LIVE)], {"moving": False, "waits": ["ci"]}),
                ("no engine run", [], {"moving": False, "waits": []})):
            with self.subTest(label):
                self.assertEqual(shown(engine_runs=runs)["movement"]["engine"], reading)


class SprintEngineWaitTest(unittest.TestCase):
    def test_with_no_forge_reading_an_open_ci_wait_and_an_open_lock_wait_read_their_sentences(self):
        for fixture, text in (("sprint-ci.jsonl", "waiting for CI on its pull request"),
                              ("sprint-lock.jsonl", "waiting its turn to merge")):
            with self.subTest(fixture):
                got = shown(engine_runs=[engine_state(fixture, LIVE)])
                self.assertEqual((got["state"], got["ball"], got["now_text"]), ("on_track", "manager", text))
                self.assertNotIn("stuck", json.dumps(got))

    def test_the_run_line_and_the_sprint_line_give_one_wait_sentence(self):
        for wait in ("ci", "lock", "usage-limit", "host-slot"):
            with self.subTest(wait):
                run = engine_state(f"sprint-{wait}.jsonl", LIVE)
                derived = line(BASE, NOW, sessions=[idle_session], engine_runs=[run])
                run_text = derived["entries"][0]["engine_runs"][0]["text"]
                now_text = entry(derived)["now_text"]
                self.assertEqual(run_text, f"building, {now_text}")
                self.assertEqual(now_text, engine_runs.wait_text(run))

    def test_a_usage_limit_and_a_free_slot_read_the_run_lines_sentences(self):
        for fixture, text in (("sprint-usage-limit.jsonl", "waiting out a usage limit"),
                              ("sprint-host-slot.jsonl", "waiting for a free session slot on this host")):
            with self.subTest(fixture):
                got = shown(engine_runs=[engine_state(fixture, LIVE)])
                self.assertEqual((got["ball"], got["now_text"]), ("manager", text))

    def test_a_usage_limit_sprint_block_carries_the_end_time_its_run_line_shows(self):
        run = engine_state("sprint-usage-limit.jsonl", LIVE)
        got = shown(engine_runs=[run])
        self.assertEqual(got["now_until"], "2026-11-12T12:00:00Z")
        self.assertEqual(got["now_until"], line(BASE, NOW, sessions=[idle_session], engine_runs=[run])
                         ["entries"][0]["engine_runs"][0]["wait_until"])

    def test_a_wait_with_no_end_time_leaves_the_sprint_block_without_one(self):
        for fixture in ("sprint-host-slot.jsonl", "sprint-ci.jsonl", "sprint-lock.jsonl"):
            with self.subTest(fixture):
                self.assertIsNone(shown(engine_runs=[engine_state(fixture, LIVE)])["now_until"])

    def test_a_limit_beside_a_ci_wait_names_the_ci_wait_and_no_end_time(self):
        runs = [engine_state("sprint-usage-limit.jsonl", LIVE, issue=4), engine_state("sprint-ci.jsonl", LIVE, issue=5)]
        got = shown(engine_runs=runs)
        self.assertEqual((got["now_text"], got["now_until"]), (NOW_CI_TEXT, None))

    def test_engine_waits_follow_ci_commit_release_and_lock_in_that_order(self):
        release = moving(release_ms=NOW - MIN)
        for label, fixtures, movement, text in (
                ("ci beats a slot", ("sprint-host-slot.jsonl", "sprint-ci.jsonl"), None, NOW_CI_TEXT),
                ("lock beats a limit", ("sprint-lock.jsonl", "sprint-usage-limit.jsonl"), None, NOW_LOCK_TEXT),
                ("limit beats a slot", ("sprint-usage-limit.jsonl", "sprint-host-slot.jsonl"), None,
                 "waiting out a usage limit"),
                ("release beats a lock", ("sprint-lock.jsonl",), release, "waiting for a release step"),
                ("ci beats a release", ("sprint-ci.jsonl",), release, NOW_CI_TEXT)):
            with self.subTest(label):
                runs = [engine_state(fixture, LIVE, issue=4 + number) for number, fixture in enumerate(fixtures)]
                self.assertEqual(shown(engine_runs=runs, movement=movement)["now_text"], text)

    def test_a_moving_run_beside_a_waiting_one_names_no_wait(self):
        runs = [engine_state("sprint-moving.jsonl", LIVE, issue=4), engine_state("sprint-ci.jsonl", LIVE, issue=5)]
        self.assertEqual(shown(engine_runs=runs)["now_text"], "building 1 of 7: Importer resumes")

    def test_the_forge_is_not_read_for_an_issue_an_engine_run_carries(self):
        ci_on_4 = moving(pulls=(PullMovement(40, frozenset({4}), NOW - MIN, None),), read_ms=NOW - MIN)
        dead = engine_state("sprint-moving.jsonl", DEAD)
        self.assertEqual(shown(movement=ci_on_4)["now_text"], NOW_CI_TEXT)
        self.assertEqual(shown(engine_runs=[dead], movement=ci_on_4)["state"], "quiet")
        ci_on_5 = moving(pulls=(PullMovement(41, frozenset({5}), NOW - MIN, None),), read_ms=NOW - MIN)
        self.assertEqual(shown(engine_runs=[dead], movement=ci_on_5)["now_text"], NOW_CI_TEXT)
        placed = shown(engine_runs=[engine_state("sprint-lock.jsonl", LIVE)], movement=moving(positions=((4, 2),)))
        self.assertEqual(placed["now_text"], "waiting its turn to merge")

    def test_with_no_clock_no_engine_wait_is_named(self):
        got = entry(line(BASE, None, sessions=[idle_session], engine_runs=[engine_state("sprint-ci.jsonl", LIVE)]))
        self.assertEqual(got["now_text"], "building 1 of 7: Importer resumes")


if __name__ == "__main__":
    unittest.main()


class GuestSprintEngineTest(unittest.TestCase):
    def test_a_guests_sprint_reads_its_engine_run_and_the_guest_sees_no_run_line(self):
        stopped = engine_state("stopped.jsonl", LIVE, issue=5)
        inputs = {"states": [state("p00", 1)], "sprints": {A: BASE}, "sessions": [idle_session],
                  "now_ms": NOW, "engine_runs": [engine_state("sprint-moving.jsonl", LIVE), stopped]}
        owner = view.derive_view(**inputs)
        guest_view = view.derive_view(**guest.scoped(inputs, frozenset({"p00"})))
        reading = ("on_track", "manager", "building 1 of 7: Importer resumes")
        for derived in (owner, guest_view):
            got = entry(derived)
            self.assertEqual((got["state"], got["ball"], got["now_text"]), reading)
        self.assertEqual(len(owner["entries"][0]["engine_runs"]), 2)
        self.assertEqual(guest_view["entries"][0]["engine_runs"], [])
        self.assertEqual((owner["statement"]["inbox_items"], guest_view["statement"]["inbox_items"]), (1, 0))

    def test_without_engine_lines_no_engine_run_makes_a_project_active(self):
        live = engine_state("sprint-moving.jsonl", LIVE, project="acme/app")
        project = view.ProjectState("acme/app", "/srv/app", 1, "2026-11-21T10:00:00Z", 0)
        hidden = view.derive_view(states=[project], now_ms=NOW, engine_runs=[live], engine_lines=False)
        shown_ = view.derive_view(states=[project], now_ms=NOW, engine_runs=[live])
        self.assertIs(hidden["entries"][0]["quiet"], True)
        self.assertEqual(hidden["entries"][0]["engine_runs"], [])
        self.assertIs(shown_["entries"][0]["quiet"], False)
        self.assertEqual(len(shown_["entries"][0]["engine_runs"]), 1)
