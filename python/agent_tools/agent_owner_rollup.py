"""The owner report's arm and project rows, built from lineage rows through one aggregate (issue 503).

A lineage row's spend is its `total_dollars` plus its `ping_dollars`, and its owner spend is its
`owner_dollars` plus its `owner_ping_dollars`. `arm_rows` and `project_rows` both reduce rows
through `aggregate`, so an arm and one of its projects state their counts, sums and quotients
the same way. python/README.md (agent-costs) holds the contract.
"""

import statistics
from collections import defaultdict

from agent_tools.agent_costs import percentile


def spend(row: dict) -> float:
    """A lineage row's spend: `total_dollars + ping_dollars`."""
    return row["total_dollars"] + row["ping_dollars"]


def owner_spend(row: dict) -> float:
    """A lineage row's owner spend: `owner_dollars + owner_ping_dollars`."""
    return row["owner_dollars"] + row["owner_ping_dollars"]


def _quotient(numerator, denominator):
    return numerator / denominator if denominator else None


def aggregate(rows: list[dict]) -> dict:
    """Counts, sums and quotients of `rows`; a quotient over a zero denominator is None."""
    delivered = sum(1 for row in rows if row["delivered"])
    return {
        "n": len(rows), "delivered": delivered,
        "delivery_rate": _quotient(delivered, len(rows)),
        "dollars_per_delivered": _quotient(sum((spend(row) for row in rows), 0.0), delivered),
        "owner_dollars_per_lineage": _quotient(sum((owner_spend(row) for row in rows), 0.0),
                                               len(rows)),
        "owner_dollars": sum((row["owner_dollars"] for row in rows), 0.0),
        "owner_ping_dollars": sum((row["owner_ping_dollars"] for row in rows), 0.0),
        "total_dollars": sum((row["total_dollars"] for row in rows), 0.0),
        "ping_dollars": sum((row["ping_dollars"] for row in rows), 0.0),
    }


def arm_rows(rows: list[dict], required=()) -> list[dict]:
    """One row per arm: the `required` arms first, in their order and each with a row even when
    it has no lineage, then any other arm, by name. A row holds the aggregate's quotients plus the
    delivered spend's sd (None below two), the undelivered rows' spend and the rows' peak-context
    p50 and p90."""
    arms = defaultdict(list)
    for row in rows:
        arms[row["arm"]].append(row)
    result = []
    for arm in [*required, *sorted(set(arms) - set(required))]:
        members = arms.get(arm, [])
        total = aggregate(members)
        delivered = [spend(row) for row in members if row["delivered"]]
        peaks = [row["peak_context"] for row in members]
        result.append({
            "arm": arm, "n": total["n"], "delivered": total["delivered"],
            "delivery_rate": total["delivery_rate"],
            "dollars_per_delivered": total["dollars_per_delivered"],
            "owner_dollars_per_lineage": total["owner_dollars_per_lineage"],
            "sd": statistics.stdev(delivered) if len(delivered) >= 2 else None,
            "undelivered_dollars": sum((spend(row) for row in members if not row["delivered"]),
                                       0.0),
            "ping_dollars": total["ping_dollars"],
            "peak_p50": percentile(peaks, 50), "peak_p90": percentile(peaks, 90),
        })
    return result


def project_rows(rows: list[dict], arms: list[str]) -> list[dict]:
    """For each arm of `arms`, in that order, the aggregate of each of its projects, by project."""
    result = []
    for arm in arms:
        projects = defaultdict(list)
        for row in rows:
            if row["arm"] == arm:
                projects[row["project"]].append(row)
        result.extend({"arm": arm, "project": project, **aggregate(projects[project])}
                      for project in sorted(projects))
    return result


def _ratio(candidate, baseline):
    return None if candidate is None or baseline is None or baseline == 0 else candidate / baseline


def comparison(arms: list[dict], projects: list[dict], baseline: str, candidate: str) -> dict:
    """The candidate arm over the baseline arm: the two arm ratios and, per project of either
    arm, the owner-spend ratio and the delivery-rate change (candidate minus baseline, a fraction;
    None unless both arms have the project). A ratio is None when a side is None or the baseline is 0."""
    by_arm = {row["arm"]: row for row in arms}
    base, cand = by_arm[baseline], by_arm[candidate]
    rows = {(row["arm"], row["project"]): row for row in projects}
    names = sorted({project for arm, project in rows if arm in (baseline, candidate)})
    entries = []
    for name in names:
        before, after = rows.get((baseline, name)), rows.get((candidate, name))
        both = before is not None and after is not None
        entries.append({
            "project": name,
            "owner_dollars_per_lineage_ratio": _ratio(
                after["owner_dollars_per_lineage"], before["owner_dollars_per_lineage"]) if both else None,
            "delivery_rate_change": after["delivery_rate"] - before["delivery_rate"] if both else None,
        })
    return {
        "owner_dollars_per_lineage_ratio": _ratio(cand["owner_dollars_per_lineage"],
                                                  base["owner_dollars_per_lineage"]),
        "dollars_per_delivered_ratio": _ratio(cand["dollars_per_delivered"],
                                              base["dollars_per_delivered"]),
        "projects": entries,
    }
