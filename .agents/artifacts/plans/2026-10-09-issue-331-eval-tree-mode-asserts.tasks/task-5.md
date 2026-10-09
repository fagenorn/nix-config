# Task 5: Measure AC1 — writing-plans eval 1 in tree mode

Run this task last, after Tasks 1–4 are committed; it commits only the row and the record, so sdd's final gate on the final head still covers the measured head's files (D6).

**Files:**
- Modify: `home/common/agent-skills/evals/results/results.jsonl` (the runner appends one row; nothing is hand-edited)
- Create: `.agents/artifacts/plans/2026-10-09-issue-331-eval-tree-mode-asserts.acceptance.md`

**Interfaces:**
- Consumes: Tasks 1–3 committed (runner `</dev/null`, writing-plans case 1's corrected asserts, the corpus shape tests) and Task 4 committed.
- Produces: the committed `results.jsonl` row and acceptance-record row AC1 that the acceptance map cites.

**Invariants:**
- The measured head carries every change to AC1's measured surface (plan root, Global Constraints); `git status --porcelain` is empty before the run, so the row records `tree_dirty: false` (D6, D8).
- The row is the runner's own output: never edited, re-graded or re-run to obtain a different verdict.
- A model-behaviour FAIL with `total` 8 is a real measurement: it is recorded as observed and AC1 is `unmet` (spec Acceptance handling). A row with `total` other than 8 is a harness defect: stop and report BLOCKED with the row, without committing it.

- [ ] **Step 1: Confirm the measured head**

Run: `test -z "$(git status --porcelain)" && git rev-parse HEAD`
Expected: exit 0 and the measured SHA, recorded as `MEASURED`. A non-empty status means the task cannot start: commit or report first.

- [ ] **Step 2: Run the live eval**

From the worktree root, in the foreground with a 3600 s tool timeout (the runner's own `EVAL_TIMEOUT` default is 2700 s):

Run: `SCRATCH=$(launch-scope scratch --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id>); launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- env EVAL_TREE=. EVAL_MODEL=sonnet just evals writing-plans 1 > "$SCRATCH/ac1-eval.log" 2>&1; tail -n 3 "$SCRATCH/ac1-eval.log"`
Expected: a `VERDICT: PASS (8/8 asserts)` line. The log stays on disk; read only failing lines from it.

- [ ] **Step 3: Verify the row**

Run: `tail -n 1 home/common/agent-skills/evals/results/results.jsonl | jq -e --arg rev "$MEASURED" '.skill == "writing-plans" and .id == 1 and .verdict == "PASS" and .model == "sonnet" and .failed == 0 and .total == 8 and .tree_dirty == false and .tree_mode == "project-skills" and .tree_rev == $rev' >/dev/null`
Expected: exit 0. Exit 1 with `total` 8 is the recorded-FAIL case of the invariants; with any other `total`, the task is BLOCKED.

- [ ] **Step 4: Write the acceptance record**

Create the record with this schema (sdd `final-review.md`), Verdict cells `—` for the controller to fill:

```markdown
# Acceptance record — issue #331

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AC1 | [evidence] writing-plans eval 1 PASSes on main in tree mode — measured: EVAL_TREE=. just evals writing-plans 1, sonnet, verdict PASS with all 8 asserts reported | evidence | `EVAL_TREE=. EVAL_MODEL=sonnet just evals writing-plans 1`; threshold: row verdict PASS, failed 0, total 8, tree_dirty false | <row's verdict, passed/total, ts> | <MEASURED> | tree mode on the worktree (tree_rev <MEASURED>), sonnet, clean tree; row committed in results.jsonl | — |
| AC2 | [code] The interim-results copy-identity test covers ship-issue — measured: test_workflow_skill_contracts | code | test_workflow_skill_contracts.py `InterimChildResultContractsTest` | in final verification | — | — | — |
```

Fill the `<…>` cells from the row; `Observed` quotes the row's `verdict`, `passed`/`total` and `ts`.

Run: `grep -c '^| AC[12] |' .agents/artifacts/plans/2026-10-09-issue-331-eval-tree-mode-asserts.acceptance.md`
Expected: `2` (the file does not exist at the starting commit).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/evals/results/results.jsonl .agents/artifacts/plans/2026-10-09-issue-331-eval-tree-mode-asserts.acceptance.md
launch-commit … -- -m "docs(acceptance): record writing-plans eval 1 in tree mode (#331)" -m "<trailers>"
```

This commit touches no measured path, so the row stays fresh against `MEASURED`.
