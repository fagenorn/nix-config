"""Proof obligations and the convergence cohort over a transaction's history (#207 D6-D11,
D21, D22, D25, D27-D31): the observation and evaluation vocabularies, the closed
`ProofRefused` reasons and their one construction path, the core-minted evidence ids,
collection admission, the observer's request and result check, the pure evaluation at a
cutoff, the cohort table, the seal's clock-free facts (`seal_violation`), the decision halves
of `start_cohort` (`cohort_start`) and `settle_proof` (`settlement`), the lifecycle gates
(`gate_violation`) and what `advance` may not write (`advance_violation`), the validator's
proof event and reserved-reason pairing rules, and the derived `proof` view.

`agent_tools.transaction_history` hands every proof event to `proof_event_violation` and
`apply_proof_event`, every adjacent pair of events to `pairing_violation` and every
transition to `gate_violation`, and
`agent_tools.transaction_core` keeps only the locks, the clock, the observer call and the
writes around the pure halves held here. Every function here is pure: the module reads no
file, lock or clock.
"""

import copy
import dataclasses
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from agent_tools.transaction_custody import EVIDENCE_EVENTS, admissibility, fence_violation
from agent_tools.transaction_invocation import ActionFold, fold_actions, status, unresolved
from agent_tools.transaction_plan import DERIVED_REASONS, MAX_COHORT_ATTEMPTS
from agent_tools.transaction_storage import ProofRefused, TransitionRefused, format_at, parse_at

OUTCOMES = ("satisfied", "unsatisfied", "unknown")
EVALUATIONS = ("accepted", "rejected", "indeterminate", "not_applicable", "unsupported")
PROOF_REFUSAL_REASONS = (
    "state_not_proving", "unknown_obligation", "unsupported_obligation",
    "dependency_not_accepted", "already_accepted", "not_cohort_member", "clock_regressed",
    "proof_incomplete", "cohort_open", "convergence_exhausted", "no_open_cohort")
COHORT_FAILURE_REASONS = ("fence_changed", "cohort_expired", "member_missing",
                          "collection_bound_exceeded", "member_indeterminate")
RESERVED_REASONS = ("proof_rejected", "proof_did_not_converge")
SEAL_REASON = "proof_sealed"
_PAIRED = MappingProxyType({"proof_rejected": ("attention_required", "proof_rejected"),
                            "proof_convergence_exhausted": ("attention_required",
                                                            "proof_did_not_converge"),
                            "proof_sealed": ("succeeded", None)})
_GATES = MappingProxyType({("publishing", "published"): "publication",
                           ("activating", "proving"): "activation"})

_ENVELOPE_KEYS = frozenset({"seq", "type", "at"})
PROOF_EVENT_KEYS: Mapping[str, frozenset[str]] = MappingProxyType({
    "obligation_observed": _ENVELOPE_KEYS | {
        "obligation_id", "evidence_id", "form", "outcome", "reason", "reference", "fence",
        "cohort", "latency_ms"},
    "proof_cohort_started": _ENVELOPE_KEYS | {"cohort", "fence"},
    "proof_cohort_failed": _ENVELOPE_KEYS | {"cohort", "reason", "fence"},
    "proof_convergence_exhausted": _ENVELOPE_KEYS | {"cohorts", "exhausted_by", "fence"},
    "proof_rejected": _ENVELOPE_KEYS | {"obligations", "fence"},
    "proof_sealed": _ENVELOPE_KEYS | {"cohort", "proof_cutoff_at", "makespan_ms",
                                      "governing_window_ms", "advisory_warnings", "fence"},
})
_RESULT_KEYS = frozenset({"outcome", "reason", "reference"})
_DECIMAL = re.compile(r"[0-9]+")


def proof_refused(transaction_id: str, reason: str, detail: str) -> ProofRefused:
    """The one construction path for `ProofRefused`; a `reason` outside
    `PROOF_REFUSAL_REASONS` is a programming error (`ValueError`) (#206 D21)."""
    if reason not in PROOF_REFUSAL_REASONS:
        raise ValueError(f"proof_refused: {reason!r} is not a proof refusal reason")
    return ProofRefused(f"{transaction_id}: proof refused: {reason}: {detail}", reason=reason)


def obligation(plan: Mapping, obligation_id: str) -> dict | None:
    """The plan obligation named `obligation_id`, or None."""
    for entry in plan["obligations"]:
        if entry["obligation_id"] == obligation_id:
            return entry
    return None


def _suffix(evidence_id: Any, obligation_id: str) -> int | None:
    """`k` when `evidence_id` is exactly `<obligation_id>@<k>` with `k` all decimal digits."""
    prefix = f"{obligation_id}@"
    if type(evidence_id) is not str or not evidence_id.startswith(prefix):
        return None
    digits = evidence_id[len(prefix):]
    return int(digits) if _DECIMAL.fullmatch(digits) else None


def next_evidence_id(events: Sequence[Mapping], obligation_id: str) -> str:
    """`<obligation_id>@<n>`, n one past the largest suffix any interval, evidence or
    observation id of that obligation carries, else 1 (D25)."""
    suffixes = [_suffix(event["evidence_id"], obligation_id) for event in events
                if event["type"] in ("interval_opened", *EVIDENCE_EVENTS)]
    return f"{obligation_id}@{max((k for k in suffixes if k is not None), default=0) + 1}"


def _fold_cohort(event: Mapping, table: list[dict]) -> None:
    """Fold one cohort event into `table`; any other event changes nothing."""
    if event["type"] == "proof_cohort_started":
        table.append({"cohort": event["cohort"], "fence": event["fence"],
                      "started_ms": parse_at(event["at"]), "status": "open", "reason": None})
    elif event["type"] == "proof_cohort_failed":
        table[-1].update(status="failed", reason=event["reason"])
    elif event["type"] == "proof_sealed":
        table[-1]["status"] = "sealed"


def cohorts(events: Sequence[Mapping]) -> list[dict]:
    """One `{cohort, fence, started_ms, status, reason}` per started cohort, in order;
    `status` is `open`, `failed` or `sealed` and `reason` None unless failed (D11)."""
    table: list[dict] = []
    for event in events:
        _fold_cohort(event, table)
    return table


def _open(table: Sequence[dict]) -> dict | None:
    """The open cohort's entry, whatever its fence, or None."""
    return table[-1] if table and table[-1]["status"] == "open" else None


def _open_under(table: Sequence[dict], fence: Mapping) -> int | None:
    current = _open(table)
    return current["cohort"] if current is not None and current["fence"] == fence else None


def open_cohort(events: Sequence[Mapping], fence: Mapping) -> int | None:
    """The number of the cohort open under `fence`, or None (D27)."""
    return _open_under(cohorts(events), fence)


def convergence_start_ms(events: Sequence[Mapping]) -> int | None:
    """The `at` of the first transition into `proving`, where the window starts (D11)."""
    return next((parse_at(event["at"]) for event in events
                 if event["type"] == "transitioned" and event["to"] == "proving"), None)


def observation_request(document: dict, entry: dict, cohort: int | None) -> Mapping[str, Any]:
    """The read-only request an observer receives, carrying deep copies of the obligation's
    parameters and the held fence (D6)."""
    return MappingProxyType({
        "transaction_id": document["transaction_id"], "obligation_id": entry["obligation_id"],
        "predicate": entry["predicate"], "collector": entry["collector"],
        "parameters": copy.deepcopy(entry["parameters"]),
        "fence": copy.deepcopy(document["custody"]["fence"]), "cohort": cohort})


def closed_result_violation(result: Any, label: str) -> str | None:
    """How `result` fails the closed `{outcome, reason, reference}` shape, an `outcome` in
    `OUTCOMES` and a non-empty `reason` and `reference`, in a message starting with `label`,
    or None (#208 D26)."""
    if type(result) is not dict or set(result) != _RESULT_KEYS:
        return f"{label} is not the closed outcome/reason/reference object"
    if type(result["outcome"]) is not str or result["outcome"] not in OUTCOMES:
        return f"{label} outcome {result['outcome']!r} is not one of {OUTCOMES}"
    for name in ("reason", "reference"):
        if type(result[name]) is not str or not result[name]:
            return f"{label} {name} is not a non-empty string"
    return None


def observation_violation(result: Any, entry: Mapping) -> str | None:
    """How an observer's `result` for `entry` fails `closed_result_violation`, or None; a
    derived obligation's non-`satisfied` reason must lie in its class's closed space (D8)."""
    violation = closed_result_violation(result, "observation")
    if violation is not None:
        return violation
    if (entry["obligation_kind"] == "core_derived" and result["outcome"] != "satisfied"
            and result["reason"] not in DERIVED_REASONS[entry["derived_class"]]):
        return (f"observation reason {result['reason']!r} is not in the "
                f"{entry['derived_class']} reason space")
    return None


def _observations(events: Sequence[Mapping]) -> dict[str, list[Mapping]]:
    """Each obligation's `obligation_observed` events, in `seq` order."""
    observed: dict[str, list[Mapping]] = {}
    for event in events:
        if event["type"] == "obligation_observed":
            observed.setdefault(event["obligation_id"], []).append(event)
    return observed


def evaluate(plan: Mapping, events: Sequence[Mapping],
             cutoff_ms: int) -> dict[str, tuple[str, str]]:
    """Each obligation's (evaluation, reason) at `cutoff_ms`, in plan order (D8, D28).

    A rejected or indeterminate dep suppresses (`dependency_suppressed`); an advisory
    obligation its collector cannot observe is `unsupported`; otherwise the latest
    observation decides: none is `evidence_missing`, an inadmissible one `fence_lost`, a
    snapshot older than its freshness at the cutoff `evidence_stale`, and else `satisfied`
    is accepted and `unsatisfied` rejected with the observer's reason, `unknown`
    indeterminate with `unreachable`.
    """
    admissible = {entry["seq"]: entry["admissible"] for entry in admissibility(events)[0]}
    observed = _observations(events)
    results: dict[str, tuple[str, str]] = {}
    for entry in plan["obligations"]:
        identity = entry["obligation_id"]
        latest = observed.get(identity, [None])[-1]
        if any(results[dep][0] in ("rejected", "indeterminate") for dep in entry["deps"]):
            results[identity] = ("indeterminate", "dependency_suppressed")
        elif not entry["required"] and entry["predicate"] not in (
                plan["collectors"][entry["collector"]]["predicates"]):
            results[identity] = ("unsupported", "predicate_unsupported")
        elif latest is None:
            results[identity] = ("indeterminate", "evidence_missing")
        elif not admissible[latest["seq"]]:
            results[identity] = ("indeterminate", "fence_lost")
        elif entry["form"] == "snapshot" and (
                cutoff_ms > parse_at(latest["at"]) + entry["freshness_ms"]):
            results[identity] = ("indeterminate", "evidence_stale")
        elif latest["outcome"] == "satisfied":
            results[identity] = ("accepted", latest["reason"])
        elif latest["outcome"] == "unsatisfied":
            results[identity] = ("rejected", latest["reason"])
        else:
            results[identity] = ("indeterminate", "unreachable")
    return results


def collection_refusal(document: dict, obligation_id: Any, now_ms: int) -> str | None:
    """The first admission rule collecting `obligation_id` at `now_ms` breaks, or None
    (D7, D27): outside `proving`, an unknown obligation, a predicate its collector lacks, a
    dep not `accepted`, an `event`/`interval` obligation already `accepted`, or a
    non-member while a cohort is open under the held fence."""
    if document["state"] != "proving":
        return "state_not_proving"
    plan = document["proof_plan"]
    entry = obligation(plan, obligation_id)
    if entry is None:
        return "unknown_obligation"
    if entry["predicate"] not in plan["collectors"][entry["collector"]]["predicates"]:
        return "unsupported_obligation"
    evaluations = evaluate(plan, document["events"], now_ms)
    if any(evaluations[dep][0] != "accepted" for dep in entry["deps"]):
        return "dependency_not_accepted"
    if entry["form"] != "snapshot" and evaluations[obligation_id][0] == "accepted":
        return "already_accepted"
    if (open_cohort(document["events"], document["custody"]["fence"]) is not None
            and obligation_id not in plan["cohort"]["members"]):
        return "not_cohort_member"
    return None


def _in_cohort(events: Sequence[Mapping], cohort: int) -> dict[str, Mapping]:
    """Each obligation's latest observation recorded in `cohort`."""
    return {event["obligation_id"]: event for event in events
            if event["type"] == "obligation_observed" and event["cohort"] == cohort}


def _bound(plan: Mapping, obligation_id: str) -> int:
    return plan["collectors"][obligation(plan, obligation_id)["collector"]][
        "max_collection_latency_ms"]


def seal_violation(plan: Mapping, events: Sequence[Mapping], cohort: int) -> str | None:
    """The first clock-free seal fact `events` break for `cohort`, or None (D30, D31): every
    member observed in the cohort, each member's latest in-cohort latency within its
    collector's bound, and every required obligation's latest observation `satisfied` and
    admissible."""
    latest = _in_cohort(events, cohort)
    for member in plan["cohort"]["members"]:
        if member not in latest:
            return f"cohort member {member} has no observation in cohort {cohort}"
        if latest[member]["latency_ms"] > _bound(plan, member):
            return f"cohort member {member} latency exceeds its collector's bound"
    admissible = {entry["seq"]: entry["admissible"] for entry in admissibility(events)[0]}
    observed = _observations(events)
    for entry in plan["obligations"]:
        seen = observed.get(entry["obligation_id"], [None])[-1]
        if entry["required"] and (seen is None or seen["outcome"] != "satisfied"
                                  or not admissible[seen["seq"]]):
            return (f"required obligation {entry['obligation_id']} has no admissible "
                    f"satisfied latest observation")
    return None


def _ids(plan: Mapping, required: bool) -> list[str]:
    return [entry["obligation_id"] for entry in plan["obligations"]
            if entry["required"] is required]


def _exhausted_by(document: dict, table: Sequence[dict], now_ms: int) -> str | None:
    """`budget` when every attempt is used, else `window` when the time left in the
    convergence window is below the makespan and margin, else None (D11, D28)."""
    plan, events = document["proof_plan"], document["events"]
    if len(table) >= MAX_COHORT_ATTEMPTS:
        return "budget"
    left = convergence_start_ms(events) + plan["convergence_window_ms"] - now_ms
    return "window" if left < plan["cohort"]["makespan_ms"] + plan["cohort"]["margin_ms"] \
        else None


def cohort_start(document: dict, now_ms: int) -> list[dict]:
    """The events `start_cohort` appends at `now_ms`, or `ProofRefused` (D11): refused
    `state_not_proving`, `proof_incomplete` (a required obligation with no admissible
    `satisfied` observation, whatever its age), `cohort_open` (one open under the held
    fence) and `convergence_exhausted`, in that order. A cohort open under an older fence
    first fails `fence_changed`; the new cohort is numbered one past every started one."""
    def refuse(reason: str) -> ProofRefused:
        return proof_refused(document["transaction_id"], reason, "start_cohort")

    if document["state"] != "proving":
        raise refuse("state_not_proving")
    plan, events = document["proof_plan"], document["events"]
    fence = document["custody"]["fence"]
    admissible = {entry["seq"]: entry["admissible"] for entry in admissibility(events)[0]}
    observed = _observations(events)
    if not all(any(seen["outcome"] == "satisfied" and admissible[seen["seq"]]
                   for seen in observed.get(identity, ())) for identity in _ids(plan, True)):
        raise refuse("proof_incomplete")
    table = cohorts(events)
    current = _open(table)
    if current is not None and current["fence"] == fence:
        raise refuse("cohort_open")
    if _exhausted_by(document, table, now_ms) is not None:
        raise refuse("convergence_exhausted")
    failed = [] if current is None else [{"type": "proof_cohort_failed",
                                          "cohort": current["cohort"],
                                          "reason": "fence_changed", "fence": fence}]
    return failed + [{"type": "proof_cohort_started", "cohort": len(table) + 1,
                      "fence": fence}]


def _cohort_failure(document: dict, current: dict, evaluations: Mapping,
                    now_ms: int) -> str | None:
    """Why the open cohort `current` cannot seal at `now_ms`, the first of
    `COHORT_FAILURE_REASONS` that applies, or None when it seals (D10, D28, D30)."""
    plan, events = document["proof_plan"], document["events"]
    if current["fence"] != document["custody"]["fence"]:
        return "fence_changed"
    latest = _in_cohort(events, current["cohort"])
    members = plan["cohort"]["members"]
    governing = plan["cohort"]["governing_window_ms"]
    if ((governing is not None and now_ms - current["started_ms"] > governing)
            or now_ms > convergence_start_ms(events) + plan["convergence_window_ms"]
            or any(member in latest and now_ms > parse_at(latest[member]["at"])
                   + obligation(plan, member)["freshness_ms"] for member in members)):
        return "cohort_expired"
    if any(member not in latest for member in members):
        return "member_missing"
    if any(latest[member]["latency_ms"] > _bound(plan, member) for member in members):
        return "collection_bound_exceeded"
    if seal_violation(plan, events, current["cohort"]) is not None or any(
            evaluations[identity][0] != "accepted" for identity in _ids(plan, True)):
        return "member_indeterminate"
    return None


def _parking(reason: str) -> dict:
    return {"type": "transitioned", "from": "proving", "to": "attention_required",
            "reason": reason, "external_state": "known"}


def settlement(document: dict, now_ms: int) -> list[dict]:
    """The events `settle_proof` appends with `now_ms` as the cutoff, the first matching
    case in order (D10, D11, D21, D28), after refusing `state_not_proving`:

    1. rejected: `proof_rejected` naming every required obligation evaluating `rejected`,
       then the parking reason `proof_rejected`;
    2. seal: the cohort open under the held fence seals (`_cohort_failure` finds nothing):
       `TransitionRefused` while an action is unresolved, else `proof_sealed` and the
       transition to `succeeded`;
    3. cohort failed: the open cohort fails with its first failure reason;
    4. exhausted: with no cohort left open and the budget or window spent,
       `proof_convergence_exhausted` and the parking reason `proof_did_not_converge`;
    5. otherwise case 3's event alone, or, with none, `ProofRefused` `no_open_cohort`.
    """
    transaction_id = document["transaction_id"]
    if document["state"] != "proving":
        raise proof_refused(transaction_id, "state_not_proving", "settle_proof")
    plan, events = document["proof_plan"], document["events"]
    fence = document["custody"]["fence"]
    evaluations = evaluate(plan, events, now_ms)
    rejected = [identity for identity in _ids(plan, True)
                if evaluations[identity][0] == "rejected"]
    if rejected:
        return [{"type": "proof_rejected", "obligations": rejected, "fence": fence},
                _parking("proof_rejected")]
    table = cohorts(events)
    current = _open(table)
    appended = []
    if current is not None:
        reason = _cohort_failure(document, current, evaluations, now_ms)
        if reason is None:
            blocker = unresolved(fold_actions(events))
            if blocker is not None:
                raise TransitionRefused(f"{transaction_id}: settle_proof: seal over unresolved "
                                        f"action {blocker.action_id} ({status(blocker)})")
            return [{"type": "proof_sealed", "cohort": current["cohort"],
                     "proof_cutoff_at": format_at(now_ms),
                     "makespan_ms": plan["cohort"]["makespan_ms"],
                     "governing_window_ms": plan["cohort"]["governing_window_ms"],
                     "advisory_warnings": [identity for identity in _ids(plan, False)
                                           if evaluations[identity][0] != "accepted"],
                     "fence": fence},
                    {"type": "transitioned", "from": "proving", "to": "succeeded",
                     "reason": SEAL_REASON, "external_state": "known"}]
        appended.append({"type": "proof_cohort_failed", "cohort": current["cohort"],
                         "reason": reason, "fence": fence})
    exhausted_by = _exhausted_by(document, table, now_ms)
    if exhausted_by is not None:
        return appended + [{"type": "proof_convergence_exhausted", "cohorts": len(table),
                            "exhausted_by": exhausted_by, "fence": fence},
                           _parking("proof_did_not_converge")]
    if not appended:
        raise proof_refused(transaction_id, "no_open_cohort", "settle_proof")
    return appended


def gate_violation(plan: Mapping, actions: Mapping[str, ActionFold], source: str,
                   target: str) -> str | None:
    """The lifecycle gate `source -> target` breaks against `actions`, or None (D12):
    `publishing -> published` needs every publication unit's action `satisfied`,
    `activating -> proving` every activation unit's, and `published -> proving` a plan with
    no activation unit. Every other edge, a resume to `parked_from` included, is ungated."""
    if (source, target) == ("published", "proving"):
        return next((f"published -> proving needs a plan with no activation unit, and "
                     f"{unit['name']} is one"
                     for unit in plan["units"] if unit["phase"] == "activation"), None)
    phase = _GATES.get((source, target))
    for unit in plan["units"]:
        if unit["phase"] != phase:
            continue
        entry = actions.get(unit["action_id"])
        state = None if entry is None else status(entry)
        if state != "satisfied":
            return (f"{phase} unit {unit['name']} ({unit['action_id']}) is "
                    f"{state or 'undeclared'}")
    return None


def advance_violation(document: dict, target: str, reason: str) -> str | None:
    """Why `advance` may not take `document` to `target` with `reason`, or None (D10, D12,
    D27): `succeeded` is `settle_proof`'s, as is a parking from `proving` with a reserved
    reason, and every lifecycle gate applies."""
    source = document["state"]
    if target == "succeeded":
        return "succeeded is entered only through settle_proof"
    if (source, target) == ("proving", "attention_required") and reason in RESERVED_REASONS:
        return f"reserved reason {reason} is written only by settle_proof"
    return gate_violation(document["proof_plan"], fold_actions(document["events"]), source,
                          target)


@dataclasses.dataclass
class ProofFold:
    """What the validator folds from the proof events before the one it checks: the
    cohort table `cohorts` derives."""

    cohorts: list[dict] = dataclasses.field(default_factory=list)


def proof_event_violation(event: dict, events_before: Sequence[Mapping], fold: ProofFold, *,
                          plan: Mapping, keys: list[str], open_fence: dict | None,
                          state: str) -> str | None:
    """The first rule the closed-shape proof `event` breaks against the history before it
    and `fold`, or None. Every proof event happens in `proving`, fenced by the open span.
    An observation is of a plan obligation and its form, numbered by the core, a valid
    observation with a core-measured latency, in the cohort open under its fence (D6,
    D25); the cohort events follow `_cohort_rule` (D10, D11, D31)."""
    if state != "proving":
        return f"{event['type']} happens in {state}, not proving"
    if open_fence is None:
        return f"{event['type']} sits outside an open custody span"
    violation = fence_violation(event["fence"], keys)
    if violation is not None:
        return violation
    if event["fence"] != open_fence:
        return f"{event['type']} fence does not equal the open span's fence"
    if event["type"] != "obligation_observed":
        return _cohort_rule(event, events_before, fold.cohorts, plan)
    identity = event["obligation_id"]
    entry = obligation(plan, identity) if type(identity) is str else None
    if entry is None:
        return f"obligation_id {identity!r} names no plan obligation"
    if event["form"] != entry["form"]:
        return f"form {event['form']!r} is not the obligation's form {entry['form']!r}"
    evidence_id = event["evidence_id"]
    if _suffix(evidence_id, identity) is None:
        return f"evidence_id {evidence_id!r} is not {identity}@<decimal>"
    if entry["form"] != "interval" and evidence_id != next_evidence_id(events_before,
                                                                      identity):
        return f"evidence_id {evidence_id!r} is not the core's next evidence id"
    violation = observation_violation(
        {name: event[name] for name in _RESULT_KEYS}, entry)
    if violation is not None:
        return violation
    if type(event["latency_ms"]) is not int or event["latency_ms"] < 0:
        return "latency_ms is not an integer >= 0"
    expected = _open_under(fold.cohorts, event["fence"])
    if not _same(event["cohort"], expected):
        return f"cohort {event['cohort']!r} is not the open cohort {expected!r}"
    return None


def _same(value: Any, expected: Any) -> bool:
    return type(value) is type(expected) and value == expected


def _ordered(value: Any, ids: list[str]) -> bool:
    """`value` is a duplicate-free list of `ids` members, in their order."""
    return type(value) is list and value == [identity for identity in ids if identity in value]


def _cohort_rule(event: dict, events_before: Sequence[Mapping], table: list[dict],
                 plan: Mapping) -> str | None:
    """The first rule a cohort, exhaustion, rejection or seal event breaks, or None."""
    kind, current = event["type"], _open(table)
    if kind == "proof_cohort_started":
        if current is not None or not _same(event["cohort"], len(table) + 1) \
                or len(table) >= MAX_COHORT_ATTEMPTS:
            return f"cohort {event['cohort']!r} is not the next of {MAX_COHORT_ATTEMPTS} " \
                   f"with none open"
    elif kind == "proof_cohort_failed":
        if current is None or not _same(event["cohort"], current["cohort"]):
            return f"cohort {event['cohort']!r} is not the open cohort"
        reason = event["reason"]
        if type(reason) is not str or reason not in COHORT_FAILURE_REASONS:
            return f"reason {reason!r} is not one of {COHORT_FAILURE_REASONS}"
        if (reason == "fence_changed") != (current["fence"] != event["fence"]):
            return "reason is fence_changed exactly when the cohort's fence differs"
    elif kind == "proof_convergence_exhausted":
        if current is not None or not _same(event["cohorts"], len(table)):
            return f"cohorts {event['cohorts']!r} is not {len(table)} with none open"
        exhausted_by = event["exhausted_by"]
        if exhausted_by not in ("budget", "window") or (
                exhausted_by == "budget" and len(table) != MAX_COHORT_ATTEMPTS):
            return f"exhausted_by {exhausted_by!r} is not window or a spent budget"
    elif kind == "proof_rejected":
        if not event["obligations"] or not _ordered(event["obligations"], _ids(plan, True)):
            return "obligations is not a non-empty list of required ids in plan order"
    else:
        if current is None or current["fence"] != event["fence"] \
                or not _same(event["cohort"], current["cohort"]):
            return f"cohort {event['cohort']!r} is not open under its fence"
        violation = seal_violation(plan, events_before, current["cohort"])
        if violation is not None:
            return violation
        if event["proof_cutoff_at"] != event["at"]:
            return "proof_cutoff_at does not equal at"
        for name in ("makespan_ms", "governing_window_ms"):
            if not _same(event[name], plan["cohort"][name]):
                return f"{name} is not the plan's"
        if not _ordered(event["advisory_warnings"], _ids(plan, False)):
            return "advisory_warnings is not a list of advisory ids in plan order"
    return None


def pairing_violation(previous: Mapping | None, event: Mapping | None) -> str | None:
    """How `event`, the one after `previous` (None past the end), breaks a reserved pairing,
    or None (D10, D27): `proof_rejected` and `proof_convergence_exhausted` come immediately
    before their `proving -> attention_required` parking and `proof_sealed` immediately
    before the transition to `succeeded`; a parking with a reserved reason and a transition
    to `succeeded` come immediately after their event."""
    kind = None if previous is None else previous.get("type")
    edge = None
    if event is not None and event.get("type") == "transitioned":
        edge = (event.get("from"), event.get("to"), event.get("reason"))
    if kind in _PAIRED:
        target, reason = _PAIRED[kind]
        if edge is None or edge[1] != target or (
                reason is not None and edge != ("proving", target, reason)):
            return f"{kind} is not immediately followed by its transition to {target}"
    if edge is not None and edge[:2] == ("proving", "attention_required") \
            and edge[2] in RESERVED_REASONS and _PAIRED.get(kind, ("", ""))[1] != edge[2]:
        return f"reserved reason {edge[2]} does not immediately follow its event"
    if edge is not None and edge[1] == "succeeded" and kind != SEAL_REASON:
        return "transition to succeeded does not immediately follow proof_sealed"
    return None


def apply_proof_event(event: dict, fold: ProofFold) -> None:
    """Fold one validated proof event into `fold`'s cohort table."""
    _fold_cohort(event, fold.cohorts)


def proof_view(document: dict) -> dict:
    """The derived, clock-free `proof` view: the plan digest, each plan obligation's
    observation count, latest outcome and latest admissibility, in plan order, the cohorts
    and the seal's cutoff (D13)."""
    events = document["events"]
    admissible = {entry["seq"]: entry["admissible"] for entry in admissibility(events)[0]}
    observed = _observations(events)
    obligations = []
    for entry in document["proof_plan"]["obligations"]:
        seen = observed.get(entry["obligation_id"], [])
        obligations.append({
            **{name: entry[name] for name in ("obligation_id", "obligation_kind", "semantic",
                                              "derived_class", "form", "required")},
            "observations": len(seen),
            "latest_outcome": seen[-1]["outcome"] if seen else None,
            "latest_admissible": admissible[seen[-1]["seq"]] if seen else None})
    seal = next((event for event in events if event["type"] == "proof_sealed"), None)
    return {"plan_digest": events[0]["proof_plan_digest"], "obligations": obligations,
            "cohorts": [{name: entry[name] for name in ("cohort", "status", "reason")}
                        for entry in cohorts(events)],
            "proof_cutoff_at": None if seal is None else seal["proof_cutoff_at"]}
