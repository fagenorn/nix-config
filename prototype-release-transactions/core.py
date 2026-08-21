"""Release-transaction core — the portable part of this prototype.

QUESTION THIS PROTOTYPE ANSWERS (wayfind ticket #86)
----------------------------------------------------
Does the release contract settled by #81/#82/#83/#84/#85/#87/#88 survive concrete,
no-mutation dry runs for three unlike real projects (nix-config, Nodo, Argus) and one
adversarial future shape (publish-only library that cannot recall a published artifact)
*without a single project-specific branch inside the core*?

The invariant under test is mechanical and checkable by reading this file: it must contain
no project name, no provider name, no provider verb, and no `if project == ...`. Everything
project-shaped lives in `profiles.py`; everything provider-shaped lives behind the
describe/inspect/invoke adapter seam in `world.py`. Any place where the core *had* to learn
a project fact is recorded as a GAP via `Run.gap()` and surfaced in the TUI — those gaps are
the deliverable, not this code.

Throwaway. No persistence, no tests, no error handling beyond runnability. Simulated
external world only: nothing here tags, publishes, deploys, activates, restarts or writes
outside this directory.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Closed core vocabularies (#82, #81, #84, #88, #83). Unknown values fail closed.
# ---------------------------------------------------------------------------
CORE_STATES = (
    "created", "awaiting_verification", "ready", "publishing", "published",
    "activating", "proving",
)
NONTERMINAL_BRANCHES = ("attention_required", "recovering")
TERMINALS = ("succeeded", "abandoned", "rolled_back", "failed")

PUBLICATION_MODES = ("materialize", "promote", "index")
ACTIVATION_MODES = ("local_apply", "provider_deploy", "publication_triggered", "convergent_pull")
RECOVERY_ACTIONS = ("restore", "compensate")
POSTURES = ("restorable", "compensatable", "supersedable_only", "manual_only")

EFFECT_INSPECT = ("absent", "in_progress", "satisfied", "diverged", "unknown")
PREDICATE_INSPECT = ("satisfied", "unsatisfied", "unknown")
INVOKE_RESULTS = ("accepted", "rejected", "unknown")

PROOF_SEMANTICS = ("liveness", "readiness", "product_smoke", "observability", "rollback_readiness")
TEMPORAL_FORMS = ("event", "snapshot", "interval")
# Not in #88's closed profile vocabulary — see Run._derive_floor_obligations.
DERIVED_SEMANTIC = "subject_identity"
EVALUATIONS = ("accepted", "rejected", "indeterminate", "not_applicable", "unsupported")

EFFECT_CLASSES = ("reversible_no_incremental_spend", "reversible_bounded_spend", "irreversible")
RETRYABLE_ERROR_CLASSES = ("transient_transport", "provider_throttled", "provider_unavailable")

PROFILE_GROUPS = (
    "profile_version", "target", "requirements", "bindings",
    "publication", "activation", "proof", "recovery", "limits",
)

MAX_ATTEMPTS = 3               # 1 initial + 2 automatic (#82)
RETRY_WINDOW_SECONDS = 15 * 60
CORE_MAX_FRESHNESS = 30 * 60


GAP_FENCE_RENEWAL = (
    "Leases expire and must be reacquired with a NEWER fence, but #88 only admits evidence "
    "matching the current fencing epoch — so an ordinary lease renewal by the same owner "
    "silently invalidates proof it already collected. The contract never distinguishes lease "
    "loss from lease renewal; it needs owner-scoped evidence admissibility, or a renewal that "
    "preserves the epoch, or an explicit rule that proof restarts on every renewal.")


def digest(obj: Any) -> str:
    """SHA-256 over RFC-8785-ish canonical JSON (sorted keys, tight separators)."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()[:16]


class ContractError(Exception):
    """Structural rejection before any mutation: invalid_contract / inadmissible."""


# ---------------------------------------------------------------------------
# Resolution (#85): compile authored profile -> immutable ResolvedReleaseProfile
# ---------------------------------------------------------------------------
@dataclass
class ResolvedProfile:
    profile_id: str
    profile_version: int
    profile_digest: str
    target: dict
    publication: list
    activation: list          # [] means declared `none`
    activation_declared_none: bool
    proof: list
    recovery: dict
    limits: dict
    bindings: dict
    adapters: dict            # alias -> adapter instance (exact selected identity)
    adapter_identities: dict


def _toposort(nodes: list, label: str) -> list:
    by_id = {n["id"]: n for n in nodes}
    if len(by_id) != len(nodes):
        raise ContractError(f"invalid_contract: duplicate node id in {label}")
    seen, stack, ordered = set(), set(), []

    def visit(nid):
        if nid in seen:
            return
        if nid in stack:
            raise ContractError(f"invalid_contract: cycle in {label} at {nid}")
        stack.add(nid)
        for dep in by_id[nid].get("deps", []):
            if dep not in by_id:
                raise ContractError(
                    f"invalid_contract: {label} node {nid} depends on unknown {dep}")
            visit(dep)
        stack.discard(nid)
        seen.add(nid)
        ordered.append(by_id[nid])

    for n in nodes:
        visit(n["id"])
    return ordered


def resolve(profile: dict, registry: dict) -> ResolvedProfile:
    unknown = set(profile) - set(PROFILE_GROUPS)
    if unknown:
        raise ContractError(f"invalid_contract: unknown profile groups {sorted(unknown)}")
    missing = set(PROFILE_GROUPS) - set(profile)
    if missing:
        raise ContractError(f"invalid_contract: missing profile groups {sorted(missing)}")

    bindings = profile["bindings"]
    adapters, identities = {}, {}
    for alias, binding in bindings.items():
        if alias.startswith("_"):
            continue
        name = binding["adapter"]
        if name not in registry:
            raise ContractError(f"invalid_contract: binding {alias} names unknown adapter {name}")
        adapter = registry[name]
        d = adapter.describe()
        lo, hi = binding["contract_range"]           # inclusive min, exclusive max
        if not (lo <= d["adapter_contract_version"] < hi):
            raise ContractError(
                f"invalid_contract: {alias} adapter {name} v{d['adapter_contract_version']} "
                f"outside [{lo},{hi})")
        adapters[alias] = adapter
        identities[alias] = f"{name}@{d['adapter_contract_version']}+{d['implementation_digest']}"

    def check_support(node, kind, allowed_modes):
        if node["mode"] not in allowed_modes:
            raise ContractError(f"invalid_contract: unknown {kind} mode {node['mode']!r}")
        alias = node["binding"]
        if alias not in adapters:
            raise ContractError(
                f"invalid_contract: {node['id']} references unknown binding {alias}")
        d = adapters[alias].describe()
        if d["modes"].get(node["mode"]) != "supported":
            reason = d["modes"].get(node["mode"], "unknown_mode")
            raise ContractError(
                f"invalid_contract: {node['id']} references unsupported mode "
                f"{node['mode']} on {alias} ({reason})")
        if node["effect_class"] not in EFFECT_CLASSES:
            raise ContractError(f"invalid_contract: {node['id']} unknown effect class")

    publication = _toposort(profile["publication"], "publication")
    for n in publication:
        check_support(n, "publication", PUBLICATION_MODES)

    act = profile["activation"]
    declared_none = act == "none"
    if not declared_none and not act:
        raise ContractError("invalid_contract: activation must be `none` or a non-empty DAG")
    activation = [] if declared_none else _toposort(act, "activation")
    for n in activation:
        check_support(n, "activation", ACTIVATION_MODES)

    proof = _toposort(profile["proof"], "proof")
    for o in proof:
        if o["semantic"] not in PROOF_SEMANTICS:
            raise ContractError(f"invalid_contract: obligation {o['id']} unknown semantic")
        if o["temporal"] not in TEMPORAL_FORMS:
            raise ContractError(f"invalid_contract: obligation {o['id']} unknown temporal form")
        d = adapters[o["binding"]].describe()
        if d["predicates"].get(o["predicate"], "unsupported") != "supported":
            if o["required"]:
                raise ContractError(
                    f"inadmissible: required obligation {o['id']} has unsupported "
                    f"collector {o['predicate']} on {o['binding']}")
            o["_unsupported"] = True
        if o["temporal"] == "snapshot":
            window = o.get("freshness_seconds")
            if window is None:
                raise ContractError(
                    f"invalid_contract: snapshot {o['id']} has no freshness bound")
            if window > CORE_MAX_FRESHNESS:
                raise ContractError(
                    f"invalid_contract: {o['id']} freshness exceeds core maximum")

    limits = profile["limits"]
    if limits.get("max_attempts", MAX_ATTEMPTS) > MAX_ATTEMPTS:
        raise ContractError("invalid_contract: limits may lower but never raise core maxima")

    recovery = profile["recovery"]
    for unit_id, spec in recovery.get("units", {}).items():
        if spec["posture"] not in POSTURES:
            raise ContractError(f"invalid_contract: unknown posture for {unit_id}")
        for edge in spec.get("edges", []):
            if edge["action"] not in RECOVERY_ACTIONS:
                raise ContractError(f"invalid_contract: unknown recovery action in {unit_id}")

    canonical = {
        "profile_version": profile["profile_version"],
        "target": profile["target"],
        "requirements": profile["requirements"],
        "bindings": {k: v for k, v in bindings.items()},
        "publication": profile["publication"],
        "activation": profile["activation"],
        "proof": [{k: v for k, v in o.items() if not k.startswith("_")} for o in profile["proof"]],
        "recovery": profile["recovery"],
        "limits": limits,
        "adapters": identities,
    }
    return ResolvedProfile(
        profile_id=profile["target"]["profile_id"],
        profile_version=profile["profile_version"],
        profile_digest=digest(canonical),
        target=profile["target"],
        publication=publication,
        activation=activation,
        activation_declared_none=declared_none,
        proof=proof,
        recovery=recovery,
        limits=limits,
        bindings=bindings,
        adapters=adapters,
        adapter_identities=identities,
    )


# ---------------------------------------------------------------------------
# Durable-ish state records
# ---------------------------------------------------------------------------
@dataclass
class Attempt:
    n: int
    started_at: int
    invoke_result: str | None = None
    error_class: str | None = None
    post_inspect: str | None = None


@dataclass
class Action:
    id: str
    phase: str                # "publication" | "activation"
    mode: str
    binding: str
    deps: list
    effect_class: str
    expected_subject: dict
    status: str = "pending"   # pending|in_progress|satisfied|diverged|unknown|rejected
    attempts: list = field(default_factory=list)
    first_failure_at: int | None = None
    first_observed_at: int | None = None
    idempotency_key: str = ""
    intent_written: bool = False
    extra_attempt_grants: int = 0


@dataclass
class Evidence:
    obligation_id: str
    temporal: str
    outcome: str              # satisfied|unsatisfied|unknown
    reason: str
    observed_subject: dict
    observed_at: int
    expires_at: int | None
    fence: int
    payload_ref: str


@dataclass
class Lease:
    keys: tuple
    executor: str
    fence: int
    expires_at: int


# ---------------------------------------------------------------------------
# The core engine
# ---------------------------------------------------------------------------
class Run:
    """One child release transaction. Project-agnostic by construction."""

    def __init__(self, subject: dict, profile: dict, registry: dict, world,
                 creation_key: str, executor: str = "exec-1"):
        self.world = world
        self.subject = dict(subject)          # immutable after creation
        self.creation_key = creation_key
        self.release_id = "rel_" + digest([creation_key, subject])[:12]
        self.executor = executor
        self.events: list[tuple[int, str, str]] = []
        self.gaps: list[str] = []
        self.revision = 0
        self.state = "created"
        self.attention_reason: str | None = None
        self.lease: Lease | None = None
        self.fence_epoch = 0
        self.authorization: dict | None = None
        self.recovery_grant: dict | None = None
        self.receipts: dict[str, dict] = {}
        self.evidence: list[Evidence] = []
        self.evaluations: dict[str, tuple[str, str]] = {}
        self.proof_cutoff_at: int | None = None
        self.effect_snapshot: dict | None = None
        self.recollect_rounds = 0
        self.terminal_reason: str = ""
        self.semver: str | None = None
        self.actions: list[Action] = []
        self.contract_error: str | None = None
        self.resolved: ResolvedProfile | None = None
        try:
            self.resolved = resolve(profile, registry)
        except ContractError as exc:
            self.contract_error = str(exc)
            self.state = "attention_required"
            self.attention_reason = str(exc)
            self.log(f"resolution rejected: {exc}")
            return
        self.log(f"created {self.release_id} profile={self.resolved.profile_id}"
                 f" v{self.resolved.profile_version} digest={self.resolved.profile_digest}")
        for n in self.resolved.publication:
            self.actions.append(self._mk_action(n, "publication"))
        for n in self.resolved.activation:
            self.actions.append(self._mk_action(n, "activation"))
        self._derive_floor_obligations()

    def _derive_floor_obligations(self) -> None:
        """#88's mandatory floor: exact expected/running subject identity per declared unit.

        The core derives these — a profile author cannot forget or weaken them. Building
        this exposed the first real gap: the floor obligations need a `semantic` value, and
        #88's closed profile vocabulary (liveness | readiness | product_smoke |
        observability | rollback_readiness) has no member that means "this is the exact
        artifact / the exact running code". So the core has to mint one outside the closed
        set, which means evidence envelopes and terminal receipts carry a semantic the
        settled vocabulary does not define.
        """
        self.gap("#88's closed proof-semantic vocabulary has no member for the core-derived "
                 "subject-identity floor (publication artifact identity, running code "
                 "identity). Evidence envelopes and terminal receipts need a defined name "
                 "for it — either a sixth semantic or an explicit derived-obligation class.")
        derived = []
        for a in self.actions:
            if a.phase == "publication":
                derived.append({
                    "id": f"floor:publication:{a.id}", "semantic": DERIVED_SEMANTIC,
                    "temporal": "event", "predicate": "publication_visible",
                    "binding": a.binding, "expected_subject": a.expected_subject,
                    "required": True, "deps": [], "derived": True})
            else:
                derived.append({
                    "id": f"floor:activation:{a.id}", "semantic": DERIVED_SEMANTIC,
                    "temporal": "snapshot", "predicate": "running_subject_identity",
                    "binding": a.binding, "expected_subject": a.expected_subject,
                    "required": True, "deps": [], "derived": True,
                    "freshness_seconds": 600})
        for o in derived:
            support = self.resolved.adapters[o["binding"]].describe()["predicates"].get(
                o["predicate"], "unsupported")
            if support != "supported":
                self.contract_error = (
                    f"inadmissible: {o['binding']} cannot inspect the mandatory "
                    f"{o['predicate']} postcondition ({support})")
                self.attention(self.contract_error)
                return
        self.resolved.proof = derived + self.resolved.proof

    # -- bookkeeping ------------------------------------------------------
    def _mk_action(self, node: dict, phase: str) -> Action:
        a = Action(id=node["id"], phase=phase, mode=node["mode"], binding=node["binding"],
                   deps=node.get("deps", []), effect_class=node["effect_class"],
                   expected_subject=node["expected_subject"])
        a.idempotency_key = digest([self.release_id, a.id, a.expected_subject])
        return a

    def log(self, msg: str, kind: str = "event") -> None:
        self.revision += 1
        self.events.append((self.world.clock, kind, msg))

    def gap(self, msg: str) -> None:
        if msg not in self.gaps:
            self.gaps.append(msg)
            self.log(f"GAP: {msg}", "gap")

    def attention(self, reason: str) -> None:
        self.state = "attention_required"
        self.attention_reason = reason
        self.log(f"attention_required: {reason}", "attention")

    @property
    def terminal(self) -> bool:
        return self.state in TERMINALS

    @property
    def limit_attempts(self) -> int:
        if not self.resolved:
            return MAX_ATTEMPTS
        return self.resolved.limits.get("max_attempts", MAX_ATTEMPTS)

    # -- leases / authorization ------------------------------------------
    def acquire_lease(self) -> None:
        self.fence_epoch += 1
        keys = tuple(self.resolved.target["concurrency_keys"])
        self.lease = Lease(keys, self.executor, self.fence_epoch, self.world.clock + 600)
        self.log(f"lease acquired keys={list(keys)} fence={self.fence_epoch} "
                 f"executor={self.executor}")

    def lease_ok(self) -> bool:
        return (self.lease is not None
                and self.lease.executor == self.executor
                and self.lease.fence == self.fence_epoch
                and self.lease.expires_at > self.world.clock)

    def plan_preview(self) -> dict:
        """Secret-free read-only preview (#84). Nothing here mutates anything."""
        r = self.resolved
        return {
            "release_id": self.release_id,
            "subject": self.subject,
            "profile": f"{r.profile_id} v{r.profile_version} ({r.profile_digest})",
            "adapters": r.adapter_identities,
            "publication": [(a.id, a.mode, a.effect_class)
                            for a in self.actions if a.phase == "publication"],
            "activation": ("none" if r.activation_declared_none else
                           [(a.id, a.mode, a.effect_class)
                            for a in self.actions if a.phase == "activation"]),
            "required_proof": [o["id"] for o in r.proof if o["required"]],
            "postures": {k: v["posture"] for k, v in r.recovery.get("units", {}).items()},
            "irreversible": [a.id for a in self.actions if a.effect_class == "irreversible"],
            "spend_bound": r.limits.get("spend"),
            "non_atomicity_warning": "publication is not activation; effects are not all-or-nothing",
        }

    def preflight(self) -> bool:
        """Read-only revalidation immediately before the first mutation (#84/#83)."""
        r = self.resolved
        for unit_id, spec in r.recovery.get("units", {}).items():
            if spec["posture"] != "restorable":
                continue
            res = r.adapters[spec["binding"]].inspect("rollback_anchor", {
                "expected_subject": spec["anchor"], "fence": self.fence_epoch})
            if res["outcome"] != "satisfied":
                self.attention(
                    f"preflight blocked: unit {unit_id} claims restorable but anchor "
                    f"inspection returned {res['outcome']} ({res['reason']})")
                return False
            self.evidence.append(Evidence(
                obligation_id=f"preflight_rollback_readiness:{unit_id}", temporal="snapshot",
                outcome="satisfied", reason=res["reason"],
                observed_subject=res["observed_subject"], observed_at=self.world.clock,
                expires_at=self.world.clock + CORE_MAX_FRESHNESS,
                fence=self.fence_epoch, payload_ref=res["payload_ref"]))
        self.receipts["preflight"] = {
            "name": "preflight", "at": self.world.clock,
            "digest": digest(["preflight", self.release_id, self.world.clock]),
            "stores": ["local"], "body": {}}
        self.log("preflight receipt sealed (read-only)")
        return True

    def authorize(self, actor: str = "human", irreversible_confirmed: tuple = ()) -> bool:
        irreversible = [a.id for a in self.actions if a.effect_class == "irreversible"]
        pending = [i for i in irreversible if i not in irreversible_confirmed]
        spend_actions = [a for a in self.actions
                         if a.effect_class == "reversible_bounded_spend"]
        if spend_actions and not self.resolved.limits.get("spend"):
            self.attention("inadmissible: bounded-spend action without an explicit spend grant")
            return False
        self.authorization = {
            "actor": actor,
            "action_ids": [a.id for a in self.actions if a.effect_class != "irreversible"],
            "confirmed_irreversible": list(irreversible_confirmed),
            "profile_digest": self.resolved.profile_digest,
            "epoch": self.fence_epoch,
            "expires_at": self.world.clock + 3600,
            "spend": self.resolved.limits.get("spend"),
        }
        self.log(f"authorization granted by {actor}: "
                 f"{len(self.authorization['action_ids'])} reversible actions; "
                 f"irreversible confirmed={list(irreversible_confirmed)}")
        if pending:
            self.log(f"note: irreversible actions still need fresh one-action "
                     f"confirmation: {pending}")
        return True

    def authorized_for(self, a: Action) -> bool:
        g = self.authorization
        if not g or g["expires_at"] <= self.world.clock or g["epoch"] != self.fence_epoch:
            return False
        if a.effect_class == "irreversible":
            return a.id in g["confirmed_irreversible"]
        return a.id in g["action_ids"]

    # -- action execution protocol (#82) ---------------------------------
    def ready_actions(self, phase: str) -> list[Action]:
        done = {a.id for a in self.actions if a.status == "satisfied"}
        return [a for a in self.actions
                if a.phase == phase and a.status in ("pending", "in_progress")
                and all(d in done for d in a.deps)]

    def _classify_retry(self, a: Action, post: str, err: str | None) -> None:
        if post == "satisfied":
            a.status = "satisfied"
            self.log(f"{a.id}: inspect=satisfied")
            return
        if post == "in_progress":
            self._observe_in_progress(a, "inspect=in_progress (observing, not retrying)")
            return
        if post in ("diverged", "unknown"):
            a.status = post
            self.attention(f"{a.id}: inspect={post} — no automatic retry, no overwrite")
            return
        # post == absent -> the effect provably did not happen
        if a.first_failure_at is None:
            a.first_failure_at = self.world.clock
        budget = self.limit_attempts + a.extra_attempt_grants
        within_window = self.world.clock - a.first_failure_at <= RETRY_WINDOW_SECONDS
        if err not in RETRYABLE_ERROR_CLASSES:
            self.attention(f"{a.id}: error class {err} requires attention (inspect=absent)")
            return
        if len(a.attempts) >= budget:
            self.attention(f"{a.id}: retry budget {budget} exhausted (nonterminal; needs one "
                           f"authorized extra attempt after fresh inspection)")
            return
        if not within_window:
            self.attention(f"{a.id}: outside {RETRY_WINDOW_SECONDS}s automatic-retry window")
            return
        a.status = "pending"
        self.log(f"{a.id}: retryable {err}, inspect=absent — attempt "
                 f"{len(a.attempts) + 1} eligible")

    def _observe_in_progress(self, a: Action, why: str) -> None:
        """#84: units declare a finite observation deadline. Expiry is attention, never
        failure and never permission to replay."""
        a.status = "in_progress"
        if a.first_observed_at is None:
            a.first_observed_at = self.world.clock
        deadline = self.resolved.limits.get("observation_deadline_seconds", 900)
        self.log(f"{a.id}: {why}")
        if self.world.clock - a.first_observed_at > deadline:
            self.attention(f"{a.id}: observation deadline ({deadline}s) expired while "
                           f"in_progress — elapsed time proves neither failure nor "
                           f"replay safety")

    def run_action(self, a: Action) -> None:
        adapter = self.resolved.adapters[a.binding]
        if not self.lease_ok():
            self.attention(f"{a.id}: lease lost or stale fence — stopping before another effect")
            return
        if not self.authorized_for(a):
            need = ("fresh one-action human confirmation [c]"
                    if a.effect_class == "irreversible" else "a valid release authorization")
            self.attention(f"{a.id}: blocked — needs {need}")
            return
        env = {"release_id": self.release_id, "action_id": a.id,
               "attempt": len(a.attempts) + 1, "expected_subject": a.expected_subject,
               "fence": self.fence_epoch, "idempotency_key": a.idempotency_key, "mode": a.mode}
        if not a.intent_written:
            a.intent_written = True
            self.log(f"{a.id}: write-intent (key={a.idempotency_key[:8]} "
                     f"fence={self.fence_epoch})")
        pre = adapter.inspect(a.mode, env)
        if pre["outcome"] == "satisfied":
            a.status = "satisfied"
            self.log(f"{a.id}: precondition inspect=satisfied — idempotent, no invoke")
            return
        if pre["outcome"] == "in_progress":
            self._observe_in_progress(
                a, f"pre-inspect in_progress ({pre['reason']}) — observing, never re-invoking")
            return
        if pre["outcome"] == "diverged":
            a.status = "diverged"
            self.attention(f"{a.id}: diverged before invoke ({pre['reason']}) — no-clobber")
            return
        if pre["outcome"] == "unknown":
            a.status = "unknown"
            self.attention(f"{a.id}: pre-inspect unknown ({pre['reason']}) — "
                           f"cannot prove safe replay")
            return
        att = Attempt(n=len(a.attempts) + 1, started_at=self.world.clock)
        a.attempts.append(att)
        res = adapter.invoke(a.mode, env)
        att.invoke_result, att.error_class = res["result"], res.get("error_class")
        self.log(f"{a.id}: invoke#{att.n} -> {res['result']}"
                 + (f" ({res['error_class']})" if res.get("error_class") else ""))
        if self.world.crash_pending:
            self.world.crash_pending = False
            self.log("*** executor lost after invoke; nothing observed yet ***", "crash")
            self.executor = "<dead>"
            self.attention("executor lost mid-action — resume must inspect before anything else")
            return
        post = adapter.inspect(a.mode, env)
        att.post_inspect = post["outcome"]
        self._classify_retry(a, post["outcome"], att.error_class)

    def grant_extra_attempt(self) -> None:
        for a in self.actions:
            if a.status == "pending" and a.attempts:
                a.extra_attempt_grants += 1
                a.first_failure_at = self.world.clock
                self.state = "publishing" if a.phase == "publication" else "activating"
                self.attention_reason = None
                self.log(f"{a.id}: one authorized extra attempt granted after fresh inspection")
                return
        self.log("no action is waiting on an extra attempt")

    def takeover(self, executor: str = "exec-2") -> None:
        self.executor = executor
        self.fence_epoch += 1
        keys = tuple(self.resolved.target["concurrency_keys"])
        self.lease = Lease(keys, executor, self.fence_epoch, self.world.clock + 600)
        self.log(f"takeover by {executor}, new fence={self.fence_epoch}; inspecting every "
                 f"action that carries durable intent before any mutation")
        if any(not e.obligation_id.startswith("preflight_") for e in self.evidence):
            self.gap(GAP_FENCE_RENEWAL)
        if self.authorization:
            self.authorization["epoch"] = self.fence_epoch
        for a in self.actions:
            if a.intent_written and a.status != "satisfied":
                env = {"release_id": self.release_id, "action_id": a.id,
                       "expected_subject": a.expected_subject, "fence": self.fence_epoch,
                       "idempotency_key": a.idempotency_key, "mode": a.mode,
                       "attempt": len(a.attempts)}
                res = self.resolved.adapters[a.binding].inspect(a.mode, env)
                self.log(f"resume inspect {a.id} -> {res['outcome']} ({res['reason']})")
                if res["outcome"] == "satisfied":
                    a.status = "satisfied"
                elif res["outcome"] == "absent":
                    a.status = "pending"
                else:
                    a.status = res["outcome"]
                    self.attention(f"resume: {a.id} is {res['outcome']} — cannot replay")
                    return
        self.attention_reason = None
        self.state = self._phase_state()
        self.log(f"resumed into {self.state}")

    def _phase_state(self) -> str:
        if any(a.phase == "publication" and a.status != "satisfied" for a in self.actions):
            return "publishing"
        if "publication" not in self.receipts:
            return "publishing"
        if any(a.phase == "activation" and a.status != "satisfied" for a in self.actions):
            return "activating"
        return "proving"

    # -- sealing ----------------------------------------------------------
    def _seal(self, name: str, body: dict) -> dict:
        d = digest([name, body])
        stores = self.resolved.bindings.get("_evidence_stores", ["local"])
        receipt = {"name": name, "digest": d, "at": self.world.clock,
                   "stores": stores, "body": body}
        self.receipts[name] = receipt
        self.log(f"{name} receipt sealed digest={d} stores={stores} "
                 f"(create-if-absent, read back by digest)")
        return receipt

    def seal_publication(self) -> None:
        units = [{"id": a.id, "mode": a.mode, "artifact_ref": a.expected_subject}
                 for a in self.actions if a.phase == "publication"]
        manifest = {"release_id": self.release_id, "semver": self.semver,
                    "subject": self.subject, "profile_digest": self.resolved.profile_digest,
                    "units": units}
        self._seal("publication_manifest", manifest)
        self._seal("publication",
                   {"manifest_digest": self.receipts["publication_manifest"]["digest"],
                    "units": units})
        self.state = "published"

    def seal_activation(self) -> None:
        if self.resolved.activation_declared_none:
            self._seal("activation_not_applicable",
                       {"reason": "profile declares activation none"})
        else:
            self._seal("activation", {"units": [
                {"id": a.id, "mode": a.mode, "subject": a.expected_subject}
                for a in self.actions if a.phase == "activation"]})
        self.state = "proving"

    # -- proof (#88) -------------------------------------------------------
    def collect_next_obligation(self) -> bool:
        collected = {e.obligation_id for e in self.evidence}
        for o in self.resolved.proof:
            if o["id"] in collected or o["id"] in self.evaluations:
                continue
            if o.get("_unsupported"):
                self.evaluations[o["id"]] = ("unsupported",
                                             "advisory obligation, no deterministic collector")
                self.log(f"{o['id']}: unsupported advisory obligation retained as warning")
                return True
            unmet = [d for d in o.get("deps", [])
                     if self.evaluations.get(d, ("", ""))[0] != "accepted"]
            if unmet:
                continue
            res = self.resolved.adapters[o["binding"]].inspect(o["predicate"], {
                "expected_subject": o["expected_subject"], "fence": self.fence_epoch,
                "release_id": self.release_id})
            exp = (self.world.clock + o["freshness_seconds"]
                   if o["temporal"] == "snapshot" else None)
            self.evidence.append(Evidence(o["id"], o["temporal"], res["outcome"], res["reason"],
                                          res["observed_subject"], self.world.clock, exp,
                                          self.fence_epoch, res["payload_ref"]))
            self._grade(o, self.evidence[-1])
            self.log(f"{o['id']} ({o['semantic']}/{o['temporal']}): "
                     f"{res['outcome']} — {res['reason']}")
            return True
        for o in self.resolved.proof:
            if o["id"] in self.evaluations:
                continue
            self.evaluations[o["id"]] = ("indeterminate", "dependency_not_accepted")
            self.log(f"{o['id']}: suppressed — prerequisite not accepted "
                     f"(one dependency reason, no collection)")
            return True
        return False

    def _grade(self, o: dict, e: Evidence) -> None:
        if e.outcome == "satisfied":
            self.evaluations[o["id"]] = ("accepted", e.reason)
        elif e.outcome == "unsatisfied":
            self.evaluations[o["id"]] = ("rejected", e.reason)
        else:
            self.evaluations[o["id"]] = ("indeterminate", e.reason)

    def evaluate_and_seal(self) -> None:
        """Fix one proof_cutoff_at, revalidate freshness/fence, then seal or hold."""
        if not self.lease_ok():
            self.attention("proof cannot seal: the release lease is expired, so the fence "
                           "backing every observation is no longer valid")
            return
        self.proof_cutoff_at = self.world.clock
        by_id = {o["id"]: o for o in self.resolved.proof}
        for e in self.evidence:
            o = by_id.get(e.obligation_id)
            if o is None or self.evaluations.get(o["id"], ("",))[0] != "accepted":
                continue
            if e.temporal == "snapshot" and e.expires_at is not None \
                    and e.expires_at <= self.proof_cutoff_at:
                self.evaluations[o["id"]] = ("indeterminate",
                                             "snapshot_expired_before_cutoff (recollect)")
            elif e.fence != self.fence_epoch:
                self.evaluations[o["id"]] = ("indeterminate", "evidence_from_stale_fence")
                self.gap(GAP_FENCE_RENEWAL)
        required = [o for o in self.resolved.proof if o["required"]]
        bad = [(o["id"], self.evaluations.get(o["id"], ("indeterminate", "not_collected")))
               for o in required
               if self.evaluations.get(o["id"], ("indeterminate",))[0] != "accepted"]
        warnings = [(o["id"], self.evaluations[o["id"]]) for o in self.resolved.proof
                    if not o["required"]
                    and self.evaluations.get(o["id"], ("accepted",))[0] != "accepted"]
        if bad:
            self.attention("required proof not accepted at cutoff: "
                           + ", ".join(f"{i}={v[0]}({v[1]})" for i, v in bad))
            return
        self._seal("terminal", {"outcome": "succeeded", "proof_cutoff_at": self.proof_cutoff_at,
                                "evaluations": dict(self.evaluations), "warnings": warnings})
        self.state = "succeeded"
        self.terminal_reason = "every required obligation accepted at proof_cutoff_at"
        self.log("TERMINAL succeeded", "terminal")

    def recollect_stale(self) -> None:
        stale = [oid for oid, (v, r) in self.evaluations.items()
                 if v == "indeterminate" and ("expired" in r or "stale_fence" in r)]
        if not stale:
            self.log("nothing to recollect")
            return
        self.recollect_rounds += 1
        if self.recollect_rounds >= 2:
            self.gap("Common-cutoff proof can livelock: recollecting one expired snapshot "
                     "spends time that expires another, so a healthy release never seals "
                     "and eventually rolls back. #88 fixes one proof_cutoff_at and a finite "
                     "per-obligation freshness window but declares no convergence rule — no "
                     "resolution-time feasibility check that the whole snapshot set can be "
                     "collected inside the shortest window, no bounded recollection budget, "
                     "and no typed outcome for `proof could not converge` as distinct from "
                     "`proof rejected`.")
        self.evidence = [e for e in self.evidence if e.obligation_id not in stale]
        for oid in stale:
            del self.evaluations[oid]
        self.attention_reason = None
        self.state = "proving"
        self.log(f"recollecting expired snapshots {stale} (never extending an old observation)")

    # -- recovery (#83) ----------------------------------------------------
    def reconcile(self) -> None:
        snap = {}
        for a in self.actions:
            if not a.intent_written:
                snap[a.id] = "no_effect"
                continue
            env = {"release_id": self.release_id, "action_id": a.id, "mode": a.mode,
                   "expected_subject": a.expected_subject, "fence": self.fence_epoch,
                   "idempotency_key": a.idempotency_key, "attempt": len(a.attempts)}
            res = self.resolved.adapters[a.binding].inspect(a.mode, env)
            snap[a.id] = {"absent": "no_effect", "satisfied": "target_satisfied",
                          "in_progress": "in_progress", "diverged": "diverged",
                          "unknown": "unknown"}[res["outcome"]]
        self.effect_snapshot = {"digest": digest(snap), "classes": snap, "at": self.world.clock}
        self.log(f"effect_snapshot frozen digest={self.effect_snapshot['digest']}: {snap}")

    def plan_recovery(self) -> None:
        if not self.effect_snapshot:
            self.reconcile()
        units = self.resolved.recovery.get("units", {})
        affected = [aid for aid, cls in self.effect_snapshot["classes"].items()
                    if cls in ("target_satisfied", "in_progress", "diverged", "unknown")]
        postures = {aid: units.get(aid, {}).get("posture", "manual_only") for aid in affected}
        blocking = {aid: p for aid, p in postures.items()
                    if p in ("supersedable_only", "manual_only")}
        self.log(f"recovery preview posture={self.resolved.recovery.get('posture')} "
                 f"affected={affected} postures={postures}")
        if blocking:
            self.log(f"restore impossible for {list(blocking)} — declared "
                     f"{sorted(set(blocking.values()))}; only compensate, linked "
                     f"roll-forward, or truthful failure remain")

    def grant_recovery(self, actor: str = "human") -> None:
        if not self.effect_snapshot:
            self.reconcile()
        self.recovery_grant = {"actor": actor, "snapshot": self.effect_snapshot["digest"],
                               "epoch": self.fence_epoch, "expires_at": self.world.clock + 1800}
        self.log(f"fresh recovery grant recorded by {actor} over snapshot "
                 f"{self.effect_snapshot['digest']} (never reuses the release grant)")
        self.state = "recovering"
        self.attention_reason = None

    def run_recovery(self) -> None:
        if not self.recovery_grant:
            self.log("recovery blocked: needs a fresh recovery grant [G]")
            return
        units = self.resolved.recovery.get("units", {})
        affected = [aid for aid, cls in self.effect_snapshot["classes"].items()
                    if cls in ("target_satisfied", "in_progress", "diverged", "unknown")]
        if not affected:
            self.log("recovery selected an empty subgraph: no declared effect exists, so the "
                     "truthful terminal is abandoned, not rolled_back")
            self.dispose_no_recovery()
            return
        residue, restored, failed = [], [], []
        for aid in affected:
            spec = units.get(aid)
            if spec is None:
                failed.append((aid, "no declared recovery edge for an effect-present unit"))
                continue
            if spec["posture"] in ("supersedable_only", "manual_only"):
                failed.append((aid, f"posture {spec['posture']}: no restore edge exists"))
                continue
            adapter = self.resolved.adapters[spec["binding"]]
            for edge in spec.get("edges", []):
                env = {"release_id": self.release_id, "action_id": f"recover:{aid}",
                       "expected_subject": spec.get("anchor", {}), "fence": self.fence_epoch,
                       "idempotency_key": digest(["recover", self.release_id, aid,
                                                  edge["action"]]),
                       "mode": edge["op"], "attempt": 1}
                if edge["action"] == "restore":
                    compat = adapter.inspect("compatibility", env)
                    if compat["outcome"] != "satisfied":
                        failed.append((aid, f"restore inadmissible: {compat['reason']}"))
                        continue
                inv = adapter.invoke(edge["op"], env)
                post = adapter.inspect(edge["op"], env)
                self.log(f"recover {aid} via {edge['action']}/{edge['op']}: "
                         f"invoke={inv['result']} inspect={post['outcome']} ({post['reason']})")
                if post["outcome"] != "satisfied":
                    failed.append((aid, f"{edge['action']} inspect={post['outcome']}"))
                elif edge["action"] == "restore":
                    restored.append(aid)
                else:
                    residue.append({"unit": aid,
                                    "residue": edge.get("residue", "declared bounded residue")})
        if not failed:
            # #83: every affected unit must accept its exact target identity at one cutoff
            # before a rollback receipt may be sealed.
            for aid in restored:
                spec, act = units[aid], next(a for a in self.actions if a.id == aid)
                predicate = ("publication_visible" if act.phase == "publication"
                             else "running_subject_identity")
                adapter = self.resolved.adapters[spec["binding"]]
                if adapter.describe()["predicates"].get(predicate) != "supported":
                    failed.append((aid, f"cannot prove the restore target: {predicate} "
                                        f"unsupported"))
                    continue
                res = adapter.inspect(predicate, {
                    "expected_subject": spec["anchor"], "fence": self.fence_epoch,
                    "release_id": self.release_id})
                self.log(f"rollback proof {aid} via {predicate}: {res['outcome']} "
                         f"({res['reason']})")
                if res["outcome"] != "satisfied":
                    failed.append((aid, f"rollback target proof {res['outcome']}"))
        if failed:
            self.attention("recovery incomplete: "
                           + "; ".join(f"{a}: {r}" for a, r in failed))
            self.log("no rollback receipt for partial recovery; the event ledger stays "
                     "authoritative", "note")
            return
        self._seal("rollback", {"snapshot": self.effect_snapshot["digest"],
                                "restored": restored, "accepted_residue": residue})
        self._seal("terminal", {"outcome": "rolled_back",
                                "rollback_receipt": self.receipts["rollback"]["digest"]})
        self.state = "rolled_back"
        self.terminal_reason = f"restored {restored}; accepted bounded residue {residue}"
        self.log("TERMINAL rolled_back", "terminal")

    def dispose_no_recovery(self, successor: str | None = None) -> None:
        if not self.effect_snapshot:
            self.reconcile()
        classes = set(self.effect_snapshot["classes"].values())
        if classes <= {"no_effect"}:
            self._seal("terminal", {"outcome": "abandoned",
                                    "reason": "no declared release effect exists"})
            self.state = "abandoned"
            self.terminal_reason = "authoritative inspection proves no release effect exists"
            self.log("TERMINAL abandoned", "terminal")
            return
        if "unknown" in classes or "in_progress" in classes:
            self.gap("A release whose external truth becomes PERMANENTLY unobservable (retired "
                     "provider, deleted account, decommissioned host) can never terminate: "
                     "unknown is never terminal, manual disposition still requires fresh "
                     "authoritative inspection, and #72 gates state cleanup on a terminal "
                     "receipt — so its runtime ledger is immortal. The contract needs a "
                     "bounded, evidence-backed way to close or archive an unobservable "
                     "release without pretending to know its effects.")
            self.attention("cannot dispose: external reality is unknown/in-progress — "
                           "unknown is never terminal")
            return
        self._seal("no_recovery_disposition", {
            "snapshot": self.effect_snapshot["digest"], "successor": successor,
            "final_effects": self.effect_snapshot["classes"]})
        self._seal("terminal", {"outcome": "failed", "successor": successor,
                                "disposition":
                                    self.receipts["no_recovery_disposition"]["digest"]})
        self.state = "failed"
        self.terminal_reason = ("final external state known; no declared recovery path remains"
                               + (f"; cites successor {successor}" if successor else ""))
        self.log("TERMINAL failed", "terminal")

    # -- the single driver step -------------------------------------------
    def step(self) -> str:
        if self.terminal:
            return "terminal — a terminal transaction never reopens"
        if self.state == "attention_required":
            return "attention_required — needs an explicit operator move"
        if self.state == "recovering":
            self.run_recovery()
            return self.state
        if self.state == "created":
            self.semver = self.resolved.target.get("next_semver")
            self.log(f"reserved project SemVer {self.semver} before any external side effect")
            self.state = "awaiting_verification"
            return "awaiting_verification"
        if self.state == "awaiting_verification":
            v = self.resolved.target["verification"]
            res = self.resolved.adapters[v["binding"]].inspect(v["predicate"], {
                "expected_subject": self.subject, "fence": self.fence_epoch})
            if res["outcome"] != "satisfied":
                self.attention(f"pre-release verification {res['outcome']}: {res['reason']}")
                return "blocked"
            self._seal("candidate_verification",
                       {"predicate": v["predicate"], "reason": res["reason"]})
            self.state = "ready"
            return "ready"
        if self.state == "ready":
            if not self.lease_ok():
                self.acquire_lease()
            if not self.preflight():
                return "blocked"
            if not self.authorization:
                return "needs authorization — [a] to preview+grant, [c] to confirm irreversible"
            self.state = "publishing"
            return "publishing"
        if self.state == "publishing":
            pend = self.ready_actions("publication")
            if pend:
                self.run_action(pend[0])
                return f"ran {pend[0].id}"
            if all(a.status == "satisfied"
                   for a in self.actions if a.phase == "publication"):
                self.seal_publication()
                return "published"
            self.attention("publication stalled: unsatisfied units and no ready action")
            return "blocked"
        if self.state == "published":
            if not self.resolved.activation:
                self.seal_activation()
                return "activation not applicable -> proving"
            self.state = "activating"
            return "activating"
        if self.state == "activating":
            pend = self.ready_actions("activation")
            if pend:
                self.run_action(pend[0])
                return f"ran {pend[0].id}"
            if all(a.status == "satisfied"
                   for a in self.actions if a.phase == "activation"):
                self.seal_activation()
                return "activated"
            self.attention("activation stalled: units remain unsatisfied and none are ready")
            return "blocked"
        if self.state == "proving":
            if self.collect_next_obligation():
                return "collected proof"
            self.evaluate_and_seal()
            return self.state
        return self.state
