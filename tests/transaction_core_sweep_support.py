"""Scenario fixture and fixture executor for the transaction core sweep (#204 D6, D17;
#206 D12, D18; #207 D14-D17, D29; #208 D13, D14, D23).

The executor is a happy-path walker over the simulated world that asks the shipped core to
advance at each lifecycle boundary through the public store API, on a store whose clock is
the world clock (#205 D22, D29). It creates each transaction with the proof declaration its
shape implies (`proof_declaration`): every publication and activation node is a unit whose
collector is its binding, every profile `proof` entry an obligation, and every binding a
deterministic collector of its adapter's supported predicates with a 30 s collection bound.
Beside it goes the recovery declaration the shape implies (`recovery_declaration`, #208):
every such node is a unit whose effect is its binding and whose posture, anchor and edges
come from the profile's `recovery` entry for it, and every binding an effect offering its
adapter's supported modes. It acquires custody before publishing and presents it on every
later advance. Right after acquiring in `ready` it verifies the rollback anchors through
`_Router`, which sends each check to its collector binding's adapter hook, and parks on a
refusal. Every node is an action driven through the core: one effect per binding wraps
that binding's adapter, action `name` is the node id and `parameters` its mode and expected
subject, and no adapter effect is called outside `inspect_action` / `invoke_action`. Each
node is pre-inspected, then invoked until its view reads `satisfied`; before each retry the
world clock moves 30 seconds, so the core's retry budget and window run on the world clock.
Proof is collected through the core: one `_Observer` per binding is the only caller of the
adapter's proof predicates. A first pass collects every plan obligation in plan order
through `collect_obligation`, skipping one whose latest evidence is still admissible and one
refused `unsupported_obligation` or `dependency_not_accepted`. Then each convergence cohort
is started, its members collected with custody renewed after each, and `settle_proof` either
seals into `succeeded` or parks with its typed reason (`proof_rejected`,
`proof_did_not_converge`); the executor repeats while it leaves the transaction in
`proving`, tolerating a `start_cohort` refused `proof_incomplete` or `convergence_exhausted`
so that `settle_proof` judges, and never advances past a park. Under the `slow_collection`
fault every observation made inside a cohort first moves the world clock 250 seconds, so a
cohort with members outlives its window (`expired_snapshot`). Scenario hooks move the world
clock: `lease_renewal` renews in place twice; `lease_lapse` lets the lease expire before the
last required obligation, has the reaper park the transaction, reacquires, resumes proving
and recollects what the new fence voided; `resume_after_crash` kills the executor between
the first publication action's recorded intent and its call, lets the lease expire, reaps,
reacquires, checks that a blind invoke is refused `inspection_required`, and resumes
publication through a fresh inspection. The recovery step runs only in `recover`-flagged
scenarios, after a park, and `drive` lets a rejected recovery declaration propagate
(#208 D13, D23). Any action view other than `absent` or `satisfied`, and any invocation or
proof refusal not named above, parks the transaction in attention_required with the
observation or the refusal's reason.
"""

from agent_tools.transaction_core import (
    InvocationRefused, ProofRefused, RecoveryRefused, StaleCustody, TransactionStore)

from .transaction_core_shapes import SHAPES
from .transaction_core_world import ExecutorCrash, World

TTL_MS = 600_000


def _add_unsupported_publication(profile, registry):
    """Port of dc98ba9's mutation: a publication node on the first binding whose adapter
    does not offer `promote`, with a `manual_only` recovery entry (#208 D14)."""
    alias = next((alias for alias, binding in profile["bindings"].items()
                  if not alias.startswith("_")
                  and registry[binding["adapter"]].modes["promote"] != "supported"), None)
    if alias is None:
        raise ValueError("every binding offers promote")
    profile["publication"].append({
        "id": "unsupported_promote", "mode": "promote", "binding": alias, "deps": [],
        "effect_class": "reversible_no_incremental_spend",
        "expected_subject": {"note": "authored against an unsupported mode"}})
    profile["recovery"]["units"]["unsupported_promote"] = {"posture": "manual_only",
                                                           "binding": alias}


def _first_activation_supersedable(profile, registry):
    """A forward-only migration rides the first activation unit: it becomes
    `supersedable_only`, with no anchor, compatibility or edges (#208 D14)."""
    if profile["activation"] == "none":
        return
    node = profile["activation"][0]
    profile["recovery"]["units"][node["id"]] = {"posture": "supersedable_only",
                                                "binding": node["binding"]}


# `success` is ported from prototype-release-transactions/scenarios.py at dc98ba9;
# `lease_renewal` and `lease_lapse` are new in #205 (D22, D29); `throttled_retry` and
# `resume_after_crash` are ported from dc98ba9 in #206 (D12), the crash moved to between
# the recorded intent and the call. The last five come from dc98ba9 in #207 (D14), with
# `expired_snapshot`'s 250 s tick moved into cohort collection.
SCENARIOS = {
    "success": {"faults": frozenset(),
                "note": "clean path: publish, activate, prove, seal a terminal receipt."},
    "lease_renewal": {"faults": frozenset(),
                      "note": "the lease is renewed twice in place during proving."},
    "lease_lapse": {"faults": frozenset(),
                    "note": "the lease lapses before the last obligation; reap, reacquire, "
                            "recollect."},
    "throttled_retry": {"faults": frozenset({"throttle_once"}),
                        "note": "every action's first invoke is throttled and inspects "
                                "absent; one automatic retry succeeds."},
    "resume_after_crash": {"faults": frozenset({"crash_before_invoke"}),
                           "note": "the executor dies between the first publication "
                                   "action's intent and its call; reap, reacquire, the "
                                   "blind invoke is refused, inspect, retry."},
    "partial_publication": {"faults": frozenset({"partial_publication"}),
                            "note": "an index/channel target already holds a different "
                                    "identity: the action inspects diverged, the executor "
                                    "parks, nothing is clobbered or re-invoked."},
    "failed_activation": {"faults": frozenset({"activation_failure"}),
                          "note": "the invoke is accepted but the provider's terminal state "
                                  "is failure: the activation action inspects diverged and "
                                  "the executor parks."},
    "stale_false_positive_health": {"faults": frozenset({"stale_health"}),
                                    "note": "liveness is satisfied while the running subject "
                                            "is the previous code; the derived identity "
                                            "floor rejects it and settle_proof parks "
                                            "proof_rejected."},
    "expired_snapshot": {"faults": frozenset({"slow_collection"}),
                         "note": "every collection inside a cohort takes 250 s, so a cohort "
                                 "outlives its window and fails; settle_proof parks "
                                 "proof_did_not_converge, never extending a snapshot."},
    "fleet_stall": {"faults": frozenset({"member_stale"}),
                    "note": "one frozen member of a convergent unit never reports the "
                            "desired digest, so activation stays in_progress and nothing "
                            "is re-invoked."},
    # The last five come from dc98ba9 in #208 (D14): `irreversible_migration` is
    # redefined, and `incompatible_restore` rolls forward instead of disposing `failed`.
    "rollback": {"faults": frozenset({"activation_failure"}), "recover": True,
                 "note": "failed_activation recovered: restore and compensate the selected "
                         "edges, then settle into rolled_back."},
    "irreversible_migration": {"faults": frozenset({"activation_failure"}), "recover": True,
                               "mutate": _first_activation_supersedable,
                               "note": "the failed first activation unit is supersedable "
                                       "only: recovery is refused and a roll-forward child "
                                       "is linked."},
    "incompatible_restore": {"faults": frozenset({"activation_failure",
                                                  "restore_incompatible"}),
                             "recover": True,
                             "note": "the prior subject is incompatible with the current "
                                     "epoch: recovery is refused and a roll-forward child is "
                                     "linked."},
    "missing_rollback_anchor": {"faults": frozenset({"missing_anchor"}), "recover": True,
                                "note": "a declared anchor is not retained: the transaction "
                                        "parks in ready and abandons through no_effect."},
    "unsupported_operation": {"faults": frozenset(), "recover": True,
                              "mutate": _add_unsupported_publication,
                              "note": "a unit's operation is not offered by its effect: "
                                      "creation is rejected and nothing is written."},
}


# The reason a derived obligation's `unknown` observation carries, per class (#207 D29).
UNOBSERVABLE = {"published_artifact_identity": "store_unreachable",
                "running_subject_identity": "identity_unobservable"}
# Collection refusals the first pass steps over rather than parks on (#207 D29).
SKIPPED = ("unsupported_obligation", "dependency_not_accepted")


class _Parked(Exception):
    pass


def proof_declaration(profile, registry):
    """The proof declaration a shape's profile implies (#207 D14)."""
    activation = [] if profile["activation"] == "none" else profile["activation"]
    units = [{"name": node["id"],
              "parameters": {"mode": node["mode"],
                             "expected_subject": node["expected_subject"]},
              "phase": phase, "collector": node["binding"]}
             for phase, nodes in (("publication", profile["publication"]),
                                  ("activation", activation))
             for node in nodes]
    obligations = []
    for entry in profile["proof"]:
        obligation = {"id": entry["id"], "semantic": entry["semantic"],
                      "form": entry["temporal"], "predicate": entry["predicate"],
                      "collector": entry["binding"], "required": entry["required"],
                      "deps": list(entry.get("deps", [])),
                      "parameters": {"expected_subject": entry["expected_subject"]}}
        if entry["temporal"] == "snapshot":
            obligation["freshness_ms"] = entry["freshness_seconds"] * 1000
        obligations.append(obligation)
    collectors = {
        alias: {"basis": "deterministic",
                "predicates": sorted(predicate for predicate, support
                                     in registry[binding["adapter"]].predicates.items()
                                     if support == "supported"),
                "max_collection_latency_ms": 30_000}
        for alias, binding in profile["bindings"].items() if not alias.startswith("_")}
    return {"units": units, "obligations": obligations, "collectors": collectors}


def shape_declaration(shape):
    """The declaration `drive` passes for `shape`."""
    _, profile, registry = SHAPES[shape](World())
    return proof_declaration(profile, registry)


def recovery_declaration(profile, registry):
    """The recovery declaration a shape's profile implies (#208, spec "Sweep fixture")."""
    activation = [] if profile["activation"] == "none" else profile["activation"]
    entries = profile["recovery"]["units"]
    effects = {alias: {"operations": sorted(mode for mode, support
                                            in registry[binding["adapter"]].modes.items()
                                            if support == "supported")}
               for alias, binding in profile["bindings"].items() if not alias.startswith("_")}
    units = []
    for node in [*profile["publication"], *activation]:
        entry = entries[node["id"]]
        anchor = entry.get("anchor")
        restorable = entry["posture"] == "restorable"
        units.append({
            "name": node["id"],
            "parameters": {"mode": node["mode"], "expected_subject": node["expected_subject"]},
            "effect": node["binding"], "operation": node["mode"], "posture": entry["posture"],
            "anchor": ({"predicate": "rollback_anchor",
                        "parameters": {"expected_subject": anchor}} if restorable else None),
            "compatibility": ({"predicate": "compatibility",
                               "parameters": {"expected_subject": anchor}}
                              if restorable else None),
            "edges": [{"action": e["action"], "operation": e["op"],
                       "parameters": {"mode": e["op"], "unit": node["id"],
                                      "expected_subject": anchor or {}},
                       "residue": e.get("residue")} for e in entry.get("edges", [])]})
    return {"effects": effects, "units": units}


def shape_recovery(shape):
    """The recovery declaration `drive` passes for `shape`."""
    _, profile, registry = SHAPES[shape](World())
    return recovery_declaration(profile, registry)


def _in_dependency_order(nodes):
    """Stable topological order: repeatedly take the first node whose deps are done."""
    done, ordered, pending = set(), [], list(nodes)
    while pending:
        for node in pending:
            if all(dep in done for dep in node.get("deps", [])):
                ordered.append(node)
                done.add(node["id"])
                pending.remove(node)
                break
        else:
            raise ValueError(f"dependency cycle among {[n['id'] for n in pending]}")
    return ordered


class _Effect:
    """One binding's effect: maps core requests onto the adapter's (op, env) calls and its
    observations onto the closed result shapes."""

    def __init__(self, unit):
        self.unit = unit

    @staticmethod
    def _call(request):
        parameters = request["parameters"]
        return parameters["mode"], {"action_id": request["action_id"],
                                    "expected_subject": parameters["expected_subject"]}

    def inspect(self, request):
        seen = self.unit.inspect(*self._call(request))
        return {"outcome": seen["outcome"], "reference": seen["payload_ref"]}

    def invoke(self, request):
        called = self.unit.invoke(*self._call(request))
        return {"result": called["result"], "error_class": called.get("error_class"),
                "reference": called.get("correlation")
                or f"{self.unit.name}:{called['error_class']}"}


class _Observer:
    """One binding's observer: asks the adapter's predicate hook about the request's expected
    subject and maps its outcome onto a stable reason token (#207 D29)."""

    def __init__(self, unit):
        self.unit = unit

    def observe(self, request):
        if "slow_collection" in self.unit.world.faults and request["cohort"] is not None:
            self.unit.world.tick(250)
        identity = request["obligation_id"]
        derived = identity.split(":")[1] if identity.startswith("derived:") else None
        parameters = request["parameters"]
        subject = (parameters["parameters"] if derived else parameters)["expected_subject"]
        seen = self.unit.inspect(request["predicate"], {"expected_subject": subject})
        outcome = (seen["outcome"] if seen["outcome"] in ("satisfied", "unsatisfied", "unknown")
                   else "unknown")
        if derived is None or outcome == "satisfied":
            reason = outcome
        elif outcome == "unsatisfied":
            reason = "subject_mismatch"
        else:
            reason = UNOBSERVABLE[derived]
        return {"outcome": outcome, "reason": reason, "reference": seen["payload_ref"]}


class _Router:
    """Every anchor or compatibility check goes to its collector binding's adapter hook; an
    adapter `absent` is `unsatisfied` with reason `anchor_absent` (#208)."""

    def __init__(self, adapters):
        self.adapters = adapters

    def observe(self, request):
        seen = self.adapters[request["collector"]].inspect(request["predicate"],
                                                           request["parameters"])
        outcome = {"absent": "unsatisfied"}.get(seen["outcome"], seen["outcome"])
        if outcome not in ("satisfied", "unsatisfied"):
            outcome = "unknown"
        reason = "anchor_absent" if seen["outcome"] == "absent" else outcome
        return {"outcome": outcome, "reason": reason, "reference": seen["payload_ref"]}


def drive(root, shape, scenario, world=None):
    world = World() if world is None else world
    world.faults = set(SCENARIOS[scenario]["faults"])
    store = TransactionStore(root, clock=lambda: world.clock * 1000)
    subject, profile, registry = SHAPES[shape](world)
    mutate = SCENARIOS[scenario].get("mutate")
    if mutate is not None:
        mutate(profile, registry)
    keys = profile["target"]["concurrency_keys"]
    proof = proof_declaration(profile, registry)
    recovery = recovery_declaration(profile, registry)
    transaction_id = store.create(f"{shape}:{scenario}", subject, concurrency_keys=keys,
                                  proof=proof, recovery=recovery).transaction_id
    definite = {"all": True}
    held = {"custody": None}

    def adapter(alias):
        return registry[profile["bindings"][alias]["adapter"]]

    effects = {alias: _Effect(adapter(alias)) for alias in profile["bindings"]
               if not alias.startswith("_")}
    observers = {alias: _Observer(adapter(alias)) for alias in effects}
    router = _Router({alias: adapter(alias) for alias in effects})

    def external_state():
        return "known" if definite["all"] else "unknown"

    def advance(target, reason):
        store.advance(transaction_id, target, reason=reason, external_state=external_state(),
                      custody=held["custody"])

    def observe(result, what):
        if result["outcome"] == "unknown":
            definite["all"] = False
        if result["outcome"] != "satisfied":
            raise _Parked(f"{what}: {result['outcome']} ({result['reason']})")

    def action(node):
        return {"name": node["id"], "effect": effects[node["binding"]],
                "parameters": {"mode": node["mode"],
                               "expected_subject": node["expected_subject"]}}

    def run_phase(nodes):
        for node in _in_dependency_order(nodes):
            snapshot = store.inspect_action(held["custody"], **action(node))
            while True:
                view = next(v for v in snapshot.actions if v["name"] == node["id"])
                if view["status"] == "satisfied":
                    break
                if view["status"] != "absent":
                    if view["status"] == "unknown":
                        definite["all"] = False
                    raise _Parked(f"{node['id']}: {view['status']} after attempt "
                                  f"{view['attempts']}")
                if view["attempts"] > 0:
                    world.tick(30)
                try:
                    snapshot = store.invoke_action(held["custody"], **action(node))
                except InvocationRefused as refused:
                    raise _Parked(f"{node['id']}: invoke refused {refused.reason}") from None

    def publish():
        publication = profile["publication"]
        if scenario != "resume_after_crash":
            run_phase(publication)
            return
        world.arm_crash()
        try:
            run_phase(publication)
        except ExecutorCrash as crash:
            crashed = next(v["name"] for v in store.load(transaction_id).actions
                           if v["action_id"] == str(crash))
        else:
            raise _Parked("the armed crash never interrupted publication")
        world.tick(TTL_MS // 1000 + 1)
        store.reap(transaction_id, reason="executor lost during publication")
        acquire()
        advance("publishing", "resumed after reacquisition")
        node = next(n for n in publication if n["id"] == crashed)
        try:
            store.invoke_action(held["custody"], **action(node))
        except InvocationRefused as refused:
            if refused.reason != "inspection_required":
                raise _Parked(f"{crashed}: blind invoke refused {refused.reason}") from None
        else:
            raise _Parked(f"{crashed}: blind invoke was not refused")
        run_phase(publication)

    def acquire():
        held["custody"] = store.acquire(transaction_id, executor_id="fixture-executor",
                                        subject_path=f"/fixture/{shape}",
                                        ttl_ms=TTL_MS).custody

    def records(obligation_id):
        return [entry for entry in store.load(transaction_id).evidence
                if entry["evidence_id"].rsplit("@", 1)[0] == obligation_id]

    def renew():
        world.tick(301)
        store.renew(held["custody"])

    def collect(entry, skipped=()):
        """Collect `entry` through its collector's observer; False when a `skipped` refusal
        stepped over it, parked on any other refusal."""
        try:
            store.collect_obligation(held["custody"], obligation_id=entry["obligation_id"],
                                     observer=observers[entry["collector"]])
        except ProofRefused as refused:
            if refused.reason in skipped:
                return False
            raise _Parked(f"{entry['obligation_id']}: collection refused "
                          f"{refused.reason}") from None
        return True

    def first_pass(lapsing):
        obligations = store.load(transaction_id).proof_plan["obligations"]
        required = [entry["obligation_id"] for entry in obligations if entry["required"]]
        if scenario == "lease_renewal":
            renew()
        collected = 0
        for entry in obligations:
            earlier = records(entry["obligation_id"])
            if earlier and earlier[-1]["admissible"]:
                continue
            if lapsing and entry["obligation_id"] == required[-1]:
                world.tick(601)
            if not collect(entry, SKIPPED) or not entry["required"]:
                continue
            collected += 1
            if scenario == "lease_renewal" and collected == len(required) // 2:
                renew()

    def converge():
        while True:
            try:
                started = store.start_cohort(held["custody"])
            except ProofRefused as refused:
                if refused.reason not in ("proof_incomplete", "convergence_exhausted"):
                    raise _Parked(f"start_cohort refused {refused.reason}") from None
            else:
                plan = started.proof_plan
                by_id = {entry["obligation_id"]: entry for entry in plan["obligations"]}
                for member in plan["cohort"]["members"]:
                    collect(by_id[member])
                    store.renew(held["custody"])
            try:
                settled = store.settle_proof(held["custody"])
            except ProofRefused as refused:
                raise _Parked(f"settle_proof refused {refused.reason}") from None
            if settled.state != "proving":
                return

    def drive_edge(unit, edge):
        """Drive one selected edge as `run_phase` drives a node, until it reads other than
        `absent`."""
        call = {"name": edge["operation"], "parameters": edge["parameters"],
                "effect": effects[unit["effect"]]}
        snapshot = store.inspect_action(held["custody"], **call)
        while True:
            view = next(v for v in snapshot.actions if v["action_id"] == edge["action_id"])
            if view["status"] != "absent":
                return
            if view["attempts"] > 0:
                world.tick(30)
            snapshot = store.invoke_action(held["custody"], **call)

    def recover():
        """The one recovery step after a park (#208 D13, D14)."""
        store.issue_grant(held["custody"], grant_id="recovery-1", actor="fixture-operator")
        try:
            begun = store.begin_recovery(held["custody"], grant_id="recovery-1", observer=router)
        except RecoveryRefused as refused:
            world.notes.append(str(refused))
            if refused.reason == "no_effect":
                advance("abandoned", "no release effect exists")
            elif refused.reason in ("unit_not_restorable", "restore_incompatible"):
                store.roll_forward(
                    held["custody"], grant_id="recovery-1", reason=refused.reason,
                    creation_key=f"{shape}:{scenario}:forward",
                    subject={**subject, "candidate": subject["candidate"] + "-forward"},
                    concurrency_keys=keys, proof=proof, recovery=recovery)
            return
        edges = {edge["action_id"]: (unit, edge) for unit in begun.recovery_plan["units"]
                 for edge in unit["edges"]}
        for edge_id in begun.recovery["selected"]:
            drive_edge(*edges[edge_id])
        store.settle_recovery(held["custody"])

    try:
        advance("awaiting_verification", "candidate verification requested")
        check = profile["target"]["verification"]
        observe(adapter(check["binding"]).inspect(check["predicate"],
                                                  {"expected_subject": subject}),
                "candidate verification")
        advance("ready", "candidate verification satisfied")
        acquire()
        try:
            store.verify_anchors(held["custody"], observer=router)
        except RecoveryRefused as refused:
            world.notes.append(str(refused))
            raise _Parked(f"rollback anchors refused: {refused}") from None
        advance("publishing", "publication started")
        publish()
        advance("published", "every publication unit satisfied")
        activation = [] if profile["activation"] == "none" else profile["activation"]
        if activation:
            advance("activating", "activation started")
            run_phase(activation)
            advance("proving", "every activation unit satisfied")
        else:
            advance("proving", "profile declares activation none")
        try:
            first_pass(lapsing=scenario == "lease_lapse")
        except StaleCustody:
            store.reap(transaction_id, reason="lease expired during proving")
            acquire()
            advance("proving", "resumed after reacquisition")
            first_pass(lapsing=False)
        if scenario == "lease_renewal" and any(
                store.inspect_lease(key)["holder"]["term"] != 3 for key in keys):
            raise _Parked("lease was not renewed to term 3 before sealing")
        converge()
    except _Parked as parked:
        advance("attention_required", str(parked))
        if SCENARIOS[scenario].get("recover"):
            recover()
    return transaction_id
