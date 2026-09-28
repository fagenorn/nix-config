"""Durable-file primitives, the refusal hierarchy and the pure codecs shared by the
transaction modules (#205 D1, #206 D15): the `at`-timestamp codec (`format_at`,
`parse_at`) and the strict JSON object rule (`json_object_violation`) live here so that
every transaction module can import them without importing another's model.
"""

import calendar
import datetime
import fcntl
import json
import math
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from agent_tools.canonical import (
    reject_duplicate_keys, reject_nonfinite_literal, telemetry_digest)


class TransactionError(Exception):
    """Base of every refusal the transaction core raises."""


class StateInvalid(TransactionError):
    """A stored file, the layout, an operation's arguments, or a reused evidence or grant id
    fails the closed schema."""


class TransactionBusy(TransactionError):
    """A lock the call needs is held elsewhere."""


class TransitionRefused(TransactionError):
    """An illegal edge, a terminal source, or an ungrounded terminal."""


class CreationConflict(TransactionError):
    """The same creation key was requested with a different subject or concurrency key set."""


class UnknownTransaction(TransactionError):
    """No transaction with that id exists under this root."""


class FenceViolation(TransactionError):
    """A presented custody credential does not fence the write."""


class StaleCustody(FenceViolation):
    """No, stale or lapsed custody, or an unissued late-result credential."""


class CustodyMisbound(FenceViolation):
    """The presented subject path differs from the one the first acquisition bound."""


class GrantInvalid(FenceViolation):
    """An unknown grant, or a grant whose fence is not the current one."""


class LeaseUnavailable(TransactionError):
    """A concurrency key is live-held."""


class InvocationRefused(TransactionError):
    """An administrative-protocol refusal; `reason` names the rule. An admission refusal
    comes before any write or effect call; `attempt_in_flight` at an operation's second
    lock hold follows the call and records nothing from it (#206 D7, D19)."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class EffectResultInvalid(TransactionError):
    """An effect result outside the closed shapes; nothing from
    that call is recorded (#206 D11)."""


def format_at(ms: int) -> str:
    """Epoch milliseconds as UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`."""
    seconds = datetime.datetime.fromtimestamp(ms // 1000, tz=datetime.timezone.utc)
    return seconds.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms % 1000:03d}Z"


def parse_at(at: str) -> int:
    """Epoch milliseconds of a `YYYY-MM-DDTHH:MM:SS.mmmZ` stamp; `format_at`'s inverse."""
    seconds, millis = at[:-1].split(".")
    parsed = datetime.datetime.strptime(seconds, "%Y-%m-%dT%H:%M:%S")
    return calendar.timegm(parsed.timetuple()) * 1000 + int(millis)


def serialize(document: dict) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False) + "\n"


def _finite_float(literal: str) -> float:
    """`parse_float` hook: an overflowing literal such as `1e400` decodes to infinity."""
    value = float(literal)
    if not math.isfinite(value):
        raise ValueError(f"JSON number {literal} is not finite")
    return value


def strict_loads(text: str) -> Any:
    return json.loads(text, object_pairs_hook=reject_duplicate_keys,
                      parse_constant=reject_nonfinite_literal, parse_float=_finite_float)


def json_object_violation(value: Any) -> str | None:
    """How `value` fails to be a JSON object that survives a strict JSON round trip, or
    None: the rule a created `subject` and a late owner `result` share (D34)."""
    if type(value) is not dict:
        return "is not a JSON object"
    try:
        loaded = strict_loads(serialize(value))
    except (TypeError, ValueError) as error:
        return f"is not strict JSON ({error})"
    if loaded != value or telemetry_digest(loaded) != telemetry_digest(value):
        return "does not survive a strict JSON round trip"
    return None


def lstat_mode(path: Path) -> int | None:
    """The `lstat` mode of `path`, or None when nothing is there."""
    try:
        return os.lstat(path).st_mode
    except FileNotFoundError:
        return None


def read_json(path: Path) -> Any:
    """Strictly load one regular, non-symlinked JSON file, else StateInvalid."""
    mode = lstat_mode(path)
    if mode is None:
        raise StateInvalid(f"{path}: file is missing")
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise StateInvalid(f"{path}: not a regular file")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with open(descriptor, "rb") as handle:
            raw = handle.read()
    except OSError as error:
        raise StateInvalid(f"{path}: unreadable ({error.strerror})") from error
    try:
        return strict_loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise StateInvalid(f"{path}: not strict JSON ({error})") from error


def fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(directory: Path, path: Path, document: dict) -> None:
    """Replace `path` by a fsynced temporary sibling, then fsync `directory`."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix="." + path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            output.write(serialize(document))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        fsync_directory(directory)
    except BaseException as original_error:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                raise cleanup_error from original_error
        raise


def require_directory(path: Path, missing_ok: bool) -> bool:
    """Refuse a symlinked or non-directory `path` by `lstat`; report whether it exists."""
    mode = lstat_mode(path)
    if mode is None:
        if missing_ok:
            return False
        raise StateInvalid(f"{path}: directory is missing")
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise StateInvalid(f"{path}: not a directory")
    return True


def open_lock(path: Path) -> int:
    """Open (creating) a regular, non-symlinked lock file and take it non-blocking."""
    mode = lstat_mode(path)
    if mode is not None and (stat.S_ISLNK(mode) or not stat.S_ISREG(mode)):
        raise StateInvalid(f"{path}: lock is not a regular file")
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as error:
        raise StateInvalid(f"{path}: lock cannot be opened ({error.strerror})") from error
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        os.close(descriptor)
        raise TransactionBusy(f"{path}: lock is held elsewhere") from error
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor
