"""`context-meter`: a PreToolUse hook that measures the context of a progress call (issue 424).

Claude Code runs it before every Bash tool call with the call as JSON on stdin.
A command that contains no `workflow-state progress` invocation produces no
output and reads no transcript. For one that does, it reads the calling agent's
own context from its transcript and answers with the same command rewritten to
carry that measurement in place of whatever `--context-tokens` the agent wrote,
so the value the progress gate sees is measured, never self-reported. A progress
call it cannot tokenise passes through unchanged with a message saying so.

An agent that runs a registering call (a `workflow-state progress` or
`mark-progress`, or an `sdd-gate`, with an `--action-id`) becomes an owner of a
phase gate. For an owner every Bash call reads the transcript, and the first
measurement at or above `CONTEXT_CEILING - CONTEXT_HEADROOM` adds one
instruction to run the phase gate; it fires again only after a measurement below
the threshold. The per-owner state lives under
`~/.agents/state/context-meter/` (see `context_meter_crossing`); a call that
registers nothing from an agent with no state file reads no transcript and
writes nothing.

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
from pathlib import Path

from agent_tools import context_meter_crossing, phase_budget
from agent_tools.context_meter_commands import (
    lex, mentions_progress, progress_starts, registers_owner, rewrite_progress)
from agent_tools.context_meter_transcript import agent_identity, measure

MEASURED_NOTE = ("context-meter: this workflow-state progress call carries "
                 "--context-tokens {tokens}, measured from your transcript.")
UNMEASURED_NOTE = ("context-meter: your context could not be measured, so this "
                   "workflow-state progress call carries no --context-tokens.")
UNMEASURED_MESSAGE = ("context-meter: could not measure this agent's context ({reason}); "
                      "its workflow-state progress call runs without --context-tokens.")
UNCHANGED_MESSAGE = "context-meter: left a workflow-state progress call unchanged ({reason})."
CROSSING_NOTE = (
    "context-meter: your context is {tokens} tokens, at or above the {threshold}-token "
    "hand-off threshold. At the next safe point (the step in hand committed, no worker you "
    "dispatched still running), run your phase gate: workflow-state progress for your last "
    "completed phase, with truthful booleans, then obey its action. This notice is not "
    "repeated.")


def _unchanged(reason: str) -> dict:
    return {"systemMessage": UNCHANGED_MESSAGE.format(reason=reason)}


def _progress_output(command: str, tool_input: dict, tokens: list,
                     measured: int | None, reason: str | None) -> dict:
    rewrite = rewrite_progress(command, tokens, measured)
    if not rewrite.proved:
        return _unchanged("the rewrite failed its proof")
    hook: dict = {"hookEventName": "PreToolUse"}
    if rewrite.command != command:
        hook["updatedInput"] = {**tool_input, "command": rewrite.command}
    if measured is None:
        hook["additionalContext"] = UNMEASURED_NOTE
        return {"hookSpecificOutput": hook,
                "systemMessage": UNMEASURED_MESSAGE.format(reason=reason)}
    hook["additionalContext"] = MEASURED_NOTE.format(tokens=measured)
    return {"hookSpecificOutput": hook}


def respond(payload: object, *, state_dir: Path, threshold: int) -> dict | None:
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
    starts = progress_starts(tokens)
    register = registers_owner(tokens)
    identity = agent_identity(payload)
    owner = identity is not None and (
        register or context_meter_crossing.is_owner(state_dir, identity))
    if not starts and not owner:
        return None
    measurement = measure(payload)
    output = (_progress_output(command, tool_input, tokens, measurement.tokens,
                               measurement.reason) if starts else None)
    if owner and context_meter_crossing.record(
            state_dir, identity, register=register, measured=measurement.tokens,
            progress=bool(starts), threshold=threshold):
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": CROSSING_NOTE.format(
                tokens=measurement.tokens, threshold=threshold)}}
    return output


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
        result = respond(
            payload, state_dir=context_meter_crossing.state_dir(Path.home()),
            threshold=phase_budget.CONTEXT_CEILING - phase_budget.CONTEXT_HEADROOM)
    except Exception:
        traceback.print_exc()
        return 1
    if result is not None:
        sys.stdout.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
