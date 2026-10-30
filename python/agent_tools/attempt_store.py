"""The effectful half of attempt run identity and attempt custody (#337 D27, #338).

The store root beside `workflows`, the blocking store lock, mint and lookup, the binding
check, the locked-read and unlocked-check transform under the caller's lock, and the direct
index probe. It also keeps the issue hold pointers that lead from an issue to the
orchestrated runs holding it (`settle_holds`, `hold_runs`; issue 475). From schema 9 it also
applies `agent_tools.attempt_custody`'s settle plan to `TransactionStore` under the store
lock: `settle_custody` before a ledger write, `seal_custody` after it, and `pending_seals` to
find a seal a crash left undone. From schema 10 the plan covers every delivery remainder as
well as every attempt, records a held owner claim on its launch's span, and wakes a
`host_capacity` suspension; `launch_views` reads, without a lock, what the store says of each
current launch for a control sweep's occupancy and capacity gate.
`workflow-state` keeps the ledger lock, the ledger read and commit, the delivery chain and
`validate_state`; it passes the last two to this module as callbacks.
"""

import contextlib
import copy
import fcntl
import json
import os
import stat
import tempfile
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, NamedTuple

from agent_tools import attempt_custody as custody_rules
from agent_tools import attempt_delivery as delivery_rules
from agent_tools.attempt_identity import (
    LEGACY_DIALECTS, REFUSAL_REASONS, REPORT_ROW_FIELDS, MigrationRefused, RunIdentity,
    RunPlan, classify, creation_arguments, direct_key, hold_key, hold_plan, hold_violation,
    identity_of, legacy_alias, legacy_identity, legacy_key, minted_plan, plan_migration,
    report, schema_refusal, subject_handle, subject_violation)
from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_core import TransactionError, TransactionStore
from agent_tools.transaction_history import TERMINALS, Transaction
from agent_tools.transaction_storage import (
    LeaseUnavailable, ProofRefused, UnknownTransaction, is_id)

BOUND_SCHEMA_VERSION = 8  # bound to its run; custody not yet in the core
CUSTODY_SCHEMA_VERSION = 9  # attempt custody is held in the core
CORE_STATE_SCHEMA_VERSION = 10  # claims and remainder custody are held in the core too


class StoreRefused(Exception):
    """A refusal by the attempt store; the message is what `workflow-state` prints."""


class StoreFault(StoreRefused):
    """The store itself cannot be read; never a refusal of one ledger (#337 D37)."""


class LedgerRefused(StoreRefused):
    """A ledger that cannot be read as a run; `reason` is one of `REFUSAL_REASONS` (#337 D14)."""

    def __init__(self, reason: str, detail: str) -> None:
        if reason not in REFUSAL_REASONS:
            raise ValueError(f"unknown refusal reason {reason!r}")
        super().__init__(f"workflow state refused: {reason}: {detail}")
        self.reason = reason


class FencingRefused(StoreRefused):
    """A write the custody fence refuses; `reason` is one of `FENCING_REASONS` (#338 D13)."""

    def __init__(self, reason: str, detail: str) -> None:
        if reason not in custody_rules.FENCING_REASONS:
            raise ValueError(f"unknown fencing reason {reason!r}")
        super().__init__(f"fencing violation: {reason}: {detail}")
        self.reason = reason


class OwnerReport(NamedTuple):
    """An owner result a write submits: the `report` of attempt `attempt` of issue `issue`."""

    issue: int
    attempt: int
    report: dict


class LockedRead(NamedTuple):
    """A ledger as a locked read yields it: bound to its run transaction at schema 10.

    `changed` is true when the stored file is still a schema-9 or older document, so the
    caller's commit is also the migration write. `bound_launches` is then, for a document
    stored below schema 9, the 8 -> 9 plan, `(issue, attempt) -> launch count` for each
    attempt that was live; otherwise `{}`. `bound_remainders` is, for a document stored below
    schema 10, the same plan over its live delivery remainders, `(issue, remainder) -> launch
    count`; otherwise `{}`.
    """

    state: dict
    identity: RunIdentity
    changed: bool
    bound_launches: dict[tuple[int, int], int]
    bound_remainders: dict[tuple[int, int], int]


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


def _publish_gitignore(directory: Path, gitignore: Path) -> None:
    """Publish a complete `*` `.gitignore` by linking a fsynced temporary sibling into place,
    so a concurrent reader sees no file or the whole file; a lost race keeps the winner's."""
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                     prefix=".gitignore.", suffix=".tmp") as output:
        os.fchmod(output.fileno(), 0o644)
        output.write("*\n")
        output.flush()
        os.fsync(output.fileno())
        try:
            os.link(output.name, gitignore)
        except FileExistsError:
            pass
    _fsync_directory(directory)


def _ensure_gitignore(directory: Path, label: str) -> None:
    gitignore = directory / ".gitignore"
    if not _require_regular_path(gitignore, label, allow_missing=True):
        _publish_gitignore(directory, gitignore)
    descriptor = _open_existing_regular(gitignore, label, os.O_RDONLY)
    with os.fdopen(descriptor, encoding="utf-8") as source:
        patterns = source.read().splitlines()
    if "*" not in patterns:
        raise StoreRefused(f"{label} must contain '*'")


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
        raise StoreFault("attempt transactions must be a non-symlink directory")
    return store


def creation_key_plan(caller_key: str) -> RunPlan:
    """The plan of the orchestrated run a caller's creation key names."""
    try:
        return minted_plan(identity=RunIdentity("orchestrated", None, None),
                           prior_run=None, caller_key=caller_key)
    except ValueError as error:
        raise StoreRefused("invalid creation key") from error


@contextlib.contextmanager
def store_lock(store: Path) -> Iterator[None]:
    """Hold the blocking exclusive lock `<store>/attempt-runs.lock`, creating the store first.

    Every core write `workflow-state` makes runs under it (#338 D15). It is taken after any
    ledger `state.lock` and before the core's own locks, never while a `state.lock` is
    requested, and never while it is already held.
    """
    ensure_store(store)
    descriptor = _open_stable_lock(store / "attempt-runs.lock", "attempt mint lock")
    with os.fdopen(descriptor, "r+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def mint_run(store: Path, plan: RunPlan) -> str:
    """The id of `plan`'s run transaction, created if its creation key is new (#337 D9).

    The `create` runs under the store lock.
    """
    with store_lock(store):
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
        raise StoreFault(f"run transaction store: {error}") from error


def bound_identity(store: Path, state: dict[str, Any], run_id: str) -> RunIdentity:
    """The identity of the run transaction a schema-8 or schema-9 `state` names, read
    without a lock.

    Refuses a missing store, an unknown or invalid transaction, a subject that is not the
    closed attempt-run subject, a transaction whose handle is not `run_id`, and a `state`
    whose `prior_run` is not its subject's. Creates nothing.
    """
    transaction_id = state.get("transaction_id") if isinstance(state, dict) else None
    if not is_id(transaction_id):
        raise StoreRefused("invalid transaction identity")
    if _existing_store(store) is None:
        raise StoreRefused("the run transaction store does not exist")
    try:
        subject = TransactionStore(store).load(transaction_id).subject
    except UnknownTransaction as error:
        raise StoreRefused(f"run transaction store: {error}") from error
    except TransactionError as error:
        raise StoreFault(f"run transaction store: {error}") from error
    violation = subject_violation(subject)
    if violation is not None:
        raise StoreRefused(f"run transaction {transaction_id}: {violation}")
    if subject_handle(subject, transaction_id) != run_id:
        raise StoreRefused("workflow state run identity does not match its run transaction")
    if state.get("prior_run") != subject["prior_run"]:
        raise StoreRefused("workflow state prior_run does not match its run transaction")
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


def plan_custody(candidate: dict[str, Any]) -> dict[tuple[int, int], int]:
    """The 8 -> 9 plan of a validated `candidate`, or a `LedgerRefused` for a refused ledger."""
    try:
        return custody_rules.plan_custody_migration(candidate)
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


def _schema_ten(document: dict[str, Any], identity: RunIdentity, *, run_id: str,
                validate: Callable[..., dict]) -> tuple[dict[str, Any], dict, dict]:
    """A schema-8 or schema-9 `document` as the validated schema-10 candidate with its bind
    plans: the 8 -> 9 launch plan (empty for schema 9) and the remainder plan."""
    candidate = copy.deepcopy(document)
    candidate["schema_version"] = CORE_STATE_SCHEMA_VERSION
    validated = validate(candidate, run_id=run_id, identity=identity)
    launches = plan_custody(validated) if document["schema_version"] == BOUND_SCHEMA_VERSION \
        else {}
    return validated, launches, delivery_rules.plan_remainder_migration(validated)


def locked_read(state_path: Path, document: Any, *, run_id: str, upgrade: Callable[..., dict],
                validate: Callable[..., dict]) -> LockedRead:
    """A ledger read under its `state.lock`, bound to a run transaction.

    A schema-10 `document` is bound to the transaction it names. A schema-8 or schema-9 one
    is bound the same way, copied as schema 10 and planned (`bound_launches`,
    `bound_remainders`), with `changed` set. An older one is upgraded, planned, its
    transaction minted (the caller holds the ledger lock, the store lock nests inside it,
    #337 D9) and the candidate returned as schema 10 with `changed` set. A refused ledger
    mints nothing.
    """
    store = ledger_store(state_path)
    require_known_schema(document)
    version = document["schema_version"]
    if version == CORE_STATE_SCHEMA_VERSION:
        identity = bound_identity(store, document, run_id)
        return LockedRead(validate(document, run_id=run_id, identity=identity), identity,
                          False, {}, {})
    if version in (BOUND_SCHEMA_VERSION, CUSTODY_SCHEMA_VERSION):
        identity = bound_identity(store, document, run_id)
        validated, launches, remainders = _schema_ten(
            document, identity, run_id=run_id, validate=validate)
        return LockedRead(validated, identity, True, launches, remainders)
    candidate, plan = _upgraded(document, run_id=run_id, upgrade=upgrade)
    launches = plan_custody(candidate)
    candidate["transaction_id"] = mint_run(store, plan)
    candidate["schema_version"] = CORE_STATE_SCHEMA_VERSION
    identity = identity_of(plan.subject)
    validated = validate(candidate, run_id=run_id, identity=identity)
    return LockedRead(validated, identity, True, launches,
                      delivery_rules.plan_remainder_migration(validated))


def check_unlocked(state_path: Path, document: Any, *, run_id: str, upgrade: Callable[..., dict],
                   validate: Callable[..., dict]) -> dict[str, Any]:
    """Check a ledger without a lock or a write and return it as checked: schema 10 against
    its run transaction, schema 8 or 9 the same way and as the schema-10 candidate its next
    write binds, an older one through `upgrade`, `plan_migration` and `plan_custody` as its
    schema-7 candidate. No store or directory is created."""
    require_known_schema(document)
    version = document["schema_version"]
    if version == CORE_STATE_SCHEMA_VERSION:
        identity = bound_identity(ledger_store(state_path), document, run_id)
        return validate(document, run_id=run_id, identity=identity)
    if version in (BOUND_SCHEMA_VERSION, CUSTODY_SCHEMA_VERSION):
        identity = bound_identity(ledger_store(state_path), document, run_id)
        return _schema_ten(document, identity, run_id=run_id, validate=validate)[0]
    candidate, _ = _upgraded(document, run_id=run_id, upgrade=upgrade)
    plan_custody(candidate)
    return candidate


class PendingSeal(NamedTuple):
    """A seal not yet applied: the custody transaction to seal and the seal's reason.

    `reap` is the reason of the reap `seal_custody` applies first, for a seal whose span
    lapsed after its ledger write; None when the seal has no such prerequisite. A `succeeded`
    seal carries the `issue` whose delivery receipt it cites and the `executor` of its span.
    """

    transaction_id: str
    reason: str
    reap: str | None = None
    issue: int | None = None
    executor: str | None = None


class _Planned(NamedTuple):
    """One record's settle plan with what the write phase needs to apply it: the attempt or
    delivery `remainder` record of `issue`, whether it is the `latest` record of its issue
    (no attempt or remainder follows it), its custody `transaction` and the `operations`."""

    issue: int
    record: dict
    remainder: bool
    latest: bool
    transaction: Transaction | None
    operations: tuple[custody_rules.Operation, ...]

    @property
    def ordinal(self) -> int:
        return self.record["remainder" if self.remainder else "attempt"]

    @property
    def label(self) -> str:
        return f"remainder {self.ordinal}" if self.remainder else f"attempt {self.ordinal}"

    def key(self, run: str) -> str:
        return _custody_key(run, self.issue, self.ordinal, remainder=self.remainder)

    def predecessor_key(self, run: str) -> str | None:
        """The creation key of the custody transaction a new subject's `prior` names: the
        previous attempt's, or for remainder 1 the source attempt's and for a later
        remainder the previous remainder's. None for attempt 1."""
        if not self.remainder:
            return None if self.ordinal == 1 else _custody_key(
                run, self.issue, self.ordinal - 1, remainder=False)
        if self.ordinal == 1:
            return _custody_key(run, self.issue, self.record["source_attempt"], remainder=False)
        return _custody_key(run, self.issue, self.ordinal - 1, remainder=True)


def _custody_key(run: str, issue: int, ordinal: int, *, remainder: bool) -> str:
    """The creation key of an attempt's or a delivery remainder's custody transaction."""
    make = delivery_rules.remainder_key if remainder else custody_rules.creation_key
    return make(run, issue, ordinal)


def _records(issue_state: Mapping) -> list[tuple[dict, bool]]:
    """An issue's records in custody order, each with whether it is a delivery remainder:
    every attempt, then every remainder."""
    return [*((record, False) for record in issue_state["attempts"]),
            *((record, True) for record in issue_state["delivery_remainders"])]


def _custody_under(store: Path, creation_key: str) -> Transaction | None:
    if _existing_store(store) is None:
        return None
    try:
        core = TransactionStore(store)
        identity = core.lookup(creation_key)
        return None if identity is None else core.load(identity)
    except TransactionError as error:
        raise StoreFault(f"custody store: {error}") from error


def custody_of(store: Path, run: str, issue: int, attempt: int) -> Transaction | None:
    """The custody transaction of `attempt` of `issue` in `run`, read without a lock.

    None when the store directory or the creation key's index entry is missing; creates
    nothing. A core error is a `StoreFault`.
    """
    return _custody_under(store, custody_rules.creation_key(run, issue, attempt))


def remainder_custody_of(store: Path, run: str, issue: int, remainder: int) -> Transaction | None:
    """The custody transaction of delivery `remainder` of `issue` in `run`: `custody_of`'s
    twin, read the same way."""
    return _custody_under(store, delivery_rules.remainder_key(run, issue, remainder))


class LaunchView(NamedTuple):
    """The store's view of one record's current launch. `open`: the transaction's open span
    is that launch's and has not lapsed. `roles`: the claim entry's role set, None when not
    open or unclaimed. `parked`: the transaction is `attention_required`."""

    open: bool
    roles: dict[str, int] | None
    parked: bool


def launch_views(store: Path, state: dict, *, now_ms: int) -> dict[str, LaunchView]:
    """A view per current launch of each issue's last attempt and last remainder that has a
    custody transaction, keyed by launch id. Lock-free and read-only; a core error is a
    `StoreFault`."""
    views = {}
    for key in sorted(state["issues"], key=int):
        issue, issue_state = int(key), state["issues"][key]
        for records, remainder in ((issue_state["attempts"], False),
                                   (issue_state["delivery_remainders"], True)):
            if not records:
                continue
            record = records[-1]
            ordinal = record["remainder" if remainder else "attempt"]
            read = remainder_custody_of if remainder else custody_of
            transaction = read(store, state["transaction_id"], issue, ordinal)
            if transaction is None:
                continue
            launch = _current_launch(issue, record, remainder=remainder)
            span = transaction.custody
            lapsed = span is None or custody_rules.span_lapsed(
                span, _lease_of(store, transaction, remainder=remainder, now_ms=now_ms), now_ms)
            held = span is not None and span.executor_id == launch and not lapsed
            reference = custody_rules.claimed(transaction, launch) if held else None
            views[launch] = LaunchView(
                open=held,
                roles=None if reference is None else custody_rules.claim_roles(reference),
                parked=transaction.state == "attention_required")
    return views


def standing_worktree(store: Path, directory: str) -> str | None:
    """The attempt worktree `directory` stands in: the first of it and its ancestors, nearest
    first, whose `attempt-worktree:<path>` key has a lease record, held or not (#338 D7).

    None when no path has a record or the store directory does not exist. It takes no
    lock, writes nothing and runs no child process; a core error is a `StoreFault`.
    """
    if _existing_store(store) is None:
        return None
    try:
        core = TransactionStore(store)
        path = Path(directory)
        for candidate in (path, *path.parents):
            if core.inspect_lease(custody_rules.worktree_key(str(candidate))) is not None:
                return str(candidate)
    except TransactionError as error:
        raise StoreFault(f"custody store: {error}") from error
    return None


def _core(store: Path, now_ms: int) -> TransactionStore:
    """The store on a clock that reads `now_ms`, so one settle reads one instant (#338 D17)."""
    try:
        return TransactionStore(store, clock=lambda: now_ms)
    except TransactionError as error:
        raise StoreFault(f"custody store: {error}") from error


@contextlib.contextmanager
def _core_errors() -> Iterator[None]:
    """Core errors as the refusals `workflow-state` prints (#338 D13)."""
    try:
        yield
    except LeaseUnavailable as error:
        raise FencingRefused("custody_unavailable", str(error)) from error
    except TransactionError as error:
        raise StoreRefused(f"custody store: {error}") from error


@contextlib.contextmanager
def reading(store: Path, now_ms: int) -> Iterator[TransactionStore | None]:
    """The core on a clock that reads `now_ms`, for lock-free reads; None when the store
    directory does not exist. Creates nothing; a core error is a `StoreFault`."""
    if _existing_store(store) is None:
        yield None
        return
    core = _core(store, now_ms)
    try:
        yield core
    except TransactionError as error:
        raise StoreFault(f"custody store: {error}") from error


@contextlib.contextmanager
def writing(store: Path, now_ms: int) -> Iterator[TransactionStore]:
    """The core on a clock that reads `now_ms`, under the store lock (which creates the
    store); core errors are raised as the refusals `_core_errors` maps them to."""
    with store_lock(store):
        core = _core(store, now_ms)
        with _core_errors():
            yield core


def _require_recorded_worktree(issue: int, label: str, record: Mapping,
                               transaction: Transaction, canonical: Callable[[str], str]) -> None:
    """Refuse a live `record` (`label` names it: `attempt 2`, `remainder 1`) recorded at another
    worktree than its custody subject's.

    The subject fixes the worktree when the transaction is created (#338 D1, D19), so a
    transaction that a write cut before its ledger was published left behind is not taken
    up by a repeat naming a different worktree: the ledger would name one path while the
    lease protects the other. `canonical` is the identity the subject was created with.
    A record that is not in `LIVE_STATES` is not compared. Raises `ProjectionMismatch`.
    """
    if record["state"] not in custody_rules.LIVE_STATES:
        return
    recorded, bound = canonical(record["worktree"]), transaction.subject["worktree"]
    if recorded != bound:
        raise custody_rules.ProjectionMismatch(
            f"issue {issue} {label} is recorded at {recorded} but its "
            f"custody transaction {transaction.transaction_id} is bound to {bound}")


def _current_launch(issue: int, record: Mapping, *, remainder: bool) -> str:
    """The launch id of `record`'s current launch: its last, by the record's launch count."""
    make = delivery_rules.remainder_launch_id if remainder else custody_rules.launch_id
    return make(issue, record["remainder" if remainder else "attempt"], len(record["launches"]))


def _lease_of(store: Path, transaction: Transaction, *, remainder: bool,
              now_ms: int) -> Mapping | None:
    """The lease record of the worktree key of `transaction`, a custody transaction of an
    attempt or, with `remainder`, of a delivery remainder, read without a lock.

    A subject that is not the closed custody subject of its kind is a `StoreRefused`
    projection mismatch; a core error is a `StoreFault`.
    """
    check = (delivery_rules.remainder_subject_violation if remainder
             else custody_rules.subject_violation)
    violation = check(transaction.subject)
    if violation is not None:
        raise StoreRefused(f"custody projection mismatch: "
                           f"{transaction.transaction_id}: {violation}")
    try:
        return _core(store, now_ms).inspect_lease(
            custody_rules.worktree_key(transaction.subject["worktree"]))
    except TransactionError as error:
        raise StoreFault(f"custody store: {error}") from error


def _read_plans(store: Path, state: dict, *, now_ms: int,
                bound_launches: Mapping[tuple[int, int], int],
                bound_remainders: Mapping[tuple[int, int], int], report: OwnerReport | None,
                delivered: frozenset[int] = frozenset(),
                canonical: Callable[[str], str] | None = None) -> list[_Planned]:
    """The settle plans of every record that has operations, in read order, without a lock.

    Issues ascend by number; each issue's attempts run in order, then its delivery
    remainders. A record is the issue's `latest` when no attempt or remainder follows it.
    Each plan gets the run's admission facts for the record's current launch (its held claim,
    whether the host reported its owner gone, whether its `host_capacity` gate is open) and
    whether the issue is in `delivered`. Nothing is created. With `canonical`, each live
    record that has a custody transaction is also held to its subject's worktree
    (`_require_recorded_worktree`). A `supplement` the receipt already holds is dropped, so a
    settled ledger plans nothing.
    """
    plans, admission = [], state["admission"]
    for key in sorted(state["issues"], key=int):
        issue, issue_state = int(key), state["issues"][key]
        records = _records(issue_state)
        for position, (record, remainder) in enumerate(records):
            latest = position == len(records) - 1
            ordinal = record["remainder" if remainder else "attempt"]
            label = f"{'remainder' if remainder else 'attempt'} {ordinal}"
            transaction = _custody_under(
                store, _custody_key(state["transaction_id"], issue, ordinal, remainder=remainder))
            lease = (None if transaction is None
                     else _lease_of(store, transaction, remainder=remainder, now_ms=now_ms))
            named = (not remainder and report is not None
                     and (report.issue, report.attempt) == (issue, ordinal))
            current = _current_launch(issue, record, remainder=remainder)
            try:
                if transaction is not None and canonical is not None:
                    _require_recorded_worktree(issue, label, record, transaction, canonical)
                operations = custody_rules.settle_plan(
                    issue_state, record, transaction, lease=lease, now_ms=now_ms, latest=latest,
                    report_digest=telemetry_digest(report.report) if named else None,
                    bound=(issue, ordinal) in (bound_remainders if remainder else bound_launches),
                    current=current, claim=custody_rules.held_claim(admission, current),
                    owner_gone=custody_rules.owner_gone(admission, current),
                    gate_open=admission is not None
                    and custody_rules.gate_open(admission["claims"], current),
                    delivered=issue in delivered)
            except custody_rules.ProjectionMismatch as error:
                raise StoreRefused(f"custody projection mismatch: {error}") from error
            if operations and operations[0].kind == "supplement" and _recorded(
                    _core(store, now_ms), transaction.terminal["receipt_digest"],
                    operations[0].reason, operations[0].reference):
                continue
            if operations:
                plans.append(_Planned(issue, record, remainder, latest, transaction, operations))
    return plans


_SEAL_COMPLETIONS = (("seal",), ("reap", "seal"))


def _succeeded_seal(transaction_id: str, plan: _Planned,
                    operation: custody_rules.Operation) -> PendingSeal:
    return PendingSeal(transaction_id, operation.reason, issue=plan.issue,
                       executor=operation.executor_id)


def pending_seals(store: Path, state: dict, *, now_ms: int,
                  delivered: frozenset[int] = frozenset()) -> list[PendingSeal]:
    """The seals a write left undone (#338 D24), found lock-free; nothing is created.

    These are the seals of every record whose settle plan, with no owner report and no bind,
    is a seal completion: one `seal`, or the `reap` of a span that has lapsed (another
    transaction took the worktree once its window passed, say) and then the `seal` (D16), or
    the one `seal_succeeded` of a record of an issue in `delivered`, which the caller limits to
    those whose delivery proof has not parked unconverged (#339 D5, D27). They come in read
    order, in the shape `seal_custody` takes. Every other plan is left to the next write.
    """
    pending = []
    for plan in _read_plans(store, state, now_ms=now_ms, bound_launches={}, bound_remainders={},
                            report=None, delivered=delivered):
        operations = plan.operations
        kinds = tuple(operation.kind for operation in operations)
        if kinds in _SEAL_COMPLETIONS:
            pending.append(PendingSeal(
                plan.transaction.transaction_id, operations[-1].reason,
                operations[0].reason if len(operations) == 2 else None))
        elif kinds == ("seal_succeeded",):
            pending.append(_succeeded_seal(plan.transaction.transaction_id, plan, operations[0]))
    return pending


def _new_subject(core: TransactionStore, run: str, plan: _Planned, *, canonical:
                 Callable[[str], str], bound: Mapping[tuple[int, int], int]) -> dict:
    """The custody subject of the attempt or remainder `plan` creates; `prior` is the
    predecessor's transaction in the store now (`_Planned.predecessor_key`), `bound` the bind
    plan of its kind. A subject the rules refuse is a `StoreRefused`."""
    predecessor = plan.predecessor_key(run)
    with _core_errors():
        prior = None if predecessor is None else core.lookup(predecessor)
    make = delivery_rules.remainder_subject if plan.remainder else custody_rules.subject
    try:
        return make(run=run, issue=plan.issue, worktree=canonical(plan.record["worktree"]),
                    prior=prior, bound_launch=bound.get((plan.issue, plan.ordinal)),
                    **{"remainder" if plan.remainder else "attempt": plan.ordinal})
    except ValueError as error:
        raise StoreRefused(f"custody subject of issue {plan.issue} {plan.label}: "
                           f"{error}") from error


def _ends_span(plan: _Planned) -> bool:
    """Whether the plan, applied in the write phase, leaves its transaction without a span:
    the last of its span operations is a release, a reap or the seal of an earlier record."""
    ended = None
    for operation in plan.operations:
        if operation.kind == "acquire":
            ended = False
        elif operation.kind in ("release", "reap") or (operation.kind == "seal"
                                                       and not plan.latest):
            ended = True
    return bool(ended)


def _preflight(core: TransactionStore, run: str, planned: list[_Planned], *, now_ms: int,
               canonical: Callable[[str], str],
               bound_launches: Mapping[tuple[int, int], int],
               bound_remainders: Mapping[tuple[int, int], int]) -> dict[int, dict]:
    """The subject of every plan that creates, and the refusal of a live holder before any
    write (#338 D19).

    Every plan that acquires is checked, a new record's and an existing one's alike, so a
    refused sweep has written nothing. A live holder of the worktree key is no refusal when
    it is the plan's own transaction or when its own plan, earlier in the read order, ends
    its span (D24): a predecessor's interrupted seal is applied first, and an attempt or
    remainder whose successor launches in the same write gives the worktree up first (#339
    D3).
    """
    subjects, ending = {}, set()
    for position, plan in enumerate(planned):
        creating = plan.operations[0].kind == "create"
        if creating:
            subjects[position] = _new_subject(
                core, run, plan, canonical=canonical,
                bound=bound_remainders if plan.remainder else bound_launches)
        if any(operation.kind == "acquire" for operation in plan.operations):
            worktree = (subjects[position] if creating else plan.transaction.subject)["worktree"]
            with _core_errors():
                lease = core.inspect_lease(custody_rules.worktree_key(worktree))
            holder = None if lease is None else lease["holder"]
            own = None if creating else plan.transaction.transaction_id
            if holder is not None and now_ms < holder["expires_at"] \
                    and holder["transaction_id"] not in ending | {own}:
                raise FencingRefused(
                    "custody_unavailable",
                    f"worktree {worktree} is held by executor {holder['executor_id']} "
                    f"of transaction {holder['transaction_id']}")
        if plan.transaction is not None and _ends_span(plan):
            ending.add(plan.transaction.transaction_id)
    return subjects


def _apply(core: TransactionStore, run: str, plan: _Planned, subject: dict | None,
           created: dict[str, str], report: OwnerReport | None) -> list[PendingSeal]:
    """Apply one plan's operations in order, each against the transaction's current snapshot.

    `created` maps the creation key of each transaction this settle created to its id. The
    seal of an issue's latest record and the `succeeded` seals are returned, not applied.
    """
    snapshot, seals = plan.transaction, []
    for operation in plan.operations:
        if operation.kind == "create":
            subject = {**subject, "prior": created.get(plan.predecessor_key(run),
                                                        subject["prior"])}
            snapshot = core.create(plan.key(run), subject,
                                   **custody_rules.creation_arguments(subject))
            created[plan.key(run)] = snapshot.transaction_id
            continue
        identifier, custody = snapshot.transaction_id, snapshot.custody
        path = snapshot.subject["worktree"]
        if operation.kind == "acquire":
            snapshot = core.acquire(identifier, executor_id=operation.executor_id,
                                    subject_path=path, ttl_ms=operation.ttl_ms)
        elif operation.kind == "release":
            if custody is not None:
                snapshot = core.release(custody)
        elif operation.kind == "reap":
            snapshot = core.reap(identifier, reason=operation.reason)
        elif operation.kind == "park":
            snapshot = core.advance(identifier, "attention_required", reason=operation.reason,
                                    custody=custody)
        elif operation.kind == "unpark":
            snapshot = core.advance(identifier, "created", reason=operation.reason,
                                    custody=custody)
        elif operation.kind == "renew":
            snapshot = core.renew(custody, ttl_ms=operation.ttl_ms)
        elif operation.kind == "claim":
            snapshot = core.record_evidence(
                custody, evidence_id=custody_rules.claim_id(
                    operation.executor_id, custody_rules.span_epoch(custody)),
                form="snapshot", reference=operation.reference)
        elif operation.kind == "record_result":
            snapshot = core.record_owner_result(
                identifier, executor_id=operation.executor_id, subject_path=path,
                fence=custody_rules.launch_fence(snapshot, operation.executor_id),
                result=report.report)
        elif operation.kind == "seal":
            if plan.latest:
                seals.append(PendingSeal(identifier, operation.reason))
            else:
                snapshot = core.advance(identifier, "abandoned", reason=operation.reason,
                                        external_state="known", custody=custody)
        elif operation.kind == "seal_succeeded":
            seals.append(_succeeded_seal(identifier, plan, operation))
        elif operation.kind == "supplement":
            supplement(core, snapshot.terminal["receipt_digest"], outcome="satisfied",
                       reason=operation.reason, reference=operation.reference)
        else:
            raise ValueError(f"unknown custody operation {operation.kind!r}")
    return seals


def settle_custody(store: Path, state: dict, *, now_ms: int, canonical: Callable[[str], str],
                   bound_launches: Mapping[tuple[int, int], int],
                   bound_remainders: Mapping[tuple[int, int], int],
                   report: OwnerReport | None = None,
                   delivered: frozenset[int] = frozenset()) -> list[PendingSeal]:
    """Bring the core's custody to the projection of `state`, before its ledger write (#338 D4).

    Every core call reads the clock `now_ms`. The read phase takes no lock and plans every
    attempt, then every delivery remainder, of each issue (`custody projection mismatch` is a
    `StoreRefused`); with nothing to do it returns `[]` and creates no directory, lock file
    or store. Otherwise, under the store lock, a live holder of a new record's worktree is
    `FencingRefused("custody_unavailable")` before anything is created, then the plans are
    applied in the order read. `bound_launches` is the 8 -> 9 plan, `bound_remainders` the
    9 -> 10 plan, `report` an owner result this write submits, `delivered` the issues whose
    delivery is complete (their records give up their launch spans), `canonical` the worktree
    comparison identity: a new subject's worktree is made with it, and a live record whose
    existing custody subject names another worktree is a `custody projection mismatch` in the
    read phase. It returns the seals of each issue's latest record and the `succeeded` seals of
    the delivered issues, which `seal_custody` applies after the ledger is replaced; a settle
    that holds nothing else takes no lock.
    """
    planned = _read_plans(store, state, now_ms=now_ms, bound_launches=bound_launches,
                          bound_remainders=bound_remainders, report=report, delivered=delivered,
                          canonical=canonical)
    if not planned:
        return []
    if all(operation.kind == "seal_succeeded" for plan in planned
           for operation in plan.operations):
        return [_succeeded_seal(plan.transaction.transaction_id, plan, plan.operations[0])
                for plan in planned]
    run, seals, created = state["transaction_id"], [], {}
    with store_lock(store):
        core = _core(store, now_ms)
        subjects = _preflight(core, run, planned, now_ms=now_ms, canonical=canonical,
                              bound_launches=bound_launches, bound_remainders=bound_remainders)
        with _core_errors():
            for position, plan in enumerate(planned):
                seals.extend(_apply(core, run, plan, subjects.get(position), created, report))
    return seals


def _recorded(core: TransactionStore, receipt_digest: str, reason: str, reference: str) -> bool:
    return any(entry["reason"] == reason and entry["reference"] == reference
               for entry in core.post_terminal_observations(receipt_digest))


def supplement(core: TransactionStore, receipt_digest: str, *, outcome: str, reason: str,
               reference: str) -> None:
    """Record what arrived for a sealed transaction as a post-terminal observation of its
    receipt (#339 D6), unless it is there already. The caller holds the store lock."""
    if not _recorded(core, receipt_digest, reason, reference):
        core.record_post_terminal(
            receipt_digest, observation={"outcome": outcome, "reason": reason,
                                         "reference": reference}, contradicts_ground=False)


def helper_span(core: TransactionStore, transaction: Transaction, *, executor: str,
                lease_key: str, subject_path: str, now_ms: int) -> Any:
    """The custody a helper's writes run under (#339 D24b): the transaction's open span of
    `executor` that has not lapsed, else a new one; a key another holds is `LeaseUnavailable`."""
    span = transaction.custody
    if span is not None and span.executor_id == executor and not custody_rules.span_lapsed(
            span, core.inspect_lease(lease_key), now_ms):
        return span
    return core.acquire(transaction.transaction_id, executor_id=executor,
                        subject_path=subject_path, ttl_ms=delivery_rules.HELPER_TTL_MS).custody


def reach_proving(core: TransactionStore, transaction: Transaction, span: Any) -> Transaction:
    """Take a transaction to `proving` under `span` (#339 D19b): out of a parking, then through
    each of `FORWARD_STATES` it has not reached."""
    identifier = transaction.transaction_id
    if transaction.state == "attention_required":
        transaction = core.advance(identifier, transaction.parked_from,
                                   reason=custody_rules.DELIVERED, custody=span)
    forward = custody_rules.FORWARD_STATES
    reached = forward.index(transaction.state) + 1 if transaction.state in forward else 0
    for target in forward[reached:]:
        transaction = core.advance(identifier, target, reason=custody_rules.DELIVERED,
                                   custody=span)
    return transaction


def settle_sealed(core: TransactionStore, span: Any) -> Transaction:
    """Open a cohort under `span` and settle the proof (#339 D19, D27). A cohort a cut seal
    left open is passed over, spent limits park the transaction unconverged, any other refusal
    propagates; a transaction not sealed afterwards gives its span up."""
    try:
        core.start_cohort(span)
    except ProofRefused as refusal:
        if refusal.reason not in ("cohort_open", "convergence_exhausted"):
            raise
    settled = core.settle_proof(span)
    if settled.state not in TERMINALS:
        core.release(span)
    return settled


def _succeed(core: TransactionStore, snapshot: Transaction, seal: PendingSeal, receipt: str,
             now_ms: int) -> None:
    """Seal a custody transaction `succeeded` under the delivery `receipt` it cites (#339 D5);
    a worktree another custody holds leaves the seal pending."""
    if custody_rules.unconverged(snapshot):
        return
    worktree = snapshot.subject["worktree"]
    try:
        span = helper_span(core, snapshot, executor=seal.executor,
                           lease_key=custody_rules.worktree_key(worktree),
                           subject_path=worktree, now_ms=now_ms)
    except LeaseUnavailable:
        return
    if delivery_rules.RECEIPT_EVIDENCE not in {e["evidence_id"] for e in snapshot.evidence}:
        core.record_evidence(span, evidence_id=delivery_rules.RECEIPT_EVIDENCE, form="event",
                             reference=receipt)
    reach_proving(core, snapshot, span)
    settle_sealed(core, span)


def seal_custody(store: Path, pending: list[PendingSeal], *, now_ms: int,
                 receipts: Mapping[int, str] = MappingProxyType({})) -> None:
    """Apply the seals `settle_custody` or `pending_seals` returned, after the ledger write.

    Does nothing for `[]`. Under the store lock, each seal's `reap`, when it names one, is
    applied before its `advance` to `abandoned` (the core's `reap` writes nothing unless the
    span has lapsed). A `succeeded` seal waits for its issue's receipt in `receipts`. A
    transaction already sealed is left alone, so a repeat is safe.
    """
    due = [seal for seal in pending if seal.issue is None or seal.issue in receipts]
    if not due:
        return
    with store_lock(store):
        core = _core(store, now_ms)
        with _core_errors():
            for seal in due:
                snapshot = core.load(seal.transaction_id)
                if snapshot.state in TERMINALS:
                    continue
                if seal.issue is not None:
                    _succeed(core, snapshot, seal, receipts[seal.issue], now_ms)
                    continue
                if seal.reap is not None:
                    snapshot = core.reap(seal.transaction_id, reason=seal.reap)
                core.advance(seal.transaction_id, "abandoned", reason=seal.reason,
                             external_state="known", custody=snapshot.custody)


def retain_result(store: Path, run: str, *, issue: int, attempt: int, launch: int,
                  report: dict, now_ms: int) -> bool:
    """Record a refused owner `report` on the attempt's custody transaction (#338 D6, D20).

    The report is recorded with `record_owner_result` against the fence of the latest span
    of `launch` (the launch ordinal of `attempt` of `issue` in `run`), under the store lock,
    on the clock `now_ms`. It returns False and writes nothing when the attempt has no custody
    transaction, the core issued no span for that launch, or that span already holds a result
    with the same `telemetry_digest`. A sealed one takes it as a supplement (D6): True.
    """
    if custody_of(store, run, issue, attempt) is None:
        return False
    executor = custody_rules.launch_id(issue, attempt, launch)
    with store_lock(store):
        transaction = custody_of(store, run, issue, attempt)
        if transaction is None:
            return False
        fence = custody_rules.launch_fence(transaction, executor)
        if fence is None:
            return False
        if transaction.state in TERMINALS:
            with _core_errors():
                supplement(_core(store, now_ms), transaction.terminal["receipt_digest"],
                           outcome="unknown", reason=f"owner_result:{executor}",
                           reference=telemetry_digest(report))
            return True
        if custody_rules.result_recorded(transaction, executor, telemetry_digest(report)):
            return False
        with _core_errors():
            _core(store, now_ms).record_owner_result(
                transaction.transaction_id, executor_id=executor,
                subject_path=transaction.subject["worktree"], fence=fence, result=report)
    return True


def run_handle(store: Path, run_id: str) -> str | None:
    """The handle of the run transaction `run_id`, read without a lock: the legacy alias's id
    a migrated ledger keeps, else the transaction id. None when its subject is not the closed
    attempt-run subject."""
    try:
        subject = TransactionStore(store).load(run_id).subject
    except UnknownTransaction as error:
        raise StoreRefused(f"run transaction store: {error}") from error
    except TransactionError as error:
        raise StoreFault(f"run transaction store: {error}") from error
    return None if subject_violation(subject) is not None else subject_handle(subject, run_id)


def direct_runs(store: Path, workflows_dir: Path, issue: int) -> Iterator[tuple[int, str, Path]]:
    """The minted direct runs of `issue` as `(sequence, handle, run_dir)`, from sequence 1, in
    order, found by index and never by listing `workflows`.

    Lazy: the caller locks and checks each run before the next lookup. A miss ends the list;
    so does a missing `run_dir` or `state.json`, which is the reserved id of the next mint.
    """
    sequence = 0
    while True:
        sequence += 1
        run_id = lookup_run(store, direct_key(issue, sequence))
        if run_id is None:
            return
        handle = run_handle(store, run_id)
        if handle is None:
            raise StoreRefused("direct run index entry is not a run transaction")
        run_dir = workflows_dir / handle
        status = _path_status(run_dir)
        if status is None:
            return
        if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
            raise StoreRefused("direct run entry must be a non-symlink directory")
        if _path_status(run_dir / "state.json") is None:
            return
        yield sequence, handle, run_dir


def _hold_subject(store: Path, transaction_id: str) -> Mapping[str, Any]:
    """The closed issue-hold/v1 subject of the pointer `transaction_id`, read without a lock."""
    try:
        subject = TransactionStore(store).load(transaction_id).subject
    except UnknownTransaction as error:
        raise StoreRefused(f"issue hold store: {error}") from error
    except TransactionError as error:
        raise StoreFault(f"issue hold store: {error}") from error
    violation = hold_violation(subject)
    if violation is not None:
        raise StoreRefused(f"issue hold index entry is not a hold pointer: {violation}")
    return subject


def _hold_slot(store: Path, issue: int, run: str) -> int | None:
    """The first free pointer ordinal of `issue`, or None when a pointer already names `run`."""
    ordinal = 0
    while True:
        ordinal += 1
        transaction_id = lookup_run(store, hold_key(issue, ordinal))
        if transaction_id is None:
            return ordinal
        if _hold_subject(store, transaction_id)["run"] == run:
            return None


def settle_holds(store: Path, state: dict, identity: RunIdentity, *, now_ms: int) -> None:
    """Give each issue an orchestrated run's `state` holds a pointer naming its run (issue 475
    D6, D11).

    The read phase takes no lock: with every pointer in place (or for a direct run, which the
    direct index already finds) it creates nothing, not even the store. Otherwise, under the
    store lock, each missing pointer's slot is decided again and created at the first free
    ordinal with the run transactions' creation arguments. Pointers are never removed.
    """
    if identity.direct:
        return
    run = state["transaction_id"]
    held = [int(key) for key in sorted(state["issues"], key=int)
            if custody_rules.holds_issue(state["issues"][key])]
    missing = [issue for issue in held if _hold_slot(store, issue, run) is not None]
    if not missing:
        return
    with writing(store, now_ms) as core:
        for issue in missing:
            ordinal = _hold_slot(store, issue, run)
            if ordinal is not None:
                plan = hold_plan(issue, ordinal, run)
                core.create(plan.creation_key, plan.subject_json(), **creation_arguments(plan))


def hold_runs(store: Path, issue: int) -> Iterator[str]:
    """The handle of each run a hold pointer of `issue` names, in pointer order, read without a
    lock and never by listing `workflows`; nothing is created (issue 475 D5). A pointer that
    names no attempt run is a `StoreRefused`."""
    ordinal = 0
    while True:
        ordinal += 1
        transaction_id = lookup_run(store, hold_key(issue, ordinal))
        if transaction_id is None:
            return
        handle = run_handle(store, _hold_subject(store, transaction_id)["run"])
        if handle is None:
            raise StoreRefused("issue hold pointer does not name a run transaction")
        yield handle


def unmigrated_direct(store: Path, workflows_dir: Path, issue: int) -> bool:
    """Whether a legacy `direct-<issue>-<sequence>` directory sits at the first sequence the
    index has no entry for: a direct run `migrate --apply` has not bound yet.

    Takes no lock and creates nothing.
    """
    sequence = 1
    while lookup_run(store, direct_key(issue, sequence)) is not None:
        sequence += 1
    return _path_status(workflows_dir / f"direct-{issue}-{sequence:06d}") is not None


def _inventory(superpowers: Path) -> list[str]:
    """The ledgers `migrate` reads: non-dot, non-symlink directories of `workflows` that hold
    a regular `state.json`, in name order. Nothing else is read."""
    workflows = superpowers / "workflows"
    status = _path_status(workflows)
    if status is None or stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
        raise StoreRefused("workflows must be an existing non-symlink directory")
    ledgers = []
    for name in sorted(os.listdir(workflows)):
        if name.startswith("."):
            continue
        directory = _path_status(workflows / name)
        if directory is None or stat.S_ISLNK(directory.st_mode) or not stat.S_ISDIR(
                directory.st_mode):
            continue
        state = _path_status(workflows / name / "state.json")
        if state is not None and stat.S_ISREG(state.st_mode):
            ledgers.append(name)
    return ledgers


def _typed(document: Any, field: str, kind: type) -> Any:
    value = document.get(field) if isinstance(document, dict) else None
    return value if type(value) is kind else None


def _recorded_issues(document: Any) -> list[int] | None:
    issues = _typed(document, "issues", dict)
    if issues is None or not all(key.isascii() and key.isdecimal() for key in issues):
        return None
    return sorted(int(key) for key in issues)


def _prior_transaction_id(store: Path, prior_run: str | None) -> str | None:
    """The run id a ledger's `prior_run` names: a core id itself, else the index's answer."""
    if prior_run is None:
        return None
    dialect = classify(prior_run)
    if dialect == "core":
        return prior_run
    if dialect == "direct":
        prior = legacy_identity(prior_run)
        return lookup_run(store, direct_key(prior.issue, prior.sequence))
    return lookup_run(store, legacy_key(prior_run))


def _row_verdict(row: dict, document: Any, store: Path, *, upgrade: Callable[..., dict],
                 validate: Callable[..., dict], refusals: tuple[type[Exception], ...],
                 migrated: bool) -> tuple[str, str | None]:
    """The verdict and refusal reason of one parsed ledger; fills `transaction_id`."""
    run_id, version = row["run_id"], row["schema_version"]
    if schema_refusal(document) is not None:
        return "refused", "unknown_schema"
    if run_id is None:
        return "refused", "invalid_state"
    if run_id != row["ledger"]:
        return "refused", "location_mismatch"
    if version in (BOUND_SCHEMA_VERSION, CUSTODY_SCHEMA_VERSION, CORE_STATE_SCHEMA_VERSION):
        try:
            identity = bound_identity(store, document, run_id)
            if version == CORE_STATE_SCHEMA_VERSION:
                validate(document, run_id=run_id, identity=identity)
            else:
                _schema_ten(document, identity, run_id=run_id, validate=validate)
        except StoreFault:
            raise
        except (StoreRefused, *refusals):
            return "refused", "invalid_state"
        row["transaction_id"] = document["transaction_id"]
        if version != CORE_STATE_SCHEMA_VERSION:
            return "migrate", None
        return ("migrated" if migrated else "current"), None
    try:
        candidate, plan = _upgraded(document, run_id=run_id, upgrade=upgrade)
        plan_custody(candidate)
    except LedgerRefused as error:
        return "refused", error.reason
    except refusals:
        return "refused", "invalid_state"
    row["transaction_id"] = lookup_run(store, plan.creation_key)
    return "migrate", None


def migration_row(superpowers: Path, ledger: str, *, upgrade: Callable[..., dict],
                  validate: Callable[..., dict], refusals: tuple[type[Exception], ...],
                  migrated: bool = False) -> dict:
    """One ledger's report row, read without a lock; creates no store, lock or directory.

    `upgrade` and `validate` follow `locked_read`'s callback contract and `refusals` are the
    caller's error types, which a row reports as `invalid_state`; a `StoreFault` propagates.
    `migrated` turns a bound ledger's `current` into `migrated` (what an apply just bound).
    """
    store = store_root(superpowers)
    row = dict.fromkeys(REPORT_ROW_FIELDS)
    row["ledger"] = ledger
    try:
        document = json.loads(
            (superpowers / "workflows" / ledger / "state.json").read_text(encoding="utf-8"))
    except ValueError:
        row["verdict"], row["reason"] = "refused", "invalid_state"
        return row
    row.update(run_id=_typed(document, "run_id", str),
               schema_version=_typed(document, "schema_version", int),
               prior_run=_typed(document, "prior_run", str), issues=_recorded_issues(document),
               dialect=classify(_typed(document, "run_id", str)))
    if row["dialect"] in LEGACY_DIALECTS:
        row["alias"] = legacy_alias(row["run_id"])
    # A core run id (schema 8, 9 or 10) is a minted run, whose subject has no alias: alias
    # stays null.
    row["verdict"], row["reason"] = _row_verdict(
        row, document, store, upgrade=upgrade, validate=validate, refusals=refusals,
        migrated=migrated)
    row["prior_transaction_id"] = _prior_transaction_id(store, row["prior_run"])
    return row


def migration_report(superpowers: Path, *, apply: bool, upgrade: Callable[..., dict],
                     validate: Callable[..., dict], bind: Callable[[str], None],
                     pending: Callable[[str], bool],
                     refusals: tuple[type[Exception], ...]) -> dict:
    """The `attempt-migration-report/v1` of every ledger under `superpowers/workflows`.

    A read-only dry run comes first and completes no seal. With `apply`, each `migrate` ledger
    is bound through the caller's locked no-op write `bind(handle)` on bytes re-read under that
    ledger's lock, so a refusal under the lock (`LedgerRefused`) replaces the advisory dry-run
    verdict, and the rows are then recomputed. Any other `StoreRefused` of a ledger (a fencing
    refusal, a projection mismatch) is likewise its `invalid_state` row, and later ledgers are
    still bound. A `current` ledger for which the caller's `pending(handle)` finds a seal
    undone (#338 D24, #339 D5) gets the same `bind(handle)`, which completes the seal
    without rewriting the ledger; its verdict stays `current`, and one with nothing pending is
    not opened, locked or written. Refusals are reported data; a missing `workflows` directory
    raises `StoreRefused`, and a `StoreFault` raises.
    """
    options = {"upgrade": upgrade, "validate": validate, "refusals": refusals}
    rows = {ledger: migration_row(superpowers, ledger, **options)
            for ledger in _inventory(superpowers)}
    if apply:
        bound = []
        for ledger, row in rows.items():
            binding = row["verdict"] == "migrate"
            if not binding and row["verdict"] != "current":
                continue
            try:
                if not binding and not pending(ledger):
                    continue
                bind(ledger)
            except StoreFault:
                raise
            except StoreRefused as error:
                reason = error.reason if isinstance(error, LedgerRefused) else "invalid_state"
                rows[ledger] = {**row, "verdict": "refused", "reason": reason}
            else:
                if binding:
                    bound.append(ledger)
        for ledger in bound:
            rows[ledger] = migration_row(superpowers, ledger, migrated=True, **options)
    return report("apply" if apply else "dry_run", list(rows.values()))
