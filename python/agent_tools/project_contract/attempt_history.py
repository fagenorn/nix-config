"""A schema-3 project's attempt budget, derived from its recorded delivered attempts.

An attempt is one try at delivering an issue, from the claim that starts it to the
end of that claim. A delivered attempt ended with its change merged into the
integration branch; its duration runs from the claim's creation to that merge. An
attempt that stopped or still runs has no merge and is not delivered.

The rule (ADR-project-contract-016): take the `WINDOW` (20) delivered attempts with the latest merge; the
budget is 1.5 times the nearest-rank 90th percentile of their durations, in whole
minutes rounded up and at least 1. With fewer than `WINDOW` delivered attempts the
budget is `FALLBACK_MINUTES` (240). The nearest rank of `n` durations is the
`ceil(9n/10)`th smallest.

The history (ADR-project-contract-016) lives in one file beside the repository's git config, in the common git
directory a linked worktree shares: `<git dir>/agent-platform/attempt-history.json`.
Its wire format is exactly this object, written with `json.dumps(indent=1,
sort_keys=True)` and a final newline:

    {"version": 1, "repo": "owner/name", "recorded_at": "2026-11-22T12:00:00Z",
     "attempts": [
       {"issue": 1458, "pull": 1612, "claimed_at": "2026-11-21T09:00:00Z",
        "merged_at": "2026-11-21T12:30:00Z"},
       {"issue": 1458, "pull": null, "claimed_at": "2026-11-20T09:00:00Z",
        "merged_at": null}]}

Every timestamp is `%Y-%m-%dT%H:%M:%SZ` in UTC and nothing else. `pull` is null
exactly when `merged_at` is, and `merged_at` is not before `claimed_at`. Any other
shape is refused as `invalid`; a well-shaped file of another repository is
`other_repository`.

`read` never raises and never writes. It returns a `Budget` whose `basis` says
where the number came from: `{"source": "history", "delivered", "percentile_90_seconds",
"recorded_at"}`, or `{"source": "fallback", "reason"}` with the reason `no_history`
(no git directory or no file), `unreadable` (not a regular file, cannot be read, not
UTF-8, or not strict JSON: a duplicate key, `NaN`, nesting past the limit), `invalid`
or `other_repository`, or the reason `too_few` with the `delivered` count.

The module reads files only through `read_regular_file`, which opens nonblocking so a
FIFO is refused instead of waited on; it writes only in `write_history`, which the
recording command alone calls; it starts no child process, opens no connection and
imports no resolver (the resolver imports this module).
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, NamedTuple, Sequence

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.project_contract import derived_values
from agent_tools.project_contract.agent_platform import read_regular_file

WINDOW = 20
FALLBACK_MINUTES = 240
HISTORY_VERSION = 1
HISTORY_DIR = "agent-platform"
HISTORY_FILE = "attempt-history.json"

STAMP = "%Y-%m-%dT%H:%M:%SZ"
DOCUMENT_MEMBERS = {"version", "repo", "recorded_at", "attempts"}
ATTEMPT_MEMBERS = {"issue", "pull", "claimed_at", "merged_at"}


class Attempt(NamedTuple):
    issue: int
    pull: int | None
    claimed_at: datetime
    merged_at: datetime | None

    def seconds(self) -> int | None:
        """Whole seconds from the claim to the merge; None for an attempt not delivered."""
        if self.merged_at is None:
            return None
        return int((self.merged_at - self.claimed_at).total_seconds())


class Budget(NamedTuple):
    minutes: int
    basis: dict
    used: tuple[Attempt, ...]


class HistoryRefused(Exception):
    """A history file that parses but is not this repository's well-shaped history."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(STAMP)


def instant(text: object) -> datetime:
    """The aware UTC moment of exactly the `STAMP` form; anything else is a `ValueError`."""
    if not isinstance(text, str):
        raise ValueError("timestamp must be a string")
    moment = datetime.strptime(text, STAMP).replace(tzinfo=timezone.utc)
    if stamp(moment) != text:
        raise ValueError("timestamp is not in the exact form")
    return moment


def percentile_90_seconds(seconds: Sequence[int]) -> int:
    """The nearest-rank 90th percentile: the `ceil(9n/10)`th smallest of `n` values."""
    ordered = sorted(seconds)
    return ordered[(9 * len(ordered) + 9) // 10 - 1]


def fallback(reason: str, **extra: int) -> dict:
    return {"source": "fallback", "reason": reason, **extra}


def budget(attempts: Iterable[Attempt], recorded_at: datetime) -> Budget:
    done = sorted(
        (a for a in attempts if a.merged_at is not None),
        key=lambda a: (a.merged_at, a.claimed_at),
        reverse=True,
    )
    used = tuple(done[:WINDOW])
    if len(used) < WINDOW:
        return Budget(FALLBACK_MINUTES, fallback("too_few", delivered=len(used)), used)
    percentile = percentile_90_seconds([a.seconds() for a in used])
    basis = {
        "source": "history",
        "delivered": len(used),
        "percentile_90_seconds": percentile,
        "recorded_at": stamp(recorded_at),
    }
    return Budget(max(1, (3 * percentile + 119) // 120), basis, used)


def history_path(root: Path) -> Path:
    """The history file of the repository at `root`; `Underivable` when it has no git directory."""
    return derived_values.git_config_path(root).parent / HISTORY_DIR / HISTORY_FILE


def positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def parse_attempt(entry: object) -> Attempt:
    if not isinstance(entry, dict) or set(entry) != ATTEMPT_MEMBERS:
        raise HistoryRefused("invalid")
    issue, pull = entry["issue"], entry["pull"]
    if not positive_int(issue) or not (pull is None or positive_int(pull)):
        raise HistoryRefused("invalid")
    claimed_at = instant(entry["claimed_at"])
    merged_at = None if entry["merged_at"] is None else instant(entry["merged_at"])
    if (pull is None) != (merged_at is None):
        raise HistoryRefused("invalid")
    if merged_at is not None and merged_at < claimed_at:
        raise HistoryRefused("invalid")
    return Attempt(issue, pull, claimed_at, merged_at)


def parse_history(document: object, slug: str | None) -> tuple[datetime, list[Attempt]]:
    """The recording moment and attempts of a well-shaped history of repository `slug`."""
    try:
        if not isinstance(document, dict) or set(document) != DOCUMENT_MEMBERS:
            raise HistoryRefused("invalid")
        if type(document["version"]) is not int or document["version"] != HISTORY_VERSION:
            raise HistoryRefused("invalid")
        if not isinstance(document["repo"], str) or not isinstance(document["attempts"], list):
            raise HistoryRefused("invalid")
        recorded_at = instant(document["recorded_at"])
        attempts = [parse_attempt(entry) for entry in document["attempts"]]
    except (ValueError, TypeError):
        raise HistoryRefused("invalid") from None
    if slug is None or document["repo"] != slug:
        raise HistoryRefused("other_repository")
    return recorded_at, attempts


def read(root: Path, slug: str | None) -> Budget:
    """The budget the repository's history gives, or the fallback with its reason; never raises."""

    def refused(reason: str) -> Budget:
        return Budget(FALLBACK_MINUTES, fallback(reason), ())

    try:
        path = history_path(root)
    except derived_values.Underivable:
        return refused("no_history")
    try:
        data = read_regular_file(path)
    except (FileNotFoundError, NotADirectoryError):
        return refused("no_history")
    except OSError:
        return refused("unreadable")
    try:
        document = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite_literal,
        )
    except (ValueError, RecursionError):
        return refused("unreadable")
    try:
        recorded_at, attempts = parse_history(document, slug)
    except HistoryRefused as error:
        return refused(error.reason)
    return budget(attempts, recorded_at)


def render_history(slug: str, recorded_at: datetime, attempts: Sequence[Attempt]) -> str:
    document = {
        "version": HISTORY_VERSION,
        "repo": slug,
        "recorded_at": stamp(recorded_at),
        "attempts": [
            {
                "issue": a.issue,
                "pull": a.pull,
                "claimed_at": stamp(a.claimed_at),
                "merged_at": None if a.merged_at is None else stamp(a.merged_at),
            }
            for a in attempts
        ],
    }
    return json.dumps(document, indent=1, sort_keys=True) + "\n"


def write_history(root: Path, text: str) -> Path:
    """Replace the history file with `text` through a sibling temporary file; returns its path."""
    path = history_path(root)
    path.parent.mkdir(exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".attempt-history-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return path
