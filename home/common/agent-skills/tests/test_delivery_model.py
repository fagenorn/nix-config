from __future__ import annotations

import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).parents[4]
SOURCE = ROOT / "home/common/agent-skills/scripts/delivery_model/__init__.py"
DEFAULT_NIX = ROOT / "home/common/agent-skills/default.nix"


def load_model(path: Path, name: str):
    if not path.is_file():
        raise FileNotFoundError(path)
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[str(path.parent)])
    if spec is None or spec.loader is None:
        raise AssertionError("delivery model loader unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        for key in tuple(sys.modules):
            if key == name or key.startswith(name + "."):
                sys.modules.pop(key, None)
        raise
    return module


def seal(model, value, field="id"):
    value[field] = model.canonical_digest(value, omit_derived=field)
    return value


def custody(kind="implementation", ordinal=1, launch=1):
    if kind == "implementation":
        return {"kind": kind, "attempt": ordinal, "launch": launch,
                "action_id": f"151:{ordinal}:{launch}"}
    return {"kind": kind, "remainder": ordinal, "launch": launch,
            "action_id": f"151:r{ordinal}:{launch}"}


def next_launch(value):
    result = copy.deepcopy(value)
    result["launch"] += 1
    if result["kind"] == "implementation":
        result["action_id"] = f"151:{result['attempt']}:{result['launch']}"
    else:
        result["action_id"] = f"151:r{result['remainder']}:{result['launch']}"
    return result


def scope(model, *, audience="private", pr="17"):
    return seal(model, {
        "schema_version": 1, "kind": "scope-tuple", "id": "",
        "principal": {"kind": "agent", "stable_id": "worker-1"},
        "action": "merge_pull_request", "effect": "provider_write",
        "target": {
            "project_id": "sim-project", "provider": "github",
            "repository_id": "sim-repo", "repository_slug": "sim.invalid/repo",
            "issue": 151, "branch": "feature", "base": "main",
            "pr_ref": {"kind": "literal", "value": pr},
            "output_ref": {"kind": "slot", "slot_id": "reviewed"},
        },
        "endpoint": {"kind": "literal", "value": "provider:merge"},
        "data": {"kind": "selected_output_slot", "slot_id": "reviewed",
                 "classification": "source", "audience": audience},
        "risk": "repository_write", "spend": {"kind": "none"},
    })


def intent(model, declared, *, predecessor=None, issued="2026-09-20T00:00:00Z",
           key="key-1", source="explicit_user"):
    return seal(model, {
        "schema_version": 1, "kind": "authorization-intent", "id": "",
        "predecessor_intent_id": predecessor,
        "source": {"kind": source, "reference": f"ref:{key}",
                   "evidence_digest": "sha256:" + "1" * 64},
        "issued_at": issued, "expires_at": None, "revocation_key": key,
        "scopes": [declared],
    })


def selection(model, contract_digest, *, subject_kind="commit", subject_value=None):
    if subject_value is None:
        subject_value = ("sha256:" + "a" * 64) if subject_kind == "record" else "a" * 40
    return seal(model, {
        "schema_version": 1, "kind": "selected-output", "id": "",
        "contract_digest": contract_digest, "slot_id": "reviewed",
        "subject_kind": subject_kind, "subject_value": subject_value,
        "data_identity_digest": "sha256:" + "2" * 64,
        "repository_id": "sim-repo", "branch": "feature", "base": "main",
        "evidence_digest": "sha256:" + "3" * 64,
        "acceptance_evidence_ids": ["accept-1"],
        "review_evidence_ids": ["review-1"],
        "test_evidence_ids": ["test-1"],
    })


def contract_and_delivery(model):
    declared = scope(model)
    first = intent(model, declared)
    stage_specs = [
        ("select", "select_reviewed_output", "select_output", "ledger_write"),
        ("publish", "publish_branch", "push_branch", "repository_write"),
        ("open", "open_pr", "open_pull_request", "provider_write"),
        ("merge", "merge_pr", "merge_pull_request", "provider_write"),
    ]
    target_ref = {
        "kind": "slot", "slot_id": "reviewed", "subject_kind": "commit",
        "constraints": {
            "project_id": "sim-project", "provider": "github",
            "repository_id": "sim-repo", "repository_slug": "sim.invalid/repo",
            "branch": "feature", "base": "main", "deliverable_class": "source",
            "data_ref": {"kind": "selected_output_slot", "slot_id": "reviewed",
                         "classification": "source", "audience": "private"},
        },
    }
    stages = []
    for index, (stage_id, kind, action, effect) in enumerate(stage_specs):
        stages.append({
            "id": stage_id, "kind": kind, "action": action, "effect": effect,
            "target_ref": copy.deepcopy(target_ref),
            "worktree_requirement": "matching_required",
            "depends_on": [] if index == 0 else [stages[index - 1]["id"]],
            "retryable": True,
        })
    contract = {
        "schema_version": 1, "kind": "delivery-contract",
        "project": {"project_id": "sim-project", "provider": "github",
                    "repository_id": "sim-repo", "repository_slug": "sim.invalid/repo"},
        "issue": 151,
        "deliverable": {"id": "delivery-151", "summary": "Deliver model",
                        "obligations": {"implementation_delivered": "required",
                                        "pr_merged": "required",
                                        "tracker_closed": "not_applicable",
                                        "cleanup_complete": "not_applicable"}},
        "stages": stages, "initial_authorization_intent_id": first["id"],
        "initial_authorization_intent_digest": model.canonical_digest(first),
        "provenance": {"kind": "issue", "reference": "issue:151",
                       "digest": "sha256:" + "4" * 64,
                       "created_at": "2026-09-20T00:00:00Z"},
    }
    digest = model.canonical_digest(contract)
    facts = [seal(model, {"schema_version": 1, "kind": "delivery-stage-fact", "id": "",
                               "contract_digest": digest, "stage_id": item["id"],
                               "state": "pending", "observation_id": None}) for item in stages]
    delivery = {
        "contract": contract, "contract_digest": digest,
        "authorization_intents": [first],
        "authorization_chain_digest": model.canonical_digest({"intent_ids": [first["id"]]}),
        "authority_observations": [], "reevaluation_evidence": [],
        "authority_evaluation_consumptions": [], "delivery_observations": [],
        "selected_outputs": [], "stage_facts": facts,
        "postconditions": {
            "implementation_delivered": {"state": "pending", "observation_id": None},
            "pr_merged": {"state": "pending", "observation_id": None},
            "tracker_closed": {"state": "not_applicable", "observation_id": None},
            "cleanup_complete": {"state": "not_applicable", "observation_id": None},
        },
    }
    return contract, delivery


def requested_scope(model, declared, selected):
    value = copy.deepcopy(declared)
    value["target"]["output_ref"] = {"kind": "literal", "value": selected["subject_value"]}
    value["data"] = {"kind": "literal", "digest": selected["data_identity_digest"],
                     "classification": "source", "audience": "private"}
    return seal(model, value)


def authority(model, contract, declared, launch, verdict="rejected"):
    return seal(model, {
        "schema_version": 1, "kind": "authority-observation", "id": "",
        "contract_digest": model.canonical_digest(contract), "scope_id": declared["id"],
        "launch_id": launch["action_id"], "authority_kind": "host", "verdict": verdict,
        "reason_code": "host_result", "observed_at": "2026-09-20T01:00:00Z",
        "evidence_digest": "sha256:" + "5" * 64,
        "opaque_host_reference": None, "revocation_subject": None,
        "evaluation_use_key": None,
    })


def reevaluation(model, contract, denial):
    return seal(model, {
        "schema_version": 1, "kind": "reevaluation-evidence", "id": "",
        "contract_digest": model.canonical_digest(contract), "scope_id": denial["scope_id"],
        "rejected_observation_id": denial["id"], "source_kind": "host",
        "reason_code": "material_change", "observed_at": "2026-09-20T02:00:00Z",
        "evidence_digest": "sha256:" + "6" * 64,
    })


def evaluation(**changes):
    value = {"at_time": "2026-09-21T00:00:00Z", "custody": None,
             "current_launch": None, "requested_scope": None, "source_kind": "direct",
             "authorization_intents": [], "authority_observations": [],
             "reevaluation_evidence": [], "delivery_observations": []}
    value.update(changes)
    return value


def workflow_responses(model):
    contract, _ = contract_and_delivery(model); digest = model.canonical_digest(contract)
    active = custody(); pending = [stage["id"] for stage in contract["stages"]]
    block = {"custody": active, "contract": contract, "contract_digest": digest,
             "pending_stage_ids": pending, "requirements": [], "authority_evaluation": None}
    owner = {"interface_version": 2, "kind": "owner", "ledger_repo_root": "/repo",
             "run_id": "run-1", "issue": 151, "attempt": 1, "owner": "151:1",
             "action_id": "151:1:1", "launch_kind": "spawn", "worktree": "/worktree",
             "handoff_path": "/handoff", "deadline_at": "2026-09-21T01:00:00Z", **block}
    control_owner = {"id": "151:1:1", "kind": "spawn", "issue": 151, "attempt": 1,
                     "owner": "151:1", "worktree": "/worktree", "handoff_path": "/handoff",
                     "deadline_at": "2026-09-21T01:00:00Z", **block}
    remainder_custody = {"kind": "remainder", "remainder": 1, "launch": 1,
                         "action_id": "151:r1:1"}
    remainder = {"interface_version": 2, "kind": "delivery_remainder",
                 "ledger_repo_root": "/repo", "run_id": "run-1", "issue": 151,
                 "source_attempt": 1, "owner": "151:r1", "custody": remainder_custody,
                 "worktree": "/worktree", "contract": contract, "contract_digest": digest,
                 "pending_stage_ids": pending, "deadline_at": "2026-09-21T01:00:00Z",
                 "requirements": [], "authority_evaluation": None}
    common = {"interface_version": 2, "ledger_repo_root": "/repo", "run_id": "run-1",
              "issue": 151, "owner": "151:1", "custody": active,
              "contract_digest": digest, "accepted_observation_ids": [],
              "pending_stage_ids": pending}
    return {
        "current": {"action_id": "151:1:1", "current": True,
                    "current_action_id": "151:1:1", "reason": "current"},
        "bootstrap": {"interface_version": 2, "kind": "workflow_bootstrap",
                      "run_id": "run-1", "requirements": []},
        "control": {"interface_version": 2, "run_id": "run-1", "now": "2026-09-21T00:00:00Z",
                    "summaries": [{"issue": 151, "state": "active", "custody": active,
                        "owner": "151:1", "worktree": "/worktree", "deadline_at": "2026-09-21T01:00:00Z",
                        "blocked_on": None, "blockers": [], "result": None,
                        "contract_digest": digest, "pending_stage_ids": pending, "requirements": []}],
                    "deltas": [{"issue": 151, "custody": active, "kind": "spawned", "state": "active"}],
                    "actions": [control_owner], "next_deadline": "2026-09-21T01:00:00Z"},
        "observe": {"interface_version": 2, "kind": "observe", "issue": 151,
                    "run_id": "run-1", "requirements": [{"kind": "tracker"}]},
        "owner": owner,
        "terminal": {"interface_version": 2, "kind": "terminal", "issue": 151,
                     "run_id": "run-1", "source": "ledger", "reason": "closed",
                     "blockers": [], "result": None, "reentry": "resume"},
        "remainder": remainder,
        "checkpointed": {**common, "kind": "delivery_checkpointed", "next_action": None,
                         "requirements": [], "authority_evaluation": None, "state": "active", "blocked_on": None},
        "stalled": {**common, "kind": "delivery_stalled", "state": "terminal_failed",
                    "stalled_resumes": 3, "result_source": "stalled",
                    "reason_code": "suspension_stalled_without_progress"},
        "complete": {**common, "kind": "delivery_complete", "pending_stage_ids": [],
                     "state": "delivery_complete"},
        "failed": {**common, "kind": "terminal_failed", "state": "terminal_failed",
                   "result_source": "owner", "reason_code": "owner_reported_failure"},
    }


def with_host_rejection(model, contract, delivery, active):
    result = copy.deepcopy(delivery)
    denial = authority(model, contract, result["authorization_intents"][-1]["scopes"][0], active)
    result["authority_observations"] = [denial]
    return result, denial


def observation(model, contract, kind, subject):
    return seal(model, {
        "schema_version": 1, "kind": "delivery-observation", "id": "",
        "contract_digest": model.canonical_digest(contract),
        "project": copy.deepcopy(contract["project"]), "observation_kind": kind,
        "subject": copy.deepcopy(subject),
        "source": {"kind": "provider", "reference": f"sim:{kind}"},
        "observed_at": "2026-09-20T03:00:00Z",
        "evidence_digest": "sha256:" + "7" * 64,
    })


def with_observed(model, contract, delivery, stage_ids):
    result = copy.deepcopy(delivery)
    mapping = {
        "select": ("selected_output", {"selected_output": selection(model, model.canonical_digest(contract))}),
        "publish": ("branch_published", {"repository_id": "sim-repo", "branch": "feature", "selected_head": "a" * 40}),
        "open": ("pr_opened", {"provider_repository_id": "sim-repo", "pr_number": 17,
                                    "pr_url": "https://sim.invalid/pr/17", "expected_head": "a" * 40, "base": "main"}),
        "merge": ("pr_merged", {"provider_repository_id": "sim-repo", "pr_number": 17,
                                     "pr_url": "https://sim.invalid/pr/17", "expected_head": "a" * 40,
                                     "base": "main", "merge_sha": "b" * 40, "merged": True}),
    }
    for stage_id in stage_ids:
        kind, subject = mapping[stage_id]
        item = observation(model, contract, kind, subject)
        result["delivery_observations"].append(item)
    result["delivery_observations"].sort(key=lambda item: item["id"])
    return result


def rebind_contract(model, contract, delivery):
    result = copy.deepcopy(delivery)
    result["contract"] = copy.deepcopy(contract)
    result["contract_digest"] = model.canonical_digest(contract)
    result["stage_facts"] = [seal(model, {
        "schema_version": 1, "kind": "delivery-stage-fact", "id": "",
        "contract_digest": result["contract_digest"], "stage_id": stage["id"],
        "state": "pending", "observation_id": None,
    }) for stage in contract["stages"]]
    return result


def cleanup_contract_and_delivery(model):
    contract, delivery = contract_and_delivery(model)
    stages = (
        ("close", "close_tracker", "close_issue", "tracker_write", "151", "not_required"),
        ("remote", "delete_remote_branch", "delete_remote_branch", "repository_write", "feature", "cleanup_target"),
        ("worktree", "remove_worktree", "remove_worktree", "filesystem_write", "/worktree", "cleanup_target"),
        ("local", "delete_local_branch", "delete_local_branch", "repository_write", "feature", "cleanup_target"),
    )
    dependency = "merge"
    for stage_id, kind, action, effect, target, requirement in stages:
        contract["stages"].append({
            "id": stage_id, "kind": kind, "action": action, "effect": effect,
            "target_ref": {"kind": "literal", "value": target},
            "worktree_requirement": requirement, "depends_on": [dependency],
            "retryable": True,
        })
        dependency = stage_id
    contract["deliverable"]["obligations"].update(
        tracker_closed="required", cleanup_complete="required")
    delivery = rebind_contract(model, contract, delivery)
    delivery["postconditions"]["tracker_closed"] = {"state": "pending", "observation_id": None}
    delivery["postconditions"]["cleanup_complete"] = {"state": "pending", "observation_id": None}
    return contract, delivery


def ship_handoff(model, contract, delivery):
    artifact = {"budget_status": "within_budget", "kind": "design-spec",
                "metrics": {"root_bytes": 1, "total_bytes": 1, "file_count": 1,
                            "largest_member_bytes": 0},
                "path": ".claude/specs/sim.md"}
    return {"interface_version": 2, "state": "complete", "ledger_repo_root": "/repo",
            "run_id": "run-1", "owner": "151:1", "owner_worktree": "/worktree",
            "custody": custody(), "issue_number": 151, "branch": "feature",
            "worktree_path": "/worktree", "spec_artifact": artifact,
            "plan_artifact": {**artifact, "kind": "implementation-plan",
                              "path": ".claude/plans/sim.md"},
            "head_sha": "a" * 40, "review_state": "clean", "auto": True,
            "report_path": None, "notes": "simulated", "delivery_contract": contract,
            "delivery_contract_digest": model.canonical_digest(contract),
            "authorization_intents": delivery["authorization_intents"],
            "authorization_chain_digest": delivery["authorization_chain_digest"],
            "authority_observation_ids": [], "reevaluation_evidence_ids": [],
            "authority_evaluation_consumption_ids": [],
            "pending_stage_ids": [stage["id"] for stage in contract["stages"]],
            "selected_outputs": delivery["selected_outputs"]}


class DeliveryModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_model(SOURCE, "delivery_model_source_test")

    def validate(self, value, kind):
        return self.model.validate_delivery_object(
            value, expected_kind=kind, notes_max_characters=4096)

    def assert_invalid(self, value, kind):
        with self.assertRaises(self.model.DeliveryModelError):
            self.validate(value, kind)

    def test_import_is_pure_and_interface_is_exact(self):
        with tempfile.TemporaryDirectory() as raw:
            before = set(Path(raw).iterdir()); prior = Path.cwd()
            try:
                os.chdir(raw); module = load_model(SOURCE, "delivery_model_purity_test")
            finally:
                os.chdir(prior)
            self.assertEqual(module.MODEL_INTERFACE_VERSION, 1)
            self.assertEqual(set(module.__all__), {
                "MODEL_INTERFACE_VERSION", "DeliveryModelError", "canonical_bytes",
                "canonical_digest", "validate_delivery_object", "validate_custody_ref",
                "match_scope", "reduce_delivery",
            })
            self.assertEqual(set(Path(raw).iterdir()), before)
            self.assertFalse(hasattr(module, "main"))

    def test_canonical_bytes_and_derived_digest_are_exact(self):
        value = {"z": [2, 1], "id": "ignored", "a": "é"}
        body = b'{"a":"\xc3\xa9","z":[2,1]}\n'
        self.assertEqual(self.model.canonical_bytes(value, omit_derived="id"), body)
        self.assertEqual(self.model.canonical_digest(value, omit_derived="id"),
                         "sha256:" + hashlib.sha256(body).hexdigest())

    def test_strict_scope_and_custody_validation(self):
        valid = scope(self.model)
        self.assertEqual(self.validate(valid, "scope-tuple"), valid)
        for mutation in ("unknown", "bool", "null", "id"):
            bad = copy.deepcopy(valid)
            if mutation == "unknown": bad["extra"] = 1
            if mutation == "bool": bad["target"]["issue"] = True
            if mutation == "null": bad["data"]["audience"] = None
            if mutation == "id": bad["id"] = "sha256:" + "f" * 64
            with self.subTest(mutation=mutation): self.assert_invalid(bad, "scope-tuple")
        self.assertEqual(self.model.validate_custody_ref(custody(), issue=151), custody())
        with self.assertRaises(self.model.DeliveryModelError):
            self.model.validate_custody_ref({"kind": "remainder", "attempt": 1, "launch": 1, "action_id": "151:1:1"}, issue=151)

    def test_slot_narrowing_and_literal_pr_are_exact(self):
        contract, delivery = contract_and_delivery(self.model)
        declared = delivery["authorization_intents"][0]["scopes"][0]
        selected = selection(self.model, self.model.canonical_digest(contract))
        requested = requested_scope(self.model, declared, selected)
        result = self.model.match_scope(contract, delivery["authorization_intents"][0], requested,
            selected_outputs=[selected], at_time="2026-09-21T00:00:00Z", revocation_observations=[])
        self.assertEqual(result["reason_code"], "matched")
        for field, replacement, reason in (("audience", "public", "scope_data_mismatch"),
                                            ("digest", "sha256:" + "9" * 64, "scope_data_mismatch")):
            bad = copy.deepcopy(requested); bad["data"][field] = replacement; seal(self.model, bad)
            self.assertEqual(self.model.match_scope(contract, delivery["authorization_intents"][0], bad,
                selected_outputs=[selected], at_time="2026-09-21T00:00:00Z", revocation_observations=[])["reason_code"], reason)
        bad = copy.deepcopy(requested); bad["target"]["pr_ref"] = {"kind": "literal", "value": "18"}; seal(self.model, bad)
        self.assertEqual(self.model.match_scope(contract, delivery["authorization_intents"][0], bad,
            selected_outputs=[selected], at_time="2026-09-21T00:00:00Z", revocation_observations=[])["reason_code"], "scope_target_mismatch")

        successor = intent(self.model, scope(self.model, pr="18"),
                           predecessor=delivery["authorization_intents"][0]["id"], key="pr-18")
        for pr, expected in ((18, "observed"), (999, "pending")):
            candidate = with_observed(self.model, contract, delivery,
                                      ["select", "publish", "open", "merge"])
            candidate["authorization_intents"] = sorted(
                delivery["authorization_intents"] + [successor], key=lambda item: item["id"])
            candidate["authorization_chain_digest"] = self.model.canonical_digest({
                "intent_ids": [item["id"] for item in candidate["authorization_intents"]]})
            for item in candidate["delivery_observations"]:
                if item["observation_kind"] in {"pr_opened", "pr_merged"}:
                    item["subject"]["pr_number"] = pr; seal(self.model, item)
            candidate["delivery_observations"].sort(key=lambda item: item["id"])
            reduced = self.model.reduce_delivery(contract, candidate, evaluation=evaluation())
            with self.subTest(pr=pr):
                self.assertEqual(reduced["next_delivery"]["postconditions"]["pr_merged"]["state"], expected)

    def test_matcher_expiry_contract_and_slot_constraints(self):
        contract, delivery = contract_and_delivery(self.model)
        selected = selection(self.model, self.model.canonical_digest(contract))
        original = delivery["authorization_intents"][0]
        requested = requested_scope(self.model, original["scopes"][0], selected)

        expired = copy.deepcopy(original)
        expired["expires_at"] = "2026-09-20T12:00:00Z"
        seal(self.model, expired)
        expired_contract = copy.deepcopy(contract)
        expired_contract["initial_authorization_intent_id"] = expired["id"]
        expired_contract["initial_authorization_intent_digest"] = self.model.canonical_digest(expired)
        self.assertEqual(self.model.match_scope(expired_contract, expired, requested,
            selected_outputs=[selection(self.model, self.model.canonical_digest(expired_contract))],
            at_time="2026-09-21T00:00:00Z", revocation_observations=[])["reason_code"], "intent_expired")

        foreign = copy.deepcopy(contract)
        foreign["initial_authorization_intent_digest"] = "sha256:" + "f" * 64
        self.assertEqual(self.model.match_scope(foreign, original, requested,
            selected_outputs=[selected], at_time="2026-09-21T00:00:00Z",
            revocation_observations=[])["reason_code"], "contract_mismatch")

        wrong_selection = copy.deepcopy(selected)
        wrong_selection["branch"] = "other"
        seal(self.model, wrong_selection)
        self.assertEqual(self.model.match_scope(contract, original, requested,
            selected_outputs=[wrong_selection], at_time="2026-09-21T00:00:00Z",
            revocation_observations=[])["reason_code"], "slot_constraint_mismatch")

    def test_revocation_binds_intent_and_key(self):
        contract, delivery = contract_and_delivery(self.model)
        first = delivery["authorization_intents"][0]; second = intent(self.model, first["scopes"][0], predecessor=first["id"], key="key-2")
        revoked = seal(self.model, {"schema_version": 1, "kind": "authority-observation", "id": "",
            "contract_digest": self.model.canonical_digest(contract), "scope_id": first["scopes"][0]["id"],
            "launch_id": None, "authority_kind": "intent_revocation", "verdict": "revoked",
            "reason_code": "revoked", "observed_at": "2026-09-20T02:00:00Z",
            "evidence_digest": "sha256:" + "8" * 64, "opaque_host_reference": None,
            "revocation_subject": {"intent_id": first["id"], "revocation_key": "key-1"},
            "evaluation_use_key": None})
        self.assertEqual(self.model.match_scope(contract, first, first["scopes"][0], selected_outputs=[],
            at_time="2026-09-21T00:00:00Z", revocation_observations=[revoked])["reason_code"], "intent_revoked")
        self.assertTrue(self.model.match_scope(contract, second, second["scopes"][0], selected_outputs=[],
            at_time="2026-09-21T00:00:00Z", revocation_observations=[revoked])["matched"])

    def test_reducer_orders_stages_without_mutating_input(self):
        contract, delivery = contract_and_delivery(self.model); before = copy.deepcopy(delivery)
        self.assertEqual(self.model.reduce_delivery(contract, delivery, evaluation=evaluation())["next_stage_id"], "select")
        opened = with_observed(self.model, contract, delivery, ["select", "publish", "open"])
        reduced = self.model.reduce_delivery(contract, opened, evaluation=evaluation())
        self.assertEqual(reduced["next_stage_id"], "merge")
        merged = with_observed(self.model, contract, opened, ["merge"])
        done = self.model.reduce_delivery(contract, merged, evaluation=evaluation())
        self.assertEqual(done["next_delivery"]["postconditions"]["pr_merged"]["state"], "observed")
        self.assertEqual(done["next_delivery"]["postconditions"]["implementation_delivered"]["state"], "pending")
        self.assertEqual(delivery, before)

    def test_rejection_bases_are_independent_and_one_shot(self):
        contract, delivery = contract_and_delivery(self.model); active = custody()
        denied, rejection = with_host_rejection(self.model, contract, delivery, active)
        requested = denied["authorization_intents"][0]["scopes"][0]
        successor = intent(self.model, requested, predecessor=denied["authorization_intents"][0]["id"],
                           issued="2026-09-20T02:00:00Z", key="key-2")
        other_scope = copy.deepcopy(requested)
        other_scope["action"] = "close_issue"
        seal(self.model, other_scope)
        cosmetic = intent(self.model, other_scope, predecessor=denied["authorization_intents"][0]["id"],
                          issued="2026-09-20T02:00:00Z", key="key-cosmetic")
        unchanged = self.model.reduce_delivery(contract, denied, evaluation=evaluation(
            custody=active, current_launch=True, requested_scope=requested,
            authorization_intents=[cosmetic]))
        self.assertEqual(unchanged["blocking"]["reason_code"], "host_rejected")
        evidence = reevaluation(self.model, contract, rejection)
        for basis_kind, changes in (("successor_intent", {"authorization_intents": [successor]}),
                                    ("reevaluation_evidence", {"reevaluation_evidence": [evidence]})):
            first = self.model.reduce_delivery(contract, denied, evaluation=evaluation(
                custody=active, current_launch=True, requested_scope=requested, **changes))
            permit = first["authority_evaluation"]
            self.assertEqual(permit["basis_kind"], basis_kind)
            self.assertEqual(first["next_delivery"]["authority_evaluation_consumptions"][0]["use_key"], permit["use_key"])
            for replay_custody in (active, next_launch(active)):
                replay = self.model.reduce_delivery(contract, first["next_delivery"], evaluation=evaluation(
                    custody=replay_custody, current_launch=True, requested_scope=requested, **changes))
                self.assertIsNone(replay["authority_evaluation"])
                self.assertEqual(replay["blocking"]["reason_code"], "reevaluation_consumed")

    def test_conflicting_observation_identity_and_operational_denial_refuse(self):
        contract, delivery = contract_and_delivery(self.model)
        first = observation(self.model, contract, "branch_published",
            {"repository_id": "sim-repo", "branch": "feature", "selected_head": "a" * 40})
        conflict = copy.deepcopy(first)
        conflict["subject"]["selected_head"] = "b" * 40
        bad = copy.deepcopy(delivery)
        bad["delivery_observations"] = [first, conflict]
        with self.assertRaises(self.model.DeliveryModelError):
            self.model.reduce_delivery(contract, bad, evaluation=evaluation())

        denied, rejection = with_host_rejection(self.model, contract, delivery, custody())
        result = self.model.reduce_delivery(contract, denied, evaluation=evaluation(
            custody=custody(), current_launch=True,
            requested_scope=denied["authorization_intents"][0]["scopes"][0]))
        self.assertEqual(result["blocking"], {"blocked_on": "human_gate",
            "reason_code": "host_rejected", "subject_id": rejection["id"]})

    def test_late_old_launch_facts_are_history_not_current_authority(self):
        contract, delivery = contract_and_delivery(self.model); old = custody(); current = next_launch(old)
        declared = delivery["authorization_intents"][0]["scopes"][0]
        allowed = authority(self.model, contract, declared, old, verdict="allowed")
        reduced = self.model.reduce_delivery(contract, delivery, evaluation=evaluation(
            custody=current, current_launch=True, requested_scope=declared,
            authority_observations=[allowed], source_kind="direct"))
        self.assertIn(allowed["id"], {x["id"] for x in reduced["next_delivery"]["authority_observations"]})
        self.assertEqual(reduced["requirements"][0]["reason_code"], "authority_launch_mismatch")

    def test_workflow_response_validation_is_structural_only(self):
        fixtures = workflow_responses(self.model)
        self.assertEqual(set(fixtures), {"current", "bootstrap", "control", "observe", "owner",
            "terminal", "remainder", "checkpointed", "stalled", "complete", "failed"})
        for name, value in fixtures.items():
            with self.subTest(name=name):
                self.assertEqual(self.validate(value, "workflow-response"), value)
        mutations = {}
        for name, value in fixtures.items():
            bad = copy.deepcopy(value); bad["unexpected"] = True; mutations[f"{name}_extra"] = bad
        bad = copy.deepcopy(fixtures["complete"]); bad["pending_stage_ids"] = ["merge"]; mutations["complete_pending"] = bad
        bad = copy.deepcopy(fixtures["failed"]); bad["reason_code"] = "transport"; mutations["failed_reason"] = bad
        bad = copy.deepcopy(fixtures["owner"]); bad["custody"]["action_id"] = "151:1:9"; mutations["owner_identity"] = bad
        bad = copy.deepcopy(fixtures["control"]); bad["summaries"][0]["custody"] = None; bad["summaries"][0]["owner"] = {"bad": True}; mutations["summary_nested"] = bad
        bad = copy.deepcopy(fixtures["remainder"]); bad["pending_stage_ids"] = list(reversed(bad["pending_stage_ids"])); mutations["stage_order"] = bad
        bad = copy.deepcopy(fixtures["control"]); bad["deltas"][0]["custody"] = {"kind": "implementation"}; mutations["delta_custody"] = bad
        bad = copy.deepcopy(fixtures["observe"]); bad["requirements"][0]["extra"] = True; mutations["requirement_hybrid"] = bad
        bad = copy.deepcopy(fixtures["control"]); bad["actions"][0]["id"] = "151:1:9"; mutations["action_identity"] = bad
        bad = copy.deepcopy(fixtures["owner"]); bad["contract_digest"] = "sha256:" + "f" * 64; mutations["contract_digest"] = bad
        bad = copy.deepcopy(fixtures["owner"]); bad["authority_evaluation"] = {"kind": "native_authority_evaluation"}; mutations["evaluation_shape"] = bad
        bad = copy.deepcopy(fixtures["checkpointed"]); bad["next_action"] = {"kind": "unknown"}; mutations["next_action"] = bad
        bad = copy.deepcopy(fixtures["current"]); bad["current"] = False; mutations["current_correlation"] = bad
        bad = copy.deepcopy(fixtures["checkpointed"]); bad["accepted_observation_ids"] = ["sha256:" + "a" * 64] * 2; mutations["duplicate_observation"] = bad
        for name, value in mutations.items():
            with self.subTest(mutation=name): self.assert_invalid(value, "workflow-response")

    def test_critical_authority_lineage_and_evidence_invariants(self):
        contract, delivery = contract_and_delivery(self.model); active = custody()
        public = scope(self.model, audience="public")
        allowed = authority(self.model, contract, public, active, verdict="allowed")
        with self.assertRaises(self.model.DeliveryModelError):
            self.model.reduce_delivery(contract, delivery, evaluation=evaluation(
                custody=active, current_launch=True, requested_scope=public,
                authority_observations=[allowed]))
        successor = intent(self.model, public,
                           predecessor=delivery["authorization_intents"][0]["id"],
                           issued="2026-09-20T02:00:00Z", key="later")
        with self.assertRaises(self.model.DeliveryModelError):
            self.model.reduce_delivery(contract, delivery, evaluation=evaluation(
                custody=active, current_launch=True, requested_scope=public,
                authorization_intents=[successor], authority_observations=[allowed]))

        declared = scope(self.model); declared["target"]["output_ref"] = {"kind": "none"}; declared["data"] = {"kind": "none"}; seal(self.model, declared)
        owner_intent = intent(self.model, declared); none_contract = copy.deepcopy(contract)
        none_contract["initial_authorization_intent_id"] = owner_intent["id"]
        none_contract["initial_authorization_intent_digest"] = self.model.canonical_digest(owner_intent)
        widened = copy.deepcopy(declared); widened["target"]["output_ref"] = {"kind": "literal", "value": "new"}; seal(self.model, widened)
        self.assertEqual(self.model.match_scope(none_contract, owner_intent, widened,
            selected_outputs=[], at_time="2026-09-21T00:00:00Z", revocation_observations=[])["reason_code"], "scope_target_mismatch")

        bad_scope = scope(self.model); bad_scope["schema_version"] = True; seal(self.model, bad_scope)
        self.assert_invalid(bad_scope, "scope-tuple")

        first = delivery["authorization_intents"][0]; forked = copy.deepcopy(delivery)
        forked["authorization_intents"] += [intent(self.model, first["scopes"][0], predecessor=first["id"], key="fork-a"), intent(self.model, first["scopes"][0], predecessor=first["id"], key="fork-b")]
        forked["authorization_intents"].sort(key=lambda item: item["id"])
        forked["authorization_chain_digest"] = self.model.canonical_digest({"intent_ids": [item["id"] for item in forked["authorization_intents"]]})
        self.assert_invalid(forked, "delivery")

        fabricated = copy.deepcopy(delivery)
        fabricated["postconditions"]["implementation_delivered"] = {"state": "observed", "observation_id": "sha256:" + "0" * 64}
        self.assert_invalid(fabricated, "delivery")

        false_merge = observation(self.model, contract, "pr_merged", {"provider_repository_id": "sim-repo", "pr_number": 18, "pr_url": "https://sim.invalid/pr/18", "expected_head": "c" * 40, "base": "wrong-base", "merge_sha": "b" * 40, "merged": False})
        result = self.model.reduce_delivery(contract, delivery, evaluation=evaluation(delivery_observations=[false_merge]))
        self.assertEqual(result["next_delivery"]["postconditions"]["pr_merged"]["state"], "pending")
        self.assertEqual(next(item["state"] for item in result["next_delivery"]["stage_facts"] if item["stage_id"] == "merge"), "pending")

        repeated = with_observed(self.model, contract, delivery, ["select", "publish"])
        branch = next(item for item in repeated["delivery_observations"] if item["observation_kind"] == "branch_published")
        reprobe = copy.deepcopy(branch); reprobe["observed_at"] = "2026-09-20T04:00:00Z"; seal(self.model, reprobe)
        compatible = self.model.reduce_delivery(contract, repeated, evaluation=evaluation(delivery_observations=[reprobe]))
        self.assertEqual(next(item["state"] for item in compatible["next_delivery"]["stage_facts"] if item["stage_id"] == "publish"), "observed")

    def test_consumed_rejection_allows_one_fresh_current_result(self):
        contract, delivery = contract_and_delivery(self.model); active = custody()
        denied, rejection = with_host_rejection(self.model, contract, delivery, active)
        requested = denied["authorization_intents"][0]["scopes"][0]; basis = reevaluation(self.model, contract, rejection)
        permit = self.model.reduce_delivery(contract, denied, evaluation=evaluation(custody=active, current_launch=True, requested_scope=requested, reevaluation_evidence=[basis]))
        allowed = authority(self.model, contract, requested, active, verdict="allowed"); allowed["observed_at"] = "2026-09-21T00:00:01Z"; allowed["evaluation_use_key"] = permit["authority_evaluation"]["use_key"]; seal(self.model, allowed)
        after = self.model.reduce_delivery(contract, permit["next_delivery"], evaluation=evaluation(at_time="2026-09-21T00:00:02Z", custody=active, current_launch=True, requested_scope=requested, authority_observations=[allowed]))
        self.assertIsNone(after["blocking"]); self.assertEqual(after["requirements"], [])
        unbound = copy.deepcopy(allowed); unbound["evaluation_use_key"] = None; seal(self.model, unbound)
        refused = self.model.reduce_delivery(contract, permit["next_delivery"], evaluation=evaluation(
            at_time="2026-09-21T00:00:02Z", custody=active, current_launch=True,
            requested_scope=requested, authority_observations=[unbound]))
        self.assertEqual(refused["blocking"]["reason_code"], "host_rejected")
        later = authority(self.model, contract, requested, active, verdict="rejected")
        later["observed_at"] = "2026-09-21T00:00:02Z"; later["evaluation_use_key"] = permit["authority_evaluation"]["use_key"]; seal(self.model, later)
        refused = self.model.reduce_delivery(contract, permit["next_delivery"], evaluation=evaluation(
            at_time="2026-09-21T00:00:03Z", custody=active, current_launch=True,
            requested_scope=requested, authority_observations=sorted([allowed, later], key=lambda item: item["id"])))
        self.assertEqual(refused["blocking"]["reason_code"], "host_rejected")

    def test_positive_evidence_shapes_and_targets_are_closed(self):
        contract, delivery = contract_and_delivery(self.model)
        selected = selection(self.model, delivery["contract_digest"])
        for field, replacement in (("acceptance_evidence_ids", None),
                                   ("review_evidence_ids", []),
                                   ("test_evidence_ids", ["z", "a"]),
                                   ("test_evidence_ids", ["test-1", "test-1"])):
            bad = copy.deepcopy(selected)
            if replacement is None: bad.pop(field)
            else: bad[field] = replacement
            seal(self.model, bad)
            self.assert_invalid(bad, "selected-output")
        for kind, subject in (
            ("implementation_delivered", {"probe_succeeded": False}),
            ("cleanup_complete", {"absent": False}),
        ):
            bad = observation(self.model, contract, kind, subject)
            with self.subTest(kind=kind): self.assert_invalid(bad, "delivery-observation")

        close = {"id": "close", "kind": "close_tracker", "action": "close_issue",
                 "effect": "tracker_write", "target_ref": {"kind": "literal", "value": "151"},
                 "worktree_requirement": "not_required", "depends_on": ["merge"],
                 "retryable": True}
        contract["stages"].append(close)
        contract["deliverable"]["obligations"]["tracker_closed"] = "required"
        delivery = rebind_contract(self.model, contract, delivery)
        delivery["postconditions"]["tracker_closed"] = {"state": "pending", "observation_id": None}
        foreign = observation(self.model, contract, "tracker_closed", {
            "tracker_repository_id": "other", "issue": 152, "state": "closed",
            "close_reason": "completed", "observation_identity": "foreign-152"})
        reduced = self.model.reduce_delivery(
            contract, delivery, evaluation=evaluation(delivery_observations=[foreign]))
        self.assertEqual(reduced["next_delivery"]["postconditions"]["tracker_closed"]["state"], "pending")
        self.assertEqual(next(f["state"] for f in reduced["next_delivery"]["stage_facts"]
                             if f["stage_id"] == "close"), "pending")

    def test_all_stage_and_completion_families_bind_exact_subjects(self):
        contract, delivery = cleanup_contract_and_delivery(self.model)
        observed = with_observed(self.model, contract, delivery,
                                 ["select", "publish", "open", "merge"])
        subjects = {
            "tracker_closed": {"tracker_repository_id": "sim-repo", "issue": 151,
                               "state": "closed", "close_reason": "completed",
                               "observation_identity": "tracker:151:closed"},
            "remote_branch_absent": {"repository_id": "sim-repo", "branch": "feature",
                                     "absent": True},
            "worktree_absent": {"path": "/worktree", "recorded_worktree_identity": "wt-151",
                                "probe_mode": "no_follow", "absent": True},
            "local_branch_absent": {"repository_id": "sim-repo", "branch": "feature",
                                    "absent": True},
        }
        additions = {kind: observation(self.model, contract, kind, subject)
                     for kind, subject in subjects.items()}
        merge = next(item for item in observed["delivery_observations"]
                     if item["observation_kind"] == "pr_merged")
        implementation = observation(self.model, contract, "implementation_delivered", {
            "selected_subject": {"kind": "commit", "value": "a" * 40},
            "integration_subject": {"kind": "commit", "value": "b" * 40},
            "presence": {"kind": "reachability", "repository_id": "sim-repo",
                         "selected_value": "a" * 40, "integration_value": "b" * 40,
                         "integrated_ref": "refs/heads/main", "succeeded": True},
            "merge_observation_id": merge["id"], "acceptance_evidence_ids": ["accept-1"],
            "review_evidence_ids": ["review-1"], "test_evidence_ids": ["test-1"],
        })
        cleanup = observation(self.model, contract, "cleanup_complete", {
            "remote_branch_observation_ids": [additions["remote_branch_absent"]["id"]],
            "local_branch_observation_ids": [additions["local_branch_absent"]["id"]],
            "worktree_observation_ids": [additions["worktree_absent"]["id"]],
            "durable_detail": {"detail_pointer": ".superpowers/review-evidence/151/detail.json",
                               "read_evidence_digest": "sha256:" + "d" * 64,
                               "succeeded": True},
        })
        observed["delivery_observations"] += list(additions.values()) + [implementation, cleanup]
        observed["delivery_observations"].sort(key=lambda item: item["id"])
        result = self.model.reduce_delivery(contract, observed, evaluation=evaluation())
        self.assertEqual({fact["stage_id"] for fact in result["next_delivery"]["stage_facts"]
                          if fact["state"] == "observed"},
                         {stage["id"] for stage in contract["stages"]})
        self.assertTrue(all(item["state"] == "observed"
                            for item in result["next_delivery"]["postconditions"].values()))

        for mutation in ({"merged": False}, {"provider_repository_id": "other"},
                         {"pr_number": 999}, {"expected_head": "c" * 40},
                         {"base": "other"}):
            rejected_merge = copy.deepcopy(merge)
            rejected_merge["subject"].update(mutation); seal(self.model, rejected_merge)
            rejected_delivery = copy.deepcopy(implementation)
            rejected_delivery["subject"]["merge_observation_id"] = rejected_merge["id"]
            seal(self.model, rejected_delivery)
            candidate = copy.deepcopy(observed)
            candidate["delivery_observations"] = sorted(
                [item for item in candidate["delivery_observations"]
                 if item["observation_kind"] not in {"pr_merged", "implementation_delivered"}]
                + [rejected_merge, rejected_delivery], key=lambda item: item["id"])
            self.assertEqual(self.model.reduce_delivery(contract, candidate, evaluation=evaluation())
                ["next_delivery"]["postconditions"]["implementation_delivered"]["state"], "pending")

        for label, kind, mutation in (
            ("publication branch", "branch_published", {"branch": "other"}),
            ("PR head", "pr_opened", {"expected_head": "c" * 40}),
            ("merge PR", "pr_merged", {"pr_number": 18}),
            ("tracker issue", "tracker_closed", {"issue": 152}),
            ("remote target", "remote_branch_absent", {"branch": "other"}),
            ("local target", "local_branch_absent", {"branch": "other"}),
            ("worktree target", "worktree_absent", {"path": "/other"}),
        ):
            bad = copy.deepcopy(additions.get(kind) or next(
                item for item in observed["delivery_observations"]
                if item["observation_kind"] == kind))
            bad["subject"].update(mutation); seal(self.model, bad)
            candidate = rebind_contract(self.model, contract, delivery)
            candidate["delivery_observations"] = sorted([bad], key=lambda item: item["id"])
            reduced = self.model.reduce_delivery(contract, candidate, evaluation=evaluation())
            expected_stage = {"branch_published": "publish", "tracker_closed": "close",
                              "pr_opened": "open", "pr_merged": "merge",
                              "remote_branch_absent": "remote", "local_branch_absent": "local",
                              "worktree_absent": "worktree"}[kind]
            with self.subTest(label=label):
                self.assertEqual(next(f["state"] for f in reduced["next_delivery"]["stage_facts"]
                                      if f["stage_id"] == expected_stage), "pending")

        for label, item in (
            ("implementation missing", copy.deepcopy(implementation)),
            ("implementation failed", copy.deepcopy(implementation)),
            ("cleanup unreadable", copy.deepcopy(cleanup)),
            ("cleanup extra", copy.deepcopy(cleanup)),
        ):
            if label == "implementation missing": item["subject"].pop("test_evidence_ids")
            elif label == "implementation failed": item["subject"]["presence"]["succeeded"] = False
            elif label == "cleanup unreadable": item["subject"]["durable_detail"]["succeeded"] = False
            else: item["subject"]["extra"] = True
            seal(self.model, item)
            with self.subTest(label=label):
                self.assert_invalid(item, "delivery-observation")

        for label, item in (
            ("wrong selected subject", copy.deepcopy(implementation)),
            ("unknown merge reference", copy.deepcopy(implementation)),
            ("misplaced acceptance proof", copy.deepcopy(implementation)),
            ("wrong cleanup reference", copy.deepcopy(cleanup)),
        ):
            if label == "wrong selected subject":
                item["subject"]["selected_subject"]["value"] = "c" * 40
                item["subject"]["presence"]["selected_value"] = "c" * 40
            elif label == "unknown merge reference":
                item["subject"]["merge_observation_id"] = "sha256:" + "f" * 64
            elif label == "misplaced acceptance proof":
                item["subject"]["acceptance_evidence_ids"] = ["review-1"]
            else:
                item["subject"]["remote_branch_observation_ids"] = ["sha256:" + "f" * 64]
            seal(self.model, item)
            candidate = copy.deepcopy(observed)
            candidate["delivery_observations"] = [existing for existing in candidate["delivery_observations"]
                                                   if existing["observation_kind"] != item["observation_kind"]]
            candidate["delivery_observations"].append(item)
            candidate["delivery_observations"].sort(key=lambda existing: existing["id"])
            reduced = self.model.reduce_delivery(contract, candidate, evaluation=evaluation())
            with self.subTest(label=label):
                self.assertEqual(reduced["next_delivery"]["postconditions"]
                                 [item["observation_kind"]]["state"], "pending")

    def test_repository_record_stage_binds_digest_branch_and_reviews(self):
        contract, delivery = contract_and_delivery(self.model)
        for stage in contract["stages"]:
            stage["target_ref"]["subject_kind"] = "record"
        record_stage = {
            "id": "record", "kind": "deliver_repository_record", "action": "write_record",
            "effect": "repository_write", "target_ref": copy.deepcopy(contract["stages"][0]["target_ref"]),
            "worktree_requirement": "matching_required", "depends_on": ["select"],
            "retryable": True}
        open_stage = copy.deepcopy(contract["stages"][2]); open_stage["depends_on"] = ["record"]
        merge_stage = copy.deepcopy(contract["stages"][3]); merge_stage["depends_on"] = ["open"]
        contract["stages"] = [contract["stages"][0], record_stage, open_stage, merge_stage]
        delivery = rebind_contract(self.model, contract, delivery)
        chosen = selection(self.model, delivery["contract_digest"], subject_kind="record")
        selected_observation = observation(
            self.model, contract, "selected_output", {"selected_output": chosen})
        record = observation(self.model, contract, "repository_record_proposed", {
            "repository_id": "sim-repo", "selected_record_digest": chosen["subject_value"],
            "branch": "feature", "live_pr_head": "c" * 40,
            "review_evidence_ids": ["review-1", "test-1"]})
        opened = observation(self.model, contract, "pr_opened", {
            "provider_repository_id": "sim-repo", "pr_number": 17,
            "pr_url": "https://sim.invalid/pr/17", "expected_head": "c" * 40,
            "base": "main"})
        merged = observation(self.model, contract, "pr_merged", {
            "provider_repository_id": "sim-repo", "pr_number": 17,
            "pr_url": "https://sim.invalid/pr/17", "expected_head": "c" * 40,
            "base": "main", "merge_sha": "b" * 40, "merged": True})
        delivered = observation(self.model, contract, "implementation_delivered", {
            "selected_subject": {"kind": "record", "value": chosen["subject_value"]},
            "integration_subject": {"kind": "record", "value": chosen["subject_value"]},
            "presence": {"kind": "record_presence", "repository_id": "sim-repo",
                         "selected_value": chosen["subject_value"],
                         "integration_value": chosen["subject_value"],
                         "integrated_ref": "refs/heads/main", "succeeded": True},
            "merge_observation_id": merged["id"], "acceptance_evidence_ids": ["accept-1"],
            "review_evidence_ids": ["review-1"], "test_evidence_ids": ["test-1"]})
        candidate = copy.deepcopy(delivery)
        candidate["delivery_observations"] = sorted(
            [selected_observation, record, opened, merged, delivered],
                                                     key=lambda item: item["id"])
        result = self.model.reduce_delivery(contract, candidate, evaluation=evaluation())
        self.assertEqual(next(f["state"] for f in result["next_delivery"]["stage_facts"]
                              if f["stage_id"] == "record"), "observed")
        self.assertEqual(next(f["state"] for f in result["next_delivery"]["stage_facts"]
                              if f["stage_id"] == "merge"), "observed")
        self.assertEqual(result["next_delivery"]["postconditions"]
                         ["implementation_delivered"]["state"], "observed")
        for field, replacement in (("selected_record_digest", "sha256:" + "f" * 64),
                                   ("branch", "other"),
                                   ("repository_id", "other")):
            bad = copy.deepcopy(record); bad["subject"][field] = replacement; seal(self.model, bad)
            candidate["delivery_observations"] = sorted([selected_observation, bad, opened, merged],
                                                         key=lambda item: item["id"])
            reduced = self.model.reduce_delivery(contract, candidate, evaluation=evaluation())
            with self.subTest(field=field):
                self.assertEqual(next(f["state"] for f in reduced["next_delivery"]["stage_facts"]
                                      if f["stage_id"] == "record"), "pending")

        wrong_delivery = copy.deepcopy(delivered)
        wrong_delivery["subject"]["integration_subject"]["value"] = "sha256:" + "d" * 64
        wrong_delivery["subject"]["presence"]["integration_value"] = "sha256:" + "d" * 64
        seal(self.model, wrong_delivery)
        candidate["delivery_observations"] = sorted(
            [selected_observation, record, opened, merged, wrong_delivery],
            key=lambda item: item["id"])
        reduced = self.model.reduce_delivery(contract, candidate, evaluation=evaluation())
        self.assertEqual(reduced["next_delivery"]["postconditions"]
                         ["implementation_delivered"]["state"], "pending")

    def test_delivery_graph_binds_retained_contract_and_intent_identity(self):
        contract, delivery = contract_and_delivery(self.model)
        wrong = copy.deepcopy(delivery)
        wrong["contract"]["initial_authorization_intent_digest"] = "sha256:" + "e" * 64
        wrong["contract_digest"] = self.model.canonical_digest(wrong["contract"])
        self.assert_invalid(wrong, "delivery")

        active = custody(); requested = delivery["authorization_intents"][0]["scopes"][0]
        allowed = authority(self.model, contract, requested, active, verdict="allowed")
        allowed["contract_digest"] = "sha256:" + "f" * 64; seal(self.model, allowed)
        foreign = copy.deepcopy(delivery); foreign["authority_observations"] = [allowed]
        with self.assertRaises(self.model.DeliveryModelError):
            self.model.reduce_delivery(contract, foreign, evaluation=evaluation(
                custody=active, current_launch=True, requested_scope=requested))

        wrong_selection = selection(self.model, "sha256:" + "f" * 64)
        bad = copy.deepcopy(delivery); bad["selected_outputs"] = [wrong_selection]
        self.assert_invalid(bad, "delivery")

        selected_observation = observation(self.model, contract, "selected_output", {
            "selected_output": selection(self.model, delivery["contract_digest"])})
        selected_observation["project"]["repository_id"] = "other"; seal(self.model, selected_observation)
        bad = copy.deepcopy(delivery); bad["delivery_observations"] = [selected_observation]
        self.assert_invalid(bad, "delivery")

        denied, rejection = with_host_rejection(self.model, contract, delivery, active)
        evidence = reevaluation(self.model, contract, rejection)
        evidence["rejected_observation_id"] = "sha256:" + "9" * 64; seal(self.model, evidence)
        bad = copy.deepcopy(denied); bad["reevaluation_evidence"] = [evidence]
        self.assert_invalid(bad, "delivery")

        revoked = seal(self.model, {
            "schema_version": 1, "kind": "authority-observation", "id": "",
            "contract_digest": delivery["contract_digest"], "scope_id": requested["id"],
            "launch_id": None, "authority_kind": "intent_revocation", "verdict": "revoked",
            "reason_code": "revoked", "observed_at": "2026-09-20T02:00:00Z",
            "evidence_digest": "sha256:" + "8" * 64, "opaque_host_reference": None,
            "revocation_subject": {"intent_id": delivery["authorization_intents"][0]["id"],
                                   "revocation_key": "wrong-key"},
            "evaluation_use_key": None})
        bad = copy.deepcopy(delivery); bad["authority_observations"] = [revoked]
        self.assert_invalid(bad, "delivery")

    def test_contract_requires_normative_stage_dependencies(self):
        contract, _ = contract_and_delivery(self.model)
        for stage_id in ("publish", "open", "merge"):
            bad = copy.deepcopy(contract)
            next(stage for stage in bad["stages"] if stage["id"] == stage_id)["depends_on"] = []
            with self.subTest(stage=stage_id):
                self.assert_invalid(bad, "delivery-contract")
        cleanup, _ = cleanup_contract_and_delivery(self.model)
        self.validate(cleanup, "delivery-contract")
        for stage_id in ("remote", "worktree", "local"):
            bad = copy.deepcopy(cleanup)
            next(stage for stage in bad["stages"] if stage["id"] == stage_id)["depends_on"] = ["merge"]
            with self.subTest(cleanup=stage_id):
                self.assert_invalid(bad, "delivery-contract")

    def test_current_launch_and_null_contract_correlations_are_exact(self):
        fixtures = workflow_responses(self.model)
        malformed = copy.deepcopy(fixtures["current"])
        malformed.update(current=False, current_action_id="151:9:9", reason="unknown_run")
        self.assert_invalid(malformed, "workflow-response")
        no_contract = copy.deepcopy(fixtures["control"])
        summary = no_contract["summaries"][0]
        summary.update(custody=None, owner=None, worktree=None, deadline_at=None,
                       contract_digest=None, pending_stage_ids=[], requirements=[])
        no_contract["actions"] = []
        self.assert_invalid(no_contract, "workflow-response")
        summary["requirements"] = [{"kind": "delivery_contract", "subject_id": "151",
                                    "reason_code": "delivery_contract_required",
                                    "detail_pointer": None}]
        self.assertEqual(self.validate(no_contract, "workflow-response"), no_contract)

        valid_rows = (
            ("unknown_run", None), ("unknown_issue", None),
            ("inactive_attempt", None), ("inactive_attempt", "151:1:1"),
            ("unknown_attempt", "151:1:2"), ("superseded_attempt", "151:2:1"),
            ("superseded_launch", "151:1:2"),
        )
        for reason, current_action_id in valid_rows:
            value = {"action_id": "151:1:1", "current": False,
                     "current_action_id": current_action_id, "reason": reason}
            with self.subTest(reason=reason, current_action_id=current_action_id):
                self.assertEqual(self.validate(value, "workflow-response"), value)
        for reason, current_action_id in (
            ("unknown_issue", "151:1:2"), ("inactive_attempt", "151:1:2"),
            ("unknown_attempt", "151:1:1"), ("superseded_attempt", "151:1:1"),
            ("superseded_launch", "151:1:1"),
        ):
            value = {"action_id": "151:1:1", "current": False,
                     "current_action_id": current_action_id, "reason": reason}
            with self.subTest(invalid_reason=reason):
                self.assert_invalid(value, "workflow-response")

    def test_ship_handoff_cross_references_and_contract_order(self):
        contract, delivery = contract_and_delivery(self.model)
        handoff = ship_handoff(self.model, contract, delivery)
        self.assertEqual(self.validate(handoff, "ship-handoff"), handoff)
        for name, mutate in (
            ("issue", lambda value: value.update(issue_number=152)),
            ("chain", lambda value: value.update(authorization_chain_digest="sha256:" + "f" * 64)),
            ("pending", lambda value: value.update(pending_stage_ids=sorted(value["pending_stage_ids"]))),
        ):
            bad = copy.deepcopy(handoff); mutate(bad)
            with self.subTest(name=name): self.assert_invalid(bad, "ship-handoff")
        selected = selection(self.model, handoff["delivery_contract_digest"])
        selected["branch"] = "other"; seal(self.model, selected)
        bad = copy.deepcopy(handoff); bad["selected_outputs"] = [selected]
        self.assert_invalid(bad, "ship-handoff")
        bad = copy.deepcopy(handoff); bad["branch"] = "other"
        self.assert_invalid(bad, "ship-handoff")
    def test_source_and_generated_installed_layout_load_same_model(self):
        source = load_model(SOURCE, "delivery_model_source_layout")
        with tempfile.TemporaryDirectory() as raw:
            prior_path = list(sys.path)
            store = Path(raw) / "nix-store/delivery_model"
            shutil.copytree(SOURCE.parent, store)
            installed = Path(raw) / ".agents/lib/python/delivery_model"
            installed.parent.mkdir(parents=True)
            installed.symlink_to(store, target_is_directory=True)
            target = load_model(installed / "__init__.py", "delivery_model_installed_layout")
            self.assertEqual(source.canonical_bytes({"x": 1}), target.canonical_bytes({"x": 1}))
            self.assertEqual(sys.path, prior_path)
            (store / "_wire.py").unlink()
            with self.assertRaises((FileNotFoundError, ImportError)):
                load_model(installed / "__init__.py", "delivery_model_missing_private")
            self.assertNotIn("delivery_model_missing_private", sys.modules)

    def test_nix_publication_and_managed_test_registration(self):
        nix = DEFAULT_NIX.read_text(encoding="utf-8")
        self.assertIn('".agents/lib/python/delivery_model"', nix)
        self.assertIn("source = ./scripts/delivery_model;", nix)
        self.assertIn("recursive = false;", nix)
        self.assertIn("test_delivery_model.py", (ROOT / "justfile").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
