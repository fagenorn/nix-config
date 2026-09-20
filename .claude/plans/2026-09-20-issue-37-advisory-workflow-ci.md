# Advisory workflow-suite CI Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Run the workflow-suite recipe on Ubuntu as measured advisory CI without altering the required `Nix Eval` contract.

**Architecture:** Add an independent CI observation job. Continued measurement steps plus a final summary keep the all-check shipping watcher usable while preserving raw outcomes. A tracked record starts empty and is completed only from real Ubuntu runs.

**Tech stack:** GitHub Actions YAML, Nix flakes, just, Python unittest, GitHub Actions summaries.

## Global Constraints

- Preserve `contents: read` and the exact sole required `Nix Eval` check with Actions app ID `15368` (D5).
- Use `nix shell --inputs-from . nixpkgs#just`; do not add Python packages, activation, or a protection write (D2).
- Report `Agent Workflow Tests (advisory)`, set a ten-minute timeout, skip schedules, and introduce no path filter (D2, D6).
- Preserve raw setup and suite outcomes despite a completed observation check; cancellation and timeout are incomplete evidence (D3).
- Three real non-scheduled Ubuntu outcomes can support only a keep-advisory decision (D4).

## Test seams

- `tests/test_branch_protection.py` pins the workflow shape and unchanged required-check payload.
- `just agent-workflow-tests` is the executed behavioral suite.
- The observation record plus GitHub job/run data are the later evidence seam.

## Delivery estimate and boundaries

Estimate: three product files and 130–200 changed lines for Task 1. Task 2 is evidence-gated and remains incomplete until three real Ubuntu runs exist; it must never be fabricated from local execution or a passing observation check.

## Task index

Task 1 — Add the measured advisory CI job — `.github/workflows/ci.yaml`, `tests/test_branch_protection.py`, `.github/agent-workflow-observation.md` — full — [task-1.md](2026-09-20-issue-37-advisory-workflow-ci.tasks/task-1.md)

Task 2 — Record the initial Ubuntu observation window — `.github/agent-workflow-observation.md` — full — [task-2.md](2026-09-20-issue-37-advisory-workflow-ci.tasks/task-2.md)

## Decisions

The specification owns the decision ledger. This plan applies D1–D6 and introduces no new decision.

---
