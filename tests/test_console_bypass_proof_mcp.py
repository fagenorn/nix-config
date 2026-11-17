"""The stub MCP server that records a production MCP tool call for the bypass proof (#1152).

Run: just agent-workflow-tests
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.console.bypass_proof_mcp import split_tool
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parents[1]
TOOL = "mcp__bypassproof__apply"


def request(id, method, **params):
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params}


class BypassProofMcpTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.marks = Path(temporary.name)

    def run_server(self, *messages):
        stdin = "".join(json.dumps(message) + "\n" for message in messages)
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.console.bypass_proof_mcp",
             "--tool", TOOL, "--marks", str(self.marks)],
            input=stdin, capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONPATH": str(ROOT / "python")})
        self.assertEqual(done.returncode, 0, done.stderr)
        return [json.loads(line) for line in done.stdout.splitlines()]

    def test_initialize_list_and_call_record_the_mark(self):
        replies = self.run_server(
            request(1, "initialize", protocolVersion="2025-06-18"),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            request(2, "tools/list"),
            request(3, "tools/call", name="apply", arguments={}))
        self.assertEqual([reply["id"] for reply in replies], [1, 2, 3])
        self.assertEqual(replies[0]["result"]["serverInfo"]["name"], "bypassproof")
        self.assertEqual(replies[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual([tool["name"] for tool in replies[1]["result"]["tools"]], ["apply"])
        self.assertIs(replies[2]["result"]["isError"], False)
        self.assertTrue((self.marks / TOOL).exists())

    def test_listing_alone_writes_no_mark(self):
        self.run_server(request(1, "initialize", protocolVersion="2025-06-18"),
                        request(2, "tools/list"))
        self.assertEqual(list(self.marks.iterdir()), [])

    def test_unknown_method_and_tool_are_errors(self):
        replies = self.run_server(request(4, "resources/list"),
                                  request(5, "tools/call", name="other", arguments={}))
        self.assertEqual(replies[0]["error"]["code"], -32601)
        self.assertEqual(replies[1]["error"]["code"], -32602)
        self.assertEqual(list(self.marks.iterdir()), [])

    def test_split_tool(self):
        self.assertEqual(split_tool(TOOL), ("bypassproof", "apply"))
        self.assertEqual(split_tool("mcp__a__b__c"), ("a", "b__c"))
        for bad in ("apply", "mcp__nounderscores"):
            with self.assertRaises(ValueError):
                split_tool(bad)


if __name__ == "__main__":
    unittest.main()
