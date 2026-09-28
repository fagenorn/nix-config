"""Scenario fixture and fixture executor for the transaction core sweep (#204 D6, D17;
#206 D12, D18).

The executor is a happy-path walker over the simulated world that asks the shipped core
to advance at each lifecycle boundary through the public store API, on a store whose
clock is the world clock (#205 D22, D29). It acquires custody before publishing and
presents it on every later advance. Every publication and activation node is an action
driven through the core: one effect per binding wraps that binding's adapter, action
`name` is the node id and `parameters` its mode and expected subject, and no adapter
effect is called outside `inspect_action` / `invoke_action`. Each node is pre-inspected,
then invoked until its view reads `satisfied`; before each retry the world clock moves
30 seconds, so the core's retry budget and window run on the world clock. While proving
it records one fenced evidence item per obligation in the obligation's temporal form,
opening an interval first, and skips an obligation whose latest record is still
admissible. Scenario hooks move the world clock: `lease_renewal` renews in place twice;
`lease_lapse` lets the lease expire, has the reaper park the transaction, reacquires,
resumes proving and recollects what the new fence voided; `resume_after_crash` kills the
executor between the first publication action's recorded intent and its call, lets the
lease expire, reaps, reacquires, checks that a blind invoke is refused
`inspection_required`, and resumes publication through a fresh inspection. It carries
none of the prototype's authorization or recovery logic. Any view other than `absent`
or `satisfied`, and any invocation refusal, parks the transaction in attention_required
with the observation or the refusal's reason.
"""

from agent_tools.transaction_core import InvocationRefused, StaleCustody, TransactionStore

from .transaction_core_shapes import SHAPES
from .transaction_core_world import ExecutorCrash, World

TTL_MS = 600_000

# `success` is ported from prototype-release-transactions/scenarios.py at dc98ba9;
# `lease_renewal` and `lease_lapse` are new in #205 (D22, D29); `throttled_retry` and
# `resume_after_crash` are ported from dc98ba9 in #206 (D12), the crash moved to between
# the recorded intent and the call.
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
}


class _Parked(Exception):
    pass


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


def drive(root, shape, scenario, world=None):
    world = World() if world is None else world
    world.faults = set(SCENARIOS[scenario]["faults"])
    store = TransactionStore(root, clock=lambda: world.clock * 1000)
    subject, profile, registry = SHAPES[shape](world)
    keys = profile["target"]["concurrency_keys"]
    transaction_id = store.create(
        f"{shape}:{scenario}", subject, concurrency_keys=keys,
        proof={"units": [], "obligations": [], "collectors": {}}).transaction_id
    definite = {"all": True}
    held = {"custody": None}

    def adapter(alias):
        return registry[profile["bindings"][alias]["adapter"]]

    effects = {alias: _Effect(adapter(alias)) for alias in profile["bindings"]
               if not alias.startswith("_")}

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

    def prove(obligations, first_pass):
        if scenario == "lease_renewal":
            renew()
        accepted, recorded = set(), 0
        for obligation_id, predicate, source, deps, form in obligations:
            earlier = records(obligation_id)
            if earlier and earlier[-1]["admissible"]:
                accepted.add(obligation_id)
                continue
            unmet = [dep for dep in deps if dep not in accepted]
            if unmet:
                raise _Parked(f"{obligation_id}: prerequisite not accepted {unmet}")
            evidence_id = f"{obligation_id}@{len(earlier) + 1}"
            if form == "interval":
                store.open_interval(held["custody"], evidence_id=evidence_id)
            result = adapter(source["binding"]).inspect(
                predicate, {"expected_subject": source["expected_subject"]})
            observe(result, obligation_id)
            store.record_evidence(held["custody"], evidence_id=evidence_id, form=form,
                                  reference=result["payload_ref"])
            accepted.add(obligation_id)
            recorded += 1
            if scenario == "lease_renewal" and recorded == len(obligations) // 2:
                renew()
            if scenario == "lease_lapse" and first_pass and recorded == len(obligations) - 1:
                world.tick(601)

    try:
        advance("awaiting_verification", "candidate verification requested")
        check = profile["target"]["verification"]
        observe(adapter(check["binding"]).inspect(check["predicate"],
                                                  {"expected_subject": subject}),
                "candidate verification")
        advance("ready", "candidate verification satisfied")
        acquire()
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
        obligations = (
            [("floor:publication:" + n["id"], "publication_visible", n, [], "snapshot")
             for n in profile["publication"]]
            + [("floor:activation:" + n["id"], "running_subject_identity", n, [], "snapshot")
               for n in activation]
            + [(o["id"], o["predicate"], o, o.get("deps", []), o["temporal"])
               for o in profile["proof"] if o["required"]])
        try:
            prove(obligations, first_pass=True)
        except StaleCustody:
            store.reap(transaction_id, reason="lease expired during proving")
            acquire()
            advance("proving", "resumed after reacquisition")
            prove(obligations, first_pass=False)
        if scenario == "lease_renewal" and any(
                store.inspect_lease(key)["holder"]["term"] != 3 for key in keys):
            raise _Parked("lease was not renewed to term 3 before sealing")
        advance("succeeded", "every required obligation satisfied")
    except _Parked as parked:
        advance("attention_required", str(parked))
    return transaction_id
