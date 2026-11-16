# ADR-console-051 — An owner check that blocks none of a sprint's open issues is a check line, not waiting on you

- **Status:** accepted
- **Decided in:** #1111

## Context

A sprint's ball and its now-sentence read "waiting on you" for any open inbox item that names one of the sprint's issues. A held issue carries a manual check for the owner (a verification prompt), and when that check blocks none of the work the manager still has to do, the sprint read as waiting on the owner while the manager was building. The owner's check hid the manager's work, and the sprint looked stuck on a person who had nothing the sprint needed.

## Decision

**D1. What an owner check is.** An owner check is a tracker item whose reason is one of the verification owner prompts (`verify_owner.REASONS`) or the held-issue review card of ADR-console-053 (`inbox.REVIEW_REASON`). Only an owner check can become a check line; every other tracker item still counts as waiting on the owner.

**D2. Blocking is the tracker's edge.** `blocking` is the list of open issues of the same repository that the check's issue blocks on the tracker, read by the inbox reader. The sprint reads it as it finds it and never asks the tracker again (D-plan-1).

**D3. The sprint's open issues.** A sprint's open issues are the issues of its report whose stage is not landed, held, dropped or closed out. A check blocks work only when its `blocking` list shares a number with them.

**D4. Unknown counts as blocking.** A check whose `blocking` is missing or not a list is read as blocking, so the sprint keeps waiting on the owner: a record written before the reader listed `blocking` never hides a wait it cannot account for.

**D5. Still an inbox item.** The check is still one inbox item: the statement, its headline and `inbox.open` are unchanged. The page shows it as one "Your check: <question>" line inside the sprint block, which focuses its card.

**D6. Pictures wait for the owner.** A page change is held for the owner's before and after pictures (ADR-console-038, ADR-console-039), so the check stays visible and open until the owner answers it.

## Consequences

- Answering a check is unchanged (ADR-console-012).
- Movement is unchanged (ADR-console-042): a non-blocking check is absent from `waiting`, so the state line, the ball and the now-sentence read as if it were not there.
- The digest's waiting words and the manager's bring-back (ADR-console-017) read the same `sprint_waiting`, so a non-blocking check neither reads as waiting in the digest nor holds back a wake of a gone manager.
- Related: ADR-console-012, ADR-console-017, ADR-console-038, ADR-console-039, ADR-console-042.
