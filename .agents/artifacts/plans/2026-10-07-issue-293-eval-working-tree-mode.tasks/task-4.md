# Task 4: Record the Sonnet/Opus baseline

This task spends real money and wall time. Fourteen `claude -p` runs execute against the eval sandbox, and each can take up to 45 minutes. Nothing here changes code.

**Files:**
- Modify: `home/common/agent-skills/evals/results/results.jsonl` (append-only; rows come from the runner, never written by hand)
- Create: `.agents/artifacts/plans/2026-10-07-issue-293-eval-working-tree-mode.acceptance.md`

**Interfaces:**
- Consumes from Tasks 1–3:
  - `just evals <skill> <id>`, which runs from the repository root;
  - the env `EVAL_TREE`, `EVAL_MODEL` and `EVAL_TIMEOUT`;
  - the row fields `ts`, `skill`, `id`, `mode`, `model`, `verdict`, `wall_s`, `input_tokens`, `claude_exit`, `tree` and `tree_rev`;
  - the cases `from-issue 1`, `2` and `3`, `ship-issue 5`, `sdd 4`, `ship-release 5` and `orchestrate-issues 7`.
- Produces: the committed baseline rows that S9 compares against, and the acceptance record's evidence for row AC3.

**Invariants:**
- The baseline measures `main`'s skills. Before any run, the instruction paths (D13) at `HEAD` equal `origin/main`'s (spec "Baseline procedure" step 1).
- Tree mode is used when its auth probe passes. Otherwise deployed mode is used, and only after the D9 and D13 identity check passes. Neither mode switches the machine: `just switch` is never run.
- Each (case, model) pair gets one trial (D9). A `FAIL` verdict is recorded as it is, because the baseline is not a gate.
- Every appended line parses as JSON. No row is edited or deleted (D10).

- [ ] **Step 1: Check that the tree is main's skills**

Run from the worktree root:

```bash
git fetch -q origin
git diff --quiet origin/main HEAD -- home/common/agent-skills/skills home/common/claude-code/skills \
  home/common/claude-code/agents home/common/agent-guidance/AGENTS.md \
  ':(exclude)home/common/agent-skills/skills/*/evals/*' ':(exclude)home/common/claude-code/skills/*/evals/*' \
  && echo instruction-paths-match
```

Expected: `instruction-paths-match`. If anything else prints, stop. Report `BLOCKED: instruction paths differ from origin/main`, followed by `git diff --stat origin/main HEAD -- <same pathspec>`. A sync of `main` is the controller's call, not this task's.

- [ ] **Step 2: Choose the mode**

```bash
probe=$(mktemp -d "${TMPDIR:-/tmp}/auth-probe.XXXXXX")
CLAUDE_CONFIG_DIR="$probe" claude auth status >/dev/null 2>&1; probe_status=$?
rm -rf -- "$probe"
echo "probe_status=$probe_status"
```

- `probe_status=0`: set `MODE_ENV="EVAL_TREE=."` (tree mode).
- Otherwise use deployed mode with `MODE_ENV=""`, but first run the D9/D13 identity check below. It must print `deployed-matches-tree`. On any `drift:` line, stop and report `BLOCKED` with those lines. Never run `just switch`.

```bash
drift=0
for s in from-issue ship-issue sdd ship-release; do
  diff -r -x __pycache__ -x evals "$HOME/.claude/skills/$s" "home/common/agent-skills/skills/$s" >/dev/null || { echo "drift: $s"; drift=1; }
done
diff -r -x __pycache__ -x evals "$HOME/.claude/skills/orchestrate-issues" home/common/claude-code/skills/orchestrate-issues >/dev/null || { echo "drift: orchestrate-issues"; drift=1; }
for f in home/common/claude-code/agents/*.md; do
  cmp -s "$f" "$HOME/.claude/agents/$(basename "$f")" || { echo "drift: agents/$(basename "$f")"; drift=1; }
done
cmp -s home/common/agent-guidance/AGENTS.md "$HOME/.claude/CLAUDE.md" || { echo "drift: CLAUDE.md"; drift=1; }
[ "$drift" -eq 0 ] && echo deployed-matches-tree
```

Before any run, record the mode and `git rev-parse --short HEAD` (the measured commit).

- [ ] **Step 3: Launch all 14 runs at once (D17)**

Run this as one foreground Bash call with a tool timeout of 3600000 ms. It returns when the slowest run ends, which is at most 3000 s. Put `$MODE_ENV` in place, or leave it empty in deployed mode:

```bash
LOGS="${TMPDIR:-/tmp}/eval-baseline-293"
mkdir -p "$LOGS"
for model in sonnet opus; do
  for run in from-issue:1 from-issue:2 from-issue:3 ship-issue:5 sdd:4 ship-release:5 orchestrate-issues:7; do
    skill=${run%%:*}; id=${run#*:}
    ( env $MODE_ENV EVAL_MODEL="$model" EVAL_TIMEOUT=2700 timeout 3000 \
        ./home/common/agent-skills/evals/run-eval.sh "$skill" "$id" >"$LOGS/$skill-$id-$model.log" 2>&1
      echo "exit=$?" >>"$LOGS/$skill-$id-$model.log" ) &
  done
done
wait
grep -H '^exit=' "$LOGS"/*.log
grep -l '^run-eval:' "$LOGS"/*.log || echo no-runner-die
```

Expected: 14 `exit=` lines. `0` is a pass, `1` is a recorded `FAIL`, and `124` means the outer timeout fired. The last line is `no-runner-die`. A log containing a `run-eval:` line means the runner died, and per the spec a case that cannot run is fixed before the baseline is recorded. In that case stop, report `BLOCKED` with the die line and the case, and commit nothing.

- [ ] **Step 4: Rerun pairs that have no token count**

```bash
F=home/common/agent-skills/evals/results/results.jsonl
jq -c . "$F" >/dev/null && echo all-lines-parse
jq -rs '[.[] | select(.ts >= "2026-10-07" and .mode == "pipeline" and (.input_tokens | type) == "number") | "\(.skill):\(.id):\(.model)"] | unique | .[]' "$F"
```

Expected: `all-lines-parse`, followed by the `skill:id:model` triples that are covered. If a (skill, model) pair from the five skills × `sonnet`/`opus` has no covered triple at all, rerun one of its cases once, in the foreground, with a tool timeout of 3600000 ms. Use the case whose earlier run ended `124`, or else the first case listed in Step 3:

```bash
env $MODE_ENV EVAL_MODEL=<model> EVAL_TIMEOUT=3300 timeout 3500 ./home/common/agent-skills/evals/run-eval.sh <skill> <id> >"$LOGS/<skill>-<id>-<model>-rerun.log" 2>&1
```

Reruns can go in parallel the same way as Step 3. If a pair is still uncovered after its rerun, stop. Report `BLOCKED` with the pair and its log tails, and commit nothing.

- [ ] **Step 5: Verify AC3**

```bash
jq -s '[.[] | select(.ts >= "2026-10-07" and .mode == "pipeline" and .verdict != null
          and (.wall_s | type) == "number" and (.input_tokens | type) == "number")
        | "\(.skill)/\(.model)"
        | select(test("^(from-issue|ship-issue|sdd|ship-release|orchestrate-issues)/(sonnet|opus)$"))]
       | unique | length' home/common/agent-skills/evals/results/results.jsonl
```

Expected: `10`. At the base commit the file is empty, so this prints `0`. Also print the table that goes in the record:

```bash
jq -rs '.[] | select(.ts >= "2026-10-07" and .mode == "pipeline") | [.skill, .id, .model, .verdict, .wall_s, .input_tokens, .cost_usd] | @tsv' home/common/agent-skills/evals/results/results.jsonl
```

- [ ] **Step 6: Write the acceptance record and commit**

Create `.agents/artifacts/plans/2026-10-07-issue-293-eval-working-tree-mode.acceptance.md` in the schema of `home/common/agent-skills/skills/sdd/final-review.md` § Acceptance record. The heading is `# Acceptance record — issue #293`, followed by the table `| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |` with one row per AC1–AC4:
- The `Criterion` column holds the issue line verbatim, without its checkbox.
- For AC1 and AC2, `Observed` holds `in final verification`, and the other evidence columns hold `—`.
- For AC3, `Observed` holds `10/10 skill×model pairs` and each pair's verdicts, with the total `cost_usd`. `Commit` holds the measured commit from Step 2. `Conditions` holds the mode (`tree` or `deployed`), `1 trial per case`, `EVAL_TIMEOUT 2700`, any reruns, and `ts >= 2026-10-07`.
- For AC4, the evidence columns hold `—`. When Step 2 chose deployed mode, `Conditions` adds `setup-token not yet run; tree-mode auth probe refused`.
- Leave every `Verdict` cell empty, because the controller writes verdicts.

Commit `results.jsonl` and the record together with the message `chore(evals): record the Sonnet/Opus baseline on main's skills (#293)`, using sdd's lifecycle commit rule. Leave the sandboxes in `$TMPDIR` for inspection.

In the task report, give the mode, the measured commit, the 10-pair count, and the per-pair verdict table. If the mode was deployed, state that AC4 (`claude setup-token` on mbp) is still due from the user.
