"""Simulated external world + the describe/inspect/invoke adapter seam.

Nothing in here touches a real provider. `invoke` writes into `World.effects`, an
in-memory dict; `inspect` reads it back. That is deliberate: the prototype is a
no-mutation dry run, so "the provider" is a dictionary and the interesting content is
*which typed observation* each adapter is able to return.

Every adapter is a `SimAdapter` with exactly three core-facing operations (#85). The core
never learns a provider verb; adapters never decide action, phase, or release truth.
"""
from __future__ import annotations

EFFECT_MODES = ("materialize", "promote", "index",
                "local_apply", "provider_deploy", "publication_triggered", "convergent_pull",
                # recovery ops are effects too
                "restore_apply", "restore_publish", "restore_deploy", "compensate")

FAULTS = (
    "verification_fails",       # candidate never passes pre-release verification
    "throttle_once",            # first mutating invoke is throttled, effect provably absent
    "partial_publication",      # index lands on a different identity -> diverged, no clobber
    "activation_failure",       # deploy accepted but provider terminal state is failure
    "stale_health",             # liveness 200 from the *previous* code (false positive)
    "unknown_inspection",       # provider cannot be observed at all
    "missing_anchor",           # declared rollback anchor is not retained
    "member_stale",             # one frozen fleet member never converges
    "smoke_fail",               # interval product smoke fails
    "restore_incompatible",     # prior subject incompatible with current schema/data epoch
    "crash_after_invoke",       # executor dies between invoke and observation
)


class World:
    def __init__(self):
        self.clock = 0
        self.faults: set[str] = set()
        self.effects: dict[str, dict] = {}
        self.throttled: dict[str, int] = {}
        self.crash_pending = False
        self.notes: list[str] = []

    def tick(self, seconds: int) -> None:
        self.clock += seconds

    def toggle(self, fault: str) -> None:
        self.faults.symmetric_difference_update({fault})

    def arm_crash(self) -> None:
        self.crash_pending = True


def _obs(outcome, reason, subject=None, ref="evidence://sim"):
    return {"outcome": outcome, "reason": reason,
            "observed_subject": subject or {}, "payload_ref": ref}


class SimAdapter:
    """One deep adapter module: describe / inspect / invoke, strict typed results."""

    def __init__(self, name, contract_version, impl_digest, world,
                 modes: dict, predicates: dict,
                 fault_effects: dict | None = None,   # fault -> (state, reason, modes)
                 predicate_hooks: dict | None = None):
        self.name = name
        self.contract_version = contract_version
        self.impl_digest = impl_digest
        self.world = world
        self.modes = modes
        self.predicates = predicates
        self.fault_effects = fault_effects or {}
        self.predicate_hooks = predicate_hooks or {}

    # -- 1. describe: pure static versioned metadata ----------------------
    def describe(self) -> dict:
        return {"adapter": self.name,
                "adapter_contract_version": self.contract_version,
                "implementation_digest": self.impl_digest,
                "modes": self.modes,
                "predicates": self.predicates}

    # -- 2. inspect: every read-only observation --------------------------
    def inspect(self, op: str, env: dict) -> dict:
        if op in EFFECT_MODES:
            return self._inspect_effect(op, env)
        hook = self.predicate_hooks.get(op)
        if hook is None:
            return _obs("unknown", f"no collector for predicate {op!r} on {self.name}")
        return hook(self.world, env)

    def _inspect_effect(self, op: str, env: dict) -> dict:
        if "unknown_inspection" in self.world.faults:
            return _obs("unknown", "provider unreachable; external state cannot be observed")
        rec = self.world.effects.get(env["action_id"])
        if rec is None:
            return _obs("absent", "no effect recorded for this idempotency key")
        if rec["state"] == "satisfied" and rec["subject"] == env["expected_subject"]:
            return _obs("satisfied", rec.get("reason", "exact expected subject observed"),
                        rec["subject"])
        if rec["state"] == "in_progress":
            return _obs("in_progress", rec.get("reason", "provider still working"),
                        rec["subject"])
        if rec["state"] == "unknown":
            return _obs("unknown", rec.get("reason", "indeterminate provider state"),
                        rec["subject"])
        return _obs("diverged", rec.get("reason", "target holds a different identity"),
                    rec["subject"])

    # -- 3. invoke: one predeclared effect, never a truth claim -----------
    def invoke(self, op: str, env: dict) -> dict:
        if self.modes.get(op) not in ("supported", None) and op in EFFECT_MODES \
                and op in self.modes and self.modes[op] != "supported":
            return {"result": "rejected", "error_class": "unsupported_operation"}
        key = env["action_id"]
        if "throttle_once" in self.world.faults and self.world.throttled.get(key, 0) == 0:
            self.world.throttled[key] = 1
            return {"result": "rejected", "error_class": "provider_throttled"}
        # A forward-path fault must not also poison the recovery path for the same adapter.
        recovery_op = op.startswith("restore_") or op == "compensate"
        for fault, spec in ({} if recovery_op else self.fault_effects).items():
            state, reason, modes = (spec if len(spec) == 3 else (*spec, None))
            if fault in self.world.faults and (modes is None or op in modes):
                self.world.effects[key] = {"subject": env["expected_subject"],
                                           "state": state, "reason": reason}
                return {"result": "accepted", "correlation": f"{self.name}:{key}"}
        self.world.effects[key] = {"subject": env["expected_subject"], "state": "satisfied",
                                   "reason": "exact expected subject observed"}
        return {"result": "accepted", "correlation": f"{self.name}:{key}"}


# ---------------------------------------------------------------------------
# Reusable predicate hooks
# ---------------------------------------------------------------------------
def hook_ok(reason, subject_key="expected_subject"):
    def h(world, env):
        return _obs("satisfied", reason, env.get(subject_key))
    return h


def hook_fault(fault, ok_reason, bad_reason, bad_outcome="unsatisfied", observed=None):
    def h(world, env):
        if fault in world.faults:
            return _obs(bad_outcome, bad_reason, observed or {"observed": "other identity"})
        return _obs("satisfied", ok_reason, env.get("expected_subject"))
    return h


def _is_prior(subject) -> bool:
    """Does this expected subject name a retained prior identity (a restore target)?"""
    return "prev" in str(subject).lower() or "prior" in str(subject).lower()


def hook_identity(fault, ok_reason, bad_reason, observed=None):
    """Running-subject identity. A false-positive-health fault means the PREVIOUS code is
    live, so the same observation legitimately *satisfies* a restore target."""
    def h(world, env):
        if fault in world.faults and not _is_prior(env.get("expected_subject")):
            return _obs("unsatisfied", bad_reason, observed or {"observed": "previous subject"})
        return _obs("satisfied", ok_reason, env.get("expected_subject"))
    return h


def hook_anchor(anchor_reason):
    def h(world, env):
        if "missing_anchor" in world.faults:
            return _obs("absent", "declared anchor is not retained; restore has no target")
        return _obs("satisfied", anchor_reason, env.get("expected_subject"))
    return h


def hook_compatibility():
    def h(world, env):
        if "restore_incompatible" in world.faults:
            return _obs("unsatisfied",
                        "prior subject incompatible with the current schema/data epoch; "
                        "recovery never runs an implicit down migration")
        return _obs("satisfied", "prior subject compatible with the current data epoch",
                    env.get("expected_subject"))
    return h


def hook_fleet(members=("vps-a", "vps-b", "vps-c")):
    def h(world, env):
        stale = [m for m in members if "member_stale" in world.faults and m == members[-1]]
        if stale:
            return _obs("unsatisfied",
                        f"frozen membership snapshot: {stale} still report the prior digest",
                        {"members": list(members), "converged": len(members) - len(stale)})
        return _obs("satisfied",
                    f"all {len(members)} frozen members report the exact desired digest",
                    {"members": list(members), "converged": len(members)})
    return h


def hook_interval(fault="smoke_fail"):
    def h(world, env):
        if fault in world.faults:
            return _obs("unsatisfied", "interval smoke closed with failures")
        return _obs("satisfied",
                    "interval closed; declared completeness predicate met over samples",
                    env.get("expected_subject"))
    return h


def hook_verification(fault="verification_fails"):
    def h(world, env):
        if fault in world.faults:
            return _obs("unsatisfied", "candidate verification failed")
        return _obs("satisfied", "digest-addressed verification receipt accepted",
                    env.get("expected_subject"))
    return h
