# Direct Autonomous Implementation Owner Rollover Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Make module-owned direct autonomous runs delegate at self-contained artifact seams, resume an exact absent Phase-0 reservation, and transfer reviewed implementation to one fresh lifecycle owner before SDD.

**Architecture:** Deepen the existing `workflow-state` module without widening its CLI or ledger schema: phase-action derivation becomes run-identity-aware, and the shared acquisition policy admits one direct-only Phase-0 resume fact. Tighten the installed `from-issue` autonomous contract so the reviewed Phase-5 artifact boundary durably delegates Phases 6–7 to a fresh owner while every adjacent acquisition mode retains its existing behavior.

**Tech stack:** Python 3 standard library CLI and `unittest`, Markdown skill/spec contracts, Git worktrees, Just, Nix.

## Global Constraints

- Apply the new phase-action order and reviewed-plan rollover only to module-owned direct autonomous identities; dispatcher-owned, explicitly durable interactive, and ledger-free interactive behavior remains byte-for-byte unchanged.
- Keep phase-input fields, persisted attempt schema, action enum, attempt limits, fixed deadlines, terminal summaries, direct-owner authorization, and lifecycle schema version unchanged.
- Derive direct policy from the validated reserved run ID inside `workflow-state`; add no caller mode or authorization flag.
- Keep Git, tracker reads, worktree creation, owner dispatch, artifact reads, SDD, and shipping outside the lifecycle module.
- Resume an absent recorded path only for an unexpired handed-off direct attempt whose completed phase is exactly 0, and preserve the run, attempt, owner, worktree, start time, deadline, and handoff path.
- The pre-rollover controller must stop before SDD or implementation edits; dispatch failure may be durably failed but never implemented locally.
- Bind the fresh continuation to the exact reviewed full HEAD SHA and reject any clean but different commit before artifact reads.
- Record every delegated-owner phase boundary: Phase-6 `delegate` launches the existing ship owner, and Phase-7 ledger-only `delegate` launches only the exact finish bookkeeper.
- Append explicit issue-74 amendment markers to the accepted issue-33 phase-order and issue-73 acquisition records; do not rewrite their point-in-time claims or create a glossary/ADR tree.
- Every task is `full` risk because it changes lifecycle, concurrency-sensitive persistence, or public agent contracts.

## Test seams

- Progress CLI seam: exercise the complete direct-only mixed-input precedence and reopened action validation while retaining exact non-direct ledger bytes.
- Direct-owner CLI seam: exercise exact absent Phase-0 handoff reacquisition plus mutation-free mismatch, wrong-phase, active-owner, dispatcher, and alternate-candidate cases.
- Real-filesystem seam: create a temporary repository with `origin/main`, resume the absent reservation, materialize that exact path with `git worktree add`, and record Phase 1 on the same attempt.
- Skill contract seam: pin the ordered Phase-5 commit/check/progress/delegate/dispatch protocol, exact reviewed-HEAD continuation, fresh-owner validation, Phase-6 ship delegation, Phase-7 ledger-only finish delegation, terminal persistence, and earlier-controller stop.
- Repository seams: `just agent-workflow-tests` proves deterministic module/skill contracts and `just build` proves the helper and installed skill documentation ship together.

## Task index

Task 1 — Select direct phase actions from durable run identity — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_workflow_state.py`, `.claude/specs/2026-08-17-workflow-lifecycle-hardening-design.md` — full — [task-1.md](2026-08-20-direct-autonomous-implementation-owner-rollover.tasks/task-1.md)

Task 2 — Resume and materialize an exact absent Phase-0 reservation — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_workflow_state.py`, `.claude/specs/2026-08-20-direct-autonomous-issue-durability-design.md` — full — [task-2.md](2026-08-20-direct-autonomous-implementation-owner-rollover.tasks/task-2.md)

Task 3 — Enforce the reviewed-plan implementation-owner rollover — `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/from-issue/AUTO.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-3.md](2026-08-20-direct-autonomous-implementation-owner-rollover.tasks/task-3.md)

## Standards review

Reviewer provenance: `reviewer=native; job_id=issue74-phase5-native; base_sha=c780b38f613c59a7d6674dc081d9f67666054ebf; fallback=false`. Applied B1 by closing and separating the transfer/owner/controller-stop test seams (D7); applied S1 by adding clean task starts and mechanically scoped current-task path gates; applied S2 by pinning exact-recorded authority in the presence of an alternate candidate (D8); resolved D1 by including mechanical-only direct autonomous runs in the rollover while preserving their existing fresh-owner Phase-6 route (D9).

Ship review: conformance clean; correctness findings COR-001 and COR-002 applied by binding the continuation to `reviewed_head_sha` (D10) and routing the delegated owner's Phase-6/7 actions through the existing ship-owner and ledger-only seams (D11).

## Decisions

- Direct-only precedence and identity-derived policy follow D1–D2.
- The mandatory reviewed-plan seam and bounded fresh-owner interface follow D3–D4.
- Exact absent Phase-0 reservation resume follows D5.
- Public CLI, real-filesystem, installed-skill, and documentation seams follow D6.
- Phase-5 closed-interface, mixed-observation authority, and mechanical-direct scope corrections follow D7–D9.
- Reviewed-content identity and delegated-owner Phase-6/7 action routing follow D10–D11.

---
