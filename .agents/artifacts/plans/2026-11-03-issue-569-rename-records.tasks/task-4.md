# Task 4: Acceptance evidence: the ten #178 moves and the retained tier

This task changes no code. It measures AC6, the ten #178 pure moves under both policies, and AC8's retained tier on a private quiescent root, at the head Tasks 1–3 left. Then it writes the acceptance record (D18). The controller writes each row's `Verdict` later.

The controller's brief must state that Task 3's review has passed with its fixes committed; without that, stop and report `NEEDS_CONTEXT`, because the evidence must be measured at the final code head.

Run every long command from the worktree root, in the foreground, as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with the timeout shown.

**Files:**
- Create: `.agents/artifacts/plans/2026-11-03-issue-569-rename-records.acceptance.md`

**Interfaces:**
- Consumes: Tasks 1–3 at `T`, the last branch commit that changes `python/`. It uses `actual_inputs_from_trees(…, record_policy=…)` with `RECORD_POLICY_V1` and `RECORD_POLICY`, and the recipe `just agent-retained-tests <root>`.
- Produces: the acceptance record, one row per criterion. AC6 and AC8 carry measured `Observed`, `Commit` and `Conditions`.

**Invariants:**
- `HEAD:python` equals `T:python` from Step 1 to the end; this task changes no path outside its one file.
- Every scratch path lives under the root `launch-scope scratch --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id>` prints.
- The retained root is private and quiescent: built by `make_root` below, never the shared checkout. Its `root_digest` is equal before and after the tier, or the run is void and repeated.

- [ ] **Step 1: Set up and fix `T`**

```bash
set -euo pipefail
TREE=$(git rev-parse --show-toplevel); cd "$TREE"
MAIN=/Users/anis/tmp/nix-config
BASE=3be26be2878da02e4aa9417719f3388f08f0298c
ARCHIVE=.superpowers/review-evidence/100/direct-100-000002/source-integration-a7b7c6f
OUT=$(mktemp -d "$(launch-scope scratch --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id>)/ev569-XXXXXX")
T=$(git log -1 --no-merges --format=%H -- python)
test "$(git rev-parse "$T:python")" = "$(git rev-parse HEAD:python)"
test -z "$(git status --porcelain -- python tests home)"
```

Shell variables do not survive between Bash calls: write `OUT` and `T` down and substitute them as literals in later steps.

- [ ] **Step 2: AC6, the ten #178 pure moves under both policies**

A detached clone of `BASE` takes the ten `git mv`s that #178's spec lists (no other edit), and the branch's package measures the range under each policy:

```bash
git clone -q --shared "$MAIN" "$OUT/m178"
git -C "$OUT/m178" checkout -q --detach "$BASE"
env PYTHONPATH="$TREE/python" timeout 600 python3 - "$OUT/m178" <<'EOF'
import subprocess, sys
from pathlib import Path
from agent_tools.review_actual import RECORD_POLICY, RECORD_POLICY_V1, actual_inputs_from_trees
from agent_tools.review_pack import ReviewLimits
repo = Path(sys.argv[1])
def git(*a):
    return subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True).stdout.strip()
base, S, T = git("rev-parse", "HEAD"), "home/common/agent-skills/scripts", "python/agent_tools"
moves = [("workflow-state.py", "workflow_state.py"), *((n, n) for n in (
    "workflow_delivery.py", "workflow_delivery_wire.py", "workflow_delivery_build.py", "artifact_budget.py",
    *(f"delivery_model/{m}.py" for m in ("__init__", "_canonical", "_objects", "_reconcile", "_wire"))))]
(repo / T / "delivery_model").mkdir(exist_ok=True)
for old, new in moves:
    git("mv", f"{S}/{old}", f"{T}/{new}")
git("-c", "user.name=Evidence", "-c", "user.email=evidence@example.test", "-c", "commit.gpgsign=false",
    "commit", "-qm", "the ten #178 pure moves")
head = git("rev-parse", "HEAD")
trees = [git("rev-parse", f"{c}^{{tree}}") for c in (base, head)]
for policy in (RECORD_POLICY_V1, RECORD_POLICY):
    item = next(actual_inputs_from_trees(repo, *trees, base=base, head=head, commits=(), package_name="review.json",
                                         limits=ReviewLimits(16384, 65536, 8, 524288), record_policy=policy))
    records = item.records
    print(policy["kind"], len(records), sum(len(r.payload) for r in records),
          all(b"\nsimilarity index 100%\n" in r.payload and b"\n@@ " not in r.payload for r in records),
          item.stat, head)
EOF
```

Expected, two lines (measured while planning, at the tree Task 1 leaves):

```
review-git-records/v1 10 2618 True {'files_changed': 10, 'insertions': 0, 'deletions': 0} <head>
review-git-records/v2 10 2618 True {'files_changed': 10, 'insertions': 0, 'deletions': 0} <head>
```

Any other count, byte total or a `False` means AC6 is unmet. Stop and report it; never adjust the moves.

- [ ] **Step 3: AC8, the retained tier on a private quiescent root**

```bash
make_root() {  # $1: a new path
  git clone -q --no-local --no-checkout "$MAIN" "$1"
  cp -R "$MAIN/.git/objects/." "$1/.git/objects/"   # the unreachable pins, e.g. fe85677c
  mkdir -p "$1/$(dirname "$ARCHIVE")"; cp -R "$MAIN/$ARCHIVE" "$1/$ARCHIVE"
}
basis() {  # any output line or a non-zero status voids the run
  for repo in "$TREE" "$ROOT"; do
    found=$(find "$repo" \( -name .git -o -name .worktrees \) -prune -o -name .gitattributes -print -quit)
    if [ -n "$found" ]; then echo "attributes file: $found"; return 1; fi
    for dir in $(git -C "$repo" rev-parse --path-format=absolute --git-dir --git-common-dir); do
      if [ -e "$dir/info/attributes" ]; then echo "attributes file: $dir/info/attributes"; return 1; fi
    done
    if git -C "$repo" config --show-scope --get-regexp '^(diff\.|core\.attributesfile$)'; then return 1; fi
  done
  if [ -e "${XDG_CONFIG_HOME:-$HOME/.config}/git/attributes" ]; then echo "global attributes file"; return 1; fi
}
root_digest() {
  PYTHONPATH=python python3 -c '
import json, sys
from tests.test_review_retained_full import root_state
print(json.dumps(root_state(sys.argv[1]), sort_keys=True))' "$ROOT" | shasum -a 256 | cut -d" " -f1
}
ROOT=$OUT/root; make_root "$ROOT"
basis
before=$(root_digest)
timeout 14400 just agent-retained-tests "$ROOT" > "$OUT/retained.log" 2>&1 || { tail -40 "$OUT/retained.log"; exit 1; }
basis
test "$(root_digest)" = "$before"
tail -3 "$OUT/retained.log"
grep -cE '^(test_bundle_files_fit_the_whole_record_caps|test_committed_evidence_reproduces_with_the_reviewed_tool|test_hostile_record_sources_reproduce_the_clean_bundle|test_issue100_domains_are_exact_and_distinct) \(' "$OUT/retained.log"
if grep -Eq '\.\.\. (skipped|FAIL|ERROR)' "$OUT/retained.log"; then exit 1; fi
```

The recipe runs `just build` first; the tier took about 21 minutes for #556. Expected: the last line is `OK`, after `Ran N tests`; the count is `4`, so each named case ran (a case with a docstring prints its `... ok` on the docstring's line); neither `basis` prints anything; the digest is unchanged. The four named cases are AC8's retained substance and AC7's reproduction at `TOOL_COMMIT`. A `just agent-retained-tests` failure is a finding to report, never a reason to edit the bundle, `ANCHOR_SHA256` or `TOOL_COMMIT`.

- [ ] **Step 4: Write the acceptance record**

Create the file with this header and one row per criterion, AC1 to AC8:

```markdown
# Acceptance record — issue #569

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
```

- `Criterion` is the issue's criterion line verbatim, without its checkbox. Read the lines from `env -u GITHUB_TOKEN gh issue view 569 --repo fagenorn/nix-config --json body --jq .body`.
- `Kind` and `Check or command` are the plan's `## Acceptance map` row.
- AC6: `Observed` is Step 2's two lines; `Commit` is `T`; `Conditions` is `detached clone of BASE, ten git mv only, branch package at T via PYTHONPATH, git 2.51.2`.
- AC8: `Observed` is `retained tier: last log line OK after Ran <N> tests, no skip, the four named cases ok; just build and just agent-workflow-tests in final verification`; `Commit` is `T`; `Conditions` is `private root from make_root under launch-scope scratch, basis empty before and after, root digest <before> unchanged`.
- Every `code` row: `Observed` is `in final verification`, `Commit` is `—`, and `Conditions` is `final head, sdd final verification`.
- Every `Verdict` cell is `—`: the controller grades.

Escape a literal `|` inside a cell as `\|`.

- [ ] **Step 5: Verify and commit**

```bash
test "$(grep -c '^| AC[1-8] |' .agents/artifacts/plans/2026-11-03-issue-569-rename-records.acceptance.md)" = 8
test "$(git rev-parse HEAD:python)" = "$(git rev-parse "$T:python")"
test "$(git status --porcelain | wc -l)" -eq 1
```

Expected: exit 0. Then stage only the record and run `launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "docs(issue-569): record the acceptance evidence" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":4,"records":[{"bounds":[{"added_lines":14,"boundary":"all","deleted_lines":0,"record_bytes":12288,"support":{"covers":["r4a"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r4a","last_task":4,"owner":4,"path":".agents/artifacts/plans/2026-11-03-issue-569-rename-records.acceptance.md"}]}}
```
