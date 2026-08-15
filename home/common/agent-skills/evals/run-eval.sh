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
# Every run appends one JSON line per trial to results/results.jsonl (gitignored):
# skill, id, per-assert pass/fail, wall seconds, verdict, model, budget ceiling.
#
# Env: EVAL_MODEL (default sonnet), EVAL_TIMEOUT seconds (default 2700),
#      EVAL_MAX_USD (optional spend ceiling), EVAL_TRIALS repeat count (default 1;
#      >1 reruns the same eval in fresh sandboxes and prints pass rate + p50/p90
#      wall time so run-to-run comparisons are possible).

set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
FIXTURE="$HERE/fixture-repo"
ASSERT_LIB="$HERE/assert-lib.sh"
# Two skill roots: the shared tree and the Claude-only tree.
SKILL_ROOTS=("$HERE/../skills" "$HERE/../../claude-code/skills")
RESULTS_DIR="$HERE/results"
RESULTS_FILE="$RESULTS_DIR/results.jsonl"

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

# record_result <trial> <verdict> <passed> <failed> <total> <wall_s> <claude_exit> <workdir> <asserts-json>
record_result() {
  mkdir -p "$RESULTS_DIR"
  jq -cn \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg skill "$SKILL" --argjson id "$ID" --arg name "$NAME" --arg mode "$MODE" \
    --arg model "$EVAL_MODEL" --argjson trial "$1" --argjson trials "$EVAL_TRIALS" \
    --arg verdict "$2" --argjson passed "$3" --argjson failed "$4" --argjson total "$5" \
    --argjson wall_s "$6" --arg claude_exit "$7" --arg workdir "$8" --argjson asserts "$9" \
    --arg max_usd "${EVAL_MAX_USD:-}" \
    '{ts:$ts, skill:$skill, id:$id, name:$name, mode:$mode, model:$model,
      trial:$trial, trials:$trials, verdict:$verdict,
      passed:$passed, failed:$failed, total:$total, wall_s:$wall_s,
      claude_exit:($claude_exit | if . == "" then null else tonumber end),
      workdir:($workdir | if . == "" then null else . end),
      eval_max_usd:($max_usd | if . == "" then null else tonumber end),
      asserts:$asserts}' >>"$RESULTS_FILE"
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
  record_result 1 "PRINTED" 0 0 0 0 "" "" "[]"
  exit 0
fi

[ "$MODE" = "pipeline" ] || die "unknown mode '$MODE'"
command -v claude >/dev/null || die "claude CLI is required"
command -v git >/dev/null || die "git is required"

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

  local SPEC_DIR PLAN_DIR
  SPEC_DIR=$(jq -r '.specDir // ".claude/specs"' "$REPO/.claude/skills.config.json")
  PLAN_DIR=$(jq -r '.planDir // ".claude/plans"' "$REPO/.claude/skills.config.json")

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
    *) die "unknown setup kind: $SETUP_KIND" ;;
  esac

  # --- run --------------------------------------------------------------------

  local claude_args=(
    -p "$PROMPT"
    --model "$EVAL_MODEL"
    --dangerously-skip-permissions
    --output-format text
    --no-session-persistence
    --add-dir "$WORK"
  )
  [ -n "${EVAL_MAX_USD:-}" ] && claude_args+=(--max-budget-usd "$EVAL_MAX_USD")

  echo "workdir: $WORK"
  echo "running: claude -p --model $EVAL_MODEL (timeout ${EVAL_TIMEOUT}s)"
  local start CLAUDE_EXIT
  start=$(date +%s)
  ( cd "$REPO" && timeout "$EVAL_TIMEOUT" claude "${claude_args[@]}" ) 2>&1 | tee "$OUT"
  CLAUDE_EXIT=${PIPESTATUS[0]}
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

  export WORK REPO ORIGIN OUT WT WT_COUNT PRE_WT SPEC_DIR PLAN_DIR CLAUDE_EXIT

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
    "$TRIAL_WALL_S" "$CLAUDE_EXIT" "$WORK" "$asserts_json"
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
