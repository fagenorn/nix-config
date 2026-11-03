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

from agent_tools import sdd_brief

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


def force_check(result):
    """Shim code that makes the review-package check, and only it, print `result` and exit 3."""
    line = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    return ('if sys.argv[1:5] == ["check", "--kind", "review-package", "--root"]:\n'
            f'    sys.stdout.write({line!r})\n'
            '    raise SystemExit(3)\n')


# The checker's over-budget wire form: metrics, violations and overages agree (issue 472 D6).
OVER_BUDGET = {"interface_version": 1, "kind": "review-package",
               "metrics": {"file_count": 1, "largest_member_bytes": 1, "root_bytes": 1,
                           "total_bytes": 2},
               "overages": {"aggregate_bytes": {"limit": 1, "over_by": 1}},
               "status": "over_budget", "violations": ["aggregate_bytes"]}
FORCE_OVER_BUDGET = force_check(OVER_BUDGET)

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
        out = self.assert_gate_refused(
            self.review(1), command="review", step="budget-check", gate="failed",
            steps=["ledger", "review-package", "validate-report"])
        self.assertEqual(out["detail"], "package is over_budget")
        self.assertFalse(self.brief().exists())

    def test_a_check_that_breaks_the_overages_contract_is_refused_at_budget_check(self):
        """Issue 472 D8, D14: the budget authority refuses a check whose overages break the wire form."""
        self.start_task(1, "src/app.py", "value = 2\n")
        self.ready(self.review(1))
        self.brief().unlink()
        broken = {
            "missing": {key: value for key, value in OVER_BUDGET.items() if key != "overages"},
            "keys": {**OVER_BUDGET, "overages": {}},
            "over_by": {**OVER_BUDGET,
                        "overages": {"aggregate_bytes": {"limit": 1, "over_by": 0}}},
        }
        for name, result in broken.items():
            with self.subTest(result=name):
                self.write_budget_shim(force_check(result))
                out = self.assert_gate_refused(
                    self.review(1), command="review", step="budget-check", gate="failed",
                    steps=["ledger", "review-package", "validate-report"])
                self.assertEqual(out["detail"], "budget check refused: invalid budget check")
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


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class ForecastCase(GateCase):
    """The fixture plan with a v3 forecast whose delivery base is the fixture's plan commit (D15)."""

    def setUp(self):
        super().setUp()
        self.forecast_base = self.delivery_base = self.repo_git("rev-parse", "HEAD")
        package = {"spec": "spec.md", "plan": "plan.md", "tasks": ["plan.tasks/task-1.md", "plan.tasks/task-2.md"]}
        paths = [package["spec"], package["plan"], *package["tasks"]]
        bound = lambda size: [{"boundary": "all", "added_lines": 40, "deleted_lines": 0,
                               "record_bytes": size, "support": None}]
        def record(rid, owner, path, change, horizon, size):
            row = {"id": rid, "owner": owner, "path": path, "change": change, "last_task": horizon,
                   "bounds": bound(size)}
            row["bounds"][0]["support"] = {"kind": "authored-cumulative/v1", "covers": [rid]}
            return row
        self.delivery = {"schema_version": 3, "kind": "review-feasibility-delivery",
            "delivery_base": self.forecast_base, "proposed_boundary": "all", "derived_from": None,
            "boundaries": [{"id": "all", "parent": None, "tasks": [1, 2], "acceptance": "Fixture delivery",
                "depends_on": [], "prerequisite": {"kind": "delivery-base"}, "process_package": package,
                "process_forecast_ids": [f"p{n}" for n in range(4)],
                "process_commit_subject_bytes": [64, 64, 64]}],
            "process_records": [record(f"p{n}", 0, path, "add" if path == "spec.md" else "modify", 2, 4096)
                                for n, path in enumerate(paths)],
            "actual_evidence": {"kind": "git-range-ownership/v1", "head": self.forecast_base,
                "tree": self.repo_git("rev-parse", self.forecast_base + "^{tree}"), "process_ranges": []}}
        self.tasks = [{"schema_version": 3, "kind": "review-feasibility-task", "task": {"id": n,
            "commit_subject_bytes": [64, 64], "actual_ranges": [],
            "records": [record(f"r{n}", n, path, change, n, 2048)]}}
            for n, path, change in ((1, "src/app.py", "modify"), (2, "notes.txt", "add"))]
        self.write("spec.md", "# Fixture spec\n")
        self.emit_forecast()
        self.repo_commit("forecast")

    def emit_forecast(self):
        text = (FIXTURES / "plan.md").read_text(encoding="utf-8")
        self.write("plan.md", text + "\n## Review feasibility delivery\n\n```json\n"
                   + canonical(self.delivery) + "\n```\n")
        for n, block in enumerate(self.tasks, 1):
            member = (FIXTURES / f"plan.tasks/task-{n}.md").read_text(encoding="utf-8")
            self.write(f"plan.tasks/task-{n}.md", member + "\n## Review feasibility task\n\n```json\n"
                       + canonical(block) + "\n```\n")

    def read_blocks(self):
        def block(path, heading):
            lines = (self.repo / path).read_text(encoding="utf-8").splitlines()
            return json.loads(lines[lines.index(heading) + 3])
        return (block("plan.md", "## Review feasibility delivery"),
                [block(f"plan.tasks/task-{n}.md", "## Review feasibility task") for n in (1, 2)])

    def record(self, task):
        return self.gate("record", self.plan, "--task", task)


class RecordTest(ForecastCase):
    def test_record_rewrites_the_forecast_from_the_ledger_and_git(self):
        base, head = self.start_task(1, "src/app.py", "value = 2\n")
        out = self.ready(self.record(1))
        self.assertEqual(out, {"command": "record", "outcome": "ready", "task": 1, "head_sha": head,
                               "paths": [str(self.plan), str(self.repo / "plan.tasks/task-1.md")],
                               "changed": True})
        delivery, tasks = self.read_blocks()
        self.assertEqual(tasks[0]["task"]["actual_ranges"], [{"base": base, "head": head}])
        self.assertEqual(delivery["actual_evidence"]["head"], head)
        self.assertEqual(delivery["actual_evidence"]["tree"], self.repo_git("rev-parse", head + "^{tree}"))
        self.assertEqual(delivery["actual_evidence"]["process_ranges"],
                         [{"base": self.forecast_base, "head": base, "boundaries": ["all"]}])
        self.assertIn(f"Task 1: recorded (head {head})", self.ledger_lines())
        recording = self.repo_commit("plan: record task 1 evidence")
        projected = subprocess.run([sys.executable, "-m", "agent_tools.review_feasibility", "project",
            "--plan", str(self.plan), "--base", self.forecast_base, "--head", recording,
            "--completed-through", "1"], cwd=self.repo, env=self.env, capture_output=True)
        self.assertEqual(projected.returncode, 0, projected.stderr)
        again = self.ready(self.record(1))
        self.assertEqual((again["head_sha"], again["changed"]), (head, False))
        self.assertEqual(self.ledger_lines().count(f"Task 1: recorded (head {head})"), 1)

    def test_a_later_task_commit_is_not_taken_for_the_recording(self):
        base, head = self.start_task(1, "src/app.py", "value = 2\n")
        self.ready(self.record(1))
        self.write("src/app.py", "value = 3\n")                      # a review fix over the recorded head
        self.repo_git("add", "src/app.py"); self.repo_git("commit", "-q", "-m", "review fix")
        out = self.assert_gate_refused(self.record(1), command="record", step="ledger", gate=None, steps=[])
        self.assertIn("changes more than its plan files", out["detail"])
        self.assertEqual(self.ledger_lines().count(f"Task 1: recorded (head {head})"), 1)

    def test_a_due_prerequisite_gets_the_recorded_identity(self):
        self.delivery["boundaries"][0]["process_commit_subject_bytes"] = [64] * 4
        child = {"id": "two", "parent": "all", "tasks": [2], "acceptance": "Second", "depends_on": ["one"],
                 "prerequisite": {"kind": "completed-tasks", "tasks": [1], "commit": None, "tree": None},
                 "process_package": {"spec": "two-spec.md", "plan": "two.md", "tasks": ["two.tasks/task-1.md"]},
                 "process_forecast_ids": ["q0", "q1", "q2"], "process_commit_subject_bytes": [64]}
        first = {**child, "id": "one", "tasks": [1], "depends_on": [], "prerequisite": {"kind": "delivery-base"},
                 "process_package": {"spec": "one-spec.md", "plan": "one.md", "tasks": ["one.tasks/task-1.md"]},
                 "process_forecast_ids": ["o0", "o1", "o2"]}
        self.delivery["boundaries"] += [first, child]
        for prefix, row in (("o", first), ("q", child)):
            for n, path in enumerate([row["process_package"]["spec"], row["process_package"]["plan"],
                                      *row["process_package"]["tasks"]]):
                self.delivery["process_records"].append({"id": f"{prefix}{n}", "owner": 0, "path": path,
                    "change": "add", "last_task": 2, "bounds": [{"boundary": row["id"], "added_lines": 1,
                    "deleted_lines": 0, "record_bytes": 512,
                    "support": {"kind": "authored-cumulative/v1", "covers": [f"{prefix}{n}"]}}]})
        for n, block in enumerate(self.tasks, 1):
            block["task"]["records"][0]["bounds"].append(
                {**block["task"]["records"][0]["bounds"][0], "boundary": "one" if n == 1 else "two"})
        self.emit_forecast(); self.repo_commit("children")
        _, head = self.start_task(1, "src/app.py", "value = 2\n")
        self.ready(self.record(1))
        delivery, _ = self.read_blocks()
        self.assertEqual(delivery["boundaries"][2]["prerequisite"],
                         {"kind": "completed-tasks", "tasks": [1], "commit": head,
                          "tree": self.repo_git("rev-parse", head + "^{tree}")})

    def test_record_refuses_each_unsafe_state(self):
        refused = lambda: self.assert_gate_refused(self.record(1), command="record", step=step, gate=None,
                                                   steps=steps)
        step, steps = "ledger", []
        refused()                                                     # task 1 never dispatched
        base = self.repo_git("rev-parse", "HEAD")
        self.append_ledger(f"Task 1: dispatched (base {base})")
        step, steps = "worktree", ["ledger"]
        refused()                                                     # no task commit: B == H
        self.write("src/app.py", "value = 2\n"); self.repo_commit("task 1")
        self.write("stray.txt", "x\n"); self.repo_git("add", "stray.txt")
        refused()                                                     # extra dirty tracked path
        self.repo_git("rm", "-q", "--cached", "stray.txt"); (self.repo / "stray.txt").unlink()
        member = self.repo / "plan.tasks/task-1.md"; text = member.read_text(encoding="utf-8")
        self.write("plan.tasks/task-1.md", text.replace('"record_bytes":2048', '"record_bytes":1024'))
        self.assertNotEqual(member.read_text(encoding="utf-8"), text)
        self.repo_commit("task 1 lowers its bound")
        step, steps = "record", ["ledger", "worktree"]
        refused()                                                     # a task commit edited the forecast
        self.append_ledger(f"Task 1: recorded (head {base})")
        step, steps = "ledger", []
        refused()                                                     # recorded head differs from HEAD's chain

    def test_record_refuses_to_discard_an_uncommitted_plan_edit(self):
        self.start_task(1, "src/app.py", "value = 2\n")
        member = self.repo / "plan.tasks/task-1.md"
        edited = member.read_bytes() + b"\nReview note: keep this.\n"
        member.write_bytes(edited)
        out = self.assert_gate_refused(self.record(1), command="record", step="record", gate=None,
                                       steps=["ledger", "worktree"])
        self.assertIn("plan.tasks/task-1.md", out["detail"])
        self.assertEqual(member.read_bytes(), edited)
        self.assertFalse(any(line.startswith("Task 1: recorded") for line in self.ledger_lines()))


NEXT_STEPS = ["ledger", "mark-progress", "review-package", "validate-report", "budget-check",
              "metrics-match", "projection", "task-brief", "prepare-brief", "register-worker"]
# A re-dispatch reuses the ledger's projection, so it runs no `projection` step.
REDISPATCH_STEPS = [step for step in NEXT_STEPS if step != "projection"]

# A `workflow-state` shim that refuses `release-worker` and passes every other subcommand on.
FAIL_RELEASE = ('#!/bin/sh\ncase "$1" in\n  release-worker) echo "release refused" >&2; exit 1 ;;\n'
                'esac\nexec {python} {workflow} "$@"\n')


class NextTest(ForecastCase):
    def brief(self, task=1):
        return self.workspace / f"task-{task}-implementer-dispatch.md"

    def next(self, *args, skill=SKILL):
        return self.gate("next", self.plan, "--skill-dir", skill,
                         "--standards", PROJECT_STANDARDS, *args)

    def first(self, *args, skill=SKILL):
        """The run's first call: it carries the delivery base."""
        return self.next("--task", 1, "--delivery-base", self.delivery_base, *args, skill=skill)

    def head(self):
        return self.repo_git("rev-parse", "HEAD")

    def delivery_gate(self, head):
        """(manifest root, metrics, ledger line) of the cumulative gate at `head`."""
        root = self.package_root(self.delivery_base, head)
        metrics = self.budget_metrics("review-package", self.repo / root)
        return root, metrics, (
            f"Delivery gate: {self.delivery_base}..{head} root_bytes={metrics['root_bytes']} "
            f"total_bytes={metrics['total_bytes']} file_count={metrics['file_count']} "
            f"largest_member_bytes={metrics['largest_member_bytes']}")

    def workers(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))["workers"]

    def finish(self, task, relative, text):
        """Commit task `task`'s change and its recording: (task head, recording head)."""
        head = self.start_task(task, relative, text)[1]
        self.ready(self.record(task))
        return head, self.repo_commit(f"plan: record task {task} evidence")

    def projected(self, head, through):
        """The independent `project` run over `head`: its metrics."""
        done = subprocess.run([sys.executable, "-m", "agent_tools.review_feasibility", "project",
            "--plan", str(self.plan), "--base", self.forecast_base, "--head", head,
            "--completed-through", str(through)], cwd=self.repo, env=self.env, capture_output=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)["metrics"]

    def test_the_first_call_records_both_bases_and_renders_the_implementer_brief(self):
        head = self.head()
        context = self.root / "context.md"
        context.write_text("Fits after setup.\nUse `value`.\n\n", encoding="utf-8")
        out = self.ready(self.first("--context-file", context))
        root, metrics, line = self.delivery_gate(head)
        through = self.projected(head, 0)
        self.assertEqual(out, {
            "command": "next", "outcome": "ready", "completed": None, "task": 1,
            "brief_path": str(self.brief()),
            "report_path": str(self.workspace / "task-1-report.md"),
            "base_sha": head, "worker_id": None, "mark_progress": "skipped",
            "delivery": {"base_sha": self.delivery_base, "head_sha": head,
                         "manifest_root": root, "metrics": metrics},
            "projection": {"completed_through": 0, "head_sha": head, "metrics": through},
            "standards": [str(self.bar), str(PROJECT_STANDARDS / "python-rules.md")]})
        self.assertEqual(self.ledger_lines()[1:], [
            f"Delivery base: {self.delivery_base}", line,
            f"Projection gate: {self.delivery_base}..{head} through 0 root_bytes={through['root_bytes']} "
            f"total_bytes={through['total_bytes']} file_count={through['file_count']} "
            f"largest_member_bytes={through['largest_member_bytes']}",
            f"Task 1: dispatched (base {head})"])
        self.assertEqual(self.brief().read_bytes(), self.golden("golden-implementer-brief.md"))
        self.assertEqual((self.workspace / "task-1-brief.md").read_bytes(),
                         (self.repo / "plan.tasks/task-1.md").read_bytes())

    def test_a_repeated_call_writes_no_second_ledger_line(self):
        first = self.first()
        self.ready(first)
        lines = self.ledger_lines()
        again = self.next("--task", 1)  # the ledger holds the delivery base now
        self.assertEqual((again.returncode, again.stdout), (0, first.stdout))
        self.assertEqual(self.ledger_lines(), lines)
        # No context: the [CONTEXT] line and the empty line after it are gone.
        self.assertIn("task-1-report.md\n\nPlan: ", self.brief().read_text(encoding="utf-8"))

    def test_the_delivery_base_must_be_known_and_must_not_change(self):
        header = self.ledger_lines()
        self.assert_gate_refused(self.next("--task", 1), command="next", step="ledger",
                                 gate=None, steps=[])
        self.assertEqual(self.ledger_lines(), header)
        self.ready(self.first())
        lines = self.ledger_lines()
        self.assert_gate_refused(self.next("--task", 1, "--delivery-base", self.head()),
                                 command="next", step="ledger", gate=None, steps=[])
        self.assertEqual(self.ledger_lines(), lines)

    def test_completing_a_task_appends_its_line_once(self):
        self.ready(self.first())
        base = self.head()
        task_head, head = self.finish(1, "src/app.py", "value = 2\n")
        out = self.ready(self.next("--completed", 1, "--task", 2))
        self.assertEqual(self.ledger_lines()[-4:-2], [
            f"Task 1: complete (commits {base[:7]}..{task_head[:7]}, review clean)",
            self.delivery_gate(head)[2]])
        self.assertEqual(self.ledger_lines()[-1], f"Task 2: dispatched (base {head})")
        self.assertEqual((out["completed"], out["task"], out["base_sha"]), (1, 2, head))
        self.assertEqual(out["standards"], [str(self.bar)])  # Task 2's row names notes.txt only
        lines = self.ledger_lines()
        self.ready(self.next("--completed", 1, "--task", 2))
        self.assertEqual(self.ledger_lines(), lines)

    def test_parked_findings_are_counted_and_the_last_call_renders_nothing(self):
        self.ready(self.first())
        self.finish(1, "src/app.py", "value = 2\n")
        self.ready(self.next("--completed", 1, "--task", 2))
        base = self.head()
        task_head, head = self.finish(2, "notes.txt", "note\n")
        out = self.ready(self.next("--completed", 2, "--parked", 3))
        self.assertEqual(self.ledger_lines()[-2:], [
            f"Task 2: complete (commits {base[:7]}..{task_head[:7]}, 3 parked)",
            self.delivery_gate(head)[2]])
        self.assertEqual([out[key] for key in ("task", "brief_path", "report_path", "base_sha",
                                               "worker_id", "projection")], [None] * 6)
        self.assertEqual((out["completed"], out["standards"]), (2, []))

    def test_completing_an_undispatched_task_is_refused_before_any_write(self):
        header = self.ledger_lines()
        self.assert_gate_refused(
            self.next("--completed", 2, "--delivery-base", self.delivery_base),
            command="next", step="ledger", gate=None, steps=[])
        self.assertEqual(self.ledger_lines(), header)

    def test_an_over_budget_delivery_stops_before_the_next_dispatch(self):
        self.ready(self.first())
        self.finish(1, "src/app.py", "X" * 70_000 + "\n")
        out = self.assert_gate_refused(
            self.next("--completed", 1, "--task", 2), command="next", step="validate-report",
            gate="decompose_required",
            steps=["ledger", "evidence", "ledger-complete", "review-package"], code=3)
        self.assertEqual(out["report"]["state"], "decompose_required")
        self.assertTrue(self.ledger_lines()[-1].startswith("Task 1: complete ("))
        self.assertFalse(self.brief(2).exists())

    def test_a_task_without_an_index_row_is_refused_at_task_brief(self):
        self.ready(self.first())
        self.finish(1, "src/app.py", "value = 2\n")
        self.ready(self.next("--completed", 1, "--task", 2))
        self.finish(2, "notes.txt", "note\n")
        self.assert_gate_refused(
            self.next("--completed", 2, "--task", 3), command="next", step="task-brief", gate=None,
            steps=["ledger", "evidence", "ledger-complete", *NEXT_STEPS[2:7]])
        self.assertFalse(any(line.startswith("Task 3") for line in self.ledger_lines()))

    def test_a_brief_that_cannot_be_prepared_is_refused_before_a_worker_is_registered(self):
        self.launch()
        drifted = self.root / "drifted"
        shutil.copytree(SKILL, drifted)
        template = drifted / "implementer-prompt.md"
        template.write_text(template.read_text(encoding="utf-8").replace(
            "    End.\n", "    End [SURPRISE].\n"), encoding="utf-8")
        cases = {"template drift": (lambda: self.first(*self.identity(), skill=drifted),
                                    NEXT_STEPS[:8]),
                 "an unreadable context file": (lambda: self.first(
                     "--context-file", self.root / "absent.md", *self.identity()),
                     REDISPATCH_STEPS[:7])}  # the first case recorded the dispatch
        for name, (call, steps) in cases.items():
            with self.subTest(case=name):
                self.assert_gate_refused(call(), command="next", step="prepare-brief", gate=None,
                                         steps=steps)
        self.assertEqual(self.workers(), [])
        self.assertFalse(self.brief().exists())

    def test_under_an_identity_the_worker_is_registered_and_named_in_the_brief(self):
        self.launch()
        out = self.ready(self.first(*self.identity()))
        self.assertEqual((out["worker_id"], out["mark_progress"]), ("14:1:1:w1", "baseline"))
        self.assertTrue(self.check_worker("14:1:1:w1")["live"])
        block = sdd_brief.worker_block(str(self.root), self.run_id, "14:1:1:w1")
        self.assertIn(f"## Worker\n\n{block}\n\nEnd.\n", self.brief().read_text(encoding="utf-8"))
        self.run_tool("workflow-state", "release-worker", "--repo-root", str(self.root),
                      "--run-id", self.run_id, "--worker-id", "14:1:1:w1", "--event", "returned")
        again = self.ready(self.next("--task", 1, *self.identity()))  # a re-dispatch of the task
        self.assertEqual((again["worker_id"], again["base_sha"], again["mark_progress"]),
                         ("14:1:1:w2", out["base_sha"], "unchanged"))

    def test_a_repeated_dispatch_is_refused_while_the_earlier_worker_is_live(self):
        self.launch()
        self.ready(self.first(*self.identity()))
        brief = self.brief().read_bytes()
        out = self.assert_gate_refused(self.next("--task", 1, *self.identity()), command="next",
                                       step="register-worker", gate=None,
                                       steps=REDISPATCH_STEPS[:8])
        self.assertEqual(out["detail"], "worker 14:1:1:w1 from an earlier dispatch of task 1 is "
                                        "still registered: release it before calling next again")
        self.assertEqual([(worker["worker_id"], worker["release_event"])
                          for worker in self.workers()], [("14:1:1:w1", None)])
        self.assertEqual(self.brief().read_bytes(), brief)

    def test_a_refused_progress_mark_does_not_stop_the_call(self):
        self.launch(worktree=self.root / "gone")
        out = self.ready(self.first(*self.identity()))
        self.assertEqual((out["mark_progress"], out["worker_id"]), ("refused", "14:1:1:w1"))

    def test_a_refused_registration_leaves_no_brief(self):
        self.launch()
        head = self.head()
        self.assert_gate_refused(self.first(*self.identity("14:1:9")), command="next",
                                 step="register-worker", gate=None, steps=NEXT_STEPS[:9])
        self.assertFalse(self.brief().exists())
        self.assertEqual(self.workers(), [])
        self.assertEqual(self.ledger_lines()[-1], f"Task 1: dispatched (base {head})")

    def test_a_failed_write_releases_the_worker_it_registered(self):
        self.launch()
        (self.brief() / "occupied").mkdir(parents=True)  # a rename cannot replace this directory
        self.assert_gate_refused(self.first(*self.identity()), command="next", step="write-brief",
                                 gate=None, steps=NEXT_STEPS)
        self.assertEqual([(worker["worker_id"], worker["release_event"])
                          for worker in self.workers()], [("14:1:1:w1", "stopped")])

    def test_a_failed_write_names_the_worker_it_could_not_release(self):
        self.launch()
        (self.brief() / "occupied").mkdir(parents=True)
        self.write_executable("workflow-state", FAIL_RELEASE.format(
            python=shlex.quote(sys.executable), workflow=shlex.quote(str(WORKFLOW))))
        out = self.assert_gate_refused(self.first(*self.identity()), command="next",
                                       step="write-brief", gate=None, steps=NEXT_STEPS)
        self.assertIn("14:1:1:w1", out["detail"])
        self.assertIn("release-worker", out["detail"])
        self.assertEqual([(worker["worker_id"], worker["release_event"])
                          for worker in self.workers()], [("14:1:1:w1", None)])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores file modes")
    def test_an_unwritable_ledger_is_refused_at_the_step_that_writes_to_it(self):
        def set_ledger_mode(mode):
            self.ledger.chmod(mode)

        self.addCleanup(set_ledger_mode, 0o644)
        set_ledger_mode(0o444)
        self.assert_gate_refused(self.first(), command="next", step="ledger", gate=None, steps=[])
        set_ledger_mode(0o644)
        self.ready(self.first())
        self.finish(1, "src/app.py", "value = 2\n")
        set_ledger_mode(0o444)
        self.assert_gate_refused(self.next("--completed", 1, "--task", 2), command="next",
                                 step="ledger-complete", gate=None, steps=["ledger", "evidence"])
        # The cumulative gate could not be recorded, so it has not passed: `failed`, not listed.
        self.assert_gate_refused(
            self.next("--task", 1), command="next", step="metrics-match", gate="failed",
            steps=["ledger", "review-package", "validate-report", "budget-check"])

    def test_an_invalid_next_invocation_prints_one_stderr_line(self):
        base = ("next", self.plan, "--skill-dir", SKILL)
        cases = {
            "neither --completed nor --task": base,
            "--parked without --completed": (*base, "--task", "1", "--parked", "1"),
            "--context-file without --task": (*base, "--completed", "1", "--context-file", "c.md"),
            "a short delivery base": (*base, "--task", "1", "--delivery-base", "abc1234"),
            "a worker id": (*base, "--task", "1", *self.identity(), "--worker-id", "14:1:1:w1"),
            "the stdin flag the design dropped": (*base, "--task", "1", "--context-stdin"),
        }
        for name, argv in cases.items():
            with self.subTest(case=name):
                done = self.gate(*argv)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (2, "", INVALID))


SUMMARY_KEYS = {"artifact_policy_sha256", "base", "completed_through", "forecast_sha256", "head", "kind",
                "metrics", "packing_policy_sha256", "plan", "plan_package_sha256", "recommended_boundary",
                "schema_version", "state", "violations"}
GATE_STEPS = ["ledger", "review-package", "validate-report", "budget-check", "metrics-match"]


class NextProjectionTest(ForecastCase):
    def next(self, *args):
        return self.gate("next", self.plan, "--skill-dir", SKILL, "--standards", PROJECT_STANDARDS, *args)

    def first(self, *args):
        return self.next("--task", 1, "--delivery-base", self.forecast_base, *args)

    def workers(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))["workers"]

    def complete(self, task, path, text):
        """Run task `task` to a committed recording; return (task head, recording head)."""
        _, head = self.start_task(task, path, text)
        self.ready(self.record(task))
        return head, self.repo_commit(f"plan: record task {task} evidence")

    def lines_matching(self, prefix):
        return [line for line in self.ledger_lines() if line.startswith(prefix)]

    def test_the_initial_projection_runs_after_the_actual_gate_and_before_dispatch(self):
        head = self.repo_git("rev-parse", "HEAD")
        out = self.ready(self.first())
        self.assertEqual((out["projection"]["completed_through"], out["projection"]["head_sha"]), (0, head))
        lines = self.ledger_lines()
        gate = next(i for i, l in enumerate(lines) if l.startswith("Delivery gate:"))
        projected = next(i for i, l in enumerate(lines) if l.startswith("Projection gate:"))
        dispatched = lines.index(f"Task 1: dispatched (base {head})")
        self.assertLess(gate, projected); self.assertLess(projected, dispatched)
        self.assertTrue(lines[projected].startswith(
            f"Projection gate: {self.forecast_base}..{head} through 0 root_bytes="))
        self.assertTrue((self.workspace / f"projection-{head[:7]}-0.json").is_file())

    def test_a_projected_overflow_stops_with_a_confirmable_summary(self):
        self.delivery["boundaries"][0]["process_commit_subject_bytes"] = [120] * 100
        self.emit_forecast(); head = self.repo_commit("oversized forecast")
        done = self.first()
        out = self.assert_gate_refused(done, command="next", step="projection", gate="decompose_required",
                                       steps=GATE_STEPS, code=3)
        self.assertEqual(set(out["report"]), SUMMARY_KEYS)
        self.assertEqual((out["report"]["state"], out["report"]["head"], out["report"]["completed_through"]),
                         ("decompose_required", head, 0))
        self.assertEqual(self.lines_matching("Task 1: dispatched"), [])
        self.assertFalse((self.workspace / "task-1-implementer-dispatch.md").exists())
        raw = json.dumps(out["report"]).encode()
        confirmed = subprocess.run([sys.executable, "-m", "agent_tools.review_feasibility", "confirm",
            "--plan", str(self.plan), "--base", self.forecast_base, "--input", "-"], input=raw,
            cwd=self.repo, env=self.env, capture_output=True)
        self.assertEqual(confirmed.returncode, 3, confirmed.stderr)

    def test_an_invalid_projection_fails_before_dispatch_and_registers_nothing(self):
        self.launch()
        self.delivery["delivery_base"] = "0" * 40
        self.emit_forecast(); self.repo_commit("wrong forecast base")
        done = self.first(*self.identity())
        self.assert_gate_refused(done, command="next", step="projection", gate="failed",
                                 steps=["ledger", "mark-progress", *GATE_STEPS[1:]])
        self.assertEqual(self.lines_matching("Task 1: dispatched"), [])
        self.assertEqual(self.workers(), [])

    def test_post_task_order_needs_the_exact_recording_commit(self):
        self.ready(self.first())
        base = self.repo_git("rev-parse", "HEAD")
        _, task_head = self.start_task(1, "src/app.py", "value = 2\n")
        self.assert_gate_refused(self.next("--completed", 1, "--task", 2), command="next", step="ledger",
                                 gate=None, steps=[])                       # not recorded
        self.ready(self.record(1))
        self.assert_gate_refused(self.next("--completed", 1, "--task", 2), command="next", step="evidence",
                                 gate="failed", steps=["ledger"])                   # not committed
        self.write("notes.txt", "smuggled\n"); recording = self.repo_commit("plan: record task 1 evidence")
        self.assert_gate_refused(self.next("--completed", 1, "--task", 2), command="next", step="evidence",
                                 gate="failed", steps=["ledger"])                   # extra path
        self.assertEqual(self.lines_matching("Task 1: complete"), [])           # D19: no unverified marker
        self.assert_gate_refused(self.next("--task", 2), command="next", step="ledger", gate=None, steps=[])
        self.repo_git("reset", "-q", "--hard", task_head)
        self.ready(self.record(1)); recording = self.repo_commit("plan: record task 1 evidence")
        out = self.ready(self.next("--completed", 1, "--task", 2))
        self.assertEqual(out["projection"]["head_sha"], recording)
        self.assertIn(f"Task 1: complete (commits {base[:7]}..{task_head[:7]}, review clean)",
                      self.ledger_lines())
        self.assertTrue(self.lines_matching(f"Projection gate: {self.forecast_base}..{recording} through 1 "))
        again = self.ready(self.next("--task", 2))                       # re-dispatch reuses the line
        self.assertEqual(len(self.lines_matching("Projection gate:")), 2)
        self.assertEqual(again["projection"]["head_sha"], recording)

    def test_a_completion_marker_never_authorizes_an_unverified_head(self):
        self.ready(self.first())
        self.complete(1, "src/app.py", "value = 2\n")
        self.ready(self.next("--completed", 1))
        member = self.repo / "plan.tasks/task-2.md"; text = member.read_text(encoding="utf-8")
        self.write("plan.tasks/task-2.md", text.replace('"record_bytes":2048', '"record_bytes":1024'))
        self.assertNotEqual(member.read_text(encoding="utf-8"), text)
        self.repo_commit("plan: lower task 2 bound")                            # a lowered future bound
        self.assert_gate_refused(self.next("--task", 2), command="next", step="evidence", gate="failed",
                                 steps=["ledger"])
        self.assertEqual(len(self.lines_matching("Projection gate:")), 1)
        self.assertEqual(self.lines_matching("Task 2: dispatched"), [])

    def test_an_actual_overflow_refuses_before_any_projection(self):
        self.ready(self.first())
        self.complete(1, "src/app.py", "".join(f"value_{n} = {n}\n" for n in range(8000)))
        out = self.assert_gate_refused(self.next("--completed", 1, "--task", 2), command="next",
            step="validate-report", gate="decompose_required",
            steps=["ledger", "evidence", "ledger-complete", "review-package"], code=3)
        self.assertEqual(out["report"]["state"], "decompose_required")
        self.assertEqual(len(self.lines_matching("Projection gate:")), 1)
        self.assertEqual(self.lines_matching("Task 2: dispatched"), [])

    def test_completing_the_last_task_runs_no_projection(self):
        self.ready(self.first())
        self.complete(1, "src/app.py", "value = 2\n")
        self.ready(self.next("--completed", 1, "--task", 2))
        self.complete(2, "notes.txt", "notes\n")
        out = self.ready(self.next("--completed", 2))
        self.assertIsNone(out["projection"])
        self.assertEqual(len(self.lines_matching("Projection gate:")), 2)


if __name__ == "__main__":
    unittest.main()
