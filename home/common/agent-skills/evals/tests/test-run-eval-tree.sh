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
# FAKE_EMPTY=1 makes a -p run print nothing on stdout, as a timed-out run does.
if [ "${1:-}" = auth ] && [ "${2:-}" = status ]; then
  printf 'auth_config_dir=%s\n' "${CLAUDE_CONFIG_DIR:-}" >>"$FAKE_STATE/record"
  exit "${FAKE_AUTH_EXIT:-0}"
fi
cfg=${CLAUDE_CONFIG_DIR:-}
{
  printf 'run_config_dir=%s\n' "$cfg"
  printf 'resolve_project=%s\n' "$(command -v resolve-project)"
  printf 'args=%s\n' "$(printf '%s' "$*" | tr '\n' ' ')"
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

# --- an empty result: the run printed nothing (a timeout) --------------------------
scenario empty-result
run_env FAKE_EMPTY=1 FAKE_RUN_EXIT=124
CFG=$(recorded run_config_dir)
check "empty result: exactly one row is still written" test "$(row_count)" -eq 1
check "empty result: the row has claude_exit 124 and null usage" row_has_null_usage 124
check "empty result: the temp root is gone" root_gone "$CFG"

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

# --- setup kinds, smoke-tested in deployed mode (D15, D16) -------------------------
cat >"$FAKE_BIN/resolve-project" <<SHIM
#!/usr/bin/env bash
PYTHONPATH="$TREE/python" exec python3 -P -m agent_tools.resolve_project "\$@"
SHIM
chmod +x "$FAKE_BIN/resolve-project"
row_is_deployed_pass() {
  last_row | jq -e '.verdict == "PASS" and .failed == 0 and .tree == "deployed"
    and .tree_rev == null and .tree_dirty == null and .input_tokens == 246' >/dev/null
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
  check "setup smoke $id: deployed mode makes no temp root" smoke_tmp_holds_only_its_sandbox "$id"
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
