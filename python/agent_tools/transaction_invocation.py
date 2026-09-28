"""The administrative protocol's document rules for the transaction core (#206 D1): the
vocabularies (inspection outcomes, effect results, error classes, refusal reasons), the retry
budget (`MAX_ATTEMPTS` attempts within `RETRY_WINDOW_MS`), the action name and parameter rule
(`action_violation`), the deterministic action id (`action_id`) that is also the idempotency
key an effect receives, the closed action event key sets (`ACTION_EVENT_KEYS`), the rule an
action event breaks against the fold before it (`action_event_violation`), the fold itself
(`apply_action_event`, `fold_actions`, `ActionFold`), the inspect and invoke result checks
(`inspect_result_violation`, `invoke_result_violation`), the request an effect receives
(`effect_request`) and the per-action view a snapshot derives (`action_views`).

Admission is decided here too: `satisfied` says an invoke is a no-op, and `refusal` is the one
home of the four admission rules, in order: a fresh `absent` inspection under the held fence
(`inspection_required`, `not_absent`), a retry-safe predecessor (`not_retryable`), at most
`MAX_ATTEMPTS` attempts (`budget_exhausted`) and a retry within `RETRY_WINDOW_MS` of the first
retryable failure, inclusive (`window_closed`). `refused_error` is the one construction path
for `InvocationRefused` and raises `ValueError` for a reason outside `REFUSAL_REASONS`. The
module reads no file, lock or clock; the caller passes the time `refusal` judges at.
"""

import copy
import dataclasses
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_custody import fence_violation
from agent_tools.transaction_storage import (
    InvocationRefused, StateInvalid, format_at, json_object_violation, parse_at)

OUTCOMES = ("absent", "in_progress", "satisfied", "diverged", "unknown")
RESULTS = ("accepted", "rejected", "unknown")
ERROR_CLASSES = ("transient_transport", "provider_throttled", "provider_unavailable",
                 "invalid_input", "authorization_denied", "precondition_failed",
                 "unsupported_operation")
RETRY_SAFE_CLASSES = frozenset(ERROR_CLASSES[:3])
MAX_ATTEMPTS = 3
RETRY_WINDOW_MS = 900_000
EFFECT_STATES = ("publishing", "activating")
REFUSAL_REASONS = ("inspection_required", "not_absent", "not_retryable",
                   "budget_exhausted", "window_closed", "state_not_effectful",
                   "attempt_in_flight")

_ENVELOPE_KEYS = frozenset({"seq", "type", "at"})
ACTION_EVENT_KEYS: Mapping[str, frozenset[str]] = MappingProxyType({
    "action_declared": _ENVELOPE_KEYS | {"action_id", "name", "parameters"},
    "action_inspected": _ENVELOPE_KEYS | {"action_id", "outcome", "reference", "fence"},
    "invocation_intended": _ENVELOPE_KEYS | {"action_id", "attempt", "fence"},
    "invocation_returned": _ENVELOPE_KEYS | {"action_id", "attempt", "result", "error_class",
                                             "reference", "fence"},
})
_INSPECT_RESULT_KEYS = frozenset({"outcome", "reference"})
_INVOKE_RESULT_KEYS = frozenset({"result", "error_class", "reference"})


@dataclasses.dataclass
class ActionFold:
    """What the history says about one declared action (#206 D2, D6).

    `returned` is the latest attempt's `invocation_returned`, `inspection` the latest
    `action_inspected` as `{outcome, fence, at}`, and `first_failure_ms` the `at` of the
    first `absent` inspection after attempt 1, in epoch milliseconds.
    """

    action_id: str
    name: str
    attempts: int = 0
    open: bool = False
    intent_fence: dict | None = None
    returned: dict | None = None
    inspection: dict | None = None
    first_failure_ms: int | None = None


def action_violation(name: Any, parameters: Any) -> str | None:
    """The first rule an action's name or parameters break, or None (#206 D4)."""
    if type(name) is not str or not name:
        return f"name {name!r} is not a non-empty string"
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return f"name {name!r} is not encodable as UTF-8"
    violation = json_object_violation(parameters)
    return None if violation is None else f"parameters {violation}"


def action_id(transaction_id: str, name: str, parameters: dict) -> str:
    """`act_` + the first 32 hex digits of the digest of [transaction id, name,
    parameters]; also the idempotency key an effect receives (#206 D4)."""
    if type(transaction_id) is not str or not transaction_id:
        raise StateInvalid(f"{transaction_id!r}: action_id: transaction_id is not a "
                           f"non-empty string")
    violation = action_violation(name, parameters)
    if violation is not None:
        raise StateInvalid(f"{transaction_id}: action_id: {violation}")
    return "act_" + telemetry_digest([transaction_id, name, parameters])[7:39]


def _outcome_violation(outcome: Any) -> str | None:
    if type(outcome) is not str or outcome not in OUTCOMES:
        return "outcome is not absent, in_progress, satisfied, diverged or unknown"
    return None


def _reference_violation(reference: Any) -> str | None:
    if type(reference) is not str or not reference:
        return "reference is not a non-empty string"
    return None


def _returned_violation(result: Any, error_class: Any, reference: Any) -> str | None:
    if type(result) is not str or result not in RESULTS:
        return "result is not accepted, rejected or unknown"
    if (error_class is not None if result == "accepted"
            else type(error_class) is not str or error_class not in ERROR_CLASSES):
        return "error_class does not match the result"
    return _reference_violation(reference)


def invoke_result_violation(result: Any) -> str | None:
    """The first rule an `invoke` result breaks, or None: the closed
    `{result, error_class, reference}` object, `error_class` null exactly when the result
    is `accepted` and otherwise one of `ERROR_CLASSES` (#206 D11)."""
    if type(result) is not dict or set(result) != _INVOKE_RESULT_KEYS:
        return "invoke result is not the closed {result, error_class, reference} object"
    return _returned_violation(result["result"], result["error_class"], result["reference"])


def inspect_result_violation(result: Any) -> str | None:
    """The first rule an `inspect` result breaks, or None: the closed
    `{outcome, reference}` object (#206 D11)."""
    if type(result) is not dict or set(result) != _INSPECT_RESULT_KEYS:
        return "inspect result is not the closed {outcome, reference} object"
    return _outcome_violation(result["outcome"]) or _reference_violation(result["reference"])


def action_event_violation(event: dict, actions: dict[str, ActionFold], *,
                           transaction_id: str, keys: list[str], open_fence: dict | None,
                           state: str) -> str | None:
    """The rule one envelope-checked action event breaks against the actions folded before
    it, the open span's fence (None outside a span) and the folded `state`, or None
    (#206 D2, D14, D17)."""
    event_type = event["type"]
    identity = event["action_id"]
    if type(identity) is not str:
        return "action_id is not a string"
    if event_type == "action_declared":
        if identity in actions:
            return f"action_id {identity!r} is declared twice"
        violation = action_violation(event["name"], event["parameters"])
        if violation is not None:
            return violation
        if identity != action_id(transaction_id, event["name"], event["parameters"]):
            return f"action_id {identity!r} does not re-derive from its name and parameters"
        return None
    if identity not in actions:
        return f"{event_type} action_id {identity!r} has no earlier action_declared"
    if "fence" in event:
        violation = fence_violation(event["fence"], keys)
        if violation is not None:
            return violation
        if open_fence is None:
            return f"{event_type} sits outside an open custody span"
        if event["fence"] != open_fence:
            return f"{event_type} fence does not equal the open span's fence"
    entry = actions[identity]
    if event_type == "action_inspected":
        violation = (_outcome_violation(event["outcome"])
                     or _reference_violation(event["reference"]))
        if (violation is None and entry.open and entry.returned is None
                and event["fence"] == entry.intent_fence):
            return "action_inspected closes a return-less attempt under its intent's fence"
        return violation
    attempt, latest = event["attempt"], entry.attempts
    if event_type == "invocation_intended":
        if type(attempt) is not int or attempt != latest + 1:
            return f"invocation_intended attempt {attempt!r} does not follow attempt {latest}"
        if attempt > MAX_ATTEMPTS:
            return f"invocation_intended attempt {attempt} exceeds {MAX_ATTEMPTS}"
        if state not in EFFECT_STATES:
            return "invocation_intended sits outside publishing and activating"
        inspection = entry.inspection
        if (entry.open or inspection is None or inspection["outcome"] != "absent"
                or inspection["fence"] != event["fence"]):
            return "invocation_intended does not follow an absent inspection under its fence"
        if attempt > 1 and not retry_safe(entry):
            return "invocation_intended retry follows an attempt that is not retry-safe"
        return None
    if event_type == "invocation_returned":
        if not entry.open:
            return "invocation_returned follows no open attempt"
        if type(attempt) is not int or attempt != latest:
            return "invocation_returned attempt does not name the open attempt"
        if entry.returned is not None:
            return f"invocation_returned attempt {latest} already returned"
        if event["fence"] != entry.intent_fence:
            return "invocation_returned fence does not equal its intent's"
        return _returned_violation(event["result"], event["error_class"], event["reference"])
    raise ValueError(f"action_event_violation: unhandled action event type {event_type!r}")


def apply_action_event(event: dict, actions: dict[str, ActionFold]) -> None:
    """Fold one valid action event into `actions` (#206 D2, D6)."""
    event_type = event["type"]
    if event_type == "action_declared":
        actions[event["action_id"]] = ActionFold(event["action_id"], event["name"])
        return
    entry = actions[event["action_id"]]
    if event_type == "action_inspected":
        entry.inspection = {"outcome": event["outcome"], "fence": event["fence"],
                            "at": event["at"]}
        entry.open = False
        if (event["outcome"] == "absent" and entry.attempts >= 1
                and entry.first_failure_ms is None):
            entry.first_failure_ms = parse_at(event["at"])
        return
    if event_type == "invocation_intended":
        entry.attempts, entry.open = event["attempt"], True
        entry.intent_fence, entry.returned = event["fence"], None
        return
    if event_type == "invocation_returned":
        entry.returned = {key: event[key] for key in _INVOKE_RESULT_KEYS}
        return
    raise ValueError(f"apply_action_event: unhandled action event type {event_type!r}")


def fold_actions(events: Sequence[Mapping[str, Any]]) -> dict[str, ActionFold]:
    """Every declared action of a valid history, in declaration order."""
    actions: dict[str, ActionFold] = {}
    for event in events:
        if event["type"] in ACTION_EVENT_KEYS:
            apply_action_event(event, actions)
    return actions


def retry_safe(entry: ActionFold) -> bool:
    """Whether the latest attempt was interrupted (it has no recorded return) or returned a
    non-`accepted` result of a retry-safe class (#206 D6)."""
    returned = entry.returned
    return returned is None or (returned["result"] != "accepted"
                                and returned["error_class"] in RETRY_SAFE_CLASSES)


def satisfied(entry: ActionFold | None) -> bool:
    """Whether the action exists, has no open attempt and last read `satisfied` (#206 D7)."""
    return (entry is not None and not entry.open and entry.inspection is not None
            and entry.inspection["outcome"] == "satisfied")


def refusal(entry: ActionFold | None, *, held_fence: dict, now_ms: int) -> str | None:
    """The reason the next attempt is not admitted at `now_ms` under `held_fence`, or None:
    rules 1-4 in order (#206 D5, D6)."""
    inspection = None if entry is None or entry.open else entry.inspection
    if inspection is None or inspection["fence"] != held_fence:
        return "inspection_required"
    if inspection["outcome"] != "absent":
        return "not_absent"
    attempt = entry.attempts + 1
    if attempt > 1 and not retry_safe(entry):
        return "not_retryable"
    if attempt > MAX_ATTEMPTS:
        return "budget_exhausted"
    if attempt > 1 and now_ms - entry.first_failure_ms > RETRY_WINDOW_MS:
        return "window_closed"
    return None


def refused_error(transaction_id: str, identity: str, reason: str) -> InvocationRefused:
    """The one construction path for `InvocationRefused`; a `reason` outside
    `REFUSAL_REASONS` is a programming error (`ValueError`) (#206 D21)."""
    if reason not in REFUSAL_REASONS:
        raise ValueError(f"refused_error: {reason!r} is not a refusal reason")
    return InvocationRefused(f"{transaction_id}: action {identity} refused: {reason}",
                             reason=reason)


def status(entry: ActionFold) -> str:
    """`open` while an attempt awaits inspection, else the latest inspection's outcome,
    else `declared` (#206 D2)."""
    if entry.open:
        return "open"
    return "declared" if entry.inspection is None else entry.inspection["outcome"]


def action_views(events: Sequence[Mapping[str, Any]]) -> list[dict]:
    """One view per declared action, in declaration order; derived, never stored
    (#206 D2, D17)."""
    views = []
    for entry in fold_actions(events).values():
        current = status(entry)
        views.append({
            "action_id": entry.action_id, "name": entry.name, "attempts": entry.attempts,
            "status": current,
            "last_error_class": None if entry.returned is None
            else entry.returned["error_class"],
            "retry_eligible": (current == "absent" and entry.attempts < MAX_ATTEMPTS
                               and (entry.attempts == 0 or retry_safe(entry))),
            "retry_deadline_at": None if entry.first_failure_ms is None
            else format_at(entry.first_failure_ms + RETRY_WINDOW_MS),
        })
    return views


def effect_request(document: dict, identity: str, name: str, parameters: dict,
                   attempt: int) -> Mapping[str, Any]:
    """The read-only request an effect receives, carrying deep copies of `parameters` and
    the held fence (#206 D3)."""
    return MappingProxyType({
        "transaction_id": document["transaction_id"], "action_id": identity, "name": name,
        "parameters": copy.deepcopy(parameters),
        "fence": copy.deepcopy(document["custody"]["fence"]), "attempt": attempt})
