"""The effectful half of attempt run identity (#337 D27).

The store root beside `workflows`, the blocking mint lock, mint and lookup, the binding
check, the locked-read and unlocked-check transform under the caller's lock, and the direct
index probe. `workflow-state` keeps the ledger lock, the ledger read and commit, the delivery
chain and `validate_state`; it passes the last two to this module as callbacks.
"""

import fcntl
import os
import stat
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NamedTuple

from agent_tools.attempt_identity import (
    REFUSAL_REASONS, MigrationRefused, RunIdentity, RunPlan, classify, creation_arguments,
    direct_key, identity_of, legacy_identity, minted_plan, plan_migration, schema_refusal,
    subject_handle, subject_violation)
from agent_tools.transaction_core import TransactionError, TransactionStore
from agent_tools.transaction_storage import is_id

BOUND_SCHEMA_VERSION = 8


class StoreRefused(Exception):
    """A refusal by the attempt store; the message is what `workflow-state` prints."""


class LedgerRefused(StoreRefused):
    """A ledger that cannot be read as a run; `reason` is one of `REFUSAL_REASONS` (#337 D14)."""

    def __init__(self, reason: str, detail: str) -> None:
        if reason not in REFUSAL_REASONS:
            raise ValueError(f"unknown refusal reason {reason!r}")
        super().__init__(f"workflow state refused: {reason}: {detail}")
        self.reason = reason


class LockedRead(NamedTuple):
    """A ledger as a locked read yields it: bound to its run transaction at schema 8.

    `changed` is true when the stored file is still a schema-7 or older document, so the
    caller's commit is also the migration write.
    """

    state: dict
    identity: RunIdentity
    changed: bool


def _path_status(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _ensure_directory(path: Path, label: str) -> None:
    status = _path_status(path)
    if status is None:
        try:
            path.mkdir()
        except FileExistsError:
            pass
        status = _path_status(path)
    if status is None or stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
        raise StoreRefused(f"{label} must be a non-symlink directory")


def _require_regular_path(path: Path, label: str, *, allow_missing: bool) -> bool:
    status = _path_status(path)
    if status is None:
        if allow_missing:
            return False
        raise StoreRefused(f"{label} does not exist")
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode):
        raise StoreRefused(f"{label} must be a non-symlink regular file")
    return True


def _verify_open_file(path: Path, descriptor: int, label: str) -> None:
    path_info = path.lstat()
    file_info = os.fstat(descriptor)
    if (
        stat.S_ISLNK(path_info.st_mode)
        or not stat.S_ISREG(path_info.st_mode)
        or not stat.S_ISREG(file_info.st_mode)
        or (path_info.st_dev, path_info.st_ino) != (file_info.st_dev, file_info.st_ino)
    ):
        raise StoreRefused(f"{label} changed while being opened")


def _open_existing_regular(path: Path, label: str, flags: int) -> int:
    descriptor = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0))
    try:
        _verify_open_file(path, descriptor, label)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _open_stable_lock(lock_path: Path, label: str) -> int:
    if _require_regular_path(lock_path, label, allow_missing=True):
        return _open_existing_regular(lock_path, label, os.O_RDWR)
    try:
        descriptor = os.open(
            lock_path, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        descriptor = _open_existing_regular(lock_path, label, os.O_RDWR)
    try:
        _verify_open_file(lock_path, descriptor, label)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _ensure_gitignore(directory: Path, label: str) -> None:
    gitignore = directory / ".gitignore"
    _require_regular_path(gitignore, label, allow_missing=True)
    try:
        descriptor = os.open(
            gitignore, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o644)
    except FileExistsError:
        descriptor = _open_existing_regular(gitignore, label, os.O_RDONLY)
        with os.fdopen(descriptor, encoding="utf-8") as source:
            patterns = source.read().splitlines()
        if "*" not in patterns:
            raise StoreRefused(f"{label} must contain '*'")
        return
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        _verify_open_file(gitignore, output.fileno(), label)
        output.write("*\n")
        output.flush()
        os.fsync(output.fileno())
    _fsync_directory(directory)


def store_root(superpowers: Path) -> Path:
    """Where every attempt run's core transaction lives (a pure path, #337 D2)."""
    return superpowers / "attempt-transactions"


def ledger_store(state_path: Path) -> Path:
    """The store beside the `workflows` directory holding `<run>/state.json` (pure, D28)."""
    return store_root(state_path.parents[2])


def ensure_store(store: Path) -> Path:
    """Create the store root and its `*` `.gitignore`; write paths only."""
    _ensure_directory(store.parent, ".superpowers")
    _ensure_directory(store, "attempt transactions")
    _ensure_gitignore(store, "attempt transactions .gitignore")
    return store


def _existing_store(store: Path) -> Path | None:
    """`store` when it is a real directory, None when absent; creates nothing."""
    status = _path_status(store)
    if status is None:
        return None
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
        raise StoreRefused("attempt transactions must be a non-symlink directory")
    return store


def creation_key_plan(caller_key: str) -> RunPlan:
    """The plan of the orchestrated run a caller's creation key names."""
    try:
        return minted_plan(identity=RunIdentity("orchestrated", None, None),
                           prior_run=None, caller_key=caller_key)
    except ValueError as error:
        raise StoreRefused("invalid creation key") from error


def mint_run(store: Path, plan: RunPlan) -> str:
    """The id of `plan`'s run transaction, created if its creation key is new (#337 D9).

    Every `create` runs under the exclusive mint lock, which is taken after any ledger
    `state.lock` and before the core's own locks, and never while a `state.lock` is
    requested.
    """
    ensure_store(store)
    descriptor = _open_stable_lock(store / "attempt-runs.lock", "attempt mint lock")
    with os.fdopen(descriptor, "r+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            transaction = TransactionStore(store).create(
                plan.creation_key, plan.subject_json(), **creation_arguments(plan))
        except TransactionError as error:
            raise StoreRefused(f"run transaction store: {error}") from error
    return transaction.transaction_id


def lookup_run(store: Path, creation_key: str) -> str | None:
    """The run id `creation_key` names, or None; never creates the store root."""
    if _existing_store(store) is None:
        return None
    try:
        return TransactionStore(store).lookup(creation_key)
    except TransactionError as error:
        raise StoreRefused(f"run transaction store: {error}") from error


def bound_identity(store: Path, state: dict[str, Any], run_id: str) -> RunIdentity:
    """The identity of the run transaction a schema-8 `state` names, read without a lock.

    Refuses a missing store, an unknown or invalid transaction, a subject that is not the
    closed attempt-run subject, and a transaction whose handle is not `run_id`. Creates
    nothing.
    """
    transaction_id = state.get("transaction_id") if isinstance(state, dict) else None
    if not is_id(transaction_id):
        raise StoreRefused("invalid transaction identity")
    if _existing_store(store) is None:
        raise StoreRefused("the run transaction store does not exist")
    try:
        subject = TransactionStore(store).load(transaction_id).subject
    except TransactionError as error:
        raise StoreRefused(f"run transaction store: {error}") from error
    violation = subject_violation(subject)
    if violation is not None:
        raise StoreRefused(f"run transaction {transaction_id}: {violation}")
    if subject_handle(subject, transaction_id) != run_id:
        raise StoreRefused("workflow state run identity does not match its run transaction")
    return identity_of(subject)


def require_known_schema(document: Any) -> None:
    if schema_refusal(document) is not None:
        version = document.get("schema_version") if isinstance(document, dict) else None
        raise LedgerRefused(
            "unknown_schema", f"unsupported workflow state schema version: {version!r}")


def plan_legacy_run(document: dict[str, Any]) -> RunPlan:
    try:
        return plan_migration(document)
    except MigrationRefused as error:
        raise LedgerRefused(error.reason, str(error).partition(": ")[2]) from error


def _upgraded(document: Any, *, run_id: str, upgrade: Callable[..., dict]) -> tuple[
        dict[str, Any], RunPlan]:
    """A schema 1-7 document as a validated schema-7 candidate with its run plan.

    `upgrade` runs the migration chain and the schema-7 validation on a detached copy, then
    `plan_migration`; nothing is written and no store is touched.
    """
    try:
        identity = legacy_identity(run_id)
    except MigrationRefused:
        identity = RunIdentity("orchestrated", None, None)
    candidate = upgrade(document, run_id=run_id, identity=identity)
    return candidate, plan_legacy_run(candidate)


def locked_read(state_path: Path, document: Any, *, run_id: str, upgrade: Callable[..., dict],
                validate: Callable[..., dict]) -> LockedRead:
    """A ledger read under its `state.lock`, bound to a run transaction.

    A schema-8 `document` is bound to the transaction it names. An older one is upgraded,
    its transaction minted (the caller holds the ledger lock, the mint lock nests inside it,
    #337 D9) and the candidate returned as schema 8 with `changed` set.
    """
    store = ledger_store(state_path)
    require_known_schema(document)
    if document["schema_version"] == BOUND_SCHEMA_VERSION:
        identity = bound_identity(store, document, run_id)
        return LockedRead(validate(document, run_id=run_id, identity=identity), identity, False)
    candidate, plan = _upgraded(document, run_id=run_id, upgrade=upgrade)
    candidate["transaction_id"] = mint_run(store, plan)
    candidate["schema_version"] = BOUND_SCHEMA_VERSION
    identity = identity_of(plan.subject)
    return LockedRead(validate(candidate, run_id=run_id, identity=identity), identity, True)


def check_unlocked(state_path: Path, document: Any, *, run_id: str, upgrade: Callable[..., dict],
                   validate: Callable[..., dict]) -> None:
    """Check a ledger without a lock or a write: schema 8 against its run transaction, an
    older one through `upgrade` and `plan_migration`. No store or directory is created."""
    require_known_schema(document)
    if document["schema_version"] == BOUND_SCHEMA_VERSION:
        identity = bound_identity(ledger_store(state_path), document, run_id)
        validate(document, run_id=run_id, identity=identity)
        return
    _upgraded(document, run_id=run_id, upgrade=upgrade)


def indexed_direct_runs(store: Path, workflows_dir: Path, issue: int, *,
                        after: int) -> Iterator[tuple[int, str, Path]]:
    """The minted direct runs of `issue` past sequence `after`, in order, found by index.

    Lazy: the caller locks and checks each run before the next lookup.
    """
    sequence = after
    while True:
        sequence += 1
        run_id = lookup_run(store, direct_key(issue, sequence))
        if run_id is None:
            return
        if classify(run_id) != "core":
            raise StoreRefused("direct run index entry is not a run transaction")
        run_dir = workflows_dir / run_id
        status = _path_status(run_dir)
        if status is None:
            return
        if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
            raise StoreRefused("direct run entry must be a non-symlink directory")
        if _path_status(run_dir / "state.json") is None:
            return
        yield sequence, run_id, run_dir
