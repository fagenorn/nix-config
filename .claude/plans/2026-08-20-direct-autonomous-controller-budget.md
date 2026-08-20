# Direct Autonomous Controller Budget Certification Implementation Plan

> **For agentic workers:** execute Task 1 with the `sdd` skill and one reviewed
> implementer. Per D6, Task 2 is executed only by the separate post-terminal
> certifier, without SDD. Steps use `- [ ]` checkboxes.

**Goal:** Produce one compact, reproducible evidence report that truthfully certifies or rejects the controller-input budget for representative run `direct-75-000002` without altering the deployed lifecycle.

**Architecture:** One Markdown report advances through two immutable evidence checkpoints. The fresh delegated owner first commits facts available before shipping with verdict `pending`; after the run is durably terminal and both controller prefixes are closed, a separate read-only certifier seals the same report on a follow-up branch and derives the closed verdict from a reproduction matrix.

**Tech stack:** Markdown, Git, POSIX shell, `jq`, `readlink`, platform `stat`, `realpath`, `cmp`, `shasum -a 256`, Codex rollout JSONL, and the workflow-state JSON ledger.

## Global Constraints

- The claim covers only run `direct-75-000002`, attempt `1`, owner `75:1`, its recorded worktree, and the inclusive `<= 150000` logical single-turn input ceiling.
- Create and later update only `.claude/specs/2026-08-20-direct-autonomous-controller-budget-evidence.md`; do not change lifecycle code, skills, workflow-state schema, token logging, or report validators.
- The first committed report is `pending`, contains only already-observed facts, and does not predict the representative merge, terminal result, final controller maximum, or final evidence commit.
- Per D6, the representative run executes and ships only Task 1. Task 2 starts after durable terminal state on an ordinary follow-up branch from the merged representative run and invokes neither SDD nor any lifecycle-mutating command.
- Neither lifecycle controller edits after terminal relay. The post-terminal certifier preserves terminal ledger bytes and does not reacquire the run, activate a system generation, or start another direct trace.
- Inventory every observed run-associated session. Per D2, only sessions that acquire or adopt the issue-level envelope or persist issue-level progression are required controllers; any unexpected qualifying session gains the same evidence obligations.
- Per D3, select each required controller's completed `token_count` record with maximum `last_token_usage.input_tokens`, breaking a tie by later timestamp. Pair cached input from that record, derive fresh input by subtraction, and never use cumulative totals or combine turns/controllers/categories.
- Required source counters are non-boolean integers satisfying `0 <= cached <= logical`; a missing or invalid required counter is unmeasurable. Compare only logical input with the inclusive ceiling.
- Mutable rollout prefixes and terminal ledger bytes carry absolute paths, exact covered byte counts, and SHA-256 digests. Git anchors are full object IDs, installed files are compared byte-for-byte with the issue-74 merge, and the base revision must differ at those definitions.
- Copy no transcript or prompt prose. Retain only compact structured fields, literal reproduction commands with resolved paths and object IDs, and bounded observed results.
- Compare the two rechecked issue-49-era root-controller observations descriptively only; report no percentage, average, aggregate, causal wait attribution, counterfactual, or claim beyond this run.
- Final verdict follows D8: an observed failure yields `not certified`; absent any failure, missing evidence yields `unknown`; only a complete all-pass matrix yields `certified`. `pending` is never final.
- Identify the report's own finalizing commit with the path-scoped clean-checkout query in D7; never predict or embed a self-referential object ID.

## Test seams

- Deployment seam: compare installed `SKILL.md`, `AUTO.md`, and `workflow-state` bytes with `f3fac9554761d0c3085d70bf4526cf3e7486de3e`, prove they differ from `c780b38f613c59a7d6674dc081d9f67666054ebf`, resolve `/run/current-system`, and assert `merge_time <= activation_time < process/session_start`.
- Lifecycle seam: require the sealed Phase-5 observation and terminal ledger to agree on run `direct-75-000002`, attempt `1`, owner `75:1`, action `delegate` at Phase 5, unchanged envelope, a distinct later fresh-owner session, and one durable terminal result.
- Controller seam: build the complete role inventory, apply D2, extract one D3 maximum record from each required sealed prefix, validate paired counters, and require every logical value to be at most `150000` for an all-pass result.
- Ownership seam: diff the issue-74 deployment merge to reviewed HEAD and inspect structured dispatches; before rollover, only the design and complete plan package may change and no SDD task may launch, while the first SDD launch belongs to the fresh owner.
- Report seam: from a clean checkout at the final evidence commit, run every reproduction row and compare its compact output; any absent or mismatched required value moves the verdict away from `certified`.

## Task index

Task 1 — Commit the truthful pre-terminal evidence checkpoint — `.claude/specs/2026-08-20-direct-autonomous-controller-budget-evidence.md` — full — [task-1.md](2026-08-20-direct-autonomous-controller-budget.tasks/task-1.md)

Task 2 — Seal the post-terminal certification — `.claude/specs/2026-08-20-direct-autonomous-controller-budget-evidence.md` — full — [task-2.md](2026-08-20-direct-autonomous-controller-budget.tasks/task-2.md)

## Decisions

- The two-writer report lifecycle and truthful pending checkpoint follow D1; controller classification follows D2; token selection and decomposition follow D3.
- Immutable evidence anchors and sealed mutable prefixes follow D4; the bounded historical comparison follows D5.
- The task execution boundary follows D6, final-report self-identification follows D7, and the closed verdict precedence follows D8.

---
