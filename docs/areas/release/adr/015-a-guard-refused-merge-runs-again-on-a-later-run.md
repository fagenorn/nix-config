# ADR-release-015 — A guard-refused merge runs again on a later run

- **Status:** accepted
- **Decided in:** issue 1376; amends #206 D6 for the actions a transaction names at creation

## Context

A guard refusal is an invoke that returns `rejected` with the class `authorization_denied`.
The adapter raises it before the one mutation, so it applied nothing. The transaction core
nonetheless parked it as not retryable for good, because only the three transient classes are
retry-safe. A merge the guard refused once could therefore never run again, and the release
had to be abandoned and created again even after the guard admitted the merge.

## Decision

The `created` event may carry `rerun_denied`: the sorted, non-empty list of distinct action
names whose guard-refused attempt may run again. It is written only when it holds a name, so a
transaction that names none stores and loads exactly as before. `create` takes the names, refuses
a malformed set with `StateInvalid` before the creation lock, and treats a same-key create
whose sorted names differ as a `CreationConflict` naming `rerun_denied`.

Admission of an attempt after the first treats a predecessor of a named action that
returned `rejected` `authorization_denied` as admissible. It passes the `not_retryable` rule and
the `window_closed` rule, because a refusal that applied nothing has no failure window to
protect. The rules `inspection_required`, `not_absent` and `budget_exhausted` still apply, in
that order, so an action runs at most `MAX_ATTEMPTS` times. Every other non-retry-safe
predecessor stays `not_retryable` for a named action too: `invalid_input`,
`precondition_failed`, `unsupported_operation`, an `unknown` result of class
`authorization_denied` and an `accepted` attempt that reads `absent`. A retry-safe predecessor is
still closed by `window_closed`.

Replay enforces what admission does. The history rule that a retry follows a retry-safe
attempt now also admits a denied attempt of an action the created event names, so a hand edit
that un-names the action, names another or changes the result fails to load. A malformed member
fails the load with `event 1 rerun_denied is not a sorted list of distinct non-empty strings`.

The release driver names the merge action, and only when the profile has a sync. A guard
refusal of the tag or the release stays `not_retryable`. After the third refusal the release
parks, the next run parks with `merge: refused budget_exhausted`, and abandoning it is a
separate `abandon` call: no refusal abandons on its own.

## Consequences

- Recovery, `roll_forward` children and every action that is not named keep the class rule, and
  `retry_eligible` in the core's action views still shows the class rule.
- A release whose merge the guard refused is resumed by running it again once the guard admits
  the merge, with no abandon.
- A build from before this change cannot load a transaction whose created event carries the
  member.
