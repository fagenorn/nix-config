# Task 1: Publish the bundle and its trust pin

The one place committed evidence bytes come from (spec § *Publication*, § *Trust identity*; EV1, EV2, EV5, EV8, EV13; RP11, RP24). The controller's brief must state that G0 cleared at `--completed-through 0` on the current head. Without that statement, stop and report `NEEDS_CONTEXT`.

**Files:**
- Create: `tests/fixtures/retained-review-evidence/derivation-anchor.json`, `derivation-witness.json`, `issue-100-derived.json`, `issue-121.json`, `task7-estimate.json` (in that directory, and nothing else there)
- Create: `tests/retained_evidence_test_support.py`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (three entries in `LEGACY_MIGRATION_INPUTS`)

**Interfaces:**
- Consumes: `python3 -m agent_tools.derive_review_feasibility_fixtures` with exactly `--issue-121-repo`, `--issue-100-repo`, `--archive-dir`, `--tool-repo`, `--tool-commit`, `--output-dir`. Exit 0 prints one canonical JSON line `{"anchor_sha256": "sha256:…", "members": [{path, bytes, raw_sha256} × 5]}` and writes the five files into the new output directory. Any refusal is exit 2, empty stdout and `derive-review-feasibility-fixtures: invalid: <code>`.
- Consumes: `python3 -m agent_tools.replay_retained --fixtures-dir <dir> --expected-anchor-sha256 <digest>`.
- Consumes: `core_gate`, defined in `.agents/artifacts/plans/2026-09-30-issue-233-review-projection-core.md` § *Matching gate environment*. Copy that one shell function verbatim into your shell.
- Produces: `tests/retained_evidence_test_support.py` with `BUNDLE` (a `pathlib.Path`), `ANCHOR_SHA256` and `TOOL_COMMIT` (both `str`). Tasks 2 and 3 import these three names.

**Invariants:**
- The committed files are derivation A's bytes. Nobody edits, reformats, re-encodes or regenerates them by another route, and the directory holds no sixth file.
- `ANCHOR_SHA256` is the literal below, typed from this task and the spec. It is never computed from the bundle. If a derivation prints another digest, do not adopt it: stop, and report which bound identity moved (the tool closure, a policy digest or a retained input).
- `HEAD:python` is tree `6ce6afdda7b95e749184fcd8e132fc0a38de915e`, the pin's. This task changes no path under `python/`.
- A derivation only reads the retained root. The root is compared before and after each one, and a difference voids that derivation. No commit, fetch or gc may run in any worktree of the root while a derivation runs, because every worktree shares the root's refs and object store.
- The support module imports no `agent_tools` and declares no `TestCase`.
- The legacy-surface contract exempts exactly the listed tokens in exactly the three listed bundle files (EV13). Its scan, its token list and every other entry are unchanged.

- [ ] **Step 1: Set up and watch the base fail.**

```bash
set -euo pipefail
TREE=$(git rev-parse --show-toplevel); cd "$TREE"
ROOT=/Users/anis/tmp/nix-config
ARCHIVE=$ROOT/.superpowers/review-evidence/100/direct-100-000002/source-integration-a7b7c6f
PIN=691d8f257615c5698965918b3cca036c2e9ccec9
DIGEST=sha256:d0968f6a9ca20160bd027bb3ce12b5231efa603057a054a76fe37e5f4870a8a5
DIR=tests/fixtures/retained-review-evidence
OUT=$(mktemp -d "${TMPDIR:-/tmp}/ev235-a-XXXXXX")
test "$(git rev-parse HEAD:python)" = 6ce6afdda7b95e749184fcd8e132fc0a38de915e
test -z "$(git ls-tree 8971e41802fd2ee4de8d1c85626ea1cdcf2d384d -- "$DIR")"
if [ -e "$DIR" ] || [ -e tests/retained_evidence_test_support.py ]; then exit 1; fi
```

- [ ] **Step 2: Record the host basis** (RP24; https://github.com/fagenorn/nix-config/issues/255 is open). Any line of output, or a non-zero status, stops publication.

```bash
basis() {
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
basis
```

- [ ] **Step 3: Derivation A.** It takes about three minutes; the bound is thirty.

```bash
before=$(root_digest)
core_gate source "$TREE" "$(command -v python3)" timeout 1800 python3 -m agent_tools.derive_review_feasibility_fixtures \
  --issue-121-repo "$ROOT" --issue-100-repo "$ROOT" --archive-dir "$ARCHIVE" \
  --tool-repo "$TREE" --tool-commit "$PIN" --output-dir "$OUT/a" > "$OUT/a.summary"
test "$(root_digest)" = "$before"
test "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["anchor_sha256"])' "$OUT/a.summary")" = "$DIGEST"
test "$(ls "$OUT/a" | wc -l)" -eq 5
wc -c "$OUT"/a/*.json
```

  Expected sizes: 13,769, 15,891, 62,118, 48,917 and 43,757 B, 184,452 B in all. A different digest or size stops the task as the second invariant says.

- [ ] **Step 4: Copy the bundle and write the pin.**

```bash
mkdir -p "$DIR"
cp "$OUT"/a/*.json "$DIR"/
for name in "$OUT"/a/*.json; do cmp "$name" "$DIR/$(basename "$name")"; done
```

  Write `tests/retained_evidence_test_support.py` exactly:

```python
"""The committed retained review evidence and the identities its tests trust (issue 235; EV1, EV2).

`BUNDLE` is the committed bundle directory. `ANCHOR_SHA256` is the anchor digest
a reader trusts for it, and `TOOL_COMMIT` the reviewed tool commit it was
derived with. Both are literals fixed by review: nothing computes them from the
bundle, so replacing the bundle cannot move them. This module declares no
TestCase and imports no `agent_tools`, so the launcher module can import it.
"""
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent / "fixtures/retained-review-evidence"
ANCHOR_SHA256 = "sha256:d0968f6a9ca20160bd027bb3ce12b5231efa603057a054a76fe37e5f4870a8a5"
TOOL_COMMIT = "691d8f257615c5698965918b3cca036c2e9ccec9"
```

- [ ] **Step 5: List the bundle's historical names.** Three bundle files record legacy policy names as facts of the retained ranges, and the repository-wide scan `test_living_source_has_no_legacy_policy_surface` reads every tracked JSON file under `tests/`. Watch it fail, then add the entries:

```bash
git add "$DIR" tests/retained_evidence_test_support.py
PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -3
```

  Expected: `FAILED (failures=1, …)`. In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, add to `LEGACY_MIGRATION_INPUTS`, directly after the `"python/agent_tools/review_issue100.py"` entry:

```python
    # The committed retained evidence (https://github.com/fagenorn/nix-config/issues/235) records the same
    # historical paths as facts of the retained ranges.
    "tests/fixtures/retained-review-evidence/issue-100-derived.json": frozenset({
        ".claude/skills.config.json", "resolve-bindings",  # policy-gate-pattern
    }),
    "tests/fixtures/retained-review-evidence/issue-121.json": frozenset({".claude/skills.config.json"}),  # policy-gate-pattern
    "tests/fixtures/retained-review-evidence/task7-estimate.json": frozenset({".claude/skills.config.json"}),  # policy-gate-pattern
```

  Repeat the command: it ends `OK`. The scan requires each listed token to be seen in its file, so an entry cannot outlive the bundle.

- [ ] **Step 6: Verify.** Replay a scratch copy sealed: an empty environment, a scratch `HOME` and a `PATH` of one empty directory.

```bash
cp -R "$DIR" "$OUT/copy"; mkdir -p "$OUT/sealed/bin"
replay() {
  (cd "$OUT/sealed" && env -i HOME="$OUT/sealed" PATH="$OUT/sealed/bin" PYTHONPATH="$TREE/python" \
    "$(command -v python3)" -m agent_tools.replay_retained --fixtures-dir "$OUT/copy" \
    --expected-anchor-sha256 "$1" 2>&1; echo "exit=$?")
}
test "$(replay "$DIGEST")" = "replay-retained: projection_unavailable: tasks-1-3,tasks-4-6
exit=2"
test "$(replay "sha256:$(printf '0%.0s' $(seq 64))")" = "replay-retained: invalid: anchor_digest
exit=2"
test "$(python3 -c 'from tests.retained_evidence_test_support import *; print(ANCHOR_SHA256, TOOL_COMMIT, BUNDLE.is_dir())')" = "$DIGEST $PIN True"
```

  The first line is the authentic outcome: replay authenticated the anchor and the four members and validated every payload before it classified the bundle. The second shows the gate can fail.

- [ ] **Step 7: Commit and read the blobs back.** Stage only the seven Files. Check that `printf %s "$subject" | wc -c` is at most 64, then commit `test(review): commit the retained evidence bundle (#235)`.

```bash
for name in "$OUT"/a/*.json; do git cat-file blob "HEAD:$DIR/$(basename "$name")" | cmp - "$name"; done
test "$(git ls-tree --name-only HEAD "$DIR/" | wc -l)" -eq 5
test -z "$(git status --porcelain)"
timeout 7200 just agent-workflow-tests > "$OUT/workflow.log" 2>&1 || { tail -20 "$OUT/workflow.log"; exit 1; }
```

  Equal blobs show that no hook or filter touched the bytes, and the full suite ends `OK`. Report the commit, `$OUT`, the two root digests and the host-basis result. Do not run derivation B.

- [ ] **Step 8: Derivation B (a fresh actor).** The controller dispatches an agent that did not run Steps 1 to 7 and gives it this step, the setup lines of Step 1 without their last line, the `basis` and `root_digest` functions of Step 2, and the path of A's summary file as `A_SUMMARY`. B derives with the built launcher, each issue repository being its own disposable shared clone of the root, and the archive read from the root.

```bash
basis
timeout 3000 just build > "$OUT/build.log" 2>&1
set -- $(nix-store --query --requisites ./result | grep -- '-home-manager-files$'); test "$#" -eq 1; HM=$1
LAUNCHER=$HM/.agents/bin/derive-review-feasibility-fixtures
PY=$(sed -n 's|^exec \(/nix/store/[^/ ]*/bin/python3\) -I -m agent_tools\.derive_review_feasibility_fixtures .*|\1|p' "$LAUNCHER")
test -x "$PY"
git clone -q --shared --no-checkout "$ROOT" "$OUT/repo-121"
git clone -q --shared --no-checkout "$ROOT" "$OUT/repo-100"
before=$(root_digest)
(cd "$OUT" && core_gate built "$HM" "$PY" timeout 1800 "$LAUNCHER" \
  --issue-121-repo "$OUT/repo-121" --issue-100-repo "$OUT/repo-100" --archive-dir "$ARCHIVE" \
  --tool-repo "$TREE" --tool-commit "$PIN" --output-dir "$OUT/b" > "$OUT/b.summary")
test "$(root_digest)" = "$before"
for name in "$OUT"/b/*.json; do git cat-file blob "HEAD:$DIR/$(basename "$name")" | cmp - "$name"; done
test "$(ls "$OUT/b" | wc -l)" -eq 5
cmp "$OUT/b.summary" "$A_SUMMARY"
grep -q "\"anchor_sha256\":\"$DIGEST\"" "$OUT/b.summary"
rm -rf "$OUT/repo-121" "$OUT/repo-100"
```

  Every line must succeed. A difference is not repaired here: the task is not accepted, and the difference goes back to the controller with both summaries.

- [ ] **Step 9: G1 (controller).** Run the plan root's closure check and G1 at the new `HEAD`, record this task's `actual_ranges` and refresh `actual_evidence` in a process-only commit, then renew G0 at `--completed-through 1`. Keep A's and B's summaries, the root digests and both host-basis results in the SDD workspace.

## Forecast basis

Each bundle record is its measured size at this directory (EV8), reproduced at planning by a scratch commit of a bundle derived at the pin: 14,118, 16,243, 62,467, 49,242 and 44,097 B, one added line each. These five are measurements. The other two are estimates: the support module's record measured 1,038 B / +13 and is forecast at 1,536 B / +18, and the contract module's measured 2,323 B / +7 and is forecast at 3,072 B / +9.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":1,"records":[{"bounds":[{"added_lines":1,"boundary":"evidence","deleted_lines":0,"record_bytes":14118,"support":{"covers":["t1-1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-1","last_task":1,"owner":1,"path":"tests/fixtures/retained-review-evidence/derivation-anchor.json"},{"bounds":[{"added_lines":1,"boundary":"evidence","deleted_lines":0,"record_bytes":16243,"support":{"covers":["t1-2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-2","last_task":1,"owner":1,"path":"tests/fixtures/retained-review-evidence/derivation-witness.json"},{"bounds":[{"added_lines":1,"boundary":"evidence","deleted_lines":0,"record_bytes":62467,"support":{"covers":["t1-3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-3","last_task":1,"owner":1,"path":"tests/fixtures/retained-review-evidence/issue-100-derived.json"},{"bounds":[{"added_lines":1,"boundary":"evidence","deleted_lines":0,"record_bytes":49242,"support":{"covers":["t1-4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-4","last_task":1,"owner":1,"path":"tests/fixtures/retained-review-evidence/issue-121.json"},{"bounds":[{"added_lines":1,"boundary":"evidence","deleted_lines":0,"record_bytes":44097,"support":{"covers":["t1-5"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-5","last_task":1,"owner":1,"path":"tests/fixtures/retained-review-evidence/task7-estimate.json"},{"bounds":[{"added_lines":18,"boundary":"evidence","deleted_lines":0,"record_bytes":1536,"support":{"covers":["t1-6"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1-6","last_task":1,"owner":1,"path":"tests/retained_evidence_test_support.py"},{"bounds":[{"added_lines":9,"boundary":"evidence","deleted_lines":0,"record_bytes":3072,"support":{"covers":["t1-7"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t1-7","last_task":1,"owner":1,"path":"home/common/agent-skills/tests/test_workflow_skill_contracts.py"}]}}
```
