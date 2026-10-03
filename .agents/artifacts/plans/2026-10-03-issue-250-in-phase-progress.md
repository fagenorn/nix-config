# Durable In-Phase Progress Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Let an active attempt record a durable progress marker so that a
same-phase suspension after real forward movement starts a fresh anti-zombie
stall count, while an owner that parks without moving still stops at the
existing boundary (issue #250).

**Architecture:** The lifecycle ledger moves to schema 6, where every attempt
carries a nullable `progress_marker` commit ID. A new `workflow-state
mark-progress` verb derives the marker from the attempt's recorded worktree and
clears the stall fields only when the checked-out commit strictly descends from
the stored marker. `suspend_attempt` and every suspension path stay unedited;
the sdd and from-issue skills tell the Phase 6 owner when to run the verb.

**Tech stack:** Python 3 standard library (`home/common/agent-skills/scripts/workflow-state.py`,
`workflow_delivery.py`), `unittest`, `git` by name on `PATH`, Markdown skill sources.

Spec: [2026-10-03-issue-250-in-phase-progress-design.md](../specs/2026-10-03-issue-250-in-phase-progress-design.md).
Read it before any task; it owns the design and the decision ledger.

## Global Constraints

- `STALL_LIMIT`, `suspend_attempt`, `resume_attempt`, `demote_expired_attempt`,
  the `stalled` result source and the stop reason text
  `suspension stalled without phase progress` are not edited (per D5, D9).
- The delivery remainder record, its `progress_token` and its bound are not
  edited.
- A progress marker is `null` or a full lowercase hexadecimal commit ID of 40
  or 64 characters; nothing else validates (per D4).
- The verb's command line is exactly
  `workflow-state mark-progress --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --action-id <action_id>`;
  it takes no marker argument (per D1, D2).
- The new code lands in the legacy `workflow-state` script, with no new
  `agent_tools` module and no new command-table row (per D10).
- Source carries no `TODO` or `FIXME`. Comments say why; they cite this
  issue's decisions as `#250 D<n>`.
- Project commits are SSH-signed; never disable signing for them, and surface
  a signing failure rather than working around it. Every commit message ends
  with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Run every command from the worktree root. Summarise test output to the
  failing lines; never paste whole logs. A gate that pipes a runner into
  `tail` starts with `set -o pipefail;` so the runner's failure is the gate's
  (per D14).

## Test seams

- Public `workflow-state` commands run as a subprocess through
  `LifecycleHarness.run_cli`, and the persisted `state.json` read back with
  `read_state` / `state_path.read_bytes()`. No test calls `suspend_attempt` or
  the new rule function directly, and none mocks git.
- A real git repository created under the test's temporary directory serves as
  the attempt worktree (per D13).
- Host-capacity refusals are driven through `LaunchRefusalTest` in
  `test_host_admission.py`, which shares `LifecycleHarness` (per D13): four
  refusal cycles through `control`, with no stall counter written by hand
  (per D14).
- The two probe-to-transaction re-checks are the only in-process cases: the
  probe is wrapped so a public command lands between it and the transaction
  (per D14).
- Skill wording is pinned by ordered-anchor assertions over
  whitespace-normalised skill text in `test_workflow_skill_contracts.py`.

## Delivery estimate and boundaries

Estimates, not promises: about 11 files change — 2 scripts, 4 test modules, 3
skill sources, `instruction-load.json` and `CLAUDE.md` — for roughly 550 added
lines, most of them tests. The growth risk is `test_workflow_state.py`
(already 6,850 lines) and the instruction-load ceilings, which have zero
headroom today and must rise with the skill prose. The three tasks are
sequential: Task 2 needs Task 1's schema, and Task 3 documents the verb Task 2
ships. Task 1 alone is deliverable (a field nothing writes yet); Tasks 1–2
together fix the helper without changing owner behaviour.

## Task index

Task 1 — Ledger schema 6: `progress_marker` and the 5→6 migration — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/scripts/workflow_delivery.py`, `home/common/agent-skills/tests/test_workflow_state.py`, `home/common/agent-skills/tests/test_delivery_workflow.py`, `home/common/agent-skills/tests/test_host_admission.py` — full — [task-1.md](2026-10-03-issue-250-in-phase-progress.tasks/task-1.md)

Task 2 — `workflow-state mark-progress`: marker rule, worktree probe and command — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_workflow_state.py`, `home/common/agent-skills/tests/test_host_admission.py` — full — [task-2.md](2026-10-03-issue-250-in-phase-progress.tasks/task-2.md)

Task 3 — Owner instructions, skill contract, architecture document and completion gates — `home/common/agent-skills/skills/sdd/SKILL.md`, `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, `home/common/agent-skills/instruction-load.json`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `CLAUDE.md` — full — [task-3.md](2026-10-03-issue-250-in-phase-progress.tasks/task-3.md)

All three are `full`: Task 1 is a ledger migration, Task 2 is lifecycle code,
and Task 3 changes the instructions that drive lifecycle owners.

## Acceptance coverage

| Issue criterion | Task |
|---|---|
| New marker between same-phase suspensions never stalls | 2 (demo, expiry and host-capacity tests) |
| No new marker still stops at the fourth suspension, host-caused included | 2 (non-reset cases); existing stall tests stay green in 1–3 |
| Replay and non-active recording do not reset | 2 |
| Persisted before success, survives suspend/resume, strict validation, old ledgers load with counts | 1 (schema), 2 (persistence) |
| Owner instructions plus skill-contract test | 3 |
| Suite through public commands; `just agent-workflow-tests` and `just build` pass | 1–3, final gate in 3 |

## Decisions

This plan rests on the spec's ledger: D1–D3 (verb, helper-derived marker,
strict descendant), D4 (schema 6), D5 (reset at record time), D6–D7 (baseline
and zero-exit no-write outcomes), D8 (probe before the lock), D9–D11, and the
plan-phase rows D12 (how a pre-schema-6 ledger reads during `mark-progress`)
D13 (test seams for the git fixture and host-capacity case) and D14 (unseeded
host-capacity cycles, the launch re-check test and `pipefail` gates).

## Standards review provenance

Reviewer: Codex (gpt-6-astra, xhigh), isolated read-only mode, no focus, no
fallback. Base SHA 5f865639eb669ac80ea66c50c9a20a0636fa1dde. Findings: 3
accepted, 0 rejected, 0 deferred.

- B1 (blocking, accepted): every gate that pipes a runner into `tail` now
  sets `pipefail`; red-phase steps expect a non-zero exit.
- S1 (should-fix, accepted): the host-capacity stall tests drive four refusal
  cycles through `control` with no seeded counter; the seeded test is
  replaced under its own name (Task 2).
- S2 (should-fix, accepted): a second probe-interleaving test suspends the
  launch before the transaction, so only the locked launch re-check can
  refuse it (Task 2).

---
