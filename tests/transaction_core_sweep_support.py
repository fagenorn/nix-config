"""Scenario fixture and fixture executor for the transaction core sweep (#204 D6, D17).

The executor is a happy-path walker over the simulated world that asks the shipped core
to advance at each lifecycle boundary through the public store API. It deliberately
carries none of the prototype's lease, retry, authorization or recovery logic; later
slices move that into the core and this walker shrinks. Any observation other than
satisfied parks the transaction in attention_required with the observation as reason.
"""

from .transaction_core_shapes import SHAPES
from .transaction_core_world import World

# Ported from prototype-release-transactions/scenarios.py at dc98ba9: only the scenarios
# whose sweep rows this slice asserts.
SCENARIOS = {
    "success": {"faults": frozenset(),
                "note": "clean path: publish, activate, prove, seal a terminal receipt."},
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


def drive(store, shape, scenario):
    world = World()
    world.faults = set(SCENARIOS[scenario]["faults"])
    subject, profile, registry = SHAPES[shape](world)
    transaction_id = store.create(
        f"{shape}:{scenario}", subject,
        concurrency_keys=profile["target"]["concurrency_keys"]).transaction_id
    definite = {"all": True}

    def adapter(alias):
        return registry[profile["bindings"][alias]["adapter"]]

    def external_state():
        return "known" if definite["all"] else "unknown"

    def advance(target, reason):
        store.advance(transaction_id, target, reason=reason, external_state=external_state())

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

    try:
        advance("awaiting_verification", "candidate verification requested")
        check = profile["target"]["verification"]
        observe(adapter(check["binding"]).inspect(check["predicate"],
                                                  {"expected_subject": subject}),
                "candidate verification")
        advance("ready", "candidate verification satisfied")
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
            [("floor:publication:" + n["id"], "publication_visible", n, [])
             for n in profile["publication"]]
            + [("floor:activation:" + n["id"], "running_subject_identity", n, [])
               for n in activation]
            + [(o["id"], o["predicate"], o, o.get("deps", []))
               for o in profile["proof"] if o["required"]])
        accepted = set()
        for obligation_id, predicate, source, deps in obligations:
            unmet = [dep for dep in deps if dep not in accepted]
            if unmet:
                raise _Parked(f"{obligation_id}: prerequisite not accepted {unmet}")
            observe(adapter(source["binding"]).inspect(
                predicate, {"expected_subject": source["expected_subject"]}), obligation_id)
            accepted.add(obligation_id)
        advance("succeeded", "every required obligation satisfied")
    except _Parked as parked:
        advance("attention_required", str(parked))
    return transaction_id
