"""The transaction core's local lease authority (#205 D2, D6-D8, D24).

One closed `transaction-lease/v1` record per concurrency key under
`<root>/leases/<sha256(key)>.json`, keeping the key's epoch forever and a
nullable holder; a holder is live while the clock reads below its `expires_at`.
Every record write happens under `<root>/leases.lock`, which the caller takes
through `LeaseAuthority.locked()` after its transaction lock. Reads take no lock.
`admissibility` is the pure fold that judges fenced evidence and grants (D15, D16, D20).
"""

import contextlib
import copy
import hashlib
import os
import re
import secrets
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from agent_tools.transaction_storage import (
    StateInvalid, atomic_write, fsync_directory, lstat_mode, open_lock, read_json,
    require_directory)

LEASE_SCHEMA = "transaction-lease/v1"
CUSTODY_EVENTS = frozenset({"lease_acquired", "lease_reacquired", "lease_released",
                            "lease_lapse_detected"})
INSTANCE_PATTERN = re.compile(r"lin_[0-9a-f]{32}")
EVIDENCE_FORMS = ("event", "snapshot", "interval")

_RECORD_KEYS = frozenset({"schema", "key", "epoch", "holder"})
_HOLDER_KEYS = frozenset({"transaction_id", "executor_id", "instance", "term", "ttl_ms",
                          "acquired_at", "expires_at", "renewal_count", "last_renewed_at"})
_FENCE_ENTRY_KEYS = frozenset({"epoch", "instance"})


def renewal_margin_ms(ttl_ms: int) -> int:
    """Remaining validity below which a renewal extends: half the TTL, floor 60 s (#92)."""
    return min(ttl_ms, max(ttl_ms // 2, 60000))


def _is_count(value: object, least: int) -> bool:
    return type(value) is int and value >= least


def fence_violation(fence: Any, keys: Iterable[str] | None = None) -> str | None:
    """The first fence rule `fence` breaks, or None (D10).

    A fence maps each key to the closed `{epoch, instance}` object, every entry
    sharing one instance; with `keys`, it covers exactly those keys.
    """
    if not isinstance(fence, Mapping) or not fence:
        return "fence is not a non-empty object"
    if keys is not None and set(fence) != set(keys):
        return "fence does not cover exactly the concurrency keys"
    for key, entry in fence.items():
        if type(key) is not str or not key:
            return f"fence key {key!r} is not a non-empty string"
        if not isinstance(entry, Mapping) or set(entry) != _FENCE_ENTRY_KEYS:
            return f"fence entry for {key!r} is not the closed epoch/instance object"
        if not _is_count(entry["epoch"], 1):
            return f"fence epoch for {key!r} is not an integer >= 1"
        instance = entry["instance"]
        if type(instance) is not str or INSTANCE_PATTERN.fullmatch(instance) is None:
            return f"fence instance for {key!r} is not lin_ + 32 lowercase hex"
    if len({entry["instance"] for entry in fence.values()}) != 1:
        return "fence entries do not share one instance"
    return None


def admissibility(events: Sequence[Mapping[str, Any]]) -> tuple[list[dict], list[dict]]:
    """The evidence and grant entries a validated history derives, in `seq` order (D20).

    The latest fence is the last opening's. `event` evidence is always
    admissible; `snapshot` needs the latest fence (else `fence_changed`);
    `interval` needs no custody event strictly between its open and its record
    (else `fence_discontinuity`) and then the latest fence (else `fence_changed`).
    A grant is valid while its fence is the latest and that span is still open.
    Pure: fresh dicts, no I/O.
    """
    custody_seqs, opened_at = [], {}
    latest, span_open = None, False
    for event in events:
        if event["type"] in CUSTODY_EVENTS:
            custody_seqs.append(event["seq"])
            span_open = event["type"] in ("lease_acquired", "lease_reacquired")
            if span_open:
                latest = event["fence"]
        elif event["type"] == "interval_opened":
            opened_at[event["evidence_id"]] = event["seq"]
    evidence, grants = [], []
    for event in events:
        if event["type"] == "evidence_recorded":
            void = None
            if event["form"] == "interval" and any(
                    opened_at[event["evidence_id"]] < seq < event["seq"] for seq in custody_seqs):
                void = "fence_discontinuity"
            elif event["form"] != "event" and event["fence"] != latest:
                void = "fence_changed"
            evidence.append({
                "evidence_id": event["evidence_id"], "form": event["form"],
                "reference": event["reference"], "fence": copy.deepcopy(event["fence"]),
                "seq": event["seq"], "admissible": void is None, "void_reason": void})
        elif event["type"] == "grant_issued":
            grants.append({
                "grant_id": event["grant_id"], "actor": event["actor"],
                "fence": copy.deepcopy(event["fence"]), "seq": event["seq"],
                "valid": span_open and event["fence"] == latest})
    return evidence, grants


def _holder_violation(holder: Any) -> str | None:
    if type(holder) is not dict or set(holder) != _HOLDER_KEYS:
        return "holder is not null or the closed holder object"
    for name in ("transaction_id", "executor_id"):
        if type(holder[name]) is not str or not holder[name]:
            return f"holder {name} is not a non-empty string"
    if type(holder["instance"]) is not str \
            or INSTANCE_PATTERN.fullmatch(holder["instance"]) is None:
        return "holder instance is not lin_ + 32 lowercase hex"
    for name, least in (("term", 1), ("ttl_ms", 1), ("acquired_at", 0), ("expires_at", 0),
                        ("renewal_count", 0)):
        if not _is_count(holder[name], least):
            return f"holder {name} is not an integer >= {least}"
    renewed = holder["last_renewed_at"]
    if renewed is not None and not _is_count(renewed, 0):
        return "holder last_renewed_at is not null or an integer >= 0"
    return None


class LeaseAuthority:
    """The lease records under one store `root` (D2)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.directory = root / "leases"

    def _path(self, key: str) -> Path:
        return self.directory / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.json"

    @contextlib.contextmanager
    def locked(self) -> Iterator[None]:
        """Hold `<root>/leases.lock`, taken non-blocking (D8)."""
        descriptor = open_lock(self.root / "leases.lock")
        try:
            yield
        finally:
            os.close(descriptor)

    def record(self, key: str) -> dict | None:
        """The validated record for `key`, or None when the key was never acquired."""
        if not require_directory(self.directory, missing_ok=True):
            return None
        path = self._path(key)
        if lstat_mode(path) is None:
            return None
        document = read_json(path)
        if type(document) is not dict or set(document) != _RECORD_KEYS:
            raise StateInvalid(f"{path}: lease record is not the closed {LEASE_SCHEMA} object")
        if document["schema"] != LEASE_SCHEMA:
            raise StateInvalid(f"{path}: lease schema is not {LEASE_SCHEMA}")
        if document["key"] != key:
            raise StateInvalid(f"{path}: lease record names a different key")
        if not _is_count(document["epoch"], 1):
            raise StateInvalid(f"{path}: lease epoch is not an integer >= 1")
        if document["holder"] is not None:
            violation = _holder_violation(document["holder"])
            if violation is not None:
                raise StateInvalid(f"{path}: {violation}")
        return document

    def span_lapsed(self, fence: Mapping[str, Mapping[str, Any]], now: int) -> bool:
        """Whether any key no longer holds the span live under its epoch and instance (D24)."""
        for key, entry in fence.items():
            record = self.record(key)
            holder = None if record is None else record["holder"]
            if (holder is None or record["epoch"] != entry["epoch"]
                    or holder["instance"] != entry["instance"]
                    or now >= holder["expires_at"]):
                return True
        return False

    def first_live_key(self, keys: Iterable[str], now: int) -> str | None:
        """The first of `keys`, in sorted order, whose holder is live at `now` (D6)."""
        for key in sorted(keys):
            record = self.record(key)
            if record is not None and record["holder"] is not None \
                    and now < record["holder"]["expires_at"]:
                return key
        return None

    def next_fence(self, keys: Iterable[str]) -> dict:
        """Every key at its next epoch under one fresh instance (D7)."""
        instance = "lin_" + secrets.token_hex(16)
        fence = {}
        for key in sorted(keys):
            record = self.record(key)
            fence[key] = {"epoch": (0 if record is None else record["epoch"]) + 1,
                          "instance": instance}
        return fence

    def hold(self, fence: Mapping[str, Mapping[str, Any]], *, transaction_id: str,
             executor_id: str, ttl_ms: int, now: int) -> None:
        """Write every key's record as held by the fence's span; caller holds `locked()`."""
        if not require_directory(self.directory, missing_ok=True):
            self.directory.mkdir(exist_ok=True)
            require_directory(self.directory, missing_ok=False)
            fsync_directory(self.root)
        for key, entry in fence.items():
            atomic_write(self.directory, self._path(key), {
                "schema": LEASE_SCHEMA, "key": key, "epoch": entry["epoch"], "holder": {
                    "transaction_id": transaction_id, "executor_id": executor_id,
                    "instance": entry["instance"], "term": 1, "ttl_ms": ttl_ms,
                    "acquired_at": now, "expires_at": now + ttl_ms, "renewal_count": 0,
                    "last_renewed_at": None}})

    def extend_if_due(self, fence: Mapping[str, Mapping[str, Any]], now: int) -> bool:
        """Whether the span still holds at `now` under `locked()`, renewing it in place
        once its earliest remaining validity is inside the margin (D13, D25).

        The caller holds `locked()` and has passed the lock-free fenced check. When
        `span_lapsed` holds at `now` (a successor took a key since that check), it
        returns False with nothing written. Otherwise it returns True, writing nothing outside
        the margin; inside it every record keeps its epoch and instance and gains one
        term and one renewal, renewed at `now` and valid for its recorded TTL from `now`.
        """
        if self.span_lapsed(fence, now):
            return False
        records = {key: self.record(key) for key in fence}
        holders = [record["holder"] for record in records.values()]
        remaining = min(holder["expires_at"] for holder in holders) - now
        if remaining >= min(renewal_margin_ms(holder["ttl_ms"]) for holder in holders):
            return True
        for key, record in records.items():
            holder = record["holder"]
            atomic_write(self.directory, self._path(key), {**record, "holder": {
                **holder, "term": holder["term"] + 1,
                "renewal_count": holder["renewal_count"] + 1, "last_renewed_at": now,
                "expires_at": now + holder["ttl_ms"]}})
        return True

    def clear(self, fence: Mapping[str, Mapping[str, Any]]) -> None:
        """Null the holder, keeping the epoch, on each record still naming the fence's
        instance; caller holds `locked()` (D24)."""
        for key, entry in fence.items():
            record = self.record(key)
            if record is not None and record["holder"] is not None \
                    and record["holder"]["instance"] == entry["instance"]:
                atomic_write(self.directory, self._path(key), {**record, "holder": None})
