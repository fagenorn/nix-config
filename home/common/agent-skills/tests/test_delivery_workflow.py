from __future__ import annotations

import copy
import hashlib
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
    authority, cleanup_contract_and_delivery, contract_and_delivery,
    contract_and_delivery_for_stage, observation, pr_subject, seal, selection,
    stage_scope,
)
from .test_resolve_project import make_home, make_project_root, run as run_resolver, source_contract


ROOT = Path(__file__).parents[4]
SCRIPTS = ROOT / "home/common/agent-skills/scripts"
WORKFLOW = SCRIPTS / "workflow-state.py"
MODEL = SCRIPTS / "delivery_model/__init__.py"
POLICY = ROOT / "home/common/agent-skills/artifact-budget-policy.json"
ARTIFACT_BUDGET = SCRIPTS / "artifact_budget.py"
NOW = "2026-09-21T00:00:00Z"
WORKTREE_NAME = "worktree-issue-171-delivery-contract-source"
LATER = "2026-09-21T00:10:00Z"


class FakeProvider:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute(self, scope):
        self.calls.append(copy.deepcopy(scope))
        return copy.deepcopy(self.result)


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
            "issues": [151], "tracker": [{"issue": 151, "state": "open",
                "open_blockers": [], "decision_blockers": []}],
            "owners": [], "worktrees": [],
            "forge": {"151": {"state": "none", "url": None, "merge_sha": None}},
            "delivery_contracts": {"151": contract},
            "authorization_intents": copy.deepcopy(empty),
            "authority_observations": copy.deepcopy(empty),
            "reevaluation_evidence": copy.deepcopy(empty),
            "delivery_observations": copy.deepcopy(empty),
            "requested_scopes": scope,
            "recoveries": {"151": None}}

    def direct_request(self, contract=None):
        return {"interface_version": 2, "issue": 151, "now": NOW,
            "attempt_budget_minutes": 30, "new_run": False,
            "owner_unavailable": False, "tracker": None, "worktree": None,
            "forge": None, "delivery_contract": contract,
            "authorization_intents": [], "authority_observations": [],
            "reevaluation_evidence": [], "delivery_observations": [],
            "requested_scope": None, "recovery": None}

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

    @staticmethod
    def failed_summary(custody_value, digest, notes="failed"):
        historical = {"issue": 151, "state": "failed", "pr_url": None,
            "merge_sha": None, "issue_closed": False, "discussion_items": [],
            "detail_state": "none", "report_path": None, "notes": notes}
        return {"interface_version": 2, "issue": 151,
            "state": "terminal_failed", "custody": custody_value,
            "historical_owner_result": historical,
            "delivery_contract_digest": digest, "delivery_observations": [],
            "authority_observations": [], "reevaluation_evidence": [],
            "detail_state": "none", "report_path": None, "notes": notes}

    def state_with_attempt(self):
        state = self.workflow.new_run_state(run_id="admission", now=NOW, issues={})
        attempt = self.workflow.new_control_attempt(
            issue=151, attempt_number=1, worktree="/worktree", now=NOW,
            deadline_at="2026-09-21T01:00:00Z")
        state["issues"]["151"] = {"issue": 151, "attempts": [attempt],
            "outcome": None,
            "delivery": self.workflow._delivery().empty_delivery(),
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
        migrated = self.workflow._delivery().migrate(value, migration_contracts={})
        self.workflow.validate_state(migrated, run_id="admission")
        return value

    def test_interface_two_maps_and_singular_inputs_are_closed(self):
        request, context = self.workflow.validate_control_request(self.control_request())
        self.assertEqual(context, {151: None}); self.assertEqual(request["interface_version"], 2)
        direct, direct_context = self.workflow.validate_direct_owner_request(
            self.direct_request())
        self.assertEqual(direct_context, {151: None}); self.assertEqual(direct["interface_version"], 2)
        for variant in ("missing", "extra", "noncanonical", "legacy", "null_facts"):
            bad = self.control_request()
            if variant == "missing": bad.pop("requested_scopes")
            elif variant == "extra": bad["requested_scopes"]["152"] = None
            elif variant == "noncanonical": bad["requested_scopes"] = {"0151": None}
            elif variant == "legacy": bad["interface_version"] = 1
            else: bad["delivery_observations"]["151"] = [{"kind": "delivery-observation"}]
            with self.subTest(variant=variant), self.assertRaises(self.workflow.WorkflowError):
                self.workflow.validate_control_request(bad)
        contract, delivery = contract_and_delivery(self.model)
        valid_intent = delivery["authorization_intents"][0]
        for field, value in (("authorization_intents", [valid_intent]),
                             ("requested_scope", stage_scope(self.model, contract, "select"))):
            bad = self.direct_request(); bad[field] = value
            with self.subTest(null_contract_field=field), self.assertRaises(self.workflow.WorkflowError):
                self.workflow.validate_direct_owner_request(bad)
        bad = self.direct_request(contract)
        bad["authorization_intents"] = [valid_intent, valid_intent]
        with self.assertRaises(self.workflow.WorkflowError):
            self.workflow.validate_direct_owner_request(bad)
        bad = self.direct_request(contract); bad["issue"] = 152
        with self.assertRaises(self.workflow.WorkflowError):
            self.workflow.validate_direct_owner_request(bad)
        original = self.direct_request(contract); before = copy.deepcopy(original)
        detached, context = self.workflow.validate_direct_owner_request(original)
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
                "requirements": [{"kind": "tracker"}]})
            control_request = self.control_request()
            control_request["worktrees"] = [{"issue": 151, "recorded": None, "candidate": {
                "path": str(root / "worktree"), "state": "absent"}}]
            control_path = root / "control.json"
            control_path.write_text(json.dumps(control_request))
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

    def test_schema_three_accepts_the_legacy_finish_transport_on_a_contractless_issue(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialized = subprocess.run(
                [sys.executable, str(WORKFLOW), "init-run", "--repo-root", str(root),
                 "--run-id", "legacy-contractless", "--now", NOW],
                capture_output=True, text=True, check=False)
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            state_path = root / ".superpowers/workflows/legacy-contractless/state.json"
            worktree = str(root / "worktree")
            state = json.loads(state_path.read_text())
            state["issues"]["151"] = {"issue": 151, "outcome": None, "attempts": [
                self.workflow.new_control_attempt(issue=151, attempt_number=1,
                    worktree=worktree, now=NOW, deadline_at="2026-09-21T01:00:00Z")],
                "delivery": self.workflow._delivery().empty_delivery(),
                "delivery_remainders": []}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            result = {"issue": 151, "state": "failed", "pr_url": None,
                "merge_sha": None, "issue_closed": False, "discussion_items": [],
                "detail_state": "none", "report_path": None, "notes": "failed"}
            result_path = root / "legacy-result.json"
            result_path.write_text(json.dumps(result), encoding="utf-8")
            finished = subprocess.run(
                [sys.executable, str(WORKFLOW), "finish", "--repo-root", str(root),
                 "--run-id", "legacy-contractless", "--issue", "151", "--attempt", "1",
                 "--result-file", str(result_path), "--now", NOW],
                capture_output=True, text=True, check=False)
            self.assertEqual(finished.returncode, 0, finished.stderr)
            # A failed result retains its worktree path in the notes (retain_worktree).
            expected = {**result, "notes": f"failed; worktree: {worktree}"}
            stored = json.loads(state_path.read_text())["issues"]["151"]
            self.assertEqual((stored["outcome"], stored["delivery"]["contract"]),
                             (expected, None))

    def test_adjacent_migration_is_detached_and_writes_only_schema_three(self):
        contract, _ = contract_and_delivery(self.model)
        for version in (1, 2):
            legacy = self.legacy(version); original = copy.deepcopy(legacy)
            migrated = self.workflow.upgrade_state(
                legacy, run_id="admission", migration_contracts={151: contract})
            self.assertEqual(legacy, original); self.assertEqual(migrated["schema_version"], 3)
            self.assertEqual(migrated["issues"]["151"]["delivery"],
                             self.workflow._delivery().empty_delivery())
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
            "result": None, "result_source": None, "recovery": None,
            "finished_at": None}]
        state["updated_at"] = NOW
        self.workflow.validate_state(state, run_id="admission")
        requirement = self.workflow.bootstrap_response(state)["requirements"][0]
        self.assertEqual(requirement["custody"]["action_id"], "151:r1:1")
        self.assertEqual(set(requirement), {"issue", "owner", "custody", "recorded_worktree",
                                            "contract_digest"})
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
                shutil.copy2(SCRIPTS / "workflow_delivery_wire.py",
                             store / "workflow_delivery_wire.py")
                shutil.copy2(SCRIPTS / "workflow_delivery_build.py",
                             store / "workflow_delivery_build.py")
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
                    (library / "workflow_delivery_wire.py").symlink_to(
                        store / "workflow_delivery_wire.py")
                    (library / "workflow_delivery_build.py").symlink_to(
                        store / "workflow_delivery_build.py")
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
                def rejects_dependency(fragment):
                    result = subprocess.run([sys.executable, str(cli), "direct-owner",
                        "--repo-root", str(repo), "--request-file", str(malformed)],
                        capture_output=True, text=True, env=env, check=False)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(fragment, result.stderr)
                    self.assertNotIn("JSON", result.stderr)
                entry = store / "delivery_model/__init__.py"; saved_entry = entry.read_bytes()
                entry.write_text("MODEL_INTERFACE_VERSION = True\n")
                rejects_dependency("interface"); entry.write_bytes(saved_entry)
                model_wire = store / "delivery_model/_wire.py"
                saved_wire = model_wire.read_bytes(); model_wire.unlink()
                rejects_dependency("model")
                model_wire.write_bytes(saved_wire)
                helper = store / "workflow_delivery_wire.py"
                helper_bytes = helper.read_bytes()
                before = {str(path.relative_to(repo)): path.read_bytes()
                          for path in repo.rglob("*") if path.is_file()}
                for replacement in (None,
                        b"WORKFLOW_DELIVERY_WIRE_INTERFACE_VERSION = 2\n"
                        b"class DeliveryProjection: pass\n"):
                    if replacement is None: helper.unlink()
                    else: helper.write_bytes(replacement)
                    rejects_dependency("projection")
                    self.assertEqual(before, {str(path.relative_to(repo)): path.read_bytes()
                        for path in repo.rglob("*") if path.is_file()})
                    helper.write_bytes(helper_bytes)
                builder = store / "workflow_delivery_build.py"
                builder_bytes = builder.read_bytes()
                for replacement in (None,
                        b"WORKFLOW_DELIVERY_BUILD_INTERFACE_VERSION = 2\n"
                        b"class DeliveryBuilder: pass\n"):
                    if replacement is None: builder.unlink()
                    else: builder.write_bytes(replacement)
                    rejects_dependency("builder")
                    self.assertEqual(before, {str(path.relative_to(repo)): path.read_bytes()
                        for path in repo.rglob("*") if path.is_file()})
                    builder.write_bytes(builder_bytes)

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

            digest = self.model.canonical_digest(contract)
            summary = self.failed_summary(owner_value["custody"], digest, "provider failed")
            summary["delivery_observations"] = [
                observation(self.model, contract, "selected_output",
                            {"selected_output": selection(self.model, digest)})]
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

    def test_typed_effect_uses_raw_validation_and_both_launch_fences(self):
        def validated(boundary, raw):
            result = subprocess.run(
                [sys.executable, str(ARTIFACT_BUDGET), "validate-report",
                 "--boundary", boundary, "--input", "-", "--policy", str(POLICY)],
                input=raw, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, (result.stderr, raw))
            return json.loads(result.stdout)

        for case in ("success", "scope_mismatch", "stale_after_effect",
                     "provider_denial"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as raw:
                root = Path(raw); worktree = str(root / "worktree")
                if case == "provider_denial":
                    contract, initial_intent = self.all_stage_contract()
                    delivery = {"authorization_intents": [initial_intent],
                                "delivery_observations": []}
                    actual = stage_scope(self.model, contract, "publish")
                else:
                    contract, delivery, actual = contract_and_delivery_for_stage(
                        self.model, "select")
                effect_scope = (stage_scope(self.model, contract, "select")
                                if case == "provider_denial" else actual)
                digest = self.model.canonical_digest(contract)

                def invoke(*args):
                    return subprocess.run(
                        [sys.executable, str(WORKFLOW), *map(str, args)],
                        capture_output=True, check=False)

                def store(name, value):
                    path = root / name
                    path.write_text(json.dumps(value), encoding="utf-8")
                    return path

                request = self.direct_request(contract)
                request.update(
                    tracker={"issue": 151, "state": "open", "open_blockers": [],
                             "decision_blockers": []},
                    worktree={"issue": 151, "recorded": None,
                              "candidate": {"path": worktree, "state": "absent"}},
                    forge={"state": "none", "url": None, "merge_sha": None},
                    authorization_intents=delivery["authorization_intents"],
                    delivery_observations=delivery["delivery_observations"],
                    requested_scope=effect_scope,
                )
                owner_raw = invoke("direct-owner", "--repo-root", root,
                                   "--request-file", store("direct.json", request))
                self.assertEqual(owner_raw.returncode, 0, owner_raw.stderr.decode())
                action = validated("workflow-response", owner_raw.stdout)
                provider_result = observation(
                    self.model, contract, "selected_output",
                    {"selected_output": selection(self.model, digest)})
                provider = FakeProvider(provider_result)
                supplied_scope = copy.deepcopy(effect_scope)
                if case == "scope_mismatch":
                    supplied_scope["endpoint"] = {"kind": "literal", "value": "foreign"}
                before = (root / ".superpowers/workflows" / action["run_id"] /
                          "state.json").read_bytes()
                if action["requested_scope"] != supplied_scope:
                    self.assertEqual(provider.calls, [])
                    self.assertEqual((root / ".superpowers/workflows" /
                                      action["run_id"] / "state.json").read_bytes(), before)
                    continue

                first_raw = invoke("current-launch", "--repo-root", root,
                                   "--run-id", action["run_id"], "--action-id",
                                   action["custody"]["action_id"])
                first = validated("workflow-response", first_raw.stdout)
                self.assertTrue(first["current"])
                observed = provider.execute(supplied_scope)
                if case == "stale_after_effect":
                    suspended = invoke(
                        "suspend", "--repo-root", root, "--run-id", action["run_id"],
                        "--issue", 151, "--attempt", 1, "--blocked-on", "external",
                        "--now", "2026-09-21T00:00:01Z")
                    self.assertEqual(suspended.returncode, 0, suspended.stderr.decode())
                before_observation = (root / ".superpowers/workflows" /
                                      action["run_id"] / "state.json").read_bytes()
                second_raw = invoke("current-launch", "--repo-root", root,
                                    "--run-id", action["run_id"], "--action-id",
                                    action["custody"]["action_id"])
                second = validated("workflow-response", second_raw.stdout)
                if case == "stale_after_effect":
                    self.assertFalse(second["current"])
                    self.assertEqual(len(provider.calls), 1)
                    self.assertEqual((root / ".superpowers/workflows" /
                                      action["run_id"] / "state.json").read_bytes(),
                                     before_observation)
                    continue

                self.assertTrue(second["current"])
                report = self.report_common(action["custody"], digest)
                allowed = authority(
                    self.model, contract, effect_scope, action["custody"],
                    verdict="allowed")
                report.update(delivery_observations=[observed],
                              authority_observations=[allowed],
                              requested_scope=None)
                canonical_report = validated(
                    "ship-checkpoint", json.dumps(report).encode("utf-8"))
                checkpoint = invoke(
                    "checkpoint-delivery", "--repo-root", root, "--run-id",
                    action["run_id"], "--checkpoint-file",
                    store("checkpoint.json", canonical_report), "--now",
                    "2026-09-21T00:00:01Z")
                self.assertEqual(checkpoint.returncode, 0, checkpoint.stderr.decode())
                response = validated("workflow-response", checkpoint.stdout)
                self.assertIn(observed["id"], response["accepted_observation_ids"])
                self.assertEqual(provider.calls, [effect_scope])
                if case == "provider_denial":
                    proposal = self.report_common(action["custody"], digest)
                    proposal["requested_scope"] = actual
                    proposal = validated(
                        "ship-checkpoint", json.dumps(proposal).encode())
                    proposed = invoke(
                        "checkpoint-delivery", "--repo-root", root, "--run-id",
                        action["run_id"], "--checkpoint-file",
                        store("proposal.json", proposal), "--now",
                        "2026-09-21T00:00:01Z")
                    self.assertEqual(proposed.returncode, 0,
                                     proposed.stderr.decode())
                    proposed = validated("workflow-response", proposed.stdout)
                    self.assertEqual(proposed["requested_scope"], actual)
                    denial = authority(self.model, contract, actual,
                                       action["custody"], verdict="rejected")
                    denial["observed_at"] = "2026-09-21T00:00:02Z"
                    seal(self.model, denial)
                    denying_provider = FakeProvider(denial)
                    first = validated("workflow-response", invoke(
                        "current-launch", "--repo-root", root, "--run-id",
                        action["run_id"], "--action-id",
                        action["custody"]["action_id"]).stdout)
                    self.assertTrue(first["current"])
                    rejected = denying_provider.execute(actual)
                    second = validated("workflow-response", invoke(
                        "current-launch", "--repo-root", root, "--run-id",
                        action["run_id"], "--action-id",
                        action["custody"]["action_id"]).stdout)
                    self.assertTrue(second["current"])
                    denied_report = self.report_common(action["custody"], digest)
                    denied_report.update(authority_observations=[rejected],
                                         requested_scope=actual)
                    denied_report = validated(
                        "ship-checkpoint", json.dumps(denied_report).encode())
                    denied = invoke(
                        "checkpoint-delivery", "--repo-root", root, "--run-id",
                        action["run_id"], "--checkpoint-file",
                        store("denied.json", denied_report), "--now",
                        "2026-09-21T00:00:02Z")
                    self.assertEqual(denied.returncode, 0, denied.stderr.decode())
                    denied = validated("workflow-response", denied.stdout)
                    self.assertEqual((denied["state"], denied["blocked_on"]),
                                     ("suspended", "human_gate"))
                    resume = self.direct_request(contract)
                    resume.update(now="2026-09-21T00:00:03Z",
                        tracker={"issue": 151, "state": "open", "open_blockers": [],
                                 "decision_blockers": []},
                        worktree={"issue": 151, "recorded": {
                            "path": worktree, "state": "matching_issue_branch"},
                            "candidate": None},
                        forge={"state": "none", "url": None, "merge_sha": None})
                    resumed_raw = invoke("direct-owner", "--repo-root", root,
                        "--request-file", store("resume.json", resume))
                    self.assertEqual(resumed_raw.returncode, 0,
                                     resumed_raw.stderr.decode())
                    resumed = validated("workflow-response", resumed_raw.stdout)
                    self.assertEqual(resumed["custody"]["launch"], 2)
                    saved = json.loads((root / ".superpowers/workflows" /
                        action["run_id"] / "state.json").read_text())["issues"]["151"]["delivery"]
                    self.assertIn(rejected["id"], [item["id"] for item in
                                                   saved["authority_observations"]])
                    self.assertEqual(next(item["state"] for item in saved["stage_facts"]
                                          if item["stage_id"] == "select"), "observed")
                    self.assertEqual(next(item["state"] for item in saved["stage_facts"]
                                          if item["stage_id"] == "publish"), "pending")
                    self.assertEqual(denying_provider.calls, [actual])

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
        contract, delivery, actual = contract_and_delivery_for_stage(self.model, "publish")
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
                authorization_intents=delivery["authorization_intents"])
            owner = json.loads(call("direct-owner", "--repo-root", root,
                               "--request-file", store("owner.json", request)).stdout)
            failed = self.failed_summary(owner["custody"], digest)
            failed["delivery_observations"] = [
                observation(self.model, contract, "selected_output",
                            {"selected_output": selection(self.model, digest)})]
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
            resume["now"] = "2026-09-21T04:00:00Z"
            value = json.loads(call("direct-owner", "--repo-root", root,
                "--request-file", store("expired-resume.json", resume)).stdout)
            self.assertEqual(
                (value["custody"]["remainder"], value["custody"]["launch"],
                 value["deadline_at"]), (1, 3, "2026-09-21T04:30:00Z"))
            for ordinal in (1, 2):
                repeated = self.report_common(value["custody"], digest)
                repeated["requested_scope"] = actual
                parked = json.loads(call("checkpoint-delivery", "--repo-root", root,
                    "--run-id", owner["run_id"], "--checkpoint-file",
                    store(f"repeat-{ordinal}.json", repeated), "--now",
                    f"2026-09-21T04:00:0{ordinal}Z").stdout)
                if ordinal == 2:
                    self.assertEqual((parked["kind"], parked["stalled_resumes"]),
                                     ("delivery_stalled", 3))
                    break
                resume["now"] = f"2026-09-21T04:00:0{ordinal + 1}Z"
                value = json.loads(call("direct-owner", "--repo-root", root,
                    "--request-file", store(f"resume-{ordinal}.json", resume)).stdout)
                self.assertEqual(value["custody"]["launch"], ordinal + 3)

    def test_remainder_two_requires_closed_recovery_proof_and_replays(self):
        contract, delivery, actual = contract_and_delivery_for_stage(self.model, "publish")
        digest = self.model.canonical_digest(contract)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); worktree = str(root / "worktree"); serial = 0
            def store(value):
                nonlocal serial; serial += 1
                path = root / f"recovery-{serial}.json"
                path.write_text(json.dumps(value)); return path
            def call(*args, ok=True):
                completed = subprocess.run([sys.executable, str(WORKFLOW), *map(str, args)],
                    capture_output=True, text=True, check=False)
                if ok: self.assertEqual(completed.returncode, 0, completed.stderr)
                return completed
            request = self.direct_request(contract)
            request.update(now=NOW,
                tracker={"issue": 151, "state": "open", "open_blockers": [],
                         "decision_blockers": []},
                worktree={"issue": 151, "recorded": None,
                          "candidate": {"path": worktree, "state": "absent"}},
                forge={"state": "none", "url": None, "merge_sha": None},
                authorization_intents=delivery["authorization_intents"])
            owner = json.loads(call("direct-owner", "--repo-root", root,
                "--request-file", store(request)).stdout)
            historical = {"issue": 151, "state": "failed", "pr_url": None,
                "merge_sha": None, "issue_closed": False, "discussion_items": [],
                "detail_state": "none", "report_path": None, "notes": "transient"}
            def failed(custody):
                return {"interface_version": 2, "issue": 151,
                    "state": "terminal_failed", "custody": custody,
                    "historical_owner_result": historical,
                    "delivery_contract_digest": digest, "delivery_observations": [],
                    "authority_observations": [], "reevaluation_evidence": [],
                    "detail_state": "none", "report_path": None, "notes": "transient"}
            selected = failed(owner["custody"])
            selected["delivery_observations"] = [
                observation(self.model, contract, "selected_output",
                            {"selected_output": selection(self.model, digest)})]
            first = json.loads(call("finish", "--repo-root", root, "--run-id",
                owner["run_id"], "--summary-file", store(selected),
                "--now", "2026-09-21T00:00:01Z").stdout)

            proof = {"schema_version": 1, "kind": "delivery-recovery", "id": "",
                "contract_digest": digest, "stage_id": "publish",
                "requested_scope": actual,
                "failure": {"kind": "effect_failure", "effect_attempted": True,
                    "classification": "transient", "source_kind": "provider",
                    "reference": "provider:attempt-1", "observed_at": "2026-09-21T00:00:02Z",
                    "evidence_digest": "sha256:" + "1" * 64},
                "effect_absence": {"kind": "effect_absence", "absent": True,
                    "probe_succeeded": True, "source_kind": "repository",
                    "reference": "repo:absence-1", "observed_at": "2026-09-21T00:00:03Z",
                    "evidence_digest": "sha256:" + "2" * 64},
                "basis": {"kind": "changed_relevant_evidence", "scope_id": actual["id"],
                    "source_kind": "provider", "reference": "provider:new-input",
                    "observed_at": "2026-09-21T00:00:03Z",
                    "evidence_digest": "sha256:" + "3" * 64}}
            proof["id"] = self.model.canonical_digest(proof, omit_derived="id")
            recovery_request = self.direct_request(contract)
            recovery_request.update(now="2026-09-21T00:00:04Z",
                authorization_intents=delivery["authorization_intents"], recovery=proof)

            before = (root / f".superpowers/workflows/{owner['run_id']}/state.json").read_bytes()
            active = call("direct-owner", "--repo-root", root,
                "--request-file", store(recovery_request), ok=False)
            self.assertIn("delivery recovery refused", active.stderr)
            self.assertEqual((root / f".superpowers/workflows/{owner['run_id']}/state.json").read_bytes(), before)

            terminal = json.loads(call("finish", "--repo-root", root, "--run-id",
                owner["run_id"], "--summary-file", store(failed(first["custody"])),
                "--now", "2026-09-21T00:00:02Z").stdout)
            self.assertEqual(terminal["kind"], "terminal_failed")
            state_path = root / f".superpowers/workflows/{owner['run_id']}/state.json"
            terminal_bytes = state_path.read_bytes()

            stale = copy.deepcopy(recovery_request)
            stale["recovery"]["failure"]["observed_at"] = "2026-09-20T23:59:59Z"
            stale["recovery"]["id"] = self.model.canonical_digest(
                stale["recovery"], omit_derived="id")
            refused = call("direct-owner", "--repo-root", root,
                "--request-file", store(stale), ok=False)
            self.assertIn("delivery recovery refused", refused.stderr)
            self.assertEqual(state_path.read_bytes(), terminal_bytes)

            unknown_absence = copy.deepcopy(recovery_request)
            unknown_absence["recovery"]["effect_absence"]["probe_succeeded"] = False
            unknown_absence["recovery"]["id"] = self.model.canonical_digest(
                unknown_absence["recovery"], omit_derived="id")
            refused = call("direct-owner", "--repo-root", root,
                "--request-file", store(unknown_absence), ok=False)
            self.assertIn("invalid delivery inputs", refused.stderr)
            self.assertEqual(state_path.read_bytes(), terminal_bytes)

            denied_request = copy.deepcopy(recovery_request)
            denied = authority(self.model, contract, actual, first["custody"])
            denied["observed_at"] = "2026-09-21T00:00:03Z"; seal(self.model, denied)
            denied_request["authority_observations"] = [denied]
            rejected = call("direct-owner", "--repo-root", root,
                "--request-file", store(denied_request), ok=False)
            self.assertIn("delivery recovery refused", rejected.stderr)
            self.assertEqual(state_path.read_bytes(), terminal_bytes)

            second = json.loads(call("direct-owner", "--repo-root", root,
                "--request-file", store(recovery_request)).stdout)
            self.assertEqual((second["kind"], second["custody"]["remainder"],
                              second["requested_scope"]),
                             ("delivery_remainder", 2, None))
            persisted = json.loads(state_path.read_text())
            self.assertEqual(persisted["issues"]["151"]["delivery_remainders"][1]
                             ["recovery"], proof)
            replay_bytes = state_path.read_bytes()
            replay = json.loads(call("direct-owner", "--repo-root", root,
                "--request-file", store(recovery_request)).stdout)
            self.assertEqual(replay, second)
            self.assertEqual(state_path.read_bytes(), replay_bytes)

            other = copy.deepcopy(recovery_request)
            other["recovery"]["basis"]["reference"] = "provider:different"
            other["recovery"]["id"] = self.model.canonical_digest(
                other["recovery"], omit_derived="id")
            third = call("direct-owner", "--repo-root", root,
                "--request-file", store(other), ok=False)
            self.assertIn("delivery recovery refused", third.stderr)
            self.assertEqual(state_path.read_bytes(), replay_bytes)

    def test_control_resumes_remainder_without_spending_implementation_attempt(self):
        contract, delivery, actual = contract_and_delivery_for_stage(self.model, "publish")
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
            owner = invoke("control", "--repo-root", root, "--run-id", run_id,
                           "--request-file", store(request))["actions"][0]
            failed = self.failed_summary(owner["custody"], digest)
            failed["delivery_observations"] = [
                observation(self.model, contract, "selected_output",
                            {"selected_output": selection(self.model, digest)})]
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
                tracker=[{"issue": 151, "state": "closed", "open_blockers": [],
                          "decision_blockers": []}], worktrees=[{"issue": 151,
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

    def test_control_allocates_only_one_proven_second_remainder(self):
        contract, delivery, actual = contract_and_delivery_for_stage(self.model, "publish")
        digest = self.model.canonical_digest(contract)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); run_id = "recovery-control"; serial = 0
            def store(value):
                nonlocal serial; serial += 1
                path = root / f"control-recovery-{serial}.json"
                path.write_text(json.dumps(value)); return path
            def invoke(*args):
                completed = subprocess.run([sys.executable, str(WORKFLOW), *map(str, args)],
                    capture_output=True, text=True, check=False)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                return json.loads(completed.stdout)
            invoke("init-run", "--repo-root", root, "--run-id", run_id, "--now", NOW)
            request = self.control_request(contract)
            request.update(tracker=[{"issue": 151, "state": "open", "open_blockers": [],
                "decision_blockers": []}], worktrees=[{"issue": 151, "recorded": None,
                "candidate": {"path": str(root / "worktree"), "state": "absent"}}])
            request["authorization_intents"]["151"] = delivery["authorization_intents"]
            owner = invoke("control", "--repo-root", root, "--run-id", run_id,
                           "--request-file", store(request))["actions"][0]
            historical = {"issue": 151, "state": "failed", "pr_url": None,
                "merge_sha": None, "issue_closed": False, "discussion_items": [],
                "detail_state": "none", "report_path": None, "notes": "transient"}
            def failed(custody):
                return {"interface_version": 2, "issue": 151,
                    "state": "terminal_failed", "custody": custody,
                    "historical_owner_result": historical,
                    "delivery_contract_digest": digest, "delivery_observations": [],
                    "authority_observations": [], "reevaluation_evidence": [],
                    "detail_state": "none", "report_path": None, "notes": "transient"}
            selected = failed(owner["custody"])
            selected["delivery_observations"] = [
                observation(self.model, contract, "selected_output",
                            {"selected_output": selection(self.model, digest)})]
            first = invoke("finish", "--repo-root", root, "--run-id", run_id,
                "--summary-file", store(selected), "--now",
                "2026-09-21T00:00:01Z")
            invoke("finish", "--repo-root", root, "--run-id", run_id,
                "--summary-file", store(failed(first["custody"])), "--now",
                "2026-09-21T00:00:02Z")
            recovery = {"schema_version": 1, "kind": "delivery-recovery", "id": "",
                "contract_digest": digest, "stage_id": "publish", "requested_scope": actual,
                "failure": {"kind": "effect_failure", "effect_attempted": True,
                    "classification": "transient", "source_kind": "host",
                    "reference": "host:failed", "observed_at": "2026-09-21T00:00:02Z",
                    "evidence_digest": "sha256:" + "4" * 64},
                "effect_absence": {"kind": "effect_absence", "absent": True,
                    "probe_succeeded": True, "source_kind": "filesystem",
                    "reference": "fs:absent", "observed_at": "2026-09-21T00:00:03Z",
                    "evidence_digest": "sha256:" + "5" * 64},
                "basis": {"kind": "changed_relevant_evidence", "scope_id": actual["id"],
                    "source_kind": "tracker", "reference": "tracker:changed",
                    "observed_at": "2026-09-21T00:00:03Z",
                    "evidence_digest": "sha256:" + "6" * 64}}
            recovery["id"] = self.model.canonical_digest(recovery, omit_derived="id")
            recover = self.control_request(contract)
            recover.update(now="2026-09-21T00:00:04Z", tracker=request["tracker"])
            recover["authorization_intents"]["151"] = delivery["authorization_intents"]
            recover["recoveries"]["151"] = recovery
            response = invoke("control", "--repo-root", root, "--run-id", run_id,
                              "--request-file", store(recover))
            second = next(item for item in response["actions"]
                          if item["kind"] == "delivery_remainder")
            self.assertEqual((second["custody"]["remainder"],
                              second["requested_scope"]), (2, None))
            state = json.loads((root / f".superpowers/workflows/{run_id}/state.json").read_text())
            self.assertEqual([item["remainder"] for item in
                              state["issues"]["151"]["delivery_remainders"]], [1, 2])
            state_path = root / f".superpowers/workflows/{run_id}/state.json"
            before = state_path.read_bytes()
            replay = invoke("control", "--repo-root", root, "--run-id", run_id,
                            "--request-file", store(recover))
            self.assertEqual(next(item for item in replay["actions"]
                                  if item["kind"] == "delivery_remainder"), second)
            self.assertEqual(state_path.read_bytes(), before)

    def issue_contract(self, issue, worktree):
        """The eight-stage cleanup contract and its first intent, bound to one issue.

        Its ``remove_worktree`` literal is the candidate path the caller spawns at.
        """
        contract, delivery = cleanup_contract_and_delivery(self.model)
        intent = copy.deepcopy(delivery["authorization_intents"][0])
        contract["issue"] = issue
        contract["deliverable"]["id"] = f"delivery-{issue}"
        for stage in contract["stages"]:
            if stage["kind"] == "close_tracker":
                stage["target_ref"]["value"] = str(issue)
            elif stage["kind"] == "remove_worktree":
                stage["target_ref"]["value"] = worktree
        for declared in intent["scopes"]:
            declared["target"]["issue"] = issue
            seal(self.model, declared)
        intent["scopes"].sort(key=lambda item: item["id"])
        seal(self.model, intent)
        contract["initial_authorization_intent_id"] = intent["id"]
        contract["initial_authorization_intent_digest"] = self.model.canonical_digest(intent)
        return contract, intent

    def test_dispatching_control_response_passes_raw_workflow_response_validation(self):
        """The adapter validates control bytes before decoding; a real dispatch must pass."""
        issues = [151, 152]

        def keyed(value):
            return {str(issue): copy.deepcopy(value) for issue in issues}

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); run_id = "dispatch-wire"
            bound = {issue: self.issue_contract(issue, str(root / f"worktree-{issue}"))
                     for issue in issues}
            initialized = subprocess.run(
                [sys.executable, str(WORKFLOW), "init-run", "--repo-root", str(root),
                 "--run-id", run_id, "--now", NOW], capture_output=True, check=False)
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            request = {"interface_version": 2, "now": NOW, "max_parallel": 2,
                "attempt_budget_minutes": 30, "human_directed": True, "issues": issues,
                "tracker": [{"issue": issue, "state": "open", "open_blockers": [],
                             "decision_blockers": []} for issue in issues],
                "owners": [],
                "worktrees": [{"issue": issue, "recorded": None, "candidate": {
                    "path": str(root / f"worktree-{issue}"), "state": "absent"}}
                    for issue in issues],
                "forge": keyed({"state": "none", "url": None, "merge_sha": None}),
                "delivery_contracts": {str(issue): bound[issue][0] for issue in issues},
                "authorization_intents": {str(issue): [bound[issue][1]] for issue in issues},
                "authority_observations": keyed([]), "reevaluation_evidence": keyed([]),
                "delivery_observations": keyed([]), "requested_scopes": keyed(None),
                "recoveries": keyed(None)}
            path = root / "control.json"; path.write_text(json.dumps(request))
            completed = subprocess.run(
                [sys.executable, str(WORKFLOW), "control", "--repo-root", str(root),
                 "--run-id", run_id, "--request-file", str(path)],
                capture_output=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            response = json.loads(completed.stdout)
            self.assertEqual([action["kind"] for action in response["actions"]],
                             ["spawn", "spawn", "wait"])
            self.assertEqual(response["actions"][-1]["wake_on"],
                             ["deadline", "owner_notification", "tracker_change"])
            # Two dispatched contracts already outgrow the owner phase-report bound.
            policy = json.loads(POLICY.read_text(encoding="utf-8"))
            self.assertGreater(len(completed.stdout), policy["phase_reports"]["wire_max_bytes"])
            validated = subprocess.run(
                [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
                 "workflow-response", "--input", "-", "--policy", str(POLICY)],
                input=completed.stdout, capture_output=True, check=False)
            self.assertEqual((validated.returncode, validated.stderr), (0, b""))
            self.assertEqual(validated.stdout, completed.stdout)


class BuilderHarness:
    """One synthetic resolvable project and a CLI driver shared by builder-backed tests."""

    def project(self, mutate=None):
        self.home = make_home()
        self.addCleanup(shutil.rmtree, self.home, True)
        contract = source_contract()
        if mutate is not None:
            mutate(contract)
        self.root = make_project_root(contract)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.worktree = str(self.root / ".worktrees" / WORKTREE_NAME)
        return self.root

    def cli(self, *args, stdin=None, ok=True):
        completed = subprocess.run(
            [sys.executable, str(WORKFLOW), *map(str, args)], input=stdin,
            capture_output=True, check=False,
            env={**os.environ, "HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"})
        if ok:
            self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        return completed

    def build(self, kind, value, *, ok=True):
        completed = self.cli("build-delivery", "--repo-root", self.root, "--kind", kind,
                             "--input", "-", stdin=json.dumps(value).encode(), ok=ok)
        return json.loads(completed.stdout) if ok else completed

    def resolver_refusal_line(self, root, label):
        """The builder's exact stderr when the resolver refuses at `root` (D1, D8).

        The resolver runs directly on the same root and HOME, so the expected
        bytes are the resolver's own stdout, never a literal.
        """
        code, stdout, stderr = run_resolver("resolve", "--repo-root", str(root),
                                            home=self.home)
        self.assertEqual(code, 2, stderr)
        return (f"workflow-state: resolve-project refused at {label}: "
                + stdout.removesuffix("\n") + "\n").encode()

    def contract_input(self, **changes):
        value = {"issue": 171, "worktree": self.worktree, "source_kind": "explicit_user",
                 "source_reference": "invocation:/from-issue 171 --auto", "now": NOW}
        value.update(changes)
        return value

    def direct_request(self, **changes):
        value = {"interface_version": 2, "issue": 171, "now": NOW,
            "attempt_budget_minutes": 30, "new_run": False, "owner_unavailable": False,
            "tracker": None, "worktree": None, "forge": None, "delivery_contract": None,
            "authorization_intents": [], "authority_observations": [],
            "reevaluation_evidence": [], "delivery_observations": [],
            "requested_scope": None, "recovery": None}
        value.update(changes)
        return value

    def acquire(self, contract, intent):
        request = self.direct_request(
            tracker={"issue": 171, "state": "open", "open_blockers": [],
                     "decision_blockers": []},
            forge={"state": "none", "url": None, "merge_sha": None},
            worktree={"issue": 171, "recorded": None,
                      "candidate": {"path": self.worktree, "state": "absent"}},
            delivery_contract=contract, authorization_intents=[intent])
        owner = json.loads(self.cli("direct-owner", "--repo-root", self.root,
            "--request-file", "-", stdin=json.dumps(request).encode()).stdout)
        self.assertEqual((owner["kind"], owner["worktree"]), ("owner", self.worktree))
        return owner

    def control_request(self, issues, *, now=NOW, contracts=None, intents=None,
                        worktrees=(), forge=None, max_parallel=2):
        def keyed(value):
            return {str(issue): copy.deepcopy(value) for issue in issues}
        return {"interface_version": 2, "now": now, "max_parallel": max_parallel,
            "attempt_budget_minutes": 30, "human_directed": True, "issues": list(issues),
            "tracker": [{"issue": issue, "state": "open", "open_blockers": [],
                         "decision_blockers": []} for issue in issues],
            "owners": [], "worktrees": list(worktrees),
            "forge": forge or keyed({"state": "none", "url": None, "merge_sha": None}),
            "delivery_contracts": contracts or keyed(None),
            "authorization_intents": intents or keyed([]),
            "authority_observations": keyed([]), "reevaluation_evidence": keyed([]),
            "delivery_observations": keyed([]), "requested_scopes": keyed(None),
            "recoveries": keyed(None)}


class DeliveryBuilderTest(BuilderHarness, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load(MODEL, "delivery_model_builder", package=True)

    def validate(self, value, kind):
        return self.model.validate_delivery_object(
            value, expected_kind=kind, notes_max_characters=500)

    def test_contract_is_deterministic_policy_derived_and_valid(self):
        self.project()
        raw = json.dumps(self.contract_input()).encode()
        path = self.root / "contract-input.json"; path.write_bytes(raw)
        first = self.cli("build-delivery", "--repo-root", self.root, "--kind", "contract",
                         "--input", "-", stdin=raw)
        second = self.cli("build-delivery", "--repo-root", self.root, "--kind", "contract",
                          "--input", path)
        self.assertEqual(first.stdout, second.stdout)
        built = json.loads(first.stdout)
        self.assertEqual(first.stdout, self.model.canonical_bytes(built))
        self.assertEqual(set(built), {"contract", "initial_intent"})
        contract, initial = built["contract"], built["initial_intent"]
        self.validate(contract, "delivery-contract"); self.validate(initial, "authorization-intent")
        self.assertEqual(contract["initial_authorization_intent_id"], initial["id"])
        self.assertEqual(contract["initial_authorization_intent_digest"],
                         self.model.canonical_digest(initial))
        self.assertEqual([stage["id"] for stage in contract["stages"]], [
            "select_reviewed_output", "publish_branch", "open_pr", "merge_pr",
            "close_tracker", "delete_remote_branch", "remove_worktree",
            "delete_local_branch"])
        constraints = contract["stages"][0]["target_ref"]["constraints"]
        self.assertEqual((constraints["branch"], constraints["base"]), (WORKTREE_NAME, "main"))
        literals = {stage["id"]: stage["target_ref"].get("value") for stage in contract["stages"]}
        self.assertEqual((literals["close_tracker"], literals["remove_worktree"],
                          literals["delete_local_branch"]), ("171", self.worktree, WORKTREE_NAME))
        self.assertEqual(set(contract["deliverable"]["obligations"].values()), {"required"})
        self.assertEqual(len(initial["scopes"]), 8)
        self.assertEqual((initial["source"]["kind"], initial["revocation_key"]),
                         ("explicit_user", f"fagenorn/nix-config#171@{NOW}"))

        def keep_remote(contract_value):
            contract_value["bindings"]["vcs"]["merge"]["delete_branch"] = False
        self.project(keep_remote)
        stages = self.build("contract", self.contract_input())["contract"]["stages"]
        self.assertNotIn("delete_remote_branch", [stage["id"] for stage in stages])

    def test_provenance_digest_seals_the_seven_authored_policy_members(self):
        self.project()
        value = self.contract_input()
        contract = self.build("contract", value)["contract"]
        authored = source_contract()
        vcs, tracker = authored["bindings"]["vcs"], authored["bindings"]["tracker"]
        self.assertEqual(contract["provenance"]["digest"], self.model.canonical_digest({
            "policy": {"project_id": authored["project"]["id"],
                       "tracker_kind": tracker["kind"],
                       "repository_slug": tracker["repo_slug"],
                       "branch_pattern": vcs["branch_pattern"],
                       "worktree_prefix": vcs["worktree"]["prefix"],
                       "integration_branch": vcs["integration_branch"],
                       "delete_branch": vcs["merge"]["delete_branch"]},
            "issue": 171, "worktree": self.worktree,
            "source": {"kind": value["source_kind"], "reference": value["source_reference"]}}))

    def test_contract_refusals_exit_two_with_empty_stdout(self):
        def gitlab(contract_value):
            contract_value["bindings"]["tracker"]["kind"] = "gitlab"
        cases = (("non-github tracker", gitlab, {}, b"tracker kind"),
                 ("foreign issue branch", None, {"worktree": "/wt/issue-172-other"},
                  b"branch pattern"),
                 ("unpatterned branch", None, {"worktree": "/wt/feature-171"},
                  b"branch pattern"),
                 ("relative worktree", None, {"worktree": "wt/" + WORKTREE_NAME},
                  b"worktree must be absolute"),
                 ("parent handoff", None, {"source_kind": "parent_handoff"}, b"source kind"),
                 ("unknown key", None, {"extra": True}, b"builder input keys"))
        for label, mutate, changes, reason in cases:
            with self.subTest(label=label):
                self.project(mutate)
                refused = self.build("contract", self.contract_input(**changes), ok=False)
                self.assertEqual((refused.returncode, refused.stdout), (2, b""))
                self.assertIn(reason, refused.stderr)
        self.project()
        missing = self.contract_input(); missing.pop("now")
        for kind, value, reason in (("contract", missing, b"builder input keys"),
                                    ("nonsense", self.contract_input(), b"invalid choice")):
            with self.subTest(kind=kind):
                refused = self.build(kind, value, ok=False)
                self.assertEqual((refused.returncode, refused.stdout), (2, b""))
                self.assertIn(reason, refused.stderr)

    def test_resolver_refusal_relays_the_resolver_document_exactly(self):
        def two_violations(contract_value):
            del contract_value["bindings"]["tracker"]["repo_slug"]
            contract_value["bindings"]["vcs"]["merge"]["delete_branch"] = "yes"

        def future_schema(contract_value):
            contract_value["schema_version"] = 2

        prefix = b"workflow-state: resolve-project refused at repo-root: "
        for label, mutate, code, pointers in (
                ("two ordered violations", two_violations, "invalid_contract",
                 ["/bindings/tracker/repo_slug", "/bindings/vcs/merge/delete_branch"]),
                ("reason code", future_schema, "unsupported_schema", ["/schema_version"])):
            with self.subTest(label=label):
                self.project(mutate)
                expected = self.resolver_refusal_line(self.root, "repo-root")
                refused = self.build("contract", self.contract_input(), ok=False)
                self.assertEqual((refused.returncode, refused.stdout, refused.stderr),
                                 (2, b"", expected))
                error = json.loads(refused.stderr.removeprefix(prefix))["error"]
                self.assertEqual(
                    (error["code"], [item["pointer"] for item in error["violations"]],
                     "reason_code" in error),
                    (code, pointers, code == "unsupported_schema"))

    def test_scope_and_initial_intent_regenerate_from_the_contract(self):
        self.project()
        built = self.build("contract", self.contract_input())
        contract, initial = built["contract"], built["initial_intent"]
        self.assertEqual(self.build("initial-intent", {"contract": contract}), initial)
        declared = {item["id"]: item for item in initial["scopes"]}
        for stage in contract["stages"]:
            scope = self.build("scope", {"contract": contract, "stage_id": stage["id"]})
            with self.subTest(stage=stage["id"]):
                self.assertEqual(declared[scope["id"]], scope)
                self.assertEqual((scope["action"], scope["effect"], scope["risk"]),
                                 (stage["action"], stage["effect"], stage["effect"]))
                self.assertEqual(scope["principal"], {
                    "kind": "issue_owner", "stable_id": "fagenorn/nix-config#171"})
                self.assertEqual(scope["target"]["pr_ref"], (
                    {"kind": "slot", "slot_id": "reviewed"}
                    if stage["kind"] in {"open_pr", "merge_pr"} else {"kind": "none"}))
        tampered = copy.deepcopy(contract)
        tampered["provenance"]["created_at"] = "2026-09-22T00:00:00Z"
        for kind, value, reason in (
                ("initial-intent", {"contract": tampered}, b"derived intent"),
                ("scope", {"contract": tampered, "stage_id": "merge_pr"}, b"derived intent"),
                ("scope", {"contract": contract, "stage_id": "unknown"}, b"unknown stage")):
            with self.subTest(kind=kind, stage=value.get("stage_id")):
                refused = self.build(kind, value, ok=False)
                self.assertEqual((refused.returncode, refused.stdout), (2, b""))
                self.assertIn(reason, refused.stderr)

    def test_authorization_chain_seals_the_handoff_chain_digest(self):
        self.project()
        built = self.build("contract", self.contract_input())
        value = {"contract": built["contract"], "authorization_intents": [built["initial_intent"]]}
        sealed = self.cli("build-delivery", "--repo-root", self.root, "--kind",
                          "authorization-chain", "--input", "-",
                          stdin=json.dumps(value).encode()).stdout
        ids = ('{"intent_ids":["%s"]}\n' % built["initial_intent"]["id"]).encode()
        self.assertEqual(sealed, b'{"authorization_chain_digest":"sha256:%s"}\n'
                         % hashlib.sha256(ids).hexdigest().encode())
        stray = self.build("contract", self.contract_input(now="2026-09-22T00:00:00Z"))
        refused = self.build("authorization-chain", {**value,
            "authorization_intents": [stray["initial_intent"]]}, ok=False)
        self.assertEqual((refused.returncode, refused.stdout), (2, b""))
        self.assertIn(b"authorization chain", refused.stderr)


class HelperInputTest(BuilderHarness, unittest.TestCase):
    def pipe(self, boundary, raw):
        completed = subprocess.run(
            [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
             boundary, "--input", "-", "--policy", str(POLICY)],
            input=raw, capture_output=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout

    def assert_parity(self, state, args, flag, raw, piped=None):
        """The path form and the stdin form leave identical stdout and ledger bytes."""
        before = state.read_bytes()
        path = self.root / f"{flag.strip('-')}.json"; path.write_bytes(raw)
        by_path = self.cli(*args, flag, path)
        after = state.read_bytes(); state.write_bytes(before)
        by_stdin = self.cli(*args, flag, "-", stdin=raw if piped is None else piped)
        self.assertEqual((by_stdin.stdout, state.read_bytes()), (by_path.stdout, after))
        return by_stdin.stdout

    def test_every_input_flag_reads_stdin_and_refuses_relative_paths(self):
        self.project()
        run = ("--repo-root", self.root, "--run-id", "inputs")
        for command in (("control", *run, "--request-file"),
                        ("direct-owner", "--repo-root", self.root, "--request-file"),
                        ("checkpoint-delivery", *run, "--now", NOW, "--checkpoint-file"),
                        ("finish", *run, "--now", NOW, "--summary-file"),
                        ("finish", *run, "--now", NOW, "--issue", 151, "--attempt", 1,
                         "--result-file"),
                        ("build-delivery", "--repo-root", self.root, "--kind", "contract",
                         "--input")):
            with self.subTest(command=command[0], flag=command[-1]):
                refused = self.cli(*command, "relative.json", ok=False)
                self.assertEqual(refused.returncode, 2)
                self.assertIn(b"file path must be absolute", refused.stderr)

        self.cli("init-run", *run, "--now", NOW)
        state = self.root / ".superpowers/workflows/inputs/state.json"
        candidate = {"issue": 151, "recorded": None, "candidate": {
            "path": str(self.root / ".worktrees/worktree-issue-151-inputs"), "state": "absent"}}
        stdout = self.assert_parity(state, ("control", *run), "--request-file", json.dumps(
            self.control_request([151], worktrees=[candidate])).encode())
        self.assertEqual(self.pipe("workflow-response", stdout), stdout)

        built = self.build("contract", self.contract_input())
        request = {"interface_version": 2, "issue": 171, "now": NOW,
            "attempt_budget_minutes": 30, "new_run": False, "owner_unavailable": False,
            "tracker": {"issue": 171, "state": "open", "open_blockers": [],
                        "decision_blockers": []},
            "worktree": {"issue": 171, "recorded": None,
                         "candidate": {"path": self.worktree, "state": "absent"}},
            "forge": {"state": "none", "url": None, "merge_sha": None},
            "delivery_contract": built["contract"],
            "authorization_intents": [built["initial_intent"]],
            "authority_observations": [], "reevaluation_evidence": [],
            "delivery_observations": [], "requested_scope": None, "recovery": None}
        owner = json.loads(self.cli("direct-owner", "--repo-root", self.root,
                                    "--request-file", "-",
                                    stdin=json.dumps(request).encode()).stdout)
        historical = {"issue": 171, "state": "failed", "pr_url": None, "merge_sha": None,
            "issue_closed": False, "discussion_items": [], "detail_state": "none",
            "report_path": None, "notes": "failed"}
        summary = json.dumps({"interface_version": 2, "issue": 171,
            "state": "terminal_failed", "custody": owner["custody"],
            "historical_owner_result": historical,
            "delivery_contract_digest": owner["contract_digest"],
            "delivery_observations": [], "authority_observations": [],
            "reevaluation_evidence": [], "detail_state": "none",
            "report_path": None, "notes": "failed"}).encode()
        direct_state = self.root / f".superpowers/workflows/{owner['run_id']}/state.json"
        self.assert_parity(direct_state, ("finish", "--repo-root", self.root, "--run-id",
                           owner["run_id"], "--now", LATER), "--summary-file", summary,
                           piped=self.pipe("ship-summary", summary))

        workflow = load(WORKFLOW, "workflow_state_inputs")
        legacy = workflow.new_run_state(run_id="legacy-inputs", now=NOW, issues={})
        legacy["schema_version"] = 2
        legacy["issues"]["151"] = {"issue": 151, "outcome": None, "attempts": [
            workflow.new_control_attempt(issue=151, attempt_number=1,
                worktree=str(self.root / "wt-151"), now=NOW,
                deadline_at="2026-09-21T01:00:00Z")]}
        legacy_state = self.root / ".superpowers/workflows/legacy-inputs/state.json"
        legacy_state.parent.mkdir(parents=True)
        legacy_state.write_text(json.dumps(legacy), encoding="utf-8")
        self.assert_parity(legacy_state, ("finish", "--repo-root", self.root, "--run-id",
                           "legacy-inputs", "--now", LATER, "--issue", 151, "--attempt", 1),
                           "--result-file", json.dumps({**historical, "issue": 151}).encode())


URL = "https://github.com/fagenorn/nix-config/pull/5"
SOURCES = {"selected_output": "repository", "branch_published": "repository",
           "pr_opened": "provider", "pr_merged": "provider", "tracker_closed": "tracker",
           "remote_branch_absent": "repository", "worktree_absent": "filesystem",
           "local_branch_absent": "repository", "implementation_delivered": "repository",
           "cleanup_complete": "filesystem"}


class DeliveryLoopTest(BuilderHarness, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load(MODEL, "delivery_model_loop", package=True)

    def observed(self, kind, **facts):
        return self.build("observation", {"contract": self.contract, "observation_kind": kind,
            "source_kind": SOURCES[kind], "source_reference": f"probe:{kind}",
            "observed_at": NOW, "evidence": f"{kind} evidence", **facts})

    def checkpoint(self, observations, authority, scope, *, ok=True):
        value = {"interface_version": 2, "issue": 171, "custody": self.custody,
            "contract_digest": self.digest,
            "delivery_observations": sorted(observations, key=lambda item: item["id"]),
            "authority_observations": authority, "reevaluation_evidence": [],
            "requested_scope": scope, "detail_state": "none", "report_path": None,
            "notes": ""}
        completed = self.cli("checkpoint-delivery", *self.run_args, "--now", LATER,
                             "--checkpoint-file", "-",
                             stdin=self.validated("ship-checkpoint", value), ok=ok)
        return json.loads(completed.stdout) if ok else completed

    def validated(self, boundary, value):
        """Pipe one wire object through artifact-budget, as an owner must, and return its bytes."""
        completed = subprocess.run(
            [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
             boundary, "--input", "-", "--policy", str(POLICY)],
            input=json.dumps(value).encode(), capture_output=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout

    def handoff(self, owner, intent):
        """The Phase-7 ship-handoff/v2 a first ship receives, with realistic artifacts."""
        def artifact(kind, path, size):
            return {"kind": kind, "path": path, "budget_status": "within_budget",
                    "metrics": {"root_bytes": size, "total_bytes": size, "file_count": 1,
                                "largest_member_bytes": size}}
        return {"interface_version": 2, "state": "complete",
            "ledger_repo_root": str(self.root), "run_id": owner["run_id"],
            "owner": owner["owner"], "owner_worktree": self.worktree,
            "custody": self.custody, "issue_number": 171, "branch": WORKTREE_NAME,
            "worktree_path": self.worktree,
            "spec_artifact": artifact("design-spec",
                ".claude/specs/2026-09-23-issue-171-delivery-contract-source-design.md", 47301),
            "plan_artifact": artifact("implementation-plan",
                ".claude/plans/2026-09-24-issue-171-delivery-contract-source.md", 8375),
            "head_sha": "a" * 40, "review_state": "clean", "auto": True,
            "report_path": None, "notes": "", "delivery_contract": self.contract,
            "delivery_contract_digest": self.digest, "authorization_intents": [intent],
            "authorization_chain_digest": self.model.canonical_digest(
                {"intent_ids": [intent["id"]]}),
            "authority_observation_ids": [], "reevaluation_evidence_ids": [],
            "authority_evaluation_consumption_ids": [],
            "pending_stage_ids": [stage["id"] for stage in self.contract["stages"]],
            "selected_outputs": [], "requested_scope": None}

    def deliver(self, proposed):
        """Drive one implementation custody through every stage with builder outputs only."""
        self.project()
        built = self.build("contract", self.contract_input())
        self.contract = built["contract"]; self.digest = self.model.canonical_digest(self.contract)
        owner = self.acquire(self.contract, built["initial_intent"])
        self.custody = owner["custody"]
        self.run_args = ("--repo-root", self.root, "--run-id", owner["run_id"])
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        handed = self.validated("ship-handoff", self.handoff(owner, built["initial_intent"]))
        # A real handoff outgrows the phase-report bound; that is why D28 moves it.
        self.assertGreater(len(handed), policy["phase_reports"]["wire_max_bytes"])
        self.assertLessEqual(len(handed), policy["workflow_responses"]["wire_max_bytes"])
        state = self.root / f".superpowers/workflows/{owner['run_id']}/state.json"
        head, merge_sha = "a" * 40, "b" * 40
        selection = self.build("selected-output", {"contract": self.contract, "head": head,
            "tree": "c" * 40, "acceptance_ref": ".claude/specs/issue-171.md",
            "review_ref": "clean", "test_ref": "checks"})
        self.assertEqual(selection["test_evidence_ids"], [f"test:checks@{head}"])
        facts = {"select_reviewed_output": [self.observed("selected_output", selection=selection)],
            "publish_branch": [self.observed("branch_published", head=head)],
            "open_pr": [self.observed("pr_opened", pr_number=5, pr_url=URL, head=head)],
            "merge_pr": [self.observed("pr_merged", pr_number=5, pr_url=URL, head=head,
                                       merge_sha=merge_sha)],
            "close_tracker": [self.observed("tracker_closed", close_reason="completed",
                                            observation_identity="github:issue:171:closed")],
            "delete_remote_branch": [self.observed("remote_branch_absent")],
            "remove_worktree": [self.observed("worktree_absent")],
            "delete_local_branch": [self.observed("local_branch_absent")]}
        pending, authority = [], []
        for stage in self.contract["stages"]:
            if stage["id"] in proposed:
                scope = self.build("scope", {"contract": self.contract, "stage_id": stage["id"]})
                echoed = self.checkpoint(pending, authority, scope)
                self.assertEqual((echoed["kind"], echoed["requested_scope"]),
                                 ("delivery_checkpointed", scope))
                self.assertEqual(echoed["requirements"], [{"kind": "observation",
                    "subject_id": scope["id"], "reason_code": "native_evaluation_required",
                    "detail_pointer": None}])
                pending, authority = [], [self.build("authority-observation", {
                    "contract": self.contract, "scope_id": scope["id"],
                    "launch_id": self.custody["action_id"], "authority_kind": "native_guard",
                    "verdict": "allowed", "reason_code": "guard_allowed",
                    "observed_at": LATER, "evidence": stage["id"]})]
                if stage["id"] == "merge_pr":
                    before = state.read_bytes()
                    second = self.observed("pr_opened", pr_number=6, pr_url=URL + "6", head=head)
                    refused = self.checkpoint([second], [], None, ok=False)
                    self.assertEqual((refused.returncode, state.read_bytes()), (2, before))
            pending += facts[stage["id"]]
        by_kind = {item["observation_kind"]: item["id"] for items in facts.values() for item in items}
        completing = pending + [
            self.observed("implementation_delivered", selection=selection, merge_sha=merge_sha,
                          integrated_ref="refs/heads/main",
                          merge_observation_id=by_kind["pr_merged"]),
            self.observed("cleanup_complete",
                          remote_branch_observation_ids=[by_kind["remote_branch_absent"]],
                          local_branch_observation_ids=[by_kind["local_branch_absent"]],
                          worktree_observation_ids=[by_kind["worktree_absent"]],
                          detail_pointer=".superpowers/issue-delivery/171/detail.json",
                          read_evidence="detail read")]
        historical = {"issue": 171, "state": "merged", "pr_url": URL, "merge_sha": merge_sha,
            "issue_closed": True, "discussion_items": [], "detail_state": "none",
            "report_path": None, "notes": "delivered"}
        summary = {"interface_version": 2, "issue": 171, "state": "delivery_complete",
            "custody": self.custody, "historical_owner_result": historical,
            "delivery_contract_digest": self.digest,
            "delivery_observations": sorted(completing, key=lambda item: item["id"]),
            "authority_observations": authority, "reevaluation_evidence": [],
            "detail_state": "none", "report_path": None, "notes": "delivered"}
        validated = self.validated("ship-summary", summary)
        self.assertLessEqual(len(validated), policy["phase_reports"]["wire_max_bytes"])
        finished = json.loads(self.cli("finish", *self.run_args, "--now", LATER,
            "--summary-file", "-", stdin=validated).stdout)
        self.assertEqual((finished["kind"], finished["pending_stage_ids"]),
                         ("delivery_complete", []))
        stored = json.loads(state.read_text(encoding="utf-8"))["issues"]["171"]
        self.assertEqual(len(stored["delivery"]["authorization_intents"]), 1)
        self.assertEqual(stored["attempts"][-1]["state"], "merged")

    def test_every_builder_scope_is_covered_when_its_stage_is_ready(self):
        self.deliver({"select_reviewed_output", "publish_branch", "open_pr", "merge_pr",
                      "close_tracker", "delete_remote_branch", "remove_worktree",
                      "delete_local_branch"})

    def test_one_custody_completes_the_selection_gated_loop(self):
        self.deliver({"merge_pr", "close_tracker", "remove_worktree", "delete_local_branch"})

    def test_evidence_kinds_are_exact_and_closed(self):
        self.project()
        self.contract = self.build("contract", self.contract_input())["contract"]
        opened = self.observed("pr_opened", pr_number=5, pr_url=URL, head="a" * 40)
        self.assertEqual(opened["subject"], {"provider_repository_id": "fagenorn/nix-config",
            "pr_number": 5, "pr_url": URL, "expected_head": "a" * 40, "base": "main"})
        self.assertEqual(opened["evidence_digest"],
            "sha256:" + hashlib.sha256(b"pr_opened evidence").hexdigest())
        gone = self.observed("worktree_absent")["subject"]
        self.assertEqual(gone, {"path": self.worktree, "recorded_worktree_identity":
            self.worktree, "probe_mode": "no_follow", "absent": True})
        base = {"contract": self.contract, "source_kind": "provider",
                "source_reference": "probe", "observed_at": NOW, "evidence": "x"}
        for kind, value, reason in (
                ("observation", {**base, "observation_kind": "repository_record_proposed"},
                 b"unsupported observation kind"),
                ("observation", {**base, "observation_kind": "pr_opened", "pr_number": 5},
                 b"builder input keys"),
                ("observation", {**base, "observation_kind": "worktree_absent", "path": "/x"},
                 b"builder input keys"),
                ("authority-observation", {"contract": self.contract, "scope_id": "sha256:" + "0" * 64,
                    "launch_id": "171:1:1", "authority_kind": "host", "verdict": "allowed",
                    "reason_code": "r", "observed_at": NOW, "evidence": "x"},
                 b"unknown scope"),
                ("authority-observation", {"contract": self.contract,
                    "scope_id": self.build("scope", {"contract": self.contract,
                                                     "stage_id": "merge_pr"})["id"],
                    "launch_id": None, "authority_kind": "intent_revocation",
                    "verdict": "revoked", "reason_code": "r", "observed_at": NOW,
                    "evidence": "x"},
                 b"unsupported authority kind")):
            with self.subTest(kind=kind, variant=value.get("observation_kind") or value.get("authority_kind")):
                refused = self.build(kind, value, ok=False)
                self.assertEqual((refused.returncode, refused.stdout), (2, b""))
                self.assertIn(reason, refused.stderr)


TRACKER = {"issue": 171, "state": "open", "open_blockers": [], "decision_blockers": []}
NO_PR = {"state": "none", "url": None, "merge_sha": None}
CONTRACT_REQUIRED = [{"kind": "delivery_contract", "subject_id": "171",
                      "reason_code": "delivery_contract_required", "detail_pointer": None}]


class ContractLifecycleTest(BuilderHarness, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load(MODEL, "delivery_model_lifecycle", package=True)
        cls.workflow = load(WORKFLOW, "workflow_state_lifecycle")

    def direct(self, *, ok=True, **changes):
        completed = self.cli("direct-owner", "--repo-root", self.root, "--request-file", "-",
            stdin=json.dumps(self.direct_request(**changes)).encode(), ok=ok)
        return json.loads(completed.stdout) if ok else completed

    def control(self, run_id, request, *, ok=True):
        completed = self.cli("control", "--repo-root", self.root, "--run-id", run_id,
            "--request-file", "-", stdin=json.dumps(request).encode(), ok=ok)
        return json.loads(completed.stdout) if ok else completed

    def write_run(self, run_id, attempts, *, schema=3):
        state = self.workflow.new_run_state(run_id=run_id, now=NOW, issues={})
        issue = {"issue": attempts[0]["issue"], "attempts": attempts,
                 "outcome": attempts[-1]["result"]}
        if schema == 3:
            issue.update(delivery=self.workflow._delivery().empty_delivery(),
                         delivery_remainders=[])
        state["schema_version"] = schema
        state["issues"][str(issue["issue"])] = issue
        path = self.root / f".superpowers/workflows/{run_id}/state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
        (path.parent / "state.lock").touch()
        return path

    def attempt(self, issue, number=1, **changes):
        value = self.workflow.new_control_attempt(issue=issue, attempt_number=number,
            worktree=self.worktree, now=NOW, deadline_at="2026-09-21T01:00:00Z")
        value.update(changes)
        return value

    def direct_runs(self, issue):
        return sorted((self.root / ".superpowers/workflows").glob(f"direct-{issue}-*"))

    def test_direct_acquisition_asks_for_the_contract_last(self):
        self.project()
        facts = {}
        for key, value, expected in (("tracker", TRACKER, [{"kind": "tracker"}]),
                ("forge", NO_PR, [{"kind": "forge_pr", "path": "issue-171-"}]),
                ("worktree", {"issue": 171, "recorded": None, "candidate": {
                    "path": self.worktree, "state": "absent"}}, [{"kind": "candidate_worktree"}])):
            response = self.direct(**facts)
            self.assertEqual((response["kind"], response["requirements"]), ("observe", expected))
            facts[key] = value
        self.assertEqual(self.direct(**facts), {"interface_version": 2, "kind": "observe",
            "issue": 171, "run_id": None, "requirements": CONTRACT_REQUIRED})
        self.assertEqual(self.direct_runs(171), [])
        other = self.build("contract", self.contract_input(
            worktree=str(self.root / ".worktrees/worktree-issue-171-other")))
        refused = self.direct(ok=False, delivery_contract=other["contract"],
                              authorization_intents=[other["initial_intent"]], **facts)
        self.assertEqual((refused.returncode, self.direct_runs(171)), (2, []))
        built = self.build("contract", self.contract_input())
        owner = self.direct(delivery_contract=built["contract"],
                            authorization_intents=[built["initial_intent"]], **facts)
        self.assertEqual((owner["kind"], owner["worktree"], owner["contract"]),
                         ("owner", self.worktree, built["contract"]))
        self.cli("suspend", "--repo-root", self.root, "--run-id", owner["run_id"], "--now",
                 LATER, "--issue", 171, "--attempt", 1, "--blocked-on", "usage_limit")
        resumed = self.direct(now=LATER, tracker=TRACKER, forge=NO_PR, worktree={
            "issue": 171, "recorded": {"path": self.worktree,
                                       "state": "matching_issue_branch"}, "candidate": None})
        self.assertEqual((resumed["kind"], resumed["launch_kind"], resumed["contract_digest"]),
                         ("owner", "resume", owner["contract_digest"]))

    def test_contractless_direct_runs_replay_and_reconcile_without_a_contract(self):
        self.project()
        merged = self.workflow.reconciled_result(172, "https://example.invalid/pr/1", "b" * 40)
        self.write_run("direct-172-000001", [self.attempt(172, state="merged", result=merged,
            result_source="superseded", finished_at=NOW)], schema=2)
        replay = self.direct(issue=172)
        self.assertEqual((replay["kind"], replay["reason"], replay["result"]),
                         ("terminal", "merged", merged))
        suspended = self.attempt(173)
        self.workflow.suspend_attempt(suspended, blocked_on="external", now=NOW)
        path = self.write_run("direct-173-000001", [suspended], schema=2)
        recorded = {"issue": 173, "recorded": {"path": self.worktree,
                    "state": "matching_issue_branch"}, "candidate": None}
        tracker = {**TRACKER, "issue": 173}
        waiting = self.direct(issue=173, tracker=tracker, forge=NO_PR, worktree=recorded)
        self.assertEqual((waiting["run_id"], waiting["requirements"][0]["kind"]),
                         ("direct-173-000001", "delivery_contract"))
        pr = {"state": "merged", "url": "https://example.invalid/pr/2", "merge_sha": "c" * 40}
        closed = self.direct(issue=173, tracker=tracker, forge=pr, worktree=recorded)
        self.assertEqual((closed["kind"], closed["reason"]), ("terminal", "merged"))
        stored = json.loads(path.read_text())["issues"]["173"]
        self.assertEqual((stored["attempts"][0]["result_source"], stored["delivery"]["contract"]),
                         ("superseded", None))

    def test_control_installs_a_built_contract_only_at_spawn_and_keeps_it(self):
        self.project()
        self.cli("init-run", "--repo-root", self.root, "--run-id", "orch", "--now", NOW)
        built = self.build("contract", self.contract_input())
        digest = self.model.canonical_digest(built["contract"])
        spawned = self.control("orch", self.control_request([171],
            contracts={"171": built["contract"]}, intents={"171": [built["initial_intent"]]},
            worktrees=[{"issue": 171, "recorded": None, "candidate": {
                "path": self.worktree, "state": "absent"}}]))
        action = spawned["actions"][0]
        self.assertEqual((action["kind"], action["contract"], action["worktree"]),
                         ("spawn", built["contract"], self.worktree))
        boot = json.loads(self.cli("init-run", "--repo-root", self.root, "--run-id", "orch",
                                   "--now", LATER).stdout)
        self.assertEqual([item["contract_digest"] for item in boot["requirements"]], [digest])
        governed = self.control("orch", self.control_request([171], now=LATER))
        self.assertEqual(governed["summaries"][0]["contract_digest"], digest)
        state = self.root / ".superpowers/workflows/orch/state.json"; before = state.read_bytes()
        other = self.build("contract", self.contract_input(now=LATER))
        refused = self.control("orch", self.control_request([171], now=LATER,
            contracts={"171": other["contract"]}, intents={"171": [other["initial_intent"]]}),
            ok=False)
        self.assertEqual((refused.returncode, state.read_bytes()), (2, before))

    def test_control_leaves_live_contractless_custody_idle(self):
        self.project()
        path = self.write_run("legacy", [self.attempt(171)])
        before = path.read_bytes()
        built = self.build("contract", self.contract_input())
        for label, contracts, intents in (("null", None, None), ("supplied",
                {"171": built["contract"]}, {"171": [built["initial_intent"]]})):
            with self.subTest(contract=label):
                raw = self.cli("control", "--repo-root", self.root, "--run-id", "legacy",
                    "--request-file", "-", stdin=json.dumps(self.control_request(
                        [171], now=LATER, contracts=contracts, intents=intents)).encode()).stdout
                response = json.loads(raw); summary = response["summaries"][0]
                self.assertEqual((summary["state"], summary["custody"]["action_id"],
                    summary["contract_digest"], summary["pending_stage_ids"],
                    summary["requirements"]), ("active", "171:1:1", None, [], []))
                self.assertEqual([(item["kind"], item.get("deadline_at"))
                                  for item in response["actions"]],
                                 [("wait", "2026-09-21T01:00:00Z")])
                self.assertEqual(path.read_bytes(), before)
                wire = subprocess.run([sys.executable, str(ARTIFACT_BUDGET), "validate-report",
                    "--boundary", "workflow-response", "--input", "-", "--policy", str(POLICY)],
                    input=raw, capture_output=True, check=False)
                self.assertEqual(wire.returncode, 0, wire.stderr)

    def test_contractless_refusal_is_lifecycle_only(self):
        self.project()
        failed = {"state": "failed", "result_source": "owner", "finished_at": NOW}
        path = self.write_run("refuse", [
            self.attempt(171, 1, result=self.workflow.terminal_result(171, "failed", "one"), **failed),
            self.attempt(171, 2, result=self.workflow.terminal_result(171, "failed", "two"), **failed)])
        response = self.control("refuse", self.control_request([171], now=LATER))
        # A terminal contractless issue is never asked for a contract (D31).
        self.assertEqual(response["summaries"][0]["requirements"], [])
        self.assertEqual([delta["kind"] for delta in response["deltas"]], ["retry_refused"])
        stored = json.loads(path.read_text())["issues"]["171"]
        self.assertEqual((stored["attempts"][-1]["result_source"], stored["delivery"]["contract"]),
                         ("refused", None))

    def failed_attempt(self, issue):
        return self.attempt(issue, state="failed", result_source="owner", finished_at=NOW,
                            result=self.workflow.terminal_result(issue, "failed", "one"))

    def test_contractless_retry_on_an_absent_path_asks_for_its_contract(self):
        """D34: the recorded path, not a candidate, makes a retry contract bindable."""
        self.project()
        path = self.write_run("retry", [self.failed_attempt(171)])
        state = json.loads(path.read_text())
        holder = self.workflow.new_control_attempt(issue=172, attempt_number=1,
            worktree=str(self.root / ".worktrees/holder"), now=NOW,
            deadline_at="2026-09-21T01:00:00Z")
        state["issues"]["172"] = {"issue": 172, "attempts": [holder], "outcome": None,
            "delivery": self.workflow._delivery().empty_delivery(), "delivery_remainders": []}
        path.write_text(json.dumps(state))
        absent = [{"issue": 171, "recorded": {"path": self.worktree, "state": "absent"},
                   "candidate": None}]
        built = self.build("contract", self.contract_input())
        supplied = {"contracts": {"171": built["contract"]},
                    "intents": {"171": [built["initial_intent"]]}}
        # Capacity 0: the retry is not planned, so nothing asks and nothing installs.
        before = path.read_bytes()
        starved = self.control("retry", self.control_request([171], now=LATER,
            worktrees=absent, max_parallel=1, **supplied))
        self.assertEqual(starved["summaries"][0]["requirements"], [])
        self.assertEqual(path.read_bytes(), before)
        # Capacity and no contract: the issue asks for it; the sweep is not refused.
        asked = self.control("retry", self.control_request([171], now=LATER,
            worktrees=absent))
        self.assertEqual((asked["summaries"][0]["contract_digest"],
                          asked["summaries"][0]["requirements"]),
                         (None, CONTRACT_REQUIRED))
        self.assertEqual([item for item in asked["actions"] if item.get("issue") == 171], [])
        self.assertEqual(path.read_bytes(), before)
        # The builder contract bound to the recorded path retries in place.
        retried = self.control("retry", self.control_request([171], now=LATER,
            worktrees=absent, **supplied))
        action = retried["actions"][0]
        self.assertEqual((action["kind"], action["attempt"], action["worktree"],
                          action["contract_digest"]),
                         ("retry", 2, self.worktree,
                          self.model.canonical_digest(built["contract"])))

    def test_contractless_direct_retry_on_an_absent_path_asks_for_its_contract(self):
        self.project()
        self.write_run("direct-171-000001", [self.failed_attempt(171)])
        facts = {"tracker": TRACKER, "forge": NO_PR, "worktree": {"issue": 171,
                 "recorded": {"path": self.worktree, "state": "absent"}, "candidate": None}}
        self.assertEqual(self.direct(**facts), {"interface_version": 2, "kind": "observe",
            "issue": 171, "run_id": "direct-171-000001", "requirements": CONTRACT_REQUIRED})
        built = self.build("contract", self.contract_input())
        owner = self.direct(delivery_contract=built["contract"],
                            authorization_intents=[built["initial_intent"]], **facts)
        self.assertEqual((owner["kind"], owner["launch_kind"], owner["attempt"],
                          owner["worktree"]), ("owner", "retry", 2, self.worktree))

    def mismatched(self, candidate):
        other = {"path": str(self.root / ".worktrees/worktree-issue-171-other"), "state": "absent"}
        return {"issue": 171, "recorded": {"path": self.worktree, "state": "mismatch"},
                "candidate": other if candidate else None}

    def assert_mismatch_refused(self, refused, path, before):
        self.assertEqual((refused.returncode, refused.stdout, path.read_bytes()), (2, b"", before))
        self.assertIn(b"recorded custody worktree does not match the issue branch", refused.stderr)

    def test_contractless_retry_on_a_mismatched_path_refuses_at_once(self):
        """D44: the contract bound to the recorded path could only refuse, so refuse now."""
        self.project()
        for candidate in (True, False):
            with self.subTest(lane="control", candidate=candidate):
                path = self.write_run("retry", [self.failed_attempt(171)])
                before = path.read_bytes()
                self.assert_mismatch_refused(self.control("retry", self.control_request(
                    [171], now=LATER, worktrees=[self.mismatched(candidate)]), ok=False),
                    path, before)
            with self.subTest(lane="direct", candidate=candidate):
                path = self.write_run("direct-171-000001", [self.failed_attempt(171)])
                before = path.read_bytes()
                self.assert_mismatch_refused(self.direct(ok=False, tracker=TRACKER, forge=NO_PR,
                    worktree=self.mismatched(candidate)), path, before)

    def test_contractless_new_run_on_a_mismatched_retained_path_refuses_at_once(self):
        self.project()
        path = self.write_run("direct-171-000001", [self.attempt(171, state="failed",
            result_source="refused", finished_at=NOW,
            result=self.workflow.terminal_result(171, "failed", "refused"))])
        before = path.read_bytes()
        for candidate in (True, False):
            with self.subTest(candidate=candidate):
                self.assert_mismatch_refused(self.direct(ok=False, new_run=True, tracker=TRACKER,
                    forge=NO_PR, worktree=self.mismatched(candidate)), path, before)
                self.assertEqual(self.direct_runs(171), [path.parent])

    def merged(self, issue):
        return {"issue": issue, "state": "merged", "pr_url": f"https://example.invalid/pr/{issue}",
                "merge_sha": "d" * 40, "issue_closed": True, "discussion_items": [],
                "detail_state": "none", "report_path": None, "notes": "merged"}

    def legacy_finish(self, run_id, issue, *, ok=True):
        return self.cli("finish", "--repo-root", self.root, "--run-id", run_id, "--now", LATER,
                        "--issue", issue, "--attempt", 1, "--result-file", "-",
                        stdin=json.dumps(self.merged(issue)).encode(), ok=ok)

    def test_legacy_finish_lands_only_on_contractless_issues(self):
        self.project()
        path = self.write_run("legacy-finish", [self.attempt(171)])
        persisted = json.loads(self.legacy_finish("legacy-finish", 171).stdout)
        stored = json.loads(path.read_text())["issues"]["171"]
        self.assertEqual((persisted, stored["outcome"], stored["attempts"][0]["state"],
                          stored["delivery"]["contract"]),
                         (self.merged(171), self.merged(171), "merged", None))
        self.cli("init-run", "--repo-root", self.root, "--run-id", "v2", "--now", NOW)
        built = self.build("contract", self.contract_input())
        self.control("v2", self.control_request([171], contracts={"171": built["contract"]},
            intents={"171": [built["initial_intent"]]}, worktrees=[{"issue": 171,
                "recorded": None, "candidate": {"path": self.worktree, "state": "absent"}}]))
        state = self.root / ".superpowers/workflows/v2/state.json"; before = state.read_bytes()
        refused = self.legacy_finish("v2", 171, ok=False)
        self.assertEqual((refused.returncode, state.read_bytes()), (2, before))
        self.assertIn(b"contracted issue", refused.stderr)

    def test_v1_owners_survive_the_migration_to_interface_two(self):
        self.project()
        state = self.workflow.new_run_state(run_id="survive", now=NOW, issues={})
        state["schema_version"] = 2
        for issue in (151, 152):
            state["issues"][str(issue)] = {"issue": issue, "outcome": None, "attempts": [
                self.workflow.new_control_attempt(issue=issue, attempt_number=1,
                    worktree=str(self.root / f"wt-{issue}"), now=NOW,
                    deadline_at="2026-09-21T01:00:00Z")]}
        path = self.root / ".superpowers/workflows/survive/state.json"
        path.parent.mkdir(parents=True); path.write_text(json.dumps(state), encoding="utf-8")
        run = ("--repo-root", self.root, "--run-id", "survive")
        boot = json.loads(self.cli("init-run", *run, "--now", NOW).stdout)
        self.assertEqual([(item["issue"], item["contract_digest"]) for item in boot["requirements"]],
                         [(151, None), (152, None)])
        self.assertEqual(json.loads(path.read_text())["schema_version"], 3)
        swept = self.control("survive", self.control_request([151, 152]))
        self.assertEqual([action["kind"] for action in swept["actions"]], ["wait"])
        self.cli("progress", *run, "--now", LATER, "--issue", 151, "--attempt", 1,
                 "--phase", 3, "--next-needs-context", "false",
                 "--artifacts-sufficient", "true", "--remainder-self-contained", "true")
        launch = json.loads(self.cli("check-launch", *run, "--action-id", "152:1:1").stdout)
        self.assertTrue(launch["current"])
        self.assertEqual(json.loads(self.legacy_finish("survive", 152).stdout), self.merged(152))
        summary = next(item for item in self.control("survive", self.control_request(
            [151, 152], now=LATER))["summaries"] if item["issue"] == 152)
        self.assertEqual((summary["state"], summary["result"]["state"]), ("merged", "merged"))

    MERGED_PR = {"state": "merged", "url": "https://example.invalid/pr/9", "merge_sha": "e" * 40}

    def forge_request(self, **changes):
        return self.control_request([171], now=LATER, forge={"171": self.MERGED_PR}, **changes)

    def failed_summary(self, custody_value, digest, observations=()):
        historical = {"issue": 171, "state": "failed", "pr_url": None, "merge_sha": None,
            "issue_closed": False, "discussion_items": [], "detail_state": "none",
            "report_path": None, "notes": "failed"}
        return {"interface_version": 2, "issue": 171, "state": "terminal_failed",
            "custody": custody_value, "historical_owner_result": historical,
            "delivery_contract_digest": digest,
            "delivery_observations": sorted(observations, key=lambda item: item["id"]),
            "authority_observations": [], "reevaluation_evidence": [],
            "detail_state": "none", "report_path": None, "notes": "failed"}

    def spawn_contracted(self, run_id):
        self.cli("init-run", "--repo-root", self.root, "--run-id", run_id, "--now", NOW)
        built = self.build("contract", self.contract_input())
        response = self.control(run_id, self.control_request([171],
            contracts={"171": built["contract"]}, intents={"171": [built["initial_intent"]]},
            worktrees=[{"issue": 171, "recorded": None,
                        "candidate": {"path": self.worktree, "state": "absent"}}]))
        return built["contract"], response["actions"][0]["custody"]

    def latest(self, path):
        return json.loads(path.read_text())["issues"]["171"]["attempts"][-1]

    def test_control_reconciles_a_merged_forge_only_without_live_custody(self):
        self.project()
        suspended = self.attempt(171)
        self.workflow.suspend_attempt(suspended, blocked_on="external", now=NOW)
        path = self.write_run("forge-suspended", [suspended])
        response = self.control("forge-suspended", self.forge_request())
        self.assertEqual([item["kind"] for item in response["actions"]], ["finalize"])
        self.assertEqual((self.latest(path)["state"], self.latest(path)["result_source"],
                          self.latest(path)["result"]["issue_closed"]),
                         ("merged", "superseded", False))
        report = ".superpowers/issue-delivery/171/run-1/ship-review.json"
        verdict = {"issue": 171, "state": "failed", "pr_url": None, "merge_sha": None,
            "issue_closed": False, "discussion_items": [], "detail_state": "present",
            "report_path": report, "notes": f"owner verdict; details: {report}"}
        path = self.write_run("forge-detail", [self.attempt(171, state="failed",
            result=verdict, result_source="owner", finished_at=NOW)])
        self.control("forge-detail", self.forge_request())
        self.assertEqual((self.latest(path)["result_source"],
                          self.latest(path)["result"]["report_path"]), ("superseded", report))
        path = self.write_run("forge-live", [self.attempt(171)]); before = path.read_bytes()
        self.control("forge-live", self.forge_request())
        self.assertEqual(path.read_bytes(), before)
        self.legacy_finish("forge-live", 171)
        path = self.write_run("forge-verdict", [self.attempt(171, state="merged",
            result=self.merged(171), result_source="owner", finished_at=NOW)])
        before = path.read_bytes()
        self.control("forge-verdict", self.forge_request())
        self.assertEqual(path.read_bytes(), before)

    def test_contracted_reconciliation_mints_remainder_one(self):
        self.project()
        self.spawn_contracted("forge-v2")
        self.cli("suspend", "--repo-root", self.root, "--run-id", "forge-v2", "--now", LATER,
                 "--issue", 171, "--attempt", 1, "--blocked-on", "external")
        response = self.control("forge-v2", self.forge_request())
        remainder = next(item for item in response["actions"]
                         if item["kind"] == "delivery_remainder")
        self.assertEqual((remainder["custody"]["action_id"], remainder["pending_stage_ids"][0]),
                         ("171:r1:1", "select_reviewed_output"))
        path = self.root / ".superpowers/workflows/forge-v2/state.json"
        self.assertEqual(self.latest(path)["result_source"], "superseded")

    def test_reconciled_remainder_waits_for_capacity(self):
        """A reconcile sweep without capacity persists the closeout; a later sweep mints r1."""
        self.project()
        self.spawn_contracted("forge-wait")
        self.cli("suspend", "--repo-root", self.root, "--run-id", "forge-wait", "--now", LATER,
                 "--issue", 171, "--attempt", 1, "--blocked-on", "external")
        path = self.root / ".superpowers/workflows/forge-wait/state.json"
        state = json.loads(path.read_text())
        holder = self.workflow.new_control_attempt(issue=172, attempt_number=1,
            worktree=str(self.root / ".worktrees/holder"), now=NOW,
            deadline_at="2026-09-21T01:00:00Z")
        state["issues"]["172"] = {"issue": 172, "attempts": [holder], "outcome": None,
            "delivery": self.workflow._delivery().empty_delivery(), "delivery_remainders": []}
        path.write_text(json.dumps(state))
        starved = self.control("forge-wait", self.forge_request(max_parallel=1))
        self.assertEqual([item for item in starved["actions"]
                          if item["kind"] == "delivery_remainder"], [])
        self.assertEqual((self.latest(path)["state"], self.latest(path)["result_source"]),
                         ("merged", "superseded"))
        self.legacy_finish("forge-wait", 172)
        minted = self.control("forge-wait", self.forge_request(max_parallel=1))
        remainder = next(item for item in minted["actions"]
                         if item["kind"] == "delivery_remainder")
        self.assertEqual(remainder["custody"]["action_id"], "171:r1:1")

    def test_failure_before_selection_keeps_the_retry_lane(self):
        self.project()
        contract, custody_value = self.spawn_contracted("orch-fail")
        digest = self.model.canonical_digest(contract)
        run = ("--repo-root", self.root, "--run-id", "orch-fail", "--now", LATER)
        failed = json.loads(self.cli("finish", *run, "--summary-file", "-", stdin=json.dumps(
            self.failed_summary(custody_value, digest)).encode()).stdout)
        self.assertEqual(failed["kind"], "terminal_failed")
        retried = self.control("orch-fail", self.control_request([171], now=LATER,
            worktrees=[{"issue": 171, "recorded": {"path": self.worktree, "state": "absent"},
                        "candidate": None}]))
        action = retried["actions"][0]
        self.assertEqual((action["kind"], action["attempt"], action["worktree"]),
                         ("retry", 2, self.worktree))
        selection = self.build("selected-output", {"contract": contract, "head": "a" * 40,
            "tree": "c" * 40, "acceptance_ref": "spec", "review_ref": "clean",
            "test_ref": "checks"})
        selected = self.build("observation", {"contract": contract,
            "observation_kind": "selected_output", "selection": selection,
            "source_kind": "repository", "source_reference": "probe", "observed_at": NOW,
            "evidence": "selected"})
        minted = json.loads(self.cli("finish", *run, "--summary-file", "-", stdin=json.dumps(
            self.failed_summary(action["custody"], digest, [selected])).encode()).stdout)
        self.assertEqual((minted["kind"], minted["custody"]["action_id"]),
                         ("delivery_remainder", "171:r1:1"))

if __name__ == "__main__":
    unittest.main()
