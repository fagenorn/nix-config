# ADR-delivery-003 — Vendored skills are refreshed by hand against a pinned upstream

- **Status:** accepted
- **Decided in:** the Vendored skills section of `home/common/agent-skills/README.md` (before issue 694)

## Context

A skill under `skills/` may be an adaptation of an upstream skill. Its adaptations are made by hand, and an automatic refresh would lose them silently.

## Decision

There is no flake input for the upstream and no build-time synchronisation. A refresh is a manual comparison against a newer revision: the recorded adaptations are re-applied by hand and the pin is moved. The upstream URL, pinned revision, inspection date and every departure from upstream live in the skill's own `LICENSE`, above the unmodified upstream notice.

## Consequences

- A refresh costs a person's attention, and an upstream fix does not arrive until someone does it.
- The contract suite in `home/common/agent-skills/tests/` pins each adaptation, so a careless refresh fails a test instead of silently reverting one.
