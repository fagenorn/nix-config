"""Eval case files as data (#293): setup kinds, setup inputs and pipeline cases."""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
EVALS_DIR = REPO_ROOT / "home/common/agent-skills/evals"
RUNNER = EVALS_DIR / "run-eval.sh"
SETUP_INPUTS = EVALS_DIR / "setups/issue-3"
SKILL_ROOTS = (
    REPO_ROOT / "home/common/agent-skills/skills",
    REPO_ROOT / "home/common/claude-code/skills",
)
BUDGET = REPO_ROOT / "home/common/agent-skills/scripts/artifact_budget.py"
POLICY = REPO_ROOT / "home/common/agent-skills/artifact-budget-policy.json"
SETUP_KINDS = {"dirty-worktree", "shippable-worktree", "planned-worktree", "release-ready"}
PIPELINE_SKILLS = ("from-issue", "ship-issue", "sdd", "ship-release", "orchestrate-issues")
ASSERT_LIB = EVALS_DIR / "assert-lib.sh"


def case_files():
    return sorted(path for root in SKILL_ROOTS for path in root.glob("*/evals/evals.json"))


def runner_setup_arms():
    text = RUNNER.read_text(encoding="utf-8")
    start = text.index('case "$SETUP_KIND" in')
    block = text[start:text.index("esac", start)]
    arms = set()
    for label in re.findall(r'^\s*([a-z|"*-]+)\)', block, re.M):
        arms.update(alt for alt in label.split("|") if alt not in ('""', "*"))
    return arms


def skill_cases(skill):
    for root in SKILL_ROOTS:
        path = root / skill / "evals/evals.json"
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))["evals"]
    raise AssertionError(f"no evals.json for {skill}")


def plan_tasks_verifiable(root):
    return subprocess.run(
        ["bash", "-c", 'source "$0"; plan_tasks_verifiable "$1"', str(ASSERT_LIB), str(root)],
        capture_output=True, text=True, timeout=60)


class EvalCasesTest(unittest.TestCase):
    def test_runner_dispatch_arms_are_the_closed_setup_kinds(self):
        self.assertEqual(runner_setup_arms(), SETUP_KINDS)

    def test_every_named_setup_kind_is_a_runner_arm(self):
        arms = runner_setup_arms()
        for path in case_files():
            for case in json.loads(path.read_text(encoding="utf-8"))["evals"]:
                kind = (case.get("setup") or {}).get("kind")
                if kind is not None:
                    with self.subTest(path=str(path.relative_to(REPO_ROOT)), case=case["id"]):
                        self.assertIn(kind, arms)

    def assert_within_budget(self, kind, root):
        done = subprocess.run(
            [sys.executable, str(BUDGET), "check", "--kind", kind, "--root", str(root),
             "--policy", str(POLICY), "--format", "json"],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["status"], "within_budget")

    def test_setup_spec_passes_the_design_spec_budget(self):
        self.assert_within_budget(
            "design-spec", SETUP_INPUTS / "2026-10-07-issue-3-rename-flag-design.md")

    def test_setup_plan_passes_the_implementation_plan_budget(self):
        self.assert_within_budget(
            "implementation-plan", SETUP_INPUTS / "2026-10-07-issue-3-rename-flag.md")

    def test_setup_patch_implements_issue_three_on_the_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "repo"
            shutil.copytree(EVALS_DIR / "fixture-repo", work,
                            ignore=shutil.ignore_patterns("__pycache__"))
            subprocess.run(["git", "init", "-q", str(work)], check=True)
            applied = subprocess.run(
                ["git", "-C", str(work), "apply", str(SETUP_INPUTS / "implementation.patch")],
                capture_output=True, text=True)
            self.assertEqual(applied.returncode, 0, applied.stderr)
            tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-q"],
                                   cwd=work, capture_output=True, text=True, timeout=120)
            self.assertEqual(tests.returncode, 0, tests.stderr)
            probe = str(Path(tmp) / "probe.json")
            cli = [sys.executable, "-m", "tinytask", "--file", probe, "list"]
            self.assertEqual(subprocess.run(cli + ["--include-done"], cwd=work,
                                            capture_output=True).returncode, 0)
            self.assertEqual(subprocess.run(cli + ["--all"], cwd=work,
                                            capture_output=True).returncode, 2)
            for relative in ("tinytask/cli.py", "README.md", "tests/test_cli.py"):
                with self.subTest(file=relative):
                    self.assertNotIn("--all", (work / relative).read_text(encoding="utf-8"))

    def test_each_pipeline_skill_has_a_scripted_pipeline_case(self):
        for skill in PIPELINE_SKILLS:
            with self.subTest(skill=skill):
                scripted = [
                    case for case in skill_cases(skill)
                    if case.get("mode") == "pipeline"
                    and case.get("prompt", "").strip() and case.get("asserts")
                ]
                self.assertGreaterEqual(len(scripted), 1, f"{skill} has no pipeline case")

    def test_pipeline_prompts_resolve_once_and_stop_explicitly(self):
        for skill in PIPELINE_SKILLS:
            for case in skill_cases(skill):
                if case.get("mode") != "pipeline":
                    continue
                with self.subTest(skill=skill, case=case["id"]):
                    self.assertIn("ResolvedProject", case["prompt"])
                    self.assertRegex(case["prompt"].lower(), r"\bstop\b")

    def test_from_issue_asserts_never_prefix_an_absolute_artifact_dir(self):
        for case in skill_cases("from-issue"):
            for check in case.get("asserts") or []:
                with self.subTest(case=case["id"], name=check["name"]):
                    self.assertNotRegex(check["shell"], r'\$(WT|REPO|PRE_WT)/\$(SPEC|PLAN)_DIR')
                    self.assertNotRegex(check["shell"], r'commits_touch "\$WT" "\$(SPEC|PLAN)_DIR"')

    def test_plan_tasks_verifiable_reads_indexed_members(self):
        index = ("# Plan\n\n## Task index\n\n"
                 "Task 1 \u2014 x \u2014 f \u2014 full \u2014 [task-1.md](p.tasks/task-1.md)\n"
                 "Task 2 \u2014 y \u2014 g \u2014 full \u2014 [task-2.md](p.tasks/task-2.md)\n\n## Acceptance map\n")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "p.md"
            root.write_text(index, encoding="utf-8")
            members = Path(tmp) / "p.tasks"
            members.mkdir()
            (members / "task-1.md").write_text("# Task 1: x\n\nRun: `true`\nExpected: exit 0.\n", encoding="utf-8")
            with self.subTest(case="a linked member is missing"):
                self.assertNotEqual(plan_tasks_verifiable(root).returncode, 0)
            (members / "task-2.md").write_text("# Task 2: y\n\n- [ ] Step 1: edit g\n", encoding="utf-8")
            with self.subTest(case="a member has no verification line"):
                done = plan_tasks_verifiable(root)
                self.assertNotEqual(done.returncode, 0)
                self.assertIn("task-2.md", done.stdout)
            (members / "task-2.md").write_text("# Task 2: y\n\nRun: `true`\nExpected: exit 0.\n", encoding="utf-8")
            with self.subTest(case="every member is verifiable"):
                done = plan_tasks_verifiable(root)
                self.assertEqual(done.returncode, 0, done.stdout)
            root.write_text("# Plan\n\n## Task index\n\nnone\n", encoding="utf-8")
            with self.subTest(case="an index that links no member"):
                self.assertNotEqual(plan_tasks_verifiable(root).returncode, 0)
            root.write_text("# Plan\n\n### Task 1: x\n\nExpected: ok\n", encoding="utf-8")
            with self.subTest(case="a legacy single-file plan"):
                self.assertEqual(plan_tasks_verifiable(root).returncode, 0)


if __name__ == "__main__":
    unittest.main()
