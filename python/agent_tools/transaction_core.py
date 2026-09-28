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
that `release` and every fenced write check against the stored projection and the
live lease records. The durable-file primitives and the refusal hierarchy live in
`agent_tools.transaction_storage`, whose error classes this module re-exports.
The module has no command and no caller yet.
"""

import calendar
import contextlib
import copy
import dataclasses
import datetime
import fcntl
import hashlib
import os
import re
import secrets
import stat
import time
import uuid
from collections.abc import Callable, Collection, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_custody import CUSTODY_EVENTS, LeaseAuthority, fence_violation
from agent_tools.transaction_storage import (
    CreationConflict, CustodyMisbound, FenceViolation, GrantInvalid, LeaseUnavailable,
    StaleCustody, StateInvalid, TransactionBusy, TransactionError, TransitionRefused,
    UnknownTransaction, atomic_write, fsync_directory, lstat_mode, open_lock, read_json,
    require_directory, serialize, strict_loads)

SCHEMA = "transaction-state/v2"
INDEX_SCHEMA = "transaction-creation-key/v1"

FORWARD = ("created", "awaiting_verification", "ready", "publishing", "published",
           "activating", "proving")
PARKINGS = ("attention_required", "recovering")
TERMINALS = frozenset({"succeeded", "abandoned", "rolled_back", "failed"})
STATES = frozenset(FORWARD) | frozenset(PARKINGS) | TERMINALS

TRANSITIONS: Mapping[str, frozenset[str]] = MappingProxyType({
    "created": frozenset({"awaiting_verification", "attention_required", "abandoned"}),
    "awaiting_verification": frozenset({"ready", "attention_required", "abandoned"}),
    "ready": frozenset({"publishing", "attention_required", "abandoned"}),
    "publishing": frozenset({"published", "attention_required"}),
    "published": frozenset({"activating", "proving", "attention_required"}),
    "activating": frozenset({"proving", "attention_required"}),
    "proving": frozenset({"succeeded", "attention_required"}),
    "attention_required": frozenset(FORWARD) | frozenset({"recovering", "abandoned",
                                                          "failed"}),
    "recovering": frozenset({"rolled_back", "attention_required", "abandoned", "failed"}),
    "succeeded": frozenset(),
    "abandoned": frozenset(),
    "rolled_back": frozenset(),
    "failed": frozenset(),
})

_ID_PATTERN = re.compile(
    r"rel_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
_AT_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")
_STATE_KEYS = frozenset({"schema", "transaction_id", "creation_key", "subject", "state",
                         "parked_from", "revision", "events", "concurrency_keys", "custody"})
_KEY_COLLECTIONS = (list, tuple, set, frozenset)
_INDEX_KEYS = frozenset({"schema", "creation_key", "transaction_id"})
_CREATED_KEYS = frozenset({"seq", "type", "at"})
_TRANSITIONED_KEYS = frozenset({"seq", "type", "at", "from", "to", "reason",
                                "external_state"})
_ENVELOPE_KEYS = frozenset({"seq", "type", "at"})
_OPENING_KEYS = _ENVELOPE_KEYS | {"executor_id", "subject_path", "fence"}
_EVENT_KEYS: Mapping[str, frozenset[str]] = MappingProxyType({
    "transitioned": _TRANSITIONED_KEYS,
    "lease_acquired": _OPENING_KEYS,
    "lease_reacquired": _OPENING_KEYS | {"prior_executor_id", "prior_fence", "reason"},
    "lease_released": _ENVELOPE_KEYS | {"fence", "reason"},
    "lease_lapse_detected": _ENVELOPE_KEYS | {"fence", "executor_id"},
})
_RELEASE_REASONS = ("released", "quiesced", "terminal")
_EXTERNAL_STATES = ("known", "unknown", None)
_MAX_CLOCK_MS = 253_402_300_799_999  # 9999-12-31T23:59:59.999Z, the last `at` that fits


@dataclasses.dataclass(frozen=True)
class Custody:
    """The credential of one custody span (#205 D12).

    An ordering token, not a secret: a holder may persist and rebuild it, and
    every fenced write compares it with the stored custody and the live lease
    records. `fence` maps each concurrency key to its `{epoch, instance}`.
    """

    transaction_id: str
    executor_id: str
    subject_path: str
    fence: Mapping[str, Mapping[str, Any]]


@dataclasses.dataclass(frozen=True)
class Transaction:
    """A validated snapshot of one transaction.

    `subject`, each event and `custody.fence` (with each fence entry) are
    `types.MappingProxyType` views over deep copies. Only those levels are
    read-only: nested values stay mutable, but they are copies, so mutating
    them cannot reach disk.
    """

    transaction_id: str
    creation_key: str
    subject: Mapping[str, Any]
    state: str
    parked_from: str | None
    revision: int
    events: tuple[Mapping[str, Any], ...]
    concurrency_keys: tuple[str, ...]
    custody: Custody | None


def _edge_allowed(source: str, parked_from: str | None, target: str) -> bool:
    """Contract: `target` is in TRANSITIONS[source]; from a parking, a forward-state
    target must be the recorded `parked_from` (D15)."""
    if target not in TRANSITIONS.get(source, frozenset()):
        return False
    if source == "attention_required" and target in FORWARD:
        return target == parked_from
    return True


def _mint_id() -> str:
    """`rel_` + an RFC 9562 UUIDv7 over wall-clock milliseconds (D3)."""
    ms = time.time_ns() // 1_000_000
    value = ((ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | secrets.randbits(12) << 64
             | 0b10 << 62 | secrets.randbits(62))
    return "rel_" + str(uuid.UUID(int=value))


def _is_id(value: object) -> bool:
    return type(value) is str and _ID_PATTERN.fullmatch(value) is not None


def _format_at(ms: int) -> str:
    """Epoch milliseconds as UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`."""
    seconds = datetime.datetime.fromtimestamp(ms // 1000, tz=datetime.timezone.utc)
    return seconds.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms % 1000:03d}Z"


def _parse_at(at: str) -> int:
    """Epoch milliseconds of a `YYYY-MM-DDTHH:MM:SS.mmmZ` stamp; `_format_at`'s inverse."""
    seconds, millis = at[:-1].split(".")
    parsed = datetime.datetime.strptime(seconds, "%Y-%m-%dT%H:%M:%S")
    return calendar.timegm(parsed.timetuple()) * 1000 + int(millis)


def _is_timestamp(value: object) -> bool:
    if type(value) is not str or _AT_PATTERN.fullmatch(value) is None:
        return False
    try:
        datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return False
    return True


def _key_set_violation(keys: Any) -> str | None:
    """The first concurrency key set rule `keys` breaks, or None when it breaks none (D4)."""
    if type(keys) not in _KEY_COLLECTIONS:
        return "concurrency_keys is not a list, tuple, set or frozenset"
    if not keys:
        return "concurrency_keys is empty"
    for key in keys:
        if type(key) is not str or not key:
            return f"concurrency key {key!r} is not a non-empty string"
        try:
            key.encode("utf-8")
        except UnicodeEncodeError:
            return f"concurrency key {key!r} is not encodable as UTF-8"
    if len(set(keys)) != len(keys):
        return "concurrency_keys holds a duplicate key"
    return None


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
    if not _is_id(entry["transaction_id"]):
        raise StateInvalid(f"{path}: index entry transaction_id is not a rel_ UUIDv7")
    return entry["transaction_id"]


def _fold_transitioned(event: dict, seq: int, state: str, parked: str | None,
                      refuse: Callable[[str], StateInvalid]) -> tuple[str, str | None]:
    """Check one transitioned event against the fold; the folded (state, parked_from)."""
    if set(event) != _TRANSITIONED_KEYS:
        raise refuse(f"event {seq} is not the closed transitioned event")
    if type(event["seq"]) is not int or event["seq"] != seq:
        raise refuse(f"event {seq} does not carry seq {seq}")
    if not _is_timestamp(event["at"]):
        raise refuse(f"event {seq} at is not a YYYY-MM-DDTHH:MM:SS.mmmZ timestamp")
    target = event["to"]
    if event["from"] != state:
        raise refuse(f"event {seq} from does not equal the folded state {state}")
    if type(target) is not str or target not in STATES:
        raise refuse(f"event {seq} to is not a known state")
    if not _edge_allowed(state, parked, target):
        raise refuse(f"event {seq} edge {state} -> {target} is not allowed")
    if type(event["reason"]) is not str or not event["reason"]:
        raise refuse(f"event {seq} reason is not a non-empty string")
    external_state = event["external_state"]
    if external_state is not None and (type(external_state) is not str
                                       or external_state not in _EXTERNAL_STATES):
        raise refuse(f"event {seq} external_state is not known, unknown or null")
    if target in TERMINALS and external_state != "known":
        raise refuse(f"event {seq} reaches terminal {target} without known external state")
    if target == "attention_required":
        parked = state
    elif state == "attention_required":
        parked = None
    return target, parked


def _is_subject_path(value: object) -> bool:
    """An absolute path string equal to its own normalization (D5)."""
    return type(value) is str and os.path.isabs(value) and value == os.path.normpath(value)


@dataclasses.dataclass
class _CustodyFold:
    """What the validator folds from the custody events (D11, D30)."""

    keys: list[str]
    custody: dict | None = None
    bound_path: str | None = None
    spans: list[tuple[str, dict]] = dataclasses.field(default_factory=list)
    last_close: str | None = None


def _fold_closing(event: dict, seq: int, fold: _CustodyFold, state: str,
                  entered_terminal: int | None, refuse: Callable[[str], StateInvalid]) -> None:
    """Check one lease_released or lease_lapse_detected event and close the open span."""
    event_type = event["type"]
    if fold.custody is None:
        raise refuse(f"event {seq} {event_type} closes no open custody span")
    if event["fence"] != fold.custody["fence"]:
        raise refuse(f"event {seq} {event_type} fence does not equal the open span's fence")
    if event_type == "lease_lapse_detected":
        if event["executor_id"] != fold.custody["executor_id"]:
            raise refuse(f"event {seq} executor_id does not equal the open span's executor")
        fold.last_close = "lapsed"
    else:
        reason = event["reason"]
        if type(reason) is not str or reason not in _RELEASE_REASONS:
            raise refuse(f"event {seq} reason is not released, quiesced or terminal")
        if reason == "quiesced" and state not in PARKINGS:
            raise refuse(f"event {seq} quiesced release happens outside a parking")
        if reason == "terminal" and entered_terminal != seq - 1:
            raise refuse(f"event {seq} terminal release does not immediately follow a "
                         f"transition into a terminal")
        fold.last_close = "released"
    fold.custody = None


def _fold_opening(event: dict, seq: int, fold: _CustodyFold,
                  refuse: Callable[[str], StateInvalid]) -> None:
    """Check one lease_acquired or lease_reacquired event and open its span (D5, D7, D30)."""
    event_type = event["type"]
    if type(event["executor_id"]) is not str or not event["executor_id"]:
        raise refuse(f"event {seq} executor_id is not a non-empty string")
    if not _is_subject_path(event["subject_path"]):
        raise refuse(f"event {seq} subject_path is not an absolute normalized path")
    if event_type == "lease_acquired":
        if fold.spans:
            raise refuse(f"event {seq} lease_acquired follows an earlier custody span")
        fold.bound_path = event["subject_path"]
    else:
        if fold.custody is not None:
            raise refuse(f"event {seq} lease_reacquired opens a span while one is open")
        if not fold.spans:
            raise refuse(f"event {seq} lease_reacquired follows no earlier custody span")
        prior_executor, prior_fence = fold.spans[-1]
        if event["subject_path"] != fold.bound_path:
            raise refuse(f"event {seq} subject_path differs from the bound path")
        if event["prior_executor_id"] != prior_executor:
            raise refuse(f"event {seq} prior_executor_id does not name the prior span's "
                         f"executor")
        if fence_violation(event["prior_fence"], fold.keys) is not None \
                or event["prior_fence"] != prior_fence:
            raise refuse(f"event {seq} prior_fence does not equal the prior span's fence")
        if any(event["fence"][key]["epoch"] <= prior_fence[key]["epoch"] for key in fold.keys):
            raise refuse(f"event {seq} fence epoch does not increase over the prior span")
        expected = "expired" if fold.last_close == "lapsed" else "released"
        if event["reason"] != expected:
            raise refuse(f"event {seq} reason does not match how the prior span closed")
    fold.spans.append((event["executor_id"], event["fence"]))
    fold.custody = {"executor_id": event["executor_id"],
                    "subject_path": event["subject_path"], "fence": event["fence"]}


def _fold_custody(event: dict, seq: int, fold: _CustodyFold, state: str,
                  entered_terminal: int | None, refuse: Callable[[str], StateInvalid]) -> None:
    """Check one custody event's envelope and fence, then fold it (D11)."""
    event_type = event["type"]
    if set(event) != _EVENT_KEYS[event_type]:
        raise refuse(f"event {seq} is not the closed {event_type} event")
    if type(event["seq"]) is not int or event["seq"] != seq:
        raise refuse(f"event {seq} does not carry seq {seq}")
    if not _is_timestamp(event["at"]):
        raise refuse(f"event {seq} at is not a YYYY-MM-DDTHH:MM:SS.mmmZ timestamp")
    violation = fence_violation(event["fence"], fold.keys)
    if violation is not None:
        raise refuse(f"event {seq} {violation}")
    if event_type in ("lease_acquired", "lease_reacquired"):
        _fold_opening(event, seq, fold, refuse)
    else:
        _fold_closing(event, seq, fold, state, entered_terminal, refuse)


def _validate_state(document: Any, transaction_id: str, root: Path) -> None:
    """Refuse (StateInvalid) any document that is not a valid transaction-state/v2."""
    def refuse(rule: str) -> StateInvalid:
        return StateInvalid(f"{transaction_id}: {rule}")

    if type(document) is not dict:
        raise refuse("state.json is not a JSON object")
    if document.get("schema") != SCHEMA:
        raise refuse(f"schema {document.get('schema')!r} is not {SCHEMA}")
    if set(document) != _STATE_KEYS:
        raise refuse(f"state.json is not the closed {SCHEMA} key set")
    if not _is_id(document["transaction_id"]) or document["transaction_id"] != transaction_id:
        raise refuse("transaction_id is not a rel_ UUIDv7 equal to its directory name")
    creation_key = document["creation_key"]
    if type(creation_key) is not str or not creation_key:
        raise refuse("creation_key is not a non-empty string")
    try:
        indexed = _read_index(root, creation_key)
    except UnicodeEncodeError as error:
        raise refuse("creation_key is not encodable as UTF-8") from error
    if indexed != transaction_id:
        raise refuse("creation_key index entry does not point back to this transaction")
    if type(document["subject"]) is not dict:
        raise refuse("subject is not a JSON object")
    keys = document["concurrency_keys"]
    if type(keys) is not list:
        raise refuse("concurrency_keys is not a list")
    violation = _key_set_violation(keys)
    if violation is not None:
        raise refuse(violation)
    if keys != sorted(keys):
        raise refuse("concurrency_keys is not sorted")
    events = document["events"]
    if type(events) is not list or not events:
        raise refuse("events is not a non-empty list")
    first = events[0]
    if type(first) is not dict or set(first) != _CREATED_KEYS:
        raise refuse("event 1 is not the closed created event")
    if type(first["seq"]) is not int or first["seq"] != 1 or first["type"] != "created":
        raise refuse("event 1 is not seq 1 of type created")
    if not _is_timestamp(first["at"]):
        raise refuse("event 1 at is not a YYYY-MM-DDTHH:MM:SS.mmmZ timestamp")
    state, parked, entered_terminal = "created", None, None
    fold = _CustodyFold(keys)
    for seq, event in enumerate(events[1:], start=2):
        if state in TERMINALS and not (
                entered_terminal == seq - 1 and type(event) is dict
                and event.get("type") == "lease_released" and event.get("reason") == "terminal"):
            raise refuse(f"event {seq} follows the terminal state {state}")
        if type(event) is not dict:
            raise refuse(f"event {seq} is not a JSON object")
        event_type = event.get("type")
        match event_type:
            case "transitioned":
                state, parked = _fold_transitioned(event, seq, state, parked, refuse)
                if state in TERMINALS:
                    entered_terminal = seq
            case str() if event_type in CUSTODY_EVENTS:
                _fold_custody(event, seq, fold, state, entered_terminal, refuse)
            case _:
                raise refuse(f"event {seq} has unknown event type {event_type!r}")
    custody = fold.custody
    if state in TERMINALS and custody is not None:
        raise refuse(f"terminal state {state} still holds custody")
    if type(document["state"]) is not str or document["state"] != state:
        raise refuse(f"state does not equal the folded state {state}")
    stored_parked = document["parked_from"]
    if not (stored_parked is None and parked is None
            or type(stored_parked) is str and stored_parked == parked):
        raise refuse("parked_from does not equal the folded parked_from")
    stored_custody = document["custody"]
    if not (stored_custody is None and custody is None
            or type(stored_custody) is dict and custody is not None
            and serialize(stored_custody) == serialize(custody)):
        raise refuse("custody does not equal the folded custody")
    if type(document["revision"]) is not int or document["revision"] != len(events):
        raise refuse("revision does not equal the number of events")


def _snapshot(document: dict) -> Transaction:
    projection = document["custody"]
    custody = None
    if projection is not None:
        custody = Custody(
            transaction_id=document["transaction_id"],
            executor_id=projection["executor_id"],
            subject_path=projection["subject_path"],
            fence=MappingProxyType({key: MappingProxyType(copy.deepcopy(entry))
                                    for key, entry in projection["fence"].items()}))
    return Transaction(
        transaction_id=document["transaction_id"],
        creation_key=document["creation_key"],
        subject=MappingProxyType(copy.deepcopy(document["subject"])),
        state=document["state"],
        parked_from=document["parked_from"],
        revision=document["revision"],
        events=tuple(MappingProxyType(copy.deepcopy(event))
                     for event in document["events"]),
        concurrency_keys=tuple(document["concurrency_keys"]),
        custody=custody,
    )


def _require_custody_shape(custody: Any) -> None:
    """Refuse (StateInvalid), before any lock, a credential that is not a well-formed
    `Custody` (D21)."""
    if not isinstance(custody, Custody):
        raise StateInvalid(f"{custody!r}: not a Custody credential")
    where = f"{custody.transaction_id!r}: custody"
    for name in ("transaction_id", "executor_id"):
        value = getattr(custody, name)
        if type(value) is not str or not value:
            raise StateInvalid(f"{where} {name} is not a non-empty string")
    violation = fence_violation(custody.fence)
    if violation is not None:
        raise StateInvalid(f"{where} {violation}")


def _bound_path(document: dict) -> str | None:
    """The subject path the first acquisition bound, or None before any (D5)."""
    for event in document["events"]:
        if event["type"] == "lease_acquired":
            return event["subject_path"]
    return None


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
    if type(subject) is not dict:
        raise StateInvalid(f"{where}: subject is not a JSON object")
    try:
        loaded = strict_loads(serialize(subject))
    except (TypeError, ValueError) as error:
        raise StateInvalid(f"{where}: subject is not strict JSON ({error})") from error
    if loaded != subject or telemetry_digest(loaded) != telemetry_digest(subject):
        raise StateInvalid(f"{where}: subject does not survive a strict JSON round trip")
    violation = _key_set_violation(concurrency_keys)
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
        if not _is_id(transaction_id):
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
        return _snapshot(self._validated_document(transaction_id))

    def advance(self, transaction_id: str, target: str, *, reason: str,
                external_state: str | None = None) -> Transaction:
        """Move one transaction along one allowed edge under its lock (D5, D7-D10, D13).

        Every refusal happens before any write; the lock file is never created.
        """
        with self._transaction_locked(transaction_id):
            return self._advance_locked(transaction_id, target, reason, external_state)

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
                        external_state: Any) -> Transaction:
        prior = self._validated_document(transaction_id)
        source = prior["state"]
        where = f"{transaction_id}: {source} -> {target!r}"
        if source in TERMINALS:
            raise TransitionRefused(f"{where}: source is terminal")
        if type(target) is not str or target not in STATES:
            raise TransitionRefused(f"{where}: target is not a known state")
        if not _edge_allowed(source, prior["parked_from"], target):
            raise TransitionRefused(f"{where}: edge is not allowed")
        if type(reason) is not str or not reason:
            raise TransitionRefused(f"{where}: reason is not a non-empty string")
        if external_state is not None and (type(external_state) is not str
                                           or external_state not in _EXTERNAL_STATES):
            raise TransitionRefused(f"{where}: external_state is not known, unknown or None")
        if target in TERMINALS and external_state != "known":
            raise TransitionRefused(f"{where}: terminal target needs known external state")
        candidate = copy.deepcopy(prior)
        candidate["events"].append({
            "seq": prior["revision"] + 1, "type": "transitioned", "at": _format_at(self._now()),
            "from": source, "to": target, "reason": reason,
            "external_state": external_state})
        if target == "attention_required":
            candidate["parked_from"] = source
        elif source == "attention_required":
            candidate["parked_from"] = None
        candidate["state"] = target
        candidate["revision"] = len(candidate["events"])
        if candidate["events"][:-1] != prior["events"]:
            raise StateInvalid(f"{transaction_id}: prior events are not the new history's "
                               f"prefix")
        _validate_state(candidate, transaction_id, self.root)
        directory = self.root / transaction_id
        atomic_write(directory, directory / "state.json", candidate)
        return _snapshot(candidate)

    def create(self, creation_key: str, subject: dict, *,
               concurrency_keys: Collection[str]) -> Transaction:
        """Create the transaction for `creation_key`, or return the one it already names.

        The concurrency key set is fixed here, stored sorted, and compared with the
        subject when the key already names a transaction (D4).
        """
        _require_creatable(self.root, creation_key, subject, concurrency_keys)
        keys = sorted(concurrency_keys)
        at = _format_at(self._now())
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
                return _snapshot(document)
            document = {
                "schema": SCHEMA, "transaction_id": transaction_id,
                "creation_key": creation_key, "subject": copy.deepcopy(subject),
                "state": "created", "parked_from": None, "revision": 1,
                "events": [{"seq": 1, "type": "created", "at": at}],
                "concurrency_keys": keys, "custody": None,
            }
            _validate_state(document, transaction_id, self.root)
            atomic_write(directory, directory / "state.json", document)
            return _snapshot(document)
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
        if not _is_subject_path(subject_path):
            raise StateInvalid(f"{where}: subject_path {subject_path!r} is not an absolute "
                               f"normalized path")
        if type(ttl_ms) is not int or ttl_ms < 1:
            raise StateInvalid(f"{where}: ttl_ms {ttl_ms!r} is not a positive integer")
        with self._transaction_locked(transaction_id):
            prior = self._validated_document(transaction_id)
            if prior["state"] in TERMINALS:
                raise TransitionRefused(f"{where}: state {prior['state']} is terminal")
            bound = _bound_path(prior)
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
        return _snapshot(candidate)

    def _acquisition(self, prior: dict, executor_id: str, subject_path: str,
                     now: int) -> dict:
        """The validated candidate an acquisition at `now` writes; refuses a live key."""
        transaction_id = prior["transaction_id"]
        candidate = copy.deepcopy(prior)
        events = candidate["events"]
        at = _format_at(now)
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
        _require_custody_shape(custody)
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
                    "at": _format_at(now), "fence": fence, "reason": "released"})
                candidate["custody"] = None
                candidate["revision"] = len(candidate["events"])
                _validate_state(candidate, transaction_id, self.root)
                directory = self.root / transaction_id
                atomic_write(directory, directory / "state.json", candidate)
                self._leases.clear(fence)
        return _snapshot(candidate)

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
