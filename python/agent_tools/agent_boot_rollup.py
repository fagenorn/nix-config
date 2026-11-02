"""The boot report's group rows, built from boot rows (issues 448, 504).

Pure statistics over the boot rows agent_tools.agent_boot_report collects: per host, cohort
and phase group, the count and the mean and median per boot. python/README.md (agent-costs)
holds the contract.
"""

import statistics

ALL = "all"
COHORTS = ("fresh", "spawned")
PHASE_GROUPS = ("0-5", "6-7", ALL)


def median(values, weights=None):
    """The median of `values`, a float, or None when there are none.

    Each value has its weight in `weights` (1 each without), and weights are positive ints or
    Fractions. It is the first value in sorted order whose cumulative weight reaches half the
    total, or the mean of that value and the next when the cumulative weight is exactly half.
    With equal weights that is `statistics.median` (issue 504 D4).
    """
    values = list(values)
    if not values:
        return None
    pairs = sorted(zip(values, weights if weights is not None else [1] * len(values)),
                   key=lambda pair: pair[0])
    total = sum(weight for _, weight in pairs)
    cumulative = 0
    for index, (value, weight) in enumerate(pairs):
        cumulative += weight
        if 2 * cumulative == total:
            return (value + pairs[index + 1][0]) / 2
        if 2 * cumulative > total:
            return float(value)


def group_rows(arm, host, boots, buckets):
    """The group rows of one arm's one host's `boots` (`arm` is the arm they all belong to and
    `host` a label or ALL).

    There is one row per cohort and phase group (ALL pools both) that has a boot, in
    COHORTS x PHASE_GROUPS order. A row holds the count and the per-boot mean and median of B,
    B without tool schemas, both sub-totals and each of `buckets`.
    """
    rows = []
    for cohort in COHORTS:
        for group in PHASE_GROUPS:
            members = [boot for boot in boots if boot["cohort"] == cohort
                       and group in (ALL, boot["phase_group"])]
            if not members:
                continue
            b = [boot["b"] for boot in members]
            b_without_schemas = [boot["b"] - boot["buckets"]["tool_schemas"] for boot in members]
            boot_reading = [boot["boot_reading"] for boot in members]
            first_unit_work = [boot["first_unit_work"] for boot in members]
            rows.append({
                "arm": arm, "host": host, "cohort": cohort, "phase_group": group, "count": len(members),
                "b_mean": statistics.fmean(b), "b_median": median(b),
                "b_without_schemas_mean": statistics.fmean(b_without_schemas),
                "b_without_schemas_median": median(b_without_schemas),
                "boot_reading_mean": statistics.fmean(boot_reading),
                "boot_reading_median": median(boot_reading),
                "first_unit_work_mean": statistics.fmean(first_unit_work),
                "first_unit_work_median": median(first_unit_work),
                "buckets": {name: statistics.fmean(boot["buckets"][name] for boot in members)
                            for name in buckets},
                "bucket_medians": {name: median(boot["buckets"][name] for boot in members)
                                   for name in buckets}})
    return rows
