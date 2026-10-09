# Task 2: writing-plans eval 1 grades the absolute plan dir and exits on a failed precondition

**Files:**
- Modify: `home/common/agent-skills/skills/writing-plans/evals/evals.json` (case `"id": 1` asserts only)
- Test: `home/common/agent-skills/tests/test_eval_cases.py`

**Interfaces:**
- Consumes: Task 1's runner contract (asserts read `/dev/null`); no code from it.
- Produces: `run_assert(shell, cwd, *, stdin=subprocess.DEVNULL, **env)` in `test_eval_cases.py`; the module constant `FAIL_THEN_CONTINUE` (a compiled regex); the helper `writing_plans_fixture(tmp, *, with_plan=True) -> tuple[Path, dict]`. Task 3 adds a sibling corpus test beside the one this task adds.

**Invariants:**
- writing-plans case 1 keeps exactly its 8 asserts, names and order unchanged.
- No case-1 assert contains `$REPO/$SPEC_DIR` or `$REPO/$PLAN_DIR` (D1).
- No assert in any `evals.json` under either skill root matches `FAIL_THEN_CONTINUE` (D2).
- On a production-shaped repo holding a good committed plan, all 8 asserts pass; with no plan, the has-file, task-section and decision asserts fail (D7).
- The decision assert, with no plan and a non-empty stdin, fails with `no decision section` and reads nothing from stdin (D10).
- The task-section assert grades every `"$PLAN_DIR"/*.md` root with `plan_tasks_verifiable` (D9).

- [ ] **Step 1: Write the failing tests**

Change `run_assert` to (D10):

```python
def run_assert(shell, cwd, *, stdin=subprocess.DEVNULL, **env):
    """Run one assert snippet the way run-eval.sh grades it, stdin from /dev/null."""
    return subprocess.run(
        ["bash", "-c", f'source "$0"; {shell}', str(ASSERT_LIB)],
        cwd=cwd, env={"PATH": os.environ["PATH"], **env}, stdin=stdin,
        capture_output=True, text=True, timeout=60)
```

Add, at module level after `find_case`:

```python
FAIL_THEN_CONTINUE = re.compile(
    r'\|\|\s*fail\b(?:"(?:[^"\\]|\\.)*"|[^;{}"])*;\s*(?!(?:fi|done|esac)\b|[};])\S')


def writing_plans_fixture(tmp, *, with_plan=True):
    """A repo shaped like writing-plans eval 1's sandbox after a good run (D7)."""
    repo = Path(tmp) / "repo"
    (repo / "issues").mkdir(parents=True)
    shutil.copy(EVALS_DIR / "fixture-repo/issues/001-well-specified.md", repo / "issues")
    git = ["git", "-C", str(repo), "-c", "user.name=eval", "-c", "user.email=eval@example.invalid",
           "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "base"], check=True)
    subprocess.run(git + ["update-ref", "refs/remotes/origin/main", "HEAD"], check=True)
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
```

Add to `EvalCasesTest`:

```python
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
```

Add a new class after `EvalCasesTest`:

```python
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
```

The fixture root is `Path(tmp).resolve()` on purpose: on macOS the temp dir is a `/var` → `/private/var` symlink, and git refuses an absolute pathspec that does not sit under its real top level.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_eval_cases.py -k WritingPlans -k guarding_fail 2>&1 | tail -n 5`
Expected: `FAILED (failures=6)` over 4 tests — `test_every_assert_passes_on_a_good_plan` fails on `a plan artifact exists…` (`"$REPO/$PLAN_DIR"` never exists) and the decision assert; `test_plan_asserts_fail_when_no_plan_was_written` fails on the task-section assert (it passes vacuously with no plan); `test_a_failed_precondition_reads_no_stdin` sees `decision heading vanished`; `test_no_assert_runs_on_after_a_guarding_fail` flags case 1's task-section and decision asserts. (Planning ran these exact tests against the starting commit and then against Step 3's asserts.)

- [ ] **Step 3: Edit writing-plans case 1's asserts (per D1, D2, D9)**

Edit the JSON so that, decoded with `jq -r '.evals[] | select(.id==1) | .asserts[] | .shell'`, the asserts read as follows (names unchanged):

1. `a plan artifact exists…`: `has_file "$PLAN_DIR"/*.md`
2. `every task section…` (keep its `contract` field): `for f in "$PLAN_DIR"/*.md; do [ -f "$f" ] || { fail "no plan root under $PLAN_DIR"; exit 1; }; plan_tasks_verifiable "$f" || exit 1; done`
3. `the plan's acceptance map…`: unchanged.
4. `self-answered decisions…`: in the current text replace `"$REPO/$SPEC_DIR" "$REPO/$PLAN_DIR"` with `"$SPEC_DIR" "$PLAN_DIR"`, and `|| fail "no decision section under $SPEC_DIR or $PLAN_DIR"; awk` with `|| { fail "no decision section under $SPEC_DIR or $PLAN_DIR"; exit 1; }; awk`. The `awk` program and its operand stay byte-identical.
5. `the plan artifacts are committed`: unchanged.
6. `no placeholder text…`: replace `"$REPO/$PLAN_DIR"` with `"$PLAN_DIR"`; nothing else.
7, 8: unchanged.

Planning replayed exactly these eight on the retained sandbox `eval-writing-plans-1.DRRyFk` (a correct thin-index plan): all pass.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_eval_cases.py 2>&1 | tail -n 3`
Expected: `OK` (the whole module; `test_from_issue_asserts_never_prefix_an_absolute_artifact_dir` is still the from-issue-only version here).

Run: `if jq -r '.evals[] | select(.id==1) | .asserts[] | .shell' home/common/agent-skills/skills/writing-plans/evals/evals.json | grep -F '$REPO/$'; then exit 1; fi`
Expected: exit 0, no output (exits 1 at the starting commit).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/writing-plans/evals/evals.json home/common/agent-skills/tests/test_eval_cases.py
launch-commit … -- -m "fix(evals): writing-plans eval 1 grades the plan it names (#331)" -m "<trailers>"
```
