"""The transaction core (#204, #205, #206, #207, #208).

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
authentic late owner result beside that stop without changing state or custody.
`inspect_action` observes one declared action through a caller-passed effect with no lock
held across the call, and records the observation fence-stamped (#206); the two protocol
operations are that and `invoke_action`, which calls the effect only after a fresh `absent`
inspection, behind a durable intent and within the retry budget. An action observed in
flight (`open`, or last read `in_progress`) keeps `renew` from quiescing a parked
transaction, and `advance` enters no terminal while an action is `open`, `in_progress` or
`unknown`; it never enters `succeeded` nor writes a reserved parking reason, and applies
the publication and activation gates of `agent_tools.transaction_proof`. The durable-file
primitives and the refusal hierarchy live in
`agent_tools.transaction_storage`, and the document model — vocabularies, `Custody`,
`Transaction`, the validator and the snapshot fold — in `agent_tools.transaction_history`;
this module re-exports the errors and the public model names. `action_id` and the retry
constants live in `agent_tools.transaction_invocation`, which this module re-exports too.
`agent_tools.transaction_plan` is the home of the proof declaration's compiler and the plan
constants, which this module re-exports as well. `collect_obligation` records one proof
observation around the pure halves in `agent_tools.transaction_proof` (re-exported too);
`start_cohort` opens a convergence cohort and `settle_proof` judges it in one write.
`agent_tools.transaction_recovery_plan` compiles, binds and materializes the recovery
declaration (#208); this module re-exports its constants and those three functions.
`verify_anchors` observes every restorable unit's rollback anchor in `ready` around the pure
halves in `agent_tools.transaction_recovery`, whose refusal reasons and effect classes this
module re-exports; `begin_recovery` enters `recovering` under a fresh grant around that module's
admission, and `advance` applies its gates. The module has no command and no caller yet.
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
from agent_tools.transaction_invocation import (
    EFFECT_STATES, MAX_ATTEMPTS, REFUSAL_REASONS, RETRY_WINDOW_MS, ActionFold, action_id,
    action_violation, effect_request, fold_actions, inspect_result_violation,
    invoke_result_violation, observed, refusal, refused_error, satisfied, status, unresolved)
from agent_tools.transaction_plan import (
    COHORT_MARGIN_FLOOR_MS, COHORT_MARGIN_PERCENT, DEFAULT_CONVERGENCE_WINDOW_MS,
    MAX_COHORT_ATTEMPTS, MAX_COLLECTION_LATENCY_MS, MAX_CONVERGENCE_WINDOW_MS, MAX_FRESHNESS_MS,
    PLAN_REJECTION_REASONS, PLAN_SCHEMA, RUNNING_IDENTITY_FRESHNESS_MS, compile_proof,
    materialize_plan)
from agent_tools.transaction_proof import (
    PROOF_REFUSAL_REASONS, advance_violation, cohort_start, collection_refusal,
    next_evidence_id, obligation, observation_request, observation_violation, open_cohort,
    proof_refused, settlement)
from agent_tools.transaction_recovery import (
    EFFECT_CLASSES, RECOVERY_REFUSAL_REASONS, anchor_requests, anchors_events, begin_events,
    begin_requests, check_result_violation, recovery_advance_violation, recovery_refused)
from agent_tools.transaction_recovery_plan import (
    EDGE_ACTIONS, POSTURES, RECOVERY_PLAN_SCHEMA, RECOVERY_REJECTION_REASONS, bind_recovery,
    compile_recovery, materialize_recovery)
from agent_tools.transaction_storage import (
    LAST_AT_MS, CreationConflict, CustodyMisbound, EffectResultInvalid, FenceViolation,
    GrantInvalid, InvocationRefused, LeaseUnavailable, ProofPlanRejected, ProofRefused,
    RecoveryPlanRejected, RecoveryRefused, StaleCustody,
    StateInvalid, TransactionBusy, TransactionError, TransitionRefused, UnknownTransaction,
    atomic_write, fsync_directory, lstat_mode, open_lock, read_json, require_directory)

INDEX_SCHEMA = "transaction-creation-key/v1"
PARKED_CUSTODY_WINDOW_MS = 900_000  # the core cap on custody held through a parking (D19)
_INDEX_KEYS = frozenset({"schema", "creation_key", "transaction_id"})
_MAX_CLOCK_MS = LAST_AT_MS  # the clock ceiling: the last `at` that fits


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
    """Refuse (StateInvalid) arguments that cannot form a valid transaction-state/v5 document."""
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


def _refuse_in_flight(prior: dict, identity: str, entry: ActionFold | None,
                      latest_seq: int | None = None) -> None:
    """Refuse `attempt_in_flight` when the action's latest attempt is open under the held
    fence or, given the latest event seq an earlier hold read, the action recorded any
    event since, a changed attempt count or a newer inspection alike (D14, D16)."""
    seq = 0 if entry is None else entry.latest_seq
    if ((latest_seq is not None and seq != latest_seq)
            or (entry is not None and entry.open
                and entry.intent_fence == prior["custody"]["fence"])):
        raise refused_error(prior["transaction_id"], identity, "attempt_in_flight")


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
        D26, D27; #206 D9).

        A terminal source is `TransitionRefused` before any custody check. Custody
        is required when the target is `publishing`, when the history has ever
        entered `publishing`, or when the transaction holds custody; a required
        custody that is None is `StaleCustody`. A presented custody is always
        fenced-checked, required or not, before the lifecycle refusals. The last of
        those refuses a terminal target while some action is `open`, `in_progress` or
        `unknown` (`TransitionRefused` naming the first such action and its status),
        whatever `external_state` the caller passes. Before it, `advance_violation` refuses
        `succeeded` (entered only through `settle_proof`), a `proving -> attention_required`
        with a reserved reason, and a failing publication or activation gate (#207 D10, D12,
        D27); after it, `recovery_advance_violation` refuses `recovering`, a reserved recovery
        reason, `abandoned` over an action with effect, and `ready -> publishing` without an
        `anchors_verified` under the held fence (#208 D7, D10, D22). Entering a terminal while
        custody is held appends the transition and a `lease_released` reason `terminal` in one
        `state.json` write, then clears the lease records. Every refusal happens
        before any write; the lock file is never created.
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
        rule = advance_violation(prior, target, reason)
        if rule is not None:
            raise TransitionRefused(f"{where}: {rule}")
        blocker = unresolved(fold_actions(prior["events"])) if target in TERMINALS else None
        if blocker is not None:
            raise TransitionRefused(f"{where}: terminal target over unresolved action "
                                    f"{blocker.action_id} ({status(blocker)})")
        rule = recovery_advance_violation(prior, target, reason)
        if rule is not None:
            raise TransitionRefused(f"{where}: {rule}")
        return self._append(prior, now, [{
            "type": "transitioned", "from": source, "to": target, "reason": reason,
            "external_state": external_state}])

    def create(self, creation_key: str, subject: dict, *, concurrency_keys: Collection[str],
               proof: dict, recovery: dict) -> Transaction:
        """Create the transaction for `creation_key`, or return the one it already names.

        The concurrency key set is fixed here, stored sorted, and compared with the
        subject when the key already names a transaction (D4). Neither the `proof` nor the
        `recovery` declaration has a default; before any lock the recovery declaration is
        compiled, then the proof declaration, then the two are bound unit for unit, so a
        rejected one (`RecoveryPlanRejected`, `ProofPlanRejected`) leaves nothing behind.
        The two plans they materialize under the transaction id are stored with their
        digests on the `created` event, whose `recovers` is null here; a same-key create
        whose subject, key set, proof plan digest or recovery plan digest differs is a
        `CreationConflict` (#207 D2, D3; #208 D2, D5, D6).
        """
        return self._create(creation_key, subject, concurrency_keys, proof, recovery, None)

    def _create(self, creation_key: str, subject: dict, concurrency_keys: Collection[str],
                proof: dict, recovery: dict, recovers: str | None) -> Transaction:
        """`create`, with the `created` event's `recovers` back-link set to `recovers`, which
        a same-key create must match too (#208 D11)."""
        _require_creatable(self.root, creation_key, subject, concurrency_keys)
        where = f"{self.root}: creation_key {creation_key!r}"
        compiled_recovery = compile_recovery(recovery, where=where)
        compiled = compile_proof(proof, where=where)
        bound = bind_recovery(compiled_recovery, compiled, where=where)
        keys = sorted(concurrency_keys)
        at = format_at(self._now())
        descriptor = open_lock(self.root / "creation.lock")
        try:
            return self._create_locked(creation_key, subject, keys, compiled, bound, recovers,
                                       at)
        finally:
            os.close(descriptor)

    def _create_locked(self, creation_key: str, subject: dict, keys: list[str],
                       compiled: dict, bound: dict, recovers: str | None,
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
        plan = materialize_plan(compiled, transaction_id)
        recovery_plan = materialize_recovery(bound, transaction_id)
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
                    ("concurrency key set", document["concurrency_keys"] != keys),
                    ("proof plan", telemetry_digest(plan)
                     != document["events"][0]["proof_plan_digest"]),
                    ("recovery plan", telemetry_digest(recovery_plan)
                     != document["events"][0]["recovery_plan_digest"]),
                    ("recovers", document["events"][0]["recovers"] != recovers)) if differ]
                if differs:
                    raise CreationConflict(
                        f"{transaction_id}: creation_key {creation_key!r} already names a "
                        f"transaction with a different {' and '.join(differs)}")
                return snapshot(document)
            document = {
                "schema": SCHEMA, "transaction_id": transaction_id,
                "creation_key": creation_key, "subject": copy.deepcopy(subject),
                "state": "created", "parked_from": None, "revision": 1,
                "events": [{"seq": 1, "type": "created", "at": at,
                            "proof_plan_digest": telemetry_digest(plan),
                            "recovery_plan_digest": telemetry_digest(recovery_plan),
                            "recovers": recovers}],
                "concurrency_keys": keys, "custody": None, "proof_plan": plan,
                "recovery_plan": recovery_plan,
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
            with self._leases.locked():
                return self._released(prior, now, "released")

    def _released(self, prior: dict, now: int, reason: str) -> Transaction:
        """Append `lease_released` with `reason` to `state.json`, then clear the records;
        the caller holds both locks and has passed the fenced check (D8, D24)."""
        transaction_id = prior["transaction_id"]
        fence = prior["custody"]["fence"]
        candidate = copy.deepcopy(prior)
        candidate["events"].append({
            "seq": prior["revision"] + 1, "type": "lease_released", "at": format_at(now),
            "fence": fence, "reason": reason})
        candidate["custody"] = None
        candidate["revision"] = len(candidate["events"])
        _validate_state(candidate, transaction_id, self.root)
        directory = self.root / transaction_id
        atomic_write(directory, directory / "state.json", candidate)
        self._leases.clear(fence)
        return snapshot(candidate)

    def renew(self, custody: Custody) -> Transaction:
        """The core's renewal duty, a tick the holder's host loop calls (D13, D19, D27, D28;
        #206 D9).

        A terminal transaction is `TransitionRefused` before the fenced check; a
        failed check (a lapsed lease included) refuses without reacquiring. While
        the transaction is parked longer than `PARKED_CUSTODY_WINDOW_MS`, measured
        from the transition that entered the parked run, and no action is observed
        in flight (`open`, or last read `in_progress`; `unknown` and `diverged` hold
        nothing), it quiesces instead: `lease_released` reason `quiesced` in
        `state.json`, then the records are cleared, and the snapshot has no custody.
        Otherwise, an observed action included, it never appends an event or writes
        `state.json`: under the lease lock it judges the records again at the same
        clock reading, so a key a successor took after the lock-free check is
        `StaleCustody` with nothing written; it then extends every record by its
        recorded TTL only when the earliest remaining validity is inside the renewal
        margin, and writes nothing at all outside it.
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
            with self._leases.locked():
                if (prior["state"] in PARKINGS
                        and now - parked_since(prior["events"]) > PARKED_CUSTODY_WINDOW_MS
                        and not observed(fold_actions(prior["events"]))):
                    return self._released(prior, now, "quiesced")
                if not self._leases.extend_if_due(prior["custody"]["fence"], now):
                    raise StaleCustody(f"{transaction_id}: renew: custody lapsed before the "
                                       f"lease lock was taken")
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
        event = {**fields, "fence": prior["custody"]["fence"]}
        violation = fenced_id_violation(prior["events"], event)
        if violation is not None:
            raise StateInvalid(f"{prior['transaction_id']}: {operation}: {violation}")
        return self._append(prior, now, [event])

    def _append(self, prior: dict, now: int, events: list[dict]) -> Transaction:
        """Append `events` numbered from `prior`'s revision, each stamped `at` `now`, in one
        validated `state.json` write; the caller holds the transaction lock. A `transitioned`
        event moves `state` and `parked_from`; entering a terminal under custody also appends
        `lease_released` reason `terminal` and clears the records under the lease lock."""
        transaction_id = prior["transaction_id"]
        candidate = copy.deepcopy(prior)
        at = format_at(now)
        for fields in events:
            candidate["events"].append(
                {"seq": len(candidate["events"]) + 1, "at": at, **fields})
            if fields["type"] == "transitioned":
                source, target = fields["from"], fields["to"]
                if target == "attention_required":
                    candidate["parked_from"] = source
                elif source == "attention_required":
                    candidate["parked_from"] = None
                candidate["state"] = target
        fence = prior["custody"]["fence"] if prior["custody"] is not None else None
        if candidate["state"] in TERMINALS and fence is not None:
            candidate["events"].append({
                "seq": len(candidate["events"]) + 1, "type": "lease_released", "at": at,
                "fence": fence, "reason": "terminal"})
            candidate["custody"] = None
        candidate["revision"] = len(candidate["events"])
        _validate_state(candidate, transaction_id, self.root)
        directory = self.root / transaction_id
        if candidate["custody"] is None and fence is not None:
            with self._leases.locked():
                atomic_write(directory, directory / "state.json", candidate)
                self._leases.clear(fence)
        else:
            atomic_write(directory, directory / "state.json", candidate)
        return snapshot(candidate)

    @staticmethod
    def _action_arguments(custody: Any, operation: str, name: Any, parameters: Any,
                          effect: Any) -> str:
        """The action id, after refusing (StateInvalid), before any lock, a malformed
        credential, name or parameters, or an effect without callable `inspect` and
        `invoke` (#206 D3, D4)."""
        require_custody_shape(custody)
        where = f"{custody.transaction_id}: {operation}"
        violation = action_violation(name, parameters)
        if violation is not None:
            raise StateInvalid(f"{where}: {violation}")
        if not (callable(getattr(effect, "inspect", None))
                and callable(getattr(effect, "invoke", None))):
            raise StateInvalid(f"{where}: effect has no callable inspect and invoke")
        return action_id(custody.transaction_id, name, parameters)

    def inspect_action(self, custody: Custody, *, name: str, parameters: dict,
                       effect: Any) -> Transaction:
        """Observe one action through `effect.inspect` and record what it saw (#206 D3, D5,
        D8, D14, D16).

        Argument shapes are refused first, before any lock. The first lock hold refuses a
        terminal (`TransitionRefused`), runs the fenced check, then refuses an action whose
        latest attempt is open under the held fence (`InvocationRefused`
        `attempt_in_flight`) before any call, reads the action's attempt count (0 when
        undeclared) and builds the request, whose `attempt` is that count; the lock is then
        released and `effect.inspect` runs with no lock held. A result outside the closed
        shape is `EffectResultInvalid` with nothing written. The second lock hold repeats
        the terminal refusal and the fenced check, so a lapse during the call is
        `StaleCustody` with nothing written, then re-folds the action and refuses
        `attempt_in_flight` when it recorded any event since the first hold (a new attempt
        or a newer inspection) or an attempt is open under the held fence, so an
        observation older than the history is never appended: that refusal follows the
        read-only `effect.inspect` call and records nothing from it. Otherwise it appends,
        in one `state.json` write, `action_declared` when the history has no event of this
        action yet and `action_inspected` stamped with the held fence. Any state but a
        terminal may inspect, parkings included. Whatever the effect raises propagates.
        """
        identity = self._action_arguments(custody, "inspect_action", name, parameters,
                                          effect)
        with self._fenced(custody, "inspect_action", writes=True) as (prior, _):
            entry = fold_actions(prior["events"]).get(identity)
            _refuse_in_flight(prior, identity, entry)
            attempts = 0 if entry is None else entry.attempts
            latest_seq = 0 if entry is None else entry.latest_seq
            request = effect_request(prior, identity, name, parameters, attempts)
        result = effect.inspect(request)
        violation = inspect_result_violation(result)
        if violation is not None:
            raise EffectResultInvalid(f"{custody.transaction_id}: inspect_action: "
                                      f"{violation}")
        with self._fenced(custody, "inspect_action", writes=True) as (prior, now):
            entry = fold_actions(prior["events"]).get(identity)
            _refuse_in_flight(prior, identity, entry, latest_seq)
            events = []
            if entry is None:
                events.append({"type": "action_declared", "action_id": identity,
                               "name": name, "parameters": copy.deepcopy(parameters)})
            events.append({"type": "action_inspected", "action_id": identity,
                           "outcome": result["outcome"], "reference": result["reference"],
                           "fence": prior["custody"]["fence"]})
            return self._append(prior, now, events)

    def invoke_action(self, custody: Custody, *, name: str, parameters: dict,
                      effect: Any) -> Transaction:
        """Make the next attempt of one action through `effect.invoke`, then inspect it
        (#206 D3, D5-D8).

        Argument shapes are refused first, before any lock. The first lock hold refuses a
        terminal (`TransitionRefused`), runs the fenced check, then refuses a state other
        than `publishing` or `activating` (`InvocationRefused` `state_not_effectful`).
        An action whose latest inspection reads `satisfied` returns the unchanged snapshot
        with no write and no call. Otherwise the admission rules refuse, in order,
        `inspection_required`, `not_absent`, `not_retryable`, `budget_exhausted` and
        `window_closed`, each before any write or call. An admitted attempt `n` appends
        `invocation_intended` stamped with the held fence, and the lock is released.
        `effect.invoke` and then `effect.inspect` run with no lock held, on one request
        whose `attempt` is `n`; a result outside its closed shape is `EffectResultInvalid`
        and whatever the effect raises propagates, leaving the intent open. The second lock
        hold repeats the terminal refusal and the fenced check, so a lapse during the calls
        is `StaleCustody` with the intent open and the effect possibly applied, then
        appends `invocation_returned` and the closing `action_inspected` in one
        `state.json` write.
        """
        identity = self._action_arguments(custody, "invoke_action", name, parameters,
                                          effect)
        transaction_id = custody.transaction_id
        with self._fenced(custody, "invoke_action", writes=True) as (prior, now):
            if prior["state"] not in EFFECT_STATES:
                raise refused_error(transaction_id, identity, "state_not_effectful")
            entry = fold_actions(prior["events"]).get(identity)
            if satisfied(entry):
                return snapshot(prior)
            fence = prior["custody"]["fence"]
            reason = refusal(entry, held_fence=fence, now_ms=now)
            if reason is not None:
                raise refused_error(transaction_id, identity, reason)
            attempt = entry.attempts + 1
            self._append(prior, now, [{"type": "invocation_intended", "action_id": identity,
                                       "attempt": attempt, "fence": fence}])
            request = effect_request(prior, identity, name, parameters, attempt)
        returned = effect.invoke(request)
        violation = invoke_result_violation(returned)
        if violation is None:
            inspected = effect.inspect(request)
            violation = inspect_result_violation(inspected)
        if violation is not None:
            raise EffectResultInvalid(f"{transaction_id}: invoke_action: {violation}")
        with self._fenced(custody, "invoke_action", writes=True) as (prior, now):
            fence = prior["custody"]["fence"]
            return self._append(prior, now, [
                {"type": "invocation_returned", "action_id": identity, "attempt": attempt,
                 "result": returned["result"], "error_class": returned["error_class"],
                 "reference": returned["reference"], "fence": fence},
                {"type": "action_inspected", "action_id": identity,
                 "outcome": inspected["outcome"], "reference": inspected["reference"],
                 "fence": fence}])

    def collect_obligation(self, custody: Custody, *, obligation_id: str,
                           observer: Any) -> Transaction:
        """Observe one plan obligation through `observer.observe`, then record it (#207 D6,
        D7, D27, D33, D34).

        A malformed credential or id, or no callable `observe`, is `StateInvalid` before any
        lock. The first hold (`_fenced`, clock read once as `started`) refuses a broken
        admission rule `ProofRefused` with no write and no call, appends `interval_opened`
        for an `interval` obligation, and builds the request. The observer runs with no lock
        held; what it raises propagates, and a result outside the closed shape is
        `EffectResultInvalid`. The second hold refuses a terminal, a lapse (`StaleCustody`),
        `clock_regressed`, a re-run admission rule and a changed cohort
        (`not_cohort_member`); none records anything from the call, but an opened interval
        stays unclosed and the next collection mints a new id. Otherwise it appends
        `obligation_observed` with the held fence and `latency_ms = now - started`.
        """
        require_texts(custody, "collect_obligation", obligation_id=obligation_id)
        transaction_id = custody.transaction_id
        if not callable(getattr(observer, "observe", None)):
            raise StateInvalid(f"{transaction_id}: collect_obligation: observer has no callable "
                               f"observe")
        detail = f"collect_obligation {obligation_id!r}"
        with self._fenced(custody, "collect_obligation", writes=True) as (prior, started):
            reason = collection_refusal(prior, obligation_id, started)
            if reason is not None:
                raise proof_refused(transaction_id, reason, detail)
            entry = obligation(prior["proof_plan"], obligation_id)
            cohort = open_cohort(prior["events"], prior["custody"]["fence"])
            evidence_id = None
            if entry["form"] == "interval":
                evidence_id = next_evidence_id(prior["events"], obligation_id)
                self._append(prior, started, [{"type": "interval_opened",
                                               "evidence_id": evidence_id,
                                               "fence": prior["custody"]["fence"]}])
            request = observation_request(prior, entry, cohort)
        result = observer.observe(request)
        violation = observation_violation(result, entry)
        if violation is not None:
            raise EffectResultInvalid(f"{transaction_id}: collect_obligation: {violation}")
        with self._fenced(custody, "collect_obligation", writes=True) as (prior, now):
            fence = prior["custody"]["fence"]
            reason = "clock_regressed" if now < started else collection_refusal(
                prior, obligation_id, now)
            if reason is None and open_cohort(prior["events"], fence) != cohort:
                reason = "not_cohort_member"
            if reason is not None:
                raise proof_refused(transaction_id, reason, detail)
            return self._append(prior, now, [{
                "type": "obligation_observed", "obligation_id": obligation_id,
                "evidence_id": evidence_id or next_evidence_id(prior["events"], obligation_id),
                "form": entry["form"], "outcome": result["outcome"],
                "reason": result["reason"], "reference": result["reference"],
                "fence": fence, "cohort": cohort, "latency_ms": now - started}])

    def start_cohort(self, custody: Custody) -> Transaction:
        """Open the next cohort in one write: `cohort_start`'s events, which first fail one
        left open under an older fence, or its `ProofRefused` (#207 D11, D22)."""
        return self._decide(custody, "start_cohort", cohort_start)

    def settle_proof(self, custody: Custody) -> Transaction:
        """Judge the proof at one cutoff in one write, `settlement`'s first matching case:
        rejected, seal (into `succeeded`), cohort failed, exhausted, else `no_open_cohort`
        (#207 D10, D11, D21, D22)."""
        return self._decide(custody, "settle_proof", settlement)

    def verify_anchors(self, custody: Custody, *, observer: Any) -> Transaction:
        """Observe every `restorable` unit's rollback anchor in `ready`, then record
        `anchors_verified`: `_observed` around `anchor_requests` and `anchors_events` (#208
        D7, D20). Every refusal, `rollback_anchor_missing` included, writes nothing."""
        return self._observed(custody, "verify_anchors", observer, anchor_requests,
                              anchors_events)

    def begin_recovery(self, custody: Custody, *, grant_id: str, observer: Any) -> Transaction:
        """Enter `recovering`: `_observed` around `begin_requests` and `begin_events` for
        `grant_id` (#208 D8, D20). A malformed credential or `grant_id` refuses before any
        lock; every refusal writes nothing."""
        require_texts(custody, "begin_recovery", grant_id=grant_id)
        return self._observed(
            custody, "begin_recovery", observer, lambda prior: begin_requests(prior, grant_id),
            lambda prior, requests, results: begin_events(prior, grant_id, requests, results))

    def _observed(self, custody: Custody, operation: str, observer: Any,
                  admit: Callable[[dict], list[Mapping]],
                  conclude: Callable[[dict, list, list], list[dict]]) -> Transaction:
        """The two-hold check pattern (#207 D6; #208 D20). Before any lock, a malformed
        credential or no callable `observer.observe` is `StateInvalid`. The first hold
        (`_fenced`) runs `admit`, which may refuse; with no request it appends what
        `conclude(prior, [], [])` yields, if anything, and returns. Each request then goes to
        `observer.observe` with no lock held; what it raises propagates, and a result failing
        `check_result_violation` is `EffectResultInvalid`. The second hold refuses
        `history_changed` when the revision moved, else appends `conclude`'s events."""
        require_custody_shape(custody)
        transaction_id = custody.transaction_id
        if not callable(getattr(observer, "observe", None)):
            raise StateInvalid(f"{transaction_id}: {operation}: observer has no callable "
                               f"observe")
        with self._fenced(custody, operation, writes=True) as (prior, now):
            requests = admit(prior)
            if not requests:
                events = conclude(prior, [], [])
                return self._append(prior, now, events) if events else snapshot(prior)
            revision = prior["revision"]
        results = []
        for request in requests:
            result = observer.observe(request)
            violation = check_result_violation(result)
            if violation is not None:
                raise EffectResultInvalid(f"{transaction_id}: {operation}: {violation}")
            results.append(result)
        with self._fenced(custody, operation, writes=True) as (prior, now):
            if prior["revision"] != revision:
                raise recovery_refused(transaction_id, "history_changed",
                                       f"{operation}: the history grew during the calls")
            return self._append(prior, now, conclude(prior, requests, results))

    def _decide(self, custody: Custody, operation: str,
                decide: Callable[[dict, int], list[dict]]) -> Transaction:
        """A malformed credential refuses before any lock; `decide` refuses before any
        write; no observer or effect is called."""
        require_custody_shape(custody)
        with self._fenced(custody, operation, writes=True) as (prior, now):
            return self._append(prior, now, decide(prior, now))

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
