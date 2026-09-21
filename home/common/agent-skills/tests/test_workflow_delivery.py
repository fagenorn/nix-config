from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from ._delivery_model_fixtures import (
    cleanup_contract_and_delivery,
    contract_and_delivery_for_stage,
    custody,
    observation,
    rebind_contract,
    seal,
    selection,
    stage_scope,
)


SCRIPTS = Path(__file__).parents[1] / "scripts"
ENTRY = SCRIPTS / "workflow_delivery.py"
PROJECTION = SCRIPTS / "workflow_delivery_wire.py"
WORKFLOW = SCRIPTS / "workflow-state.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class WorkflowDeliveryRuntimeTest(unittest.TestCase):
    def test_runtime_loads_one_model_and_returns_detached_transition(self):
        module = load(ENTRY, "workflow_delivery_source_test")
        self.assertEqual(module.__all__, (
            "WORKFLOW_DELIVERY_INTERFACE_VERSION", "DeliveryRuntime"))
        runtime = module.DeliveryRuntime(notes_max_characters=10_000)
        contract, delivery, requested = contract_and_delivery_for_stage(
            runtime.model, "select"
        )
        original = copy.deepcopy(delivery)
        result = runtime.transition(
            delivery, contract=contract, at_time="2026-09-21T00:00:00Z",
            custody=custody(), current_launch=True, requested_scope=requested,
            source_kind="direct", authorization_intents=[],
            authority_observations=[], reevaluation_evidence=[],
            delivery_observations=[],
        )
        self.assertEqual(delivery, original)
        self.assertEqual(result["requested_scope"], requested)
        self.assertEqual(result["requirements"][0]["reason_code"],
                         "native_evaluation_required")

    def test_installed_lexical_layout_and_missing_model_fail_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            shutil.copy2(ENTRY, root / "workflow_delivery.py")
            shutil.copy2(PROJECTION, root / "workflow_delivery_wire.py")
            shutil.copytree(SCRIPTS / "delivery_model", root / "delivery_model")
            installed = load(root / "workflow_delivery.py", "workflow_delivery_installed_test")
            self.assertEqual(installed.DeliveryRuntime(
                notes_max_characters=100).model.MODEL_INTERFACE_VERSION, 1)

            (root / "workflow_delivery_wire.py").unlink()
            with self.assertRaises(ValueError):
                installed.DeliveryRuntime(notes_max_characters=100)
            shutil.copy2(PROJECTION, root / "workflow_delivery_wire.py")
            shutil.rmtree(root / "delivery_model")
            broken = load(root / "workflow_delivery.py", "workflow_delivery_broken_test")
            with self.assertRaises(ValueError):
                broken.DeliveryRuntime(notes_max_characters=100)

            shutil.copytree(SCRIPTS / "delivery_model", root / "delivery_model")
            (root / "workflow_delivery_wire.py").write_text(
                "WORKFLOW_DELIVERY_WIRE_INTERFACE_VERSION = 2\n"
                "class DeliveryProjection: pass\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                broken.DeliveryRuntime(notes_max_characters=100)

    def test_projection_validates_interface_two_owner_and_worktree_grammar(self):
        runtime = load(ENTRY, "workflow_delivery_projection_test").DeliveryRuntime(
            notes_max_characters=100)
        owner = {"event_id": "owner-1", "issue": 151, "state": "unavailable",
                 "custody": custody()}
        worktree = {"issue": 151,
                    "recorded": {"path": "/owned", "state": "matching_issue_branch"},
                    "candidate": None}
        request = {"owners": [owner], "worktrees": [worktree]}
        runtime.validate_control_observations(request, {151})
        for changed in (
            {**owner, "custody": {**owner["custody"], "action_id": "151:2:1"}},
            {**owner, "issue": 152},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                runtime.validate_control_observations(
                    {"owners": [changed], "worktrees": [worktree]}, {151})

    def test_remainder_reentry_uses_the_ready_stage_worktree_requirement(self):
        runtime = load(ENTRY, "workflow_delivery_reentry_requirement_test").DeliveryRuntime(
            notes_max_characters=10_000)
        contract, delivery = cleanup_contract_and_delivery(runtime.model)

        def issue_state():
            return {"issue": 151, "attempts": [], "outcome": None,
                "delivery": copy.deepcopy(delivery), "delivery_remainders": [{
                    "remainder": 1, "contract_digest": delivery["contract_digest"],
                    "source_attempt": 1, "prior_remainder": None,
                    "pending_stage_ids": [], "owner": "151:r1",
                    "worktree": "/worktree", "state": "suspended",
                    "launches": [{"kind": "fresh", "owner": "151:r1",
                                  "worktree": "/worktree", "at": "2026-09-21T00:00:00Z"}],
                    "deadline_at": "2026-09-21T03:00:00Z", "progress_token": "token",
                    "blocked_on": "external", "suspend_phase": 0,
                    "stalled_resumes": 0, "result": None, "result_source": None,
                    "recovery": None, "finished_at": None}]}

        cases = (
            ("close", None),
            ("worktree", {"path": "/worktree", "state": "absent"}),
        )
        for stage_id, recorded in cases:
            state = issue_state()
            result = runtime.remainder_policy(
                state, now="2026-09-21T00:01:00Z", owner_unavailable=False,
                dispatch_permitted=True, tracker_halted=True,
                recorded_worktree=recorded,
                remainder_deadline="2026-09-21T03:01:00Z",
                preview={"next_stage_id": stage_id})
            self.assertEqual((result["operation"], result["attempt"]["state"],
                              len(result["attempt"]["launches"])),
                             ("resume", "active", 2))
        state = issue_state(); before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            runtime.remainder_policy(
                state, now="2026-09-21T00:01:00Z", owner_unavailable=False,
                dispatch_permitted=True, tracker_halted=False,
                recorded_worktree={"path": "/worktree", "state": "mismatch"},
                remainder_deadline="2026-09-21T03:01:00Z",
                preview={"next_stage_id": "worktree"})
        self.assertEqual(state, before)

    def test_public_historical_merge_folds_facts_before_terminal_replay(self):
        runtime = load(ENTRY, "workflow_delivery_historical_merge_test").DeliveryRuntime(
            notes_max_characters=10_000)
        contract, delivery, actual = contract_and_delivery_for_stage(
            runtime.model, "select")
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); worktree = str(root / "worktree"); serial = 0
            def invoke(request):
                nonlocal serial
                serial += 1; path = root / f"direct-{serial}.json"
                path.write_text(json.dumps(request))
                result = subprocess.run(
                    [sys.executable, str(WORKFLOW), "direct-owner", "--repo-root",
                     str(root), "--request-file", str(path)],
                    capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)
            request = {"interface_version": 2, "issue": 151,
                "now": "2026-09-21T00:00:00Z", "attempt_budget_minutes": 30,
                "new_run": False, "owner_unavailable": False,
                "tracker": {"issue": 151, "state": "open", "open_blockers": [],
                            "decision_blockers": []},
                "worktree": {"issue": 151, "recorded": None,
                    "candidate": {"path": worktree, "state": "absent"}},
                "forge": {"state": "none", "url": None, "merge_sha": None},
                "delivery_contract": contract,
                "authorization_intents": delivery["authorization_intents"],
                "authority_observations": [], "reevaluation_evidence": [],
                "delivery_observations": [], "requested_scope": actual,
                "recovery": None}
            owner = invoke(request)
            state_path = root / f".superpowers/workflows/{owner['run_id']}/state.json"
            state = json.loads(state_path.read_text())
            historical = {"issue": 151, "state": "merged",
                "pr_url": "https://sim.invalid/pr/17", "merge_sha": "b" * 40,
                "issue_closed": False, "discussion_items": [],
                "detail_state": "none", "report_path": None, "notes": "merged"}
            attempt = state["issues"]["151"]["attempts"][0]
            attempt.update(state="merged", blocked_on=None, result=historical,
                           result_source="superseded",
                           finished_at="2026-09-21T00:00:01Z")
            state["issues"]["151"]["outcome"] = copy.deepcopy(historical)
            state["updated_at"] = "2026-09-21T00:00:01Z"
            state_path.write_text(json.dumps(state, sort_keys=True,
                                             separators=(",", ":")) + "\n")
            selected = selection(runtime.model, runtime.model.canonical_digest(contract))
            request.update(now="2026-09-21T00:00:02Z", requested_scope=None,
                worktree={"issue": 151, "recorded": {
                    "path": worktree, "state": "matching_issue_branch"},
                    "candidate": None}, forge={"state": "merged",
                    "url": historical["pr_url"], "merge_sha": historical["merge_sha"]},
                delivery_observations=[observation(
                    runtime.model, contract, "selected_output",
                    {"selected_output": selected})])
            remainder = invoke(request)
            self.assertEqual((remainder["kind"], remainder["custody"]["action_id"],
                              remainder["pending_stage_ids"][0]),
                             ("delivery_remainder", "151:r1:1", "publish"))
            issue = json.loads(state_path.read_text())["issues"]["151"]
            self.assertEqual((len(issue["attempts"]), issue["attempts"][0]["state"],
                              len(issue["delivery_remainders"])), (1, "merged", 1))

    def test_cleanup_facts_bind_the_exact_recorded_worktree(self):
        module = load(ENTRY, "workflow_delivery_worktree_binding_test")
        runtime = module.DeliveryRuntime(notes_max_characters=10_000)
        contract, delivery = cleanup_contract_and_delivery(runtime.model)
        worktree = "/owned/worktree"
        next(stage for stage in contract["stages"]
             if stage["kind"] == "remove_worktree")["target_ref"]["value"] = worktree
        delivery = rebind_contract(runtime.model, contract, delivery)
        record = {"attempt": 1, "launches": [{"kind": "fresh"}],
                  "state": "active", "worktree": worktree}
        issue_state = {"issue": 151, "attempts": [record],
                       "delivery_remainders": [], "delivery": delivery}
        report = {"custody": custody(),
                  "contract_digest": runtime.model.canonical_digest(contract),
                  "authority_observations": [], "reevaluation_evidence": [],
                  "requested_scope": None}

        def absent(path, identity):
            return observation(runtime.model, contract, "worktree_absent", {
                "path": path, "recorded_worktree_identity": identity,
                "probe_mode": "no_follow", "absent": True,
            })

        def request(source, facts, requested=None):
            values = {"delivery_contract": contract,
                      "authorization_intents": [], "authority_observations": [],
                      "reevaluation_evidence": [], "delivery_observations": facts,
                      "requested_scope": requested, "recovery": None}
            if source == "direct":
                return values
            return {"delivery_contracts": {"151": values["delivery_contract"]},
                    "authorization_intents": {"151": []},
                    "authority_observations": {"151": []},
                    "reevaluation_evidence": {"151": []},
                    "delivery_observations": {"151": facts},
                    "requested_scopes": {"151": requested},
                    "recoveries": {"151": None}}

        for source in ("direct", "control", "checkpoint"):
            for path, identity in (("/foreign", "/foreign"),
                                   (worktree, "foreign-identity")):
                candidate = copy.deepcopy(issue_state)
                fact = absent(path, identity)
                with self.subTest(source=source, path=path, identity=identity), \
                        self.assertRaises(ValueError):
                    if source == "checkpoint":
                        runtime.prepare_report_transition(
                            candidate, {**report, "delivery_observations": [fact]},
                            source_kind=source, at_time="2026-09-21T00:00:00Z")
                    else:
                        runtime.apply_transition(
                            candidate, issue=151, request=request(source, [fact]),
                            source_kind=source, at_time="2026-09-21T00:00:00Z")
                self.assertEqual(candidate, issue_state)

            accepted = copy.deepcopy(issue_state)
            fact = absent(worktree, worktree)
            if source == "checkpoint":
                runtime.prepare_report_transition(
                    accepted, {**report, "delivery_observations": [fact]},
                    source_kind=source, at_time="2026-09-21T00:00:00Z")
            else:
                runtime.apply_transition(
                    accepted, issue=151, request=request(source, [fact]),
                    source_kind=source, at_time="2026-09-21T00:00:00Z")

        cleanup_scope = stage_scope(runtime.model, contract, "worktree")
        wrong_scope = copy.deepcopy(cleanup_scope)
        wrong_scope["endpoint"]["value"] = "/foreign"
        seal(runtime.model, wrong_scope)
        candidate = copy.deepcopy(issue_state)
        with self.assertRaises(ValueError):
            runtime.apply_transition(
                candidate, issue=151, request=request("direct", [], wrong_scope),
                source_kind="direct", at_time="2026-09-21T00:00:00Z")
        self.assertEqual(candidate, issue_state)


if __name__ == "__main__":
    unittest.main()
