# ADR-project-contract-016 — Schema 3 derives the attempt budget from a recorded tracker history

- **Status:** accepted
- **Decided in:** #1466 (per #1430)

## Context

ADR-013 D1 made the attempt budget a platform constant of 240 minutes, so every schema-3 project got the same figure whatever its deliveries cost. The tracker holds what an attempt costs: when a claim started and when its change merged. #1430 decided that the budget follows those facts instead of a constant, and that the resolver, which only reads files, learns them from a record of the tracker rather than from the tracker.

## Decision

**D1. The rule.** An attempt is one claim on an issue. A claim ends when an `end` marker names it. A claim is delivered by the earliest merged pull request of its issue whose head is the issue's branch (the branch pattern with that issue number, and equal to the claim's `branch` when it has one), from the same repository, into the integration branch, merged between the claim's creation and the next claim's creation and no later than the claim's end. Its duration runs from the claim comment's creation to that merge, so a renewal, which moves only the comment's update time, changes nothing. A claim without such a merge stopped or still runs and is not delivered, and a merge no claim pairs with is not an attempt. Everything is judged at the forge's time when the history was recorded: a claim, end or merge after it is ignored. The budget is 1.5 times the nearest-rank 90th percentile of the durations of the 20 delivered attempts with the latest merge, in whole minutes rounded up and at least 1. With fewer than 20 delivered attempts it is 240.

**D2. The history.** The record is one file, `<git common dir>/agent-platform/attempt-history.json`, in the directory every worktree of a clone shares. It holds the repository, the recording moment and the attempts, not a number, so the rule lives in one function that the resolver and the recording command both call. The command `attempt-budget record` is its only writer; `attempt-budget report` prints what it would write. Nothing schedules it, so the history is refreshed by hand and used as recorded.

**D3. The resolver's added input.** For a schema-3 contract the resolver also reads that file, through `attempt_history.read`. It still only reads files, opens none for writing and starts no child process or connection, which amends ADR-014 D1. A schema-2 contract reads no history.

**D4. The basis, and no refusal.** The snapshot carries `bindings.workflow.orchestration.attempt_budget_basis` beside the budget. It is `{"source": "history", "delivered", "percentile_90_seconds", "recorded_at"}` when the history gives the number, else `{"source": "fallback", "reason"}` with the reason `no_history` (no git directory or no file), `unreadable` (not a regular file, not readable, not UTF-8 or not strict JSON), `invalid` (not the history's shape), `other_repository` (recorded for another repository than the derived one) or `too_few` with the `delivered` count. No state of the file refuses resolution: a project whose history is lost, damaged or short still resolves, with 240 and the reason.

**D5. No longer a constant.** The budget leaves the platform constants and joins the derived values with its basis. A schema-3 contract that authors either is refused `contract.workflow.derived_value` at its pointer. This amends ADR-013 D1 for the budget. The basis is a snapshot member only: the view the schema-2 rules validate never holds it.

## Consequences

- Schema 2 is unchanged: it keeps its authored budget and gains no member.
- This repository stays on its authored 240 until its move to schema 3.
- The history is refreshed only by running `attempt-budget record`. A stale history is used as recorded, and its recording moment is in the basis.
- A scratch export of a pinned commit, such as the guard compile or adoption's verification, has no history and resolves with the fallback.
- Every reader of the filled view sees the budget; none reads the basis.
- Rejected: asking the tracker from the resolver as a child process, which ADR-014 rejected for every resolve; a file keyed by repository under the home directory, an input located by the environment instead of the clone; a committed file, which would cost a commit for each delivery.
