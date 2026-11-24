"""The view's entry for a question card that carries an owner-approved action (issue 1687)."""
import dataclasses
import unittest

from agent_tools.console import answer
from agent_tools.console import sprints as sprints_module

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_view import A, asked, derive_view, started, state


class ActionViewTest(unittest.TestCase):
    def test_an_action_card_shows_its_whole_command_and_opens_with_nothing_picked(self):
        command = "curl -sS -X POST http://127.0.0.1:27999/api/plan-approve --data " + "x" * 300
        state_ = asked(started(A))
        first, *rest = state_.questions
        state_ = dataclasses.replace(state_, questions=(dataclasses.replace(
            first, owner_only=True, action=sprints_module.QuestionAction(command, first.options[0])),
            *rest))
        entries = derive_view([state("p00", 1)], sprints={A: state_})["inbox"]["open"]
        self.assertEqual(entries[0]["action"], {
            "command": command, "approve_index": 0,
            "line": answer.ACTION_APPROVES.format(option=first.options[0])})
        self.assertIs(entries[0]["consequential"], True)
        shown = entries[0]["questions"][0]
        self.assertIsNone(shown["recommended"])
        self.assertEqual(shown["badge_index"], first.options.index(first.recommended))
        self.assertNotIn("action", entries[1])
