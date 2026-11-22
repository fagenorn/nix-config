"""The engine run history: one line per run end, kept 180 days (#1519).

Layout, under `~/.agents/state/engine/` (mode 0700):

    history.jsonl         one compact sorted-key JSON line per run end, appended and fsynced
    .history.jsonl.lock   the exclusive flock every append and prune of the history holds

A line has exactly `format`, `run`, `project`, `issue`, `end`, `need`, `ended` and `steps`: `end` is
`done` or the name of the stop the run reached, `need` the stop's need (null for done), `ended` the
instant the line was written, in UTC, and `steps` the per-step summaries `engine_ledger.fold` derives.
A run that is continued and ends again appends a second line; no earlier line is ever rewritten, so a
run's last line is its complete one.

A line holds no environment value, no credential, no prompt and no reply: only names, counts, outcomes
and times from the ledger.

`prune_history` drops a line whose `ended` is more than `HISTORY_DAYS` days before `now` and keeps every
other line byte for byte, whatever it holds.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Mapping

from agent_tools.canonical import parse_rfc3339_utc
from agent_tools.delivery import engine_ledger

HISTORY_FORMAT = 1
HISTORY_DAYS = 180


def engine_root() -> Path:
    return Path(os.environ["HOME"]) / ".agents/state/engine"


def history_path() -> Path:
    return engine_root() / "history.jsonl"


def history_line(state: engine_ledger.RunState, ended: datetime) -> dict:
    """The history line of a run that is done or stopped; `ValueError` for any other run."""
    if state.done:
        end, need = "done", None
    elif state.stop is not None:
        end, need = state.stop["name"], state.stop["need"]
    else:
        raise ValueError("a run that is neither done nor stopped has no history line")
    return {"format": HISTORY_FORMAT, "run": state.run, "project": state.project,
            "issue": state.issue, "end": end, "need": need,
            "ended": ended.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "steps": [dict(step) for step in state.steps]}


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    lock = os.open(path.parent / f".{path.name}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield
    finally:
        os.close(lock)


def append_history(line: Mapping, path: Path | None = None) -> None:
    """Append `line` as one compact line, after cutting a torn tail; fsynced under the lock."""
    path = history_path() if path is None else Path(path)
    data = json.dumps(line, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    engine_ledger.make_root(path.parent)
    with _locked(path):
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            engine_ledger._cut_torn_tail(descriptor)
            view = memoryview(data)
            while view:
                view = view[os.write(descriptor, view):]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _expired(line: bytes, cutoff: datetime) -> bool:
    try:
        loaded = json.loads(line.decode("utf-8"))
        return parse_rfc3339_utc(loaded["ended"]) < cutoff
    except (ValueError, KeyError, TypeError):
        return False


def prune_history(now: datetime, path: Path | None = None) -> int:
    """Drop the lines older than `HISTORY_DAYS` days and any torn tail; return how many lines went."""
    path = history_path() if path is None else Path(path)
    if not path.exists():
        return 0
    cutoff = now - timedelta(days=HISTORY_DAYS)
    with _locked(path):
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return 0
        *whole, tail = data.split(b"\n")
        kept = [part for part in whole if not _expired(part, cutoff)]
        dropped = len(whole) - len(kept)
        if dropped == 0 and not tail:
            return 0
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        try:
            os.fchmod(handle, 0o600)
            payload = b"".join(part + b"\n" for part in kept)
            view = memoryview(payload)
            while view:
                view = view[os.write(handle, view):]
            os.fsync(handle)
            os.close(handle)
            handle = -1
            os.replace(temporary, path)
        except BaseException:
            if handle >= 0:
                os.close(handle)
            Path(temporary).unlink(missing_ok=True)
            raise
        engine_ledger._fsync_path(path.parent)
        return dropped
