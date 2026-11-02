"""The #70 evidence #128 carries (spec D11, D24): an honest `unmeasured` bundle."""
import json
import unittest
from pathlib import Path

from agent_tools import agent_gate_bundle as gate

REPO_ROOT = Path(__file__).resolve().parents[1]
TRIALS = REPO_ROOT / ".agents/artifacts/evidence/release-128-trials.json"
BUNDLE = REPO_ROOT / ".agents/artifacts/evidence/release-128-bundle.json"
BASE = "0a25b8072c8252d069774f68e75981c39c137691"


class ReleaseEvidenceTest(unittest.TestCase):
    def test_the_committed_bundle_is_the_real_unmeasured_output(self):
        manifest = gate.load_manifest(TRIALS)
        self.assertEqual([case["case_class"] for case in manifest["cases"]],
                         list(gate.CORE_CASE_CLASSES))
        self.assertTrue(all(case["strata"] == {} for case in manifest["cases"]))
        commit = manifest["identity"]["bound"]["commit"]
        self.assertEqual(commit["base"], BASE)
        self.assertRegex(commit["candidate"], r"^[0-9a-f]{40}$")
        self.assertNotEqual(commit["candidate"], BASE)
        bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
        self.assertEqual(gate.verify_bundle(bundle), "unmeasured")
        self.assertEqual(bundle["identity"], manifest["identity"])


if __name__ == "__main__":
    unittest.main()
