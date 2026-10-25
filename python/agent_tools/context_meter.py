"""`context-meter`: a PreToolUse hook that measures an agent's context (issue 424).

It does two jobs: it rewrites a progress call to carry the measured context, and
it tells an owner of a phase gate once per crossing of the hand-off threshold.

Claude Code runs it before every Bash tool call with the call as JSON on stdin.
A command from a non-owner that contains no `workflow-state progress` invocation
produces no output and reads no transcript. For one that does, it reads the
calling agent's own context from its transcript and answers with the same command
rewritten to carry that measurement in place of whatever `--context-tokens` the
agent wrote, so the value the progress gate sees is measured, never self-reported. A progress
call it cannot tokenise passes through unchanged with a message saying so.

An agent that runs a registering call (a `workflow-state progress` or
`mark-progress`, or an `sdd-gate`, with an `--action-id`) becomes an owner of a
phase gate. For an owner every Bash call reads the transcript, and the first
measurement at or above `CONTEXT_CEILING - CONTEXT_HEADROOM` adds one
instruction to run the phase gate, unless that call is a progress call the meter
rewrote to carry the measurement (it already runs the gate); it fires again only
after a measurement below the threshold. The instruction and the measured note
never share one output, since the note exists only on such a rewrite; a progress
call left unchanged keeps its `systemMessage` beside the instruction. The per-owner state lives under
`~/.agents/state/context-meter/` (see `context_meter_crossing`); a call that
registers nothing from an agent with no state file reads no transcript and
writes nothing.

The hook grants nothing. It never prints `permissionDecision`, `decision` or
`continue` and never exits 2: the permission and lifecycle guards decide
independently whether the call runs, and a failure here leaves the call as the
agent wrote it. An unmeasurable context removes a progress call's value and says so.
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
                     measured: int | None, reason: str | None) -> tuple[dict, bool]:
    """The output for a call holding progress invocations, and whether it carries `measured`.

    It carries the measurement only on a proved rewrite of a measured context.
    """
    rewrite = rewrite_progress(command, tokens, measured)
    if not rewrite.proved:
        return _unchanged("the rewrite failed its proof"), False
    hook: dict = {"hookEventName": "PreToolUse"}
    if rewrite.command != command:
        hook["updatedInput"] = {**tool_input, "command": rewrite.command}
    if measured is None:
        hook["additionalContext"] = UNMEASURED_NOTE
        return {"hookSpecificOutput": hook,
                "systemMessage": UNMEASURED_MESSAGE.format(reason=reason)}, False
    hook["additionalContext"] = MEASURED_NOTE.format(tokens=measured)
    return {"hookSpecificOutput": hook}, True


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
    output, carries = (_progress_output(command, tool_input, tokens, measurement.tokens,
                                        measurement.reason) if starts else (None, False))
    if owner and context_meter_crossing.record(
            state_dir, identity, register=register, measured=measurement.tokens,
            progress=carries, threshold=threshold):
        crossing: dict = {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": CROSSING_NOTE.format(
                tokens=measurement.tokens, threshold=threshold)}}
        if output is not None and "systemMessage" in output:
            crossing["systemMessage"] = output["systemMessage"]
        return crossing
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
