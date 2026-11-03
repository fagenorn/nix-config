# Task 3: The advisory checkout fetches full history

Spec § CI truthfulness prerequisites, per D8. Five suite modules build fixtures from pinned ancestor commits:
- `test_control_cutover`, `test_attempt_migration` and `home/common/agent-skills/tests/test_attempt_custody` pin a `BASE_COMMIT`;
- `test_control_decisions` and `test_delivery_sealing` build on those fixtures.

The tests refuse to skip ("fetch it, do not skip"), and the advisory job's `actions/checkout@v4` step fetches one commit, so on CI they fail as designed: 2 failures and 8 `setUpClass` errors in run 40263175321. The job's `Checkout` step gains `fetch-depth: 0`, as Nix Eval, Flake Checker and Instruction Budget already have, and the workflow-shape test pins it.

**Files:**
- Modify: `.github/workflows/ci.yaml` (job `agent-workflow-tests`, step `Checkout`)
- Test: `tests/test_branch_protection.py` (`WorkflowShape.test_advisory_job_observes_each_step_and_writes_the_v1_record`)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: an advisory job that checks out full history. Nothing else in the job changes: name, step names and ids, `continue-on-error`, the `--command just agent-workflow-tests` invocation, `timeout-minutes: 45`, the observation record and the triggers stay. The longer clone lands in `Checkout`, not in the timed step `Run agent workflow tests` (D10).

**Invariants:**
- The `Checkout` step owns the line `          fetch-depth: 0` (ten spaces), under a `        with:` line that follows its `uses: actions/checkout@v4`.
- Every other assertion of `tests/test_branch_protection.py` passes unmodified.
- The three pinned base commits are ancestors of the branch head, so a full checkout of a PR merge ref or of a push to `main` reaches them.

- [ ] **Step 1: Write the failing test**

In `tests/test_branch_protection.py`, in `WorkflowShape.test_advisory_job_observes_each_step_and_writes_the_v1_record`, directly after the line `        self.assertTrue(has_summary_always_guard(steps))`, add:

```python
        # Issue 436: five suite modules build fixtures from pinned ancestor
        # commits and refuse to skip, so the advisory checkout fetches history.
        self.assertIn("          fetch-depth: 0", steps["Checkout"])
```

- [ ] **Step 2: Run the test and watch it fail**

Run the focused form (Global Constraints) on `tests/test_branch_protection.py -k test_advisory_job_observes_each_step_and_writes_the_v1_record`.
Expected: FAIL. `AssertionError: '          fetch-depth: 0' not found in [...]`, listing the `Checkout` step's four lines.

- [ ] **Step 3: Write the minimal implementation**

In `.github/workflows/ci.yaml`, change the advisory job's `Checkout` step from:

```yaml
      - name: Checkout
        id: checkout
        continue-on-error: true
        uses: actions/checkout@v4
```

to:

```yaml
      - name: Checkout
        id: checkout
        continue-on-error: true
        uses: actions/checkout@v4
        # Full history: suite modules build fixtures from pinned ancestor
        # commits and refuse to skip when one is missing (issue 436).
        with:
          fetch-depth: 0
```

Change nothing else in the file.

- [ ] **Step 4: Verify**

Run the focused form on `tests/test_branch_protection.py`.
Expected: `OK`, the whole module.

Run `bash -c 'set -e; for c in $(grep -h "^BASE_COMMIT = " home/common/agent-skills/tests/test_control_cutover.py home/common/agent-skills/tests/test_attempt_migration.py home/common/agent-skills/tests/test_attempt_custody.py | cut -d\" -f2); do git merge-base --is-ancestor "$c" HEAD; echo "ancestor $c"; done'`.
Expected: three `ancestor …` lines, and exit 0.

Run `git diff 9d2abb3f -- .github/workflows/ci.yaml | grep -E '^[-+][^-+]'`.
Expected: exactly the four added lines (two comment lines, `with:` and `fetch-depth: 0`) and no removed line.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yaml tests/test_branch_protection.py
launch-commit … -- -m "ci(issue-436): fetch full history for the advisory agent workflow tests" -m "<session trailers>"
```

Verify: `git status --short` prints nothing.
