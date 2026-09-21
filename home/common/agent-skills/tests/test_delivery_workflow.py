from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from ._delivery_model_fixtures import (
    authority, contract_and_delivery, contract_and_delivery_for_stage,
    observation, pr_subject, seal, selection, stage_scope,
)


ROOT = Path(__file__).parents[4]
SCRIPTS = ROOT / "home/common/agent-skills/scripts"
WORKFLOW = SCRIPTS / "workflow-state.py"
MODEL = SCRIPTS / "delivery_model/__init__.py"
POLICY = ROOT / "home/common/agent-skills/artifact-budget-policy.json"
NOW = "2026-09-21T00:00:00Z"


def load(path, name, *, package=False):
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[str(path.parent)] if package else None)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class DeliveryAdmissionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = load(WORKFLOW, "workflow_state_admission")
        cls.model = load(MODEL, "delivery_model_admission", package=True)

    def control_request(self, contract=None):
        empty = {"151": []}; scope = {"151": None}
        return {"interface_version": 2, "now": NOW, "max_parallel": 1,
            "attempt_budget_minutes": 30, "human_directed": False,
            "issues": [151], "tracker": [], "owners": [], "worktrees": [],
            "forge": {"151": {"state": "none", "url": None, "merge_sha": None}},
            "delivery_contracts": {"151": contract},
            "authorization_intents": copy.deepcopy(empty),
            "authority_observations": copy.deepcopy(empty),
            "reevaluation_evidence": copy.deepcopy(empty),
            "delivery_observations": copy.deepcopy(empty),
            "requested_scopes": scope}

    def direct_request(self, contract=None):
        return {"interface_version": 2, "issue": 151, "now": NOW,
            "attempt_budget_minutes": 30, "new_run": False,
            "owner_unavailable": False, "tracker": None, "worktree": None,
            "forge": None, "delivery_contract": contract,
            "authorization_intents": [], "authority_observations": [],
            "reevaluation_evidence": [], "delivery_observations": [],
            "requested_scope": None}

    def all_stage_contract(self):
        contract, delivery = contract_and_delivery(self.model)
        intent = copy.deepcopy(delivery["authorization_intents"][0])
        intent["scopes"] = sorted(
            [stage_scope(self.model, contract, stage["id"])
             for stage in contract["stages"]], key=lambda item: item["id"])
        seal(self.model, intent)
        contract["initial_authorization_intent_id"] = intent["id"]
        contract["initial_authorization_intent_digest"] = self.model.canonical_digest(intent)
        return contract, intent

    @staticmethod
    def report_common(custody_value, digest):
        return {"interface_version": 2, "issue": 151, "custody": custody_value,
            "contract_digest": digest, "delivery_observations": [],
            "authority_observations": [], "reevaluation_evidence": [],
            "requested_scope": None, "detail_state": "none",
            "report_path": None, "notes": ""}

    def state_with_attempt(self):
        state = self.workflow.new_run_state(run_id="admission", now=NOW, issues={})
        attempt = self.workflow.new_control_attempt(
            issue=151, attempt_number=1, worktree="/worktree", now=NOW,
            deadline_at="2026-09-21T01:00:00Z")
        state["issues"]["151"] = {"issue": 151, "attempts": [attempt],
            "outcome": None, "delivery": self.workflow._empty_delivery(),
            "delivery_remainders": []}
        return state

    def legacy(self, version):
        value = self.state_with_attempt()
        value["schema_version"] = version
        for issue in value["issues"].values():
            issue.pop("delivery"); issue.pop("delivery_remainders")
        if version == 1:
            value.pop("prior_run")
            for attempt in value["issues"]["151"]["attempts"]:
                for field in self.workflow.SUSPENSION_DEFAULTS: attempt.pop(field)
        self.workflow.validate_legacy_state(value, run_id="admission")
        return value

    def test_interface_two_maps_and_singular_inputs_are_closed(self):
        request, context = self.workflow.validate_control_request(
            self.control_request(), model=self.model)
        self.assertEqual(context, {151: None}); self.assertEqual(request["interface_version"], 2)
        direct, direct_context = self.workflow.validate_direct_owner_request(
            self.direct_request(), model=self.model)
        self.assertEqual(direct_context, {151: None}); self.assertEqual(direct["interface_version"], 2)
        for variant in ("missing", "extra", "noncanonical", "legacy", "null_facts"):
            bad = self.control_request()
            if variant == "missing": bad.pop("requested_scopes")
            elif variant == "extra": bad["requested_scopes"]["152"] = None
            elif variant == "noncanonical": bad["requested_scopes"] = {"0151": None}
            elif variant == "legacy": bad["interface_version"] = 1
            else: bad["delivery_observations"]["151"] = [{"kind": "delivery-observation"}]
            with self.subTest(variant=variant), self.assertRaises(self.workflow.WorkflowError):
                self.workflow.validate_control_request(bad, model=self.model)
        contract, delivery = contract_and_delivery(self.model)
        valid_intent = delivery["authorization_intents"][0]
        for field, value in (("authorization_intents", [valid_intent]),
                             ("requested_scope", stage_scope(self.model, contract, "select"))):
            bad = self.direct_request(); bad[field] = value
            with self.subTest(null_contract_field=field), self.assertRaises(self.workflow.WorkflowError):
                self.workflow.validate_direct_owner_request(bad, model=self.model)
        bad = self.direct_request(contract)
        bad["authorization_intents"] = [valid_intent, valid_intent]
        with self.assertRaises(self.workflow.WorkflowError):
            self.workflow.validate_direct_owner_request(bad, model=self.model)
        bad = self.direct_request(contract); bad["issue"] = 152
        with self.assertRaises(self.workflow.WorkflowError):
            self.workflow.validate_direct_owner_request(bad, model=self.model)
        original = self.direct_request(contract); before = copy.deepcopy(original)
        detached, context = self.workflow.validate_direct_owner_request(
            original, model=self.model)
        self.assertEqual(original, before)
        detached["delivery_contract"]["issue"] = 999
        self.assertEqual(original, before)
        context[151]["issue"] = 998
        self.assertEqual(detached["delivery_contract"]["issue"], 999)

    def test_contractless_public_outputs_are_requirement_only(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
            def run(*args):
                return subprocess.run([sys.executable, str(WORKFLOW), *map(str, args)],
                    capture_output=True, text=True, env=env, check=False)
            initialized = run("init-run", "--repo-root", root, "--run-id", "admission",
                              "--now", NOW)
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            direct_path = root / "direct.json"
            direct_path.write_text(json.dumps(self.direct_request()))
            direct = run("direct-owner", "--repo-root", root,
                         "--request-file", direct_path)
            self.assertEqual(direct.returncode, 0, direct.stderr)
            self.assertEqual(json.loads(direct.stdout), {"interface_version": 2,
                "kind": "observe", "issue": 151, "run_id": None,
                "requirements": [{"kind": "delivery_contract", "subject_id": "151",
                    "reason_code": "delivery_contract_required", "detail_pointer": None}]})
            control_path = root / "control.json"
            control_path.write_text(json.dumps(self.control_request()))
            control = run("control", "--repo-root", root, "--run-id", "admission",
                          "--request-file", control_path)
            self.assertEqual(control.returncode, 0, control.stderr)
            response = json.loads(control.stdout); summary = response["summaries"][0]
            self.assertEqual((summary["custody"], summary["contract_digest"],
                              summary["pending_stage_ids"]), (None, None, []))
            self.assertEqual(summary["requirements"][0]["kind"], "delivery_contract")
            self.assertFalse(any(item["kind"] in {"spawn", "resume", "retry",
                                                   "delivery_remainder"}
                                 for item in response["actions"]))

    def test_adjacent_migration_is_detached_and_writes_only_schema_three(self):
        contract, _ = contract_and_delivery(self.model)
        for version in (1, 2):
            legacy = self.legacy(version); original = copy.deepcopy(legacy)
            migrated = self.workflow.upgrade_state(
                legacy, run_id="admission", migration_contracts={151: contract})
            self.assertEqual(legacy, original); self.assertEqual(migrated["schema_version"], 3)
            self.assertEqual(migrated["issues"]["151"]["delivery"],
                             self.workflow._empty_delivery())
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); run = root / ".superpowers/workflows/admission"
            run.mkdir(parents=True)
            (run / "state.json").write_text(json.dumps(self.legacy(2)))
            with mock.patch.object(self.workflow, "atomic_write_state",
                                   wraps=self.workflow.atomic_write_state) as write:
                result = self.workflow.transact(
                    str(root), "admission", lambda state: (state, False),
                    migration_contracts={151: contract})
            write.assert_called_once()
            self.assertEqual(write.call_args.args[2]["schema_version"], 3)
            self.assertEqual(result["schema_version"], 3)

    def test_model_owns_nonempty_delivery_validation(self):
        contract, delivery = contract_and_delivery(self.model)
        state = self.state_with_attempt(); state["issues"]["151"]["delivery"] = delivery
        self.assertEqual(self.workflow.validate_state(state, run_id="admission"), state)
        bad = copy.deepcopy(state)
        bad["issues"]["151"]["delivery"]["authorization_chain_digest"] = "sha256:" + "f" * 64
        with self.assertRaises(self.workflow.WorkflowError):
            self.workflow.validate_state(bad, run_id="admission")
        absent = self.state_with_attempt()
        absent["issues"]["151"]["delivery"]["contract_digest"] = "sha256:" + "a" * 64
        with self.assertRaises(self.workflow.WorkflowError):
            self.workflow.validate_state(absent, run_id="admission")

    def test_bootstrap_uses_exact_custody_and_remainder_precedence(self):
        state = self.state_with_attempt()
        boot = self.workflow.bootstrap_response(state)
        self.assertEqual(boot["kind"], "workflow_bootstrap")
        self.assertEqual(boot["requirements"][0]["custody"]["action_id"], "151:1:1")
        contract, delivery = contract_and_delivery(self.model)
        attempt = state["issues"]["151"]["attempts"][0]
        self.workflow.stop_attempt(attempt, reason="owner failed", now=NOW, source="owner")
        state["issues"]["151"]["outcome"] = copy.deepcopy(attempt["result"])
        state["issues"]["151"]["delivery"] = delivery
        state["issues"]["151"]["delivery_remainders"] = [{
            "remainder": 1, "contract_digest": self.model.canonical_digest(contract),
            "source_attempt": 1, "prior_remainder": None,
            "pending_stage_ids": [stage["id"] for stage in contract["stages"]],
            "owner": "151:r1", "worktree": "/worktree", "state": "active",
            "launches": [{"kind": "fresh", "owner": "151:r1",
                          "worktree": "/worktree", "at": NOW}],
            "deadline_at": "2026-09-21T01:00:00Z", "progress_token": "initial",
            "blocked_on": None, "suspend_phase": None, "stalled_resumes": 0,
            "result": None, "result_source": None}]
        state["updated_at"] = NOW
        self.workflow.validate_state(state, run_id="admission")
        requirement = self.workflow.bootstrap_response(state)["requirements"][0]
        self.assertEqual(requirement["custody"]["action_id"], "151:r1:1")
        self.assertEqual(set(requirement), {"issue", "owner", "custody", "recorded_worktree"})
        terminal_result = copy.deepcopy(attempt["result"])
        mutations = {}
        both_active = copy.deepcopy(state)
        both_active["issues"]["151"]["attempts"][0].update(
            state="active", result=None, finished_at=None, result_source=None)
        both_active["issues"]["151"]["outcome"] = None
        mutations["ambiguous custody"] = both_active
        for name, mutate in (
            ("unknown pending", lambda item: item.update(pending_stage_ids=["unknown"])),
            ("pending order", lambda item: item.update(pending_stage_ids=["publish", "select"])),
            ("launch kind", lambda item: item["launches"][0].update(kind="spawn")),
            ("launch time", lambda item: item["launches"][0].update(at="2026-09-21T02:00:00Z")),
            ("counter", lambda item: item.update(stalled_resumes=4)),
            ("active result", lambda item: item.update(result=terminal_result, result_source="owner")),
            ("active blocked", lambda item: item.update(blocked_on="external")),
        ):
            candidate = copy.deepcopy(state); mutate(candidate["issues"]["151"]["delivery_remainders"][0])
            mutations[name] = candidate
        for name, candidate in mutations.items():
            with self.subTest(invalid_remainder=name), self.assertRaises(self.workflow.WorkflowError):
                self.workflow.validate_state(candidate, run_id="admission")
        for malformed in (None, {}, False):
            candidate = self.state_with_attempt()
            candidate["issues"]["151"]["delivery_remainders"] = malformed
            with self.subTest(absent_remainders=malformed), self.assertRaises(self.workflow.WorkflowError):
                self.workflow.validate_state(candidate, run_id="admission")

    def test_public_source_and_installed_admission_fail_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for layout in ("source", "installed"):
                base = root / layout; home = base / "home"; repo = base / "repo"
                home.mkdir(parents=True); repo.mkdir()
                env = {**os.environ, "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}
                store = base / ("toolchain/scripts" if layout == "source" else "store")
                store.mkdir(parents=True)
                shutil.copy2(WORKFLOW, store / "workflow-state.py")
                shutil.copy2(SCRIPTS / "workflow_delivery.py", store / "workflow_delivery.py")
                shutil.copy2(SCRIPTS / "artifact_budget.py", store / "artifact_budget.py")
                shutil.copy2(SCRIPTS / "artifact-budget", store / "artifact-budget")
                shutil.copy2(POLICY, store / "artifact-budget-policy.json")
                if layout == "source":
                    shutil.copy2(POLICY, store.parent / "artifact-budget-policy.json")
                shutil.copytree(MODEL.parent, store / "delivery_model")
                if layout == "source":
                    cli = store / "workflow-state.py"
                else:
                    binary = home / ".agents/bin"; library = home / ".agents/lib/python"
                    share = home / ".agents/share"
                    for directory in (binary, library, share): directory.mkdir(parents=True)
                    cli = binary / "workflow-state"; cli.symlink_to(store / "workflow-state.py")
                    (binary / "artifact-budget").symlink_to(store / "artifact-budget")
                    (library / "artifact_budget.py").symlink_to(store / "artifact_budget.py")
                    (library / "workflow_delivery.py").symlink_to(store / "workflow_delivery.py")
                    (library / "delivery_model").symlink_to(store / "delivery_model", target_is_directory=True)
                    (share / "artifact-budget-policy.json").symlink_to(
                        store / "artifact-budget-policy.json")
                completed = subprocess.run([sys.executable, str(cli), "init-run",
                    "--repo-root", str(repo), "--run-id", "admission", "--now", NOW],
                    capture_output=True, text=True, env=env, check=False)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(json.loads(completed.stdout), {"interface_version": 2,
                    "kind": "workflow_bootstrap", "run_id": "admission", "requirements": []})
                malformed = base / "bad.json"; malformed.write_text("{malformed")
                entry = store / "delivery_model/__init__.py"; saved_entry = entry.read_bytes()
                entry.write_text("MODEL_INTERFACE_VERSION = True\n")
                wrong = subprocess.run([sys.executable, str(cli), "direct-owner",
                    "--repo-root", str(repo), "--request-file", str(malformed)],
                    capture_output=True, text=True, env=env, check=False)
                self.assertEqual(wrong.returncode, 2); self.assertIn("interface", wrong.stderr)
                self.assertNotIn("JSON", wrong.stderr); entry.write_bytes(saved_entry)
                (store / "delivery_model/_wire.py").unlink()
                refused = subprocess.run([sys.executable, str(cli), "direct-owner",
                    "--repo-root", str(repo), "--request-file", str(malformed)],
                    capture_output=True, text=True, env=env, check=False)
                self.assertEqual(refused.returncode, 2); self.assertIn("model", refused.stderr)
                self.assertNotIn("JSON", refused.stderr)

    def test_direct_checkpoint_and_failure_remainder_round_trip(self):
        contract, delivery, actual = contract_and_delivery_for_stage(self.model, "select")
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); worktree = str(root / "worktree")
            request = self.direct_request(contract)
            request.update(
                tracker={"issue": 151, "state": "open", "open_blockers": [],
                         "decision_blockers": []},
                worktree={"issue": 151, "recorded": None,
                          "candidate": {"path": worktree, "state": "absent"}},
                forge={"state": "none", "url": None, "merge_sha": None},
                authorization_intents=delivery["authorization_intents"],
                requested_scope=actual,
            )
            request_path = root / "direct.json"; request_path.write_text(json.dumps(request))
            owner = subprocess.run(
                [sys.executable, str(WORKFLOW), "direct-owner", "--repo-root", str(root),
                 "--request-file", str(request_path)], capture_output=True, text=True,
                check=False)
            self.assertEqual(owner.returncode, 0, owner.stderr)
            owner_value = json.loads(owner.stdout)
            self.assertEqual(owner_value["kind"], "owner")
            self.assertEqual(owner_value["requested_scope"], actual)
            self.assertIsNone(owner_value["authority_evaluation"])
            self.assertEqual(owner_value["requirements"], [{
                "kind": "observation", "subject_id": actual["id"],
                "reason_code": "native_evaluation_required", "detail_pointer": None,
            }])

            allowed = authority(self.model, contract, actual, owner_value["custody"],
                                verdict="allowed")
            allowed["observed_at"] = "2026-09-21T00:00:01Z"
            seal(self.model, allowed)
            checkpoint = {
                "interface_version": 2, "issue": 151,
                "custody": owner_value["custody"],
                "contract_digest": self.model.canonical_digest(contract),
                "delivery_observations": [], "authority_observations": [allowed],
                "reevaluation_evidence": [], "requested_scope": actual,
                "detail_state": "none", "report_path": None, "notes": "",
            }
            checkpoint_path = root / "checkpoint.json"
            checkpoint_path.write_text(json.dumps(checkpoint))
            persisted = subprocess.run(
                [sys.executable, str(WORKFLOW), "checkpoint-delivery",
                 "--repo-root", str(root), "--run-id", owner_value["run_id"],
                 "--checkpoint-file", str(checkpoint_path), "--now",
                 "2026-09-21T00:00:01Z"], capture_output=True, text=True, check=False)
            self.assertEqual(persisted.returncode, 0, persisted.stderr)
            checkpointed = json.loads(persisted.stdout)
            self.assertEqual(checkpointed["kind"], "delivery_checkpointed")
            self.assertEqual(checkpointed["accepted_observation_ids"], [allowed["id"]])
            self.assertEqual(checkpointed["requested_scope"], actual)

            historical = {"issue": 151, "state": "failed", "pr_url": None,
                "merge_sha": None, "issue_closed": False, "discussion_items": [],
                "detail_state": "none", "report_path": None, "notes": "provider failed"}
            summary = {"interface_version": 2, "issue": 151,
                "state": "terminal_failed", "custody": owner_value["custody"],
                "historical_owner_result": historical,
                "delivery_contract_digest": self.model.canonical_digest(contract),
                "delivery_observations": [], "authority_observations": [],
                "reevaluation_evidence": [], "detail_state": "none",
                "report_path": None, "notes": "provider failed"}
            summary_path = root / "summary.json"; summary_path.write_text(json.dumps(summary))
            finished = subprocess.run(
                [sys.executable, str(WORKFLOW), "finish", "--repo-root", str(root),
                 "--run-id", owner_value["run_id"], "--summary-file", str(summary_path),
                 "--now", "2026-09-21T00:00:02Z"], capture_output=True, text=True,
                check=False)
            self.assertEqual(finished.returncode, 0, finished.stderr)
            remainder = json.loads(finished.stdout)
            self.assertEqual(remainder["kind"], "delivery_remainder")
            self.assertEqual(remainder["custody"]["action_id"], "151:r1:1")

    def test_all_stages_fold_before_delivery_completion(self):
        contract, initial_intent = self.all_stage_contract()
        digest = self.model.canonical_digest(contract)
        scopes = {stage["id"]: stage_scope(self.model, contract, stage["id"])
                  for stage in contract["stages"]}
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); worktree = str(root / "worktree")

            def run(*args):
                completed = subprocess.run(
                    [sys.executable, str(WORKFLOW), *map(str, args)],
                    capture_output=True, text=True, check=False)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                return json.loads(completed.stdout)

            def write(name, value):
                path = root / name; path.write_text(json.dumps(value)); return path

            request = self.direct_request(contract)
            request.update(
                tracker={"issue": 151, "state": "open", "open_blockers": [],
                         "decision_blockers": []},
                worktree={"issue": 151, "recorded": None,
                          "candidate": {"path": worktree, "state": "absent"}},
                forge={"state": "none", "url": None, "merge_sha": None},
                authorization_intents=[initial_intent], requested_scope=scopes["select"])
            action = run("direct-owner", "--repo-root", root, "--request-file",
                         write("direct.json", request))
            custody_value = action["custody"]
            selected = selection(self.model, digest)
            stage_observations = {
                "select": observation(self.model, contract, "selected_output",
                                      {"selected_output": selected}),
                "publish": observation(self.model, contract, "branch_published",
                    {"repository_id": "sim-repo", "branch": "feature",
                     "selected_head": "a" * 40}),
                "open": observation(self.model, contract, "pr_opened",
                                    pr_subject("pr_opened")),
                "merge": observation(self.model, contract, "pr_merged",
                                     pr_subject("pr_merged")),
            }
            order = ["select", "publish", "open", "merge"]
            for index, stage_id in enumerate(order):
                allowed = authority(self.model, contract, scopes[stage_id], custody_value,
                                    verdict="allowed")
                allowed["observed_at"] = f"2026-09-21T00:00:0{index + 1}Z"
                seal(self.model, allowed)
                report = self.report_common(custody_value, digest)
                report["authority_observations"] = [allowed]
                report["delivery_observations"] = [stage_observations[stage_id]]
                report["requested_scope"] = (scopes[order[index + 1]]
                                             if index + 1 < len(order) else None)
                action = run("checkpoint-delivery", "--repo-root", root,
                    "--run-id", action["run_id"], "--checkpoint-file",
                    write(f"checkpoint-{stage_id}.json", report), "--now",
                    f"2026-09-21T00:00:0{index + 1}Z")
                self.assertEqual(action["accepted_observation_ids"], sorted(
                    [allowed["id"], stage_observations[stage_id]["id"]]))
                if index + 1 < len(order):
                    self.assertEqual(action["next_action"]["requested_scope"],
                                     report["requested_scope"])
            self.assertIsNone(action["next_action"])
            self.assertEqual(action["requirements"][0]["subject_id"],
                             "implementation_delivered")
            merged = stage_observations["merge"]
            integrated = observation(self.model, contract, "implementation_delivered", {
                "selected_subject": {"kind": "commit", "value": "a" * 40},
                "integration_subject": {"kind": "commit", "value": "b" * 40},
                "presence": {"kind": "reachability", "repository_id": "sim-repo",
                    "selected_value": "a" * 40, "integration_value": "b" * 40,
                    "integrated_ref": "refs/heads/main", "succeeded": True},
                "merge_observation_id": merged["id"],
                "acceptance_evidence_ids": ["accept-1"],
                "review_evidence_ids": ["review-1"], "test_evidence_ids": ["test-1"],
            })
            summary = {"interface_version": 2, "issue": 151,
                "state": "delivery_complete", "custody": custody_value,
                "historical_owner_result": None,
                "delivery_contract_digest": digest,
                "delivery_observations": [integrated], "authority_observations": [],
                "reevaluation_evidence": [], "detail_state": "none",
                "report_path": None, "notes": "delivered"}
            finished = run("finish", "--repo-root", root, "--run-id", action["run_id"],
                "--summary-file", write("summary.json", summary), "--now",
                "2026-09-21T00:00:05Z")
            self.assertEqual((finished["kind"], finished["state"],
                              finished["pending_stage_ids"]),
                             ("delivery_complete", "delivery_complete", []))
            current = run("current-launch", "--repo-root", root, "--run-id",
                          action["run_id"], "--action-id", custody_value["action_id"])
            self.assertEqual((current["current"], current["reason"]),
                             (False, "inactive_attempt"))

    def test_suspended_remainder_resumes_same_identity_and_deadline(self):
        contract, delivery, actual = contract_and_delivery_for_stage(self.model, "select")
        digest = self.model.canonical_digest(contract)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); worktree = str(root / "worktree")
            def call(*args, ok=True):
                completed = subprocess.run([sys.executable, str(WORKFLOW), *map(str, args)],
                    capture_output=True, text=True, check=False)
                if ok: self.assertEqual(completed.returncode, 0, completed.stderr)
                return completed
            def store(name, value):
                path = root / name; path.write_text(json.dumps(value)); return path
            request = self.direct_request(contract)
            request.update(tracker={"issue": 151, "state": "open", "open_blockers": [],
                "decision_blockers": []}, worktree={"issue": 151, "recorded": None,
                "candidate": {"path": worktree, "state": "absent"}},
                forge={"state": "none", "url": None, "merge_sha": None},
                authorization_intents=delivery["authorization_intents"],
                requested_scope=actual)
            owner = json.loads(call("direct-owner", "--repo-root", root,
                               "--request-file", store("owner.json", request)).stdout)
            failed = {"interface_version": 2, "issue": 151,
                "state": "terminal_failed", "custody": owner["custody"],
                "historical_owner_result": {"issue": 151, "state": "failed",
                    "pr_url": None, "merge_sha": None, "issue_closed": False,
                    "discussion_items": [], "detail_state": "none",
                    "report_path": None, "notes": "failed"},
                "delivery_contract_digest": digest, "delivery_observations": [],
                "authority_observations": [], "reevaluation_evidence": [],
                "detail_state": "none", "report_path": None, "notes": "failed"}
            remainder = json.loads(call("finish", "--repo-root", root, "--run-id",
                owner["run_id"], "--summary-file", store("failed.json", failed), "--now",
                "2026-09-21T00:00:01Z").stdout)
            denial = authority(self.model, contract, actual, remainder["custody"])
            denial["observed_at"] = "2026-09-21T00:00:02Z"; seal(self.model, denial)
            checkpoint = self.report_common(remainder["custody"], digest)
            checkpoint["authority_observations"] = [denial]
            checkpoint["requested_scope"] = actual
            suspended = json.loads(call("checkpoint-delivery", "--repo-root", root,
                "--run-id", owner["run_id"], "--checkpoint-file",
                store("denial.json", checkpoint), "--now", "2026-09-21T00:00:02Z").stdout)
            self.assertEqual((suspended["state"], suspended["blocked_on"]),
                             ("suspended", "human_gate"))
            resume = self.direct_request(contract)
            resume.update(now="2026-09-21T00:00:03Z",
                tracker={"issue": 151, "state": "open", "open_blockers": [],
                "decision_blockers": []}, worktree={"issue": 151,
                "recorded": {"path": worktree, "state": "matching_issue_branch"},
                "candidate": None}, forge={"state": "none", "url": None,
                "merge_sha": None}, requested_scope=None)
            resumed = call("direct-owner", "--repo-root", root,
                           "--request-file", store("resume.json", resume))
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            value = json.loads(resumed.stdout)
            self.assertEqual((value["kind"], value["custody"]["remainder"],
                              value["custody"]["launch"], value["deadline_at"]),
                             ("delivery_remainder", 1, 2, remainder["deadline_at"]))
            for ordinal in (1, 2, 3):
                repeated = self.report_common(value["custody"], digest)
                repeated["requested_scope"] = actual
                parked = json.loads(call("checkpoint-delivery", "--repo-root", root,
                    "--run-id", owner["run_id"], "--checkpoint-file",
                    store(f"repeat-{ordinal}.json", repeated), "--now",
                    f"2026-09-21T00:00:{3 + ordinal:02d}Z").stdout)
                if ordinal == 3:
                    self.assertEqual((parked["kind"], parked["stalled_resumes"]),
                                     ("delivery_stalled", 3))
                    break
                resume["now"] = f"2026-09-21T00:00:{4 + ordinal:02d}Z"
                value = json.loads(call("direct-owner", "--repo-root", root,
                    "--request-file", store(f"resume-{ordinal}.json", resume)).stdout)
                self.assertEqual(value["custody"]["launch"], ordinal + 2)

    def test_control_resumes_remainder_without_spending_implementation_attempt(self):
        contract, delivery, actual = contract_and_delivery_for_stage(self.model, "select")
        digest = self.model.canonical_digest(contract)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); worktree = str(root / "worktree")
            serial = 0
            def invoke(*args):
                completed = subprocess.run([sys.executable, str(WORKFLOW), *map(str, args)],
                    capture_output=True, text=True, check=False)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                return json.loads(completed.stdout)
            def store(value):
                nonlocal serial; serial += 1
                path = root / f"input-{serial}.json"; path.write_text(json.dumps(value)); return path
            run_id = "orchestrated"
            invoke("init-run", "--repo-root", root, "--run-id", run_id, "--now", NOW)
            request = self.control_request(contract)
            request.update(tracker=[{"issue": 151, "state": "open", "open_blockers": [],
                "decision_blockers": []}], worktrees=[{"issue": 151, "recorded": None,
                "candidate": {"path": worktree, "state": "absent"}}])
            request["authorization_intents"]["151"] = delivery["authorization_intents"]
            request["requested_scopes"]["151"] = actual
            owner = invoke("control", "--repo-root", root, "--run-id", run_id,
                           "--request-file", store(request))["actions"][0]
            failed = {"interface_version": 2, "issue": 151,
                "state": "terminal_failed", "custody": owner["custody"],
                "historical_owner_result": {"issue": 151, "state": "failed",
                    "pr_url": None, "merge_sha": None, "issue_closed": False,
                    "discussion_items": [], "detail_state": "none",
                    "report_path": None, "notes": "failed"},
                "delivery_contract_digest": digest, "delivery_observations": [],
                "authority_observations": [], "reevaluation_evidence": [],
                "detail_state": "none", "report_path": None, "notes": "failed"}
            remainder = invoke("finish", "--repo-root", root, "--run-id", run_id,
                               "--summary-file", store(failed), "--now",
                               "2026-09-21T00:00:01Z")
            denial = authority(self.model, contract, actual, remainder["custody"])
            denial["observed_at"] = "2026-09-21T00:00:02Z"; seal(self.model, denial)
            checkpoint = self.report_common(remainder["custody"], digest)
            checkpoint.update(authority_observations=[denial], requested_scope=actual)
            invoke("checkpoint-delivery", "--repo-root", root, "--run-id", run_id,
                   "--checkpoint-file", store(checkpoint), "--now",
                   "2026-09-21T00:00:02Z")
            resume = self.control_request(contract)
            resume.update(now="2026-09-21T00:00:03Z",
                tracker=request["tracker"], worktrees=[{"issue": 151,
                    "recorded": {"path": worktree, "state": "matching_issue_branch"},
                    "candidate": None}])
            response = invoke("control", "--repo-root", root, "--run-id", run_id,
                              "--request-file", store(resume))
            action = next(item for item in response["actions"]
                          if item["kind"] == "delivery_remainder")
            self.assertEqual((action["custody"]["remainder"],
                              action["custody"]["launch"], action["deadline_at"]),
                             (1, 2, remainder["deadline_at"]))
            state = json.loads((root / ".superpowers/workflows/orchestrated/state.json").read_text())
            self.assertEqual(len(state["issues"]["151"]["attempts"]), 1)


if __name__ == "__main__":
    unittest.main()
