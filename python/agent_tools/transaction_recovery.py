"""Recovery (#208): the closed `RecoveryRefused` reasons and their one construction path, the
anchor and compatibility check requests and their result check, the admission and decision
halves of `verify_anchors`, the recovery event rules, the publication gate and the derived
`recovery` view.

A check request is a read-only mapping naming the unit by action id, the check, its
predicate and parameters, the unit's proof collector and the held fence; its result is the
closed `{outcome, reason, reference}` shape of `transaction_proof.closed_result_violation`,
so a check shares the observation outcome vocabulary (D21, D26). `anchor_requests` admits a
verification in `ready` only, one request per `restorable` unit in plan order, and
`anchors_events` refuses `rollback_anchor_missing` for the first result that is not
`satisfied`, else yields one `anchors_verified` stamped with the held fence (D7). A refusal
naming a unit says `<name> (<action id>)` (D23). `agent_tools.transaction_history` hands every
`RECOVERY_EVENT_KEYS` event to `recovery_event_violation` and every transition to
`recovery_transition_violation`, which refuses `ready -> publishing` for a plan with a
`restorable` unit unless an `anchors_verified` carries the open span's fence;
`agent_tools.transaction_core`'s `advance` applies the same gate through
`recovery_advance_violation` with the held fence (D7, D22).

`recovery_view` reads the `created` event's `recovery_plan_digest` and `recovers`
back-link, the latest `recovery_started` event's `effect_snapshot` and `selected` units,
and every `roll_forward_linked` event's child transaction id, in history order. It reads
those events by type only; the snapshot fold derives it on every load and it is never
stored (D12). Every function here is pure: the module reads no file, lock or clock.
"""

import copy
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from agent_tools.transaction_custody import fence_violation
from agent_tools.transaction_proof import closed_result_violation
from agent_tools.transaction_storage import RecoveryRefused

RECOVERY_REFUSAL_REASONS = (
    "state_not_ready", "state_not_attention", "state_not_recovering", "history_changed",
    "rollback_anchor_missing", "grant_required", "reconciliation_required",
    "undeclared_effect", "effect_uncertain", "no_effect", "unit_not_restorable",
    "restore_incompatible", "recovery_pending")

_ENVELOPE_KEYS = frozenset({"seq", "type", "at"})
RECOVERY_EVENT_KEYS: Mapping[str, frozenset[str]] = MappingProxyType({
    "anchors_verified": _ENVELOPE_KEYS | {"anchors", "fence"},
})
_ANCHOR_KEYS = frozenset({"unit", "reference"})


def recovery_refused(transaction_id: str, reason: str, detail: str) -> RecoveryRefused:
    """The one construction path for `RecoveryRefused`; a `reason` outside
    `RECOVERY_REFUSAL_REASONS` is a programming error (`ValueError`) (D16)."""
    if reason not in RECOVERY_REFUSAL_REASONS:
        raise ValueError(f"recovery_refused: {reason!r} is not a recovery refusal reason")
    return RecoveryRefused(f"{transaction_id}: recovery refused: {reason}: {detail}",
                           reason=reason)


def _restorable(document: dict) -> list[dict]:
    return [unit for unit in document["recovery_plan"]["units"]
            if unit["posture"] == "restorable"]


def unit_label(document: dict, identity: str) -> str:
    """`<name> (<action id>)` for the recovery unit whose action id is `identity` (D23)."""
    name = next(unit["name"] for unit in document["recovery_plan"]["units"]
                if unit["action_id"] == identity)
    return f"{name} ({identity})"


def check_requests(document: dict, check: str, units: list[dict]) -> list[Mapping[str, Any]]:
    """One read-only request per unit for its `check` (`anchor` or `compatibility`), with
    deep copies of the check's parameters and the held fence; the collector is the unit's
    proof collector (D7)."""
    collectors = {unit["action_id"]: unit["collector"]
                  for unit in document["proof_plan"]["units"]}
    return [MappingProxyType({
        "transaction_id": document["transaction_id"], "unit": unit["action_id"],
        "check": check, "predicate": unit[check]["predicate"],
        "collector": collectors[unit["action_id"]],
        "parameters": copy.deepcopy(unit[check]["parameters"]),
        "fence": copy.deepcopy(document["custody"]["fence"])}) for unit in units]


def check_result_violation(result: Any) -> str | None:
    """How a check `result` fails the closed observation result shape, or None (D21, D26)."""
    return closed_result_violation(result, "check result")


def anchor_requests(document: dict) -> list[Mapping[str, Any]]:
    """`verify_anchors`' admission: `state_not_ready` outside `ready`, else the anchor
    requests of every `restorable` unit, in plan order (D7)."""
    if document["state"] != "ready":
        raise recovery_refused(document["transaction_id"], "state_not_ready",
                               f"verify_anchors runs in ready, not {document['state']}")
    return check_requests(document, "anchor", _restorable(document))


def anchors_events(document: dict, requests: Sequence[Mapping],
                   results: Sequence[Mapping]) -> list[dict]:
    """`verify_anchors`' decision: nothing without requests; `rollback_anchor_missing`
    naming the first unit whose anchor is not `satisfied`, a missing and an unverifiable
    anchor alike; else one `anchors_verified` of each unit's reference under the held fence
    (D7)."""
    if not requests:
        return []
    for request, result in zip(requests, results):
        if result["outcome"] != "satisfied":
            raise recovery_refused(
                document["transaction_id"], "rollback_anchor_missing",
                f"unit {unit_label(document, request['unit'])} anchor {result['outcome']}")
    return [{"type": "anchors_verified",
             "anchors": [{"unit": request["unit"], "reference": result["reference"]}
                         for request, result in zip(requests, results)],
             "fence": copy.deepcopy(document["custody"]["fence"])}]


def recovery_event_violation(event: dict, events_before: Sequence[Mapping], document: dict, *,
                             keys: list[str], open_fence: dict | None,
                             state: str) -> str | None:
    """The first rule the closed-shape recovery `event` breaks, or None. An
    `anchors_verified` happens in `ready`, stamped with the open span's fence, and lists
    exactly the `restorable` units' action ids in plan order, each with a non-empty
    reference (D7)."""
    kind = event["type"]
    if state != "ready":
        return f"{kind} happens in {state}, not ready"
    if open_fence is None:
        return f"{kind} sits outside an open custody span"
    violation = fence_violation(event["fence"], keys)
    if violation is not None:
        return f"{kind} {violation}"
    if event["fence"] != open_fence:
        return f"{kind} fence does not equal the open span's fence"
    anchors = event["anchors"]
    if (type(anchors) is not list
            or any(type(entry) is not dict or set(entry) != _ANCHOR_KEYS
                   or type(entry["reference"]) is not str or not entry["reference"]
                   for entry in anchors)
            or [entry["unit"] for entry in anchors]
            != [unit["action_id"] for unit in _restorable(document)]):
        return (f"{kind} anchors are not each restorable unit's unit and non-empty "
                f"reference, in plan order")
    return None


def recovery_transition_violation(document: dict, events_before: Sequence[Mapping],
                                  source: str, target: str,
                                  open_fence: dict | None) -> str | None:
    """The gate `source -> target` breaks, or None: `ready -> publishing` for a plan with a
    `restorable` unit needs an `anchors_verified` in `events_before` whose fence is
    `open_fence`. Every other edge, a resume to `publishing` included, is ungated (D7)."""
    if (source, target) != ("ready", "publishing") or not _restorable(document):
        return None
    if any(event["type"] == "anchors_verified" and event["fence"] == open_fence
           for event in events_before):
        return None
    return "ready -> publishing needs an anchors_verified under the entering fence"


def recovery_advance_violation(document: dict, target: str, reason: str) -> str | None:
    """Why `advance` may not take `document` to `target` with `reason`, or None: the
    publication gate under the held fence (D7, D22)."""
    held = document["custody"]
    return recovery_transition_violation(document, document["events"], document["state"],
                                         target, None if held is None else held["fence"])


def recovery_view(document: dict) -> dict[str, Any]:
    """`{"plan_digest", "recovers", "effect_snapshot", "selected", "children"}` for a
    validated `document`; `effect_snapshot` is None and `selected` empty before any
    recovery starts (D12)."""
    events = document["events"]
    created = events[0]
    started = [event for event in events if event["type"] == "recovery_started"]
    latest = started[-1] if started else None
    return {
        "plan_digest": created["recovery_plan_digest"],
        "recovers": created["recovers"],
        "effect_snapshot": None if latest is None else copy.deepcopy(latest["effect_snapshot"]),
        "selected": [] if latest is None else copy.deepcopy(latest["selected"]),
        "children": [event["child_transaction_id"] for event in events
                     if event["type"] == "roll_forward_linked"],
    }
