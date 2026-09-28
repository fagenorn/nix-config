"""Transaction core slice 4: obligations, the convergence cohort and settlement (#207).

Run: just agent-workflow-tests
"""

import copy
import json
import unittest

from agent_tools import transaction_storage
from agent_tools.transaction_core import (
    PROOF_REFUSAL_REASONS, EffectResultInvalid, ProofRefused, StaleCustody, StateInvalid,
    TransactionError, TransitionRefused, action_id)

from .test_transaction_custody import KEYS, SUBJECT, TTL, CustodyCase, plain, serialize
from .test_transaction_invocation import FakeEffect, FakeWorld, renumbered

PUB, ACT = "published_artifact_identity", "running_subject_identity"
C = {"basis": "deterministic", "max_collection_latency_ms": 30_000,
     "predicates": ["publication_visible", "running_subject_identity", "migrated", "health",
                    "smoke"]}
M = {"basis": "model", "predicates": ["vibe"], "max_collection_latency_ms": 30_000}
UNITS = [{"name": "build", "parameters": {"n": 1}, "phase": "publication", "collector": "c"},
         {"name": "start", "parameters": {"n": 2}, "phase": "activation", "collector": "c"}]


def ob(identity, form, predicate, *, deps=(), required=True, collector="c",
       semantic="readiness"):
    entry = {"id": identity, "semantic": semantic, "form": form, "predicate": predicate,
             "collector": collector, "required": required, "deps": list(deps),
             "parameters": {"of": identity}}
    if form == "snapshot":
        entry["freshness_ms"] = 600_000
    return entry


DECLARATION = {"units": UNITS, "collectors": {"c": C, "m": M}, "obligations": [
    ob("migrated", "event", "migrated"),
    ob("health", "snapshot", "health", deps=["migrated"], semantic="liveness"),
    ob("smoke", "interval", "smoke", deps=[f"derived:{ACT}:start"], semantic="product_smoke"),
    ob("vibe", "snapshot", "vibe", required=False, collector="m", semantic="observability"),
    ob("uptime", "snapshot", "uptime", required=False, semantic="observability")]}


class Boom(Exception):
    """An observer dying mid-call."""


class Observer:
    """An in-memory observer. `outcomes` maps obligation ids to outcomes (default
    `satisfied`); `step_ms` advances the store clock inside every call; `result`
    replaces the reply; `fail` is raised. The reference encodes the request."""

    def __init__(self, clock, outcomes=None, *, reasons=None, step_ms=0, result=None,
                 fail=None):
        self.clock, self.outcomes, self.reasons = clock, outcomes or {}, reasons or {}
        self.step_ms, self.result, self.fail = step_ms, result, fail

    def observe(self, request):
        self.clock.advance(self.step_ms)
        if self.fail is not None:
            raise self.fail
        if self.result is not None:
            return self.result
        outcome = self.outcomes.get(request["obligation_id"], "satisfied")
        reason = self.reasons.get(request["obligation_id"],
                                  "ok" if outcome == "satisfied" else "subject_mismatch")
        epoch = min(entry["epoch"] for entry in request["fence"].values())
        return {"outcome": outcome, "reason": reason,
                "reference": f"obs:{request['cohort']}:{epoch}:{request['predicate']}"}


class ProofCase(CustodyCase):
    def setUp(self):
        super().setUp()
        self.world = FakeWorld()
        self.transaction_id = self.store.create(
            "proof", SUBJECT, concurrency_keys=KEYS, proof=DECLARATION).transaction_id
        self.custody = self.acquire(self.transaction_id)
        self.plan = self.store.load(self.transaction_id).proof_plan
        self.ids = [entry["obligation_id"] for entry in self.plan["obligations"]]
        self.pub, self.act = self.ids[:2]

    def to(self, *targets, custody=None):
        for target in targets:
            after = self.store.advance(self.transaction_id, target, reason="r",
                                       external_state="known",
                                       custody=custody or self.custody)
        return after

    def satisfy(self, name, parameters):
        for operation in (self.store.inspect_action, self.store.invoke_action):
            operation(self.custody, name=name, parameters=parameters,
                      effect=FakeEffect(self.world))

    def proving(self):
        self.to("awaiting_verification", "ready", "publishing")
        self.satisfy("build", {"n": 1})
        self.to("published", "activating")
        self.satisfy("start", {"n": 2})
        return self.to("proving")

    def observer(self, *args, **options):
        return Observer(self.clock, *args, **options)

    def collect(self, obligation_id, observer=None, custody=None):
        return self.store.collect_obligation(custody or self.custody,
                                             obligation_id=obligation_id,
                                             observer=observer or self.observer())

    def collect_required(self, observer=None):
        for obligation_id in (self.pub, self.act, "migrated", "health", "smoke"):
            after = self.collect(obligation_id, observer)
        return after

    def refused(self, reason, call):
        now = self.clock.now
        error = self.assertRefusedUnchanged(ProofRefused, call)
        self.assertEqual((error.reason, self.clock.now), (reason, now))
        self.assertIn(self.transaction_id, str(error))
        return error

    def observed(self):
        return [dict(e) for e in self.store.load(self.transaction_id).events
                if e["type"] == "obligation_observed"]

    def entry(self, obligation_id):
        return next(dict(e) for e in self.store.load(self.transaction_id).proof["obligations"]
                    if e["obligation_id"] == obligation_id)

    def reacquired(self):
        self.clock.advance(TTL)
        self.store.reap(self.transaction_id, reason="executor lost")
        self.custody = self.acquire(self.transaction_id)
        return self.to("proving")


class CollectTest(ProofCase):
    def test_an_observation_is_recorded_with_its_core_measured_latency(self):
        self.proving()
        after = self.collect(self.pub, self.observer(step_ms=1_234))
        recorded = {k: v for k, v in after.events[-1].items() if k not in ("seq", "at")}
        self.assertEqual(recorded, {
            "type": "obligation_observed", "obligation_id": self.pub,
            "evidence_id": f"{self.pub}@1", "form": "event", "outcome": "satisfied",
            "reason": "ok", "reference": "obs:None:1:publication_visible",
            "fence": plain(self.custody.fence), "cohort": None, "latency_ms": 1_234})
        [evidence] = [e for e in after.evidence if e["evidence_id"] == f"{self.pub}@1"]
        self.assertEqual((evidence["form"], evidence["admissible"]), ("event", True))

    def test_the_request_is_read_only(self):
        class Mutating(Observer):
            def observe(self, request):
                request["cohort"] = 1

        self.proving()
        self.assertRefusedUnchanged(TypeError, lambda: self.collect(
            self.pub, Mutating(self.clock)))

    def test_evidence_ids_step_past_every_earlier_id_of_the_obligation(self):
        self.proving()
        self.collect(self.act)
        self.collect(self.act)
        self.store.record_evidence(self.custody, evidence_id=f"{self.act}@7",
                                   form="snapshot", reference="by hand")
        self.collect(self.act)
        self.assertEqual([e["evidence_id"] for e in self.observed()],
                         [f"{self.act}@1", f"{self.act}@2", f"{self.act}@8"])
        self.assertRefusedUnchanged(StateInvalid, lambda: self.store.record_evidence(
            self.custody, evidence_id=f"{self.act}@8", form="snapshot", reference="again"))

    def test_the_core_opens_an_interval_before_its_call(self):
        self.proving()
        self.collect(self.act)
        with self.assertRaises(Boom):
            self.collect("smoke", self.observer(fail=Boom()))
        after = self.collect("smoke")
        trail = [(e["type"], e.get("evidence_id")) for e in after.events
                 if e.get("evidence_id", "").startswith("smoke@")]
        self.assertEqual(trail, [("interval_opened", "smoke@1"), ("interval_opened", "smoke@2"),
                                 ("obligation_observed", "smoke@2")])
        self.assertEqual(self.entry("smoke")["latest_admissible"], True)

    def test_an_invalid_interval_result_keeps_its_opened_marker(self):
        self.proving()
        self.collect(self.act)
        with self.assertRaises(EffectResultInvalid):
            self.collect("smoke", self.observer(result={"outcome": "maybe", "reason": "ok",
                                                        "reference": "r"}))
        self.assertEqual([(e["type"], e.get("evidence_id")) for e in self.store.load(
            self.transaction_id).events][-1], ("interval_opened", "smoke@1"))
        self.assertEqual(self.entry("smoke")["observations"], 0)
        self.assertEqual(self.collect("smoke").events[-1]["evidence_id"], "smoke@2")

    def test_a_clock_that_runs_backwards_during_the_call_records_nothing(self):
        self.proving()
        error = self.assertRefusedUnchanged(ProofRefused, lambda: self.collect(
            self.pub, self.observer(step_ms=-5_000)))
        self.assertEqual(error.reason, "clock_regressed")

    def test_admission_refusals_come_before_any_write_or_call(self):
        slow = self.observer(step_ms=1)
        self.refused("state_not_proving", lambda: self.collect(self.pub, slow))
        self.proving()
        self.refused("unknown_obligation", lambda: self.collect("ghost", slow))
        self.refused("unsupported_obligation", lambda: self.collect("uptime", slow))
        self.refused("dependency_not_accepted", lambda: self.collect("health", slow))
        self.refused("dependency_not_accepted", lambda: self.collect("smoke", slow))
        self.collect("migrated")
        self.refused("already_accepted", lambda: self.collect("migrated", slow))
        self.collect(self.act)
        self.collect("smoke")
        self.refused("already_accepted", lambda: self.collect("smoke", slow))

    def test_a_rejected_prerequisite_suppresses_collection(self):
        self.proving()
        self.collect("migrated", self.observer({"migrated": "unsatisfied"}))
        self.refused("dependency_not_accepted", lambda: self.collect("health"))

    def test_out_of_shape_observations_record_nothing(self):
        self.proving()
        for obligation_id, result in (
                (self.pub, ["not", "a", "result"]),
                (self.pub, {"outcome": "satisfied", "reference": "r"}),
                (self.pub, {"outcome": "satisfied", "reason": "ok", "reference": "r", "x": 1}),
                (self.pub, {"outcome": "maybe", "reason": "ok", "reference": "r"}),
                (self.pub, {"outcome": "satisfied", "reason": "", "reference": "r"}),
                (self.pub, {"outcome": "satisfied", "reason": "ok", "reference": 7}),
                (self.act, {"outcome": "unsatisfied", "reason": "flaky", "reference": "r"}),
                (self.pub, {"outcome": "unknown", "reason": "subject_absent",
                            "reference": "r"})):
            with self.subTest(obligation=obligation_id, result=result):
                self.assertRefusedUnchanged(EffectResultInvalid, lambda: self.collect(
                    obligation_id, self.observer(result=result)))
        self.collect(self.pub, self.observer(result={
            "outcome": "unknown", "reason": "store_unreachable", "reference": "r"}))
        self.collect("migrated", self.observer(result={
            "outcome": "unsatisfied", "reason": "anything stable", "reference": "r"}))

    def test_a_lapse_during_the_call_records_nothing(self):
        self.proving()
        self.assertRefusedUnchanged(StaleCustody, lambda: self.collect(
            self.act, self.observer(step_ms=TTL)))

    def test_the_view_keeps_events_and_voids_snapshots_across_a_fence_change(self):
        self.proving()
        self.collect(self.pub)
        self.collect(self.act)
        view = self.reacquired().proof
        self.assertEqual(view["plan_digest"],
                         self.store.load(self.transaction_id).events[0]["proof_plan_digest"])
        self.assertEqual((view["cohorts"], view["proof_cutoff_at"]), ([], None))
        entries = {e["obligation_id"]: dict(e) for e in view["obligations"]}
        self.assertEqual(list(entries), self.ids)
        self.assertEqual(entries[self.pub], {
            "obligation_id": self.pub, "obligation_kind": "core_derived", "semantic": None,
            "derived_class": PUB, "form": "event", "required": True, "observations": 1,
            "latest_outcome": "satisfied", "latest_admissible": True})
        self.assertEqual((entries[self.act]["latest_admissible"],
                          entries["health"]["observations"],
                          entries["health"]["latest_outcome"],
                          entries["health"]["latest_admissible"]), (False, 0, None, None))

    def test_hand_edited_observations_are_state_invalid(self):
        self.proving()
        pristine = json.loads(serialize(self.state_doc(self.collect(self.pub).transaction_id)))
        last = len(pristine["events"])
        for field, value in (("obligation_id", "ghost"), ("form", "snapshot"),
                             ("evidence_id", f"{self.pub}@2"), ("outcome", "maybe"),
                             ("reason", ""), ("latency_ms", -1), ("latency_ms", True),
                             ("cohort", 1)):
            with self.subTest(field=field, value=value):
                document = copy.deepcopy(pristine)
                document["events"][-1][field] = value
                if field == "obligation_id":
                    document["events"][-1]["evidence_id"] = "ghost@1"
                self.assertRuleRefuses(self.transaction_id, document, f"event {last}")
        document = copy.deepcopy(pristine)
        document["events"][-1].update(outcome="unsatisfied", reason="flaky")
        self.assertRuleRefuses(self.transaction_id, document, f"event {last}")
        document = copy.deepcopy(pristine)
        proving = next(i for i, e in enumerate(document["events"])
                       if e["type"] == "transitioned" and e["to"] == "proving")
        document["events"].insert(proving, copy.deepcopy(document["events"][-1]))
        self.assertRuleRefuses(self.transaction_id, renumbered(document), f"event {proving + 1}")


class ProofVocabularyTest(unittest.TestCase):
    def test_the_error_is_a_transaction_error_homed_in_storage(self):
        self.assertIs(ProofRefused, transaction_storage.ProofRefused)
        self.assertTrue(issubclass(ProofRefused, TransactionError))

    def test_the_refusal_reasons_are_fixed(self):
        self.assertEqual(len(set(PROOF_REFUSAL_REASONS)), 11)


if __name__ == "__main__":
    unittest.main()
