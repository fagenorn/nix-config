"""The per-owner state that makes the hand-off instruction fire once per crossing (issue 424).

An owner is an agent that has run a registering call (`workflow-state progress`
or `mark-progress`, or `sdd-gate`, with an `--action-id`). Each owner has one
state file, `<session_id>.main.json` for a main session and
`<session_id>.agent-<agent_id>.json` for a subagent, holding
`{"notified": <bool>, "owner": true}`. Hooks of parallel tool calls update it
under an exclusive `flock`, so the read-decide-write sequence is atomic.

A measurement below the threshold clears `notified`; the first measurement at or
above it sets `notified` and is due, unless the same call is a progress call
the meter rewrote to carry the measurement (that call reports the context
itself, so the instruction would repeat the gate it is already running). Later measurements at or above the
threshold are not due until one falls below it again. An unmeasured call changes
nothing. An empty file is an owner being registered; any other content that is
not exactly the record (a repeated key included) raises `ValueError`.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

from agent_tools.canonical import reject_duplicate_keys
from agent_tools.context_meter_transcript import AgentIdentity

RECORD_KEYS = {"notified", "owner"}


def state_dir(home: Path) -> Path:
    return home / ".agents" / "state" / "context-meter"


def state_path(directory: Path, identity: AgentIdentity) -> Path:
    who = "main" if identity.agent_id is None else f"agent-{identity.agent_id}"
    return directory / f"{identity.session_id}.{who}.json"


def is_owner(directory: Path, identity: AgentIdentity) -> bool:
    return state_path(directory, identity).exists()


def _open(directory: Path, path: Path, register: bool) -> int | None:
    if register:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        return os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        return os.open(path, os.O_RDWR)
    except FileNotFoundError:
        return None


def _read(fd: int, path: Path) -> dict:
    raw = b""
    while chunk := os.read(fd, 1 << 16):
        raw += chunk
    if not raw:
        return {"notified": False, "owner": True}
    message = f"context-meter: {path} is not an owner state record"
    try:
        state = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
    except ValueError as error:
        raise ValueError(message) from error
    if (not isinstance(state, dict) or set(state) != RECORD_KEYS
            or state["owner"] is not True or not isinstance(state["notified"], bool)):
        raise ValueError(message)
    return state


def _transition(state: dict, measured: int | None, progress: bool,
                threshold: int) -> tuple[dict, bool]:
    if measured is None:
        return state, False
    if measured < threshold:
        return {**state, "notified": False}, False
    return {**state, "notified": True}, not state["notified"] and not progress


def record(directory: Path, identity: AgentIdentity, *, register: bool, measured: int | None,
           progress: bool, threshold: int) -> bool:
    """Apply one call to the owner's state; whether the hand-off instruction is due."""
    path = state_path(directory, identity)
    if not register and not path.exists():
        return False
    fd = _open(directory, path, register)
    if fd is None:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        state, due = _transition(_read(fd, path), measured, progress, threshold)
        os.lseek(fd, 0, 0)
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps(state, sort_keys=True).encode("utf-8"))
        return due
    finally:
        os.close(fd)
