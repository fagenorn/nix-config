"""The per-owner state that makes the hand-off instruction fire once per crossing (issue 424).

An owner is an agent that has run a registering call (`workflow-state progress`
or `mark-progress`, or `sdd-gate`, with an `--action-id`). Each owner has one
state file, `<session_id>.main.json` for a main session and
`<session_id>.agent-<agent_id>.json` for a subagent, holding
`{"notified": <bool>, "owner": true, "phase": <0-8 or null>}`; a record written
before `phase` existed has only the first two keys and is read as `phase: null`,
and every write is the three-key form. `phase` is the phase the owner is entering,
so the hand-off threshold is the one of that phase. Hooks of parallel tool calls update it
under an exclusive `flock`, so the read-decide-write sequence is atomic.

A call that holds a progress invocation sets `phase` to its `--phase` plus one, and a
registering `mark-progress` or `sdd-gate` sets it to 6 while it is `null`; the update is
applied before the crossing is decided. A measurement below the threshold clears `notified`; the first measurement at or
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

from agent_tools import phase_budget
from agent_tools.canonical import reject_duplicate_keys
from agent_tools.context_meter_transcript import AgentIdentity

RECORD_KEYS = {"notified", "owner", "phase"}
LAST_PHASE = 8
SDD_PHASE = 6


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
        return {"notified": False, "owner": True, "phase": None}
    message = f"context-meter: {path} is not an owner state record"
    try:
        state = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
    except ValueError as error:
        raise ValueError(message) from error
    if isinstance(state, dict) and set(state) == RECORD_KEYS - {"phase"}:
        state = {**state, "phase": None}
    phase = state.get("phase") if isinstance(state, dict) else None
    if (not isinstance(state, dict) or set(state) != RECORD_KEYS
            or state["owner"] is not True or not isinstance(state["notified"], bool)
            or not (phase is None or (type(phase) is int and 0 <= phase <= LAST_PHASE))):
        raise ValueError(message)
    return state


def _entered(state: dict, phase_update: int | None, sets_phase_six: bool) -> dict:
    if phase_update is not None and 0 <= phase_update <= LAST_PHASE:
        return {**state, "phase": phase_update}
    if sets_phase_six and state["phase"] is None:
        return {**state, "phase": SDD_PHASE}
    return state


def _transition(state: dict, measured: int | None, progress: bool,
                threshold: int) -> tuple[dict, bool]:
    if measured is None:
        return state, False
    if measured < threshold:
        return {**state, "notified": False}, False
    return {**state, "notified": True}, not state["notified"] and not progress


def record(directory: Path, identity: AgentIdentity, *, register: bool, measured: int | None,
           progress: bool, phase_update: int | None, sets_phase_six: bool,
           budget: phase_budget.PhaseBudget) -> tuple[bool, int]:
    """Apply one call to the owner's state: whether the instruction is due, and the threshold used."""
    path = state_path(directory, identity)
    unowned = phase_budget.crossing_threshold(budget, None, None)
    if not register and not path.exists():
        return False, unowned
    fd = _open(directory, path, register)
    if fd is None:
        return False, unowned
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        state = _entered(_read(fd, path), phase_update, sets_phase_six)
        threshold = phase_budget.crossing_threshold(budget, state["phase"], None)
        state, due = _transition(state, measured, progress, threshold)
        os.lseek(fd, 0, 0)
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps(state, sort_keys=True).encode("utf-8"))
        return due, threshold
    finally:
        os.close(fd)
