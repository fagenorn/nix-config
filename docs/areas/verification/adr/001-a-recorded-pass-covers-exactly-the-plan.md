# ADR-verification-001 — A recorded verification pass covers exactly the planned ids

- **Status:** accepted
- **Decided in:** #263, issue 437, issue 477

## Context

`verified-tree` records a passing verification against the exact git tree it verified (#263). Issue 437 then let `workflow.verification_conditions` skip an id whose condition does not match the change, so a planned run no longer runs every declared id. The plan depends on `origin/<integration_branch>`, which can move between the `check` that printed the plan and the `record` that stores the pass, and two callers can `check` the same worktree in turn.

## Decision

`verified-tree record` records only the `run` of a plan that `check` persisted for the same tree, and only when the plan recomputed at `record` time has the same `run`; otherwise it exits 2 and writes no record. A later `check` of a tree whose plan is still pending may narrow the plan to the ids both plans run and never widen it. `record` consumes the persisted plan once it has read it, recorded or not. A skipped id therefore never reads as passed, and every recorded id is one the caller was told to run. Evidence measured at an earlier commit is judged by `verified-tree fresh --since <commit>` (issue 477), which compares trees instead of trusting a hand judgement.

## Consequences

- A moved `origin/<integration_branch>` makes `record` fail instead of silently recording an id the caller skipped; the caller reruns `check`.
- Each `check` backs at most one `record`, so a second caller's `check` in the same worktree can only shrink the first caller's pending plan.
- The plan is a second file beside the record, guarded by an exclusive lock on `verified-tree-plan.lock`; a plan file `check` cannot parse is replaced rather than repaired.
- The record holds one latest pass per worktree and carries no run, attempt or launch identity, so it cannot say which run produced it.
