# Stop Superseded Owner Handles Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** orchestrate-issues stops every superseded owner host task before it dispatches a response's owners and at `finalize`, so a post-expiry resume never shares its worktree with a live predecessor (#275, slice S1 of the launch process reaping design).

**Architecture:** One new **Stop pass** paragraph in orchestrate-issues §4, invoked by the `finalize` and all-refused `delivery_contract` clauses, plus a separate stop-failure list in §5, pinned by one new phrase-level contract class. Spec: `.agents/artifacts/specs/2026-10-07-issue-275-stop-superseded-owner-handles-design.md` (ledger D1–D7); parent: `.agents/artifacts/specs/2026-10-06-launch-process-reaping-design.md` (read-only).

**Tech stack:** Markdown skill text, JSON instruction-load model, Python 3 standard-library `unittest`.

## Global Constraints

- §2 of orchestrate-issues (rules (a), (b), (c) and the surrounding text) is not edited by a single byte (AC3, per D5).
- No `workflow-state`, ledger, response-shape, guard or `launch-scope` change; no new `<!-- agent-dispatch:` marker.
- The new test class is appended immediately before the `if __name__ == "__main__":` line of `test_workflow_skill_contracts.py`; existing classes and module constants are not edited.
- Every test command runs from the worktree root with `PYTHONPATH=python`, in the foreground, with `timeout 300` or more.
- Final-gate verification (run once by sdd on the final head, not per task): `just build` (timeout 3600 s) and `just agent-workflow-tests` (timeout 3600 s).

## Test seams

- Skill-text contract tests in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, asserting ordered phrases on whitespace-normalized text (the module's `normalized()` helper), per D5.
- The instruction-load ceiling check in `home/common/agent-skills/tests/test_instruction_load.py` over `home/common/agent-skills/instruction-load.json`, per D7.

## Delivery estimate and boundaries

Estimate: 3 changed product files, about 2 KB of skill prose and 70 test lines. One slice; no aggregate-growth risk near the review-package boundary.

## Task index

Task 1 — Stop pass in orchestrate-issues §4 and its stop-failure report — home/common/claude-code/skills/orchestrate-issues/SKILL.md, home/common/agent-skills/instruction-load.json, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-1.md](2026-10-07-issue-275-stop-superseded-owner-handles.tasks/task-1.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `SupersededOwnerStopPassContractsTest.test_the_stop_pass_precedes_dispatch_and_runs_at_finalize` in `test_workflow_skill_contracts.py` under `just agent-workflow-tests` |
| AC2 | code | Task 1 | `SupersededOwnerStopPassContractsTest.test_a_stop_failure_is_reported_and_never_blocks_dispatch` in `test_workflow_skill_contracts.py` under `just agent-workflow-tests` |
| AC3 | code | Task 1 | `InterimOwnerNotificationContractsTest` and the dispatcher-fence rule (b)/(c) assertions in `test_workflow_skill_contracts.py`, unchanged and green, plus `SupersededOwnerStopPassContractsTest.test_section_two_carries_no_stop_pass` under `just agent-workflow-tests` |

## Decisions

Task 1 rests on spec ledger rows D1–D5 and on plan-level rows D6 (which stop failures §5 lists) and D7 (the dispatcher ceiling raise), appended to the spec's ledger during planning.

---
