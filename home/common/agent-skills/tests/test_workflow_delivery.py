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
)


SCRIPTS = Path(__file__).parents[1] / "scripts"
ENTRY = SCRIPTS / "workflow_delivery.py"


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
            shutil.copytree(SCRIPTS / "delivery_model", root / "delivery_model")
            installed = load(root / "workflow_delivery.py", "workflow_delivery_installed_test")
            self.assertEqual(installed.DeliveryRuntime(
                notes_max_characters=100).model.MODEL_INTERFACE_VERSION, 1)
            shutil.rmtree(root / "delivery_model")
            broken = load(root / "workflow_delivery.py", "workflow_delivery_broken_test")
            with self.assertRaises(ValueError):
                broken.DeliveryRuntime(notes_max_characters=100)

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

        for path, identity in (("/foreign", "/foreign"),
                               (worktree, "foreign-identity")):
            candidate = copy.deepcopy(issue_state)
            rejected = {**report, "delivery_observations": [absent(path, identity)]}
            with self.subTest(path=path, identity=identity), self.assertRaises(ValueError):
                runtime.prepare_report_transition(
                    candidate, rejected, source_kind="checkpoint",
                    at_time="2026-09-21T00:00:00Z")
            self.assertEqual(candidate, issue_state)

        accepted = {**report,
                    "delivery_observations": [absent(worktree, worktree)]}
        runtime.prepare_report_transition(
            issue_state, accepted, source_kind="checkpoint",
            at_time="2026-09-21T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
