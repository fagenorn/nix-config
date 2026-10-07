# Typed, Located Acceptance Criteria Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Every issue criterion carries a kind and a measurement place at authoring, every plan maps each criterion to one owning task and check, and plan review blocks a plan whose map has a gap (#274, slice S3 of the acceptance-criteria gate).

**Architecture:** Skill-text changes in `to-issues`, `writing-plans` and the Phase-5 `REVIEW-CONTRACT.md`, pinned by phrase-level contract tests; one eval-grading helper in `assert-lib.sh` used by the two evals that plan from fixture issue 001, unit-tested by sourcing the real library; one literal dispatch-marker count pin. Spec: `.agents/artifacts/specs/2026-10-07-issue-274-typed-located-criteria-design.md` (ledger D1–D10); parent: `.agents/artifacts/specs/2026-10-06-acceptance-criteria-gate-design.md` (read-only).

**Tech stack:** Markdown skill text, JSON eval definitions, POSIX/BSD-compatible bash + awk (`assert-lib.sh`), Python 3 standard-library `unittest`.

## Global Constraints

- No file under `home/common/agent-skills/skills/sdd/` is touched; `acceptance_state`, `tracker_held` and the acceptance record's file and columns stay out (S1 #272, S2 #273).
- No new `<!-- agent-dispatch:` marker anywhere (the total stays 39, per D8).
- Fixtures `002-fuzzy.md` and `003-mechanical.md` and the parent spec are not edited (per D6).
- New tests are new `TestCase` classes appended immediately before the `if __name__ == "__main__":` line of the named test file; existing classes and module-level constants are not edited (per D10).
- `assert-lib.sh` stays BSD-awk compatible: no `gensub`, no `-v` value containing a newline.
- Every test command runs from the worktree root with `PYTHONPATH=python`, in the foreground, with `timeout 300` or more.
- Final-gate verification (run once by sdd on the final head, not per task): `just build` (timeout 3600 s) and `just agent-workflow-tests` (timeout 3600 s).

## Test seams

- Skill-text contract tests in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, asserting phrases on whitespace-normalized text (the module's `normalized()` helper).
- The eval assert library `home/common/agent-skills/evals/assert-lib.sh`, executed from unittest by `bash -c 'source <lib>; …'` against temp files and the real fixture.
- The dispatch-marker inventory in `home/common/agent-skills/tests/test_dispatch_contracts.py` (per D8).

## Delivery estimate and boundaries

Estimate: 8 changed product files (3 skill docs, 1 fixture, 2 `evals.json`, `assert-lib.sh`, 2 test files counted once each), roughly 350 added lines, most of them tests. One slice; no aggregate-growth risk near the review-package boundary.

## Task index

Task 1 — Type and locate the to-issues criterion line — home/common/agent-skills/skills/to-issues/SKILL.md, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-1.md](2026-10-07-issue-274-typed-located-criteria.tasks/task-1.md)
Task 2 — Acceptance map in writing-plans and its blocking review check — home/common/agent-skills/skills/writing-plans/SKILL.md, home/common/agent-skills/skills/from-issue/REVIEW-CONTRACT.md, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-2.md](2026-10-07-issue-274-typed-located-criteria.tasks/task-2.md)
Task 3 — Grade the acceptance map in the fixture-001 evals — home/common/agent-skills/evals/assert-lib.sh, home/common/agent-skills/evals/fixture-repo/issues/001-well-specified.md, home/common/agent-skills/skills/from-issue/evals/evals.json, home/common/agent-skills/skills/writing-plans/evals/evals.json, home/common/agent-skills/tests/test_workflow_skill_contracts.py — low-risk — [task-3.md](2026-10-07-issue-274-typed-located-criteria.tasks/task-3.md)
Task 4 — Pin the dispatch-marker total — home/common/agent-skills/tests/test_dispatch_contracts.py — low-risk — [task-4.md](2026-10-07-issue-274-typed-located-criteria.tasks/task-4.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `ToIssuesCriterionLineContractsTest` in `test_workflow_skill_contracts.py` under `just agent-workflow-tests` |
| AC2 | code | Task 2 | `AcceptanceMapContractsTest` in `test_workflow_skill_contracts.py` under `just agent-workflow-tests` |
| AC3 | code | Task 3 | `AcceptanceMapEvalGradingTest` (live-eval grading and helper cases) in `test_workflow_skill_contracts.py` under `just agent-workflow-tests` |
| AC4 | code | Task 4 | `DispatchMarkerInventoryTest` in `test_dispatch_contracts.py` (total pinned at 39) under `just agent-workflow-tests` |

## Decisions

Tasks rest on spec ledger rows D1–D10: Task 1 per D1, D9; Task 2 per D2, D3, D4, D5; Task 3 per D6, D7, D10; Task 4 per D8. Plan-level rows D9 and D10 were appended to the spec's ledger during planning.

---
