# Epoch-Fenced Attempt Custody and Late-Result Receipts Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** every implementation attempt holds its worktree under an epoch-fenced core lease, and a reaper's stop and an owner's late result are both kept as core events that a write-once receipt seals, with misbound and superseded owner transports refused as fencing violations.

**Architecture:** each attempt gets one core *custody transaction* in package 1's attempt store. A pure module, `agent_tools.attempt_custody`, maps a ledger attempt and a transaction snapshot to an ordered operation list; `agent_tools.attempt_store` applies it under the blocking store lock; `workflow-state` calls that settle step inside `commit_state`, core first and seal last, so the ledger's attempt fields become a projection the core can refuse. Owner transports pass one pre-mutation step in `transact` (launch fence, late-finish adoption, retention of a refused result) and a lock-free misbinding check before any lock.

**Tech stack:** Python 3 standard library and `unittest`; `agent_tools` (`transaction_core`, `transaction_custody`, `attempt_identity`, `attempt_store`); `just`.

Spec: `.agents/artifacts/specs/2026-10-10-issue-338-fenced-custody-receipts-design.md`, for https://github.com/fagenorn/nix-config/issues/338. Its `## Decision ledger` rows D1–D26 are cited by ID.

## Global Constraints

- Delivery base: `5bd914e199f3e57217780596beefe69838f4efd4`. The old-helper test pins the same commit (D14).
- **Never touch a live ledger.** `/Users/anis/tmp/nix-config/.superpowers/` holds the ledgers of the orchestration that runs this plan. No test, command or manual check runs a lifecycle write, `migrate --apply` or any built `workflow-state` against it, or against a `--repo-root` that is not a `tempfile` directory.
- Subject, key, reason and vocabulary literals are the constants `agent_tools.attempt_custody` defines in Task 2. No later task restates or changes one.
- The only change to a `transaction_*` module is Task 1's. `tests/test_transaction_core_sweep.py` (the neutrality check) stays green; the identifier `rebase` is a forbidden word there.
- Not edited by any task: `home/common/agent-skills/scripts/workflow_delivery*.py`, `home/common/agent-skills/scripts/delivery_model/*`, `home/common/claude-code/lifecycle_guard.py`, root `CLAUDE.md`, `home/common/agent-skills/instruction-load.json` (D10, D9). A task that seems to need one stops and reports.
- The lifecycle guard is not edited, so `tests/test_claude_permission_guard.py` needs no change and must stay green. Task 7's skill edit is gated by the instruction budget and by the skill contract, shell-example and lint suites.
- Every refusal `workflow-state` prints today keeps its text (D13, D20). New refusals are `workflow-state: fencing violation: <reason>: <detail>` (exit 2) and `workflow-state: custody projection mismatch: <detail>` (exit 2).
- Lock order, outermost first: `.direct-<issue>.lock` → ledger `state.lock`s → the store lock (`<store>/attempt-runs.lock`, blocking) → core `creation.lock` → core `<id>/lock` → core `leases.lock`. Every core write `workflow-state` makes runs under the store lock; the store lock is never requested while it is held; lock-free readers take none (D15).
- `check-launch`, `current-launch`, `owner-liveness` and `resume-pack` stay read-only: no clock, no lock, no core write, the same bytes.
- New helper code follows `docs/standards/agent-helpers.md`: package modules, plain imports, no `sys.path` or `importlib` use, digests through `agent_tools.canonical.telemetry_digest`.
- Prose a task writes into code or docs (docstrings, comments, README sentences) describes the code as it is at that task's head. Where a task gives content points instead of text, the implementer writes the sentences from the implemented code.
- A floor failure outside D22's declared fixture changes is a defect in the new code or a conflict with the spec: stop and report it. Never weaken an assertion to pass.
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration. Commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root.
- Python tests run as `PYTHONPATH="$PWD/python" python3 -m unittest <file> [-k <pattern>]` (an absolute `PYTHONPATH`; a relative one breaks the launcher suites), timeout at least 900 s; a whole lifecycle suite needs 1800 s.
- Review-package budget (estimate basis below): `git diff -U10 5bd914e199f3e57217780596beefe69838f4efd4..HEAD -- <file> | wc -c` stays at most 60000 for every changed code or test file after every task.
- Final gate, run once on the final head by Task 7: `just build`, `just agent-workflow-tests`, `just agent-installed-skill-tests` (timeout 3600 s each) and `just agent-instruction-budget` with no `--raise-label`. No agent applies the `instruction-budget-raise` label.

## Test seams

- **The workflow-state CLI from source**, through `LifecycleHarness.run_cli` (in process) and `DeliveredControlHarness.cli` (a subprocess), in the new `home/common/agent-skills/tests/test_attempt_custody.py`. Observable: stdout, stderr, exit code, ledger bytes, and the store read through `TransactionStore.lookup`, `load`, `inspect_lease` and `read_receipt`. A tree snapshot is every path under the observed root with its bytes: the whole root for the delivered-control harness, `<root>/.superpowers` for the lifecycle harness, which keeps its request files beside it.
- **`agent_tools.attempt_custody`'s pure functions**, imported normally by the new `tests/test_attempt_custody.py`; its planner cases build real snapshots with a `TransactionStore` on an injected clock.
- **The core store with an injected clock**, in the existing `tests/test_transaction_custody.py`, for `renew(ttl_ms=…)`.
- `agent_tools.attempt_store` is tested only through the CLI seam.

## Delivery estimate and boundaries

Estimates, measured on a throwaway prototype of this design (`git diff -U10` bytes per file; shipped code adds docstrings, so allow about a quarter more): `workflow-state.py` 31200; `home/…/tests/test_attempt_custody.py` 33000 (new); `test_workflow_state.py` 24300; `attempt_store.py` 19700; `tests/test_attempt_custody.py` 14900 (new); `attempt_custody.py` 10700 (new); `test_delivery_workflow.py` 7600; `transaction_core.py` 4000; `test_attempt_migration.py` 3200; `test_host_admission.py`, `transaction_custody.py`, `tests/test_transaction_custody.py`, `tests/test_attempt_identity.py`, `attempt_identity.py` under 3000 each; plus Task 7's skill line, two test pins and two README sections. About 17 files and 165 KB, no file near the 60000 ceiling.

The prototype ran the lifecycle suites: every pre-existing failure fell into D22's fixture changes. Aggregate risk is the fixture sweep in `test_workflow_state.py` and `test_delivery_workflow.py` (Tasks 3 and 4), not product code. Fallback slices if a review package overflows: Tasks 1–3 (custody in the core, migration) and Tasks 4–7 (fencing, intake, compatibility, prose); each leaves the suite green.

## Task index

Task 1 — Core `renew(ttl_ms=…)` — `python/agent_tools/transaction_core.py`, `python/agent_tools/transaction_custody.py`, `tests/test_transaction_custody.py` — full — [task-1.md](2026-10-10-issue-338-fenced-custody-receipts.tasks/task-1.md)
Task 2 — The pure `attempt_custody` module and the vocabulary's one home — `python/agent_tools/attempt_custody.py`, `tests/test_attempt_custody.py`, `home/common/agent-skills/scripts/workflow-state.py`, `justfile` — full — [task-2.md](2026-10-10-issue-338-fenced-custody-receipts.tasks/task-2.md)
Task 3 — Schema 9: the custody settle step and the 8 → 9 bind — `python/agent_tools/attempt_store.py`, `python/agent_tools/attempt_identity.py`, `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_attempt_custody.py`, `justfile`, floor fixtures in `home/common/agent-skills/tests/test_workflow_state.py`, `test_attempt_migration.py`, `test_delivery_workflow.py`, `test_host_admission.py`, `tests/test_attempt_identity.py` — full — [task-3.md](2026-10-10-issue-338-fenced-custody-receipts.tasks/task-3.md)
Task 4 — Owner transports: the launch fence and misbinding — `home/common/agent-skills/scripts/workflow-state.py`, `python/agent_tools/attempt_store.py`, `home/common/agent-skills/tests/test_attempt_custody.py`, harness transports in `test_workflow_state.py`, `test_delivery_workflow.py`, `test_host_admission.py` — full — [task-4.md](2026-10-10-issue-338-fenced-custody-receipts.tasks/task-4.md)
Task 5 — Late-result intake: recording, adoption, retention — `home/common/agent-skills/scripts/workflow-state.py`, `python/agent_tools/attempt_store.py`, `home/common/agent-skills/tests/test_attempt_custody.py` — full — [task-5.md](2026-10-10-issue-338-fenced-custody-receipts.tasks/task-5.md)
Task 6 — Compatibility: the base helper and the launch projections — `home/common/agent-skills/tests/test_attempt_custody.py` — full — [task-6.md](2026-10-10-issue-338-fenced-custody-receipts.tasks/task-6.md)
Task 7 — Skill argv, contract prose and the final gate — `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `python/README.md`, `home/common/agent-skills/README.md` — full — [task-7.md](2026-10-10-issue-338-fenced-custody-receipts.tasks/task-7.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 3 | `home/common/agent-skills/tests/test_attempt_custody.py`: the three `CustodyLeaseTest.test_ac1_*` tests; with Task 1's `tests/test_transaction_custody.py`: `RenewTest.test_renew_with_a_ttl_rebases_the_lease_in_place_whatever_the_margin` and `test_renew_with_a_ttl_refuses_a_bad_ttl_and_a_lapsed_span` |
| AC2 | code | Task 5 | same file: `LateLegacyResultTest.test_ac2_a_late_finish_supersedes_the_reapers_stop_in_the_receipt`, `test_ac2_a_late_merged_finish_is_recorded_and_left_unsealed`, `LateSummaryTest.test_ac2_a_late_summary_supersedes_the_reapers_stop_in_the_receipt`; with Task 3's `CustodyRepairTest` (an interrupted seal is completed) |
| AC3 | code | Task 4 | same file: `MisbindingTest.test_ac3_a_session_in_another_attempts_worktree_is_refused_before_any_write` |
| AC4 | code | Task 5 | same file: `LateSummaryTest.test_ac4_merged_and_closed_are_observed_apart_from_custody`, beside the AC2 and AC3 fixtures above |
| AC5 | code | Task 5 | same file: `LaunchFenceTest.test_ac5_attempt_keyed_finish_is_refused_and_its_result_retained`; `test_an_earlier_launch_cannot_replace_its_successors_stalled_stop`; with Task 4's `test_ac5_attempt_keyed_progress_and_suspend_after_a_successor_launch` and `test_ac5_an_attempt_created_at_schema_9_needs_its_launch_named` |
| AC6 | code | Task 7 | `just agent-workflow-tests` green at the final head with D22's fixture changes as the only edits to pre-existing tests and `test_admission_replay` on its committed baseline; `just build`; `just agent-installed-skill-tests`; with Task 6's `CompatibilityTest.test_ac6_the_base_helper_refuses_a_schema_9_ledger_without_writing` and `test_ac6_launch_projections_print_the_same_bytes_across_the_bind` |

## Decisions

- Custody object, lease window, launch as a span, projection and write order: D1–D4, D12, D15, D16. Clock, every-attempt settle, sealed-is-final, lazy creation: D17–D19. Interrupted-write recovery and seal completion: D24.
- Verdicts, receipts and what stays unsealed: D5. Intake, adoption and retention: D6, D21.
- Misbinding: D7. Launch naming, fencing reasons and where they print: D9, D13, D20, D23.
- Suspension vocabulary and its home: D8. Remainders and the delivery runtime untouched: D10.
- Migration, schema marker, old-helper pin: D4, D11, D14, D25. Floor fixture changes: D22. Byte-exact refusal fixtures: D26.

## Standards review provenance

Plan review by `Codex`, base SHA `5bd914e199f3e57217780596beefe69838f4efd4`, isolated read-only mode, no focus, no fallback. Accepted 6, rejected 0, deferred 0; every finding was re-checked against the cited code first.

- 338-B1: accepted. A finish from an earlier launch over a synthetic stop is fenced and retained (Task 5; D23).
- 338-B2: accepted. The planner tracks parking and span separately, with a per-prefix recovery test (Task 2; D24).
- 338-B3: accepted. The preflight ignores a holder whose own earlier plan ends its span (Task 3; D24).
- 338-B4: accepted. An unchanged repeat and `migrate --apply` complete a pending seal (Tasks 3 and 5; D24).
- 338-B5: accepted. An attempt its binding write ends is still bound and sealed (Tasks 2 and 3; D25).
- 338-S1: accepted. Byte-exact refusal fixtures use a finish helper that restores nothing (Tasks 3 to 5; D26).

---
