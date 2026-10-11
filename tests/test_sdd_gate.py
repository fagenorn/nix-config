"""`sdd-gate` run from source (issue 353, spec seam 1).

The command runs as `python -m agent_tools.sdd_gate` in a temporary git
repository under a temporary HOME. PATH shims run the source `artifact-budget`,
`sdd-workspace`, `task-brief` and `workflow-state`; the lifecycle ledger is
driven through the lifecycle suites' harness, loaded from its source file as
tests/test_launch_commit.py loads it.
"""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/sdd-gate"
SKILL = FIXTURES / "skill"
PROJECT_STANDARDS = FIXTURES / "standards-project"
SKILLS = ROOT / "home/common/agent-skills"
HARNESS_SOURCE = SKILLS / "tests/test_workflow_state.py"
WORKFLOW = SKILLS / "scripts/workflow-state.py"
BUDGET_MODULE = SKILLS / "scripts/artifact_budget.py"
POLICY = SKILLS / "artifact-budget-policy.json"
SDD_SCRIPTS = SKILLS / "skills/sdd/scripts"
COMMAND = [sys.executable, "-m", "agent_tools.sdd_gate"]
INVALID = "sdd-gate: invalid invocation\n"
HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
REFUSAL_KEYS = {"command", "outcome", "step", "gate", "detail", "report", "completed_steps"}
# The shim runs the source budget command; FORCE makes the independent
# review-package check, and only it, answer over budget in the checker's wire form.
BUDGET_SHIM = ("#!{python}\nimport os, sys\n{force}"
               "os.execv(sys.executable, [sys.executable, {module!r}, *sys.argv[1:]])\n")
FORCE_OVER_BUDGET = (
    'if sys.argv[1:5] == ["check", "--kind", "review-package", "--root"]:\n'
    '    import json\n'
    '    sys.stdout.write(json.dumps({"interface_version": 1, "kind": "review-package",\n'
    '        "metrics": {"file_count": 1, "largest_member_bytes": 1, "root_bytes": 1,\n'
    '                    "total_bytes": 2},\n'
    '        "status": "over_budget", "violations": ["aggregate_bytes"]},\n'
    '        ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\\n")\n'
    '    raise SystemExit(3)\n')

FAIL_DESCRIBE = ('if sys.argv[1:2] == ["describe"]:\n'
                 '    raise SystemExit(4)\n')


def _harness():
    spec = importlib.util.spec_from_file_location("sdd_gate_harness", HARNESS_SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.LifecycleHarness


LifecycleHarness = _harness()


class GateCase(LifecycleHarness, unittest.TestCase):
    """A committed fixture plan in a primary checkout, with an sdd ledger for it."""

    def setUp(self):
        super().setUp()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.write_budget_shim()
        for name in ("sdd-workspace", "task-brief"):
            (self.bin / name).symlink_to(SDD_SCRIPTS / name)
        self.write_executable(
            "workflow-state",
            f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(WORKFLOW))} "$@"\n')
        (self.home / ".agents/share/artifact-budget-policy.json").symlink_to(POLICY)
        self.bar = self.home / ".agents/standards/the-bar.md"
        self.bar.parent.mkdir()
        shutil.copy(FIXTURES / "standards-global/the-bar.md", self.bar)
        self.env = {**self.cli_env, **HERMETIC_GIT, "PYTHONPATH": str(ROOT / "python"),
                    "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"}
        (self.root / "repo").mkdir()
        self.repo = (self.root / "repo").resolve()
        self.repo_git("init", "-q", "--initial-branch", "issue-14")
        self.repo_git("config", "commit.gpgsign", "false")  # throwaway fixture repo
        shutil.copy(FIXTURES / "plan.md", self.repo / "plan.md")
        shutil.copytree(FIXTURES / "plan.tasks", self.repo / "plan.tasks")
        self.write("src/app.py", "value = 1\n")
        self.delivery_base = self.repo_commit("base")
        self.write("README.md", "fixture\n")
        self.repo_commit("plan")
        self.plan = self.repo / "plan.md"
        self.workspace = Path(self.run_tool("sdd-workspace", str(self.plan)).strip())
        self.ledger = self.workspace / "progress.md"
        self.ledger.write_text(f"# SDD ledger — plan: {self.plan}\n", encoding="utf-8")

    def write_executable(self, name, text):
        path = self.bin / name
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)

    def write_budget_shim(self, force=""):
        self.write_executable("artifact-budget", BUDGET_SHIM.format(
            python=sys.executable, force=force, module=str(BUDGET_MODULE)))

    def run_tool(self, *argv):
        return subprocess.run(argv, cwd=self.repo, env=self.env, capture_output=True,
                              text=True, check=True).stdout

    def repo_git(self, *args):
        return self.run_tool("git", *args).strip()

    def write(self, relative, text):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def repo_commit(self, message):
        self.repo_git("add", "-A")
        self.repo_git("commit", "-q", "-m", message)
        return self.repo_git("rev-parse", "HEAD")

    def gate(self, *args):
        return subprocess.run([*COMMAND, *map(str, args)], cwd=self.repo, env=self.env,
                              capture_output=True, text=True, check=False)

    def review(self, task, *extra):
        return self.gate("review", self.plan, "--skill-dir", SKILL, "--task", task,
                         "--standards", PROJECT_STANDARDS, *extra)

    def identity(self, action="14:1:1"):
        return ("--repo-root", self.root, "--run-id", self.run_id, "--action-id", action)

    def launch(self, worktree=None):
        """Mint the run and spawn issue 14's first launch, `14:1:1`."""
        self.init_run()
        spawned = self.spawn(issue=14, worktree=str(self.repo if worktree is None else worktree))
        self.assertEqual(spawned["id"], "14:1:1")

    def one_object(self, completed):
        self.assertEqual(completed.stdout.count("\n"), 1, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def ready(self, completed):
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        return self.one_object(completed)

    def assert_gate_refused(self, completed, *, command, step, gate, steps, code=2):
        self.assertEqual(completed.returncode, code, completed.stderr + completed.stdout)
        out = self.one_object(completed)
        self.assertEqual(set(out), REFUSAL_KEYS)
        self.assertEqual(
            (out["command"], out["outcome"], out["step"], out["gate"], out["completed_steps"]),
            (command, "refused", step, gate, steps))
        self.assertIsInstance(out["detail"], str)
        self.assertNotIn("\n", out["detail"])
        if gate != "decompose_required":
            self.assertIsNone(out["report"])
        return out

    def ledger_lines(self):
        return self.ledger.read_text(encoding="utf-8").splitlines()

    def append_ledger(self, line):
        with self.ledger.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def start_task(self, task, relative, text):
        """Record the task's base as `sdd-gate next` does, then commit its change: (base, head)."""
        base = self.repo_git("rev-parse", "HEAD")
        self.append_ledger(f"Task {task}: dispatched (base {base})")
        self.write(relative, text)
        return base, self.repo_commit(f"task {task}")

    def budget_metrics(self, kind, root):
        return json.loads(self.run_tool("artifact-budget", "check", "--kind", kind, "--root",
                                        str(root), "--format", "json"))["metrics"]

    def package_root(self, base, head):
        return f".superpowers/sdd/primary/plan/review-{base[:7]}..{head[:7]}.json"

    def golden(self, name, **slots):
        """The hand-assembled golden with its run-dependent `@@NAME@@` slots filled."""
        text = (FIXTURES / name).read_text(encoding="utf-8")
        for key, value in {**slots, "WORKSPACE": self.workspace, "PLAN_ROOT": self.plan,
                           "HOME": self.home, "STANDARDS": PROJECT_STANDARDS}.items():
            text = text.replace(f"@@{key}@@", str(value))
        for key, value in self.budget_metrics("implementation-plan", self.plan).items():
            text = text.replace(f"@@PLAN_{key.upper()}@@", str(value))
        self.assertNotIn("@@", text)
        return text.encode("utf-8")


class ReviewTest(GateCase):
    def brief(self, task=1):
        return self.workspace / f"task-{task}-review-dispatch.md"

    def test_review_renders_the_golden_reviewer_brief(self):
        base, head = self.start_task(1, "src/app.py", "value = 2\n")
        out = self.ready(self.review(1))
        root = self.package_root(base, head)
        metrics = self.budget_metrics("review-package", self.repo / root)
        self.assertEqual(out, {
            "command": "review", "outcome": "ready", "task": 1, "brief_path": str(self.brief()),
            "base_sha": base, "head_sha": head, "manifest_root": root, "metrics": metrics,
            "standards": [str(self.bar), str(PROJECT_STANDARDS / "python-rules.md")]})
        self.assertEqual(self.brief().read_bytes(), self.golden(
            "golden-reviewer-brief.md", BASE_SHA=base, HEAD_SHA=head, MANIFEST_ROOT=root,
            **{key.upper(): value for key, value in metrics.items()}))
        self.assertEqual(self.ledger_lines()[1:], [f"Task 1: dispatched (base {base})"])

    def test_an_ungoverned_diff_drops_the_layer_two_document(self):
        self.start_task(2, "notes.txt", "note\n")
        out = self.ready(self.review(2))
        self.assertEqual(out["standards"], [str(self.bar)])
        brief = self.brief(2).read_text(encoding="utf-8")
        self.assertIn(f"Source: {self.bar}\n", brief)
        self.assertNotIn("python-rules.md", brief)

    def test_a_refused_release_is_refused_at_release_worker(self):
        self.launch()
        self.start_task(1, "src/app.py", "value = 2\n")
        refused = self.review(1, *self.identity(), "--worker-id", "14:1:1:w9")
        self.assert_gate_refused(refused, command="review", step="release-worker", gate=None,
                                 steps=["ledger"])
        self.assertFalse(self.brief().exists())
        self.assertEqual(list(self.workspace.glob("review-*")), [])

    def test_a_decompose_required_report_is_refused_at_validate_report(self):
        self.write("large.txt", "small\n")
        self.repo_commit("small")
        self.start_task(1, "large.txt", "X" * 70_000 + "\n")
        out = self.assert_gate_refused(
            self.review(1), command="review", step="validate-report", gate="decompose_required",
            steps=["ledger", "review-package"], code=3)
        self.assertEqual(out["report"]["state"], "decompose_required")
        self.assertEqual(out["report"]["artifact"]["budget_status"], "over_budget")
        self.assertFalse(self.brief().exists())

    def test_an_over_budget_package_is_refused_at_budget_check(self):
        self.start_task(1, "src/app.py", "value = 2\n")
        self.ready(self.review(1))
        self.brief().unlink()
        # The producer runs the same check, so the refusal is forced on the reuse path (D14).
        self.write_budget_shim(FORCE_OVER_BUDGET)
        self.assert_gate_refused(
            self.review(1), command="review", step="budget-check", gate="failed",
            steps=["ledger", "review-package", "validate-report"])
        self.assertFalse(self.brief().exists())

    def test_a_worker_is_released_and_a_repeated_call_reuses_the_package(self):
        self.launch()
        worker = self.register_worker(action_id="14:1:1", now="2026-08-13T20:01:00Z")["worker_id"]
        self.start_task(1, "src/app.py", "value = 2\n")
        first = self.review(1, *self.identity(), "--worker-id", worker)
        self.ready(first)
        self.assertFalse(self.check_worker(worker)["live"])
        again = self.review(1, *self.identity(), "--worker-id", worker)
        self.assertEqual((again.returncode, again.stdout), (0, first.stdout))
        self.assertEqual(len(list(self.workspace.glob("review-*.report.json"))), 1)

    def test_an_existing_package_that_cannot_be_reused_is_refused(self):
        base, head = self.start_task(1, "src/app.py", "value = 2\n")
        self.ready(self.review(1))
        root = self.repo / self.package_root(base, head)
        saved = root.with_name(root.stem + ".report.json")
        report = saved.read_bytes()

        def without_its_saved_report():
            saved.unlink()

        def with_another_range():
            manifest = json.loads(root.read_bytes())
            manifest["range"]["head"] = "0" * 40
            root.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
                            encoding="utf-8")

        for arrange in (without_its_saved_report, with_another_range):
            with self.subTest(case=arrange.__name__):
                saved.write_bytes(report)
                arrange()
                self.brief().unlink(missing_ok=True)
                self.assert_gate_refused(self.review(1), command="review", step="review-package",
                                         gate="failed", steps=["ledger"])
                self.assertFalse(self.brief().exists())
                self.assertTrue(root.exists())

    def test_each_reuse_refusal_names_its_own_cause(self):
        base, head = self.start_task(1, "src/app.py", "value = 2\n")
        self.ready(self.review(1))
        root = self.repo / self.package_root(base, head)
        saved = root.with_name(root.stem + ".report.json")
        manifest, report = root.read_bytes(), saved.read_bytes()

        def no_saved_report():
            saved.unlink()

        def another_range():
            changed = json.loads(manifest)
            changed["range"]["head"] = "0" * 40
            root.write_text(json.dumps(changed), encoding="utf-8")

        def duplicate_keys():
            root.write_text('{"range":1,"range":2}', encoding="utf-8")

        details = {}
        for arrange in (no_saved_report, another_range, duplicate_keys):
            root.write_bytes(manifest)
            saved.write_bytes(report)
            arrange()
            out = self.assert_gate_refused(self.review(1), command="review",
                                           step="review-package", gate="failed", steps=["ledger"])
            details[arrange.__name__] = out["detail"]
        self.assertEqual(len(set(details.values())), len(details), details)

    def test_a_failed_producer_refusal_carries_its_stderr_tail(self):
        self.start_task(1, "src/app.py", "value = 2\n")
        # The producer's own `describe` fails, so it exits 2 and says why on stderr.
        self.write_budget_shim(FAIL_DESCRIBE)
        out = self.assert_gate_refused(self.review(1), command="review", step="review-package",
                                       gate="failed", steps=["ledger"])
        self.assertIn("validator unavailable", out["detail"])

    def test_the_ledger_is_checked_before_anything_runs(self):
        header = self.ledger.read_text(encoding="utf-8")
        base = self.repo_git("rev-parse", "HEAD")
        cases = {
            "no dispatched line": header,
            "a foreign plan": "# SDD ledger — plan: /elsewhere/plan.md\n"
                              f"Task 1: dispatched (base {base})\n",
            "two bases for one task": header + f"Task 1: dispatched (base {base})\n"
                                      f"Task 1: dispatched (base {self.delivery_base})\n",
            "no ledger": None,
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                if text is None:
                    self.ledger.unlink()
                else:
                    self.ledger.write_text(text, encoding="utf-8")
                self.assert_gate_refused(self.review(1), command="review", step="ledger",
                                         gate=None, steps=[])
        self.assertEqual(list(self.workspace.glob("review-*")), [])

    def test_a_header_path_relative_to_the_checkout_is_this_plan(self):
        self.ledger.write_text("# SDD ledger — plan: plan.md\n", encoding="utf-8")
        self.start_task(1, "src/app.py", "value = 2\n")
        self.ready(self.review(1))

    def test_an_invalid_invocation_prints_one_stderr_line(self):
        base = ("review", self.plan, "--skill-dir", SKILL, "--task", "1")
        cases = {
            "a worker id without an identity": (*base, "--worker-id", "14:1:1:w1"),
            "a partial identity": (*base, "--repo-root", self.root, "--run-id", "run-1"),
            "an identity without a worker id": (*base, *self.identity()),
            "task zero": ("review", self.plan, "--skill-dir", SKILL, "--task", "0"),
            "no task": ("review", self.plan, "--skill-dir", SKILL),
            "no subcommand": (),
            "an unknown flag": (*base, "--force"),
        }
        for name, argv in cases.items():
            with self.subTest(case=name):
                done = self.gate(*argv)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (2, "", INVALID))

    def test_help_prints_usage_and_exits_zero(self):
        done = self.gate("--help")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(done.stdout.startswith("usage: sdd-gate "), done.stdout[:80])


if __name__ == "__main__":
    unittest.main()
