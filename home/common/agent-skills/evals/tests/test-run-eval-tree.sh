#!/usr/bin/env bash
#
# Black-box test of run-eval.sh working-tree mode (#293 AC1; project-skills layout). It copies evals/ to a
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
# Fake claude, run with its cwd at the sandbox repo. FAKE_RUN_EXIT chooses the exit
# code. FAKE_HOLD=1 makes a -p run touch $FAKE_STATE/started and wait (bounded) for
# $FAKE_STATE/release. FAKE_EMPTY=1 makes a -p run print nothing on stdout, as a
# timed-out run does. Any non -p invocation (an auth probe) is recorded as `other=`.
if [ "${1:-}" != -p ]; then
  printf 'other=%s\n' "$*" >>"$FAKE_STATE/record"
  exit 0
fi
{
  printf 'run=1\n'
  printf 'run_config_dir=%s\n' "${CLAUDE_CONFIG_DIR:-}"
  printf 'resolve_project=%s\n' "$(command -v resolve-project)"
  printf 'cwd=%s\n' "$(pwd -P)"
  printf 'args=%s\n' "$(printf '%s' "$*" | tr '\n' ' ')"
} >>"$FAKE_STATE/record"
if [ -d .claude ]; then
  ( find .claude -type l | sed 's|^\./||' | sort | while IFS= read -r link; do
      printf '%s\t%s\n' "$link" "$(readlink "$link")"
    done ) >"$FAKE_STATE/project-links"
  ( find .claude/skills .claude/agents -type f 2>/dev/null | sort ) >"$FAKE_STATE/project-regular-files"
  git status --porcelain --untracked-files=all >"$FAKE_STATE/git-status"
  git ls-files .claude >"$FAKE_STATE/tracked-claude"
  cp CLAUDE.md "$FAKE_STATE/root-CLAUDE.md"
fi
if [ "${FAKE_HOLD:-}" = 1 ]; then
  printf '%s\n' "$$" >"$FAKE_STATE/pid"
  : >"$FAKE_STATE/started"
  for _ in $(seq 1 300); do
    [ -e "$FAKE_STATE/release" ] && break
    sleep 0.1
  done
  : >"$FAKE_STATE/finished"
fi
[ "${FAKE_EMPTY:-}" = 1 ] && exit "${FAKE_RUN_EXIT:-0}"
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
# shim_root — the temp root holding the run's command shims: two levels above the
# resolve-project the fake saw.
shim_root() { local p; p=$(recorded resolve_project); [ -n "$p" ] && dirname "$(dirname "$p")"; }
root_gone() { [ -n "$1" ] && [ ! -e "$1" ]; }
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
# project_links_match_tree — the sandbox's .claude/ symlinks are exactly one per skill
# directory in the two skill roots, one per agent file and CLAUDE.md, each pointing at
# the tree's own path. The expected set is listed from the tree, not from the runner.
project_links_match_tree() {
  local root dir file
  [ -s "$STATE/project-links" ] || { echo "no .claude/ links recorded"; return 1; }
  {
    for root in "$TREE/home/common/agent-skills/skills" "$TREE/home/common/claude-code/skills"; do
      for dir in "$root"/*/; do
        [ -d "$dir" ] || continue
        printf '.claude/skills/%s\t%s\n' "$(basename "$dir")" "$root/$(basename "$dir")"
      done
    done
    for file in "$TREE"/home/common/claude-code/agents/*.md; do
      printf '.claude/agents/%s\t%s\n' "$(basename "$file")" "$file"
    done
    printf '.claude/CLAUDE.md\t%s\n' "$TREE/home/common/agent-guidance/AGENTS.md"
  } | sort >"$STATE/expected-links"
  diff "$STATE/expected-links" "$STATE/project-links" ||
    { echo "the sandbox's .claude/ links differ from the tree's skills, agents and AGENTS.md"; return 1; }
  [ ! -s "$STATE/project-regular-files" ] || { echo "regular files were written into .claude/skills or .claude/agents"; return 1; }
}
# the fixture's tracked .claude/ content, listed from the fixture itself.
tracked_claude_is_fixtures_own() {
  ( cd "$EVALS_SRC/fixture-repo" && find .claude -type f ! -path '*/__pycache__/*' | sort ) >"$STATE/expected-tracked"
  sort "$STATE/tracked-claude" | diff "$STATE/expected-tracked" - >/dev/null ||
    { echo "tracked .claude/ files differ from the fixture's own"; return 1; }
}
args_have() { grep -q -- "^args=.*$1" "$STATE/record"; }
row_has_tree_and_tokens() {
  last_row | jq -e --arg tree "$TREE" --arg rev "$(git -C "$TREE" rev-parse HEAD)" \
    --argjson exit "$1" '
      .tree == $tree and .tree_rev == $rev and (.tree_dirty | type) == "boolean"
      and .tree_mode == "project-skills"
      and .input_tokens == 246 and .uncached_input_tokens == 11
      and .cache_read_input_tokens == 202 and .cache_creation_input_tokens == 33
      and .output_tokens == 44 and .cost_usd == 0.25 and .num_turns == 7
      and .models == ["claude-haiku-y", "claude-sonnet-x"] and .claude_exit == $exit' >/dev/null
}
row_has_null_usage() {
  last_row | jq -e --arg tree "$TREE" --argjson exit "$1" '
      .tree == $tree and .claude_exit == $exit and .input_tokens == null
      and .uncached_input_tokens == null and .cache_read_input_tokens == null
      and .cache_creation_input_tokens == null and .output_tokens == null
      and .cost_usd == null and .num_turns == null and .models == null' >/dev/null
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
ROOT=$(shim_root)
check "the claude run happened" test "$(recorded run)" = 1
check "the claude run saw no CLAUDE_CONFIG_DIR" test -z "$(recorded run_config_dir)"
check "no auth probe or other claude call was made" test -z "$(recorded other)"
check "claude ran in the sandbox repo" test "$(basename "$(recorded cwd)")" = repo
check "the sandbox's .claude/ links the tree's skills, agents and AGENTS.md" project_links_match_tree
check "the fixture's root CLAUDE.md is untouched" cmp -s "$EVALS_SRC/fixture-repo/CLAUDE.md" "$STATE/root-CLAUDE.md"
check "the injected .claude/ entries never show in git status" test ! -s "$STATE/git-status"
check "nothing injected is tracked; the fixture's .claude/ files still are" tracked_claude_is_fixtures_own
check "claude ran with --setting-sources project,local" args_have '--setting-sources project,local'
check "claude ran with --settings naming EVAL_SETTINGS" args_have "--settings $SETTINGS_FIXTURE"
check "claude ran with --dangerously-skip-permissions" args_have '--dangerously-skip-permissions'
check "claude ran with --output-format json" args_have '--output-format json'
check "claude ran with --add-dir" args_have '--add-dir '
shim_root_is_temp() { case "$(basename "$ROOT")" in run-eval-tree.*) [ "$(recorded resolve_project)" = "$ROOT/bin/resolve-project" ] ;; *) false ;; esac; }
check "resolve-project resolves to a run-eval-tree temp root's shim" shim_root_is_temp
check "the shim root sits in TMPDIR" test "$(dirname "$ROOT")" = "$(cd "$RUN_TMP" && pwd -P)"
check "the row carries the tree, tree_mode and the canned token sums" row_has_tree_and_tokens 0
check "the transcript is the result text and result.json is kept" transcript_is_result_text
check "exit 0: the shim root is gone" root_gone "$ROOT"
check "exit 0: only the sandbox is left in TMPDIR" tmp_holds_only_sandboxes
check "exit 0: the runner exits 1 because the fake did no work" test "$status" -eq 1

# --- exit path 2: the claude run exits non-zero ------------------------------------
scenario claude-exit-1
run_env FAKE_RUN_EXIT=1
ROOT=$(shim_root)
check "non-zero: the row records claude_exit 1 and the token sums" row_has_tree_and_tokens 1
check "non-zero: the shim root is gone" root_gone "$ROOT"
check "non-zero: only the sandbox is left in TMPDIR" tmp_holds_only_sandboxes

# --- an empty result: the run printed nothing (a timeout) --------------------------
scenario empty-result
run_env FAKE_EMPTY=1 FAKE_RUN_EXIT=124
ROOT=$(shim_root)
check "empty result: exactly one row is still written" test "$(row_count)" -eq 1
check "empty result: the row has claude_exit 124 and null usage" row_has_null_usage 124
check "empty result: the shim root is gone" root_gone "$ROOT"

# --- a preparation failure: the tree's agents/ holds no agent file -----------------
# Every member the runner validates is present, so only the agents/*.md check fails.
scenario prep-failure
BROKEN="$S/tree"
mkdir -p "$BROKEN/home/common/agent-skills" "$BROKEN/home/common/claude-code/agents" \
  "$BROKEN/home/common/agent-guidance" "$BROKEN/python" "$BROKEN/lib"
ln -s "$TREE/home/common/agent-skills/skills" "$BROKEN/home/common/agent-skills/skills"
ln -s "$TREE/home/common/claude-code/skills" "$BROKEN/home/common/claude-code/skills"
ln -s "$TREE/python/agent_tools" "$BROKEN/python/agent_tools"
cp "$TREE/home/common/agent-guidance/AGENTS.md" "$BROKEN/home/common/agent-guidance/"
cp "$TREE/lib/agent-tools.nix" "$BROKEN/lib/"
git -C "$BROKEN" init -q
git -C "$BROKEN" add -A
git -C "$BROKEN" -c user.name=t -c user.email=t@example.invalid -c commit.gpgsign=false \
  commit -qm "broken tree"
run_env EVAL_TREE="$BROKEN"
status=$?
check "prep failure: the runner exits 2" test "$status" -eq 2
check "prep failure: the message names the missing agent files" grep -q 'run-eval: no agent files in' "$S/log"
check "prep failure: claude -p never ran" test -z "$(recorded run)"
check "prep failure: no row was written" test "$(row_count)" -eq 0
check "prep failure: no sandbox and no temp root remain" tmp_is_empty

# --- a preparation failure: the settings file is not JSON --------------------------
scenario bad-settings
printf 'not json\n' >"$S/settings.json"
run_env EVAL_SETTINGS="$S/settings.json"
status=$?
check "bad settings: the runner exits 2" test "$status" -eq 2
check "bad settings: the message names the settings file" grep -q 'run-eval: settings file is not JSON' "$S/log"
check "bad settings: claude -p never ran" test -z "$(recorded run)"
check "bad settings: no sandbox and no temp root remain" tmp_is_empty

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
# The fake is never released: the runner must stop it, not wait for it to finish.
wait "$pid"
status=$?
ROOT=$(shim_root)
check "SIGTERM: the runner exits 143" test "$status" -eq 143
check "SIGTERM: the claude run was stopped, not left to finish" test ! -e "$STATE/finished"
fake_pid=$(cat "$STATE/pid" 2>/dev/null)
process_gone() { [ -n "$1" ] && ! kill -0 "$1" 2>/dev/null; }
check "SIGTERM: the claude process is gone" process_gone "$fake_pid"
: >"$STATE/release"
check "SIGTERM: the shim root is gone" root_gone "$ROOT"
check "SIGTERM: no row was written" test "$(row_count)" -eq 0

# --- setup kinds, smoke-tested in deployed mode (D15, D16) -------------------------
cat >"$FAKE_BIN/resolve-project" <<SHIM
#!/usr/bin/env bash
PYTHONPATH="$TREE/python" exec python3 -P -m agent_tools.resolve_project "\$@"
SHIM
chmod +x "$FAKE_BIN/resolve-project"
row_is_deployed_pass() {
  last_row | jq -e '.verdict == "PASS" and .failed == 0 and .tree == "deployed"
    and .tree_rev == null and .tree_dirty == null and .tree_mode == null
    and .input_tokens == 246' >/dev/null
}
row_total_is_fixture_count() {
  local want
  want=$(jq --argjson id "$1" '.evals[] | select(.id == $id) | .asserts | length' \
    "$EVALS_SRC/tests/fixtures/setup-smoke-evals.json") || return 1
  last_row | jq -e --argjson want "$want" '.total == $want and .failed == 0' >/dev/null
}
smoke_tmp_holds_only_its_sandbox() {
  local entry
  for entry in "$RUN_TMP"/* "$RUN_TMP"/.[!.]*; do
    [ -e "$entry" ] || continue
    case "$(basename "$entry")" in
      eval-setup-smoke-"$1".*) ;;
      *) echo "left behind: $entry"; return 1 ;;
    esac
  done
}
for id in 1 2 3; do
  scenario "setup-smoke-$id"
  mkdir -p "$S/skills/setup-smoke/evals"
  cp "$EVALS_SRC/tests/fixtures/setup-smoke-evals.json" "$S/skills/setup-smoke/evals/evals.json"
  env FAKE_STATE="$STATE" TMPDIR="$RUN_TMP" PATH="$FAKE_BIN:$PATH" EVAL_TIMEOUT=120 \
    bash "$COPY/run-eval.sh" setup-smoke "$id" >"$S/log" 2>&1
  status=$?
  check "setup smoke $id: every setup assert passes" test "$status" -eq 0
  check "setup smoke $id: the row is a deployed-mode PASS" row_is_deployed_pass
  check "setup smoke $id: the row reports every fixture assert" row_total_is_fixture_count "$id"
  check "setup smoke $id: deployed mode makes no temp root" smoke_tmp_holds_only_its_sandbox "$id"
  check "setup smoke $id: deployed mode passes no --setting-sources" test -z "$(grep -- '--setting-sources' "$STATE/record")"
done

if [ "$FAILURES" -ne 0 ]; then
  for log in "$SCRATCH"/*/log; do
    echo "--- $log (last 15 lines)"
    tail -n 15 "$log"
  done
  echo "test-run-eval-tree: $FAILURES check(s) failed" >&2
  exit 1
fi
echo "test-run-eval-tree: all checks passed"
