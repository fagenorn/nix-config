"""The desk page's sprint line offering a move to another account."""

import json
import unittest

from agent_tools.console import quota_move

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_page import GOAL_HEADERS, SPRINT, full, has_class, nodes, render, sprint_lines, START, with_sprints

TIER = "fast"


class PageMoveTest(unittest.TestCase):
    def test_a_sprint_line_offering_a_move_posts_it_and_says_a_failure(self) -> None:
        sprint = {**SPRINT, "state": "quota", "state_text": "waiting on quota until",
                  "now_text": quota_move.CALLED_OFF_TEXT, "manager_state": "started",
                  "manager_text": None, "retry": False, "move": True}
        (snap,) = render([
            START, {"frame": with_sprints([sprint])},
            {"respond": {"status": 409, "text": "no other account has room\n"}},
            {"click": "move"}, {"frame": with_sprints([sprint])}, {"snapshot": True},
        ])
        (line,) = sprint_lines(snap)
        self.assertIn(quota_move.CALLED_OFF_TEXT, full(line))
        buttons = [n for n in nodes(line) if n["tag"] == "button"]
        (move,) = [n for n in buttons if has_class(n, "move")]
        self.assertEqual(full(move), "Move to another account")
        self.assertEqual([n for n in buttons if has_class(n, "retry")], [])
        (post,) = [p for p in snap["posts"] if p["url"] == "/api/retry-manager"]
        self.assertEqual(post["headers"], GOAL_HEADERS)
        self.assertEqual(json.loads(post["body"]), {"project_id": "owner/p00", "sprint_id": "a" * 16})
        self.assertIn("Could not move: no other account has room", full(line))
        (quiet,) = render([START, {"frame": with_sprints([{**sprint, "move": False}])}, {"snapshot": True}])
        (line,) = sprint_lines(quiet)
        self.assertEqual([n for n in nodes(line) if n["tag"] == "button" and has_class(n, "move")], [])


if __name__ == "__main__":
    unittest.main()
