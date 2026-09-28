"""The transaction core's first slice (#204).

A caller-rooted store of closed-schema transactions with a closed lifecycle:
`TransactionStore(root)` creates deduplicated transactions under an absolute,
pre-existing root and loads validated snapshots of them. Each transaction's
whole state and typed event history live in one `state.json` whose
`state`/`parked_from`/`revision` are a projection the validator re-folds from
the events. The module has no command and no caller yet.
"""

import copy
import dataclasses
import datetime
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import stat
import tempfile
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from agent_tools.canonical import (
    reject_duplicate_keys, reject_nonfinite_literal, telemetry_digest)

SCHEMA = "transaction-state/v1"
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
                         "parked_from", "revision", "events"})
_INDEX_KEYS = frozenset({"schema", "creation_key", "transaction_id"})
_CREATED_KEYS = frozenset({"seq", "type", "at"})
_TRANSITIONED_KEYS = frozenset({"seq", "type", "at", "from", "to", "reason",
                                "external_state"})
_EXTERNAL_STATES = ("known", "unknown", None)


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


@dataclasses.dataclass(frozen=True)
class Transaction:
    """A validated snapshot of one transaction.

    `subject` and each event are `types.MappingProxyType` views over deep
    copies. Only the top level is read-only: nested values stay mutable, but
    they are copies, so mutating them cannot reach disk.
    """

    transaction_id: str
    creation_key: str
    subject: Mapping[str, Any]
    state: str
    parked_from: str | None
    revision: int
    events: tuple[Mapping[str, Any], ...]


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


def _timestamp() -> str:
    """UTC now as `YYYY-MM-DDTHH:MM:SS.mmmZ`."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _is_timestamp(value: object) -> bool:
    if type(value) is not str or _AT_PATTERN.fullmatch(value) is None:
        return False
    try:
        datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return False
    return True


def _serialize(document: dict) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False) + "\n"


def _finite_float(literal: str) -> float:
    """`parse_float` hook: an overflowing literal such as `1e400` decodes to infinity."""
    value = float(literal)
    if not math.isfinite(value):
        raise ValueError(f"JSON number {literal} is not finite")
    return value


def _strict_loads(text: str) -> Any:
    return json.loads(text, object_pairs_hook=reject_duplicate_keys,
                      parse_constant=reject_nonfinite_literal, parse_float=_finite_float)


def _lstat_mode(path: Path) -> int | None:
    """The `lstat` mode of `path`, or None when nothing is there."""
    try:
        return os.lstat(path).st_mode
    except FileNotFoundError:
        return None


def _read_json(path: Path) -> Any:
    """Strictly load one regular, non-symlinked JSON file, else StateInvalid."""
    mode = _lstat_mode(path)
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
        return _strict_loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise StateInvalid(f"{path}: not strict JSON ({error})") from error


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(directory: Path, path: Path, document: dict) -> None:
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
            output.write(_serialize(document))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        _fsync_directory(directory)
    except BaseException as original_error:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                raise cleanup_error from original_error
        raise


def _index_path(root: Path, creation_key: str) -> Path:
    digest = hashlib.sha256(creation_key.encode("utf-8")).hexdigest()
    return root / "creation-keys" / f"{digest}.json"


def _require_directory(path: Path, missing_ok: bool) -> bool:
    """Refuse a symlinked or non-directory `path` by `lstat`; report whether it exists."""
    mode = _lstat_mode(path)
    if mode is None:
        if missing_ok:
            return False
        raise StateInvalid(f"{path}: directory is missing")
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise StateInvalid(f"{path}: not a directory")
    return True


def _read_index(root: Path, creation_key: str) -> str | None:
    """The id the key's index entry names, or None when there is no entry."""
    index_directory = root / "creation-keys"
    if not _require_directory(index_directory, missing_ok=True):
        return None
    path = _index_path(root, creation_key)
    if _lstat_mode(path) is None:
        return None
    entry = _read_json(path)
    if type(entry) is not dict or set(entry) != _INDEX_KEYS:
        raise StateInvalid(f"{path}: index entry is not the closed {INDEX_SCHEMA} object")
    if entry["schema"] != INDEX_SCHEMA:
        raise StateInvalid(f"{path}: index schema is not {INDEX_SCHEMA}")
    if entry["creation_key"] != creation_key:
        raise StateInvalid(f"{path}: index entry names a different creation key")
    if not _is_id(entry["transaction_id"]):
        raise StateInvalid(f"{path}: index entry transaction_id is not a rel_ UUIDv7")
    return entry["transaction_id"]


def _validate_state(document: Any, transaction_id: str, root: Path) -> None:
    """Refuse (StateInvalid) any document that is not a valid transaction-state/v1."""
    def refuse(rule: str) -> StateInvalid:
        return StateInvalid(f"{transaction_id}: {rule}")

    if type(document) is not dict or set(document) != _STATE_KEYS:
        raise refuse(f"state.json is not the closed {SCHEMA} key set")
    if document["schema"] != SCHEMA:
        raise refuse(f"schema is not {SCHEMA}")
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
    state, parked = "created", None
    for position, event in enumerate(events[1:], start=1):
        seq = position + 1
        if state in TERMINALS:
            raise refuse(f"event {seq} follows the terminal state {state}")
        if type(event) is not dict or set(event) != _TRANSITIONED_KEYS:
            raise refuse(f"event {seq} is not the closed transitioned event")
        if event["type"] != "transitioned":
            raise refuse(f"event {seq} is not of type transitioned")
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
        state = target
    if type(document["state"]) is not str or document["state"] != state:
        raise refuse(f"state does not equal the folded state {state}")
    stored_parked = document["parked_from"]
    if not (stored_parked is None and parked is None
            or type(stored_parked) is str and stored_parked == parked):
        raise refuse("parked_from does not equal the folded parked_from")
    if type(document["revision"]) is not int or document["revision"] != len(events):
        raise refuse("revision does not equal the number of events")


def _snapshot(document: dict) -> Transaction:
    return Transaction(
        transaction_id=document["transaction_id"],
        creation_key=document["creation_key"],
        subject=MappingProxyType(copy.deepcopy(document["subject"])),
        state=document["state"],
        parked_from=document["parked_from"],
        revision=document["revision"],
        events=tuple(MappingProxyType(copy.deepcopy(event))
                     for event in document["events"]),
    )


def _open_lock(path: Path) -> int:
    """Open (creating) a regular, non-symlinked lock file and take it non-blocking."""
    mode = _lstat_mode(path)
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


def _require_creatable(root: Path, creation_key: Any, subject: Any) -> None:
    """Refuse (StateInvalid) arguments that cannot form a valid v1 state (D16)."""
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
        loaded = _strict_loads(_serialize(subject))
    except (TypeError, ValueError) as error:
        raise StateInvalid(f"{where}: subject is not strict JSON ({error})") from error
    if loaded != subject or telemetry_digest(loaded) != telemetry_digest(subject):
        raise StateInvalid(f"{where}: subject does not survive a strict JSON round trip")


class TransactionStore:
    """Transactions under one absolute, pre-existing `root` the caller owns (D2)."""

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path) or not root.is_absolute() or not root.is_dir():
            raise TransactionError(f"{root}: store root is not an absolute existing directory")
        self.root = root

    def _existing_directory(self, transaction_id: str) -> Path:
        """The transaction's real directory, else UnknownTransaction; creates nothing (D16)."""
        if not _is_id(transaction_id):
            raise UnknownTransaction(f"{transaction_id!r}: not a rel_ UUIDv7 transaction id")
        directory = self.root / transaction_id
        mode = _lstat_mode(directory)
        if mode is None or stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise UnknownTransaction(f"{transaction_id}: no transaction directory under "
                                     f"{self.root}")
        return directory

    def _validated_document(self, transaction_id: str) -> dict:
        """Read and fully validate `state.json` without writing or locking (D13, D16)."""
        directory = self._existing_directory(transaction_id)
        lock_mode = _lstat_mode(directory / "lock")
        if lock_mode is None or stat.S_ISLNK(lock_mode) or not stat.S_ISREG(lock_mode):
            raise StateInvalid(f"{transaction_id}: lock file is missing or not a regular file")
        document = _read_json(directory / "state.json")
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
        directory = self._existing_directory(transaction_id)
        lock = directory / "lock"
        mode = _lstat_mode(lock)
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
            return self._advance_locked(transaction_id, target, reason, external_state)
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
            "seq": prior["revision"] + 1, "type": "transitioned", "at": _timestamp(),
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
        _atomic_write(directory, directory / "state.json", candidate)
        return _snapshot(candidate)

    def create(self, creation_key: str, subject: dict) -> Transaction:
        """Create the transaction for `creation_key`, or return the one it already names."""
        _require_creatable(self.root, creation_key, subject)
        descriptor = _open_lock(self.root / "creation.lock")
        try:
            return self._create_locked(creation_key, subject)
        finally:
            os.close(descriptor)

    def _create_locked(self, creation_key: str, subject: dict) -> Transaction:
        transaction_id = _read_index(self.root, creation_key)
        if transaction_id is None:
            transaction_id = _mint_id()
            index_directory = self.root / "creation-keys"
            if not _require_directory(index_directory, missing_ok=True):
                index_directory.mkdir(exist_ok=True)
                _require_directory(index_directory, missing_ok=False)
                _fsync_directory(self.root)
            _atomic_write(index_directory, _index_path(self.root, creation_key), {
                "schema": INDEX_SCHEMA, "creation_key": creation_key,
                "transaction_id": transaction_id})
        directory = self.root / transaction_id
        if not _require_directory(directory, missing_ok=True):
            directory.mkdir(exist_ok=True)
            _require_directory(directory, missing_ok=False)
            _fsync_directory(self.root)
        descriptor = _open_lock(directory / "lock")
        try:
            if _lstat_mode(directory / "state.json") is not None:
                document = self._validated_document(transaction_id)
                if document["creation_key"] != creation_key:
                    raise StateInvalid(
                        f"{transaction_id}: creation_key index {creation_key!r} names a "
                        f"transaction created under a different creation_key")
                if telemetry_digest(document["subject"]) != telemetry_digest(subject):
                    raise CreationConflict(
                        f"{transaction_id}: creation_key {creation_key!r} already names a "
                        f"different subject")
                return _snapshot(document)
            document = {
                "schema": SCHEMA, "transaction_id": transaction_id,
                "creation_key": creation_key, "subject": copy.deepcopy(subject),
                "state": "created", "parked_from": None, "revision": 1,
                "events": [{"seq": 1, "type": "created", "at": _timestamp()}],
            }
            _validate_state(document, transaction_id, self.root)
            _atomic_write(directory, directory / "state.json", document)
            return _snapshot(document)
        finally:
            os.close(descriptor)
