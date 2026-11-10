# ADR-claims-005 — Only a waiting acquirer takes over an idle land lock, after 45 minutes

- **Status:** accepted
- **Decided in:** issue 629 D3, D4, D8; https://github.com/fagenorn/nix-config/issues/629#issuecomment-6693579241

## Context

A holder that dies mid-landing leaves a lock at a head that never merges. Reading event timestamps to detect idleness needs a wall clock and a persisted record, and an unattended takeover of a live landing would merge two branches at once. The owner chose option B on issue 629.

## Decision

A one-shot `status` or `acquire` treats only the lock of a merged or closed pull request as stale, takes only that over, and reads no event timestamps. Only `acquire --wait` takes over a held lock, after watching the same oid unchanged for 45 minutes on its own monotonic clock, counted from its first observation of that oid. No wall clock is read and nothing is persisted, so every `--wait` invocation starts a fresh watch. Every completed ref observation feeds the watch, so an interrupted watch restarts when the oid changes. `--wait` attempts every 120 seconds up to 3600 seconds and then answers `land-contended`.

## Consequences

- Accepted residual: a holder whose landing keeps the same sha for more than 45 minutes can lose the lock to a waiter, and its later `release` then answers `not_held` and cannot delete the new holder's lock.
- A dead holder blocks one-shot acquirers until a waiter's 45 minutes pass or its pull request closes.
