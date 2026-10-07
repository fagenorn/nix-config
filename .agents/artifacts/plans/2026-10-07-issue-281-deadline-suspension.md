# Deadline Suspension at Task Boundaries Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Let an `sdd` owner park its attempt cleanly as `suspended(deadline)` at a task boundary before the attempt deadline, and let any sweep or re-entry resume it.

**Architecture:** `workflow-state` admits a new owner-writable, auto-resumable `blocked_on` value `deadline`, and the delivery model's closed `suspended` wire reply admits it. `sdd` states the headroom rule, and from-issue hands `sdd` its `deadline_at` and lists the value in its suspension procedure. Spec: [2026-10-07-issue-281-deadline-suspension-design.md](../specs/2026-10-07-issue-281-deadline-suspension-design.md) (decision ledger D1–D9).

**Tech stack:** Python 3 standard library (`unittest`), Markdown skill text, JSON instruction-load model.

## Global Constraints

- No ledger schema bump, no new helper verb, no persisted task timing (D2, D4).
- Only the `suspended` wire reply admits `deadline`; the delivery `checkpoint` response's closed `blocked_on` set is unchanged (D3).
- No new test pins an English phrase (`docs/standards/agent-helpers.md` rule 6; D5, D9).
- orchestrate-issues and the reaper, expiry and anti-zombie accounting are untouched (D7).
- All commits are signed and go through `launch-commit` under the implementer's `Lifecycle worker:` line.
- Final gate commands (run once by sdd's final gate, not per task): `just build` and `just agent-workflow-tests`, each in the foreground with timeout 3600000 ms.
- Run focused tests from the worktree root as `PYTHONPATH=python python3 -m unittest -k <pattern> <test file>`.

## Test seams

- `workflow-state` command tests: `home/common/agent-skills/tests/test_workflow_state.py` (`WorkflowStateLifecycleTest`, `OwnerExitFenceTest`).
- Delivery-model wire test: `home/common/agent-skills/tests/test_delivery_model.py::test_suspended_reply_is_closed_and_names_an_owner_cause`.
- Skill contract tests: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (`WorkflowSkillContractsTest`, `LaunchFencedWorkerContractsTest`).
- Instruction growth gate: `just agent-instruction-budget` (`agent_tools.instruction_load check`).

## Delivery estimate and boundaries

Estimate: 8 changed files (2 scripts, 3 test files, 2 skills, 1 JSON model), roughly +150 test lines and +2 KB of skill prose. Aggregate growth risk is only the instruction-load ceilings (D8). One deliverable slice; Task 1 is independently shippable without Task 2.

## Task index

Task 1 — Admit `deadline` in the ledger and the wire reply — home/common/agent-skills/scripts/workflow-state.py, home/common/agent-skills/scripts/delivery_model/_wire.py, home/common/agent-skills/tests/test_workflow_state.py, home/common/agent-skills/tests/test_delivery_model.py — full — [task-1.md](2026-10-07-issue-281-deadline-suspension.tasks/task-1.md)
Task 2 — State the `sdd` headroom rule and wire from-issue — home/common/agent-skills/skills/sdd/SKILL.md, home/common/agent-skills/skills/from-issue/SKILL.md, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json — full — [task-2.md](2026-10-07-issue-281-deadline-suspension.tasks/task-2.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `test_workflow_state.py::WorkflowStateLifecycleTest::test_deadline_suspension_parks_the_attempt_without_spending_it`, `::test_direct_reentry_resumes_a_deadline_suspension_in_place`, `::OwnerExitFenceTest::test_a_deadline_suspend_refuses_until_the_worker_is_released` |
| AC2 | code | Task 2 | `test_workflow_skill_contracts.py::WorkflowSkillContractsTest::test_sdd_states_the_deadline_suspension_order` under `just agent-workflow-tests` |
| AC3 | code | Task 1 | `test_workflow_state.py::WorkflowStateLifecycleTest::test_a_label_sweep_resumes_a_deadline_suspension` |

## Decisions

Tasks cite the spec's ledger: D2, D3 (Task 1); D1, D4, D5, D6, D8, D9 (Task 2). Planning added D8 (instruction-ceiling raise and its human label) and D9 (contract-test anchoring).
