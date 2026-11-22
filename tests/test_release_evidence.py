"""Issue 554 D11: the merge certification's spelling and descriptor stay current."""
import json
import unittest
from pathlib import Path

from agent_tools.release import forge_adapter
from agent_tools.canonical import telemetry_digest

from . import release_merge_certification as harness

REPO_ROOT = Path(__file__).resolve().parents[1]
SPELLINGS = REPO_ROOT / "tests/fixtures/forge-adapter-spellings.json"
CERTIFIED_PR = 13
CERTIFIED_HEAD = "853578d2cff7230d6ed5399c628d13bd33379da9"
CERTIFIED_SPELLING = ("gh pr merge 13 --repo fagenorn/release-merge-sandbox --merge "
                      "--match-head-commit 853578d2cff7230d6ed5399c628d13bd33379da9")
CERTIFIED_DESCRIPTOR_DIGEST = "sha256:810fe4e4cc16c9e71b28f4842a22165ae81edc21100ac0c77173aeb7e23b70f8"


class MergeCertificationEvidenceTest(unittest.TestCase):
    """Issue 554 D11: the certified spelling and descriptor are the current ones."""

    def test_the_spelling_and_descriptor_are_the_current_ones(self):
        """D11 (issue 554, ADR-guard-008): a spelling or descriptor change demands a new certification, kept at
https://github.com/fagenorn/nix-config/blob/6b06a4e277ab8885d02cca9cec38e85a6de5dc55/.agents/artifacts/evidence/release-554-native-certification.json.
"""
        fixture = json.loads(SPELLINGS.read_text(encoding="utf-8"))
        row = next(r for r in fixture["rows"] if r["id"] == "pr_merge.merge")
        canonical = fixture["canonical"]
        expected = (row["raw"].replace(canonical["slug"], harness.SANDBOX)
                    .replace(f" {canonical['pr']} ", f" {CERTIFIED_PR} ")
                    .replace(canonical["commit"], CERTIFIED_HEAD))
        digest = telemetry_digest(forge_adapter.describe()["operations"]["pr_merge"])
        self.assertEqual(expected, CERTIFIED_SPELLING)
        self.assertEqual(digest, CERTIFIED_DESCRIPTOR_DIGEST)


if __name__ == "__main__":
    unittest.main()
