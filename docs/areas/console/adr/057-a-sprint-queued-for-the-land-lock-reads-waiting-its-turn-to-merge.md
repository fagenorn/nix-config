# ADR-console-057 — A sprint queued for the land lock reads waiting its turn to merge

- **Status:** accepted
- **Decided in:** #1184

## Context

Queued pull requests wait up to an hour under the land lock while nothing the console reads moves, so after fifteen minutes the sprint read "nothing running, may be stuck" (16 Nov), though the lock is something the console can see.

## Decision

**D1. The signal.** A lock wait is the fourth wait signal, kept per issue at the time last seen (ADR-console-050 D1). It is seen for the issues of an open pull request whose head (`headRefOid`) is the oid of `refs/agent-locks/land/<its base branch>`, or, for a same-repository pull request, of `refs/agent-locks/land/<its head branch>` (a release pull request, whose head is the locked integration branch itself), the holder of forge_land_lock D2; a fork's branch of that name never holds. A holder's issues are seen only while a delivery run of that issue is in a session that has not ended: a run that died (its session ended) holding the lock leaves its pull request holding until a waiter's idle watch takes the lock over (forge_land_lock D3, D4), and counting it would refresh the time every read and keep its sprint reading waiting its turn forever, hiding the orphaned lock (ADR-console-042); a holder with no live run here ages out after fifteen minutes and its sprint may read may be stuck. It is also seen for an issue whose delivery run, in a session that has not ended, sits in a lock step: the latest staged step for that issue is `pr`, `land-lock-<k>`, `land-relock-<k>` or `checks-<k>` (a single run's labels) or `land-pr-<n>`, `land-lock-<n>-<k>`, `land-relock-<n>-<k>` or `land-record-<n>-<m>` (a batch's), with no result read yet; the `checks` and `land-record` steps count because a conflict or a CI fix retakes the lock, waiting, inside them. A lock step counts only while the last good forge read saw an open pull request holding a lock: then somebody is ahead of it.

**D2. The read.** The lock is read by one REST call, `repos/<slug>/git/matching-refs/agent-locks/land`, after the GraphQL pulls query, because GraphQL lists no ref under `refs/agent-locks/` (checked 16 Nov 2026: `ref(qualifiedName:)` answered null where REST listed the lock). Only refs under `refs/agent-locks/land/` are locks. A failure of either call fails the read and keeps the last reading, as ADR-console-050 D5, and refreshes no lock time, a journal lock step's included: a lock step counts only in a good read that saw a pull request hold a lock, so through failed reads a lock wait ages out after fifteen minutes like every other signal, with no exception to D5. The cost becomes two forge calls per project with a running sprint every two minutes; this amends ADR-console-050 D5.

**D3. The sentence and its place.** `waiting its turn to merge`, named only when the waits alone move the sprint, fourth after CI, a committing delivery and a release step; after the merge-refused (ADR-console-048), owner, stall and quota rules, as ADR-console-050 D3. The words "stalled" and "stuck" are never written for it.

**D4. Aging.** A lock wait that ended keeps its last-seen time and moves the sprint for fifteen minutes after it, then the sprint may read may be stuck (ADR-console-050 D1).

**D5. Not read.** The waiters' registrations (`refs/agent-locks/land-wait/`) are not read; a run whose session ended, or a lock step while no pull request holds a lock, moves nothing.

## Consequences

- This amends ADR-console-050: D3's order gains a fourth wait, and D5's cost is two calls.
- A hung run in a lock step with someone ahead reads waiting until its session ends.
- A run that died holding the lock moves its sprint for fifteen minutes only, then it may read may be stuck, as ADR-console-042 requires.
- A release pull request holding the lock counts as a holder but names no issue.
- Related: ADR-console-042, ADR-console-048, ADR-console-050.
