"""Public recipe compiler against the real builders, validator and delivery engine."""

import copy
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import unittest

from . import test_delivery_workflow as fixtures
from .test_delivery_workflow import (
    ARTIFACT_BUDGET, BuilderHarness, HELD_COMMENT, HELD_RECORD,
    LATER, NOW, POLICY, SOURCES, URL, WORKFLOW,
)


class ShipDeliveryTest(BuilderHarness, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.DeliveryLoopTest.setUpClass()
        cls.model = fixtures.DeliveryLoopTest.model

    def setUp(self):
        self.project()
        built = self.build("contract", self.contract_input())
        self.contract, intent = built["contract"], built["initial_intent"]
        self.digest = self.model.canonical_digest(self.contract)
        owner = self.acquire(self.contract, intent)
        self.custody = owner["custody"]
        self.run_args = ("--repo-root", self.root, "--run-id", owner["run_id"])
        self.state_path = self.root / ".superpowers/workflows" / owner["run_id"] / "state.json"
        self.context_value = fixtures.DeliveryLoopTest.handoff(self, owner, intent)
        self.runtime = self.root / ".agents/runtime"
        self.runtime.mkdir(parents=True)
        self.context = self.runtime / "context.json"
        self.context.write_text(json.dumps(self.context_value))
        bins = self.runtime / "bin"
        bins.mkdir()
        for name, script, extra in (("workflow-state", WORKFLOW, []),
                ("artifact-budget", ARTIFACT_BUDGET, ["--policy", str(POLICY)])):
            wrapper = bins / name
            wrapper.write_text("#!/bin/sh\nexec " + " ".join(map(shlex.quote,
                [sys.executable, str(script)])) + ' "$@" ' + " ".join(map(shlex.quote, extra)) + "\n")
            wrapper.chmod(0o755)
        self.env = {**os.environ, "HOME": str(self.home), "PATH": str(bins) + os.pathsep + os.environ["PATH"]}
        self.counter = 0

    def compile(self, mode, recipe, *, prior=(), context=None, ok=True, raw=None, output=None):
        self.counter += 1
        path = output or self.runtime / f"payload-{self.counter}.json"
        argv = [sys.executable, "-m", "agent_tools.ship_delivery", mode,
                "--context", str(context or self.context), "--output", str(path)]
        for item in prior:
            argv += ["--prior", str(item)]
        before = self.state_path.read_bytes()
        completed = subprocess.run(argv, input=raw if raw is not None else json.dumps(recipe),
            env=self.env, capture_output=True, text=True, check=False, timeout=60)
        self.assertEqual(self.state_path.read_bytes(), before, "compiler changed the ledger")
        if ok:
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(path.read_text(), completed.stdout)
            return json.loads(completed.stdout), path
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(completed.stdout, "")
        return completed

    @staticmethod
    def obs(kind, **facts):
        return {"kind": kind, "source_kind": SOURCES[kind],
                "source_reference": f"probe:{kind}", "evidence": f"{kind} evidence", "facts": facts}

    @staticmethod
    def authority(stage, verdict="allowed"):
        return {"stage_id": stage, "authority_kind": "native_guard", "verdict": verdict,
                "reason_code": "guard_" + verdict, "evidence": "native effect decision"}

    def checkpoint(self, recipe, *, prior=()):
        value, path = self.compile("checkpoint", {"observed_at": NOW, **recipe}, prior=prior)
        response = json.loads(self.cli("checkpoint-delivery", *self.run_args, "--now", LATER,
            "--checkpoint-file", "-", stdin=json.dumps(value).encode()).stdout)
        return response, path

    def selected(self):
        self.checkpoint({"requested_stage": None})
        response, path = self.checkpoint({"requested_stage": "merge_pr", "selections": [{
            "kind": "initial", "head": "a" * 40, "tree": "c" * 40,
            "acceptance_ref": "spec", "review_ref": "clean", "test_ref": "checks",
            "source_kind": "repository", "source_reference": "review:head", "evidence": "review green"}],
            "observations": [self.obs("branch_published", head="a" * 40),
                             self.obs("pr_opened", pr_number=5, pr_url=URL, head="a" * 40)]})
        self.assertEqual(response["pending_stage_ids"][0], "merge_pr")
        return path

    def deliver(self, *, hold=False, remainder=False):
        self.selected()
        if remainder:
            summary, _ = self.compile("summary", {"observed_at": NOW, "state": "terminal_failed",
                "result": {"state": "stopped", "pr_url": URL, "merge_sha": None, "issue_closed": False},
                "notes": "transport interrupted"})
            context = json.loads(self.cli("finish", *self.run_args, "--now", LATER,
                "--summary-file", "-", stdin=json.dumps(summary).encode()).stdout)
            self.assertEqual(context["kind"], "delivery_remainder")
            self.context.write_text(json.dumps(context))
            self.custody = context["custody"]
            self.checkpoint({"requested_stage": None})
        response, merged = self.checkpoint({"requested_stage": "close_tracker",
            "observations": [self.obs("pr_merged", pr_number=5, pr_url=URL,
                                      head="a" * 40, merge_sha="b" * 40)],
            "authority": [self.authority("merge_pr")]})
        self.assertEqual(response["pending_stage_ids"][0], "close_tracker")
        tracker = self.obs("tracker_held", comment_url=HELD_COMMENT, record_path=HELD_RECORD,
            acceptance_state="unmet", observation_identity="github:issue:171:held") if hold else self.obs(
            "tracker_closed", close_reason="completed", observation_identity="github:issue:171:closed")
        # Remote deletion by merge is observation-only. No fake authority is manufactured.
        response, closed = self.checkpoint({"requested_stage": "remove_worktree",
            "observations": [tracker, self.obs("remote_branch_absent")],
            "authority": [self.authority("close_tracker")]})
        self.assertEqual(response["pending_stage_ids"][0], "remove_worktree")
        response, removed = self.checkpoint({"requested_stage": "delete_local_branch",
            "observations": [self.obs("worktree_absent")],
            "authority": [self.authority("remove_worktree")]})
        self.assertEqual(response["pending_stage_ids"], ["delete_local_branch"])
        summary, _ = self.compile("summary", {"observed_at": NOW, "state": "delivery_complete",
            "result": {"state": "merged", "pr_url": URL, "merge_sha": "b" * 40,
                       "issue_closed": not hold},
            "notes": f"held for verification: {HELD_COMMENT}" if hold else "delivered",
            "authority": [self.authority("delete_local_branch")],
            "observations": [self.obs("local_branch_absent"), self.obs("implementation_delivered",
                selection="$selection", merge_sha="b" * 40, integrated_ref="refs/heads/main",
                merge_observation_id="$pr_merged"), self.obs("cleanup_complete",
                remote_branch_observation_ids=["$remote_branch_absent"],
                local_branch_observation_ids=["$local_branch_absent"],
                worktree_observation_ids=["$worktree_absent"],
                detail_pointer="none", read_evidence="no retained findings")]},
            prior=[merged, closed, removed])
        finished = json.loads(self.cli("finish", *self.run_args, "--now", LATER,
            "--summary-file", "-", stdin=json.dumps(summary).encode()).stdout)
        self.assertEqual((finished["kind"], finished["pending_stage_ids"]), ("delivery_complete", []))
        issue = json.loads(self.state_path.read_text())["issues"]["171"]
        if remainder:
            # Delivery completion seals the remainder's custody; it preserves
            # the historical implementation failure and remainder row.
            self.assertEqual(issue["attempts"][-1]["state"], "stopped")
            self.assertTrue(all(item["state"] in {"observed", "not_applicable"}
                                for item in issue["delivery"]["postconditions"].values()))
        else:
            self.assertEqual(issue["attempts"][-1]["state"], "merged")
            self.assertIs(issue["attempts"][-1]["result"]["issue_closed"], not hold)

    def test_complete_delivery_and_hold_use_engine_accepted_payloads(self):
        self.deliver(hold=True)

    def test_close_delivery_uses_engine_accepted_payloads(self):
        self.deliver()

    def test_remainder_context_completes_delivery_through_its_own_finish(self):
        self.deliver(remainder=True)

    def test_denial_with_partial_observation_suspends_at_human_gate(self):
        self.selected()
        response, _ = self.checkpoint({"requested_stage": "merge_pr",
            "observations": [self.obs("branch_published", head="a" * 40)],
            "authority": [self.authority("merge_pr", "rejected")]})
        self.assertEqual((response["state"], response["blocked_on"]), ("suspended", "human_gate"))
        denied = self.compile("checkpoint", {"observed_at": NOW, "requested_stage": "merge_pr"}, ok=False)
        self.assertIn("not current", denied.stderr)

    def test_sync_recipe_extends_the_installed_selection(self):
        self.selected()
        response, path = self.checkpoint({"requested_stage": "merge_pr", "selections": [{
            "kind": "sync", "head": "d" * 40, "tree": "e" * 40,
            "parents": ["a" * 40, "f" * 40], "review_ref": "merge-delta-clean",
            "test_ref": "checks", "source_kind": "repository", "source_reference": "sync:head",
            "evidence": "sync reviewed and checked"}], "observations": [
                self.obs("branch_published", head="d" * 40),
                self.obs("pr_opened", pr_number=5, pr_url=URL, head="d" * 40)]})
        self.assertEqual(response["pending_stage_ids"][0], "merge_pr")
        selection = next(item["subject"]["selected_output"] for item in json.loads(path.read_text())[
            "delivery_observations"] if item["observation_kind"] == "selected_output")
        self.assertEqual((selection["schema_version"], selection["sync"]["first_parent"]), (2, "a" * 40))
        bad = {"observed_at": NOW, "requested_stage": "merge_pr", "selections": [{
            "kind": "sync", "head": "9" * 40, "tree": "8" * 40,
            "parents": ["a" * 40, "7" * 40], "review_ref": "merge-delta-clean", "test_ref": "checks",
            "source_kind": "repository", "source_reference": "sync:wrong", "evidence": "wrong parent"}]}
        self.assertIn("prior selection", self.compile("checkpoint", bad, ok=False).stderr)

    def test_malformed_recipes_and_cross_custody_inputs_fail_without_output(self):
        base = {"observed_at": NOW, "requested_stage": None}
        for value in ({**base, "custody": {}}, {**base, "authority": [{}]},
                      {**base, "observations": [self.obs("pr_merged")]},
                      {**base, "observations": [self.obs("implementation_delivered",
                       selection="$selection", merge_sha="b" * 40, integrated_ref="main",
                       merge_observation_id="$missing")]},
                      {**base, "observations": [self.obs("branch_published", contract={})]}):
            with self.subTest(value=value):
                self.compile("checkpoint", value, ok=False)
        self.compile("checkpoint", None, raw='{"observed_at":NaN,"requested_stage":null}', ok=False)
        self.compile("checkpoint", None, raw='{"requested_stage":null,"requested_stage":null}', ok=False)
        _, prior = self.compile("checkpoint", base)
        modified = json.loads(prior.read_text())
        modified["custody"]["launch"] += 1
        modified["custody"]["action_id"] = "171:1:2"
        prior.write_text(json.dumps(modified))
        self.assertIn("another contract or custody", self.compile("checkpoint", base, prior=[prior], ok=False).stderr)
        _, prior = self.compile("checkpoint", {**base,
            "observations": [self.obs("branch_published", head="a" * 40)]})
        modified = json.loads(prior.read_text())
        observation = modified["delivery_observations"][0]
        observation["contract_digest"] = "sha256:" + "0" * 64
        fixtures.seal(self.model, observation)
        prior.write_text(json.dumps(modified))
        self.assertIn("prior observation belongs to another contract",
                      self.compile("checkpoint", base, prior=[prior], ok=False).stderr)

    def test_stale_context_cannot_checkpoint_but_can_report_truthful_failure(self):
        context = copy.deepcopy(self.context_value)
        context["custody"]["launch"] += 1
        context["custody"]["action_id"] = "171:1:2"
        self.context.write_text(json.dumps(context))
        self.compile("checkpoint", {"observed_at": NOW, "requested_stage": None}, ok=False)
        summary, _ = self.compile("summary", {"observed_at": NOW, "state": "terminal_failed",
            "result": {"state": "stopped", "pr_url": None, "merge_sha": None, "issue_closed": False},
            "notes": "launch superseded"})
        self.assertEqual(summary["historical_owner_result"]["state"], "stopped")

    def test_output_is_exclusive_and_local_references_must_be_unambiguous(self):
        base = {"observed_at": NOW, "requested_stage": None}
        _, existing = self.compile("checkpoint", base)
        original = existing.read_bytes()
        self.compile("checkpoint", base, output=existing, ok=False)
        self.assertEqual(existing.read_bytes(), original)
        recipe = {**base, "observations": [self.obs("remote_branch_absent"), {
            **self.obs("remote_branch_absent"), "evidence": "second evidence"},
            self.obs("cleanup_complete", remote_branch_observation_ids=["$remote_branch_absent"],
                local_branch_observation_ids=[], worktree_observation_ids=[],
                detail_pointer="none", read_evidence="empty")]}
        self.assertIn("expected one observation", self.compile("checkpoint", recipe, ok=False).stderr)
