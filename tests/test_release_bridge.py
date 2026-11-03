"""Legacy skills-config bridge (#124 AC5). Run: just agent-workflow-tests"""
import json
import unittest
from pathlib import Path

from agent_tools import release_bridge, release_profile

REPO = Path(__file__).resolve().parents[1]
LEGACY = (Path(__file__).parent / "fixtures/legacy-skills-config-1722a65d.json").read_bytes()

def contract():
    return json.loads((REPO / ".agents/project.json").read_text("utf-8"))

class NixConfigProfileTest(unittest.TestCase):
    def test_committed_profile_is_the_fixture_and_the_bridge_shape(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/release/github-release-profile.json")
                             .read_text("utf-8"))
        source = contract()
        self.assertEqual(source["release"], {"profiles": {"github-release": fixture}})
        self.assertEqual(release_bridge.forge_only_profile(source), fixture)
        release_profile.compile_profile("github-release", fixture, source)

class ProjectionTest(unittest.TestCase):
    def test_nix_config_last_legacy_bytes_are_identical(self):
        self.assertEqual(len(LEGACY), 81)
        self.assertEqual(release_bridge.project_legacy_deploy(LEGACY, contract()["release"]), LEGACY)

    def test_no_file_generates_nothing(self):
        self.assertFalse((REPO / ".claude/skills.config.json").exists())

    def test_a_present_deploy_member_is_regenerated(self):
        legacy = json.dumps({"deploy": {"adapter": "none"}, "orchestration": {"maxParallel": 2}}).encode()
        self.assertEqual(release_bridge.project_legacy_deploy(legacy, contract()["release"]),
                         b'{\n  "orchestration": {\n    "maxParallel": 2\n  }\n}\n')

    def test_unsupported_and_unrenderable(self):
        self.assertEqual(release_bridge.project_legacy_deploy(b"{ }", "unsupported"), b"{ }")
        profile = json.loads(json.dumps(contract()["release"]))
        profile["profiles"]["github-release"]["activation"] = {"units": []}
        with self.assertRaises(ValueError):
            release_bridge.project_legacy_deploy(LEGACY, profile)

class PlannerTest(unittest.TestCase):
    def test_forge_representable_inputs_become_the_forge_profile(self):
        expected = {"profiles": {"github-release": release_bridge.forge_only_profile(contract())}}
        for legacy in (None, LEGACY, b'{"deploy": {"adapter": "none"}}'):
            with self.subTest(legacy=legacy):
                self.assertEqual(release_bridge.plan_legacy_release(legacy, contract()),
                                 {"release": expected, "questions": []})

    def test_railway_input_is_a_question_never_a_value(self):
        legacy = json.dumps({"deploy": {"adapter": "railway", "project": "p", "services": ["api"],
                                        "watchDoc": "docs/deploy.md"}}).encode()
        self.assertEqual(release_bridge.plan_legacy_release(legacy, contract()), {
            "release": None,
            "questions": [{"id": "release.deploy_adapter_unrepresentable", "pointer": "/deploy"},
                          {"id": "release.watch_doc_to_operations", "pointer": "/deploy/watchDoc"}]})

    def test_unreadable_and_non_forge(self):
        self.assertEqual(release_bridge.plan_legacy_release(b"[", contract())["questions"],
                         [{"id": "release.legacy_unreadable", "pointer": ""}])
        gitlab = contract()
        gitlab["bindings"]["tracker"]["kind"] = "gitlab"
        self.assertEqual(release_bridge.plan_legacy_release(None, gitlab)["questions"],
                         [{"id": "release.forge_unavailable", "pointer": "/deploy"}])

if __name__ == "__main__":
    unittest.main()
