# ADR-claims-004 — Landings serialise on a compare-and-swap ref

- **Status:** accepted
- **Decided in:** issue 629 D1, D2, D4, D5, D9

## Context

Two deliveries to one integration branch must not merge at once, and they may run on different hosts, so no local lock serves. A ref in the repository is visible to all of them, but the forge's REST ref deletion is unconditional: it cannot tell the holder's lock from a successor's. A spike on issue 629 showed that the GraphQL `updateRefs` mutation with `beforeOid` and `force: true` is a true compare-and-swap, and that a failed one answers HTTP 200 with a generic error.

## Decision

The lock is the ref `refs/agent-locks/land/<branch>`, whose value is a pull-request head sha. It is created by REST (HTTP 422 means not created); every move and the release go through `updateRefs` with `beforeOid`. Any CAS error counts as not done, and the ref is re-read to classify the outcome. REST deletion is never used. The holder is derived, not stored, and the lock is classified by pull-request head, not by containment: it is held while it is the head of an open pull request other than the caller's. A holder merges only after a one-shot `acquire` answers `already_held` or `moved`, never on exit status alone, because `acquired` also exits 0 and means the lock was lost and taken again.

## Consequences

- Every outcome needs a re-read after the swap, which costs one more call per move.
- Accepted residual, the stacked holder: a holder whose previous head is also contained in another open pull request gets `held_by` naming its own pull request, and must run `land release --sha <lock_sha>` before acquiring again.
- A closed holder older than the 500 most recently updated closed pull requests of the branch is not found by head sha and reads as `held_by`; the `--wait` idle takeover of ADR-claims-005 covers it.
