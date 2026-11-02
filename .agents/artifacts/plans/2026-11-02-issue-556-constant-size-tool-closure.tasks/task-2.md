# Task 2: Re-issue the committed evidence at `T`

The one place the new committed bytes come from (spec § *Committed evidence*; D4, D5, D8, D9, D10; EVIDENCE's publication protocol as D5 adapts it; RP11, RP24). The controller's brief must state that Task 1's review has passed with its fixes committed. Without that statement, stop and report `NEEDS_CONTEXT`: `T` is fixed only then.

Run every long command from the worktree root, in the foreground, as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <command>` with the timeout shown.

**Files:**
- Modify: `tests/fixtures/retained-review-evidence/derivation-anchor.json`, `tests/fixtures/retained-review-evidence/derivation-witness.json` (replaced by derivation A's bytes)
- Modify: `tests/retained_evidence_test_support.py` (the `ANCHOR_SHA256` and `TOOL_COMMIT` literals only)

The other three bundle files are overwritten by A's files too and must come out byte for byte unchanged, so they never appear in a diff.

**Interfaces:**
- Consumes: Task 1's encoding at `T`; `python3 -m agent_tools.derive_review_feasibility_fixtures` with exactly `--issue-121-repo`, `--issue-100-repo`, `--archive-dir`, `--tool-repo`, `--tool-commit`, `--output-dir` (exit 0 prints one canonical line `{"anchor_sha256": "sha256:…", "members": [5 × {path, bytes, raw_sha256}]}`; a refusal is exit 2, empty stdout, `derive-review-feasibility-fixtures: invalid: <code>`); `python3 -m agent_tools.replay_retained --fixtures-dir <dir> --expected-anchor-sha256 <digest>`; `root_state` from `tests/test_review_retained_full.py`.
- Produces: `TOOL_COMMIT = T` and `ANCHOR_SHA256 = ` A's `anchor_sha256`, the two literals every committed-copy test trusts (EV2); the final gate's tier run (derivation B, D5 step 4) must reproduce both.

**Invariants:**
- The five committed files are A's bytes. Nobody edits, reformats or re-encodes them, and the directory holds no sixth file.
- A's three fixture payloads equal the committed ones byte for byte. If one differs, publication stops and the report names the bound identity that moved (a policy digest, a retained input or the archive); new payload bytes are never adopted (D5 step 3, EVIDENCE step 4).
- `HEAD:python` equals `T:python` from Step 1 to the end; this task changes no path under `python/`.
- Derivation only reads the retained root: its `root_state` digest is equal before and after, or the run is void and repeated (RP11). The root is private (D10), never the shared checkout.
- The literals are typed from A's summary and `T`. Nothing computes them from the committed bundle.

- [ ] **Step 1: Set up, fix `T` and watch the committed copy fail**

```bash
set -euo pipefail
TREE=$(git rev-parse --show-toplevel); cd "$TREE"
MAIN=/Users/anis/tmp/nix-config
ARCHIVE=.superpowers/review-evidence/100/direct-100-000002/source-integration-a7b7c6f
DIR=tests/fixtures/retained-review-evidence
OUT=$(mktemp -d "$(launch-scope scratch --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id>)/ev556-XXXXXX")
T=$(git log -1 --no-merges --format=%H -- python)
test "$(git rev-parse "$T:python")" = "$(git rev-parse HEAD:python)"
if git merge-base --is-ancestor "$T" origin/main; then exit 1; fi
test -z "$(git status --porcelain -- python tests)"
```

`T` is the last branch commit that changes `python/`, Task 1's reviewed head; the `merge-base` check fails if it is `main`'s.

Run: `env PYTHONPATH=python timeout 900 python3 -m unittest tests/test_review_evidence.py 2>&1 | tail -1`
Expected: `FAILED (failures=1, errors=4)` over 8 tests. `test_authentic_copy_replays_to_the_historical_refusal` fails because replay prints `invalid: component_mismatch`, and the three fact cases and `test_rehashed_changes_are_refused_under_either_digest` raise `WitnessError: component_mismatch`: the committed bundle still holds the 57-row list that `T`'s validator refuses (D4, D9).

- [ ] **Step 2: Build the private root and record the host basis** (D10; RP24, #255 open)

```bash
make_root() {  # $1: a new path
  git clone -q --no-local --no-checkout "$MAIN" "$1"
  cp -R "$MAIN/.git/objects/." "$1/.git/objects/"   # the unreachable pins, e.g. fe85677c
  mkdir -p "$1/$(dirname "$ARCHIVE")"; cp -R "$MAIN/$ARCHIVE" "$1/$ARCHIVE"
}
basis() {  # any output line or a non-zero status stops publication
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
```

- [ ] **Step 3: Derivation A, in `T`'s matching source environment** (D8)

`T`'s package, budget helper and policy, wired exactly as `source_budget_env(tmp, clone)` wires them for the tier's reproduction case. It took 2 min 13 s while planning; the bound is 30 min.

```bash
git clone -q --shared --no-checkout "$TREE" "$OUT/tool"
git -C "$OUT/tool" checkout -q --detach "$T"
H=$OUT/budget-home; mkdir -p "$H/.agents/lib/python" "$H/.agents/share"
ln -s "$OUT/tool/home/common/agent-skills/scripts/artifact_budget.py" "$H/.agents/lib/python/artifact_budget.py"
ln -s "$OUT/tool/home/common/agent-skills/artifact-budget-policy.json" "$H/.agents/share/artifact-budget-policy.json"
before=$(root_digest)
(cd "$OUT" && env HOME="$H" PYTHONPATH="$OUT/tool/python" PATH="$OUT/tool/home/common/agent-skills/scripts:$PATH" \
  timeout 1800 python3 -m agent_tools.derive_review_feasibility_fixtures \
  --issue-121-repo "$ROOT" --issue-100-repo "$ROOT" --archive-dir "$ROOT/$ARCHIVE" \
  --tool-repo "$OUT/tool" --tool-commit "$T" --output-dir "$OUT/a" > "$OUT/a.summary")
test "$(root_digest)" = "$before"
for name in issue-100-derived.json issue-121.json task7-estimate.json; do cmp "$OUT/a/$name" "$DIR/$name"; done
test "$(ls "$OUT/a" | wc -l)" -eq 5
wc -c "$OUT"/a/*.json
```

Expected sizes: anchor 4,671 B, witness 6,794 B, then 62,118, 48,917 and 43,757 B, 166,257 B in all. Every tool member is fixed-width, so these hold for any `T` (D7). A `cmp` failure stops the task as the second invariant says.

- [ ] **Step 4: Copy the bundle and write the literals**

```bash
cp "$OUT"/a/*.json "$DIR"/
for name in "$OUT"/a/*.json; do cmp "$name" "$DIR/$(basename "$name")"; done
python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["anchor_sha256"])' "$OUT/a.summary"; echo "$T"
```

In `tests/retained_evidence_test_support.py`, type the printed digest into `ANCHOR_SHA256 = "sha256:…"` and `T` into `TOOL_COMMIT = "…"`. Nothing else in the module changes. Then `git status --porcelain` lists exactly the two anchor and witness files and the support module.

- [ ] **Step 5: Verify**

Run: `env PYTHONPATH=python timeout 900 python3 -m unittest tests/test_review_evidence.py 2>&1 | tail -1`
Expected: `OK` (the authentic replay to `projection_unavailable: tasks-1-3,tasks-4-6`, the literal facts, the tamper, trusted-site and rehashed tables, now on the shape `T` emits).

Run: `env PYTHONPATH=python timeout 600 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_living_source_has_no_legacy_policy_surface 2>&1 | tail -1`
Expected: `OK` (1 test); the scan reads every tracked JSON under `tests/`, and its three bundle entries still match the unchanged payloads.

Sealed replay of a scratch copy, which must print the authentic outcome under the new literal and refuse a zero digest:

```bash
cp -R "$DIR" "$OUT/copy"; mkdir -p "$OUT/sealed/bin"
replay() {
  (cd "$OUT/sealed" && env -i HOME="$OUT/sealed" PATH="$OUT/sealed/bin" PYTHONPATH="$TREE/python" \
    "$(command -v python3)" -m agent_tools.replay_retained --fixtures-dir "$OUT/copy" \
    --expected-anchor-sha256 "$1" 2>&1; echo "exit=$?")
}
DIGEST=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["anchor_sha256"])' "$OUT/a.summary")
test "$(replay "$DIGEST")" = "replay-retained: projection_unavailable: tasks-1-3,tasks-4-6
exit=2"
test "$(replay "sha256:$(printf '0%.0s' $(seq 64))")" = "replay-retained: invalid: anchor_digest
exit=2"
```

- [ ] **Step 6: Commit and read the blobs back**

Stage only the three Files, then `launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "test(review): re-derive the retained evidence at T (issue 556)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`.

```bash
for name in "$OUT"/a/*.json; do git cat-file blob "HEAD:$DIR/$(basename "$name")" | cmp - "$name"; done
test "$(git ls-tree --name-only HEAD "$DIR/" | wc -l)" -eq 5
test "$(git rev-parse HEAD:python)" = "$(git rev-parse "$T:python")"
test -z "$(git status --porcelain -- python tests)"
```

Equal blobs show no hook or filter touched the bytes.

- [ ] **Step 7: The retained tier, in full** (acceptance 1; D9)

This run is derivation A's own check, not derivation B. B is the final gate's run by another actor (D5 step 4). The recipe builds first; the tier takes about half an hour.

```bash
basis
test "$(root_digest)" = "$before"
timeout 14400 just agent-retained-tests "$ROOT" > "$OUT/retained.log" 2>&1 || { tail -40 "$OUT/retained.log"; exit 1; }
tail -1 "$OUT/retained.log" | grep -qx 'OK'
for case in test_bundle_files_fit_the_whole_record_caps test_committed_evidence_reproduces_with_the_reviewed_tool \
            test_committed_evidence_replays_alike_from_source_and_built; do
  grep -A1 "^$case " "$OUT/retained.log" | grep -q '\.\.\. ok$'
done
```

A voided case (the root changed, RP11) is repeated on a new root from `make_root`, never accepted. Fill acceptance-record row `AC1` with the command, the head, the root's construction (D10), the basis result and the log's last line. Report `T`, `$OUT` (A's summary and the log), the two root digests and the basis result to the controller.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":2,"records":[{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":22528,"support":{"covers":["r2a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2a","last_task":2,"owner":2,"path":"tests/fixtures/retained-review-evidence/derivation-anchor.json"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":27648,"support":{"covers":["r2b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2b","last_task":2,"owner":2,"path":"tests/fixtures/retained-review-evidence/derivation-witness.json"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":4,"record_bytes":3072,"support":{"covers":["r2c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2c","last_task":2,"owner":2,"path":"tests/retained_evidence_test_support.py"}]}}
```
