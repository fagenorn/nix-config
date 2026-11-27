"""Engine run evidence, read as the engine's ledger reads a run (`agent_tools.delivery.engine_ledger`).

A verification check may not import the delivery area, so this module holds the ledger's contract for what a check
reads and `tests/test_verify_engine_past_setup.py` pins each member of it to the ledger's own tables and verdicts.
A run is a directory named by a run id whose `run.json` holds the run members and names that run; an event is a line
of strict JSON whose members are exactly those its type carries. `runs` and `lines` raise `EvidenceError` when the
evidence cannot be read, so a check never picks a verdict without it; `event` raises `ValueError` for a line the
ledger would refuse.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.canonical import parse_rfc3339_utc, reject_duplicate_keys, reject_nonfinite_literal

RUN_ID_RE = re.compile(r"^([1-9][0-9]*)-([0-9]{8}T[0-9]{6}Z)-([a-z0-9]{4})$")
NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
RUN_MEMBERS = frozenset(("host", "inputs", "issue", "platform_revision", "procedure", "project",
                         "run", "sequence", "started"))
OPTIONAL_RUN_MEMBERS = frozenset(("tracker", "parent", "starter"))
STAGES = ("setup", "planning", "plan review", "building", "final review",
          "verifying", "awaiting look", "landing", "closing out", "done")
NEEDS = ("owner-decision", "owner-look", "retry", "nothing")
# The members of each event type besides `event` and `at`, and those it may carry besides.
EVENT_MEMBERS = {
    "step_entered": ("step", "visit", "stage"),
    "session_starting": ("step", "visit", "session", "role", "account"),
    "process_started": ("step", "visit", "pid", "started"),
    "session_resuming": ("step", "visit", "session", "attempt"),
    "session_answered": ("step", "visit", "session", "attempt", "account"),
    "result_stored": ("step", "visit", "result", "wall_seconds", "turns", "tokens", "spend_usd"),
    "outcome_graded": ("step", "visit", "outcome"),
    "transition_taken": ("step", "visit", "outcome", "to"),
    "wait_started": ("wait", "until"),
    "wait_ended": ("wait",),
    "stop_reached": ("step", "stop", "need"),
    "call": ("step", "visit", "child", "index", "items"),
    "keep_alive_ran": ("step", "visit", "attempt", "verdict"),
    "run_continued": (),
    "run_done": (),
}
EVENT_OPTIONAL = {"result_stored": ("head", "outcome", "startup_seconds"),"run_continued": ("step", "visit")}


class EvidenceError(Exception):
    """The evidence could not be read: `kind` is the label a check reports."""

    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind = kind


def _int(value: object, least: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= least


def _strict(text: str) -> object:
    return json.loads(text, object_pairs_hook=reject_duplicate_keys, parse_constant=reject_nonfinite_literal)


def named_start(run_id: str) -> datetime:
    """The second a run id names, which is the run's start."""
    return datetime.strptime(RUN_ID_RE.fullmatch(run_id).group(2),
                             "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def read_run(run_dir: Path) -> tuple[datetime, dict]:
    """The start and `run.json` of a run, as the ledger reads a run; `ValueError` when it is not one."""
    document = _strict((run_dir / "run.json").read_text(encoding="utf-8"))
    if (not isinstance(document, dict) or not RUN_MEMBERS <= set(document)
            or not set(document) <= RUN_MEMBERS | OPTIONAL_RUN_MEMBERS):
        raise ValueError("run.json does not have exactly the run members")
    parent, tracker, starter = (document.get(member) for member in ("parent", "tracker", "starter"))
    if "parent" in document and not (isinstance(parent, str) and RUN_ID_RE.fullmatch(parent)):
        raise ValueError("run.json parent is not a run id")
    if any(member in document and not (isinstance(value, str) and value)
           for member, value in (("tracker", tracker), ("starter", starter))):
        raise ValueError("run.json tracker or starter is not a non-empty string")
    if not isinstance(document["project"], str) or not _int(document["sequence"], 1):
        raise ValueError("run.json project is not a string or sequence not an integer of at least 1")
    if document["run"] != run_dir.name:
        raise ValueError("run.json run is not the name of its run directory")
    return parse_rfc3339_utc(document["started"]), document


def runs(runs_root: Path, since: datetime) -> list[tuple[datetime, str, Path, dict]]:
    """The (started, id, directory, run.json) of each published run under `runs_root`, earliest first.

    An unpublished `.<run id>.tmp` directory is no run. A runs root that cannot be listed (an absent one holds
    none), or a run named at or after `since` that is not read as the ledger reads one, is an `EvidenceError`;
    a run named before `since` that does not read is no candidate and is skipped."""
    try:
        names = sorted(path for path in runs_root.iterdir() if RUN_ID_RE.fullmatch(path.name) and path.is_dir())
    except FileNotFoundError:
        return []
    except OSError as error:
        raise EvidenceError("runs_unreadable", f"{runs_root}: {type(error).__name__}") from error
    found = []
    for run_dir in names:
        try:
            started, document = read_run(run_dir)
        except (OSError, ValueError) as error:
            if not run_dir.exists() or named_start(run_dir.name) < since:
                continue  # renamed away by a housekeeping sweep, or older than any delivery that counts
            raise EvidenceError("run_unreadable", f"{run_dir.name}: {error}") from error
        found.append((started, run_dir.name, run_dir, document))
    return sorted(found, key=lambda run: run[:2])


def lines(run_dir: Path) -> list[bytes]:
    """The complete lines of a run's `events.jsonl`; a last segment with no newline is a write cut short.

    No lines when the file is absent; an `EvidenceError` when it cannot be read."""
    try:
        data = (run_dir / "events.jsonl").read_bytes()
    except FileNotFoundError:
        return []
    except OSError as error:
        raise EvidenceError("run_unreadable", f"{run_dir.name}: {type(error).__name__}") from error
    return data.split(b"\n")[:-1]


def event(line: bytes) -> dict:
    """The event one line holds, `ValueError` when the ledger would refuse it.

    Its members are exactly those its type carries; each member a check reads is validated as the ledger does."""
    loaded = _strict(line.decode("utf-8"))
    kind = loaded.get("event") if isinstance(loaded, dict) else None
    if kind not in EVENT_MEMBERS:
        raise ValueError("not an event of a known type")
    required = {"event", "at", *EVENT_MEMBERS[kind]}
    if not required <= set(loaded) <= required | set(EVENT_OPTIONAL.get(kind, ())):
        raise ValueError(f"{kind} does not have exactly its members")
    parse_rfc3339_utc(loaded["at"])
    checks = {
        "step": lambda v: isinstance(v, str) and NAME_RE.fullmatch(v), "visit": lambda v: _int(v, 1),
        "stage": lambda v: v in STAGES, "need": lambda v: v in NEEDS,
        "stop": lambda v: isinstance(v, str) and v != "", "outcome": lambda v: isinstance(v, str) and v != "",
        "to": lambda v: isinstance(v, str) and v != ""}
    for member, valid in checks.items():
        if member in loaded and not valid(loaded[member]):
            raise ValueError(f"{member} of {kind} is not valid")
    return loaded
