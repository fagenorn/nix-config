# Harness accounting correction Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer per task, reviewed between tasks.

**Goal:** Remove replay inflation and expose Codex usage source and coverage limits.

**Architecture:** Select modern response records per rollout, otherwise deduplicate legacy snapshots. Preserve existing projections and add measurement metadata at the run boundary.

**Tech stack:** Python standard library, unittest.

## Global Constraints

- Comparative telemetry only; no monetary savings or complete-month claims.
- Preserve default Claude text byte identity and existing JSON field shapes.
- No third-party dependencies or retained private transcript fixtures.
- Do not modify unrelated retained worktrees or raw session files.

## Test seams

- `scan_codex_file`, `collect_codex_groups`, `build_record` and CLI synthetic fixtures.
- Existing `agent-gate-bundle` record-consumer tests.

## Task index

Task 1 — Correct Codex record selection and coverage — scripts/agent-costs.py, tests/test_agent_costs.py, tests/test_agent_gate_bundle.py — full — [task-1.md](2026-09-19-harness-accounting-correction.tasks/task-1.md)

## Decisions

See [specification](../specs/2026-09-19-harness-accounting-correction.md), D1–D4.
