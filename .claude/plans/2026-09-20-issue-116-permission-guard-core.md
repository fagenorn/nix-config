# Permission Guard/Core Decision Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Make the repository's living authorization prose agree with the current permission-guard owner roster and link it to the accepted guard/core decision.

**Architecture:** The committed decision record remains the architectural authority, while `CLAUDE.md` remains the single living description of the current native guard. One semantic-documentation task replaces the stale owner restriction and adds a relative decision link; it does not alter or certify runtime enforcement.

**Tech stack:** Markdown, Git-scoped assertions, Python 3 standard library, repository `just` verification commands.

## Global Constraints

- Per D4, living authorization prose names `home/common/claude-code/default.nix`'s `authorizedOwners` set as the current authoritative roster; it does not infer core adoption or mutation authority.
- Per D5–D7, retain both currently documented merge arms and describe the integration protection exceptions and permanent-head deletion check as unresolved gaps; do not claim that the future core operation is admissible.
- Per D6, preserve the provider-enforced required-status-check floor for both merge arms.
- Per D9, change only living prose. Do not edit the guard, owner/integration tables, resolver contracts, tests, generated AGENTS/import lines, historical records, downstream artifacts, host state or provider state.
- The decision spec stays byte-identical at accepted SHA-256 `8f9b341897b59d85a3f6f5883db56b4df384f35c29947af942c4592e2e4171a8`.
- Final implementation commits are signed and include `Co-Authored-By: Codex <noreply@openai.com>`.

## Test seams

- A scoped `CLAUDE.md` assertion proves the stale `fagenorn`-only clause is present at the implementation base, then proves the exact authoritative-roster clause and decision link replace it exactly once.
- Relative-link resolution proves the living link targets the tracked accepted decision; repository inventory confirms no second living owner restriction is introduced.
- `just agent-workflow-tests` and `just build` run once at the final product state. They prove repository integrity, not future core enforcement or provider certification.
- The final branch review covers both the committed decision record and the living-prose commit against D1–D9; no passing legacy guard test substitutes for that semantic review.

## Delivery estimate and boundaries

Estimate: one product file (`CLAUDE.md`) plus this two-file plan package; the already committed decision spec remains part of the full delivery range. Expect four changed files across the complete issue branch and about 55–80 KiB of review-package diff bytes, with the long `CLAUDE.md` line as the largest record. The single full-lane task is the smallest independently reviewable delivery: separating the owner clause from its decision link would temporarily leave living authorization truth incomplete.

## Task index

Task 1 — Align living guard authorization prose — `CLAUDE.md` — full — [task-1.md](2026-09-20-issue-116-permission-guard-core.tasks/task-1.md)

## Decisions

This plan introduces no new design choice. Task 1 implements D4 and D9 while preserving D1, D5, D6, D7 and D8.

---
