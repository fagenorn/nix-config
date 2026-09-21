from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import shutil
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
    stage_scope,
)


SCRIPTS = Path(__file__).parents[1] / "scripts"
ENTRY = SCRIPTS / "workflow_delivery.py"
PROJECTION = SCRIPTS / "workflow_delivery_wire.py"


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
