"""One case per control decision of the current control interface (#339 AC3, D13): the
reply equals the package-2 helper's in the same root (D20), and the store is read back.

Run: just agent-workflow-tests
"""

import json
import os
import shutil
import unittest

from agent_tools import attempt_custody as ac
from agent_tools import attempt_delivery as ad

from .test_control_cutover import BOTH, MATCHING, MERGED, ROLES, RUN_ID, Cutover
from .test_delivered_control import DELIVERED, DISPATCH, LIVE, at

FIRST, SECOND = f"{DELIVERED}:1:1", f"{LIVE}:1:1"


class DecisionTest(Cutover, unittest.TestCase):
    def twin(self, scenario, slots=7):
        """Run `scenario` (it returns completed commands) on both generations and compare;
        the head pass's replies, decoded. The head pass runs last, so the store is its."""
        self.setup_run()
        replies = {}
        for generation in ("base", "head"):
            self.generation = generation
            shutil.rmtree(self.root / ".superpowers")
            self.declare(slots)
            minted = json.loads(self.cli("init-run", "--repo-root", self.root,
                                         "--creation-key", "twin", "--now", at(0)).stdout)
            self.run_args = ("--repo-root", self.root, "--run-id", minted["run_id"])
            self.ledger = (self.root / ".superpowers/workflows" / minted["run_id"]
                           / "state.json")
            replies[generation] = [
                RUN_ID.sub(b"RUN", self.validated("workflow-response", done.stdout))
                for done in scenario()]
        self.assertEqual(replies["head"], replies["base"])
        return [json.loads(raw) for raw in replies["head"]]

    def spawned(self, *issues, **kwargs):
        return self.sweep(0, recorded=dict.fromkeys(issues), contracts=True, **kwargs)

    def dispatched(self, reply):
        return [(a["kind"], a["custody"]["action_id"]) for a in reply["actions"]
                if a["kind"] in DISPATCH]

    def deltas(self, reply):
        return [(d["issue"], d["kind"], d["state"]) for d in reply["deltas"]]

    def run_id(self):
        return self.ledger_document()["transaction_id"]

    def unsealed_retry(self):
        return [self.spawned(DELIVERED), self.failing(FIRST, 3), self.sweep(4, recorded=MATCHING),
                self.failing(f"{DELIVERED}:2:1", 5), self.sweep(6, recorded=MATCHING)]

    def test_01_spawn(self):
        (reply,) = self.twin(lambda: [self.spawned(DELIVERED)])
        self.assertEqual((self.dispatched(reply), self.deltas(reply)),
                         ([("spawn", FIRST)], [(DELIVERED, "spawned", "active")]))
        held = self.custody(DELIVERED)
        self.assertEqual((held.custody.executor_id, self.claim_ids(held)),
                         (FIRST, [f"admission-claim:{FIRST}:1"]))
        (claim,) = [e for e in held.evidence if e["evidence_id"].startswith("admission-")]
        self.assertEqual((claim["form"], json.loads(claim["reference"])),
                         ("snapshot", {"roles": ROLES, "route": "claude-code"}))
        journal = self.delivery(DELIVERED)
        self.assertTrue(journal is not None and journal.evidence)

    def test_02_resume(self):
        reply = self.twin(lambda: [self.spawned(DELIVERED), self.sweep(31, recorded=MATCHING)])[-1]
        self.assertEqual(self.dispatched(reply), [("resume", f"{DELIVERED}:1:2")])
        self.assertIn((DELIVERED, "resumed", "active"), self.deltas(reply))
        held = self.custody(DELIVERED)
        self.assertEqual((held.state, held.custody.executor_id, ac.span_epoch(held.custody),
                          self.claim_ids(held)[-1:]),
                         ("created", f"{DELIVERED}:1:2", 2,
                          [f"admission-claim:{DELIVERED}:1:2:2"]))
        # The earlier launch's claim is void: a snapshot does not outlive its fence.
        self.assertEqual([e["admissible"] for e in held.evidence
                          if e["evidence_id"].startswith("admission-")], [False, True])

    def test_03_retry(self):
        reply = self.twin(lambda: [self.spawned(DELIVERED), self.failing(FIRST, 3),
                                   self.sweep(4, recorded=MATCHING)])[-1]
        self.assertEqual((self.dispatched(reply), self.deltas(reply)), (
            [("retry", f"{DELIVERED}:2:1")], [(DELIVERED, "retried", "active")]))
        first, second = self.custody(DELIVERED), self.custody(DELIVERED, 2)
        self.assertEqual((first.state, second.subject["prior"], second.state,
                          second.custody.executor_id, self.claim_ids(second)),
                         ("abandoned", first.transaction_id, "created", f"{DELIVERED}:2:1",
                          [f"admission-claim:{DELIVERED}:2:1:2"]))

    def test_04_remainder_launch(self):
        reply = self.twin(lambda: [self.spawned(DELIVERED), self.sweep(
            31, recorded=MATCHING, forge={DELIVERED: MERGED})])[-1]
        self.assertEqual(self.dispatched(reply), [("delivery_remainder", f"{DELIVERED}:r1:1")])
        attempt, held = self.custody(DELIVERED), self.remainder(DELIVERED)
        self.assertIsNotNone(held)
        self.assertEqual(dict(held.subject), ad.remainder_subject(
            run=self.run_id(), issue=DELIVERED, remainder=1, prior=attempt.transaction_id,
            worktree=os.path.realpath(self.worktrees[DELIVERED]), bound_launch=None))
        self.assertEqual((attempt.custody, held.custody.executor_id, self.claim_ids(held)),
                         (None, f"{DELIVERED}:r1:1", [f"admission-claim:{DELIVERED}:r1:1:2"]))
        self.assertEqual(self.lease(self.worktrees[DELIVERED])["holder"]["transaction_id"],
                         held.transaction_id)

    def recovery(self):
        contract = self.built[DELIVERED]["contract"]
        scope = self.build("scope", {"contract": contract, "stage_id": "merge_pr"})

        def evidence(kind, minute, digit):
            return {"source_kind": kind, "reference": f"{kind}:probe", "observed_at": at(minute),
                    "evidence_digest": "sha256:" + digit * 64}

        proof = {"schema_version": 1, "kind": "delivery-recovery", "id": "",
                 "contract_digest": self.model.canonical_digest(contract),
                 "stage_id": "merge_pr", "requested_scope": scope,
                 "failure": {"kind": "effect_failure", "effect_attempted": True,
                             "classification": "transient", **evidence("host", 39, "4")},
                 "effect_absence": {"kind": "effect_absence", "absent": True,
                                    "probe_succeeded": True, **evidence("filesystem", 41, "5")},
                 "basis": {"kind": "changed_relevant_evidence", "scope_id": scope["id"],
                           **evidence("tracker", 42, "6")}}
        proof["id"] = self.model.canonical_digest(proof, omit_derived="id")
        return proof

    def test_05_recover(self):
        def scenario():
            custody, sweeps = self.reconciled_twin()
            self.merge_checkpoint(custody, 33)  # r1 reaches the merge stage, then fails
            return [*sweeps, self.finish(self.summary(custody, "failed"), 40),
                    self.sweep(43, recorded=MATCHING, contracts=True,
                               recoveries={DELIVERED: self.recovery()})]

        reply = self.twin(scenario)[-1]
        self.assertEqual(self.dispatched(reply), [("delivery_remainder", f"{DELIVERED}:r2:1")])
        first, second = self.remainder(DELIVERED), self.remainder(DELIVERED, 2)
        self.assertIsNotNone(second)
        self.assertEqual((first.state, second.subject["prior"], second.custody.executor_id),
                         ("abandoned", first.transaction_id, f"{DELIVERED}:r2:1"))

    def reconciled_twin(self):
        """`reconciled` as scenario steps: (r1's custody, the two completed sweeps)."""
        first = self.spawned(DELIVERED)
        second = self.sweep(31, recorded=MATCHING, forge={DELIVERED: MERGED})
        (custody,) = [a["custody"] for a in json.loads(second.stdout)["actions"]
                      if a["kind"] in DISPATCH]
        return custody, [first, second]

    def test_06_refuse(self):
        reply = self.twin(self.unsealed_retry)[-1]
        self.assertEqual((self.dispatched(reply), self.deltas(reply)),
                         ([], [(DELIVERED, "retry_refused", "failed")]))
        self.assertEqual(self.custody(DELIVERED, 2).state, "abandoned")

    def test_07_reconcile(self):
        # A dead owner's merged attempt, with no capacity left for its remainder (D19).
        reply = self.twin(lambda: [self.spawned(DELIVERED, LIVE), self.sweep(
            5, recorded=BOTH, forge={DELIVERED: MERGED}, max_parallel=1,
            owners=[self.held(issue=DELIVERED)])])[-1]
        self.assertEqual((self.dispatched(reply), self.deltas(reply),
                          [summary["state"] for summary in reply["summaries"]]),
                         ([], [], ["merged", "active"]))
        self.assertEqual(self.records(DELIVERED)[0][0]["result_source"], "superseded")
        held = self.custody(DELIVERED)
        self.assertEqual((held.state, held.custody, held.terminal, self.events(DELIVERED)[-1]),
                         ("created", None, None, "lease_released"))
        journal = self.delivery(DELIVERED)
        self.assertIsNotNone(journal)
        self.assertFalse([entry for entry in journal.evidence
                          if entry["evidence_id"].startswith("delivery_observations:")])

    def test_08_terminal(self):
        def scenario():
            done = self.unsealed_retry()
            self.before = self.tree()
            return [*done, self.sweep(7, recorded=MATCHING)]

        reply = self.twin(scenario)[-1]
        self.assertEqual((self.dispatched(reply), self.deltas(reply), self.tree()),
                         ([], [], self.before))

    def watched(self):
        """A live owner and a sweep with nothing to decide; the tree before that sweep."""
        done = [self.spawned(DELIVERED)]
        self.before = self.tree()
        return [*done, self.sweep(1, recorded=MATCHING)]

    def test_09_idle(self):
        reply = self.twin(self.watched)[-1]
        self.assertEqual((self.dispatched(reply), self.deltas(reply), self.tree()),
                         ([], [], self.before))

    def test_18_wait(self):
        (wait,) = self.twin(self.watched)[-1]["actions"]
        self.assertEqual(
            (wait["kind"], wait["wake_on"], wait["deadline_at"], wait["wait_seconds"]),
            ("wait", ["deadline", "owner_notification", "tracker_change"], at(30), 29 * 60))

    def assert_reaped(self, reply):
        self.assertEqual((self.dispatched(reply), self.deltas(reply)),
                         ([], [(DELIVERED, "expired", "suspended")]))
        held = self.custody(DELIVERED)
        self.assertEqual((held.state, held.custody, self.reason(held), self.events(DELIVERED)[-3:]),
                         ("attention_required", None, "expiry",
                          ["lease_lapse_detected", "stop_synthesized", "transitioned"]))

    def test_10_observe_that_ends_one_resume(self):
        reply = self.twin(lambda: [self.spawned(DELIVERED), self.sweep(
            31, recorded={DELIVERED: "mismatch"})])[-1]
        self.assertIn("worktree_fact",
                      [r["kind"] for r in reply["summaries"][0]["requirements"]])
        self.assert_reaped(reply)

    def test_12_reap_of_an_expired_launch(self):
        late = {DELIVERED: "matching_issue_branch", LIVE: None}
        reply = self.twin(lambda: [
            self.spawned(DELIVERED), self.sweep(10, recorded=late, contracts=True),
            self.sweep(31, recorded=BOTH, max_parallel=1)])[-1]
        self.assert_reaped(reply)

    def test_11_contract(self):
        (reply,) = self.twin(lambda: [self.sweep(0, recorded={DELIVERED: None})])
        self.assertEqual([a["kind"] for a in reply["actions"]], ["delivery_contract"])
        self.assertIn("delivery_contract_required", [
            r.get("reason_code") for r in reply["summaries"][0]["requirements"]])
        digest = self.model.canonical_digest(self.built[DELIVERED]["contract"])
        self.assertEqual((self.custody(DELIVERED), self.transaction(
            ad.delivery_key(DELIVERED, digest, 1))), (None, None))

    def test_13_withheld_for_a_role_set(self):
        (reply,) = self.twin(lambda: [self.spawned(DELIVERED, LIVE)], slots=4)
        self.assertEqual((self.dispatched(reply), reply["admission"]["waiting"]),
                         ([("spawn", FIRST)], [LIVE]))
        self.assertIsNone(self.core().lookup(ac.creation_key(self.run_id(), LIVE, 1)))

    def test_14_withheld_at_max_parallel(self):
        (reply,) = self.twin(lambda: [self.spawned(DELIVERED, LIVE, max_parallel=1)])
        self.assertEqual((self.dispatched(reply), reply["admission"]["waiting"]),
                         ([("spawn", FIRST)], []))
        self.assertIsNone(self.core().lookup(ac.creation_key(self.run_id(), LIVE, 1)))

    def refused(self):
        return [self.spawned(DELIVERED, LIVE),
                self.sweep(1, recorded=BOTH, owners=[self.held("launch_refused")])]

    def test_15_launch_refused(self):
        reply = self.twin(self.refused)[-1]
        self.assertEqual((self.dispatched(reply), reply["admission"]["waiting"]), ([], [LIVE]))
        self.assertEqual(self.records(LIVE)[0][0]["blocked_on"], "host_capacity")
        held = self.custody(LIVE)
        self.assertEqual((held.state, held.custody, self.reason(held)),
                         ("attention_required", None, "suspended:host_capacity"))

    def test_16_gate_opened_by_a_later_release(self):
        reply = self.twin(lambda: [*self.refused(), self.failing(FIRST, 3),
                                   self.sweep(4, recorded=BOTH)])[-1]
        self.assertIn(("resume", f"{LIVE}:1:2"), self.dispatched(reply))
        held = self.custody(LIVE)
        self.assertEqual(
            ([e["reason"] for e in held.events if e["type"] == "transitioned"],
             held.custody.executor_id),
            (["suspended:host_capacity", "capacity_released"], f"{LIVE}:1:2"))

    def test_17_owner_unavailable(self):
        reply = self.twin(lambda: [self.spawned(DELIVERED, LIVE),
                                   self.sweep(5, recorded=BOTH, owners=[self.held()])])[-1]
        self.assertEqual(self.dispatched(reply), [("resume", f"{LIVE}:1:2")])
        released = {claim["holder"]: claim["release_event"]
                    for claim in self.ledger_document()["admission"]["claims"]}
        self.assertEqual(released[SECOND], "owner_unavailable")
        held = self.custody(LIVE)
        reacquired = [e for e in held.events if e["type"] == "lease_reacquired"][-1]
        self.assertEqual((reacquired["reason"], held.custody.executor_id,
                          self.claim_ids(held)[-1:]),
                         ("released", f"{LIVE}:1:2", [f"admission-claim:{LIVE}:1:2:2"]))

    def test_19_finalize(self):
        (reply,) = self.twin(lambda: [self.sweep(0, recorded={DELIVERED: None},
                                                 closed={DELIVERED}, contracts=True)])
        self.assertEqual([a["kind"] for a in reply["actions"]], ["finalize"])
        # The controller's seat has no custody: the run transaction is the store's only one.
        store = self.root / ".superpowers/attempt-transactions"
        self.assertEqual([path.name for path in store.glob("rel_*")], [self.run_id()])
