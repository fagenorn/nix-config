# Instruction Growth Gate Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Make agent-instruction growth a human decision: a required `Instruction Budget` check that lints the authored skill trees, holds every instruction ceiling tight, and demands the `instruction-budget-raise` label for any raise or gate edit (#292, slice S1 of #291).

**Architecture:** A new `agent_tools.skill_lint` module owns the skill-tree knowledge (snapshot seam, matcher, frontmatter, classification) and the L1–L5 rules with a shrink-only debt file. `agent_tools.instruction_load` imports it, gains conditional/corpus/description ceilings and the `check`/`tighten` subcommands. A new workflow runs `check` against `HEAD^1` on pull requests. The protection payload then requires it beside `Nix Eval` with `strict: true`. Spec: `.agents/artifacts/specs/2026-10-07-issue-292-instruction-growth-gate-design.md` (ledger D1–D19). Program spec: `.agents/artifacts/specs/2026-10-07-issue-291-skill-best-practices-design.md` (read-only; its rows are "program Dn").

**Tech stack:** Python 3 standard library only (`unittest`, `argparse`, `dataclasses`, `json`, `subprocess`), GitHub Actions YAML, `just`, Nix (command table only).

## Global Constraints

- Standard library only; no PyYAML or other dependency (per D12).
- Every strict JSON load uses `reject_duplicate_keys` / `reject_nonfinite_literal` from `agent_tools.canonical` (docs/standards/agent-helpers.md rule 4).
- `home/common/agent-skills/instruction-load.json` is always written as `json.dumps(model, indent=2, ensure_ascii=False) + "\n"`.
- Parser `prog` values: `skill-lint` for `agent_tools.skill_lint`, `agent-instruction-load` for `agent_tools.instruction_load` (unchanged).
- `report`'s output and its existing tests are unchanged (spec "Out of scope").
- No edit to any skill document, `home/common/agent-guidance/AGENTS.md` or `home/common/claude-code/agents/*.md`. L1–L5 debt is recorded, never fixed (per D6, program D8).
- No step applies live branch protection, creates or applies a label, or makes any other forge write (per D2).
- Test commands run from the worktree root as `PYTHONPATH=python python3 -m unittest <file>`, in the foreground with a timeout of at least 300 s.
- Final-gate verification, run once by sdd on the final head and not per task: `just build` (timeout 3600 s) and `just agent-workflow-tests` (timeout 3600 s).

## Test seams

- The snapshot seam (per D15): `skill_lint.Snapshot(read, list_files)`. Tests build it from one `dict` with `dict_snapshot(files)`; the live tree uses `skill_lint.working_tree(root)`; a revision uses `instruction_load.revision_snapshot(root, rev)`.
- `home/common/agent-skills/tests/test_skill_lint.py` (new): fixture trees per rule, debt cases, CLI exit codes, one live-tree test.
- `home/common/agent-skills/tests/test_instruction_load.py` (extended): two in-memory snapshots drive `run_check`; one temporary git repository drives the `check`/`tighten` CLI; live tests.
- `tests/test_branch_protection.py` (rewritten): the indentation parser over every workflow, plus the exact protection payload.

## Delivery estimate and boundaries

Estimate only: 14 changed files (3 created modules/data, 1 workflow, 4 tests, justfile, nix table, protection JSON, ci.yaml, 2 docs, CLAUDE.md). Roughly 1,600–2,100 added lines, about 60% tests. The live debt file holds about 37 keys (L2×3, L3×16, L4b×13, L5×5 by a planning prototype; the implementer regenerates them). One slice. The tool tasks (1–4) cannot ship without the workflow (5), because the workflow is what makes them required. If a review package is over its boundary, review Tasks 1–4 and 5–6 as two passes over one PR. Do not split the PR.

## Task index

Task 1 — skill_lint foundation: snapshot seam, matcher move, frontmatter, reflow, classification — python/agent_tools/skill_lint.py, python/agent_tools/instruction_load.py, home/common/agent-skills/tests/test_skill_lint.py, justfile — low-risk — [task-1.md](2026-10-07-issue-292-instruction-growth-gate.tasks/task-1.md)
Task 2 — L1–L5 rules, debt file and the `skill-lint` command — python/agent_tools/skill_lint.py, home/common/agent-skills/skill-lint-debt.json, home/common/agent-skills/tests/test_skill_lint.py, lib/agent-tools.nix — full — [task-2.md](2026-10-07-issue-292-instruction-growth-gate.tasks/task-2.md)
Task 3 — Conditional, corpus and description ceilings — python/agent_tools/instruction_load.py, home/common/agent-skills/instruction-load.json, home/common/agent-skills/tests/test_instruction_load.py — full — [task-3.md](2026-10-07-issue-292-instruction-growth-gate.tasks/task-3.md)
Task 4 — `check` and `tighten`, and `just agent-instruction-budget` — python/agent_tools/instruction_load.py, home/common/agent-skills/tests/test_instruction_load.py, justfile — full — [task-4.md](2026-10-07-issue-292-instruction-growth-gate.tasks/task-4.md)
Task 5 — Instruction Budget workflow and the protection payload — .github/workflows/instruction-budget.yaml, .github/branch-protection.json, .github/workflows/ci.yaml, tests/test_branch_protection.py, justfile — full — [task-5.md](2026-10-07-issue-292-instruction-growth-gate.tasks/task-5.md)
Task 6 — Test policy, CLAUDE.md mentions, final tighten and budget check — docs/standards/agent-helpers.md, docs/standards/README.md, CLAUDE.md, home/common/agent-skills/instruction-load.json — full — [task-6.md](2026-10-07-issue-292-instruction-growth-gate.tasks/task-6.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 2 | `RuleTest`, `DebtTest`, `CommandTest` and `LiveTreeTest` in `home/common/agent-skills/tests/test_skill_lint.py` under `just agent-workflow-tests` |
| AC2 | code | Task 4 | `CheckTest.test_each_raise_fails_unlabelled_and_passes_labelled` and `CheckTest.test_a_grown_debt_file_fails_with_and_without_the_label` in `test_instruction_load.py` |
| AC3 | code | Task 4 | `CheckTest.test_a_loose_ceiling_fails_and_tighten_fixes_it_without_raising` and `CheckTest.test_a_breach_survives_tighten` in `test_instruction_load.py` |
| AC4 | code | Task 5 | `ProtectionPayload` and `BudgetWorkflowShape` in `tests/test_branch_protection.py` |
| AC5 | evidence | Task 6 | `just show-protection`, run by the user after the user runs `just protect-main` once this PR has merged (D2). Threshold: the output contains `Instruction Budget` and `"strict": true`. Task 6's implementer writes acceptance-record row AC5 as `remaining — user-run after merge (D2)`. The ship handoff carries it as remaining evidence. |
| AC6 | code | Task 6 | The `Instruction Budget` job green on this PR. Locally: `PYTHONPATH=python python3 -m agent_tools.instruction_load check --base origin/main` exits 0 (`LiveBudgetTest` in `test_instruction_load.py`) |

## Decisions

Tasks rest on spec ledger rows: Task 1 per D3, D11, D12, D15, D17; Task 2 per D5, D6, D11, D12, D17; Task 3 per D3, D4, D16; Task 4 per D1, D7, D8, D9, D16, D18, D19; Task 5 per D2, D10, D14; Task 6 per D1, D2, D7, D13. Rows D15–D19 were appended to the spec's ledger during planning.
