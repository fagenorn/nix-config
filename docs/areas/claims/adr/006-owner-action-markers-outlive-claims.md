# ADR-claims-006 — Batch owner-action markers carry no claim

- **Status:** accepted
- **Decided in:** issue 636 D6

## Context

A delivery batch asks the owner for a decision, a conflict resolution or a missing label by posting an owner-action marker. A claim on the same issue can end, go stale or be renewed while the owner is still deciding. Claim retirement ends the owner-action markers that name the claim, so a marker tied to a claim could vanish under a pending question.

## Decision

The markers posted by `owner-action` carry no `claim` field. Claim retirement (`status`, `renew`, `release`) ends only owner-action markers that carry one, so a claim ending, going stale or being renewed never ends or hides a pending decision.

## Consequences

- A decision marker outlives its batch until `owner-action end` runs; the batch that posted it, or a relaunch, ends it.
- A claim-less marker or a prompt of another reason counts as live when a call decides whether the `owner-action` label may go, so the label stays while one exists.
