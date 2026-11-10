# ADR-release-009 — The codesigned-artifact adapter installs the checkout and never builds

- **Status:** accepted
- **Decided in:** issue 547 D9

## Context

A profile that releases a signed application bundle needs the bundle on the host. Building it is a separate concern with its own tools, and an adapter that built inside `invoke` would carry a build policy the core and the profile do not own.

## Decision

The codesigned-artifact adapter never builds. It installs the bundle the checkout already holds, and only when HEAD is the candidate and no tracked file changed. It stages and signs a copy, then swaps it onto the install path.

## Consequences

- The adapter cannot prove the bundle was built from that commit: a clean checkout at the candidate can still hold a bundle built earlier from other sources, and the adapter installs and signs it. The stamped `AgentReleaseCommit` names the candidate, not the commit the bundle was built from.
- An operator who needs that proof builds the bundle from the candidate before the release; the adapter does not check it.
