# Design Code Map Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** The `design` skill leaves a code map in the worktree's git directory, the `writing-plans` skill reads it before mapping files, and the autonomous `from-issue` plan dispatch names it, so the planner stops re-finding what design already read (https://github.com/fagenorn/nix-config/issues/354).

**Architecture:** Skill text, eval cases and two eval assert helpers; no helper command, no artifact-budget change. Three skill documents gain the rule and each ends smaller than it started, because every instruction ceiling stays where it is (D8, D10). The eval assert library gains a spec-format check and a code map check, unit-tested as shell functions. `design` gets its first eval file and `writing-plans` one more case; both are then run once in working-tree mode.

**Tech stack:** Markdown skill documents, Bash and awk (`assert-lib.sh`), Python 3 standard library `unittest`, JSON eval cases, `run-eval.sh` in tree mode, `agent_tools.instruction_load` (the Instruction Budget gate).

Spec: `.agents/artifacts/specs/2026-10-11-issue-354-design-code-map-design.md`. Its `## Decisions` section is the behaviour; its `## Decision ledger` rows D1–D11 are cited by ID.

## Global Constraints

- No instruction ceiling is raised and `home/common/agent-skills/instruction-load.json` is not edited (D8). Only the user applies the `instruction-budget-raise` label: never pass `--raise-label`, never request the label.
- Skill text changes only through Task 2's script, which is byte-exact: `design/SKILL.md` 7272 → 7268 bytes, `writing-plans/SKILL.md` 12771 → 12753, `from-issue/AUTO.md` 11802 → 11776. A reworded sentence changes a count. If `just agent-instruction-budget` fails after a review fix or a sync merge with `main`, stop and report: do not thin the code map rule and do not cut further on your own (D8, D10).
- Never edit a gate file: `.github/workflows/instruction-budget.yaml`, `python/agent_tools/skill_lint.py`, `python/agent_tools/instruction_load.py`, `.github/branch-protection.json`.
- Unchanged: `home/common/agent-skills/scripts/artifact_budget.py` and `artifact-budget-policy.json` (D2); `evals/run-eval.sh`, `evals/fixture-repo/`, `evals/setups/` (D7: no new setup kind); `model-matrix.json`; every `<!-- agent-dispatch: … -->` marker and `Agent(...)` line; `grill-with-docs/` and `from-issue/SKILL.md` (D4).
- Skill text and docs write "code map" in full, never a bare "map".
- No test pins a sentence of skill prose (`docs/standards/agent-helpers.md` rule 6). Tests assert helper output, assert names and case shapes.
- Extract, never retype. Each task carries its code between `# begin <name>` and `# end <name>` lines. Start each command that uses it with `block() { sed -n "/^# begin $1\$/,/^# end $1\$/p" "$2" | sed '1d;$d'; }` (shell state does not survive between tool calls), then use `block <name> <task file>` as the task says.
- Commands run from the worktree root, in the foreground. With a `Lifecycle worker:` line in your prompt, wrap each long command in the `launch-scope exec … --` form that line's following sentence gives, create scratch files under `launch-scope scratch`, and commit through `launch-commit`. Without one, use `git commit` and a `mktemp -d` scratch directory. Never disable commit signing.
- Focused tests: `PYTHONPATH="$PWD/python" python3 -m unittest <file> -k <pattern>` (timeout 600 s). Budget gate: `just agent-instruction-budget` (timeout 600 s), expected output `check: pass`.
- Final gate, once on the final head (sdd's final gate, not a per-task gate): `just build` (timeout 3600 s) and `just agent-workflow-tests` (timeout 5400 s).

## Test seams

- The eval assert library's two helpers, as shell functions over crafted files: `home/common/agent-skills/tests/test_eval_cases.py`, driven through its existing `run_assert` (spec seam 1). The new cases' assert snippets are graded the same way over a crafted sandbox (D11).
- Skill evals in working-tree mode: `design` case 1, `writing-plans` case 4 and the existing `writing-plans` case 1 (spec seam 2).
- The Instruction Budget gate: `just agent-instruction-budget` with no raise (spec seam 3).

## Delivery estimate and boundaries

Estimates, measured on a scratch prototype of this plan's exact blocks at `3b831be8`: ten changed files outside the plan and spec (`assert-lib.sh`, `test_eval_cases.py`, three skill documents, the agent-skills `README.md`, two `evals.json`, `results.jsonl`, the acceptance record); skill corpus −48 bytes; after the change the tightest ceilings keep 4 bytes (design-and-grill owner, hot) and 18 bytes (planning owner, hot). The prototype was built by running Tasks 1 to 3 from these task files on a clean checkout: `just agent-instruction-budget` printed `check: pass` and `just agent-workflow-tests` ran 2642 tests with no failure (about 31 minutes). The evals of Task 4 were not run. One review package.

The margins are small and sibling issues of the same run may land on `main` first. A sync merge that grows any of the three skill documents can break the gate; the Global Constraints stop rule applies, because a raise needs the user's label.

Task 2 is one task because the gate balances only with all of its edits applied together. Task 3 needs Task 1's helpers. Task 4 measures the final text of Tasks 2 and 3 and must run last.

## Task index

Task 1 — Spec-format and code map assert helpers — `home/common/agent-skills/evals/assert-lib.sh`, `home/common/agent-skills/tests/test_eval_cases.py` — full — [task-1.md](2026-10-11-issue-354-design-code-map.tasks/task-1.md)
Task 2 — Code map rule in the skill text, paid for byte by byte — `home/common/agent-skills/skills/design/SKILL.md`, `home/common/agent-skills/skills/writing-plans/SKILL.md`, `home/common/agent-skills/skills/from-issue/AUTO.md`, `home/common/agent-skills/README.md` — full — [task-2.md](2026-10-11-issue-354-design-code-map.tasks/task-2.md)
Task 3 — Eval cases for the code map and the plan dispatch — `home/common/agent-skills/skills/design/evals/evals.json`, `home/common/agent-skills/skills/writing-plans/evals/evals.json`, `home/common/agent-skills/tests/test_eval_cases.py` — full — [task-3.md](2026-10-11-issue-354-design-code-map.tasks/task-3.md)
Task 4 — Run the three evals in tree mode and write the acceptance record — `home/common/agent-skills/evals/results/results.jsonl`, `.agents/artifacts/plans/2026-10-11-issue-354-design-code-map.acceptance.md` — full — [task-4.md](2026-10-11-issue-354-design-code-map.tasks/task-4.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | evidence | Task 4 | Not measurable before merge (D9). Command: `bash measure.sh DESIGN.jsonl PLANNER.jsonl WORKTREE_ROOT`, the script Task 4 records under `Deferred measurement` in the acceptance record, reading its `AC1` line (D12). Conditions: the next three orchestrated nodocom issues, run with the merged skills installed. Threshold: at most 30% of the planner's read calls touch a file the design agent opened (baseline median about 64%). Task 4 fills acceptance-record row AC1 as not measured. |
| AC2 | evidence | Task 4 | Not measurable before merge (D9). Command: the `AC2` line of the same `bash measure.sh` run per planner transcript (D12). Conditions: the same three issues as AC1. Threshold: median ≤ 55 (baseline median 79 over ten issues). Task 4 fills acceptance-record row AC2 as not measured. |
| AC3 | code | Task 4 | `env EVAL_TREE=. EVAL_MODEL=sonnet just evals design 1` and `… just evals writing-plans 4`, each with a `PASS` row in `results.jsonl` for the final skill text (D11): for `design` 1 the asserts `the code map exists in the git directory, named after the spec` and `the code map is well-formed and lists the three files the issue decides about`; for `writing-plans` 4 the assert `the printed plan prompt names the spec's code map file`. `writing-plans` 1 passes in the same mode. |
| AC4 | code | Task 4 | The same `design` 1 run: the assert `the spec's Decisions section names no file path or line number` passes in its `PASS` row. |
| AC5 | human | Task 4 | The maintainer compares plan-review findings on those three issues against the prior ten: no increase in findings that cite a wrong file, symbol or test (D9). Task 4 writes row AC5 with `—` evidence. |

## Decisions

- Where the code map lives, that it is unbudgeted, and what it may hold: D1, D2, D3. Which dispatch text changes: D4. The spec-format check and coverage by fixture knowledge: D5, D6. The dispatch case and no seeded-map case: D7. Byte neutrality and the stop rule: D8. Post-delivery criteria: D9.
- Appended by this plan: D10 (what the cuts are, the compressed rule with the README as its long form, "the file map"), D11 (assert count and path derivation, how a code map path and a line reference are read, case-assert tests, what a `PASS` row for the revision is).

---

## Standards review provenance

- Reviewer: Codex (`codex-plan-review`, model gpt-6-astra, effort xhigh), isolated read-only mode, no fallback, no focus. Base SHA `bff1d1d4905405587fccc33decc2803b78babea6`.
- Findings: 1 blocking, 2 should-fix, 0 discussion. Accepted 3, rejected 0, deferred 0; each was verified against the live plan, the review contract and the assert library first.
- B1 (AC1 and AC2 named prose, not commands): accepted; the rows now name a concrete script that Task 4 records (D12).
- S1 (the committed-spec assert passed a spec edited after its commit): accepted in Task 3, with a failing case.
- S2 (the not-started assert missed untracked files): accepted in Task 3, with a failing case.
