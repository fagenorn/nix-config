# Ledger Clock Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `workflow-state` stamps ledger writes from the system clock. A supplied time more than 60 seconds ahead is refused, and a backward refusal says how long to wait. Skill and prompt text stops handing agents timestamps and gains a rule against wait loops (#309).

**Architecture:** One seam, `ledger_clock()`, sits in `home/common/agent-skills/scripts/workflow-state.py`. Three small helpers sit beside it: `supplied_time` (parse a supplied time and apply the skew rule), `ledger_time` / `stamp_request` (read an omitted time under the ledger lock) and `backward_refusal` (the wait suffix). Every ledger-writing command, `control`, `direct-owner` and `build-delivery --kind contract` route their time through them. The delivery modules keep receiving times as arguments. The skill trees drop `--now` and `now`, and a fourth dispatch-contract clause, `no-wait-loops`, joins the three existing ones. Spec: `.agents/artifacts/specs/2026-10-07-issue-309-ledger-clock-design.md` (ledger D1–D12).

**Tech stack:** Python 3 standard library (`datetime`, `math`, `ast`, `unittest`), Markdown skill text, JSON instruction-load model.

## Global Constraints

- Standard library only. `workflow_delivery.py`, `workflow_delivery_build.py`, `workflow_delivery_wire.py` and `delivery_model/` are not edited and read no clock (D1). The legacy flat script `workflow-state.py` is edited in place (agent-helpers rule 1).
- No ledger schema change (`SCHEMA_VERSION` stays 6). No interface-version change: control stays 3, direct-owner stays 2 (D3).
- The override variable is exactly `WORKFLOW_STATE_TEST_CLOCK`. The skew bound is exactly 60 seconds, inclusive, and is not configurable (D2, D6).
- Exact stderr lines. Each is printed by `main` as `workflow-state: <message>` and exits 2:
  - skew: `<label> <supplied> is <N> seconds ahead of the clock <clock>; a supplied time may lead it by at most 60 seconds — omit it to use the clock`. The labels are `--now`, `control now`, `direct owner now` and `contract now`. `N` is the lead rounded up to whole seconds.
  - backward: `<existing prefix>: <now> is before the <field> <stored>; it would succeed in <N> seconds`. `<field>` is `run updated_at` or `attempt last_progress_at` (D8).
  - override: `invalid WORKFLOW_STATE_TEST_CLOCK: expected an RFC3339 UTC timestamp` and `invalid WORKFLOW_STATE_TEST_CLOCK: <value> is later than the clock <clock>`.
- Skill-text pins are on argv tokens, JSON keys and carrier clauses only. No new English-phrase pin (agent-helpers rule 6, D9, D10).
- Test commands run from the worktree root, in the foreground, as `PYTHONPATH="$PWD/python" python3 -m unittest <file> [-k <pattern>]`, with a timeout of at least 600 s.
- The final gate runs once on the final head: `just build` and `just agent-workflow-tests` (each with a 3600 s timeout), plus `just agent-instruction-budget`. The PR carries the `instruction-budget-raise` label only if Task 4 or Task 5 had to raise a ceiling.

## Test seams

- `LedgerClockSeamTest` in `home/common/agent-skills/tests/test_workflow_state.py`: CLI runs through `LifecycleHarness.run_cli`, plus an `ast` scan of the `workflow-state` sources (spec Test seams 4).
- `LedgerClockTest` in `home/common/agent-skills/tests/test_delivery_workflow.py`. It reuses `LifecycleHarness`, imported from `.test_workflow_state`, whose `run_cli` passes `cli_env` into the in-process runner. The override goes in through `self.cli_env` (spec Test seams 1–3).
- `DeliveryBuilderTest` in `test_delivery_workflow.py` for the contract stamp. `BuilderHarness.cli` copies `os.environ`, so the override goes in through `mock.patch.dict(os.environ, …)`.
- Skill pins in `test_workflow_skill_contracts.py`, `test_shell_example_contracts.py` and `test_dispatch_contracts.py`, plus the instruction gate (`just agent-instruction-budget`) and `test_instruction_load.py`.

## Delivery estimate and boundaries

These are estimates. About 22 changed files: `workflow-state.py` (about +90/−40 lines), four test files (about +400 lines, mostly `LedgerClockTest`), about 13 skill documents (small deletions, plus nine copies of a 150-byte clause), `instruction-load.json` if a ceiling moves, and `CLAUDE.md` (two sentences). This is one slice, far from any review-package boundary.

## Task index

Task 1 — Clock seam, skew rule and wait suffix for the flag commands — home/common/agent-skills/scripts/workflow-state.py, home/common/agent-skills/tests/test_workflow_state.py, home/common/agent-skills/tests/test_delivery_workflow.py — full — [task-1.md](2026-10-07-issue-309-ledger-clock.tasks/task-1.md)
Task 2 — Optional `now` in `control` and `direct-owner` requests, stamped under the lock — home/common/agent-skills/scripts/workflow-state.py, home/common/agent-skills/tests/test_delivery_workflow.py — full — [task-2.md](2026-10-07-issue-309-ledger-clock.tasks/task-2.md)
Task 3 — `build-delivery --kind contract` stamps an omitted `now` — home/common/agent-skills/scripts/workflow-state.py, home/common/agent-skills/tests/test_delivery_workflow.py, CLAUDE.md — full — [task-3.md](2026-10-07-issue-309-ledger-clock.tasks/task-3.md)
Task 4 — Skill text drops hand-built timestamps — home/common/agent-skills/skills/from-issue/SKILL.md, home/common/agent-skills/skills/from-issue/AUTO.md, home/common/agent-skills/skills/from-issue/ship-handoff.md, home/common/agent-skills/skills/ship-issue/SKILL.md, home/common/agent-skills/skills/sdd/SKILL.md, home/common/agent-skills/skills/sdd/final-review.md, home/common/claude-code/skills/orchestrate-issues/SKILL.md, home/common/claude-code/skills/orchestrate-issues/evals/evals.json, CLAUDE.md, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/tests/test_shell_example_contracts.py, home/common/agent-skills/instruction-load.json — full — [task-4.md](2026-10-07-issue-309-ledger-clock.tasks/task-4.md)
Task 5 — The `no-wait-loops` dispatch clause — home/common/agent-skills/tests/test_dispatch_contracts.py, home/common/agent-skills/skills/sdd/implementer-prompt.md, home/common/agent-skills/skills/sdd/task-reviewer-prompt.md, home/common/agent-skills/skills/sdd/re-review-prompt.md, home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md, home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md, home/common/agent-skills/skills/sdd/SKILL.md, home/common/agent-skills/skills/from-issue/ship-handoff.md, home/common/agent-skills/skills/from-issue/SKILL.md, home/common/agent-skills/skills/from-issue/AUTO.md, home/common/claude-code/skills/orchestrate-issues/SKILL.md, home/common/agent-skills/instruction-load.json — full — [task-5.md](2026-10-07-issue-309-ledger-clock.tasks/task-5.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 2 | `LedgerClockTest.test_a_supplied_time_over_the_bound_is_refused_and_writes_nothing` (`checkpoint-delivery`, `release-worker`, `finish`; Task 1) and `LedgerClockTest.test_a_control_time_over_the_bound_is_refused_and_writes_nothing` (Task 2) in `test_delivery_workflow.py`, under `just agent-workflow-tests` |
| AC2 | code | Task 2 | `LedgerClockTest.test_every_flag_command_without_a_time_stamps_the_clock` (Task 1) and `LedgerClockTest.test_control_and_direct_owner_without_now_stamp_the_clock` (Task 2) in `test_delivery_workflow.py`, under `just agent-workflow-tests` |
| AC3 | code | Task 1 | `LedgerClockSeamTest` in `test_workflow_state.py` (override refusals, and an `ast` scan finding the override and the clock call only in `ledger_clock`), plus the whole `just agent-workflow-tests` suite in CI |
| AC4 | code | Task 1 | `LedgerClockTest.test_a_backward_refusal_names_the_wait` in `test_delivery_workflow.py`, under `just agent-workflow-tests` |
| AC5 | code | Task 5 | `HandBuiltTimeContractsTest` in `test_workflow_skill_contracts.py` (Task 4: no `--now` token and no `"now":` key in the three skill trees), and `SourceTreeContractsTest.test_no_wait_loops` in `test_dispatch_contracts.py` (Task 5), under `just agent-workflow-tests` |

## Decisions

The tasks rest on spec rows D1–D10 and on the plan-level rows D11 (where each command reads an omitted time, and the single-function seam) and D12 (the contract skew check applies only to a value that parses). Each member cites the rows it uses.

---
