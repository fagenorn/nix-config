# Task 5: Tree-mode `workflow-state` shim, derived settings and `EVAL_POLICY`

Spec § Tree mode and § `EVAL_POLICY`; per D16, with the grammar of D21. Tree mode today lets the flat `workflow-state` and the store-path meter hook escape the tree; this task shims `workflow-state` and points a derived settings file's meter hook at the tree's `context-meter` shim. It also adds `EVAL_POLICY`, validated up front, exported as `AGENT_PHASE_BUDGET` and recorded as `policy`.

**Files:**
- Modify: `home/common/agent-skills/evals/run-eval.sh`
- Modify: `home/common/agent-skills/evals/tests/test-run-eval-tree.sh`
- Modify: `home/common/agent-skills/evals/tests/fixtures/settings.json` (add a meter hook entry; see below)
- Modify: `home/common/agent-skills/evals/README.md` (tree-mode section, the env list, the results-row fields)

**Interfaces:**
- Consumes: Task 3's `phase_budget.parse` (product knobs).
- Produces, for Task 6 and Task 8:
  - In tree mode `$TREE_ROOT/bin/workflow-state` exists, and `TREE_SETTINGS` is `$TREE_ROOT/settings.json` (derived).
  - The claude run's environment carries `AGENT_PHASE_BUDGET` exactly when `EVAL_POLICY` is set.
  - Every results row gains `policy` (string or `null`).
  - The runner's header comment documents `EVAL_POLICY`.

**Invariants:**
- The shim is `$TREE_ROOT/bin/workflow-state`, written like the command shims: `#!/usr/bin/env bash`, `unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE`, then `PYTHONPATH=<tree>/python exec python3 -P <tree>/home/common/agent-skills/scripts/workflow-state.py "$@"`, with paths `printf %q`-quoted. It is executable. `prepare_tree_env` checks that the script exists, failing with `die` if not.
- Derived settings: `jq` copies `$EVAL_SETTINGS` (default `$HOME/.claude/settings.json`). Every hook object, under any event and any matcher, whose `type` is `command` and whose `command` ends with `-agent-tools-context-meter` gets `command` = `$TREE_ROOT/bin/context-meter`. Every other byte of meaning (the guard's entry, permissions, plugins, env) is unchanged. Zero replaced commands → `die "settings file has no context-meter hook: <path>"` before any sandbox. The run passes `--settings "$TREE_ROOT/settings.json"`.
- `EVAL_POLICY`:
  - Set without `EVAL_TREE` → `die "EVAL_POLICY requires EVAL_TREE"`.
  - With `EVAL_TREE`, it is validated before any sandbox by `PYTHONPATH=<tree>/python python3 -P -c 'import sys; from agent_tools import phase_budget; phase_budget.parse(sys.argv[1])' "$EVAL_POLICY"`. A failure dies with `invalid EVAL_POLICY '<value>':` plus the last stderr line.
  - It is exported as `AGENT_PHASE_BUDGET` only inside the claude subshell, beside `CLAUDE_CODE_FORCE_SESSION_PERSISTENCE`.
  - `record_result` writes `policy: $EVAL_POLICY`, or `null` when it is unset or empty.
- Plan-only evals and deployed mode are unchanged, apart from the `policy: null` field.

- [ ] **Step 1: Write the failing checks** in `test-run-eval-tree.sh`

Give the fixture settings a meter hook:

```json
"hooks": { "PreToolUse": [ { "matcher": "Bash", "hooks": [
  { "type": "command", "command": "/nix/store/0000-claude-bash-lifecycle-guard/bin/claude-bash-lifecycle-guard", "timeout": 30 },
  { "type": "command", "command": "/nix/store/0000-agent-tools-context-meter", "timeout": 10 } ] } ] },
```

The fake claude must also record, into its state directory, the `--settings` file it was given (a copy), the output of `command -v workflow-state` (as `which-workflow-state`) and that file's content (as `workflow-state-shim`), and `printenv AGENT_PHASE_BUDGET` (as `agent-phase-budget`). Extend it the same way it already records argv and environment. Then add these checks, using the script's existing `scenario`, `run_env`, `check`, `recorded` and `tmp_is_empty` helpers:

```bash
# --- tree mode shims workflow-state and points the meter at the tree --------------
scenario tree-shims
run_env EVAL_TREE="$TREE" EVAL_SETTINGS="$SETTINGS_FIXTURE"
check "shim: workflow-state resolves to the tree shim" grep -q '/run-eval-tree\.[^/]*/bin/workflow-state$' "$S/state/which-workflow-state"
check "shim: it runs the tree's script" grep -q "home/common/agent-skills/scripts/workflow-state.py" "$S/state/workflow-state-shim"
check "settings: the meter hook names the tree shim" jq -e '[.hooks.PreToolUse[0].hooks[1].command | endswith("/bin/context-meter")] | all' "$S/state/settings.json"
check "settings: the guard entry is unchanged" jq -e '.hooks.PreToolUse[0].hooks[0].command == "/nix/store/0000-claude-bash-lifecycle-guard/bin/claude-bash-lifecycle-guard"' "$S/state/settings.json"
check "row: policy is null without EVAL_POLICY" jq -e 'select(.policy == null)' "$S/results.jsonl"

# --- a settings file with no meter hook is refused --------------------------------
scenario no-meter
jq '.hooks.PreToolUse = []' "$SETTINGS_FIXTURE" >"$S/settings.json"
run_env EVAL_TREE="$TREE" EVAL_SETTINGS="$S/settings.json"
check "no meter: the runner exits 2" test "$status" -eq 2
check "no meter: the message names the file" grep -q 'run-eval: settings file has no context-meter hook' "$S/log"
check "no meter: claude -p never ran" test -z "$(recorded run)"
check "no meter: no sandbox and no temp root remain" tmp_is_empty

# --- EVAL_POLICY ------------------------------------------------------------------
scenario policy
run_env EVAL_TREE="$TREE" EVAL_SETTINGS="$SETTINGS_FIXTURE" EVAL_POLICY="threshold=140000"
check "policy: exported to the run" grep -qx 'threshold=140000' "$S/state/agent-phase-budget"
check "policy: recorded on the row" jq -e 'select(.policy == "threshold=140000")' "$S/results.jsonl"
scenario bad-policy
run_env EVAL_TREE="$TREE" EVAL_SETTINGS="$SETTINGS_FIXTURE" EVAL_POLICY="boot=slim"
check "bad policy: exits 2 before any sandbox" test "$status" -eq 2
check "bad policy: names the value" grep -q "run-eval: invalid EVAL_POLICY 'boot=slim'" "$S/log"
check "bad policy: claude -p never ran" test -z "$(recorded run)"
scenario policy-without-tree
run_env EVAL_POLICY="threshold=140000"
check "policy without tree: exits 2" test "$status" -eq 2
check "policy without tree: says so" grep -q 'run-eval: EVAL_POLICY requires EVAL_TREE' "$S/log"
```

Adapt the variable names (`$S`, the state directory, the results path) to the ones the script already uses for its scenarios, and keep each check's observable. The existing check `claude ran with --settings naming EVAL_SETTINGS` becomes "claude ran with --settings naming the derived settings under the shim root".

- [ ] **Step 2: Run the checks and watch them fail**

Run: **Harness tests** (the `test-run-eval-tree.sh` one).
Expected: FAIL lines for every new check, and a non-zero exit.

- [ ] **Step 3: Implement** in `prepare_tree_env` (the shim and derived settings, after the command shims) and at the top of the runner (the two `EVAL_POLICY` refusals, after the `EVAL_TREE` block, so both precede any sandbox). Pass the policy into `run_trial`'s claude subshell and into `record_result`. Update `evals/README.md`: the shim, the derived settings and their refusal, the remaining condition that absolute `~/.agents/bin/workflow-state` calls still reach the deployed helper, `EVAL_POLICY` (tree only, product knobs only, exported as `AGENT_PHASE_BUDGET`) and the `policy` row field.

- [ ] **Step 4: Verify**

Run: **Harness tests** (both commands).
Expected: every line `ok`, exit 0; `test_eval_cases.py` prints `OK`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/evals/run-eval.sh home/common/agent-skills/evals/tests/test-run-eval-tree.sh \
  home/common/agent-skills/evals/tests/fixtures/settings.json home/common/agent-skills/evals/README.md
launch-commit … -- -m "feat(evals): tree mode shims workflow-state and the meter, and takes EVAL_POLICY (issue 432)"
```
