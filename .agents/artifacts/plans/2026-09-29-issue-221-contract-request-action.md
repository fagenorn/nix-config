# Control asks for a missing delivery contract — Implementation Plan (issue 221)

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** When nothing is live and an issue waits only on its delivery contract, `workflow-state control` returns a `delivery_contract` action naming those issues instead of `finalize`, so `orchestrate-issues` never has to override `finalize`.

**Architecture:** The terminal choice at the end of the `control` sweep in the flat `workflow-state.py` becomes three-way (per D1, D2): `wait` when a deadline is armed, else `delivery_contract` when any requested issue planned `"contract"`, else `finalize`. Admission keeps keying on "no deadline", so a `delivery_contract` sweep behaves like a `finalize` sweep for claims (per D4). The workflow-response validator in `delivery_model/_wire.py` accepts the new kind with its couplings (per D6). `orchestrate-issues` §4 holds the one adapter rule (per D5).

**Tech stack:** Python 3 standard library (`unittest`), the `workflow-state` / `artifact-budget` CLIs, Markdown skill text, JSON evals, Nix (`just build`).

**Spec:** `.agents/artifacts/specs/2026-09-29-issue-221-contract-request-action-design.md` (authoritative; ledger D1–D13).

## Global Constraints

- Control stays at `interface_version` 3; no request or bootstrap change (per D8).
- The action is exactly `{"id": "delivery_contract", "kind": "delivery_contract", "issues": [<int>, …]}`, `issues` in request order (per D1).
- Code changes stay in `home/common/agent-skills/scripts/workflow-state.py` and `home/common/agent-skills/scripts/delivery_model/_wire.py`; nothing moves into `agent_tools`; the Codex `orchestrate-issues` stub and `direct-owner` are untouched (per D7); from-issue's durable interactive route gains one prose sentence and no code (per D12).
- Admission-waiting issues are never listed (per D3).
- Commits are signed (never pass `--no-gpg-sign` / `-c commit.gpgsign=false`) and end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Run single tests from the worktree root as `PYTHONPATH=python python3 -m unittest <test-file-path> -k <name>`; summarize output to the failing lines.

## Test seams

- `workflow-state control` CLI through `ContractLifecycleTest` in `home/common/agent-skills/tests/test_delivery_workflow.py` (T1–T4, T6; per D9, D11).
- `validate_delivery_object(..., "workflow-response")` through the control fixture in `home/common/agent-skills/tests/test_delivery_model.py`, plus `artifact-budget validate-report --boundary workflow-response` on the T1 CLI reply (per D6).
- Skill-text anchors in `WorkflowSkillContractsTest` in `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (T5), and the live instruction-load ceiling in `test_instruction_load.py` (per D10).

## Delivery estimate and boundaries

Estimate: 9 changed files, roughly +15 lines in `workflow-state.py`, +15 in `_wire.py`, +110 test lines across three test files, about +1.1 KB of SKILL.md prose, two eval enumerations, one ceiling value. One deliverable slice; no review-package boundary risk expected. Tasks run in order 1 → 2 → 3 (Task 2's end-to-end test reuses Task 1's helper).

## Task index

Task 1 — Control returns `delivery_contract` instead of `finalize` — home/common/agent-skills/scripts/workflow-state.py, home/common/agent-skills/tests/test_delivery_workflow.py — full — [task-1.md](2026-09-29-issue-221-contract-request-action.tasks/task-1.md)
Task 2 — Workflow-response validator accepts the coupled `delivery_contract` — home/common/agent-skills/scripts/delivery_model/_wire.py, home/common/agent-skills/tests/test_delivery_model.py, home/common/agent-skills/tests/test_delivery_workflow.py — full — [task-2.md](2026-09-29-issue-221-contract-request-action.tasks/task-2.md)
Task 3 — `orchestrate-issues` states the one rule; evals and ceiling follow — home/common/claude-code/skills/orchestrate-issues/SKILL.md, home/common/claude-code/skills/orchestrate-issues/evals/evals.json, home/common/agent-skills/skills/from-issue/SKILL.md, home/common/agent-skills/instruction-load.json, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-3.md](2026-09-29-issue-221-contract-request-action.tasks/task-3.md)

## Decisions

Tasks cite the spec's ledger: D1–D9 (design), D10 (instruction-load ceiling raise) and D11 (T1 fixture shape and task order) appended by planning; D12 (durable interactive consumer) and D13 (falsifiable guards) appended by the Phase-5 review.

## Final verification (after Task 3)

- `just agent-workflow-tests 2>&1 | tail -5` — expect `OK`.
- `just build 2>&1 | tail -3` — expect success.
- Scoped diff: `git diff --stat 93bf5fd..HEAD -- home/common/agent-skills/scripts home/common/agent-skills/tests home/common/claude-code/skills/orchestrate-issues home/common/agent-skills/instruction-load.json home/common/agent-skills/skills/from-issue home/common/codex` — expect only the nine files in the Task index, and nothing under `home/common/codex`.

## Standards review provenance

- Reviewer: Claude fallback (native `reviewer`, Opus/high, isolated, read-only), against base `93bf5fd2cdff5bb6ca347dc38a14767ebd6d4176`, plan HEAD `40551f9`. Fallback reason: the configured Codex `plan-review` run completed but its JSONL carried no runtime-selection event naming the selected model/effort and more than one agent message, so it failed metadata validation; its output was not used as a verdict (its two Should-fix items coincided with SF-2 and SF-4 below).
- Blocking: none. Should fix: 4 accepted — SF-1 durable interactive consumer (Task 3, per D12), SF-2 order/last-position guards made falsifiable (Task 2, per D13), SF-3 held controller claim released on a `delivery_contract` sweep (Task 1 T7, per D13), SF-4 stale `finalized`/suspension prose (Task 3).
- Discussion: 2 accepted (D-1 §3 sentence antecedent; D-5 compute `contract_requests` once), 5 deferred as out of scope or harmless — D-2 control-call trigger list (§4's rule already says to call at once; facts are re-observed per §2 as for every call), D-3 eval rule grading (spec asks only for the enumeration), D-4 adjacent `finalize`-closed harnesses (green today; no scenario there yields the new kind), D-6 T2 source reference (the builder's reference does not affect the spawn assertion), D-7 old wait observer (per D2, harmless).
