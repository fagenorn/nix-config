"""The #70 evidence #128 carries (spec D11, D24): an honest `unmeasured` bundle."""
import json
import unittest
from pathlib import Path

from agent_tools import agent_gate_bundle as gate
from agent_tools.release import forge_adapter
from agent_tools.canonical import telemetry_digest

REPO_ROOT = Path(__file__).resolve().parents[1]
TRIALS = REPO_ROOT / ".agents/artifacts/evidence/release-128-trials.json"
BUNDLE = REPO_ROOT / ".agents/artifacts/evidence/release-128-bundle.json"
CERTIFICATION = REPO_ROOT / ".agents/artifacts/evidence/release-554-native-certification.json"
SPELLINGS = REPO_ROOT / "tests/fixtures/forge-adapter-spellings.json"
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


class MergeCertificationEvidenceTest(unittest.TestCase):
    """Issue 554 AC4, D10, D11, D19: the native certification is real, passing and current."""

    def setUp(self):
        self.text = CERTIFICATION.read_text(encoding="utf-8")
        self.evidence = json.loads(self.text)
        self.rows = {row["id"]: row for row in self.evidence["rows"]}

    def test_the_sandbox_run_passed_under_the_floor(self):
        from . import release_merge_certification as harness
        evidence = self.evidence
        self.assertEqual((evidence["schema"], evidence["issue"], evidence["repository"],
                          evidence["guard"], evidence["result"]),
                         ("release-merge-certification/v1", 554, harness.SANDBOX, "recording-shim", "passed"))
        self.assertEqual(sorted(self.rows), ["a", "b", "c"])
        self.assertTrue(all(row["passed"] and row["verdict"] == "passed" for row in evidence["rows"]))
        self.assertEqual(evidence["protection"], {"strict": True, "required_contexts": [harness.CONTEXT],
                                                  "enforce_admins": True})
        for marker in ("gho_", "ghp_", "github_pat_", "Authorization", "Bearer "):
            self.assertNotIn(marker, self.text)

    def test_each_row_shows_what_github_did(self):
        a, b, c = self.rows["a"], self.rows["b"], self.rows["c"]
        self.assertEqual([(t["via"], t["outcome"]) for t in a["attempts"]],
                         [("adapter", "accepted"), ("adapter", "refused")])
        self.assertEqual((a["after"]["state"], a["after"]["parents"]),
                         ("MERGED", [a["bound"]["base_tip"], a["bound"]["head"]]))
        self.assertEqual([(t["via"], t["outcome"]) for t in b["attempts"]],
                         [("argv", "refused"), ("graphql", "refused")])
        self.assertNotEqual(b["after"]["base_tip"], b["bound"]["base_tip"])
        self.assertEqual([(t["via"], t["outcome"]) for t in c["attempts"]], [("argv", "refused")])
        self.assertEqual(c["after"]["base_tip"], c["bound"]["base_tip"])
        for row in (b, c):
            self.assertEqual((row["after"]["state"], row["after"]["merge_commit"]), ("OPEN", None))
        self.assertEqual({t["class"] for t in c["attempts"]}, {"merge_condition"})  # D20
        self.assertEqual(b["mergeable_state"], "behind")  # D23

    def test_the_spelling_and_descriptor_are_the_current_ones(self):
        """D11: a spelling or descriptor change demands a new certification."""
        fixture = json.loads(SPELLINGS.read_text(encoding="utf-8"))
        row = next(r for r in fixture["rows"] if r["id"] == "pr_merge.merge")
        canonical, a = fixture["canonical"], self.rows["a"]
        expected = (row["raw"].replace(canonical["slug"], self.evidence["repository"])
                    .replace(f" {canonical['pr']} ", f" {a['pr']} ")
                    .replace(canonical["commit"], a["bound"]["head"]))
        self.assertEqual(self.evidence["spelling"], expected)
        implementation = self.evidence["implementation"]
        self.assertEqual(implementation["pr_merge_descriptor_digest"],
                         telemetry_digest(forge_adapter.describe()["operations"]["pr_merge"]))
        self.assertRegex(implementation["commit"], r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
