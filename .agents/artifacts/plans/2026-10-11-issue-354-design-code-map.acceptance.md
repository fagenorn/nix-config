# Acceptance record — issue #354

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [evidence] At most 30% of the planner's read calls touch a file the design agent opened — measured: design and planner transcripts of the next three orchestrated nodocom issues, comparing file paths in their read, grep and sed calls; baseline median about 64%. | evidence | The `AC1` line of the measurement script under `Deferred measurement` below, run on the design and planner transcripts of each of the next three orchestrated nodocom issues; threshold: at most 30% | not measured: those three issues have not run and cannot be produced in this repository | — | needs the merged skills installed and three orchestrated nodocom issues | |
| AC2 | [evidence] Median planner turns across those three issues is ≤ 55 — measured: request count in each planner transcript; baseline median 79 over ten issues. | evidence | The `AC2` line of the same script for each of those three planner transcripts; threshold: median ≤ 55 | not measured: same three issues as AC1 | — | needs the merged skills installed and three orchestrated nodocom issues | |
| AC3 | [code] The design phase produces a code map and the planning dispatch names it — measured: design and writing-plans skill evals, one asserting the map exists with at least one entry per spec decision that names a module, one asserting the planner brief carries its path. | code | `env EVAL_TREE=. EVAL_MODEL=sonnet just evals design 1` (asserts 3 and 4) and `… just evals writing-plans 4`; `… just evals writing-plans 1` as the no-code-map check | design 1: row ts 2026-10-11T02:17:14Z, PASS, 6/6 asserts, 1 run (asserts 3 and 4 both pass); writing-plans 4: row ts 2026-10-11T02:19:35Z, PASS, 2/2 asserts, 1 run; writing-plans 1: row ts 2026-10-11T02:23:17Z, PASS, 8/8 asserts, 1 run | a8f4b2423caea0a08bf57de28d2887a3762e613f | tree mode (tree_mode project-skills), sonnet, clean tree (tree_dirty false) at the measured commit | |
| AC4 | [code] Specs remain free of file paths and line numbers — measured: the existing spec-format check in the design skill evals. | code | assert 2 of `design` case 1 in the same run | assert 2 ("the spec's Decisions section names no file path or line number") has pass true in the PASS row of design 1, ts 2026-10-11T02:17:14Z | a8f4b2423caea0a08bf57de28d2887a3762e613f | tree mode (tree_mode project-skills), sonnet, clean tree (tree_dirty false) at the measured commit | |
| AC5 | [human] Plans written from a map are no weaker than before — measured: the maintainer compares plan-review findings on those three issues against the prior ten; no increase in findings that cite a wrong file, symbol or test. | human | The maintainer compares plan-review findings on those three issues against the prior ten | — | — | — | |

## Deferred measurement (AC1, AC2)

Run once per issue, with jq installed: `bash measure.sh DESIGN.jsonl PLANNER.jsonl WORKTREE_ROOT`, where the first two are the design and planner subagent transcripts of that issue. Save the block below as `measure.sh`. A Bash call counts as a read only on a line that runs sed, rg, grep, cat, head or tail, and only its path-shaped tokens are taken. WORKTREE_ROOT is the absolute path of the issue's worktree as it appears in the transcripts, without a trailing slash. Known limits: a file named without any slash is not counted, a command on an indented line is not counted, and a sed expression that looks like a path (for example an `s/a.b/c.d/` substitution) is counted as a read path, which enlarges the total. The script writes design-files.txt and planner-reads.txt into the current directory.

```bash
DESIGN=$1 PLANNER=$2 ROOT=$3
paths() {
  jq -r 'select(.type=="assistant") | .message.content[]? | select(.type=="tool_use")
    | if .name=="Read" then .input.file_path
      elif .name=="Grep" then (.input.path // empty)
      elif .name=="Bash" then (.input.command | split("\n")[]
        | select(test("(^|&& *|; *)(sed|rg|grep|cat|head|tail) "))
        | scan("[A-Za-z0-9_.~-]*/[A-Za-z0-9_./-]*[A-Za-z0-9_-]\\.[A-Za-z0-9]+"))
      else empty end' "$1" | sed -e "s|^$ROOT/||" -e 's|^\./||'
}
paths "$DESIGN" | sort -u > design-files.txt
paths "$PLANNER" > planner-reads.txt
echo "AC1: $(grep -cFxf design-files.txt planner-reads.txt) of $(grep -c . planner-reads.txt) planner read paths are files the design agent opened"
echo "AC2: $(jq -s '[.[] | select(.type=="assistant") | .message.id] | unique | length' "$PLANNER") planner requests"
```
