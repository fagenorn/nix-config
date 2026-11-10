# ADR-release-001 — Attempts are the transaction core's first consumer, ship-release second

- **Status:** superseded by ADR-release-002
- **Decided in:** #117 (the [attempt-lifecycle design](../../../../.agents/artifacts/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md)), #123, #125

## Context

Two workflows needed durable, fenced state: the agent attempt lifecycle and ship-release. Building the transaction core for both at once would have fixed its shape before either consumer had exercised it.

## Decision

The attempt lifecycle is the transaction core's first consumer and ship-release the second. The decision governs the planned single-store migration, immutable subject and identity, fenced custody and terminal evidence, and maps the already-delivered agent-slot admission (#150) and the delivery contracts, remainders and authorization continuity (#151, #171) onto that core. Its runtime was the core delivered by #123, then the attempt lifecycle moved onto it by #125.

## Consequences

- The core was shaped by a lifecycle that issue 689 later retired; ADR-release-002 records what remains.
- The attempt lifecycle and the helpers that wrote it no longer exist, so this record explains the core's generality and nothing in the running code.
