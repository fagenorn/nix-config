# Attempt-Lifecycle First-Consumer Decision Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Make the #117 decision record's statements about the shipped engine match the branch's live code, so the record and its `CLAUDE.md` pointer can be delivered as the issue's product.

**Architecture:** The refreshed design spec is the decision record and the product; `CLAUDE.md` already carries its one discovery pointer, which the plan-phase audit found accurate. The same audit found three shipped-behavior statements in the record that are incomplete or ambiguous against live `workflow-state`. One semantic-documentation task corrects them in place, per D17, and changes no choice in D1–D16 and no runtime code.

**Tech stack:** Markdown; Python 3 standard-library assertions and the existing `workflow-state` test harnesses (read-only probes); Git-scoped checks; the repository `just` verification recipes.

## Global Constraints

- The product is `.agents/artifacts/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md`. `CLAUDE.md` stays byte-identical, and its pointer paragraph is already delivered.
- Per D17, only the shipped-engine inventory changes: the "Shipped engine today" cells, shipped-behavior prose and the factual gap clause that ends D15's Choice cell. Every other ledger cell stays unchanged, as do the core (non-shipped) outcomes, the test seams, the acceptance cross-check and the out-of-scope text.
- Nothing under `home/`, `python/`, `tests/`, `lib/`, generated projections, tracker state or host state is modified. Probes run against the live code but write only to temporary directories outside the worktree.
- Every sentence written into the record describes behavior that the Step-1 probes observe at the task base. If a probe fails, stop: the text must be re-derived, never written from this plan.
- Commits are signed with the repository's default SSH signing, which is never bypassed. Each ends with the executing agent's `Co-Authored-By` trailer.

## Test seams

- Live-fact probes, run as preconditions: `workflow-state host-route` with the committed declaration under a temporary `HOME`; the lifecycle harness in `home/common/agent-skills/tests/test_workflow_state.py` for handed-off versus suspended resume over a closed tracker; `DeliveryRuntime.record_for_custody` for a v2 report against a stopped or failed attempt.
- A scoped record check fails at the task base (stale inventory text present) and passes after the edit. Its reverse-replacement oracle must reproduce `git show HEAD:<spec>` exactly.
- Pointer, ledger-sequence (D1–D17) and nine-criterion-row invariants hold before and after.
- `just agent-workflow-tests` and `just build` each run once at the final bytes. They prove repository integrity, not core delivery or conformance.
- The mandatory final two-axis review counts the spec as product across the branch. Plan-package files are process artifacts.

## Delivery estimate and boundaries

Estimate: one task edits one product file in four places, well under 1 KiB of changed text. The whole branch then carries about 430 product lines in two product files: the new spec and the two-line `CLAUDE.md` pointer. That is inside the ship-time small-diff line of ≤1,000 lines and ≤20 files, and `diff-scope` excludes this plan package by `--artifact-path`. The one task is the smallest reviewable unit: every correction is a statement of the same kind about the same engine, and splitting them would review the same audit twice.

## Task index

Task 1 — Correct the record's shipped-engine inventory — `.agents/artifacts/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md` — full — [task-1.md](2026-09-27-issue-117-attempt-lifecycle-first-consumer.tasks/task-1.md)

## Decisions

This plan adds D17 to the spec's ledger: correct factual inventory in place, not through amending rows. Task 1 implements D17 and corrects the gap clause D15 carries. It restates D10's shipped host-admission mapping more precisely and extends the D5/D16 late-owner inventory. It preserves the choices of D1–D16.

---
