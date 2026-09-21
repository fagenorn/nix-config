from __future__ import annotations

import copy
from pathlib import Path
import runpy
import unittest

from ._delivery_model_fixtures import (
    cleanup_contract_and_delivery, contract_and_delivery_for_stage,
    control_delivery_request, custody, direct_delivery_request,
    issue_with_attempt, observation, rebind_contract, seal, selection,
    stage_scope, suspended_remainder,
)

SCRIPTS = Path(__file__).parents[1] / "scripts"
ENTRY = SCRIPTS / "workflow_delivery.py"
NOW = "2026-09-21T00:00:00Z"


def runtime():
    return runpy.run_path(str(ENTRY))["DeliveryRuntime"](
        notes_max_characters=10_000)


def direct_policy(active, issue, request):
    return active.delivery_policy(issue, issue=151, request=request,
        source_kind="direct", now="2026-09-21T00:01:00Z",
        dispatch_permitted=True, remainder_deadline="2026-09-21T03:01:00Z",
        owner_unavailable=False, tracker_halted=False,
        recorded_worktree={"path": "/worktree", "state": "matching_issue_branch"})


class WorkflowDeliveryRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.active = runtime()

    def test_remainder_reentry_uses_ready_stage_worktree_requirement(self):
        active = self.active
        _, delivery = cleanup_contract_and_delivery(active.model)
        common = {"now": "2026-09-21T00:01:00Z", "owner_unavailable": False,
            "dispatch_permitted": True,
            "remainder_deadline": "2026-09-21T03:01:00Z"}
        for stage, recorded in (("close", None),
                ("worktree", {"path": "/worktree", "state": "absent"})):
            result = active.remainder_policy(suspended_remainder(delivery),
                tracker_halted=True, recorded_worktree=recorded,
                preview={"next_stage_id": stage}, **common)
            self.assertEqual((result["operation"], result["attempt"]["state"],
                len(result["attempt"]["launches"])), ("resume", "active", 2))
        for prior_state, expected_stalls, expiry_event in (
                ("active", 2, True), ("suspended", 1, False)):
            state = suspended_remainder(delivery); record = state["delivery_remainders"][0]
            record.update(state=prior_state, deadline_at="2026-09-21T00:00:30Z",
                          suspend_phase=1, stalled_resumes=1)
            result = active.remainder_policy(state, tracker_halted=True,
                recorded_worktree=None, preview={"next_stage_id": "close"}, **common)
            self.assertEqual((result["operation"], result["expired"],
                record["state"], record["stalled_resumes"], record["deadline_at"]),
                ("resume", expiry_event, "active", expected_stalls,
                 common["remainder_deadline"]))
        state = suspended_remainder(delivery); before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            active.remainder_policy(state, tracker_halted=False,
                recorded_worktree={"path": "/worktree", "state": "mismatch"},
                preview={"next_stage_id": "worktree"}, **common)
        self.assertEqual(state, before)

    def test_public_historical_merge_folds_facts_before_terminal_replay(self):
        active = self.active
        contract, delivery, _ = contract_and_delivery_for_stage(active.model, "select")
        forge = {"state": "merged", "url": "https://example.test/pull/17",
                 "merge_sha": "a" * 40}
        request = direct_delivery_request(
            contract, intents=delivery["authorization_intents"])
        request["forge"] = forge
        for retained in (delivery, active.empty_delivery()):
            issue = issue_with_attempt(retained, state="merged")
            result = {"state": "merged", "pr_url": forge["url"],
                      "merge_sha": forge["merge_sha"]}
            issue["attempts"][0]["result"] = result
            issue["outcome"] = copy.deepcopy(result)
            self.assertTrue(active.historical_direct_requested(issue, request))
            self.assertFalse(active.historical_direct_requested(
                issue, {**request, "new_run": True}))
            self.assertFalse(active.historical_direct_requested(
                issue, {**request, "forge": {**forge, "merge_sha": "b" * 40}}))
            policy = direct_policy(active, issue, request)
            self.assertEqual((policy["operation"], issue["attempts"][0]["state"],
                issue["delivery_remainders"][0]["owner"],
                policy["reduction"]["pending_stage_ids"][0]),
                ("resume", "merged", "151:r1", "select"))

    def test_resume_preview_never_replaces_current_custody_reduction(self):
        active = self.active
        contract, delivery, _ = contract_and_delivery_for_stage(active.model, "select")
        chosen = selection(active.model, delivery["contract_digest"])
        fact = observation(active.model, contract, "selected_output",
                           {"selected_output": chosen})
        issue = suspended_remainder(delivery)
        request = direct_delivery_request(contract, [fact])
        policy = direct_policy(active, issue, request)
        self.assertIsNone(policy["reduction"])
        self.assertEqual(issue["delivery"]["delivery_observations"], [])
        state = {"issues": {"151": issue}, "updated_at": NOW}
        changed, response = active.complete_direct_policy(
            state, issue=151, request=request, policy=policy,
            ledger_repo_root="/repo", run_id="direct-151-000001", reentry="resume")
        self.assertTrue(changed)
        self.assertEqual((response["custody"]["action_id"],
                          response["pending_stage_ids"][0]),
                         ("151:r1:2", "publish"))
        self.assertEqual(issue["delivery"]["selected_outputs"], [chosen])

    def test_cleanup_facts_bind_exact_recorded_worktree(self):
        active = self.active
        contract, delivery = cleanup_contract_and_delivery(active.model)
        worktree = "/owned/worktree"
        next(s for s in contract["stages"] if s["kind"] == "remove_worktree" \
            )["target_ref"]["value"] = worktree
        delivery = rebind_contract(active.model, contract, delivery)
        issue = issue_with_attempt(delivery, worktree=worktree)
        report = {"custody": custody(),
            "contract_digest": active.model.canonical_digest(contract),
            "authority_observations": [], "reevaluation_evidence": [],
            "requested_scope": None}

        def absent(path, identity):
            return observation(active.model, contract, "worktree_absent", {
                "path": path, "recorded_worktree_identity": identity,
                "probe_mode": "no_follow", "absent": True})

        def apply(candidate, source, facts, scope=None):
            if source == "checkpoint":
                return active.prepare_report_transition(candidate, {
                    **report, "delivery_observations": facts}, source_kind=source,
                    at_time=NOW)
            request = direct_delivery_request(contract, facts, scope)
            if source == "control":
                request = control_delivery_request(request)
            return active.apply_transition(candidate, issue=151, request=request,
                source_kind=source, at_time=NOW)

        for source, path, identity in (
                ("direct", "/foreign", "/foreign"),
                ("control", worktree, "foreign-identity"),
                ("checkpoint", "/foreign", "/foreign")):
            candidate = copy.deepcopy(issue)
            with self.subTest(source=source), self.assertRaises(ValueError):
                apply(candidate, source, [absent(path, identity)])
            self.assertEqual(candidate, issue)
        for source in ("direct", "control", "checkpoint"):
            apply(copy.deepcopy(issue), source, [absent(worktree, worktree)])
        wrong = stage_scope(active.model, contract, "worktree")
        wrong["endpoint"]["value"] = "/foreign"; seal(active.model, wrong)
        candidate = copy.deepcopy(issue)
        with self.assertRaises(ValueError):
            apply(candidate, "direct", [], wrong)
        self.assertEqual(candidate, issue)


if __name__ == "__main__":
    unittest.main()
