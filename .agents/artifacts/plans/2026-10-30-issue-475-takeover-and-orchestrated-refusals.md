# Takeover and Orchestrated-Hold Refusals Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `workflow-state direct-owner` makes two refusals. An `owner_unavailable` takeover that would fence a live worker inside its deadline is refused, and the refusal names the worker. A direct acquisition of an issue that an orchestrated run holds is refused with the `orchestrate-control start … --run-id` command that resumes the run. The from-issue and orchestrate-issues guidance relays both refusals.

**Architecture:** A pure predicate, `takeover_blockers`, gates `direct-owner`'s takeover. Every locked write of an orchestrated run leaves an inert core *issue hold pointer* (`issue-hold/v1:<issue>:<k>`) for each issue the run holds. `direct-owner` probes those pointers before it creates anything, and reads each named run's validated ledger. The refusal texts and the resume argv are module-level literals in `workflow-state`. The skill-contract test reads them by AST.

**Tech stack:** Python 3 standard library (`unittest`, `ast`), the `agent_tools` package (`attempt_identity`, `attempt_custody`, `attempt_store`, `transaction_core`), the flat `workflow-state` script, Markdown skill text, Nix (`just build`).

Spec: `.agents/artifacts/specs/2026-10-30-issue-475-takeover-and-orchestrated-refusals-design.md` (spec commit `6a64ae8a`). A bare "Dn" cites the spec's `## Decision ledger`. This plan appends D11 to D14 to it. Issue: https://github.com/fagenorn/nix-config/issues/475.

## Global Constraints

- Base `9cb00414` (`origin/main`). Tasks land in index order, each on top of the one before.
- These stay unchanged: every other `direct-owner` refusal and reply; `control`'s and the deadline reaper's `owner_unavailable` handling (D2); the `suspend` reply's `reentry` and `reentry_command` (D9); the ledger schema (10) and every `migrate` row (D6); the Codex `orchestrate-issues` stub; every instruction-budget ceiling (D14).
- `agent_tools.attempt_identity` and `agent_tools.attempt_custody` stay pure: no file, lock, clock or environment read. `agent_tools.attempt_store` owns every store effect. Nothing new lists `workflows` or the store (D5).
- `home/common/agent-skills/tests/test_workflow_skill_contracts.py` imports nothing from `agent_tools` (issue 473 D11).
- Comments, docstrings and README sentences describe the code as it behaves at that task's commit. Where the implemented code differs from a clause this plan dictates, rewrite the clause from the code. Write "issue 475", never a bare `#475`. No `TODO` or `FIXME`.
- Run every long command, each test command included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration.
- Commit through `launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <git commit args>`. Commits are signed (never disable signing) and end with the session's trailer lines. Never run `just switch`, and never push.
- Payload discipline: targeted `rg` over whole-file reads, bounded reads around the lines that matter, and test output cut to its tail.
- **Unit run** (timeout 900 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest -q <path> [-k <pattern>]... 2>&1 | tail -12'`, where `<path>` is the repository-relative test file a member names.
- **Contract run** (timeout 600 s): `bash -c 'set -o pipefail; python3 -m unittest -q home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -6'`, with no `PYTHONPATH`.
- **Budget** (timeout 600 s): `bash -c 'set -o pipefail; just agent-instruction-budget 2>&1 | tail -3'`. It prints `check: pass`.
- Final gate (sdd, once on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each).

## Test seams

Per the spec's § Test seams, with D11 and D13 placing two of them:

- **R1 and R2 at the CLI.** `home/common/agent-skills/tests/test_workflow_state.py` drives `workflow-state` from source through `LifecycleHarness` (`direct_owner_raw`, `acquire_direct`, `init_run`, `spawn`, `suspend`, `fail_owner`, `register_worker`, `release_worker`, `mark_progress`, `check_worker`, `tree_snapshot`). It asserts exit code, stdout, stderr and the bytes under `.superpowers`.
- **R1 predicate.** The same file loads `workflow-state.py` with `load_source_module` and calls `takeover_blockers` on a hand-built ledger.
- **Pointer store.** `tests/test_attempt_identity.py` calls `attempt_identity`'s hold grammar and `attempt_store.settle_holds` and `hold_runs` on a temporary store (D11). `tests/test_attempt_custody.py` calls `holds_issue` (D12).
- **Regression.** `home/common/agent-skills/tests/test_control_cutover.py` AC1 tests stay unmodified and green.
- **Skill text.** `test_workflow_skill_contracts.py` reads `workflow-state`'s literals with `module_constants` and pins the re-entry argv and the two refusal markers (D10, D13).

## Delivery estimate and boundaries

All figures are estimates: 12 changed files and no new file, plus this package and the spec ledger, about +520/−15 lines.

- `workflow-state.py` about +65/−4; `attempt_store.py` about +60; `attempt_identity.py` about +30; `attempt_custody.py` about +8.
- Tests: `test_workflow_state.py` about +140; `tests/test_attempt_identity.py` about +95; `tests/test_attempt_custody.py` about +18; `test_workflow_skill_contracts.py` about +30.
- Text: `acquire-direct.md` +169 bytes, `orchestrate-issues/SKILL.md` +27 bytes (D14); `home/common/agent-skills/README.md` 2 sentences and 1 paragraph; `python/README.md` 1 sentence.

The change fits one review package. Task 1 stands alone. Task 3 needs Task 2's pointers. Task 4 needs Tasks 1 and 3, because its text and tests read their literals.

## Task index

Task 1 — Takeover refusal over live workers (R1) — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_workflow_state.py` — full — [task-1.md](2026-10-30-issue-475-takeover-and-orchestrated-refusals.tasks/task-1.md)
Task 2 — Issue hold pointers — `python/agent_tools/attempt_identity.py`, `python/agent_tools/attempt_custody.py`, `python/agent_tools/attempt_store.py`, `home/common/agent-skills/scripts/workflow-state.py`, `tests/test_attempt_identity.py`, `tests/test_attempt_custody.py`, `home/common/agent-skills/tests/test_workflow_state.py` — full — [task-2.md](2026-10-30-issue-475-takeover-and-orchestrated-refusals.tasks/task-2.md)
Task 3 — Orchestrated-hold refusal (R2) — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_workflow_state.py` — full — [task-3.md](2026-10-30-issue-475-takeover-and-orchestrated-refusals.tasks/task-3.md)
Task 4 — Guidance, READMEs and skill contracts — `home/common/agent-skills/skills/from-issue/acquire-direct.md`, `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, `home/common/agent-skills/README.md`, `python/README.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-4.md](2026-10-30-issue-475-takeover-and-orchestrated-refusals.tasks/task-4.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `home/common/agent-skills/tests/test_workflow_state.py::DirectTakeoverWorkerTest::test_a_takeover_inside_the_deadline_names_every_live_worker` |
| AC2 | code | Task 3 | `home/common/agent-skills/tests/test_workflow_state.py::OrchestratedHoldTest::test_every_direct_request_for_a_held_issue_is_refused_naming_the_resume_command` |
| AC3 | code | Task 4 | `home/common/agent-skills/tests/test_workflow_skill_contracts.py::OrchestratedReentryContractsTest` (both tests) and `::WorkflowSkillContractsTest::test_orchestrate_documents_carry_their_machine_text` |
| AC4 | code | Task 4 | `just agent-workflow-tests` on the final head, run by sdd's final gate after Task 4 |

## Decisions

- Task 1 follows D1 to D3. Task 2 follows D5, D6, D11 and D12. Task 3 follows D5, D7, D8, D12 and D13. Task 4 follows D4, D9, D10, D13 and D14.
- Planning appended D11 to D14 to the spec's ledger.
- Lanes: every task changes a lifecycle refusal, persisted core state, or the skill text and contract that state them, so every task is full.
- Planning trials on 2026-10-30 ran in a scratch worktree of the spec commit and were never committed. At the base, they showed:
  - the R1 positive case exits 0 with a `73:1:2` owner reply, so the takeover proceeds;
  - the R2 positive case and the pointer tests error on the missing `attempt_store.hold_runs`;
  - the contract tests fail on the base skill text, for both markers, the re-entry argv and the machine-text table row.
- With every task's dictated code, tests and skill text applied to that scratch tree (the README sentences and new docstrings excepted, since no test reads them):
  - each task's focused tests passed;
  - `just agent-instruction-budget` printed `check: pass`. `acquire-direct.md` grew by 169 bytes and `orchestrate-issues/SKILL.md` by 27;
  - `just agent-workflow-tests` passed 106 of 106 members in about 19 minutes;
  - `just build` built the darwin system.

---
