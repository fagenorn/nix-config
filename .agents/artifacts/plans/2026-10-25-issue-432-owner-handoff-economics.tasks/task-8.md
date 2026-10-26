# Task 8: Live arms, the A/B and sweep report and the verdict

Spec § A/B report and verdict and test seam 8; per D8, D15, D18, D22 and D23. This task changes no code (a D23 revert aside). Values outside their bounds are recorded as observed, never tuned toward a target. The sdd controller runs Parts A and B itself (D22). Part C may go to an implementer.

**Files:**
- Modify: `.agents/artifacts/plans/2026-10-25-issue-432-owner-handoff-economics.acceptance.md` (`## A/B and sweep report`, `## Verdict`, rows `AC1`–`AC6`)
- Modify: `home/common/agent-skills/evals/results/results.jsonl` (the arms' rows, appended as written)

**Interfaces:**
- Consumes: eval 8 (Task 6); `EVAL_POLICY`/derived settings (Task 5); `--report owners --eval-results … --eval from-issue:8`, `--sweep` and `--policy` (Tasks 2 and 4); `## Replay verdicts` (Task 7).
- Produces: the committed A/B and sweep report. ship-issue pastes its `## Verdict` into the PR body.

**Invariants:**
- Host `mbp` (`hostname -s`). Record `claude --version` and the worktree build's settings path (`nix-store --query --requisites ./result | grep -- '-claude-code-settings\.json$'`, after **Build**).
- An arm = two concurrent invocations of `EVAL_TRIALS=1`. Each runs as `launch-scope exec … -- bash -c 'cd "$0" && TMPDIR="$1" EVAL_TREE="$0" EVAL_SETTINGS="$2" EVAL_MODEL=opus EVAL_MAX_USD=40 EVAL_TIMEOUT="$3" EVAL_TRIALS=1 ./home/common/agent-skills/evals/run-eval.sh from-issue 8 >"$1/arm-<name>-<k>.out" 2>&1; echo "exit $?"' <frozen> <scratch> <settings> <timeout>`, through the Bash tool with `run_in_background: true`.
- `<frozen>` is `git worktree add --detach "$SCRATCH/arm-<name>" <commit>`, where `<commit>` is Task 6's commit for `baseline` and the final code head for `candidate`.
- Deadline (D22): read `deadline_at` from the lifecycle identity. Start an arm only when `deadline_at − now ≥ 100 min`, with `<timeout>` = min(7200, remaining seconds − 600). Otherwise do not start it: write the evidence gap (`not run: attempt deadline <deadline_at>, <n> min left`) into the record's rows and continue.
- While an arm runs, the controller waits for it before any phase gate, hand-off, suspension or exit. Each wait is one bounded `sleep` (≤ 600 s) followed by one check of the `.out` files, repeated as separate calls. A trial is a sample only when its results row has `claude_exit` 0; any other exit, or no row, is an evidence gap even when every assert passed (D26).
- When an arm ends, append the new lines of `<frozen>/home/common/agent-skills/evals/results/results.jsonl` (counted from its line count at the arm's start) to the worktree's `results.jsonl` before removing `<frozen>`.

- [ ] **Part A — Baseline arm** (right after Task 6, before Task 7). Run the preconditions (host, version, `git status --short` empty, **Build**, settings path), then the deadline check. Launch both invocations at Task 6's commit and record the start time in the record. Then continue with Task 7; the wait rule above applies.
- [ ] **Part B — Candidate arm** (after Task 7's last commit). When Task 7 kept no candidate, do not run Part B: AC6 reads `not met: no candidate kept` (spec AC6). Otherwise run the same steps at the final code head, after Part A's trials have ended.
- [ ] **Part C — Report** (after both arms, or after recording their gaps). Run, at the final head:

```bash
just agent-costs --report owners --days 14 --sweep >"$SCRATCH/live-sweep.txt"
just agent-costs --report owners --format json --eval-results home/common/agent-skills/evals/results/results.jsonl \
  --eval from-issue:8 >"$SCRATCH/eval-arms.json"
just agent-costs --report owners --eval-results home/common/agent-skills/evals/results/results.jsonl \
  --eval from-issue:8 >"$SCRATCH/eval-arms.txt"
jq -c --arg rev "<Task 6 commit, full SHA>" 'select(.skill == "from-issue" and .id == 8 and .tree_rev == $rev)' \
  home/common/agent-skills/evals/results/results.jsonl >"$SCRATCH/baseline-rows.jsonl"
just agent-costs --report owners --format json --eval-results "$SCRATCH/baseline-rows.jsonl" \
  --eval from-issue:8 --policy "kept=<the combined row's spec from Task 7>" >"$SCRATCH/eval-predict.json"
```

Write `## A/B and sweep report`, pasting tables verbatim and stating every number with its source:
  1. corpus, pricing source and identity check (from Task 7's record, re-run at the final head);
  2. the baseline policy's $/delivered issue (mean, sd, n);
  3. the threshold sweep table covering 90k, 110k, 140k, 170k, 200k and never (and the per-phase grid when it ran), the chosen value, and why (D7's lowest-cost-unless-inside-the-noise rule, with the paired lower bound that decided it). `never` is a reference row; when it is the cheapest, say so (D27);
  4. each candidate alone and in the final combination: $/delivered, mean saving, lower bound, share, `keep`/`reject`, and `live confirmation required`;
  5. the live arms: per-trial cost, verdict and wall time, then mean ± sd per arm. Calibration compares the candidate arm as the replay predicts it from the baseline trials (the `kept` row's `dollars_per_delivered` in `eval-predict.json`, whose input holds only the baseline arm's rows) with the candidate trials' observed $/delivered;
  6. conditions: host, Claude Code version, settings path, both commits, `absolute_path_calls` per trial, and every evidence gap;
  7. the keepalive simulation's saving, for issue 423.
- D23: if the candidate arm's mean $/delivered is not below the baseline's, or any trial is not `PASS`, `git revert` each kept candidate commit whose `live_confirmation_required` is true (newest first), label the others "replay-only, live unconfirmed", and record AC6 as not met. If an arm has fewer than two `PASS` trials with `claude_exit` 0, AC6 is not met and the report says why.
- `## Verdict`: what works, what does not, the measured numbers, the recommended route, and what keepalive means for issue 423, in at most 15 lines.
- Fill rows `AC1`, `AC4` and `AC6` with `Observed`, `Commit`, `Conditions` and `Verdict` (`met`, `not met` or `evidence gap`); the sdd controller confirms each verdict.
  - `AC1` is met when at least one trial graded asserts 1–5 `PASS`.
  - `AC4` is met when the sweep table holds 90k, 110k, 140k and 170k and the chosen value has its reason.
  - `AC6` follows the rules above.

- [ ] **Verify:** `rg -n "90000|110000|140000|170000" .agents/artifacts/plans/2026-10-25-issue-432-owner-handoff-economics.acceptance.md | wc -l` prints at least 4. `rg -c "pending" <record>` prints `0` for the rows this task owns, unless a gap is recorded. `git diff --stat <Task 7 head>.. -- home/common/agent-skills/evals/results/results.jsonl` shows only appended lines.
- [ ] **Commit:** `docs(plan): issue 432 A/B and sweep report and verdict`, staging the record and `results.jsonl` Each D23 revert is its own commit: `git revert --no-commit <sha>`, then `launch-commit … -- -m "revert: <candidate> (issue 432, D23)"`.
