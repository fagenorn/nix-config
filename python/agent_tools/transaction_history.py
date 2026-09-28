"""The transaction-state/v2 document model of the transaction core (#205 D33): the
lifecycle vocabularies, the `Custody` credential and `Transaction` snapshot types, the
credential shape checks, the pure history validator and the snapshot fold. It reads no
file, lock or clock: `validate_state` takes the creation-key index lookup as a callable,
which `agent_tools.transaction_core` binds to its store root. It also composes what a reap
appends to a lapsed span (`reaped`) and a late owner result's event (`owner_result_event`),
and answers whether an executor and fence were ever issued a span (`span_issued`). The
`at`-timestamp codec (`format_at`, `parse_at`) and the strict JSON object rule
(`json_object_violation`) that a created `subject` and a late `result` share are imported
from `agent_tools.transaction_storage`, not held here.
"""

import copy
import dataclasses
import datetime
import os
import re
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import Any

from agent_tools.transaction_custody import (
    CUSTODY_EVENTS, EVIDENCE_FORMS, admissibility, fence_violation)
from agent_tools.transaction_storage import (
    StateInvalid, format_at, json_object_violation, parse_at, serialize)

SCHEMA = "transaction-state/v2"

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
EXTERNAL_STATES = ("known", "unknown", None)

_ID_PATTERN = re.compile(
    r"rel_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
_AT_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")
_STATE_KEYS = frozenset({"schema", "transaction_id", "creation_key", "subject", "state",
                         "parked_from", "revision", "events", "concurrency_keys", "custody"})
_KEY_COLLECTIONS = (list, tuple, set, frozenset)
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
    "evidence_recorded": _ENVELOPE_KEYS | {"evidence_id", "form", "reference", "fence"},
    "interval_opened": _ENVELOPE_KEYS | {"evidence_id", "fence"},
    "grant_issued": _ENVELOPE_KEYS | {"grant_id", "actor", "fence"},
    "stop_synthesized": _ENVELOPE_KEYS | {"fence", "executor_id", "reason"},
    "owner_result": _ENVELOPE_KEYS | {"executor_id", "fence", "custody", "supersedes",
                                      "result"},
})
_FENCED_EVENTS = frozenset({"evidence_recorded", "interval_opened", "grant_issued"})
_OUTCOME_EVENTS = frozenset({"stop_synthesized", "owner_result"})
_OPENING_EVENTS = ("lease_acquired", "lease_reacquired")
_RELEASE_REASONS = ("released", "quiesced", "terminal")


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
    them cannot reach disk. `evidence` and `grants` entries carry verdicts
    derived from the history on every load; they are never stored.
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
    evidence: tuple[Mapping[str, Any], ...]
    grants: tuple[Mapping[str, Any], ...]


def edge_allowed(source: str, parked_from: str | None, target: str) -> bool:
    """Contract: `target` is in TRANSITIONS[source]; from a parking, a forward-state
    target must be the recorded `parked_from` (D15)."""
    if target not in TRANSITIONS.get(source, frozenset()):
        return False
    if source == "attention_required" and target in FORWARD:
        return target == parked_from
    return True


def is_id(value: object) -> bool:
    return type(value) is str and _ID_PATTERN.fullmatch(value) is not None


def parked_since(events: list[dict]) -> int | None:
    """Epoch ms of the transition that entered the current parked run from an unparked
    state, or None when the history is not parked (D28)."""
    start = None
    for event in events:
        if event["type"] != "transitioned":
            continue
        if event["to"] in PARKINGS and event["from"] not in PARKINGS:
            start = parse_at(event["at"])
        elif event["to"] not in PARKINGS:
            start = None
    return start


def _is_timestamp(value: object) -> bool:
    if type(value) is not str or _AT_PATTERN.fullmatch(value) is None:
        return False
    try:
        datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return False
    return True


def key_set_violation(keys: Any) -> str | None:
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


def _check_envelope(event: dict, seq: int, keys: frozenset[str],
                    refuse: Callable[[str], StateInvalid]) -> None:
    """Refuse an event whose key set is not `keys`, whose `seq` is not `seq`, or whose
    `at` is not a timestamp, in that order."""
    if set(event) != keys:
        raise refuse(f"event {seq} is not the closed {event['type']} event")
    if type(event["seq"]) is not int or event["seq"] != seq:
        raise refuse(f"event {seq} does not carry seq {seq}")
    if not _is_timestamp(event["at"]):
        raise refuse(f"event {seq} at is not a YYYY-MM-DDTHH:MM:SS.mmmZ timestamp")


def _fold_transitioned(event: dict, seq: int, state: str, parked: str | None,
                      refuse: Callable[[str], StateInvalid]) -> tuple[str, str | None]:
    """Check one transitioned event against the fold; the folded (state, parked_from)."""
    _check_envelope(event, seq, _TRANSITIONED_KEYS, refuse)
    target = event["to"]
    if event["from"] != state:
        raise refuse(f"event {seq} from does not equal the folded state {state}")
    if type(target) is not str or target not in STATES:
        raise refuse(f"event {seq} to is not a known state")
    if not edge_allowed(state, parked, target):
        raise refuse(f"event {seq} edge {state} -> {target} is not allowed")
    if type(event["reason"]) is not str or not event["reason"]:
        raise refuse(f"event {seq} reason is not a non-empty string")
    external_state = event["external_state"]
    if external_state is not None and (type(external_state) is not str
                                       or external_state not in EXTERNAL_STATES):
        raise refuse(f"event {seq} external_state is not known, unknown or null")
    if target in TERMINALS and external_state != "known":
        raise refuse(f"event {seq} reaches terminal {target} without known external state")
    if target == "attention_required":
        parked = state
    elif state == "attention_required":
        parked = None
    return target, parked


def is_subject_path(value: object) -> bool:
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
    evidence_ids: dict[str, str] = dataclasses.field(default_factory=dict)
    grant_ids: set[str] = dataclasses.field(default_factory=set)
    stops: list[tuple[int, dict]] = dataclasses.field(default_factory=list)


def _id_violation(event: dict, fold: _CustodyFold) -> str | None:
    """The id rule a fenced record breaks against the ids folded before it, or None (D27)."""
    if event["type"] == "grant_issued":
        grant_id = event["grant_id"]
        return f"grant_id {grant_id!r} is reused" if grant_id in fold.grant_ids else None
    evidence_id = event["evidence_id"]
    seen = fold.evidence_ids.get(evidence_id)
    if event["type"] == "evidence_recorded" and event["form"] == "interval":
        if seen is None:
            return f"evidence_id {evidence_id!r} closes no opened interval"
        if seen == "opened":
            return None
    return None if seen is None else f"evidence_id {evidence_id!r} is reused"


def _note_id(event: dict, fold: _CustodyFold) -> None:
    """Fold one fenced record's id: a grant, an opened interval or a recorded item."""
    if event["type"] == "grant_issued":
        fold.grant_ids.add(event["grant_id"])
    else:
        fold.evidence_ids[event["evidence_id"]] = (
            "opened" if event["type"] == "interval_opened" else "recorded")


def fenced_id_violation(events: Sequence[Mapping[str, Any]],
                        event: Mapping[str, Any]) -> str | None:
    """The id rule the fenced record `event` breaks against the evidence, interval and
    grant ids `events` already hold, or None (D27)."""
    fold = _CustodyFold([])
    for prior in events:
        if prior["type"] in _FENCED_EVENTS:
            _note_id(prior, fold)
    return _id_violation(event, fold)


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
    if not is_subject_path(event["subject_path"]):
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


def _fold_fenced(event: dict, seq: int, fold: _CustodyFold,
                 refuse: Callable[[str], StateInvalid]) -> None:
    """Check one evidence, interval or grant record against the open span, then fold its
    id (D10, D15, D16, D27)."""
    event_type = event["type"]
    _check_envelope(event, seq, _EVENT_KEYS[event_type], refuse)
    for name in sorted(_EVENT_KEYS[event_type] - _ENVELOPE_KEYS - {"form", "fence"}):
        if type(event[name]) is not str or not event[name]:
            raise refuse(f"event {seq} {name} is not a non-empty string")
    if event_type == "evidence_recorded" and (type(event["form"]) is not str
                                              or event["form"] not in EVIDENCE_FORMS):
        raise refuse(f"event {seq} form is not event, snapshot or interval")
    if fold.custody is None:
        raise refuse(f"event {seq} {event_type} sits outside an open custody span")
    violation = fence_violation(event["fence"], fold.keys)
    if violation is not None:
        raise refuse(f"event {seq} {violation}")
    if event["fence"] != fold.custody["fence"]:
        raise refuse(f"event {seq} {event_type} fence does not equal the open span's fence")
    violation = _id_violation(event, fold)
    if violation is not None:
        raise refuse(f"event {seq} {violation}")
    _note_id(event, fold)


def _fold_outcome(event: dict, seq: int, previous: Any, fold: _CustodyFold,
                  refuse: Callable[[str], StateInvalid]) -> None:
    """Check one stop_synthesized or owner_result event; neither opens nor closes a span
    (D17, D18, D30)."""
    event_type = event["type"]
    _check_envelope(event, seq, _EVENT_KEYS[event_type], refuse)
    violation = fence_violation(event["fence"], fold.keys)
    if violation is not None:
        raise refuse(f"event {seq} {violation}")
    pair = (event["executor_id"], event["fence"])
    if event_type == "stop_synthesized":
        if not (type(previous) is dict and previous.get("type") == "lease_lapse_detected"
                and (previous["executor_id"], previous["fence"]) == pair):
            raise refuse(f"event {seq} stop_synthesized does not follow a "
                         f"lease_lapse_detected of its fence and executor")
        if type(event["reason"]) is not str or not event["reason"]:
            raise refuse(f"event {seq} reason is not a non-empty string")
        fold.stops.append((seq, event["fence"]))
        return
    if pair not in fold.spans:
        raise refuse(f"event {seq} owner_result names no custody span of that executor "
                     f"and fence")
    if type(event["custody"]) is not str or event["custody"] not in ("current", "stale"):
        raise refuse(f"event {seq} owner_result custody is not current or stale")
    supersedes = event["supersedes"]
    if supersedes is not None and (type(supersedes) is not int or (
            supersedes, event["fence"]) not in fold.stops):
        raise refuse(f"event {seq} owner_result supersedes names no earlier "
                     f"stop_synthesized of its fence")
    violation = json_object_violation(event["result"])
    if violation is not None:
        raise refuse(f"event {seq} owner_result result {violation}")


def _fold_custody(event: dict, seq: int, fold: _CustodyFold, state: str,
                  entered_terminal: int | None, refuse: Callable[[str], StateInvalid]) -> None:
    """Check one custody event's envelope and fence, then fold it (D11)."""
    event_type = event["type"]
    _check_envelope(event, seq, _EVENT_KEYS[event_type], refuse)
    violation = fence_violation(event["fence"], fold.keys)
    if violation is not None:
        raise refuse(f"event {seq} {violation}")
    if event_type in _OPENING_EVENTS:
        _fold_opening(event, seq, fold, refuse)
    else:
        _fold_closing(event, seq, fold, state, entered_terminal, refuse)


def validate_state(document: Any, transaction_id: str,
                   indexed: Callable[[str], str | None]) -> None:
    """Refuse (StateInvalid) any document that is not a valid transaction-state/v2."""
    def refuse(rule: str) -> StateInvalid:
        return StateInvalid(f"{transaction_id}: {rule}")

    if type(document) is not dict:
        raise refuse("state.json is not a JSON object")
    if document.get("schema") != SCHEMA:
        raise refuse(f"schema {document.get('schema')!r} is not {SCHEMA}")
    if set(document) != _STATE_KEYS:
        raise refuse(f"state.json is not the closed {SCHEMA} key set")
    if not is_id(document["transaction_id"]) or document["transaction_id"] != transaction_id:
        raise refuse("transaction_id is not a rel_ UUIDv7 equal to its directory name")
    creation_key = document["creation_key"]
    if type(creation_key) is not str or not creation_key:
        raise refuse("creation_key is not a non-empty string")
    try:
        named = indexed(creation_key)
    except UnicodeEncodeError as error:
        raise refuse("creation_key is not encodable as UTF-8") from error
    if named != transaction_id:
        raise refuse("creation_key index entry does not point back to this transaction")
    if type(document["subject"]) is not dict:
        raise refuse("subject is not a JSON object")
    keys = document["concurrency_keys"]
    if type(keys) is not list:
        raise refuse("concurrency_keys is not a list")
    violation = key_set_violation(keys)
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
            case str() if event_type in _FENCED_EVENTS:
                _fold_fenced(event, seq, fold, refuse)
            case str() if event_type in _OUTCOME_EVENTS:
                _fold_outcome(event, seq, events[seq - 2], fold, refuse)
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


def snapshot(document: dict) -> Transaction:
    projection = document["custody"]
    custody = None
    if projection is not None:
        custody = Custody(
            transaction_id=document["transaction_id"],
            executor_id=projection["executor_id"],
            subject_path=projection["subject_path"],
            fence=MappingProxyType({key: MappingProxyType(copy.deepcopy(entry))
                                    for key, entry in projection["fence"].items()}))
    evidence, grants = admissibility(document["events"])
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
        evidence=tuple(MappingProxyType(entry) for entry in evidence),
        grants=tuple(MappingProxyType(entry) for entry in grants),
    )


def require_custody_shape(custody: Any) -> None:
    """Refuse (StateInvalid), before any lock, a credential that is not a well-formed
    `Custody` (D21)."""
    if not isinstance(custody, Custody):
        raise StateInvalid(f"{custody!r}: not a Custody credential")
    where = f"{custody.transaction_id!r}: custody"
    for name in ("transaction_id", "executor_id"):
        value = getattr(custody, name)
        if type(value) is not str or not value:
            raise StateInvalid(f"{where} {name} is not a non-empty string")
    if not is_subject_path(custody.subject_path):
        raise StateInvalid(f"{where} subject_path {custody.subject_path!r} is not an absolute "
                           f"normalized path")
    violation = fence_violation(custody.fence)
    if violation is not None:
        raise StateInvalid(f"{where} {violation}")


def require_texts(custody: Any, operation: str, **values: Any) -> None:
    """Refuse (StateInvalid), before any lock, a malformed credential or any argument that
    is not a non-empty string (D21)."""
    require_custody_shape(custody)
    for name, value in values.items():
        if type(value) is not str or not value:
            raise StateInvalid(f"{custody.transaction_id}: {operation}: {name} {value!r} is "
                               f"not a non-empty string")


def bound_path(document: dict) -> str | None:
    """The subject path the first acquisition bound, or None before any (D5)."""
    for event in document["events"]:
        if event["type"] == "lease_acquired":
            return event["subject_path"]
    return None


def reaped(document: dict, at: str, reason: str) -> dict:
    """A deep-copied candidate recording the lapse of `document`'s held span at `at`: the
    lapse, a synthesized stop and, outside a parking, a park to `attention_required` with
    unknown external state; custody cleared (D17). The caller has checked the lapse."""
    candidate = copy.deepcopy(document)
    events = candidate["events"]
    held = candidate["custody"]
    for event_type, extra in (("lease_lapse_detected", {}),
                              ("stop_synthesized", {"reason": reason})):
        events.append({"seq": len(events) + 1, "type": event_type, "at": at,
                       "fence": copy.deepcopy(held["fence"]),
                       "executor_id": held["executor_id"], **extra})
    source = candidate["state"]
    if source not in PARKINGS:
        events.append({"seq": len(events) + 1, "type": "transitioned", "at": at,
                       "from": source, "to": "attention_required", "reason": reason,
                       "external_state": "unknown"})
        candidate["parked_from"] = source
        candidate["state"] = "attention_required"
    candidate["custody"] = None
    candidate["revision"] = len(events)
    return candidate


def span_issued(events: Sequence[Mapping[str, Any]], executor_id: str, fence: Any) -> bool:
    """Whether some opening event carries `executor_id` and a fence equal to `fence` (D18)."""
    return any(event["type"] in _OPENING_EVENTS and event["executor_id"] == executor_id
               and event["fence"] == fence for event in events)


def owner_result_event(document: dict, *, at: str, executor_id: str, fence: dict,
                       result: dict, lapsed: bool) -> dict:
    """The `owner_result` event a late result appends to `document` (D18, D34).

    `custody` is `current` only when the projection holds this executor and fence and
    `lapsed` is false, else `stale`; `supersedes` is the seq of the latest
    `stop_synthesized` with an equal fence, else None.
    """
    held = document["custody"]
    current = (held is not None and held["executor_id"] == executor_id
               and held["fence"] == fence and not lapsed)
    stops = [event["seq"] for event in document["events"]
             if event["type"] == "stop_synthesized" and event["fence"] == fence]
    return {"seq": document["revision"] + 1, "type": "owner_result", "at": at,
            "executor_id": executor_id, "fence": copy.deepcopy(fence),
            "custody": "current" if current else "stale",
            "supersedes": stops[-1] if stops else None, "result": copy.deepcopy(result)}
