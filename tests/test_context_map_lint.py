import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
LINTER = REPO_ROOT / "python/agent_tools/context_map_lint.py"


class ContextMapLintTest(unittest.TestCase):
    def run_lint(self, root, context_map):
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.context_map_lint", "--repo-root", str(root), "--context-map", str(context_map)],
            text=True, capture_output=True,
        )

    def test_selected_valid_map_exits_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context_map = root / "CONTEXT-MAP.md"
            area = root / "area.md"
            area.write_text("---\narea: example\nbudget: 200\n---\n\n**Thing**: a term\n")
            context_map.write_text("## Areas\n| Area | Context file | Gist | governs |\n|---|---|---|---|\n| Example | [area](area.md) | x | `*.py` |\n\n## Terms\n| Term | Area |\n|---|---|\n| Thing | Example |\n")
            (root / "main.py").write_text("")
            self.assertEqual(self.run_lint(root, context_map).returncode, 0)

    def test_relative_and_outside_maps_are_misuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            relative = subprocess.run([sys.executable, "-m", "agent_tools.context_map_lint", "--repo-root", str(root), "--context-map", "CONTEXT-MAP.md"], text=True, capture_output=True)
            self.assertEqual(relative.returncode, 2)
            outside = self.run_lint(root, Path(temp).parent / "outside.md")
            self.assertEqual(outside.returncode, 2)

    def test_missing_context_map_and_malformed_map(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            missing = subprocess.run([sys.executable, "-m", "agent_tools.context_map_lint", "--repo-root", str(root)], text=True, capture_output=True)
            self.assertEqual(missing.returncode, 2)
            context_map = root / "CONTEXT-MAP.md"
            context_map.write_text("not a context map")
            self.assertEqual(self.run_lint(root, context_map).returncode, 1)

    def test_source_has_no_policy_discovery(self):
        source = LINTER.read_text(encoding="utf-8")
        for token in ("resolve-project", ".agents/project.json", "find_map(", "docs/CONTEXT-MAP.md"):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
