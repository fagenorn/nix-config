# Task 5: Measure the slice, run the gated evals and record acceptance

**Files:**
- Create: `.agents/artifacts/plans/2026-10-07-issue-298-slim-ship-release-orchestrate.acceptance.md`
- Modify (only when `tighten` lowers a ceiling after a sync): `home/common/agent-skills/instruction-load.json`
- Modify (only when `CLAUDE_CODE_OAUTH_TOKEN` is non-empty): `home/common/agent-skills/evals/results/results.jsonl`

**Interfaces:**
- Consumes: Task 4's tree, where all four scoped documents are cut and none of the four debt keys remains.
- Produces: the acceptance record that sdd's final review grades (`home/common/agent-skills/skills/sdd/final-review.md` § Acceptance record). This task writes the `Observed`, `Commit` and `Conditions` columns; `Verdict` holds `—` for the controller.

**Invariants:**
- No scoped document, test or debt entry changes in this task. `instruction-load.json` changes only through `tighten` (per D2).
- AC3's base is fixed at `75784bed` (267,725 B) whatever the integration branch has advanced to (per D13). A head over 214,180 B is an unmet criterion: report it and do not alter the measure.
- No eval result is written, estimated or copied when the token is absent (per D9).
- No forge write and no label.

- [ ] **Step 1: Re-tighten**

Run `just agent-instruction-load tighten` (timeout 300 s). If it changed `instruction-load.json`, commit it as `chore(instruction-load): re-tighten after #298 (#298)`.

- [ ] **Step 2: Measure body lengths (AC2)**

```bash
PYTHONPATH=python python3 - <<'EOF'
from pathlib import Path
from agent_tools import skill_lint
worst = 0
for path in ("home/common/agent-skills/skills/ship-release/SKILL.md",
             "home/common/claude-code/skills/orchestrate-issues/SKILL.md",
             "home/common/codex/skills/orchestrate-issues/SKILL.md"):
    text = Path(path).read_text(encoding="utf-8")
    lines = skill_lint.reflowed_lines(skill_lint.parse_frontmatter(text)[1])
    worst = max(worst, lines)
    print(path, lines, len(text.encode("utf-8")))
raise SystemExit(0 if worst <= 500 else 1)
EOF
```

Expected: three lines, each ≤ 500 (targets 380, 430, 21), and exit 0. At the base it exits 1 (558 and 510).

- [ ] **Step 3: Measure the load (AC3, per D3 and D13)**

Save this script in the launch scratch root (never in the worktree) as `load.py`:

```python
import json, sys
d = json.load(sys.stdin)
ids = ("orchestration-dispatcher", "release-owner", "ship-release")
sums = {"base": 0, "head": 0}
for p in d["profiles"]:
    if p["id"] not in ids:
        continue
    for side in p["hosts"].values():
        for kind in ("hot", "conditional"):
            for rev in sums:
                sums[rev] += side[kind][rev]["bytes"]
sums["threshold"] = int(0.80 * sums["base"])
sums["ratio"] = round(sums["head"] / sums["base"], 4)
print(json.dumps(sums))
raise SystemExit(0 if sums["head"] <= sums["threshold"] else 1)
```

Run: `PYTHONPATH=python python3 -m agent_tools.instruction_load report --base 75784bed116805ee948d6e2f7f45a6d0ad3b4212 --head HEAD --format json | python3 <scratch>/load.py` (timeout 300 s).
Expected: `"base": 267725`, `"threshold": 214180`, `head` ≤ 214180 (about 206,620 at the per-file targets), and exit 0. At the base head it prints `"head": 267725` and exits 1.

- [ ] **Step 4: Gate and audit (AC1, AC5)**

Run `git fetch origin`, then `just agent-instruction-budget` (timeout 300 s). Expected: `check: pass` and exit 0, with no `lint:`, `ceiling:`, `tightness:`, `debt:` or `raise:` line (per D2: no label).

Run: `if grep -q 'ship-release/\|orchestrate-issues/' home/common/agent-skills/skill-lint-debt.json; then exit 1; fi`. Expected: exit 0.

For the AC5 attestation, list every test method that still reads a scoped file. Use an AST walk of `home/common/agent-skills/tests/test_workflow_skill_contracts.py` and `home/common/agent-skills/tests/test_ship_release_contracts.py`: each method whose body mentions `ORCHESTRATE`, `CODEX_ORCHESTRATE`, `self.orchestrate`, `SHIP_RELEASE`, `CHANGELOG`, `self.skill` or `self.changelog`. Also count indirect readers: any method that iterates `LIFECYCLE_DOCS`, `ORCHESTRATE_MACHINE_TEXT`, `SHARED_POLICY_ENTRIES`, `CLAUDE_POLICY_ENTRIES`, or another module-level name whose value names a scoped path. Print the class, method and line, and put the list in the task report, so the reviewer can attest that each one asserts only machine-read text (commands, argv, JSON keys, closed values, anchors, frontmatter, the resolve paragraph, the D12 sentence or the eval shape).

- [ ] **Step 5: Evals (AC4, per D9)**

If `CLAUDE_CODE_OAUTH_TOKEN` is non-empty, run each of these in the foreground (timeout 3000 s each):

```text
EVAL_TREE=. EVAL_MODEL=sonnet just evals ship-release 5
EVAL_TREE=. EVAL_MODEL=opus just evals ship-release 5
EVAL_TREE=. EVAL_MODEL=sonnet just evals orchestrate-issues 7
EVAL_TREE=. EVAL_MODEL=opus just evals orchestrate-issues 7
```

Compare each new row's `passed` with the threshold 5 (the S3 baseline, 5/5 for both cases on both models), then commit `results.jsonl` as `test(evals): #298 tree-mode eval rows`. If the token is empty, run none of them and change no rows.

- [ ] **Step 6: Acceptance record**

Create the record in the schema `final-review.md` § Acceptance record gives: `# Acceptance record — issue #298`, then the table `| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |` with rows AC1–AC5. Each `Criterion` is the issue line verbatim, without its checkbox. `Verdict` is `—` on every row.
- AC1, AC2 and AC5 (`code`): `Observed` is `in final verification`; AC2 adds the three Step 2 numbers; AC1 adds "`agent-instruction-budget` exit 0, no label".
- AC3 (`evidence`): `Observed` is `base 267725 → head <n> (threshold ≤ 214180, ratio <r>)`. `Commit` is the short SHA the report measured. `Conditions` is `report --base 75784bed --head HEAD; orchestration-dispatcher, release-owner, ship-release; all hosts; hot + conditional (D3, D13)`.
- AC4 (`evidence`): with the token, the four `passed` values against the threshold 5 and the results commit. Without it, `Observed` is `not run — CLAUDE_CODE_OAUTH_TOKEN unset`, `Commit` is `—`, and `Conditions` lists the four Step 5 commands (D9).

Commit as `docs(plans): acceptance record for #298`.

- [ ] **Step 7: Verify**

Run the focused suite (Global Constraints). Expected: OK.
Run: `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`.
Run: `test -f .agents/artifacts/plans/2026-10-07-issue-298-slim-ship-release-orchestrate.acceptance.md && grep -c '^| AC[1-5] |' .agents/artifacts/plans/2026-10-07-issue-298-slim-ship-release-orchestrate.acceptance.md`. Expected: `5`. At Task 4's head the file is absent and the command fails.
