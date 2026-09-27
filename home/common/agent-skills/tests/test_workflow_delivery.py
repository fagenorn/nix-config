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


class InstalledIntentTest(unittest.TestCase):
    """#193 D5-D7, D12: the builder's own check of an installed intent, behind the facade."""

    NOT_INSTALLED = "; no ledger under the repo root installs this contract"

    @classmethod
    def setUpClass(cls):
        cls.runtime = runpy.run_path(str(ENTRY))["DeliveryRuntime"](
            notes_max_characters=10_000)
        built = cls.runtime.build_delivery("contract", {
            "issue": 193, "worktree": "/repo/.worktrees/worktree-issue-193-legacy",
            "source_kind": "explicit_user", "source_reference": "invocation:/from-issue 193",
            "now": NOW}, policy=resolved_snapshot("/repo"))
        cls.derived, cls.derived_intent = built["contract"], built["initial_intent"]

    def resealed(self, change):
        """The derived intent after `change`, sealed again under a new id."""
        intent = copy.deepcopy(self.derived_intent)
        change(intent)
        return seal(self.runtime.model, intent)

    def legacy(self, intent):
        """A hand-built contract: unsourced provenance kind, recording `intent`."""
        contract = copy.deepcopy(self.derived)
        contract["provenance"]["kind"] = "orchestrate-issues"
        contract["initial_authorization_intent_id"] = intent["id"]
        contract["initial_authorization_intent_digest"] = (
            self.runtime.model.canonical_digest(intent))
        return contract

    def hand_built_intent(self):
        return self.resealed(lambda intent: intent["source"].update(
            reference="orchestrate-issues:orch-193"))

    def tampered(self):
        """A sourced contract whose recorded intent no longer re-derives."""
        contract = copy.deepcopy(self.derived)
        contract["provenance"]["created_at"] = "2026-09-22T00:00:00Z"
        return contract

    def unregenerable(self):
        """A sourced, model-valid contract whose worktree stage is not literal.

        ``_contract_facts`` rejects it, so ``_derivation`` returns the third
        reason through its ``except ValueError`` (per D14).
        """
        contract = copy.deepcopy(self.derived)
        slot = next(stage["target_ref"] for stage in contract["stages"]
                    if stage["target_ref"].get("kind") == "slot")
        for stage in contract["stages"]:
            if stage["kind"] == "remove_worktree":
                stage["target_ref"] = copy.deepcopy(slot)
        return contract

    def build(self, kind, value, installed):
        return self.runtime.build_delivery(kind, value, policy=None,
                                           installed_intent=installed)

    def refusal(self, kind, value, installed):
        with self.assertRaises(ValueError) as caught:
            self.build(kind, value, installed)
        return str(caught.exception)

    def test_only_a_valid_contract_that_does_not_re_derive_needs_an_installed_intent(self):
        invalid = copy.deepcopy(self.derived)
        invalid["issue"] = 0
        malformed = copy.deepcopy(self.derived)
        malformed["stages"][0]["target_ref"] = None
        for label, contract, expected in (
                ("derives", self.derived, False),
                ("hand-built", self.legacy(self.hand_built_intent()), True),
                ("tampered", self.tampered(), True),
                ("model-invalid", invalid, False), ("not an object", "contract", False),
                ("null nested member", malformed, False),
                ("unregenerable", self.unregenerable(), True)):
            with self.subTest(label=label):
                self.assertIs(self.runtime.requires_installed_intent(contract), expected)

    def test_without_an_installed_intent_the_derivation_reason_gains_the_ledger_clause(self):
        for label, contract, reason in (
                ("hand-built", self.legacy(self.hand_built_intent()),
                 "source kind of the contract cannot source an initial intent"),
                ("tampered", self.tampered(),
                 "derived intent does not match the contract's initial intent"),
                ("unregenerable", self.unregenerable(),
                 "derived intent cannot be regenerated: the contract has no "
                 "reviewed slot or worktree stage")):
            with self.subTest(label=label):
                self.assertEqual(self.refusal("initial-intent", {"contract": contract}, None),
                                 reason + self.NOT_INSTALLED)

    def test_a_contract_that_re_derives_ignores_any_installed_intent(self):
        self.assertEqual(self.build("initial-intent", {"contract": self.derived},
                                    self.hand_built_intent()), self.derived_intent)

    def test_the_installed_intent_must_be_the_contracts_valid_root(self):
        intent = self.hand_built_intent()
        successor = self.resealed(
            lambda value: value.update(predecessor_intent_id=intent["id"]))
        self.runtime.validate(successor, "authorization-intent")
        nulled = copy.deepcopy(intent)
        nulled["scopes"][0] = None
        for label, contract, installed in (
                ("another intent", self.legacy(intent), self.derived_intent),
                ("not an intent", self.legacy(intent), {"kind": "authorization-intent"}),
                ("a null nested member", self.legacy(intent), nulled),
                ("a successor", self.legacy(successor), successor)):
            with self.subTest(label=label):
                self.assertEqual(
                    self.refusal("initial-intent", {"contract": contract}, installed),
                    "installed initial intent does not match the contract")
        self.assertEqual(self.build("initial-intent", {"contract": self.legacy(intent)},
                                    intent), intent)

    def test_scope_refuses_a_stage_the_installed_intent_does_not_declare(self):
        action = next(stage["action"] for stage in self.derived["stages"]
                      if stage["id"] == "close_tracker")
        intent = self.resealed(lambda value: value.update(scopes=[
            scope for scope in value["scopes"] if scope["action"] != action]))
        contract = self.legacy(intent)
        self.assertEqual(
            self.refusal("scope", {"contract": contract, "stage_id": "close_tracker"}, intent),
            "the contract's initial intent declares no single scope for stage close_tracker")
        merge = self.build("scope", {"contract": contract, "stage_id": "merge_pr"}, intent)
        self.assertIn(merge, intent["scopes"])

        def twice(value):
            """A second merge scope for another PR: two scopes for one stage."""
            second = copy.deepcopy(next(scope for scope in value["scopes"]
                                        if scope["action"] == merge["action"]))
            second["target"]["pr_ref"] = {"kind": "literal", "value": "6"}
            value["scopes"].append(seal(self.runtime.model, second))
            value["scopes"].sort(key=lambda item: item["id"])

        doubled = self.resealed(twice)
        self.runtime.validate(doubled, "authorization-intent")
        self.assertEqual(
            self.refusal("scope", {"contract": self.legacy(doubled), "stage_id": "merge_pr"},
                         doubled),
            "the contract's initial intent declares no single scope for stage merge_pr")


LEGACY = "/repo/.worktrees/worktree-issue-154"
LIVE = "worktree-issue-154-shell-checker-examples"


def sealed_members(snapshot):
    """The seven policy members a contract seals, keyed as its provenance digest keys them."""
    vcs, tracker = snapshot["bindings"]["vcs"], snapshot["bindings"]["tracker"]
    return {"project_id": snapshot["project"]["id"], "tracker_kind": tracker["kind"],
            "repository_slug": tracker["repo_slug"], "branch_pattern": vcs["branch_pattern"],
            "worktree_prefix": vcs["worktree"]["prefix"],
            "integration_branch": vcs["integration_branch"],
            "delete_branch": vcs["merge"]["delete_branch"]}


class WorktreeBranchTest(unittest.TestCase):
    """#192 D2-D4, D19: a live branch names the contract only where the path cannot."""

    SOURCE = {"kind": "explicit_user", "reference": "invocation:/from-issue 154 --auto"}

    @classmethod
    def setUpClass(cls):
        cls.runtime = runpy.run_path(str(ENTRY))["DeliveryRuntime"](
            notes_max_characters=10_000)
        cls.policy = resolved_snapshot("/repo")

    def value(self, worktree=LEGACY, **changes):
        return {"issue": 154, "worktree": worktree, "source_kind": self.SOURCE["kind"],
                "source_reference": self.SOURCE["reference"], "now": NOW, **changes}

    def build(self, value, worktree_branch=None):
        return self.runtime.build_delivery("contract", value, policy=self.policy,
                                           worktree_branch=worktree_branch)

    def refusal(self, value, worktree_branch=None):
        with self.assertRaises(ValueError) as caught:
            self.build(value, worktree_branch)
        return str(caught.exception)

    def digest(self, worktree, **branch):
        return self.runtime.model.canonical_digest({
            "policy": sealed_members(self.policy), "issue": 154, "worktree": worktree,
            "source": self.SOURCE, **branch})

    def test_only_a_well_formed_unpatterned_input_requires_a_worktree_branch(self):
        gitlab = copy.deepcopy(self.policy)
        gitlab["bindings"]["tracker"]["kind"] = "gitlab"
        unslugged = copy.deepcopy(self.policy)
        del unslugged["bindings"]["tracker"]["repo_slug"]
        for label, value, policy, expected in (
                ("slugless", self.value(), self.policy, True),
                ("another issue's branch",
                 self.value("/repo/.worktrees/worktree-issue-155-other"), self.policy, True),
                ("patterned", self.value(f"/repo/.worktrees/{LIVE}"), self.policy, False),
                ("patterned without the prefix",
                 self.value("/repo/.worktrees/issue-154-shell"), self.policy, False),
                ("relative", self.value(".worktrees/worktree-issue-154"), self.policy, False),
                ("unnormalized", self.value("/repo/.worktrees/../worktree-issue-154"),
                 self.policy, False),
                ("unknown key", self.value(extra=True), self.policy, False),
                ("unsourced kind", self.value(source_kind="parent_handoff"), self.policy,
                 False),
                ("bad clock", self.value(now="today"), self.policy, False),
                ("not an object", "contract", self.policy, False),
                ("no policy", self.value(), None, False),
                ("non-github tracker", self.value(), gitlab, False),
                ("missing sealed member", self.value(), unslugged, False)):
            with self.subTest(label=label):
                self.assertIs(self.runtime.requires_worktree_branch(value, policy), expected)

    def test_a_live_branch_names_the_contract_and_enters_its_provenance(self):
        built = self.build(self.value(), LIVE)
        contract = built["contract"]
        literals = {stage["id"]: stage["target_ref"].get("value")
                    for stage in contract["stages"]}
        self.assertEqual({stage["target_ref"]["constraints"]["branch"]
                          for stage in contract["stages"]
                          if stage["target_ref"]["kind"] == "slot"}, {LIVE})
        self.assertEqual((literals["delete_remote_branch"], literals["delete_local_branch"],
                          literals["remove_worktree"]), (LIVE, LIVE, LEGACY))
        self.assertEqual(contract["provenance"]["digest"], self.digest(LEGACY, branch=LIVE))
        # Re-derivation reads the branch from the contract, never from the path.
        self.assertEqual(self.runtime.build_delivery(
            "initial-intent", {"contract": contract}, policy=None), built["initial_intent"])

    def test_a_patterned_name_wins_and_ignores_the_worktree_branch(self):
        patterned = self.value(f"/repo/.worktrees/{LIVE}")
        plain = self.build(patterned)
        self.assertEqual(
            self.runtime.model.canonical_bytes(
                self.build(patterned, "worktree-issue-154-elsewhere")),
            self.runtime.model.canonical_bytes(plain))
        self.assertEqual(plain["contract"]["provenance"]["digest"],
                         self.digest(f"/repo/.worktrees/{LIVE}"))

    def test_refusals_keep_the_pattern_prefix_and_name_their_reason(self):
        prefix = "worktree name 'worktree-issue-154' does not match the issue branch pattern"
        self.assertEqual(self.refusal(self.value()), prefix)
        for branch in ("feature-x", "worktree-issue-155-other"):
            with self.subTest(branch=branch):
                self.assertEqual(
                    self.refusal(self.value(), branch),
                    f"{prefix}, and its checked-out branch {branch!r} does not match either")
        self.assertEqual(self.runtime.worktree_pattern_refusal(LEGACY), prefix)
        self.assertEqual(
            self.runtime.worktree_pattern_refusal(LEGACY, "the worktree is absent"),
            prefix + ", and the worktree is absent")

if __name__ == "__main__":
    unittest.main()
