"""Delivery proof, the `succeeded` seals and receipt supplements (#339 D5, D6), through the
CLI from source.

Run: just agent-workflow-tests
"""

import unittest

from agent_tools import attempt_custody as ac
from agent_tools import attempt_delivery as ad
from agent_tools.canonical import telemetry_digest

from .test_attempt_custody import LifecycleCustody, T
from .test_control_cutover import MATCHING, MERGED, Cutover
from .test_delivered_control import DELIVERED, at

ABSENT = {DELIVERED: "absent"}


class SealingTest(Cutover, unittest.TestCase):
    def receipt(self, transaction):
        return self.core().read_receipt(transaction.terminal["receipt_digest"])

    def supplements(self, transaction):
        return [(s["outcome"], s["reason"], s["reference"]) for s in
                self.core().post_terminal_observations(transaction.terminal["receipt_digest"])]

    def receipts(self):
        return {path: content for path, content in self.tree().items()
                if "/receipts/" in path and "/observations" not in path}

    def assert_sealed(self):
        delivery = self.delivery(DELIVERED)
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.state, "succeeded")
        digest, post = delivery.terminal["receipt_digest"], self.ledger_document()[
            "issues"][str(DELIVERED)]["delivery"]["postconditions"]
        self.assertEqual((self.receipt(delivery)["outcome"],
                          [e["obligation_id"] for e in self.receipt(delivery)["evaluations"]]),
                         ("succeeded", list(ad.POSTCONDITIONS)))
        self.assertEqual(
            {e["obligation_id"]: (e["outcome"], e["reason"], e["reference"])
             for e in delivery.events if e["type"] == "obligation_observed"},
            {name: ("satisfied", "observed", post[name]["observation_id"])
             for name in ad.POSTCONDITIONS})
        for held in (self.custody(DELIVERED), self.remainder(DELIVERED)):
            self.assertEqual((held.state, held.custody, self.receipt(held)["outcome"]),
                             ("succeeded", None, "succeeded"))
            self.assertIn(("delivery-receipt", digest),
                          [(e["evidence_id"], e["reference"]) for e in held.evidence])
        self.assertIsNone(self.lease(self.worktrees[DELIVERED])["holder"])
        return digest

    def test_ac4_a_delivery_through_a_remainder_seals_its_proof_then_its_custody(self):
        self.delivered()
        digest = self.assert_sealed()
        (stop,) = self.receipt(self.custody(DELIVERED))["stops"]
        self.assertEqual((stop["reason"], stop["executor_id"]), ("expiry", f"{DELIVERED}:1:1"))
        self.assertEqual(self.records(DELIVERED)[1][0]["state"], "active")
        sealed = self.receipts()
        self.assertEqual(len(sealed), 3)
        late = self.observed(self.built[DELIVERED]["contract"], at(40), "worktree_absent")
        self.sweep(40, recorded=ABSENT, closed={DELIVERED}, contracts=True,
                   observations={DELIVERED: [late]})
        self.assertEqual(
            [(s["outcome"], s["reason"], s["reference"], s["contradicts_ground"])
             for s in self.core().post_terminal_observations(digest)],
            [("satisfied", f"delivery_observations:{late['id']}",
              self.model.canonical_bytes(late).decode(), False)])
        self.sweep(41, recorded=ABSENT, closed={DELIVERED})
        self.assertEqual((len(self.core().post_terminal_observations(digest)), self.receipts()),
                         (1, sealed))

    def cut(self, *reached, cohort=False):
        """A delivered schema-9 ledger whose attempt's custody seal was cut at the last of
        `reached` (after opening its cohort, with `cohort`)."""
        self.generation = "base"
        self.delivered()
        self.generation = "head"
        attempt = self.custody(DELIVERED)
        core = self.core(at(33))
        core.advance(attempt.transaction_id, "created", reason="delivered")
        held = core.acquire(attempt.transaction_id, executor_id=f"{DELIVERED}:1:seal",
                            subject_path=attempt.subject["worktree"],
                            ttl_ms=ad.HELPER_TTL_MS).custody
        for target in reached:
            core.advance(attempt.transaction_id, target, reason="delivered", custody=held)
        if cohort:
            core.start_cohort(held)

    def test_a_schema_9_ledger_that_is_already_delivered_seals_at_its_bind(self):
        self.cut("awaiting_verification", "ready")
        self.cli("migrate", "--repo-root", self.root, "--apply")
        self.assertEqual(self.ledger_document()["schema_version"], 10)
        self.assert_sealed()
        self.assertEqual(self.remainder(DELIVERED).subject["bound_launch"], 1)
        bound = self.tree()
        self.cli("migrate", "--repo-root", self.root, "--apply")
        self.assertEqual(self.tree(), bound)

    def test_a_seal_cut_after_its_cohort_resumes(self):
        self.cut(*ac.FORWARD_STATES, cohort=True)
        self.cli("migrate", "--repo-root", self.root, "--apply")
        self.assert_sealed()

    def test_a_seal_past_the_window_parks(self):
        self.cut(*ac.FORWARD_STATES)
        late = self.observed(self.built[DELIVERED]["contract"], at(70), "worktree_absent")
        self.sweep(70, recorded=ABSENT, closed={DELIVERED}, contracts=True,
                   observations={DELIVERED: [late]})
        attempt = self.custody(DELIVERED)
        self.assertEqual(
            (attempt.state, attempt.custody, self.reason(attempt),
             self.delivery(DELIVERED).state, self.remainder(DELIVERED).state),
            ("attention_required", None, "proof_did_not_converge", "succeeded", "succeeded"))
        parked = self.tree()
        self.cli("migrate", "--repo-root", self.root, "--apply")
        self.assertEqual(self.tree(), parked)

    def test_a_merge_reconciled_after_an_abandoned_seal_is_a_supplement(self):
        self.spawn(DELIVERED)
        self.failing(f"{DELIVERED}:1:1", 3)
        sealed = self.custody(DELIVERED)
        self.assertEqual(sealed.state, "abandoned")
        receipt = self.receipts()
        self.sweep(4, recorded=MATCHING, forge={DELIVERED: MERGED})
        attempt = self.records(DELIVERED)[0][0]
        self.assertEqual((attempt["state"], attempt["result_source"]), ("merged", "superseded"))
        expected = [("satisfied", "reconciled_merge", telemetry_digest(attempt["result"]))]
        self.assertEqual(self.supplements(sealed), expected)
        self.sweep(5, recorded=MATCHING)
        self.assertEqual(self.supplements(sealed), expected)
        self.assertEqual({path: content for path, content in self.receipts().items()
                          if path in receipt}, receipt)


class LateResultTest(LifecycleCustody, unittest.TestCase):
    def test_an_owner_result_after_the_seal_is_a_supplement(self):
        self.spawn_14()
        self.contractless()
        self.finish_raw(1, self.stopped(), now=T(5), action_id="14:1:1")
        sealed = self.custody(14)
        self.assertEqual(sealed.state, "abandoned")
        late, ledger = self.stopped("a different report"), self.state_path.read_bytes()
        for minute in (6, 7):  # the same report twice is one supplement
            refused = self.finish_raw(1, late, now=T(minute), action_id="14:1:1", ok=False)
            self.assertIn("conflicting terminal result", refused.stderr)
        self.assertEqual(
            [(s["outcome"], s["reason"], s["reference"]) for s in
             self.core().post_terminal_observations(sealed.terminal["receipt_digest"])],
            [("unknown", "owner_result:14:1:1", telemetry_digest(late))])
        self.assertEqual(self.state_path.read_bytes(), ledger)
