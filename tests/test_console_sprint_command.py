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
import unittest
from pathlib import Path

from agent_tools.console import sprint

from . import console_test_support as support
from .test_console_answer import view_of
from .test_console_briefs import APPROVE, JSON, PARTS, REPLY
from .test_console_writes import Case

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_sprint(*args, stdin=None):
    return subprocess.run(
        [sys.executable, "-m", "agent_tools.console.sprint", *map(str, args)],
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "python")},
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


class CommandContractTest(unittest.TestCase):
    def test_the_command_table_names_the_module_and_its_docstring_states_the_contract(self):
        table = (REPO_ROOT / "lib/agent-tools.nix").read_text()
        self.assertIsNotNone(re.search(r'^\s*"sprint" = "console\.sprint";$', table, re.M))
        source = (REPO_ROOT / "python/agent_tools/console/sprint.py").read_text()
        docstring = ast.get_docstring(ast.parse(source))
        for name in ("sprint brief", "sprint status", "--sprint", "--secret-file",
                     "--brief-file", "--port", "POST /api/brief", "GET /api/sprint-status",
                     "exit 0", "exit 1", "exit 2", "printed nowhere"):
            self.assertIn(name, docstring)
        self.assertEqual(sprint.build_parser().prog, "sprint")


if __name__ == "__main__":
    unittest.main()
