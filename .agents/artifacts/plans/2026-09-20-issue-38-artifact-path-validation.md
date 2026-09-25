# Artifact-path validation Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Make `diff-scope` reject artifact paths that become absolute after `./` normalization.

**Architecture:** Adjust the existing normalization order and pin the public CLI behavior at the existing subprocess test seam. Per D1, no matching or output logic changes.

**Tech stack:** Python standard library, unittest, just.

## Global Constraints

- Preserve the `diff-scope` CLI exit-1 diagnostic convention.
- Do not add dependencies or change valid `./x` behavior.
- Verify with `just agent-workflow-tests` and `just build`.

## Test seams

- The existing CLI subprocess test in `home/common/agent-skills/tests/test_diff_scope.py`.

## Task index

Task 1 — Reject post-normalization absolute paths — `home/common/agent-skills/scripts/diff-scope.py`, `home/common/agent-skills/tests/test_diff_scope.py` — low-risk — [task-1.md](2026-09-20-issue-38-artifact-path-validation.tasks/task-1.md)

## Decisions

Follow D1 in `.claude/specs/2026-09-20-issue-38-artifact-path-validation-design.md`.
