# Helpers available to every assert snippet in an evals.json.
#
# Sourced by run-eval.sh into a fresh `bash -c` per assert, so an assert is just a
# one-liner calling one of these. Every helper prints its reason to stdout on failure
# (the runner captures and indents it) and returns non-zero.
#
# Environment an assert can rely on:
#   WORK      the eval's temp dir
#   REPO      the fixture checkout (base branch, `main`)
#   ORIGIN    the bare remote
#   OUT       the run's transcript: the result text (or raw stdout when no result
#             object parsed) followed by claude's stderr
#   WT        first worktree other than REPO ("" when none was created)
#   WT_COUNT  how many worktrees exist besides REPO
#   PRE_WT    worktree the setup hook pre-created ("" when the eval has no setup)
#   BASE_MAIN local `main`'s SHA right after the setup hook (the initial commit when
#             there is no setup)
#   SPEC_DIR / PLAN_DIR  absolute paths from the fixture's retained resolver snapshot
#   CLAUDE_EXIT          exit status of the claude run

fail() {
  echo "$*"
  return 1
}

# first_file <glob...> — print the first path matching any glob, or fail.
first_file() {
  local pattern
  for pattern in "$@"; do
    local match
    for match in $pattern; do
      [ -e "$match" ] && { echo "$match"; return 0; }
    done
  done
  fail "no file matched: $*"
}

# has_file <glob...> — at least one match exists.
has_file() {
  first_file "$@" >/dev/null || return 1
}

# section_has_entries <file> <heading> — the heading exists and at least one `### `
# entry follows it before the next `## ` heading. Heading match is case-insensitive:
# agents capitalise "decisions" about half the time and that isn't what's being graded.
section_has_entries() {
  local file="$1" heading="$2"
  [ -f "$file" ] || fail "not a file: $file" || return 1
  awk -v heading="$heading" '
    BEGIN { heading = tolower(heading) }
    index(tolower($0), heading) == 1 { inside = 1; found = 1; next }
    inside && /^## / { inside = 0 }
    inside && /^### / { entries++ }
    END {
      if (!found) { print "heading not found: " heading; exit 1 }
      if (entries < 1) { print "heading present but has no `### ` entries: " heading; exit 1 }
    }
  ' "$file"
}

# ledger_has_rows <file> <heading> — the heading exists and is followed (before the
# next `## `) by at least one data row: a `|`-table row with >= 4 cells that is not
# the header/separator, or a legacy `### ` entry. Case-insensitive like above.
ledger_has_rows() {
  local file="$1" heading="$2"
  [ -f "$file" ] || fail "not a file: $file" || return 1
  awk -v heading="$heading" '
    BEGIN { heading = tolower(heading) }
    index(tolower($0), heading) == 1 { inside = 1; found = 1; next }
    inside && /^## / { inside = 0 }
    inside && /^### / { entries++ }
    inside && /^\|/ && split($0, cells, "|") >= 5 \
      && tolower($0) !~ /\| *id *\|/ && $0 !~ /^[|: -]+$/ { entries++ }
    END {
      if (!found) { print "heading not found: " heading; exit 1 }
      if (entries < 1) { print "heading present but has no ledger rows or `### ` entries: " heading; exit 1 }
    }
  ' "$file"
}

# plan_tasks_verifiable <plan-root> — every task carries at least one falsifiable
# verification line (Expected/Verify/Acceptance/Assert). A root with a `## Task index`
# is graded through its members: each `[task-N.md](<stem>.tasks/task-N.md)` link must
# resolve, beside the root, to a member holding such a line, and an index that links no
# member fails. A root without one is a legacy single-file plan, graded by its
# `### Task N` sections.
plan_tasks_verifiable() {
  local file="$1" dir member members bad=0
  [ -f "$file" ] || fail "not a file: $file" || return 1
  members=$(awk '
    tolower($0) == "## task index" { inside = 1; found = 1; next }
    inside && /^## / { inside = 0 }
    inside {
      while (match($0, /\]\([^)]*\.tasks\/task-[0-9]+\.md\)/)) {
        print substr($0, RSTART + 2, RLENGTH - 3)
        $0 = substr($0, RSTART + RLENGTH)
      }
    }
    END { if (found) print "@index" }
  ' "$file")
  if [ -n "$members" ]; then
    [ "$members" != "@index" ] || fail "the task index links no task member" || return 1
    dir=$(dirname "$file")
    while IFS= read -r member; do
      [ "$member" = "@index" ] && continue
      if [ ! -f "$dir/$member" ]; then
        echo "task member missing: $member"; bad=1
      elif ! grep -Eiq 'expected|verif|acceptance|assert' "$dir/$member"; then
        echo "no verification line in: $member"; bad=1
      fi
    done <<<"$members"
    return "$bad"
  fi
  awk '
    function close_task() {
      if (tasks > 0 && !verified) { print "no verification line under: " title; bad++ }
    }
    # The trailing digit matters: plans carry prose headings like "### Task ordering"
    # under Auto-resolved decisions, and those are not tasks.
    /^##+[[:space:]]+[Tt]ask[[:space:]]+[0-9]/ { close_task(); tasks++; verified = 0; title = $0; next }
    tasks > 0 && tolower($0) ~ /expected|verif|acceptance|assert/ { verified = 1 }
    END {
      close_task()
      if (tasks == 0) { print "no `### Task N` sections found — is this a plan?"; exit 1 }
      exit (bad > 0)
    }
  ' "$file"
}

# out_matches <extended-regex> — the captured claude output matches, case-insensitively.
out_matches() {
  grep -Eiq -- "$1" "$OUT" || fail "output does not match /$1/"
}

# out_lacks <extended-regex> — the captured claude output does not match.
out_lacks() {
  grep -Eiq -- "$1" "$OUT" && fail "output unexpectedly matches /$1/ — $(grep -Eio -m1 -- "$1" "$OUT")"
  return 0
}

# commits_touch <dir> <pathspec...> — HEAD is ahead of main and the commits between
# them touch at least one of the given paths.
commits_touch() {
  local dir="$1"
  shift
  local touched
  touched=$(git -C "$dir" log --oneline main..HEAD -- "$@" 2>/dev/null)
  [ -n "$touched" ] || fail "no commits between main..HEAD touching: $*"
}

# path_unchanged_since <dir> <ref> <pathspec...> — the working tree matches <ref> for
# those paths. Used to prove a phase-5 stop never executed the implementation.
path_unchanged_since() {
  local dir="$1" ref="$2"
  shift 2
  git -C "$dir" diff --quiet "$ref" -- "$@" ||
    fail "$* changed since $ref: $(git -C "$dir" diff --name-only "$ref" -- "$@" | tr '\n' ' ')"
}

# acceptance_map_covers <plan-root> <issue-file> — the plan root's `## Acceptance map`
# holds rows AC1..AC<n>, each once and in issue order, for the n column-0 criterion
# items (`- [ ]`/`- [x]` or `<n>.`) under the issue's `## Acceptance criteria`. A row's
# kind equals the issue's `[code|evidence|human]` tag, or is `<kind> (classified)` for
# an untagged item. With no criteria the map must be the single line
# `None — no acceptance criteria.` Headings match case-insensitively.
acceptance_map_covers() {
  local plan="$1" issue="$2" kinds
  [ -f "$plan" ] || fail "not a file: $plan" || return 1
  [ -f "$issue" ] || fail "not a file: $issue" || return 1
  kinds=$(awk '
    tolower($0) == "## acceptance criteria" { inside = 1; next }
    inside && /^## / { inside = 0 }
    inside && /^- \[[ xX]\] / {
      kind = "untagged"
      if (match($0, /^- \[[ xX]\] \[(code|evidence|human)\] /)) kind = substr($0, 8, RLENGTH - 9)
      out = out (out == "" ? "" : ",") kind
      next
    }
    inside && /^[0-9]+\. / { out = out (out == "" ? "" : ",") "untagged" }
    END { print out }
  ' "$issue")
  awk -v kinds="$kinds" '
    BEGIN { n = (kinds == "" ? 0 : split(kinds, want, ",")) }
    tolower($0) == "## acceptance map" { inside = 1; found = 1; next }
    inside && /^## / { inside = 0 }
    inside && $0 == "None — no acceptance criteria." { none = 1; next }
    inside && /^\|/ {
      split($0, cells, "|")
      id = cells[2]; kind = cells[3]
      gsub(/^[ \t]+|[ \t]+$/, "", id); gsub(/^[ \t]+|[ \t]+$/, "", kind)
      if (tolower(id) == "ac" || id ~ /^[-: ]*$/) next
      rows++
      if (id != "AC" rows) { print "row " rows " is " id ", expected AC" rows; bad++; next }
      if (rows > n) { print id ": no issue criterion for this row"; bad++; next }
      if (want[rows] == "untagged") {
        if (kind !~ /^(code|evidence|human) \(classified\)$/) { print id ": untagged criterion needs <kind> (classified), got " kind; bad++ }
      } else if (kind != want[rows]) { print id ": kind " kind " contradicts the issue tag " want[rows]; bad++ }
    }
    END {
      if (!found) { print "heading not found: ## Acceptance map"; exit 1 }
      if (n == 0) {
        if (!none || rows > 0) { print "issue has no criteria; the map must be the single line: None — no acceptance criteria."; exit 1 }
        exit 0
      }
      if (rows < n) { print "map has " rows " rows for " n " criteria"; bad++ }
      exit (bad > 0)
    }
  ' "$plan"
}
