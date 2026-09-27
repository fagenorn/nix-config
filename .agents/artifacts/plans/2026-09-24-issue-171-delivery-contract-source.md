# Delivery Contract Source Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Interface 2 runs one issue end to end: a deterministic builder seals
every delivery object, the initial intent authorizes the PR it will open, contract
acquisition comes last, v1 owners survive the 2→3 migration, control reconciles
merged forges, and the lifecycle skills and auto-mode permissions describe and
allow exactly that ([#171](https://github.com/fagenorn/nix-config/issues/171)).

**Architecture:** The delivery model gains a slot `pr_ref` (Task 1). A new pure
module `workflow_delivery_build.py`, loaded by `DeliveryRuntime` beside the
projection, backs one read-only `workflow-state build-delivery` verb (Tasks 2–3),
and every helper input flag reads `-` as stdin. Tasks 4–6 change lifecycle
policy in `workflow-state.py`, `workflow_delivery.py`,
`workflow_delivery_wire.py` and the wire validator: contract-last acquisition
and null-contract semantics, legacy continuity, and forge reconciliation. Task 7
rewrites the lifecycle skills around one delivery loop; Task 8 adds four allow
rules.

**Tech stack:** Python 3 stdlib (`unittest`, subprocess round trips), Markdown
skill prose, JSON evals, Nix/Home Manager, `just`.

Spec (source of truth, read whole):
`.claude/specs/2026-09-23-issue-171-delivery-contract-source-design.md`, D1–D32.

## Global Constraints

- Scope is all of #171 in one PR (D2); out of scope is exactly the spec's
  `## Out of scope` (no ledger repair, bridge or schema-2 writer — D11, D20; no
  successor-intent minting, revocation tooling or expiring intents; only
  `tracker.kind: github`; no record deliverables; no live auto-mode demo).
- Interface 2 and schema 3 are refined in place, with no version bump (D12).
- The builder takes no lock, reads no ledger or clock, writes nothing; success
  exits 0 with canonical bytes (`model.canonical_bytes`), any refusal exits 2 with
  empty stdout (spec §1).
- Every helper input flag accepts `-` for stdin; any other value must be absolute
  (D22, D23).
- Tests use only the existing seams below (D19); the builder is exercised only
  through its CLI, never by importing the module.
- Tests use temporary roots, `HOME`s and ledgers only. Never open, migrate or
  repair `.superpowers/workflows/` in the primary checkout.
- The helpers under `~/.agents/bin` are `main`'s build: every gate runs this
  worktree's `home/common/agent-skills/scripts/*` directly or through the tests.
- A `.nix` change requires `just build` in that task; never `just switch`.
- The `PreToolUse` lifecycle guard's adjudication is unchanged (D18).
- Every task ends with `just agent-workflow-tests` green (baseline on 58eca39:
  1013 tests, 1 skipped, ~292 s); failures are summarized to failing test ids.
- Commits are SSH-signed (never disable signing) and end with the harness's
  attribution trailer lines.

Path abbreviations used in members: `S` = `home/common/agent-skills/scripts`,
`T` = `home/common/agent-skills/tests`, `SK` = `home/common/agent-skills/skills`,
`OI` = `home/common/claude-code/skills/orchestrate-issues`.

## Test seams

- Pure model facade `T/test_delivery_model.py`: slot `pr_ref` grammar, admission
  and conflict.
- `workflow-state` subprocess round trips over synthetic ledgers and project roots
  in `T/test_delivery_workflow.py` and `T/test_workflow_state.py`: builder,
  acquisition, mixed control, legacy finish, forge reconciliation, the full loop
  and the regression. Task 2's `BuilderHarness` mixin is the one project-root and
  builder driver later tasks reuse.
- `artifact-budget` CLI `T/test_artifact_budget.py`: the refined control summary
  and bootstrap shapes.
- Skill text `T/test_workflow_skill_contracts.py` and `OI/evals/evals.json`.
- Settings `tests/test_claude_permission_guard.py` over `just show-claude-settings`.

## Delivery estimate and boundaries

Estimate only: about 24 product files, the largest the new
`S/workflow_delivery_build.py` (~350 lines), `S/workflow-state.py` (+~250/−~60)
and tests (+~1,400 lines across seven files). The diff (est. 180–240 KB) exceeds
one review-package member, so review splits into three independently testable
slices: builder and binding (Tasks 1–3), lifecycle policy (Tasks 4–6), skills
plus permissions (Tasks 7–8). Tasks run in index order; each depends on every
earlier one.

## Task index

Task 1 — Slot PR binding in the delivery model — `S/delivery_model/_objects.py`, `T/test_delivery_model.py` — full — [task-1.md](2026-09-24-issue-171-delivery-contract-source.tasks/task-1.md)

Task 2 — Stdin inputs and the builder verb's contract, intent and scope kinds — `S/workflow_delivery_build.py` (create), `S/workflow_delivery.py`, `S/workflow-state.py`, `S/delivery_model/{__init__.py,_objects.py}`, `home/common/agent-skills/default.nix`, `CLAUDE.md`, `T/test_delivery_workflow.py`, `T/test_delivery_model.py`, `T/test_resolve_project.py` — full — [task-2.md](2026-09-24-issue-171-delivery-contract-source.tasks/task-2.md)

Task 3 — Builder evidence kinds and the end-to-end delivery loop — `S/workflow_delivery_build.py`, `S/workflow-state.py`, `S/artifact_budget.py`, `CLAUDE.md`, `T/test_delivery_workflow.py`, `T/test_artifact_budget.py` — full — [task-3.md](2026-09-24-issue-171-delivery-contract-source.tasks/task-3.md)

Task 4 — Contract-last acquisition and null-contract semantics — `S/workflow-state.py`, `S/workflow_delivery.py`, `S/workflow_delivery_wire.py`, `S/delivery_model/_wire.py`, `T/test_delivery_workflow.py`, `T/test_workflow_state.py`, `T/test_artifact_budget.py` — full — [task-4.md](2026-09-24-issue-171-delivery-contract-source.tasks/task-4.md)

Task 5 — Legacy finish continuity and the survival regression — `S/workflow-state.py`, `T/test_delivery_workflow.py`, `T/test_workflow_state.py` — full — [task-5.md](2026-09-24-issue-171-delivery-contract-source.tasks/task-5.md)

Task 6 — Control forge reconciliation and the selection-gated remainder — `S/workflow-state.py`, `S/workflow_delivery.py`, `S/workflow_delivery_wire.py`, `T/test_delivery_workflow.py`, `T/test_workflow_state.py`, `T/test_delivery_model.py` — full — [task-6.md](2026-09-24-issue-171-delivery-contract-source.tasks/task-6.md)

Task 7 — Lifecycle skills on interface 2 — `OI/SKILL.md`, `OI/evals/evals.json`, `SK/from-issue/{SKILL.md,AUTO.md,ship-handoff.md}`, `SK/ship-issue/{SKILL.md,REVIEW.md,HUMAN-GATE.md}`, `CLAUDE.md`, `T/test_workflow_skill_contracts.py` — full — [task-7.md](2026-09-24-issue-171-delivery-contract-source.tasks/task-7.md)

Task 8 — Auto-mode allow rules for the lifecycle helpers — `home/common/claude-code/default.nix`, `tests/test_claude_permission_guard.py`, `CLAUDE.md` — full — [task-8.md](2026-09-24-issue-171-delivery-contract-source.tasks/task-8.md)

## Criterion → task trace

| Criterion | Task | Criterion | Task |
|---|---|---|---|
| AC1.1 | 2 | AC2.3 | 4 |
| AC1.2 | 3 | AC2.4 | 4 |
| AC1.3 | 4 | AC2.5 | 5 |
| AC1.4 | 4 | AC3.1–AC3.4 | 6 |
| AC1.5 | 1 (model), 3 (workflow) | AC4.1, AC4.2 | 7 |
| AC1.6 | 3 | AC5.1, AC5.2 | 8 |
| AC1.7 | 6 | AC5.3 | 2 |
| AC2.1, AC2.2 | 5 | | |

The "Re-pins that follow" list in the spec's `## Test seams` lands in Task 4
(contractless outputs, direct-acquisition fixtures), Task 5 (`concurrent_finish`,
the schema-3 legacy refusal), Task 6 (failure-remainder round trip) and Task 7
(AUTO continuation keys, direct-acquisition anchors). The D21 `CLAUDE.md` edits
land with the code that makes them true: the builder sentence in Task 2, the
stdin sentence in Task 7 and the allow count in Task 8.

## Decisions

The spec's `## Decision ledger` is authoritative. Tasks cite D1–D22 from design
and the five rows planning added: D23 (one stdin-aware input reader, absolute
otherwise), D24 (lifecycle-only transitions, including `refuse`, never install a
contract), D25 (the scope of D8's worktree binding), D26 (remainder owners reuse
existing dispatch sites) and D27 (workflow-state resolves policy, the build
module stays pure and reads the model's `STAGE_ACTIONS` export). Phase-5 review
added D28 (the ship-handoff boundary reads under the workflow-response wire
bound), D29 (lifecycle post-merge effects are delivery-loop cycles; the legacy
summary row stays), D30 (control's reconciled remainder keys on persisted state),
D31 (a null-digest summary asks for a contract only before a would-be dispatch;
refines D10) and D32 (refusals name their rule; the contract check's stated reach).

## Standards review provenance

Reviewer: Claude fallback (opus, high), because Codex hit its usage limit. Base
`58eca39dd03641f99f0fcfa84a49fe8b7efbcc3f`, reviewed HEAD
`a8737c4431529ac62462ec79e997009be4e94b9b`; isolated and read-only; focus none.
Accepted 9 (B2 and Dsc2 with modification), rejected 0, deferred 0.

- B1 (ship-handoff exceeds the report wire bound) — D28, Task 3.
- B2 (post-merge exemption contradicts the loop) — D29, Task 7; the 9-key row is kept.
- S1 (reconciled remainder never re-planned) — D30, Task 6.
- S2 (runtime wrapper and pre-selection remainder test missed) — D30, Task 6.
- S3 (stale reconcile docstring and comments) — D30, Task 6.
- S4 (refusal tests assert only the exit code) — D32, Tasks 2–3.
- S5 (harness restates the resolver fixture) — routine, Task 2.
- Dsc1 (contract-refusal claim over-reaches) — D32, Task 2.
- Dsc2 (terminal legacy issues asked for a contract forever) — D31, Tasks 4 and 7.

---
