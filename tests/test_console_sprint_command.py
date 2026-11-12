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

from agent_tools.console import manager, sprint

from . import console_test_support as support
from .test_console_answer import view_of
from .test_console_briefs import APPROVE, JSON, PARTS, REPLY
from .test_console_reports import REPORT
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


class CommandContractTest(unittest.TestCase):
    def test_the_command_table_names_the_module_and_its_docstring_states_the_contract(self):
        table = (REPO_ROOT / "lib/agent-tools.nix").read_text()
        self.assertIsNotNone(re.search(r'^\s*"sprint" = "console\.sprint";$', table, re.M))
        source = (REPO_ROOT / "python/agent_tools/console/sprint.py").read_text()
        docstring = ast.get_docstring(ast.parse(source))
        for name in ("sprint brief", "sprint status", "--sprint", "--secret-file",
                     "--brief-file", "--port", "POST /api/brief", "GET /api/sprint-status",
                     "exit 0", "exit 1", "exit 2", "printed nowhere", "sprint report", "--report-file",
                     "POST /api/report", "sprint contract"):
            self.assertIn(name, docstring)
        self.assertEqual(sprint.build_parser().prog, "sprint")


if __name__ == "__main__":
    unittest.main()
