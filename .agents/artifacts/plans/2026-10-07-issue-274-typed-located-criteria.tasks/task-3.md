# Task 3: Grade the acceptance map in the fixture-001 evals

Per D6, D7, D10. Measures issue #274 AC3.

**Files:**
- Modify: `home/common/agent-skills/evals/assert-lib.sh`
- Modify: `home/common/agent-skills/evals/fixture-repo/issues/001-well-specified.md`
- Modify: `home/common/agent-skills/skills/from-issue/evals/evals.json`
- Modify: `home/common/agent-skills/skills/writing-plans/evals/evals.json`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (append one new class)

**Interfaces:**
- Consumes: the criterion-line shape `- [ ] [<kind>] <outcome> — measured: <where>` and the map shape `| AC | Kind | Task | Check |` / `None — no acceptance criteria.` (both fixed by the spec, D1–D4); the test module's `REPO_ROOT`.
- Produces: the shell function `acceptance_map_covers <plan-root> <issue-file>` in `assert-lib.sh` — exit 0 when covered, non-zero with one reason per line on stdout otherwise (the library's convention); the eval assert named `the plan's acceptance map has one row per issue criterion` in from-issue eval 1 and writing-plans eval 1.

**Invariants:**
- Criteria are counted only between the issue's `## Acceptance criteria` line and the next `## ` line, and only at column 0: `- [ ] `/`- [x] `/`- [X] ` items and `<n>. ` items. Continuation lines never count.
- A `- [ ] [code|evidence|human] ` item is tagged with that kind; every other counted item is untagged.
- Map row `i` (header `AC` and `|---|` separator skipped) must be exactly `AC<i>`; a tagged criterion's kind cell equals its tag exactly (so `code (classified)` on a tagged item fails); an untagged one's kind cell matches `^(code|evidence|human) \(classified\)$`; fewer rows than criteria fails.
- With zero criteria the helper passes only when the map holds the line `None — no acceptance criteria.` and no rows (per D10).
- Both headings match case-insensitively; a missing `## Acceptance map` fails.
- BSD awk compatible: no `gensub`; kinds pass to the second awk comma-joined through `-v`, never newline-joined.
- Fixture 001 keeps its seven criteria in the same order and meaning; fixtures 002/003 are untouched.

- [ ] **Step 1: Write the failing test**

Append immediately before `if __name__ == "__main__":` in `test_workflow_skill_contracts.py` (after any class an earlier task appended):

```python
class AcceptanceMapEvalGradingTest(unittest.TestCase):
    """#274 AC3: fixture 001 is tagged and both evals grade its map (D6, D7, D10)."""

    ASSERT_LIB = REPO_ROOT / "home/common/agent-skills/evals/assert-lib.sh"
    FIXTURE = (REPO_ROOT
               / "home/common/agent-skills/evals/fixture-repo/issues/001-well-specified.md")
    EVALS = (
        REPO_ROOT / "home/common/agent-skills/skills/from-issue/evals/evals.json",
        REPO_ROOT / "home/common/agent-skills/skills/writing-plans/evals/evals.json",
    )
    ASSERT_NAME = "the plan's acceptance map has one row per issue criterion"
    TAGGED = ("# Issue\n\n## Acceptance criteria\n\n"
              "- [ ] [code] a — measured: t\n"
              "- [ ] [evidence] b — measured: cmd, idle, ≤ 5 s\n"
              "- [x] [human] c — measured: the user, on mbp\n\n"
              "## Blocked by\n\nNone\n")
    LEGACY = "# Issue\n\n## Acceptance criteria\n\n1. a\n   more of a\n2. b\n\n## Notes\n"
    EMPTY = "# Issue\n\n## Acceptance criteria\n\n## Notes\n"

    @staticmethod
    def plan(*rows):
        return ("# Plan\n\n## Task index\n\nTask 1 — x — f — full — [task-1.md](p.tasks/task-1.md)\n\n"
                "## Acceptance map\n\n| AC | Kind | Task | Check |\n|----|------|------|-------|\n"
                + "".join(f"| {ac} | {kind} | Task 1 | check |\n" for ac, kind in rows)
                + "\n## Decisions\n")

    def covers(self, plan_text, issue_text=None, issue_path=None):
        with tempfile.TemporaryDirectory() as temporary:
            plan_path = Path(temporary) / "plan.md"
            plan_path.write_text(plan_text, encoding="utf-8")
            if issue_path is None:
                issue_path = Path(temporary) / "issue.md"
                issue_path.write_text(issue_text, encoding="utf-8")
            return subprocess.run(
                ["bash", "-c", 'source "$0"; acceptance_map_covers "$1" "$2"',
                 str(self.ASSERT_LIB), str(plan_path), str(issue_path)],
                check=False, capture_output=True, text=True)

    def test_a_conforming_tagged_map_passes(self):
        result = self.covers(self.plan(("AC1", "code"), ("AC2", "evidence"), ("AC3", "human")),
                             self.TAGGED)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_each_structural_gap_fails_with_a_reason(self):
        cases = {
            "missing row": (("AC1", "code"), ("AC2", "evidence")),
            "duplicate row": (("AC1", "code"), ("AC1", "code"), ("AC2", "evidence"),
                              ("AC3", "human")),
            "out of order": (("AC2", "evidence"), ("AC1", "code"), ("AC3", "human")),
            "kind contradicts tag": (("AC1", "evidence"), ("AC2", "evidence"),
                                     ("AC3", "human")),
            "tagged kind reclassified": (("AC1", "code (classified)"), ("AC2", "evidence"),
                                         ("AC3", "human")),
        }
        for name, rows in cases.items():
            with self.subTest(case=name):
                result = self.covers(self.plan(*rows), self.TAGGED)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stdout.strip(), "a failing helper names its reason")

    def test_legacy_numbered_criteria_need_a_classified_kind(self):
        good = self.covers(self.plan(("AC1", "code (classified)"), ("AC2", "human (classified)")),
                           self.LEGACY)
        self.assertEqual(good.returncode, 0, good.stdout)
        bare = self.covers(self.plan(("AC1", "code"), ("AC2", "human (classified)")),
                           self.LEGACY)
        self.assertNotEqual(bare.returncode, 0)

    def test_no_criteria_pass_only_on_the_none_line(self):
        none = "# Plan\n\n## Acceptance map\n\nNone — no acceptance criteria.\n"
        self.assertEqual(self.covers(none, self.EMPTY).returncode, 0)
        self.assertNotEqual(self.covers("# Plan\n\n## Acceptance map\n", self.EMPTY).returncode, 0)
        self.assertNotEqual(self.covers("# Plan\n\n## Task index\n", self.TAGGED).returncode, 0)

    def test_fixture_001_has_seven_tagged_code_criteria_graded_by_the_helper(self):
        text = self.FIXTURE.read_text(encoding="utf-8")
        section = text[text.index("## Acceptance criteria\n"):]
        section = section[:section.index("\n## ", 1)]
        items = [line for line in section.splitlines()
                 if re.match(r"^(- \[[ xX]\] |[0-9]+\. )", line)]
        self.assertEqual(len(items), 7)
        for line in items:
            with self.subTest(line=line):
                self.assertRegex(
                    line, r"^- \[ \] \[code\] \S.* — measured: .*tests/test_cli\.py$")
        result = self.covers(self.plan(*((f"AC{n}", "code") for n in range(1, 8))),
                             issue_path=self.FIXTURE)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_both_fixture_001_evals_call_the_helper(self):
        for path in self.EVALS:
            with self.subTest(evals=path.parent.parent.name):
                case = next(item for item in json.loads(path.read_text(encoding="utf-8"))["evals"]
                            if item["id"] == 1)
                shells = [item["shell"] for item in case["asserts"]
                          if item["name"] == self.ASSERT_NAME]
                self.assertEqual(len(shells), 1)
                self.assertIn("acceptance_map_covers", shells[0])
                self.assertIn('"$REPO/issues/001-well-specified.md"', shells[0])

    def test_both_eval_assert_shells_grade_a_plan_under_harness_paths(self):
        # run-eval.sh exports PLAN_DIR as the resolver's ABSOLUTE path under
        # $REPO and runs each shell as `cd $REPO && bash -c "source lib; …"`;
        # from-issue's plan lands in the worktree at the same relative suffix.
        full = self.plan(*((f"AC{n}", "code") for n in range(1, 8)))
        short = self.plan(*((f"AC{n}", "code") for n in range(1, 7)))
        for path in self.EVALS:
            case = next(item for item in json.loads(path.read_text(encoding="utf-8"))["evals"]
                        if item["id"] == 1)
            shell = next(item["shell"] for item in case["asserts"]
                         if item["name"] == self.ASSERT_NAME)
            for label, text, passes in (("complete", full, True), ("missing row", short, False)):
                with self.subTest(evals=path.parent.parent.name, plan=label), \
                        tempfile.TemporaryDirectory() as temporary:
                    repo = Path(temporary) / "repo"
                    worktree = Path(temporary) / "wt"
                    plan_dir = repo / ".agents/artifacts/plans"
                    (repo / "issues").mkdir(parents=True)
                    (repo / "issues/001-well-specified.md").write_text(
                        self.FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
                    owner = (worktree if "from-issue" in str(path) else repo)
                    (owner / ".agents/artifacts/plans").mkdir(parents=True)
                    (owner / ".agents/artifacts/plans/plan.md").write_text(text, encoding="utf-8")
                    env = dict(os.environ, REPO=str(repo), WT=str(worktree),
                               PLAN_DIR=str(plan_dir))
                    result = subprocess.run(
                        ["bash", "-c", f"source '{self.ASSERT_LIB}'; {shell}"],
                        cwd=repo, env=env, check=False, capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, passes,
                                     result.stdout + result.stderr)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH=python timeout 300 python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py -k AcceptanceMapEvalGrading 2>&1 | tail -5`
Expected: FAILED — the helper is undefined (`acceptance_map_covers: command not found` on stderr, so passing cases fail and the gap cases fail for an empty stdout reason), fixture 001 has numbered untagged criteria, and neither eval carries the named assert: all 6 tests fail.

- [ ] **Step 3: Write the minimal implementation**

1. Append to `home/common/agent-skills/evals/assert-lib.sh`, after `path_unchanged_since`, exactly (this is the decision-bearing wire format of D7/D10, so it is given in full):

```bash

# acceptance_map_covers <plan-root> <issue-file> — the plan root's `## Acceptance map`
# holds rows AC1..AC<n>, each once and in issue order, for the n column-0 criterion
# items (`- [ ]`/`- [x]` or `<n>.`) under the issue's `## Acceptance criteria`. A row's
# kind equals the issue's `[code|evidence|human]` tag, or is `<kind> (classified)` for
# an untagged item. With no criteria the map must be the single line
# `None — no acceptance criteria.` Headings match case-insensitively.
acceptance_map_covers() {
  local plan="$1" issue="$2" kinds
  [ -f "$plan" ] || fail "not a file: $plan" || return 1
  [ -f "$issue" ] || fail "not a file: $issue" || return 1
  kinds=$(awk '
    tolower($0) == "## acceptance criteria" { inside = 1; next }
    inside && /^## / { inside = 0 }
    inside && /^- \[[ xX]\] / {
      kind = "untagged"
      if (match($0, /^- \[[ xX]\] \[(code|evidence|human)\] /)) kind = substr($0, 8, RLENGTH - 9)
      out = out (out == "" ? "" : ",") kind
      next
    }
    inside && /^[0-9]+\. / { out = out (out == "" ? "" : ",") "untagged" }
    END { print out }
  ' "$issue")
  awk -v kinds="$kinds" '
    BEGIN { n = (kinds == "" ? 0 : split(kinds, want, ",")) }
    tolower($0) == "## acceptance map" { inside = 1; found = 1; next }
    inside && /^## / { inside = 0 }
    inside && $0 == "None — no acceptance criteria." { none = 1; next }
    inside && /^\|/ {
      split($0, cells, "|")
      id = cells[2]; kind = cells[3]
      gsub(/^[ \t]+|[ \t]+$/, "", id); gsub(/^[ \t]+|[ \t]+$/, "", kind)
      if (tolower(id) == "ac" || id ~ /^[-: ]*$/) next
      rows++
      if (id != "AC" rows) { print "row " rows " is " id ", expected AC" rows; bad++; next }
      if (rows > n) { print id ": no issue criterion for this row"; bad++; next }
      if (want[rows] == "untagged") {
        if (kind !~ /^(code|evidence|human) \(classified\)$/) { print id ": untagged criterion needs <kind> (classified), got " kind; bad++ }
      } else if (kind != want[rows]) { print id ": kind " kind " contradicts the issue tag " want[rows]; bad++ }
    }
    END {
      if (!found) { print "heading not found: ## Acceptance map"; exit 1 }
      if (n == 0) {
        if (!none || rows > 0) { print "issue has no criteria; the map must be the single line: None — no acceptance criteria."; exit 1 }
        exit 0
      }
      if (rows < n) { print "map has " rows " rows for " n " criteria"; bad++ }
      exit (bad > 0)
    }
  ' "$plan"
}
```

2. In `home/common/agent-skills/evals/fixture-repo/issues/001-well-specified.md`, replace the seven numbered items under `## Acceptance criteria` (through `7. Tests cover each of 1-5 …`) with exactly these seven single-line items (per D6), leaving every other section unchanged:

```markdown
- [ ] [code] `list --state done` prints only tasks whose state is `done`, in id order, in the existing `id<TAB>state<TAB>title` shape — measured: tests/test_cli.py
- [ ] [code] `list --state open` prints exactly what bare `list` prints for the same task file — measured: tests/test_cli.py
- [ ] [code] `list --state wibble` exits non-zero and writes a message naming the valid states to stderr, and nothing is printed to stdout — measured: tests/test_cli.py
- [ ] [code] `list --all --state done` exits non-zero with a usage error — measured: tests/test_cli.py
- [ ] [code] Bare `list` and `list --all` behave exactly as they do today, with no change — measured: tests/test_cli.py
- [ ] [code] `--state` appears in `tinytask list --help` — measured: a `--help` output test added to tests/test_cli.py
- [ ] [code] Tests cover each of criteria 1-5 with exact expected output lines — measured: tests/test_cli.py
```

3. In `home/common/agent-skills/skills/from-issue/evals/evals.json`, eval `id` 1, insert directly after the assert named `every plan task has a falsifiable verification line`:

```json
{
  "name": "the plan's acceptance map has one row per issue criterion",
  "shell": "acceptance_map_covers \"$(first_file \"$WT/${PLAN_DIR#\"$REPO\"/}\"/*.md)\" \"$REPO/issues/001-well-specified.md\""
}
```

and append to that eval's `expected_output` the sentence ` The plan root carries an Acceptance map with rows AC1 to AC7, each of kind code, each owned by one task.`

4. In `home/common/agent-skills/skills/writing-plans/evals/evals.json`, eval `id` 1, insert directly after the assert named `every task section (inline or per-task brief) has a falsifiable verification line`:

```json
{
  "name": "the plan's acceptance map has one row per issue criterion",
  "shell": "acceptance_map_covers \"$(first_file \"$PLAN_DIR\"/*.md)\" \"$REPO/issues/001-well-specified.md\""
}
```

and append the same sentence to that eval's `expected_output`. Keep both files' existing indentation and key order; validate with `python3 -m json.tool <file> >/dev/null`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python timeout 300 python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py -k AcceptanceMapEvalGrading 2>&1 | tail -3`
Expected: `Ran 6 tests` … `OK`

Run: `for f in home/common/agent-skills/skills/from-issue/evals/evals.json home/common/agent-skills/skills/writing-plans/evals/evals.json; do python3 -m json.tool "$f" >/dev/null || exit 1; done; git diff --quiet HEAD -- home/common/agent-skills/evals/fixture-repo/issues/002-fuzzy.md home/common/agent-skills/evals/fixture-repo/issues/003-mechanical.md && echo untouched`
Expected: `untouched`, no JSON error.

Run: `PYTHONPATH=python timeout 600 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -3`
Expected: `OK` — `test_live_evals_grade_strict_policy_and_direct_review` still passes over the edited evals.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/evals/assert-lib.sh home/common/agent-skills/evals/fixture-repo/issues/001-well-specified.md home/common/agent-skills/skills/from-issue/evals/evals.json home/common/agent-skills/skills/writing-plans/evals/evals.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "test(evals): tag fixture 001 and grade the acceptance map in both planning evals (#274)"
```
