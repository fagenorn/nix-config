# Task 4: Run the three evals in tree mode and write the acceptance record

Background for a reader with no context. Tasks 1 to 3 gave the `design` skill a code map rule, taught `writing-plans` and the autonomous `from-issue` plan dispatch about it, and added two eval cases. This task runs those cases, and the older `writing-plans` case that has no code map, against this worktree's skill text, commits the result rows, and writes the issue's acceptance record. You change no skill text, no eval case and no helper here.

`run-eval.sh` in **working-tree mode** (`EVAL_TREE=.`) makes this checkout's skills the sandbox's project skills, runs `claude -p` on the case's prompt, grades the sandbox, and appends one JSON row per run to `home/common/agent-skills/evals/results/results.jsonl` (committed, append-only). A row records `skill`, `id`, `verdict`, per-assert results, `tree_rev` (this checkout's `HEAD`), `tree_dirty` and `tree_mode`. Read `home/common/agent-skills/evals/README.md` § "Two modes" once.

**Files:**
- Modify: `home/common/agent-skills/evals/results/results.jsonl` (the runner appends rows; nothing is hand-edited)
- Create: `.agents/artifacts/plans/2026-10-11-issue-354-design-code-map.acceptance.md`

**Interfaces:**
- Consumes: `design` case 1 (six asserts) and `writing-plans` case 4 (two asserts) from Task 3; `writing-plans` case 1 (eight asserts, unchanged); the final skill text from Task 2.
- Produces: for each of the three cases, at least one committed row with `verdict` `PASS` for the measured revision; the acceptance record with rows AC1 to AC5 that the plan's Acceptance map cites.

**Invariants:**
- A row counts only when `tree_mode` is `project-skills`, `tree_dirty` is `false`, and `tree_rev` is the commit you measured at (D11).
- `results.jsonl` only grows: every row the runner wrote stays, `FAIL` rows included.
- At most three runs per case. A case with no `PASS` in three runs is a finding, not something to retry (D11).
- After the runs, nothing under the instruction paths differs between the measured commit and `HEAD`.

- [ ] **Step 1: Check the precondition**

Run: `git status --porcelain | grep -v '^?? ' ; MEASURED=$(git rev-parse HEAD); echo "$MEASURED"; just agent-instruction-budget`
Expected: no line before the SHA (no tracked file is modified), then the SHA, then `check: pass`. Uncommitted work from Tasks 1 to 3 means stop: that commit belongs to those tasks. Note the SHA: shell variables do not survive between tool calls, so Step 3 sets `MEASURED` to it again.

- [ ] **Step 2: Run the three evals**

Run each from the worktree root, in the foreground, with a 3600 s tool timeout (the runner's own `EVAL_TIMEOUT` default is 2700 s). `SCRATCH` is your scratch directory. With a `Lifecycle worker:` line in your prompt, put `launch-scope exec … --` before `env`.

Run: `env EVAL_TREE=. EVAL_MODEL=sonnet just evals design 1 > "$SCRATCH/design-1.log" 2>&1; tail -n 12 "$SCRATCH/design-1.log"`
Expected: a `VERDICT: PASS (6/6 asserts)` line.

Run: `env EVAL_TREE=. EVAL_MODEL=sonnet just evals writing-plans 4 > "$SCRATCH/writing-plans-4.log" 2>&1; tail -n 8 "$SCRATCH/writing-plans-4.log"`
Expected: a `VERDICT: PASS (2/2 asserts)` line.

Run: `env EVAL_TREE=. EVAL_MODEL=sonnet just evals writing-plans 1 > "$SCRATCH/writing-plans-1.log" 2>&1; tail -n 14 "$SCRATCH/writing-plans-1.log"`
Expected: a `VERDICT: PASS (8/8 asserts)` line. This case has no code map; it is the check that an absent one changes nothing.

On a `FAIL`: read the `FAIL` lines and their indented reasons in the log, and the kept sandbox the log names after `artifacts kept at:`. Run that case again, up to three runs in total. If none passes, stop and report `BLOCKED` with the failing assert names, their reasons and the sandbox path. Do not edit an assert, a prompt, a helper or skill text to get a pass: a wrong assert goes back to Task 3 and wrong skill text to Task 2, where the byte budget binds.

- [ ] **Step 3: Verify the rows**

Run:

```bash
MEASURED=<the SHA from Step 1>
R=home/common/agent-skills/evals/results/results.jsonl
for case in "design 1 6" "writing-plans 4 2" "writing-plans 1 8"; do
  set -- $case
  jq -e -s --arg skill "$1" --argjson id "$2" --argjson total "$3" --arg rev "$MEASURED" \
    'map(select(.skill == $skill and .id == $id and .verdict == "PASS" and .failed == 0
                and .total == $total and .tree_mode == "project-skills"
                and .tree_dirty == false and .tree_rev == $rev)) | length >= 1' "$R" >/dev/null \
    || { echo "no PASS row at $MEASURED for $1 $2"; exit 1; }
done
if ! git diff --quiet "$MEASURED" -- home/common/agent-skills/skills home/common/claude-code/skills home/common/claude-code/agents home/common/agent-guidance/AGENTS.md home/common/agent-skills/evals/assert-lib.sh; then echo "instruction paths changed since $MEASURED"; exit 1; fi
git diff --numstat -- "$R"
```

Expected: no `no PASS row` and no `instruction paths changed` line; the last line shows added rows and `0` deletions for `results.jsonl`. Before this task ran, no row for `design` existed at all, so the loop cannot pass on the starting commit.

- [ ] **Step 4: Write the acceptance record**

Create `.agents/artifacts/plans/2026-10-11-issue-354-design-code-map.acceptance.md` with this content. Replace each `<…>` with what you observed: `<sha>` is `MEASURED`; for AC3 and AC4 cite the row (`ts`, verdict, `passed`/`total`) and how many runs each case took. Leave the `Verdict` cells empty: the sdd controller writes them.

```markdown
# Acceptance record — issue #354

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [evidence] At most 30% of the planner's read calls touch a file the design agent opened — measured: design and planner transcripts of the next three orchestrated nodocom issues, comparing file paths in their read, grep and sed calls; baseline median about 64%. | evidence | Compare the file paths in the read, grep and sed calls of the design and planner transcripts of the next three orchestrated nodocom issues; threshold: at most 30% | not measured: those three issues have not run and cannot be produced in this repository | — | needs the merged skills installed and three orchestrated nodocom issues | |
| AC2 | [evidence] Median planner turns across those three issues is ≤ 55 — measured: request count in each planner transcript; baseline median 79 over ten issues. | evidence | Request count in each planner transcript of those three issues; threshold: median ≤ 55 | not measured: same three issues as AC1 | — | needs the merged skills installed and three orchestrated nodocom issues | |
| AC3 | [code] The design phase produces a code map and the planning dispatch names it — measured: design and writing-plans skill evals, one asserting the map exists with at least one entry per spec decision that names a module, one asserting the planner brief carries its path. | code | `env EVAL_TREE=. EVAL_MODEL=sonnet just evals design 1` (asserts 3 and 4) and `… just evals writing-plans 4`; `… just evals writing-plans 1` as the no-code-map check | <design 1: row ts, verdict, passed/total, runs; writing-plans 4: the same; writing-plans 1: the same> | <sha> | tree mode, sonnet, clean tree at the measured commit | |
| AC4 | [code] Specs remain free of file paths and line numbers — measured: the existing spec-format check in the design skill evals. | code | assert 2 of `design` case 1 in the same run | <the assert's pass value in the PASS row, with the row ts> | <sha> | tree mode, sonnet, clean tree at the measured commit | |
| AC5 | [human] Plans written from a map are no weaker than before — measured: the maintainer compares plan-review findings on those three issues against the prior ten; no increase in findings that cite a wrong file, symbol or test. | human | The maintainer compares plan-review findings on those three issues against the prior ten | — | — | — | |
```

- [ ] **Step 5: Verify and commit**

Run: `f=.agents/artifacts/plans/2026-10-11-issue-354-design-code-map.acceptance.md; [ "$(grep -c '^| AC[1-5] |' "$f")" -eq 5 ] || { echo "expected five AC rows"; exit 1; }; if grep -q '<' "$f"; then echo "unfilled placeholder"; exit 1; fi; echo record-ok`
Expected: `record-ok`.

```bash
git add home/common/agent-skills/evals/results/results.jsonl .agents/artifacts/plans/2026-10-11-issue-354-design-code-map.acceptance.md
git commit -m "docs(issue-354): eval result rows and acceptance record for the code map"
```

Report in your result: the three verdicts, the number of runs each took, `MEASURED`, and any `FAIL` row's failing assert names.
