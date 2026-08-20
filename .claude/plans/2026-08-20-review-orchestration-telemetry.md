# Review Orchestration Telemetry Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Preserve plan-review versus diff-review identity through the detached reviewer lifecycle, and attribute multi-issue transcript telemetry truthfully while degrading unavailable process pools to an equivalent ordered sequential scan.

**Architecture:** The collaboration envelope and companion CLI carry one closed review-operation value while durable records retain the operation in `kind` and the shared lifecycle in `jobClass: review`; all post-ingress lifecycle branches use the class per D1–D2. The telemetry scanner enriches each ordered per-transcript result with identity/cwd/envelope evidence, partitions only proven owner transcripts, computes global additive totals from the raw ordered results, and wraps parallel scanning in an all-or-nothing fallback boundary per D3–D5.

**Tech stack:** Node.js ESM and `node:test` in the patched `openai/codex-plugin-cc` tree; Python 3 standard library and `unittest`; Nix patch derivation and `just` repository gates.

## Global Constraints

- The transport envelope's first two lines are exactly `WORKTREE_ROOT: <absolute path>` and `REVIEW_OPERATION: <operation>`; the closed operation set is exactly `plan-review | diff-review` (D1).
- Persist `kind = operation` and `jobClass = review`; the request carries the operation value, not a reviewer boolean. Validate at the bridge, CLI, and worker boundaries (D1).
- Cancellation, liveness reconciliation, reviewer-runtime cleanup, SessionEnd terminalization/cleanup, status family, and retention branch on review class/status, never on an operation switch (D2).
- Owner evidence is `agentId` matching `aissue-<positive issue>-owner-<positive attempt>-<generated suffix>` plus that transcript's own cwd evidence resolving to exactly the same single issue (D3).
- Root transcripts and every unproven owner/helper/reviewer transcript remain root overhead; two or more proven owner issue numbers force the root row to `(multi-issue)` (D3).
- Only the initial sidechain envelope qualifies existing `codex-collaboration` attribution as `/plan-review` or `/diff-review`; prompt prose elsewhere is not evidence (D4).
- Fully materialize pool results before accumulation. Any ordinary pool construction, mapping, iteration, or teardown exception emits exactly `Process pool unavailable (<ExceptionClass>); scanning sequentially.` and rescans every path in original order; a sequential exception still fails (D5).
- Fold global turns, token buckets, and estimated cost once from ordered raw scan results rather than reconstructing them from partitioned groups (D5).
- Do not change pricing, distribute root overhead, alter reviewer runtime policy, change non-review task lifecycle, redesign unrelated report output, add process-pool configuration, migrate records, deploy, switch, or perform live certification.
- Plugin edits happen in a scratch checkout at upstream `db52e28f4d9ded852ab3942cea316258ae4ef346`; apply with `git apply --unidiff-zero`, regenerate with `git diff -U0 <pin>`, bump `patchRevision` from 9, inspect patched source rather than patch-wide grep, and scrub `CLAUDE_PLUGIN_DATA`, `CODEX_COMPANION_SESSION_ID`, and `CODEX_COMPANION_TRANSCRIPT_PATH` for plugin tests.
- Add no dependency. Preserve SSH/GPG signing and include `Co-Authored-By: Codex <noreply@openai.com>` on every implementation commit.

## Test seams

- Companion CLI subprocess plus durable request/job records: shared cases for both operations; negative CLI and worker-side persisted-value validation.
- Status, human result, JSON result, cancellation, raw-output durability, and identical isolated-runtime cleanup for both operations.
- Dead-worker reconciliation and SessionEnd live/terminal/retention behavior parameterized over both operation kinds.
- Transcript scanner extraction of owner identity, own cwd evidence, and exact initial review envelope, including rejection of ambiguous/mismatched/prose-only evidence.
- One synthetic dispatcher session containing two owners, one helper, one plan-review transport, and one diff-review transport; separate issue rows, explicit multi-issue overhead, operation-qualified attribution, and one destination per transcript.
- Injected executor factories that fail at construction and after yielding a prefix; ordered sequential values and complete report stdout remain equal, with one concise stderr disclosure.
- Regenerated patched-tree focused/full Node tests, `python3 -m unittest -v tests/test_agent_costs.py`, `just agent-workflow-tests`, and `just build`.

## Task index

Task 1 — Preserve detached review operation identity and shared lifecycle — `patches/agent-plugins/codex-plugin-cc.patch`, `lib/agent-plugins.nix`, `home/common/claude-code/skills/codex-collaboration/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-1.md](2026-08-20-review-orchestration-telemetry.tasks/task-1.md)

Task 2 — Attribute transcript telemetry and add ordered pool fallback — `scripts/agent-costs.py`, `tests/test_agent_costs.py` — full — [task-2.md](2026-08-20-review-orchestration-telemetry.tasks/task-2.md)

## Decisions

- Review transport, record shape, validation boundaries, lifecycle classification, and shared operation coverage are fixed by D1, D2, and D6.
- Owner attribution and explicit root overhead are fixed by D3; review-operation evidence is fixed by D4.
- Pool fallback, ordered raw totals, and equivalence coverage are fixed by D5–D6.
- No new planning decision was required: the two task boundaries are the two independently testable vertical slices already selected by the accepted design.

---
