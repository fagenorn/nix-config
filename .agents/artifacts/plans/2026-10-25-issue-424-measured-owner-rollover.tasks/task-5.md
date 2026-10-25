# Task 5: Eval runs keep their sessions

Per D13 (and D12's evidence path). Claude Code 2.1.302 writes no transcript when session persistence is off: the runner turns it off explicitly with `--no-session-persistence`, and a `claude -p` started from inside a Claude Code session (`CLAUDE_CODE_CHILD_SESSION=1` in its environment) has it off too unless `CLAUDE_CODE_FORCE_SESSION_PERSISTENCE` is set. Without a transcript the context meter measures nothing and `agent-costs` sees nothing, so the runner stops disabling persistence and forces it on, in both modes.

**Files:**
- Modify: `home/common/agent-skills/evals/run-eval.sh`
- Modify: `home/common/agent-skills/evals/tests/test-run-eval-tree.sh`
- Modify: `home/common/agent-skills/evals/README.md`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: every pipeline-mode `claude -p` the runner starts has no `--no-session-persistence` argument and `CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1` in its environment; Task 6 relies on the sandbox's transcripts existing under the login's projects directory (`~/.claude/projects/<sandbox path with every non-alphanumeric character replaced by ->`).

**Invariants:**
- Every other `claude_args` member, the `cd "$REPO"`, the `timeout` and `exec` chain and the trap behaviour are unchanged; `CLAUDE_CONFIG_DIR` is still never set.
- The variable is set only in the subshell that execs `claude`, never exported into the runner's own environment.

- [ ] **Step 1: Write the failing test**

In `test-run-eval-tree.sh`:
- Add `CLAUDE_CODE_FORCE_SESSION_PERSISTENCE` to the `unset CLAUDE_CONFIG_DIR EVAL_TREE EVAL_SETTINGS EVAL_MAX_USD EVAL_TRIALS` line, so an ambient value cannot satisfy the check.
- In the fake `claude`'s recorded block, after the `run_config_dir=` line, add `printf 'force_session_persistence=%s\n' "${CLAUDE_CODE_FORCE_SESSION_PERSISTENCE:-}"`.
- Beside `args_have`, add `args_lack() { ! grep -q -- "^args=.*$1" "$STATE/record"; }`.
- In the `claude-exit-0` scenario, after `check "claude ran with --add-dir" args_have '--add-dir '`, add:

```bash
check "claude ran without --no-session-persistence" args_lack '--no-session-persistence'
check "claude ran with CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1" test "$(recorded force_session_persistence)" = 1
```

- [ ] **Step 2: Run the test and watch it fail**

```bash
bash -c 'bash home/common/agent-skills/evals/tests/test-run-eval-tree.sh 2>&1 | grep -E "^FAIL" ; echo "exit ${PIPESTATUS[0]}"'
```

(timeout 600 s). Expected: exactly the two new checks print `FAIL`, and the exit is non-zero.

- [ ] **Step 3: Write the minimal implementation**

`run-eval.sh`: delete the `--no-session-persistence` line from `claude_args`, and change the launching subshell to

```bash
  ( cd "$REPO" && export CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1 &&
    exec timeout "$EVAL_TIMEOUT" claude "${claude_args[@]}" ) \
    >"$WORK/result.json" 2>"$WORK/stderr.txt" </dev/null &
```

with a comment above it: the run keeps its session because the context meter and `agent-costs` read its transcripts, and Claude Code writes none for a `-p` run started inside a Claude Code session unless `CLAUDE_CODE_FORCE_SESSION_PERSISTENCE` is set (issue 424).

`evals/README.md`: in `## Conventions`, one bullet saying that every pipeline run keeps its session (no `--no-session-persistence`, `CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1`, and why), that the sandbox's transcripts land in the login's projects directory under the sandbox path's project name, and that `agent-costs` therefore counts eval spend.

- [ ] **Step 4: Verify**

Rerun the Step 2 command. Expected: no `FAIL` line and `exit 0`. Then:

```bash
if grep -n -- '--no-session-persistence' home/common/agent-skills/evals/run-eval.sh; then exit 1; fi
bash -n home/common/agent-skills/evals/run-eval.sh && echo syntax-ok
```

Expected: no match, then `syntax-ok`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/evals/run-eval.sh \
  home/common/agent-skills/evals/tests/test-run-eval-tree.sh home/common/agent-skills/evals/README.md
launch-commit … -- -m "fix(evals): keep eval sessions so their transcripts can be measured (issue 424)" -m "<session trailers>"
```

Verify: `git status --short -- home/common/agent-skills/evals` prints nothing.
