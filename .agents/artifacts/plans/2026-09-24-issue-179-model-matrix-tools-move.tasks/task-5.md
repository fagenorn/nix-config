# Task 5: Pin the deployed launcher floor and verify the slice

Decisions: D8, D9, D12; parent D9, D15; #175 D8. Spec sections "The
installed-layout test (D8)" and "Acceptance criteria and how each is verified
(D9)". Work from the worktree root. `PK` = `python/agent_tools`,
`AS` = `home/common/agent-skills`.

**Files:**
- Modify: `tests/test_agent_tools_launchers.py`

**Interfaces:**
- Consumes: Task 4's `MISUSE_USAGE` constant and extended hostile run. The
  command table after Task 4 holds `"agent-evidence"`, `"agent-model-matrix"`,
  `"context-map-lint"` and `"diff-scope"`.
- Produces: the module constant
  `LAUNCHER_FLOOR = ("agent-evidence", "agent-model-matrix", "context-map-lint", "diff-scope")`,
  unannotated like the file's other constants,
  and the test `test_the_command_table_generates_each_deployed_command`, which
  replaces `test_the_command_table_generates_agent_evidence`.

**Invariants:**
- The floor is the set #175 and #179 accepted as launchers. It is a floor, not
  the full set: the command table owns that (#175 D8). A new row needs no edit
  here.
- The floor asserts one subtest per name, so a missing launcher is named in the
  failure.
- The enumeration, the naming test, the hostile run and the controls do not
  change.

- [ ] **Step 0: Record the starting commit**

Run: `START=$(git rev-parse HEAD); BASE=$(git merge-base HEAD origin/main); B=$(mktemp -d); echo "$START $BASE $B"`.
Substitute the printed values literally wherever later steps write `${START}`,
`${BASE}` or `$B`. `BASE` is the PR base, where the three commands were still
flat scripts.

- [ ] **Step 1: Write the floor test**

In `tests/test_agent_tools_launchers.py`, directly after `TIMEOUT_SECONDS = 60`
and before the `MISUSE_USAGE` comment, add:

```python
# The commands #175 and #179 accepted as launchers: a floor, not the full set,
# which the command table in lib/agent-tools.nix owns (#175 D8).
LAUNCHER_FLOOR = ("agent-evidence", "agent-model-matrix", "context-map-lint", "diff-scope")
```

Replace `test_the_command_table_generates_agent_evidence` with:

```python
    def test_the_command_table_generates_each_deployed_command(self):
        launchers = self.launchers()
        for name in LAUNCHER_FLOOR:
            with self.subTest(launcher=name):
                self.assertIn(name, launchers)
```

- [ ] **Step 2: Show the floor fails without a row, then restore**

Delete the line `    "diff-scope"` from `commands` in `lib/agent-tools.nix`, and do
not commit it. The launcher disappears, and no hand-written link replaces it.
Then run:

```bash
just agent-installed-skill-tests > "$B/floor.log" 2>&1; echo "exit=$?"
grep -E "^FAIL:|AssertionError" "$B/floor.log" | head -4
git checkout -- lib/agent-tools.nix
```

Expected: a non-zero `exit=`, and
`FAIL: test_the_command_table_generates_each_deployed_command … (launcher='diff-scope')`
with `AssertionError: 'diff-scope' not found in {…}`.

- [ ] **Step 3: Verify the test and commit**

Run: `just agent-installed-skill-tests 2>&1 | grep -E "test_the_command_table|^Ran |^OK|FAILED"`
Expected: `test_the_command_table_generates_each_deployed_command … ok`,
`Ran 15 tests` and `OK`. At `$START` the test does not exist.

```bash
git add tests/test_agent_tools_launchers.py
git commit -m "test(agent-tools): pin the four deployed launchers in the installed-layout test"
```

The message ends with the plan's trailer lines.

- [ ] **Step 4: Acceptance and regression floor (read-only)**

These checks change nothing. Record each command's output for the final review.

AC1. The three commands are package launchers, and the installed test exercises
them. `unittest -v` prints no line for a passing subtest, so read the entries
directly:

```bash
H=$(nix-store --query --requisites ./result | grep -- '-home-manager-files$')
for n in agent-model-matrix context-map-lint diff-scope; do
  tail -n +2 "$H/.agents/bin/$n" | head -2
done
```

Expected: for each name, the `unset NIX_PYTHONPATH …` line and
`exec /nix/store/…/bin/python3 -I -m agent_tools.<name with _> "$@"`. The
installed run in Step 3 passed its floor, hostile-run and control subtests over
those entries.

AC2. No loader remains in the package or in the moved tools' suites:

```bash
set -e
if git grep -nE "importlib|SourceFileLoader|spec_from_file_location|sys\.path|__file__" -- python/agent_tools; then exit 1; fi
if git grep -nE "importlib|SourceFileLoader|spec_from_file_location|sys\.path" -- \
  tests/agent_model_drift_test_support.py 'tests/test_agent_model_drift_*.py' \
  tests/test_context_map_lint.py home/common/agent-skills/tests/test_agent_model_matrix.py \
  home/common/agent-skills/tests/test_diff_scope.py; then exit 1; fi
echo ac2-clean
```

Expected: `ac2-clean`. The suites' `REPO_ROOT` constants locate data files,
or source read as text, never code to import.

AC3. The telemetry digest and the duplicate-key hook are defined only in
`agent_tools.canonical` across product code (D9):

```bash
git grep -l hashlib -- python scripts
git grep -nF 'raise ValueError(f"duplicate JSON key {key!r}")' -- . ':!.claude' ':!tests' ':!**/tests/**'
git grep -nE "object_pairs_hook=" -- . ':!.claude' ':!tests' ':!**/tests/**'
```

Expected:
- The first command prints only `python/agent_tools/canonical.py`. At `${BASE}`
  it also listed the two drift files under `scripts/`.
- The second prints only `python/agent_tools/canonical.py:…`.
- The third prints five lines. Four are package lines passing
  `reject_duplicate_keys`: `agent_evidence`, `agent_gate_bundle`,
  `agent_model_matrix` and `agent_model_drift_schema`. The fifth is
  `artifact_budget.py`'s `_pairs_no_duplicates`, #178's variant.

Regression floor. Each built command's `--help` answer is byte-identical to the
base source run through a file named for the command:

```bash
L="$H/.agents/bin"; PY=$(sed -n 's/^exec \([^ ]*\) -I -m .*/\1/p' "$L/diff-scope")
git show "${BASE}:home/common/agent-skills/scripts/agent-model-matrix.py" > "$B/agent-model-matrix"
git show "${BASE}:home/common/agent-skills/scripts/diff-scope.py" > "$B/diff-scope"
git show "${BASE}:scripts/context-map-lint.py" > "$B/context-map-lint"
for n in agent-model-matrix diff-scope context-map-lint; do
  COLUMNS=80 "$PY" "$B/$n" --help > "$B/$n.out" 2> "$B/$n.err"; a=$?
  COLUMNS=80 "$L/$n" --help > "$B/$n.out2" 2> "$B/$n.err2"; b=$?
  cmp -s "$B/$n.out" "$B/$n.out2" && cmp -s "$B/$n.err" "$B/$n.err2" && [ "$a" = "$b" ] && echo "$n identical ($a)"
done
```

Expected: `agent-model-matrix identical (0)`, `diff-scope identical (0)` and
`context-map-lint identical (2)`.

Run: `test -z "$(git ls-files scripts)" && echo scripts-empty`
Expected: `scripts-empty`.

Run: `just build 2>&1 | tail -3`
Expected: success, with no `error:` line.

Run: `WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests 2>&1 | tail -3`
Expected: `Ran 1228 tests`, `OK (skipped=2)`.

Demo:
- Run `just agent-model-matrix 2>/dev/null | head -2`. Expected:
  `agent model matrix: valid` and the first representative trace line.
- Run `just agent-model-drift --help 2>/dev/null | head -1`. Expected:
  `usage: agent-model-drift [-h] --record RECORD …`.
- `just agent-installed-skill-tests` passed in Step 3 with the three new
  launchers.

Run: `git status --porcelain`
Expected: no output.
