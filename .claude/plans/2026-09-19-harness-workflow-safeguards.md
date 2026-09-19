# Harness workflow safeguards Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer per task, reviewed between tasks.

**Goal:** Prevent repeated approvals, abandoned authorized reconciliation, and late discovery of cumulative package overflow.

**Architecture:** Correct the owning skill instructions and add scenario evals. Reuse existing package commands and lifecycle contracts.

**Tech stack:** Markdown skills, JSON behavioral evals, existing Python verification.

## Global Constraints

- Keep lifecycle/result JSON schemas, launch guards, required CI, and runtime permission boundaries intact.
- Do not add a scheduler, claim reservations exist, or default refused project policy.
- Preserve the one-decision wayfind boundary and independent review.
- Keep instructions concise; replace contradictory clauses instead of layering exceptions.

## Test seams

- Independent plan-only scenarios using the edited skills; no live external mutations in probes.
- Existing workflow skill contracts, review-package tests, model-matrix validation and skill frontmatter validation.

## Task index

Task 1 — Reconcile authorized workflow progress and check delivery size early — home/common/agent-skills/skills/{from-issue,handoff,wayfind,design,writing-plans,sdd}, home/common/claude-code/skills/orchestrate-issues — full — [task-1.md](2026-09-19-harness-workflow-safeguards.tasks/task-1.md)

## Decisions

See [specification](../specs/2026-09-19-harness-workflow-safeguards.md), D1–D3.
