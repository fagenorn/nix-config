# Tracker Hold (needs-verification) Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** When the effective acceptance state is `unmet` or `human_pending`, ship merges the PR but holds the issue open with `needs-verification` and a verdict-table comment. A `tracker_held` delivery observation satisfies `close_tracker` with no contract or digest change. Control reports the held issue as `held` and never relaunches it, and orchestrate-issues keeps it an open blocker for its dependents (#273, slice S2 of the acceptance-criteria gate).

**Architecture:** The delivery model gains one closed `tracker_held` observation grammar and one place, owned by its objects module, that records which observation kinds satisfy each stage and each postcondition. The reducer, the wire validator and the builder all read that place. The owner-report rule admits `merged` with `issue_closed: false`, and finish cross-checks that cell against the observed tracker kind. Control's projection names a delivered, held, still-open issue `held`. ship-issue, HUMAN-GATE, from-issue's ship handoff and orchestrate-issues gain the close-or-hold text, which phrase-level contract tests pin. Spec: `.agents/artifacts/specs/2026-10-07-issue-273-tracker-held-design.md` (ledger D1–D18). Parent: `.agents/artifacts/specs/2026-10-06-acceptance-criteria-gate-design.md` (read-only).

**Tech stack:** Python 3 standard library (`unittest`), the flat delivery scripts under `home/common/agent-skills/scripts/`, Markdown skill text, the JSON instruction-load model.

## Global Constraints

- No change to `STAGE_ACTIONS`' 3-tuples, the contract's stages, schema version, scope tuples, obligation keys or digests. The `tracker_closed` obligation key stays (D5).
- The hold label is the literal `needs-verification`. It is created only when missing, and never with `--force` (D10).
- A hold's `acceptance_state` is exactly `unmet` or `human_pending`. Both the builder and the model reject `met` and `not_applicable` (D3).
- Every PR body stays inside the lifecycle guard's form: one double-quoted `--body` argument with no `"`, `$`, backtick or backslash (D9).
- Every ship-skill command added is a single command, with no pipe, redirect, `&&`, heredoc or command substitution, so the shell-example sweep stays green.
- Do not move `artifact_budget.py` or the delivery scripts into `agent_tools`. Make no lifecycle-guard or permission-surface change.
- Run every test command from the worktree root with `PYTHONPATH=python`, in the foreground, with `timeout 900` or more.
- Final-gate verification, run once by sdd on the final head and not per task: `just build` (timeout 3600 s) and `just agent-workflow-tests` (timeout 3600 s).

## Test seams

- `home/common/agent-skills/tests/test_delivery_model.py` is the reducer and object grammar seam, through `_delivery_model_fixtures` (`cleanup_contract_and_delivery`, `with_observed`, `observation`, `evaluation`).
- `home/common/agent-skills/tests/test_workflow_delivery.py` is the builder and digest seam, through the `DeliveryRuntime.build_delivery` facade and `resolved_snapshot("/repo")`. Its digest literals are pinned at base 8a2e2631 (D12).
- `home/common/agent-skills/tests/test_artifact_budget.py` is the owner-report rule seam, through the real `validate-report` CLI.
- `home/common/agent-skills/tests/test_delivery_workflow.py` is the finish cross-check seam, through `DeliveryLoopTest`'s real-CLI loop (D17).
- `home/common/agent-skills/tests/test_workflow_state.py` and `home/common/agent-skills/tests/test_delivered_control.py` are the control seam. A `DeliveredControlHarness` mixin moves out of #220's `DeliveredControlTest` (D12).
- `home/common/agent-skills/tests/test_workflow_skill_contracts.py` is the skill-text seam. Its phrase assertions run on `normalized()` text.
- `home/common/agent-skills/tests/test_instruction_load.py` and `test_shell_example_contracts.py` are the ceiling seam and the shell-form sweep.

## Delivery estimate and boundaries

These figures are estimates. About 14 product files change: 4 model files, 3 runtime scripts, `artifact_budget.py` and 6 skill or model documents. About 250 lines of code and 450 test lines are added. Six reviewable tasks make one slice. The largest growth is in the skill text, about 6 KB, which raises five instruction-load ceilings. The review package should stay well inside its boundary.

## Task index

Task 1 — Delivery model: tracker_held grammar and the satisfies-mappings — home/common/agent-skills/scripts/delivery_model/_objects.py, home/common/agent-skills/scripts/delivery_model/_reconcile.py, home/common/agent-skills/scripts/delivery_model/_wire.py, home/common/agent-skills/scripts/delivery_model/__init__.py, home/common/agent-skills/tests/test_delivery_model.py — full — [task-1.md](2026-10-07-issue-273-tracker-held.tasks/task-1.md)
Task 2 — Builder: tracker_held observation and the digest pin — home/common/agent-skills/scripts/workflow_delivery_build.py, home/common/agent-skills/tests/test_workflow_delivery.py — full — [task-2.md](2026-10-07-issue-273-tracker-held.tasks/task-2.md)
Task 3 — Owner rule admits a held merge; finish cross-checks issue_closed — home/common/agent-skills/scripts/artifact_budget.py, home/common/agent-skills/scripts/workflow_delivery.py, home/common/agent-skills/tests/test_artifact_budget.py, home/common/agent-skills/tests/test_delivery_workflow.py — full — [task-3.md](2026-10-07-issue-273-tracker-held.tasks/task-3.md)
Task 4 — Control projects `held` and never relaunches it — home/common/agent-skills/scripts/workflow_delivery_wire.py, home/common/agent-skills/scripts/delivery_model/_wire.py, home/common/agent-skills/scripts/workflow-state.py, home/common/agent-skills/tests/test_delivered_control.py, home/common/agent-skills/tests/test_workflow_state.py — full — [task-4.md](2026-10-07-issue-273-tracker-held.tasks/task-4.md)
Task 5 — ship-issue close-or-hold text and HUMAN-GATE — home/common/agent-skills/skills/ship-issue/SKILL.md, home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md, home/common/agent-skills/skills/ship-issue/evals/evals.json, home/common/agent-skills/instruction-load.json, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-5.md](2026-10-07-issue-273-tracker-held.tasks/task-5.md)
Task 6 — orchestrate-issues reports held; from-issue handoff close-or-hold — home/common/claude-code/skills/orchestrate-issues/SKILL.md, home/common/agent-skills/skills/from-issue/ship-handoff.md, home/common/agent-skills/instruction-load.json, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-6.md](2026-10-07-issue-273-tracker-held.tasks/task-6.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1, Task 2, Task 3 | `TrackerHeldModelTest` in `test_delivery_model.py` (held folds `close_tracker`; a closed-state held subject is rejected), `TrackerHeldBuilderTest.test_the_builder_builds_a_held_observation_the_model_accepts` and `test_a_closed_state_subject_is_rejected_by_the_model` in `test_workflow_delivery.py`, and `DeliveryLoopTest.test_a_held_delivery_completes_with_issue_closed_false` (builder output reduced through the real CLI) in `test_delivery_workflow.py`, under `just agent-workflow-tests` |
| AC2 | code | Task 4 | `HeldControlTest.test_a_held_delivery_is_never_relaunched_and_reads_held` in `test_workflow_state.py` under `just agent-workflow-tests` |
| AC3 | code | Task 2 | `TrackerHeldBuilderTest.test_the_contract_digest_for_an_unchanged_input_is_pinned` in `test_workflow_delivery.py` (literals captured at 8a2e2631) under `just agent-workflow-tests` |
| AC4 | code | Task 5 | `TrackerHoldContractsTest` in `test_workflow_skill_contracts.py` (delivery loop and Phase 8 hold branch, PR-body `## Acceptance` table) under `just agent-workflow-tests` |

## Decisions

Task 1 rests on D1–D5. Task 2 rests on D1, D3, D5 and D12. Task 3 rests on D6 and D17, and closes AC1's builder-to-reducer path. Task 4 rests on D7, D12, D15 and D18. Task 5 rests on D8–D11, D13, D14 and D16. Task 6 rests on D7, D11 and D15, plus parent D7. Rows D16–D18 were appended to the spec's ledger during planning.

---

## Standards review provenance

Reviewer: Codex (gpt-6-astra, xhigh), fresh isolated read-only plan-review thread; base SHA 8a2e2631b173b30351480a86cd4018f8b5bccc8c; no fallback. Findings: 3 accepted (PR273-1 and PR273-2 blocking, PR273-3 should-fix; per D19 for the first two), 0 rejected, 0 deferred.
