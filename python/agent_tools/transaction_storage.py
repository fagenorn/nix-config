"""Durable-file primitives and the refusal hierarchy shared by the transaction modules (#205 D1)."""

import fcntl
import json
import math
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal


class TransactionError(Exception):
    """Base of every refusal the transaction core raises."""


class StateInvalid(TransactionError):
    """A stored file, the layout, or a create argument fails the closed schema."""


class TransactionBusy(TransactionError):
    """A lock the call needs is held elsewhere."""


class TransitionRefused(TransactionError):
    """An illegal edge, a terminal source, or an ungrounded terminal."""


class CreationConflict(TransactionError):
    """The same creation key was requested with a different subject."""


class UnknownTransaction(TransactionError):
    """No transaction with that id exists under this root."""


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
