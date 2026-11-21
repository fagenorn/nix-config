# ADR-delivery-013 — A declared live fault is delivered in a lane with no plan, one implementer and one diff review

- **Status:** accepted
- **Decided in:** #1433

## Context

A fault live in production was delivered like any other issue: a plan, a plan review, a final review and the fixes each of them asked for, so the repair waited on a process built for a larger change. The console now records a manager's live-fault declaration with its evidence (ADR-console-099), and the standard and direct lanes (ADR-delivery-001 names Codex a reviewer only, and the direct lane has no plan) did not read it. The owner decided the shape of the lane on 21 Nov.

## Decision

**D1. The owner's answer, 21 Nov.** A diff has at most 80 changed lines outside tests and at most 3 files, and the lane refuses authentication, secrets and a command or permission guard. It has no plan phase and no second-model plan review, one implementer and one independent diff review. A critical finding blocks and every other finding becomes a follow-up issue. The time from the declaration to a green pull request is recorded. The declaration is the console's live-fault record, read from there.

**D2. The declaration selects the lane, failing closed.** The manager starts a known declared issue with `lane: live`. A fresh run with no lane reads the sprint recap: a standing entry for its issue makes the lane `live`, and so does a read that failed or returned no usable answer, which the gate then stops as unread before any planner. Only a recap that names no entry for the issue, or no sprint, keeps the run standard. An explicit `lane: standard` or `lane: direct` reads nothing and is the way into an ordinary delivery. The lane is fixed right after the setup reply, before any exit that can build a continuation.

**D3. The one review is a Claude reviewer.** The lane runs no Codex review of any kind and skips the review-capability preflight; its pull request evidence names the live-fault lane review.

**D4. One commit, no second agent.** The implementer's commit is the head that the size clerk measures, the reviewer reads, verify verifies, the pull request carries and the merge matches. A step that would dispatch another implementer or reviewer stops at `live-bound` instead: a verification fix, a sync merge or its resolution, a continuous-integration fix, the owner's look fix, a review rerun, or a head that moved. A stop that names the ordinary delivery as the way on is final for the lane, and a resume of its continuation stops at once. A stop where a step returned nothing is resumable and runs only that step again.

**D5. The caps.** Files counts the distinct paths of the no-renames numstat, tests included, so a rename counts both sides. Lines counts the added and deleted lines of the paths that are not tests. A test path has a `test`, `tests`, `__tests__`, `spec` or `specs` directory segment, a `test_` file name prefix, or a `_test.`, `.test.` or `.spec.` infix.

**D6. An independent clerk judges sensitivity**, not the implementer, over the no-renames diff.

**D7. The evidence is structural in the program.** One command runs twice: at the start head it exits non-zero, other than 126 or 127, and the runner reports the named test failed with its failure line; at the committed head it exits 0 and the runner reports that test passed. The reviewer confirms that the test is in the diff and that the failure line is the observed harm.

**D8. One green rule.** A pull request is green at its head when every check run has completed with success, neutral or skipped, the latest status of every context is success, and every required check is present and met. The green time is the latest of those completion times. The interval from the declaration is compared unrounded: it is within the hour when it is from 0 to 3600 seconds. It is reported, never a gate. The `pr-green` command applies the rule for the close-out, and the first-use check calls the same code.

**D9. A batch leaves a declared fault out.** An issue with a standing declaration, or whose declaration could not be read, is not delivered by a batch. A live fault is delivered alone.

**D10. Identity.** A live continuation keeps the declaration's id, sprint, issue and time. Unmerged work resumes only under the same standing declaration: a withdrawn or replaced one stops it. A merged replay skips that check and closes out against the recorded declaration.

**D11. The first use is selected from primary records.** The first-use check walks the declaration rows in order. The first declaration with any pull request whose body carries its full marker decides, whatever that pull request's state, through its lowest-numbered one. The selection never moves to a later declaration.

**D12. What blocks in the review.** A critical finding blocks; so does a finding that names a criterion the same review did not grade met with evidence, an ungraded code criterion, and a non-blocking finding that cannot be filed. Every other finding, and every left-out item, is filed as a follow-up issue before the stop or the ship.

## Considered options

- **A hotfix path that skips review.** Rejected: the owner asked for one independent diff review.
- **The manager alone chooses the lane.** Rejected: a manager that forgets would run a fault through the full plan; the declaration selects the lane and an unreadable one fails closed (ADR-console-099).
- **Let the lane fix what its review or verify finds.** Rejected: a second implementer on a growing diff is the scope growth the lane exists to stop.
- **Judge sensitivity in the implementer's own report.** Rejected: the author of a change does not judge whether it is sensitive.

## Consequences

- A branch behind its base, or a red check, stops the lane under D4, because a sync merge or a CI fix would be a second implementer; the fault then goes to an ordinary delivery with `lane: standard`, at the cost of its plan.
- The first-use check reads the console's event log on the host it runs on, and the store is per host (`default_store()`), so the timing of AC5 is read per host: a declaration made on another host is not seen there.
- The lane's selection and overrides live in the delivery README, the delivery CONTEXT and the manager contract, outside the instruction corpus, so no Instruction Budget raise is needed beyond the five bytes of the skill's lane line.
- ADR-console-099 stands, and Codex stays a reviewer only (ADR-delivery-001): the lane runs no Codex review at all.
