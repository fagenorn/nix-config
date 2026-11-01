# Standalone to-issues Issue Bodies Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Every issue the to-issues skill files opens with a Problem section, explains or links each glossary term, decision ID and slice label at first use, carries a plain-outcome title, and gets a stranger reread before it is published, with no instruction ceiling raised.

**Architecture:** One task rewrites `to-issues/SKILL.md`: the template gains `## Problem` between Parent and What to build (D3), step 2 gains the title rule and the "body is the contract" paragraph gains the first-use rule and the stranger read (D4, D5), and the no-tracker sentence counts as publishing (D7). Duplicated and redundant text in the same file pays for the growth, so the file shrinks by 11 B and `instruction-load.json` stays as it is (D1, D2). One new contract class beside `ToIssuesCriterionLineContractsTest` pins the template headings and two short tokens (D6).

**Tech stack:** Markdown skill document, Python 3 standard library `unittest`, `just`, Nix (`just build`).

Spec: `.agents/artifacts/specs/2026-11-01-issue-495-standalone-issue-bodies-design.md` (a bare "Dn" cites its `## Decision ledger`). Issue: https://github.com/fagenorn/nix-config/issues/495

## Global Constraints

- Base `8d0bbc25383663fa3bc86623d0701e7d4bd4f9bc` (`origin/main` at planning); spec commits `b6161a63` and `63fc7608`.
- Files this plan changes, and no others: `home/common/agent-skills/skills/to-issues/SKILL.md` and `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (one inserted class). sdd's final review adds its acceptance record beside this plan.
- Unchanged: `home/common/agent-skills/instruction-load.json` and every other Instruction Budget gate file, `to-issues/WIDE-REFACTORS.md`, every other skill, `ToIssuesCriterionLineContractsTest`, and the resolver paragraph, Demo, Decisions, criterion lines and kinds, Blocked by, falsifiable-criterion paragraph, `measured:` sentence and GitHub `issue_id` bullet of `to-issues/SKILL.md` (D2, spec § Out of scope).
- Write every dictated text byte for byte. The result was measured: `to-issues/SKILL.md` goes from 6494 B to 6483 B against a 6494 B hot ceiling on both hosts, which also stays above the gate's 5% tightness floor (6185 B), so no `just agent-instruction-load tighten` runs. A rewording is a plan deviation: report it, do not adjust the budget. Never add the `instruction-budget-raise` label and never raise a ceiling (D1).
- `docs/standards/agent-helpers.md` rule 6 holds: the phrase-pin exception covers only the two tokens of the class this plan adds (D6).
- Process custody: every test, build or gate command runs in the foreground from the worktree root as `launch-scope exec --repo-root <R> --run-id <I> --worker-id <W> -- <argv>`, written `launch-scope exec … --` below, with the stated timeout. `<R>`, `<I>` and `<W>` come from the dispatch's `Lifecycle worker:` line. Scratch lives under what `launch-scope scratch --repo-root <R> --run-id <I> --worker-id <W>` prints. Commits go through `launch-commit --repo-root <R> --run-id <I> --worker-id <W> -- <git commit args>`; they are SSH-signed and end with the session's attribution trailer. Never push, never `just switch`.
- **To-issues classes** (timeout 600 s): `launch-scope exec … -- bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k ToIssues 2>&1 | grep -E "^(FAIL|ERROR|Ran|OK|FAILED)"'`.
- **Skill-text suites** (timeout 900 s): `launch-scope exec … -- bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_eval_cases.py 2>&1 | tail -3'`. At the base: `Ran 332 tests`, `OK (skipped=3)`.
- **Budget** (timeout 600 s): `launch-scope exec … -- bash -c 'set -o pipefail; just agent-instruction-budget 2>&1 | tail -3'`, whose last line must be `check: pass`.
- Full verification set (timeout 3600 s each): `launch-scope exec … -- bash -c 'set -o pipefail; just build 2>&1 | tail -3'` and `launch-scope exec … -- bash -c 'set -o pipefail; just agent-workflow-tests 2>&1 | tail -6'`, plus the Budget command. Task 1 runs it because it is the final task; sdd's final gate reruns it once on the final head.

## Test seams

- The new class `ToIssuesStandaloneBodyContractsTest` in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`: the exact template heading list and the tokens `at first use` and `reread each body` (D6).
- The existing `ToIssuesCriterionLineContractsTest` in the same module, unchanged.
- The Instruction Budget gate, `just agent-instruction-budget`, with no raise label (D1).
- The verification bindings `just agent-workflow-tests` and `just build`.

## Delivery estimate and boundaries

Estimates: 2 files; 10 rewritten and 4 inserted lines of skill text, about 22 added test lines. One review package. No independent slice exists, because the growth and its offset share one file and one budget.

## Task index

Task 1 — Problem-first, self-explaining to-issues bodies — `home/common/agent-skills/skills/to-issues/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-1.md](2026-11-01-issue-495-standalone-issue-bodies.tasks/task-1.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `home/common/agent-skills/tests/test_workflow_skill_contracts.py::ToIssuesStandaloneBodyContractsTest::test_the_template_sections_put_the_problem_before_what_to_build` and `::test_the_first_use_and_stranger_read_rules_are_stated`, run by `just agent-workflow-tests` |
| AC2 | code | Task 1 | `home/common/agent-skills/tests/test_workflow_skill_contracts.py::ToIssuesCriterionLineContractsTest` (both tests, unchanged), run by `just agent-workflow-tests` |
| AC3 | code | Task 1 | `just agent-workflow-tests` and `just build` pass on the final head: Task 1's full verification step, rerun by sdd's final gate |

## Decisions

- The Problem section, its place and its placeholder: per D3. The What to build "No code, except" wording: per D3 and D2.
- Where the title, first-use and stranger-read rules live, and who rereads: per D4. What a title may and may not use: per D5.
- The no-tracker route counts as publishing: per D7.
- The offset, its removals and the untouched ceiling: per D1 and D2.
- The contract class and its two tokens: per D6.

## Planning trial

A scratch worktree at `63fc7608` applied Task 1's dictated replacements and class, then was discarded. Before the skill edits, the To-issues classes gave `Ran 4 tests`, `FAILED (failures=3)`. After them, `to-issues/SKILL.md` measured 6483 B with the sha256 Task 1 states, and the To-issues classes gave `OK`. The Skill-text suites gave `Ran 334 tests`, `OK (skipped=3)`, and the Budget run gave `check: pass`. `just build` passed in about 25 s, and `just agent-workflow-tests` passed 107 of 107 members in about 963 s.

---
