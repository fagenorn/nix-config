# Slim sdd Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Cut the eight `sdd` documents by content class, give the review-package gate one home in `SKILL.md`, delete the remaining prose pins on them, and lower the two loading profiles' ceilings, so the sdd share drops by at least 35% with no workflow change (#297, slice S6 of #291).

**Architecture:** Spec `.agents/artifacts/specs/2026-10-07-issue-297-slim-sdd-design.md` (ledger D1–D18; program rows cited as "#291 Dn", sibling rows as "#295 Dn"). Its `### Target layout` table is the file map, `### Content classes and their disposition` is the cutting rule, `### Cutting rules per document` says what each file keeps, and `### Test changes` lists the only test edits. Each task cuts one file group and, in the same commit, makes the test edits that text forces, drops the debt key it clears and runs `tighten` (per D12). Every commit passes the gate.

**Tech stack:** Markdown skill documents, JSON models (`instruction-load.json`, `skill-lint-debt.json`), Python `unittest`, `agent_tools.skill_lint` / `agent_tools.instruction_load`, the eval harness.

## Global Constraints

- Execution precondition (per D18): the branch contains `origin/main` before sdd's Setup pins `DELIVERY_BASE`. The controller runs `git fetch origin` and `git merge-base --is-ancestor origin/main HEAD`; when that fails, it runs `git merge --no-ff --no-commit origin/main` and completes the merge with `git commit --no-edit` (under a lifecycle identity, as a registered worker through `launch-commit … -- --no-edit`, per sdd `SKILL.md`'s `### Lifecycle workers`). The branch holds only the spec and plan, so a conflict is a stop: report BLOCKED. Only then is `DELIVERY_BASE` pinned, so the review range never holds another issue's work.
- Scope: only `home/common/agent-skills/skills/sdd/*.md` (never `scripts/` or `evals/`), `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/instruction-load.json` (ceilings via `tighten` only), `home/common/agent-skills/skill-lint-debt.json`, the spec's `### Findings to file` list, this plan's acceptance record, and `home/common/agent-skills/evals/results/results.jsonl` (Task 6, token-gated). Never edit other skills, `agents/*.md`, `AGENTS.md`, `model-matrix.json`, helpers, `test_dispatch_contracts.py`, `test_agent_model_matrix.py` or the gate files (spec Out of scope; per D7, D11). No task writes the tracker.
- No file is added, removed, renamed or reclassified, and no profile member or note changes (per D2). `just agent-instruction-load tighten` is the only writer of `instruction-load.json`. A `raise:` line from `instruction_load check` is a defect: stop and report it, never apply a label.
- No workflow semantics change (spec Decisions, "No semantic change"). A rule found wrong rather than wordy is not edited; append it to the spec's `### Findings to file` (per D7).
- Machine-read text stays byte for byte, in its current file (per D8). No line outside a dispatch marker's call line may contain `Agent(`. The 18 markers stay in their files: `SKILL.md` 2, `fix-loop.md` 6, `final-review.md` 4, `implementer-prompt.md` 2, each other payload 1 (`DISPATCH_MARKER_TOTAL` stays 39).
- The four leaf clauses appear verbatim exactly once in `SKILL.md`'s `## Agent tiers` and exactly once after `prompt: |` inside each payload's fence. Each payload keeps exactly one unlabeled fence; every other fence in `sdd/` is labeled (`markdown`, `text`, `json`) so no other file has exactly one unlabeled fence.
- Anchors stay true (per D9): `### Cumulative delivery gate`, `## Agent tiers`, `## The task loop`, `### Lifecycle workers`, `### 1. Dispatch the implementer`, `### 2. Handle the report`, **Interim child results** (inside §2), `### 3. Review the task`, `### 4. The fix loop`, `### 5. Complete the task`, `## Final review — two axes`, `## Finish`, `## Acceptance record`, `## Final verification`, and the `progress.md` check.
- Hub rule (spec Decisions, "One home per rule"): `fix-loop.md` and `final-review.md` name `SKILL.md` sections by heading and never name each other; payloads name no controller section.
- `SKILL.md`'s opening paragraph must not contain `resolve-project resolve` (it stays a no-resolve rule).
- Per-file ceilings (spec § Byte and line targets; "ceiling, not goal"): `SKILL.md` ≤ 14,500 bytes and ≤ 230 reflowed body lines; `final-review.md` ≤ 10,500; `fix-loop.md` ≤ 4,300 and ≤ 95 reflowed lines; `implementer-prompt.md` ≤ 5,200; `task-reviewer-prompt.md` ≤ 6,000; `re-review-prompt.md` ≤ 4,200; `conformance-reviewer-prompt.md` ≤ 6,500; `correctness-reviewer-prompt.md` ≤ 5,200. An overshoot is allowed only when every remaining sentence is machine-read or carries a rule, and the commit body names the file and its size. Hard lines: `SKILL.md` ≤ 300 reflowed lines (AC2) and the share (AC3).
- Review-package bound (per D13): before each commit, every plan-owned path's net diff against `git merge-base HEAD origin/main` stays ≤ 49,152 bytes. Run this from the worktree root (timeout 120 s):

```bash
set -euo pipefail
base=$(git merge-base HEAD origin/main)
status=0
for f in home/common/agent-skills/skills/sdd/*.md home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/instruction-load.json home/common/agent-skills/skill-lint-debt.json; do
  n=$(git diff --binary -U10 --diff-algorithm=myers --no-indent-heuristic --inter-hunk-context=0 "$base" -- "$f" | wc -c | tr -d ' ')
  if [ "$n" -gt 49152 ]; then echo "D13 over: $f $n"; status=1; fi
done
exit $status
```

  A breach stops the task: report BLOCKED with the file and its size, so the controller splits that file's rewrite across two PRs (per D13).
- Per commit: `just agent-instruction-load tighten` (timeout 300 s), then `PYTHONPATH=python python3 -m agent_tools.instruction_load check` prints `check: pass` (per D12).
- Focused suite (timeout 600 s), from the worktree root: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/tests/test_eval_cases.py`. Lint (timeout 300 s): `PYTHONPATH=python python3 -m agent_tools.skill_lint check` exits 0.
- A focused-suite failure in a test not named in the task's own steps is a plan bug: report it, never weaken that test (per D11).
- Final-gate verification, run once by sdd on the final head: `just build` (timeout 3600 s) and `just agent-workflow-tests` (timeout 3600 s).
- Sync conflicts in shared test structures resolve to the union of both slices' deletions (per D16); after any integration-branch sync, re-run `tighten` and take the measured values (#295 D12).

## Test seams

- `skill-lint check` (L1–L5 plus the shrink-only debt file) and `skill_lint.reflowed_lines` over `parse_frontmatter`'s body for the 300-line line.
- `instruction_load` `report`/`check`/`tighten` for the share, the ceilings and the absence of any `raise:` line; `LiveBudgetTest` runs them on every commit.
- The machine-read checks: `test_dispatch_contracts`, `test_agent_model_matrix`, `test_shell_example_contracts`, `SDD_MACHINE_TEXT`, the sdd report key-set test.
- The eval harness (`EVAL_TREE=. EVAL_MODEL=<model> just evals sdd 4`), gated by D14.

## Delivery estimate and boundaries

Estimate only: 12 changed paths (the eight sdd documents, one test file, two JSON models, the acceptance record), plus `results.jsonl` when the eval token is present and the spec when a finding is filed. Skill text should fall from 93,317 bytes (92,972 at `origin/main` 75784bed, after #281) to about 56,000. The test file should lose about 30–40 lines. Measured at base: a whole-file rewrite of `SKILL.md` costs about 28,200 bytes of deletion diff plus the new text, so `SKILL.md` stays under the D13 bound at any head ≤ 20,000 bytes; every other sdd document is under it as long as it does not grow. One PR; the branch diff is estimated at about 170 KB, within the 524,288-byte aggregate.

## Task index

Task 1 — Cut SKILL.md and give the review-package gate one home — home/common/agent-skills/skills/sdd/SKILL.md, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json — full — [task-1.md](2026-10-07-issue-297-slim-sdd.tasks/task-1.md)
Task 2 — Cut fix-loop.md under 100 lines — home/common/agent-skills/skills/sdd/fix-loop.md, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json, home/common/agent-skills/skill-lint-debt.json — full — [task-2.md](2026-10-07-issue-297-slim-sdd.tasks/task-2.md)
Task 3 — Cut final-review.md and give it a Contents list — home/common/agent-skills/skills/sdd/final-review.md, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json, home/common/agent-skills/skill-lint-debt.json — full — [task-3.md](2026-10-07-issue-297-slim-sdd.tasks/task-3.md)
Task 4 — Cut the task-loop payloads — home/common/agent-skills/skills/sdd/{implementer-prompt.md, task-reviewer-prompt.md, re-review-prompt.md}, home/common/agent-skills/instruction-load.json — full — [task-4.md](2026-10-07-issue-297-slim-sdd.tasks/task-4.md)
Task 5 — Cut the final-review payloads and drop the conformance policy-support rows — home/common/agent-skills/skills/sdd/{conformance-reviewer-prompt.md, correctness-reviewer-prompt.md}, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json — full — [task-5.md](2026-10-07-issue-297-slim-sdd.tasks/task-5.md)
Task 6 — Measure the slice and record acceptance evidence — .agents/artifacts/plans/2026-10-07-issue-297-slim-sdd.acceptance.md, home/common/agent-skills/instruction-load.json, home/common/agent-skills/evals/results/results.jsonl (token-gated) — full — [task-6.md](2026-10-07-issue-297-slim-sdd.tasks/task-6.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 6 | `PYTHONPATH=python python3 -m agent_tools.skill_lint check` exits 0, `skill-lint-debt.json` holds no `skills/sdd/` key, and `just agent-instruction-budget` exits 0 with no `lint:` or `raise:` line (the `Instruction Budget` job's checks; per D2) |
| AC2 | code | Task 6 | The Task 6 Step 1 command: `skill_lint.reflowed_lines` over `parse_frontmatter(SKILL.md)[1]` prints ≤ 300 (plan target ≤ 230) |
| AC3 | evidence | Task 6 | Command: the Task 6 Step 2 share script over `instruction_load report --format json`, run at base `baac2897f15daab46a4f25ec625b40d384d3573c` and at the Task 6 head. Conditions: profiles `orchestrated-issue-owner` and `implementation-owner` over all hosts, `sdd/` members listed hot or conditional (per D1). Threshold: head share ≤ 181,968 (0.65 × 279,951), with the synced-base share (per D18) and the whole-profile total reported beside it. Implementer fills acceptance-record row `AC3` |
| AC4 | evidence | Task 6 | Command: `EVAL_TREE=. EVAL_MODEL=<sonnet|opus> just evals sdd 4` (two runs). Conditions: run only when `CLAUDE_CODE_OAUTH_TOKEN` is non-empty (per D14). Threshold: `passed` ≥ 6 on each model (S3 baseline 6/6 sonnet, 6/6 opus). Without the token, row `AC4` records `not run — CLAUDE_CODE_OAUTH_TOKEN unset` and both commands, and grades `human_pending`. Implementer fills acceptance-record row `AC4` |
| AC5 | code | Task 6 | `just agent-workflow-tests` on the final head, plus the Task 6 Step 4 inventory with the reviewer's attestation that every remaining assertion over an sdd document pins machine-read text only |

## Decisions

The spec owns the ledger. This plan cites D1–D16 and adds D17 (`fix-loop.md` leaves `SDD_MACHINE_TEXT` without a replacement pin) and D18 (execution starts from a branch synced with `origin/main`; #281's deadline paragraph is kept; AC3's base stays `baac2897`).

---
