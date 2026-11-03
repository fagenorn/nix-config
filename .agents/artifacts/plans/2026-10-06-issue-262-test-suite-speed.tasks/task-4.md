# Task 4: Shared closures at the paired and looped call sites

Per D3 and D9. Hotspot H2: several functions ask `original_commit` about commits they already hold, one closure each. The paired lookup `(original_commit(repo, oid).tree for oid in (base, head))` opens two closures to answer one question. Loops that walk an authenticated range open one more closure per commit. This task moves each such site onto `original_commits`, which answers from one closure.

**Files:**
- Modify: `python/agent_tools/review_actual.py` (`actual_inputs`)
- Modify: `python/agent_tools/review_issue100.py` (`_historical`, `fresh_records` and the function holding the `trees = {name: ...}` line, around line 337)
- Modify: `python/agent_tools/review_issue121.py` (`contribution_edges`, `_writer` and the function holding `base_tree, head_tree = ...`, around line 453)

**Interfaces:**
- Consumes: `agent_tools.review_git.original_commits(repo: Path, oids: Sequence[str]) -> tuple[OriginalCommit, ...]`, from Task 3. It returns one authenticated commit per requested oid, in the order requested, from one `_closure`, and `()` for an empty request. It raises `HistoryError` exactly where `original_commit` would.
- Produces: no new names. Every converted function keeps its signature, return value and exceptions.

**Invariants:**
- Each conversion stays inside the same `try`/`with _authenticated()` block as the code it replaces, so every mapped error (`GenerationError("invalid original history")`, `ContributionError("history_unauthenticated")` and the issue-100 equivalents) is unchanged.
- The checks run in the same order. In `contribution_edges` the `history_nonlinear` check still runs before `edge_facts` for each row. The commits are fetched up front, not taken from the `edge_facts` return.
- Unconverted on purpose: `original_commit(live_repo, pins.live)`, which reads another repository, and the single lookups `original_commit(repo, pins.head).tree` in `_anchors`, the `value["commit"]` lookup near line 315 and `middle and original_commit(repo, middle).tree`.

Exact conversions:
1. `review_actual.actual_inputs`: `base_commit, head_commit = original_commits(repo, (base, head))`, then `base_tree, head_tree = base_commit.tree, head_commit.tree`.
2. `review_issue100`, both paired sites: `base, head = (c.tree for c in original_commits(repo, (pins.base, pins.head)))`.
3. `review_issue100` near line 337:
   - `trees = dict(zip(("base", "live", "head"), (c.tree for c in original_commits(repo, (pins.base, pins.live, pins.head)))))`
   - before the edge loop, `held = dict(zip(commits, original_commits(repo, commits)))`
   - in the loop, `held[oid].parents`
4. `review_issue121.contribution_edges`:
   - `parent, *chain = original_commits(repo, (pins.base, *(row["commit"] for row in expected)))`
   - `for row, commit in zip(expected, chain):` with the loop body otherwise unchanged
5. `review_issue121._writer`, per step:
   - `commit = original_commit(repo, oid)`, then `same = [c.oid for c in original_commits(repo, commit.parents) if tree_entry(repo, c.tree, path) == entry]`
   - keep the `parent` order, so `same[0]` is the same first-matching parent
6. `review_issue121` near line 453: `base_tree, head_tree = (c.tree for c in original_commits(repo, (pins.base, pins.head)))`.

Import `original_commits` from `agent_tools.review_git` in each module.

- [ ] **Step 1: Write the failing gate** (scratch only)

```bash
cat > "${TMPDIR:-/tmp}/issue262-t4-gate.sh" <<'SH'
set -euo pipefail
P=python/agent_tools
for pattern in 'original_commit(repo, oid).tree for oid in' 'original_commit(repo, oid).parents' \
               'original_commit(repo, row["commit"])' 'original_commit(repo, parent).tree' \
               'original_commit(repo, head).tree'; do
  if grep -nF "$pattern" $P/review_actual.py $P/review_issue100.py $P/review_issue121.py; then
    echo "unconverted: $pattern"; exit 1
  fi
done
test "$(grep -c 'original_commits' $P/review_actual.py)" -ge 2
test "$(grep -c 'original_commits' $P/review_issue100.py)" -ge 5
test "$(grep -c 'original_commits' $P/review_issue121.py)" -ge 4
echo T4-GATE-OK
SH
```

- [ ] **Step 2: Run it and watch it fail**

Run: `bash "${TMPDIR:-/tmp}/issue262-t4-gate.sh"`
Expected at the start commit: the gate prints an `original_commit(repo, oid).tree for oid in` match, then `unconverted: ...`, and exits 1.

- [ ] **Step 3: Implement**

Apply conversions 1–6 exactly as listed.

- [ ] **Step 4: Verify**

1. Run `bash "${TMPDIR:-/tmp}/issue262-t4-gate.sh"`. Expect `T4-GATE-OK`.
2. Run these modules, each with `timeout 2400`, logging to `${TMPDIR:-/tmp}/issue262-t4-<name>.log` and reporting the tail only. Each must end `OK`:
   - `tests/test_review_pack.py`
   - `home/common/agent-skills/tests/test_review_package.py`
   - `tests/test_review_issue100.py`
   - `tests/test_review_compact100.py`
   - `tests/test_review_issue121.py`
   - `tests/test_review_compact121.py`
   - `tests/test_review_evidence.py`
3. Run the root's coverage gate. Expect `COVERAGE-GATE-OK 2077 test ids`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/review_actual.py python/agent_tools/review_issue100.py python/agent_tools/review_issue121.py
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id run-20261006-261-262-263-264-265 --worker-id <your worker id> -- \
  -m "perf(review): share one closure across paired commit lookups (#262)" -m "<trailer lines>"
```
