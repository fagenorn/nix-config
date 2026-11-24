"""The interrupted-run back-off, its streak store and its log line for `verify-pending run`.

A check run that a signal ended says nothing about the check, so the runner re-runs it once after a
short wait instead of recording an outcome. This module owns the pieces of that rule that need the
host: the back-off curve, the per-check streak of interruptions kept in a private file under the
runner's state directory (so a later pass knows an earlier pass was interrupted at the same check),
the one log line a person or a parser reads, and the pass interval the next-run time is computed from.
The host clock lives here and not in `verify_run`: that module reads time only from the forge
(`Context.now()`), and a wait the host performs, or a log line the host writes, is the host's time.
The runner catches SIGTERM and SIGHUP for the length of a run, so a sweep of the account's processes is
recorded as interrupted runs instead of ending the runner; SIGINT and SIGKILL still end it.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator

BACKOFF_BASE_SECONDS = 60
BACKOFF_CEILING_SECONDS = 300
PASS_INTERVAL_SECONDS = 900
SURVIVED = (signal.SIGTERM, signal.SIGHUP)
STORE = Path(".agents/state/verify-pending/interrupted.json")

_STAMP = "%Y-%m-%dT%H:%M:%SZ"
_LINE = re.compile(
    r"^(\S+) interrupted host=(\S+) repo=(\S+) issue=(\d+) check=(\d+) ac=(\S+) signal=(\S+) next=(\S+) "
    r"then=(rerun|held)$"
)


def backoff_seconds(streak: int) -> int:
    """The wait after `streak` earlier interruptions: 60, 120, 240, then 300 for every later one."""
    return min(BACKOFF_BASE_SECONDS * 2**streak, BACKOFF_CEILING_SECONDS)


def signal_name(number: int) -> str:
    """The signal's name, or its number when it is no known signal."""
    try:
        return signal.Signals(number).name
    except ValueError:
        return str(number)


def key(repo: str, issue: int, block: str, check: int) -> str:
    """The streak key of one check of one block version of one issue."""
    return f"{repo}#{issue}/{block}/{check}"


def stamp(at: datetime) -> str:
    """`at` in UTC in the runner log's stamp format."""
    return at.astimezone(timezone.utc).strftime(_STAMP)


def format_line(at, *, host, repo, issue, check, ac, signal, next_at, then) -> str:
    """The one log line of an interruption; `then` is `rerun` or `held`."""
    return (
        f"{stamp(at)} interrupted host={host} repo={repo} issue={issue} check={check} ac={ac} "
        f"signal={signal_name(signal)} next={stamp(next_at)} then={then}"
    )


def parse_line(text: str) -> dict | None:
    """The fields `format_line` wrote, as text where it wrote text, or None for any other line."""
    found = _LINE.match(text)
    if found is None:
        return None
    at, host, repo, issue, check, ac, sig, nxt, then = found.groups()
    return {
        "at": at, "host": host, "repo": repo, "issue": int(issue), "check": int(check),
        "ac": ac, "signal": sig, "next": nxt, "then": then,
    }


@contextlib.contextmanager
def survive() -> Iterator[list[int]]:
    """Catch `SURVIVED` for the length of the block, yielding the signal numbers received, in order.

    The handler only records, so a blocked wait or child read resumes. Main thread only: `signal.signal`
    refuses any other. Nothing is ignored (an ignored signal would stay ignored in every check child),
    and the previous handlers return on leaving.
    """
    received: list[int] = []
    saved = {number: signal.getsignal(number) for number in SURVIVED}

    def record(number, frame) -> None:
        received.append(number)

    for number in SURVIVED:
        signal.signal(number, record)
    try:
        yield received
    finally:
        for number, handler in saved.items():
            signal.signal(number, handler)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_stderr(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _counted(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _read(path: Path) -> dict[str, int]:
    """The streaks stored at `path`; a missing or damaged store, or a bad entry, reads as none."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    streaks = data.get("streaks") if isinstance(data, dict) else None
    if not isinstance(streaks, dict):
        return {}
    return {name: value for name, value in streaks.items() if _counted(value)}


@dataclass
class Interruptions:
    path: Path
    clock: Callable[[], datetime] = utc_now
    sleep: Callable[[float], None] = time.sleep
    log: Callable[[str], None] = to_stderr
    started: datetime | None = None

    def __post_init__(self) -> None:
        if self.started is None:
            self.started = self.clock()

    @classmethod
    def at_home(cls, **seams) -> "Interruptions":
        return cls(Path.home() / STORE, **seams)

    def streak(self, key: str) -> int:
        return _read(self.path).get(key, 0)

    def hold(self, key: str) -> int:
        """Count one more interruption of `key`, persist it and return the new streak."""
        return self._change(key, lambda streaks: streaks.get(key, 0) + 1)

    def clear(self, key: str) -> None:
        """End the streak of `key`; touches no file when there is no store or no such streak."""
        if self.path.exists():
            self._change(key, lambda streaks: 0)

    def backoff(self, key: str) -> int:
        return backoff_seconds(self.streak(key))

    def next_pass(self) -> datetime:
        """When the schedule starts the next pass: one interval after this run began, never in the past."""
        return max(self.started + timedelta(seconds=PASS_INTERVAL_SECONDS), self.clock())

    def note(self, *, host, repo, issue, check, ac, signal, next_at, then) -> None:
        self.log(format_line(
            self.clock(), host=host, repo=repo, issue=issue, check=check, ac=ac,
            signal=signal, next_at=next_at, then=then,
        ))

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(f"{self.path}.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def _change(self, key: str, update: Callable[[dict[str, int]], int]) -> int:
        """Re-read under the lock, set `key` to `update(streaks)` (0 drops it) and replace the file."""
        with self._locked():
            streaks = _read(self.path)
            value = update(streaks)
            if value == 0 and key not in streaks:
                return 0
            if value == 0:
                del streaks[key]
            else:
                streaks[key] = value
            self._write(streaks)
            return value

    def _write(self, streaks: dict[str, int]) -> None:
        tmp = Path(f"{self.path}.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump({"v": 1, "streaks": streaks}, handle)
        os.replace(tmp, self.path)
