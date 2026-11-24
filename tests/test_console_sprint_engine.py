"""A sprint reads its engine runs' movement and waits from their events (#1531).

Run: just agent-workflow-tests
"""

import json
import tempfile
import unittest
from pathlib import Path

from agent_tools.console.engine_runs import EngineRuns
from agent_tools.console.movement import ProjectMovement, SessionMovement

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_engine_runs import DEAD, LIVE, make_run
from .test_console_view import A, MIN, R, entry, idle_session, line, reported, started, with_manager

TIER = "fast"

BASE = reported(with_manager(started(A)), R)
NOW = R + 40 * MIN


def engine_state(fixture, probe, issue=4, project="p00"):
    with tempfile.TemporaryDirectory() as tmp:
        make_run(tmp, f"{issue}-20261112T100100Z-ab12", fixture, issue=issue, project=project)
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


if __name__ == "__main__":
    unittest.main()
