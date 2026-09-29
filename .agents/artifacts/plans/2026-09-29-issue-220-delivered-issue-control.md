# Delivered-Issue Control Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `workflow-state control` never plans a launch for an issue whose delivery is
complete, reports a stale nonterminal record of such an issue in its summary, and never
commits a reply the `workflow-response` boundary rejects
([#220](https://github.com/fagenorn/nix-config/issues/220)).

**Architecture:** three changes to the legacy flat scripts, each behind its own regression
test at the existing CLI seam. Control computes the requested issues whose persisted ledger
is delivery-complete right after its opening admission settle, and gives each a fixed
`terminal` verdict in place of the one-issue policy, both in the analysis pass and in its one
`apply_policy` entry (per D1, D2, D9). The custody projection gains `nonterminal_custody`,
the unmasked read that `current_custody` becomes a masked view over, and a delivered
summary's `custody` comes from it (per D4). Control renders its reply to the exact bytes it
prints and validates them through `artifact_budget_validate` at the `workflow-response`
boundary inside the ledger transaction, before `commit_state` (per D5, D6).

**Tech stack:** Python 3 standard library, `unittest`, `just`, the real `artifact-budget`
validator (`home/common/agent-skills/scripts/artifact_budget.py`).

Spec (source of truth, read it whole):
`.agents/artifacts/specs/2026-09-29-issue-220-delivered-issue-control-design.md`, D1–D15.
The code base is commit `3081d23`.

## Global Constraints

- Scope is exactly the spec's; its `## Out of scope` list binds: no terminalisation or repair
  of stale records, no `direct-owner` change, no same-sweep fold special case, no
  `agent_tools.transaction_*` or #125 work, no move into `agent_tools`, no CI or
  branch-protection change (per D1, D2, D7).
- No ledger schema change and no migration: a ledger that already holds a stale `active`
  remainder or attempt stays valid and unrewritten (per D7).
- No new wire vocabulary: summary, delta and action shapes and their closed value sets are
  unchanged; only a delivered summary's existing `custody` field gains a value (per D4).
- No mock of the validator, the policy or `workflow-state`: every new test drives the real
  CLI as a subprocess and pipes replies through the real `artifact_budget.py` (per D8).
- The adapter's own per-object boundary validation in `orchestrate-issues` §4 stays exactly
  as written (per D6).
- Standard library only; no new import machinery in `workflow-state.py` (per D5).
- Commits are SSH-signed; every commit message ends with the two trailer lines
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01WG2fFRR2AsYntH7C2Y5XM6`.

## Test seams

- `home/common/agent-skills/tests/test_delivered_control.py`, one `BuilderHarness` test case
  that drives `workflow-state.py` as a subprocess under the recipe's `PYTHONPATH` and runs the
  real `artifact_budget.py validate-report --boundary workflow-response` on replies. The
  fixture reproducing the issue-207 shape is pinned per D11.
- A source-layout copy of `home/common/agent-skills/scripts/` beside a copied
  `artifact-budget-policy.json` whose `workflow_responses.wire_max_bytes` is 64, so the real
  boundary rejects every control reply (per D8).
- The existing `test_workflow_state.py` lifecycle suite, whose one combined-blocker
  expectation changes order per D10.

## Delivery estimate and boundaries

Estimates only. About six changed files: `workflow-state.py` (about +50/−10 lines),
`workflow_delivery_wire.py` (about +10), one new test file (about 400 lines),
`test_workflow_state.py` (a 4-line reorder), the `justfile` (+1) and the
`orchestrate-issues` skill (+1 sentence). The new test file is the aggregate-growth risk; the
whole change is one reviewable slice well inside a review-package boundary, so no further
split is planned.

## Task index

Task 1 — Gate delivered issues out of control's launch lanes (acceptance 1, TDD) — `home/common/agent-skills/tests/test_delivered_control.py`, `justfile`, `home/common/agent-skills/scripts/workflow-state.py` — full — [task-1.md](2026-09-29-issue-220-delivered-issue-control.tasks/task-1.md)

Task 2 — Report a delivered issue's stale custody in its summary (acceptance 3) — `home/common/agent-skills/scripts/workflow_delivery_wire.py`, `home/common/agent-skills/tests/test_delivered_control.py`, `home/common/claude-code/skills/orchestrate-issues/SKILL.md` — full — [task-2.md](2026-09-29-issue-220-delivered-issue-control.tasks/task-2.md)

Task 3 — Validate control's reply bytes before commit (acceptance 2) — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_delivered_control.py`, `home/common/agent-skills/tests/test_workflow_state.py` — full — [task-3.md](2026-09-29-issue-220-delivered-issue-control.tasks/task-3.md)

Task 4 — Run the full workflow suite and the Nix build (acceptance 4) — no files — mechanical — [task-4.md](2026-09-29-issue-220-delivered-issue-control.tasks/task-4.md)

## Decisions

The spec's `## Decision ledger` owns every row. Tasks cite D1–D9 from the design and the
planning rows D10 (control sorts its blockers into the wire's closed order), D11 (the pinned
issue-207 regression fixture), D12 (delivered issues also skip the candidate-worktree replay
check), and the plan-review rows D13 (the delivered summary signature adds empty
`requirements` and null `owner`, amending D4), D14 (no remainder-lane guard; the replay skip
and D9's recovery proof each get a regression, amending D12) and D15 (`print_json` writes
`render_json`, amending D5).

## Standards review provenance

The plan-review reviewer was the Claude fallback (native Opus reviewer). The Codex run
(gpt-6-astra/xhigh, read-only, ephemeral) completed, but its JSONL lacked the required
runtime-selection model/effort event, so it failed metadata validation and triggered exactly
one native fallback; its single should-fix (PR220-01) duplicated SF-3. Base SHA
`93bf5fd2cdff5bb6ca347dc38a14767ebd6d4176`; the review ran isolated and read-only.

- Accepted: 4 should-fix, 0 blocking — SF-1 (D13), SF-2 and SF-3 with PR220-01 merged into
  SF-3 (D14), SF-4 (D15).
- Discussion: D-1 kept as-is (the `apply_policy` gate stays the single entry, per D1); D-2
  recorded in D10 (direct-owner blocker order); D-3 recorded in the spec's `## Out of scope`
  (a delivered issue's `launch_refused`).
- Rejected: none.

---
