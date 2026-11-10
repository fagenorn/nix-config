"""Eval case files as data (#293): setup kinds, setup inputs and pipeline cases."""

import json
import os
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
BUDGET = (sys.executable, "-m", "agent_tools.artifact_budget")
POLICY = REPO_ROOT / "home/common/agent-skills/artifact-budget-policy.json"
SETUP_KINDS = {"dirty-worktree", "shippable-worktree", "planned-worktree", "release-ready", "tracked-issue"}
PIPELINE_SKILLS = ("ship-release",)
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


def run_assert(shell, cwd, *, stdin=subprocess.DEVNULL, **env):
    """Run one assert snippet the way run-eval.sh grades it, stdin from /dev/null."""
    return subprocess.run(
        ["bash", "-c", f'source "$0"; {shell}', str(ASSERT_LIB)],
        cwd=cwd, env={"PATH": os.environ["PATH"], **env}, stdin=stdin,
        capture_output=True, text=True, timeout=60)


def case_assert(skill, case_id, name):
    for case in skill_cases(skill):
        if case["id"] == case_id:
            for check in case["asserts"]:
                if check["name"] == name:
                    return check["shell"]
    raise AssertionError(f"{skill} case {case_id} has no assert named {name!r}")


def find_case(skill, case_id):
    return next(case for case in skill_cases(skill) if case["id"] == case_id)


FAIL_THEN_CONTINUE = re.compile(
    r'\|\|\s*fail\b(?:"(?:[^"\\]|\\.)*"|[^;{}"])*;\s*(?!(?:fi|done|esac)\b|[};])\S')


def base_commit(repo):
    """Commit the repo once on main as the eval identity, origin/main at it; return the git argv."""
    git = ["git", "-C", str(repo), "-c", "user.name=eval", "-c", "user.email=eval@example.invalid",
           "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "base"], check=True)
    subprocess.run(git + ["update-ref", "refs/remotes/origin/main", "HEAD"], check=True)
    return git


def writing_plans_fixture(tmp, *, with_plan=True):
    """A repo shaped like writing-plans eval 1's sandbox after a good run (D7)."""
    repo = Path(tmp) / "repo"
    (repo / "issues").mkdir(parents=True)
    shutil.copy(EVALS_DIR / "fixture-repo/issues/001-well-specified.md", repo / "issues")
    git = base_commit(repo)
    spec_dir, plan_dir = repo / ".claude/specs", repo / ".claude/plans"
    if with_plan:
        issue = (repo / "issues/001-well-specified.md").read_text(encoding="utf-8")
        criteria = issue.split("## Acceptance criteria", 1)[1].split("\n## ", 1)[0]
        kinds = re.findall(r"^- \[[ xX]\] \[(code|evidence|human)\] ", criteria, re.M)
        rows = "".join(f"| AC{n} | {kind} | Task 1 | `tests/test_cli.py` |\n"
                       for n, kind in enumerate(kinds, 1))
        (plan_dir / "p.tasks").mkdir(parents=True)
        (plan_dir / "p.md").write_text(
            "# Plan\n\n## Task index\n\n"
            "Task 1 — Add the filter — tinytask/cli.py — full — "
            "[task-1.md](p.tasks/task-1.md)\n\n"
            "## Acceptance map\n\n| AC | Kind | Task | Check |\n|----|------|------|-------|\n" + rows +
            "\n## Decision ledger\n\n| ID | Choice | Grounding | Rejected alternative |\n"
            "|----|--------|-----------|----------------------|\n"
            "| P1 | One task | the task-size rule | Two tasks: one file changes |\n",
            encoding="utf-8")
        (plan_dir / "p.tasks/task-1.md").write_text(
            "# Task 1: Add the filter\n\nRun: `python3 -m unittest tests.test_cli`\nExpected: PASS.\n",
            encoding="utf-8")
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "docs: plan"], check=True)
    env = {"REPO": str(repo), "SPEC_DIR": str(spec_dir), "PLAN_DIR": str(plan_dir), "WT_COUNT": "0"}
    return repo, env


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
            [*BUDGET, "check", "--kind", kind, "--root", str(root),
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

    def test_no_assert_runs_on_after_a_guarding_fail(self):
        samples = (
            ('[ -n "$f" ] || fail "x"; awk 1 "$f"', True),
            ('x || fail no dir; for f in a; do b; done', True),
            ('[ -n "$f" ] || { fail "x"; exit 1; }; awk 1 "$f"', False),
            ('a || fail "x; y"', False),
            ('a || fail "x"', False),
            ('if a; then b || fail "x"; fi', False),
        )
        for sample, flagged in samples:
            with self.subTest(sample=sample):
                self.assertEqual(bool(FAIL_THEN_CONTINUE.search(sample)), flagged)
        for path in case_files():
            for case in json.loads(path.read_text(encoding="utf-8"))["evals"]:
                for check in case.get("asserts") or []:
                    with self.subTest(path=str(path.relative_to(REPO_ROOT)), case=case["id"],
                                      name=check["name"]):
                        self.assertNotRegex(check["shell"], FAIL_THEN_CONTINUE)

    ARTIFACT_DIR = r'\$(?:(?:SPEC|PLAN)_DIR\b|\{(?:SPEC|PLAN)_DIR\})'

    def test_no_assert_prefixes_an_absolute_artifact_dir(self):
        prefixed = re.compile(r'\$\{?(?:WT|REPO|PRE_WT)\}?/' + self.ARTIFACT_DIR)
        touched = re.compile(
            r'commits_touch\s+"\$\{?(?:WT|PRE_WT)\}?"[^;&|]*"' + self.ARTIFACT_DIR + '"')
        samples = (
            ('has_file "$REPO/$PLAN_DIR"/*.md', True),
            ('has_file "$WT/${SPEC_DIR}"/*.md', True),
            ('commits_touch "$WT" "$SPEC_DIR"', True),
            ('has_file "$PLAN_DIR"/*.md', False),
            ('has_file "$WT/${PLAN_DIR#"$REPO"/}"/*.md', False),
            ('commits_touch "$WT" "${SPEC_DIR#"$REPO"/}"', False),
            ('git -C "$REPO" log main -- "$SPEC_DIR"', False),
        )
        for sample, flagged in samples:
            with self.subTest(sample=sample):
                self.assertEqual(bool(prefixed.search(sample) or touched.search(sample)), flagged)
        for path in case_files():
            for case in json.loads(path.read_text(encoding="utf-8"))["evals"]:
                for check in case.get("asserts") or []:
                    with self.subTest(path=str(path.relative_to(REPO_ROOT)), case=case["id"],
                                      name=check["name"]):
                        self.assertNotRegex(check["shell"], prefixed)
                        self.assertNotRegex(check["shell"], touched)

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
            (members / "task-2.md").write_text(
                "# Task 2: Verify configuration\n\n- [ ] Step 1: edit the acceptance notes and assert nothing\n",
                encoding="utf-8")
            with self.subTest(case="a member with only incidental verification vocabulary"):
                done = plan_tasks_verifiable(root)
                self.assertNotEqual(done.returncode, 0, done.stdout)
                self.assertIn("task-2.md", done.stdout)
            (members / "task-2.md").write_text("# Task 2: y\n\nExpected: it works.\n", encoding="utf-8")
            with self.subTest(case="a member with an Expected line but no command"):
                done = plan_tasks_verifiable(root)
                self.assertNotEqual(done.returncode, 0, done.stdout)
                self.assertIn("task-2.md", done.stdout)
            (members / "task-2.md").write_text(
                "# Task 2: y\n\n- [ ] **Step 2: Verify**\n\n```bash\ntrue\n```\n\n**Expected:** exit 0.\n",
                encoding="utf-8")
            with self.subTest(case="a fenced command and a bold Expected label"):
                done = plan_tasks_verifiable(root)
                self.assertEqual(done.returncode, 0, done.stdout)
            (members / "task-2.md").write_text(
                "# Task 2: y\n\n**Files:**\n- Modify: `tinytask/cli.py`\n\n"
                "- [ ] **Step 1: Rename the option**\n\nIn `tinytask/cli.py`, rename it.\n\n"
                "```python\ndef run():\n    pass\n```\n\n"
                "- [ ] **Step 5: Commit**\n\n```bash\ngit commit -m x\n```\n\nExpected: `OK`.\n",
                encoding="utf-8")
            with self.subTest(case="backticked filenames, code and commit fences and an Expected value"):
                done = plan_tasks_verifiable(root)
                self.assertNotEqual(done.returncode, 0, done.stdout)
                self.assertIn("task-2.md", done.stdout)
            (members / "task-2.md").write_text(
                "# Task 2: y\n\n- Modify: `tinytask/cli.py`\n\n"
                "Run, from outside the committed tree: `python3 -m tinytask list --help`\n"
                "Expected: the help lists `--include-done`.\n",
                encoding="utf-8")
            with self.subTest(case="a qualified Run label beside backticked filenames"):
                done = plan_tasks_verifiable(root)
                self.assertEqual(done.returncode, 0, done.stdout)
            root.write_text("# Plan\n\n## Task index\n\n"
                            "Task 1 — x — f — full — [task-1.md](p.tasks/task-1.md)\n"
                            "Task 2 — y — g — full\n\n## Acceptance map\n", encoding="utf-8")
            with self.subTest(case="an index row that lost its member link"):
                done = plan_tasks_verifiable(root)
                self.assertNotEqual(done.returncode, 0, done.stdout)
                self.assertIn("Task 2", done.stdout)
            root.write_text("# Plan\n\n## Task index\n\n"
                            "Task 1 — x — f — full — [task-1.md](p.tasks/task-1.md)\n\n"
                            "## Acceptance map\n", encoding="utf-8")
            with self.subTest(case="a member on disk that the index never links"):
                done = plan_tasks_verifiable(root)
                self.assertNotEqual(done.returncode, 0, done.stdout)
                self.assertIn("task-2.md", done.stdout)
            root.write_text("# Plan\n\n## Task index\n\n"
                            "Task 2 — y — g — full — [task-2.md](p.tasks/task-2.md)\n"
                            "Task 2 — y — g — full — [task-2.md](p.tasks/task-2.md)\n\n"
                            "## Acceptance map\n", encoding="utf-8")
            with self.subTest(case="members not numbered contiguously from 1"):
                self.assertNotEqual(plan_tasks_verifiable(root).returncode, 0)
            root.write_text(index, encoding="utf-8")
            with self.subTest(case="the full index still passes"):
                done = plan_tasks_verifiable(root)
                self.assertEqual(done.returncode, 0, done.stdout)
            root.write_text("# Plan\n\n## Task index\n\nnone\n", encoding="utf-8")
            with self.subTest(case="an index that links no member"):
                self.assertNotEqual(plan_tasks_verifiable(root).returncode, 0)
            root.write_text("# Plan\n\n### Task 1: x\n\nExpected: ok\n", encoding="utf-8")
            with self.subTest(case="a legacy single-file plan"):
                self.assertEqual(plan_tasks_verifiable(root).returncode, 0)


class WritingPlansPipelineAssertsTest(unittest.TestCase):
    """#331: writing-plans eval 1 grades the plan at the absolute retained dirs."""

    DECISION = "self-answered decisions are logged as ledger rows (spec- or plan-hosted; legacy ### accepted)"

    def test_every_assert_passes_on_a_good_plan(self):
        case = find_case("writing-plans", 1)
        self.assertEqual(len(case["asserts"]), 8)
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = writing_plans_fixture(Path(tmp).resolve())
            for check in case["asserts"]:
                with self.subTest(name=check["name"]):
                    done = run_assert(check["shell"], repo, **env)
                    self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_plan_asserts_fail_when_no_plan_was_written(self):
        names = ("a plan artifact exists under the retained plans directory",
                 "every task section (inline or per-task brief) has a falsifiable verification line",
                 self.DECISION)
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = writing_plans_fixture(Path(tmp).resolve(), with_plan=False)
            for name in names:
                with self.subTest(name=name):
                    done = run_assert(case_assert("writing-plans", 1, name), repo, **env)
                    self.assertNotEqual(done.returncode, 0, done.stdout)

    def test_a_failed_precondition_reads_no_stdin(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            repo, env = writing_plans_fixture(tmp, with_plan=False)
            feed = tmp / "stdin"
            feed.write_text('{"name":"the next assert","shell":"true"}\n', encoding="utf-8")
            with feed.open("rb") as stdin:
                done = run_assert(case_assert("writing-plans", 1, self.DECISION), repo,
                                  stdin=stdin, **env)
                offset = os.lseek(stdin.fileno(), 0, os.SEEK_CUR)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("no decision section", done.stdout)
        self.assertNotIn("decision heading vanished", done.stdout)
        self.assertEqual(offset, 0, "the assert read the stream it was handed")

    def run_decision_on_ledger(self, ledger):
        """Grade the decision assert over the fixture plan with its ledger section replaced."""
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = writing_plans_fixture(Path(tmp).resolve())
            plan = Path(env["PLAN_DIR"]) / "p.md"
            head = plan.read_text(encoding="utf-8").split("## Decision ledger", 1)[0]
            plan.write_text(head + ledger, encoding="utf-8")
            return run_assert(case_assert("writing-plans", 1, self.DECISION), repo, **env)

    def test_a_header_only_ledger_fails(self):
        done = self.run_decision_on_ledger(
            "## Decision ledger\n\n| ID | Choice | Grounding | Rejected alternative |\n"
            "|----|--------|-----------|----------------------|\n")
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("no entries", done.stdout)

    def test_a_ledger_of_legacy_entries_passes(self):
        done = self.run_decision_on_ledger(
            "## Decision ledger\n\n### D1 — One task\n\n"
            "Choice: one task. Grounding: the task-size rule.\n")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


def fixture_sandbox(tmp):
    """The tinytask fixture as a committed repo whose origin/main is its only commit."""
    repo = Path(tmp) / "repo"
    shutil.copytree(EVALS_DIR / "fixture-repo", repo, ignore=shutil.ignore_patterns("__pycache__"))
    git = base_commit(repo)
    return repo, git


QUIET_GIT = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


def published_sandbox(tmp):
    """fixture_sandbox plus a bare origin holding main: the runner's REPO/ORIGIN/BASE_MAIN."""
    repo, git = fixture_sandbox(tmp)
    origin = Path(tmp) / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    subprocess.run(git + ["remote", "add", "origin", str(origin)], check=True)
    subprocess.run(git + ["push", "-q", "origin", "main"], check=True,
                   env={**os.environ, **QUIET_GIT})
    base = subprocess.run(git + ["rev-parse", "main"], capture_output=True, text=True,
                          check=True).stdout.strip()
    refs = subprocess.run(["git", "-C", str(origin), "for-each-ref",
                           "--format=%(refname) %(objectname)"],
                          capture_output=True, text=True, check=True).stdout.strip()
    env = {"WORK": str(tmp), "REPO": str(repo), "ORIGIN": str(origin), "BASE_MAIN": base,
           "ORIGIN_REFS": refs,
           "SPEC_DIR": str(repo / ".claude/specs"), "PLAN_DIR": str(repo / ".claude/plans"),
           "WT": "", "WT_COUNT": "0", "PRE_WT": ""}
    return repo, git, env


def implement_issue_three(git, worktree, branch, start="main"):
    """Add a linked worktree on `branch` holding the committed issue-3 implementation."""
    subprocess.run(git + ["worktree", "add", "-q", "-b", branch, str(worktree), start], check=True)
    wgit = ["git", "-C", str(worktree), "-c", "user.name=eval",
            "-c", "user.email=eval@example.invalid", "-c", "commit.gpgsign=false"]
    subprocess.run(wgit + ["apply", str(SETUP_INPUTS / "implementation.patch")], check=True)
    subprocess.run(wgit + ["add", "-A"], check=True)
    subprocess.run(wgit + ["commit", "-q", "-m", "feat: rename list --all to --include-done (#3)"],
                   check=True)
    return wgit


class SpecFormatCheckTest(unittest.TestCase):
    """#354: spec_decisions_path_free reads only the Decisions section (D5)."""

    def check(self, spec_text):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = fixture_sandbox(Path(tmp).resolve())
            spec = Path(tmp).resolve() / "spec.md"
            spec.write_text(spec_text, encoding="utf-8")
            return run_assert('spec_decisions_path_free "$SPEC" "$REPO"', repo,
                              SPEC=str(spec), REPO=str(repo))

    def test_a_tracked_path_in_decisions_fails_and_is_named(self):
        done = self.check("# S\n\n## Decisions\n\nThe filter lands in tinytask/cli.py.\n\n## Test seams\n")
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("tinytask/cli.py", done.stdout)

    def test_the_same_path_under_test_seams_only_passes(self):
        done = self.check("# S\n\n## Decisions\n\n### Command line\n\nThe list command gains a filter.\n\n"
                          "## Test seams\n\nPrior art: tinytask/cli.py, tests/test_cli.py:12.\n")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_each_line_reference_form_fails(self):
        for reference in ("see parser.py:12", "the anchor #L33", "at line 40", "Lines 3 to 5"):
            with self.subTest(reference=reference):
                done = self.check(f"# S\n\n## Decisions\n\nThe filter, {reference}.\n")
                self.assertNotEqual(done.returncode, 0, done.stdout)
                self.assertIn("line reference", done.stdout)

    def test_a_spec_without_a_decisions_section_fails(self):
        done = self.check("# S\n\n## Problem\n\nNo way to list done tasks.\n")
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("## Decisions", done.stdout)


class CodeMapCheckTest(unittest.TestCase):
    """#354: code_map_valid grades a code map's form, its paths and its coverage (D6)."""

    REQUIRED = ("tinytask/cli.py", "tinytask/model.py", "tests/test_cli.py")
    GOOD = ("# Code map: 2026-10-11-list-state-design.md\n\n"
            "## The list command\n"
            "- Why: it gains the state filter\n"
            "- Code: `tinytask/cli.py` (`build_parser()`, `main`); `tinytask/model.py` (`STATES`)\n"
            "- Tests: `tests/test_cli.py` (`CliTest`)\n\n"
            "## The task store\n"
            "- Why: the filter reads tasks through it\n"
            "- Code: `tinytask/store.py`\n"
            "- Tests: none read\n")

    def check(self, map_text, *required):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = fixture_sandbox(Path(tmp).resolve())
            code_map = Path(tmp).resolve() / "spec.code-map.md"
            if map_text is not None:
                code_map.write_text(map_text, encoding="utf-8")
            return run_assert('code_map_valid "$MAP" "$REPO" $REQUIRED', repo,
                              MAP=str(code_map), REPO=str(repo), REQUIRED=" ".join(required))

    def test_a_valid_map_passes(self):
        done = self.check(self.GOOD, *self.REQUIRED)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_missing_file_fails(self):
        done = self.check(None)
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("not a file", done.stdout)

    def test_a_map_with_no_entry_fails(self):
        done = self.check("# Code map: 2026-10-11-list-state-design.md\n")
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("no `## ` entry", done.stdout)

    def test_an_entry_without_a_code_line_fails_and_is_named(self):
        done = self.check(self.GOOD + "\n## The help text\n- Why: it lists the option\n- Tests: none read\n")
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("## The help text", done.stdout)

    def test_an_untracked_listed_path_fails_and_is_named(self):
        done = self.check(self.GOOD.replace("`tinytask/store.py`", "`tinytask/filters.py`"))
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("tinytask/filters.py", done.stdout)

    def test_an_absent_required_path_fails_and_is_named(self):
        done = self.check(self.GOOD, *self.REQUIRED, "tests/test_store.py")
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("tests/test_store.py", done.stdout)

    def test_a_symbol_in_parentheses_is_not_read_as_a_path(self):
        done = self.check(self.GOOD.replace("(`STATES`)", "(`STATES`, `not/a/tracked/file.py`)"))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


class CodeMapEvalCasesTest(unittest.TestCase):
    """#354: the design case grades a crafted sandbox."""

    SPEC = "2026-10-11-list-state-design.md"
    SPEC_EXISTS = "a spec exists under the retained specs directory and is committed"
    SPEC_FORMAT = "the spec's Decisions section names no file path or line number"
    MAP_EXISTS = "the code map exists in the git directory, named after the spec"
    MAP_VALID = "the code map is well-formed and lists the three files the issue decides about"
    MAP_PLACED = "no code map is tracked or present in the working tree"
    NOT_STARTED = "the implementation was not started"

    def design_sandbox(self, tmp, *, decisions="The list command gains a state filter.", with_map=True):
        """The fixture after a good design run: a committed spec and its code map in .git."""
        repo, git = fixture_sandbox(tmp)
        spec_dir = repo / ".claude/specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / self.SPEC).write_text(
            f"# Design\n\n## Problem\n\nNo done-only view.\n\n## Decisions\n\n{decisions}\n\n"
            "## Test seams\n\nThe command line, as tests/test_cli.py drives it.\n", encoding="utf-8")
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "docs: spec"], check=True)
        if with_map:
            (repo / ".git" / self.SPEC.replace(".md", ".code-map.md")).write_text(
                f"# Code map: {self.SPEC}\n\n## The list command\n- Why: it gains the state filter\n"
                "- Code: `tinytask/cli.py` (`main`); `tinytask/model.py` (`STATES`)\n"
                "- Tests: `tests/test_cli.py` (`CliTest`)\n", encoding="utf-8")
        return repo, {"REPO": str(repo), "SPEC_DIR": str(spec_dir)}

    def grade(self, name, repo, env):
        return run_assert(case_assert("design", 1, name), repo, **env)

    def test_every_design_assert_passes_on_a_good_run(self):
        case = find_case("design", 1)
        self.assertEqual(case["mode"], "pipeline")
        self.assertEqual(len(case["asserts"]), 6)
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = self.design_sandbox(Path(tmp).resolve())
            for check in case["asserts"]:
                with self.subTest(name=check["name"]):
                    done = run_assert(check["shell"], repo, **env)
                    self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_the_code_map_asserts_fail_without_a_code_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = self.design_sandbox(Path(tmp).resolve(), with_map=False)
            for name in (self.MAP_EXISTS, self.MAP_VALID):
                with self.subTest(name=name):
                    self.assertNotEqual(self.grade(name, repo, env).returncode, 0)
            self.assertEqual(self.grade(self.SPEC_EXISTS, repo, env).returncode, 0)

    def test_a_code_map_in_the_working_tree_fails_the_placement_assert(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = self.design_sandbox(Path(tmp).resolve())
            stray = repo / ".claude/specs" / self.SPEC.replace(".md", ".code-map.md")
            stray.write_text("# Code map\n", encoding="utf-8")
            done = self.grade(self.MAP_PLACED, repo, env)
            self.assertNotEqual(done.returncode, 0, done.stdout)
            self.assertIn(stray.name, done.stdout)
            for name in (self.SPEC_EXISTS, self.SPEC_FORMAT, self.MAP_EXISTS, self.MAP_VALID):
                with self.subTest(name=name):
                    done = self.grade(name, repo, env)
                    self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_tracked_path_in_decisions_fails_the_spec_format_assert(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = self.design_sandbox(
                Path(tmp).resolve(), decisions="The filter lands in tinytask/cli.py.")
            done = self.grade(self.SPEC_FORMAT, repo, env)
            self.assertNotEqual(done.returncode, 0, done.stdout)
            self.assertIn("tinytask/cli.py", done.stdout)

    def test_a_spec_edited_after_its_commit_fails_the_committed_assert(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = self.design_sandbox(Path(tmp).resolve())
            spec = repo / ".claude/specs" / self.SPEC
            spec.write_text(spec.read_text(encoding="utf-8") + "\nA later draft.\n", encoding="utf-8")
            done = self.grade(self.SPEC_EXISTS, repo, env)
            self.assertNotEqual(done.returncode, 0, done.stdout)
            self.assertIn("differs from its committed content", done.stdout)

    def test_an_untracked_source_file_fails_the_not_started_assert(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = self.design_sandbox(Path(tmp).resolve())
            self.assertEqual(self.grade(self.NOT_STARTED, repo, env).returncode, 0)
            (repo / "tinytask" / "extra.py").write_text("STATE = 1\n", encoding="utf-8")
            done = self.grade(self.NOT_STARTED, repo, env)
            self.assertNotEqual(done.returncode, 0, done.stdout)
            self.assertIn("tinytask/extra.py", done.stdout)


class DirectDeliveryEvalCaseTest(unittest.TestCase):
    """#725: deliver-direct case 1, the routine-issue corpus case, grades a crafted sandbox."""

    CRITICAL = ("a worktree was created", "nothing was pushed",
                "local and origin main are unchanged",
                "the implementation is committed on the worktree branch",
                "the renamed flag works through the CLI")
    NONCRITICAL = ("the worktree branch is named for issue 3",
                   "the fixture's tests pass in the worktree",
                   "no occurrence of the old flag remains", "no spec or plan was written",
                   "the worktree is left clean")

    def good_run(self, tmp):
        repo, git, env = published_sandbox(tmp)
        worktree = repo / ".worktrees/issue-3-rename-flag"
        wgit = implement_issue_three(git, worktree, "issue-3-rename-flag")
        env.update(WT=str(worktree), WT_COUNT="1")
        return repo, git, wgit, env

    def grade(self, name, repo, env):
        return run_assert(case_assert("deliver-direct", 1, name), repo, **env)

    def test_the_case_is_a_scripted_pipeline_case(self):
        case = find_case("deliver-direct", 1)
        self.assertEqual((case["name"], case["mode"]), ("direct-issue-through-test-first", "pipeline"))
        self.assertNotIn("setup", case)
        self.assertEqual(tuple(check["name"] for check in case["asserts"]),
                         self.CRITICAL + self.NONCRITICAL)
        self.assertIn("ResolvedProject", case["prompt"])
        self.assertIn("issues/003-mechanical.md", case["prompt"])
        self.assertRegex(case["prompt"].lower(), r"\bstop\b")

    def test_every_assert_passes_on_a_good_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, _, env = self.good_run(Path(tmp).resolve())
            for name in self.CRITICAL + self.NONCRITICAL:
                with self.subTest(name=name):
                    done = self.grade(name, repo, env)
                    self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    OLD_FLAG = "no occurrence of the old flag remains"
    REJECTION_TEST = (
        "\n    def test_list_all_is_rejected(self):\n"
        "        with self.assertRaises(SystemExit):\n"
        "            run(\"--file\", self.path, \"list\", \"--all\")\n")

    def commit_edit(self, wgit, worktree, name, edit, message):
        path = worktree / name
        path.write_text(edit(path.read_text(encoding="utf-8")), encoding="utf-8")
        subprocess.run(wgit + ["commit", "-qam", message], check=True,
                       env={**os.environ, **QUIET_GIT})

    def test_every_assert_passes_with_a_test_that_asserts_the_old_flag_is_rejected(self):
        """#750: criterion 2 makes a rejection test correct work, so it must not be penalized."""
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, wgit, env = self.good_run(Path(tmp).resolve())
            worktree = Path(env["WT"])
            self.commit_edit(wgit, worktree, "tests/test_cli.py",
                             lambda text: text.replace(
                                 '\n\nif __name__ == "__main__":',
                                 self.REJECTION_TEST + '\n\nif __name__ == "__main__":'),
                             "test: list --all is rejected")
            self.assertIn("--all", (worktree / "tests/test_cli.py").read_text(encoding="utf-8"))
            for name in self.CRITICAL + self.NONCRITICAL:
                with self.subTest(name=name):
                    done = self.grade(name, repo, env)
                    self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_the_old_flag_left_in_the_implementation_or_readme_fails(self):
        for name, old, new in (("tinytask/cli.py", "--include-done", "--all"),
                               ("README.md", "--include-done", "--all")):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                repo, _, wgit, env = self.good_run(Path(tmp).resolve())
                self.commit_edit(wgit, Path(env["WT"]), name,
                                 lambda text: text.replace(old, new, 1), "restore old flag")
                self.assertNotEqual(self.grade(self.OLD_FLAG, repo, env).returncode, 0)

    def test_a_test_file_that_never_exercises_the_new_flag_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, wgit, env = self.good_run(Path(tmp).resolve())
            self.commit_edit(wgit, Path(env["WT"]), "tests/test_cli.py",
                             lambda text: text.replace("--include-done", "--other"),
                             "test no longer exercises the flag")
            self.assertNotEqual(self.grade(self.OLD_FLAG, repo, env).returncode, 0)

    def test_no_worktree_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, env = published_sandbox(Path(tmp).resolve())
            self.assertNotEqual(self.grade("a worktree was created", repo, env).returncode, 0)

    def test_a_pushed_branch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, wgit, env = self.good_run(Path(tmp).resolve())
            subprocess.run(wgit + ["push", "-q", "origin", "issue-3-rename-flag"], check=True,
                           env={**os.environ, **QUIET_GIT})
            self.assertNotEqual(self.grade("nothing was pushed", repo, env).returncode, 0)

    def test_a_moved_main_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, git, _, env = self.good_run(Path(tmp).resolve())
            subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "moved"], check=True)
            self.assertNotEqual(
                self.grade("local and origin main are unchanged", repo, env).returncode, 0)

    def test_an_uncommitted_implementation_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, git, env = published_sandbox(Path(tmp).resolve())
            worktree = repo / ".worktrees/issue-3-rename-flag"
            subprocess.run(git + ["worktree", "add", "-q", "-b", "issue-3-rename-flag",
                                  str(worktree), "main"], check=True)
            subprocess.run(["git", "-C", str(worktree), "apply",
                            str(SETUP_INPUTS / "implementation.patch")], check=True)
            env.update(WT=str(worktree), WT_COUNT="1")
            for name in ("the implementation is committed on the worktree branch",
                         "the worktree is left clean"):
                with self.subTest(name=name):
                    self.assertNotEqual(self.grade(name, repo, env).returncode, 0)

    def test_an_uncommitted_rename_behind_an_unrelated_commit_fails_the_commit_check(self):
        """An unrelated docstring commit satisfies `commits_touch`; the rename left in
        the working tree satisfies the CLI check. The commit check must still fail."""
        with tempfile.TemporaryDirectory() as tmp:
            repo, git, env = published_sandbox(Path(tmp).resolve())
            worktree = repo / ".worktrees/issue-3-rename-flag"
            subprocess.run(git + ["worktree", "add", "-q", "-b", "issue-3-rename-flag",
                                  str(worktree), "main"], check=True)
            wgit = ["git", "-C", str(worktree), "-c", "user.name=eval",
                    "-c", "user.email=eval@example.invalid", "-c", "commit.gpgsign=false"]
            init = worktree / "tinytask/__init__.py"
            init.write_text('"""Tinytask."""\n' + init.read_text(encoding="utf-8"),
                            encoding="utf-8")
            subprocess.run(wgit + ["commit", "-qam", "docs: a docstring"], check=True)
            subprocess.run(wgit + ["apply", str(SETUP_INPUTS / "implementation.patch")],
                           check=True)
            env.update(WT=str(worktree), WT_COUNT="1")
            self.assertEqual(self.grade("the renamed flag works through the CLI",
                                        repo, env).returncode, 0)
            self.assertNotEqual(self.grade(
                "the implementation is committed on the worktree branch", repo, env).returncode, 0)

    def test_a_consistent_rename_to_another_flag_fails_only_the_cli_check(self):
        """Implementation, tests and README renamed together to --foo: every
        candidate-editable assert but the old-flag one (which wants `--include-done` exercised
        by the tests) still passes, and the interface the issue names does not."""
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, wgit, env = self.good_run(Path(tmp).resolve())
            worktree = Path(env["WT"])
            for name in ("tinytask/cli.py", "tests/test_cli.py", "README.md"):
                path = worktree / name
                path.write_text(path.read_text(encoding="utf-8").replace("--include-done", "--foo")
                    .replace("include_done", "foo"), encoding="utf-8")
            subprocess.run(wgit + ["commit", "-qam", "rename to --foo"], check=True,
                           env={**os.environ, **QUIET_GIT})
            for name in self.NONCRITICAL[1:2] + self.CRITICAL[3:4]:
                with self.subTest(name=name):
                    self.assertEqual(self.grade(name, repo, env).returncode, 0)
            self.assertNotEqual(self.grade("the renamed flag works through the CLI",
                                           repo, env).returncode, 0)

    def test_keeping_the_old_flag_fails_the_cli_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, git, env = published_sandbox(Path(tmp).resolve())
            worktree = repo / ".worktrees/issue-3-rename-flag"
            subprocess.run(git + ["worktree", "add", "-q", "-b", "issue-3-rename-flag",
                                  str(worktree), "main"], check=True)
            env.update(WT=str(worktree), WT_COUNT="1")
            self.assertNotEqual(self.grade("the renamed flag works through the CLI",
                                           repo, env).returncode, 0)

    def test_a_spec_in_the_worktree_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, _, env = self.good_run(Path(tmp).resolve())
            spec_dir = Path(env["WT"]) / ".claude/specs"
            spec_dir.mkdir(parents=True)
            (spec_dir / "s.md").write_text("# spec\n", encoding="utf-8")
            self.assertNotEqual(self.grade("no spec or plan was written", repo, env).returncode, 0)


class NativeReviewEvalCaseTest(unittest.TestCase):
    """#725: codex-collaboration case 4, the review-ship corpus case, grades a crafted sandbox."""

    NAMES = ("nothing was pushed", "local and origin main are unchanged",
             "the branch still carries the implementation",
             "the worktree is left exactly as committed",
             "the run names the native route for the unsupported capability",
             "the run prints the Critical, Important and Minor sections")
    GOOD_OUT = ("diff-review: capabilities.review.code is unsupported, so no Codex call; "
                "native route review of main...worktree-issue-3-rename-flag.\n"
                "Critical\n- none\nImportant\n- none\nMinor\n- README wording\n")

    IDENT = ["git", "-c", "user.name=eval", "-c", "user.email=eval@example.invalid"]

    def good_run(self, tmp, out=GOOD_OUT):
        repo, git, env = published_sandbox(tmp)
        pre_wt = tmp / "worktree-issue-3-rename-flag"
        wgit = implement_issue_three(git, pre_wt, "worktree-issue-3-rename-flag")
        (tmp / "out.txt").write_text(out, encoding="utf-8")
        head = subprocess.run(wgit + ["rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
        env.update(PRE_WT=str(pre_wt), PRE_WT_HEAD=head, WT=str(pre_wt), WT_COUNT="1",
                   OUT=str(tmp / "out.txt"))
        return repo, wgit, env

    def grade(self, name, repo, env):
        return run_assert(case_assert("codex-collaboration", 4, name), repo, **env)

    def test_the_case_is_a_scripted_pipeline_case(self):
        case = find_case("codex-collaboration", 4)
        self.assertEqual((case["name"], case["mode"], case["setup"]),
                         ("native-diff-review-before-ship", "pipeline",
                          {"kind": "shippable-worktree"}))
        self.assertEqual(tuple(check["name"] for check in case["asserts"]), self.NAMES)
        self.assertIn("ResolvedProject", case["prompt"])
        self.assertIn("diff-review", case["prompt"])
        self.assertRegex(case["prompt"].lower(), r"\bstop\b")

    def test_every_assert_passes_on_a_good_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, env = self.good_run(Path(tmp).resolve())
            for name in self.NAMES:
                with self.subTest(name=name):
                    done = self.grade(name, repo, env)
                    self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_pushed_branch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, wgit, env = self.good_run(Path(tmp).resolve())
            subprocess.run(wgit + ["push", "-q", "origin", "worktree-issue-3-rename-flag"],
                           check=True, env={**os.environ, **QUIET_GIT})
            self.assertNotEqual(self.grade("nothing was pushed", repo, env).returncode, 0)

    def test_a_push_under_another_branch_name_fails(self):
        """The branch ref stays absent, main unchanged and the worktree clean, yet the
        review's commits reached origin under another name."""
        with tempfile.TemporaryDirectory() as tmp:
            repo, wgit, env = self.good_run(Path(tmp).resolve())
            self.assertEqual(self.grade("nothing was pushed", repo, env).returncode, 0)
            subprocess.run(wgit + ["push", "-q", "origin", "HEAD:refs/heads/review-result"],
                           check=True, env={**os.environ, **QUIET_GIT})
            self.assertNotEqual(self.grade("nothing was pushed", repo, env).returncode, 0)

    def test_a_pushed_tag_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, wgit, env = self.good_run(Path(tmp).resolve())
            subprocess.run(wgit + ["push", "-q", "origin", "HEAD:refs/tags/reviewed"],
                           check=True, env={**os.environ, **QUIET_GIT})
            self.assertNotEqual(self.grade("nothing was pushed", repo, env).returncode, 0)

    def test_an_edited_worktree_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, env = self.good_run(Path(tmp).resolve())
            (Path(env["PRE_WT"]) / "README.md").write_text("edited\n", encoding="utf-8")
            self.assertNotEqual(
                self.grade("the worktree is left exactly as committed", repo, env).returncode, 0)

    def test_a_committed_revert_fails(self):
        """A clean tree and a tinytask commit are not enough: HEAD must still be the setup tip."""
        with tempfile.TemporaryDirectory() as tmp:
            repo, wgit, env = self.good_run(Path(tmp).resolve())
            subprocess.run(wgit + ["revert", "--no-edit", "HEAD"], check=True,
                           capture_output=True, env={**os.environ, **QUIET_GIT})
            for name in ("the branch still carries the implementation",
                         "the worktree is left exactly as committed"):
                with self.subTest(name=name):
                    self.assertNotEqual(self.grade(name, repo, env).returncode, 0)

    def test_a_committed_edit_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, wgit, env = self.good_run(Path(tmp).resolve())
            (Path(env["PRE_WT"]) / "README.md").write_text("edited\n", encoding="utf-8")
            subprocess.run(wgit + ["commit", "-qam", "review edit"], check=True,
                           env={**os.environ, **QUIET_GIT})
            self.assertNotEqual(
                self.grade("the branch still carries the implementation", repo, env).returncode, 0)

    def test_an_untracked_file_in_the_worktree_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, env = self.good_run(Path(tmp).resolve())
            (Path(env["PRE_WT"]) / "NOTES.wip").write_text("scratch\n", encoding="utf-8")
            self.assertNotEqual(
                self.grade("the worktree is left exactly as committed", repo, env).returncode, 0)

    def test_a_moved_main_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, env = self.good_run(Path(tmp).resolve())
            subprocess.run(self.IDENT + ["-C", str(repo), "commit", "-q", "--allow-empty",
                                         "-m", "moved"], check=True,
                           env={**os.environ, **QUIET_GIT})
            self.assertNotEqual(
                self.grade("local and origin main are unchanged", repo, env).returncode, 0)

    def test_an_edit_in_the_base_checkout_fails(self):
        """A review is read-only: an uncommitted edit or a new file in $REPO breaks it
        although main, origin and the review worktree are all untouched."""
        name = "local and origin main are unchanged"
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, env = self.good_run(Path(tmp).resolve())
            self.assertEqual(self.grade(name, repo, env).returncode, 0)
            readme = repo / "README.md"
            readme.write_text(readme.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8")
            done = self.grade(name, repo, env)
            self.assertNotEqual(done.returncode, 0, done.stdout)
            self.assertIn("README.md", done.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, env = self.good_run(Path(tmp).resolve())
            (repo / "REVIEW-NOTES.md").write_text("findings\n", encoding="utf-8")
            done = self.grade(name, repo, env)
            self.assertNotEqual(done.returncode, 0, done.stdout)
            self.assertIn("REVIEW-NOTES.md", done.stdout)

    def test_a_moved_origin_main_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, env = self.good_run(Path(tmp).resolve())
            git = self.IDENT + ["-C", str(repo)]
            quiet = {**os.environ, **QUIET_GIT}
            moved = subprocess.run(git + ["commit-tree", "main^{tree}", "-p", "main", "-m", "moved"],
                                   capture_output=True, text=True, check=True, env=quiet).stdout.strip()
            subprocess.run(git + ["push", "-q", "origin", f"{moved}:refs/heads/main"], check=True,
                           env=quiet)
            self.assertNotEqual(
                self.grade("local and origin main are unchanged", repo, env).returncode, 0)

    def test_an_output_missing_one_severity_section_fails(self):
        name = "the run prints the Critical, Important and Minor sections"
        for missing in ("Critical", "Important", "Minor"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                out = "".join(f"{word}\n- none\n" for word in ("Critical", "Important", "Minor")
                              if word != missing)
                repo, _, env = self.good_run(Path(tmp).resolve(), out=out)
                self.assertNotEqual(self.grade(name, repo, env).returncode, 0)

    def test_a_review_declared_unperformed_fails_the_sections_check(self):
        """Naming the severity words is not printing the sections: an output that says
        it cannot produce them has reviewed nothing."""
        name = "the run prints the Critical, Important and Minor sections"
        for out in ("Native review unsupported; cannot produce Critical, Important or Minor "
                    "sections\n",
                    "Critical, Important and Minor: not run, the native route was unsupported.\n",
                    "Critical\n- none\nImportant\n- none\nMinor\n- none\n"):
            with self.subTest(out=out), tempfile.TemporaryDirectory() as tmp:
                repo, _, env = self.good_run(Path(tmp).resolve(), out=out)
                self.assertNotEqual(self.grade(name, repo, env).returncode, 0)

    def test_markdown_section_headings_pass(self):
        name = "the run prints the Critical, Important and Minor sections"
        out = ("## Critical\n- none\n**Important**\n- tinytask/cli.py:23 help text\n"
               "### Minor:\n- none\n")
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, env = self.good_run(Path(tmp).resolve(), out=out)
            self.assertEqual(self.grade(name, repo, env).returncode, 0)

    def test_the_native_rubric_headings_pass(self):
        """The native reviewer prompt's own headings carry a parenthetical."""
        name = "the run prints the Critical, Important and Minor sections"
        for out in ("### Critical (Must Fix)\n- none\n### Important (Should Fix)\n- none\n"
                    "### Minor\n- tinytask/cli.py:23 help text\n",
                    "**Critical (Must Fix)**\n- none\n**Important (Should Fix):**\n- none\n"
                    "**Minor**\n- README wording\n"):
            with self.subTest(out=out), tempfile.TemporaryDirectory() as tmp:
                repo, _, env = self.good_run(Path(tmp).resolve(), out=out)
                self.assertEqual(self.grade(name, repo, env).returncode, 0)

    def test_an_output_without_the_route_or_sections_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, env = self.good_run(Path(tmp).resolve(), out="Looks good to me.\n")
            for name in self.NAMES[4:]:
                with self.subTest(name=name):
                    self.assertNotEqual(self.grade(name, repo, env).returncode, 0)


if __name__ == "__main__":
    unittest.main()
