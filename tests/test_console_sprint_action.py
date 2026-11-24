"""The `sprint` command and its contract for an owner-approved action card (issue 1687)."""
import json
import unittest

from .test_console_questions import Q0
from . import test_console_sprint_command as commands
from .test_console_sprint_command import CONTRACT, run_sprint
from .test_console_writes import Case
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)


class SprintActionTest(Case):
    open, goal, files, sent, page, port, asking, asked_rows = (
        commands.SprintCommandTest.open, commands.SprintCommandTest.goal, commands.SprintCommandTest.files,
        commands.SprintCommandTest.sent, commands.SprintCommandTest.page, commands.SprintCommandTest.port,
        commands.SprintCommandTest.asking, commands.SprintCommandTest.asked_rows)

    def test_ask_sends_an_action_only_on_an_owner_only_question(self):
        svc = self.open()
        sid = self.goal(svc)
        secret, _ = self.asking(svc, sid)
        action = {"command": "curl -sS -X POST http://127.0.0.1:27999/api/plan-approve",
                  "approve": Q0["options"][0]}
        common = ("--sprint", sid, "--secret-file", secret, "--port", self.port(svc))
        loose = self.store.parent / "action-loose.json"
        loose.write_text(json.dumps({"questions": [{**Q0, "action": action}]}))
        got = self.assert_unchanged(svc, lambda: run_sprint(
            "ask", *common, "--round-file", loose))
        self.assertEqual((got.returncode, got.stdout, got.stderr), (
            1, "", "sprint: refused 409: question 1 names an action, so it must be owner_only\n"))
        owned = self.store.parent / "action-owned.json"
        owned.write_text(json.dumps({"questions": [{**Q0, "owner_only": True, "action": action}]}))
        got = run_sprint("ask", *common, "--round-file", owned)
        self.assertEqual((got.returncode, got.stderr), (0, ""))
        (row,) = self.asked_rows()
        self.assertEqual(got.stdout, f"sprint: round {row[0]} sent, 1 question\n")


class ManagerActionContractTest(unittest.TestCase):
    def test_the_contract_says_an_owner_only_card_may_name_one_action_run_once(self):
        text = " ".join(CONTRACT.read_text(encoding="utf-8").split())
        (line,) = [part for part in text.split("- `") if part.startswith("action`")]
        for sentence in (
            "optional, `{\"command\": \"<the exact Bash command>\", \"approve\": \"<exact text of "
            "one option>\"}`, only on an `owner_only` question: it names the one command the "
            "owner's answer lets you run.",
            "A console route with its body is named by the exact command that sends it.",
            "When the owner picks the `approve` option with no words beside it, run that command, "
            "spelled exactly as sent, once, within 60 minutes of the answer.",
            "A second run, a run after that, any other spelling, an answer in words alone or with "
            "words beside the option, and a message are no approval.",
            "A merge, a rerun and a release never go on such a card: they keep their own rules.",
        ):
            with self.subTest(sentence):
                self.assertIn(sentence, line)
        self.assertIn("never does", text)


class PermitActionTest(unittest.TestCase):
    ENV, run_permit = commands.PermitCommandTest.ENV, commands.PermitCommandTest.run_permit
    hook = staticmethod(commands.PermitCommandTest.hook)

    def test_permit_is_silent_on_a_command_it_does_not_judge(self):
        for command in ("npm test", "git status", "gh pr view 7"):
            with self.subTest(command):
                code, out, sent = self.run_permit(self.hook(command), "{}")
                self.assertEqual((code, out), (0, ""))
                self.assertEqual([set(body) for _, _, _, body in sent], [
                    {"sprint_id", "phase", "session_id", "tool_use_id", "command_sha256", "nonce", "auth"}])
                self.assertNotIn("secret", json.dumps(sent))
                self.assertNotIn(command, json.dumps(sent))
