"""The manager session is the one the console launched: its short id decides, not a listing.

Run: just agent-workflow-tests
"""
import unittest

from agent_tools.console import manager, sprints
from agent_tools.console.event_log import (MANAGER_FAILED, MANAGER_STARTED, MANAGER_WAITING,
                                           Event)

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_sprints import SID, at, managed, ms, seen, stated

TIER = "fast"

TAKEOVER = "bbbbbbbb-2222-4222-8222-222222222222"
NAMESAKE = "cccccccc-3333-4333-8333-333333333333"
NAME = "p00 sprint " + SID
GOAL = stated(1, "p00", SID, "one")


def listing(seq, session_id=NAMESAKE):
    return Event(seq, at(seq), "session.seen", "p00", {
        "session_id": session_id, "cwd": "/srv/p00", "repo": "/srv/p00", "state": "idle",
        "name": NAME})


def started(seq, **payload):
    return managed(seq, SID, MANAGER_STARTED, profile="work", session_name=NAME, **payload)


def state_of(rows):
    return sprints.sprint_states(rows)[SID]


class ManagerIdentityTest(unittest.TestCase):
    def test_only_a_printed_short_id_of_the_exact_form_is_marked(self):
        table = [("aaaaaaaa", "aaaaaaaa"), (None, None), ("AAAAAAAA", None), ("aaaaaaa", None),
                 ("aaaaaaaa-1111", None), (12345678, None), ("", None)]
        for printed, launched in table:
            with self.subTest(printed=printed):
                self.assertEqual(manager.launched_short_id(printed), launched)
                self.assertEqual(manager.short_id_mark(printed),
                                 {} if launched is None else {"short_id": launched})

    def test_each_started_row_sets_or_clears_the_launched_short_id(self):
        first = started(2, short_id="aaaaaaaa")
        second = started(3, short_id="bbbbbbbb")
        self.assertEqual(state_of([GOAL, first]).manager_short_id, "aaaaaaaa")
        self.assertEqual(state_of([GOAL, first, second]).manager_short_id, "bbbbbbbb")
        self.assertIsNone(state_of([GOAL, first, second, started(4)]).manager_short_id)
        for bad in ("BBBBBBBB", "bbbbbbb", 12345678, None, "bbbbbbbb-2222"):
            with self.subTest(bad=bad):
                self.assertIsNone(
                    state_of([GOAL, first, second, started(4, short_id=bad)]).manager_short_id)
        kept = [GOAL, first, second]
        others = [managed(4, SID, MANAGER_FAILED, reason="x"),
                  managed(4, SID, MANAGER_WAITING, until=None), listing(4)]
        for other in others:
            with self.subTest(kind=other.kind):
                self.assertEqual(state_of([*kept, other]).manager_short_id, "bbbbbbbb")
        invalid = managed(4, SID, MANAGER_STARTED, session_name=NAME, short_id="aaaaaaaa")
        self.assertEqual(state_of([*kept, invalid]).manager_short_id, "bbbbbbbb")
        rows = [*kept, *others, invalid, started(5)]
        for cut in range(len(rows) + 1):
            with self.subTest(cut=cut):
                self.assertEqual(
                    sprints.sprint_states(rows[cut:], sprints.sprint_states(rows[:cut])),
                    sprints.sprint_states(rows))

    def test_the_launched_session_is_the_manager_and_the_listed_one_is_not(self):
        launched = state_of([GOAL, started(2, short_id="bbbbbbbb"), listing(3)])
        for session_id, expected in ((TAKEOVER, True), (NAMESAKE, False), ("bbbbbbb", False),
                                     ("", False)):
            with self.subTest(launched=session_id):
                self.assertIs(manager.is_manager_session(launched, session_id), expected)
        listed = state_of([GOAL, started(2), listing(3)])
        for session_id, expected in ((NAMESAKE, True), (TAKEOVER, False), ("", False)):
            with self.subTest(listed=session_id):
                self.assertIs(manager.is_manager_session(listed, session_id), expected)
        self.assertIs(manager.is_manager_session(state_of([GOAL]), ""), False)

    def test_a_delivery_of_the_launched_session_is_the_managers_own(self):
        rows = [GOAL, started(2, short_id="bbbbbbbb"),
                seen(3, "r-1", ms(3), ((12, "building"),), project="p00", session_id=TAKEOVER),
                listing(4),
                seen(5, "r-2", ms(5), ((40, "queued"),), project="p00", session_id=NAMESAKE)]
        self.assertEqual(state_of(rows).delivered, frozenset({12}))


if __name__ == "__main__":
    unittest.main()
