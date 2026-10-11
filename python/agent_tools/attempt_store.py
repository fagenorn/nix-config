"""The effectful half of attempt run identity and attempt custody (#337 D27, #338).

The store root beside `workflows`, the blocking store lock, mint and lookup, the binding
check, the locked-read and unlocked-check transform under the caller's lock, and the direct
index probe. From schema 9 it also applies `agent_tools.attempt_custody`'s settle plan to
`TransactionStore` under the store lock: `settle_custody` before a ledger write,
`seal_custody` after it, and `pending_seals` to find a seal a crash left undone.
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
from typing import Any, NamedTuple

from agent_tools import attempt_custody as custody_rules
from agent_tools.attempt_identity import (
    LEGACY_DIALECTS, REFUSAL_REASONS, REPORT_ROW_FIELDS, MigrationRefused, RunIdentity,
    RunPlan, classify, creation_arguments, direct_key, identity_of, legacy_alias,
    legacy_identity, legacy_key, minted_plan, plan_migration, report, schema_refusal,
    subject_handle, subject_violation)
from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_core import TransactionError, TransactionStore
from agent_tools.transaction_history import TERMINALS, Transaction
from agent_tools.transaction_storage import LeaseUnavailable, UnknownTransaction, is_id

BOUND_SCHEMA_VERSION = 8  # bound to its run; custody not yet in the core
CUSTODY_SCHEMA_VERSION = 9  # attempt custody is held in the core


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
    """A ledger as a locked read yields it: bound to its run transaction at schema 9.

    `changed` is true when the stored file is still a schema-8 or older document, so the
    caller's commit is also the migration write. `bound_launches` is then the 8 -> 9 plan,
    `(issue, attempt) -> launch count` for each attempt that was live; otherwise `{}`.
    """

    state: dict
    identity: RunIdentity
    changed: bool
    bound_launches: dict[tuple[int, int], int]


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
    """The identity of the run transaction a schema-8 `state` names, read without a lock.

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


def _schema_nine(document: dict[str, Any], identity: RunIdentity, *, run_id: str,
                 validate: Callable[..., dict]) -> tuple[dict[str, Any], dict]:
    """A schema-8 `document` as the validated schema-9 candidate and its 8 -> 9 plan."""
    candidate = copy.deepcopy(document)
    candidate["schema_version"] = CUSTODY_SCHEMA_VERSION
    validated = validate(candidate, run_id=run_id, identity=identity)
    return validated, plan_custody(validated)


def locked_read(state_path: Path, document: Any, *, run_id: str, upgrade: Callable[..., dict],
                validate: Callable[..., dict]) -> LockedRead:
    """A ledger read under its `state.lock`, bound to a run transaction.

    A schema-9 `document` is bound to the transaction it names. A schema-8 one is bound the
    same way, copied as schema 9 and planned (`bound_launches`), with `changed` set. An older
    one is upgraded, planned, its transaction minted (the caller holds the ledger lock, the
    store lock nests inside it, #337 D9) and the candidate returned as schema 9 with
    `changed` set. A refused ledger mints nothing.
    """
    store = ledger_store(state_path)
    require_known_schema(document)
    version = document["schema_version"]
    if version == CUSTODY_SCHEMA_VERSION:
        identity = bound_identity(store, document, run_id)
        return LockedRead(validate(document, run_id=run_id, identity=identity), identity,
                          False, {})
    if version == BOUND_SCHEMA_VERSION:
        identity = bound_identity(store, document, run_id)
        validated, bound = _schema_nine(document, identity, run_id=run_id, validate=validate)
        return LockedRead(validated, identity, True, bound)
    candidate, plan = _upgraded(document, run_id=run_id, upgrade=upgrade)
    bound = plan_custody(candidate)
    candidate["transaction_id"] = mint_run(store, plan)
    candidate["schema_version"] = CUSTODY_SCHEMA_VERSION
    identity = identity_of(plan.subject)
    return LockedRead(validate(candidate, run_id=run_id, identity=identity), identity, True,
                      bound)


def check_unlocked(state_path: Path, document: Any, *, run_id: str, upgrade: Callable[..., dict],
                   validate: Callable[..., dict]) -> None:
    """Check a ledger without a lock or a write: schema 9 against its run transaction, schema 8
    the same way and as the schema-9 candidate its next write binds, an older one through
    `upgrade`, `plan_migration` and `plan_custody`. No store or directory is created."""
    require_known_schema(document)
    version = document["schema_version"]
    if version == CUSTODY_SCHEMA_VERSION:
        identity = bound_identity(ledger_store(state_path), document, run_id)
        validate(document, run_id=run_id, identity=identity)
        return
    if version == BOUND_SCHEMA_VERSION:
        identity = bound_identity(ledger_store(state_path), document, run_id)
        _schema_nine(document, identity, run_id=run_id, validate=validate)
        return
    candidate, _ = _upgraded(document, run_id=run_id, upgrade=upgrade)
    plan_custody(candidate)


class PendingSeal(NamedTuple):
    """A seal not yet applied: the custody transaction to abandon and the seal's reason.

    `reap` is the reason of the reap `seal_custody` applies first, for a seal whose span
    lapsed after its ledger write; None when the seal has no such prerequisite.
    """

    transaction_id: str
    reason: str
    reap: str | None = None


class _Planned(NamedTuple):
    """One attempt's settle plan with what the write phase needs to apply it."""

    issue: int
    attempt: dict
    latest: bool
    transaction: Transaction | None
    operations: tuple[custody_rules.Operation, ...]


def custody_of(store: Path, run: str, issue: int, attempt: int) -> Transaction | None:
    """The custody transaction of `attempt` of `issue` in `run`, read without a lock.

    None when the store directory or the creation key's index entry is missing; creates
    nothing. A core error is a `StoreFault`.
    """
    if _existing_store(store) is None:
        return None
    try:
        core = TransactionStore(store)
        identity = core.lookup(custody_rules.creation_key(run, issue, attempt))
        return None if identity is None else core.load(identity)
    except TransactionError as error:
        raise StoreFault(f"custody store: {error}") from error


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


def _require_recorded_worktree(issue: int, attempt: Mapping, transaction: Transaction,
                               canonical: Callable[[str], str]) -> None:
    """Refuse a live `attempt` recorded at another worktree than its custody subject's.

    The subject fixes the worktree when the transaction is created (#338 D1, D19), so a
    transaction that a write cut before its ledger was published left behind is not taken
    up by a repeat naming a different worktree: the ledger would name one path while the
    lease protects the other. `canonical` is the identity the subject was created with.
    An attempt that is not in `LIVE_STATES` is not compared. Raises `ProjectionMismatch`.
    """
    if attempt["state"] not in custody_rules.LIVE_STATES:
        return
    recorded, bound = canonical(attempt["worktree"]), transaction.subject["worktree"]
    if recorded != bound:
        raise custody_rules.ProjectionMismatch(
            f"issue {issue} attempt {attempt['attempt']} is recorded at {recorded} but its "
            f"custody transaction {transaction.transaction_id} is bound to {bound}")


def _read_plans(store: Path, state: dict, *, now_ms: int,
                bound_launches: Mapping[tuple[int, int], int], report: OwnerReport | None,
                canonical: Callable[[str], str] | None = None) -> list[_Planned]:
    """The settle plans of every attempt that has operations, in read order, without a lock.

    Issues ascend by number and each issue's attempts run in order. Nothing is created.
    With `canonical`, each live attempt that has a custody transaction is also held to its
    subject's worktree (`_require_recorded_worktree`).
    """
    plans = []
    for key in sorted(state["issues"], key=int):
        issue, issue_state = int(key), state["issues"][key]
        attempts = issue_state["attempts"]
        for index, attempt in enumerate(attempts):
            number = attempt["attempt"]
            transaction = custody_of(store, state["transaction_id"], issue, number)
            lease = None
            if transaction is not None:
                violation = custody_rules.subject_violation(transaction.subject)
                if violation is not None:
                    raise StoreRefused(f"custody projection mismatch: "
                                       f"{transaction.transaction_id}: {violation}")
                try:
                    lease = _core(store, now_ms).inspect_lease(
                        custody_rules.worktree_key(transaction.subject["worktree"]))
                except TransactionError as error:
                    raise StoreFault(f"custody store: {error}") from error
            named = report is not None and (report.issue, report.attempt) == (issue, number)
            try:
                if transaction is not None and canonical is not None:
                    _require_recorded_worktree(issue, attempt, transaction, canonical)
                operations = custody_rules.settle_plan(
                    issue_state, attempt, transaction, lease=lease, now_ms=now_ms,
                    latest=index == len(attempts) - 1,
                    report_digest=telemetry_digest(report.report) if named else None,
                    bound=(issue, number) in bound_launches)
            except custody_rules.ProjectionMismatch as error:
                raise StoreRefused(f"custody projection mismatch: {error}") from error
            if operations:
                plans.append(_Planned(issue, attempt, index == len(attempts) - 1,
                                      transaction, operations))
    return plans


_SEAL_COMPLETIONS = (("seal",), ("reap", "seal"))


def pending_seals(store: Path, state: dict, *, now_ms: int) -> list[PendingSeal]:
    """The seals a write left undone (#338 D24), found lock-free; nothing is created.

    These are the seals of every attempt whose settle plan, with no owner report and no
    bind, is a seal completion: one `seal`, or the `reap` of a span that has lapsed (another
    transaction took the worktree once its window passed, say) and then the `seal` (D16).
    They come in read order, in the shape `seal_custody` takes. Every other plan is left to
    the settle step of a write that changes the ledger.
    """
    pending = []
    for plan in _read_plans(store, state, now_ms=now_ms, bound_launches={}, report=None):
        operations = plan.operations
        if tuple(operation.kind for operation in operations) in _SEAL_COMPLETIONS:
            pending.append(PendingSeal(
                plan.transaction.transaction_id, operations[-1].reason,
                operations[0].reason if len(operations) == 2 else None))
    return pending


def _new_subject(core: TransactionStore, run: str, plan: _Planned, *, canonical:
                 Callable[[str], str], bound_launches: Mapping[tuple[int, int], int]) -> dict:
    """The custody subject of the attempt `plan` creates; `prior` is the previous attempt's
    transaction in the store now. A subject the rules refuse is a `StoreRefused`."""
    number = plan.attempt["attempt"]
    with _core_errors():
        prior = None if number == 1 else core.lookup(
            custody_rules.creation_key(run, plan.issue, number - 1))
    try:
        return custody_rules.subject(
            run=run, issue=plan.issue, attempt=number,
            worktree=canonical(plan.attempt["worktree"]), prior=prior,
            bound_launch=bound_launches.get((plan.issue, number)))
    except ValueError as error:
        raise StoreRefused(f"custody subject of issue {plan.issue} attempt {number}: "
                           f"{error}") from error


def _ends_span(plan: _Planned) -> bool:
    """Whether the plan, applied in the write phase, leaves its transaction without a span:
    the last of its span operations is a release, a reap or the seal of an earlier attempt."""
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
               bound_launches: Mapping[tuple[int, int], int]) -> dict[int, dict]:
    """The subject of every plan that creates, and the refusal of a live holder before any
    write (#338 D19).

    Every plan that acquires is checked, a new attempt's and an existing one's alike, so a
    refused sweep has written nothing. A live holder of the worktree key is no refusal when
    it is the plan's own transaction or when its own plan, earlier in the read order, ends
    its span (D24): a predecessor's interrupted seal is applied first.
    """
    subjects, ending = {}, set()
    for position, plan in enumerate(planned):
        creating = plan.operations[0].kind == "create"
        if creating:
            subjects[position] = _new_subject(core, run, plan, canonical=canonical,
                                              bound_launches=bound_launches)
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
           created: dict[tuple[int, int], str], report: OwnerReport | None) -> list[PendingSeal]:
    """Apply one plan's operations in order, each against the transaction's current snapshot.

    The seal of an issue's latest attempt is returned, not applied (#338 D18).
    """
    number, snapshot, seals = plan.attempt["attempt"], plan.transaction, []
    for operation in plan.operations:
        if operation.kind == "create":
            prior = created.get((plan.issue, number - 1), subject["prior"])
            subject = {**subject, "prior": prior}
            snapshot = core.create(custody_rules.creation_key(run, plan.issue, number), subject,
                                   **custody_rules.creation_arguments(subject))
            created[(plan.issue, number)] = snapshot.transaction_id
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
        else:
            raise ValueError(f"unknown custody operation {operation.kind!r}")
    return seals


def settle_custody(store: Path, state: dict, *, now_ms: int, canonical: Callable[[str], str],
                   bound_launches: Mapping[tuple[int, int], int],
                   report: OwnerReport | None = None) -> list[PendingSeal]:
    """Bring the core's custody to the projection of `state`, before its ledger write (#338 D4).

    Every core call reads the clock `now_ms`. The read phase takes no lock and plans every
    attempt (`custody projection mismatch` is a `StoreRefused`); with nothing to do it returns
    `[]` and creates no directory, lock file or store. Otherwise, under the store lock, a
    live holder of a new attempt's worktree is `FencingRefused("custody_unavailable")` before
    anything is created, then the plans are applied in the order read. `bound_launches` is
    the 8 -> 9 plan, `report` an owner result this write submits, `canonical` the worktree
    comparison identity: a new subject's worktree is made with it, and a live attempt whose
    existing custody subject names another worktree is a `custody projection mismatch` in
    the read phase. It returns the seals of each issue's latest attempt, which
    `seal_custody` applies after the ledger is replaced.
    """
    planned = _read_plans(store, state, now_ms=now_ms, bound_launches=bound_launches,
                          report=report, canonical=canonical)
    if not planned:
        return []
    run, seals, created = state["transaction_id"], [], {}
    with store_lock(store):
        core = _core(store, now_ms)
        subjects = _preflight(core, run, planned, now_ms=now_ms, canonical=canonical,
                              bound_launches=bound_launches)
        with _core_errors():
            for position, plan in enumerate(planned):
                seals.extend(_apply(core, run, plan, subjects.get(position), created, report))
    return seals


def seal_custody(store: Path, pending: list[PendingSeal], *, now_ms: int) -> None:
    """Apply the seals `settle_custody` or `pending_seals` returned, after the ledger write.

    Does nothing for `[]`. Under the store lock, each seal's `reap`, when it names one, is
    applied before its `advance` to `abandoned` (the core's `reap` writes nothing unless the
    span has lapsed). A transaction already sealed is left alone, so a repeat is safe.
    """
    if not pending:
        return
    with store_lock(store):
        core = _core(store, now_ms)
        with _core_errors():
            for seal in pending:
                snapshot = core.load(seal.transaction_id)
                if snapshot.state in TERMINALS:
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
    transaction, the transaction is terminal, the core issued no span for that launch, or
    that span already holds a result with the same `telemetry_digest`.
    """
    if custody_of(store, run, issue, attempt) is None:
        return False
    executor = custody_rules.launch_id(issue, attempt, launch)
    with store_lock(store):
        transaction = custody_of(store, run, issue, attempt)
        if transaction is None or transaction.state in TERMINALS:
            return False
        fence = custody_rules.launch_fence(transaction, executor)
        if fence is None or custody_rules.result_recorded(
                transaction, executor, telemetry_digest(report)):
            return False
        with _core_errors():
            _core(store, now_ms).record_owner_result(
                transaction.transaction_id, executor_id=executor,
                subject_path=transaction.subject["worktree"], fence=fence, result=report)
    return True


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
    if version in (BOUND_SCHEMA_VERSION, CUSTODY_SCHEMA_VERSION):
        try:
            identity = bound_identity(store, document, run_id)
            if version == BOUND_SCHEMA_VERSION:
                _schema_nine(document, identity, run_id=run_id, validate=validate)
            else:
                validate(document, run_id=run_id, identity=identity)
        except StoreFault:
            raise
        except (StoreRefused, *refusals):
            return "refused", "invalid_state"
        row["transaction_id"] = document["transaction_id"]
        if version == BOUND_SCHEMA_VERSION:
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
    # A core run id at schema 8 is a minted run, whose subject has no alias: alias stays null.
    row["verdict"], row["reason"] = _row_verdict(
        row, document, store, upgrade=upgrade, validate=validate, refusals=refusals,
        migrated=migrated)
    row["prior_transaction_id"] = _prior_transaction_id(store, row["prior_run"])
    return row


def _seals_pending(superpowers: Path, ledger: str) -> bool:
    """Whether the stored document of `ledger` has a seal a crash left undone (read-only).

    An unreadable document or a `updated_at` that is not a UTC `...Z` stamp has none to find.
    """
    try:
        document = json.loads(
            (superpowers / "workflows" / ledger / "state.json").read_text(encoding="utf-8"))
        now_ms = custody_rules.at_ms(document["updated_at"])
    except (ValueError, KeyError, TypeError):
        return False
    return bool(pending_seals(store_root(superpowers), document, now_ms=now_ms))


def migration_report(superpowers: Path, *, apply: bool, upgrade: Callable[..., dict],
                     validate: Callable[..., dict], bind: Callable[[str], None],
                     refusals: tuple[type[Exception], ...]) -> dict:
    """The `attempt-migration-report/v1` of every ledger under `superpowers/workflows`.

    A read-only dry run comes first and completes no seal. With `apply`, each `migrate` ledger
    is bound through the caller's locked no-op write `bind(handle)` on bytes re-read under that
    ledger's lock, so a refusal under the lock (`LedgerRefused`) replaces the advisory dry-run
    verdict, and the rows are then recomputed. Any other `StoreRefused` of a ledger (a fencing
    refusal, a projection mismatch) is likewise its `invalid_state` row, and later ledgers are
    still bound. A `current` ledger whose document has a seal
    pending (`pending_seals`, #338 D24) gets the same `bind(handle)`, which completes the seal
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
                if not binding and not _seals_pending(superpowers, ledger):
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
