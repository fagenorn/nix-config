# Advisory workflow-suite CI Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Run the workflow-suite recipe on Ubuntu as measured advisory CI without altering the required `Nix Eval` contract.

**Architecture:** Task 1 adds the advisory job, its deterministic log-and-summary record, the empty evidence ledger, and local CI guidance. Once that slice locally passes, is signed committed, and independently task-reviewed, the issue owner checks the current lifecycle launch and publishes the feature branch under the existing grant; Task 2 alone owns bounded manual dispatch, foreground observation, and record updates while the issue remains open.

**Tech stack:** GitHub Actions YAML, Nix flakes, just, Python unittest, GitHub Actions summaries, GitHub REST Actions API, gh CLI.

## Global Constraints

- Preserve `contents: read` and the exact sole required `Nix Eval` check with Actions app ID `15368` (D5).
- Use `nix shell --inputs-from . nixpkgs#just`; add no dependency, activation, protection write, PR, merge, closure, or cleanup (D2, D7).
- Report `Agent Workflow Tests (advisory)`, set a ten-minute timeout, run for PR/main-push/manual dispatch, skip schedules, and add no path filter (D2, D6).
- Emit one compact, stable `AGENT_WORKFLOW_OBSERVATION_V1=` JSON line identically to logs and `$GITHUB_STEP_SUMMARY`; raw step outcomes are never inferred from continued-step conclusions (D3, D8).
- Three qualifying real non-scheduled Ubuntu outcomes permit only keep-advisory. Failed, missing, cancelled, timed-out, or setup-failed attempts are retained and do not qualify (D4).

## Test seams

- `tests/test_branch_protection.py` pins every named workflow step, raw outcome reference, summary schema/trigger, and the exact unchanged required-check payload.
- `just agent-workflow-tests` is the executed behavioral suite.
- The log-and-summary JSON record plus GitHub workflow/job metadata are the evidence seam.

## Delivery estimate and boundaries

Estimate: four product/documentation files and 170–250 changed lines for Task 1. Task 2 has one owner-controlled publication/dispatch handoff, at most three initial manual dispatches, and a 15-minute foreground watch per accepted run; failed evidence is recorded without retrying for success. It remains incomplete until evidence exists and must never be fabricated from local execution.

## Task index

Task 1 — Add deterministic advisory CI observation — `.github/workflows/ci.yaml`, `tests/test_branch_protection.py`, `.github/agent-workflow-observation.md`, `CLAUDE.md` — full — [task-1.md](2026-09-20-issue-37-advisory-workflow-ci.tasks/task-1.md)

Task 2 — Publish, dispatch, and record bounded Ubuntu evidence — `.github/agent-workflow-observation.md` — full — [task-2.md](2026-09-20-issue-37-advisory-workflow-ci.tasks/task-2.md)

## Decisions

The specification owns the decision ledger. This plan applies D1–D8 and introduces no new decision.

## Accepted review provenance

Accepted dispositions: B1 lifecycle handoff, B2 retrievable raw outcomes, S1 discriminating assertions, and S2 `CLAUDE.md` scope correction from `/root/issue37_plan_review`, reviewed at `117e8cedcc5d4fa11b1ab972828b62604b431b2d` against `a656dd9`. This is a native independent first pass; the requested Sol/high identity was not attested by the reviewer runtime.

---
