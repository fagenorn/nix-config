# ADR-verification-003 — Only workflow.verification commands with no effects run unattended

- **Status:** accepted
- **Decided in:** issue 630 P1, P2

## Context

The runner executes blocks on every host with no person present. A contract `command` can be any declared command, including ones that deploy, publish or spend money, and a check can ask for `live` or `paid` effects or for the owner.

## Decision

Unattended, the runner runs a check only when it is `kind: evidence` with no `ask` or `act` run, has `effects` of `none` (never `live` or `paid`, P1) and, for a `command` run, names a command listed in `workflow.verification` (the lead decision: no other contract command runs unattended, P2). Output is trimmed and never trusted (P2). A check that asks, acts or needs `live` or `paid` effects reaches the owner through an owner prompt, where approval lifts only the effects gate. A `command` outside `workflow.verification` raises no owner prompt: it is reported `command_not_verification` before any prompt is dispatched.

## Consequences

- A command that is not in `workflow.verification` is never run unattended, even when it is read-only; the check reports `command_not_verification` and waits, and an operator should not expect an approval request for it.
- `live` and `paid` checks are reported `effects_live` or `effects_paid` and wait for the owner's approval instead of running.
- The gate lives in `verify_exec`, apart from the lint, so a block the lint accepts can still be skipped at run time.
