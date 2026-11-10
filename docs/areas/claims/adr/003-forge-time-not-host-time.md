# ADR-claims-003 — Staleness reads the forge's clock, never the host's

- **Status:** accepted
- **Decided in:** #623 D3

## Context

A claim is stale when the time since its last activity reaches 24 hours. The activity times (a claim's `updated_at`, a branch push, a pull request's `updated_at`) are all stamped by the forge. Comparing them with the time of whichever host runs the verb would let one host with a skewed clock declare every claim stale, or none.

## Decision

"Now" is the `Date` header of `gh api --include rate_limit`, read from the forge on each judgement. The claim code reads no host clock, so a skewed host changes no verdict.

## Consequences

- Each staleness judgement costs one more forge call.
- A forge that answers without a usable `Date` header makes the verb fail with a forge error instead of guessing.
