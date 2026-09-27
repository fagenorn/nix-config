# Attempt-Lifecycle First-Consumer Decision Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Make the #117 decision record's statements about the shipped engine match the branch's live code, and make its close-before-merge test seam cover every lane that ignores closure today, so the record and its `CLAUDE.md` pointer can be delivered as the issue's product.

**Architecture:** The refreshed design spec is the decision record and the product. `CLAUDE.md` already carries its one discovery pointer, which the plan-phase audit found accurate. The audit and the Phase-5 standards review found shipped-behavior statements in the record that are incomplete or ambiguous against live `workflow-state`, and a test seam narrower than D15's outcome. One semantic-documentation task corrects them in place, per D17 and D18. It changes no choice in D1–D16 and no runtime code.

**Tech stack:** Markdown; Python 3 standard-library assertions over the existing `workflow-state` CLI and lifecycle test harness (read-only probes); Git-scoped checks; the repository `just` verification recipes.

## Global Constraints

- The product is `.agents/artifacts/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md`. `CLAUDE.md` stays byte-identical, and its pointer paragraph is already delivered.
- Task 1 changes only five things. Three are inventory facts per D17: the "Shipped engine today" cells, the host-admission prose and the factual gap clause that ends D15's Choice cell. The fourth is test seam 3's close-before-merge clause, per D18. Nothing else changes: not the other ledger cells, the core (non-shipped) outcomes, the rest of the test seams, the acceptance cross-check or the out-of-scope text. D17 and D18 are this plan's own rows and are final at the task base.
- Nothing under `home/`, `python/`, `tests/`, `lib/`, generated projections, tracker state or host state is modified. Probes run against the live code, but they write only to temporary directories outside the worktree.
- Every fact a replacement adds to the record is observed by a Step-1 probe at the task base. If a probe fails, stop: the code has moved, and the text must be re-derived rather than written from this plan.
- Commits use the repository's default SSH signing, never bypassed. Each commit ends with the executing agent's `Co-Authored-By` trailer.

## Test seams

- Live-fact probes run as preconditions, over the `workflow-state` CLI and the `LifecycleHarness` of `home/common/agent-skills/tests/test_workflow_state.py`. They cover four facts:
  - `host-route` answers `claude-code` and `codex` from the committed declaration and refuses `direct`. Control's `direct` route takes one issue at `max_parallel` 1, reads no declaration and records no claims.
  - Over a closed tracker, an unexpired handed-off resume and a dead-owner resume both proceed, while a suspended attempt is held without a write.
  - A v2 checkpoint or summary against a stalled custody fails with the CLI strings and leaves the state bytes unchanged. The same reports are accepted under current custody.
  - `DeliveryRuntime.record_for_custody` gives the internal reason: the custody is not current.
- A scoped record check fails at the task base, where the stale text is present, and passes after the edit. Its reverse-replacement oracle must reproduce `git show HEAD:<spec>` exactly.
- Pointer, ledger-sequence (D1–D18) and nine-criterion-row invariants hold before and after.
- `just agent-workflow-tests` and `just build` each run once at the final bytes. They prove repository integrity, not core delivery or conformance.
- The mandatory final two-axis review counts the spec as product across the branch. Plan-package files are process artifacts.

## Delivery estimate and boundaries

Estimate: one task edits one product file in five places, about 1 KiB of changed text. The whole branch then carries about 435 product lines in two product files: the new spec and the two-line `CLAUDE.md` pointer. That is inside the ship-time small-diff line of ≤1,000 lines and ≤20 files, and `diff-scope` excludes this plan package by `--artifact-path`. One task is the smallest reviewable unit. Every edit restates what the same engine does or tests, and splitting them would review the same audit twice.

## Task index

Task 1 — Correct the record's shipped-engine inventory and close-before-merge seam — `.agents/artifacts/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md` — full — [task-1.md](2026-09-27-issue-117-attempt-lifecycle-first-consumer.tasks/task-1.md)

## Decisions

This plan adds two rows to the spec's ledger:
- D17: correct the factual inventory in place, without amending rows.
- D18: extend test seam 3 to the handed-off and dead-owner resume lanes.

Task 1 implements D17 and D18 and corrects the gap clause D15 carries. It also states D10's shipped host-admission mapping more precisely and extends the D5/D16 late-owner inventory. The choices of D1–D16 are unchanged.

## Standards review provenance

Reviewer: Claude fallback. Base SHA `17da7f2d53c33886073a107ce72627f9e1ec5ce1`; isolated and read-only; no focus. Outcome: accepted 3, rejected 0, deferred 0 (SF-1, SF-2 and DI-1, applied here and recorded as D18). The fallback ran because the configured Codex run's JSONL carried no runtime-selection event reporting the selected model gpt-6-astra and effort xhigh, so its output could not establish reviewer identity. No reviewer transcript is stored.

---
