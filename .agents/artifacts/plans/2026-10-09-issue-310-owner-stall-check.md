# Owner Stall Check Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** orchestrate-issues stops an owner that stays silent past `stall_minutes` after an interim notification and sends exactly one `unavailable` observation for it. Every observer the adapter arms sleeps for a number of seconds the helper computed (#310).

**Architecture:** `resolve-project` accepts an optional `bindings.workflow.orchestration.stall_minutes`. `workflow-state` gains one read-only verb, `owner-liveness`, which reads the ledger without a lock and the clock once through `ledger_clock()`. It answers with a closed `owner_liveness` reply that the delivery model's workflow-response boundary validates. Control's `wait` action gains a validated `wait_seconds`. orchestrate-issues rule (a) arms a liveness observer, a new rule (d) handles its wake, and §4 arms the wait observer as `sleep <wait_seconds>`. Spec: `.agents/artifacts/specs/2026-10-09-issue-310-owner-stall-check-design.md` (ledger D1–D13).

**Tech stack:** Python 3 standard library (`datetime`, `math`, `re`, `unittest`, `unittest.mock`), Markdown skill text, JSON project contract and instruction-load model.

## Global Constraints

- Standard library only. `home/common/agent-skills/scripts/workflow-state.py` is a legacy flat script and is edited in place (agent-helpers rule 1). `python/agent_tools/resolve_project.py` is a package module.
- No ledger schema change (`SCHEMA_VERSION` stays 7). The control interface stays version 3 and the wait id stays `wait:<deadline_at>` (D9). `check-launch`, `current-launch` and `launch_verdict` do not change (spec Out of scope).
- `owner_liveness` reply: exactly the members `interface_version` (the integer 1), `kind` (`"owner_liveness"`), `action_id`, `reason`, `verdict`, `since`, `progress_at`, `stall_at` and `wait_seconds`. `verdict` is one of `live`, `stalled`, `past_deadline` and `not_current` (D5, D10).
- Exact stderr lines, each printed by `main` as `workflow-state: <message>` at exit 2 with empty stdout:
  - `--since <supplied> is <N> seconds ahead of the clock <clock>; a supplied time may lead it by at most 60 seconds — omit it to use the clock` (#309's text, label `--since`, D4);
  - `invalid --since: expected an RFC3339 UTC timestamp`;
  - `invalid --stall-minutes: expected a positive integer` (D11);
  - `invalid run_id` and `invalid action_id`, as `check-launch` prints them.
- The lifecycle guard and the Claude allow list already allow `workflow-state` outright, and the verb is a subcommand of the installed script. No guard, allow-list, launcher-table or Nix change is needed.
- Skill-text pins are on `workflow-state` argv, `bindings.*` names, JSON keys and shell examples only. No new English-phrase pin (agent-helpers rule 6).
- Run test commands from the worktree root in the foreground, as `PYTHONPATH="$PWD/python" python3 -m unittest <file> [-k <pattern>]`, with a timeout of at least 600 s.
- The final gate runs once on the final head: `just build` and `just agent-workflow-tests` (each with a 3600 s timeout), and `just agent-instruction-budget --raise-label` when Task 5 raised the ceiling (otherwise `just agent-instruction-budget`). If Task 5 raised it, the PR asks the user for the `instruction-budget-raise` label. Only the user applies that label.

## Test seams

- `StallMinutesTest` and `CommittedContractTest` in `home/common/agent-skills/tests/test_resolve_project.py`: the resolver CLI, run from source (spec seam 5).
- `OwnerLivenessResponseTest` and `ControlWaitResponseTest` in `home/common/agent-skills/tests/test_delivery_model.py`: `validate_delivery_object(…, expected_kind="workflow-response")` (spec seams 1 and 2).
- `OwnerLivenessTest` and `ControlWaitSecondsTest` in `home/common/agent-skills/tests/test_workflow_state.py`: `LifecycleHarness.run_cli`, with the clock pinned through `self.cli_env["WORKFLOW_STATE_TEST_CLOCK"]` (spec seams 1 and 2).
- `OwnerLivenessRemainderTest` in `home/common/agent-skills/tests/test_delivered_control.py`: `DeliveredControlHarness`, with the clock pinned through `mock.patch.dict(os.environ, …)` (D12).
- `AdmissionReplayTest.test_a_silent_owner_is_freed_and_a_progressing_owner_is_left_alone` in `home/common/agent-skills/tests/test_admission_replay.py` (spec seam 3, D12).
- `ORCHESTRATE_MACHINE_TEXT` and `CLAUDE_POLICY_ENTRIES` in `test_workflow_skill_contracts.py`, and `ObserverSleepExampleTest` in `test_shell_example_contracts.py` (spec seam 4, D13).

## Delivery estimate and boundaries

These are estimates. About 14 changed files: `workflow-state.py` (about +110 lines), `delivery_model/_wire.py` (about +30), `resolve_project.py` (about +6), two project contracts (one line each), the orchestrate-issues `SKILL.md` (about +1.6 KB net), `instruction-load.json` (one ceiling and one note), and seven test files (about +600 lines). The aggregate risk is the orchestrate-issues instruction ceiling, which equals the file's current size, so any growth needs a raise. This is one slice, well inside any review-package boundary.

## Task index

Task 1 — Optional `stall_minutes` orchestration binding — python/agent_tools/resolve_project.py, .agents/project.json, home/common/agent-skills/evals/fixture-repo/.agents/project.json, home/common/agent-skills/tests/test_resolve_project.py — full — [task-1.md](2026-10-09-issue-310-owner-stall-check.tasks/task-1.md)
Task 2 — `owner_liveness` reply at the workflow-response boundary — home/common/agent-skills/scripts/delivery_model/_wire.py, home/common/agent-skills/tests/test_delivery_model.py — full — [task-2.md](2026-10-09-issue-310-owner-stall-check.tasks/task-2.md)
Task 3 — The read-only `owner-liveness` verb — home/common/agent-skills/scripts/workflow-state.py, home/common/agent-skills/tests/test_workflow_state.py, home/common/agent-skills/tests/test_delivered_control.py — full — [task-3.md](2026-10-09-issue-310-owner-stall-check.tasks/task-3.md)
Task 4 — Control `wait` carries a validated `wait_seconds` — home/common/agent-skills/scripts/workflow-state.py, home/common/agent-skills/scripts/delivery_model/_wire.py, home/common/agent-skills/tests/test_workflow_state.py, home/common/agent-skills/tests/test_delivery_model.py — full — [task-4.md](2026-10-09-issue-310-owner-stall-check.tasks/task-4.md)
Task 5 — orchestrate-issues liveness rules and computed sleeps — home/common/claude-code/skills/orchestrate-issues/SKILL.md, home/common/agent-skills/instruction-load.json, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/tests/test_shell_example_contracts.py — full — [task-5.md](2026-10-09-issue-310-owner-stall-check.tasks/task-5.md)
Task 6 — Stall replay over the real CLI — home/common/agent-skills/tests/test_admission_replay.py — full — [task-6.md](2026-10-09-issue-310-owner-stall-check.tasks/task-6.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 6 | `AdmissionReplayTest.test_a_silent_owner_is_freed_and_a_progressing_owner_is_left_alone` in `test_admission_replay.py` (one `unavailable` across the run, A's claim released as `owner_unavailable` before A's `deadline_at`, B re-armed with no observation), under `just agent-workflow-tests` |
| AC2 | code | Task 5 | `WorkflowSkillContractsTest.test_orchestrate_documents_carry_their_machine_text` with the `owner-liveness` argv and `` `wait_seconds` `` pins, and `ObserverSleepExampleTest` in `test_shell_example_contracts.py` (the `sleep <wait_seconds>` example, and no `date` invocation in the skill); the helper unit test for the computed wait is Task 4's `ControlWaitSecondsTest` in `test_workflow_state.py` and `ControlWaitResponseTest` in `test_delivery_model.py`. All run under `just agent-workflow-tests` |
| AC3 | code | Task 1 | `StallMinutesTest` and `CommittedContractTest.test_orchestration_values_are_committed_contract_values` in `test_resolve_project.py`, under `just agent-workflow-tests`; the documentation half is the `bindings.workflow.orchestration.stall_minutes` entry Task 5 adds to `CLAUDE_POLICY_ENTRIES` for orchestrate-issues §1 |

## Decisions

The tasks rest on spec rows D1–D10 and on the plan rows D11 (one clock read, whole-second `--since`, handler-parsed `--stall-minutes`, no self-validation), D12 (the replay's own driver and clock route; the remainder case's home) and D13 (the regex `date` pin). Each member cites the rows it uses.

---
