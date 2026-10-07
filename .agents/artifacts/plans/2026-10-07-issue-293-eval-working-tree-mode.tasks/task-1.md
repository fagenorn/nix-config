# Task 1: Working-tree mode, JSON token capture and committed results

**Files:**
- Modify: `home/common/agent-skills/evals/run-eval.sh`
- Modify: `home/common/agent-skills/evals/assert-lib.sh` (header comment only)
- Modify: `home/common/agent-skills/evals/.gitignore`
- Modify: `home/common/agent-skills/evals/README.md`
- Create: `home/common/agent-skills/evals/results/results.jsonl` (empty, tracked)
- Create: `home/common/agent-skills/evals/tests/test-run-eval-tree.sh` (executable)
- Create: `home/common/agent-skills/evals/tests/fixtures/settings.json`
- Modify: `justfile` (recipe `agent-workflow-tests` only)

**Interfaces:**
- Consumes: the existing `run-eval.sh` flow (arg parsing, `SKILL_ROOTS`, `record_result`, `run_trial`), and the `commands = [ … ];` list in `lib/agent-tools.nix` (one quoted command name per line).
- Produces, for Tasks 2–4:
  - env `EVAL_TREE` (a checkout path) and `EVAL_SETTINGS` (a settings file; it defaults to `$HOME/.claude/settings.json`);
  - the temp root `${TMPDIR:-/tmp}/run-eval-tree.XXXXXX` holding `config/` and `bin/`;
  - per-sandbox files `$WORK/result.json`, `$WORK/stderr.txt` and `$WORK/output.txt` (the transcript that asserts grep as `$OUT`);
  - row fields `tree`, `tree_rev`, `tree_dirty`, `input_tokens`, `uncached_input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `output_tokens`, `cost_usd`, `num_turns` and `models`;
  - the bash test helpers `scenario`, `runner_env`, `run_env`, `recorded` and `check`, plus the fake `claude` at `$FAKE_BIN/claude`, all of which Task 2 extends.

**Invariants:**
- With `EVAL_TREE` unset, no temp root is created, `CLAUDE_CONFIG_DIR` is left as inherited, and the skill roots stay `$HERE/../skills` and `$HERE/../../claude-code/skills`. The row writes `tree: "deployed"` with `tree_rev` and `tree_dirty` set to `null`.
- With `EVAL_TREE` set, the temp root is removed on every exit path: a normal end, a `die`, a non-zero claude exit, INT (exit 130) and TERM (exit 143), per D3. Nothing is written into it before the `EXIT` trap is registered.
- An auth refusal exits 2 before any sandbox, `claude -p` run or row exists, and its message contains `claude setup-token` and `CLAUDE_CODE_OAUTH_TOKEN`, per D2.
- `config/skills/<name>/` is a real directory, and each regular file in the tree's skill directory, except `__pycache__` contents, appears as a symlink to the tree's absolute file. No regular file is copied in, per D11. A name present in both roots dies.
- `input_tokens = uncached + cache_read + cache_creation`, summed over every `modelUsage` entry (D1). Every token field is `null` when there is no parseable result object or the row is plan-only.
- `tree_dirty` reads `git status --porcelain` over the instruction paths from D13: both skill roots, `home/common/claude-code/agents` and `home/common/agent-guidance/AGENTS.md`, minus `':(exclude)home/common/agent-skills/skills/*/evals/*'` and `':(exclude)home/common/claude-code/skills/*/evals/*'`.
- The runner still has exactly one `resolve-project resolve --repo-root "$REPO"` and its existing refusal block.

- [ ] **Step 1: Write the failing test**

Create `home/common/agent-skills/evals/tests/fixtures/settings.json`:

```json
{
  "env": { "EVAL_FIXTURE": "1" },
  "hooks": { "PreToolUse": [] },
  "permissions": { "allow": [], "defaultMode": "auto" },
  "enabledPlugins": { "example@market": true },
  "extraKnownMarketplaces": { "market": { "source": { "source": "directory", "path": "/nonexistent" } } }
}
```

Create `home/common/agent-skills/evals/tests/test-run-eval-tree.sh` (then `chmod +x`):

```bash
#!/usr/bin/env bash
#
# Black-box test of run-eval.sh working-tree mode (#293 AC1). It copies evals/ to a
# scratch dir and runs the copy with EVAL_TREE set to this checkout and a fake
# `claude` first on PATH, so no model runs. Exit 0 only when every check passes.
set -uo pipefail

TREE=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../.." && pwd -P)
EVALS_SRC="$TREE/home/common/agent-skills/evals"
SETTINGS_FIXTURE="$EVALS_SRC/tests/fixtures/settings.json"
SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/run-eval-tree-test.XXXXXX") || exit 1
SCRATCH=$(cd "$SCRATCH" && pwd -P)
trap 'rm -rf -- "$SCRATCH"' EXIT

FAILURES=0
check() {
  local description=$1
  shift
  if "$@"; then
    printf 'ok    %s\n' "$description"
  else
    printf 'FAIL  %s\n' "$description"
    FAILURES=$((FAILURES + 1))
  fi
}

# resolve-project loads its platform manifest from $HOME/.agents/share (D16).
export HOME="$SCRATCH/home"
mkdir -p "$HOME/.agents/share"
cp "$TREE/home/common/agent-skills/platform-manifest.json" \
  "$TREE/home/common/agent-skills/host-declaration.json" "$HOME/.agents/share/"
unset CLAUDE_CONFIG_DIR EVAL_TREE EVAL_SETTINGS EVAL_MAX_USD EVAL_TRIALS

FAKE_BIN="$SCRATCH/fakebin"
mkdir -p "$FAKE_BIN"
cat >"$FAKE_BIN/claude" <<'FAKE'
#!/usr/bin/env bash
# Fake claude. FAKE_AUTH_EXIT / FAKE_RUN_EXIT choose exit codes. FAKE_HOLD=1 makes a
# -p run touch $FAKE_STATE/started and wait (bounded) for $FAKE_STATE/release.
if [ "${1:-}" = auth ] && [ "${2:-}" = status ]; then
  printf 'auth_config_dir=%s\n' "${CLAUDE_CONFIG_DIR:-}" >>"$FAKE_STATE/record"
  exit "${FAKE_AUTH_EXIT:-0}"
fi
cfg=${CLAUDE_CONFIG_DIR:-}
{
  printf 'run_config_dir=%s\n' "$cfg"
  printf 'resolve_project=%s\n' "$(command -v resolve-project)"
  printf 'args=%s\n' "$*"
} >>"$FAKE_STATE/record"
if [ -n "$cfg" ]; then
  ls -A "$cfg" >"$FAKE_STATE/config-listing"
  ( cd "$cfg/skills" && find . -type l | sed 's|^\./||' | sort | while IFS= read -r link; do
      printf '%s\t%s\n' "$link" "$(readlink "$link")"
    done ) >"$FAKE_STATE/skill-links"
  ( cd "$cfg/skills" && find . -type f | sed 's|^\./||' | sort ) >"$FAKE_STATE/skill-regular-files"
  cp "$cfg/CLAUDE.md" "$FAKE_STATE/CLAUDE.md"
  mkdir -p "$FAKE_STATE/agents"
  cp "$cfg"/agents/*.md "$FAKE_STATE/agents/"
  jq -c 'keys' "$cfg/settings.json" >"$FAKE_STATE/settings-keys"
fi
if [ "${FAKE_HOLD:-}" = 1 ]; then
  : >"$FAKE_STATE/started"
  for _ in $(seq 1 300); do
    [ -e "$FAKE_STATE/release" ] && break
    sleep 0.1
  done
fi
cat <<'JSON'
{"type":"result","subtype":"success","is_error":false,"result":"FAKE-RESULT-TEXT","num_turns":7,"total_cost_usd":0.25,"modelUsage":{"claude-sonnet-x":{"inputTokens":10,"cacheReadInputTokens":200,"cacheCreationInputTokens":30,"outputTokens":40},"claude-haiku-y":{"inputTokens":1,"cacheReadInputTokens":2,"cacheCreationInputTokens":3,"outputTokens":4}}}
JSON
exit "${FAKE_RUN_EXIT:-0}"
FAKE
chmod +x "$FAKE_BIN/claude"

# scenario <name> — a fresh copy of evals/, fresh fake state and a private TMPDIR.
scenario() {
  S="$SCRATCH/$1"
  COPY="$S/evals"
  STATE="$S/state"
  RUN_TMP="$S/tmp"
  mkdir -p "$S" "$STATE" "$RUN_TMP"
  cp -R "$EVALS_SRC" "$COPY"
  rm -f "$COPY/results/results.jsonl"
  : >"$STATE/record"
}
runner_env() {
  RUNNER_ENV=(FAKE_STATE="$STATE" TMPDIR="$RUN_TMP" PATH="$FAKE_BIN:$PATH"
    EVAL_TREE="$TREE" EVAL_SETTINGS="$SETTINGS_FIXTURE" EVAL_TIMEOUT=120)
}
# run_env [VAR=value...] — run the copied runner on from-issue 1 in the foreground.
run_env() {
  runner_env
  env "${RUNNER_ENV[@]}" "$@" bash "$COPY/run-eval.sh" from-issue 1 >"$S/log" 2>&1
}
recorded() { sed -n "s/^$1=//p" "$STATE/record" | head -n 1; }
row_count() {
  if [ -f "$COPY/results/results.jsonl" ]; then
    wc -l <"$COPY/results/results.jsonl" | tr -d ' '
  else
    echo 0
  fi
}
last_row() { tail -n 1 "$COPY/results/results.jsonl" 2>/dev/null; }
root_gone() { [ -n "$1" ] && [ ! -e "$(dirname "$1")" ]; }
tmp_is_empty() { [ -z "$(ls -A "$RUN_TMP")" ]; }
tmp_holds_only_sandboxes() {
  local entry
  for entry in "$RUN_TMP"/* "$RUN_TMP"/.[!.]*; do
    [ -e "$entry" ] || continue
    case "$(basename "$entry")" in
      eval-from-issue-1.*) ;;
      *) echo "left behind: $entry"; return 1 ;;
    esac
  done
}
config_lists_members() {
  local member
  for member in CLAUDE.md agents settings.json skills; do
    grep -qx "$member" "$STATE/config-listing" || { echo "config dir lacks $member"; return 1; }
  done
}
agents_match_tree() {
  local file count=0
  for file in "$TREE"/home/common/claude-code/agents/*.md; do
    count=$((count + 1))
    cmp -s "$file" "$STATE/agents/$(basename "$file")" ||
      { echo "agents/$(basename "$file") differs from the tree"; return 1; }
  done
  [ "$(ls "$STATE/agents" | wc -l | tr -d ' ')" -eq "$count" ] || { echo "agent count differs"; return 1; }
}
skill_links_match_tree() {
  local link target root
  [ -s "$STATE/skill-links" ] || { echo "no skill links recorded"; return 1; }
  while IFS=$'\t' read -r link target; do
    case "$target" in
      "$TREE/home/common/agent-skills/skills/$link" | "$TREE/home/common/claude-code/skills/$link") ;;
      *) echo "skills/$link -> $target is not the tree's file"; return 1 ;;
    esac
  done <"$STATE/skill-links"
  for root in "$TREE/home/common/agent-skills/skills" "$TREE/home/common/claude-code/skills"; do
    ( cd "$root" && find . -type f ! -path '*/__pycache__/*' | sed 's|^\./||' )
  done | sort >"$STATE/expected-links"
  cut -f1 "$STATE/skill-links" | diff - "$STATE/expected-links" >/dev/null ||
    { echo "the linked set differs from the tree's skill files"; return 1; }
  [ ! -s "$STATE/skill-regular-files" ] || { echo "regular files were copied into skills/"; return 1; }
}
row_has_tree_and_tokens() {
  last_row | jq -e --arg tree "$TREE" --arg rev "$(git -C "$TREE" rev-parse HEAD)" \
    --argjson exit "$1" '
      .tree == $tree and .tree_rev == $rev and (.tree_dirty | type) == "boolean"
      and .input_tokens == 246 and .uncached_input_tokens == 11
      and .cache_read_input_tokens == 202 and .cache_creation_input_tokens == 33
      and .output_tokens == 44 and .cost_usd == 0.25 and .num_turns == 7
      and .models == ["claude-haiku-y", "claude-sonnet-x"] and .claude_exit == $exit' >/dev/null
}
transcript_is_result_text() {
  local work
  work=$(last_row | jq -r '.workdir') || return 1
  grep -q 'FAKE-RESULT-TEXT' "$work/output.txt" &&
    jq -e '.num_turns == 7' "$work/result.json" >/dev/null
}

# --- exit path 1: the claude run exits 0 -------------------------------------------
scenario claude-exit-0
run_env FAKE_RUN_EXIT=0
status=$?
CFG=$(recorded run_config_dir)
check "the claude run saw a CLAUDE_CONFIG_DIR" test -n "$CFG"
check "the auth probe used the same config dir" test "$(recorded auth_config_dir)" = "$CFG"
check "config dir holds CLAUDE.md, agents, settings.json and skills" config_lists_members
check "CLAUDE.md is the tree's AGENTS.md" cmp -s "$TREE/home/common/agent-guidance/AGENTS.md" "$STATE/CLAUDE.md"
check "agents/ holds exactly the tree's agent files" agents_match_tree
check "settings drop the plugin keys and keep the rest" test "$(cat "$STATE/settings-keys")" = '["env","hooks","permissions"]'
check "every skills/ entry links the tree's file, for every skill" skill_links_match_tree
check "resolve-project resolves to the temp root's shim" test "$(recorded resolve_project)" = "$(dirname "$CFG")/bin/resolve-project"
check "claude ran with --output-format json" grep -q -- '^args=.*--output-format json' "$STATE/record"
check "the row carries the tree and the canned token sums" row_has_tree_and_tokens 0
check "the transcript is the result text and result.json is kept" transcript_is_result_text
check "exit 0: the temp root is gone" root_gone "$CFG"
check "exit 0: only the sandbox is left in TMPDIR" tmp_holds_only_sandboxes
check "exit 0: the runner exits 1 because the fake did no work" test "$status" -eq 1

# --- exit path 2: the claude run exits non-zero ------------------------------------
scenario claude-exit-1
run_env FAKE_RUN_EXIT=1
CFG=$(recorded run_config_dir)
check "non-zero: the row records claude_exit 1 and the token sums" row_has_tree_and_tokens 1
check "non-zero: the temp root is gone" root_gone "$CFG"
check "non-zero: only the sandbox is left in TMPDIR" tmp_holds_only_sandboxes

# --- exit path 3: the auth probe refuses -------------------------------------------
scenario auth-refused
run_env FAKE_AUTH_EXIT=1
status=$?
check "auth refusal: the runner exits 2" test "$status" -eq 2
check "auth refusal: the message names claude setup-token" grep -q 'claude setup-token' "$S/log"
check "auth refusal: the message names CLAUDE_CODE_OAUTH_TOKEN" grep -q 'CLAUDE_CODE_OAUTH_TOKEN' "$S/log"
check "auth refusal: the probe ran against a temp config dir" test -n "$(recorded auth_config_dir)"
check "auth refusal: claude -p never ran" test -z "$(recorded run_config_dir)"
check "auth refusal: no row was written" test "$(row_count)" -eq 0
check "auth refusal: no sandbox and no temp root remain" tmp_is_empty

# --- exit path 4: SIGTERM to the runner during the claude run ----------------------
scenario sigterm
runner_env
env "${RUNNER_ENV[@]}" FAKE_HOLD=1 bash "$COPY/run-eval.sh" from-issue 1 >"$S/log" 2>&1 &
pid=$!
for _ in $(seq 1 300); do
  [ -e "$STATE/started" ] && break
  sleep 0.1
done
check "SIGTERM: the claude run started" test -e "$STATE/started"
kill -TERM "$pid"
: >"$STATE/release"
wait "$pid"
status=$?
CFG=$(recorded run_config_dir)
check "SIGTERM: the runner exits 143" test "$status" -eq 143
check "SIGTERM: the temp root is gone" root_gone "$CFG"
check "SIGTERM: no row was written" test "$(row_count)" -eq 0

if [ "$FAILURES" -ne 0 ]; then
  for log in "$SCRATCH"/*/log; do
    echo "--- $log (last 15 lines)"
    tail -n 15 "$log"
  done
  echo "test-run-eval-tree: $FAILURES check(s) failed" >&2
  exit 1
fi
echo "test-run-eval-tree: all checks passed"
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `timeout 600 bash home/common/agent-skills/evals/tests/test-run-eval-tree.sh 2>&1 | tail -n 40`
Expected: exit 1. The runner ignores `EVAL_TREE`, so `the claude run saw a CLAUDE_CONFIG_DIR` and the row checks print `FAIL`. Depending on PATH, the runner may also die with `resolve-project is required`.

- [ ] **Step 3: Implement working-tree mode and the row fields in `run-eval.sh`**

Make these changes in order. Do not touch the resolver block.

1. **Header comment.** Rows are appended to the tracked `results/results.jsonl` (D10). The env list adds `EVAL_TREE` and `EVAL_SETTINGS`, described as Step 3 implements them.
2. **Tree validation.** Do this right after `EVAL_TRIALS` validation and before the `evals.json` lookup. Start from `TREE_LABEL=deployed`, `TREE_REV=""` and `TREE_DIRTY=""`. If `EVAL_TREE` is non-empty:
   - `[ -d ]`, or die;
   - normalise with `EVAL_TREE=$(cd "$EVAL_TREE" && pwd -P)`;
   - die (exit 2) naming the first missing member of `home/common/agent-skills/skills`, `home/common/claude-code/skills`, `home/common/agent-guidance/AGENTS.md`, `home/common/claude-code/agents`, `python/agent_tools` and `lib/agent-tools.nix`;
   - set `SKILL_ROOTS=("$EVAL_TREE/home/common/agent-skills/skills" "$EVAL_TREE/home/common/claude-code/skills")`, `TREE_LABEL=$EVAL_TREE` and `TREE_REV=$(git -C "$EVAL_TREE" rev-parse HEAD)` (die on failure);
   - set `TREE_DIRTY` to `true` or `false` from a non-empty or empty `git -C "$EVAL_TREE" status --porcelain -- <the D13 pathspec in Invariants>`.
3. **`prepare_tree_env`.** It runs only for pipeline mode with `EVAL_TREE` set. Call it after `command -v claude`, `git` and `jq` succeed, and before `command -v resolve-project`, so that the check sees the shim. Its steps:
   - Set `settings=${EVAL_SETTINGS:-$HOME/.claude/settings.json}`. If it is not a file, die with `settings file not found: <path> (set EVAL_SETTINGS)`.
   - `TREE_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/run-eval-tree.XXXXXX")`, or die. Immediately afterwards run `trap 'rm -rf -- "$TREE_ROOT"' EXIT`, `trap 'exit 130' INT` and `trap 'exit 143' TERM`. Only then set `TREE_ROOT=$(cd "$TREE_ROOT" && pwd -P)`.
   - `CONFIG="$TREE_ROOT/config"`, `SHIM_BIN="$TREE_ROOT/bin"`, then `mkdir -p "$CONFIG/skills" "$CONFIG/agents" "$SHIM_BIN"`.
   - For each root in `SKILL_ROOTS` order, and each `"$root"/*/` directory: let `name` be its basename. If `$CONFIG/skills/$name` exists, die with `skill '<name>' exists in both skill roots`. Otherwise `mkdir` it, and for each `rel` from `(cd "$root/$name" && find . -type f ! -path '*/__pycache__/*' | sed 's|^\./||')`, run `mkdir -p` on its parent and `ln -s "$root/$name/$rel" "$CONFIG/skills/$name/$rel"`. Feed the loop with `done < <(…)`, so that `die` exits the runner and not a subshell.
   - `cp "$EVAL_TREE/home/common/agent-guidance/AGENTS.md" "$CONFIG/CLAUDE.md"` and `cp "$EVAL_TREE"/home/common/claude-code/agents/*.md "$CONFIG/agents/"`.
   - `jq 'del(.enabledPlugins, .extraKnownMarketplaces)' "$settings" >"$CONFIG/settings.json"`. If it fails, die with `settings file is not JSON: <path>` (D4).
   - Read the command table with `awk '/^[[:space:]]*commands = \[/ {inside = 1; next} inside && /\];/ {exit} inside {gsub(/[" \t]/, ""); if ($0 != "") print}' "$EVAL_TREE/lib/agent-tools.nix"`. Empty output dies. For each command, write `$SHIM_BIN/<command>` as below and `chmod +x` it (D5). In the shim, `%q` is replaced by the `printf %q` of `$EVAL_TREE/python`, and the module is the command with `-` replaced by `_`:
     ```bash
     #!/usr/bin/env bash
     unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE
     PYTHONPATH=%q exec python3 -P -m agent_tools.<module> "$@"
     ```
   - The auth probe runs `CLAUDE_CONFIG_DIR="$CONFIG" claude auth status >/dev/null 2>&1`. On failure, die with: `claude is not logged in for the temporary config dir. One-time step: run \`claude setup-token\` and export the printed token as CLAUDE_CODE_OAUTH_TOKEN, then rerun.` (D2)
   - `export CLAUDE_CONFIG_DIR="$CONFIG"` and `export PATH="$SHIM_BIN:$PATH"`.
4. **Run and transcript (D1, D14).** In `run_trial`, replace `--output-format text` with `--output-format json`, and replace the `tee` pipeline with:
   ```bash
   ( cd "$REPO" && timeout "$EVAL_TIMEOUT" claude "${claude_args[@]}" ) >"$WORK/result.json" 2>"$WORK/stderr.txt"
   CLAUDE_EXIT=$?
   ```
   Then build `$OUT`. If `jq -er 'if type == "object" and (.result | type) == "string" then .result else error("no result") end' "$WORK/result.json" >"$OUT" 2>/dev/null` fails, run `cat "$WORK/result.json" >"$OUT"`. In both cases follow with `cat "$WORK/stderr.txt" >>"$OUT"` and `cat "$OUT"`. Keep the `claude exited …` and timeout NOTE lines.
5. **Usage extraction.** Add `usage_json <file>`, which prints one compact object or `{}`:
   ```bash
   usage_json() {
     jq -c 'if type == "object" and (.modelUsage | type) == "object" then
         [.modelUsage[]] as $m
         | {uncached_input_tokens: ($m | map(.inputTokens // 0) | add // 0),
            cache_read_input_tokens: ($m | map(.cacheReadInputTokens // 0) | add // 0),
            cache_creation_input_tokens: ($m | map(.cacheCreationInputTokens // 0) | add // 0),
            output_tokens: ($m | map(.outputTokens // 0) | add // 0),
            cost_usd: .total_cost_usd, num_turns: .num_turns,
            models: (.modelUsage | keys | sort)}
         | .input_tokens = .uncached_input_tokens + .cache_read_input_tokens + .cache_creation_input_tokens
       else {} end' "$1" 2>/dev/null || echo '{}'
   }
   ```
6. **Row writer.** `record_result` takes a tenth argument, the usage object. The pipeline call passes `"$(usage_json "$WORK/result.json")"`, and the plan-only call passes `'{}'`. Add `--arg tree "$TREE_LABEL" --arg tree_rev "$TREE_REV" --arg tree_dirty "$TREE_DIRTY" --argjson usage "${10}"`, and extend the object with `tree:$tree, tree_rev:($tree_rev | if . == "" then null else . end), tree_dirty:($tree_dirty | if . == "" then null else . == "true" end)`. Then apply `+ ({input_tokens:null, uncached_input_tokens:null, cache_read_input_tokens:null, cache_creation_input_tokens:null, output_tokens:null, cost_usd:null, num_turns:null, models:null} + $usage)` to the whole object.

Edit `assert-lib.sh`'s header only: `OUT` is now "the run's transcript: the result text (or raw stdout when no result object parsed) followed by claude's stderr".

Replace `home/common/agent-skills/evals/.gitignore` with two lines, `results/*` and `!results/results.jsonl`, and create an empty `results/results.jsonl` (D10).

In `justfile`'s `agent-workflow-tests` recipe, add one line right after the multi-line unittest command: `  bash home/common/agent-skills/evals/tests/test-run-eval-tree.sh`.

**README.** Rewrite "## Evals exercise the DEPLOYED skills" as a "## Two modes: deployed and working tree" section. Update "## Results persistence" too. Write every sentence from the implemented code, covering:
- deployed mode, which is the default and is what it was;
- `EVAL_TREE=. just evals from-issue 1`: the temp `CLAUDE_CONFIG_DIR` and what it holds, the shims ahead on `PATH`, and the cleanup;
- what tree mode does not cover (spec "Decisions");
- the one-time `claude setup-token` step and the `CLAUDE_CODE_OAUTH_TOKEN` export;
- `EVAL_SETTINGS`;
- the new row fields and the meaning of `input_tokens`;
- the fact that `results/results.jsonl` is committed and append-only;
- a comparison one-liner such as `jq -r 'select(.skill=="from-issue" and .id==1 and .input_tokens != null) | [.ts, .model, (.tree_rev // "deployed"), .verdict, .wall_s, .input_tokens] | @tsv' results/results.jsonl`.

Drop the old claim that only the spend ceiling is recorded.

- [ ] **Step 4: Verify**

Run: `timeout 600 bash home/common/agent-skills/evals/tests/test-run-eval-tree.sh 2>&1 | tail -n 40`
Expected: exit 0, every line `ok`, and `test-run-eval-tree: all checks passed`.

Run: `PYTHONPATH=python timeout 600 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_ship_release_contracts.py 2>&1 | tail -n 3`
Expected: `OK`. The resolver-refusal pin still holds.

Run: `if grep -q -- '--output-format text' home/common/agent-skills/evals/run-eval.sh; then exit 1; fi; if git check-ignore -q home/common/agent-skills/evals/results/results.jsonl; then exit 1; fi`
Expected: exit 0. The runner no longer asks for text output, and the results file is not ignored.

- [ ] **Step 5: Commit**

Commit the eight files above with the message `feat(evals): working-tree mode and token capture in run-eval (#293)`, using sdd's lifecycle commit rule.
