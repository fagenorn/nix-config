"""`bypass_proof_mcp`: a stub MCP server that records a production MCP tool call (#1152).

`python -m agent_tools.console.bypass_proof_mcp --tool NAME --marks DIR` is not a command: the
bypass proof starts it as the stdio MCP server of a throwaway project. `NAME` is the full tool
name, `mcp__<server>__<tool>`; `DIR` is where a call leaves its mark.

It reads newline-delimited JSON-RPC 2.0 from stdin, writes one JSON line per response to stdout
and flushes, and exits 0 on stdin EOF. Standard library only.

- `initialize` answers `{"protocolVersion": <the request's params.protocolVersion, else
  "2025-06-18">, "capabilities": {"tools": {}}, "serverInfo": {"name": <server>, "version": "1"}}`.
- A message without `id` (a notification such as `notifications/initialized`) gets no reply.
- `tools/list` answers exactly one tool, `<tool>`, with `inputSchema` `{"type": "object"}`.
- `tools/call` with `params.name` equal to `<tool>` creates the empty file `DIR/NAME` and answers
  `{"content": [{"type": "text", "text": "the production MCP tool ran"}], "isError": false}`; any
  other name answers JSON-RPC error -32602.
- Any other method answers error -32601 (method not found); a line that is not a JSON object is
  skipped.

Listing never writes a mark: the file exists only if the tool itself ran.
"""
import argparse
import json
import sys
from pathlib import Path

DEFAULT_PROTOCOL = "2025-06-18"
DESCRIPTION = "Bypass proof: records that the production MCP tool ran."
RESULT_TEXT = "the production MCP tool ran"


def split_tool(name):
    """`mcp__<server>__<tool>` -> `(server, tool)`, split at the first `__` after the prefix."""
    prefix = "mcp__"
    if not name.startswith(prefix):
        raise ValueError(f"not an MCP tool name (no {prefix} prefix): {name}")
    server, separator, tool = name[len(prefix):].partition("__")
    if not separator or not server or not tool:
        raise ValueError(f"not an MCP tool name (no server and tool parts): {name}")
    return server, tool


def _error(id, code, message):
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


def handle(message, tool, marks):
    """The JSON-RPC response for one request; None for a notification."""
    if "id" not in message:
        return None
    id = message["id"]
    server, tool_part = split_tool(tool)
    params = message.get("params")
    params = params if isinstance(params, dict) else {}
    method = message.get("method")
    if method == "initialize":
        protocol = params.get("protocolVersion")
        result = {"protocolVersion": protocol if isinstance(protocol, str) else DEFAULT_PROTOCOL,
                  "capabilities": {"tools": {}},
                  "serverInfo": {"name": server, "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": tool_part, "description": DESCRIPTION,
                             "inputSchema": {"type": "object"}}]}
    elif method == "tools/call":
        if params.get("name") != tool_part:
            return _error(id, -32602, f"unknown tool: {params.get('name')}")
        marks.mkdir(parents=True, exist_ok=True)
        (marks / tool).touch()
        result = {"content": [{"type": "text", "text": RESULT_TEXT}], "isError": False}
    else:
        return _error(id, -32601, f"method not found: {method}")
    return {"jsonrpc": "2.0", "id": id, "result": result}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="bypass_proof_mcp")
    parser.add_argument("--tool", required=True)
    parser.add_argument("--marks", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        split_tool(args.tool)
    except ValueError as problem:
        parser.error(str(problem))
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if not isinstance(message, dict):
            continue
        response = handle(message, args.tool, args.marks)
        if response is not None:
            print(json.dumps(response), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
