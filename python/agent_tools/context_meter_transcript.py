"""Where an agent's transcript is and how its last model call is read (issue 424).

`context-meter` measures an agent's context from the usage Claude Code records
on the agent's last assistant message: input, cache-read and cache-creation
tokens. A subagent's transcript is `subagents/agent-<agent_id>.jsonl` beside the
session transcript; a main session reads the session transcript itself, whose
sidechain records belong to its subagents and are skipped. Only the last
`WINDOW_BYTES` of a transcript are read, so a transcript of any size costs one
bounded read.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

PLAIN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
WINDOW_BYTES = 1 << 20
USAGE_FIELDS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
SYNTHETIC_MODEL = "<synthetic>"


class AgentIdentity(NamedTuple):
    session_id: str
    agent_id: str | None


class Measurement(NamedTuple):
    """`reason` is set exactly when `tokens` is `None`."""

    tokens: int | None
    reason: str | None


def _plain_id(value: object) -> bool:
    return isinstance(value, str) and PLAIN_ID.fullmatch(value) is not None


def agent_identity(payload: Mapping[str, object]) -> AgentIdentity | None:
    """The session and agent ids when both are plain identifiers, else `None`."""
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not _plain_id(session_id):
        return None
    agent_id = payload.get("agent_id")
    if agent_id is None:
        return AgentIdentity(session_id, None)
    if not isinstance(agent_id, str) or not _plain_id(agent_id):
        return None
    return AgentIdentity(session_id, agent_id)


def _unmeasured(reason: str) -> Measurement:
    return Measurement(None, reason)


def _usage_sum(usage: object) -> int:
    """The context a usage record reports, or 0 when it reports none or is malformed."""
    if not isinstance(usage, dict):
        return 0
    total = 0
    for name in USAGE_FIELDS:
        count = usage.get(name)
        if count is None:
            continue
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return 0
        total += count
    return total


def _record_context(piece: bytes, *, main_session: bool) -> int:
    """The context one transcript line reports, or 0 when it is not a usage record."""
    try:
        record = json.loads(piece)
    except (ValueError, RecursionError):
        return 0
    if not isinstance(record, dict) or record.get("type") != "assistant":
        return 0
    if main_session and record.get("isSidechain") is True:
        return 0
    message = record.get("message")
    if not isinstance(message, dict) or message.get("model") == SYNTHETIC_MODEL:
        return 0
    return _usage_sum(message.get("usage"))


def measure(payload: Mapping[str, object]) -> Measurement:
    """The agent's context at its last model call, or the reason it is unknown."""
    identity = agent_identity(payload)
    if identity is None:
        return _unmeasured("session or agent id is not a plain identifier")
    transcript_path = payload.get("transcript_path")
    if not isinstance(transcript_path, str) or not transcript_path:
        return _unmeasured("no transcript path")
    path = Path(transcript_path)
    if identity.agent_id is not None:
        path = path.parent / identity.session_id / "subagents" / f"agent-{identity.agent_id}.jsonl"
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            offset = max(0, size - WINDOW_BYTES)
            handle.seek(offset)
            data = handle.read()
    except FileNotFoundError:
        return _unmeasured("transcript not found")
    except OSError:
        return _unmeasured("transcript unreadable")
    pieces = data.split(b"\n")
    if offset > 0:
        pieces = pieces[1:]
    for piece in reversed(pieces):
        context = _record_context(piece, main_session=identity.agent_id is None)
        if context > 0:
            return Measurement(context, None)
    return _unmeasured(f"no usage record in the last {WINDOW_BYTES} bytes")
