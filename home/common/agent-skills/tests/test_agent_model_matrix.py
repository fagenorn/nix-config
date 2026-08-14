from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).parents[4]
SCRIPT = REPO_ROOT / "home/common/agent-skills/scripts/agent-model-matrix.py"
MATRIX = REPO_ROOT / "home/common/agent-skills/model-matrix.json"
AGENTS = REPO_ROOT / "home/common/claude-code/agents"

EXPECTED_TIERS = {
    "issue-owner": ("opus", "high"),
    "ship-owner": ("opus", "high"),
    "implementer": ("opus", "high"),
    "reviewer": ("opus", "high"),
    "reviewer-lite": ("sonnet", "medium"),
    "mechanic": ("sonnet", "medium"),
    "explorer": ("haiku", "medium"),
    "codex-transport": ("sonnet", "medium"),
}


def load_module():
    spec = importlib.util.spec_from_file_location("agent_model_matrix", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        return {}
    result = {}
    for line in lines[1:]:
        if line == "---":
            return result
        key, separator, value = line.partition(":")
        if separator:
            result[key.strip()] = value.strip()
    return {}


def write_fixture(root: Path, data: dict) -> None:
    matrix_path = root / "home/common/agent-skills/model-matrix.json"
    matrix_path.parent.mkdir(parents=True)
    matrix_path.write_text(json.dumps(data), encoding="utf-8")
    agents = root / "home/common/claude-code/agents"
    agents.mkdir(parents=True)
    for role in ("implementer", "mechanic", "reviewer", "reviewer-lite"):
        model, effort = EXPECTED_TIERS[role]
        (agents / f"{role}.md").write_text(
            f"---\nname: {role}\nmodel: {model}\neffort: {effort}\n---\n",
            encoding="utf-8",
        )


class AgentModelMatrixTest(unittest.TestCase):
    def test_matrix_declares_the_exact_closed_role_tiers(self):
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"roles", "dispatch_sites", "scenarios"})
        self.assertEqual(set(data["roles"]), set(EXPECTED_TIERS))
        for role, expected in EXPECTED_TIERS.items():
            spec = data["roles"][role]
            self.assertEqual((spec["model"], spec["effort"]), expected)
            self.assertEqual(
                set(spec), {"model", "effort", "eligible", "prohibited"}
            )
            self.assertIsInstance(spec["eligible"], list)
            self.assertIsInstance(spec["prohibited"], list)

    def test_every_custom_agent_explicitly_matches_its_matrix_role(self):
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        files = sorted(AGENTS.glob("*.md"))
        self.assertEqual(
            [path.name for path in files],
            ["implementer.md", "mechanic.md", "reviewer-lite.md", "reviewer.md"],
        )
        for path in files:
            metadata = frontmatter(path)
            self.assertIn("model", metadata, path)
            self.assertIn("effort", metadata, path)
            role = metadata["name"]
            self.assertIn(role, data["roles"], path)
            self.assertEqual(metadata["model"], data["roles"][role]["model"], path)
            self.assertEqual(metadata["effort"], data["roles"][role]["effort"], path)

    def test_repository_contract_validates(self):
        module = load_module()
        self.assertEqual(module.validate(REPO_ROOT), [])

    def test_cli_reports_missing_manifest_path_and_unknown_role(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = json.loads(MATRIX.read_text(encoding="utf-8"))
            data["dispatch_sites"] = [
                {
                    "id": "missing-site",
                    "path": "missing/SKILL.md",
                    "marker": "agent-dispatch:missing-site",
                    "role": "not-a-role",
                    "model": "opus",
                    "effort": "high",
                    "requires": [],
                }
            ]
            write_fixture(root, data)

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "validate", "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing/SKILL.md", result.stderr)
        self.assertIn("unknown role 'not-a-role'", result.stderr)

    def test_omitted_agent_model_fails(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            matrix_path = root / "home/common/agent-skills/model-matrix.json"
            data = json.loads(MATRIX.read_text(encoding="utf-8"))
            write_fixture(root, data)
            agents = root / "home/common/claude-code/agents"
            (agents / "implementer.md").write_text(
                "---\nname: implementer\neffort: high\n---\n", encoding="utf-8"
            )

            errors = module.validate(root)

        self.assertTrue(
            any("implementer.md" in error and "model" in error for error in errors),
            errors,
        )

    def test_malformed_known_role_returns_errors_instead_of_crashing(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = json.loads(MATRIX.read_text(encoding="utf-8"))
            data["roles"]["reviewer"] = "not-an-object"
            write_fixture(root, data)

            errors = module.validate(root)

        self.assertTrue(
            any("matrix.roles.reviewer: must be an object" in error for error in errors),
            errors,
        )

    def test_duplicate_dispatch_id_marker_mismatch_and_reviewer_lite_misuse_fail(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = json.loads(MATRIX.read_text(encoding="utf-8"))
            manifest = root / "workflow.md"
            manifest.write_text("expected-marker\n", encoding="utf-8")
            data["dispatch_sites"] = [
                {
                    "id": "duplicate",
                    "path": "workflow.md",
                    "marker": "absent-marker",
                    "role": "reviewer-lite",
                    "model": "sonnet",
                    "effort": "medium",
                    "requires": [],
                },
                {
                    "id": "duplicate",
                    "path": "workflow.md",
                    "marker": "expected-marker",
                    "role": "reviewer",
                    "model": "sonnet",
                    "effort": "medium",
                    "requires": [],
                },
            ]
            write_fixture(root, data)

            errors = module.validate(root)

        joined = "\n".join(errors)
        self.assertIn("duplicate id 'duplicate'", joined)
        self.assertIn("absent-marker", joined)
        self.assertIn("reviewer-lite requires", joined)
        self.assertIn("does not match role 'reviewer'", joined)

    def test_trace_is_deterministic_and_rejects_unknown_scenario(self):
        module = load_module()
        first = module.trace(REPO_ROOT, "sdd")
        second = module.trace(REPO_ROOT, "sdd")
        self.assertEqual(first, second)
        self.assertTrue(first)
        self.assertTrue(all(set(event) == {"id", "role", "model", "effort"} for event in first))
        with self.assertRaises(ValueError):
            module.trace(REPO_ROOT, "does-not-exist")


if __name__ == "__main__":
    unittest.main()
