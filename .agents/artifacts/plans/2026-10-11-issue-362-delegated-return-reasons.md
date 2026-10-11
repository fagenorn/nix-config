# Delegated Return Reasons Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** The `from-issue` skill tells a delegating owner why it relays three kinds of delegated return untouched, so eval 6 can grade pass and the third acceptance criterion of issue 352 can be met (https://github.com/fagenorn/nix-config/issues/362).

**Architecture:** One skill document changes: `SKILL.md` of `from-issue` gains two parentheses in its `delegate` action and loses two clauses that restate their own sentence, for a net change of 0 bytes (D1, D2). Evals 5, 6 and 7 are then graded once each on the committed text, and the result is appended to the AC3 row of 352's acceptance record and written to this issue's own record (D3, D4, D5, D7). No helper code, test, eval case or budget ceiling changes.

**Tech stack:** Markdown skill text, Python 3 standard library (two exact-match scripts carried in the task files, `unittest`), `just`, `agent_tools.instruction_load` (the Instruction Budget gate), fresh `general-purpose` subagents as the eval answerers.

Spec: `.agents/artifacts/specs/2026-10-11-issue-362-delegated-return-reasons-design.md`. Its `## Decisions` section is the behaviour; its `## Decision ledger` rows D1–D10 are cited by ID.

## Global Constraints

- No instruction ceiling is raised and `home/common/agent-skills/instruction-load.json` is not edited (D2). Only the user applies the `instruction-budget-raise` label: never pass `--raise-label`, never request the label.
- `home/common/agent-skills/skills/from-issue/SKILL.md` changes only through Task 1's script and stays at its starting byte count (30409 at `96174d0e`). If `just agent-instruction-budget` fails after a review fix or a sync merge with `main`, stop and report: do not cut further on your own.
- Never edited: `home/common/agent-skills/skills/from-issue/evals/evals.json` (D1), every other `from-issue` document, `home/common/agent-skills/README.md`, any test, any helper under `python/` or `home/common/agent-skills/scripts/`, and the gate files `.github/workflows/instruction-budget.yaml`, `python/agent_tools/instruction_load.py`, `python/agent_tools/skill_lint.py`, `.github/branch-protection.json`.
- No test pins a sentence of skill prose (`docs/standards/agent-helpers.md` rule 6). This plan adds no test.
- Grading rules (D3): each of evals 5, 6 and 7 is graded exactly once per graded commit; no expected output or case prompt is edited; no answer is chosen between two; a verdict is written only from an answer that exists.
- "The five graded files" are `SKILL.md`, `AUTO.md`, `delegated-owner.md`, `ship-handoff.md` and `acquire-dispatcher.md` under `home/common/agent-skills/skills/from-issue/`. Any commit after the graded commit that changes one of them (a review fix, a sync merge with `main`) makes the gradings stale: Task 2 is then run again in full on the new head and both records are extended, never rewritten (D4, D5).
- Extract, never retype. Each task carries its script between a `# begin <name>` line and a `# end <name>` line. Start each command that uses it with `block() { sed -n "/^# begin $1\$/,/^# end $1\$/p" "$2" | sed '1d;$d'; }` (shell state does not survive between tool calls), then use `block <name> <task file>` as the task says.
- Commands run from the worktree root, in the foreground. With a `Lifecycle worker:` line in your prompt, wrap each long command in the `launch-scope exec … --` form that line's following sentence gives, create scratch files under the directory `launch-scope scratch` prints, and commit through `launch-commit`. Without one, use `git commit` and one `mktemp -d` directory. Either way, write the scratch directory's absolute path literally into later commands. Never disable commit signing.
- Focused tests: `PYTHONPATH="$PWD/python" python3 -m unittest <file> -k <pattern>` (timeout 600 s). Budget gate: `just agent-instruction-budget` (timeout 600 s), expected last line `check: pass`.
- Final gate, once on the final head (sdd's final gate, not a per-task gate): `just build` (timeout 3600 s) and `just agent-workflow-tests` (timeout 5400 s). Task 2 also runs `just agent-workflow-tests` once, as a measurement the record cites (D9).

## Test seams

- The four existing contract tests in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`: `test_delegate_action_checks_the_return_before_it_ships`, `test_delegated_return_line_is_spelled_identically_everywhere`, `test_generic_delegated_owner_returns_the_handoff_without_a_terminal_write`, `test_from_issue_evals_cover_the_delegated_ship_route` (spec seam 1).
- `just agent-workflow-tests`, the whole suite (spec seam 2).
- `just agent-instruction-budget` with no raise label (spec seam 3).
- Evals 5, 6 and 7 of `from-issue`, each answered by a fresh subagent and graded once (spec seam 4).

## Delivery estimate and boundaries

Estimates, from a scratch prototype of this plan's scripts at `53b1885a`: three changed files outside the plan and spec (`SKILL.md`, 3 lines; 352's acceptance record, 1 line; this issue's acceptance record, new); skill corpus +0 bytes. On the prototype Task 1's script printed `apply: 30409 -> 30409 bytes`, `just agent-instruction-budget` printed `check: pass`, the four contract tests ran OK and the five skill-text suites ran 284 tests OK (about 17 seconds). Task 2's two scripts were run on the prototype with made-up inputs; no eval was graded. `just agent-workflow-tests` is expected to take about 30 minutes. One review package.

Task 2 measures the text Task 1 commits and must run after Task 1 has passed its review. Its outcome is not known in advance: if a grading fails, Task 2 still completes its records with the failure in them and reports it. The one text revision D3 allows is not a task of this plan, because the fact it would add is unknown until a grading names it; D8 says who makes it and what follows.

## Task index

Task 1 — State the two reasons in the `delegate` action, paid for by two cuts — `home/common/agent-skills/skills/from-issue/SKILL.md` — full — [task-1.md](2026-10-11-issue-362-delegated-return-reasons.tasks/task-1.md)
Task 2 — Grade evals 5, 6 and 7 once and write the acceptance evidence — `.agents/artifacts/plans/2026-10-10-issue-352-delegated-ship-routing.acceptance.md`, `.agents/artifacts/plans/2026-10-11-issue-362-delegated-return-reasons.acceptance.md` — full — [task-2.md](2026-10-11-issue-362-delegated-return-reasons.tasks/task-2.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 2 | Eval 6 (`delegating-owner-handles-delegated-return`) answered once by a fresh `general-purpose` subagent shown only the case prompt and the five graded files, at the graded commit. Pass: every clause of the expected output stated or plainly implied, none contradicted, and the two sub-clauses that failed at `3c0090fb` stated, not implied (D3). Recorded in acceptance-record row AC1. |
| AC2 | code | Task 2 | Evals 5 (`delegated-owner-returns-ship-handoff`) and 7 (`no-subagent-launch-ships-inline`), one grading each at the same commit by the same method (D3). Recorded in row AC2. |
| AC3 | code | Task 2 | `just agent-workflow-tests` ends `OK`; `just agent-instruction-budget` prints `check: pass`; both at the graded commit (D9) and again in sdd's final gate. Recorded in row AC3. |
| AC4 | evidence | Task 2 | Command: `grep -c '^. AC3 . .* . met .$' .agents/artifacts/plans/2026-10-10-issue-352-delegated-ship-routing.acceptance.md`. Conditions: that row extended by Task 2's script from the gradings and runs at the graded commit, its earlier history unchanged (D5, D10). Threshold: prints `1`. Task 2 fills acceptance-record row AC4. |

## Decisions

- Where the reasons go and that eval 6 is not edited: D1. The paying cuts and the untouched ceilings: D2. The grading method, the tighter rule for eval 6 and what a failure allows: D3. What the gradings stand for, and when they are repeated: D4. How 352's row is extended and its verdict rule: D5. The design-time probes: D6.
- Appended by this plan: D7 (this issue's own acceptance record and its two commits), D8 (no inline grading; a failed grading is reported, not repaired, by the grader), D9 (the full suite is run once at the graded commit as a cited measurement), D10 (the skill edit and the row extension are made by exact-match scripts).

---
