# Task 3: `sdd-gate review` and the golden reviewer brief

**Files:**
- Create: `python/agent_tools/sdd_gate.py`
- Create: `tests/test_sdd_gate.py`
- Create: `tests/fixtures/sdd-gate/plan.md`, `tests/fixtures/sdd-gate/plan.tasks/task-1.md`, `tests/fixtures/sdd-gate/plan.tasks/task-2.md`
- Create: `tests/fixtures/sdd-gate/skill/task-reviewer-prompt.md`, `tests/fixtures/sdd-gate/golden-reviewer-brief.md`
- Create: `tests/fixtures/sdd-gate/standards-global/the-bar.md`, `tests/fixtures/sdd-gate/standards-project/README.md`, `tests/fixtures/sdd-gate/standards-project/python-rules.md`
- Modify: `lib/agent-tools.nix` (one command-table row)
- Modify: `tests/test_agent_tools_launchers.py` (`LAUNCHER_FLOOR`)
- Modify: `justfile` (one line in `agent-workflow-tests`)
- Modify: `python/README.md` (new ``## `sdd-gate` `` section)
- Test: `tests/test_sdd_gate.py`

**Interfaces:**
- Consumes, from Tasks 1–2, in `agent_tools.sdd_brief`: `BriefError`; `REVIEWER_TEMPLATE`, `REVIEWER_TOKENS`; `render(template_text: str, tokens: frozenset[str], values: Mapping[str, str]) -> str`; `plan_section(plan_text: str, heading: str) -> str`; `select_standards(global_dir: Path, entries: Sequence[Path], touched: Sequence[str]) -> list[Path]`; `standards_value(documents: Sequence[Path]) -> str`.
- Consumes, existing: `agent_tools.siblings.sibling_argv(module: str) -> list[str]`; `agent_tools.review_budget.describe(kind: str) -> BudgetAuthority`, whose `check(kind, root) -> BudgetCheck` (`.status`, `.metrics`) and `validate_report(raw: bytes, boundary: str) -> bytes` raise `BudgetError`; `reject_duplicate_keys` and `reject_nonfinite_literal` from `agent_tools.canonical`.
- Produces, in `agent_tools.sdd_gate` (Task 4 imports nothing but extends this module, so these names are its contract):
  - `class InvocationError(Exception)`; `class Refusal(Exception)` built as `Refusal(step: str, detail: str, *, gate: str | None = None, report: dict | None = None)` with those four attributes.
  - `@dataclass(frozen=True) class Ledger` — `workspace: Path`, `path: Path` (`workspace / "progress.md"`), `lines: tuple[str, ...]`, `top: Path` (the checkout's top level).
  - `open_ledger(plan: Path) -> Ledger`; `recorded_sha(ledger: Ledger, pattern: str) -> str | None` — the one distinct group-1 value among ledger lines that match `pattern` in full, `None` when no line matches, `Refusal("ledger", …)` when two different values are recorded; `task_base(ledger: Ledger, task: int) -> str` — `recorded_sha` for the task's `dispatched` line, refused when it is `None`; `append_line(ledger: Ledger, line: str) -> None` — one append of `line` and a newline, preceded by a newline when the file does not end with one.
  - `pinned_head() -> str` — the full `git rev-parse HEAD` of the current checkout.
  - `@dataclass(frozen=True) class Package` — `manifest_root: str`, `root: Path`, `metrics: dict[str, int]`, `authority: BudgetAuthority`.
  - `package_gate(plan: Path, ledger: Ledger, base: str, head: str, done: list[str]) -> Package` — steps `review-package` to `metrics-match`.
  - `workflow_state(step: str, *argv: str) -> dict` — runs `workflow-state <argv>` by name; a non-zero exit, a command that cannot start or a reply that is not one JSON object raises `Refusal(step, …)`.
  - `shared_values(plan: Path, ledger: Ledger, task: int, authority: BudgetAuthority, documents: Sequence[Path]) -> dict[str, str]` — the values of the ten tokens both templates share except `[GLOBAL_CONSTRAINTS]`.
  - `write_atomic(path: Path, data: bytes) -> None`.
  - `review(args: argparse.Namespace, done: list[str]) -> dict`; `main(argv: Sequence[str] | None = None) -> int`.
- Produces: the installed command `sdd-gate` (one row in `lib/agent-tools.nix`).

**Invariants (spec "`sdd-gate review`: steps in order", "Output and exit codes", "Reusing a package"; D1–D5, D8, D10, D12):**
- Steps run in the order `ledger`, `release-worker`, `review-package`, `validate-report`, `budget-check`, `metrics-match`, `render-brief`; the first that fails is the refusal's `step`, and `completed_steps` lists the steps that ran and passed, in order. Without a lifecycle identity `release-worker` does not run and is not listed.
- `gate` is `decompose_required` only when `validate-report` saw a validated `decompose_required` report, `failed` for every other refusal of `review-package` to `metrics-match`, and `null` otherwise. `report` is the validated report object exactly when `gate` is `decompose_required`.
- Stdout is one compact JSON object and one newline, keys in the order the spec's examples show; an invalid invocation prints nothing on stdout.
- No brief file exists after a refusal unless an earlier call wrote it.
- The command never deletes or overwrites a review package. An existing root is reused only when its manifest's `range` is exactly `{"base": <base40>, "head": <head40>}` and the report saved beside it exists.
- The command never resolves the project, reads the environment only through `Path.home()`, and reads Git only from the current checkout.
- `python/agent_tools/review_*.py`, `artifact_budget.py` and `workflow-state.py` are not edited.

- [ ] **Step 1: Create the fixtures**

Create each file with exactly this content and one final newline. They are fixtures written for this test; none is a copy of a shipped document (D9).

`tests/fixtures/sdd-gate/plan.md`:

````markdown
# Fixture plan

**Goal:** exercise sdd-gate.

## Global Constraints

- Python 3.11 standard library only.
- Paths are repository-relative.

## Test seams

- The command, run from source.

## Task index

Task 1 — Change the value — `src/app.py` — full — [task-1.md](plan.tasks/task-1.md)
Task 2 — Write the notes — `notes.txt` — low-risk — [task-2.md](plan.tasks/task-2.md)
````

`tests/fixtures/sdd-gate/plan.tasks/task-1.md`:

````markdown
# Task 1: Change the value

Set `value` to 2 in `src/app.py`.
````

`tests/fixtures/sdd-gate/plan.tasks/task-2.md`:

````markdown
# Task 2: Write the notes

Create `notes.txt`.
````

`tests/fixtures/sdd-gate/standards-global/the-bar.md`:

````markdown
# Fixture bar

Keep modules deep.
````

`tests/fixtures/sdd-gate/standards-project/README.md`:

````markdown
# Fixture project standards

| Shard | governs | Gist |
|---|---|---|
| [python-rules.md](python-rules.md) | `src/**` | Fixture rules. |
````

`tests/fixtures/sdd-gate/standards-project/python-rules.md`:

````markdown
# Fixture Python rules

Name the unit under test.
````

`tests/fixtures/sdd-gate/skill/task-reviewer-prompt.md` (the last prompt line is indented by six spaces, so it renders with two):

````markdown
# Fixture reviewer template

Text outside the fence is never rendered: [NOT_A_SLOT].

```
Subagent (fixture):
  description: "Review Task N"
  prompt: |
    Review one task.

    Brief: [BRIEF_FILE]
    Report: [REPORT_FILE]
    Plan: [PLAN_ROOT] ([PLAN_ROOT_BYTES], [PLAN_TOTAL_BYTES], [PLAN_FILE_COUNT], [PLAN_LARGEST_MEMBER_BYTES])

    Constraints:
    [GLOBAL_CONSTRAINTS]

    Range: [BASE_SHA]..[HEAD_SHA]
    Manifest: [MANIFEST_ROOT] ([ROOT_BYTES], [TOTAL_BYTES], [FILE_COUNT], [LARGEST_MEMBER_BYTES])

    ## Standards

    [STANDARDS]

    Stacks: [STACKS_DIR]

      Verdict: [Approved | Needs fixes]
```
````

`tests/fixtures/sdd-gate/golden-reviewer-brief.md` — assembled by hand from the files above: the template's prompt body with each token replaced by its value. A `@@NAME@@` slot stands for a value that differs per run (a temporary path, a commit, a measured metric); the test fills the slots from its own observations (D14):

````markdown
Review one task.

Brief: @@WORKSPACE@@/task-1-brief.md
Report: @@WORKSPACE@@/task-1-report.md
Plan: @@PLAN_ROOT@@ (@@PLAN_ROOT_BYTES@@, @@PLAN_TOTAL_BYTES@@, @@PLAN_FILE_COUNT@@, @@PLAN_LARGEST_MEMBER_BYTES@@)

Constraints:
- Python 3.11 standard library only.
- Paths are repository-relative.

Range: @@BASE_SHA@@..@@HEAD_SHA@@
Manifest: @@MANIFEST_ROOT@@ (@@ROOT_BYTES@@, @@TOTAL_BYTES@@, @@FILE_COUNT@@, @@LARGEST_MEMBER_BYTES@@)

## Standards

Source: @@HOME@@/.agents/standards/the-bar.md

# Fixture bar

Keep modules deep.

Source: @@STANDARDS@@/python-rules.md

# Fixture Python rules

Name the unit under test.

Stacks: @@HOME@@/.agents/standards/stacks

  Verdict: [Approved | Needs fixes]
````

- [ ] **Step 2: Write the failing test**

Create `tests/test_sdd_gate.py`:

````python
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
````

The harness is loaded through `importlib` exactly as `tests/test_launch_commit.py` loads it; that is test code, and rule 3's ban binds `python/`.

- [ ] **Step 3: Run the test and watch it fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_sdd_gate.py`
Expected: 11 tests, every one failing or erroring because the command does not exist: the child's stderr reads `No module named agent_tools.sdd_gate`, so return codes are 1 where 0, 2 or 3 is expected.

- [ ] **Step 4: Write `python/agent_tools/sdd_gate.py` (the `review` subcommand)**

A thin command (rule 2): `main` parses, calls `review`, prints, maps to an exit code. Everything else is the importable functions under **Interfaces**. Decisions the code must embody:

*Parsing.* One `argparse` parser with `prog="sdd-gate"` and a required subcommand; this task adds `review` only. Its `error` method raises `InvocationError` instead of exiting; `--help` keeps argparse's behaviour (usage on stdout, exit 0), which is what `tests/test_agent_tools_launchers.py` expects of every launcher (D12). `review` takes the positional `PLAN_FILE`, required `--skill-dir` and `--task`, repeatable `--standards`, and optional `--repo-root`, `--run-id`, `--action-id`, `--worker-id`. `--task` must match `[1-9][0-9]*`. After parsing: the three identity flags are all present or all absent; `--worker-id` is present exactly when the identity is. Any violation, and any argparse error, is an invalid invocation: `sdd-gate: invalid invocation` and a newline on stderr, nothing on stdout, exit 2.

*Paths.* `plan = Path(os.path.abspath(PLAN_FILE))`. Each `--standards` value becomes `Path(os.path.abspath(value))`. The global standards directory is `Path.home() / ".agents/standards"`.

*Step `ledger`* (`open_ledger`, `task_base`). Run `sdd-workspace <plan>` by name; its stdout, stripped, is the workspace. Read `progress.md` there as UTF-8. The first line must match `# SDD ledger — plan: (.+)` in full; the named path, taken relative to `git rev-parse --show-toplevel` when it is not absolute, must have the same `os.path.realpath` as `plan`. The task base is the one distinct SHA among lines matching `Task <N>: dispatched \(base ([0-9a-f]{40})\)` in full. A workspace that cannot be resolved, a missing or unreadable ledger, another header, no `dispatched` line or two different bases for the task: `Refusal("ledger", …)`.

*Step `release-worker`.* Only under an identity: `workflow_state("release-worker", "release-worker", "--repo-root", R, "--run-id", I, "--worker-id", W, "--event", "returned")`.

*Steps `review-package` to `metrics-match`* (`package_gate`). `head = pinned_head()` is taken once, before this step. The default root is `ledger.workspace / f"review-{base[:7]}..{head[:7]}.json"` and the saved report is `root.with_name(root.stem + ".report.json")`.
1. `review-package`. When the root does not exist: run `[*sibling_argv("review_package"), str(plan), base, head]`, capturing stdout as bytes; an exit other than 0 or 3 is `Refusal("review-package", …, gate="failed")`. When it exists: load the manifest strictly; refuse with `gate="failed"` unless it is an object whose `range` equals `{"base": base, "head": head}` and the saved report can be read; the report bytes are the saved file's, and there is no producer exit.
2. `validate-report`. `authority = describe("review-package")`, then `authority.validate_report(raw, "producer")`, then a strict load of the validated bytes. Refuse with `gate="failed"` on `BudgetError`, on a state other than `complete` or `decompose_required`, when `artifact.path` (relative to the checkout top when not absolute) is not the default root by `os.path.realpath`, or when a fresh producer's exit is not 0 for `complete` and 3 for `decompose_required`. After a fresh build that passed these checks, save the validated bytes to the saved-report path with `write_atomic`, for either state (D12). Then a `decompose_required` state is `Refusal("validate-report", …, gate="decompose_required", report=<the object>)`.
3. `budget-check`. `authority.check("review-package", root)`; `BudgetError` or a status other than `within_budget` is `gate="failed"`.
4. `metrics-match`. `dict(check.metrics)` must equal the report's `artifact.metrics`; otherwise `gate="failed"`.
`Package.manifest_root` is the report's `artifact.path` exactly as the producer printed it.

*Step `render-brief`.* The touched paths are `git diff --name-only --no-renames -z <base> <head>` split on NUL, so a rename counts as a deletion and an addition. `documents = select_standards(global_dir, standards_entries, touched)`. `shared_values` runs `authority.check("implementation-plan", plan)` (a status other than `within_budget` is refused) and returns `[BRIEF_FILE]` and `[REPORT_FILE]` (`task-<N>-brief.md` and `task-<N>-report.md` in the workspace), `[PLAN_ROOT]` (`str(plan)`), the four `[PLAN_…]` metrics as decimal strings, `[STANDARDS]` (`standards_value(documents)`) and `[STACKS_DIR]` (`str(global_dir / "stacks")`). `review` adds `[GLOBAL_CONSTRAINTS]` (`plan_section(plan_text, "## Global Constraints")`), `[BASE_SHA]`, `[HEAD_SHA]`, `[MANIFEST_ROOT]` and the package's four metrics. The template is `<skill-dir>/task-reviewer-prompt.md`, read as UTF-8. Write `render(…)` encoded as UTF-8 to `task-<N>-review-dispatch.md` in the workspace with `write_atomic`. `BriefError`, `BudgetError`, `OSError` or `UnicodeDecodeError` here is `Refusal("render-brief", …)` with no gate.

*`write_atomic`.* A temporary file in the destination's directory, then `os.replace`; on `OSError` remove the temporary file and re-raise.

*Output.* Ready: the object the first test compares, in that key order. Refused: `command`, `outcome`, `step`, `gate`, `detail`, `report`, `completed_steps`. `detail` is one line: collapse every whitespace run to one space and keep at most 300 characters; it never carries a member list or artifact content. Print with `json.dumps(obj, separators=(",", ":"), ensure_ascii=False)` and one newline. Exit 0 ready, 3 when `gate == "decompose_required"`, 2 otherwise.

Write the module docstring and each function's docstring from the code you implemented. The module docstring states the invocation, the step order, the exit codes and that every step is safe to repeat.

- [ ] **Step 5: Register the command**

- `lib/agent-tools.nix`: add the row `"sdd-gate"` to `commands`, between `"review-range"` and `"skill-lint"`.
- `tests/test_agent_tools_launchers.py`: add `"sdd-gate"` to `LAUNCHER_FLOOR` and `#353` to the list of issues in the comment above it.
- `justfile`, recipe `agent-workflow-tests`: add `    tests/test_sdd_gate.py \` directly after `    tests/test_sdd_brief.py \`.

- [ ] **Step 6: Document the contract**

In `python/README.md` add a section ``## `sdd-gate` `` after ``## `lane-triage` ``. Write it from the implemented code, in the register of the neighbouring sections. It states: the `review` invocation and its flags; the seven step names in order and what each does; the ready object's members and the refused object's members; the exit codes; the saved report beside a package and the reuse rule; that the task base comes from the ledger's `dispatched` line, which the `next` subcommand writes and Task 4 adds. Do not edit `CLAUDE.md`.

- [ ] **Step 7: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_sdd_gate.py` (timeout 900 s)
Expected: `OK`, 11 tests, no warnings.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_sdd_brief.py home/common/agent-skills/tests/test_review_package.py tests/test_launch_commit.py` (timeout 900 s)
Expected: `OK` (the collaborators' suites are unaffected).

Run: `if grep -nE "__file__|importlib|sys\.path" python/agent_tools/sdd_gate.py; then exit 1; fi`
Expected: no output, exit 0.

Run: `git diff --stat cd4b1746e5a844a17f806ccf791e6840e26d4cb2 -- python/agent_tools/review_package.py python/agent_tools/review_publish.py python/agent_tools/review_budget.py home/common/agent-skills/scripts`
Expected: no output.

Run: `just build` (timeout 3600 s)
Expected: exit 0: the command table's module assertion and the import check accept `agent_tools.sdd_gate`.

Run, after that build: `env AGENT_SKILLS_INSTALLED_HOME="$(nix-store --query --requisites ./result | grep -- '-home-manager-files$')" python3 -m unittest tests/test_agent_tools_launchers.py -k AgentToolsLauncherTest` (timeout 900 s)
Expected: `OK`; the installed `sdd-gate --help` exits 0 with `usage: sdd-gate `. If a subtest for another launcher fails, check whether it fails the same way at the base commit, report it, and do not change it in this task.

- [ ] **Step 8: Commit**

```bash
git add python/agent_tools/sdd_gate.py tests/test_sdd_gate.py tests/fixtures/sdd-gate lib/agent-tools.nix tests/test_agent_tools_launchers.py justfile python/README.md
git commit -m "feat(issue-353): sdd-gate review gates a task's package and renders the reviewer brief"
```
