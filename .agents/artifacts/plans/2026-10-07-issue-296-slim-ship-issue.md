# Slim ship-issue Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Restructure `ship-issue` into a `SKILL.md` hub with three route files, cut the helper-enforced, duplicated and rationale text in every document, delete the prose pins on the scoped files, and shrink what each loading profile reads (#296, slice S5 of #291).

**Architecture:** Spec `.agents/artifacts/specs/2026-10-07-issue-296-slim-ship-issue-design.md` (ledger D1–D16; program rows cited as "#291 Dn", precedent rows as "#295 Dn"). The spec's `### Target layout` table is the file map, and its `### Content classes and their disposition` table is the cutting rule. Each task moves or cuts one group of text. In the same commit it re-points the tests that read that text, deletes their prose pins, updates `instruction-load.json` membership and ceilings, and drops the debt keys it clears (per D14). Every commit therefore passes the gate.

**Tech stack:** Markdown skill documents, JSON models (`instruction-load.json`, `skill-lint-debt.json`), Python `unittest`, `agent_tools.skill_lint` / `agent_tools.instruction_load`, the eval harness.

## Global Constraints

- Scope: only `home/common/agent-skills/skills/ship-issue/*.md` (the `evals/` directory excluded), `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/instruction-load.json` (only the `ship-owner`, `orchestrated-issue-owner` and `implementation-owner` member lists, `unread` maps and ceilings, plus `description_ceiling_bytes` and `corpus_ceiling_bytes` as `tighten` sets them), `home/common/agent-skills/skill-lint-debt.json` (only ship-issue keys), this plan's acceptance record, the spec's `### Findings to file` list, and `home/common/agent-skills/evals/results/results.jsonl` (Task 6, token-gated). Never edit other skills, `agents/*.md`, `AGENTS.md`, `model-matrix.json`, helpers, profile `note`s, or the gate files `instruction-budget.yaml`, `skill_lint.py`, `instruction_load.py`, `branch-protection.json` (spec Out of scope; per D9, D13).
- No workflow semantics change: every gate, order, closed set, stop and return shape keeps its meaning (spec Decisions, "No semantic change"). The four rules in the spec's `### Findings to file` are carried over verbatim (per D12): Phase 6's docs-only CI skip, `CI-MERGE.md`'s option "(c) merge without CI if the project allows admin-merge", `SYNC.md`'s `cargo update`, and from-issue's `--no-ff` (out of scope). Any further wrong rule found is appended to that list, not edited.
- Machine-read text stays byte for byte, in the file its check reads after the move (per D7, #291 D6). That covers the four dispatch markers and their `Agent(...)` lines, the resolve paragraph, the `Lifecycle worker:` line and its two `launch-scope` sentences, the vetted shell examples, frontmatter `name`, JSON key sets, helper argv and the closed PR-body and comment lines (spec's Machine-read text row).
- Marker home (per #295 D3): all four markers stay in `SKILL.md` Phase 5, each a whole line with its call on the next line: `ship-issue-merge-delta-review`, `ship-issue-full-conformance-review`, `ship-issue-full-correctness-fallback`, `ship-issue-scoped-fix-rereview`. No other line in `ship-issue/` may contain `Agent(`. No ship-issue file carries a leaf-agent clause.
- `workflow-state build-delivery` is spelled only in `SKILL.md`, in the `## Delivery loop` stub (per D5). Route files say "the builder".
- Hub rule (per D6): only `SKILL.md` names a reference file, through its `## Files beside this one` index. A reference file names `SKILL.md` phases and headings and never a sibling basename. Other skills' files (`from-issue/SKILL.md`, `from-issue/ship-handoff.md`, `from-issue/AUTO.md`) may still be named.
- A reference file over 100 reflowed lines starts with a `## Contents` list before its first other `##` heading (L3). The targets below keep every one under 100.
- Kept anchors (per D4): `## Delivery loop` and `## Remainder mode` (stubs), the Phase-0 reviewer-dispatch probe, Phase 5's range selection, Phase 8 step 1's hold sequence, `## gh hygiene`'s `unset GITHUB_TOKEN && ` sentence, `### Local commits`, the `## Phase 0`–`## Phase 8` headings with their titles, `HUMAN-GATE.md`'s owner-runs-itself case and `## Never route around a denial` (per D11), `REVIEW.md`'s worktree-local retained candidate, and the severity mapping plus fix flow as "ship-issue's auto-mode rules".
- The resolve paragraph (body line starting "Run `resolve-project resolve --repo-root <checkout>`") stays byte for byte (#295 D10).
- Per-file byte targets (spec § Byte and line targets; ceilings, not goals): `SKILL.md` ≤ 22,000 and ≤ 280 reflowed body lines; `DELIVERY-LOOP.md` ≤ 4,500; `POST-SELECTION-SYNC.md` ≤ 4,800; `REMAINDER.md` ≤ 2,600; `SYNC.md` ≤ 2,700; `REVIEW.md` ≤ 5,800; `CONSOLIDATE.md` ≤ 3,300; `CI-MERGE.md` ≤ 3,000; `HUMAN-GATE.md` ≤ 3,800. Each task's size script prints any file over its target. An overshoot is allowed only when every remaining sentence is machine-read or carries meaning, and the commit body then names the file, its size and why. The hard lines are `SKILL.md` ≤ 300 reflowed lines (AC2) and D1's share (AC3).
- Per commit (per D14): run `just agent-instruction-load tighten`. A conditional ceiling that `instruction_load check` reports breached is set to the measure only when text moved there from a hot member in the same commit, and the commit body carries one line per raise: `raise: <profile> on <host> conditional <old> -> <new>`.
- Tests follow D11 and D16: machine-read assertions are re-pointed, prose assertions on scoped files are deleted, assertions on other skills' text in the same method stay, and a method left with no assertion is deleted. No new test pins prose.
- Commands run from the worktree root in the foreground. Focused suite (timeout 600 s): `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/tests/test_eval_cases.py`. Lint (timeout 300 s): `PYTHONPATH=python python3 -m agent_tools.skill_lint check` exits 0. Gate (timeout 300 s): `PYTHONPATH=python python3 -m agent_tools.instruction_load check` prints `check: pass`.
- Final-gate verification, run once by sdd on the final head: `just build` (timeout 3600 s) and `just agent-workflow-tests` (timeout 3600 s).
- No agent applies the `instruction-budget-raise` label, and no step edits `instruction-load.json` to clear the `raise:` line (per D2, #295 D5).

## Test seams

- `skill-lint check` (L1–L5 plus the shrink-only debt file), and `skill_lint.reflowed_lines` over `parse_frontmatter`'s body for the 300-line target (#295 D8).
- `instruction_load` `report`/`check`/`tighten` for membership, closure, ceilings and the share. `LiveModelTest` and `LiveBudgetTest` run them on the working tree.
- The machine-read checks: `test_ship_issue_documents_carry_their_machine_text`, `test_dispatch_contracts`, `test_shell_example_contracts`, `test_agent_model_matrix`, `LIFECYCLE_DOCS`, and the argv, closed-line and key-set tests in `test_workflow_skill_contracts.py`.
- The eval harness (`EVAL_TREE=. just evals ship-issue 5`) for behaviour, gated by D15.

## Delivery estimate and boundaries

Estimate only: about 14 changed paths. That is nine scoped documents (three new), one test file, two JSON models, the acceptance record and the spec. Skill text should fall from 86,869 bytes to about 50,000–55,000. The test file should lose roughly 60–150 lines. One PR, which stops at the label human gate (per D2). If the review package is over its boundary, review Tasks 1–3 and Tasks 4–6 as two passes over the one PR.

## Task index

Task 1 — Split the lifecycle routes into DELIVERY-LOOP.md and REMAINDER.md — home/common/agent-skills/skills/ship-issue/{SKILL.md, DELIVERY-LOOP.md (new), REMAINDER.md (new)}, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json — full — [task-1.md](2026-10-07-issue-296-slim-ship-issue.tasks/task-1.md)
Task 2 — Move the post-selection sync into POST-SELECTION-SYNC.md and cut CI-MERGE.md — home/common/agent-skills/skills/ship-issue/{CI-MERGE.md, REVIEW.md, POST-SELECTION-SYNC.md (new), SKILL.md, DELIVERY-LOOP.md, REMAINDER.md}, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json, home/common/agent-skills/skill-lint-debt.json — full — [task-2.md](2026-10-07-issue-296-slim-ship-issue.tasks/task-2.md)
Task 3 — Cut REVIEW.md, SYNC.md and CONSOLIDATE.md — home/common/agent-skills/skills/ship-issue/{REVIEW.md, SYNC.md, CONSOLIDATE.md}, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json, home/common/agent-skills/skill-lint-debt.json — full — [task-3.md](2026-10-07-issue-296-slim-ship-issue.tasks/task-3.md)
Task 4 — Cut HUMAN-GATE.md to the gates it alone holds — home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json, home/common/agent-skills/skill-lint-debt.json — full — [task-4.md](2026-10-07-issue-296-slim-ship-issue.tasks/task-4.md)
Task 5 — Cut SKILL.md to the hub — home/common/agent-skills/skills/ship-issue/SKILL.md, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json, home/common/agent-skills/skill-lint-debt.json — full — [task-5.md](2026-10-07-issue-296-slim-ship-issue.tasks/task-5.md)
Task 6 — Measure the slice and record acceptance evidence — home/common/agent-skills/instruction-load.json, .agents/artifacts/plans/2026-10-07-issue-296-slim-ship-issue.acceptance.md, home/common/agent-skills/evals/results/results.jsonl (token-gated), home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-6.md](2026-10-07-issue-296-slim-ship-issue.tasks/task-6.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 6 | `PYTHONPATH=python python3 -m agent_tools.skill_lint check` exits 0, `skill-lint-debt.json` holds no `skills/ship-issue/` key, and `just agent-instruction-budget` prints no `lint:` line. That is the `Instruction Budget` job's lint step; its `raise:` line is the D2 human gate |
| AC2 | code | Task 6 | The Task 6 Step 2 command: `skill_lint.reflowed_lines` over `parse_frontmatter(SKILL.md)[1]` prints ≤ 300 (#295 D8; plan target ≤ 280) |
| AC3 | evidence | Task 6 | Command: the Task 6 Step 3 share script over `instruction_load report --format json`, run at base `baac2897f15daab46a4f25ec625b40d384d3573c` and at the Task 6 head. Conditions: profiles `ship-owner`, `orchestrated-issue-owner`, `implementation-owner` over all their hosts, `ship-issue/` members listed hot or conditional (per D1). Threshold: head share ≤ 282,324 (0.65 × 434,345), with the whole-profile total reported beside it. Implementer fills acceptance-record row `AC3` |
| AC4 | evidence | Task 6 | Command: `EVAL_TREE=. EVAL_MODEL=<sonnet|opus> just evals ship-issue 5` (two runs). Conditions: run only when `CLAUDE_CODE_OAUTH_TOKEN` is non-empty (per D15). Threshold: `passed` ≥ 5 on sonnet and ≥ 6 on opus, and no failed assertion other than "the run names the push it would run next". Without the token, row `AC4` records `human_pending — CLAUDE_CODE_OAUTH_TOKEN unset` and the two commands. Implementer fills acceptance-record row `AC4` |
| AC5 | code | Task 6 | `just agent-workflow-tests` on the final head, plus the Task 6 Step 4 audit with the reviewer's attestation that no prose assertion over a scoped file remains |

## Decisions

The spec owns the ledger. This plan cites D1–D15 and adds D16 (each machine-read item is pinned only in its one home).

---

## Standards review provenance

Reviewer: Codex (gpt-6-astra, xhigh), fresh isolated read-only thread; base SHA baac2897f15daab46a4f25ec625b40d384d3573c, plan HEAD ba33302e. No fallback. Findings: 2 Blocking accepted (R1 keep the `check-launch` four-key list in Task 5 step 4; R2 keep the `wt-<worktree-name>` bucket literal in Task 5 step 13), 0 Should fix, 0 Discussion; 0 rejected, 0 deferred. Both were verified against the live `SKILL.md` and `test_workflow_skill_contracts.py`. Neither needed a ledger row, because both restore text the spec's preservation inventory already keeps.
