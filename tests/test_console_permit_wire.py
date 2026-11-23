"""The wire between `sprint permit` and the service route (#1377, moved out of the manager service tests, #1620).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

from agent_tools.console import manager
from agent_tools.console import sprint

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
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


if __name__ == "__main__":
    unittest.main()
