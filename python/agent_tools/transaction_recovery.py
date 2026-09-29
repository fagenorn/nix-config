"""Recovery (#208): the closed `RecoveryRefused` reasons and their one construction path, the
anchor and compatibility check requests and their result check, the effect classes, the
selection and which actions it admits (`selection_refusal`), the admission and decision
halves of `verify_anchors` and `begin_recovery`, the decision of `settle_recovery`
(`recovery_settlement`, `settled_citations`), the admission and link of `roll_forward`
(`roll_forward_refusal`, `link_events`), the recovery event and pairing rules, the gates and
the derived `recovery` view.

A check request is a read-only mapping naming the unit by action id, the check, its
predicate and parameters, the unit's proof collector and the held fence; its result is the
closed `{outcome, reason, reference}` shape of `transaction_proof.closed_result_violation`,
so a check shares the observation outcome vocabulary (D21, D26). `anchor_requests` admits a
verification in `ready` only, one request per `restorable` unit in plan order, and
`anchors_events` refuses `rollback_anchor_missing` for the first result that is not
`satisfied`, else yields one `anchors_verified` stamped with the held fence (D7). A refusal
naming a unit says `<name> (<action id>)` (D23).

An action's `effect_class` comes from its #206 fold: `no_effect` with no intended attempt, else
`in_progress` while open, else its latest inspection's outcome (D8, D19); a unit is affected
while its forward action or any of its edges is not `no_effect`. `begin_requests`
refuses with `begin_refusal`'s first reason in D8's order, else asks one compatibility check
per affected `restorable` unit; `begin_events` refuses `restore_incompatible`, else yields
`recovery_started` (the `effect_snapshot`, the `selection` of every affected unit's edges and
the checks) and the transition into `recovering`. `recovery_settlement` judges the latest
selection in one write (D9): every edge `satisfied` yields `recovery_settled`, citing
`settled_citations`' restored units and declared residue, and `recovering -> rolled_back`; a
`diverged`, `unknown` or unretryable edge yields `recovery_incomplete` and its park; anything
else is `recovery_pending`. `roll_forward_refusal` refuses `state_not_attention`, then
`grant_required`, as `begin_refusal` does, and `link_events` yields one `roll_forward_linked`
naming a child, or nothing once a link names it (D11). `agent_tools.transaction_history`
hands every `RECOVERY_EVENT_KEYS` event to `recovery_event_violation`, which re-derives a
`recovery_started` and a `recovery_settled`'s citations through the same functions, every
event pair to `recovery_pairing_violation`, and every transition to
`recovery_transition_violation`, which refuses `abandoned` while `effecting_action` names an
action and `ready -> publishing` for a plan with a `restorable` unit unless an
`anchors_verified` carries the open span's fence;
`agent_tools.transaction_core`'s `advance` applies the same gates through
`recovery_advance_violation` with the held fence, and refuses `recovering`, `rolled_back` and
the `RESERVED_RECOVERY_REASONS` (D7, D9, D10, D22).

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
from agent_tools.transaction_invocation import (
    ActionFold, fold_actions, refusal, satisfied, status, unresolved)
from agent_tools.transaction_proof import closed_result_violation
from agent_tools.transaction_storage import RecoveryRefused, TransitionRefused

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
    "recovery_settled": _ENVELOPE_KEYS | {"restored", "residue", "fence"},
    "recovery_incomplete": _ENVELOPE_KEYS | {"actions", "fence"},
    "roll_forward_linked": _ENVELOPE_KEYS | {"child_transaction_id", "grant_id", "reason",
                                             "fence"},
})
_ANCHOR_KEYS = frozenset({"unit", "reference"})
_ENTERED = ("attention_required", "recovering", "recovery_started", "known")
_SETTLED = ("recovering", "rolled_back", "recovery_settled", "known")
_EVENT_STATES = MappingProxyType({"anchors_verified": "ready", "recovery_settled": "recovering",
                                  "recovery_incomplete": "recovering",
                                  "roll_forward_linked": "attention_required"})
_UNRETRYABLE = ("not_retryable", "budget_exhausted", "window_closed")


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
    """The plan units whose forward action or any recovery edge is not `no_effect`, in plan
    order: an edge an earlier recovery drove keeps its unit affected, so a re-begun recovery
    never drops an outstanding edge and `no_effect` agrees with the `abandoned` gate (D8)."""
    return [unit for unit in plan["units"]
            if any(effect_class(actions.get(identity)) != "no_effect" for identity in
                   [unit["action_id"], *(edge["action_id"] for edge in unit["edges"])])]


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


def _parked_refusal(document: dict, grant_id: Any, operation: str) -> tuple[str, str] | None:
    state = document["state"]
    if state != "attention_required":
        return "state_not_attention", f"{operation} runs in attention_required, not {state}"
    if not fresh_grant(document["events"], grant_id, document["custody"]["fence"]):
        return "grant_required", (f"grant {grant_id!r} was not issued under the held fence "
                                  f"since the latest parking")
    return None


def begin_refusal(document: dict, grant_id: Any) -> tuple[str, str] | None:
    """`begin_recovery`'s first refusal `(reason, detail)` under the held fence, in D8's
    order, or None: `state_not_attention`, `grant_required`, `reconciliation_required`,
    `undeclared_effect`, `effect_uncertain`, `no_effect`, `unit_not_restorable`."""
    parked = _parked_refusal(document, grant_id, "begin_recovery")
    if parked is not None:
        return parked
    held = document["custody"]["fence"]
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


def _selected(events: Sequence[Mapping]) -> list[str]:
    return [event for event in events if event["type"] == "recovery_started"][-1]["selected"]


def settled_citations(plan: Mapping, selected: list[str]) -> tuple[list[str], list[dict]]:
    """`(restored, residue)` for the `selected` edges, in selection order: the unit action id
    of each `restore` edge, and `{unit, residue}` with the unit action id and the declared
    residue of each `compensate` edge (D4, D9)."""
    edges = {edge["action_id"]: (unit["action_id"], edge)
             for unit in plan["units"] for edge in unit["edges"]}
    restored, residue = [], []
    for identity in selected:
        unit, edge = edges[identity]
        if edge["action"] == "restore":
            restored.append(unit)
        else:
            residue.append({"unit": unit, "residue": edge["residue"]})
    return restored, residue


def _stuck(entry: ActionFold | None, held: dict, now_ms: int) -> bool:
    if entry is None or entry.open:
        return False
    return (status(entry) in ("diverged", "unknown")
            or refusal(entry, held_fence=held, now_ms=now_ms) in _UNRETRYABLE)


def recovery_settlement(document: dict, now_ms: int) -> list[dict]:
    """`settle_recovery`'s decision at `now_ms` under the held fence, the first matching case
    over the latest `recovery_started`'s `selected` edges (D9): `state_not_recovering` outside
    `recovering`; with every edge `satisfied`, `TransitionRefused` while `unresolved` names an
    action, else `recovery_settled` citing `settled_citations` and `recovering -> rolled_back`;
    with an edge `diverged`, `unknown`, or `absent` under the held fence and refused
    `not_retryable`, `budget_exhausted` or `window_closed`, `recovery_incomplete` listing those
    edges in selection order and the park `recovering -> attention_required`, external state
    `unknown` when a listed edge is; else `recovery_pending`."""
    transaction_id, state = document["transaction_id"], document["state"]
    if state != "recovering":
        raise recovery_refused(transaction_id, "state_not_recovering",
                               f"settle_recovery runs in recovering, not {state}")
    events, held = document["events"], document["custody"]["fence"]
    selected, actions = _selected(events), fold_actions(events)
    fence = copy.deepcopy(held)
    if all(satisfied(actions.get(identity)) for identity in selected):
        blocker = unresolved(actions)
        if blocker is not None:
            raise TransitionRefused(f"{transaction_id}: settle_recovery: rolled_back over "
                                    f"unresolved action {blocker.action_id} ({status(blocker)})")
        restored, residue = settled_citations(document["recovery_plan"], selected)
        return [{"type": "recovery_settled", "restored": restored, "residue": residue,
                 "fence": fence},
                dict(zip(("type", "from", "to", "reason", "external_state"),
                         ("transitioned", *_SETTLED)))]
    stuck = [identity for identity in selected if _stuck(actions.get(identity), held, now_ms)]
    if not stuck:
        raise recovery_refused(transaction_id, "recovery_pending",
                               "a selected edge is not yet settled and may still be driven")
    unknown = any(status(actions[identity]) == "unknown" for identity in stuck)
    return [{"type": "recovery_incomplete", "actions": stuck, "fence": fence},
            {"type": "transitioned", "from": "recovering", "to": "attention_required",
             "reason": "recovery_incomplete",
             "external_state": "unknown" if unknown else "known"}]


def roll_forward_refusal(document: dict, grant_id: Any) -> None:
    """`roll_forward`'s admission under the held fence, run in both holds: refuse
    `state_not_attention`, then `grant_required`, with `begin_refusal`'s meanings (D8, D11,
    D19)."""
    parked = _parked_refusal(document, grant_id, "roll_forward")
    if parked is not None:
        raise recovery_refused(document["transaction_id"], *parked)


def link_events(document: dict, child_id: str, grant_id: str, reason: str) -> list[dict]:
    """`roll_forward`'s link: nothing when a `roll_forward_linked` already names `child_id`,
    so a retry links its child once; else one `roll_forward_linked` under the held fence
    (D11)."""
    if child_id in _children(document["events"]):
        return []
    return [{"type": "roll_forward_linked", "child_transaction_id": child_id,
             "grant_id": grant_id, "reason": reason,
             "fence": copy.deepcopy(document["custody"]["fence"])}]


def _children(events: Sequence[Mapping]) -> list[Any]:
    return [event["child_transaction_id"] for event in events
            if event["type"] == "roll_forward_linked"]


def _linked_violation(event: dict, events_before: Sequence[Mapping],
                      document: dict) -> str | None:
    if not fresh_grant(events_before, event["grant_id"], event["fence"]):
        return (f"roll_forward_linked grant {event['grant_id']!r} was not issued under its "
                f"fence since the latest parking")
    child = event["child_transaction_id"]
    if child == document["transaction_id"] or child in _children(events_before):
        return ("roll_forward_linked child_transaction_id is the transaction's own or an "
                "earlier link's")
    if type(event["reason"]) is not str or not event["reason"]:
        return "roll_forward_linked reason is not a non-empty string"
    return None


def _settled_violation(event: dict, events_before: Sequence[Mapping],
                       document: dict) -> str | None:
    selected, actions = _selected(events_before), fold_actions(events_before)
    for identity in selected:
        entry = actions.get(identity)
        if not satisfied(entry):
            return (f"recovery_settled needs every selected edge satisfied; edge {identity} is "
                    f"{'undeclared' if entry is None else status(entry)}")
    restored, residue = settled_citations(document["recovery_plan"], selected)
    if event["restored"] != restored:
        return "recovery_settled restored is not the selected restore edges' units"
    if event["residue"] != residue:
        return "recovery_settled residue is not the selected compensate edges' declared residue"
    return None


def _incomplete_violation(event: dict, events_before: Sequence[Mapping]) -> str | None:
    listed, selected = event["actions"], _selected(events_before)
    if (type(listed) is not list or not listed
            or listed != [identity for identity in selected if identity in listed]):
        return ("recovery_incomplete actions are not a non-empty list of selected edges in "
                "selection order")
    actions = fold_actions(events_before)
    for identity in listed:
        if satisfied(actions.get(identity)):
            return f"recovery_incomplete actions list the satisfied edge {identity}"
    return None


def _unit_references_violation(entries: Any, expected_ids: list[str]) -> bool:
    """Whether `entries` is not a list of closed `{unit, reference}` objects, each with a
    non-empty string reference, whose units are `expected_ids` in order."""
    return (type(entries) is not list
            or any(type(entry) is not dict or set(entry) != _ANCHOR_KEYS
                   or type(entry["reference"]) is not str or not entry["reference"]
                   for entry in entries)
            or [entry["unit"] for entry in entries] != expected_ids)


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
    if _unit_references_violation(event["checks"],
                                  [unit["action_id"] for unit in _checked(before)]):
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
    `effect_snapshot`, `selected` and `checks` units are the writer's (D10). A
    `recovery_settled` and a `recovery_incomplete` happen in `recovering`: the first needs
    every selected edge `satisfied` in the fold before it and `restored` and `residue` equal
    to `settled_citations`; the second needs `actions` to be a non-empty list of selected
    edges in selection order, none `satisfied`, and does not re-judge the retry window (D9,
    D10). A `roll_forward_linked` happens in `attention_required` under a `fresh_grant`, and
    names a child that is neither the transaction nor an earlier link, with a non-empty
    `reason`; `agent_tools.transaction_history` checks the child is a transaction id (D11)."""
    kind = event["type"]
    if kind in _EVENT_STATES and state != _EVENT_STATES[kind]:
        return f"{kind} happens in {state}, not {_EVENT_STATES[kind]}"
    if open_fence is None:
        return f"{kind} sits outside an open custody span"
    violation = fence_violation(event["fence"], keys)
    if violation is not None:
        return f"{kind} {violation}"
    if event["fence"] != open_fence:
        return f"{kind} fence does not equal the open span's fence"
    if kind == "recovery_started":
        return _started_violation(event, events_before, document, open_fence, state)
    if kind == "recovery_settled":
        return _settled_violation(event, events_before, document)
    if kind == "recovery_incomplete":
        return _incomplete_violation(event, events_before)
    if kind == "roll_forward_linked":
        return _linked_violation(event, events_before, document)
    if _unit_references_violation(event["anchors"],
                                  [unit["action_id"] for unit in _restorable(document)]):
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
    is `begin_recovery`'s, `rolled_back` is `settle_recovery`'s, a reserved reason is the
    recovery operations', and the `recovery_transition_violation` gates apply under the held
    fence (D7, D9, D10, D22)."""
    if target == "recovering":
        return "recovering is entered only through begin_recovery"
    if target == "rolled_back":
        return "rolled_back is entered only through settle_recovery"
    if reason in RESERVED_RECOVERY_REASONS:
        return f"reserved reason {reason} is written only by the recovery operations"
    held = document["custody"]
    return recovery_transition_violation(document, document["events"], document["state"],
                                         target, None if held is None else held["fence"])


def recovery_pairing_violation(previous: Mapping | None, event: Mapping | None) -> str | None:
    """How `event`, the one after `previous` (None past the end), breaks a recovery pairing,
    or None (D10): `recovery_started` comes immediately before `attention_required ->
    recovering` with reason `recovery_started` and external state `known`, every transition
    into `recovering` immediately after it; `recovery_settled` immediately before `recovering
    -> rolled_back` with reason `recovery_settled` and external state `known`, every
    transition into `rolled_back` immediately after it; `recovery_incomplete` immediately
    before `recovering -> attention_required` with reason `recovery_incomplete`; and a
    transition with a reserved reason immediately after its event."""
    kind = None if previous is None else previous.get("type")
    edge = None
    if event is not None and event.get("type") == "transitioned":
        edge = tuple(event.get(key) for key in ("from", "to", "reason", "external_state"))
    if kind == "recovery_started" and edge != _ENTERED:
        return ("recovery_started is not immediately followed by attention_required -> "
                "recovering with reason recovery_started and external state known")
    if edge is not None and edge[1] == "recovering" and kind != "recovery_started":
        return "transition into recovering does not immediately follow recovery_started"
    if kind == "recovery_settled" and edge != _SETTLED:
        return ("recovery_settled is not immediately followed by recovering -> rolled_back "
                "with reason recovery_settled and external state known")
    if edge is not None and edge[1] == "rolled_back" and kind != "recovery_settled":
        return "transition into rolled_back does not immediately follow recovery_settled"
    if kind == "recovery_incomplete" and (edge is None or edge[:3] != (
            "recovering", "attention_required", "recovery_incomplete")):
        return ("recovery_incomplete is not immediately followed by recovering -> "
                "attention_required with reason recovery_incomplete")
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
        "children": _children(events),
    }
