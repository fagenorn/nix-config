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

ENTRY = Path(__file__).parents[1] / "scripts" / "workflow_delivery.py"
NOW = "2026-09-21T00:00:00Z"
WORKTREE = "/worktree"


def direct_policy(runtime, issue, request):
    return runtime.delivery_policy(
        issue, issue=151, request=request, source_kind="direct",
        now="2026-09-21T00:01:00Z", dispatch_permitted=True,
        remainder_deadline="2026-09-21T03:01:00Z", owner_unavailable=False,
        tracker_halted=False,
        recorded_worktree={"path": WORKTREE, "state": "matching_issue_branch"})


def resolved_snapshot(root):
    """A resolver-shaped snapshot rooted at `root` with this repo's authored policy.

    The resolver makes only `paths` members and command `cwd`s absolute under
    `root`, so snapshots from two roots differ only in path-shaped members.
    """
    return {
        "schema_version": 1,
        "project": {"id": "fagenorn/nix-config", "name": "nix-config", "root": root},
        "bindings": {
            "vcs": {"kind": "git", "default_branch": "main", "integration_branch": "main",
                    "branch_pattern": "issue-<num>-<slug>",
                    "worktree": {"root": ".worktrees", "prefix": "worktree-"},
                    "commit": {"co_authored_by": True, "signed": True},
                    "merge": {"strategy": "merge", "delete_branch": True}},
            "tracker": {"kind": "github", "cli": "gh", "repo_slug": "fagenorn/nix-config",
                        "credential_env": {"unset_before_invocation": []}},
            "paths": {"artifacts": {"plans": f"{root}/.claude/plans",
                                    "specs": f"{root}/.claude/specs"},
                      "architecture": [f"{root}/CLAUDE.md"]},
            "workflow": {"orchestration": {"max_parallel": 2, "attempt_budget_minutes": 180}},
        },
        "capabilities": {},
    }


class WorkflowDeliveryRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = runpy.run_path(str(ENTRY))["DeliveryRuntime"](
            notes_max_characters=10_000)

    def test_remainder_reentry_uses_ready_stage_worktree_requirement(self):
        runtime = self.runtime
        _, delivery = cleanup_contract_and_delivery(runtime.model)
        common = dict(
            now="2026-09-21T00:01:00Z", owner_unavailable=False,
            dispatch_permitted=True, remainder_deadline="2026-09-21T03:01:00Z")
        cases = (("close", None),
                 ("worktree", {"path": WORKTREE, "state": "absent"}))
        for stage, recorded in cases:
            result = runtime.remainder_policy(
                suspended_remainder(delivery), tracker_halted=True,
                recorded_worktree=recorded, preview={"next_stage_id": stage}, **common)
            self.assertEqual((result["operation"], result["attempt"]["state"],
                len(result["attempt"]["launches"])), ("resume", "active", 2))

        for prior, stalls, expiry_event in (
                ("active", 2, True), ("suspended", 1, False)):
            state = suspended_remainder(delivery)
            record = state["delivery_remainders"][0]
            record.update(state=prior, deadline_at="2026-09-21T00:00:30Z",
                          suspend_phase=1, stalled_resumes=1)
            result = runtime.remainder_policy(
                state, tracker_halted=True, recorded_worktree=None,
                preview={"next_stage_id": "close"}, **common)
            self.assertEqual(
                (result["operation"], result["expired"], record["state"],
                 record["stalled_resumes"], record["deadline_at"]),
                ("resume", expiry_event, "active", stalls,
                 common["remainder_deadline"]))

        state = suspended_remainder(delivery)
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            runtime.remainder_policy(
                state, tracker_halted=False,
                recorded_worktree={"path": WORKTREE, "state": "mismatch"},
                preview={"next_stage_id": "worktree"}, **common)
        self.assertEqual(state, before)

    def test_resume_preview_never_replaces_current_custody_reduction(self):
        runtime = self.runtime
        contract, delivery, _ = contract_and_delivery_for_stage(
            runtime.model, "select")
        chosen = selection(runtime.model, delivery["contract_digest"])
        fact = observation(runtime.model, contract, "selected_output",
                           {"selected_output": chosen})
        issue = suspended_remainder(delivery)
        request = direct_delivery_request(contract, [fact])
        policy = direct_policy(runtime, issue, request)
        self.assertIsNone(policy["reduction"])
        self.assertEqual(issue["delivery"]["delivery_observations"], [])
        changed, response = runtime.complete_direct_policy(
            {"issues": {"151": issue}, "updated_at": NOW}, issue=151,
            request=request, policy=policy, ledger_repo_root="/repo",
            run_id="direct-151-000001", reentry="resume")
        self.assertEqual(
            (changed, response["custody"]["action_id"],
             response["pending_stage_ids"][0],
             issue["delivery"]["selected_outputs"]),
            (True, "151:r1:2", "publish", [chosen]))

    def test_cleanup_facts_bind_exact_recorded_worktree(self):
        runtime = self.runtime
        contract, delivery = cleanup_contract_and_delivery(runtime.model)
        worktree = "/owned/worktree"
        next(stage for stage in contract["stages"]
             if stage["kind"] == "remove_worktree")["target_ref"]["value"] = worktree
        delivery = rebind_contract(runtime.model, contract, delivery)
        issue = issue_with_attempt(delivery, worktree=worktree)
        report = {
            "custody": custody(),
            "contract_digest": runtime.model.canonical_digest(contract),
            "authority_observations": [], "reevaluation_evidence": [],
            "requested_scope": None}

        def absent(path, identity):
            return observation(runtime.model, contract, "worktree_absent", {
                "path": path, "recorded_worktree_identity": identity,
                "probe_mode": "no_follow", "absent": True})

        def apply(candidate, source, facts, scope=None):
            if source == "checkpoint":
                return runtime.prepare_report_transition(
                    candidate, {**report, "delivery_observations": facts},
                    source_kind=source, at_time=NOW)
            request = direct_delivery_request(contract, facts, scope)
            if source == "control":
                request = control_delivery_request(request)
            return runtime.apply_transition(
                candidate, issue=151, request=request,
                source_kind=source, at_time=NOW)

        mismatches = (("direct", "/foreign", "/foreign"),
            ("control", worktree, "foreign-identity"),
            ("checkpoint", "/foreign", "/foreign"))
        for source, path, identity in mismatches:
            candidate = copy.deepcopy(issue)
            with self.subTest(source=source), self.assertRaises(ValueError):
                apply(candidate, source, [absent(path, identity)])
            self.assertEqual(candidate, issue)
        for source in ("direct", "control", "checkpoint"):
            apply(copy.deepcopy(issue), source, [absent(worktree, worktree)])
        wrong = stage_scope(runtime.model, contract, "worktree")
        wrong["endpoint"]["value"] = "/foreign"
        seal(runtime.model, wrong)
        candidate = copy.deepcopy(issue)
        with self.assertRaises(ValueError):
            apply(candidate, "direct", [], wrong)
        self.assertEqual(candidate, issue)


class WorktreePolicyCheckTest(unittest.TestCase):
    """D4, D9: the pure sealed-policy comparison behind the worktree cross-check."""

    @classmethod
    def setUpClass(cls):
        cls.runtime = runpy.run_path(str(ENTRY))["DeliveryRuntime"](
            notes_max_characters=10_000)

    def refusal(self, worktree_policy):
        with self.assertRaises(ValueError) as caught:
            self.runtime.check_worktree_policy(resolved_snapshot("/repo"), worktree_policy)
        return str(caught.exception)

    def test_equal_sealed_members_pass_whatever_the_root_and_unsealed_policy(self):
        worktree = resolved_snapshot("/repo/.worktrees/worktree-issue-181-x")
        worktree["bindings"]["workflow"]["orchestration"]["max_parallel"] = 5
        self.assertIsNone(
            self.runtime.check_worktree_policy(resolved_snapshot("/repo"), worktree))

    def test_differing_members_are_named_in_table_order(self):
        worktree = resolved_snapshot("/wt")
        worktree["bindings"]["vcs"]["merge"]["delete_branch"] = False
        worktree["bindings"]["vcs"]["integration_branch"] = "dev"
        self.assertEqual(self.refusal(worktree),
                         "worktree policy differs from repo-root policy: "
                         "bindings.vcs.integration_branch, bindings.vcs.merge.delete_branch")

    def test_a_missing_or_mistyped_worktree_member_refuses_with_the_worktree_prefix(self):
        missing = resolved_snapshot("/wt")
        del missing["bindings"]["tracker"]["repo_slug"]
        mistyped = resolved_snapshot("/wt")
        mistyped["bindings"]["vcs"]["merge"]["delete_branch"] = "true"
        for worktree, message in (
                (missing, "worktree policy member missing: bindings.tracker.repo_slug"),
                (mistyped, "worktree policy member mistyped: bindings.vcs.merge.delete_branch")):
            with self.subTest(message=message):
                self.assertEqual(self.refusal(worktree), message)


if __name__ == "__main__":
    unittest.main()
