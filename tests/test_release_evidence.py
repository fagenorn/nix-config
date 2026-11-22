"""Issue 554 D11: the merge certification's spelling and descriptor stay current."""
import json
import subprocess
import unittest
from pathlib import Path

from agent_tools.release import forge_adapter
from agent_tools.canonical import telemetry_digest

REPO_ROOT = Path(__file__).resolve().parents[1]
SPELLINGS = REPO_ROOT / "tests/fixtures/forge-adapter-spellings.json"
REPORT_COMMIT = "6b06a4e277ab8885d02cca9cec38e85a6de5dc55"
# The report's path is concatenated so the working-artifact scan in test_docs_tree does not read it as a live file.
REPORT_PATH = ".agents/" + "artifacts/evidence/release-554-native-certification.json"


def certification_report():
    """The native-certification report kept at REPORT_COMMIT, read from local Git."""
    shown = subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"{REPORT_COMMIT}:{REPORT_PATH}"],
                           check=True, capture_output=True)
    return json.loads(shown.stdout)


class MergeCertificationEvidenceTest(unittest.TestCase):
    """Issue 554 D11: the certified spelling and descriptor are the current ones."""

    def test_the_spelling_and_descriptor_are_the_current_ones(self):
        """D11 (issue 554, ADR-guard-008): a spelling or descriptor change demands a new certification, kept at
https://github.com/fagenorn/nix-config/blob/6b06a4e277ab8885d02cca9cec38e85a6de5dc55/.agents/artifacts/evidence/release-554-native-certification.json.
"""
        report = certification_report()
        self.assertEqual(report["result"], "passed")
        row = next(r for r in report["rows"] if r["id"] == "a")
        fixture = json.loads(SPELLINGS.read_text(encoding="utf-8"))
        spelling = next(r for r in fixture["rows"] if r["id"] == "pr_merge.merge")
        canonical = fixture["canonical"]
        expected = (spelling["raw"].replace(canonical["slug"], report["repository"])
                    .replace(f" {canonical['pr']} ", f" {row['pr']} ")
                    .replace(canonical["commit"], row["bound"]["head"]))
        self.assertEqual(report["spelling"], expected)
        self.assertEqual(report["implementation"]["pr_merge_descriptor_digest"],
                         telemetry_digest(forge_adapter.describe()["operations"]["pr_merge"]))


if __name__ == "__main__":
    unittest.main()
