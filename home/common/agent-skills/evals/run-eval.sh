#!/usr/bin/env bash
#
# Run one skill eval and grade it.
#
#   run-eval.sh <skill> <eval-id>     e.g. run-eval.sh from-issue 3
#   run-eval.sh <eval-id>             shorthand for skill=from-issue
#
# Skills are resolved from BOTH skill roots: the shared tree (../skills) and the
# Claude-only tree (../../claude-code/skills, home of codex-collaboration and
# orchestrate-issues).
#
# Pipeline evals ("mode": "pipeline") copy evals/fixture-repo into a fresh temp dir,
# give it a real git history and a bare origin, run `claude -p` with the eval's prompt,
# then grade the artifacts with the eval's scripted asserts. Plan-only evals just print
# the prompt and the expected output for manual or CI grading.
#
# Every run appends one JSON line per trial to results/results.jsonl, which is tracked
# and append-only: skill, id, per-assert pass/fail, wall seconds, verdict, model, budget
# ceiling, which tree ran (deployed or a checkout path, its revision and whether its
# instruction files were dirty), and the token and cost totals the claude run reported.
#
# Env: EVAL_MODEL (default sonnet), EVAL_TIMEOUT seconds (default 2700),
#      EVAL_MAX_USD (optional spend ceiling), EVAL_TRIALS repeat count (default 1;
#      >1 reruns the same eval in fresh sandboxes and prints pass rate + p50/p90
#      wall time so run-to-run comparisons are possible).
#      EVAL_TREE  a checkout to evaluate instead of the deployed skills. A pipeline run
#                 then links that checkout's skills, agents and AGENTS.md into the
#                 sandbox repo's .claude/ as project copies, runs claude with
#                 --setting-sources project,local so no user-level copy shadows them,
#                 and puts shims for its agent_tools commands ahead on PATH. The login
#                 is the normal one: CLAUDE_CONFIG_DIR is never set. The shim root is
#                 removed on every exit path.
#      EVAL_SETTINGS  the settings file passed as --settings in tree mode (default
#                 $HOME/.claude/settings.json), so its hooks, permissions and plugins
#                 still apply. Used only with EVAL_TREE.

set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
FIXTURE="$HERE/fixture-repo"
SETUPS="$HERE/setups"
ASSERT_LIB="$HERE/assert-lib.sh"
# Two skill roots: the shared tree and the Claude-only tree.
SKILL_ROOTS=("$HERE/../skills" "$HERE/../../claude-code/skills")
RESULTS_DIR="$HERE/results"
RESULTS_FILE="$RESULTS_DIR/results.jsonl"
TREE_LABEL=deployed
TREE_REV=""
TREE_DIRTY=""
TREE_MODE=""

EVAL_MODEL=${EVAL_MODEL:-sonnet}
EVAL_TIMEOUT=${EVAL_TIMEOUT:-2700}
EVAL_TRIALS=${EVAL_TRIALS:-1}

die() { echo "run-eval: $*" >&2; exit 2; }

case $# in
  1) SKILL=from-issue; ID=$1 ;;
  2) SKILL=$1; ID=$2 ;;
  *) die "usage: run-eval.sh [<skill>] <eval-id>" ;;
esac

case "$EVAL_TRIALS" in
  ''|*[!0-9]*) die "EVAL_TRIALS must be a positive integer, got '$EVAL_TRIALS'" ;;
  0) die "EVAL_TRIALS must be >= 1" ;;
esac

if [ -n "${EVAL_TREE:-}" ]; then
  [ -d "$EVAL_TREE" ] || die "EVAL_TREE is not a directory: $EVAL_TREE"
  EVAL_TREE=$(cd "$EVAL_TREE" && pwd -P)
  for member in home/common/agent-skills/skills home/common/claude-code/skills \
    home/common/agent-guidance/AGENTS.md home/common/claude-code/agents \
    python/agent_tools lib/agent-tools.nix; do
    [ -e "$EVAL_TREE/$member" ] || die "EVAL_TREE lacks $member: $EVAL_TREE"
  done
  SKILL_ROOTS=("$EVAL_TREE/home/common/agent-skills/skills" "$EVAL_TREE/home/common/claude-code/skills")
  TREE_LABEL=$EVAL_TREE
  TREE_MODE=project-skills
  TREE_REV=$(git -C "$EVAL_TREE" rev-parse HEAD) || die "EVAL_TREE is not a git checkout: $EVAL_TREE"
  if [ -n "$(git -C "$EVAL_TREE" status --porcelain -- \
    home/common/agent-skills/skills home/common/claude-code/skills \
    home/common/claude-code/agents home/common/agent-guidance/AGENTS.md \
    ':(exclude)home/common/agent-skills/skills/*/evals/*' \
    ':(exclude)home/common/claude-code/skills/*/evals/*')" ]; then
    TREE_DIRTY=true
  else
    TREE_DIRTY=false
  fi
fi

EVALS_FILE=""
for skill_root in "${SKILL_ROOTS[@]}"; do
  candidate="$skill_root/$SKILL/evals/evals.json"
  [ -f "$candidate" ] && { EVALS_FILE=$candidate; break; }
done
[ -n "$EVALS_FILE" ] || die "no evals.json for skill '$SKILL' (looked in: ${SKILL_ROOTS[*]/%//$SKILL/evals/evals.json})"
command -v jq >/dev/null || die "jq is required"

EVAL=$(jq -ce --argjson id "$ID" '.evals[] | select(.id == $id)' "$EVALS_FILE") ||
  die "no eval with id $ID in $EVALS_FILE"

NAME=$(jq -r '.name' <<<"$EVAL")
MODE=$(jq -r '.mode // "plan-only"' <<<"$EVAL")
PROMPT=$(jq -r '.prompt' <<<"$EVAL")
EXPECTED_TODAY=$(jq -r '.expected_today // "pass"' <<<"$EVAL")
NOTE=$(jq -r '.note // ""' <<<"$EVAL")

# usage_json <result-file> — print exactly one compact JSON object: the token and cost
# totals of the claude result, or {} when there is no single parseable result object.
# input_tokens is the sum of uncached, cache-read and cache-creation input, over every
# model in modelUsage. Slurping makes an empty file yield [] (so {}), and a parse error
# prints nothing before the fallback.
usage_json() {
  jq -cs 'if length == 1 and (.[0] | type) == "object" and (.[0].modelUsage | type) == "object" then
      .[0] | [.modelUsage[]] as $m
      | {uncached_input_tokens: ($m | map(.inputTokens // 0) | add // 0),
         cache_read_input_tokens: ($m | map(.cacheReadInputTokens // 0) | add // 0),
         cache_creation_input_tokens: ($m | map(.cacheCreationInputTokens // 0) | add // 0),
         output_tokens: ($m | map(.outputTokens // 0) | add // 0),
         cost_usd: .total_cost_usd, num_turns: .num_turns,
         models: (.modelUsage | keys | sort)}
      | .input_tokens = .uncached_input_tokens + .cache_read_input_tokens + .cache_creation_input_tokens
    else {} end' "$1" 2>/dev/null || echo '{}'
}

# record_result <trial> <verdict> <passed> <failed> <total> <wall_s> <claude_exit> <workdir> <asserts-json> <usage-json>
record_result() {
  mkdir -p "$RESULTS_DIR"
  jq -cn \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg skill "$SKILL" --argjson id "$ID" --arg name "$NAME" --arg mode "$MODE" \
    --arg model "$EVAL_MODEL" --argjson trial "$1" --argjson trials "$EVAL_TRIALS" \
    --arg verdict "$2" --argjson passed "$3" --argjson failed "$4" --argjson total "$5" \
    --argjson wall_s "$6" --arg claude_exit "$7" --arg workdir "$8" --argjson asserts "$9" \
    --arg max_usd "${EVAL_MAX_USD:-}" \
    --arg tree "$TREE_LABEL" --arg tree_rev "$TREE_REV" --arg tree_dirty "$TREE_DIRTY" \
    --arg tree_mode "$TREE_MODE" \
    --argjson usage "${10}" \
    '{ts:$ts, skill:$skill, id:$id, name:$name, mode:$mode, model:$model,
      trial:$trial, trials:$trials, verdict:$verdict,
      passed:$passed, failed:$failed, total:$total, wall_s:$wall_s,
      claude_exit:($claude_exit | if . == "" then null else tonumber end),
      workdir:($workdir | if . == "" then null else . end),
      eval_max_usd:($max_usd | if . == "" then null else tonumber end),
      asserts:$asserts,
      tree:$tree, tree_rev:($tree_rev | if . == "" then null else . end),
      tree_dirty:($tree_dirty | if . == "" then null else . == "true" end),
      tree_mode:($tree_mode | if . == "" then null else . end)}
    + ({input_tokens:null, uncached_input_tokens:null, cache_read_input_tokens:null,
        cache_creation_input_tokens:null, output_tokens:null, cost_usd:null,
        num_turns:null, models:null} + $usage)' >>"$RESULTS_FILE"
}

echo "=== $SKILL eval $ID: $NAME ($MODE) ==="

if [ "$MODE" = "plan-only" ]; then
  echo
  echo "--- prompt ---"
  echo "$PROMPT"
  echo
  echo "--- expected output ---"
  jq -r '.expected_output' <<<"$EVAL"
  echo
  echo "Plan-only eval: graded by reading the transcript against the expected output."
  echo "Paste the prompt into a session on a repo matching this skill's assumptions."
  record_result 1 "PRINTED" 0 0 0 0 "" "" "[]" '{}'
  exit 0
fi

[ "$MODE" = "pipeline" ] || die "unknown mode '$MODE'"
command -v claude >/dev/null || die "claude CLI is required"
command -v git >/dev/null || die "git is required"

# stop_claude_and_exit <code> — the INT/TERM trap: stop a claude run still in flight and
# reap it before exiting, so cancelling the runner never leaves a model run spending.
# The run is a background job the main shell `wait`s on, because bash defers a trapped
# signal until a foreground command returns, which would let the run go on to
# EVAL_TIMEOUT.
CLAUDE_PID=""
stop_claude_and_exit() {
  if [ -n "$CLAUDE_PID" ]; then
    kill -TERM "$CLAUDE_PID" 2>/dev/null
    wait "$CLAUDE_PID" 2>/dev/null
  fi
  exit "$1"
}

# prepare_tree_env — check the tree's injectable members and the settings file, and
# build the command shims for EVAL_TREE. Runs in the main shell, so a die here exits the
# runner and the EXIT trap removes the shim root.
TREE_SETTINGS=""
TREE_AGENTS=()
prepare_tree_env() {
  TREE_SETTINGS=${EVAL_SETTINGS:-$HOME/.claude/settings.json}
  [ -f "$TREE_SETTINGS" ] || die "settings file not found: $TREE_SETTINGS (set EVAL_SETTINGS)"
  jq empty "$TREE_SETTINGS" || die "settings file is not JSON: $TREE_SETTINGS"

  # Every step below is checked: the runner has no `set -e`, and a half-prepared tree
  # would still let the model run.
  local root dir name seen=" "
  for root in "${SKILL_ROOTS[@]}"; do
    for dir in "$root"/*/; do
      [ -d "$dir" ] || continue
      name=$(basename "$dir")
      case "$seen" in *" $name "*) die "skill '$name' exists in both skill roots" ;; esac
      seen="$seen$name "
    done
  done
  local agent
  for agent in "$EVAL_TREE"/home/common/claude-code/agents/*.md; do
    [ -f "$agent" ] && TREE_AGENTS+=("$agent")
  done
  [ "${#TREE_AGENTS[@]}" -gt 0 ] || die "no agent files in $EVAL_TREE/home/common/claude-code/agents"
  [ -f "$EVAL_TREE/home/common/agent-guidance/AGENTS.md" ] ||
    die "EVAL_TREE's AGENTS.md is not a file: $EVAL_TREE/home/common/agent-guidance/AGENTS.md"

  TREE_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/run-eval-tree.XXXXXX") || die "mktemp failed"
  trap 'rm -rf -- "$TREE_ROOT"' EXIT
  trap 'stop_claude_and_exit 130' INT
  trap 'stop_claude_and_exit 143' TERM
  TREE_ROOT=$(cd "$TREE_ROOT" && pwd -P)
  local SHIM_BIN="$TREE_ROOT/bin"
  mkdir -p "$SHIM_BIN" || die "could not create the shim dir under $TREE_ROOT"

  local commands cmd
  commands=$(awk '/^[[:space:]]*commands = \[/ {inside = 1; next} inside && /\];/ {exit} inside {gsub(/[" \t]/, ""); if ($0 != "") print}' "$EVAL_TREE/lib/agent-tools.nix")
  [ -n "$commands" ] || die "no commands found in $EVAL_TREE/lib/agent-tools.nix"
  while IFS= read -r cmd; do
    {
      echo '#!/usr/bin/env bash'
      echo 'unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE'
      printf 'PYTHONPATH=%q exec python3 -P -m agent_tools.%s "$@"\n' "$EVAL_TREE/python" "${cmd//-/_}"
    } >"$SHIM_BIN/$cmd" || die "could not write the $cmd shim"
    chmod +x "$SHIM_BIN/$cmd" || die "could not make the $cmd shim executable"
  done <<<"$commands"

  export PATH="$SHIM_BIN:$PATH"
}

# inject_tree <repo> — make EVAL_TREE's instructions the sandbox repo's project copies:
# .claude/skills/<name> links each skill directory of both roots, .claude/agents/<file>
# links each agent file, and .claude/CLAUDE.md links AGENTS.md (project memory beside the
# fixture's own root CLAUDE.md, which stays as it is). The three injected paths, and only
# those, go in .git/info/exclude: the fixture's tracked .claude/ content and the specs,
# plans and maps an eval writes there must stay visible to git.
inject_tree() {
  local repo=$1 root dir name agent
  [ ! -e "$repo/.claude/skills" ] && [ ! -e "$repo/.claude/agents" ] && [ ! -e "$repo/.claude/CLAUDE.md" ] ||
    die "the fixture already has .claude/skills, .claude/agents or .claude/CLAUDE.md"
  mkdir -p "$repo/.claude/skills" "$repo/.claude/agents" || die "could not create the sandbox's .claude/ dirs"
  for root in "${SKILL_ROOTS[@]}"; do
    for dir in "$root"/*/; do
      [ -d "$dir" ] || continue
      name=$(basename "$dir")
      ln -s "$root/$name" "$repo/.claude/skills/$name" || die "could not link .claude/skills/$name"
    done
  done
  for agent in "${TREE_AGENTS[@]}"; do
    ln -s "$agent" "$repo/.claude/agents/$(basename "$agent")" ||
      die "could not link .claude/agents/$(basename "$agent")"
  done
  ln -s "$EVAL_TREE/home/common/agent-guidance/AGENTS.md" "$repo/.claude/CLAUDE.md" ||
    die "could not link .claude/CLAUDE.md"
  mkdir -p "$repo/.git/info" &&
    printf '%s\n' '# run-eval tree mode: the injected project copies' \
      '/.claude/skills/' '/.claude/agents/' '/.claude/CLAUDE.md' >>"$repo/.git/info/exclude" ||
    die "could not write the sandbox's .git/info/exclude"
}
[ -n "${EVAL_TREE:-}" ] && prepare_tree_env
command -v resolve-project >/dev/null || die "resolve-project is required"

# run_trial <trial-number> — build a fresh sandbox, run the eval, grade it.
# Sets TRIAL_VERDICT and TRIAL_WALL_S. Records one results.jsonl line.
run_trial() {
  local trial=$1

  # --- build the sandbox ------------------------------------------------------

  # `pwd -P` matters: git reports worktree paths as realpaths, and on macOS $TMPDIR is a
  # symlink into /private. Without this the worktree comparison below never matches.
  local WORK REPO ORIGIN OUT
  WORK=$(mktemp -d "${TMPDIR:-/tmp}/eval-$SKILL-$ID.XXXXXX") || die "mktemp failed"
  WORK=$(cd "$WORK" && pwd -P)
  REPO="$WORK/repo"
  ORIGIN="$WORK/origin.git"
  OUT="$WORK/output.txt"

  mkdir -p "$REPO"
  cp -R "$FIXTURE/." "$REPO/"
  # Whatever the operator left lying around in the fixture stays out of the sandbox, so
  # the initial commit is identical on every machine.
  find "$REPO" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null

  git init -q -b main "$REPO"
  git -C "$REPO" config user.name "Eval Harness"
  git -C "$REPO" config user.email "eval@example.invalid"
  # The harness owns this sandbox; signing here would depend on the operator's key.
  # (Skills are still expected never to disable signing themselves — that's a different rule.)
  git -C "$REPO" config commit.gpgsign false
  git -C "$REPO" config tag.gpgsign false
  git -C "$REPO" add -A
  git -C "$REPO" commit -qm "chore: initial tinytask import"

  git init -q --bare -b main "$ORIGIN"
  git -C "$REPO" remote add origin "$ORIGIN"
  git -C "$REPO" push -q -u origin main
  # After the initial commit, before any setup hook stages files: the injected links are
  # never part of the fixture's history.
  [ -n "${EVAL_TREE:-}" ] && inject_tree "$REPO"

  local RESOLVED_PROJECT SPEC_DIR PLAN_DIR
  if ! RESOLVED_PROJECT=$(resolve-project resolve --repo-root "$REPO"); then
    printf '%s\n' "$RESOLVED_PROJECT" >&2
    die "resolver refused the initialized fixture"
  fi
  jq -e 'has("schema_version") and has("project") and has("bindings") and has("capabilities")' \
    <<<"$RESOLVED_PROJECT" >/dev/null || die "resolver returned an invalid snapshot"
  SPEC_DIR=$(jq -er '.bindings.paths.artifacts.specs' <<<"$RESOLVED_PROJECT") ||
    die "resolver snapshot has no specs artifact path"
  PLAN_DIR=$(jq -er '.bindings.paths.artifacts.plans' <<<"$RESOLVED_PROJECT") ||
    die "resolver snapshot has no plans artifact path"

  # --- optional setup hook ----------------------------------------------------

  local PRE_WT=""
  local SETUP_KIND
  SETUP_KIND=$(jq -r '.setup.kind // ""' <<<"$EVAL")
  case "$SETUP_KIND" in
    "") ;;
    dirty-worktree)
      local branch
      branch=$(jq -r '.setup.branch' <<<"$EVAL")
      PRE_WT="$WORK/$branch"
      git -C "$REPO" worktree add -q -b "$branch" "$PRE_WT" origin/main ||
        die "setup: could not create worktree $branch"
      printf '\nHalf-finished sentence from a previous run that ' >>"$PRE_WT/README.md"
      printf 'scratch notes from the interrupted run\n' >"$PRE_WT/NOTES.wip"
      echo "setup: pre-created dirty worktree at $PRE_WT"
      ;;
    shippable-worktree|planned-worktree)
      local spec_rel plan_rel
      PRE_WT="$WORK/worktree-issue-3-rename-flag"
      git -C "$REPO" worktree add -q -b worktree-issue-3-rename-flag "$PRE_WT" origin/main ||
        die "setup: could not create worktree worktree-issue-3-rename-flag"
      spec_rel=${SPEC_DIR#"$REPO"/}
      plan_rel=${PLAN_DIR#"$REPO"/}
      mkdir -p "$PRE_WT/$spec_rel" || die "setup: could not create $spec_rel"
      cp "$SETUPS/issue-3/2026-10-07-issue-3-rename-flag-design.md" "$PRE_WT/$spec_rel/" ||
        die "setup: could not copy the spec"
      git -C "$PRE_WT" add -A && git -C "$PRE_WT" commit -qm "docs(spec): issue 3 rename-flag design" ||
        die "setup: could not commit the spec"
      mkdir -p "$PRE_WT/$plan_rel" || die "setup: could not create $plan_rel"
      cp -R "$SETUPS/issue-3/2026-10-07-issue-3-rename-flag.md" \
        "$SETUPS/issue-3/2026-10-07-issue-3-rename-flag.tasks" "$PRE_WT/$plan_rel/" ||
        die "setup: could not copy the plan"
      git -C "$PRE_WT" add -A && git -C "$PRE_WT" commit -qm "docs(plan): issue 3 rename-flag plan" ||
        die "setup: could not commit the plan"
      if [ "$SETUP_KIND" = shippable-worktree ]; then
        git -C "$PRE_WT" apply "$SETUPS/issue-3/implementation.patch" ||
          die "setup: could not apply the implementation patch"
        git -C "$PRE_WT" add -A && git -C "$PRE_WT" commit -qm "feat: rename list --all to --include-done (#3)" ||
          die "setup: could not commit the implementation"
      fi
      echo "setup: $SETUP_KIND worktree at $PRE_WT"
      ;;
    release-ready)
      git -C "$REPO" tag -a v0.1.0 -m "release: v0.1.0" main &&
        git -C "$REPO" switch -q -c feat/include-done || die "setup: could not tag v0.1.0 and branch"
      git -C "$REPO" apply "$SETUPS/issue-3/implementation.patch" ||
        die "setup: could not apply the implementation patch"
      git -C "$REPO" add -A && git -C "$REPO" commit -qm "feat: rename list --all to --include-done" ||
        die "setup: could not commit the feature"
      git -C "$REPO" switch -q main &&
        git -C "$REPO" merge -q --no-ff -m "Merge branch 'feat/include-done'" feat/include-done ||
        die "setup: could not merge the feature into main"
      git -C "$REPO" branch -q -d feat/include-done &&
        git -C "$REPO" push -q origin main v0.1.0 || die "setup: could not publish main and v0.1.0"
      echo "setup: release-ready main at $(git -C "$REPO" rev-parse --short main)"
      ;;
    *) die "unknown setup kind: $SETUP_KIND" ;;
  esac
  local BASE_MAIN
  BASE_MAIN=$(git -C "$REPO" rev-parse main) || die "setup: could not read main"

  # --- run --------------------------------------------------------------------

  local claude_args=(
    -p "$PROMPT"
    --model "$EVAL_MODEL"
    --dangerously-skip-permissions
    --output-format json
    --no-session-persistence
    --add-dir "$WORK"
  )
  [ -n "${EVAL_MAX_USD:-}" ] && claude_args+=(--max-budget-usd "$EVAL_MAX_USD")
  # Tree mode: project and local settings only, so the user-level skills, agents and
  # memory cannot shadow the project copies; the user's settings come back by flag.
  [ -n "${EVAL_TREE:-}" ] && claude_args+=(--setting-sources project,local --settings "$TREE_SETTINGS")

  echo "workdir: $WORK"
  echo "running: claude -p --model $EVAL_MODEL (timeout ${EVAL_TIMEOUT}s)"
  local start CLAUDE_EXIT
  start=$(date +%s)
  # `exec` makes the job's pid timeout's own, so the trap's TERM reaches timeout, which
  # passes it on to claude.
  ( cd "$REPO" && exec timeout "$EVAL_TIMEOUT" claude "${claude_args[@]}" ) \
    >"$WORK/result.json" 2>"$WORK/stderr.txt" </dev/null &
  CLAUDE_PID=$!
  wait "$CLAUDE_PID"
  CLAUDE_EXIT=$?
  CLAUDE_PID=""
  # The transcript the asserts grep: the result text (raw stdout when no result object
  # parsed), then claude's stderr.
  if ! jq -er 'if type == "object" and (.result | type) == "string" then .result else error("no result") end' \
    "$WORK/result.json" >"$OUT" 2>/dev/null; then
    cat "$WORK/result.json" >"$OUT"
  fi
  cat "$WORK/stderr.txt" >>"$OUT"
  cat "$OUT"
  TRIAL_WALL_S=$(( $(date +%s) - start ))
  echo "claude exited $CLAUDE_EXIT after ${TRIAL_WALL_S}s"
  [ "$CLAUDE_EXIT" = 124 ] && echo "NOTE: the run hit EVAL_TIMEOUT — asserts below grade a truncated run"

  # --- collect worktree state -------------------------------------------------

  local WT="" WT_COUNT=0 line path
  while IFS= read -r line; do
    case "$line" in
      "worktree "*)
        path=${line#worktree }
        [ "$path" = "$REPO" ] && continue
        WT_COUNT=$((WT_COUNT + 1))
        [ -z "$WT" ] && WT=$path
        ;;
    esac
  done < <(git -C "$REPO" worktree list --porcelain)

  # --- grade ------------------------------------------------------------------

  export WORK REPO ORIGIN OUT BASE_MAIN WT WT_COUNT PRE_WT SPEC_DIR PLAN_DIR CLAUDE_EXIT

  echo
  echo "--- asserts ---"
  local failed=0 total=0 assert aname snippet reason ok
  local asserts_json="[]"
  while IFS= read -r assert; do
    total=$((total + 1))
    aname=$(jq -r '.name' <<<"$assert")
    snippet=$(jq -r '.shell' <<<"$assert")
    ok=true
    if reason=$(cd "$REPO" && bash -c "source '$ASSERT_LIB'; $snippet" 2>&1); then
      printf 'PASS  %s\n' "$aname"
    else
      ok=false
      failed=$((failed + 1))
      printf 'FAIL  %s\n' "$aname"
      [ -n "$reason" ] && printf '%s\n' "$reason" | sed 's/^/        /'
    fi
    asserts_json=$(jq -c --arg name "$aname" --argjson pass "$ok" '. + [{name:$name, pass:$pass}]' <<<"$asserts_json")
  done < <(jq -c '.asserts[]' <<<"$EVAL")

  echo
  echo "artifacts kept at: $WORK"

  if [ "$failed" -eq 0 ]; then
    if [ "$EXPECTED_TODAY" = "fail" ]; then
      TRIAL_VERDICT="UNEXPECTED-PASS"
      echo "VERDICT: UNEXPECTED-PASS ($total/$total asserts) — drop \"expected_today\" from this eval"
      [ -n "$NOTE" ] && echo "note: $NOTE"
    else
      TRIAL_VERDICT="PASS"
      echo "VERDICT: PASS ($total/$total asserts)"
    fi
  elif [ "$EXPECTED_TODAY" = "fail" ]; then
    TRIAL_VERDICT="EXPECTED-FAIL"
    echo "VERDICT: EXPECTED-FAIL ($((total - failed))/$total asserts)"
    [ -n "$NOTE" ] && echo "note: $NOTE"
  else
    TRIAL_VERDICT="FAIL"
    echo "VERDICT: FAIL ($((total - failed))/$total asserts)"
  fi

  record_result "$trial" "$TRIAL_VERDICT" "$((total - failed))" "$failed" "$total" \
    "$TRIAL_WALL_S" "$CLAUDE_EXIT" "$WORK" "$asserts_json" "$(usage_json "$WORK/result.json")"
}

FAIL_TRIALS=0
WALL_TIMES=()
VERDICTS=()
for trial in $(seq 1 "$EVAL_TRIALS"); do
  [ "$EVAL_TRIALS" -gt 1 ] && { echo; echo "=== trial $trial/$EVAL_TRIALS ==="; }
  TRIAL_VERDICT=""
  TRIAL_WALL_S=0
  run_trial "$trial"
  WALL_TIMES+=("$TRIAL_WALL_S")
  VERDICTS+=("$TRIAL_VERDICT")
  [ "$TRIAL_VERDICT" = "FAIL" ] && FAIL_TRIALS=$((FAIL_TRIALS + 1))
done

if [ "$EVAL_TRIALS" -gt 1 ]; then
  # p50/p90 by nearest-rank over the sorted wall times.
  sorted=$(printf '%s\n' "${WALL_TIMES[@]}" | sort -n)
  p50=$(echo "$sorted" | awk -v n="$EVAL_TRIALS" 'NR == int((n * 50 + 99) / 100) { print; exit }')
  p90=$(echo "$sorted" | awk -v n="$EVAL_TRIALS" 'NR == int((n * 90 + 99) / 100) { print; exit }')
  ok_trials=$((EVAL_TRIALS - FAIL_TRIALS))
  echo
  echo "=== summary: $ok_trials/$EVAL_TRIALS trials ok (${VERDICTS[*]}) ==="
  echo "wall time: p50 ${p50}s  p90 ${p90}s"
  echo "results appended to: $RESULTS_FILE"
fi

[ "$FAIL_TRIALS" -eq 0 ] && exit 0
exit 1
