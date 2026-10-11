# Task 3: Eval cases for the code map and the plan dispatch

Background for a reader with no context. Each skill keeps its eval cases in `<skill>/evals/evals.json`. A `pipeline` case runs `claude -p` in a sandbox copy of the tinytask fixture (`home/common/agent-skills/evals/fixture-repo/`) and then grades the sandbox with shell `asserts`, which run with `evals/assert-lib.sh` sourced and see `REPO` (the sandbox checkout), `OUT` (the transcript), `SPEC_DIR` (the absolute specs directory, `.claude/specs` in the fixture), `BASE_MAIN` (main's SHA before the run) and `WT_COUNT` (worktrees created). Read `home/common/agent-skills/evals/README.md` once.

Issue 354 has the `design` skill leave a **code map** in the git directory, named after the spec file with `.code-map.md` in place of `.md`, and has the autonomous `from-issue` plan dispatch name that file. This task adds the two cases that measure it: the first eval file of `design`, and case 4 of `writing-plans`, which asks the model to print the plan-subagent prompt and greps the transcript (D7). It does not run them; Task 4 does.

**Files:**
- Create: `home/common/agent-skills/skills/design/evals/evals.json`
- Modify: `home/common/agent-skills/skills/writing-plans/evals/evals.json` (append case 4, extend `notes`)
- Test: `home/common/agent-skills/tests/test_eval_cases.py` (one class, inserted before the final `if __name__ == "__main__":` block)

**Interfaces:**
- Consumes, from Task 1: `spec_decisions_path_free <spec> <repo>` and `code_map_valid <map> <repo> [required-path...]` in `assert-lib.sh`; `fixture_sandbox(tmp) -> (repo, git)` in `test_eval_cases.py`. Existing: `run_assert`, `case_assert(skill, case_id, name)`, `find_case(skill, case_id)`, and the helpers `first_file`, `fail`, `out_matches`, `path_unchanged_since`.
- Produces, for Task 4:
  - `design` case 1, `design-leaves-a-code-map`, `mode: pipeline`, exactly six asserts in this order (the spec's numbering, which AC3 and AC4 cite):
    1. `a spec exists under the retained specs directory and is committed` (it also fails when the spec differs from its committed content)
    2. `the spec's Decisions section names no file path or line number`
    3. `the code map exists in the git directory, named after the spec`
    4. `the code map is well-formed and lists the three files the issue decides about`
    5. `no code map is tracked or present in the working tree`
    6. `the implementation was not started` (it also fails on an uncommitted or untracked file under the source or test directory)
  - `writing-plans` case 4, `auto-plan-dispatch-names-the-code-map`, `mode: pipeline`, two asserts: `the printed plan prompt names the spec's code map file`, `the repository is unchanged`.

**Invariants:**
- Asserts 3 and 4 derive the code map path the same way: `"$(git -C "$REPO" rev-parse --absolute-git-dir)/$(basename "$spec" .md).code-map.md"`, where `spec` is the first `*.md` under `$SPEC_DIR` (D1, D11).
- Assert 4 requires `tinytask/cli.py`, `tinytask/model.py` and `tests/test_cli.py` (D6).
- No assert prefixes `$SPEC_DIR` with `$REPO/`, and none runs on after a guarding `fail`: a guard is written `|| { …; exit 1; }` (two existing tests in the module enforce both for every case file).
- `writing-plans` cases 1, 2 and 3 are byte-identical after the change; the file keeps its two-space JSON indentation.
- No setup kind is added and no case names one (D7).

- [ ] **Step 1: Write the failing tests**

Insert this block into `home/common/agent-skills/tests/test_eval_cases.py`, immediately before the final `if __name__ == "__main__":` line, with two blank lines before and after it. Extract it, do not retype it (`T` is this task file's path, `SCRATCH` your scratch directory):

```bash
block task-3-tests "$T" > "$SCRATCH/task-3-tests.py"
python3 - "$SCRATCH/task-3-tests.py" <<'PY'
import pathlib, sys
path = pathlib.Path("home/common/agent-skills/tests/test_eval_cases.py")
text = path.read_text(encoding="utf-8")
marker = '\n\nif __name__ == "__main__":\n'
assert text.count(marker) == 1
block = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
path.write_text(text.replace(marker, "\n\n" + block.rstrip("\n") + "\n" + marker), encoding="utf-8")
PY
```

```python
# begin task-3-tests
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
# end task-3-tests
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_eval_cases.py -k CodeMapEvalCasesTest 2>&1 | tail -n 3`
Expected: FAIL — `Ran 8 tests` and a `FAILED (…)` line, none passing: the six `design` tests raise `AssertionError: no evals.json for design` (one of them in three subtests), and the two dispatch tests raise `StopIteration` or `has no assert named`, because `writing-plans` has no case 4.

- [ ] **Step 3: Add the cases**

Generate both files with this script; do not hand-write the JSON, whose shell snippets are easy to mis-escape. It refuses to run when `design/evals/evals.json` exists or `writing-plans` does not hold exactly cases 1, 2 and 3.

```bash
block task-3-cases "$T" > "$SCRATCH/task-3-cases.py"
python3 "$SCRATCH/task-3-cases.py" "$PWD"
```

```python
# begin task-3-cases
"""Issue 354: write the design eval file and add writing-plans eval 4. Usage: python3 cases.py <worktree root>"""
import json
import pathlib
import sys

SKILLS = pathlib.Path(sys.argv[1]) / "home/common/agent-skills/skills"
SPEC = 'spec=$(first_file "$SPEC_DIR"/*.md) || { echo "$spec"; exit 1; }; '
MAP = SPEC + 'map="$(git -C "$REPO" rev-parse --absolute-git-dir)/$(basename "$spec" .md).code-map.md"; '
REPORT = ('{"state":"complete","artifact":{"kind":"design-spec",'
          '"path":".claude/specs/2026-10-07-issue-3-rename-flag-design.md",'
          '"metrics":{"root_bytes":1520,"total_bytes":1520,"file_count":1,"largest_member_bytes":0},'
          '"budget_status":"within_budget"},"notes":"Spec committed and grilled; no ADR."}')

DESIGN = {
    "skill_name": "design",
    "notes": (
        "Eval 1 is a pipeline run against the shared tinytask fixture: `design` runs with autonomous "
        "decisions authorized on the well-specified issue, on the current branch, and stops after the "
        "spec. It grades the spec's form and the code map the skill leaves in the git directory, named "
        "after the spec. The three required files are fixture knowledge (#354 D6): the issue decides "
        "about the command-line module, the model module that enumerates the states, and the "
        "command-line test module."),
    "evals": [{
        "id": 1,
        "name": "design-leaves-a-code-map",
        "mode": "pipeline",
        "prompt": (
            "Use the `design` skill to design `issues/001-well-specified.md`.\n\n"
            "Resolve once into a retained ResolvedProject. The tracker capability is unsupported, so "
            "this file is the issue; refusal is fatal and no value is defaulted or inferred. Work on "
            "the current branch without a worktree. I authorize you to make every design decision "
            "yourself within this issue's scope: post no question round and wait for nothing. Produce "
            "and commit the design spec only; do not edit `tinytask/` or `tests/`.\n\n"
            "**Stop after the design.** Do not grill, plan or implement. Report the spec path."),
        "expected_output": (
            "One design spec under the retained specs directory, committed on the current branch, whose "
            "Decisions section names modules and behavior without file paths or line numbers. A code map "
            "for that spec in the repository's git directory, named after the spec file with "
            "`.code-map.md` in place of `.md`: one entry per module the spec decides about, each with a "
            "Why line and a Code line of tracked paths, covering `tinytask/cli.py`, `tinytask/model.py` "
            "and `tests/test_cli.py`. No code map is tracked or present in the working tree, and no "
            "source or test file is touched."),
        "asserts": [
            {"name": "a spec exists under the retained specs directory and is committed",
             "shell": SPEC + '[ -n "$(git -C "$REPO" log --oneline origin/main..HEAD -- "$spec" 2>/dev/null)" ] '
                             '|| { fail "the spec is not committed on the current branch: $spec"; exit 1; }; '
                             '[ -z "$(git -C "$REPO" status --porcelain -- "$spec")" ] '
                             '|| fail "the spec differs from its committed content: $spec"'},
            {"name": "the spec's Decisions section names no file path or line number",
             "shell": SPEC + 'spec_decisions_path_free "$spec" "$REPO"'},
            {"name": "the code map exists in the git directory, named after the spec",
             "shell": MAP + '[ -f "$map" ] || fail "no code map at $map"'},
            {"name": "the code map is well-formed and lists the three files the issue decides about",
             "shell": MAP + 'code_map_valid "$map" "$REPO" tinytask/cli.py tinytask/model.py tests/test_cli.py'},
            {"name": "no code map is tracked or present in the working tree",
             "shell": "found=$(git -C \"$REPO\" ls-files -- '*.code-map.md'; "
                      "find \"$REPO\" -name .git -prune -o -name '*.code-map.md' -print); "
                      '[ -z "$found" ] || fail "a code map outside the git directory: $found"'},
            {"name": "the implementation was not started",
             "shell": 'path_unchanged_since "$REPO" origin/main tinytask tests || exit 1; '
                      'extra=$(git -C "$REPO" status --porcelain -- tinytask tests); '
                      '[ -z "$extra" ] || fail "uncommitted or untracked files under tinytask or tests: $extra"'},
        ],
    }],
}

DISPATCH = {
    "id": 4,
    "name": "auto-plan-dispatch-names-the-code-map",
    "mode": "pipeline",
    "prompt": (
        "Change nothing in this repository: no file edit, no commit, no worktree, and dispatch no "
        "subagent.\n\n"
        "You are the `from-issue` controller in autonomous mode (`--auto`) for issue 3, at the start of "
        "Phase 4, with the retained ResolvedProject already resolved. The worktree is "
        "`.worktrees/worktree-issue-3-rename-flag`. The design subagent returned this validated producer "
        "report:\n\n" + REPORT + "\n\n"
        "Read the `from-issue` skill's autonomous-mode instructions for the plan subagent, then print, in "
        "full, the exact prompt you would dispatch to that subagent. Then stop."),
    "expected_output": (
        "The full plan-subagent prompt as the autonomous `from-issue` controller would dispatch it. It "
        "hands over the validated spec root, metrics and notes, and names the spec's code map by file "
        "name, `2026-10-07-issue-3-rename-flag-design.code-map.md`, as a file in the worktree's git "
        "directory. Nothing in the repository changes and no subagent is dispatched."),
    "asserts": [
        {"name": "the printed plan prompt names the spec's code map file",
         "shell": "out_matches '2026-10-07-issue-3-rename-flag-design\\.code-map\\.md'"},
        {"name": "the repository is unchanged",
         "shell": '[ -z "$(git -C "$REPO" status --porcelain)" ] || '
                  '{ fail "the working tree changed: $(git -C "$REPO" status --porcelain | tr \'\\n\' \' \')"; exit 1; }; '
                  '[ "$(git -C "$REPO" rev-parse HEAD)" = "$BASE_MAIN" ] || { fail "HEAD moved off $BASE_MAIN"; exit 1; }; '
                  '[ "$WT_COUNT" -eq 0 ] || fail "created $WT_COUNT worktree(s)"'},
    ],
}
NOTE = (" Eval 4 asks for the autonomous `from-issue` plan-subagent prompt and greps the transcript for "
        "the spec's code map file name (#354 D7); eval 1, which has no code map, is the check that an "
        "absent one changes nothing.")


def dump(path, document):
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


design_path = SKILLS / "design/evals/evals.json"
if design_path.exists():
    sys.exit(f"{design_path} already exists: stop and report")
plans_path = SKILLS / "writing-plans/evals/evals.json"
plans = json.loads(plans_path.read_text(encoding="utf-8"))
if [case["id"] for case in plans["evals"]] != [1, 2, 3]:
    sys.exit(f"{plans_path}: expected cases 1, 2 and 3 only: stop and report")
design_path.parent.mkdir()
dump(design_path, DESIGN)
plans["notes"] += NOTE
plans["evals"].append(DISPATCH)
dump(plans_path, plans)
print("wrote", design_path, "and case 4 of", plans_path)
# end task-3-cases
```

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_eval_cases.py 2>&1 | tail -n 3`
Expected: PASS — `Ran 38 tests` and `OK`. A count below 38 means the test block was not inserted; any failure means the task is incomplete.

Run: `jq -e '.evals | length == 1 and .[0].id == 1 and (.[0].asserts | length == 6)' home/common/agent-skills/skills/design/evals/evals.json && jq -e '[.evals[].id] == [1,2,3,4] and (.evals[3].asserts | length == 2)' home/common/agent-skills/skills/writing-plans/evals/evals.json && git diff --stat -- home/common/agent-skills/skills/writing-plans/evals/evals.json | tail -n 1`
Expected: `true`, `true`, then `1 file changed, 18 insertions(+), 1 deletion(-)` — the one deleted line is the `notes` line, so cases 1 to 3 are untouched.

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_skill_lint.py 2>&1 | tail -n 3`
Expected: PASS — `OK`; these modules read every eval file and lint the skill tree, which now holds `design/evals/`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/design/evals/evals.json home/common/agent-skills/skills/writing-plans/evals/evals.json home/common/agent-skills/tests/test_eval_cases.py
git commit -m "test(evals): add the code map and plan-dispatch eval cases (#354)"
```
