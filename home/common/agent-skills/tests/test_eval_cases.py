"""Eval case files as data (#293): setup kinds, setup inputs and pipeline cases."""

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[4]
EVALS_DIR = REPO_ROOT / "home/common/agent-skills/evals"
RUNNER = EVALS_DIR / "run-eval.sh"
SETUP_INPUTS = EVALS_DIR / "setups/issue-3"
SKILL_ROOTS = (
    REPO_ROOT / "home/common/agent-skills/skills",
    REPO_ROOT / "home/common/claude-code/skills",
)
BUDGET = (sys.executable, "-m", "agent_tools.delivery.artifact_budget")
POLICY = REPO_ROOT / "home/common/agent-skills/artifact-budget-policy.json"
SETUP_KINDS = {"dirty-worktree", "shippable-worktree", "planned-worktree", "release-ready", "tracked-issue",
                "marked-pr"}
PIPELINE_SKILLS = ("ship-release",)
ASSERT_LIB = EVALS_DIR / "assert-lib.sh"
MARKED_SETUP = EVALS_DIR / "setups/marked-pr/setup.sh"
GH_SHIM = EVALS_DIR / "setups/tracked-issue/gh.py"


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
    origin = Path(tmp) / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    subprocess.run(git + ["remote", "add", "origin", str(origin)], check=True)
    subprocess.run(git + ["push", "-q", "origin", "main"], check=True,
                   env={**os.environ, **QUIET_GIT})
    spec_dir, plan_dir = repo / ".git/specs", repo / ".git/plans"
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
    base = subprocess.run(git + ["rev-parse", "main"], capture_output=True, text=True,
                          check=True).stdout.strip()
    refs = subprocess.run(["git", "-C", str(origin), "for-each-ref",
                           "--format=%(refname) %(objectname)"],
                          capture_output=True, text=True, check=True).stdout.strip()
    env = {"REPO": str(repo), "ORIGIN": str(origin), "BASE_MAIN": base, "ORIGIN_REFS": refs,
           "SPEC_DIR": str(spec_dir), "PLAN_DIR": str(plan_dir), "WT_COUNT": "0"}
    return repo, env


def eval_git(repo):
    """The git argv that commits in `repo` as the eval identity."""
    return ["git", "-C", str(repo), "-c", "user.name=eval", "-c", "user.email=eval@example.invalid",
            "-c", "commit.gpgsign=false"]


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
        names = ("a plan root exists in the git directory's plans directory",
                 "every task section (inline or per-task brief) has a falsifiable verification line",
                 self.DECISION)
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = writing_plans_fixture(Path(tmp).resolve(), with_plan=False)
            for name in names:
                with self.subTest(name=name):
                    done = run_assert(case_assert("writing-plans", 1, name), repo, **env)
                    self.assertNotEqual(done.returncode, 0, done.stdout)

    CLEAN = "nothing was committed and the working tree is clean"

    def commit_plan_copy(self, repo, env):
        stray = repo / ".claude/plans/p.md"
        stray.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(Path(env["PLAN_DIR"]) / "p.md", stray)
        git = eval_git(repo)
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "docs: plan"], check=True)

    def test_a_committed_plan_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = writing_plans_fixture(Path(tmp).resolve())
            self.commit_plan_copy(repo, env)
            done = run_assert(case_assert("writing-plans", 1, self.CLEAN), repo, **env)
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("a commit was made", done.stdout)

    def test_a_plan_committed_on_a_side_branch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = writing_plans_fixture(Path(tmp).resolve())
            git = eval_git(repo)
            subprocess.run(git + ["switch", "-q", "-c", "side"], check=True)
            self.commit_plan_copy(repo, env)
            subprocess.run(git + ["switch", "-q", "main"], check=True)
            subprocess.run(git + ["branch", "-q", "-D", "side"], check=True)
            done = run_assert(case_assert("writing-plans", 1, self.CLEAN), repo, **env)
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("a commit was made", done.stdout)

    def test_a_new_origin_ref_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = writing_plans_fixture(Path(tmp).resolve())
            subprocess.run(eval_git(repo) + ["push", "-q", "origin", "main:refs/heads/extra"],
                           check=True, env={**os.environ, **QUIET_GIT})
            done = run_assert(case_assert("writing-plans", 1, self.CLEAN), repo, **env)
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("origin's refs changed", done.stdout)

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


class PlanningLedgerWriteBackAssertsTest(unittest.TestCase):
    """#1441: writing-plans eval 4 grades the ledger write-back to the spec's issue."""

    ISSUE = "issues/001-well-specified.md"
    ROW = ("\n## Decision ledger\n\n| ID | Choice | Grounding | Rejected alternative |\n"
           "|----|----|----|----|\n| P1 | One task | the task-size rule | Two tasks |\n")
    CITED = "the issue body carries every ledger row the plan cites"
    NO_COMMIT = "no commit was made or pushed"
    ONLY_ISSUE = "the issue file is the only working-tree change and its acceptance criteria are unchanged"

    def good(self, tmp):
        repo, env = writing_plans_fixture(Path(tmp).resolve())
        with (Path(env["PLAN_DIR"]) / "p.md").open("a", encoding="utf-8") as plan:
            plan.write("\nPer P1, one task.\n")
        with (repo / self.ISSUE).open("a", encoding="utf-8") as issue:
            issue.write(self.ROW)
        return repo, env

    def grade(self, name, repo, env):
        return run_assert(case_assert("writing-plans", 4, name), repo, **env)

    def test_every_assert_passes_on_a_good_run(self):
        case = find_case("writing-plans", 4)
        self.assertEqual(case["mode"], "pipeline")
        self.assertNotIn("setup", case)
        self.assertEqual(len(case["asserts"]), 4)
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = self.good(tmp)
            for check in case["asserts"]:
                with self.subTest(name=check["name"]):
                    done = run_assert(check["shell"], repo, **env)
                    self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_row_only_in_the_plan_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = self.good(tmp)
            subprocess.run(["git", "-C", str(repo), "checkout", "--", self.ISSUE], check=True)
            done = self.grade(self.CITED, repo, env)
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("which the issue body lacks", done.stdout)

    def test_a_row_under_another_heading_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = self.good(tmp)
            subprocess.run(["git", "-C", str(repo), "checkout", "--", self.ISSUE], check=True)
            with (repo / self.ISSUE).open("a", encoding="utf-8") as issue:
                issue.write("\n## Notes\n\n| P1 | One task | the task-size rule | Two tasks |\n")
            done = self.grade(self.CITED, repo, env)
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("which the issue body lacks", done.stdout)

    def test_a_ledger_row_with_an_empty_cell_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = self.good(tmp)
            subprocess.run(["git", "-C", str(repo), "checkout", "--", self.ISSUE], check=True)
            with (repo / self.ISSUE).open("a", encoding="utf-8") as issue:
                issue.write("\n## Decision ledger\n\n| ID | Choice | Grounding | Rejected alternative |\n"
                            "|----|----|----|----|\n| P1 | One task |  |  |\n")
            done = self.grade(self.CITED, repo, env)
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("which the issue body lacks", done.stdout)

    def test_a_committed_ledger_row_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = self.good(tmp)
            git = eval_git(repo)
            subprocess.run(git + ["commit", "-q", "-m", "docs: ledger", "--", self.ISSUE], check=True)
            done = self.grade(self.NO_COMMIT, repo, env)
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("a commit was made", done.stdout)

    def test_a_changed_acceptance_criteria_section_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = self.good(tmp)
            issue = repo / self.ISSUE
            text = issue.read_text(encoding="utf-8")
            start = text.index("## Acceptance criteria")
            first = text.index("- [ ]", start)
            end = text.index("\n", first)
            issue.write_text(text[:first] + "- [ ] [code] changed" + text[end:], encoding="utf-8")
            done = self.grade(self.ONLY_ISSUE, repo, env)
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("acceptance criteria", done.stdout)

    def test_an_extra_working_tree_change_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = self.good(tmp)
            (repo / "notes.md").write_text("stray\n", encoding="utf-8")
            done = self.grade(self.ONLY_ISSUE, repo, env)
        self.assertNotEqual(done.returncode, 0, done.stdout)
        self.assertIn("more than the issue's new body", done.stdout)


class CommitBoundaryAssertsTest(unittest.TestCase):
    """#1441: what a no-setup design run may commit, and the check that no commit goes unseen."""

    DRAFT = ("the design spec draft is in the worktree's git directory "
             "and no commit added a spec or plan")
    DRAFT_FILE = "specs/2026-10-11-store-design.md"

    def design_worktree(self, tmp, *, draft=True):
        repo, git, env = published_sandbox(tmp)
        worktree = repo / ".worktrees/design"
        subprocess.run(git + ["worktree", "add", "-q", "-b", "design", str(worktree), "main"],
                       check=True)
        wgit = eval_git(worktree)
        if draft:
            gitdir = Path(subprocess.run(wgit + ["rev-parse", "--absolute-git-dir"], check=True,
                                         capture_output=True, text=True).stdout.strip())
            (gitdir / "specs").mkdir()
            (gitdir / self.DRAFT_FILE).write_text("# Design\n", encoding="utf-8")
        env.update(WT=str(worktree), WT_COUNT="1")
        return repo, wgit, worktree, env

    def grade(self, repo, env):
        return run_assert(case_assert("improve-codebase-architecture", 2, self.DRAFT), repo, **env)

    def commit_file(self, wgit, worktree, name):
        path = worktree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Doc\n", encoding="utf-8")
        subprocess.run(wgit + ["add", name], check=True)
        subprocess.run(wgit + ["commit", "-q", "-m", f"docs: {name}"], check=True,
                       env={**os.environ, **QUIET_GIT})

    def test_a_draft_with_no_commit_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, _, env = self.design_worktree(Path(tmp).resolve())
            done = self.grade(repo, env)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_domain_doc_committed_on_the_design_branch_passes(self):
        for name in ("docs/areas/store/CONTEXT.md", "docs/areas/store/adr/0001-store-seam.md",
                     "docs/CONTEXT-MAP.md"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                repo, wgit, worktree, env = self.design_worktree(Path(tmp).resolve())
                self.commit_file(wgit, worktree, name)
                done = self.grade(repo, env)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_missing_draft_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, _, env = self.design_worktree(Path(tmp).resolve(), draft=False)
            done = self.grade(repo, env)
            self.assertNotEqual(done.returncode, 0, done.stdout)
            self.assertIn("no spec draft", done.stdout)

    def test_a_committed_spec_or_plan_fails(self):
        for name in ("specs/2026-10-11-store.md", "docs/plans/p.md", "docs/2026-10-11-store-design.md"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                repo, wgit, worktree, env = self.design_worktree(Path(tmp).resolve())
                self.commit_file(wgit, worktree, name)
                done = self.grade(repo, env)
                self.assertNotEqual(done.returncode, 0, done.stdout)
                self.assertIn("a commit added a spec or plan", done.stdout)

    def test_a_pushed_branch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, wgit, worktree, env = self.design_worktree(Path(tmp).resolve())
            self.commit_file(wgit, worktree, "docs/CONTEXT-MAP.md")
            subprocess.run(wgit + ["push", "-q", "origin", "design"], check=True,
                           env={**os.environ, **QUIET_GIT})
            done = self.grade(repo, env)
            self.assertNotEqual(done.returncode, 0, done.stdout)
            self.assertIn("the origin's refs changed", done.stdout)

    def test_a_commit_in_a_removed_detached_worktree_still_counts(self):
        """#1441: a detached worktree's HEAD log goes with the worktree, the commit object stays."""
        with tempfile.TemporaryDirectory() as tmp:
            repo, git, env = published_sandbox(Path(tmp).resolve())
            side = Path(tmp).resolve() / "side"
            subprocess.run(git + ["worktree", "add", "-q", "--detach", str(side), "main"], check=True)
            (side / "note.md").write_text("x\n", encoding="utf-8")
            sgit = eval_git(side)
            subprocess.run(sgit + ["add", "note.md"], check=True)
            subprocess.run(sgit + ["commit", "-q", "-m", "docs: note"], check=True,
                           env={**os.environ, **QUIET_GIT})
            subprocess.run(git + ["worktree", "remove", "--force", str(side)], check=True)
            done = run_assert('no_new_commits "$REPO"', repo, **env)
            self.assertNotEqual(done.returncode, 0, done.stdout)
            self.assertIn("a commit was made", done.stdout)

    def test_a_clean_sandbox_has_no_new_commits(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, env = published_sandbox(Path(tmp).resolve())
            done = run_assert('no_new_commits "$REPO"', repo, **env)
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
           "SPEC_DIR": str(repo / ".git/specs"), "PLAN_DIR": str(repo / ".git/plans"),
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


def marked_pr_sandbox(tmp):
    """published_sandbox after the marked-pr setup: the runner's REPO and grading env."""
    repo, _, env = published_sandbox(tmp)
    for key, value in (("user.name", "eval"), ("user.email", "eval@example.invalid"),
                       ("commit.gpgsign", "false")):
        subprocess.run(["git", "-C", str(repo), "config", key, value], check=True)
    subprocess.run(["bash", str(MARKED_SETUP), str(tmp), str(repo)],
                   env={**os.environ, **QUIET_GIT}, check=True)
    worktree = Path(tmp) / "issue-3-rename-flag"

    def rev(*argv):
        return subprocess.run(["git", "-C", *argv], capture_output=True, text=True,
                              check=True).stdout.strip()

    env.update(BASE_MAIN=rev(str(repo), "rev-parse", "main"),
               ORIGIN_REFS=rev(env["ORIGIN"], "for-each-ref", "--format=%(refname) %(objectname)"),
               PRE_WT=str(worktree), PRE_WT_HEAD=rev(str(worktree), "rev-parse", "HEAD"),
               WT=str(worktree), WT_COUNT="1")
    return repo, env


SANDBOXES = None
BUILT = {}


def restored(key, build):
    """The sandbox `build(work)` makes for `key`, built once per run, put back before every use.

    A sandbox bakes its own absolute path into git links, remote URLs and wrapper scripts, so
    a copy is valid only where it was built: build at a fixed path, keep a pristine copy and
    put that copy back at the same path. Returns (work, a deep copy of the build's result)."""
    global SANDBOXES
    if SANDBOXES is None:
        SANDBOXES = Path(tempfile.mkdtemp(prefix="eval-sandboxes-")).resolve()
        unittest.addModuleCleanup(shutil.rmtree, SANDBOXES, True)
    work, pristine = SANDBOXES / key / "work", SANDBOXES / key / "pristine"
    if key not in BUILT:
        work.mkdir(parents=True)
        BUILT[key] = build(work)
        shutil.copytree(work, pristine, symlinks=True)
    shutil.rmtree(work)
    shutil.copytree(pristine, work, symlinks=True)
    return work, copy.deepcopy(BUILT[key])


class RestoredSandboxTest(unittest.TestCase):
    """#1615: a sandbox is built once per run and put back in place before every use."""

    @staticmethod
    def head_of(repo):
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()

    def test_a_restored_sandbox_is_its_build_without_an_earlier_tests_change(self):
        key = f"probe-{self.id()}"
        calls = []

        def build(work):
            calls.append(work)
            repo, git = fixture_sandbox(work)
            head = subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True,
                                  check=True).stdout.strip()
            return {"repo": str(repo), "head": head, "env": {"OUT": "built"}}

        first_work, first = restored(key, build)
        with open(Path(first["repo"]) / "README.md", "a", encoding="utf-8") as readme:
            readme.write("edit\n")
        subprocess.run(eval_git(Path(first["repo"])) + ["commit", "-qam", "edit"], check=True)
        (first_work / "stray").write_text("x", encoding="utf-8")
        first["head"] = "changed"
        first["env"]["OUT"] = "changed"
        second_work, second = restored(key, build)
        self.assertEqual(len(calls), 1)
        self.assertEqual(second_work, first_work)
        self.assertFalse((second_work / "stray").exists())
        self.assertNotIn("edit", (Path(second["repo"]) / "README.md").read_text(encoding="utf-8"))
        self.assertEqual(self.head_of(second["repo"]), second["head"])
        self.assertNotEqual(second["head"], "changed")
        self.assertEqual(second["env"], {"OUT": "built"})
        status = subprocess.run(["git", "-C", second["repo"], "status", "--porcelain"],
                                capture_output=True, text=True, check=True).stdout
        self.assertEqual(status, "")

    def test_the_first_use_is_already_a_restored_copy(self):
        key = f"probe-{self.id()}"
        held = []
        self.addCleanup(lambda: [handle.close() for handle in held])

        def build(work):
            marker = work / "marker"
            marker.write_text("m", encoding="utf-8")
            held.append(open(marker, "a", encoding="utf-8"))
            return None

        work, _ = restored(key, build)
        held[0].write("changed")
        held[0].flush()
        self.assertEqual((work / "marker").read_text(encoding="utf-8"), "m")

    def test_marked_sandboxes_are_built_once_per_run(self):
        module = sys.modules[__name__]
        with mock.patch.object(module, "marked_pr_sandbox", wraps=marked_pr_sandbox) as spy:
            first = MarkedIssueEvalCaseTest("test_every_assert_passes_on_a_good_run").sandbox()
            second = MarkedIssueResumeEvalCaseTest("test_every_assert_passes_on_a_good_run").sandbox()
        self.assertLessEqual(spy.call_count, 1)
        self.assertEqual(first[0], second[0])
        self.assertEqual(self.head_of(second[2]["PRE_WT"]), second[2]["PRE_WT_HEAD"])


class MarkedPrSetupTest(unittest.TestCase):
    """#1140: the marked-pr setup gives a marked issue 3, its pushed branch and an open pull request 7."""

    def sandbox(self):
        root, (repo, env) = restored("marked-pr", marked_pr_sandbox)
        return root, repo, env

    def git(self, path, *argv):
        return subprocess.run(["git", "-C", str(path), *argv], capture_output=True, text=True)

    def run_cmd(self, argv, root, **extra):
        return subprocess.run(argv, capture_output=True, text=True, timeout=60,
                              env={**os.environ, "PATH": f"{root}/bin:" + os.environ["PATH"],
                                   **extra})

    def test_the_branch_is_pushed_and_up_to_date(self):
        _, repo, env = self.sandbox()
        worktree = Path(env["PRE_WT"])
        tip = self.git(env["ORIGIN"], "rev-parse", "refs/heads/issue-3-rename-flag").stdout.strip()
        self.assertEqual(tip, env["PRE_WT_HEAD"])
        self.assertEqual(self.git(worktree, "rev-list", "--count", "main..HEAD").stdout.strip(), "1")
        self.assertEqual(self.git(worktree, "merge-base", "--is-ancestor", "main", "HEAD").returncode, 0)
        self.assertEqual(self.git(worktree, "status", "--porcelain").stdout, "")

    def test_the_issue_carries_one_look_marker(self):
        from agent_tools.delivery import look_marker
        _, repo, env = self.sandbox()
        text = (repo / "issues/003-mechanical.md").read_text(encoding="utf-8")
        body = text.partition("\n")[2]
        self.assertEqual(len(look_marker.read_look(body).criteria), 1)
        self.assertEqual(self.git(repo, "rev-parse", "main").stdout,
                         self.git(env["ORIGIN"], "rev-parse", "main").stdout)

    def test_the_reader_finds_the_look_needed_through_the_shim(self):
        root, _, env = self.sandbox()
        done = self.run_cmd(
            [sys.executable, "-m", "agent_tools.delivery.look_approval", "status", "--repo",
             "fixture/tinytask", "--issue", "3", "--pr", "7", "--head", env["PRE_WT_HEAD"]],
            root, PYTHONPATH=str(REPO_ROOT / "python"))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        out = json.loads(done.stdout)
        self.assertEqual(out["verdict"], "needed")
        self.assertTrue(out["covers"])

    def test_the_shim_serves_pull_request_seven(self):
        root, _, env = self.sandbox()
        gh = str(root / "bin/gh")
        viewed = self.run_cmd([gh, "pr", "view", "7", "--repo", "fixture/tinytask", "--json",
                               "number,state,headRefOid"], root)
        self.assertEqual(viewed.returncode, 0, viewed.stderr)
        self.assertEqual(json.loads(viewed.stdout),
                         {"number": 7, "state": "OPEN", "headRefOid": env["PRE_WT_HEAD"]})
        self.assertEqual(viewed.stdout.strip(),
                         '{"number":7,"state":"OPEN","headRefOid":"%s"}' % env["PRE_WT_HEAD"])
        listed = self.run_cmd([gh, "pr", "list", "--repo", "fixture/tinytask", "--json", "number"], root)
        self.assertEqual(listed.stdout.strip(), '[{"number":7}]')

    def test_the_shim_answers_the_checks_of_pull_request_seven(self):
        root, _, _ = self.sandbox()
        gh = str(root / "bin/gh")
        watched = self.run_cmd([gh, "pr", "checks", "7", "--repo", "fixture/tinytask", "--watch"], root)
        self.assertEqual(watched.returncode, 0, watched.stderr)
        self.assertIn("ci\tpass", watched.stdout.splitlines())
        fields = self.run_cmd([gh, "pr", "checks", "7", "--repo", "fixture/tinytask", "--json",
                               "name,bucket"], root)
        self.assertEqual(fields.returncode, 0, fields.stderr)
        self.assertEqual(json.loads(fields.stdout), [{"name": "ci", "bucket": "pass"}])
        rules = self.run_cmd([gh, "api", "repos/fixture/tinytask/rules/branches/main"], root)
        self.assertEqual(rules.returncode, 0, rules.stderr)
        self.assertEqual(json.loads(rules.stdout), [])
        required = self.run_cmd([gh, "pr", "checks", "7", "--repo", "fixture/tinytask", "--required"], root)
        self.assertEqual(required.returncode, 1)

    def test_the_shim_refuses_every_write(self):
        root, _, _ = self.sandbox()
        gh = str(root / "bin/gh")
        calls = (
            ["api", "-X", "POST", "repos/fixture/tinytask/issues/3/comments", "-f", "body=x"],
            ["api", "repos/fixture/tinytask/git/refs", "-f", "ref=refs/heads/x"],
            ["pr", "merge", "7", "--repo", "fixture/tinytask", "--merge"],
            ["pr", "create", "--repo", "fixture/tinytask"],
        )
        for argv in calls:
            with self.subTest(argv=argv):
                done = self.run_cmd([gh, *argv], root)
                self.assertEqual(done.returncode, 1)
                if argv[0] == "api":
                    self.assertIn("api writes are not available in this sandbox", done.stderr)
        logged = [json.loads(line) for line in
                  (root / "gh-calls.jsonl").read_text(encoding="utf-8").splitlines()]
        for argv in calls:
            self.assertIn({"argv": argv, "exit": 1}, logged)

    def test_without_pulls_the_shim_answers_as_before(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        repo, _ = fixture_sandbox(root)
        base = [sys.executable, "-I", str(GH_SHIM), "--repo", str(repo), "--log", str(root / "bare.jsonl")]
        self.assertEqual(self.run_cmd(base + ["pr", "list"], root).stdout.strip(), "[]")
        self.assertEqual(self.run_cmd(base + ["pr", "view", "7"], root).returncode, 1)
        self.assertEqual(self.run_cmd(base + ["pr", "checks", "7"], root).returncode, 1)

    def test_the_forge_claim_stand_in_logs_and_refuses(self):
        root, _, env = self.sandbox()
        stand_in = str(root / "bin/forge-claim")
        calls = (["land", "acquire", "--repo", "fixture/tinytask", "--branch", "main", "--sha",
                  env["PRE_WT_HEAD"], "--wait"],
                 ["release", "--repo", "fixture/tinytask", "--issue", "3"])
        for argv in calls:
            with self.subTest(argv=argv):
                done = self.run_cmd([stand_in, *argv], root)
                self.assertEqual(done.returncode, 1)
                self.assertIn("forge-claim shim:", done.stderr)
        logged = [json.loads(line) for line in
                  (root / "forge-claim-calls.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([entry["argv"] for entry in logged], [list(argv) for argv in calls])


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
    SPEC_EXISTS = "the spec is the issue's body, drafted in the git directory, and nothing was committed"
    SPEC_FORMAT = "the spec's Decisions section names no file path or line number"
    MAP_EXISTS = "the code map sits beside the spec draft, named after it"
    MAP_VALID = "the code map is well-formed and lists the three files the issue decides about"
    MAP_PLACED = "no code map is tracked or present in the working tree"
    NOT_STARTED = "the implementation was not started"

    def design_sandbox(self, tmp, *, decisions="The list command gains a state filter.", with_map=True):
        """The fixture after a good design run: the spec draft and its code map in .git, the
        issue file rewritten to the draft, and nothing committed."""
        repo, _, env = published_sandbox(tmp)
        spec_dir = Path(env["SPEC_DIR"])
        spec_dir.mkdir(parents=True)
        issue = repo / "issues/001-well-specified.md"
        text = issue.read_text(encoding="utf-8")
        draft = spec_dir / self.SPEC
        draft.write_text(
            f"# Design\n\n## Problem\n\nNo done-only view.\n\n## Decisions\n\n{decisions}\n\n"
            "## Test seams\n\nThe command line, as tests/test_cli.py drives it.\n\n"
            + text[text.index("## Proposal"):], encoding="utf-8")
        shutil.copy(draft, issue)
        if with_map:
            (spec_dir / self.SPEC.replace(".md", ".code-map.md")).write_text(
                f"# Code map: {self.SPEC}\n\n## The list command\n- Why: it gains the state filter\n"
                "- Code: `tinytask/cli.py` (`main`); `tinytask/model.py` (`STATES`)\n"
                "- Tests: `tests/test_cli.py` (`CliTest`)\n", encoding="utf-8")
        return repo, env

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

    def test_a_code_map_in_the_working_tree_fails_the_placement_and_working_tree_asserts(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = self.design_sandbox(Path(tmp).resolve())
            stray = repo / ".claude/specs" / self.SPEC.replace(".md", ".code-map.md")
            stray.parent.mkdir(parents=True, exist_ok=True)
            stray.write_text("# Code map\n", encoding="utf-8")
            done = self.grade(self.MAP_PLACED, repo, env)
            self.assertNotEqual(done.returncode, 0, done.stdout)
            self.assertIn(stray.name, done.stdout)
            done = self.grade(self.SPEC_EXISTS, repo, env)
            self.assertNotEqual(done.returncode, 0, done.stdout)
            self.assertIn("the working tree holds more than the issue's new body", done.stdout)
            for name in (self.SPEC_FORMAT, self.MAP_EXISTS, self.MAP_VALID):
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

    def test_an_issue_body_that_differs_from_the_draft_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = self.design_sandbox(Path(tmp).resolve())
            issue = repo / "issues/001-well-specified.md"
            issue.write_text(issue.read_text(encoding="utf-8") + "\nA later line.\n", encoding="utf-8")
            done = self.grade(self.SPEC_EXISTS, repo, env)
            self.assertNotEqual(done.returncode, 0, done.stdout)
            self.assertIn("the issue body is not the spec draft", done.stdout)

    def test_a_spec_committed_on_a_side_branch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = self.design_sandbox(Path(tmp).resolve())
            git = eval_git(repo)
            subprocess.run(git + ["switch", "-q", "-c", "side"], check=True)
            subprocess.run(git + ["commit", "-q", "-am", "docs: spec"], check=True)
            subprocess.run(git + ["switch", "-q", "main"], check=True)
            subprocess.run(git + ["branch", "-q", "-D", "side"], check=True)
            shutil.copy(Path(env["SPEC_DIR"]) / self.SPEC, repo / "issues/001-well-specified.md")
            done = self.grade(self.SPEC_EXISTS, repo, env)
            self.assertNotEqual(done.returncode, 0, done.stdout)
            self.assertIn("a commit was made", done.stdout)

    def test_a_changed_acceptance_criteria_section_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = self.design_sandbox(Path(tmp).resolve())
            for path in (Path(env["SPEC_DIR"]) / self.SPEC, repo / "issues/001-well-specified.md"):
                text = path.read_text(encoding="utf-8")
                path.write_text(re.sub(r"(?m)^- \[ \] \[code\] .*$", "- [ ] [code] changed",
                                       text, count=1), encoding="utf-8")
            done = self.grade(self.SPEC_EXISTS, repo, env)
            self.assertNotEqual(done.returncode, 0, done.stdout)
            self.assertIn("acceptance criteria", done.stdout)

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

    NO_SPEC = "no spec or plan was written"

    def test_a_spec_written_over_the_issue_file_fails(self):
        """#1441: the issue is the spec's home, so a rewritten issue file is a spec written."""
        for where in ("worktree", "checkout"):
            with self.subTest(where=where), tempfile.TemporaryDirectory() as tmp:
                repo, _, wgit, env = self.good_run(Path(tmp).resolve())
                base = Path(env["WT"]) if where == "worktree" else repo
                path = base / "issues/003-mechanical.md"
                path.write_text("# Design\n\n## Problem\n\nA spec.\n", encoding="utf-8")
                if where == "worktree":
                    subprocess.run(wgit + ["commit", "-qam", "feat: also the spec"], check=True,
                                   env={**os.environ, **QUIET_GIT})
                done = self.grade(self.NO_SPEC, repo, env)
                self.assertNotEqual(done.returncode, 0, done.stdout)
                self.assertIn("issues/003-mechanical.md", done.stdout)

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

    def test_a_spec_in_the_worktree_git_directory_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, _, env = self.good_run(Path(tmp).resolve())
            git_dir = subprocess.run(["git", "-C", env["WT"], "rev-parse", "--absolute-git-dir"],
                                     capture_output=True, text=True, check=True).stdout.strip()
            (Path(git_dir) / "specs").mkdir(parents=True)
            (Path(git_dir) / "specs/s.md").write_text("# spec\n", encoding="utf-8")
            self.assertNotEqual(self.grade("no spec or plan was written", repo, env).returncode, 0)

    def test_a_spec_in_the_worktree_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, _, env = self.good_run(Path(tmp).resolve())
            spec_dir = Path(env["WT"]) / ".claude/specs"
            spec_dir.mkdir(parents=True)
            (spec_dir / "s.md").write_text("# spec\n", encoding="utf-8")
            self.assertNotEqual(self.grade("no spec or plan was written", repo, env).returncode, 0)


class MarkedIssueEvalCaseTest(unittest.TestCase):
    """#1140: deliver-direct case 2 grades a stop at awaiting look on a marked issue."""

    CRITICAL = ("the look was read from the forge", "the checks of pull request 7 were waited for",
                "no land lock was sought",
                "the forge saw no write", "nothing merged and main unmoved",
                "nothing new was pushed", "the report names the stage awaiting look")
    NONCRITICAL = ("the report names the pull request and head",
                   "the report gives the plain reason", "the worktree is kept and clean")
    ISSUE_READ = {"argv": ["api", "repos/fixture/tinytask/issues/3"], "exit": 0}
    COMMENTS_READ = {"argv": ["api", "--paginate", "--slurp",
                              "repos/fixture/tinytask/issues/3/comments?per_page=100"], "exit": 0}
    CHECKS_READ = {"argv": ["pr", "checks", "7", "--repo", "fixture/tinytask", "--watch"], "exit": 0}
    WAITED = "the checks of pull request 7 were waited for"
    READ = "the look was read from the forge"
    LOCK = "no land lock was sought"
    WRITE = "the forge saw no write"
    MERGED = "nothing merged and main unmoved"
    PUSHED = "nothing new was pushed"
    STAGE = "the report names the stage awaiting look"
    PR_HEAD = "the report names the pull request and head"
    REASON = "the report gives the plain reason"
    KEPT = "the worktree is kept and clean"

    @staticmethod
    def log(path, *lines):
        Path(path).write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")

    def write_output(self, tmp, env, text):
        out = Path(tmp) / "output.txt"
        out.write_text(text, encoding="utf-8")
        env["OUT"] = str(out)

    def good_run(self, root, repo, env):
        self.log(Path(root) / "gh-calls.jsonl", self.ISSUE_READ, self.COMMENTS_READ, self.CHECKS_READ)
        (Path(root) / "forge-claim-calls.jsonl").unlink(missing_ok=True)
        self.write_output(root, env, "Stopped at stage awaiting look. Issue 3, pull request #7, head "
                          f"{env['PRE_WT_HEAD'][:7]}: issue 3 needs the owner's look before merge.")
        return repo, env

    def grade(self, name, repo, env):
        return run_assert(case_assert("deliver-direct", 2, name), repo, **env)

    def sandbox(self):
        root, (repo, env) = restored("marked-pr", marked_pr_sandbox)
        repo, env = self.good_run(root, repo, env)
        return root, repo, env

    def commit_empty(self, path):
        subprocess.run(["git", "-C", str(path), "commit", "-q", "--allow-empty", "-m", "x"],
                       check=True, env={**os.environ, **QUIET_GIT})

    def test_the_case_is_a_scripted_pipeline_case(self):
        case = find_case("deliver-direct", 2)
        self.assertEqual((case["name"], case["mode"]),
                         ("marked-issue-stops-at-awaiting-look", "pipeline"))
        self.assertEqual(case["setup"]["kind"], "marked-pr")
        self.assertEqual(tuple(check["name"] for check in case["asserts"]),
                         self.CRITICAL + self.NONCRITICAL)
        prompt = case["prompt"]
        for token in ("ResolvedProject", "issues/003-mechanical.md", "pull request 7", "step 6",
                      "`forge-claim acquire`", "`forge-claim renew`", "`forge-claim release`"):
            self.assertIn(token, prompt)
        self.assertNotIn("forge-claim land", prompt)
        self.assertRegex(prompt.lower(), r"\bstop\b")

    def test_every_assert_passes_on_a_good_run(self):
        _, repo, env = self.sandbox()
        for name in self.CRITICAL + self.NONCRITICAL:
            with self.subTest(name=name):
                done = self.grade(name, repo, env)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_the_look_read_needs_the_issue_and_its_comments(self):
        unrelated = {"argv": ["api", "repos/fixture/tinytask/pulls/7"], "exit": 0}
        cases = {"removed": None, "issue only": [self.ISSUE_READ],
                 "failed": [{**self.ISSUE_READ, "exit": 1}, {**self.COMMENTS_READ, "exit": 1}],
                 "unrelated read": [unrelated, self.COMMENTS_READ]}
        for label, lines in cases.items():
            with self.subTest(label=label):
                root, repo, env = self.sandbox()
                if lines is None:
                    (root / "gh-calls.jsonl").unlink()
                else:
                    self.log(root / "gh-calls.jsonl", *lines)
                self.assertNotEqual(self.grade(self.READ, repo, env).returncode, 0)

    def test_a_run_that_skips_the_check_wait_fails(self):
        unrelated = {"argv": ["pr", "checks", "8", "--repo", "fixture/tinytask", "--watch"], "exit": 0}
        cases = {"removed": None, "reads only": [self.ISSUE_READ, self.COMMENTS_READ],
                 "failed": [self.ISSUE_READ, self.COMMENTS_READ, {**self.CHECKS_READ, "exit": 1}],
                 "another pull request": [self.ISSUE_READ, self.COMMENTS_READ, unrelated]}
        for label, lines in cases.items():
            with self.subTest(label=label):
                root, repo, env = self.sandbox()
                if lines is None:
                    (root / "gh-calls.jsonl").unlink()
                else:
                    self.log(root / "gh-calls.jsonl", *lines)
                self.assertNotEqual(self.grade(self.WAITED, repo, env).returncode, 0)

    def test_a_land_lock_attempt_fails_even_when_refused(self):
        lock_read = {"argv": ["api", "repos/fixture/tinytask/git/ref/agent-locks/land/main"],
                     "exit": 1}
        release = {"argv": ["release", "--repo", "fixture/tinytask", "--issue", "3"]}
        for label in ("stand-in land call", "lock ref read", "exempt release only"):
            with self.subTest(label=label):
                root, repo, env = self.sandbox()
                if label == "stand-in land call":
                    self.log(root / "forge-claim-calls.jsonl",
                             {"argv": ["land", "acquire", "--repo", "fixture/tinytask", "--branch",
                                       "main", "--sha", env["PRE_WT_HEAD"], "--wait"]})
                elif label == "lock ref read":
                    self.log(root / "gh-calls.jsonl", self.ISSUE_READ, self.COMMENTS_READ, self.CHECKS_READ, lock_read)
                else:
                    self.log(root / "forge-claim-calls.jsonl", release)
                done = self.grade(self.LOCK, repo, env)
                if label == "exempt release only":
                    self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                else:
                    self.assertNotEqual(done.returncode, 0)

    def test_each_forge_write_fails_the_write_check(self):
        writes = (["pr", "merge", "7", "--repo", "fixture/tinytask", "--merge"],
                  ["api", "-X", "POST", "repos/fixture/tinytask/git/refs", "-f", "ref=x"],
                  ["api", "repos/fixture/tinytask/issues/3/comments", "-f", "body=x"],
                  ["api", "--method=POST", "repos/fixture/tinytask/git/refs", "--raw-field=ref=x"],
                  ["api", "repos/fixture/tinytask/issues/3/comments", "--field=body=x"],
                  ["api", "repos/fixture/tinytask/issues/3/comments", "--input=body.json"],
                  ["api", "-XPOST", "repos/fixture/tinytask/git/refs", "-fref=x"],
                  ["issue", "comment", "3", "--body", "x"])
        root, repo, env = self.sandbox()
        self.assertEqual(self.grade(self.WRITE, repo, env).returncode, 0)
        for argv in writes:
            with self.subTest(argv=argv):
                self.log(root / "gh-calls.jsonl", self.ISSUE_READ, self.COMMENTS_READ, self.CHECKS_READ,
                         {"argv": argv, "exit": 1})
                self.assertNotEqual(self.grade(self.WRITE, repo, env).returncode, 0)

    def test_a_moved_main_or_a_closed_pull_request_fails(self):
        with self.subTest(change="moved main"):
            _, repo, env = self.sandbox()
            self.commit_empty(repo)
            self.assertNotEqual(self.grade(self.MERGED, repo, env).returncode, 0)
        with self.subTest(change="closed pull request"):
            root, repo, env = self.sandbox()
            pulls = root / "forge/pulls.json"
            pulls_data = json.loads(pulls.read_text(encoding="utf-8"))
            pulls_data[0]["state"] = "MERGED"
            pulls.write_text(json.dumps(pulls_data), encoding="utf-8")
            self.assertNotEqual(self.grade(self.MERGED, repo, env).returncode, 0)

    def test_a_new_push_fails(self):
        _, repo, env = self.sandbox()
        self.commit_empty(env["PRE_WT"])
        subprocess.run(["git", "-C", env["PRE_WT"], "push", "-q", "origin", "issue-3-rename-flag"],
                       check=True, env={**os.environ, **QUIET_GIT})
        self.assertNotEqual(self.grade(self.PUSHED, repo, env).returncode, 0)

    def test_a_report_without_the_stage_fails(self):
        reports = (
            (self.STAGE, "Stopped. Issue 3, pull request #7, head {head}: issue 3 needs the owner's look before merge."),
            (self.PR_HEAD, "Stopped at stage awaiting look. Issue 3, head {head}: issue 3 needs the owner's look before merge."),
            (self.PR_HEAD, "Stopped at stage awaiting look. Issue 3, pull request #7: issue 3 needs the owner's look before merge."),
            (self.REASON, "Stopped at stage awaiting look. Issue 3, pull request #7, head {head}."),
        )
        for name, text in reports:
            with self.subTest(name=name, text=text):
                root, repo, env = self.sandbox()
                self.write_output(root, env, text.format(head=env["PRE_WT_HEAD"][:7]))
                self.assertNotEqual(self.grade(name, repo, env).returncode, 0)

    def test_a_removed_or_edited_worktree_fails(self):
        for label in ("edited", "removed"):
            with self.subTest(label=label):
                _, repo, env = self.sandbox()
                if label == "edited":
                    with open(Path(env["PRE_WT"]) / "README.md", "a", encoding="utf-8") as handle:
                        handle.write("edit\n")
                else:
                    subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force",
                                    env["PRE_WT"]], check=True)
                self.assertNotEqual(self.grade(self.KEPT, repo, env).returncode, 0)


class MarkedIssueResumeEvalCaseTest(unittest.TestCase):
    """#1140: deliver-direct case 3 grades a new session resuming at awaiting look on a stale approval."""

    NAMES = ("the resume read the pull request head from the forge",
             "the checks of pull request 7 were waited for", "no land lock was sought",
             "the forge saw no write", "nothing merged and main unmoved",
             "nothing new was pushed", "the report names the stage awaiting look",
             "the report names the pull request and head", "the report gives the plain reason",
             "the worktree is kept and clean")
    HEAD_READ = "the resume read the pull request head from the forge"
    WRITE = "the forge saw no write"
    VIEW = {"argv": ["pr", "view", "7", "--repo", "fixture/tinytask", "--json", "headRefOid"],
            "exit": 0}
    CHECKS = {"argv": ["pr", "checks", "7", "--repo", "fixture/tinytask", "--watch"], "exit": 0}
    WAITED = "the checks of pull request 7 were waited for"

    def sandbox(self):
        root, (repo, env) = restored("marked-pr", marked_pr_sandbox)
        MarkedIssueEvalCaseTest.log(root / "gh-calls.jsonl", self.VIEW, self.CHECKS)
        MarkedIssueEvalCaseTest().write_output(
            root, env, "Stopped at stage awaiting look. Issue 3, pull request #7, head "
            f"{env['PRE_WT_HEAD'][:7]}: issue 3 needs the owner's look before merge.")
        return root, repo, env

    def grade(self, name, repo, env):
        return run_assert(case_assert("deliver-direct", 3, name), repo, **env)

    def test_the_case_is_a_scripted_pipeline_case_on_the_marked_sandbox(self):
        case = find_case("deliver-direct", 3)
        self.assertEqual(case["setup"]["kind"], "marked-pr")
        self.assertEqual(tuple(check["name"] for check in case["asserts"]), self.NAMES)
        prompt = case["prompt"]
        for token in ("ResolvedProject", "pull request 7", "awaiting look", "approved, for head",
                      "`forge-claim acquire`"):
            self.assertIn(token, prompt)
        self.assertNotIn("step 6", prompt)
        self.assertNotIn("forge-claim land", prompt)
        self.assertRegex(prompt.lower(), r"\bstop\b")

    def test_every_assert_passes_on_a_good_run(self):
        _, repo, env = self.sandbox()
        for name in self.NAMES:
            with self.subTest(name=name):
                done = self.grade(name, repo, env)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_session_refused_by_the_open_pull_request_fails_the_head_read(self):
        for label, lines in (("no call", None),
                             ("a pr list only", [{"argv": ["pr", "list", "--search", "3"], "exit": 0}]),
                             ("a failed view", [{**self.VIEW, "exit": 1}])):
            with self.subTest(label=label):
                root, repo, env = self.sandbox()
                if lines is None:
                    (root / "gh-calls.jsonl").unlink()
                else:
                    MarkedIssueEvalCaseTest.log(root / "gh-calls.jsonl", *lines)
                self.assertNotEqual(self.grade(self.HEAD_READ, repo, env).returncode, 0)

    def test_a_run_that_skips_the_check_wait_fails(self):
        other = {"argv": ["pr", "checks", "8", "--repo", "fixture/tinytask", "--watch"], "exit": 0}
        for label, lines in (("view only", [self.VIEW]), ("failed", [self.VIEW, {**self.CHECKS, "exit": 1}]),
                             ("another pull request", [self.VIEW, other])):
            with self.subTest(label=label):
                root, repo, env = self.sandbox()
                MarkedIssueEvalCaseTest.log(root / "gh-calls.jsonl", *lines)
                self.assertNotEqual(self.grade(self.WAITED, repo, env).returncode, 0)

    def test_a_post_in_joined_forms_fails_the_write_check(self):
        post = ["api", "--method=POST", "repos/fixture/tinytask/issues/3/comments", "--raw-field=body=x"]
        root, repo, env = self.sandbox()
        MarkedIssueEvalCaseTest.log(root / "gh-calls.jsonl", self.VIEW, {"argv": post, "exit": 1})
        self.assertNotEqual(self.grade(self.WRITE, repo, env).returncode, 0)


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
