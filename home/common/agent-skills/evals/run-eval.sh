#!/usr/bin/env bash
#
# Run one skill eval and grade it.
#
#   run-eval.sh <skill> <eval-id>     e.g. run-eval.sh from-issue 3
#   run-eval.sh <eval-id>             shorthand for skill=from-issue
#
# Pipeline evals ("mode": "pipeline") copy evals/fixture-repo into a fresh temp dir,
# give it a real git history and a bare origin, run `claude -p` with the eval's prompt,
# then grade the artifacts with the eval's scripted asserts. Plan-only evals just print
# the prompt and the expected output for manual or CI grading.
#
# Env: EVAL_MODEL (default sonnet), EVAL_TIMEOUT seconds (default 2700),
#      EVAL_MAX_USD (optional spend ceiling).

set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
FIXTURE="$HERE/fixture-repo"
ASSERT_LIB="$HERE/assert-lib.sh"
SKILLS="$HERE/../skills"

EVAL_MODEL=${EVAL_MODEL:-sonnet}
EVAL_TIMEOUT=${EVAL_TIMEOUT:-2700}

die() { echo "run-eval: $*" >&2; exit 2; }

case $# in
  1) SKILL=from-issue; ID=$1 ;;
  2) SKILL=$1; ID=$2 ;;
  *) die "usage: run-eval.sh [<skill>] <eval-id>" ;;
esac

EVALS_FILE="$SKILLS/$SKILL/evals/evals.json"
[ -f "$EVALS_FILE" ] || die "no evals.json for skill '$SKILL' (looked in $EVALS_FILE)"
command -v jq >/dev/null || die "jq is required"

EVAL=$(jq -ce --argjson id "$ID" '.evals[] | select(.id == $id)' "$EVALS_FILE") ||
  die "no eval with id $ID in $EVALS_FILE"

NAME=$(jq -r '.name' <<<"$EVAL")
MODE=$(jq -r '.mode // "plan-only"' <<<"$EVAL")
PROMPT=$(jq -r '.prompt' <<<"$EVAL")
EXPECTED_TODAY=$(jq -r '.expected_today // "pass"' <<<"$EVAL")
NOTE=$(jq -r '.note // ""' <<<"$EVAL")

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
  exit 0
fi

[ "$MODE" = "pipeline" ] || die "unknown mode '$MODE'"
command -v claude >/dev/null || die "claude CLI is required"
command -v git >/dev/null || die "git is required"

# --- build the sandbox ------------------------------------------------------

# `pwd -P` matters: git reports worktree paths as realpaths, and on macOS $TMPDIR is a
# symlink into /private. Without this the worktree comparison below never matches.
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

SPEC_DIR=$(jq -r '.specDir // ".claude/specs"' "$REPO/.claude/skills.config.json")
PLAN_DIR=$(jq -r '.planDir // ".claude/plans"' "$REPO/.claude/skills.config.json")

# --- optional setup hook ----------------------------------------------------

PRE_WT=""
SETUP_KIND=$(jq -r '.setup.kind // ""' <<<"$EVAL")
case "$SETUP_KIND" in
  "") ;;
  dirty-worktree)
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

claude_args=(
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
start=$(date +%s)
( cd "$REPO" && timeout "$EVAL_TIMEOUT" claude "${claude_args[@]}" ) 2>&1 | tee "$OUT"
CLAUDE_EXIT=${PIPESTATUS[0]}
echo "claude exited $CLAUDE_EXIT after $(( $(date +%s) - start ))s"
[ "$CLAUDE_EXIT" = 124 ] && echo "NOTE: the run hit EVAL_TIMEOUT — asserts below grade a truncated run"

# --- collect worktree state -------------------------------------------------

WT=""
WT_COUNT=0
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
failed=0
total=0
while IFS= read -r assert; do
  total=$((total + 1))
  aname=$(jq -r '.name' <<<"$assert")
  snippet=$(jq -r '.shell' <<<"$assert")
  if reason=$(cd "$REPO" && bash -c "source '$ASSERT_LIB'; $snippet" 2>&1); then
    printf 'PASS  %s\n' "$aname"
  else
    failed=$((failed + 1))
    printf 'FAIL  %s\n' "$aname"
    [ -n "$reason" ] && printf '%s\n' "$reason" | sed 's/^/        /'
  fi
done < <(jq -c '.asserts[]' <<<"$EVAL")

echo
echo "artifacts kept at: $WORK"

if [ "$failed" -eq 0 ]; then
  if [ "$EXPECTED_TODAY" = "fail" ]; then
    echo "VERDICT: UNEXPECTED-PASS ($total/$total asserts) — drop \"expected_today\" from this eval"
    [ -n "$NOTE" ] && echo "note: $NOTE"
    exit 0
  fi
  echo "VERDICT: PASS ($total/$total asserts)"
  exit 0
fi

if [ "$EXPECTED_TODAY" = "fail" ]; then
  echo "VERDICT: EXPECTED-FAIL ($((total - failed))/$total asserts)"
  [ -n "$NOTE" ] && echo "note: $NOTE"
  exit 0
fi

echo "VERDICT: FAIL ($((total - failed))/$total asserts)"
exit 1
