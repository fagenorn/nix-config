# Graded Acceptance in sdd Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** sdd's final conformance axis, now on Opus/high, grades every issue
acceptance criterion, acceptance findings can never be parked, and the sdd and
ship-handoff reports carry one validated `acceptance_state` field (issue #272,
slice S1).

**Architecture:** artifact-budget gains the closed `acceptance_state` set and
its pairing table. The table is applied to the sdd report and the legacy
handoff, and after the delivery model's own check to the v2 handoff (per D8,
D9, D11). Skill prose carries the rest. The conformance prompt grades and emits
an `### Acceptance` table (per D1–D3). `final-review.md` holds the controller's
citation checks, the never-parked rule, and the acceptance record, which is
committed before Final verification (per D4–D7, D13). sdd's Finish derives
`acceptance_state`, and the handoff templates copy it. The tier ripple follows
D10.

**Tech stack:** Python 3 standard library
(`home/common/agent-skills/scripts/artifact_budget.py`,
`home/common/agent-skills/scripts/delivery_model/_wire.py`,
`python/agent_tools/agent_model_matrix.py`), `unittest`, JSON
(`model-matrix.json`, `instruction-load.json`) and Markdown skill sources.

Spec: [2026-10-07-issue-272-graded-acceptance-design.md](../specs/2026-10-07-issue-272-graded-acceptance-design.md).
Parent: [2026-10-06-acceptance-criteria-gate-design.md](../specs/2026-10-06-acceptance-criteria-gate-design.md).
Read the spec before any task. It owns the design, the pairing table, the
record schema and the decision ledger.

## Global Constraints

- `acceptance_state` takes exactly the values `met`, `unmet`, `human_pending`
  and `not_applicable`. It is required on the sdd report, the legacy
  ship-handoff and `ship-handoff/v2` (per D8).
- The conformance verdict tokens are exactly `met`, `unmet`, `unverified` and
  `human_pending`. The criterion handles are `AC1`…`ACn`, and the placeholder
  is `[ACCEPTANCE_CRITERIA]` (per D1).
- The record path is `<plans dir>/<plan stem>.acceptance.md` (per D7).
- No `agent-dispatch` marker is added or removed. The inventory stays at 37
  markers across both skill source trees (per D4, D12).
- The delivery contract, its stages and its digest do not change. No new
  `agent_tools` module and no command-table row (per D9, D11).
- Out of scope: S2 (#273), S3 (#274), #270, #284. ship-issue's close stage and
  `tracker_held` are untouched.
- No new unlabeled fence in any `sdd/` or `from-issue/` document other than an
  enrolled carrier's existing one. A schema block uses a labeled fence
  (`test_dispatch_contracts.py` enrolment guard).
- Source carries no `TODO` or `FIXME`. Comments cite decisions as `#272 D<n>`.
- Every instruction-load profile stays within its ceiling at every task's
  head. A task that grows a loaded file raises the breached ceilings to the
  exact measured value, and appends its own `Ceiling raised for #272: …
  (#155 D10).` note.
- Commits are SSH-signed through `launch-commit` when a `Lifecycle worker:`
  line is given, and never unsigned. Messages end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Run commands from the worktree root. Summarize test output to the failing
  lines. A gate that pipes a runner into `tail` starts with `set -o pipefail;`.
- Final verification is sdd's final gate, never a per-task gate:
  `just build` (timeout 3600000 ms) and `just agent-workflow-tests`
  (timeout 3600000 ms), in the foreground.

## Test seams

- `artifact-budget validate-report` is run as a subprocess through
  `ArtifactBudgetCliTest.run_validate` in
  `home/common/agent-skills/tests/test_artifact_budget.py`, for the `sdd` and
  `ship-handoff` boundaries.
- The delivery model is called directly through
  `validate_delivery_object` in
  `home/common/agent-skills/tests/test_delivery_model.py`, with the shared
  fixture `_delivery_model_fixtures.ship_handoff`.
- The dispatch and matrix inventories are tested in
  `home/common/agent-skills/tests/test_dispatch_contracts.py` and
  `home/common/agent-skills/tests/test_agent_model_matrix.py`.
- Skill wording is pinned with phrase and ordered-anchor assertions over
  `normalized` text in
  `home/common/agent-skills/tests/test_workflow_skill_contracts.py`.
- Instruction-load ceilings are checked in
  `home/common/agent-skills/tests/test_instruction_load.py`.

## Delivery estimate and boundaries

These are estimates. About 20 files change: 3 Python sources, 2 JSON models,
7 skill documents and 7 test modules, plus `instruction-load.json`. That is
roughly 700 added lines, about 60% of them tests. The growth risk is in the
instruction-load ceilings, which have no headroom and rise with every prose
task, and in `test_workflow_skill_contracts.py` (over 5,000 lines). Tasks 1–2
can be delivered alone, as the validator half. Task 3 is the tier move. Tasks
4–6 are the grading prose, and they depend on Task 1's field name only as
text.

## Task index

Task 1 — `acceptance_state` on the sdd report and the legacy handoff — `home/common/agent-skills/scripts/artifact_budget.py`, `home/common/agent-skills/tests/test_artifact_budget.py` — full — [task-1.md](2026-10-07-issue-272-graded-acceptance.tasks/task-1.md)

Task 2 — `acceptance_state` on `ship-handoff/v2` — `home/common/agent-skills/scripts/delivery_model/_wire.py`, `home/common/agent-skills/scripts/artifact_budget.py`, `home/common/agent-skills/tests/_delivery_model_fixtures.py`, `home/common/agent-skills/tests/test_delivery_model.py`, `home/common/agent-skills/tests/test_delivery_workflow.py`, `home/common/agent-skills/tests/test_artifact_budget.py` — full — [task-2.md](2026-10-07-issue-272-graded-acceptance.tasks/task-2.md)

Task 3 — Move the conformance axis to Opus/high — `home/common/agent-skills/model-matrix.json`, `python/agent_tools/agent_model_matrix.py`, `home/common/agent-skills/tests/test_agent_model_matrix.py`, `home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md`, `home/common/agent-skills/skills/sdd/final-review.md`, `home/common/agent-skills/skills/sdd/SKILL.md`, `home/common/agent-skills/tests/test_dispatch_contracts.py`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/instruction-load.json` — full — [task-3.md](2026-10-07-issue-272-graded-acceptance.tasks/task-3.md)

Task 4 — The conformance prompt grades every criterion — `home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md`, `home/common/agent-skills/skills/ship-issue/REVIEW.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/instruction-load.json` — full — [task-4.md](2026-10-07-issue-272-graded-acceptance.tasks/task-4.md)

Task 5 — Controller rules, the acceptance record and sdd's `acceptance_state` — `home/common/agent-skills/skills/sdd/final-review.md`, `home/common/agent-skills/skills/sdd/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/instruction-load.json` — full — [task-5.md](2026-10-07-issue-272-graded-acceptance.tasks/task-5.md)

Task 6 — Handoff templates carry `acceptance_state` — `home/common/agent-skills/skills/from-issue/ship-handoff.md`, `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/ship-issue/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/instruction-load.json` — full — [task-6.md](2026-10-07-issue-272-graded-acceptance.tasks/task-6.md)

All six tasks are `full`. Tasks 1–2 change a report-boundary schema, which is
a public contract. Task 3 changes model routing. Tasks 4–6 change the
instructions that drive review and delivery.

## Acceptance coverage

| Issue criterion | Task |
|---|---|
| sdd `clean` + `unmet` exits 2; `residuals` + `unmet` + detail accepted | 1 |
| ship-handoff missing `acceptance_state` rejected | 1 (legacy), 2 (v2) |
| Conformance marker `model=opus effort=high`, inventory unchanged | 3 |
| Prompt requires the Acceptance table and the evidence citation | 4 |
| final-review: acceptance findings never parked with a ruling | 5 |
| `just build` and `just agent-workflow-tests` pass | sdd final gate |

## Decisions

This plan rests on the spec's ledger rows D1–D10, and on the rows appended at
planning: D11 (the pairing stays in the legacy script and closes the v2
`review_state`), D12 (the literal marker inventory of 37), D13 (how the
controller reads the criteria, and what happens on a tracker failure) and D14
(ship's full review grades nothing).

---

## Standards review provenance

Reviewer: Codex (`codex-companion task --fresh --reviewer plan-review`, gpt-6-astra/xhigh), isolated and read-only, no fallback. Base SHA 3b911376cfbb47f3480956daa571097d53f4715d. Findings: 2 Blocking, 2 Should fix, 0 Discussion; 4 accepted, 0 rejected, 0 deferred. Applied to Task 2 (per D16) and Task 5 (per D17).
