# ADR-release-012 — The driver exposes the manual disposition and leaves roll-forward out

- **Status:** accepted
- **Decided in:** issue 1050; extends ADR-release-002 and ADR-release-008, amends #209 D11

## Context

A release parked after an effect whose deploy can never go green blocked its target for ever. Resume needs the old commit deployed, `abandon` is refused once an action had an effect, and a new candidate is refused `release_in_flight`. The core already implements `dispose_failed` and `roll_forward`, but the driver, its only caller (ADR-release-002), called neither, so the `failed` terminal was unreachable. The core also returned before its human and authority-class checks for the known-state grounds, so it would have accepted an agent's grant for `no_recovery_path`.

## Decision

The driver exposes one disposition, ground `no_recovery_path`, as `preview --dispose no_recovery_path --reference <why>` and `run` with the same arguments and `--confirm <token>`. It applies only to the current release parked `attention_required` with an action that had an effect; a release with none is abandoned instead. `preview` reads stored state alone and calls no adapter (ADR-release-008). `run` re-derives the same plan, writes nothing without the previewed token, then acquires custody, inspects every declared action again under the held fence, issues one human grant at the transaction's authority class `release` and calls `dispose_failed`. A custody acquisition other than the one the token was computed for refuses `confirmation_stale`, and a release whose declared actions all read `satisfied` after that inspection refuses `recovered`: it is resumed, never sealed `failed`. `run` never renews that custody: the core's renewal quiesces a release parked past its 900000 ms window with no action in flight, which is the release a disposition closes, so the acquisition's own lease covers the inspections. An inspection that raises refuses `inspection_failed` and gives custody up, since an inspection is a read, and custody lost before the seal refuses `custody_lost`; both dispose nothing and need a new preview. The token is `dispose:` plus a digest of the transaction id, the ground, the reference and the next acquisition ordinal, so it is no action's token and rotates on every acquisition as theirs do. The reference is mandatory and is sealed in the receipt. The terminal is `failed`, never `succeeded`; the disposed version stays reserved and the fix is an ordinary new release at the next ordinal.

The core now requires a human grant at the transaction's authority class for `no_recovery_path` as it does for the observability grounds. `successor_succeeded` keeps taking any fresh grant: the successor's sealed `succeeded` receipt proves it, so no person asserts anything.

`roll_forward` and the `successor_succeeded` ground stay out of the driver. A linked child needs a second creation path, a parent left parked until the child seals, and a rule for which of the two a verb addresses; disposing first and then releasing normally reaches the same end with the verification and confirmations a release already has.

## Consequences

- A disposition is an owner's decision: the ship-release skill asks for an explicit yes to the dispose token before it runs.
- The failed release is not linked to its successor in the store; the release notes of the successor say what the failed version left undeployed.
- An action still `in_progress` or `unknown` after the inspection refuses, so a release whose effects cannot be read is never closed with a known-state ground. The observability grounds remain unexposed.
- A disposition makes no land lock or sync call; a parked run already released the lock, and `run` with no candidate still reads a published release's sync again.
