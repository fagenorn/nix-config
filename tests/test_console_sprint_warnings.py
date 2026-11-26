"""`sprint report`, `ask` and `notice` warn once per glossary word used without its gloss, and still send.

Run: just agent-workflow-tests
"""
import json
import unittest

from agent_tools.console import owner_words, sprint, sprints

from . import console_test_support as support
from . import test_console_sprint_command as commands
from .test_console_answer import view_of
from .test_console_questions import Q0, Q1
from .test_console_reports import REPORT
from .test_console_sprint_command import run_sprint
from .test_console_writes import Case
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "fast"

G = dict(owner_words.GLOSSARY)


def said(test, line, word):
    test.assertTrue(line.startswith("sprint: warning: "), line)
    test.assertIn(f'"{word}"', line)
    test.assertIn(G[word], line)


class SprintWarningTest(Case):
    open, goal, port, files, reports, sent, asking, asked_rows, notice, notice_rows = (
        commands.SprintCommandTest.open, commands.SprintCommandTest.goal,
        commands.SprintCommandTest.port, commands.SprintCommandTest.files,
        commands.SprintCommandTest.reports, commands.SprintCommandTest.sent,
        commands.SprintCommandTest.asking, commands.SprintCommandTest.asked_rows,
        commands.SprintCommandTest.notice, commands.SprintCommandTest.notice_rows)
    page, secret_file = commands.SprintCommandTest.page, commands.SprintCommandTest.secret_file

    def report(self, report):
        svc = self.open()
        sid = self.goal(svc)
        secret, path = self.reports(svc, sid, report)
        got = run_sprint("report", "--sprint", sid, "--secret-file", secret,
                         "--report-file", path, "--port", self.port(svc))
        return svc, sid, got

    def test_a_report_with_an_unglossed_word_is_accepted_and_warns_with_its_gloss(self):
        svc, sid, got = self.report({**REPORT, "status": "waiting on the land lock"})
        lines = got.stderr.splitlines()
        self.assertEqual((got.returncode, got.stdout, len(lines)), (0, "sprint: report sent\n", 1))
        said(self, lines[0], "land lock")
        self.assertEqual(support.log_rows(self.store)[-1][2], "sprint.reported")
        (stored,) = [s for e in view_of(svc)["entries"] for s in e["sprints"]
                     if s["sprint_id"] == sid]
        self.assertEqual(stored["status"], "waiting on the land lock")

    def test_a_report_with_no_glossary_word_prints_no_warning(self):
        _, _, got = self.report(REPORT)
        self.assertEqual((got.returncode, got.stdout, got.stderr), (0, "sprint: report sent\n", ""))

    def test_a_glossed_word_prints_no_warning(self):
        status = "waiting on the land lock (" + G["land lock"] + ")"
        self.assertLessEqual(len(status), sprints.MAX_LINE_CHARS)
        _, _, got = self.report({**REPORT, "status": status})
        self.assertEqual((got.returncode, got.stdout, got.stderr), (0, "sprint: report sent\n", ""))

    def test_a_refused_report_prints_no_warning(self):
        _, _, got = self.report({**REPORT, "status": "waiting on the land lock", "phase": "nope"})
        self.assertEqual((got.returncode, got.stdout), (1, ""))
        self.assertTrue(got.stderr.startswith("sprint: refused 4"), got.stderr)
        self.assertNotIn("warning", got.stderr)

    def test_ask_warns_once_per_word_across_ask_context_and_options(self):
        svc = self.open()
        sid = self.goal(svc)
        round_ = {"questions": [
            {**Q0, "question": "May I rerun the check?",
             "context": "The land lock is held by another sprint.",
             "options": ["Wait", "Rerun now", "Ask the CI"], "recommended": "Wait"},
            {**Q1, "question": "Should I rerun the reader?"}]}
        secret, path = self.asking(svc, sid, round_)
        got = run_sprint("ask", "--sprint", sid, "--secret-file", secret, "--round-file", path,
                         "--port", self.port(svc))
        self.assertEqual(got.returncode, 0)
        self.assertEqual(got.stdout, f"sprint: round {self.asked_rows()[-1][0]} sent, 2 questions\n")
        lines = got.stderr.splitlines()
        self.assertEqual(len(lines), 4)
        for i, word in enumerate(("land lock", "held", "rerun", "CI")):
            said(self, lines[i], word)

    def test_a_notice_with_an_unglossed_word_is_posted_and_warns(self):
        svc = self.open()
        sid = self.goal(svc)
        got = self.notice(svc, sid, {"kind": "heads-up", "text": "the guard refuses a push"})
        self.assertEqual((got.returncode, got.stdout),
                         (0, f"sprint: notice {self.notice_rows()[-1][0]} posted\n"))
        lines = got.stderr.splitlines()
        self.assertEqual(len(lines), 1)
        said(self, lines[0], "guard")

    def test_the_text_helpers_pick_only_the_checked_members(self):
        self.assertEqual(sprint.report_texts({**REPORT, "next": "rerun"}), [REPORT["status"]])
        self.assertEqual(sprint.round_texts({"questions": [
            {"question": "q", "context": "c", "options": ["a", 3], "blocks": "b"}, "x"]}),
            ["q", "c", "a"])
        self.assertEqual(sprint.notice_texts(
            {"kind": "claim", "text": "t", "what": "w", "until": "u"}), ["t"])
        self.assertEqual(sprint.report_texts({"status": 5}), [])


if __name__ == "__main__":
    unittest.main()
