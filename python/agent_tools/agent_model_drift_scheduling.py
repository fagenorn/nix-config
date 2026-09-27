"""Pure scheduling and accounting-context projections for drift reports."""
from __future__ import annotations

from agent_tools.agent_model_drift_schema import SCHEDULING_METRICS
from agent_tools.canonical import telemetry_digest


def _merged(coverages):
    reasons = {}
    for coverage in coverages:
        for reason in coverage["reasons"]:
            reasons[reason["code"]] = reasons.get(reason["code"], 0) + reason["count"]
    eligible = sum(coverage["eligible_events"] for coverage in coverages)
    paired = sum(coverage["paired_events"] for coverage in coverages)
    items = [{"code": code, "count": reasons[code]} for code in sorted(reasons)]
    return {"state": "full" if not items else "partial" if paired else "none",
            "eligible_events": eligible, "paired_events": paired, "reasons": items}


def _full(metric):
    return metric["coverage"]["state"] == "full"


def _validate_pairs(runs, event_window):
    window_digest = telemetry_digest(event_window)
    for run in runs:
        metrics = run["scheduling"]
        wait, covered = metrics["wait_input_tokens"], metrics["covered_input_tokens"]
        if _full(wait) and _full(covered) and wait["cohort_digest"] != covered["cohort_digest"]:
            raise ValueError("token cohorts disagree")
        capacity, claimed = (metrics["slot_capacity_seconds"],
                             metrics["claimed_slot_seconds"])
        if _full(capacity) and _full(claimed):
            if (capacity["cohort_digest"] != window_digest
                    or claimed["cohort_digest"] != window_digest):
                raise ValueError("slot cohort is not the event window")
            if claimed["value"] > capacity["value"]:
                raise ValueError("claimed slots exceed capacity")


def _aggregate_metric(name, runs, source_coverage):
    authoritative = source_coverage["scheduling"][name]
    contributions = [run["scheduling"][name] for run in runs]
    source_only = source_coverage["source_only"]
    coverages = [metric["coverage"] for metric in contributions]
    for item in source_only.values():
        coverage = item["scheduling"][name]
        coverages.append(coverage)
        if coverage["state"] == "full" and (coverage["eligible_events"] != 0
                                               or coverage["paired_events"] != 0):
            raise ValueError("source-only full metric is not zero-event")
    if _merged(coverages) != authoritative:
        raise ValueError("scheduling coverage does not match contributions")
    available = (authoritative["state"] == "full" and all(_full(metric)
                 for metric in contributions)
                 and all(item["scheduling"][name]["state"] == "full"
                         for item in source_only.values()))
    if not available:
        return {"value": None, "coverage": authoritative, "cohort_digest": None}
    digests = [metric["cohort_digest"] for metric in contributions]
    return {"value": sum(metric["value"] for metric in contributions),
            "coverage": authoritative, "cohort_digest": telemetry_digest(sorted(digests))}


def _ratio(metrics, numerator, denominator):
    top, bottom = metrics[numerator], metrics[denominator]
    if top["coverage"]["state"] != "full" or bottom["coverage"]["state"] != "full":
        return None
    if bottom["value"] == 0:
        return None
    return top["value"] / bottom["value"]


def project_scheduling(runs: list[dict], source_coverage: dict,
                       event_window: dict) -> dict:
    """Aggregate producer scheduling telemetry without inspecting source data."""
    _validate_pairs(runs, event_window)
    metrics = {name: _aggregate_metric(name, runs, source_coverage)
               for name in SCHEDULING_METRICS}
    states = {metric["coverage"]["state"] for metric in metrics.values()}
    state = ("measured" if states == {"full"} else "partial"
             if states & {"full", "partial"} else "unmeasured")
    return {"state": state, "metrics": metrics,
            "wait_token_share": _ratio(metrics, "wait_input_tokens", "covered_input_tokens"),
            "occupancy": _ratio(metrics, "claimed_slot_seconds", "slot_capacity_seconds")}


def project_context(fleet: dict) -> dict:
    """Project the descriptive cache-read ratio from already-structured totals."""
    if not isinstance(fleet, dict):
        raise ValueError("fleet is invalid")
    totals = fleet.get("totals", {})
    if not isinstance(totals, dict):
        raise ValueError("fleet totals invalid")
    numerator, denominator = totals.get("cache_read"), totals.get("input_total")
    for value in (numerator, denominator):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)
                                  or value < 0):
            raise ValueError("cache totals invalid")
    if numerator is not None and denominator is not None and numerator > denominator:
        raise ValueError("cache read exceeds input total")
    value = (None if numerator is None or denominator is None or denominator == 0
             else numerator / denominator)
    return {"cache_read_ratio": {"value": value, "numerator": numerator,
             "denominator": denominator,
             "coverage": "measured" if value is not None else "unavailable"}}
