from __future__ import annotations

import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).parents[4]
SOURCE = ROOT / "home/common/agent-skills/scripts/delivery_model.py"
DEFAULT_NIX = ROOT / "home/common/agent-skills/default.nix"


def load_model(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError("delivery model loader unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
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


def selection(model, contract_digest):
    return seal(model, {
        "schema_version": 1, "kind": "selected-output", "id": "",
        "contract_digest": contract_digest, "slot_id": "reviewed",
        "subject_kind": "commit", "subject_value": "a" * 40,
        "data_identity_digest": "sha256:" + "2" * 64,
        "repository_id": "sim-repo", "branch": "feature", "base": "main",
        "evidence_digest": "sha256:" + "3" * 64,
        "review_evidence_ids": ["review-1", "test-1"],
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
    stages = []
    for index, (stage_id, kind, action, effect) in enumerate(stage_specs):
        stages.append({
            "id": stage_id, "kind": kind, "action": action, "effect": effect,
            "target_ref": ({
                "kind": "slot", "slot_id": "reviewed", "subject_kind": "commit",
                "constraints": {
                    "project_id": "sim-project", "provider": "github",
                    "repository_id": "sim-repo", "repository_slug": "sim.invalid/repo",
                    "branch": "feature", "base": "main", "deliverable_class": "source",
                    "data_ref": {"kind": "selected_output_slot", "slot_id": "reviewed",
                                 "classification": "source", "audience": "private"},
                },
            } if index == 0 else {"kind": "slot", "slot_id": "reviewed",
                                  "subject_kind": "commit", "constraints": {
                    "project_id": "sim-project", "provider": "github",
                    "repository_id": "sim-repo", "repository_slug": "sim.invalid/repo",
                    "branch": "feature", "base": "main", "deliverable_class": "source",
                    "data_ref": {"kind": "selected_output_slot", "slot_id": "reviewed",
                                 "classification": "source", "audience": "private"}}}),
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


def with_host_rejection(model, contract, delivery, active):
    result = copy.deepcopy(delivery)
    denial = authority(model, contract, result["authorization_intents"][-1]["scopes"][0], active)
    result["authority_observations"] = [denial]
    return result, denial


def observation(model, contract, kind, subject):
    return seal(model, {
        "schema_version": 1, "kind": "delivery-observation", "id": "",
        "contract_digest": model.canonical_digest(contract),
        "project": contract["project"], "observation_kind": kind, "subject": subject,
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


class DeliveryModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_model(SOURCE, "delivery_model_source_test")

    def test_import_is_pure_and_interface_is_exact(self):
        with tempfile.TemporaryDirectory() as raw:
            before = set(Path(raw).iterdir()); prior = Path.cwd()
            try:
                os.chdir(raw); module = load_model(SOURCE, "delivery_model_purity_test")
            finally:
                os.chdir(prior)
            self.assertEqual(module.MODEL_INTERFACE_VERSION, 1)
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
        self.assertEqual(self.model.validate_delivery_object(valid, expected_kind="scope-tuple", notes_max_characters=4096), valid)
        for mutation in ("unknown", "bool", "null", "id"):
            bad = copy.deepcopy(valid)
            if mutation == "unknown": bad["extra"] = 1
            if mutation == "bool": bad["target"]["issue"] = True
            if mutation == "null": bad["data"]["audience"] = None
            if mutation == "id": bad["id"] = "sha256:" + "f" * 64
            with self.subTest(mutation=mutation), self.assertRaises(self.model.DeliveryModelError):
                self.model.validate_delivery_object(bad, expected_kind="scope-tuple", notes_max_characters=4096)
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
            "revocation_subject": {"intent_id": first["id"], "revocation_key": "key-1"}})
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
        current = {"action_id": "151:1:1", "current": False,
                   "current_action_id": "151:1:2", "reason": "superseded_launch"}
        self.assertEqual(self.model.validate_delivery_object(current, expected_kind="workflow-response", notes_max_characters=4096), current)
        bootstrap = {"interface_version": 2, "kind": "workflow_bootstrap", "run_id": "run-1", "requirements": []}
        self.assertEqual(self.model.validate_delivery_object(bootstrap, expected_kind="workflow-response", notes_max_characters=4096), bootstrap)

    def test_source_and_generated_installed_layout_load_same_model(self):
        source = load_model(SOURCE, "delivery_model_source_layout")
        with tempfile.TemporaryDirectory() as raw:
            store = Path(raw) / "nix-store/delivery_model.py"; store.parent.mkdir(parents=True); store.write_bytes(SOURCE.read_bytes())
            installed = Path(raw) / ".agents/lib/python/delivery_model.py"; installed.parent.mkdir(parents=True); installed.symlink_to(store)
            target = load_model(installed, "delivery_model_installed_layout")
            self.assertEqual(source.canonical_bytes({"x": 1}), target.canonical_bytes({"x": 1}))

    def test_nix_publication_and_managed_test_registration(self):
        nix = DEFAULT_NIX.read_text(encoding="utf-8")
        self.assertIn('".agents/lib/python/delivery_model.py"', nix)
        self.assertIn("source = ./scripts/delivery_model.py;", nix)
        self.assertIn("test_delivery_model.py", (ROOT / "justfile").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
