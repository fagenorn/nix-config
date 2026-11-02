# Task 4: AC4 evidence over the real store and the acceptance record

Spec § Evidence run, per D11 and D14. Run the finished cache report once over this host's real transcripts for the issue's reference window, compare its two headline numbers with the issue's reference values, and record the run in the plan's acceptance record. This task changes no code: a number outside the band is recorded as observed, never tuned toward the target (D11).

**Files:**
- Create: `.agents/artifacts/plans/2026-10-24-issue-421-cache-report.acceptance.md`

**Interfaces:**
- Consumes (Task 3): `just agent-costs --report cache --events-since … --events-before …`, whose stdout holds the header `Cache report (events … → …, <n> transcripts, <n> calls)`, the totals line `Subagent deaths <n> ($<p> premium); main-session deaths <n> ($<p>)` and one `general-purpose` row in the reread table (`agent type  transcripts  reread above  peak p50  peak p90  peak max`).
- Produces: the acceptance record with rows `AC1`–`AC4`, `AC4`'s evidence columns filled; the sdd controller writes every `Verdict`.

**Invariants:**
- The run happens on host `mbp` (`hostname -s`), over `~/.claude/projects`, at a clean code head: `git status --short -- python tests justfile lib` prints nothing before the run, and this task's commit changes no path outside the acceptance record.
- The window is exactly `--events-since 2026-10-10T00:00:00Z --events-before 2026-10-24T21:40:00Z` (D11), threshold default (120,000), no other flag.
- Bands, inclusive: subagent deaths 2,250–3,042 (±15 % of 2,646); `general-purpose` `reread above` $1,870–$2,530 (±15 % of $2,200). Deviations print as `(observed − reference) / reference`, in percent to one decimal.

- [ ] **Step 1: Check the preconditions**

From the worktree root:

```bash
hostname -s                                      # expect: mbp
git status --short -- python tests justfile lib  # expect: no output
git rev-parse HEAD                               # keep as CODE_HEAD (Task 3's commit or later)
du -sh ~/.claude/projects                        # keep for Conditions
```

A different host or a dirty tree stops the task as BLOCKED, naming which.

- [ ] **Step 2: Run the report (foreground, timeout 3600 s)**

`SCRATCH` is the path `launch-scope scratch --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id>` prints.

```bash
launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  bash -c 'start=$(date -u +%s); just agent-costs --report cache --events-since 2026-10-10T00:00:00Z --events-before 2026-10-24T21:40:00Z >"$0/ac4-cache-report.txt" 2>"$0/ac4-cache-report.err"; status=$?; echo "exit $status seconds $(( $(date -u +%s) - start )) at $(date -u +%Y-%m-%dT%H:%M:%SZ)"; exit $status' "$SCRATCH"
```

Expected: `exit 0 seconds <n> at <instant>`. A non-zero exit stops the task as BLOCKED with `tail -5 "$SCRATCH/ac4-cache-report.err"`; do not change code here.

- [ ] **Step 3: Read the numbers back**

```bash
head -1 "$SCRATCH/ac4-cache-report.txt"
grep -n '^Subagent deaths' "$SCRATCH/ac4-cache-report.txt"
grep -n '^general-purpose' "$SCRATCH/ac4-cache-report.txt"
grep -n '^agent type' "$SCRATCH/ac4-cache-report.txt"
cat "$SCRATCH/ac4-cache-report.err"
```

The `general-purpose` row whose line number falls between the second and third `agent type` header lines is the reread row; its third column is the `reread above` dollars. Compute both deviations and whether each value lies in its band.

- [ ] **Step 4: Write the acceptance record**

Create `.agents/artifacts/plans/2026-10-24-issue-421-cache-report.acceptance.md` holding, in order:

1. The heading `# Acceptance record — issue #421`.
2. The sentence `Taken on host mbp; each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/421).`
3. One table with the columns `AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict` and four rows, `AC1` to `AC4` in order:
   - `Criterion`: the issue's acceptance-criterion line verbatim, without its `- [ ] ` checkbox (read it with `gh issue view 421 --repo fagenorn/nix-config --json body --jq .body`), with any `|` escaped as `\|`.
   - `Kind` and `Check or command`: copied from the plan root's Acceptance map.
   - `AC1`–`AC3`: `Observed` is `in final verification`; `Commit` and `Conditions` are `—`.
   - `AC4`: `Observed` holds, verbatim in backticks, the header line, the totals line and the reread table's `general-purpose` row, then `subagent deaths <n> (<±d.d> % of 2,646; band 2,250–3,042: inside|outside)` and `general-purpose reread above 120k $<x> (<±d.d> % of $2,200; band $1,870–$2,530: inside|outside)`. `Commit` is `CODE_HEAD`'s short SHA. `Conditions` names host `mbp`, `~/.claude/projects` and its `du -sh` size, the exact command, the run's finishing instant and seconds, the stderr content (or `stderr empty`), and `rule not tuned (D11)`.
   - `Verdict`: `—` in every row; the sdd controller writes it.
4. A section `## AC4 run output` holding the run's whole stdout in one fenced `text` block.

When a value is outside its band, also report the task DONE_WITH_CONCERNS naming the value and its band.

- [ ] **Step 5: Verify**

In the shell where `SCRATCH` is set:

```bash
set -e
f=.agents/artifacts/plans/2026-10-24-issue-421-cache-report.acceptance.md
test "$(grep -c '^| AC[1-4] |' "$f")" = 4
grep -q '^| AC4 |.*Subagent deaths' "$f"
grep -q '^## AC4 run output$' "$f"
awk '/^```text$/{on=1; next} /^```$/{on=0} on' "$f" | diff - "$SCRATCH/ac4-cache-report.txt"
```

Expected: every command exits 0 and `diff` prints nothing — four rows, AC4's row carries the totals line, and the fenced block is byte-for-byte the run's stdout.

- [ ] **Step 6: Commit**

```bash
git add .agents/artifacts/plans/2026-10-24-issue-421-cache-report.acceptance.md
launch-commit … -- -m "docs(plan): acceptance record, AC4 evidence (issue 421)" -m "<session trailers>"
```

Verify: `git status --short` prints nothing, and `git diff --stat CODE_HEAD..HEAD -- python tests justfile lib` prints nothing.
