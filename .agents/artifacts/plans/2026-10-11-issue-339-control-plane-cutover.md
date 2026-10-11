# Control-Plane Cutover to Core State Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** the orchestration control plane decides from the attempt store: runs are found by index key, a slot claim is a custody span, a capacity wake is a recorded transition, each installed contract has a delivery transaction that seals `succeeded`, and a delivery remainder has custody.

**Architecture:** the ledger stays the projection package 2 made it. Two pure modules decide (`agent_tools.attempt_custody`, the settle planner, and the new `agent_tools.attempt_delivery`); two effect modules apply under the store lock (`agent_tools.attempt_store` and the new `agent_tools.attempt_delivery_store`). Everything runs in the settle step of `commit_state`, core first, ledger published once, seals last, so the 9 → 10 bind is the ordinary write and a repeat changes nothing.

**Tech stack:** Python 3 standard library and `unittest`; the `agent_tools` package; `just`.

Spec: `.agents/artifacts/specs/2026-10-11-issue-339-control-plane-cutover-design.md`, for https://github.com/fagenorn/nix-config/issues/339. Its `## Decision ledger` rows D1–D25 are cited by ID; "P2" is package 2's spec.

## Global Constraints

- Delivery base: `079b835c54fabe6baf550097c40debc595a81bda`. The tests pin the same commit as `BASE_COMMIT` and extract the whole package-2 helper from it (D16, D20).
- **Never touch a live ledger.** `/Users/anis/tmp/nix-config/.superpowers/` holds the ledgers of the orchestration that runs this plan. No test, command or manual check runs a lifecycle write, `migrate --apply` or any built `workflow-state` against it, or against a `--repo-root` that is not a `tempfile` directory.
- No `transaction_*` module changes (D14). `tests/test_transaction_core_sweep.py` stays green.
- Not edited by any task: `home/common/agent-skills/scripts/workflow_delivery*.py`, `home/common/agent-skills/scripts/delivery_model/*`, `python/agent_tools/host_admission.py`, `home/common/claude-code/lifecycle_guard.py`, root `CLAUDE.md`, `home/common/agent-skills/instruction-load.json`, and everything under `home/common/agent-skills/tests/fixtures/`. A task that seems to need one stops and reports.
- Subject, key, reason and vocabulary literals are the constants Task 1 defines. No later task restates or changes one.
- Every reply and refusal text `workflow-state` prints today is unchanged and no reply field is added. The new texts are `workflow-state: unmigrated direct run: run workflow-state migrate --apply` and Task 5's `init-run --issue-set` refusals (exit 2).
- Lock order is package 2's: `.direct-<issue>.lock` → ledger `state.lock`s → the store lock → the core's own locks. Every core write runs under the store lock, which is never requested while held. Lock-free readers take none.
- `check-launch`, `current-launch`, `owner-liveness`, `resume-pack` and `build-delivery` stay read-only: no lock, no core write, the same bytes.
- Each task leaves the suite green. A failing pre-existing test outside D16 and D22 is a defect in the new code or a conflict with the spec: stop and report it. Never weaken an assertion to pass.
- New helper code follows `docs/standards/agent-helpers.md`: package modules, plain imports, no `sys.path` or `importlib` use, digests through `agent_tools.canonical.telemetry_digest`.
- Prose a task writes into code or docs describes the code as it is at that task's head. Where a task gives content points instead of text, the implementer writes the sentences from the implemented code.
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration. Commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root.
- Abbreviations in task commands, to expand before running: `PYTEST` is `PYTHONPATH="$PWD/python" python3 -m unittest`, `T/` is `home/common/agent-skills/tests/` and `BASE` is the delivery base SHA. Timeout at least 900 s; a whole lifecycle suite (`test_workflow_state.py`, `test_delivery_workflow.py`) needs 1800 s.
- Review-package budget (D21): after every task, `git diff -U10 079b835c54fabe6baf550097c40debc595a81bda -- <file> | wc -c` is at most 60000 for every changed code or test file. A file about to pass it stops the task: report, do not split on your own.
- Final gate, run once on the final head by Task 7: `just build`, `just agent-workflow-tests`, `just agent-installed-skill-tests` (timeout 3600 s each) and `just agent-instruction-budget` with no `--raise-label`. No agent applies the `instruction-budget-raise` label.

## Test seams

- **The workflow-state CLI from source**, in three new files under `home/common/agent-skills/tests/` (D21): `test_control_cutover.py`, `test_control_decisions.py`, `test_delivery_sealing.py`. They drive package 2's `DeliveredCustody` and `LifecycleCustody` through Task 2's `Cutover` mixin, which runs either helper generation (D25). Observable: stdout, stderr, exit code, ledger bytes, a tree snapshot (`CustodyReads.tree`), and the store through `TransactionStore.lookup`, `load`, `inspect_lease`, `read_receipt` and `post_terminal_observations`.
- **Pure functions** of `agent_tools.attempt_delivery` and the planner, in the new `tests/test_attempt_delivery.py` and the existing `tests/test_attempt_custody.py`. The two effect modules are tested only through the CLI seam.

## Delivery estimate and boundaries

All numbers are estimates (`git diff -U10` bytes). Measured on a scratch prototype of the pure half and on the new test files, which were run at the base: `attempt_custody.py` 17000; `tests/test_attempt_custody.py` 19000; `attempt_delivery.py` 10000; `tests/test_attempt_delivery.py` 8000; `test_control_cutover.py` 27000; `test_control_decisions.py` 15000; `test_delivery_sealing.py` 7000. Not prototyped, so wider: `attempt_store.py` 30000; `attempt_delivery_store.py` 14000; `workflow-state.py` 30000; floor fixtures 25000 across four files. About 22 files and 3,300 lines; D21 puts the file count above Phase 0's 12 to 18.

Aggregate risk is `attempt_store.py` and `workflow-state.py`, each touched by five tasks, and the floor sweeps of Tasks 2 and 5. Fallback slices, each leaving the suite green: Tasks 1–5 (the cutover) and Tasks 6–7 (seals, supplements, prose). A split is the caller's to authorize (D18).

## Task index

Task 1 — Pure rules: delivery subject, journal, remainder subject and the planner's new rows — `python/agent_tools/attempt_delivery.py`, `python/agent_tools/attempt_custody.py`, `tests/test_attempt_delivery.py`, `tests/test_attempt_custody.py`, `justfile` — full — [task-1.md](2026-10-11-issue-339-control-plane-cutover.tasks/task-1.md)
Task 2 — Schema 10: remainder custody, span claims, the capacity wake and the decision cases — `python/agent_tools/attempt_store.py`, `python/agent_tools/attempt_identity.py`, `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_control_cutover.py`, `home/common/agent-skills/tests/test_control_decisions.py`, `justfile`, floor fixtures in `home/common/agent-skills/tests/test_workflow_state.py` and five more test files — full — [task-2.md](2026-10-11-issue-339-control-plane-cutover.tasks/task-2.md)
Task 3 — Control reads occupancy and the capacity gate from the store — `python/agent_tools/attempt_store.py`, `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_control_cutover.py` — full — [task-3.md](2026-10-11-issue-339-control-plane-cutover.tasks/task-3.md)
Task 4 — The delivery transaction and its journal — `python/agent_tools/attempt_delivery_store.py`, `python/agent_tools/attempt_store.py`, `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_control_cutover.py`, `home/common/agent-skills/tests/test_control_decisions.py`, `home/common/agent-skills/tests/test_attempt_custody.py` — full — [task-4.md](2026-10-11-issue-339-control-plane-cutover.tasks/task-4.md)
Task 5 — Runs by index: `direct-owner`, `build-delivery` and `init-run --issue-set` — `python/agent_tools/attempt_store.py`, `python/agent_tools/attempt_delivery_store.py`, `python/agent_tools/attempt_identity.py`, `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_control_cutover.py`, `tests/test_attempt_identity.py`, floor fixtures in `home/common/agent-skills/tests/test_workflow_state.py` and two more test files — full — [task-5.md](2026-10-11-issue-339-control-plane-cutover.tasks/task-5.md)
Task 6 — Delivery proof, the `succeeded` seals and receipt supplements — `python/agent_tools/attempt_custody.py`, `python/agent_tools/attempt_store.py`, `python/agent_tools/attempt_delivery_store.py`, `home/common/agent-skills/scripts/workflow-state.py`, `tests/test_attempt_custody.py`, `home/common/agent-skills/tests/test_delivery_sealing.py`, `home/common/agent-skills/tests/test_attempt_custody.py`, `justfile` — full — [task-6.md](2026-10-11-issue-339-control-plane-cutover.tasks/task-6.md)
Task 7 — Skill argv, contract prose and the final gate — `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `python/README.md`, `home/common/agent-skills/README.md` — full — [task-7.md](2026-10-11-issue-339-control-plane-cutover.tasks/task-7.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 5 | `home/common/agent-skills/tests/test_control_cutover.py`: the three `IndexResolutionTest.test_ac1_*` tests and `UnmigratedDirectTest.test_ac1_*`; with Task 3's `StoreReadTest.test_ac1_occupancy_is_counted_from_the_store` |
| AC2 | code | Task 2 | same file: the three `CapacityWakeTest.test_ac2_*` tests (the wake, the queue, read-only `check-launch`); with Task 3's `StoreReadTest.test_the_capacity_gate_is_read_from_the_store`; `test_admission_replay.py` unedited on its committed baseline |
| AC3 | code | Task 2 | `home/common/agent-skills/tests/test_control_decisions.py`: `DecisionTest.test_01_spawn` to `test_19_finalize`, one per row of the spec's decision table, kept green by every later task (Task 4 completes rows 1 and 7); with Task 1's planner cases in `tests/test_attempt_custody.py` |
| AC4 | code | Task 7 | `just agent-workflow-tests` green at the final head with D16 and D22 as the only edits to pre-existing tests; `just build`; `just agent-installed-skill-tests`; `just agent-instruction-budget`; with Task 2's `SchemaTenTest.test_ac4_the_bind_is_dry_run_first_and_the_base_helper_refuses_schema_10` and Task 6's `SealingTest.test_ac4_a_delivery_through_a_remainder_seals_its_proof_then_its_custody` |

## Decisions

- What control reads from the store: D12. Claims as spans and `owner_unavailable`: D1, D15, D17. Wakes and the gate: D4, D23.
- Delivery transaction, journal and its module: D2, D14, D21. Remainder custody: D3. Seals and supplements, kept in this package: D5, D6, D18, D19.
- Run resolution: D9, D10, D11. Schema 10 and the bind: D7. The decision table and its twin run: D13, D20. The unreadable fixture: D8, D23. Floor changes: D16, D22. Plan-level interfaces and the test harness: D24, D25.

---
