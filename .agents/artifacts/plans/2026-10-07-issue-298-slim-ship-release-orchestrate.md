# Slim ship-release and orchestrate-issues Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Cut `ship-release` (`SKILL.md`, `CHANGELOG.md`), the Claude `orchestrate-issues` adapter and the Codex `orchestrate-issues` stub to the skill best-practices checklist in place, delete their prose pins and debt keys, and drop the hot plus conditional load of their profiles by at least 20 % (#298, slice S7 of #291).

**Architecture:** Spec `.agents/artifacts/specs/2026-10-07-issue-298-slim-ship-release-orchestrate-design.md` (ledger D1–D14; program rows cited as "#291 Dn", precedent as "#295 Dn"). Its `### Content classes and their disposition` table is the cutting rule and its `## Decisions` list is the keep-byte-for-byte list. No file is added or moved (per D1). Each of Tasks 1–4 cuts one document. In the same commit it deletes that document's prose pins, removes its debt key and runs `tighten` (per D2), so every commit passes the gate. Task 5 measures and records acceptance.

**Tech stack:** Markdown skill documents, JSON models (`instruction-load.json`, `skill-lint-debt.json`), Python `unittest`, `agent_tools.skill_lint` / `agent_tools.instruction_load`, the eval harness.

## Global Constraints

- Scope: only `home/common/agent-skills/skills/ship-release/{SKILL.md,CHANGELOG.md}`, `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, `home/common/codex/skills/orchestrate-issues/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/tests/test_ship_release_contracts.py`, `home/common/agent-skills/instruction-load.json` (via `tighten` only, per D2), `home/common/agent-skills/skill-lint-debt.json`, this plan's acceptance record, the spec's `### Findings to file` list, and `home/common/agent-skills/evals/results/results.jsonl` (Task 5, token-gated). Never edit evals directories, other skills, `agents/*.md`, `AGENTS.md`, `CLAUDE.md`, `model-matrix.json`, helpers, the lifecycle guard, or the gate files `instruction-budget.yaml`, `skill_lint.py`, `instruction_load.py` (spec Out of scope; per D6).
- `instruction-load.json` is written only by `just agent-instruction-load tighten`: no hand edit, no profile `note` edit, no membership change (per D2). `just agent-instruction-budget` must pass with no label; no agent applies `instruction-budget-raise`.
- No workflow semantics change (spec Decisions, "No semantic change"). Every pause condition, resume path, closed set, order and stop keeps its meaning. A rule that is wrong rather than wordy is not edited: append it to the spec's `### Findings to file` (per D11). The three findings already listed stay unedited in the skill text.
- Machine-read text stays byte for byte, in its current file (spec Decisions; per D4, #291 D6): dispatch markers and their whole `Agent(...)` lines, the orchestrate owner-prompt blockquote whole, every fenced command, every inline command span the shell-example sweep vets, the durable-state JSON, the §3 control-request JSON, the `build-delivery` input JSON, the owner-dispatch envelope fence, every helper argv, every `ORCHESTRATE_MACHINE_TEXT` token, both resolve paragraphs (orchestrate's includes the `build-delivery` exception sentence, per D12), and frontmatter except `description` (per D8). No other line in a scoped file may contain `Agent(`.
- Cited anchors keep their text and file (per D4): orchestrate's `## 1.`–`## 5.` headings, `**Per-issue contract rule.**`, §4's `delivery_contract` rule, the owner-object projection, the resume-pack step and `**Stop pass.**` with its sweep; ship-release's `## Durable release state` and `### 4.5d. Decide MAJOR / MINOR / PATCH`; CHANGELOG's `## Version bump signals`; ship-release's citation of `worktrees/SKILL.md`, `## Shell forms the isolation checker refuses`.
- Per-file ceilings (per D3, "ceilings, not goals"): ship-release `SKILL.md` ≤ 20,500 B and ≤ 380 reflowed body lines; `CHANGELOG.md` ≤ 7,500 B with `## Contents`; Claude orchestrate `SKILL.md` ≤ 24,000 B and ≤ 430 reflowed body lines; Codex stub ≤ 1,035 B. Hard lines: every scoped `SKILL.md` ≤ 500 reflowed body lines (AC2); ship-release `SKILL.md` + `CHANGELOG.md` ≤ 29,890 B (the spec's binding constraint); the AC3 total ≤ 214,180 B. An overshoot of a soft ceiling is allowed only when every remaining sentence is machine-read or carries meaning; the commit body then names the file, its size and why.
- Combined description bytes of the three skills ≤ 511 B (per D8); the three texts are given in Tasks 1, 3 and 4.
- Per commit (per D2): delete the debt key the commit clears, then run `just agent-instruction-load tighten` (timeout 300 s). After every sync with the integration branch, re-run `tighten` and the Task 5 measure (per D13).
- Tests follow D10 and D14: delete prose pins, keep machine-read checks, drop scoped files from multi-file prose corpora without deleting other slices' assertions. A method left with no assertion is deleted. No new test pins prose.
- Commands run from the worktree root in the foreground. Focused suite (timeout 900 s): `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_ship_release_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/tests/test_eval_cases.py` (326 tests OK at base). Gates (timeout 300 s each): `PYTHONPATH=python python3 -m agent_tools.skill_lint check` exits 0; `PYTHONPATH=python python3 -m agent_tools.instruction_load check` prints `check: pass`.
- Final-gate verification, run once by sdd on the final head: `just build` (timeout 3600 s) and `just agent-workflow-tests` (timeout 3600 s).
- No forge write (issue, PR, label or comment) from any task.

## Test seams

- `skill-lint check` (L1–L5 plus the shrink-only debt file) and `skill_lint.reflowed_lines` over `skill_lint.parse_frontmatter(text)[1]` for body length.
- `instruction_load` `report` / `check` / `tighten` for the measure, ceilings and closure; `just agent-instruction-budget` for label-free raise control.
- The machine-read checks: `test_dispatch_contracts`, `test_shell_example_contracts`, `test_agent_model_matrix`, `test_ship_release_contracts`, the kept `test_workflow_skill_contracts` checks and `test_instruction_load`'s live tree.
- The eval harness (`EVAL_TREE=. just evals <skill> <id>`) for behaviour, gated by D9.

## Delivery estimate and boundaries

Estimate only: 8 changed paths plus the acceptance record — four scoped documents, two test files, two JSON models. Scoped text should fall from 72,353 B to about 52,000 B (ship-release about 28,000 B together, orchestrate about 24,000 B). The test files should lose about 20–40 lines. AC3's head should land near 206,620 B against the 214,180 B threshold. One PR, no label and no human gate before merge (per D2); the eval rows may hold the issue as `needs-verification` (per D9). Growth risk: none expected, because every task only deletes text; the description ceiling is shared with parallel slices, so `tighten` re-runs after each sync.

## Task index

Task 1 — Cut ship-release SKILL.md — home/common/agent-skills/skills/ship-release/SKILL.md, home/common/agent-skills/tests/test_ship_release_contracts.py, home/common/agent-skills/instruction-load.json, home/common/agent-skills/skill-lint-debt.json — full — [task-1.md](2026-10-07-issue-298-slim-ship-release-orchestrate.tasks/task-1.md)
Task 2 — Cut ship-release CHANGELOG.md and add its Contents — home/common/agent-skills/skills/ship-release/CHANGELOG.md, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json, home/common/agent-skills/skill-lint-debt.json — full — [task-2.md](2026-10-07-issue-298-slim-ship-release-orchestrate.tasks/task-2.md)
Task 3 — Cut the Claude orchestrate-issues SKILL.md and delete its prose pins — home/common/claude-code/skills/orchestrate-issues/SKILL.md, home/common/agent-skills/tests/test_workflow_skill_contracts.py, home/common/agent-skills/instruction-load.json, home/common/agent-skills/skill-lint-debt.json — full — [task-3.md](2026-10-07-issue-298-slim-ship-release-orchestrate.tasks/task-3.md)
Task 4 — Give the Codex orchestrate-issues stub a third-person trigger description — home/common/codex/skills/orchestrate-issues/SKILL.md, home/common/agent-skills/instruction-load.json, home/common/agent-skills/skill-lint-debt.json — low-risk — [task-4.md](2026-10-07-issue-298-slim-ship-release-orchestrate.tasks/task-4.md)
Task 5 — Measure the slice, run the gated evals and record acceptance — .agents/artifacts/plans/2026-10-07-issue-298-slim-ship-release-orchestrate.acceptance.md, home/common/agent-skills/instruction-load.json (tighten only), home/common/agent-skills/evals/results/results.jsonl (token-gated) — full — [task-5.md](2026-10-07-issue-298-slim-ship-release-orchestrate.tasks/task-5.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 5 | `PYTHONPATH=python python3 -m agent_tools.skill_lint check` exits 0; `skill-lint-debt.json` holds none of the four keys `L2 …/ship-release/SKILL.md`, `L2 …/orchestrate-issues/SKILL.md`, `L3 …/ship-release/CHANGELOG.md`, `L5 …/codex/skills/orchestrate-issues/SKILL.md`; `just agent-instruction-budget` exits 0 with no `lint:` line (the `Instruction Budget` job) |
| AC2 | code | Task 5 | The Task 5 Step 2 script: `skill_lint.reflowed_lines` over each scoped `SKILL.md` body prints ≤ 500 for all three (plan ceilings 380 and 430), and `skill_lint check` reports no L2 for them |
| AC3 | evidence | Task 5 | Command: the Task 5 Step 3 sum over `PYTHONPATH=python python3 -m agent_tools.instruction_load report --base 75784bed116805ee948d6e2f7f45a6d0ad3b4212 --head HEAD --format json`. Conditions: profiles `orchestration-dispatcher`, `release-owner`, `ship-release`, every host, hot plus conditional bytes; base fixed at `75784bed` (per D3, D13). Threshold: base 267,725 and head ≤ 214,180. Implementer fills acceptance-record row `AC3` |
| AC4 | evidence | Task 5 | Command: `EVAL_TREE=. EVAL_MODEL=<sonnet|opus> just evals ship-release 5` and `EVAL_TREE=. EVAL_MODEL=<sonnet|opus> just evals orchestrate-issues 7` (four runs). Conditions: run only when `CLAUDE_CODE_OAUTH_TOKEN` is non-empty (per D9). Threshold: `passed` ≥ 5 on every run (the S3 baseline, 5/5 per case and model). Without the token, row `AC4` records `not run — CLAUDE_CODE_OAUTH_TOKEN unset` and the four commands. Implementer fills acceptance-record row `AC4` |
| AC5 | code | Task 5 | `just agent-workflow-tests` on the final head, plus the Task 5 Step 4 inventory with the reviewer's attestation that no prose assertion over a scoped file remains |

## Decisions

The spec owns the ledger. This plan cites D1–D12 and adds D13 (AC3's base stays fixed at `75784bed` across syncs) and D14 (the stdin-commands test keeps its English forbidden phrases only for out-of-scope paths).

---
