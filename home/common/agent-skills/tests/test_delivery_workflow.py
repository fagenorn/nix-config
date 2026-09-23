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
    authority, cleanup_contract_and_delivery, contract_and_delivery,
    contract_and_delivery_for_stage, observation, pr_subject, seal, selection,
    stage_scope,
)


ROOT = Path(__file__).parents[4]
SCRIPTS = ROOT / "home/common/agent-skills/scripts"
WORKFLOW = SCRIPTS / "workflow-state.py"
MODEL = SCRIPTS / "delivery_model/__init__.py"
POLICY = ROOT / "home/common/agent-skills/artifact-budget-policy.json"
ARTIFACT_BUDGET = SCRIPTS / "artifact_budget.py"
NOW = "2026-09-21T00:00:00Z"


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
            "issues": [151], "tracker": [], "owners": [], "worktrees": [],
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

    def test_schema_three_refuses_the_legacy_finish_transport_without_a_write(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialized = subprocess.run(
                [sys.executable, str(WORKFLOW), "init-run", "--repo-root", str(root),
                 "--run-id", "legacy-refusal", "--now", NOW],
                capture_output=True, text=True, check=False)
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            state_path = root / ".superpowers/workflows/legacy-refusal/state.json"
            before = state_path.read_bytes()
            result = {"issue": 151, "state": "failed", "pr_url": None,
                "merge_sha": None, "issue_closed": False, "discussion_items": [],
                "detail_state": "none", "report_path": None, "notes": "failed"}
            result_path = root / "legacy-result.json"
            result_path.write_text(json.dumps(result), encoding="utf-8")
            refused = subprocess.run(
                [sys.executable, str(WORKFLOW), "finish", "--repo-root", str(root),
                 "--run-id", "legacy-refusal", "--issue", "151", "--attempt", "1",
                 "--result-file", str(result_path), "--now", NOW],
                capture_output=True, text=True, check=False)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("legacy finish is read-only", refused.stderr)
            self.assertEqual(state_path.read_bytes(), before)

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
                shutil.copy2(SCRIPTS / "workflow_delivery_wire.py",
                             store / "workflow_delivery_wire.py")
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

            summary = self.failed_summary(
                owner_value["custody"], self.model.canonical_digest(contract),
                "provider failed")
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
            failed = self.failed_summary(owner["custody"], digest)
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
        contract, delivery, actual = contract_and_delivery_for_stage(self.model, "select")
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
                authorization_intents=delivery["authorization_intents"],
                requested_scope=actual)
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
            first = json.loads(call("finish", "--repo-root", root, "--run-id",
                owner["run_id"], "--summary-file", store(failed(owner["custody"])),
                "--now", "2026-09-21T00:00:01Z").stdout)

            proof = {"schema_version": 1, "kind": "delivery-recovery", "id": "",
                "contract_digest": digest, "stage_id": "select",
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
            failed = self.failed_summary(owner["custody"], digest)
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
        contract, delivery, actual = contract_and_delivery_for_stage(self.model, "select")
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
            request["requested_scopes"]["151"] = actual
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
            first = invoke("finish", "--repo-root", root, "--run-id", run_id,
                "--summary-file", store(failed(owner["custody"])), "--now",
                "2026-09-21T00:00:01Z")
            invoke("finish", "--repo-root", root, "--run-id", run_id,
                "--summary-file", store(failed(first["custody"])), "--now",
                "2026-09-21T00:00:02Z")
            recovery = {"schema_version": 1, "kind": "delivery-recovery", "id": "",
                "contract_digest": digest, "stage_id": "select", "requested_scope": actual,
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

    def issue_contract(self, issue):
        """The eight-stage cleanup contract and its first intent, bound to one issue."""
        contract, delivery = cleanup_contract_and_delivery(self.model)
        intent = copy.deepcopy(delivery["authorization_intents"][0])
        contract["issue"] = issue
        contract["deliverable"]["id"] = f"delivery-{issue}"
        for stage in contract["stages"]:
            if stage["kind"] == "close_tracker":
                stage["target_ref"]["value"] = str(issue)
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
        bound = {issue: self.issue_contract(issue) for issue in issues}

        def keyed(value):
            return {str(issue): copy.deepcopy(value) for issue in issues}

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); run_id = "dispatch-wire"
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


if __name__ == "__main__":
    unittest.main()
