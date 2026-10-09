# Task 1: Runner reads asserts' stdin from /dev/null, smoke grades the row total

**Files:**
- Modify: `home/common/agent-skills/evals/run-eval.sh` (the grading loop's per-assert `bash -c`, line ~452)
- Modify: `home/common/agent-skills/evals/assert-lib.sh` (header comment only)
- Modify: `home/common/agent-skills/evals/tests/fixtures/setup-smoke-evals.json` (case 3 gains one assert)
- Test: `home/common/agent-skills/evals/tests/test-run-eval-tree.sh` (the setup-smoke loop)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: every assert snippet the runner grades reads `/dev/null` as stdin, so no assert can consume the `jq -c '.asserts[]'` stream (D2). Task 2's `run_assert` mirrors this.

**Invariants:**
- The runner's row `total` equals the number of asserts in the case, whatever an assert reads.
- The per-assert command is otherwise unchanged: same `cd "$REPO"`, same `source '$ASSERT_LIB'; $snippet`, same `2>&1` capture.
- setup-smoke cases 1 and 2 are unchanged; case 3 keeps its four asserts, in order, and gains one before its last (D10).

- [ ] **Step 1: Write the failing smoke check**

In `setup-smoke-evals.json`, case `"id": 3`, insert this object between `"origin carries main and only v0.1.0"` and `"clean main checkout and no worktree"`, so case 3 has five asserts and the new one is fourth:

```json
{
  "name": "an assert reads no input on stdin",
  "shell": "[ -z \"$(cat)\" ] || fail \"stdin carried input: the assert stream leaked into an assert\""
}
```

In `test-run-eval-tree.sh`, beside `row_is_deployed_pass`, add:

```bash
row_total_is_fixture_count() {
  local want
  want=$(jq --argjson id "$1" '.evals[] | select(.id == $id) | .asserts | length' \
    "$EVALS_SRC/tests/fixtures/setup-smoke-evals.json") || return 1
  last_row | jq -e --argjson want "$want" '.total == $want and .failed == 0' >/dev/null
}
```

and inside the `for id in 1 2 3` loop, after the `row is a deployed-mode PASS` check:

```bash
  check "setup smoke $id: the row reports every fixture assert" row_total_is_fixture_count "$id"
```

- [ ] **Step 2: Run the smoke test and watch it fail**

Run: `bash home/common/agent-skills/evals/tests/test-run-eval-tree.sh 2>&1 | grep -E '^(FAIL|ok    setup smoke 3)|test-run-eval-tree:'`
Expected: FAIL lines for `setup smoke 3: every setup assert passes`, `setup smoke 3: the row is a deployed-mode PASS` and `setup smoke 3: the row reports every fixture assert` (the stdin reader swallows the last assert: `total` 4, `failed` 1); cases 1 and 2 pass; final line `test-run-eval-tree: 3 check(s) failed`.

- [ ] **Step 3: Redirect each assert's stdin (per D2)**

In `run-eval.sh`, change the grading line to:

```bash
    if reason=$(cd "$REPO" && bash -c "source '$ASSERT_LIB'; $snippet" </dev/null 2>&1); then
```

In `assert-lib.sh`, replace the header's second paragraph lines

```
# Sourced by run-eval.sh into a fresh `bash -c` per assert, so an assert is just a
# one-liner calling one of these. Every helper prints its reason to stdout on failure
# (the runner captures and indents it) and returns non-zero.
```

with

```
# Sourced by run-eval.sh into a fresh `bash -c` per assert, whose stdin is /dev/null,
# so an assert is just a one-liner calling one of these. Every helper prints its
# reason to stdout on failure (the runner captures and indents it) and returns
# non-zero; `fail` does not exit, so a `fail` that guards later commands is written
# `|| { fail "…"; exit 1; }`.
```

- [ ] **Step 4: Verify**

Run: `bash home/common/agent-skills/evals/tests/test-run-eval-tree.sh 2>&1 | tail -n 1`
Expected: `test-run-eval-tree: all checks passed` (timeout 900 s).

Run: `grep -c "</dev/null 2>&1); then" home/common/agent-skills/evals/run-eval.sh`
Expected: `1` (it prints `0` and exits 1 at the starting commit).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/evals/run-eval.sh home/common/agent-skills/evals/assert-lib.sh home/common/agent-skills/evals/tests/fixtures/setup-smoke-evals.json home/common/agent-skills/evals/tests/test-run-eval-tree.sh
launch-commit … -- -m "fix(evals): asserts read stdin from /dev/null (#331)" -m "<trailers>"
```
