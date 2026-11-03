# Acceptance record — issue #354

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [evidence] At most 30% of the planner's read calls touch a file the design agent opened — measured: design and planner transcripts of the next three orchestrated nodocom issues, comparing file paths in their read, grep and sed calls; baseline median about 64%. | evidence | The `AC1` line of the measurement script under `Deferred measurement` below, run on the design and planner transcripts of each of the next three orchestrated nodocom issues; threshold: at most 30% | nodocom #1803 63/152 = 41.4%, #1807 72/133 = 54.1%, #1814 65/154 = 42.2%; median 42.2%. The strictly next issues #1802 (20/96 = 20.8%) and #1804 (44/117 = 37.6%) are excluded because their design agent wrote no code map (the orchestrator served the pre-merge skill text until 2026-10-11T18:12Z) | nodocom session `c3971bc0`; file lists at `origin/dev` ∪ `origin/main` before each issue's design start | merged skills installed and loaded; the script's file-list filter (FILES) applied | unmet |
| AC2 | [evidence] Median planner turns across those three issues is ≤ 55 — measured: request count in each planner transcript; baseline median 79 over ten issues. | evidence | The `AC2` line of the same script for each of those three planner transcripts; threshold: median ≤ 55 | #1803 109, #1807 60, #1814 100 requests; median 100 | same as AC1 | same as AC1 | unmet |
| AC3 | [code] The design phase produces a code map and the planning dispatch names it — measured: design and writing-plans skill evals, one asserting the map exists with at least one entry per spec decision that names a module, one asserting the planner brief carries its path. | code | `env EVAL_TREE=. EVAL_MODEL=sonnet just evals design 1` (asserts 3 and 4) and `… just evals writing-plans 4`; `… just evals writing-plans 1` as the no-code-map check | remeasured after the sync with main, which changed instruction paths: design 1: row ts 2026-10-11T03:52:47Z, PASS, 6/6 asserts, 1 run (asserts 3 and 4 both pass); writing-plans 4: row ts 2026-10-11T03:54:15Z, PASS, 2/2 asserts, 1 run; writing-plans 1: row ts 2026-10-11T03:58:43Z, PASS, 8/8 asserts, 1 run | d2da5385e21b2f1560f7c382201d594d843814aa | tree mode (tree_mode project-skills), sonnet, clean tree (tree_dirty false) at the measured commit | met |
| AC4 | [code] Specs remain free of file paths and line numbers — measured: the existing spec-format check in the design skill evals. | code | assert 2 of `design` case 1 in the same run | assert 2 ("the spec's Decisions section names no file path or line number") has pass true in the PASS row of design 1, ts 2026-10-11T03:52:47Z | d2da5385e21b2f1560f7c382201d594d843814aa | tree mode (tree_mode project-skills), sonnet, clean tree (tree_dirty false) at the measured commit | met |
| AC5 | [human] Plans written from a map are no weaker than before — measured: the maintainer compares plan-review findings on those three issues against the prior ten; no increase in findings that cite a wrong file, symbol or test. | human | The maintainer compares plan-review findings on those three issues against the prior ten | — | — | — | human_pending |

## Deferred measurement (AC1, AC2)

Run once per issue, with jq installed: `bash measure.sh DESIGN.jsonl PLANNER.jsonl WORKTREE_ROOT FILES`, where the first two are the design and planner subagent transcripts of that issue. Save the block below as `measure.sh`. A Bash call counts as a read only on a line that runs sed, rg, grep, cat, head or tail, and only its path-shaped tokens are taken. WORKTREE_ROOT is the absolute path of the issue's worktree as it appears in the transcripts, without a trailing slash. FILES lists the repository's files at the issue's base, one repository-relative path per line (`git ls-tree -r --name-only <base>`); a path from either transcript counts only if it is listed, so directory tokens such as `src/Nodo.Api`, paths behind a shell variable, files outside the worktree and files the design agent created are not counted. Known limits: a file named without any slash is not counted, a command on an indented line is not counted, and a path behind a shell variable (`$P/plan.md`) is not counted. A Grep call that names a directory or no path is not counted and is reported on the `Unresolved` line, so a large count there means the AC1 ratio rests on few reads. The script writes design-files.txt and planner-reads.txt into the current directory.

```bash
DESIGN=$1 PLANNER=$2 ROOT=$3 FILES=$4
paths() {
  jq -r 'select(.type=="assistant") | .message.content[]? | select(.type=="tool_use")
    | if .name=="Read" then .input.file_path
      elif .name=="Grep" then (.input.path // empty | select(test("[A-Za-z0-9_-]\\.[A-Za-z0-9]+$")))
      elif .name=="Bash" then (.input.command | split("\n")[]
        | select(test("(^|&& *|; *)(sed|rg|grep|cat|head|tail) "))
        | scan("[A-Za-z0-9_.~-]*/[A-Za-z0-9_./-]*[A-Za-z0-9_-]\\.[A-Za-z0-9]+"))
      else empty end' "$1" | sed -e "s|^$ROOT/||" -e 's|^\./||' | grep -Fxf "$FILES"
}
paths "$DESIGN" | sort -u > design-files.txt
paths "$PLANNER" > planner-reads.txt
echo "AC1: $(grep -cFxf design-files.txt planner-reads.txt) of $(grep -c . planner-reads.txt) planner read paths are files the design agent opened"
echo "AC2: $(jq -s '[.[] | select(.type=="assistant") | .message.id] | unique | length' "$PLANNER") planner requests"
echo "Unresolved: $(jq -s '[.[] | select(.type=="assistant") | .message.content[]? | select(.type=="tool_use" and .name=="Grep")
  | select(.input.path // "" | test("[A-Za-z0-9_-]\\.[A-Za-z0-9]+$") | not)] | length' "$PLANNER") planner Grep calls named a directory or no path and are not counted"
```
