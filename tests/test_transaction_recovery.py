"""Transaction core slice 5: rollback anchors, entering recovery and its edges (#208).

Run: just agent-workflow-tests
"""

import copy
import unittest

from agent_tools.transaction_core import (
    RECOVERY_REFUSAL_REASONS, EffectResultInvalid, RecoveryRefused, StaleCustody,
    TransactionError, TransitionRefused, action_id)

from .test_transaction_custody import KEYS, SUBJECT, TTL, CustodyCase, plain
from .test_transaction_invocation import FakeEffect, FakeWorld, renumbered
from .test_transaction_recovery_plan import PROOF, RECOVERY, with_unit


class Boom(Exception):
    """An observer that must never be reached."""


class Checker:
    """An in-memory anchor and compatibility observer. `outcomes` maps a check (`anchor`,
    `compatibility`) to its outcome, default `satisfied`; `result` replaces the reply;
    `fail` is raised; `during` runs first. The reference encodes the request."""

    def __init__(self, outcomes=None, *, result=None, fail=None, during=None):
        self.outcomes, self.result, self.fail, self.during = outcomes or {}, result, fail, during

    def observe(self, request):
        if self.during:
            self.during()
        if self.fail is not None:
            raise self.fail
        if self.result is not None:
            return self.result
        outcome = self.outcomes.get(request["check"], "satisfied")
        epoch = min(entry["epoch"] for entry in request["fence"].values())
        return {"outcome": outcome, "reason": "ok" if outcome == "satisfied" else "gone",
                "reference": "|".join((request["check"], request["predicate"],
                                       request["collector"], request["parameters"]["prior"],
                                       request["unit"], str(epoch)))}


class RecoveryCase(CustodyCase):
    def setUp(self):
        super().setUp()
        self.world = FakeWorld()
        self.start_with(RECOVERY)

    def start_with(self, recovery, key="recovery", keys=KEYS):
        self.transaction_id = self.store.create(key, SUBJECT, concurrency_keys=keys,
                                                proof=PROOF, recovery=recovery).transaction_id
        self.custody = self.acquire(self.transaction_id)

    def act(self, name, **parameters):
        return action_id(self.transaction_id, name, parameters)

    def to(self, *targets, reason="r"):
        for target in targets:
            after = self.store.advance(self.transaction_id, target, reason=reason,
                                       external_state="known", custody=self.custody)
        return after

    def verify(self, checker=None):
        return self.store.verify_anchors(self.custody, observer=checker or Checker())

    def run_action(self, name, parameters, outcome=None, results=()):
        self.store.inspect_action(self.custody, name=name, parameters=parameters,
                                  effect=FakeEffect(self.world))
        return self.store.invoke_action(
            self.custody, name=name, parameters=parameters,
            effect=FakeEffect(self.world, inspect_outcome=outcome, results=results))

    def published(self):
        self.to("awaiting_verification", "ready")
        self.verify()
        self.to("publishing")
        self.run_action("build", {"n": 1})

    def parked(self, start="diverged", pin=None):
        self.published()
        self.to("published", "activating")
        self.run_action("start", {"n": 2}, start)
        if pin:
            self.run_action("pin", {"n": 3}, pin)
        return self.to("attention_required")

    def refused(self, reason, call):
        error = self.assertRefusedUnchanged(RecoveryRefused, call)
        self.assertEqual(error.reason, reason)
        self.assertIn(self.transaction_id, str(error))
        return error


class AnchorsTest(RecoveryCase):
    def test_verification_records_each_restorable_anchor_under_the_fence(self):
        self.to("awaiting_verification", "ready")
        after = self.verify()
        event = dict(after.events[-1])
        start = self.act("start", n=2)
        self.assertEqual((event["type"], event["fence"]),
                         ("anchors_verified", plain(self.custody.fence)))
        self.assertEqual(event["anchors"], [
            {"unit": start, "reference": f"anchor|rollback_anchor|c|gen-1|{start}|1"}])
        self.assertEqual(self.to("publishing").state, "publishing")

    def test_verification_outside_ready_is_refused_without_a_call(self):
        self.refused("state_not_ready", lambda: self.verify(Checker(fail=Boom())))

    def test_a_missing_or_unverifiable_anchor_refuses_before_publication(self):
        self.to("awaiting_verification", "ready")
        for outcome in ("unsatisfied", "unknown"):
            with self.subTest(outcome=outcome):
                error = self.refused("rollback_anchor_missing",
                                     lambda: self.verify(Checker({"anchor": outcome})))
                self.assertIn(f"start ({self.act('start', n=2)})", str(error))
        error = self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("publishing"))
        self.assertIn("anchors_verified", str(error))

    def test_publication_needs_a_verification_under_the_entering_fence(self):
        self.to("awaiting_verification", "ready")
        self.verify()
        self.clock.advance(TTL)
        self.store.reap(self.transaction_id, reason="executor lost")
        self.custody = self.acquire(self.transaction_id)
        self.to("ready")
        self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("publishing"))
        self.verify()
        self.assertEqual(self.to("publishing").state, "publishing")

    def test_a_resume_to_publishing_is_ungated(self):
        self.published()
        self.clock.advance(TTL)
        self.store.reap(self.transaction_id, reason="executor lost")
        self.custody = self.acquire(self.transaction_id)
        self.assertEqual(self.to("publishing").state, "publishing")

    def test_no_restorable_unit_means_no_call_and_no_write(self):
        self.start_with(with_unit(1, posture="manual_only", anchor=None, compatibility=None,
                                  edges=[]), key="plain", keys=("key:plain",))
        self.to("awaiting_verification", "ready")
        before = self.files()
        self.verify(Checker(fail=Boom()))
        self.assertEqual(self.files(), before)
        self.assertEqual(self.to("publishing").state, "publishing")

    def test_a_malformed_result_or_a_raising_observer_records_nothing(self):
        self.to("awaiting_verification", "ready")
        for checker, error in (
                (Checker(result={"outcome": "satisfied"}), EffectResultInvalid),
                (Checker(result={"outcome": "maybe", "reason": "r", "reference": "x"}),
                 EffectResultInvalid),
                (Checker(result={"outcome": "satisfied", "reason": "", "reference": "x"}),
                 EffectResultInvalid),
                (Checker(fail=Boom()), Boom)):
            with self.subTest(checker=checker.result):
                self.assertRefusedUnchanged(error, lambda: self.verify(checker))

    def test_a_lapse_during_the_call_writes_nothing(self):
        self.to("awaiting_verification", "ready")
        self.assertRefusedUnchanged(StaleCustody, lambda: self.verify(
            Checker(during=lambda: self.clock.advance(TTL))))

    def test_a_history_grown_during_the_call_is_refused(self):
        self.to("awaiting_verification", "ready")
        grow = lambda: self.store.issue_grant(self.custody, grant_id="during", actor="op")
        with self.assertRaises(RecoveryRefused) as caught:
            self.verify(Checker(during=grow))
        self.assertEqual(caught.exception.reason, "history_changed")
        self.assertNotIn("anchors_verified", self.types(self.transaction_id))

    def test_hand_built_anchor_breaches_are_state_invalid(self):
        self.to("awaiting_verification", "ready")
        self.verify()
        document = self.state_doc(self.transaction_id)
        emptied = copy.deepcopy(document)
        emptied["events"][-1]["anchors"] = []
        self.assertRuleRefuses(self.transaction_id, emptied, "anchors")
        skipped = copy.deepcopy(document)
        skipped["events"][-1] = {
            "seq": 0, "type": "transitioned", "at": document["events"][-1]["at"],
            "from": "ready", "to": "publishing", "reason": "r", "external_state": "known"}
        skipped["state"] = "publishing"
        self.assertRuleRefuses(self.transaction_id, renumbered(skipped), "anchors_verified")


class RecoveryVocabularyTest(unittest.TestCase):
    def test_the_refusal_reasons_are_closed(self):
        self.assertEqual(RECOVERY_REFUSAL_REASONS, (
            "state_not_ready", "state_not_attention", "state_not_recovering",
            "history_changed", "rollback_anchor_missing", "grant_required",
            "reconciliation_required", "undeclared_effect", "effect_uncertain", "no_effect",
            "unit_not_restorable", "restore_incompatible", "recovery_pending"))
        self.assertTrue(issubclass(RecoveryRefused, TransactionError))


if __name__ == "__main__":
    unittest.main()
