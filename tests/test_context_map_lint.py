import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
LINTER = REPO_ROOT / "python/agent_tools/delivery/context_map_lint.py"


class ContextMapLintTest(unittest.TestCase):
    def run_lint(self, root, context_map, *extra):
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.context_map_lint", "--repo-root", str(root), "--context-map", str(context_map), *extra],
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
            relative = subprocess.run([sys.executable, "-m", "agent_tools.delivery.context_map_lint", "--repo-root", str(root), "--context-map", "CONTEXT-MAP.md"], text=True, capture_output=True)
            self.assertEqual(relative.returncode, 2)
            outside = self.run_lint(root, Path(temp).parent / "outside.md")
            self.assertEqual(outside.returncode, 2)

    def test_missing_context_map_and_malformed_map(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            missing = subprocess.run([sys.executable, "-m", "agent_tools.delivery.context_map_lint", "--repo-root", str(root)], text=True, capture_output=True)
            self.assertEqual(missing.returncode, 2)
            context_map = root / "CONTEXT-MAP.md"
            context_map.write_text("not a context map")
            self.assertEqual(self.run_lint(root, context_map).returncode, 1)

    def over_budget_map(self, root):
        """A map the default lint fails on its 150-line budget alone."""
        area = root / "area.md"
        area.write_text("---\narea: example\nbudget: 200\n---\n\n**Thing**: a term\n")
        context_map = root / "CONTEXT-MAP.md"
        context_map.write_text("## Areas\n| Area | Context file | Gist | governs |\n|---|---|---|---|\n| Example | [area](area.md) | x | `*.py` |\n\n## Terms\n| Term | Area |\n|---|---|\n| Thing | Example |\n" + "\n" * 150)
        (root / "main.py").write_text("")
        return context_map

    def repo_lint(self, root, body):
        script = root / "repo-lint.py"
        script.write_text(body)
        return [sys.executable, str(script)]

    def test_without_a_repo_lint_the_map_budget_still_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self.run_lint(root, self.over_budget_map(root))
            self.assertEqual(result.returncode, 1)
            self.assertIn("budget 150", result.stderr)

    def test_a_map_the_repo_lint_accepts_is_not_failed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            context_map = self.over_budget_map(root)
            command = self.repo_lint(root, "import os, sys\nprint('repo lint in', os.getcwd(), sys.argv[1:])\n")
            result = self.run_lint(root, context_map, "--repo-lint", *command, "--flag", "docs")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, f"repo lint in {root} ['--flag', 'docs']\n")
            self.assertEqual(result.stderr, "")

    def test_the_repo_lint_findings_and_status_are_the_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            area = root / "area.md"
            area.write_text("---\narea: example\nbudget: 200\n---\n\n**Thing**: a term\n")
            context_map = root / "CONTEXT-MAP.md"
            context_map.write_text("## Areas\n| Area | Context file | Gist | governs |\n|---|---|---|---|\n| Example | [area](area.md) | x | `*.py` |\n\n## Terms\n| Term | Area |\n|---|---|\n| Thing | Example |\n")
            (root / "main.py").write_text("")
            self.assertEqual(self.run_lint(root, context_map).returncode, 0)
            command = self.repo_lint(root, "import sys\nprint('map over the repo budget', file=sys.stderr)\nsys.exit(1)\n")
            result = self.run_lint(root, context_map, "--repo-lint", *command)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, "map over the repo budget\n")

    def test_the_repo_lint_runs_in_its_entry_cwd(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            context_map = self.over_budget_map(root)
            scripts = root / "scripts"
            scripts.mkdir()
            lint = scripts / "lint.py"
            lint.write_text(f"#!{sys.executable}\nimport os\nprint('repo lint in', os.getcwd())\n")
            lint.chmod(0o755)
            result = self.run_lint(root, context_map, "--repo-lint-cwd", str(scripts), "--repo-lint", "./lint.py")
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, f"repo lint in {scripts}\n", ""))
            in_root = self.run_lint(root, context_map, "--repo-lint", "./lint.py")
            self.assertEqual(in_root.returncode, 2)

    def test_the_repo_lint_exit_2_is_passed_through(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context_map = self.over_budget_map(root)
            command = self.repo_lint(root, "import sys\nsys.exit(2)\n")
            result = self.run_lint(root, context_map, "--repo-lint", *command)
            self.assertEqual((result.returncode, result.stderr), (2, ""))

    def test_repo_lint_cwd_misuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context_map = self.over_budget_map(root)
            for cwd in ("scripts", str(root / "absent"), str(root.parent), str(context_map)):
                with self.subTest(cwd=cwd):
                    result = self.run_lint(root, context_map, "--repo-lint-cwd", cwd, "--repo-lint", "true")
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("--repo-lint-cwd", result.stderr)
            alone = self.run_lint(root, context_map, "--repo-lint-cwd", str(root))
            self.assertEqual(alone.returncode, 2)
            self.assertIn("Usage: context-map-lint --repo-root ", alone.stderr)

    def test_repo_lint_misuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context_map = self.over_budget_map(root)
            empty = self.run_lint(root, context_map, "--repo-lint")
            self.assertEqual(empty.returncode, 2)
            self.assertIn("Usage: context-map-lint --repo-root ", empty.stderr)
            absent = self.run_lint(root, context_map, "--repo-lint", str(root / "no-such-lint"))
            self.assertEqual(absent.returncode, 2)
            self.assertIn("cannot run the repository's lint", absent.stderr)
            outside = self.run_lint(root, root.parent / "outside.md", "--repo-lint", "true")
            self.assertEqual(outside.returncode, 2)
            stray = self.run_lint(root, context_map, "--other", "true")
            self.assertEqual(stray.returncode, 2)

    def test_source_has_no_policy_discovery(self):
        source = LINTER.read_text(encoding="utf-8")
        for token in ("resolve-project", ".agents/project.json", "find_map(", "docs/CONTEXT-MAP.md"):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
