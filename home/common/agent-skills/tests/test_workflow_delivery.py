from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from ._delivery_model_fixtures import (
    contract_and_delivery_for_stage,
    custody,
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


if __name__ == "__main__":
    unittest.main()
