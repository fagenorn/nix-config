"""The release command: profile inspection (#124 spec §5). Run: just agent-workflow-tests"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PYTHON = REPO / "python"
SHARE = REPO / "home/common/agent-skills"

class ReleaseCommandCase(unittest.TestCase):
    """Runs `python -m agent_tools.release` against a temporary copy of this repository's
    contract under a temporary HOME holding the committed platform manifest, as the
    resolver suite's `install_home` does."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve() / "home"
        (self.home / ".agents/share").mkdir(parents=True)
        for name in ("platform-manifest.json", "host-declaration.json"):
            shutil.copy(SHARE / name, self.home / ".agents/share" / name)
        self.root = Path(tmp.name).resolve() / "project"
        (self.root / ".agents").mkdir(parents=True)
        shutil.copytree(REPO / ".agents/instructions", self.root / ".agents/instructions")
        for name in ("AGENTS.md", "CLAUDE.md"):
            shutil.copy(REPO / name, self.root / name)
        self.write_contract(json.loads((REPO / ".agents/project.json").read_text("utf-8")))
        subprocess.run(["git", "init", "--quiet"], cwd=self.root, check=True)

    def write_contract(self, contract):
        (self.root / ".agents/project.json").write_text(json.dumps(contract), encoding="utf-8")

    def contract(self):
        return json.loads((self.root / ".agents/project.json").read_text("utf-8"))

    def run_release(self, *args):
        env = dict(os.environ, PYTHONPATH=str(PYTHON), HOME=str(self.home))
        result = subprocess.run([sys.executable, "-m", "agent_tools.release", *args,
                                 "--repo-root", str(self.root)],
                                capture_output=True, text=True, env=env, timeout=120)
        return result.returncode, json.loads(result.stdout), result.stderr

class ProfileInspectTest(ReleaseCommandCase):
    def test_reports_exactly_seven_members_for_nix_config(self):
        code, report, err = self.run_release("profile", "inspect", "github-release")
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(report), ["bindings", "conformance", "graphs", "profile",
                                          "repairs", "schema_version", "subject"])
        self.assertEqual(report["schema_version"], 1)
        self.assertTrue(report["profile"]["admissible"])
        self.assertEqual([n["id"] for n in report["graphs"]["publication"]], ["tag", "github-release"])
        self.assertEqual(report["graphs"]["handoffs"],
                         [{"from": "publication", "to": "activation", "receipt": "activation_not_applicable"}])
        derived = [o for o in report["graphs"]["proof"] if o["derived"]]
        self.assertEqual([(o["class"], o["predicate"], o["roots"]) for o in derived],
                         [("published_artifact_identity", "publication_visible", "tag"),
                          ("published_artifact_identity", "publication_visible", "github-release")])
        self.assertEqual(sorted(report["conformance"]["checks"]),
                         ["repository.release_profile.observation_deadline",
                          "repository.release_profile.restore_anchor",
                          "repository.release_profile.rolled_back_reachable"])
        for check in report["conformance"]["checks"].values():
            self.assertEqual(check, {"status": "passed", "reason_code": None})
        self.assertEqual(report["bindings"]["adapters"]["forge"]["adapter"], "github-forge")
        self.assertEqual(report["subject"]["project_id"], "fagenorn/nix-config")

    def test_an_inadmissible_profile_still_reports_in_full(self):
        contract = self.contract()
        del contract["release"]["profiles"]["github-release"]["publication"]["actions"][0][
            "observation_deadline_ms"]
        self.write_contract(contract)
        code, report, err = self.run_release("profile", "inspect", "github-release")
        self.assertEqual(code, 0, err)
        self.assertFalse(report["profile"]["admissible"])
        check = report["conformance"]["checks"]["repository.release_profile.observation_deadline"]
        self.assertEqual(check, {"status": "failed", "reason_code": "observation_deadline_optional"})
        self.assertIn({"repair_id": "release_profile.deadline.require",
                       "pointer": "/release/profiles/github-release/publication/actions/0",
                       "safety_class": "user_action"}, report["repairs"])

    def test_typed_errors_and_resolver_refusals(self):
        code, payload, _ = self.run_release("profile", "inspect", "nope")
        self.assertEqual((code, payload["error"]["code"]), (2, "profile_unknown"))
        contract = self.contract()
        contract["release"] = "unsupported"
        self.write_contract(contract)
        code, payload, _ = self.run_release("profile", "inspect", "github-release")
        self.assertEqual((code, payload["error"]["code"]), (2, "release_unsupported"))
        del contract["release"]
        self.write_contract(contract)
        code, payload, _ = self.run_release("profile", "inspect", "github-release")
        self.assertEqual((code, payload["error"]["code"]), (2, "invalid_contract"))

if __name__ == "__main__":
    unittest.main()
