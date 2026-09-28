"""Recovery (#208): the closed `RecoveryRefused` reasons and their one construction path, the
anchor and compatibility check requests and their result check, the effect classes, the
selection and which actions it admits (`selection_refusal`), the admission and decision
halves of `verify_anchors` and `begin_recovery`, the recovery event and pairing rules, the
gates and the derived `recovery` view.

A check request is a read-only mapping naming the unit by action id, the check, its
predicate and parameters, the unit's proof collector and the held fence; its result is the
closed `{outcome, reason, reference}` shape of `transaction_proof.closed_result_violation`,
so a check shares the observation outcome vocabulary (D21, D26). `anchor_requests` admits a
verification in `ready` only, one request per `restorable` unit in plan order, and
`anchors_events` refuses `rollback_anchor_missing` for the first result that is not
`satisfied`, else yields one `anchors_verified` stamped with the held fence (D7). A refusal
naming a unit says `<name> (<action id>)` (D23).

An action's `effect_class` comes from its #206 fold: `no_effect` with no intended attempt, else
`in_progress` while open, else its latest inspection's outcome (D8, D19). `begin_requests`
refuses with `begin_refusal`'s first reason in D8's order, else asks one compatibility check
per affected `restorable` unit; `begin_events` refuses `restore_incompatible`, else yields
`recovery_started` (the `effect_snapshot`, the `selection` of every affected unit's edges and
the checks) and the transition into `recovering`. `agent_tools.transaction_history` hands every
`RECOVERY_EVENT_KEYS` event to `recovery_event_violation`, which re-derives a
`recovery_started` through the same functions, every event pair to
`recovery_pairing_violation`, and every transition to `recovery_transition_violation`, which
refuses `abandoned` while `effecting_action` names an action and `ready -> publishing` for a
plan with a `restorable` unit unless an `anchors_verified` carries the open span's fence;
`agent_tools.transaction_core`'s `advance` applies the same gates through
`recovery_advance_violation` with the held fence, and refuses `recovering` and the
`RESERVED_RECOVERY_REASONS` (D7, D10, D22).

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
from agent_tools.transaction_invocation import ActionFold, fold_actions
from agent_tools.transaction_proof import closed_result_violation
from agent_tools.transaction_storage import RecoveryRefused

RECOVERY_REFUSAL_REASONS = (
    "state_not_ready", "state_not_attention", "state_not_recovering", "history_changed",
    "rollback_anchor_missing", "grant_required", "reconciliation_required",
    "undeclared_effect", "effect_uncertain", "no_effect", "unit_not_restorable",
    "restore_incompatible", "recovery_pending")
EFFECT_CLASSES = ("no_effect", "target_satisfied", "diverged", "in_progress", "unknown")
RESERVED_RECOVERY_REASONS = ("recovery_started", "recovery_settled", "recovery_incomplete")
_CLASS_OF_OUTCOME = MappingProxyType({
    "absent": "no_effect", "satisfied": "target_satisfied", "diverged": "diverged",
    "in_progress": "in_progress", "unknown": "unknown"})

_ENVELOPE_KEYS = frozenset({"seq", "type", "at"})
RECOVERY_EVENT_KEYS: Mapping[str, frozenset[str]] = MappingProxyType({
    "anchors_verified": _ENVELOPE_KEYS | {"anchors", "fence"},
    "recovery_started": _ENVELOPE_KEYS | {"grant_id", "effect_snapshot", "selected", "checks",
                                          "fence"},
})
_ANCHOR_KEYS = frozenset({"unit", "reference"})
_ENTERED = ("attention_required", "recovering", "recovery_started", "known")


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


def effect_class(entry: ActionFold | None) -> str:
    """The action's effect class: `no_effect` with no intended attempt, whatever it
    inspects; `in_progress` while an attempt is open; else by its latest inspection's
    outcome, `absent` reading `no_effect` (D8, D19)."""
    if entry is None or entry.attempts == 0:
        return "no_effect"
    if entry.open:
        return "in_progress"
    return _CLASS_OF_OUTCOME[entry.inspection["outcome"]]


def effect_snapshot(plan: Mapping, actions: Mapping[str, ActionFold]) -> dict[str, str]:
    """Every plan unit's action id mapped to its effect class, in plan order (D8, D19)."""
    return {unit["action_id"]: effect_class(actions.get(unit["action_id"]))
            for unit in plan["units"]}


def _affected(plan: Mapping, actions: Mapping[str, ActionFold]) -> list[dict]:
    return [unit for unit in plan["units"]
            if effect_class(actions.get(unit["action_id"])) != "no_effect"]


def selection(plan: Mapping, actions: Mapping[str, ActionFold]) -> list[str]:
    """The edge action ids of every affected unit, in plan order, then declaration order
    (D8)."""
    return [edge["action_id"] for unit in _affected(plan, actions) for edge in unit["edges"]]


def selection_refusal(recovery_plan: Mapping, events: Sequence[Mapping], state: str,
                      identity: str) -> str | None:
    """`not_selected` for an action `identity` outside the latest `recovery_started`'s
    `selected` in `recovering`, or for one of the plan's edge action ids in any other state;
    else None, so an undeclared action stays invocable in the effect states (D15, D22)."""
    if state == "recovering":
        started = [event for event in events if event["type"] == "recovery_started"]
        return None if identity in started[-1]["selected"] else "not_selected"
    edges = {edge["action_id"] for unit in recovery_plan["units"] for edge in unit["edges"]}
    return "not_selected" if identity in edges else None


def effecting_action(events: Sequence[Mapping]) -> ActionFold | None:
    """The first action, in declaration order, forward or edge, declared in the plan or not,
    whose effect class is not `no_effect`, or None (D10)."""
    return next((entry for entry in fold_actions(events).values()
                 if effect_class(entry) != "no_effect"), None)


def no_effect(events: Sequence[Mapping]) -> bool:
    """Whether no action of the history has an effect: the `abandoned` gate (D10)."""
    return effecting_action(events) is None


def fresh_grant(events: Sequence[Mapping], grant_id: Any, fence: Any) -> bool:
    """Whether a `grant_issued` named `grant_id` under `fence` postdates the latest
    transition into `attention_required` (D19)."""
    parked = max((event["seq"] for event in events if event["type"] == "transitioned"
                  and event["to"] == "attention_required"), default=0)
    return any(event["type"] == "grant_issued" and event["grant_id"] == grant_id
               and event["fence"] == fence and event["seq"] > parked for event in events)


def begin_refusal(document: dict, grant_id: Any) -> tuple[str, str] | None:
    """`begin_recovery`'s first refusal `(reason, detail)` under the held fence, in D8's
    order, or None: `state_not_attention`, `grant_required`, `reconciliation_required`,
    `undeclared_effect`, `effect_uncertain`, `no_effect`, `unit_not_restorable`."""
    state = document["state"]
    if state != "attention_required":
        return "state_not_attention", f"begin_recovery runs in attention_required, not {state}"
    held = document["custody"]["fence"]
    if not fresh_grant(document["events"], grant_id, held):
        return "grant_required", (f"grant {grant_id!r} was not issued under the held fence "
                                  f"since the latest parking")
    actions = fold_actions(document["events"])
    for entry in actions.values():
        if entry.attempts and (entry.open or entry.inspection["fence"] != held):
            return "reconciliation_required", (f"action {entry.action_id} is not inspected "
                                               f"under the held fence")
    plan = document["recovery_plan"]
    declared = {identity for unit in plan["units"] for identity in
                [unit["action_id"], *(edge["action_id"] for edge in unit["edges"])]}
    for entry in actions.values():
        if entry.action_id not in declared and effect_class(entry) != "no_effect":
            return "undeclared_effect", (f"action {entry.action_id} has an effect and no "
                                         f"posture")
    affected = _affected(plan, actions)
    for unit in affected:
        effect = effect_class(actions[unit["action_id"]])
        if effect in ("in_progress", "unknown"):
            return "effect_uncertain", f"unit {unit_label(document, unit['action_id'])} is {effect}"
    if not affected:
        return "no_effect", "no unit has an effect; abandoned is the truthful terminal"
    for unit in affected:
        if unit["posture"] in ("supersedable_only", "manual_only"):
            return "unit_not_restorable", (f"unit {unit_label(document, unit['action_id'])} "
                                           f"is {unit['posture']}")
    return None


def _checked(document: dict) -> list[dict]:
    affected = _affected(document["recovery_plan"], fold_actions(document["events"]))
    return [unit for unit in affected if unit["posture"] == "restorable"]


def begin_requests(document: dict, grant_id: str) -> list[Mapping[str, Any]]:
    """`begin_recovery`'s admission: `begin_refusal`'s reason, else one compatibility request
    per affected `restorable` unit, in plan order (D8)."""
    refusal = begin_refusal(document, grant_id)
    if refusal is not None:
        raise recovery_refused(document["transaction_id"], *refusal)
    return check_requests(document, "compatibility", _checked(document))


def begin_events(document: dict, grant_id: str, requests: Sequence[Mapping],
                 results: Sequence[Mapping]) -> list[dict]:
    """`begin_recovery`'s decision: `restore_incompatible` naming the first unit whose
    compatibility is not `satisfied`; else `recovery_started` under the held fence and the
    transition `attention_required -> recovering`, reason `recovery_started` (D8)."""
    for request, result in zip(requests, results):
        if result["outcome"] != "satisfied":
            raise recovery_refused(
                document["transaction_id"], "restore_incompatible",
                f"unit {unit_label(document, request['unit'])} compatibility "
                f"{result['outcome']}")
    plan, actions = document["recovery_plan"], fold_actions(document["events"])
    return [{"type": "recovery_started", "grant_id": grant_id,
             "effect_snapshot": effect_snapshot(plan, actions),
             "selected": selection(plan, actions),
             "checks": [{"unit": request["unit"], "reference": result["reference"]}
                        for request, result in zip(requests, results)],
             "fence": copy.deepcopy(document["custody"]["fence"])},
            dict(zip(("type", "from", "to", "reason", "external_state"),
                     ("transitioned", *_ENTERED)))]


def _started_violation(event: dict, events_before: Sequence[Mapping], document: dict,
                       open_fence: dict, state: str) -> str | None:
    before = {**document, "events": list(events_before), "state": state,
              "custody": {"fence": open_fence}}
    refusal = begin_refusal(before, event["grant_id"])
    if refusal is not None:
        return f"recovery_started does not re-derive: {refusal[0]}: {refusal[1]}"
    plan, actions = document["recovery_plan"], fold_actions(events_before)
    if event["effect_snapshot"] != effect_snapshot(plan, actions):
        return "recovery_started effect_snapshot is not the re-derived effect classes"
    if event["selected"] != selection(plan, actions):
        return "recovery_started selected is not the re-derived selection"
    checks = event["checks"]
    if (type(checks) is not list
            or any(type(entry) is not dict or set(entry) != _ANCHOR_KEYS
                   or type(entry["reference"]) is not str or not entry["reference"]
                   for entry in checks)
            or [entry["unit"] for entry in checks]
            != [unit["action_id"] for unit in _checked(before)]):
        return ("recovery_started checks are not each affected restorable unit's unit and "
                "non-empty reference, in plan order")
    return None


def recovery_event_violation(event: dict, events_before: Sequence[Mapping], document: dict, *,
                             keys: list[str], open_fence: dict | None,
                             state: str) -> str | None:
    """The first rule the closed-shape recovery `event` breaks, or None. Each is stamped
    with the open span's fence. An `anchors_verified` happens in `ready` and lists exactly
    the `restorable` units' action ids in plan order, each with a non-empty reference (D7).
    A `recovery_started` re-derives from the history before it, in `state`, under
    `open_fence`, through the writer's functions: `begin_refusal` is None, and its
    `effect_snapshot`, `selected` and `checks` units are the writer's (D10)."""
    kind = event["type"]
    if kind == "anchors_verified" and state != "ready":
        return f"{kind} happens in {state}, not ready"
    if open_fence is None:
        return f"{kind} sits outside an open custody span"
    violation = fence_violation(event["fence"], keys)
    if violation is not None:
        return f"{kind} {violation}"
    if event["fence"] != open_fence:
        return f"{kind} fence does not equal the open span's fence"
    if kind == "recovery_started":
        return _started_violation(event, events_before, document, open_fence, state)
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
    """The gate `source -> target` breaks, or None: `abandoned` needs every action in
    `events_before` without effect (D10), and `ready -> publishing` for a plan with a
    `restorable` unit needs an `anchors_verified` in `events_before` whose fence is
    `open_fence`. Every other edge, a resume to `publishing` included, is ungated (D7)."""
    if target == "abandoned":
        entry = effecting_action(events_before)
        if entry is not None:
            return (f"abandoned needs every action without effect; action {entry.action_id} "
                    f"is {effect_class(entry)}")
    if (source, target) != ("ready", "publishing") or not _restorable(document):
        return None
    if any(event["type"] == "anchors_verified" and event["fence"] == open_fence
           for event in events_before):
        return None
    return "ready -> publishing needs an anchors_verified under the entering fence"


def recovery_advance_violation(document: dict, target: str, reason: str) -> str | None:
    """Why `advance` may not take `document` to `target` with `reason`, or None: `recovering`
    is `begin_recovery`'s, a reserved reason is the recovery operations', and the
    `recovery_transition_violation` gates apply under the held fence (D7, D10, D22)."""
    if target == "recovering":
        return "recovering is entered only through begin_recovery"
    if reason in RESERVED_RECOVERY_REASONS:
        return f"reserved reason {reason} is written only by the recovery operations"
    held = document["custody"]
    return recovery_transition_violation(document, document["events"], document["state"],
                                         target, None if held is None else held["fence"])


def recovery_pairing_violation(previous: Mapping | None, event: Mapping | None) -> str | None:
    """How `event`, the one after `previous` (None past the end), breaks a recovery pairing,
    or None (D10): `recovery_started` comes immediately before `attention_required ->
    recovering` with reason `recovery_started` and external state `known`, every transition
    into `recovering` immediately after it, and a transition with a reserved reason
    immediately after its event."""
    kind = None if previous is None else previous.get("type")
    edge = None
    if event is not None and event.get("type") == "transitioned":
        edge = tuple(event.get(key) for key in ("from", "to", "reason", "external_state"))
    if kind == "recovery_started" and edge != _ENTERED:
        return ("recovery_started is not immediately followed by attention_required -> "
                "recovering with reason recovery_started and external state known")
    if edge is not None and edge[1] == "recovering" and kind != "recovery_started":
        return "transition into recovering does not immediately follow recovery_started"
    if edge is not None and edge[2] in RESERVED_RECOVERY_REASONS and kind != edge[2]:
        return f"reserved reason {edge[2]} does not immediately follow its event"
    return None


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
