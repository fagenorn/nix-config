from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).parents[4]
TASK_BRIEF = ROOT / "home/common/agent-skills/skills/sdd/scripts/task-brief"
BUDGET = ROOT / "home/common/agent-skills/scripts/artifact_budget.py"
WRAPPER = ROOT / "home/common/agent-skills/scripts/artifact-budget"
POLICY = ROOT / "home/common/agent-skills/artifact-budget-policy.json"


class TaskBriefPackageTest(unittest.TestCase):
    def make_repo(self, directory: Path) -> tuple[Path, dict[str, str]]:
        subprocess.run(["git", "init", "-q", str(directory)], check=True)
        bin_dir = directory / "bin"
        bin_dir.mkdir()
        (bin_dir / "artifact-budget").symlink_to(WRAPPER)
        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        home = directory / "home"
        policy_dir = home / ".agents/share"
        policy_dir.mkdir(parents=True)
        (policy_dir / "artifact-budget-policy.json").symlink_to(POLICY)
        module_dir = home / ".agents/lib/python"
        module_dir.mkdir(parents=True)
        (module_dir / "artifact_budget.py").symlink_to(BUDGET)
        env["HOME"] = str(home)
        return directory / "plan.md", env

    def write_package(self, root: Path) -> tuple[bytes, bytes]:
        members = root.with_suffix("").with_name(root.stem + ".tasks")
        members.mkdir()
        first = b"# Task 1: First\n\nfirst-only\n"
        second = b"# Task 2: Second\n\nsecond-only\n"
        (members / "task-1.md").write_bytes(first)
        (members / "task-2.md").write_bytes(second)
        root.write_text(
            "# Plan\n\n## Task index\n\n"
            "Task 1 — First — a.py — full — [task-1.md](plan.tasks/task-1.md)\n\n"
            "Task 2 — Second — b.py — full — [task-2.md](plan.tasks/task-2.md)\n",
            encoding="utf-8",
        )
        return first, second

    def test_copies_only_the_exact_indexed_member(self):
        with tempfile.TemporaryDirectory() as raw:
            root, env = self.make_repo(Path(raw))
            first, second = self.write_package(root)
            out = Path(raw) / "brief.md"
            result = subprocess.run(
                [str(TASK_BRIEF), str(root), "2", str(out)], env=env,
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(out.read_bytes(), second)
            self.assertNotIn(first, out.read_bytes())

    def test_missing_or_nonconventional_link_fails_without_output(self):
        with tempfile.TemporaryDirectory() as raw:
            root, env = self.make_repo(Path(raw))
            self.write_package(root)
            root.write_text(root.read_text(encoding="utf-8").replace(
                "plan.tasks/task-2.md", "elsewhere/task-2.md"), encoding="utf-8")
            out = Path(raw) / "brief.md"
            result = subprocess.run(
                [str(TASK_BRIEF), str(root), "2", str(out)], env=env,
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertFalse(out.exists())

    def test_over_budget_package_fails_before_replacing_existing_brief(self):
        with tempfile.TemporaryDirectory() as raw:
            root, env = self.make_repo(Path(raw))
            self.write_package(root)
            root.write_bytes(root.read_bytes() + b"x" * 16_384)
            out = Path(raw) / "brief.md"
            out.write_bytes(b"valid-old-brief")
            result = subprocess.run(
                [str(TASK_BRIEF), str(root), "1", str(out)], env=env,
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 3)
            self.assertEqual(out.read_bytes(), b"valid-old-brief")
            self.assertNotIn("Permission denied", result.stderr)
