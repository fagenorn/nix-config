"""Scenario table: the cases ticket #86 requires, applied to any of the four shapes.

A scenario is a set of world faults plus (rarely) a read-only mutation of the authored
profile, so the same core is pushed through success, resume, partial publication, failed
activation, false-positive health, irreversible migration, rollback and
unsupported-operation paths without the core learning which project it is looking at.
"""
from __future__ import annotations


def _add_unsupported_publication(subject, profile, registry):
    """Author a publication action whose bound adapter reports the mode unsupported."""
    for alias, binding in profile["bindings"].items():
        if alias.startswith("_"):
            continue
        adapter = registry[binding["adapter"]]
        if adapter.describe()["modes"].get("promote") != "supported":
            profile["publication"].append({
                "id": "unsupported_promote", "mode": "promote", "binding": alias,
                "deps": [], "effect_class": "reversible_no_incremental_spend",
                "expected_subject": {"note": "authored against an unsupported mode"}})
            return
    profile["publication"].append({
        "id": "unknown_mode", "mode": "teleport", "binding": "index", "deps": [],
        "effect_class": "reversible_no_incremental_spend", "expected_subject": {}})


SCENARIOS = [
    {"name": "success",
     "faults": set(), "mutate": None, "arm_crash": False,
     "note": "clean path: publish, activate, prove, seal a terminal receipt."},

    {"name": "throttled_retry",
     "faults": {"throttle_once"}, "mutate": None, "arm_crash": False,
     "note": "first mutating invoke is throttled and inspect proves absent -> "
             "one automatic retry inside the 15m window."},

    {"name": "resume_after_crash",
     "faults": set(), "mutate": None, "arm_crash": True,
     "note": "executor dies right after an invoke. Press [u] to take over: the new "
             "executor fences up and inspects every action carrying durable intent."},

    {"name": "partial_publication",
     "faults": {"partial_publication"}, "mutate": None, "arm_crash": False,
     "note": "an index/channel target already holds a different identity -> diverged, "
             "no clobber, no final publication receipt."},

    {"name": "failed_activation",
     "faults": {"activation_failure"}, "mutate": None, "arm_crash": False,
     "note": "invoke is accepted but the provider/host terminal state is failure and the "
             "previous code is still live."},

    {"name": "stale_false_positive_health",
     "faults": {"stale_health"}, "mutate": None, "arm_crash": False,
     "note": "liveness is satisfied while the running subject is the PREVIOUS code. The "
             "mandatory subject-identity floor must reject it."},

    {"name": "irreversible_migration",
     "faults": set(), "mutate": None, "arm_crash": False,
     "note": "shapes carrying a forward-only migration declare the unit irreversible; it "
             "needs fresh one-action confirmation [c] and can never be auto-retried."},

    {"name": "rollback",
     "faults": {"activation_failure"}, "mutate": None, "arm_crash": False,
     "tick": 20,
     "note": "same fault as failed_activation, driven the other way: [R] reconcile, "
             "[G] grant recovery, [n] run the subgraph — restore plus declared bounded "
             "residue, or a truthful non-rollback."},

    {"name": "incompatible_restore",
     "faults": {"activation_failure", "restore_incompatible"}, "mutate": None,
     "arm_crash": False,
     "note": "the prior subject is incompatible with the migrated data epoch, so restore "
             "is inadmissible and recovery never runs an implicit down migration."},

    {"name": "unsupported_operation",
     "faults": set(), "mutate": _add_unsupported_publication, "arm_crash": False,
     "note": "the profile authors an action whose bound adapter reports the mode "
             "unsupported: rejected at resolution, before any mutation."},

    {"name": "missing_rollback_anchor",
     "faults": {"missing_anchor"}, "mutate": None, "arm_crash": False,
     "note": "a unit claims `restorable` but the anchor is not retained -> preflight "
             "blocks before the first side effect."},

    {"name": "unknown_external_state",
     "faults": {"unknown_inspection"}, "mutate": None, "arm_crash": False,
     "note": "the provider cannot be observed at all. Unknown is never terminal and "
             "never authorises a replay."},

    {"name": "fleet_stall",
     "faults": {"member_stale"}, "mutate": None, "arm_crash": False,
     "note": "one frozen member of a convergent unit never reports the desired digest, so "
             "activation stays in_progress and nothing is re-invoked."},

    {"name": "expired_snapshot",
     "faults": set(), "mutate": None, "arm_crash": False,
     "tick": 250,
     "note": "the clock runs faster than the freshness window, so a snapshot expires "
             "before the common cutoff and must be recollected [x], never extended."},
]

BY_NAME = {s["name"]: s for s in SCENARIOS}
