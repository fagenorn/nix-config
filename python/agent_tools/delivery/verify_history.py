"""The verify-slot history: one JSON line per run, appended to a file the whole host shares.

`verify-slot run` appends one line to `history.jsonl` in the slot directory for every run that got
past setup: a run that held a slot, one that hit `--wait-limit` and one signalled while it waited.
A line is `json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)` plus a
newline, UTF-8, with exactly these keys:

    {"command":"just test","exit":0,"held_seconds":412.3,"repository":"owner/repo",
     "started":"2026-11-23T19:24:20Z","waited_seconds":12.0}

`repository` is the run's lowercased `owner/repo`, or null outside a repository. `command` is the
first `COMMAND_WORDS` whitespace-separated words of the argv. `started` is the UTC instant the run
began waiting. `waited_seconds` is the time from just before the first slot try to the slot taken
(or to the end of the wait when none was taken); `held_seconds` is the time from the slot taken to
the slot and repository lock given back, or null when no slot was taken. Both are rounded to one
decimal. `exit` is the code the run returns.

The file is created with mode 0666, so every account of the host appends to it. It is appended
without a lock, by one `O_APPEND` write per run, is never pruned, and is lost when the host clears
its temporary directory at boot.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
import json
import os
from pathlib import Path

HISTORY_FILE = "history.jsonl"
COMMAND_WORDS = 3


def history_path(directory: Path) -> Path:
    return directory / HISTORY_FILE


def entry(repository: str | None, argv: Sequence[str], started: datetime, waited: float,
          held: float | None, exit_code: int) -> dict:
    """The record of one run, with its argv cut to `COMMAND_WORDS` words."""
    return {
        "command": " ".join(" ".join(argv).split()[:COMMAND_WORDS]),
        "exit": exit_code,
        "held_seconds": None if held is None else round(held, 1),
        "repository": repository,
        "started": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "waited_seconds": round(waited, 1),
    }


def _open_history(path: Path) -> int:
    """Open the history file for appending, creating it with mode 0666 when it does not exist."""
    try:
        return os.open(path, os.O_WRONLY | os.O_APPEND)
    except FileNotFoundError:
        pass
    old = os.umask(0)
    try:
        return os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_EXCL, 0o666)
    except FileExistsError:
        return os.open(path, os.O_WRONLY | os.O_APPEND)
    finally:
        os.umask(old)


def append(path: Path, line: Mapping) -> None:
    """Append `line` as one record; raise `OSError` when it cannot be written whole."""
    data = (json.dumps(line, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    descriptor = _open_history(path)
    try:
        if os.write(descriptor, data) != len(data):
            raise OSError(f"short write to {path}")
    finally:
        os.close(descriptor)
