"""The quota move's room check: whether a chosen profile is another account the manager can move to.

Run: just agent-workflow-tests
"""

import types
import unittest

from agent_tools.console import capacity, quota_move

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

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


if __name__ == "__main__":
    unittest.main()
