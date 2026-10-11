# Delegated Ship Routing Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** On the generic `delegate` route, make the delegated from-issue owner return the validated ship handoff after Phase 6 so that the owner that delegated launches the ship owner, one level higher, where the ship owner can still launch its reviewers (https://github.com/fagenorn/nix-config/issues/352).

**Architecture:** Skill text only, plus tests and evals. `SKILL.md`'s `delegate` action gains the closed prompt line and the delegating owner's handling of the return; `delegated-owner.md` gains a `## Generic delegate` section. The ledger helper is not changed: new tests prove the existing ledger admits the sequence. The text is paid for by cutting named sentences, because every instruction ceiling stays where it is.

**Tech stack:** Markdown skill documents, Python 3 standard library `unittest`, the `workflow-state` CLI driven by the existing `LifecycleHarness`, `agent_tools.instruction_load` (the Instruction Budget gate), JSON eval cases.

Spec: `.agents/artifacts/specs/2026-10-10-issue-352-delegated-ship-routing-design.md`. Its sections `### The delegated owner (generic route)`, `### The delegating owner` and `### The Phase-6 gate` are the behaviour; its `## Decision ledger` rows D1–D11 are cited by ID.

## Global Constraints

- No instruction ceiling is raised and `instruction-load.json` changes only the `implementation-owner` profile's `note` (D7). Only the user applies the `instruction-budget-raise` label; never pass `--raise-label`.
- Never edit a gate file: `.github/workflows/instruction-budget.yaml`, `python/agent_tools/skill_lint.py`, `python/agent_tools/instruction_load.py`, `.github/branch-protection.json`.
- `home/common/agent-skills/scripts/workflow-state.py` is not changed (D5). Also unchanged: `rollover.md`, `resume-pack.md`, `acquire-dispatcher.md`, every file under `ship-issue/` and `orchestrate-issues/`, every `<!-- agent-dispatch: … -->` marker line, and every `model-matrix.json` field except the one `call` string Task 2 names (D9).
- The closed prompt line is exactly `Delegated owner: return the ship handoff` (D6). It appears, in backticks, only in `from-issue/SKILL.md` and `from-issue/delegated-owner.md`.
- Skill-text tests pin only machine-consumed strings: argv, boundary names, the closed line, dispatch ids (`docs/standards/agent-helpers.md` rule 6). No new test asserts an English phrase.
- Skill text is dictated byte for byte in Task 2. A reworded sentence changes the byte count: re-run the budget gate after any wording change, including a review fix.
- Commands run from the worktree root, in the foreground. With a `Lifecycle worker:` line in your prompt, wrap each long command in the `launch-scope exec … --` form that line's following sentence gives, and commit through `launch-commit`. Never disable commit signing.
- Focused tests: `PYTHONPATH="$PWD/python" python3 -m unittest <file> -k <pattern>` (timeout 1800 s; the host is often loaded). Budget gate: `just agent-instruction-budget` (timeout 600 s), expected output `check: pass`.
- Final gate, once on the final head (sdd's final gate, not a per-task gate): `just build` (timeout 3600 s) and `just agent-workflow-tests` (timeout 5400 s).

## Test seams

- Ledger, at the `workflow-state` command line: `home/common/agent-skills/tests/test_workflow_state.py`, a new `DelegatedShipLaunchTest(LifecycleHarness, unittest.TestCase)` (spec seam 1).
- Skill text, machine-consumed strings only: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, class `WorkflowSkillContractsTest` (spec seam 2).
- Evals: three `plan-only` cases in `home/common/agent-skills/skills/from-issue/evals/evals.json`, with one contract test that the cases exist (spec seam 3).
- Instruction budget: `just agent-instruction-budget` with no raise label (spec seam 4).

## Delivery estimate and boundaries

Estimates, measured on a scratch prototype of this plan's exact text at `b6776289`: ten changed files outside `.agents/artifacts`; skill corpus +511 bytes against 526 of headroom; after the change the tightest ceiling, `implementation-owner` hot, keeps 11 bytes and the corpus 15. On that prototype `just agent-instruction-budget` printed `check: pass` and `just agent-workflow-tests` ran 2542 tests with no failure (about 48 minutes on a loaded host). One review package.

The margin is small, and sibling issues of the same run may land on `main` first. If `just agent-instruction-budget` fails after a sync merge with `main`, the reserve cut is the parenthesis ` (with lifecycle identity the `ship-handoff/v2` candidate; ledger-free the legacy handoff)` in `SKILL.md`'s `## Phase 7` (90 bytes, pinned by no test, restated in `ship-handoff.md`). If that does not cover it, stop and report: a raise needs the user's label.

Task 2 is one task because the budget balances only with all of its edits applied together. Task 3 depends on Task 2's final text.

## Task index

Task 1 — Ledger tests for a delegated ship launch — `home/common/agent-skills/tests/test_workflow_state.py` — full — [task-1.md](2026-10-10-issue-352-delegated-ship-routing.tasks/task-1.md)
Task 2 — Route the delegated return in the skill text — `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/from-issue/AUTO.md`, `home/common/agent-skills/skills/from-issue/delegated-owner.md`, `home/common/agent-skills/skills/from-issue/ship-handoff.md`, `home/common/agent-skills/model-matrix.json`, `home/common/agent-skills/instruction-load.json`, `home/common/agent-skills/README.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-2.md](2026-10-10-issue-352-delegated-ship-routing.tasks/task-2.md)
Task 3 — Evals for the delegated ship route and the acceptance record — `home/common/agent-skills/skills/from-issue/evals/evals.json`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `.agents/artifacts/plans/2026-10-10-issue-352-delegated-ship-routing.acceptance.md` — full — [task-3.md](2026-10-10-issue-352-delegated-ship-routing.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | evidence | Task 3 | Not measurable in this repository. Command: read the subagent transcripts of the next orchestrated nodocom run. Conditions: that run has ≥ 2 rolled-over issues and uses the deployed skill text. Threshold: 0 hand-backs consisting of `capability_gap: agent_dispatch` (baseline 3 of 3). Task 3 fills acceptance-record row AC1's evidence columns as not measured; the expected verdict is `human_pending`. |
| AC2 | evidence | Task 3 | Not measurable in this repository. Command: mean of `cache_read_input_tokens + cache_creation_input_tokens` per request across the ship agent's transcript. Conditions: the same run as AC1. Threshold: ≤ 200000 tokens (baseline 330–380k inline). Task 3 fills acceptance-record row AC2's evidence columns as not measured; the expected verdict is `human_pending`. |
| AC3 | code | Task 3 | `python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_delegated_return_line -k test_generic_delegated_owner_returns -k test_delegate_action_checks -k test_from_issue_evals_cover` (4 tests pass); `just agent-instruction-budget` prints `check: pass`; evals 5, 6 and 7 each graded once against the worktree's skill text, verdicts in acceptance-record row AC3. Evals 5 and 6 are the cases at orchestrated depth. |
| AC4 | code | Task 1 | `python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k DelegatedShipLaunchTest` (3 tests pass) |

## Standards review provenance

Reviewer: Codex (`plan-review`, isolated read-only, no focus), base SHA `02d2f378ad8c4abbb8e3a3960b4c93b10879bd6b`, no fallback. Blocking 0. Should-fix 2: 1 accepted, 1 rejected, 0 deferred.

- PR-001, accepted (D12): Task 1's finish test drives the production `finish --summary-file` path instead of the legacy `--result-file` transport. Applied as Task 1's review amendment.
- PR-002, rejected: it reported the acceptance record's `Criterion` cells as rewritten. They match the live issue body line for line; the review packet had carried a paraphrase of the criteria, which is what the finding compared against.

## Decisions

- Who launches the ship owner and what is returned: D1, D2. Release, reap and the Phase-6 `progress` call: D3. The direct-autonomous rollover stays: D4. No helper change: D5. The closed line and no second delegation: D6. Ceilings and cuts: D7, as amended by D9. Eval and contract-test shape: D8.
- Appended by this plan: D9 (cuts forced by the live gates, the `model-matrix.json` mirror), D10 (compressed wording, the README as the long form, the frozen `unread` reason), D11 (no red step for the ledger tests, how the evals are graded).

---
