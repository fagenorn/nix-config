# Lane Ledger and declare-lane Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Bump the `workflow-state` ledger to schema 7, adding three attempt fields (`lane`, `lane_budget_minutes`, `lane_history`), add the `declare-lane` verb, and make the suspension resume lane-aware (#280, slice 2 of the light-lane design).

**Architecture:** Task 1 is pure schema. It adds the three fields to `ATTEMPT_FIELDS`, closes them in `validate_attempt` (D3), defaults them in `new_control_attempt` (D5), adds a `6 → 7` step to `DeliveryRuntime.migrate`, and moves every fixture to schema 7. Task 2 adds `declare-lane`, shaped like `mark-progress`, and changes the one `resume_attempt` call site so that a suspension resume uses `lane_budget_minutes` when it is set. Spec: `.agents/artifacts/specs/2026-10-07-issue-280-lane-ledger-design.md` (ledger D1–D8). Parent: `.agents/artifacts/specs/2026-10-06-light-lane-budgets-design.md`.

**Tech stack:** Python 3 standard library (`argparse`, `datetime`), `unittest`, driven through `INPROCESS_CLI` as in the existing suites.

## Global Constraints

- `workflow-state.py` is a legacy flat script (`docs/standards/agent-helpers.md`). Edit it in place. Do not move code into `python/agent_tools`.
- `control` and `direct-owner` keep their request shapes, response shapes and interface versions. `resume-pack` stays v1 (D6). No `workflow-response` boundary kind is added (D6).
- No CLAUDE.md, skill or standards text changes (D7). CLAUDE.md's "ledger schema 6" mention in the `mark-progress` bullet stays as written.
- Out of scope: `lane-triage` and `light_lane` policy (#279), `blocked_on=deadline` (#281), skill routes (#282), enablement and the values in `.agents/project.json` (#284), `workflow-state` reading its own clock (#309).
- The legal transitions and reasons are exactly those in D2. The closed lane set is `{"light", "full"}`. The closed reason set is `{"triage", "important_finding", "second_fix_round", "light_deadline", "unpredicted_risk"}`.
- Run every test command from the worktree root, in the foreground, with an explicit timeout (`timeout 900`). The focused form is `PYTHONPATH=python timeout 900 python3 -m unittest -k <Pattern> home/common/agent-skills/tests/<file>.py`. Report only the summary and failing lines.
- Final-gate verification, run once by sdd on the final head and not per task: `just build` (timeout 3600 s) and `just agent-workflow-tests` (timeout 3600 s).

## Test seams

- `home/common/agent-skills/tests/test_workflow_state.py`, which drives `workflow-state` as a CLI against a temporary ledger through `LifecycleHarness`, following the `ProgressMarkerSchemaTest`/`ProgressMarkerTest` prior art. This is the only new-test seam.
- The existing fixture suites `test_delivery_workflow.py` and `test_host_admission.py` change only mechanically, to schema 7.

## Delivery estimate and boundaries

Estimates: 6 changed files. The product change is about 150 lines across `workflow-state.py` and `workflow_delivery.py`, and the new tests are about 250 lines. One slice, well within the review-package limits. The main growth risk is fixture churn in `test_delivery_workflow.py`.

## Task index

Task 1 — Ledger schema 7: fields, validator, defaults, migration — home/common/agent-skills/scripts/workflow-state.py, home/common/agent-skills/scripts/workflow_delivery.py, home/common/agent-skills/tests/test_workflow_state.py, home/common/agent-skills/tests/test_delivery_workflow.py, home/common/agent-skills/tests/test_host_admission.py — full — [task-1.md](2026-10-07-issue-280-lane-ledger.tasks/task-1.md)
Task 2 — `declare-lane` verb and lane-aware suspension resume — home/common/agent-skills/scripts/workflow-state.py, home/common/agent-skills/tests/test_workflow_state.py — full — [task-2.md](2026-10-07-issue-280-lane-ledger.tasks/task-2.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 2 | `DeclareLaneTest.test_light_rebases_the_deadline_from_the_launch_and_records_history` in `home/common/agent-skills/tests/test_workflow_state.py` |
| AC2 | code (classified) | Task 2 | `DeclareLaneTest.test_refuses_full_to_light_and_light_to_light`, `test_refuses_a_launch_that_is_not_current` and `test_refuses_a_rebased_deadline_that_is_not_after_now` in `home/common/agent-skills/tests/test_workflow_state.py` |
| AC3 | code (classified) | Task 2 | `DeclareLaneTest.test_a_suspension_resume_uses_the_lane_budget_or_the_request_budget` in `home/common/agent-skills/tests/test_workflow_state.py` |
| AC4 | code (classified) | Task 1 | `LaneSchemaTest.test_a_schema_six_ledger_migrates_with_null_lane_fields` in `home/common/agent-skills/tests/test_workflow_state.py` |

## Decisions

Task 1 rests on D3 and D5. Task 2 rests on D1, D2, D4, D5, D6 and D8. Row D8 was appended to the spec's ledger during planning.
