"""The quota move's room check: whether a chosen profile is another account the manager can move to.

Run: just agent-workflow-tests
"""

import types
import unittest

from agent_tools.console import capacity, guest, quota_move, sprints

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_idle_service import RESET, IdleCase

TIER = "fast"


def entry(profile: str, state: str = "ok", **overrides) -> dict:
    row = {"profile": profile, "state": state, "excluded": False, "duplicate_of": None,
           "same_account_as": [], "owner": None, "account": None,
           "signin": {"state": "signed_in"}}
    row.update(overrides)
    return row


class RoomForMoveTest(unittest.TestCase):
    def test_room_for_move_is_another_account_with_room(self) -> None:
        readings = capacity.CapacityState({}, {})
        cases = [
            ("home", {}, None, frozenset(), True),
            ("work", {}, None, frozenset(), False),
            (None, {}, None, frozenset(), False),
            ("home", {"state": "out"}, None, frozenset(), False),
            ("home", {"duplicate_of": "x"}, None, frozenset(), False),
            ("home", {"same_account_as": ["work"]}, None, frozenset(), False),
            ("home", {"owner": "pat@x"}, "sam@x", frozenset({"pat@x"}), False),
        ]
        for choice, overrides, starter, waiting, expected in cases:
            with self.subTest(choice=choice, overrides=overrides):
                view = {"profiles": [entry("work", "out"), entry("home", **overrides)]}
                sprint = types.SimpleNamespace(manager=types.SimpleNamespace(profile="work"),
                                               started_by=starter)
                self.assertIs(quota_move.room_for_move(view, readings, {}, waiting, sprint, choice),
                              expected)


class NoteTest(unittest.TestCase):
    def test_the_note_says_why_a_manager_out_of_quota_is_not_moved(self) -> None:
        cases = [
            (None, False, False, quota_move.Note(quota_move.NO_ROOM_TEXT, False)),
            (None, True, True, quota_move.Note(quota_move.NO_ROOM_TEXT, False)),
            ("home", False, True, quota_move.Note(quota_move.UNMATCHED_TEXT, True)),
            ("home", True, True, quota_move.Note(quota_move.UNMATCHED_TEXT, True)),
            ("home", True, False, quota_move.Note(quota_move.CALLED_OFF_TEXT, True)),
            ("home", False, False, None),
        ]
        for target, cancelled, unmatched, expected in cases:
            with self.subTest(target=target, cancelled=cancelled, unmatched=unmatched):
                self.assertEqual(quota_move.note(target, cancelled, unmatched), expected)

    def test_a_guest_view_carries_no_move_note(self) -> None:
        note = quota_move.Note(quota_move.CALLED_OFF_TEXT, True)
        self.assertIsNone(guest.scoped({"moves": {"a" * 16: note}}, frozenset())["moves"])


class QuotaMoveServiceTest(IdleCase):
    def called_off(self):
        """A listed manager out of quota whose move was called off because its target lost room."""
        svc, sid = self.listed_out(listing=self.hooked_listing())
        self.sid = sid
        self.on_listing = lambda: svc.set_exclusion("home", True)
        self.poll(svc, 300)
        svc.set_exclusion("home", False)
        self.poll(svc, 400)
        return svc, sid

    def assert_moved(self, svc, sid):
        self.assertEqual([c.profile for c in self.launches.calls], ["work", "home"])
        self.assertIs(self.rows("manager.started")[-1]["moved"], True)

    def test_a_called_off_move_is_said_on_the_sprint_line_and_its_action_moves_the_manager(self) -> None:
        svc, sid = self.called_off()
        self.assertEqual(self.entry(svc, sid)["now_text"], quota_move.CALLED_OFF_TEXT)
        self.assertIs(self.entry(svc, sid)["move"], True)
        self.assertEqual(self.stops, [])
        svc.retry_manager("owner/p01", sid)
        self.drain()
        self.assertEqual(self.stops, [("s-1", "work", 1)])
        self.assert_moved(svc, sid)
        self.assertNotIn(sid, svc._move_cancelled)

    def test_a_manager_the_record_does_not_match_is_said_and_moved_from_the_line(self) -> None:
        svc, sid = self.listed_out()
        self.gone(svc)
        self.poll(svc, 600)
        self.assertEqual(len(self.rows("manager.held")), 1)
        self.poll(svc, 700)
        self.assertEqual(self.entry(svc, sid)["now_text"], quota_move.UNMATCHED_TEXT)
        self.assertIs(self.entry(svc, sid)["move"], True)
        svc.retry_manager("owner/p01", sid)
        self.drain()
        self.assertEqual(self.stops, [("s-1", "work", 1)])
        self.assert_moved(svc, sid)
        self.assertNotIn(sid, svc._unmatched)

    def test_an_asked_move_of_a_manager_no_longer_listed_starts_it_on_the_account_with_room(self) -> None:
        svc, sid = self.start_out(listed=False, stopper=self.stopper, listing=self.hooked_listing())
        self.sid = sid
        self.gone(svc)
        self.on_listing = lambda: svc.set_exclusion("home", True)
        self.poll(svc, 600)
        self.assertEqual([c.profile for c in self.launches.calls], ["work"])
        self.assertIn(sid, svc._move_cancelled)
        svc.set_exclusion("home", False)
        self.poll(svc, 700)
        self.assertIs(self.entry(svc, sid)["move"], True)
        svc.retry_manager("owner/p01", sid)
        self.drain()
        self.assertEqual(self.stops, [])
        self.assert_moved(svc, sid)

    def test_the_move_is_refused_where_the_line_offers_none(self) -> None:
        def no_room():
            svc, sid = self.listed_out()
            self.readings(svc, lambda p: self.exhausted(RESET))
            self.poll(svc, 300)
            self.assertEqual(self.entry(svc, sid)["now_text"], quota_move.NO_ROOM_TEXT)
            return svc, sid, sprints.HAS_MANAGER

        def has_room():
            svc, sid = self.idle_service()
            self.poll(svc, 300)
            self.assertNotEqual(self.entry(svc, sid)["now_text"], quota_move.CALLED_OFF_TEXT)
            return svc, sid, sprints.HAS_MANAGER

        def target_lost():
            svc, sid = self.called_off()
            svc.set_exclusion("home", True)
            return svc, sid, quota_move.NO_ROOM_REFUSAL

        for name, arrange in (("no other account has room", no_room), ("its account has room", has_room),
                              ("the target lost room since the line", target_lost)):
            with self.subTest(name):
                self.setUp()
                svc, sid, refusal = arrange()
                if name != "the target lost room since the line":
                    self.assertIs(self.entry(svc, sid)["move"], False)
                with self.assertRaises(sprints.Refused) as raised:
                    svc.retry_manager("owner/p01", sid)
                self.assertEqual(str(raised.exception), refusal)
                self.assertNotIn(sid, svc._launching)
                self.assertEqual([c.profile for c in self.launches.calls], ["work"])


if __name__ == "__main__":
    unittest.main()
