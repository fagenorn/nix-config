"""The `failed` disposition (#209 D8-D11, D21, D26): the closed grounds and their
vocabularies, the `DispositionRefused` reasons and their one construction path
(`disposition_refused`), the admission and event halves of `dispose_failed`
(`failure_refusal`, `failure_record`, `failure_events`), and the validator's rules.

`failure_refusal` is the one judge, called by the writer and the validator alike, which
differ only through `writer` and `now_ms`: it returns the first `(reason, detail)` of
`DISPOSITION_REFUSAL_REASONS`, in that order. A disposition is a strict JSON object of
exactly `ground`, `reference`, `occurred_at`, `successor` and `units`. A known-state ground
(`KNOWN_STATE_GROUNDS`) records `final_state_known` with no units; an observability ground
(`OBSERVABILITY_GROUNDS`) needs a fresh human grant at the transaction's authority class and
lists exactly the actions with effect, each destroyed with the authority or possibly live
with a residue bound and a recheck, whose latest inspection is `unknown`, under the held
fence and after the ground occurred. `failure_disposed` records the grant, the disposition,
the successor's receipt digest, the qualifier (`effects_unobservable` when some unit is
possibly live), `action_effects` verbatim and the held fence, and precedes `attention_required
-> failed`.

`failure_event_violation` re-derives a `failure_disposed` through the same functions, without
the clock or the successor's state, which only the writer reads. `terminal_blocker` replaces
#206 D20's unresolved-terminal rule at a terminal transition, admitting `failed` over the
`unknown` actions an observability ground lists; `effect_uncertain` refuses every other
`unknown` one first. `disposition_advance_violation` refuses an `advance` into `failed` or
with the reserved reason, and `disposition_pairing_violation` binds `failure_disposed` to the
transition right after it, every transition into `failed` and every transition with the
reserved reason to the event right before it. Every function here is pure: the module reads
no file, lock or clock.
"""

import copy
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from agent_tools.transaction_invocation import ActionFold, fold_actions, status, unresolved
from agent_tools.transaction_recovery import (
    effect_class, fresh_grant, no_effect, recovery_view, unreconciled)
from agent_tools.transaction_storage import (
    DispositionRefused, is_id, json_object_violation, parse_at)

FAILURE_REASON = "failure_disposed"
KNOWN_STATE_GROUNDS = ("successor_succeeded", "no_recovery_path")
OBSERVABILITY_GROUNDS = ("authority_retired", "tenancy_destroyed", "host_decommissioned",
                         "credential_class_revoked_without_successor", "subject_scope_erased")
GROUNDS = KNOWN_STATE_GROUNDS + OBSERVABILITY_GROUNDS
CONSEQUENCES = ("effects_destroyed_with_authority", "effects_possibly_live_unobservable")
QUALIFIERS = ("final_state_known", "effects_unobservable")
RESIDUE_BOUNDS = ("bounded", "unbounded")
DISPOSITION_REFUSAL_REASONS = (
    "state_not_attention", "grant_required", "malformed", "no_effect",
    "reconciliation_required", "effect_uncertain", "successor_not_succeeded",
    "human_required", "authority_class_mismatch", "units_mismatch",
    "inspection_not_exhausted")

_FIELDS = ("ground", "reference", "occurred_at", "successor", "units")
_UNIT_KEYS = frozenset({"unit", "consequence", "residue_bound", "recheck"})
DISPOSITION_EVENT_KEYS: Mapping[str, frozenset[str]] = MappingProxyType({
    FAILURE_REASON: frozenset({"seq", "type", "at", "grant_id", *_FIELDS, "successor_receipt",
                               "qualifier", "effect_snapshot", "fence"})})
_DISPOSED = ("attention_required", "failed", FAILURE_REASON, "known")
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


def disposition_refused(transaction_id: str, reason: str, detail: str) -> DispositionRefused:
    """The one construction path for `DispositionRefused`; a `reason` outside
    `DISPOSITION_REFUSAL_REASONS` is a programming error (`ValueError`)."""
    if reason not in DISPOSITION_REFUSAL_REASONS:
        raise ValueError(f"disposition_refused: {reason!r} is not a disposition refusal reason")
    return DispositionRefused(f"{transaction_id}: disposition refused: {reason}: {detail}",
                              reason=reason)


def action_effects(events: Sequence[Mapping]) -> dict[str, str]:
    """Every folded action's effect class, by action id in declaration order (D20)."""
    return {identity: effect_class(entry) for identity, entry in fold_actions(events).items()}


def _unit_violation(unit: Any, seen: set) -> str | None:
    if type(unit) is not dict or set(unit) != _UNIT_KEYS:
        return "a units entry is not exactly unit, consequence, residue_bound and recheck"
    name = unit["unit"]
    if type(name) is not str or not name or name in seen:
        return f"unit {name!r} is not a non-empty string listed once"
    seen.add(name)
    consequence, bound, recheck = unit["consequence"], unit["residue_bound"], unit["recheck"]
    if type(consequence) is not str or consequence not in CONSEQUENCES:
        return f"unit {name} consequence {consequence!r} is not one of {CONSEQUENCES}"
    if consequence == CONSEQUENCES[0] and (bound is not None or recheck is not None):
        return f"unit {name} is destroyed yet carries a residue_bound or recheck"
    if consequence == CONSEQUENCES[1] and (type(bound) is not str or bound not in RESIDUE_BOUNDS
                                           or type(recheck) is not str or not recheck):
        return (f"unit {name} is possibly live without a residue_bound in {RESIDUE_BOUNDS} and "
                f"a non-empty recheck")
    return None


def _shape_violation(disposition: Any, now_ms: int | None, writer: bool) -> str | None:
    """The first closed-shape, vocabulary or per-ground field rule `disposition` breaks."""
    violation = json_object_violation(disposition)
    if violation is not None:
        return f"disposition {violation}"
    if set(disposition) != set(_FIELDS):
        return "disposition is not exactly ground, reference, occurred_at, successor and units"
    ground, reference, occurred, successor, units = (disposition[key] for key in _FIELDS)
    if type(ground) is not str or ground not in GROUNDS:
        return f"ground {ground!r} is not one of GROUNDS"
    if type(reference) is not str or not reference:
        return "reference is not a non-empty string"
    if occurred is not None and (type(occurred) is not int or occurred < 0):
        return f"occurred_at {occurred!r} is neither null nor a non-negative integer"
    if successor is not None and not is_id(successor):
        return f"successor {successor!r} is neither null nor a rel_ UUIDv7"
    if type(units) is not list:
        return "units is not a list"
    seen: set = set()
    for unit in units:
        violation = _unit_violation(unit, seen)
        if violation is not None:
            return violation
    if ground in KNOWN_STATE_GROUNDS:
        if occurred is not None or units:
            return f"{ground} needs occurred_at null and units empty"
        if (successor is None) == (ground == "successor_succeeded"):
            return f"{ground} needs {'a' if successor is None else 'no'} successor"
        return None
    if occurred is None:
        return f"{ground} needs an occurred_at"
    if writer and occurred > now_ms:
        return f"{ground} occurred_at {occurred} is later than the clock {now_ms}"
    if successor is not None:
        return f"{ground} needs no successor"
    return None


def _fresh_grant_event(events: Sequence[Mapping], grant_id: Any, fence: Any) -> Mapping:
    return [event for event in events if event["type"] == "grant_issued"
            and event["grant_id"] == grant_id and event["fence"] == fence][-1]


def _uncertain(actions: Mapping[str, ActionFold], ground: str) -> ActionFold | None:
    """The first action `in_progress`, or `unknown` where no unit can name it: under a
    known-state ground, or with no effect, so `terminal_blocker` would refuse it (D21)."""
    known = ground not in OBSERVABILITY_GROUNDS
    return next((entry for entry in actions.values() if status(entry) == "in_progress"
                 or status(entry) == "unknown" and (known or effect_class(entry) == "no_effect")),
                None)


def _exhausted_violation(actions: Mapping[str, ActionFold], units: list, held: Any,
                         occurred: int) -> str | None:
    for unit in units:
        if unit["consequence"] != CONSEQUENCES[1]:
            continue
        inspection = actions[unit["unit"]].inspection
        if (inspection is None or inspection["outcome"] != "unknown"
                or inspection["fence"] != held or parse_at(inspection["at"]) <= occurred):
            seen = ("none" if inspection is None
                    else f"{inspection['outcome']} at {inspection['at']}")
            return (f"possibly-live unit {unit['unit']} last inspection ({seen}) is not unknown, "
                    f"under the held fence and after occurred_at {occurred}")
    return None


def failure_refusal(document: dict, grant_id: Any, disposition: Any, *, now_ms: int | None,
                    successor: Mapping | None, writer: bool) -> tuple[str, str] | None:
    """`dispose_failed`'s first refusal `(reason, detail)` under the held fence, or None
    (D8, D9, D11, D21), in `DISPOSITION_REFUSAL_REASONS` order: `state_not_attention`
    outside `attention_required`; `grant_required` without a `fresh_grant`; `malformed` for
    any closed-shape, vocabulary or per-ground field rule (with `writer`, an observability
    `occurred_at` later than `now_ms` too); `no_effect` when no action has an effect;
    `reconciliation_required` for an action `unreconciled` names; `effect_uncertain` for an
    action `in_progress`, or `unknown` under a known-state ground or with no effect (no unit
    can name it); for `successor_succeeded`, `successor_not_succeeded` when the successor is
    not a linked child or, with `writer`, `successor` (`{transaction_id, state,
    receipt_digest}`, None for no such transaction) is not that child sealed `succeeded`.
    Then, for an observability ground only: `human_required` and
    `authority_class_mismatch` for the latest such grant's `actor_kind` and `authority_class`
    against the `created` event's; `units_mismatch` unless the units are the actions with
    effect in declaration order; `inspection_not_exhausted` for a possibly-live unit whose
    latest inspection is not `unknown`, not under the held fence or not after `occurred_at`."""
    state, events = document["state"], document["events"]
    if state != "attention_required":
        return "state_not_attention", f"dispose_failed runs in attention_required, not {state}"
    held = document["custody"]["fence"]
    if not fresh_grant(events, grant_id, held):
        return "grant_required", (f"grant {grant_id!r} was not issued under the held fence "
                                  f"since the latest parking")
    violation = _shape_violation(disposition, now_ms, writer)
    if violation is not None:
        return "malformed", violation
    if no_effect(events):
        return "no_effect", "no action has an effect; abandoned is the truthful terminal"
    actions = fold_actions(events)
    entry = unreconciled(actions, held)
    if entry is not None:
        return "reconciliation_required", (f"action {entry.action_id} is not inspected under "
                                           f"the held fence")
    ground = disposition["ground"]
    entry = _uncertain(actions, ground)
    if entry is not None:
        return "effect_uncertain", f"action {entry.action_id} is {status(entry)}"
    if ground == "successor_succeeded":
        child = disposition["successor"]
        if child not in recovery_view(document)["children"] or writer and (
                successor is None or successor["transaction_id"] != child
                or successor["state"] != "succeeded"
                or successor["receipt_digest"] is None):
            return "successor_not_succeeded", (f"successor {child} is not a linked child "
                                               f"sealed succeeded")
    if ground in KNOWN_STATE_GROUNDS:
        return None
    grant = _fresh_grant_event(events, grant_id, held)
    if grant["actor_kind"] != "human":
        return "human_required", f"grant {grant_id} actor_kind is {grant['actor_kind']}"
    if grant["authority_class"] != events[0]["authority_class"]:
        return "authority_class_mismatch", (f"grant {grant_id} authority_class "
                                            f"{grant['authority_class']} is not "
                                            f"{events[0]['authority_class']}")
    effected = [identity for identity, fold in actions.items()
                if effect_class(fold) != "no_effect"]
    listed = [unit["unit"] for unit in disposition["units"]]
    if listed != effected:
        return "units_mismatch", f"units {listed} are not the actions with effect {effected}"
    violation = _exhausted_violation(actions, disposition["units"], held,
                                     disposition["occurred_at"])
    return None if violation is None else ("inspection_not_exhausted", violation)


def failure_record(document: dict, grant_id: str, disposition: Mapping,
                   successor_receipt: str | None) -> dict:
    """The `failure_disposed` fields without `seq` and `at`, the disposition deep-copied:
    `qualifier` `effects_unobservable` when some unit is possibly live, else
    `final_state_known`; `effect_snapshot` `action_effects` verbatim, so an `unknown` stays
    `unknown` (D10); `fence` the held fence."""
    live = any(unit["consequence"] == CONSEQUENCES[1] for unit in disposition["units"])
    return {"grant_id": grant_id, **copy.deepcopy({key: disposition[key] for key in _FIELDS}),
            "successor_receipt": successor_receipt, "qualifier": QUALIFIERS[1 if live else 0],
            "effect_snapshot": action_effects(document["events"]),
            "fence": copy.deepcopy(document["custody"]["fence"])}


def failure_events(document: dict, now_ms: int, grant_id: str, disposition: Any,
                   successor: Mapping | None) -> list[dict]:
    """`dispose_failed`'s decision: `failure_refusal`'s reason as `DispositionRefused`, else
    `failure_disposed` (citing the successor's receipt digest for `successor_succeeded`)
    and `attention_required -> failed`, reason `failure_disposed`, external state `known`."""
    refusal = failure_refusal(document, grant_id, disposition, now_ms=now_ms,
                              successor=successor, writer=True)
    if refusal is not None:
        raise disposition_refused(document["transaction_id"], *refusal)
    receipt = (successor["receipt_digest"] if disposition["ground"] == "successor_succeeded"
               else None)
    return [{"type": FAILURE_REASON,
             **failure_record(document, grant_id, disposition, receipt)},
            dict(zip(("type", "from", "to", "reason", "external_state"),
                     ("transitioned", *_DISPOSED)))]


def failure_event_violation(event: dict, events_before: Sequence[Mapping], document: dict, *,
                            open_fence: dict | None, state: str) -> str | None:
    """The first rule the closed-shape `failure_disposed` breaks, or None (D21): it sits in
    an open span; `failure_refusal` over the walk's own `state` and `open_fence`, without the
    clock or the successor's state, is None; `successor_receipt` is a receipt digest for
    `successor_succeeded` and null otherwise; every other field is `failure_record`'s."""
    if open_fence is None:
        return f"{FAILURE_REASON} sits outside an open custody span"
    view = {**document, "events": list(events_before), "state": state,
            "custody": {"fence": open_fence}}
    disposition = {key: event[key] for key in _FIELDS}
    refusal = failure_refusal(view, event["grant_id"], disposition, now_ms=None,
                              successor=None, writer=False)
    if refusal is not None:
        return f"{FAILURE_REASON} {refusal[0]}: {refusal[1]}"
    receipt = event["successor_receipt"]
    if not (receipt is None if disposition["ground"] != "successor_succeeded" else
            type(receipt) is str and _DIGEST_PATTERN.fullmatch(receipt) is not None):
        return (f"{FAILURE_REASON} successor_receipt is not null or a receipt digest as its "
                f"ground requires")
    expected = failure_record(view, event["grant_id"], disposition, receipt)
    for key in sorted(expected):
        if event[key] != expected[key]:
            return f"{FAILURE_REASON} does not match its re-derivation: {key}"
    return None


def terminal_blocker(actions: Mapping[str, ActionFold], previous: Mapping) -> ActionFold | None:
    """The action a terminal transition after `previous` may not cross, or None (D21; #206
    D20): after an observability-ground `failure_disposed`, the first action that is `open`,
    `in_progress` or `unknown`, skipping an `unknown` one its units name; else `unresolved`."""
    if previous.get("type") != FAILURE_REASON or previous["ground"] not in OBSERVABILITY_GROUNDS:
        return unresolved(actions)
    listed = {unit["unit"] for unit in previous["units"]}
    return next((entry for entry in actions.values()
                 if status(entry) in ("open", "in_progress", "unknown")
                 and not (status(entry) == "unknown" and entry.action_id in listed)), None)


def disposition_advance_violation(target: str, reason: str) -> str | None:
    """Why `advance` may not take a transaction to `target` with `reason`, or None (D8,
    D21): `failed` and the reserved reason are `dispose_failed`'s alone."""
    if target == "failed":
        return "failed is entered only through dispose_failed"
    if reason == FAILURE_REASON:
        return f"reserved reason {FAILURE_REASON} is written only by dispose_failed"
    return None


def disposition_pairing_violation(previous: Mapping | None,
                                  event: Mapping | None) -> str | None:
    """How `event`, the one after `previous` (None past the end), breaks the disposition
    pairing, or None (D21): `failure_disposed` comes immediately before `attention_required
    -> failed` with reason `failure_disposed` and external state `known`, every transition
    into `failed` immediately after it, and a transition with the reserved reason
    immediately after its event."""
    kind = None if previous is None else previous.get("type")
    edge = None
    if event is not None and event.get("type") == "transitioned":
        edge = tuple(event.get(key) for key in ("from", "to", "reason", "external_state"))
    if kind == FAILURE_REASON and edge != _DISPOSED:
        return (f"{FAILURE_REASON} is not immediately followed by attention_required -> "
                f"failed with reason {FAILURE_REASON} and external state known")
    if edge is not None and edge[1] == "failed" and kind != FAILURE_REASON:
        return f"transition into failed does not immediately follow {FAILURE_REASON}"
    if edge is not None and edge[2] == FAILURE_REASON and kind != FAILURE_REASON:
        return f"reserved reason {FAILURE_REASON} does not immediately follow its event"
    return None
