"""Whether an idle manager is told to go on (#929).

Run: just agent-workflow-tests
"""

import unittest
from dataclasses import replace

from agent_tools.console import idle
from agent_tools.console.sessions import SessionState
from agent_tools.console.sprints import Manager
from tests.test_console_view import A, MIN, R, T0, gone, iso, reported, seen, sprint, started

NAME = "p00 sprint " + A
ON = reported(replace(started(A), manager=Manager("started", T0, "work", NAME)), R)
IDLE_AT = R + MIN


def session(state="idle", at_ms=IDLE_AT):
    return SessionState("s-1", "/r", "/r", state, NAME, 1, iso(at_ms), None)


def step(state=ON, now=IDLE_AT + 5 * MIN, waiting=0, sess=None, active=None, out=False,
         forced=False):
    return idle.next_step(state, waiting, sess or session(), active, out, now, forced)


class IdleStepTest(unittest.TestCase):
    def test_an_idle_manager_of_a_sprint_with_work_is_nudged_after_five_minutes(self):
        self.assertIsNone(step(now=IDLE_AT + 5 * MIN - 1))
        self.assertEqual(step(now=IDLE_AT + 5 * MIN), idle.NUDGE)

    def test_only_an_idle_or_limit_session_is_nudged(self):
        for state in ("working", "waiting_answer", "waiting_permission"):
            with self.subTest(state):
                self.assertIsNone(step(now=IDLE_AT + 30 * MIN, sess=session(state)))
        self.assertEqual(step(now=IDLE_AT + 30 * MIN, sess=session("limit")), idle.NUDGE)
        self.assertIsNone(idle.next_step(ON, 0, None, None, False, IDLE_AT + 30 * MIN))

    def test_a_run_of_the_manager_session_that_moved_holds_the_nudge(self):
        now = IDLE_AT + 10 * MIN
        self.assertIsNone(step(now=now, active=now - 5 * MIN + 1))
        self.assertEqual(step(now=now, active=now - 5 * MIN), idle.NUDGE)

    def test_no_nudge_within_ten_minutes_of_the_last(self):
        now = IDLE_AT + 30 * MIN
        for at_ms, expected in ((now - 10 * MIN + 1, None), (now - 10 * MIN, idle.NUDGE)):
            with self.subTest(at_ms=at_ms):
                state = replace(ON, idle_nudges=1, idle_nudged_at=iso(at_ms))
                self.assertEqual(step(state, now=now), expected)

    def test_a_fourth_due_nudge_is_a_give_up_and_an_open_item_holds_everything(self):
        now = IDLE_AT + 30 * MIN
        self.assertEqual(step(replace(ON, idle_nudges=2), now=now), idle.NUDGE)
        self.assertEqual(step(replace(ON, idle_nudges=3), now=now), idle.GIVE_UP)
        held = replace(ON, idle_nudges=3, no_progress_at=iso(R))
        self.assertIsNone(step(held, now=now))

    def test_out_of_quota_sends_nothing(self):
        now = IDLE_AT + 30 * MIN
        self.assertIsNone(step(now=now, out=True))
        self.assertIsNone(step(now=now, out=True, forced=True))

    def test_forced_skips_only_the_idle_time_and_the_spacing(self):
        now = IDLE_AT + 30 * MIN
        state = replace(ON, idle_nudges=1, idle_nudged_at=iso(now))
        fresh = session(at_ms=now)
        self.assertIsNone(step(state, now=now, sess=fresh))
        self.assertEqual(step(state, now=now, sess=fresh, forced=True), idle.NUDGE)
        self.assertIsNone(step(state, now=now, sess=session("working", now), forced=True))

    def test_a_sprint_without_work_is_never_nudged(self):
        now = IDLE_AT + 30 * MIN
        manager = Manager("started", T0, "work", NAME)

        def with_manager(state, **changes):
            return replace(state, manager=manager, **changes)

        cases = {
            "waiting on the owner": (ON, 1, now),
            "closing": (reported(with_manager(started(A)), R, phase="closing"), 0, now),
            "closing, quiet clock": (reported(with_manager(started(A)), R, phase="closing"), 0,
                                     R + 20 * MIN),
            "done": (reported(with_manager(started(A)), R, phase="done"), 0, now),
            "drafting": (with_manager(sprint(A)), 0, now),
            "stopping": (replace(ON, stop_at=T0), 0, now),
            "stopped": (replace(ON, stopped_at=T0), 0, now),
            "stalled": (replace(ON, stalled="r"), 0, now),
            "failed": (replace(ON, manager=Manager("failed", T0, reason="x")), 0, now),
            "waiting": (replace(ON, manager=Manager("waiting", T0, until=None)), 0, now),
            "no manager": (replace(ON, manager=None), 0, now),
        }
        for name, (state, waiting, at_ms) in cases.items():
            with self.subTest(name):
                self.assertIsNone(step(state, now=at_ms, waiting=waiting,
                                       sess=session(at_ms=IDLE_AT)))
        self.assertEqual(step(with_manager(started(A)), now=now), idle.NUDGE)


class LastMovedTest(unittest.TestCase):
    def test_the_last_movement_of_a_session_outlives_its_run(self):
        bad_moved = replace(seen(5, "s-3", "wf_4", 0, []),
                            payload={"session_id": "s-3", "run_id": "wf_4", "moved_ms": True,
                                     "issues": []})
        bad_session = replace(seen(6, None, "wf_5", 9, []),
                              payload={"session_id": None, "run_id": "wf_5", "moved_ms": 9,
                                       "issues": []})
        rows = [seen(1, "s-1", "wf_1", 1000, []), seen(2, "s-1", "wf_2", 500, []),
                gone(3, "s-1", "wf_1"), seen(4, "s-2", "wf_3", 7, []), bad_moved, bad_session]
        expected = {"s-1": 1000, "s-2": 7}
        self.assertEqual(idle.last_moved(rows), expected)
        self.assertEqual(idle.last_moved(rows[3:], idle.last_moved(rows[:3])), expected)


if __name__ == "__main__":
    unittest.main()
