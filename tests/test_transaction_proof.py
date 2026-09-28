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


class CohortCase(ProofCase):
    def ready(self, observer=None):
        """Proving, with every required obligation accepted once, outside any cohort."""
        self.proving()
        return self.collect_required(observer)

    def start(self):
        return self.store.start_cohort(self.custody)

    def settle(self):
        return self.store.settle_proof(self.custody)

    def members(self, observer=None, only=None):
        for member in only or self.plan["cohort"]["members"]:
            after = self.collect(member, observer)
        return after

    def wait(self, ms):
        """Advance the clock by `ms`, renewing custody on the way so it never lapses."""
        while ms > 0:
            step = min(ms, 300_001)
            self.clock.advance(step)
            self.store.renew(self.custody)
            ms -= step

    def types(self):
        return [e["type"] for e in self.store.load(self.transaction_id).events]

    def last(self, event_type):
        return dict(next(e for e in reversed(self.store.load(self.transaction_id).events)
                         if e["type"] == event_type))

    def failed(self):
        self.assertEqual(self.settle().state, "proving")
        return self.last("proof_cohort_failed")["reason"]


class CohortTest(CohortCase):
    def test_a_cohort_starts_once_every_required_obligation_was_accepted(self):
        self.refused("state_not_proving", self.start)
        self.proving()
        self.collect(self.pub)
        self.refused("proof_incomplete", self.start)
        for obligation_id in (self.act, "migrated", "health", "smoke"):
            self.collect(obligation_id)
        after = self.start()
        self.assertEqual({k: v for k, v in after.events[-1].items() if k not in ("seq", "at")},
                         {"type": "proof_cohort_started", "cohort": 1,
                          "fence": plain(self.custody.fence)})
        self.refused("cohort_open", self.start)
        self.refused("not_cohort_member", lambda: self.collect("vibe", self.observer(step_ms=1)))
        self.assertEqual(self.collect(self.act).events[-1]["cohort"], 1)

    def test_a_cohort_that_opens_during_a_call_refuses_the_observation(self):
        store, custody = self.store, None

        class Starting(Observer):
            def observe(self, request):
                store.start_cohort(custody)
                return super().observe(request)

        self.ready()
        custody = self.custody
        with self.assertRaises(ProofRefused) as caught:
            self.collect("vibe", Starting(self.clock))
        self.assertEqual(caught.exception.reason, "not_cohort_member")
        self.assertNotIn("vibe", [e["obligation_id"] for e in self.observed()])
        self.assertEqual(self.types()[-1], "proof_cohort_started")

    def test_fresh_members_seal_success_at_one_cutoff(self):
        self.ready()
        self.clock.advance(1_000)
        self.start()
        self.members()
        after = self.settle()
        self.assertEqual((after.state, after.custody), ("succeeded", None))
        self.assertEqual([e["type"] for e in after.events[-3:]],
                         ["proof_sealed", "transitioned", "lease_released"])
        seal = dict(after.events[-3])
        self.assertEqual({k: v for k, v in seal.items() if k not in ("seq", "at", "fence")}, {
            "type": "proof_sealed", "cohort": 1, "proof_cutoff_at": seal["at"],
            "makespan_ms": 60_000, "governing_window_ms": 600_000,
            "advisory_warnings": ["vibe", "uptime"]})
        transition = after.events[-2]
        self.assertEqual((transition["to"], transition["reason"], transition["external_state"]),
                         ("succeeded", "proof_sealed", "known"))
        self.assertEqual(after.proof["cohorts"], [{"cohort": 1, "status": "sealed",
                                                   "reason": None}])
        self.assertEqual(after.proof["proof_cutoff_at"], seal["at"])
        self.assertTrue(all(self.store.inspect_lease(key)["holder"] is None for key in KEYS))

    def test_an_advisory_model_obligation_warns_but_never_blocks(self):
        self.ready()
        self.collect("vibe", self.observer({"vibe": "unsatisfied"}))
        self.start()
        self.members()
        after = self.settle()
        self.assertEqual(after.state, "succeeded")
        self.assertEqual(after.events[-3]["advisory_warnings"], ["vibe", "uptime"])

    def test_a_snapshot_collected_before_the_cohort_cannot_seal(self):
        self.ready()
        self.start()
        self.members(only=[self.act])
        self.assertEqual(self.failed(), "member_missing")
        view = self.store.load(self.transaction_id).proof
        self.assertEqual(view["cohorts"], [{"cohort": 1, "status": "failed",
                                            "reason": "member_missing"}])

    def test_a_member_older_than_its_freshness_fails_the_cohort(self):
        self.ready()
        self.start()
        self.members()
        self.wait(600_001)
        self.assertEqual(self.failed(), "cohort_expired")

    def test_a_cutoff_past_the_governing_window_fails_the_cohort(self):
        self.ready()
        self.start()
        self.wait(590_000)
        self.members(self.observer(step_ms=6_000))
        self.assertEqual(self.failed(), "cohort_expired")

    def test_an_observation_over_its_declared_latency_fails_the_cohort(self):
        self.ready()
        self.start()
        self.members(self.observer(step_ms=30_001))
        self.assertEqual(self.failed(), "collection_bound_exceeded")

    def test_an_indeterminate_member_fails_the_cohort(self):
        self.ready()
        self.start()
        self.members(self.observer({self.act: "unknown"},
                                   reasons={self.act: "identity_unobservable"}))
        self.assertEqual(self.failed(), "member_indeterminate")

    def test_authoritative_disproval_parks_proof_rejected(self):
        self.proving()
        self.collect(self.pub)
        after = self.collect(self.act, self.observer({self.act: "unsatisfied"}))
        after = self.settle()
        self.assertEqual((after.state, after.parked_from), ("attention_required", "proving"))
        self.assertEqual(after.custody, self.custody)
        rejected, transition = after.events[-2:]
        self.assertEqual((rejected["type"], rejected["obligations"]),
                         ("proof_rejected", [self.act]))
        self.assertEqual((transition["reason"], transition["external_state"]),
                         ("proof_rejected", "known"))
        self.assertNotIn("proof_cohort_started", self.types())

    def test_rejection_dominates_an_open_cohort(self):
        self.ready()
        self.start()
        self.members(self.observer({"health": "unsatisfied"}))
        self.assertEqual(self.settle().events[-1]["reason"], "proof_rejected")

    def test_a_spent_budget_parks_proof_did_not_converge(self):
        self.ready()
        for _ in range(3):
            self.start()
            self.members(only=[self.act])
            after = self.settle()
        self.assertEqual(after.state, "attention_required")
        failed, exhausted, transition = after.events[-3:]
        self.assertEqual((failed["type"], failed["cohort"], failed["reason"]),
                         ("proof_cohort_failed", 3, "member_missing"))
        self.assertEqual((exhausted["type"], exhausted["cohorts"], exhausted["exhausted_by"]),
                         ("proof_convergence_exhausted", 3, "budget"))
        self.assertEqual((transition["reason"], transition["external_state"]),
                         ("proof_did_not_converge", "known"))
        states = [e["to"] for e in after.events if e["type"] == "transitioned"]
        self.assertNotIn("recovering", states)
        self.to("proving")
        self.refused("convergence_exhausted", self.start)

    def test_the_window_runs_from_the_first_entry_into_proving(self):
        self.ready()
        self.wait(1_800_000 - 72_000 + 1)
        self.refused("convergence_exhausted", self.start)
        after = self.settle()
        self.assertEqual((after.events[-2]["cohorts"], after.events[-2]["exhausted_by"],
                          after.events[-1]["reason"]),
                         (0, "window", "proof_did_not_converge"))

    def test_settling_without_an_open_cohort_is_refused_while_budget_remains(self):
        self.ready()
        self.refused("no_open_cohort", self.settle)

    def test_reacquisition_fails_the_open_cohort_without_resetting_the_budget(self):
        self.ready()
        self.start()
        self.reacquired()
        self.assertIsNone(self.collect(self.act).events[-1]["cohort"])
        self.collect("health")
        self.collect("smoke")
        after = self.start()
        self.assertEqual([(e["type"], e["cohort"], e.get("reason")) for e in after.events[-2:]],
                         [("proof_cohort_failed", 1, "fence_changed"),
                          ("proof_cohort_started", 2, None)])

    def test_the_seal_is_refused_over_an_unresolved_action(self):
        self.ready()
        self.start()
        self.members()
        self.store.inspect_action(self.custody, name="build", parameters={"n": 1},
                                  effect=FakeEffect(self.world, inspect_outcome="in_progress"))
        error = self.assertRefusedUnchanged(TransitionRefused, self.settle)
        self.assertIn(action_id(self.transaction_id, "build", {"n": 1}), str(error))

    def test_a_parking_is_not_blocked_by_an_unresolved_action(self):
        self.proving()
        self.collect(self.act, self.observer({self.act: "unsatisfied"}))
        self.store.inspect_action(self.custody, name="build", parameters={"n": 1},
                                  effect=FakeEffect(self.world, inspect_outcome="in_progress"))
        self.assertEqual(self.settle().state, "attention_required")


class CohortValidatorTest(CohortCase):
    def sealed(self):
        self.ready()
        self.start()
        self.members()
        self.settle()
        return self.state_doc(self.transaction_id)

    def assertEditRefused(self, document):
        self.assertRuleRefuses(self.transaction_id, document, self.transaction_id)

    def test_hand_edited_cohorts_and_seals_are_state_invalid(self):
        pristine = self.sealed()
        index = {e["type"]: i for i, e in enumerate(pristine["events"])}

        def edit(change):
            document = copy.deepcopy(pristine)
            change(document["events"])
            return renumbered(document)

        cases = {
            "skipped number": lambda ev: ev[index["proof_cohort_started"]].update(cohort=2),
            "unobserved member": lambda ev: [e.update(cohort=None) for e in ev
                                             if e.get("obligation_id") == "health"],
            "wrong makespan": lambda ev: ev[index["proof_sealed"]].update(makespan_ms=1),
            "wrong cutoff": lambda ev: ev[index["proof_sealed"]].update(
                proof_cutoff_at="2000-01-01T00:00:00.000Z"),
            "second start": lambda ev: ev.insert(index["proof_cohort_started"] + 1,
                                                 copy.deepcopy(ev[index["proof_cohort_started"]])),
            "bad reason": lambda ev: ev.insert(index["proof_sealed"], {
                **copy.deepcopy(ev[index["proof_cohort_started"]]),
                "type": "proof_cohort_failed", "reason": "tired"}),
        }
        for name, change in cases.items():
            with self.subTest(edit=name):
                self.assertEditRefused(edit(change))

    def test_a_seal_over_unproved_required_evidence_is_state_invalid(self):
        pristine = self.sealed()
        seal = next(i for i, e in enumerate(pristine["events"]) if e["type"] == "proof_sealed")

        def latest(events, obligation_id):
            return next(e for e in reversed(events[:seal])
                        if e["type"] == "obligation_observed"
                        and e["obligation_id"] == obligation_id)

        def without_smoke(events):
            events[:] = [e for e in events if not e.get("evidence_id", "").startswith("smoke@")]

        cases = {
            "rejected": lambda ev: latest(ev, "health").update(outcome="unsatisfied",
                                                               reason="flaky"),
            "unknown": lambda ev: latest(ev, "health").update(outcome="unknown",
                                                              reason="unreachable"),
            "over latency": lambda ev: latest(ev, "health").update(latency_ms=30_001),
            "missing": without_smoke,
        }
        for name, change in cases.items():
            with self.subTest(edit=name):
                document = copy.deepcopy(pristine)
                change(document["events"])
                self.assertEditRefused(renumbered(document))

    def test_reserved_reasons_and_their_events_come_in_pairs(self):
        self.proving()
        self.collect(self.act, self.observer({self.act: "unsatisfied"}))
        self.settle()
        pristine = self.state_doc(self.transaction_id)
        unpaired_event = copy.deepcopy(pristine)
        unpaired_event["events"][-1]["reason"] = "operator looked"
        self.assertEditRefused(unpaired_event)
        unpaired_reason = copy.deepcopy(pristine)
        del unpaired_reason["events"][-2]
        self.assertEditRefused(renumbered(unpaired_reason))
        trailing = copy.deepcopy(pristine)
        del trailing["events"][-1]
        trailing.update(state="proving", parked_from=None)
        self.assertEditRefused(renumbered(trailing))


class GateTest(ProofCase):
    def test_succeeded_is_reachable_only_through_settle_proof(self):
        self.proving()
        self.collect_required()
        error = self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("succeeded"))
        self.assertIn("settle_proof", str(error))

    def test_published_needs_every_publication_unit_satisfied(self):
        self.to("awaiting_verification", "ready", "publishing")
        error = self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("published"))
        self.assertIn("undeclared", str(error))
        self.store.inspect_action(self.custody, name="build", parameters={"n": 1},
                                  effect=FakeEffect(self.world))
        error = self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("published"))
        self.assertIn("absent", str(error))
        self.satisfy("build", {"n": 1})
        self.assertEqual(self.to("published").state, "published")

    def test_proving_after_activation_needs_every_activation_unit_satisfied(self):
        self.to("awaiting_verification", "ready", "publishing")
        self.satisfy("build", {"n": 1})
        self.to("published", "activating")
        self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("proving"))
        self.satisfy("start", {"n": 2})
        self.assertEqual(self.to("proving").state, "proving")

    def test_proving_straight_from_published_needs_no_activation_unit(self):
        self.to("awaiting_verification", "ready", "publishing")
        self.satisfy("build", {"n": 1})
        self.to("published")
        error = self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("proving"))
        self.assertIn("activation", str(error))
        self.transaction_id = self.store.create(
            "no-activation", SUBJECT, concurrency_keys=("key:solo",),
            proof={**DECLARATION, "units": UNITS[:1], "obligations": []}).transaction_id
        self.custody = self.acquire(self.transaction_id)
        self.to("awaiting_verification", "ready", "publishing")
        self.satisfy("build", {"n": 1})
        self.assertEqual(self.to("published", "proving").state, "proving")

    def test_a_resume_to_the_parked_state_is_ungated(self):
        self.to("awaiting_verification", "ready", "publishing")
        self.satisfy("build", {"n": 1})
        self.to("published")
        self.store.inspect_action(self.custody, name="build", parameters={"n": 1},
                                  effect=FakeEffect(self.world, inspect_outcome="diverged"))
        self.to("attention_required")
        self.assertEqual(self.to("published").state, "published")

    def test_advance_never_writes_a_reserved_reason(self):
        self.proving()
        for reason in ("proof_rejected", "proof_did_not_converge"):
            with self.subTest(reason=reason):
                self.assertRefusedUnchanged(TransitionRefused, lambda: self.store.advance(
                    self.transaction_id, "attention_required", reason=reason,
                    custody=self.custody))
        after = self.store.advance(self.transaction_id, "attention_required",
                                   reason="operator asked", custody=self.custody)
        self.assertEqual(after.state, "attention_required")

    def test_hand_built_gate_breaches_are_state_invalid(self):
        def appended(document, source, target):
            document = copy.deepcopy(document)
            document["events"].append({
                "seq": 0, "type": "transitioned", "at": document["events"][-1]["at"],
                "from": source, "to": target, "reason": "r", "external_state": "known"})
            document.update(state=target, parked_from=None)
            return renumbered(document)

        self.to("awaiting_verification", "ready", "publishing")
        self.store.inspect_action(self.custody, name="build", parameters={"n": 1},
                                  effect=FakeEffect(self.world))
        publishing = self.state_doc(self.transaction_id)
        self.assertRuleRefuses(self.transaction_id,
                               appended(publishing, "publishing", "published"),
                               "publication unit build")
        (self.root / self.transaction_id / "state.json").write_text(serialize(publishing))
        self.store.invoke_action(self.custody, name="build", parameters={"n": 1},
                                 effect=FakeEffect(self.world))
        self.to("published", "activating")
        self.satisfy("start", {"n": 2})
        self.to("proving")
        self.collect_required()
        proving = self.state_doc(self.transaction_id)
        unsealed = appended(proving, "proving", "succeeded")
        unsealed["events"].append({
            "seq": len(unsealed["events"]) + 1, "type": "lease_released",
            "at": unsealed["events"][-1]["at"], "fence": proving["custody"]["fence"],
            "reason": "terminal"})
        unsealed.update(custody=None, revision=len(unsealed["events"]))
        self.assertRuleRefuses(self.transaction_id, unsealed, "proof_sealed")


OBSERVED_PROOF_REASONS = {
    "state_not_proving", "unknown_obligation", "unsupported_obligation",
    "dependency_not_accepted", "already_accepted", "not_cohort_member", "clock_regressed",
    "proof_incomplete", "cohort_open", "convergence_exhausted", "no_open_cohort"}


class ProofVocabularyTest(unittest.TestCase):
    def test_the_error_is_a_transaction_error_homed_in_storage(self):
        self.assertIs(ProofRefused, transaction_storage.ProofRefused)
        self.assertTrue(issubclass(ProofRefused, TransactionError))

    def test_the_refusal_reasons_are_exactly_the_observed_ones(self):
        self.assertEqual(set(PROOF_REFUSAL_REASONS), OBSERVED_PROOF_REASONS)


if __name__ == "__main__":
    unittest.main()
