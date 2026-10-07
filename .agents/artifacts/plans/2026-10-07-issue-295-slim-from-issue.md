# Slim from-issue Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Restructure `from-issue` into a `SKILL.md` hub with per-route and per-phase reference files, cut helper-enforced, duplicated and rationale text, delete the prose pins on the scoped files, and shrink what each loading profile reads (#295, slice S4 of #291).

**Architecture:** Spec `.agents/artifacts/specs/2026-10-07-issue-295-slim-from-issue-design.md` (ledger D1–D14; program rows cited as "#291 Dn"). The spec's `### Target layout` table is the file map, and its `### Content classes and their disposition` table is the cutting rule. Each task moves or cuts one group of text. In the same commit it re-points the tests that read that text, deletes their prose pins, updates `instruction-load.json` membership and ceilings, and drops any debt keys it clears (per D12). Every commit therefore passes the gate.

**Tech stack:** Markdown skill documents, JSON models (`instruction-load.json`, `skill-lint-debt.json`), Python `unittest`, `agent_tools.skill_lint` / `agent_tools.instruction_load`, the eval harness.

## Global Constraints

- Scope: only `home/common/agent-skills/skills/from-issue/*.md` (the evals directory excluded), `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/instruction-load.json`, `home/common/agent-skills/skill-lint-debt.json`, this plan's acceptance record, the spec's `### Findings to file` list, and `home/common/agent-skills/evals/results/results.jsonl` (Task 7, token-gated). Never edit other skills, `agents/*.md`, `AGENTS.md`, `model-matrix.json`, helpers, or the gate files `instruction-budget.yaml`, `skill_lint.py`, `instruction_load.py`, `branch-protection.json` (spec Out of scope; per D7, D8).
- No workflow semantics change: every gate, order, closed set and stop keeps its meaning (spec Decisions, "No semantic change"). A rule that is wrong rather than wordy is not edited. Append it to the spec's `### Findings to file` instead (per D7).
- Machine-read text stays byte for byte, in the file its check reads (per D3, #291 D6). That covers dispatch markers and their `Agent(...)` lines (each whole line, matrix-recorded), the leaf-agent clauses, the `Lifecycle worker:` line and its two sentences, vetted shell examples, frontmatter, JSON key sets and helper argv. No other line in `from-issue/` may contain the text `Agent(`, because `agent_model_matrix` rejects any unmarked call line.
- Marker homes are fixed (per D3). `SKILL.md`: `from-issue-phase-delegate`, `from-issue-ledger-remainder`, `from-issue-mechanical-implementation`, `from-issue-mechanical-review`, `from-issue-ship-owner`. `AUTO.md`: `from-issue-design-grill`, `from-issue-planning`. `standards-review.md`: `from-issue-plan-review`. `ship-handoff.md`: `from-issue-inline-ship-review`.
- Hub rule (spec Decisions): only `SKILL.md` names a reference file. A reference file names `SKILL.md` sections by heading and never names a sibling, though `REVIEW-CONTRACT.md` may be named because it is a payload. `AUTO.md` keeps naming `REVIEW-CONTRACT.md`, because the planning-owner profile loads it through `AUTO.md`.
- Every new file uses labeled fences (`json`, `text`) only. `SKILL.md` keeps exactly one unlabeled fence, the `## The flow` diagram. `ship-handoff.md` keeps exactly one, the ship-owner prompt. No other from-issue file may have exactly one unlabeled fence.
- A file over 100 reflowed lines starts with a `## Contents` list before its first other `##` heading (L3).
- Kept headings and anchors stay true (per D9, spec Decisions): `Lifecycle identity`, `Decision ledger (artifact discipline)`, `Skill-tool invocations`, `Dispatch, phase-budget and attempt-budget rules`, `Terminal return procedure`, `Suspension procedure`, every `## Phase <n>` heading and a `### Resume pack` stub stay in `SKILL.md`. So do `**Writing workers.**` and the lifecycle-call rule. `AUTO.md` keeps the Phase-0 fog gate and ends on its push/PR/merge human-gate paragraph. `ship-handoff.md` keeps `## Remainder owner prompt`.
- `SKILL.md`'s resolve paragraph (body line 1, starting "Run `resolve-project resolve`") stays byte for byte (per D10).
- Per-file byte targets (spec § Byte and line targets, "ceiling not goal"): `SKILL.md` ≤ 21,000 bytes and ≤ 280 reflowed body lines; `AUTO.md` ≤ 8,500; `rollover.md` ≤ 3,800; `delegated-owner.md` ≤ 3,000; `acquire-dispatcher.md` ≤ 1,500; `acquire-direct.md` ≤ 5,500; `acquire-interactive.md` ≤ 1,000; `acquire-durable.md` ≤ 2,000; `resume-pack.md` ≤ 2,400; `ship-handoff.md` ≤ 11,000; `investigate.md` ≤ 3,800; `standards-review.md` ≤ 3,200; `REVIEW-CONTRACT.md` ≤ 6,800; `decision-ledger.md` ≤ 950. Each task's size script prints any file over its target. An overshoot is allowed only when every remaining sentence is machine-read or carries meaning, and the commit body then names the file, its size and why. The hard lines are `SKILL.md` ≤ 300 reflowed lines (AC2) and D1's share (AC3).
- Per commit (per D12): `just agent-instruction-load tighten`. Any conditional ceiling that `instruction_load check` reports as breached is set to the measure, and only when text moved there from a hot member in the same commit. The commit body then carries one line per raise: `raise: <profile> on <host> conditional <old> -> <new>; hot <old> -> <new>`.
- Tests follow D11 and D13: prose assertions are deleted, machine-read assertions are re-pointed, and heading slices follow their heading. An ordered assertion keeps its argv, JSON, closed-value and heading anchors and loses its English anchors; one left with a single anchor becomes `assertIn`. A method left with no assertion is deleted. No new test pins prose.
- Commands run from the worktree root in the foreground. Focused suite (timeout 600 s): `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/tests/test_eval_cases.py`. Gate (timeout 300 s): `PYTHONPATH=python python3 -m agent_tools.instruction_load check` prints `check: pass`.
- Final-gate verification, run once by sdd on the final head: `just build` (timeout 3600 s) and `just agent-workflow-tests` (timeout 3600 s).
- No agent applies the `instruction-budget-raise` label or edits around the `raise:` line (per D5).

## Test seams

- `skill-lint check` (L1–L5 plus the shrink-only debt file) and `skill_lint.reflowed_lines` over `parse_frontmatter`'s body for the 300-line target (per D8).
- `instruction_load` `report`/`check`/`tighten` for membership, closure and ceilings. `LiveModelTest` and `LiveBudgetTest` run them on the working tree.
- The machine-read checks: `test_dispatch_contracts`, `test_shell_example_contracts`, `test_agent_model_matrix`, and the JSON key-set and argv tests in `test_workflow_skill_contracts.py`.
- The eval harness (`EVAL_TREE=. just evals from-issue <id>`) for behaviour, gated by D6.

## Delivery estimate and boundaries

Estimate only: about 21 changed paths. That is nine scoped documents (two deleted), seven new route and phase files, one test file, two JSON models and the acceptance record. Skill text should fall from 113,396 bytes to about 75,000–80,000 bytes. The test file should lose roughly 1,500–2,500 lines, most of them deleted prose pins. One PR, which stops at the label human gate (per D5). If the review package is over its boundary, review Tasks 1–3 and Tasks 4–7 as two passes over the one PR.

## Task index

Task 1 — Delete bindings.md and grounding.md; cut the per-file policy-support sentences — home/common/agent-skills/skills/from-issue/{bindings.md (delete), grounding.md (delete), SKILL.md, AUTO.md, investigate.md, standards-review.md, ship-handoff.md, REVIEW-CONTRACT.md}, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json, home/common/agent-skills/skill-lint-debt.json — full — [task-1.md](2026-10-07-issue-295-slim-from-issue.tasks/task-1.md)
Task 2 — Split the Phase-5 rollover out of AUTO.md and cut AUTO.md — home/common/agent-skills/skills/from-issue/{AUTO.md, rollover.md (new), delegated-owner.md (new), SKILL.md}, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json, home/common/agent-skills/skill-lint-debt.json — full — [task-2.md](2026-10-07-issue-295-slim-from-issue.tasks/task-2.md)
Task 3 — Move the four acquisition routes and the resume pack into route files — home/common/agent-skills/skills/from-issue/{SKILL.md, AUTO.md, acquire-dispatcher.md (new), acquire-direct.md (new), acquire-interactive.md (new), acquire-durable.md (new), resume-pack.md (new)}, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json — full — [task-3.md](2026-10-07-issue-295-slim-from-issue.tasks/task-3.md)
Task 4 — Move Phase-0 inspection and Phase-7 report handling; cut investigate.md and ship-handoff.md — home/common/agent-skills/skills/from-issue/{SKILL.md, investigate.md, ship-handoff.md}, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json, home/common/agent-skills/skill-lint-debt.json — full — [task-4.md](2026-10-07-issue-295-slim-from-issue.tasks/task-4.md)
Task 5 — Give the Phase-5 gates one home; cut standards-review.md, REVIEW-CONTRACT.md and decision-ledger.md — home/common/agent-skills/skills/from-issue/{standards-review.md, REVIEW-CONTRACT.md, decision-ledger.md, SKILL.md}, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json, home/common/agent-skills/skill-lint-debt.json — full — [task-5.md](2026-10-07-issue-295-slim-from-issue.tasks/task-5.md)
Task 6 — Cut SKILL.md to the hub — home/common/agent-skills/skills/from-issue/SKILL.md, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json, home/common/agent-skills/skill-lint-debt.json — full — [task-6.md](2026-10-07-issue-295-slim-from-issue.tasks/task-6.md)
Task 7 — Reconcile profile notes, measure the slice and record acceptance evidence — home/common/agent-skills/instruction-load.json, .agents/artifacts/plans/2026-10-07-issue-295-slim-from-issue.acceptance.md, home/common/agent-skills/evals/results/results.jsonl (token-gated) — full — [task-7.md](2026-10-07-issue-295-slim-from-issue.tasks/task-7.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 7 | `PYTHONPATH=python python3 -m agent_tools.skill_lint check` exits 0, `skill-lint-debt.json` holds no `skills/from-issue/` key, and `just agent-instruction-budget` prints no `lint:` line. That is the `Instruction Budget` job's lint step; its single `raise:` line is the D5 human gate |
| AC2 | code | Task 7 | The Task 7 Step 2 command: `skill_lint.reflowed_lines` over `parse_frontmatter(SKILL.md)[1]` prints ≤ 300 (per D8; plan target ≤ 280) |
| AC3 | evidence | Task 7 | Command: the Task 7 Step 3 share script over `instruction_load report --format json`, run at base `a891b08cc4d1599c71e7802ba49ec5da07631132` and at the Task 7 head. Conditions: the five profiles C, O, I, P, R over all their hosts, `from-issue/` members listed hot or conditional (per D1). Threshold: head share ≤ 350,998 (0.65 × 539,997), with the whole-profile total reported beside it. Implementer fills acceptance-record row `AC3` |
| AC4 | evidence | Task 7 | Command: `EVAL_TREE=. EVAL_MODEL=<sonnet|opus> just evals from-issue <1|2|3>` (six runs). Conditions: run only when `CLAUDE_CODE_OAUTH_TOKEN` is non-empty (per D6). Threshold: `passed` ≥ the S3 baseline per case and model (case 1: 9 sonnet, 9 opus; case 2: 4 sonnet, 3 opus; case 3: 5 sonnet, 5 opus). Without the token, row `AC4` records `not run — CLAUDE_CODE_OAUTH_TOKEN unset` and the six commands. Implementer fills acceptance-record row `AC4` |
| AC5 | code | Task 7 | `just agent-workflow-tests` on the final head, plus the Task 7 Step 4 audit with the reviewer's attestation that no prose assertion over a scoped file remains |

## Decisions

The spec owns the ledger. This plan cites D1–D11 and adds D12 (each task keeps the gate green at its own commit), D13 (a test that also pins other skills loses only its scoped-file prose) and D14 (`REVIEW-CONTRACT.md` keeps its no-resolve clause).

---

## Standards review provenance

- Reviewer: Codex (`codex-companion task --fresh --reviewer plan-review`, gpt-6-astra, xhigh), isolated and read-only, no fallback.
- Base SHA: a891b08cc4d1599c71e7802ba49ec5da07631132.
- Findings: 1 Blocking, 2 Should fix, 0 Discussion. Accepted 3, rejected 0, deferred 0.
  - R1 (Blocking): Task 3's resume-pack `AUTO.md` scoping now keeps the shared sections at every phase (per D15).
  - R2 (Should fix): the `AUTO.md` "fresh owner resolves once" sentence is cut in Task 1, so Task 1's Step 6 passes on its own.
  - R3 (Should fix): Task 7's AC5 inventory counts indirect readers (`LIFECYCLE_DOCS` and aliases), and the stdin-commands loop keeps its English forbidden phrases only for out-of-scope paths.
- The reviewer could not reach `api.github.com`; the issue criteria were supplied in the packet.
