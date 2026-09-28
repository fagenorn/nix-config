"""Proof obligations over a transaction's history (#207 D6-D8, D22, D25): the observation
and evaluation vocabularies, the closed `ProofRefused` reasons and their one construction
path, the core-minted evidence ids, collection admission, the observer's request and result
check, the pure evaluation at a cutoff, the validator's `obligation_observed` rules and the
derived `proof` view.

`agent_tools.transaction_history` hands every proof event to `proof_event_violation` and
`apply_proof_event`, and `agent_tools.transaction_core`'s `collect_obligation` keeps only the
locks, the clock, the observer call and the writes around the pure halves held here. Every
function here is pure: the module reads no file, lock or clock.
"""

import copy
import dataclasses
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from agent_tools.transaction_custody import EVIDENCE_EVENTS, admissibility, fence_violation
from agent_tools.transaction_plan import DERIVED_REASONS
from agent_tools.transaction_storage import ProofRefused, parse_at

OUTCOMES = ("satisfied", "unsatisfied", "unknown")
EVALUATIONS = ("accepted", "rejected", "indeterminate", "not_applicable", "unsupported")
PROOF_REFUSAL_REASONS = (
    "state_not_proving", "unknown_obligation", "unsupported_obligation",
    "dependency_not_accepted", "already_accepted", "not_cohort_member", "clock_regressed",
    "proof_incomplete", "cohort_open", "convergence_exhausted", "no_open_cohort")

_ENVELOPE_KEYS = frozenset({"seq", "type", "at"})
PROOF_EVENT_KEYS: Mapping[str, frozenset[str]] = MappingProxyType({
    "obligation_observed": _ENVELOPE_KEYS | {
        "obligation_id", "evidence_id", "form", "outcome", "reason", "reference", "fence",
        "cohort", "latency_ms"},
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


def open_cohort(events: Sequence[Mapping], fence: Mapping) -> int | None:
    """The number of the cohort open under `fence`, or None; no history holds a cohort yet."""
    return None


def observation_request(document: dict, entry: dict, cohort: int | None) -> Mapping[str, Any]:
    """The read-only request an observer receives, carrying deep copies of the obligation's
    parameters and the held fence (D6)."""
    return MappingProxyType({
        "transaction_id": document["transaction_id"], "obligation_id": entry["obligation_id"],
        "predicate": entry["predicate"], "collector": entry["collector"],
        "parameters": copy.deepcopy(entry["parameters"]),
        "fence": copy.deepcopy(document["custody"]["fence"]), "cohort": cohort})


def observation_violation(result: Any, entry: Mapping) -> str | None:
    """How an observer's `result` for `entry` fails the closed `{outcome, reason, reference}`
    shape, or None; a derived obligation's non-`satisfied` reason must lie in its class's
    closed space (D8)."""
    if type(result) is not dict or set(result) != _RESULT_KEYS:
        return "observation is not the closed outcome/reason/reference object"
    if type(result["outcome"]) is not str or result["outcome"] not in OUTCOMES:
        return f"observation outcome {result['outcome']!r} is not one of {OUTCOMES}"
    for name in ("reason", "reference"):
        if type(result[name]) is not str or not result[name]:
            return f"observation {name} is not a non-empty string"
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
    (D7): outside `proving`, an unknown obligation, a predicate its collector lacks, a dep
    not `accepted`, or an `event`/`interval` obligation already `accepted`."""
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
    return None


@dataclasses.dataclass
class ProofFold:
    """What the validator folds from the proof events before the one it checks; the
    observation rules read the history before it and fold nothing."""


def proof_event_violation(event: dict, events_before: Sequence[Mapping], fold: ProofFold, *,
                          plan: Mapping, keys: list[str], open_fence: dict | None,
                          state: str) -> str | None:
    """The first rule the closed-shape proof `event` breaks against the history before it,
    or None (D6, D25): observed in `proving`, fenced by the open span, of a plan obligation
    and its form, numbered by the core, a valid observation, a core-measured latency, and
    the cohort open under its fence."""
    if state != "proving":
        return f"{event['type']} happens in {state}, not proving"
    if open_fence is None:
        return f"{event['type']} sits outside an open custody span"
    violation = fence_violation(event["fence"], keys)
    if violation is not None:
        return violation
    if event["fence"] != open_fence:
        return f"{event['type']} fence does not equal the open span's fence"
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
    expected = open_cohort(events_before, event["fence"])
    if type(event["cohort"]) is not type(expected) or event["cohort"] != expected:
        return f"cohort {event['cohort']!r} is not the open cohort {expected!r}"
    return None


def apply_proof_event(event: dict, fold: ProofFold) -> None:
    """Fold one validated proof event into `fold`; an observation changes nothing there."""


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
    return {"plan_digest": events[0]["proof_plan_digest"], "obligations": obligations,
            "cohorts": [], "proof_cutoff_at": None}
