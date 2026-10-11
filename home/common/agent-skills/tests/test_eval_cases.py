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

    def test_orchestrate_ledger_assert_requires_a_ledger_shape(self):
        shell = case_assert("orchestrate-issues", 7, "a run ledger exists and records no attempt")
        ledger = {"admission": {"claims": [], "releases": 0, "route": "claude-code"},
                  "created_at": "2026-10-07T10:09:59Z", "issues": {}, "prior_run": None,
                  "run_id": "orch-1-3-20261007", "schema_version": 6,
                  "updated_at": "2026-10-07T10:11:00Z", "workers": []}
        cases = (
            ("the kept sandboxes' ledger shape", ledger, True),
            ("an empty object", {}, False),
            ("issues that is not an object", {**ledger, "issues": []}, False),
            ("an issue with an attempt", {**ledger, "issues": {"1": {"attempts": [{"n": 1}]}}}, False),
            ("an issue without an attempts array", {**ledger, "issues": {"1": {}}}, False),
            ("an issue with an empty attempts array", {**ledger, "issues": {"1": {"attempts": []}}}, True),
            ("a claimed role set", {**ledger, "admission": {**ledger["admission"], "claims": [{}]}}, False),
            ("a registered worker", {**ledger, "workers": [{}]}, False),
        )
        for label, state, passes in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as tmp:
                run_dir = Path(tmp) / ".superpowers/workflows/run"
                run_dir.mkdir(parents=True)
                (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
                done = run_assert(shell, tmp, REPO=tmp)
                self.assertEqual(done.returncode == 0, passes, done.stdout + done.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            with self.subTest(case="no ledger at all"):
                self.assertNotEqual(run_assert(shell, tmp, REPO=tmp).returncode, 0)

    def test_from_issue_no_artifact_asserts_treat_empty_and_missing_dirs_as_empty(self):
        name = "no spec or plan was written"
        for case_id in (2, 3):
            shell = case_assert("from-issue", case_id, name)
            with tempfile.TemporaryDirectory() as tmp:
                repo, pre_wt = Path(tmp) / "repo", Path(tmp) / "pre"
                repo.mkdir()
                pre_wt.mkdir()
                env = {"REPO": str(repo), "PRE_WT": str(pre_wt),
                       "SPEC_DIR": str(repo / "docs/specs"), "PLAN_DIR": str(repo / "docs/plans")}
                with self.subTest(case=case_id, dirs="missing"):
                    done = run_assert(shell, repo, **env)
                    self.assertEqual(done.returncode, 0, done.stdout)
                for base in (repo, pre_wt):
                    (base / "docs/specs").mkdir(parents=True)
                    (base / "docs/plans").mkdir(parents=True)
                with self.subTest(case=case_id, dirs="present and empty"):
                    done = run_assert(shell, repo, **env)
                    self.assertEqual(done.returncode, 0, done.stdout)
                (repo / "docs/plans/p.md").write_text("plan\n", encoding="utf-8")
                with self.subTest(case=case_id, dirs="a plan was written"):
                    self.assertNotEqual(run_assert(shell, repo, **env).returncode, 0)

    def test_from_issue_fog_gate_case_fails_on_an_acquisition_stop(self):
        # D22: case 2 keeps --auto, so on main it stops at direct-owner acquisition
        # (tracker kind none) before the fog gate; an assert must see that stop.
        case = find_case("from-issue", 2)
        self.assertIn("--auto", case["prompt"])
        self.assertEqual(case.get("expected_today"), "fail")
        self.assertRegex(case.get("note", ""), r"tracker")
        shell = case_assert("from-issue", 2, "the run reached the fog gate rather than stopping at acquisition")
        transcripts = {
            "the opus acquisition stop": (
                "I stopped issue 2 during acquisition, before Phase 0 formally began.\n"
                '{"interface_version":2,"issue":2,"kind":"observe","requirements":[{"kind":"tracker"}],"run_id":null}\n',
                False),
            "the sonnet acquisition stop": (
                "I stopped at the Phase 0 fog gate.\n**Acquisition:** the first `workflow-state direct-owner` "
                "call returned `observe` with a `tracker` requirement and no `run_id`.\n", False),
            "a builder refusal": ("build-delivery refused: tracker kind 'none' is unsupported\n", False),
            "a bare acquisition-blocked stop": (
                "Cannot proceed: acquisition is blocked because the tracker capability is unsupported.\n",
                False),
            "a stop that names no fog decision": (
                "Cannot proceed: the tracker capability is unsupported, so I am stopping here.\n", False),
            "a fog-gate stop": (
                "I stopped at the Phase 0 fog gate: the issue bundles five asks and has no "
                "acceptance criteria.\n", True),
        }
        for label, (text, passes) in transcripts.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "output.txt"
                out.write_text(text, encoding="utf-8")
                done = run_assert(shell, tmp, OUT=str(out))
                self.assertEqual(done.returncode == 0, passes, done.stdout + done.stderr)

    def test_from_issue_preflight_case_takes_the_ledger_free_route(self):
        # D22 (after D20): the Phase 0 pre-flight runs on every route, so case 3 drops
        # the literal --auto token and authorizes autonomous decisions instead.
        for case_id in (1, 3):
            prompt = find_case("from-issue", case_id)["prompt"]
            with self.subTest(case=case_id):
                self.assertNotIn("--auto", prompt)
                self.assertIn("I authorize you to make every design and plan decision yourself", prompt)
                self.assertIn("**Stop after Phase 5.**", prompt)


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
    """#354: the design case and the writing-plans dispatch case grade a crafted sandbox."""

    SPEC = "2026-10-11-list-state-design.md"
    SPEC_EXISTS = "a spec exists under the retained specs directory and is committed"
    SPEC_FORMAT = "the spec's Decisions section names no file path or line number"
    MAP_EXISTS = "the code map exists in the git directory, named after the spec"
    MAP_VALID = "the code map is well-formed and lists the three files the issue decides about"
    MAP_PLACED = "no code map is tracked or present in the working tree"
    NOT_STARTED = "the implementation was not started"
    PROMPT_NAMES = "the printed plan prompt names the spec's code map file"
    UNCHANGED = "the repository is unchanged"

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

    def dispatch_env(self, tmp, transcript):
        repo, _ = fixture_sandbox(tmp)
        out = Path(tmp) / "output.txt"
        out.write_text(transcript, encoding="utf-8")
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
        return repo, {"REPO": str(repo), "OUT": str(out), "BASE_MAIN": head, "WT_COUNT": "0"}

    def test_the_dispatch_case_greps_the_transcript_for_the_code_map_name(self):
        case = find_case("writing-plans", 4)
        self.assertEqual(case["mode"], "pipeline")
        self.assertEqual([check["name"] for check in case["asserts"]],
                         [self.PROMPT_NAMES, self.UNCHANGED])
        named = "Read `2026-10-07-issue-3-rename-flag-design.code-map.md` in the worktree's git directory.\n"
        for transcript, passes in ((named, True), ("Give it the spec root and metrics.\n", False)):
            with self.subTest(passes=passes), tempfile.TemporaryDirectory() as tmp:
                repo, env = self.dispatch_env(Path(tmp).resolve(), transcript)
                done = run_assert(case_assert("writing-plans", 4, self.PROMPT_NAMES), repo, **env)
                self.assertEqual(done.returncode == 0, passes, done.stdout + done.stderr)

    def test_the_dispatch_case_fails_on_a_changed_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = self.dispatch_env(Path(tmp).resolve(), "")
            shell = case_assert("writing-plans", 4, self.UNCHANGED)
            self.assertEqual(run_assert(shell, repo, **env).returncode, 0)
            (repo / "NOTES.md").write_text("scratch\n", encoding="utf-8")
            done = run_assert(shell, repo, **env)
            self.assertNotEqual(done.returncode, 0, done.stdout)
            self.assertIn("NOTES.md", done.stdout)


if __name__ == "__main__":
    unittest.main()
