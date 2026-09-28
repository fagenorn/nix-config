"""The transaction core (#204, #205).

A caller-rooted store of closed-schema transactions with a closed lifecycle:
`TransactionStore(root, clock=...)` creates deduplicated transactions under an
absolute, pre-existing root and loads validated snapshots of them. Each
transaction's whole state and typed event history live in one `state.json`
whose `state`/`parked_from`/`custody`/`revision` are a projection the validator
re-folds from the events, beside the immutable sorted `concurrency_keys` fixed at
creation. Every event `at` is read from the injected clock (integer
epoch milliseconds, the wall clock by default); transaction ids still come from
the wall clock. `acquire` takes custody of the whole key set from the lease
authority in `agent_tools.transaction_custody`, returning a `Custody` credential
that `renew`, `release` and every fenced write check against the stored projection
and the live lease records; `advance` is fenced from `publishing` on and while
custody is held, and entering a terminal releases custody. `record_evidence`,
`open_interval` and `issue_grant` append fence-stamped records under the held
custody, `check_grant` checks one read-only, and every snapshot re-derives their
verdicts from the history. `reap` records a lapsed span's lapse and synthesized stop,
parking the transaction unless it is already parked, and `record_owner_result` keeps an
authentic late owner result beside that stop without changing state or custody. The
durable-file
primitives and the refusal hierarchy live in `agent_tools.transaction_storage`, and
the document model — vocabularies, `Custody`, `Transaction`, the validator and the
snapshot fold — in `agent_tools.transaction_history`; this module re-exports the
errors and the public model names. The module has no command and no caller yet.
"""

import contextlib
import copy
import fcntl
import hashlib
import os
import secrets
import stat
import time
import uuid
from collections.abc import Callable, Collection, Iterator, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_custody import (
    EVIDENCE_FORMS, LeaseAuthority, admissibility, fence_violation)
from agent_tools.transaction_history import (
    EXTERNAL_STATES, FORWARD, PARKINGS, SCHEMA, STATES, TERMINALS, TRANSITIONS, Custody,
    Transaction, bound_path, edge_allowed, fenced_id_violation, format_at, is_id,
    is_subject_path, json_object_violation, key_set_violation, owner_result_event,
    parked_since, reaped, require_custody_shape, require_texts, snapshot, span_issued,
    validate_state)
from agent_tools.transaction_storage import (
    CreationConflict, CustodyMisbound, FenceViolation, GrantInvalid, LeaseUnavailable,
    StaleCustody, StateInvalid, TransactionBusy, TransactionError, TransitionRefused,
    UnknownTransaction, atomic_write, fsync_directory, lstat_mode, open_lock, read_json,
    require_directory)

INDEX_SCHEMA = "transaction-creation-key/v1"
PARKED_CUSTODY_WINDOW_MS = 900_000  # the core cap on custody held through a parking (D19)
_INDEX_KEYS = frozenset({"schema", "creation_key", "transaction_id"})
_MAX_CLOCK_MS = 253_402_300_799_999  # 9999-12-31T23:59:59.999Z, the last `at` that fits


def _mint_id() -> str:
    """`rel_` + an RFC 9562 UUIDv7 over wall-clock milliseconds (D3)."""
    ms = time.time_ns() // 1_000_000
    value = ((ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | secrets.randbits(12) << 64
             | 0b10 << 62 | secrets.randbits(62))
    return "rel_" + str(uuid.UUID(int=value))


def _index_path(root: Path, creation_key: str) -> Path:
    digest = hashlib.sha256(creation_key.encode("utf-8")).hexdigest()
    return root / "creation-keys" / f"{digest}.json"


def _read_index(root: Path, creation_key: str) -> str | None:
    """The id the key's index entry names, or None when there is no entry."""
    index_directory = root / "creation-keys"
    if not require_directory(index_directory, missing_ok=True):
        return None
    path = _index_path(root, creation_key)
    if lstat_mode(path) is None:
        return None
    entry = read_json(path)
    if type(entry) is not dict or set(entry) != _INDEX_KEYS:
        raise StateInvalid(f"{path}: index entry is not the closed {INDEX_SCHEMA} object")
    if entry["schema"] != INDEX_SCHEMA:
        raise StateInvalid(f"{path}: index schema is not {INDEX_SCHEMA}")
    if entry["creation_key"] != creation_key:
        raise StateInvalid(f"{path}: index entry names a different creation key")
    if not is_id(entry["transaction_id"]):
        raise StateInvalid(f"{path}: index entry transaction_id is not a rel_ UUIDv7")
    return entry["transaction_id"]


def _validate_state(document: Any, transaction_id: str, root: Path) -> None:
    """`validate_state` with the creation-key index read from under `root`."""
    validate_state(document, transaction_id, lambda key: _read_index(root, key))


def _require_creatable(root: Path, creation_key: Any, subject: Any,
                       concurrency_keys: Any) -> None:
    """Refuse (StateInvalid) arguments that cannot form a valid transaction-state/v2 document."""
    where = f"{root}: creation_key {creation_key!r}"
    if type(creation_key) is not str or not creation_key:
        raise StateInvalid(f"{where}: not a non-empty string")
    try:
        creation_key.encode("utf-8")
    except UnicodeEncodeError as error:
        raise StateInvalid(f"{where}: not encodable as UTF-8") from error
    violation = json_object_violation(subject)
    if violation is not None:
        raise StateInvalid(f"{where}: subject {violation}")
    violation = key_set_violation(concurrency_keys)
    if violation is not None:
        raise StateInvalid(f"{where}: {violation}")


class TransactionStore:
    """Transactions under one absolute, pre-existing `root` the caller owns (D2)."""

    def __init__(self, root: Path, *, clock: Callable[[], int] | None = None) -> None:
        if not isinstance(root, Path) or not root.is_absolute() or not root.is_dir():
            raise TransactionError(f"{root}: store root is not an absolute existing directory")
        if clock is not None and not callable(clock):
            raise TransactionError(f"{root}: clock is not callable")
        self.root = root
        self._clock = clock if clock is not None else lambda: time.time_ns() // 1_000_000
        self._leases = LeaseAuthority(root)

    def _now(self) -> int:
        """One clock reading, refused unless an int in [0, _MAX_CLOCK_MS] (D3, D32)."""
        reading = self._clock()
        if type(reading) is not int or not 0 <= reading <= _MAX_CLOCK_MS:
            raise TransactionError(f"{self.root}: clock reading {reading!r} is not an integer "
                                   f"millisecond count in [0, {_MAX_CLOCK_MS}]")
        return reading

    def _existing_directory(self, transaction_id: str) -> Path:
        """The transaction's real directory, else UnknownTransaction; creates nothing (D16)."""
        if not is_id(transaction_id):
            raise UnknownTransaction(f"{transaction_id!r}: not a rel_ UUIDv7 transaction id")
        directory = self.root / transaction_id
        mode = lstat_mode(directory)
        if mode is None or stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise UnknownTransaction(f"{transaction_id}: no transaction directory under "
                                     f"{self.root}")
        return directory

    def _validated_document(self, transaction_id: str) -> dict:
        """Read and fully validate `state.json` without writing or locking (D13, D16)."""
        directory = self._existing_directory(transaction_id)
        lock_mode = lstat_mode(directory / "lock")
        if lock_mode is None or stat.S_ISLNK(lock_mode) or not stat.S_ISREG(lock_mode):
            raise StateInvalid(f"{transaction_id}: lock file is missing or not a regular file")
        document = read_json(directory / "state.json")
        _validate_state(document, transaction_id, self.root)
        return document

    def load(self, transaction_id: str) -> Transaction:
        """A validated snapshot; writes nothing, creates nothing, takes no lock."""
        return snapshot(self._validated_document(transaction_id))

    def advance(self, transaction_id: str, target: str, *, reason: str,
                external_state: str | None = None,
                custody: Custody | None = None) -> Transaction:
        """Move one transaction along one allowed edge under its lock (#204; #205 D14,
        D26, D27).

        A terminal source is `TransitionRefused` before any custody check. Custody
        is required when the target is `publishing`, when the history has ever
        entered `publishing`, or when the transaction holds custody; a required
        custody that is None is `StaleCustody`. A presented custody is always
        fenced-checked, required or not, before the lifecycle refusals. Entering a
        terminal while custody is held appends the transition and a `lease_released`
        reason `terminal` in one `state.json` write, then clears the lease records.
        Every refusal happens before any write; the lock file is never created.
        """
        if custody is not None:
            require_custody_shape(custody)
        with self._transaction_locked(transaction_id):
            return self._advance_locked(transaction_id, target, reason, external_state,
                                        custody)

    @contextlib.contextmanager
    def _transaction_locked(self, transaction_id: str):
        """Hold the transaction's existing lock, taken non-blocking; never creates it."""
        directory = self._existing_directory(transaction_id)
        lock = directory / "lock"
        mode = lstat_mode(lock)
        if mode is None or stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise StateInvalid(f"{transaction_id}: lock file {lock} is missing or not a "
                               f"regular file")
        try:
            descriptor = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
        except OSError as error:
            raise StateInvalid(f"{transaction_id}: lock file {lock} cannot be opened "
                               f"({error.strerror})") from error
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise TransactionBusy(f"{transaction_id}: lock file {lock} is held "
                                      f"elsewhere") from error
            yield
        finally:
            os.close(descriptor)

    def _advance_locked(self, transaction_id: str, target: Any, reason: Any,
                        external_state: Any, custody: Custody | None) -> Transaction:
        prior = self._validated_document(transaction_id)
        source = prior["state"]
        where = f"{transaction_id}: {source} -> {target!r}"
        if source in TERMINALS:
            raise TransitionRefused(f"{where}: source is terminal")
        now = self._now()
        required = (target == "publishing" or prior["custody"] is not None
                    or any(event["type"] == "transitioned" and event["to"] == "publishing"
                           for event in prior["events"]))
        if required and custody is None:
            raise StaleCustody(f"{where}: custody is required and none was presented")
        if custody is not None:
            self._check_custody(prior, custody, now)
        if type(target) is not str or target not in STATES:
            raise TransitionRefused(f"{where}: target is not a known state")
        if not edge_allowed(source, prior["parked_from"], target):
            raise TransitionRefused(f"{where}: edge is not allowed")
        if type(reason) is not str or not reason:
            raise TransitionRefused(f"{where}: reason is not a non-empty string")
        if external_state is not None and (type(external_state) is not str
                                           or external_state not in EXTERNAL_STATES):
            raise TransitionRefused(f"{where}: external_state is not known, unknown or None")
        if target in TERMINALS and external_state != "known":
            raise TransitionRefused(f"{where}: terminal target needs known external state")
        at = format_at(now)
        candidate = copy.deepcopy(prior)
        candidate["events"].append({
            "seq": prior["revision"] + 1, "type": "transitioned", "at": at,
            "from": source, "to": target, "reason": reason,
            "external_state": external_state})
        if target == "attention_required":
            candidate["parked_from"] = source
        elif source == "attention_required":
            candidate["parked_from"] = None
        candidate["state"] = target
        fence = prior["custody"]["fence"] if prior["custody"] is not None else None
        if target in TERMINALS and fence is not None:
            candidate["events"].append({
                "seq": len(candidate["events"]) + 1, "type": "lease_released", "at": at,
                "fence": fence, "reason": "terminal"})
            candidate["custody"] = None
        candidate["revision"] = len(candidate["events"])
        if candidate["events"][:len(prior["events"])] != prior["events"]:
            raise StateInvalid(f"{transaction_id}: prior events are not the new history's "
                               f"prefix")
        _validate_state(candidate, transaction_id, self.root)
        directory = self.root / transaction_id
        if candidate["custody"] is None and fence is not None:
            with self._leases.locked():
                atomic_write(directory, directory / "state.json", candidate)
                self._leases.clear(fence)
        else:
            atomic_write(directory, directory / "state.json", candidate)
        return snapshot(candidate)

    def create(self, creation_key: str, subject: dict, *,
               concurrency_keys: Collection[str]) -> Transaction:
        """Create the transaction for `creation_key`, or return the one it already names.

        The concurrency key set is fixed here, stored sorted, and compared with the
        subject when the key already names a transaction (D4).
        """
        _require_creatable(self.root, creation_key, subject, concurrency_keys)
        keys = sorted(concurrency_keys)
        at = format_at(self._now())
        descriptor = open_lock(self.root / "creation.lock")
        try:
            return self._create_locked(creation_key, subject, keys, at)
        finally:
            os.close(descriptor)

    def _create_locked(self, creation_key: str, subject: dict, keys: list[str],
                       at: str) -> Transaction:
        transaction_id = _read_index(self.root, creation_key)
        if transaction_id is None:
            transaction_id = _mint_id()
            index_directory = self.root / "creation-keys"
            if not require_directory(index_directory, missing_ok=True):
                index_directory.mkdir(exist_ok=True)
                require_directory(index_directory, missing_ok=False)
                fsync_directory(self.root)
            atomic_write(index_directory, _index_path(self.root, creation_key), {
                "schema": INDEX_SCHEMA, "creation_key": creation_key,
                "transaction_id": transaction_id})
        directory = self.root / transaction_id
        if not require_directory(directory, missing_ok=True):
            directory.mkdir(exist_ok=True)
            require_directory(directory, missing_ok=False)
            fsync_directory(self.root)
        descriptor = open_lock(directory / "lock")
        try:
            if lstat_mode(directory / "state.json") is not None:
                document = self._validated_document(transaction_id)
                if document["creation_key"] != creation_key:
                    raise StateInvalid(
                        f"{transaction_id}: creation_key index {creation_key!r} names a "
                        f"transaction created under a different creation_key")
                differs = [name for name, differ in (
                    ("subject", telemetry_digest(document["subject"])
                     != telemetry_digest(subject)),
                    ("concurrency key set", document["concurrency_keys"] != keys)) if differ]
                if differs:
                    raise CreationConflict(
                        f"{transaction_id}: creation_key {creation_key!r} already names a "
                        f"transaction with a different {' and '.join(differs)}")
                return snapshot(document)
            document = {
                "schema": SCHEMA, "transaction_id": transaction_id,
                "creation_key": creation_key, "subject": copy.deepcopy(subject),
                "state": "created", "parked_from": None, "revision": 1,
                "events": [{"seq": 1, "type": "created", "at": at}],
                "concurrency_keys": keys, "custody": None,
            }
            _validate_state(document, transaction_id, self.root)
            atomic_write(directory, directory / "state.json", document)
            return snapshot(document)
        finally:
            os.close(descriptor)

    def acquire(self, transaction_id: str, *, executor_id: str, subject_path: str,
                ttl_ms: int) -> Transaction:
        """Take custody of the whole key set, all or nothing (D5, D7, D8).

        Any live key, including this transaction's own live custody, is
        `LeaseUnavailable`. Every acquisition advances each key's epoch under one
        fresh instance; lease records are written before `state.json`.
        """
        where = f"{transaction_id}: acquire"
        if type(executor_id) is not str or not executor_id:
            raise StateInvalid(f"{where}: executor_id is not a non-empty string")
        if not is_subject_path(subject_path):
            raise StateInvalid(f"{where}: subject_path {subject_path!r} is not an absolute "
                               f"normalized path")
        if type(ttl_ms) is not int or ttl_ms < 1:
            raise StateInvalid(f"{where}: ttl_ms {ttl_ms!r} is not a positive integer")
        with self._transaction_locked(transaction_id):
            prior = self._validated_document(transaction_id)
            if prior["state"] in TERMINALS:
                raise TransitionRefused(f"{where}: state {prior['state']} is terminal")
            bound = bound_path(prior)
            if bound is not None and subject_path != bound:
                raise CustodyMisbound(f"{where}: subject_path {subject_path!r} differs from "
                                      f"the bound path {bound!r}")
            with self._leases.locked():
                now = self._now()
                candidate = self._acquisition(prior, executor_id, subject_path, now)
                self._leases.hold(candidate["custody"]["fence"], transaction_id=transaction_id,
                                  executor_id=executor_id, ttl_ms=ttl_ms, now=now)
                directory = self.root / transaction_id
                atomic_write(directory, directory / "state.json", candidate)
        return snapshot(candidate)

    def _acquisition(self, prior: dict, executor_id: str, subject_path: str,
                     now: int) -> dict:
        """The validated candidate an acquisition at `now` writes; refuses a live key."""
        transaction_id = prior["transaction_id"]
        candidate = copy.deepcopy(prior)
        events = candidate["events"]
        at = format_at(now)
        held = prior["custody"]
        if held is not None:
            if not self._leases.span_lapsed(held["fence"], now):
                raise LeaseUnavailable(f"{transaction_id}: its own custody by "
                                       f"{held['executor_id']!r} is still live")
            events.append({"seq": len(events) + 1, "type": "lease_lapse_detected", "at": at,
                           "fence": held["fence"], "executor_id": held["executor_id"]})
        live = self._leases.first_live_key(prior["concurrency_keys"], now)
        if live is not None:
            raise LeaseUnavailable(f"{transaction_id}: concurrency key {live!r} is live-held")
        fence = self._leases.next_fence(prior["concurrency_keys"])
        opening = {"seq": len(events) + 1, "type": "lease_acquired", "at": at,
                   "executor_id": executor_id, "subject_path": subject_path, "fence": fence}
        openings = [e for e in events if e["type"] in ("lease_acquired", "lease_reacquired")]
        if openings:
            closing = [e for e in events
                       if e["type"] in ("lease_released", "lease_lapse_detected")][-1]
            opening.update({
                "type": "lease_reacquired", "prior_executor_id": openings[-1]["executor_id"],
                "prior_fence": openings[-1]["fence"],
                "reason": ("expired" if closing["type"] == "lease_lapse_detected"
                           else "released")})
        events.append(opening)
        candidate["custody"] = {"executor_id": executor_id, "subject_path": subject_path,
                                "fence": fence}
        candidate["revision"] = len(events)
        _validate_state(candidate, transaction_id, self.root)
        return candidate

    def release(self, custody: Custody) -> Transaction:
        """Give custody up voluntarily: `state.json` first, then the records (D8, D24)."""
        require_custody_shape(custody)
        transaction_id = custody.transaction_id
        with self._transaction_locked(transaction_id):
            prior = self._validated_document(transaction_id)
            if prior["state"] in TERMINALS:
                raise TransitionRefused(f"{transaction_id}: release: state {prior['state']} "
                                        f"is terminal")
            now = self._now()
            self._check_custody(prior, custody, now)
            fence = prior["custody"]["fence"]
            with self._leases.locked():
                candidate = copy.deepcopy(prior)
                candidate["events"].append({
                    "seq": prior["revision"] + 1, "type": "lease_released",
                    "at": format_at(now), "fence": fence, "reason": "released"})
                candidate["custody"] = None
                candidate["revision"] = len(candidate["events"])
                _validate_state(candidate, transaction_id, self.root)
                directory = self.root / transaction_id
                atomic_write(directory, directory / "state.json", candidate)
                self._leases.clear(fence)
        return snapshot(candidate)

    def renew(self, custody: Custody) -> Transaction:
        """The core's renewal duty, a tick the holder's host loop calls (D13, D19, D27, D28).

        A terminal transaction is `TransitionRefused` before the fenced check; a
        failed check (a lapsed lease included) refuses without reacquiring. While
        the transaction is parked longer than `PARKED_CUSTODY_WINDOW_MS`, measured
        from the transition that entered the parked run, it quiesces instead:
        `lease_released` reason `quiesced` in `state.json`, then the records are
        cleared, and the snapshot has no custody. Otherwise it never appends an
        event or writes `state.json`: it extends every record by its recorded TTL
        only when the earliest remaining validity is inside the renewal margin,
        and writes nothing at all outside it.
        """
        require_custody_shape(custody)
        transaction_id = custody.transaction_id
        with self._transaction_locked(transaction_id):
            prior = self._validated_document(transaction_id)
            if prior["state"] in TERMINALS:
                raise TransitionRefused(f"{transaction_id}: renew: state {prior['state']} "
                                        f"is terminal")
            now = self._now()
            self._check_custody(prior, custody, now)
            fence = prior["custody"]["fence"]
            with self._leases.locked():
                if prior["state"] in PARKINGS \
                        and now - parked_since(prior["events"]) > PARKED_CUSTODY_WINDOW_MS:
                    candidate = copy.deepcopy(prior)
                    candidate["events"].append({
                        "seq": prior["revision"] + 1, "type": "lease_released",
                        "at": format_at(now), "fence": fence, "reason": "quiesced"})
                    candidate["custody"] = None
                    candidate["revision"] = len(candidate["events"])
                    _validate_state(candidate, transaction_id, self.root)
                    directory = self.root / transaction_id
                    atomic_write(directory, directory / "state.json", candidate)
                    self._leases.clear(fence)
                    return snapshot(candidate)
                self._leases.extend_if_due(fence, now)
        return snapshot(prior)

    def record_evidence(self, custody: Custody, *, evidence_id: str, form: str,
                        reference: str) -> Transaction:
        """Append `evidence_recorded` stamped with the held fence (D10, D15, D27).

        Form `interval` closes the interval opened under the same id; any other
        form needs an unused id. A reused id or an unopened interval is
        `StateInvalid` under the lock before any write.
        """
        require_texts(custody, "record_evidence", evidence_id=evidence_id,
                       reference=reference)
        if type(form) is not str or form not in EVIDENCE_FORMS:
            raise StateInvalid(f"{custody.transaction_id}: record_evidence: form {form!r} is "
                               f"not event, snapshot or interval")
        with self._fenced(custody, "record_evidence", writes=True) as (prior, now):
            return self._append_fenced(prior, now, "record_evidence", {
                "type": "evidence_recorded", "evidence_id": evidence_id, "form": form,
                "reference": reference})

    def open_interval(self, custody: Custody, *, evidence_id: str) -> Transaction:
        """Append `interval_opened`: the core witnesses where an interval starts (D15)."""
        require_texts(custody, "open_interval", evidence_id=evidence_id)
        with self._fenced(custody, "open_interval", writes=True) as (prior, now):
            return self._append_fenced(prior, now, "open_interval", {
                "type": "interval_opened", "evidence_id": evidence_id})

    def issue_grant(self, custody: Custody, *, grant_id: str, actor: str) -> Transaction:
        """Append `grant_issued` for the held custody only, stamped with its fence (D16)."""
        require_texts(custody, "issue_grant", grant_id=grant_id, actor=actor)
        with self._fenced(custody, "issue_grant", writes=True) as (prior, now):
            return self._append_fenced(prior, now, "issue_grant", {
                "type": "grant_issued", "grant_id": grant_id, "actor": actor})

    def check_grant(self, custody: Custody, grant_id: str) -> Mapping[str, Any]:
        """The grant's entry when its fence is the presented, current one (D16).

        Fenced and read-only: writes nothing and never re-stamps. An unknown grant,
        or one minted under another fence, is `GrantInvalid`.
        """
        require_texts(custody, "check_grant", grant_id=grant_id)
        with self._fenced(custody, "check_grant", writes=False) as (prior, _):
            presented = {key: dict(entry) for key, entry in custody.fence.items()}
            for grant in admissibility(prior["events"])[1]:
                if grant["grant_id"] == grant_id and grant["fence"] == presented:
                    return MappingProxyType(grant)
        raise GrantInvalid(f"{custody.transaction_id}: check_grant: grant_id {grant_id!r} is "
                           f"unknown or not minted under the presented fence")

    @contextlib.contextmanager
    def _fenced(self, custody: Custody, operation: str, *,
                writes: bool) -> Iterator[tuple[dict, int]]:
        """Under the transaction lock, the validated prior document and the one clock reading
        the fenced check passed at; a writer on a terminal is `TransitionRefused` first
        (D25, D27)."""
        transaction_id = custody.transaction_id
        with self._transaction_locked(transaction_id):
            prior = self._validated_document(transaction_id)
            if writes and prior["state"] in TERMINALS:
                raise TransitionRefused(f"{transaction_id}: {operation}: state "
                                        f"{prior['state']} is terminal")
            now = self._now()
            self._check_custody(prior, custody, now)
            yield prior, now

    def _append_fenced(self, prior: dict, now: int, operation: str,
                       fields: dict) -> Transaction:
        """Append one record stamped with the held fence to `state.json` alone (D8, D27)."""
        transaction_id = prior["transaction_id"]
        event = {"seq": prior["revision"] + 1, "at": format_at(now), **fields,
                 "fence": prior["custody"]["fence"]}
        violation = fenced_id_violation(prior["events"], event)
        if violation is not None:
            raise StateInvalid(f"{transaction_id}: {operation}: {violation}")
        candidate = copy.deepcopy(prior)
        candidate["events"].append(event)
        candidate["revision"] = len(candidate["events"])
        _validate_state(candidate, transaction_id, self.root)
        directory = self.root / transaction_id
        atomic_write(directory, directory / "state.json", candidate)
        return snapshot(candidate)

    def _check_custody(self, prior: dict, custody: Custody, now: int) -> None:
        """The fenced check (D12, D25): credential, then path, then live records at `now`.

        Runs under the transaction lock before any write; reads the lease records
        without the lease lock and records nothing when it refuses.
        """
        transaction_id = prior["transaction_id"]
        held = prior["custody"]
        if held is None:
            raise StaleCustody(f"{transaction_id}: holds no custody")
        presented = {key: dict(entry) for key, entry in custody.fence.items()}
        if (custody.transaction_id != transaction_id
                or custody.executor_id != held["executor_id"] or presented != held["fence"]):
            raise StaleCustody(f"{transaction_id}: presented custody is not the held custody")
        if custody.subject_path != held["subject_path"]:
            raise CustodyMisbound(f"{transaction_id}: subject_path {custody.subject_path!r} "
                                  f"differs from the bound path {held['subject_path']!r}")
        if self._leases.span_lapsed(held["fence"], now):
            raise StaleCustody(f"{transaction_id}: custody has lapsed")

    def reap(self, transaction_id: str, *, reason: str) -> Transaction:
        """The reaper's entry: record a lapsed span, taking no custody (D17, D24).

        With no held custody, a terminal, or a span still live on one clock reading,
        it writes nothing and returns the unchanged snapshot, so a sweep may call it
        on every transaction. On a lapsed span one `state.json` write appends
        `lease_lapse_detected`, `stop_synthesized` with `reason` and, outside a
        parking, a transition to `attention_required` with `reason` and external
        state `unknown`; custody becomes None. Lease records are not touched: an
        expired or re-held record is already inert.
        """
        if type(reason) is not str or not reason:
            raise StateInvalid(f"{transaction_id}: reap: reason {reason!r} is not a "
                               f"non-empty string")
        with self._transaction_locked(transaction_id):
            prior = self._validated_document(transaction_id)
            if prior["state"] in TERMINALS or prior["custody"] is None:
                return snapshot(prior)
            now = self._now()
            if not self._leases.span_lapsed(prior["custody"]["fence"], now):
                return snapshot(prior)
            candidate = reaped(prior, format_at(now), reason)
            _validate_state(candidate, transaction_id, self.root)
            directory = self.root / transaction_id
            atomic_write(directory, directory / "state.json", candidate)
        return snapshot(candidate)

    def record_owner_result(self, transaction_id: str, *, executor_id: str,
                            subject_path: str, fence: Mapping[str, Mapping[str, Any]],
                            result: dict) -> Transaction:
        """Keep a late owner result as evidence, never as authority (D18, D27, D34).

        A terminal is `TransitionRefused` first; then the executor and fence must
        equal some span's opening event (else `StaleCustody`: the core never issued
        that credential), and the path the bound one (else `CustodyMisbound`). One
        `state.json` write appends `owner_result` with `custody` `current` when the
        projection holds that executor and fence and the span has not lapsed, else
        `stale`, and `supersedes` naming the latest `stop_synthesized` of that fence
        or None. It never changes state, `parked_from` or custody, and never
        touches lease records.
        """
        where = f"{transaction_id}: record_owner_result"
        if type(executor_id) is not str or not executor_id:
            raise StateInvalid(f"{where}: executor_id {executor_id!r} is not a non-empty "
                               f"string")
        if not is_subject_path(subject_path):
            raise StateInvalid(f"{where}: subject_path {subject_path!r} is not an absolute "
                               f"normalized path")
        violation = fence_violation(fence)
        if violation is not None:
            raise StateInvalid(f"{where}: {violation}")
        violation = json_object_violation(result)
        if violation is not None:
            raise StateInvalid(f"{where}: result {violation}")
        presented = {key: dict(entry) for key, entry in fence.items()}
        with self._transaction_locked(transaction_id):
            prior = self._validated_document(transaction_id)
            if prior["state"] in TERMINALS:
                raise TransitionRefused(f"{where}: state {prior['state']} is terminal")
            if not span_issued(prior["events"], executor_id, presented):
                raise StaleCustody(f"{where}: executor {executor_id!r} and the presented "
                                   f"fence name no custody span the core issued")
            bound = bound_path(prior)
            if subject_path != bound:
                raise CustodyMisbound(f"{where}: subject_path {subject_path!r} differs from "
                                      f"the bound path {bound!r}")
            now = self._now()
            candidate = copy.deepcopy(prior)
            candidate["events"].append(owner_result_event(
                prior, at=format_at(now), executor_id=executor_id, fence=presented,
                result=result, lapsed=self._leases.span_lapsed(presented, now)))
            candidate["revision"] = len(candidate["events"])
            _validate_state(candidate, transaction_id, self.root)
            directory = self.root / transaction_id
            atomic_write(directory, directory / "state.json", candidate)
        return snapshot(candidate)

    def inspect_lease(self, key: str) -> Mapping[str, Any] | None:
        """A read-only view of `key`'s lease record, or None; no lock, no write (D6)."""
        if type(key) is not str or not key:
            raise StateInvalid(f"{self.root}: lease key {key!r} is not a non-empty string")
        try:
            key.encode("utf-8")
        except UnicodeEncodeError as error:
            raise StateInvalid(f"{self.root}: lease key {key!r} is not encodable as "
                               f"UTF-8") from error
        record = self._leases.record(key)
        return None if record is None else MappingProxyType(copy.deepcopy(record))
