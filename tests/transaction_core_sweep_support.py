"""Scenario fixture and fixture executor for the transaction core sweep (#204 D6, D17).

The executor is a happy-path walker over the simulated world that asks the shipped core
to advance at each lifecycle boundary through the public store API, on a store whose
clock is the world clock (#205 D22, D29). It acquires custody before publishing and
presents it on every later advance; while proving it records one fenced evidence item
per obligation in the obligation's temporal form, opening an interval first, and skips
an obligation whose latest record is still admissible. Scenario hooks move the world
clock: `lease_renewal` renews in place twice, and `lease_lapse` lets the lease expire,
has the reaper park the transaction, reacquires, resumes proving and recollects what the
new fence voided. It still carries none of the prototype's retry, authorization or
recovery logic. Any observation other than satisfied parks the transaction in
attention_required with the observation as reason.
"""

from agent_tools.transaction_core import StaleCustody, TransactionStore

from .transaction_core_shapes import SHAPES
from .transaction_core_world import World

TTL_MS = 600_000

# `success` is ported from prototype-release-transactions/scenarios.py at dc98ba9;
# `lease_renewal` and `lease_lapse` are new in #205 (D22, D29).
SCENARIOS = {
    "success": {"faults": frozenset(),
                "note": "clean path: publish, activate, prove, seal a terminal receipt."},
    "lease_renewal": {"faults": frozenset(),
                      "note": "the lease is renewed twice in place during proving."},
    "lease_lapse": {"faults": frozenset(),
                    "note": "the lease lapses before the last obligation; reap, reacquire, "
                            "recollect."},
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


def drive(root, shape, scenario):
    world = World()
    world.faults = set(SCENARIOS[scenario]["faults"])
    store = TransactionStore(root, clock=lambda: world.clock * 1000)
    subject, profile, registry = SHAPES[shape](world)
    keys = profile["target"]["concurrency_keys"]
    transaction_id = store.create(f"{shape}:{scenario}", subject,
                                  concurrency_keys=keys).transaction_id
    definite = {"all": True}
    held = {"custody": None}

    def adapter(alias):
        return registry[profile["bindings"][alias]["adapter"]]

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

    def run_phase(nodes):
        for node in _in_dependency_order(nodes):
            env = {"action_id": node["id"], "expected_subject": node["expected_subject"]}
            unit = adapter(node["binding"])
            before = unit.inspect(node["mode"], env)
            if before["outcome"] == "satisfied":
                continue
            if before["outcome"] != "absent":
                observe(before, f"{node['id']} pre-inspect")
            invoked = unit.invoke(node["mode"], env)
            if invoked["result"] != "accepted":
                raise _Parked(f"{node['id']} invoke {invoked['result']}: "
                              f"{invoked.get('error_class')}")
            observe(unit.inspect(node["mode"], env), f"{node['id']} post-inspect")

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
        run_phase(profile["publication"])
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
