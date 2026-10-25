"""`context-meter`: a PreToolUse hook that measures the context of a progress call (issue 424).

Claude Code runs it before every Bash tool call with the call as JSON on stdin.
A command that contains no `workflow-state progress` invocation produces no
output and reads no transcript. For one that does, it reads the calling agent's
own context from its transcript and answers with the same command rewritten to
carry that measurement in place of whatever `--context-tokens` the agent wrote,
so the value the progress gate sees is measured, never self-reported.

The hook grants nothing. It never prints `permissionDecision`, `decision` or
`continue` and never exits 2: the permission and lifecycle guards decide
independently whether the call runs, and a failure here leaves the call as the
agent wrote it. An unmeasurable context removes the agent's value and says so.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback

from agent_tools.context_meter_commands import (
    lex, mentions_progress, progress_starts, rewrite_progress)
from agent_tools.context_meter_transcript import measure

MEASURED_NOTE = ("context-meter: this workflow-state progress call carries "
                 "--context-tokens {tokens}, measured from your transcript.")
UNMEASURED_NOTE = ("context-meter: your context could not be measured, so this "
                   "workflow-state progress call carries no --context-tokens.")
UNMEASURED_MESSAGE = ("context-meter: could not measure this agent's context ({reason}); "
                      "its workflow-state progress call runs without --context-tokens.")
UNCHANGED_MESSAGE = "context-meter: left a workflow-state progress call unchanged ({reason})."


def _unchanged(reason: str) -> dict:
    return {"systemMessage": UNCHANGED_MESSAGE.format(reason=reason)}


def respond(payload: object) -> dict | None:
    """The hook output for one PreToolUse payload, or `None` to leave the call alone."""
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict) or not isinstance(tool_input.get("command"), str):
        return None
    command = tool_input["command"]
    tokens = lex(command)
    if tokens is None:
        if mentions_progress(command):
            return _unchanged("the command could not be tokenised")
        return None
    if not progress_starts(tokens):
        return None
    measurement = measure(payload)
    rewrite = rewrite_progress(command, tokens, measurement.tokens)
    if not rewrite.proved:
        return _unchanged("the rewrite failed its proof")
    hook: dict = {"hookEventName": "PreToolUse"}
    if rewrite.command != command:
        hook["updatedInput"] = {**tool_input, "command": rewrite.command}
    if measurement.tokens is None:
        hook["additionalContext"] = UNMEASURED_NOTE
        return {"hookSpecificOutput": hook,
                "systemMessage": UNMEASURED_MESSAGE.format(reason=measurement.reason)}
    hook["additionalContext"] = MEASURED_NOTE.format(tokens=measurement.tokens)
    return {"hookSpecificOutput": hook}


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="context-meter", description=__doc__)


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        traceback.print_exc()
        return 1
    try:
        payload = json.loads(raw)
    except ValueError:
        return 0
    try:
        result = respond(payload)
    except Exception:
        traceback.print_exc()
        return 1
    if result is not None:
        sys.stdout.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
