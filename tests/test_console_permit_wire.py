"""The wire between `sprint permit` and the service route (#1377, moved out of the manager service tests, #1620).

Run: just agent-workflow-tests
"""
import contextlib
import http.server
import io
import json
import os
import socket
import sys
import threading
import unittest
from unittest import mock

from agent_tools.console import manager, permit
from agent_tools.console import sprint

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_approved_action import ACTION_COMMAND, ActionCase
from .test_console_manager_service import MERGE, PermitCase

TIER = "fast"  # a local service on a free port and the standard library


class PermitWireTest(PermitCase):
    def test_the_command_and_the_route_agree(self):
        svc, sid = self.boot()
        hook = {"session_id": "s-1", "tool_use_id": "t-1", "tool_name": "Bash",
                "tool_input": {"command": MERGE}}
        out = io.StringIO()
        with mock.patch.dict(os.environ, {manager.ID_ENV: sid, manager.SECRET_ENV: self.secret(sid)}), \
                mock.patch.object(sys, "stdin", io.StringIO(json.dumps(hook))), \
                contextlib.redirect_stdout(out):
            code = sprint.main(["permit", "--port", str(svc.address[1])])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue()), {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "allow",
            "permissionDecisionReason": ""}})
        self.assertEqual(len(out.getvalue().splitlines()), 1)
        out = io.StringIO()
        with mock.patch.dict(os.environ, {manager.ID_ENV: sid, manager.SECRET_ENV: self.secret(sid)}), \
                mock.patch.object(sys, "stdin", io.StringIO(json.dumps(hook))), \
                contextlib.redirect_stdout(out):
            code = sprint.main(["permit", "--landed", "--port", str(svc.address[1])])
        self.assertEqual((code, out.getvalue()), (0, ""))
        self.assertEqual(len(self.rows("permit.landed")), 1)


def hook_input(command, call="t-1"):
    document = {"session_id": "s-1", "tool_name": "Bash", "tool_input": {"command": command}}
    if call is not None:
        document["tool_use_id"] = call
    return json.dumps(document)


class ActionWireTest(ActionCase):
    def run_hook(self, port, text, *flags, env):
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), mock.patch.object(sys, "stdin", io.StringIO(text)), \
                contextlib.redirect_stdout(out):
            code = sprint.main(["permit", *flags, "--port", str(port)])
        return code, out.getvalue()

    def own(self, sid):
        return {manager.ID_ENV: sid, manager.SECRET_ENV: self.secret(sid)}

    def test_the_hook_allows_an_approved_action_once_and_records_it_ran(self):
        svc, sid = self.boot()
        svc.answer_question("owner/p01", sid, self.ask_action(svc, sid), 0, 0, None)
        port = svc.address[1]
        code, text = self.run_hook(port, hook_input(ACTION_COMMAND), env=self.own(sid))
        self.assertEqual((code, text.splitlines()), (0, [sprint.permit_line("allow", "")]))
        code, text = self.run_hook(port, hook_input(ACTION_COMMAND), "--landed", env=self.own(sid))
        self.assertEqual((code, text), (0, ""))
        landed = self.rows("permit.landed")
        self.assertEqual([row["verb"] for row in landed], ["action"])
        code, text = self.run_hook(port, hook_input(ACTION_COMMAND, "t-2"), env=self.own(sid))
        self.assertEqual((code, text.splitlines()),
                         (0, [sprint.permit_line("deny", permit.ACTION_USED)]))

    def test_an_impostor_on_the_port_learns_no_secret_and_its_allow_prints_nothing(self):
        bodies, reply = [], {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                bodies.append(self.rfile.read(int(self.headers["Content-Length"])))
                data = json.dumps(reply["now"]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        digest = permit.command_digest(ACTION_COMMAND)
        env = {manager.ID_ENV: "0" * 16, manager.SECRET_ENV: "the-sprint-secret"}
        replies = {
            "no mac": {"decision": "allow", "reason": ""},
            "another secret": {"decision": "allow", "reason": "", "mac": permit.action_reply_mac(
                "another-secret", "0" * 16, "b" * 32, digest, "allow", "")},
            "another nonce": {"decision": "allow", "reason": "", "mac": permit.action_reply_mac(
                "the-sprint-secret", "0" * 16, "b" * 32, digest, "allow", "")},
        }
        for name, answer in replies.items():
            for flags in ((), ("--landed",)):
                with self.subTest(name, flags=flags):
                    reply["now"] = answer
                    bodies.clear()
                    code, text = self.run_hook(server.server_address[1], hook_input(ACTION_COMMAND),
                                               *flags, env=env)
                    self.assertEqual((code, text), (0, ""))
                    self.assertEqual(len(bodies), 1)
                    self.assertNotIn(b"the-sprint-secret", bodies[0])
                    self.assertNotIn(ACTION_COMMAND.encode(), bodies[0])
                    sent = json.loads(bodies[0])
                    self.assertEqual(set(sent), {"sprint_id", "phase", "session_id", "tool_use_id",
                                                 "command_sha256", "nonce", "auth"})
                    self.assertEqual(sent["command_sha256"], digest)

    def test_a_plain_command_prints_nothing_when_the_console_cannot_answer(self):
        svc, sid = self.boot()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            closed = probe.getsockname()[1]
        for flags in ((), ("--landed",)):
            self.assertEqual(self.run_hook(closed, hook_input("git status"), *flags, env=self.own(sid)),
                             (0, ""))
        with mock.patch.object(sprint, "ask") as sent:
            self.assertEqual(self.run_hook(svc.address[1], hook_input("git status", None),
                                           env=self.own(sid)), (0, ""))
        sent.assert_not_called()
        svc.answer_question("owner/p01", sid, self.ask_action(svc, sid), 0, 0, None)
        wrong = {manager.ID_ENV: sid, manager.SECRET_ENV: "not the secret"}
        self.assertEqual(self.run_hook(svc.address[1], hook_input(ACTION_COMMAND), env=wrong), (0, ""))
        code, text = self.run_hook(svc.address[1], hook_input(ACTION_COMMAND), env=self.own(sid))
        self.assertEqual(text.splitlines(), [sprint.permit_line("allow", "")])
        code, text = self.run_hook(closed, hook_input(MERGE), env=self.own(sid))
        line = json.loads(text)["hookSpecificOutput"]
        self.assertEqual(line["permissionDecision"], "deny")
        self.assertTrue(line["permissionDecisionReason"].startswith(
            sprint.PERMIT_FAILED.split("{reason}")[0]))


if __name__ == "__main__":
    unittest.main()
