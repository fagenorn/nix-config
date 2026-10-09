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
import runpy

from ._delivery_model_fixtures import (
    seal,
    custody,
    next_launch,
    scope,
    intent,
    selection,
    contract_and_delivery,
    contract_and_delivery_for_stage,
    stage_scope,
    requested_scope,
    authority,
    revocation,
    reevaluation,
    evaluation,
    native_evaluation,
    stage_state,
    post_state,
    workflow_responses,
    with_host_rejection,
    observation,
    pr_subject,
    with_observed,
    rebind_contract,
    cleanup_contract_and_delivery,
    record_case,
    renewal_case,
    ship_handoff,
    ship_checkpoint,
    direct_delivery_request,
    issue_with_attempt,
    sync_selection,
    at_head,
)

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

    def test_runtime_historical_merge_folds_facts_before_terminal_replay(self):
        runtime = runpy.run_path(str(SOURCE.parent.parent / "workflow_delivery.py"))[
            "DeliveryRuntime"](notes_max_characters=10_000)
        contract, delivery, _ = contract_and_delivery_for_stage(
            runtime.model, "select")
        forge = {"state": "merged", "url": "https://example.test/pull/17",
                 "merge_sha": "a" * 40}
        request = direct_delivery_request(
            contract, intents=delivery["authorization_intents"])
        request["forge"] = forge
        for retained in (delivery, runtime.empty_delivery()):
            issue = issue_with_attempt(retained, state="merged")
            result = {"state": "merged", "pr_url": forge["url"],
                      "merge_sha": forge["merge_sha"]}
            issue["attempts"][0]["result"] = copy.deepcopy(result)
            issue["outcome"] = copy.deepcopy(result)
            candidates = (request, {**request, "new_run": True},
                {**request, "forge": {**forge, "merge_sha": "b" * 40}})
            self.assertEqual(
                [runtime.historical_requested(
                    issue, forge=value["forge"], contract=value["delivery_contract"],
                    new_run=value["new_run"])
                 for value in candidates], [True, False, False])
            policy = runtime.delivery_policy(
                issue, issue=151, request=request, source_kind="direct",
                now="2026-09-21T00:01:00Z", dispatch_permitted=True,
                remainder_deadline="2026-09-21T03:01:00Z",
                owner_unavailable=False, tracker_halted=False,
                recorded_worktree={"path": "/worktree",
                                   "state": "matching_issue_branch"})
            self.assertEqual(
                (policy["operation"], issue["attempts"][0]["state"],
                 issue["delivery_remainders"][0]["owner"],
                 policy["reduction"]["pending_stage_ids"][0]),
                ("resume", "merged", "151:r1", "select"))

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
                "match_scope", "current_selection", "reduce_delivery", "STAGE_ACTIONS",
                "OBSERVATION_KINDS",
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
                self.assertEqual(post_state(reduced, "pr_merged"), expected)

    def slot_pr_delivery(self):
        """The fixture contract under an initial intent whose open/merge scopes bind the slot PR."""
        contract, delivery = contract_and_delivery(self.model)
        declared = []
        for stage_id in ("open", "merge"):
            value = stage_scope(self.model, contract, stage_id)
            value["target"]["pr_ref"] = {"kind": "slot", "slot_id": "reviewed"}
            declared.append(seal(self.model, value))
        first = intent(self.model, declared[0])
        first["scopes"] = sorted(declared, key=lambda item: item["id"])
        seal(self.model, first)
        contract["initial_authorization_intent_id"] = first["id"]
        contract["initial_authorization_intent_digest"] = self.model.canonical_digest(first)
        delivery = rebind_contract(self.model, contract, delivery)
        delivery["authorization_intents"] = [first]
        delivery["authorization_chain_digest"] = self.model.canonical_digest(
            {"intent_ids": [first["id"]]})
        return contract, delivery, first, declared

    def test_slot_pr_ref_grammar_requires_the_same_output_slot(self):
        _, _, _, declared = self.slot_pr_delivery()
        for item in declared:
            self.assertEqual(self.validate(item, "scope-tuple"), item)
        for output_ref in ({"kind": "none"}, {"kind": "slot", "slot_id": "other"}):
            bad = copy.deepcopy(declared[0])
            bad["target"]["output_ref"] = output_ref
            seal(self.model, bad)
            with self.subTest(output_ref=output_ref):
                self.assert_invalid(bad, "scope-tuple")
        bad = copy.deepcopy(declared[0])
        bad["target"]["pr_ref"] = {"kind": "slot", "slot_id": "reviewed", "extra": 1}
        seal(self.model, bad)
        self.assert_invalid(bad, "scope-tuple")

    def test_slot_pr_ref_matches_only_the_slot_form(self):
        contract, _, first, declared = self.slot_pr_delivery()
        selected = selection(self.model, self.model.canonical_digest(contract))
        at = {"selected_outputs": [selected], "at_time": "2026-09-21T00:00:00Z",
              "revocation_observations": []}
        self.assertEqual(self.model.match_scope(
            contract, first, declared[0], **at)["reason_code"], "matched")
        literal = copy.deepcopy(declared[0])
        literal["target"]["pr_ref"] = {"kind": "literal", "value": "17"}
        seal(self.model, literal)
        self.assertEqual(self.model.match_scope(
            contract, first, literal, **at)["reason_code"], "scope_target_mismatch")

    def test_slot_pr_ref_binds_the_opened_pr_without_a_successor(self):
        contract, delivery, _, _ = self.slot_pr_delivery()
        observed = with_observed(self.model, contract, delivery,
                                 ["select", "publish", "open", "merge"])
        reduced = self.model.reduce_delivery(contract, observed, evaluation=evaluation())
        self.assertEqual(
            (stage_state(reduced, "open"), stage_state(reduced, "merge"),
             post_state(reduced, "pr_merged")),
            ("observed", "observed", "observed"))
        self.assertEqual(len(reduced["next_delivery"]["authorization_intents"]), 1)

        second = observation(self.model, contract, "pr_opened",
                             pr_subject("pr_opened", pr=18))
        conflicting = copy.deepcopy(observed)
        conflicting["delivery_observations"] = sorted(
            conflicting["delivery_observations"] + [second], key=lambda item: item["id"])
        with self.assertRaises(self.model.DeliveryModelError):
            self.model.reduce_delivery(contract, conflicting, evaluation=evaluation())

        foreign = with_observed(self.model, contract, delivery, ["select", "publish"])
        foreign["delivery_observations"] = sorted(
            foreign["delivery_observations"] + [observation(
                self.model, contract, "pr_opened",
                pr_subject("pr_opened", head="c" * 40))],
            key=lambda item: item["id"])
        reduced = self.model.reduce_delivery(contract, foreign, evaluation=evaluation())
        self.assertEqual(stage_state(reduced, "open"), "pending")

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
        revoked = revocation(self.model, contract, first)
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
        self.assertEqual(post_state(done, "pr_merged"), "observed")
        self.assertEqual(post_state(done, "implementation_delivered"), "pending")
        self.assertEqual(delivery, before)

    def test_requested_scope_is_bound_to_postfold_contract_stage(self):
        contract, delivery = contract_and_delivery(self.model); active = custody()
        def reduce(candidate_contract, candidate_delivery, candidate_scope):
            return self.model.reduce_delivery(candidate_contract, candidate_delivery,
                evaluation=evaluation(custody=active, current_launch=True,
                                      requested_scope=candidate_scope))
        with self.assertRaises(self.model.DeliveryModelError):
            reduce(contract, delivery, delivery["authorization_intents"][0]["scopes"][0])
        missing = reduce(contract, delivery, None)
        self.assertIsNone(missing["requested_scope"])
        self.assertEqual(missing["requirements"], [{"kind": "scope_tuple", "subject_id": "select", "reason_code": "scope_tuple_required", "detail_pointer": None}])
        uncovered = reduce(contract, delivery, stage_scope(self.model, contract, "select"))
        self.assertEqual((uncovered["blocking"]["blocked_on"], uncovered["requirements"][0]["reason_code"]), ("human_gate", "authorization_intent_required"))
        covered_contract, covered_delivery, covered_scope = contract_and_delivery_for_stage(self.model, "select")
        ordinary = reduce(covered_contract, covered_delivery, covered_scope)
        self.assertEqual((ordinary["requested_scope"], ordinary["requirements"][0]["reason_code"], ordinary["blocking"]), (covered_scope, "native_evaluation_required", None))

    def test_d19_slot_scope_binds_selected_identity_and_data(self):
        contract, delivery, declared = contract_and_delivery_for_stage(self.model, "publish")
        delivery = with_observed(self.model, contract, delivery, ["select"])
        delivery = self.model.reduce_delivery(contract, delivery, evaluation=evaluation())["next_delivery"]
        selected = delivery["selected_outputs"][0]
        literal = requested_scope(self.model, declared, selected)
        reduced = self.model.reduce_delivery(contract, delivery, evaluation=evaluation(
            custody=custody(), current_launch=True, requested_scope=literal))
        self.assertEqual(reduced["requested_scope"], literal)
        for path, replacement in (
            (("target", "output_ref", "value"), "b" * 40),
            (("target", "issue"), 152),
            (("target", "repository_id"), "other-repo"),
            (("target", "base"), "other-base"),
            (("data", "digest"), "sha256:" + "f" * 64),
            (("data", "classification"), "binary"),
            (("data", "audience"), "public"),
        ):
            bad = copy.deepcopy(literal); cursor = bad
            for key in path[:-1]: cursor = cursor[key]
            cursor[path[-1]] = replacement; seal(self.model, bad)
            with self.subTest(path=path):
                with self.assertRaises(self.model.DeliveryModelError):
                    self.model.reduce_delivery(contract, delivery, evaluation=evaluation(
                        custody=custody(), current_launch=True, requested_scope=bad))

    def test_d19_completion_requires_postcondition_observation_and_null_scope(self):
        contract, delivery, declared = contract_and_delivery_for_stage(self.model, "merge")
        delivery = with_observed(self.model, contract, delivery, ["select", "publish", "open", "merge"])
        reduced = self.model.reduce_delivery(contract, delivery, evaluation=evaluation())
        self.assertEqual(reduced["requirements"], [{"kind": "observation",
            "subject_id": "implementation_delivered", "reason_code": "postcondition_observation_required",
            "detail_pointer": None}])
        with self.assertRaises(self.model.DeliveryModelError):
            self.model.reduce_delivery(contract, delivery, evaluation=evaluation(
                custody=custody(), current_launch=True, requested_scope=declared))

    def test_d19_literal_cleanup_scopes_bind_exact_targets(self):
        contract, delivery = cleanup_contract_and_delivery(self.model)
        current = with_observed(self.model, contract, delivery,
                                ["select", "publish", "open", "merge"])
        cases = (
            ("close", "tracker_closed", {
                "tracker_repository_id": "sim-repo", "issue": 151,
                "state": "closed", "close_reason": "completed",
                "observation_identity": "tracker:151:closed"},
             ("target", "issue", 152)),
            ("remote", "remote_branch_absent",
             {"repository_id": "sim-repo", "branch": "feature", "absent": True},
             ("target", "branch", "other")),
            ("worktree", "worktree_absent",
             {"path": "/worktree", "recorded_worktree_identity": "wt-151",
              "probe_mode": "no_follow", "absent": True},
             ("endpoint", "value", "/other")),
            ("local", "local_branch_absent",
             {"repository_id": "sim-repo", "branch": "feature", "absent": True},
             ("target", "branch", "other")),
        )
        for stage_id, observation_kind, subject, mutation in cases:
            exact = stage_scope(self.model, contract, stage_id)
            result = self.model.reduce_delivery(contract, current, evaluation=evaluation(
                custody=custody(), current_launch=True, requested_scope=exact))
            self.assertEqual(result["requested_scope"], exact)
            bad = copy.deepcopy(exact)
            bad[mutation[0]][mutation[1]] = mutation[2]; seal(self.model, bad)
            with self.subTest(stage=stage_id, target="neighbor"):
                with self.assertRaises(self.model.DeliveryModelError):
                    self.model.reduce_delivery(contract, current, evaluation=evaluation(
                        custody=custody(), current_launch=True, requested_scope=bad))
            current = copy.deepcopy(current)
            current["delivery_observations"].append(
                observation(self.model, contract, observation_kind, subject))
            current["delivery_observations"].sort(key=lambda item: item["id"])

    def test_d19_wire_null_requirements_are_local(self):
        fixtures = workflow_responses(self.model)
        stage_requirement = {"kind": "scope_tuple", "subject_id": "select",
                             "reason_code": "scope_tuple_required", "detail_pointer": None}
        postcondition = {"kind": "observation", "subject_id": "implementation_delivered",
                         "reason_code": "postcondition_observation_required",
                         "detail_pointer": None}
        for name in ("owner", "remainder", "checkpointed"):
            value = copy.deepcopy(fixtures[name])
            self.assertEqual(value["requirements"], [stage_requirement])
            self.assertEqual(self.validate(value, "workflow-response"), value)
            for requirements in (
                [], [{"kind": "tracker"}],
                [{**stage_requirement, "subject_id": "publish"}],
                [{**stage_requirement, "subject_id": "bogus"}],
                [postcondition], [{**stage_requirement, "detail_pointer": "derived"}],
            ):
                bad = copy.deepcopy(value); bad["requirements"] = requirements
                with self.subTest(envelope=name, invalid=requirements):
                    self.assert_invalid(bad, "workflow-response")
            for requirements in ([], [postcondition]):
                complete = copy.deepcopy(value)
                complete["pending_stage_ids"] = []; complete["requirements"] = requirements
                with self.subTest(envelope=name, complete=requirements):
                    self.assertEqual(self.validate(complete, "workflow-response"), complete)
            for malformed in (
                {**postcondition, "subject_id": "unknown_postcondition"},
                {**postcondition, "reason_code": "dependency_observation_required"},
                {**postcondition, "detail_pointer": "derived"},
            ):
                bad = copy.deepcopy(value)
                bad["pending_stage_ids"] = []; bad["requirements"] = [malformed]
                with self.subTest(envelope=name, malformed_postcondition=malformed):
                    self.assert_invalid(bad, "workflow-response")
            bad = copy.deepcopy(value)
            bad["pending_stage_ids"] = []; bad["requirements"] = []
            bad["requested_scope"] = stage_scope(self.model, fixtures["owner"]["contract"], "select")
            with self.subTest(envelope=name, nonnull_scope_without_pending=True):
                self.assert_invalid(bad, "workflow-response")
        dependency = copy.deepcopy(fixtures["checkpointed"])
        dependency["requirements"] = [{"kind": "observation", "subject_id": "publish",
            "reason_code": "dependency_observation_required", "detail_pointer": None}]
        self.assertEqual(self.validate(dependency, "workflow-response"), dependency)

    def test_d19_wire_permit_and_nested_correlations_are_closed(self):
        fixtures = workflow_responses(self.model); owner = fixtures["owner"]
        _, delivery = contract_and_delivery(self.model)
        declared = delivery["authorization_intents"][0]["scopes"][0]
        actual = requested_scope(
            self.model, declared, selection(self.model, owner["contract_digest"]))
        declared_id = declared["id"]
        self.assertNotEqual(actual["id"], declared_id)
        permit = native_evaluation(owner["contract_digest"], owner["custody"], declared_id)
        for name in ("owner", "remainder", "checkpointed"):
            bad = copy.deepcopy(fixtures[name]); bad["authority_evaluation"] = copy.deepcopy(permit)
            if name == "remainder":
                bad["authority_evaluation"] = native_evaluation(
                    bad["contract_digest"], bad["custody"], declared_id)
            with self.subTest(valid_permit_with_null_scope=name):
                self.assert_invalid(bad, "workflow-response")
        checkpoint = copy.deepcopy(fixtures["checkpointed"])
        checkpoint["pending_stage_ids"] = ["merge"]
        checkpoint.update(requested_scope=actual, requirements=[{
            "kind": "observation", "subject_id": declared_id,
            "reason_code": "native_evaluation_required", "detail_pointer": None}],
            authority_evaluation=permit)
        self.assertIsNone(checkpoint["next_action"])
        self.assertEqual(self.validate(checkpoint, "workflow-response"), checkpoint)
        checkpoint["authority_evaluation"] = None
        checkpoint["next_action"] = copy.deepcopy(owner)
        checkpoint["next_action"]["pending_stage_ids"] = ["merge"]
        checkpoint["next_action"].update(
            requested_scope=copy.deepcopy(actual),
            requirements=copy.deepcopy(checkpoint["requirements"]))
        self.assertEqual(self.validate(checkpoint, "workflow-response"), checkpoint)
        mutations = {
            "scope": lambda outer: outer["next_action"].update(
                requested_scope=stage_scope(self.model, owner["contract"], "publish")),
            "custody": lambda outer: outer.update(custody=next_launch(outer["custody"])),
            "contract_digest": lambda outer: outer.update(contract_digest="sha256:" + "f" * 64),
            "pending_stage_ids": lambda outer: outer.update(pending_stage_ids=["select"]),
            "requirements": lambda outer: outer.update(requirements=[{
                "kind": "scope_tuple", "subject_id": "select",
                "reason_code": "scope_tuple_required", "detail_pointer": None}]),
            "authority_evaluation": lambda outer: outer.update(authority_evaluation=
                native_evaluation(outer["contract_digest"], outer["custody"], declared_id)),
            "ledger_repo_root": lambda outer: outer.update(ledger_repo_root="/other"),
            "run_id": lambda outer: outer.update(run_id="other-run"),
            "owner": lambda outer: outer.update(owner="151:other"),
        }
        for field, mutate in mutations.items():
            bad = copy.deepcopy(checkpoint); mutate(bad)
            with self.subTest(nested_common_field=field):
                self.assert_invalid(bad, "workflow-response")
        issue_mismatch = copy.deepcopy(checkpoint)
        issue_mismatch.update(issue=152, custody={"kind": "implementation", "attempt": 1,
            "launch": 1, "action_id": "152:1:1"})
        issue_mismatch["requested_scope"]["target"]["issue"] = 152
        seal(self.model, issue_mismatch["requested_scope"])
        self.assert_invalid(issue_mismatch, "workflow-response")

    def test_d19_report_scope_identities_are_closed(self):
        contract, delivery = contract_and_delivery(self.model)
        historical = stage_scope(self.model, contract, "select")
        checkpoint = ship_checkpoint(self.model, contract, historical)
        self.assertEqual(self.validate(checkpoint, "ship-checkpoint"), checkpoint)
        bad = copy.deepcopy(checkpoint); bad["requested_scope"]["target"]["issue"] = 152
        seal(self.model, bad["requested_scope"]); self.assert_invalid(bad, "ship-checkpoint")
        handoff = ship_handoff(self.model, contract, delivery)
        handoff["requested_scope"] = copy.deepcopy(historical)
        self.assertEqual(self.validate(handoff, "ship-handoff"), handoff)
        for field, replacement in (("issue", 152), ("project_id", "other-project"),
                                   ("provider", "other-provider"),
                                   ("repository_id", "other-repo"),
                                   ("repository_slug", "other/repo")):
            foreign = copy.deepcopy(handoff)
            foreign["requested_scope"]["target"][field] = replacement
            seal(self.model, foreign["requested_scope"])
            with self.subTest(handoff_target=field):
                self.assert_invalid(foreign, "ship-handoff")

    def test_rejection_bases_are_independent_and_one_shot(self):
        contract, delivery, requested = contract_and_delivery_for_stage(self.model, "merge")
        delivery = with_observed(self.model, contract, delivery, ["select", "publish", "open"]); active = custody()
        denied, rejection = with_host_rejection(self.model, contract, delivery, active)
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
        contract, delivery, requested = contract_and_delivery_for_stage(self.model, "merge")
        delivery = with_observed(self.model, contract, delivery, ["select", "publish", "open"])
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
            requested_scope=requested))
        self.assertEqual(result["blocking"], {"blocked_on": "human_gate",
            "reason_code": "host_rejected", "subject_id": rejection["id"]})

    def test_late_old_launch_facts_are_history_not_current_authority(self):
        contract, delivery, declared = contract_and_delivery_for_stage(self.model, "merge")
        delivery = with_observed(self.model, contract, delivery, ["select", "publish", "open"]); old = custody(); current = next_launch(old)
        allowed = authority(self.model, contract, declared, old, verdict="allowed")
        reduced = self.model.reduce_delivery(contract, delivery, evaluation=evaluation(
            custody=current, current_launch=True, requested_scope=declared,
            authority_observations=[allowed], source_kind="direct"))
        self.assertIn(allowed["id"], {x["id"] for x in reduced["next_delivery"]["authority_observations"]})
        self.assertEqual(reduced["requirements"][0]["reason_code"], "native_evaluation_required")
        for allow_at, revoke_at, operative in (
            ("2026-09-20T01:00:00Z", None, True),
            ("2026-09-20T02:00:00Z", None, True),
            ("2026-09-20T02:00:01Z", None, False),
            ("2026-09-20T01:00:00Z", "2026-09-20T01:30:00Z", True),
            ("2026-09-20T01:30:01Z", "2026-09-20T01:30:00Z", False),
        ):
            with self.subTest(allow_at=allow_at, revoke_at=revoke_at):
                result, retained = renewal_case(self.model, allow_at, revoke_at)
                self.assertIn(retained["id"], {item["id"] for item in
                              result["next_delivery"]["authority_observations"]})
                reason = None if operative else "native_evaluation_required"
                self.assertEqual(result["requirements"][0]["reason_code"]
                                 if result["requirements"] else None, reason)

    def test_workflow_response_validation_is_structural_only(self):
        fixtures = workflow_responses(self.model)
        self.assertEqual(set(fixtures), {"current", "bootstrap", "control", "observe", "owner",
            "terminal", "remainder", "checkpointed", "stalled", "complete", "failed",
            "host_route", "host_route_unsupported", "phase_gate", "suspended"})
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
        bad = copy.deepcopy(fixtures["host_route"]); bad["agent_slots"] = 3; mutations["host_route_floor"] = bad
        bad = copy.deepcopy(fixtures["host_route"]); bad["reason_code"] = "declared_unsupported"; mutations["host_route_supported_reason"] = bad
        bad = copy.deepcopy(fixtures["host_route_unsupported"]); bad["reason_code"] = "busy"; mutations["host_route_reason"] = bad
        bad = copy.deepcopy(fixtures["host_route_unsupported"]); bad["alternative"] = None; mutations["host_route_alternative"] = bad
        bad = copy.deepcopy(fixtures["control"]); bad["admission"]["waiting"] = [151]; mutations["waiting_dispatched"] = bad
        bad = copy.deepcopy(fixtures["control"]); bad["interface_version"] = 2; mutations["control_interface_two"] = bad
        bad = copy.deepcopy(fixtures["control"]); bad["admission"]["route"] = "direct"; mutations["direct_with_slots"] = bad
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
        self.assertEqual(post_state(result, "pr_merged"), "pending")
        self.assertEqual(next(item["state"] for item in result["next_delivery"]["stage_facts"] if item["stage_id"] == "merge"), "pending")

        repeated = with_observed(self.model, contract, delivery, ["select", "publish"])
        branch = next(item for item in repeated["delivery_observations"] if item["observation_kind"] == "branch_published")
        reprobe = copy.deepcopy(branch); reprobe["observed_at"] = "2026-09-20T04:00:00Z"; seal(self.model, reprobe)
        compatible = self.model.reduce_delivery(contract, repeated, evaluation=evaluation(delivery_observations=[reprobe]))
        self.assertEqual(next(item["state"] for item in compatible["next_delivery"]["stage_facts"] if item["stage_id"] == "publish"), "observed")

    def test_selected_slot_preserves_exact_none_and_literal_data(self):
        literal = {"kind": "literal", "digest": "sha256:" + "6" * 64,
                   "classification": "source", "audience": "private"}
        for declared_data in ({"kind": "none"}, literal):
            contract, delivery = contract_and_delivery(self.model)
            for stage in contract["stages"]:
                stage["target_ref"]["constraints"]["data_ref"] = declared_data
            declared = stage_scope(self.model, contract, "publish")
            first = intent(self.model, declared)
            contract["initial_authorization_intent_id"] = first["id"]
            contract["initial_authorization_intent_digest"] = self.model.canonical_digest(first)
            delivery = rebind_contract(self.model, contract, delivery)
            delivery["authorization_intents"] = [first]
            delivery["authorization_chain_digest"] = self.model.canonical_digest(
                {"intent_ids": [first["id"]]})
            chosen = selection(self.model, delivery["contract_digest"])
            observed = observation(
                self.model, contract, "selected_output", {"selected_output": chosen})
            folded = self.model.reduce_delivery(
                contract, delivery, evaluation=evaluation(delivery_observations=[observed]))
            for actual in (declared, copy.deepcopy(declared)):
                actual["target"]["output_ref"] = (
                    actual["target"]["output_ref"] if actual is declared else
                    {"kind": "literal", "value": chosen["subject_value"]})
                seal(self.model, actual)
                result = self.model.reduce_delivery(
                    contract, folded["next_delivery"], evaluation=evaluation(
                        custody=custody(), current_launch=True,
                        requested_scope=actual))
                self.assertEqual(result["requested_scope"], actual)
            wrong = copy.deepcopy(actual)
            wrong["data"] = (literal if declared_data["kind"] == "none" else
                             {**literal, "digest": "sha256:" + "7" * 64})
            seal(self.model, wrong)
            with self.assertRaises(self.model.DeliveryModelError):
                self.model.reduce_delivery(
                    contract, folded["next_delivery"], evaluation=evaluation(
                        custody=custody(), current_launch=True,
                        requested_scope=wrong))

    def test_consumed_rejection_allows_one_fresh_current_result(self):
        contract, delivery, requested = contract_and_delivery_for_stage(self.model, "merge")
        delivery = with_observed(self.model, contract, delivery, ["select", "publish", "open"]); active = custody()
        denied, rejection = with_host_rejection(self.model, contract, delivery, active)
        basis = reevaluation(self.model, contract, rejection)
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
        self.assertEqual(post_state(reduced, "tracker_closed"), "pending")
        self.assertEqual(stage_state(reduced, "close"), "pending")

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

        foreign_open = copy.deepcopy(observed)
        opened = next(item for item in foreign_open["delivery_observations"]
                      if item["observation_kind"] == "pr_opened")
        opened["subject"]["provider_repository_id"] = "foreign-repo"; seal(self.model, opened)
        foreign_open["delivery_observations"].sort(key=lambda item: item["id"])
        result = self.model.reduce_delivery(contract, foreign_open, evaluation=evaluation())
        self.assertEqual({fact["stage_id"]: fact["state"] for fact in result["next_delivery"]["stage_facts"]}
                         ["merge"], "pending")

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
            self.assertEqual(post_state(self.model.reduce_delivery(contract, candidate, evaluation=evaluation()),
                           "implementation_delivered"), "pending")

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
                self.assertEqual(stage_state(reduced, expected_stage), "pending")

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
                self.assertEqual(post_state(reduced, item["observation_kind"]), "pending")

    def test_repository_record_stage_binds_digest_branch_and_reviews(self):
        for with_merge in (True, False):
            contract, delivery, items = record_case(self.model, with_merge=with_merge)
            result = self.model.reduce_delivery(contract, delivery, evaluation=evaluation())
            self.assertEqual(stage_state(result, "record"), "observed")
            self.assertEqual(post_state(result, "implementation_delivered"), "observed")
            wrong = record_case(self.model, with_merge=with_merge,
                                integrated="sha256:" + "d" * 64)
            reduced = self.model.reduce_delivery(wrong[0], wrong[1], evaluation=evaluation())
            self.assertEqual(post_state(reduced, "implementation_delivered"), "pending")
            if not with_merge:
                continue
            self.assertEqual(stage_state(result, "merge"), "observed")
            for field, replacement in (("selected_record_digest", "sha256:" + "f" * 64),
                                       ("branch", "other"), ("repository_id", "other")):
                bad = copy.deepcopy(items["record"])
                bad["subject"][field] = replacement; seal(self.model, bad)
                candidate = copy.deepcopy(delivery)
                candidate["delivery_observations"] = sorted(
                    [item for item in candidate["delivery_observations"]
                     if item["observation_kind"] != "repository_record_proposed"] + [bad],
                    key=lambda item: item["id"])
                reduced = self.model.reduce_delivery(contract, candidate, evaluation=evaluation())
                with self.subTest(field=field):
                    self.assertEqual(stage_state(reduced, "record"), "pending")

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

        revoked = revocation(self.model, contract, delivery["authorization_intents"][0],
                             key="wrong-key")
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

    def test_phase_gate_reply_is_closed_and_bound_to_its_issue(self):
        """#191 D5: `progress` replies with one closed v2 `phase_gate`."""
        gate = workflow_responses(self.model)["phase_gate"]
        for action in ("continue", "fresh_start", "handoff", "delegate"):
            value = {**copy.deepcopy(gate), "action": action, "handoff_path": None}
            with self.subTest(action=action):
                self.assertEqual(self.validate(value, "workflow-response"), value)
        missing = copy.deepcopy(gate)
        del missing["handoff_path"]
        for name, bad in {
            "extra member": {**copy.deepcopy(gate), "phase_action": "handoff"},
            "missing member": missing,
            "interface 1": {**copy.deepcopy(gate), "interface_version": 1},
            "remainder custody": {**copy.deepcopy(gate), "custody": custody("remainder")},
            "another issue's custody": {**copy.deepcopy(gate), "issue": 152},
            "unknown action": {**copy.deepcopy(gate), "action": "retry"},
            "handoff path on continue": {**copy.deepcopy(gate), "action": "continue"},
            "empty handoff path": {**copy.deepcopy(gate), "handoff_path": ""},
            "null run": {**copy.deepcopy(gate), "run_id": None},
        }.items():
            with self.subTest(invalid=name):
                self.assert_invalid(bad, "workflow-response")

    def test_suspended_reply_is_closed_and_names_an_owner_cause(self):
        """#191 D6: a granted suspension replies with one closed v2 `suspended`."""
        suspended = workflow_responses(self.model)["suspended"]
        for cause in ("usage_limit", "transport", "human_gate", "external", "agent_dispatch", "deadline"):
            value = {**copy.deepcopy(suspended), "blocked_on": cause}
            with self.subTest(blocked_on=cause):
                self.assertEqual(self.validate(value, "workflow-response"), value)
        missing = copy.deepcopy(suspended)
        del missing["reentry"]
        for name, bad in {
            "the unversioned reply": {"kind": "suspended", "issue": 151, "attempt": 1,
                                      "blocked_on": "usage_limit", "stalled_resumes": 0,
                                      "reentry": "/from-issue 151 --auto"},
            "extra member": {**copy.deepcopy(suspended), "stalled_resumes": 0},
            "missing member": missing,
            "interface 1": {**copy.deepcopy(suspended), "interface_version": 1},
            "remainder custody": {**copy.deepcopy(suspended), "custody": custody("remainder")},
            "another issue's custody": {**copy.deepcopy(suspended), "issue": 152},
            "the reaper's cause": {**copy.deepcopy(suspended), "blocked_on": "unknown"},
            "control's cause": {**copy.deepcopy(suspended), "blocked_on": "host_capacity"},
            "empty reentry": {**copy.deepcopy(suspended), "reentry": ""},
            "null run": {**copy.deepcopy(suspended), "run_id": None},
        }.items():
            with self.subTest(invalid=name):
                self.assert_invalid(bad, "workflow-response")

    def test_current_launch_and_null_contract_correlations_are_exact(self):
        fixtures = workflow_responses(self.model)
        malformed = copy.deepcopy(fixtures["current"])
        malformed.update(current=False, current_action_id="151:9:9", reason="unknown_run")
        self.assert_invalid(malformed, "workflow-response")
        no_contract = copy.deepcopy(fixtures["control"])
        summary = no_contract["summaries"][0]
        summary.update(custody=None, owner=None, worktree=None, deadline_at=None,
                       contract_digest=None, pending_stage_ids=[], requirements=[])
        # A null digest never names its issue in an action (D12, D31).
        self.assert_invalid(no_contract, "workflow-response")
        no_contract["actions"] = []
        self.assertEqual(self.validate(no_contract, "workflow-response"), no_contract)
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

    def test_control_summaries_admit_one_closed_unresumable_worktree_fact(self):
        """T5 (#194): the per-issue resume refusal's closed rules at the control boundary."""
        fixtures = workflow_responses(self.model)
        fact = {"kind": "worktree_fact", "subject_id": "/worktree",
                "reason_code": "recorded_worktree_absent", "detail_pointer": None}
        contract_required = {"kind": "delivery_contract", "subject_id": "151",
                             "reason_code": "delivery_contract_required",
                             "detail_pointer": None}

        def with_fact(requirements, *, contracted=True, worktree="/worktree", dispatch=False):
            """The control fixture with issue 151 refused: no delta, only `finalize`."""
            value = copy.deepcopy(fixtures["control"])
            summary = value["summaries"][0]
            summary.update(worktree=worktree, requirements=sorted(
                copy.deepcopy(requirements), key=self.model.canonical_bytes))
            if not contracted:
                summary.update(contract_digest=None, pending_stage_ids=[])
            owner = fixtures["control"]["actions"]
            value.update(deltas=[], next_deadline=None, actions=[
                *(copy.deepcopy(owner) if dispatch else []),
                {"id": "finalize", "kind": "finalize"}])
            return value

        mismatch = {**fact, "reason_code": "recorded_worktree_mismatch"}
        for name, value in {
                "contracted_absent": with_fact([fact]),
                "contracted_mismatch": with_fact([mismatch]),
                "contractless": with_fact([fact], contracted=False),
                "contractless_with_its_contract_requirement": with_fact(
                    [contract_required, fact], contracted=False),
                "no_summary_worktree": with_fact(
                    [{**fact, "subject_id": "/removed"}], worktree=None),
        }.items():
            with self.subTest(accepted=name):
                self.assertEqual(self.validate(value, "workflow-response"), value)
        for name, value in {
                "unknown_code": with_fact([{**fact, "reason_code": "recorded_worktree_gone"}]),
                "detail_pointer": with_fact([{**fact, "detail_pointer": "/detail"}]),
                "other_subject": with_fact([{**fact, "subject_id": "/elsewhere"}]),
                "two_facts": with_fact([fact, mismatch]),
                "dispatched": with_fact([fact], dispatch=True),
                "contractless_extra": with_fact([fact, {"kind": "scope_tuple",
                    "subject_id": "select", "reason_code": "scope_tuple_required",
                    "detail_pointer": None}], contracted=False),
        }.items():
            with self.subTest(rejected=name):
                self.assert_invalid(value, "workflow-response")

    def test_control_delivery_contract_is_coupled_to_its_summaries(self):
        """#221 D6: `delivery_contract` lists only asking issues, last and alone."""
        fixtures = workflow_responses(self.model)

        def asking(issue):
            return {"kind": "delivery_contract", "subject_id": str(issue),
                    "reason_code": "delivery_contract_required", "detail_pointer": None}

        def reply():
            value = copy.deepcopy(fixtures["control"])
            template = value["summaries"][0]
            value["summaries"] = [{**copy.deepcopy(template), "issue": issue, "state": "queued",
                "custody": None, "owner": None, "worktree": None, "deadline_at": None,
                "contract_digest": None, "pending_stage_ids": [],
                "requirements": [asking(issue)]} for issue in (152, 151)]
            value.update(deltas=[], next_deadline=None, actions=[
                {"id": "delivery_contract", "kind": "delivery_contract", "issues": [152, 151]}])
            value["admission"].update(available=7, reserved={
                "controller": 0, "owner": 0, "worker": 0, "reviewer": 0})
            return value

        def mutated(change):
            value = reply(); change(value); return value

        def action(value):
            return value["actions"][-1]

        def not_last(value):
            # Only the last-position rule may reject this (Phase-5 SF-2): the
            # fixture's contracted, dispatched issue 151 (its summary, spawn
            # delta, `control_owner` action and admission reservation) is put
            # first, the asking issues move to 152 and 153, and the non-terminal
            # spawn follows the request; `next_deadline` stays null.
            dispatched = copy.deepcopy(fixtures["control"])
            for summary, issue in zip(value["summaries"], (152, 153)):
                summary.update(issue=issue, requirements=[asking(issue)])
            value["summaries"].insert(0, dispatched["summaries"][0])
            value.update(deltas=dispatched["deltas"], admission=dispatched["admission"],
                         actions=[{"id": "delivery_contract", "kind": "delivery_contract",
                                   "issues": [152, 153]}, *dispatched["actions"]])

        self.assertEqual(self.validate(reply(), "workflow-response"), reply())
        only_152 = mutated(lambda value: action(value).update(issues=[152]))
        self.assertEqual(self.validate(only_152, "workflow-response"), only_152)
        digest = fixtures["control"]["summaries"][0]["contract_digest"]
        finalize = {"id": "finalize", "kind": "finalize"}
        wait = {"id": "wait:2026-09-21T01:00:00Z", "kind": "wait", "wake_on": ["deadline"],
                "deadline_at": "2026-09-21T01:00:00Z", "wait_seconds": 3600}
        for name, change in {
                "extra_member": lambda value: action(value).update(issue=151),
                "missing_issues": lambda value: action(value).pop("issues"),
                "other_id": lambda value: action(value).update(id="delivery_contract:151"),
                "empty": lambda value: action(value).update(issues=[]),
                "not_a_list": lambda value: action(value).update(issues=151),
                "boolean_issue": lambda value: action(value).update(issues=[True]),
                "float_issue": lambda value: action(value).update(issues=[152.0]),
                "duplicate": lambda value: action(value).update(issues=[152, 152]),
                "out_of_order": lambda value: action(value).update(issues=[151, 152]),
                "unknown_issue": lambda value: action(value).update(issues=[152, 153]),
                "not_asking": lambda value: value["summaries"][1].update(requirements=[]),
                "contracted": lambda value: value["summaries"][0].update(
                    contract_digest=digest, requirements=[]),
                "waiting": lambda value: value["admission"].update(waiting=[152]),
                "not_last": not_last,
                "with_finalize": lambda value: value["actions"].insert(0, copy.deepcopy(finalize)),
                "with_wait": lambda value: value["actions"].insert(0, copy.deepcopy(wait)),
                "deadline_armed": lambda value: value.update(next_deadline="2026-09-21T01:00:00Z"),
                "twice": lambda value: value["actions"].insert(0, copy.deepcopy(action(value))),
        }.items():
            with self.subTest(rejected=name):
                self.assert_invalid(mutated(change), "workflow-response")

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

    def test_ship_handoff_admits_acceptance_state_as_a_string(self):
        """#272 D9: the model admits the key; artifact-budget owns its values."""
        contract, delivery = contract_and_delivery(self.model)
        handoff = ship_handoff(self.model, contract, delivery)
        self.assertEqual(handoff["acceptance_state"], "met")
        self.assertEqual(self.validate(handoff, "ship-handoff"), handoff)
        missing = copy.deepcopy(handoff)
        missing.pop("acceptance_state")
        self.assert_invalid(missing, "ship-handoff")
        for value in (None, 1, True, ["met"], ""):
            bad = copy.deepcopy(handoff)
            bad["acceptance_state"] = value
            with self.subTest(value=value):
                self.assert_invalid(bad, "ship-handoff")

    SYNC_H1, SYNC_H2 = "e" * 40, "9" * 40
    INTEGRATION_1, INTEGRATION_2 = "d" * 40, "f" * 40

    def selected_at_h0(self):
        """The fixtures' head H0 (`a` * 40) selected, published and opened, then folded."""
        contract, delivery = contract_and_delivery(self.model)
        delivery = with_observed(self.model, contract, delivery, ["select", "publish", "open"])
        folded = self.model.reduce_delivery(contract, delivery, evaluation=evaluation())
        return contract, folded["next_delivery"], folded["next_delivery"]["selected_outputs"][0]

    def fold(self, contract, delivery, observations):
        return self.model.reduce_delivery(contract, delivery, evaluation=evaluation(
            delivery_observations=sorted(observations, key=lambda item: item["id"])))

    def link(self, prior, head, integration_parent):
        return sync_selection(self.model, prior, head=head,
                              integration_parent=integration_parent)

    def test_a_sync_selection_is_selected_output_v2(self):
        _, _, h0 = self.selected_at_h0()
        h1 = self.link(h0, self.SYNC_H1, self.INTEGRATION_1)
        self.assertEqual(self.validate(h1, "selected-output"), h1)

        def resealed(change):
            bad = copy.deepcopy(h1)
            change(bad)
            return seal(self.model, bad)

        for label, bad in (
                ("tree subject", resealed(lambda value: value.update(subject_kind="tree"))),
                ("equal parents", resealed(lambda value: value["sync"].update(
                    integration_parent=value["sync"]["first_parent"]))),
                ("head as first parent", resealed(lambda value: value["sync"].update(
                    first_parent=value["subject_value"]))),
                ("head as integration parent", resealed(lambda value: value["sync"].update(
                    integration_parent=value["subject_value"]))),
                ("empty parent", resealed(lambda value: value["sync"].update(
                    integration_parent=""))),
                ("prior not a digest", resealed(lambda value: value["sync"].update(
                    prior_selection_id="h0"))),
                ("extra sync member", resealed(lambda value: value["sync"].update(merge="m"))),
                ("no sync member", resealed(lambda value: value.pop("sync"))),
                ("v1 carrying sync", resealed(lambda value: value.update(schema_version=1))),
                ("schema 3", resealed(lambda value: value.update(schema_version=3)))):
            with self.subTest(label=label):
                self.assert_invalid(bad, "selected-output")

    def test_the_tip_of_the_chain_drives_every_slot_stage(self):
        contract, delivery, h0 = self.selected_at_h0()
        h1 = self.link(h0, self.SYNC_H1, self.INTEGRATION_1)
        selected = observation(self.model, contract, "selected_output", {"selected_output": h1})
        bare = self.fold(contract, delivery, [selected])
        facts = {fact["stage_id"]: fact for fact in bare["next_delivery"]["stage_facts"]}
        self.assertEqual((bare["next_stage_id"], facts["select"]["observation_id"],
                          facts["publish"]["state"], facts["open"]["state"]),
                         ("publish", selected["id"], "pending", "pending"))
        self.assertEqual([item["id"] for item in bare["next_delivery"]["selected_outputs"]],
                         sorted([h0["id"], h1["id"]]))
        opened = self.fold(contract, bare["next_delivery"],
                           at_head(self.model, contract, h1)[1:])
        self.assertEqual(opened["next_stage_id"], "merge")
        h2 = self.link(h1, self.SYNC_H2, self.INTEGRATION_2)
        again = self.fold(contract, opened["next_delivery"], at_head(self.model, contract, h2))
        self.assertEqual((again["next_stage_id"], len(again["next_delivery"]["selected_outputs"])),
                         ("merge", 3))

    def test_selection_sets_that_are_not_one_chain_are_rejected(self):
        contract, delivery, h0 = self.selected_at_h0()
        h1 = self.link(h0, self.SYNC_H1, self.INTEGRATION_1)
        stray = selection(self.model, self.model.canonical_digest(contract),
                          subject_value="c" * 40)
        off_chain = copy.deepcopy(h1)
        off_chain["sync"]["first_parent"] = "c" * 40
        narrowed = copy.deepcopy(h1)
        narrowed["review_evidence_ids"] = [f"review:merge-delta-clean@{self.SYNC_H1}"]
        for label, links in (
                ("second v1 root", [stray]),
                ("dangling prior", [self.link(stray, self.SYNC_H1, self.INTEGRATION_1)]),
                ("fork", [h1, self.link(h0, self.SYNC_H2, self.INTEGRATION_2)]),
                ("first parent off the chain", [seal(self.model, off_chain)]),
                ("evidence not a superset", [seal(self.model, narrowed)]),
                ("repeated head", [h1, self.link(h1, h0["subject_value"], self.INTEGRATION_2)])):
            with self.subTest(label=label):
                with self.assertRaisesRegex(self.model.DeliveryModelError,
                                            "conflicting selected outputs"):
                    self.fold(contract, delivery, [
                        observation(self.model, contract, "selected_output",
                                    {"selected_output": item}) for item in links])

    def test_a_merge_at_the_tip_is_final(self):
        contract, delivery, h0 = self.selected_at_h0()
        merged = self.fold(contract, delivery, [
            observation(self.model, contract, "pr_merged", pr_subject("pr_merged"))])
        self.assertEqual(post_state(merged, "pr_merged"), "observed")
        with self.assertRaisesRegex(self.model.DeliveryModelError,
                                    "a merged selection chain cannot be extended"):
            self.fold(contract, merged["next_delivery"], at_head(
                self.model, contract, self.link(h0, self.SYNC_H1, self.INTEGRATION_1)))
        # A merge at a head the chain has not reached yet is history until it does.
        early = self.fold(contract, delivery, [observation(
            self.model, contract, "pr_merged", pr_subject("pr_merged", head=self.SYNC_H2))])
        self.assertEqual((early["next_stage_id"], post_state(early, "pr_merged")),
                         ("merge", "pending"))
        # Only a landed merge of this repository into the slot's base is final (D28).
        for label, subject in (
                ("not merged", pr_subject("pr_merged", merged=False)),
                ("another repository", pr_subject("pr_merged", repository="other-repo")),
                ("another base", pr_subject("pr_merged", base="release"))):
            with self.subTest(label=label):
                stray = self.fold(contract, delivery, [
                    observation(self.model, contract, "pr_merged", subject)])
                extended = self.fold(contract, stray["next_delivery"], at_head(
                    self.model, contract, self.link(h0, self.SYNC_H1, self.INTEGRATION_1)))
                self.assertEqual(extended["next_stage_id"], "merge")

    def test_match_scope_binds_the_tip_and_refuses_a_superseded_head(self):
        contract, delivery, declared = contract_and_delivery_for_stage(self.model, "merge")
        h0 = selection(self.model, self.model.canonical_digest(contract))
        h1 = self.link(h0, self.SYNC_H1, self.INTEGRATION_1)

        def match(selected):
            return self.model.match_scope(
                contract, delivery["authorization_intents"][0],
                requested_scope(self.model, declared, selected), selected_outputs=[h0, h1],
                at_time="2026-09-21T00:00:00Z", revocation_observations=[])

        self.assertEqual(match(h1), {"matched": True, "scope_id": declared["id"],
                                     "reason_code": "matched"})
        self.assertEqual(match(h0), {"matched": False, "scope_id": None,
                                     "reason_code": "scope_target_mismatch"})

    def test_only_the_current_selection_is_delivered(self):
        contract, delivery, h0 = self.selected_at_h0()
        h1 = self.link(h0, self.SYNC_H1, self.INTEGRATION_1)
        opened = self.fold(contract, delivery, at_head(self.model, contract, h1))["next_delivery"]
        merge = observation(self.model, contract, "pr_merged",
                            pr_subject("pr_merged", head=self.SYNC_H1))

        def delivered(selected):
            head = selected["subject_value"]
            return observation(self.model, contract, "implementation_delivered", {
                "selected_subject": {"kind": "commit", "value": head},
                "integration_subject": {"kind": "commit", "value": "b" * 40},
                "presence": {"kind": "reachability", "repository_id": "sim-repo",
                             "selected_value": head, "integration_value": "b" * 40,
                             "integrated_ref": "refs/heads/main", "succeeded": True},
                "merge_observation_id": merge["id"],
                **{name: list(selected[name]) for name in (
                    "acceptance_evidence_ids", "review_evidence_ids", "test_evidence_ids")}})

        superseded = self.fold(contract, opened, [merge, delivered(h0)])
        self.assertEqual((post_state(superseded, "pr_merged"),
                          post_state(superseded, "implementation_delivered")),
                         ("observed", "pending"))
        current = self.fold(contract, opened, [merge, delivered(h1)])
        self.assertEqual(post_state(current, "implementation_delivered"), "observed")

    def test_current_selection_is_the_reviewed_slot_tip(self):
        _, empty = contract_and_delivery(self.model)
        self.assertIsNone(self.model.current_selection(empty))
        contract, delivery, h0 = self.selected_at_h0()
        self.assertEqual(self.model.current_selection(delivery), h0)
        h1 = self.link(h0, self.SYNC_H1, self.INTEGRATION_1)
        synced = self.fold(contract, delivery, at_head(self.model, contract, h1))
        self.assertEqual(self.model.current_selection(synced["next_delivery"]), h1)
        with self.assertRaises(self.model.DeliveryModelError):
            self.model.current_selection({**synced["next_delivery"], "selected_outputs": [h1]})

    def test_a_handoff_carries_a_whole_selection_chain_or_none(self):
        contract, delivery = contract_and_delivery(self.model)
        h0 = selection(self.model, self.model.canonical_digest(contract))
        h1 = self.link(h0, self.SYNC_H1, self.INTEGRATION_1)
        handoff = ship_handoff(self.model, contract, delivery)
        chained = copy.deepcopy(handoff)
        chained["selected_outputs"] = sorted([h0, h1], key=lambda item: item["id"])
        self.assertEqual(self.validate(chained, "ship-handoff"), chained)
        stray = selection(self.model, self.model.canonical_digest(contract),
                          subject_value="c" * 40)
        for label, selections in (("a link without its root", [h1]),
                                  ("two roots", [h0, stray])):
            bad = copy.deepcopy(handoff)
            bad["selected_outputs"] = sorted(selections, key=lambda item: item["id"])
            with self.subTest(label=label):
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


class TrackerHeldModelTest(unittest.TestCase):
    """#273 D1-D4: a tracker_held observation satisfies close_tracker and tracker_closed."""

    HELD = {"tracker_repository_id": "sim-repo", "issue": 151, "state": "open",
            "label": "needs-verification",
            "comment_url": "https://sim.invalid/issues/151#issuecomment-1",
            "record_path": ".agents/artifacts/plans/2026-10-07-x.acceptance.md",
            "acceptance_state": "unmet",
            "observation_identity": "github:issue:151:held"}
    CLOSED = {"tracker_repository_id": "sim-repo", "issue": 151, "state": "closed",
              "close_reason": "completed", "observation_identity": "tracker:151:closed"}

    @classmethod
    def setUpClass(cls):
        cls.model = load_model(SOURCE, "delivery_model_tracker_held_test")

    def merged(self):
        contract, delivery = cleanup_contract_and_delivery(self.model)
        return contract, with_observed(self.model, contract, delivery,
                                       ["select", "publish", "open", "merge"])

    def reduce_with(self, contract, delivery, *items):
        candidate = copy.deepcopy(delivery)
        candidate["delivery_observations"] = sorted(
            candidate["delivery_observations"] + list(items), key=lambda item: item["id"])
        return self.model.reduce_delivery(contract, candidate, evaluation=evaluation())

    def assert_rejected(self, item):
        with self.assertRaises(self.model.DeliveryModelError):
            self.model.validate_delivery_object(
                item, expected_kind="delivery-observation", notes_max_characters=4096)

    def test_the_observable_set_adds_tracker_held_and_keeps_the_stage_tuple(self):
        self.assertIn("tracker_held", self.model.OBSERVATION_KINDS)
        self.assertIn("tracker_closed", self.model.OBSERVATION_KINDS)
        self.assertEqual(self.model.STAGE_ACTIONS["close_tracker"],
                         ("close_issue", "tracker_write", "tracker_closed"))
        self.assertEqual(
            self.model.OBSERVATION_KINDS - {"tracker_held"},
            {item[2] for item in self.model.STAGE_ACTIONS.values()}
            | {"implementation_delivered", "pr_merged", "tracker_closed", "cleanup_complete"})

    def test_a_held_observation_folds_close_tracker_and_the_postcondition(self):
        contract, delivery = self.merged()
        for acceptance in ("unmet", "human_pending"):
            with self.subTest(acceptance=acceptance):
                held = observation(self.model, contract, "tracker_held",
                                   {**self.HELD, "acceptance_state": acceptance})
                reduced = self.reduce_with(contract, delivery, held)
                self.assertEqual(stage_state(reduced, "close"), "observed")
                self.assertEqual(post_state(reduced, "tracker_closed"), "observed")
                self.assertEqual(
                    reduced["next_delivery"]["postconditions"]["tracker_closed"]
                    ["observation_id"], held["id"])
                fact = next(item for item in reduced["next_delivery"]["stage_facts"]
                            if item["stage_id"] == "close")
                self.assertEqual(fact["observation_id"], held["id"])

    def test_a_closed_observation_still_folds_close_tracker(self):
        contract, delivery = self.merged()
        closed = observation(self.model, contract, "tracker_closed", self.CLOSED)
        reduced = self.reduce_with(contract, delivery, closed)
        self.assertEqual((stage_state(reduced, "close"),
                          post_state(reduced, "tracker_closed")), ("observed", "observed"))

    def test_malformed_held_subjects_are_rejected(self):
        contract, _ = self.merged()
        changes = {
            "closed state": {"state": "closed"},
            "other label": {"label": "verify"},
            "met": {"acceptance_state": "met"},
            "not applicable": {"acceptance_state": "not_applicable"},
            "unknown acceptance": {"acceptance_state": "pending"},
            "array acceptance": {"acceptance_state": ["unmet"]},
            "object acceptance": {"acceptance_state": {"unmet": True}},
            "absolute record": {"record_path": "/abs/x.acceptance.md"},
            "parent record": {"record_path": "plans/../x.acceptance.md"},
            "backslash record": {"record_path": "plans\\x.acceptance.md"},
            "empty record": {"record_path": ""},
            "null record": {"record_path": None},
            "empty comment": {"comment_url": ""},
            "empty identity": {"observation_identity": ""},
            "issue zero": {"issue": 0},
            "boolean issue": {"issue": True},
        }
        for label, change in changes.items():
            with self.subTest(label=label):
                self.assert_rejected(observation(self.model, contract, "tracker_held",
                                                 {**self.HELD, **change}))
        missing = {key: value for key, value in self.HELD.items() if key != "record_path"}
        for label, subject in (("extra member", {**self.HELD, "close_reason": None}),
                               ("missing member", missing)):
            with self.subTest(label=label):
                self.assert_rejected(observation(self.model, contract, "tracker_held",
                                                 subject))

    def test_a_foreign_held_subject_leaves_the_stage_pending(self):
        contract, delivery = self.merged()
        for label, change in (("foreign issue", {"issue": 152}),
                              ("foreign repository", {"tracker_repository_id": "other"})):
            with self.subTest(label=label):
                foreign = observation(self.model, contract, "tracker_held",
                                      {**self.HELD, **change})
                reduced = self.reduce_with(contract, delivery, foreign)
                self.assertEqual((stage_state(reduced, "close"),
                                  post_state(reduced, "tracker_closed")),
                                 ("pending", "pending"))

    def test_held_and_closed_in_one_delivery_reject(self):
        contract, delivery = self.merged()
        held = observation(self.model, contract, "tracker_held", self.HELD)
        closed = observation(self.model, contract, "tracker_closed", self.CLOSED)
        with self.assertRaises(self.model.DeliveryModelError):
            self.reduce_with(contract, delivery, held, closed)


class OwnerLivenessResponseTest(unittest.TestCase):
    """#310 D5, D10: the closed `owner_liveness` reply at the workflow-response boundary."""

    LIVE = {"interface_version": 1, "kind": "owner_liveness", "action_id": "14:1:1",
            "reason": "current", "verdict": "live", "since": "2026-08-13T20:10:00Z",
            "progress_at": "2026-08-13T20:00:00Z", "stall_at": "2026-08-13T20:40:00Z",
            "wait_seconds": 1800}

    @classmethod
    def setUpClass(cls):
        cls.model = load_model(SOURCE, "delivery_model_owner_liveness_test")

    def validate(self, value):
        return self.model.validate_delivery_object(
            value, expected_kind="workflow-response", notes_max_characters=4096)

    def changed(self, **members):
        value = copy.deepcopy(self.LIVE)
        value.update(members)
        return value

    def accepted(self):
        return {
            "live": self.LIVE,
            "live_progress_later": self.changed(
                progress_at="2026-08-13T20:20:00Z", stall_at="2026-08-13T20:50:00Z"),
            "stalled": self.changed(verdict="stalled", wait_seconds=None),
            "past_deadline": self.changed(verdict="past_deadline", wait_seconds=None),
            "not_current": self.changed(reason="superseded_launch", verdict="not_current",
                                        progress_at=None, stall_at=None, wait_seconds=None),
            "unknown_run": self.changed(reason="unknown_run", verdict="not_current",
                                        progress_at=None, stall_at=None, wait_seconds=None),
        }

    def test_each_verdict_shape_is_accepted_unchanged(self):
        for name, value in self.accepted().items():
            with self.subTest(name=name):
                self.assertEqual(self.validate(copy.deepcopy(value)), value)

    def test_every_broken_invariant_is_rejected(self):
        missing = copy.deepcopy(self.LIVE)
        del missing["since"]
        rejected = {
            "extra_member": self.changed(now="2026-08-13T20:10:00Z"),
            "missing_member": missing,
            "version_two": self.changed(interface_version=2),
            "version_bool": self.changed(interface_version=True),
            "unknown_reason": self.changed(reason="late"),
            "unknown_verdict": self.changed(verdict="dead"),
            "empty_action": self.changed(action_id=""),
            "fractional_since": self.changed(since="2026-08-13T20:10:00.5Z"),
            "current_but_not_current": self.changed(verdict="not_current", progress_at=None,
                                                    stall_at=None, wait_seconds=None),
            "superseded_but_live": self.changed(reason="superseded_launch"),
            "not_current_with_times": self.changed(reason="superseded_launch",
                                                   verdict="not_current", wait_seconds=None),
            "live_without_progress": self.changed(progress_at=None),
            "stall_not_whole_minutes": self.changed(stall_at="2026-08-13T20:40:30Z"),
            "stall_before_since": self.changed(stall_at="2026-08-13T20:09:00Z",
                                               progress_at="2026-08-13T19:00:00Z"),
            "stall_at_base": self.changed(stall_at="2026-08-13T20:10:00Z"),
            "stall_before_base": self.changed(stall_at="2026-08-13T20:05:00Z"),
            "live_zero_wait": self.changed(wait_seconds=0),
            "live_bool_wait": self.changed(wait_seconds=True),
            "live_null_wait": self.changed(wait_seconds=None),
            "stalled_with_wait": self.changed(verdict="stalled"),
            "past_deadline_with_wait": self.changed(verdict="past_deadline"),
        }
        for name, value in rejected.items():
            with self.subTest(name=name):
                with self.assertRaises(self.model.DeliveryModelError):
                    self.validate(value)

    def test_the_check_launch_reply_is_unchanged(self):
        reply = {"action_id": "14:1:1", "current": True, "current_action_id": "14:1:1",
                 "reason": "current"}
        self.assertEqual(self.validate(copy.deepcopy(reply)), reply)
        with self.assertRaises(self.model.DeliveryModelError):
            self.validate({**reply, "reason": "late"})


class ControlWaitResponseTest(unittest.TestCase):
    """#310 D9: the boundary recomputes a control wait's `wait_seconds`."""

    @classmethod
    def setUpClass(cls):
        cls.model = load_model(SOURCE, "delivery_model_control_wait_test")

    def validate(self, value):
        return self.model.validate_delivery_object(
            value, expected_kind="workflow-response", notes_max_characters=4096)

    def with_wait(self, deadline, seconds):
        value = copy.deepcopy(workflow_responses(self.model)["control"])
        self.assertEqual(value["now"], "2026-09-21T00:00:00Z")
        value["next_deadline"] = deadline
        value["actions"].append({"id": f"wait:{deadline}", "kind": "wait",
                                 "wake_on": ["deadline", "owner_notification", "tracker_change"],
                                 "deadline_at": deadline, "wait_seconds": seconds})
        return value

    def test_the_exact_value_is_accepted(self):
        for deadline, seconds in (("2026-09-21T01:00:00Z", 3600),
                                  ("2026-09-21T00:00:01Z", 1),
                                  ("2026-09-21T00:00:00Z", 0),
                                  ("2026-09-20T23:59:00Z", 0)):
            with self.subTest(deadline=deadline):
                value = self.with_wait(deadline, seconds)
                self.assertEqual(self.validate(copy.deepcopy(value)), value)

    def test_any_other_value_or_shape_is_rejected(self):
        cases = {"one_short": self.with_wait("2026-09-21T01:00:00Z", 3599),
                 "one_over": self.with_wait("2026-09-21T01:00:00Z", 3601),
                 "negative_past": self.with_wait("2026-09-20T23:59:00Z", -60),
                 "boolean": self.with_wait("2026-09-21T00:00:01Z", True),
                 "float": self.with_wait("2026-09-21T01:00:00Z", 3600.0)}
        missing = self.with_wait("2026-09-21T01:00:00Z", 3600)
        del missing["actions"][-1]["wait_seconds"]
        cases["missing"] = missing
        for name, value in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(self.model.DeliveryModelError):
                    self.validate(value)


if __name__ == "__main__":
    unittest.main()
