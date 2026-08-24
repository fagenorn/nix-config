# Skill Prose Fixes Behind Four Agent-Error Classes — Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Close four recurring agent-error classes by fixing the shared skill prose that causes them, and hold every fix in place with the skill-contract suite.

**Architecture:** Pure prose edits under the two skill trees, each paired with a blanket assertion in the existing skill-contract suite (`home/common/agent-skills/tests/test_workflow_skill_contracts.py`). Three fixes are text inserted into or corrected inside skill documents; the fourth is a sweep defined by a rule rather than a list. The only genuinely new machinery is one module-level shell-text extraction helper in the suite, on which three of the eight new assertions depend. Every task ends with the whole suite green, so the between-task reviewer never sees a red baseline.

**Tech stack:** Markdown skill documents; Python 3 `unittest` (stdlib only, no new dependency); `just agent-workflow-tests` as the runner.

## Global Constraints

Copied from the spec; every task's requirements implicitly include these.

- **Zero project residue.** Skills under `skills/` are project-agnostic. New prose must not name this repository, this issue, or a consuming project. Citing *measured telemetry* without naming a project is existing precedent (`skills/worktrees/SKILL.md:18`).
- **No new test file, no new runner, no CI change.** All assertions go into the existing `test_workflow_skill_contracts.py`. CI evaluates the NixOS configuration only; the Python suites stay a local gate.
- **No `.nix` file changes.** `just build` is a sanity check here, not a gate.
- **Canonical clause strings live once**, as module-level constants in the suite, asserted against all six templates (per D1).
- **Clauses live inside the fence.** A clause outside a template's fenced block never reaches the subagent (per D2).
- **No ADR, no `docs/` tree, no context map** (per D9).
- **Out of scope, do not touch:** the isolation checker and harness, `scripts/resolve-bindings` and bindings resolution behaviour, `home/common/agent-skills/evals/` and every `evals/evals.json`, `workflow-state` behaviour, executable scripts under the skills, command substitution `$(…)` (per D8).
- **Discovery set for the blanket assertions:** `*.md` under `home/common/agent-skills/skills/` and `home/common/claude-code/skills/`, excluding any path with an `evals` component (per D15).
- **Guard register:** `if it exists` and `when present` are the two accepted phrasings, nothing else (per D3).

## Test seams

- **The skill-contract suite** — `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, run by `just agent-workflow-tests`. This is the only seam. A task needing another seam is a plan bug.
- Assertions follow the suite's prevailing style: module-level `Path` and string constants, a discovery generator beside `nested_workflow_documents()`, per-file/per-template `subTest` loops, and the existing `assert_ordered` / `section` helpers.

## Task index

Task 1 — Leaf-agent and read-before-write clauses in all six dispatch templates — `home/common/agent-skills/skills/sdd/{implementer,task-reviewer,re-review,correctness-reviewer,conformance-reviewer}-prompt.md`, `home/common/agent-skills/skills/from-issue/ship-handoff.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-1.md](2026-08-22-skill-prose-agent-error-fixes.tasks/task-1.md)
Task 2 — Presence guard on every bindings-config mention — `home/common/agent-skills/skills/{research,design,doc-grounded-questions,wayfind,to-issues,writing-plans,ship-issue,ship-release,grill-with-docs}/*.md`, `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-2.md](2026-08-22-skill-prose-agent-error-fixes.tasks/task-2.md)
Task 3 — Isolation-checker shell guidance and a single-invocation isolation probe — `home/common/agent-skills/skills/worktrees/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-3.md](2026-08-22-skill-prose-agent-error-fixes.tasks/task-3.md)
Task 4 — Shell-text extraction helper, heredoc checks, and the two heredoc rewrites — `home/common/agent-skills/skills/ship-issue/SKILL.md`, `home/common/agent-skills/skills/ship-release/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-4.md](2026-08-22-skill-prose-agent-error-fixes.tasks/task-4.md)
Task 5 — Chain-operator check and every chain rewrite — `home/common/agent-skills/skills/from-issue/{bindings.md,REVIEW-CONTRACT.md}`, `home/common/agent-skills/skills/ship-issue/{SKILL.md,SYNC.md}`, `home/common/agent-skills/skills/ship-release/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-5.md](2026-08-22-skill-prose-agent-error-fixes.tasks/task-5.md)
Task 6 — Pipe and redirect checks and every remaining rewrite — `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/ship-issue/{SKILL.md,CI-MERGE.md}`, `home/common/agent-skills/skills/ship-release/{SKILL.md,CHANGELOG.md}`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-6.md](2026-08-22-skill-prose-agent-error-fixes.tasks/task-6.md)

Every task is `full`: each edits semantic documentation that agents act on, and each adds or changes assertions in the contract suite, which is a public-contract change. File and line counts do not qualify a change into a cheaper lane.

## Decisions

The single issue-level decision ledger lives in
`.claude/specs/2026-08-22-skill-prose-agent-error-fixes-design.md` under `## Decision ledger`.
Tasks cite rows by ID. Rows D1–D14 were set at design time; planning appended D15–D22.

- Task 1 rests on D1, D2, D11, D12, D13, D19, D21, D22.
- Task 2 rests on D3, D14, D15.
- Task 3 rests on D5, and on the spec's verified `git rev-parse` finding.
- Task 4 rests on D4, D5, D7, D15, D16, D17.
- Task 5 rests on D4, D7, D10, D16, D17, D20.
- Task 6 rests on D4, D7, D10, D16, D17.
- D18 records why one `writing-plans` sentence needs no rewrite and no exception.

---

## Standards review provenance

- **Reviewer:** Codex, isolated read-only runtime (fresh `CODEX_HOME`, approval policy `never`, sandbox `read-only`). No native fallback was used.
- **Base SHA reviewed:** `07be8e1` (branch `worktree-issue-99-skill-prose-fixes`, cut from `origin/main` at `95b6caf`).
- **Focus:** none configured. The caller additionally asked for isolation-checker prose honesty, genuinely-asserting tests, and Task 5/6 sweep scope.
- **Counts:** 2 blocking accepted, 0 should-fix, 0 rejected, 0 deferred.
- **Accepted:** the enrolment-guard false positive (per D23) and the heredoc-check baseline asymmetry (per D24). Both were reproduced against the live worktree before the plan was edited.
- The three focus areas came back clean: the isolation-checker guidance rests on one stated invariant rather than a guessed accept/reject table, every new assertion fails if its fix is reverted, and the Task 5/6 sweep touches only files in its enumerated lists.
