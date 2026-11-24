"""A question card's owner-approved action: its refusals, its fold and the use that spends it."""
import unittest

from agent_tools.console import action_card, event_log, sprints
from agent_tools.console.event_log import Event

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_sprints import QUESTION, SID, answer_row, asked, at, question_state


ACTION_COMMAND = "curl -sS -X POST http://127.0.0.1:27999/api/plan-approve --data @/tmp/approve.json"
ACTION = {**QUESTION, "owner_only": True, "action": {"command": ACTION_COMMAND, "approve": "sqlite"}}


def action_row(seq, **changes):
    payload = {"sprint_id": SID, "session_id": "s-1", "tool_use_id": "t-1", "repo": None,
               "verb": "action", "decision": "allow", "reason": "",
               "target": {"round": 41, "index": 0}}
    return Event(seq, at(seq), event_log.PERMIT_JUDGED, "owner/p00", {**payload, **changes})


class ActionCardTest(unittest.TestCase):
    def refused(self, question):
        with self.assertRaises(sprints.Refused) as raised:
            sprints.checked_round({"questions": [question]})
        return str(raised.exception)

    def test_an_owner_only_question_naming_one_command_keeps_its_action(self):
        checked = sprints.checked_round({"questions": [ACTION]})
        state = question_state([asked(41, SID, [ACTION])])
        self.assertEqual(checked["questions"][0]["action"],
                         {"command": ACTION_COMMAND, "approve": "sqlite"})
        self.assertEqual(state.questions[0].action, sprints.QuestionAction(ACTION_COMMAND, "sqlite"))
        self.assertIsNone(state.questions[0].action_used_at)
        self.assertNotIn("action", sprints.checked_round({"questions": [QUESTION]})["questions"][0])

    def test_an_action_must_be_owner_only(self):
        self.assertEqual(self.refused({**QUESTION, "action": ACTION["action"]}),
                         action_card.ACTION_OWNER_ONLY.format(n=1))

    def test_a_malformed_action_is_refused_by_shape(self):
        for value in ("curl x", [], {"command": ACTION_COMMAND},
                      {"command": ACTION_COMMAND, "approve": "sqlite", "why": "x"},
                      {"command": 7, "approve": "sqlite"},
                      {"command": ACTION_COMMAND, "approve": None}):
            with self.subTest(value=value):
                self.assertEqual(self.refused({**ACTION, "action": value}),
                                 action_card.ACTION_SHAPE.format(n=1))

    def test_an_action_command_must_be_one_exact_line(self):
        for command in ("", "a\nb", "a\rb", " curl x", "curl x ", "curl\tx", "curl \x07x",
                        "x" * 4097):
            with self.subTest(command=command):
                self.assertEqual(
                    self.refused({**ACTION, "action": {"command": command, "approve": "sqlite"}}),
                    action_card.ACTION_COMMAND.format(n=1))
        whole = "x" * 4096
        checked = sprints.checked_round({"questions": [
            {**ACTION, "action": {"command": whole, "approve": "sqlite"}}]})
        self.assertEqual(checked["questions"][0]["action"]["command"], whole)

    def test_an_action_command_refuses_invisible_reordering_and_line_characters(self):
        for command in ("echo hi \u202e; x=\u2066 rm -rf ~ \u2069 #",
                        "echo ok\x85curl x", "echo ok\u2028curl x", "echo ok\u2029curl x",
                        "a\u202ab", "a\u202bb", "a\u202cb", "a\u202db", "a\u2067b",
                        "a\u2068b", "a\u200eb", "a\u200fb", "a\u200bb", "a\x9bb"):
            with self.subTest(command=command):
                self.assertEqual(
                    self.refused({**ACTION, "action": {"command": command, "approve": "sqlite"}}),
                    action_card.ACTION_COMMAND.format(n=1))
        hebrew = "echo hi \u05d0# ;>\u05d0 rm -rf ~"  # drawn in logical order by the card's CSS
        arabic = "echo \u0627\u0628 \u0661\u0662"
        for command in (hebrew, arabic):
            checked = sprints.checked_round({"questions": [
                {**ACTION, "action": {"command": command, "approve": "sqlite"}}]})
            self.assertEqual(checked["questions"][0]["action"]["command"], command)
        accented = "echo caf\u00e9 \u65e5\u672c"
        checked = sprints.checked_round({"questions": [
            {**ACTION, "action": {"command": accented, "approve": "sqlite"}}]})
        self.assertEqual(checked["questions"][0]["action"]["command"], accented)

    def test_an_action_cannot_be_a_merge_rerun_or_release(self):
        for command in ("gh pr merge 7 --repo o/r --merge --match-head-commit " + "a" * 40,
                        "env -u GITHUB_TOKEN gh run rerun 5 --failed --repo o/r",
                        "release transaction run --commit abc --version v1",
                        "release transaction abandon --repo-root r"):
            with self.subTest(command=command):
                self.assertEqual(
                    self.refused({**ACTION, "action": {"command": command, "approve": "sqlite"}}),
                    action_card.ACTION_PERMIT_VERB.format(n=1))

    def test_the_approve_option_must_be_an_option_that_takes_no_words(self):
        self.assertEqual(
            self.refused({**ACTION, "action": {"command": ACTION_COMMAND, "approve": "postgres"}}),
            action_card.ACTION_APPROVE.format(n=1))
        self.assertEqual(self.refused({**ACTION, "needs_words": ["sqlite"]}),
                         action_card.ACTION_APPROVE_WORDS.format(n=1))
        checked = sprints.checked_round({"questions": [
            {**ACTION, "action": {"command": ACTION_COMMAND, "approve": " sqlite "}}]})
        self.assertEqual(checked["questions"][0]["action"]["approve"], "sqlite")

    def test_an_action_cannot_ride_on_a_look(self):
        look = {"issue": 1, "pr": 2, "head": "a" * 40, "approve": "sqlite"}
        self.assertEqual(self.refused({**ACTION, "look": look}),
                         action_card.ACTION_WITH_LOOK.format(n=1))

    def test_an_allowed_action_row_marks_the_approval_used(self):
        before = [asked(41, SID, [ACTION]),
                  answer_row(42, SID, 41, 0, "sqlite", "sqlite", recommended="files")]
        state = question_state([*before, action_row(43)])
        self.assertEqual(state.questions[0].action_used_at, at(43))
        for name, row in (("deny", action_row(43, decision="deny")),
                          ("merge", action_row(43, verb="merge")),
                          ("other index", action_row(43, target={"round": 41, "index": 1})),
                          ("bool index", action_row(43, target={"round": 41, "index": True})),
                          ("extra member", action_row(43, target={"round": 41, "index": 0, "x": 1})),
                          ("other sprint", action_row(43, sprint_id="f" * 16))):
            with self.subTest(name=name):
                self.assertIsNone(question_state([*before, row]).questions[0].action_used_at)
        with self.subTest(name="unanswered"):
            state = question_state([asked(41, SID, [ACTION]), action_row(43)])
            self.assertIsNone(state.questions[0].action_used_at)
        again = question_state([*before, action_row(43), action_row(44)])
        self.assertEqual(again.questions[0].action_used_at, at(43))
