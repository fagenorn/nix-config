"""Seam 4: the committed promotion documents and the demo walk (#127 D16, D17)."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent_tools import agent_gate_bundle as gate
from agent_tools import promotion_schema as schema
from agent_tools.canonical import telemetry_digest

from .promotion_test_support import make_env, resolved_project, run

REPO_ROOT = Path(__file__).resolve().parents[1]
DRAFT = ".agents/knowledge/promotions/drafts/investigate-before-changing.json"
CANDIDATE = ".agents/knowledge/promotions/candidates/investigate-before-changing.json"
TRIALS = ".agents/artifacts/evidence/promotion-127-trials.json"
BUNDLE = ".agents/artifacts/evidence/promotion-127-bundle.json"


def load(relative):
    return json.loads((REPO_ROOT / relative).read_text(encoding="utf-8"))


class DemoCase(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.tmp = Path(scratch.name).resolve()


class CommittedDocumentsTest(DemoCase):
    def test_every_committed_promotion_document_validates(self):
        env = make_env(self.tmp, resolved_project(self.tmp))
        documents = sorted((REPO_ROOT / ".agents/knowledge/promotions").rglob("*.json"))
        self.assertGreaterEqual(len(documents), 2)
        for path in documents:
            with self.subTest(path=path.name):
                self.assertEqual(run(env, "validate", "--input", str(path))[:2],
                                 (0, {"valid": True}))

    def test_the_committed_candidate_is_its_captured_draft(self):
        draft, candidate = load(DRAFT), load(CANDIDATE)
        authored = {m: candidate[m] for m in schema.AUTHORED_MEMBERS}
        self.assertEqual(authored, {m: draft[m] for m in schema.AUTHORED_MEMBERS})
        self.assertEqual(candidate["candidate_id"], telemetry_digest(authored))
        self.assertEqual([candidate["state"], candidate["tracker"]["ref"],
                          candidate["classification"], candidate["evidence"]],
                         ["captured", None, None, None])
        command = candidate["tracker"]["create_command"]
        self.assertEqual(command[:10], [
            "gh", "issue", "create", "--repo", "fagenorn/nix-config",
            "--label", "promotion-candidate",
            "--title", "promotion: Investigate before changing", "--body"])
        self.assertIn(f"document: {CANDIDATE}", command[-1].splitlines())

    def test_the_committed_bundle_is_the_real_unmeasured_output(self):
        manifest = gate.load_manifest(REPO_ROOT / TRIALS)
        self.assertEqual([case["case_class"] for case in manifest["cases"]],
                         list(gate.CORE_CASE_CLASSES))
        self.assertTrue(all(case["strata"] == {} for case in manifest["cases"]))
        bundle = load(BUNDLE)
        self.assertEqual(gate.verify_bundle(bundle), "unmeasured")
        self.assertEqual(bundle["identity"], manifest["identity"])


class DemoWalkTest(DemoCase):
    def test_the_demo_reaches_decision_ready_and_stops_at_authorized(self):
        root = self.tmp / "project"
        for relative in (DRAFT, CANDIDATE, TRIALS, BUNDLE):
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / relative, root / relative)
        env = make_env(self.tmp, resolved_project(root))
        path = str(root / CANDIDATE)
        code, payload, err = run(env, "advance", "--candidate", path, "--to", "evaluating",
                                 "--tracker-ref", "1")
        self.assertEqual(code, 0, err)
        self.assertEqual(payload["classification"], {
            "rule": 4, "rule_id": "standard_layer", "declared_layer": "standard_layer",
            "overridden_by_rule_1": False})
        code, payload, err = run(env, "advance", "--candidate", path, "--to",
                                 "decision_ready", "--bundle", BUNDLE)
        self.assertEqual(code, 0, err)
        self.assertEqual([payload["evidence"]["state"], payload["evidence"]["bundle_id"],
                          payload["evidence"]["bundle_path"]],
                         ["unmeasured", load(BUNDLE)["bundle_id"], BUNDLE])
        self.assertEqual([c["repository"] for c in payload["corroboration"]["repositories"]],
                         ["fagenorn/argus", "elevenyellow/nodocom"])
        code, payload, _ = run(env, "advance", "--candidate", path, "--to", "authorized",
                               "--authorized-by", "fagenorn")
        self.assertEqual((code, payload["error"]["code"]), (3, "evidence_unmeasured"))
        self.assertEqual(load(CANDIDATE)["state"], "captured")
