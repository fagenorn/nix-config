"""`sprint report`, `ask` and `notice` warn once per listed word with its replacement, and still send.

Run: just agent-workflow-tests
"""
import json
import unittest

from agent_tools.console import sprint

from . import console_test_support as support
from . import test_console_sprint_command as commands
from .test_console_answer import view_of
from .test_console_questions import Q0, Q1
from .test_console_reports import REPORT
from .test_console_sprint_command import run_sprint
from .test_console_writes import Case
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "fast"

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

    def test_a_report_with_a_listed_word_is_accepted_and_warns_with_its_replacement(self):
        svc, sid, got = self.report({**REPORT, "status": "waiting on the land lock"})
        self.assertEqual((got.returncode, got.stdout, got.stderr), (0, "sprint: report sent\n",
                         'sprint: warning: rewrite "waiting on the land lock" without "land lock"; '
                         'write instead: its turn to merge\n'))
        self.assertEqual(support.log_rows(self.store)[-1][2], "sprint.reported")
        (stored,) = [s for e in view_of(svc)["entries"] for s in e["sprints"]
                     if s["sprint_id"] == sid]
        self.assertEqual(stored["status"], "waiting on the land lock")

    def test_an_explained_word_still_warns(self):
        status = "waiting on the land lock (its turn to merge)"
        _, _, got = self.report({**REPORT, "status": status})
        self.assertEqual((got.returncode, got.stdout, got.stderr), (0, "sprint: report sent\n",
                         f'sprint: warning: rewrite "{status}" without "land lock"; '
                         'write instead: its turn to merge\n'))

    def test_a_plain_report_using_ordinary_words_prints_nothing(self):
        _, _, got = self.report({**REPORT, "status": "the main page has a new look you can check"})
        self.assertEqual((got.returncode, got.stdout, got.stderr), (0, "sprint: report sent\n", ""))

    def test_a_refused_report_prints_no_warning(self):
        _, _, got = self.report({**REPORT, "status": "waiting on the land lock", "phase": "nope"})
        self.assertEqual((got.returncode, got.stdout), (1, ""))
        self.assertTrue(got.stderr.startswith("sprint: refused 4"), got.stderr)
        self.assertNotIn("warning", got.stderr)

    def test_the_next_step_of_a_report_warns_too(self):
        _, _, got = self.report({**REPORT, "next": "start the resume slice"})
        self.assertEqual((got.returncode, got.stdout, got.stderr), (0, "sprint: report sent\n",
                         'sprint: warning: rewrite "start the resume slice" without "slice"; '
                         'write instead: step\n'))

    def test_a_claim_warns_for_its_area_and_end_the_page_shows(self):
        svc = self.open()
        sid = self.goal(svc)
        got = self.notice(svc, sid, {"kind": "claim", "text": "Updating the settings page",
                                     "what": "the lint settings", "until": "CI passes", "issue": 7})
        self.assertEqual(got.returncode, 0)
        self.assertEqual(got.stderr.splitlines(), [
            'sprint: warning: rewrite "CI passes" without "CI"; write instead: the automatic checks',
            'sprint: warning: rewrite "the lint settings" without "lint"; write instead: the house-rule checks'])

    def test_ask_warns_once_per_word_across_ask_context_and_options(self):
        svc = self.open()
        sid = self.goal(svc)
        round_ = {"questions": [
            {**Q0, "question": "May I rerun the check?",
             "context": "It waits on the land lock. The PR is open.",
             "options": ["Wait", "Rerun now", "Ask the CI"], "recommended": "Wait"},
            {**Q1, "question": "Should I rerun the reader?"}]}
        secret, path = self.asking(svc, sid, round_)
        got = run_sprint("ask", "--sprint", sid, "--secret-file", secret, "--round-file", path,
                         "--port", self.port(svc))
        self.assertEqual(got.returncode, 0)
        self.assertEqual(got.stdout, f"sprint: round {self.asked_rows()[-1][0]} sent, 2 questions\n")
        self.assertEqual(got.stderr.splitlines(), [
            "sprint: warning: " + line for line in (
                'rewrite "It waits on the land lock." without "land lock"; write instead: its turn to merge',
                'rewrite "The PR is open." without "PR"; write instead: the proposed change',
                'rewrite "May I rerun the check?" without "rerun"; write instead: ran the failed check again',
                'rewrite "Ask the CI" without "CI"; write instead: the automatic checks')])

    def test_a_notice_with_a_listed_word_is_posted_and_warns(self):
        svc = self.open()
        sid = self.goal(svc)
        got = self.notice(svc, sid, {"kind": "heads-up", "text": "the guard refusal stopped the push"})
        self.assertEqual((got.returncode, got.stdout),
                         (0, f"sprint: notice {self.notice_rows()[-1][0]} posted\n"))
        self.assertEqual(got.stderr.splitlines(), [
            'sprint: warning: rewrite "the guard refusal stopped the push" without "guard refusal"; '
            'write instead: the safety check'])

    def test_the_text_helpers_pick_only_the_checked_members(self):
        self.assertEqual(sprint.report_texts({**REPORT, "next": "rerun", "phase": "slice"}),
                         [REPORT["status"], "rerun"])
        self.assertEqual(sprint.round_texts({"questions": [
            {"question": "q", "context": "c", "options": ["a", 3], "blocks": "b"}, "x"]}),
            ["q", "c", "a"])
        self.assertEqual(sprint.notice_texts(
            {"kind": "claim", "text": "t", "what": "w", "until": "u", "issue": 7}), ["t", "w", "u"])
        self.assertEqual(sprint.notice_texts({"kind": "hand-off", "text": "t", "to": "slice"}), ["t"])
        self.assertEqual(sprint.report_texts({"status": 5}), [])


if __name__ == "__main__":
    unittest.main()
