# Attempt Lifecycle First-Consumer Decision Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Finalize the accepted #117 architecture record's delivery-authority wording without changing its lifecycle decisions or claiming runtime delivery.

**Architecture:** The accepted design spec remains the product and architectural authority. Its existing discovery pointer in `CLAUDE.md` is already delivered; one semantic-documentation task changes only the spec's final out-of-scope sentence so decision authority and enclosing-delivery authority are distinct.

**Tech stack:** Markdown, Python 3 standard library assertions, Git-scoped checks, and repository `just` verification commands.

## Global Constraints

- The immutable delivery base remains `6d4b7a49dd3a44c079c8310e902a86665a6805f0`; never repin it to the sync merge or omit incoming history from cumulative evidence.
- Synced `origin/main` history through `4cd9408c4e538d6c9f0b9941e43d05d43a77c9a8` is already-delivered provenance, not new #117 product.
- Preserve D1–D8, every named scenario and all three accepted test seams. This task changes no lifecycle, core, adapter, provider, guard, host, migration or activation behavior.
- The existing #117 `CLAUDE.md` discovery pointer is already implemented and remains byte-identical at SHA-256 `cf0ab131efb93fae481b9953cb9d50713fac7805023456303e7b5dabb1d26d87`.
- The replacement says the decision record grants no publication authority while allowing a separately scoped delivery authorization to govern, subject to current host enforcement. It neither grants public permission nor weakens an actual denial.
- Treat the decision spec as product in every task/final review. Plan artifacts are process records; the accepted spec is never excluded from product coverage.
- Final implementation commits are signed and include `Co-Authored-By: Codex <noreply@openai.com>`.

## Test seams

- A scoped RED assertion proves the accepted spec contains exactly the stale delivery-authorization sentence and not the replacement; the GREEN assertion proves the exact inverse.
- A byte-reconstruction oracle replaces the new sentence with the old one in memory and requires SHA-256 `66401c772aec1a3011380503e3693ebd5796a8c83d822c7c1bfea85d4e10e22c`, proving no other accepted design byte changed.
- Link and scope checks prove the tracked spec remains the existing `CLAUDE.md` target and the spec is the only implementation-state worktree change.
- `just agent-workflow-tests` and `just build` run once at final product bytes with durable logs, exits and receipts. They establish repository integrity, not runtime core delivery or activation.

The issue's nine criteria remain covered by the accepted record: first-consumer order by D1; adoption and identity by D1–D3; core/adapter suspension vocabulary and #132/#133 launch/expiry by D4; fencing and the named races by D5 and the scenario table; host admission and authorization handoffs by D6; independent delivery/merge/tracker/cleanup observations by D7; and migration/rollback by D8. The scoped wording correction does not delegate or reopen any criterion.

## Delivery estimate and boundaries

Estimate: one two-line replacement in one product file plus this two-file plan package. One full-lane task is the smallest independently reviewable unit because splitting removal from replacement would temporarily leave the authority boundary unstated.

The complete fixed-base range also contains 45 already-delivered upstream paths. Immediately after this plan is committed, run the actual cumulative producer over `6d4b7a49dd3a44c079c8310e902a86665a6805f0..HEAD`. Any configured overage stops before SDD; do not raise limits, omit upstream records, repin the base or treat an estimate as fit evidence.

## Task index

Task 1 — Finalize decision delivery-authority wording — `.claude/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md` — full — [task-1.md](2026-09-21-issue-117-attempt-lifecycle-first-consumer.tasks/task-1.md)

## Decisions

This plan introduces no new architecture decision. Task 1 preserves D1–D8 and finalizes the record's delivery-authority wording under the already accepted architecture.

---
