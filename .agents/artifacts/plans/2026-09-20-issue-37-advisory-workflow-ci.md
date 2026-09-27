# Advisory workflow-suite CI Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Run the workflow-suite recipe on Ubuntu as measured advisory CI without altering the required `Nix Eval` contract.

**Architecture:** Task 1 added the advisory job, its deterministic log-and-summary record, the empty evidence ledger, and local CI guidance. The original three-run manual cohort has completed at its pinned published head; Task 2 consumes its retained evidence, replaces the ledger's superseded success-only classification, and records the keep-advisory decision. It performs no dispatch or watch.

**Tech stack:** GitHub Actions YAML, Nix flakes, just, Python unittest, GitHub Actions summaries, GitHub REST Actions API, gh CLI.

## Global Constraints

- Preserve `contents: read` and the exact sole required `Nix Eval` check with Actions app ID `15368` (D5).
- Use `nix shell --inputs-from . nixpkgs#just`; add no dependency, activation, protection write, PR, merge, closure, or cleanup (D2, D7).
- Report `Agent Workflow Tests (advisory)`, set a ten-minute timeout, run for PR/main-push/manual dispatch, skip schedules, and add no path filter (D2, D6).
- Emit one compact, stable `AGENT_WORKFLOW_OBSERVATION_V1=` JSON line identically to logs and `$GITHUB_STEP_SUMMARY`; raw step outcomes are never inferred from continued-step conclusions (D3, D8).
- Consume the completed original cohort at `d1094c968ea16818de8073889d25ea9f99bd8deb`: runs `35513790832`, `35514069941`, and `35514254859` are three valid non-passing V1 observations with elapsed times 111/122/121, zero passing outcomes, and zero incomplete/fallback records. Do not dispatch or replace runs. Preserve all classifications, interpret manifest `qualifies: false` only as retired D4 success-only data, and cite follow-up #160 before any future promotion decision (D9).

## Test seams

- `tests/test_branch_protection.py` pins every named workflow step, raw outcome reference, summary schema/trigger, and the exact unchanged required-check payload.
- `just agent-workflow-tests` is the executed behavioral suite.
- The log-and-summary JSON record is the raw-outcome evidence seam; GitHub workflow/job metadata is labelled fallback only for incomplete records.

## Delivery estimate and boundaries

Estimate: four product/documentation files and 170–250 changed lines for historical Task 1. Task 2 modifies one evidence ledger using the completed retained cohort; it makes zero dispatches and zero watches. It remains incomplete until the ledger replaces its success-only definition and truthfully records the measured cohort.

## Task index

Task 1 — Add deterministic advisory CI observation — `.github/workflows/ci.yaml`, `tests/test_branch_protection.py`, `.github/agent-workflow-observation.md`, `CLAUDE.md` — full — [task-1.md](2026-09-20-issue-37-advisory-workflow-ci.tasks/task-1.md)

Task 2 — Record completed pinned Ubuntu evidence — `.github/agent-workflow-observation.md` — full — [task-2.md](2026-09-20-issue-37-advisory-workflow-ci.tasks/task-2.md)

## Decisions

The specification owns the decision ledger. This plan applies D1–D9; D9 supersedes D4's qualification rule and introduces no plan-local decision.

## Accepted review provenance

Accepted dispositions: B1 lifecycle handoff, B2 retrievable raw outcomes, S1 discriminating assertions, and S2 `CLAUDE.md` scope correction from `/root/issue37_plan_review`, reviewed at `117e8cedcc5d4fa11b1ab972828b62604b431b2d` against `a656dd9`. This is a native independent first pass; the requested Sol/high identity was not attested by the reviewer runtime.

---
