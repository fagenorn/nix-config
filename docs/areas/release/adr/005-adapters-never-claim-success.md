# ADR-release-005 — An adapter answers accepted, rejected or unknown, never succeeded

- **Status:** accepted
- **Decided in:** #124 D7; #85, #206; D9, D11

## Context

An adapter's mutating call can time out, lose its response or exit non-zero after the provider applied it. An adapter that reported success from its own call would let the core record an effect that never landed, or retry one that did.

## Decision

`invoke` returns only `accepted`, `rejected` or `unknown`, and `succeeded` does not exist in the result vocabulary. Only the core's later inspection, which reads the world through the adapter's `inspect`, says that an effect landed. An adapter makes at most one mutation, never retries it and never reads the target after it; a timeout or an unexplained failure is `unknown`, which the core resolves by inspection. `release_adapter.core_binding` validates every result and adds no retry or ordering policy, so retry, ordering and outcome stay in the core.

## Consequences

- An `accepted` invoke that never lands is recorded and then observed `absent` by the next inspection.
- Every adapter needs a faithful `inspect` for each operation it mutates with, because the core has nothing else to settle on.
