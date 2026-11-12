# ADR-claims-010 — An open head on the default branch is found in the open listing

- **Status:** accepted
- **Decided in:** issue 905; extends ADR-claims-004 and ADR-claims-009

## Context

Eligibility and holder derivation both found pull requests through the forge's commit lookup, `GET commits/<sha>/pulls`. For a commit outside the default branch the lookup lists its open pull requests. For a commit on the default branch it lists merged pull requests only. Seen live after a release: sync pull request 2767 was open, in the same repository, based on `dev`, and its head was the tip of `main`; the lookup of that head listed only the merged release pull request 2764. Every sync of the default branch back into the integration branch has this shape, because its head is the default branch's tip.

Two faults followed. `land acquire` answered `no_open_pr` to the sync pull request, so it could only be merged outside the lock, which moves the base under queued landers. And a lock at such a head would have been judged by the merged pull requests alone, so it read stale and any lander could take it while the sync was live.

The pull request listing cannot filter by head sha without naming the head branch, which neither a lock nor a waiter knows.

## Decision

When the commit lookup lists no pull request headed at the sha, the open pull requests based on the locked branch are read and matched by head sha: `GET pulls?state=open&base=<branch>&sort=updated&direction=desc`, 100 a page, at most 5 pages, stopping at the first short page. Only a same-repository pull request is taken from this listing.

- Eligibility (`acquire` without `--release`, one-shot and at every `--wait` poll) reads it when the lookup has no open pull request on the branch headed at `--sha`, and answers `no_open_pr` only after both reads.
- Holder derivation reads it before the closed listing, and stops there when it finds one: an open pull request headed at the lock holds it, whatever closed pull requests share that head or contain it. The closed listing, and then the listing of pull requests headed by the branch (ADR-claims-009), are read only when the one before found none.

The open listing goes first for two reasons. A waiter polls behind a live holder every 120 seconds, while a stale lock is classified once and then taken, so the repeated path gets the shorter chain. And a closed pull request must never decide a lock that an open one with the same head holds, which happens when a sync pull request is closed and opened again from the same commit.

Fork pull requests are left out because every fork already has the default branch's commits: anyone could otherwise open a pull request at the default tip and hold a lock there, or keep a stale one looking held, without pushing a commit. A lander from a fork, whose head is outside the default branch, is still found by the commit lookup as before.

A following release wait (ADR-claims-009) reads the same two listings before it deletes a lock at the sha it started from, so a sync pull request headed there keeps its lock. `--release` eligibility is unchanged. A release head is the integration tip, which is not on the default branch until the release is published, so the lookup lists it.

## Consequences

- No call is added where the lookup lists a pull request headed at the sha: a caller with an ordinary pull request, a waiter behind a live lander or release (four calls a poll, as before), and a stale lock whose merged holder the lookup lists by head (a merge commit into the default branch).
- A sync pull request acquires a free lock in three calls: lookup, open listing, create. A waiting one pays the open listing at every poll.
- A lander's poll behind a sync holder is five calls. Before, the same poll read the closed listing (one to five pages) and the branch listing, and then took the live lock over as stale.
- One call is added, once per open page, wherever the closed listing was already read: a stale lock whose holder was squash-merged, rebase-merged or closed, a lock at an earlier head of the caller's own pull request, a holder that moved past its lock, and a lock no pull request heads. The same call is added before `no_open_pr`.
- Accepted residual: an open pull request older than the 500 most recently updated open ones on the branch is not found. As a caller it is answered `no_open_pr`. As a holder it is not seen: a live sync lock then reads stale, because the merged pull requests the lookup lists are all that is left to judge it by, and a lander can take it. The sync still does not merge on a lost lock. Its one-shot `acquire` right before the merge (ADR-claims-004) answers `held_by` when the listing finds it again, and `no_open_pr` while it is still outside the window; neither permits a merge. A pull request that was just pushed or opened is at the front of that order.
- Accepted residual: when the lookup lists a closed pull request headed at the lock, the open listing is not read. An open pull request cannot share that head: a head the base branch has reached closes every pull request on that base at it, and the forge opens no pull request without commits ahead of its base.
