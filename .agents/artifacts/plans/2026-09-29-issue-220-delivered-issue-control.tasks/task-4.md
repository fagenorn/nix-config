# Task 4: Run the full workflow suite and the Nix build

Acceptance 4 of #220. Verification only; no file changes.

**Files:** none.

**Interfaces:**
- Consumes: Tasks 1–3 as committed, including the `justfile` registration of
  `home/common/agent-skills/tests/test_delivered_control.py` from Task 1.
- Produces: nothing.

**Invariants:**
- The worktree is clean before and after (`git status --porcelain` prints nothing).
- `just agent-workflow-tests` runs `test_delivered_control.py` (3 tests) and passes.
- `just build` evaluates and builds the host configuration.

- [ ] **Step 1: Run the workflow suite**

Run: `cd /Users/anis/tmp/nix-config/.worktrees/worktree-issue-220-orchestrated && just agent-workflow-tests > "${TMPDIR:-/tmp}/issue-220-suite.log" 2>&1; echo "exit $?"; tail -3 "${TMPDIR:-/tmp}/issue-220-suite.log"; grep -E '^(FAIL|ERROR):' "${TMPDIR:-/tmp}/issue-220-suite.log"; grep -c 'test_delivered_control.DeliveredControlTest' "${TMPDIR:-/tmp}/issue-220-suite.log"`
Expected: `exit 0`, `OK` (with its skip count), no `FAIL:`/`ERROR:` lines, and the count `3`.
The run takes about ten minutes; a `3` below proves the new file is registered.

- [ ] **Step 2: Build**

Run: `cd /Users/anis/tmp/nix-config/.worktrees/worktree-issue-220-orchestrated && just build > "${TMPDIR:-/tmp}/issue-220-build.log" 2>&1; echo "exit $?"; tail -5 "${TMPDIR:-/tmp}/issue-220-build.log"`
Expected: `exit 0`.

- [ ] **Step 3: Confirm a clean tree**

Run: `cd /Users/anis/tmp/nix-config/.worktrees/worktree-issue-220-orchestrated && if [ -n "$(git status --porcelain)" ]; then git status --short; exit 1; fi; echo clean`
Expected: `clean`. There is nothing to commit; a failure in any step goes back to the task
that owns the failing file.
