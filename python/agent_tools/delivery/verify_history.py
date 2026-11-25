"""The verify-slot history: one JSON line per run, appended to a file the whole host shares.

`verify-slot run` appends one line to `history.jsonl` in the slot directory for every run that got
past setup: a run that held a slot, one that hit `--wait-limit` and one signalled while it waited.
A line is `json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)` plus a
newline, UTF-8, with exactly these keys:

    {"command":"just test","exit":0,"held_seconds":412.3,"place":2,"repository":"owner/repo",
     "started":"2026-11-23T19:24:20Z","waited_seconds":12.0}

`repository` is the run's lowercased `owner/repo`, or null outside a repository. `command` is the
first `COMMAND_WORDS` whitespace-separated words of the argv. `started` is the UTC instant the run
began waiting. `waited_seconds` is the time from just before the first slot try to the slot taken
(or to the end of the wait when none was taken); `held_seconds` is the time from the slot taken to
the slot and repository lock given back, or null when no slot was taken. Both are rounded to one
decimal. `exit` is the code the run returns. `place` is the place the run joined the queue at (at
re-join for a resumed request), or null when it never joined.

The file is created with mode 0666, so every account of the host appends to it; it is opened
without following a symlink or blocking, and a path that is not a regular file with a single link
(a hard link planted by another account) is refused, for the append and the read alike. It is
appended without a lock, by one `O_APPEND` write per run, is never pruned, and is lost when the
host clears its temporary directory at boot.

`verify-slot report` reads the file back. A line is readable when it is a JSON object with exactly
the types above (`held_seconds` a number or null, the numbers finite and not below 0, `place`
absent as in older lines, null or an integer of at least 1); any other line, a torn last one
included, is skipped and counted. Over the runs that started in the window,
per repository (`NO_REPOSITORY` for null), it gives `runs`, the median and the nearest-rank 90th
percentile (the value at rank `ceil(0.9 * n)` of the sorted values) of the wait over every run,
and of the hold over the runs that held a slot, plus the sum of those holds. Its line is

    <label> runs=N held_median=Ns held_p90=Ns held_total=Ns waited_median=Ns waited_p90=Ns

with each figure rounded to whole seconds, the hold medians `-` and the total `0s` when no run held
a slot, and ` over budget <budget>s` appended when the hold median is strictly above the budget.

`read_from(path, identity, offset, baseline=False, limit=READ_LIMIT)` reads only what a caller has not
consumed. It answers the readable
records after `offset`, the file's identity `[st_dev, st_ino]` and the new offset. It reads from
`offset` while `identity` is the file's and the file is not shorter than `offset`, and from the first
byte otherwise (a replaced or shrunk file); it seeks there and never reads the bytes before it. It
reads at most `limit` bytes (`READ_LIMIT`, 1 MiB) per call and consumes only through the last newline
of them, so a torn last line is read whole by a later call, and skips an unreadable consumed line. A
record longer than `limit` has no newline in the bytes read: they are consumed unread, so the offset
advances and the memory held stays at `limit`. `baseline=True` reads no record: it answers
`([], identity, offset)` with the offset after the last newline of the file's final `limit` bytes (the
end of the file when they hold none, 0 for a short file without one). An absent file answers
`([], None, 0)`; the open is `read`'s.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import errno
import json
import math
import os
from pathlib import Path
import stat
import statistics

from agent_tools import canonical

HISTORY_FILE = "history.jsonl"
COMMAND_WORDS = 3
READ_LIMIT = 1 << 20
NO_REPOSITORY = "(no repository)"


def history_path(directory: Path) -> Path:
    return directory / HISTORY_FILE


def entry(repository: str | None, argv: Sequence[str], started: datetime, waited: float,
          held: float | None, exit_code: int, place: int | None) -> dict:
    """The record of one run, with its argv cut to `COMMAND_WORDS` words."""
    return {
        "command": " ".join(" ".join(argv).split()[:COMMAND_WORDS]),
        "exit": exit_code,
        "held_seconds": None if held is None else round(held, 1),
        "place": place,
        "repository": repository,
        "started": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "waited_seconds": round(waited, 1),
    }


def regular_descriptor(descriptor: int, path: Path) -> int:
    """`descriptor` when it is a regular file with one link; otherwise close it and raise `OSError`.

    A second link is another account's hard link to a file that is not ours to append to.
    """
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
            raise OSError(errno.EINVAL, "not a regular file with one link", str(path))
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _open_history(path: Path) -> int:
    """Open the history file for appending, creating it with mode 0666 when it does not exist.

    The file sits in a directory every account can write to, so the open never follows a symlink,
    never blocks on a FIFO and refuses anything that is not a regular file with a single link.
    """
    flags = os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        return regular_descriptor(os.open(path, flags), path)
    except FileNotFoundError:
        pass
    old = os.umask(0)
    try:
        return regular_descriptor(os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o666), path)
    except FileExistsError:
        return regular_descriptor(os.open(path, flags), path)
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


@dataclass(frozen=True)
class Summary:
    """One repository's figures over the report window; hold figures are None without a hold."""
    repository: str | None
    runs: int
    held_median: float | None
    held_p90: float | None
    held_total: float
    waited_median: float
    waited_p90: float


def _is_seconds(value: object) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def _is_place(value: object) -> bool:
    return value is None or (type(value) is int and value >= 1)


def _readable(line: bytes) -> dict | None:
    """The record `line` holds, or None when it is not a readable record."""
    try:
        record = json.loads(line.decode("utf-8"), parse_constant=canonical.reject_nonfinite_literal)
        if not isinstance(record, dict):
            return None
        canonical.parse_rfc3339_utc(record["started"])
        ok = (isinstance(record["repository"], (str, type(None)))
              and isinstance(record["command"], str)
              and type(record["exit"]) is int
              and _is_seconds(record["waited_seconds"])
              and (record["held_seconds"] is None or _is_seconds(record["held_seconds"]))
              and _is_place(record.get("place")))
    except (ValueError, KeyError, RecursionError, OverflowError):
        return None
    return record if ok else None


def read(path: Path) -> tuple[list[dict], int]:
    """The readable records of `path` and the count of unreadable lines; absent is `([], 0)`."""
    try:
        descriptor = regular_descriptor(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), path)
    except FileNotFoundError:
        return [], 0
    with os.fdopen(descriptor, "rb") as handle:
        data = handle.read()
    pieces = data.split(b"\n")
    if pieces and pieces[-1] == b"":
        pieces.pop()
    records = [_readable(piece) for piece in pieces]
    return [record for record in records if record is not None], records.count(None)


def read_from(path: Path, identity: list[int] | None, offset: int, baseline: bool = False,
              limit: int = READ_LIMIT) -> tuple[list[dict], list[int] | None, int]:
    """The readable records of `path` after the consumed position, the file's identity and the new offset."""
    try:
        descriptor = _regular(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), path)
    except FileNotFoundError:
        return [], None, 0
    with os.fdopen(descriptor, "rb") as handle:
        status = os.fstat(handle.fileno())
        found = [status.st_dev, status.st_ino]
        if baseline:
            start = max(0, status.st_size - limit)
            handle.seek(start)
            tail = handle.read(limit)
            newline = tail.rfind(b"\n")
            return [], found, start + newline + 1 if newline >= 0 else (0 if start == 0 else status.st_size)
        start = offset if identity == found and status.st_size >= offset else 0
        handle.seek(start)
        data = handle.read(limit)
    consumed = data.rfind(b"\n") + 1
    if consumed == 0 and len(data) == limit:
        consumed = limit
    pieces = data[:consumed].split(b"\n")[:-1]
    records = [_readable(piece) for piece in pieces]
    return [record for record in records if record is not None], found, start + consumed


def nearest_rank_p90(values: Sequence[float]) -> float:
    """The 90th percentile of the non-empty `values` by the nearest-rank method."""
    return sorted(values)[math.ceil(0.9 * len(values)) - 1]


def summarize(records: Iterable[Mapping], since: datetime) -> list[Summary]:
    """Per-repository figures over the records that started at or after `since`, by label."""
    groups: dict[str | None, list[Mapping]] = defaultdict(list)
    for record in records:
        if canonical.parse_rfc3339_utc(record["started"]) >= since:
            groups[record["repository"]].append(record)
    summaries = []
    for repository, runs in groups.items():
        waits = [record["waited_seconds"] for record in runs]
        holds = [record["held_seconds"] for record in runs if record["held_seconds"] is not None]
        summaries.append(Summary(
            repository, len(runs),
            statistics.median(holds) if holds else None,
            nearest_rank_p90(holds) if holds else None,
            float(sum(holds)), statistics.median(waits), nearest_rank_p90(waits)))
    return sorted(summaries, key=lambda summary: summary.repository or NO_REPOSITORY)


def report_line(summary: Summary, budget: int | None) -> str:
    """The report line of `summary`, marked when its hold median is strictly above `budget`."""
    def seconds(value: float | None) -> str:
        return "-" if value is None else f"{round(value)}s"
    line = (f"{summary.repository or NO_REPOSITORY} runs={summary.runs}"
            f" held_median={seconds(summary.held_median)} held_p90={seconds(summary.held_p90)}"
            f" held_total={seconds(summary.held_total)} waited_median={seconds(summary.waited_median)}"
            f" waited_p90={seconds(summary.waited_p90)}")
    if budget is not None and summary.held_median is not None and summary.held_median > budget:
        line += f" over budget {budget}s"
    return line
