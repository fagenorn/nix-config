"""The `sprint` command: a manager sends a brief and reads its sprint's status (#887).

Run: just agent-workflow-tests
"""
import ast
import json
import os
import re
import socket
import subprocess
import sys
import tomllib
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from agent_tools.console import manager, sprint, sprints

from . import console_test_support as support
from .test_console_answer import view_of
from .test_console_briefs import APPROVE, JSON, PARTS, REPLY
from .test_console_questions import Q0, Q1, ROUND_ANSWER
from .test_console_reports import CHECKED, CLOSING, REPORT
from .test_console_writes import Case

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "python/agent_tools/console/manager-contract.md"


def run_sprint(*args, stdin=None, env=None):
    inherited = {k: v for k, v in os.environ.items()
                 if k not in (manager.ID_ENV, manager.SECRET_ENV)}
    return subprocess.run(
        [sys.executable, "-m", "agent_tools.console.sprint", *map(str, args)],
        env={**inherited, "PYTHONPATH": str(REPO_ROOT / "python"), **(env or {})},
        input=stdin, capture_output=True, text=True, timeout=30)


class SprintCommandTest(Case):
    def open(self):
        support.write_registry(self.registry, support.entries(2))
        return self.start()

    def goal(self, svc):
        return svc.state_goal("owner/p01", "make the importer resumable")

    def files(self, sid, parts):
        brief_path = self.store.parent / f"brief-{sid}.json"
        brief_path.write_text(json.dumps(parts))
        return self.store.parent / "sprint-secrets" / sid, brief_path

    def port(self, svc):
        return str(svc.address[1])

    def sent(self, svc, sid, parts=PARTS):
        secret, brief = self.files(sid, parts)
        got = run_sprint("brief", "--sprint", sid, "--secret-file", secret,
                         "--brief-file", brief, "--port", self.port(svc))
        self.assertEqual((got.returncode, got.stderr), (0, ""))
        return got

    def status(self, svc, sid):
        return run_sprint("status", "--sprint", sid, "--port", self.port(svc))

    def page(self, svc, path, body):
        return support.post_page(svc.address, path, self.own(svc, **JSON),
                                 json.dumps(body).encode())

    def test_a_brief_sent_with_the_secret_is_one_counted_inbox_item(self):
        svc = self.open()
        sid = self.goal(svc)
        got = self.sent(svc, sid)
        self.assertEqual(got.stdout, "sprint: brief version 1 sent\n")
        current = view_of(svc)
        self.assertEqual(current["statement"]["inbox_items"], 1)
        self.assertEqual(current["statement"]["headline"], "1 thing needs you")
        self.assertEqual([i["key"] for i in current["inbox"]["open"]], ["brief/" + sid])
        self.assertEqual(current["inbox"]["open"][0]["brief"], PARTS)

    def test_approving_answers_approved(self):
        svc = self.open()
        sid = self.goal(svc)
        self.sent(svc, sid)
        before = self.status(svc, sid)
        self.assertEqual(json.loads(before.stdout)["decision"], "none")
        got = self.page(svc, APPROVE, {"project_id": "owner/p01", "sprint_id": sid, "version": 1})
        self.assertEqual(got[0], 204)
        after = self.status(svc, sid)
        self.assertEqual(after.returncode, 0)
        self.assertEqual(json.loads(after.stdout), {
            "decision": "approved", "reply": None, "sprint_id": sid, "version": 1})
        self.assertEqual(len(after.stdout.splitlines()), 1)

    def test_a_reply_is_returned_in_the_owners_exact_words(self):
        svc = self.open()
        sid = self.goal(svc)
        self.sent(svc, sid)
        words = "Drop slice 2.\nKeep the rest. "
        got = self.page(svc, REPLY, {"project_id": "owner/p01", "sprint_id": sid,
                                     "version": 1, "reply": words})
        self.assertEqual(got[0], 204)
        after = self.status(svc, sid)
        self.assertEqual(after.returncode, 0)
        parsed = json.loads(after.stdout)
        self.assertEqual((parsed["decision"], parsed["reply"]), ("changes", words))

    def test_status_of_a_withdrawn_sprint(self):
        svc = self.open()
        sid = self.goal(svc)
        svc.withdraw_goal("owner/p01", sid)
        got = self.status(svc, sid)
        self.assertEqual(got.returncode, 0)
        self.assertEqual(json.loads(got.stdout)["decision"], "withdrawn")

    def test_refusals_exit_1_with_the_console_reason(self):
        svc = self.open()
        sid = self.goal(svc)
        real = (self.store.parent / "sprint-secrets" / sid).read_text().strip()
        wrong = self.store.parent / "wrong-secret"
        wrong.write_text("A" * 43 + "\n")
        secret, brief = self.files(sid, PARTS)
        _, no_risks = self.files(sid, {k: v for k, v in PARTS.items() if k != "risks"})
        port = self.port(svc)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            dead = str(probe.getsockname()[1])
        cases = [
            (("brief", "--sprint", sid, "--secret-file", wrong, "--brief-file", brief,
              "--port", port), "sprint: refused 403: secret refused\n"),
            (("brief", "--sprint", sid, "--secret-file", secret, "--brief-file", no_risks,
              "--port", port), "sprint: refused 409: the brief has no risks\n"),
            (("status", "--sprint", "e" * 16, "--port", port),
             "sprint: refused 404: this sprint is not known\n"),
        ]
        for args, text in cases:
            with self.subTest(args=args):
                got = self.assert_unchanged(svc, lambda: run_sprint(*args))
                self.assertEqual((got.returncode, got.stdout, got.stderr), (1, "", text))
                self.assertNotIn(real, got.stdout + got.stderr)
        got = self.assert_unchanged(svc, lambda: run_sprint(
            "brief", "--sprint", sid, "--secret-file", secret, "--brief-file", brief,
            "--port", dead))
        self.assertEqual((got.returncode, got.stdout), (1, ""))
        self.assertTrue(got.stderr.startswith("sprint: console unreachable on 127.0.0.1:"))
        self.assertNotIn(real, got.stderr)

    def test_bad_input_exits_2_and_sends_nothing(self):
        svc = self.open()
        sid = self.goal(svc)
        secret, brief = self.files(sid, PARTS)
        port = self.port(svc)
        junk = self.store.parent / "junk.json"
        junk.write_text("not json")
        array = self.store.parent / "array.json"
        array.write_text("[1]")
        missing = self.store.parent / "no-such-secret"
        cases = [
            (("brief", "--sprint", sid, "--secret-file", missing, "--brief-file", brief,
              "--port", port), "sprint: cannot read "),
            (("brief", "--sprint", sid, "--secret-file", secret, "--brief-file", junk,
              "--port", port), "sprint: cannot read "),
            (("brief", "--sprint", sid, "--secret-file", secret, "--brief-file", array,
              "--port", port), "sprint: cannot read "),
            (("status", "--sprint", "xyz", "--port", port), "usage:"),
        ]
        for args, start in cases:
            with self.subTest(args=args):
                got = self.assert_unchanged(svc, lambda: run_sprint(*args))
                self.assertEqual((got.returncode, got.stdout), (2, ""))
                self.assertTrue(got.stderr.startswith(start), got.stderr)

    def test_the_brief_may_come_from_stdin(self):
        svc = self.open()
        sid = self.goal(svc)
        secret = self.store.parent / "sprint-secrets" / sid
        got = run_sprint("brief", "--sprint", sid, "--secret-file", secret, "--brief-file", "-",
                         "--port", self.port(svc), stdin=json.dumps(PARTS))
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (0, "sprint: brief version 1 sent\n", ""))

    def test_the_sprint_and_secret_may_come_from_the_environment(self):
        svc = self.open()
        sid = self.goal(svc)
        secret, brief = self.files(sid, PARTS)
        text = secret.read_text()
        env = {manager.ID_ENV: sid, manager.SECRET_ENV: text}
        port = self.port(svc)
        got = run_sprint("brief", "--brief-file", brief, "--port", port, env=env)
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (0, "sprint: brief version 1 sent\n", ""))
        after = run_sprint("status", "--port", port, env=env)
        self.assertEqual(after.returncode, 0)
        parsed = json.loads(after.stdout)
        self.assertEqual((parsed["decision"], parsed["version"]), ("none", 1))
        for output in (got.stdout + got.stderr, after.stdout + after.stderr):
            self.assertNotIn(text.strip(), output)

    def test_a_missing_id_or_secret_exits_2_and_sends_nothing(self):
        svc = self.open()
        sid = self.goal(svc)
        secret, brief = self.files(sid, PARTS)
        text = secret.read_text()
        port = self.port(svc)
        no_id = "sprint: no sprint id: pass --sprint or set CONSOLE_SPRINT_ID\n"
        cases = [
            (("brief", "--brief-file", brief, "--port", port), {}, no_id),
            (("brief", "--brief-file", brief, "--port", port), {manager.ID_ENV: sid},
             "sprint: no secret: pass --secret-file or set CONSOLE_SPRINT_SECRET\n"),
            (("brief", "--brief-file", brief, "--port", port),
             {manager.ID_ENV: "XYZ", manager.SECRET_ENV: text},
             "sprint: CONSOLE_SPRINT_ID is not a sprint id (16 lowercase hex characters)\n"),
            (("status", "--port", port), {}, no_id),
        ]
        for args, env, line in cases:
            with self.subTest(args=args, env=sorted(env)):
                got = self.assert_unchanged(svc, lambda: run_sprint(*args, env=env))
                self.assertEqual((got.returncode, got.stdout, got.stderr), (2, "", line))
                self.assertNotIn(text.strip(), got.stderr)

    def test_flags_win_over_the_environment(self):
        svc = self.open()
        sid = self.goal(svc)
        secret, brief = self.files(sid, PARTS)
        env = {manager.ID_ENV: "b" * 16, manager.SECRET_ENV: "not the secret"}
        got = run_sprint("brief", "--sprint", sid, "--secret-file", secret,
                         "--brief-file", brief, "--port", self.port(svc), env=env)
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (0, "sprint: brief version 1 sent\n", ""))
        after = run_sprint("status", "--sprint", sid, "--port", self.port(svc), env=env)
        self.assertEqual(json.loads(after.stdout)["sprint_id"], sid)

    def messaged(self, svc, sid, text="leave the importer's schema alone"):
        """The id of one owner message, and the sprint's secret file."""
        secret, _ = self.files(sid, PARTS)
        return svc.send_message("owner/p01", sid, text), secret

    def test_inbox_prints_the_unread_messages_once(self):
        svc = self.open()
        sid = self.goal(svc)
        message, secret = self.messaged(svc, sid)
        args = ("inbox", "--sprint", sid, "--secret-file", secret, "--port", self.port(svc))
        first = run_sprint(*args)
        self.assertEqual((first.returncode, first.stderr), (0, ""))
        parsed = json.loads(first.stdout)
        self.assertIsInstance(parsed["messages"][0].pop("at"), str)
        self.assertEqual(parsed, {"messages": [{
            "id": message, "kind": "text", "text": "leave the importer's schema alone",
            "version": None}]})
        self.assertEqual(len(first.stdout.splitlines()), 1)
        second = run_sprint(*args)
        self.assertEqual((second.returncode, second.stderr), (0, ""))
        self.assertEqual(json.loads(second.stdout), {"messages": []})

    def test_inbox_prints_an_approval_a_change_request_and_a_text_each_once_in_order(self):
        svc = self.open()
        sid = self.goal(svc)
        secret, _ = self.files(sid, PARTS)
        token = secret.read_text().strip()
        first = svc.send_message("owner/p01", sid, "start with the reader")
        svc.send_brief(sid, token, PARTS)
        svc.reply_brief("owner/p01", sid, 1, "smaller slices")
        svc.send_brief(sid, token, PARTS)
        svc.approve_brief("owner/p01", sid, 2)
        last = svc.send_message("owner/p01", sid, "and keep the tests")
        args = ("inbox", "--sprint", sid, "--secret-file", secret, "--port", self.port(svc))
        got = run_sprint(*args)
        self.assertEqual((got.returncode, got.stderr), (0, ""))
        messages = json.loads(got.stdout)["messages"]
        ids = [row[0] for row in support.log_rows(self.store)
               if row[2] in ("sprint.messaged", "brief.replied", "brief.approved")]
        self.assertEqual([m["id"] for m in messages], ids)
        self.assertEqual((ids[0], ids[-1]), (first, last))
        self.assertEqual(
            [(m["kind"], m["version"], m["text"]) for m in messages],
            [("text", None, "start with the reader"), ("changes", 1, "smaller slices"),
             ("approved", 2, None), ("text", None, "and keep the tests")])
        again = run_sprint(*args)
        self.assertEqual((again.returncode, json.loads(again.stdout)), (0, {"messages": []}))

    def test_reply_records_under_its_message_and_without_the_secret_nothing(self):
        svc = self.open()
        sid = self.goal(svc)
        message, secret = self.messaged(svc, sid)
        port = self.port(svc)
        got = run_sprint("reply", "--sprint", sid, "--secret-file", secret,
                         "--message", str(message), "--reply-file", "-", "--port", port,
                         stdin="kept the schema; moved the change to the reader\n")
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (0, f"sprint: reply to message {message} sent\n", ""))
        folded = svc._sprints[sid].messages[0]
        self.assertEqual(folded.reply, "kept the schema; moved the change to the reader")
        wrong = self.store.parent / "wrong-secret"
        wrong.write_text("A" * 43 + "\n")
        before = len(support.log_rows(self.store))
        refused = self.assert_unchanged(svc, lambda: run_sprint(
            "reply", "--sprint", sid, "--secret-file", wrong, "--message", str(message),
            "--reply-file", "-", "--port", port, stdin="x"))
        self.assertEqual((refused.returncode, refused.stdout, refused.stderr),
                         (1, "", "sprint: refused 403: secret refused\n"))
        self.assertEqual(len(support.log_rows(self.store)), before)
        none = self.assert_unchanged(svc, lambda: run_sprint(
            "reply", "--sprint", sid, "--message", str(message), "--reply-file", "-",
            "--port", port, stdin="x"))
        self.assertEqual((none.returncode, none.stdout), (2, ""))
        self.assertIn("sprint: no secret", none.stderr)

    def test_inbox_and_reply_take_the_identity_from_the_environment(self):
        svc = self.open()
        sid = self.goal(svc)
        message, secret = self.messaged(svc, sid)
        env = {manager.ID_ENV: sid, manager.SECRET_ENV: secret.read_text()}
        port = self.port(svc)
        got = run_sprint("inbox", "--port", port, env=env)
        self.assertEqual((got.returncode, got.stderr), (0, ""))
        self.assertEqual([m["id"] for m in json.loads(got.stdout)["messages"]], [message])
        got = run_sprint("reply", "--message", str(message), "--reply-file", "-",
                         "--port", port, env=env, stdin="done")
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (0, f"sprint: reply to message {message} sent\n", ""))

    def test_reply_refuses_a_bad_message_id_and_an_unreadable_file(self):
        svc = self.open()
        sid = self.goal(svc)
        message, secret = self.messaged(svc, sid)
        port = self.port(svc)
        common = ("--sprint", sid, "--secret-file", secret, "--port", port)
        cases = [
            (("reply", *common, "--message", "0", "--reply-file", "-"), "usage:"),
            (("reply", *common, "--message", "x", "--reply-file", "-"), "usage:"),
            (("reply", *common, "--message", str(message), "--reply-file", "/nonexistent"),
             "sprint: cannot read /nonexistent: "),
        ]
        for args, start in cases:
            with self.subTest(args=args):
                got = self.assert_unchanged(svc, lambda: run_sprint(*args, stdin="x"))
                self.assertEqual((got.returncode, got.stdout), (2, ""))
                self.assertTrue(got.stderr.startswith(start), got.stderr)

    def reports(self, svc, sid, report):
        """An approved sprint, its secret file and a report file holding `report`."""
        secret, _ = self.files(sid, PARTS)
        svc.send_brief(sid, secret.read_text().strip(), PARTS)
        svc.approve_brief("owner/p01", sid, 1)
        path = self.store.parent / f"report-{sid}.json"
        path.write_text(json.dumps(report))
        return secret, path

    def test_a_report_sent_with_the_secret_is_stored(self):
        svc = self.open()
        sid = self.goal(svc)
        secret, path = self.reports(svc, sid, REPORT)
        port = self.port(svc)
        got = run_sprint("report", "--sprint", sid, "--secret-file", secret,
                         "--report-file", path, "--port", port)
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (0, "sprint: report sent\n", ""))
        self.assertEqual(support.log_rows(self.store)[-1][2], "sprint.reported")
        before = len(support.log_rows(self.store))
        got = run_sprint("report", "--sprint", sid, "--secret-file", secret,
                         "--report-file", "-", "--port", port, stdin=json.dumps(REPORT))
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (0, "sprint: report sent\n", ""))
        rows = support.log_rows(self.store)
        self.assertEqual((len(rows), rows[-1][2]), (before + 1, "sprint.reported"))

    def test_a_refused_report_exits_1_with_the_console_reason(self):
        svc = self.open()
        sid = self.goal(svc)
        secret, path = self.reports(svc, sid, REPORT)
        wrong = self.store.parent / "wrong-secret"
        wrong.write_text("A" * 43 + "\n")
        no_next = self.store.parent / "no-next.json"
        no_next.write_text(json.dumps({k: v for k, v in REPORT.items() if k != "next"}))
        port = self.port(svc)
        cases = [
            (wrong, path, "sprint: refused 403: secret refused\n"),
            (secret, no_next, "sprint: refused 409: the report has no valid next\n"),
        ]
        for secret_file, report_file, text in cases:
            with self.subTest(text=text):
                got = self.assert_unchanged(svc, lambda: run_sprint(
                    "report", "--sprint", sid, "--secret-file", secret_file,
                    "--report-file", report_file, "--port", port))
                self.assertEqual((got.returncode, got.stdout, got.stderr), (1, "", text))
        array = self.store.parent / "array.json"
        array.write_text("[]")
        got = self.assert_unchanged(svc, lambda: run_sprint(
            "report", "--sprint", sid, "--secret-file", secret, "--report-file", array,
            "--port", port))
        self.assertEqual((got.returncode, got.stdout), (2, ""))
        self.assertTrue(got.stderr.startswith("sprint: cannot read "), got.stderr)
        self.assertTrue(got.stderr.endswith("the report is not a JSON object\n"), got.stderr)

    def asking(self, svc, sid, round_=None):
        """An approved sprint, its secret file and a round file holding `round_`."""
        self.sent(svc, sid)
        got = self.page(svc, APPROVE, {"project_id": "owner/p01", "sprint_id": sid, "version": 1})
        self.assertEqual(got[0], 204)
        path = self.store.parent / f"round-{sid}.json"
        path.write_text(json.dumps(round_ if round_ is not None else {"questions": [Q0, Q1]}))
        return self.store.parent / "sprint-secrets" / sid, path

    def asked_rows(self):
        return [row for row in support.log_rows(self.store) if row[2] == "questions.asked"]

    def test_ask_sends_a_round_that_becomes_one_open_item_per_question(self):
        svc = self.open()
        sid = self.goal(svc)
        secret, path = self.asking(svc, sid)
        got = run_sprint("ask", "--sprint", sid, "--secret-file", secret, "--round-file", path,
                         "--port", self.port(svc))
        self.assertEqual((got.returncode, got.stderr), (0, ""))
        (row,) = self.asked_rows()
        self.assertEqual(got.stdout, f"sprint: round {row[0]} sent, 2 questions\n")
        opened = view_of(svc)["inbox"]["open"]
        self.assertEqual([i["reason"] for i in opened], ["question", "question"])
        self.assertEqual([i["questions"][0]["recommended"] for i in opened], ["files", "no"])

    def test_ask_refusals_exit_1_with_the_console_reason(self):
        svc = self.open()
        sid = self.goal(svc)
        secret, path = self.asking(svc, sid, {"questions": [{**Q0, "options": ["sqlite"]}]})
        port = self.port(svc)
        common = ("--sprint", sid, "--secret-file", secret, "--port", port)
        got = self.assert_unchanged(svc, lambda: run_sprint(
            "ask", *common, "--round-file", path))
        self.assertEqual((got.returncode, got.stdout, got.stderr), (
            1, "", "sprint: refused 409: question 1 needs two to four options\n"))
        plain = self.store.parent / "plain.json"
        plain.write_text(json.dumps({"questions": [Q0]}))
        blocker = self.store.parent / "blocker.json"
        blocker.write_text(json.dumps({"questions": [Q0], "blocker": True}))
        first = run_sprint("ask", *common, "--round-file", plain)
        self.assertEqual((first.returncode, first.stderr), (0, ""))
        got = self.assert_unchanged(svc, lambda: run_sprint(
            "ask", *common, "--round-file", plain))
        self.assertEqual((got.returncode, got.stdout, got.stderr), (
            1, "", "sprint: refused 409: a round of questions is already open\n"))
        second = run_sprint("ask", *common, "--round-file", blocker)
        self.assertEqual((second.returncode, second.stderr), (0, ""))
        wrong = self.store.parent / "wrong-secret"
        wrong.write_text("A" * 43 + "\n")
        got = self.assert_unchanged(svc, lambda: run_sprint(
            "ask", "--sprint", sid, "--secret-file", wrong, "--round-file", plain,
            "--port", port))
        self.assertEqual((got.returncode, got.stdout, got.stderr), (
            1, "", "sprint: refused 403: secret refused\n"))
        self.assertNotIn(secret.read_text().strip(), got.stdout + got.stderr)

    def test_ask_bad_input_exits_2_and_sends_nothing(self):
        svc = self.open()
        sid = self.goal(svc)
        secret, _ = self.asking(svc, sid)
        array = self.store.parent / "array.json"
        array.write_text("[1]")
        missing = self.store.parent / "no-such-round.json"
        for name in (array, missing):
            with self.subTest(round=name.name):
                got = self.assert_unchanged(svc, lambda: run_sprint(
                    "ask", "--sprint", sid, "--secret-file", secret, "--round-file", name,
                    "--port", self.port(svc)))
                self.assertEqual((got.returncode, got.stdout), (2, ""))
                self.assertTrue(got.stderr.startswith("sprint: cannot read"), got.stderr)
        self.assertEqual(self.asked_rows(), [])

    def test_ask_reads_the_round_from_stdin_and_the_identity_from_the_environment(self):
        svc = self.open()
        sid = self.goal(svc)
        secret, _ = self.asking(svc, sid)
        env = {manager.ID_ENV: sid, manager.SECRET_ENV: secret.read_text()}
        got = run_sprint("ask", "--round-file", "-", "--port", self.port(svc), env=env,
                         stdin=json.dumps({"questions": [Q0]}))
        self.assertEqual((got.returncode, got.stderr), (0, ""))
        (row,) = self.asked_rows()
        self.assertEqual(got.stdout, f"sprint: round {row[0]} sent, 1 question\n")

    def test_inbox_prints_an_answer_with_its_question(self):
        svc = self.open()
        sid = self.goal(svc)
        secret, path = self.asking(svc, sid)
        port = self.port(svc)
        self.assertEqual(run_sprint("ask", "--sprint", sid, "--secret-file", secret,
                                    "--round-file", path, "--port", port).returncode, 0)
        (row,) = self.asked_rows()
        got = self.page(svc, ROUND_ANSWER, {"project_id": "owner/p01", "sprint_id": sid,
                                            "round": row[0], "question": 0, "choice": 0})
        self.assertEqual(got[0], 204)
        got = run_sprint("inbox", "--sprint", sid, "--secret-file", secret, "--port", port)
        self.assertEqual((got.returncode, got.stderr), (0, ""))
        self.assertEqual(len(got.stdout.splitlines()), 1)
        last = json.loads(got.stdout)["messages"][-1]
        self.assertIsInstance(last.pop("at"), str)
        self.assertIsInstance(last.pop("id"), int)
        self.assertEqual(last, {
            "chosen": "sqlite", "kind": "answer", "question": "Which store keeps the checkpoints?",
            "round": row[0], "text": "sqlite", "version": None})

    def test_close_sends_the_closing_report_and_a_refusal_exits_1(self):
        svc = self.open()
        sid = self.goal(svc)
        secret, path = self.reports(svc, sid, {**REPORT, "issues": [
            {"issue": 12, "stage": "building"}]})
        port = self.port(svc)
        self.assertEqual(run_sprint("report", "--sprint", sid, "--secret-file", secret,
                                    "--report-file", path, "--port", port).returncode, 0)
        closing = {**CLOSING, "issues": [{"issue": 12, "stage": "landed"}]}
        before = len(support.log_rows(self.store))
        got = run_sprint("close", "--sprint", sid, "--secret-file", secret,
                         "--closing-file", "-", "--port", port, stdin=json.dumps(closing))
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (0, "sprint: closing report sent\n", ""))
        rows = support.log_rows(self.store)
        self.assertEqual((len(rows), rows[-1][2]), (before + 1, "sprint.closed"))
        got = self.assert_unchanged(svc, lambda: run_sprint(
            "close", "--sprint", sid, "--secret-file", secret, "--closing-file", "-",
            "--port", port, stdin=json.dumps(closing)))
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (1, "", "sprint: refused 409: this sprint has ended\n"))
        got = self.assert_unchanged(svc, lambda: run_sprint(
            "close", "--sprint", sid, "--secret-file", secret, "--closing-file", "-",
            "--port", port, stdin="[]"))
        self.assertEqual((got.returncode, got.stdout), (2, ""))
        self.assertTrue(got.stderr.startswith("sprint: cannot read -:"), got.stderr)

    def printed_examples(self):
        """The example report and the example closing report, as the contract prints them."""
        text = run_sprint("contract").stdout
        reporting = text.partition("## Reporting")[2].partition("\n## ")[0]
        ending = text.partition("## Ending")[2]
        pattern = r"```json\n(.*?)\n\s*```"
        return (re.search(pattern, reporting, re.S).group(1),
                re.search(pattern, ending, re.S).group(1), re.findall(pattern, text, re.S))

    def test_the_printed_examples_are_accepted_as_printed(self):
        report, closing, blocks = self.printed_examples()
        self.assertEqual(len(blocks), 2)
        svc = self.open()
        sid = self.goal(svc)
        secret, _ = self.reports(svc, sid, REPORT)
        port = self.port(svc)
        got = run_sprint("report", "--sprint", sid, "--secret-file", secret,
                         "--report-file", "-", "--port", port, stdin=report)
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (0, "sprint: report sent\n", ""))
        got = run_sprint("close", "--sprint", sid, "--secret-file", secret,
                         "--closing-file", "-", "--port", port, stdin=closing)
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (0, "sprint: closing report sent\n", ""))

    SECTION = "## After a restart or a takeover\n\n1. When the console tells you that it restarted this session, or your first prompt says you take over a sprint whose manager is gone, run `sprint recap`, then `sprint inbox`, and act on what `sprint inbox` prints first.\n2. `sprint recap` prints the goal, the latest brief with its decision and the owner's reply, the last report and how many of the owner's messages are unread. The console keeps this record; nothing was handed over to you.\n3. The latest brief's decision comes before the last report, because a newer brief does not remove an older report:\n   - No brief: draft one, as Drafting the brief says.\n   - Decision `changes`: revise the brief from the reply `sprint recap` printed and send the new version, even when `sprint inbox` printed nothing, because that change request was read before the restart.\n   - Decision `none`: the brief waits for the owner; end your turn.\n   - Decision `approved`: the last report may describe an earlier version of the brief, so check its next step against the approved brief's parts before following it. Continue only the work the approved brief still includes and drop what it removed; follow After approval when there is no report or nothing is left.\n"

    def test_the_contract_says_a_permission_prompt_is_refused_and_a_worktree_is_never_entered(self):
        section = run_sprint("contract").stdout.split("\n## ", 2)[1]
        self.assertTrue(section.startswith("Contract\n"), section)
        self.assertIn("- A permission prompt in this session is refused automatically, so never "
                      "wait for one.", section)
        self.assertIn("- Never enter or create a worktree yourself, because a delivery makes its "
                      "own.", section)

    def test_the_contract_says_what_follows_a_restart_or_a_takeover(self):
        text = CONTRACT.read_text(encoding="utf-8")
        _, found, rest = text.partition("## After a restart or a takeover")
        self.assertTrue(found)
        section = (found + rest).split("\n## ", 1)[0]
        self.assertEqual(section.rstrip("\n") + "\n", self.SECTION)
        self.assertLess(section.index("`sprint recap`"), section.index("`sprint inbox`"))
        self.assertLess(section.index("Decision `changes`"), section.index("Decision `approved`"))


class RecapTest(Case):
    RECAP = "/api/recap"

    def open(self):
        support.write_registry(self.registry, support.entries(2))
        return self.start()

    def secret(self, sid):
        return (self.store.parent / "sprint-secrets" / sid).read_text().removesuffix("\n")

    def post(self, svc, body, headers=JSON):
        return support.post_page(svc.address, self.RECAP,
                                 headers, json.dumps(body).encode() if isinstance(body, dict) else body)

    def asked(self, svc, sid, secret, **headers):
        return self.post(svc, {"sprint_id": sid, "secret": secret}, {**JSON, **headers})

    def goal(self, svc):
        return svc.state_goal("owner/p01", "make the importer resumable")

    def test_recap_answers_the_goal_brief_decision_last_report_and_unread_count(self):
        svc = self.open()
        sid = self.goal(svc)
        secret = self.secret(sid)
        svc.send_brief(sid, secret, PARTS)
        svc.approve_brief("owner/p01", sid, 1)
        at = svc.send_report(sid, secret, REPORT)
        svc.send_message("owner/p01", sid, "hello")
        self.assertEqual(svc.recap(sid, secret), {
            "sprint_id": sid, "goal": "make the importer resumable",
            "brief": {"version": 1, "decision": "approved", "reply": None, "parts": PARTS},
            "report": {"at": at, "status": REPORT["status"], "phase": REPORT["phase"],
                       "milestone": REPORT["milestone"], "tracker_url": REPORT["tracker_url"],
                       "issues": CHECKED["issues"], "inbox": REPORT["inbox"],
                       "next": REPORT["next"]},
            "unread": 2})

    def test_recap_of_a_sprint_without_brief_or_report_is_nulls_and_zero(self):
        svc = self.open()
        sid = self.goal(svc)
        self.assertEqual(svc.recap(sid, self.secret(sid)), {
            "sprint_id": sid, "goal": "make the importer resumable", "brief": None,
            "report": None, "unread": 0})

    def test_recap_of_a_changed_newer_brief_shows_the_reply_beside_the_old_report(self):
        svc = self.open()
        sid = self.goal(svc)
        secret = self.secret(sid)
        svc.send_brief(sid, secret, PARTS)
        svc.approve_brief("owner/p01", sid, 1)
        at = svc.send_report(sid, secret, REPORT)
        svc.send_brief(sid, secret, PARTS)
        svc.reply_brief("owner/p01", sid, 2, "split the importer")
        svc.read_inbox(sid, secret)
        got = svc.recap(sid, secret)
        self.assertEqual(got["brief"], {"version": 2, "decision": "changes",
                                        "reply": "split the importer", "parts": PARTS})
        self.assertEqual(got["report"]["at"], at)
        self.assertEqual(got["unread"], 0)

    def test_recap_reads_nothing_as_read_and_appends_nothing(self):
        svc = self.open()
        sid = self.goal(svc)
        secret = self.secret(sid)
        svc.send_brief(sid, secret, PARTS)
        svc.approve_brief("owner/p01", sid, 1)
        svc.send_message("owner/p01", sid, "hello")
        self.assert_unchanged(svc, lambda: svc.recap(sid, secret))
        self.assertEqual([m["kind"] for m in svc.read_inbox(sid, secret)],
                         ["approved", "text"])

    def test_recap_is_refused_without_the_secret(self):
        svc = self.open()
        sid = self.goal(svc)
        with self.assertRaises(sprints.SecretRefused):
            svc.recap(sid, "wrong")
        got = self.assert_unchanged(svc, lambda: self.asked(svc, sid, "wrong"))
        self.assertEqual((got[0], got[2]), (403, b"secret refused\n"))
        wrong = self.store.parent / "wrong-secret"
        wrong.write_text("wrong")
        got = self.assert_unchanged(svc, lambda: run_sprint(
            "recap", "--sprint", sid, "--secret-file", wrong, "--port", svc.address[1]))
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (1, "", "sprint: refused 403: secret refused\n"))

    def test_recap_of_a_withdrawn_sprint_is_refused_409(self):
        svc = self.open()
        sid = self.goal(svc)
        secret = self.secret(sid)
        svc.withdraw_goal("owner/p01", sid)
        got = self.assert_unchanged(svc, lambda: self.asked(svc, sid, secret))
        self.assertEqual((got[0], got[2]), (409, b"this sprint is not open\n"))

    def test_the_recap_route_refuses_an_origin_and_a_bad_body(self):
        svc = self.open()
        sid = self.goal(svc)
        secret = self.secret(sid)
        origin = {"Origin": f"http://127.0.0.1:{svc.address[1]}"}
        got = self.assert_unchanged(svc, lambda: self.asked(svc, sid, secret, **origin))
        self.assertEqual((got[0], got[2]), (403, b"origin refused\n"))
        got = self.assert_unchanged(svc, lambda: self.post(svc, {"sprint_id": sid}))
        self.assertEqual((got[0], got[2]), (400, b"bad recap\n"))

    def test_sprint_recap_prints_the_consoles_answer(self):
        svc = self.open()
        sid = self.goal(svc)
        secret = self.secret(sid)
        svc.send_brief(sid, secret, PARTS)
        got = run_sprint("recap", "--port", svc.address[1], env={
            manager.ID_ENV: sid, manager.SECRET_ENV: secret})
        self.assertEqual((got.returncode, got.stderr), (0, ""))
        self.assertEqual(len(got.stdout.splitlines()), 1)
        self.assertEqual(json.loads(got.stdout), svc.recap(sid, secret))

    def test_sprint_recap_without_a_secret_exits_2_and_sends_nothing(self):
        svc = self.open()
        sid = self.goal(svc)
        got = self.assert_unchanged(svc, lambda: run_sprint(
            "recap", "--sprint", sid, "--port", svc.address[1]))
        self.assertEqual((got.returncode, got.stdout, got.stderr), (2, "", (
            "sprint: no secret: pass --secret-file or set CONSOLE_SPRINT_SECRET\n")))


class ManagerContractTest(unittest.TestCase):
    def test_contract_prints_the_packaged_document_and_exits_0(self):
        got = run_sprint("contract")
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (0, CONTRACT.read_text(encoding="utf-8"), ""))

    def test_contract_sends_no_request(self):
        out = StringIO()
        refused = AssertionError("sprint contract opened a connection")
        with mock.patch.object(sprint.http.client, "HTTPConnection", side_effect=refused), \
                mock.patch.dict(os.environ, clear=False) as environ, redirect_stdout(out):
            environ.pop(manager.ID_ENV, None)
            environ.pop(manager.SECRET_ENV, None)
            code = sprint.main(["contract"])
        self.assertEqual((code, out.getvalue()), (0, CONTRACT.read_text(encoding="utf-8")))

    def test_contract_takes_no_sprint_secret_or_port(self):
        for args in (("--sprint", "a" * 16), ("--secret-file", "x"), ("--port", "1")):
            with self.subTest(args=args):
                got = run_sprint("contract", *args)
                self.assertEqual((got.returncode, got.stdout), (2, ""))
                self.assertIn("unrecognized arguments", got.stderr)

    def test_the_package_ships_the_contract(self):
        config = tomllib.loads((REPO_ROOT / "python/pyproject.toml").read_text(encoding="utf-8"))
        shipped = config["tool"]["setuptools"]["package-data"]["agent_tools.console"]
        self.assertIn(CONTRACT.name, shipped)

    def test_the_contract_shows_its_send_command_and_never_handles_the_secret(self):
        text = CONTRACT.read_text(encoding="utf-8")
        self.assertIn("`sprint brief --brief-file -`", text)
        self.assertIn("`sprint contract`", text)
        for forbidden in ("--secret-file", "CONSOLE_SPRINT_SECRET", "bindings."):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)

    def test_the_contract_brings_real_choices_in_one_round(self):
        text = CONTRACT.read_text(encoding="utf-8")
        questions = text.partition("## Questions")[2].partition("\n## ")[0]
        self.assertTrue(questions)
        for needle in ("`sprint ask --round-file -`", "reversible", "may I proceed", "one round",
                       "two to four", "`blocks`", "`recommended`", '`"blocker": true`',
                       "a round of questions is already open", "kind `answer`"):
            with self.subTest(needle=needle):
                self.assertIn(needle, questions)
        self.assertIn("`answer`", text.partition("## Every turn")[2].partition("\n## ")[0])

    def test_the_contract_says_what_follows_an_approval(self):
        text = CONTRACT.read_text(encoding="utf-8")
        for needle in ("`sprint inbox`", "Start every turn",
                       "`sprint reply --message <id> --reply-file -`", "`sprint contract`",
                       "one tracker milestone", "`to-issues`", "`deliver-batch`",
                       "`sprint report --report-file -`", "new brief", "approved"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        self.assertNotIn("is not part of the contract yet", text)
        after = text.partition("## After approval")[2]
        self.assertTrue(after)
        for needle in ("cut no issues", "`sprint status`", "`withdrawn`",
                       "this sprint is not open", "secret refused", "no tracker action"):
            with self.subTest(section=needle):
                self.assertIn(needle, after)


    def test_the_contract_says_how_a_sprint_ends(self):
        text = CONTRACT.read_text(encoding="utf-8")
        after = text.partition("## Ending")[2]
        self.assertTrue(after)
        for needle in ("`sprint close --closing-file -`", '"summary"', '"differently"',
                       '"landed"', '"held"', '"dropped"', "mid-merge", "start nothing new",
                       "`stop`", "an issue of this sprint is neither landed nor dropped",
                       "no tracker action", "what you would do differently"):
            with self.subTest(needle=needle):
                self.assertIn(needle, after)
        self.assertNotIn("what went differently", after)

    def test_the_contract_and_the_help_name_every_member_the_console_requires(self):
        text = run_sprint("contract").stdout
        reporting = text.partition("## Reporting")[2].partition("\n## ")[0]
        ending = text.partition("## Ending")[2]
        for command, section, members in (
                ("report", reporting, sprints.REPORT_MEMBERS),
                ("close", ending, sprints.CLOSING_MEMBERS)):
            helped = run_sprint(command, "--help").stdout
            for member in members:
                for where, shown in (("contract", section), ("help", helped)):
                    with self.subTest(command=command, member=member, where=where):
                        self.assertIn(f"`{member}`" if where == "contract" else f"{member}:",
                                      shown)
        limit = f"{sprints.MAX_LINE_CHARS} characters"
        for where, shown in (("contract", ending), ("help", run_sprint("close", "--help").stdout)):
            with self.subTest(where=where, limit=limit):
                self.assertIn(f"first line is at most {limit}", " ".join(shown.split()))
        for phase in sprints.REPORT_PHASES:
            self.assertIn(f"`{phase}`", reporting)
            self.assertIn(phase, run_sprint("report", "--help").stdout)
        for stage in sprints.REPORT_STAGES:
            self.assertIn(stage, run_sprint("report", "--help").stdout)


class CommandContractTest(unittest.TestCase):
    def test_the_command_table_names_the_module_and_its_docstring_states_the_contract(self):
        table = (REPO_ROOT / "lib/agent-tools.nix").read_text()
        self.assertIsNotNone(re.search(r'^\s*"sprint" = "console\.sprint";$', table, re.M))
        source = (REPO_ROOT / "python/agent_tools/console/sprint.py").read_text()
        docstring = ast.get_docstring(ast.parse(source))
        for name in ("sprint brief", "sprint status", "--sprint", "--secret-file",
                     "--brief-file", "--port", "POST /api/brief", "GET /api/sprint-status",
                     "exit 0", "exit 1", "exit 2", "printed nowhere", "sprint report", "--report-file",
                     "POST /api/report", "sprint contract", "sprint ask", "--round-file",
                     "POST /api/ask", "chosen", "round or reply file"):
            self.assertIn(name, docstring)
        self.assertEqual(sprint.build_parser().prog, "sprint")


if __name__ == "__main__":
    unittest.main()
