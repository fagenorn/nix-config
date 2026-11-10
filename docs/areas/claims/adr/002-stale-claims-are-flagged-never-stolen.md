# ADR-claims-002 — A stale claim is flagged to the owner, never stolen

- **Status:** accepted
- **Decided in:** #623

## Context

A holder can vanish without releasing: a crashed host, a closed session. The claim then blocks the issue for everyone. Letting the next acquirer take a stale claim over would end the block quickly, but a holder that is merely slow, or whose renewal is delayed, would then lose work it is still doing, and two sessions would deliver the same issue.

## Decision

`acquire` against a stale claim answers `held_by`; it never steals. `status` instead posts one owner-action marker whose checkbox the owner ticks. The next `status` or `acquire` honours a ticked box only while the claim it names is live and still stale at that moment: the claim is ended with reason `owner-action`, edited to `released=owner-action`, and the marker ended with reason `released`. A box ticked on a claim that is no longer stale is ended with reason `renewed` and releases nothing.

## Consequences

- An abandoned issue stays blocked until the owner ticks the box; the cost of never stealing is a human step.
- Accepted residual: an honour reads the server time and the branch activity, then takes a fresh listing and judges only that listing's `updated_at` before ending the claim. A renewal that lands between that listing and the end can still lose the claim, and a branch push landing after the activity read is likewise unseen. The holder's `renew` then reports `not_held`, so holders run `renew` before each irreversible step and stop on `not_held`.
