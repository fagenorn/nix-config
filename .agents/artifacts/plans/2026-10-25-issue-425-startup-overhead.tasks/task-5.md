# Task 5: AC4 eval evidence

Spec § Evidence runs (no regression), per D7. Run `from-issue` eval 1 once on mbp against this worktree in the eval's tree mode, with the built settings file and `ENABLE_CLAUDEAI_MCP_SERVERS=false` in its environment standing in for `claude-orchestrate`, and record the verdict. The eval appends its own row to the tracked `results.jsonl`, which this task commits with the record. This task changes no code: a FAIL is recorded as observed, never tuned or rerun toward a PASS (D7).

**Files:**
- Modify: `.agents/artifacts/plans/2026-10-25-issue-425-startup-overhead.acceptance.md` (row `AC4`, new section `## AC4 eval output`)
- Modify: `home/common/agent-skills/evals/results/results.jsonl` (the one line the eval run appends)

**Interfaces:**
- Consumes: Task 4's acceptance record (row `AC4` reads `pending (Task 5)`); the built settings artifact in `./result`'s closure; `just evals from-issue 1`, which runs `home/common/agent-skills/evals/run-eval.sh`: with `EVAL_TREE` it links the tree's skills, agents and `AGENTS.md` into the sandbox repository's `.claude/` and passes `--setting-sources project,local --settings "$EVAL_SETTINGS"`; it prints `PASS  <assert>` / `FAIL  <assert>` lines and one `VERDICT: <PASS|FAIL|…> (<n>/<m> asserts)` line, exits 0 only when no trial fails, and appends one JSON line (`ts`, `skill`, `id`, `verdict`, `wall_s`, `tree`, `tree_rev`, `tree_dirty`, `cost_usd`, …) to `results.jsonl`.
- Produces: row `AC4` filled; the sdd controller writes every `Verdict`.

**Invariants:**
- Host `mbp`; `git status --short` prints nothing before the run, so the eval records `tree_dirty: false` and `tree_rev` equal to `CODE_HEAD`.
- One trial, default model (`sonnet`) and default `EVAL_TIMEOUT` (2,700 s); the only environment additions are `EVAL_TREE=<worktree root>`, `EVAL_SETTINGS=<built settings>` and `ENABLE_CLAUDEAI_MCP_SERVERS=false`.
- This task's commit changes, outside the acceptance record, exactly one line of `home/common/agent-skills/evals/results/results.jsonl` (one insertion) and nothing else under `home tests justfile python lib`.

- [ ] **Step 1: Check the preconditions and build**

From the worktree root, `SCRATCH` being the path `launch-scope scratch --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id>` prints:

```bash
hostname -s                    # expect: mbp
git status --short             # expect: no output
CODE_HEAD=$(git rev-parse HEAD)
grep -q '^| AC4 |.*pending (Task 5)' .agents/artifacts/plans/2026-10-25-issue-425-startup-overhead.acceptance.md
```

Run the **Build** (Global Constraints), then `SETTINGS=$(nix-store --query --requisites ./result | grep -- '-claude-code-settings\.json$')` and `jq -e '.skillOverrides | length == 12' "$SETTINGS"`. A different host, a dirty tree, a missing `pending (Task 5)` row or a settings file without the map stops the task as BLOCKED, naming which.

- [ ] **Step 2: Run the eval (foreground, timeout 3600 s)**

```bash
launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  bash -c 'start=$(date -u +%s); EVAL_TREE="$PWD" EVAL_SETTINGS="$1" ENABLE_CLAUDEAI_MCP_SERVERS=false just evals from-issue 1 >"$2/ac4-eval.txt" 2>&1; status=$?; echo "exit $status seconds $(( $(date -u +%s) - start )) at $(date -u +%Y-%m-%dT%H:%M:%SZ)"; exit $status' _ "$SETTINGS" "$SCRATCH"
```

Expected: `exit 0 seconds <n> at <instant>`. A non-zero exit with a `VERDICT:` line is a recorded miss (Step 4). A non-zero exit without one (the harness died before grading) stops the task as BLOCKED with `tail -20 "$SCRATCH/ac4-eval.txt"`.

- [ ] **Step 3: Read the result back**

```bash
grep -E '^(PASS|FAIL)  |^VERDICT:|^claude exited|^NOTE:' "$SCRATCH/ac4-eval.txt"
git diff --numstat -- home/common/agent-skills/evals/results/results.jsonl   # expect: 1	0	…
tail -1 home/common/agent-skills/evals/results/results.jsonl \
  | jq -c '{ts, skill, id, verdict, passed, total, wall_s, tree, tree_rev, tree_dirty, cost_usd}'
```

The appended row has `skill` `from-issue`, `id` `1`, `tree` the worktree root, `tree_rev` `CODE_HEAD` and `tree_dirty` `false`; any other value stops the task as BLOCKED.

- [ ] **Step 4: Fill row AC4 of the acceptance record**

In `.agents/artifacts/plans/2026-10-25-issue-425-startup-overhead.acceptance.md`, row `AC4`:

- `Observed`: the `VERDICT:` line verbatim in backticks, then `<n> PASS / <m> FAIL asserts`, the names of any `FAIL` asserts, and `threshold VERDICT: PASS: met|missed`.
- `Commit`: `CODE_HEAD`'s short SHA.
- `Conditions`: host `mbp`; the exact command with `EVAL_TREE=<worktree root>`, `EVAL_SETTINGS=<$SETTINGS>` and `ENABLE_CLAUDEAI_MCP_SERVERS=false`; the finishing instant and seconds; the results row's `ts`, `wall_s` and `cost_usd`; the `claude exited` line; `one trial, not rerun (D7)`.
- `Verdict` stays `—`.

Append a section `## AC4 eval output` holding the Step 3 `grep` output in one fenced `text` block, followed by the appended `results.jsonl` line in one fenced `json` block.

When the verdict is not `PASS`, report the task DONE_WITH_CONCERNS naming the failed asserts.

- [ ] **Step 5: Verify**

```bash
set -e
f=.agents/artifacts/plans/2026-10-25-issue-425-startup-overhead.acceptance.md
test "$(grep -c '^| AC[1-4] |' "$f")" = 4
grep -q '^| AC4 |.*VERDICT:' "$f"
if grep -q 'pending (Task 5)' "$f"; then exit 1; fi
grep -q '^## AC4 eval output$' "$f"
test "$(git diff --numstat -- home/common/agent-skills/evals/results/results.jsonl | cut -f1,2)" = "$(printf '1\t0')"
```

Expected: every command exits 0 — four rows, AC4 filled, no pending marker, one appended eval row.

- [ ] **Step 6: Commit**

```bash
git add .agents/artifacts/plans/2026-10-25-issue-425-startup-overhead.acceptance.md home/common/agent-skills/evals/results/results.jsonl
launch-commit … -- -m "docs(plan): acceptance record, AC4 eval evidence (issue 425)" -m "<session trailers>"
```

Verify: `git status --short` prints nothing, and `git diff --numstat "$CODE_HEAD"..HEAD -- home tests justfile python lib` prints exactly one line, `1	0	home/common/agent-skills/evals/results/results.jsonl`.
