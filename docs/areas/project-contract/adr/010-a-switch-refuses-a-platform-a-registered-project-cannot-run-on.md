# ADR-project-contract-010 — A switch refuses to activate a platform a registered project cannot run on

- **Status:** accepted
- **Decided in:** issue 1451, issue 1415, issue 66

## Context

The host's installed copy of the platform is not protected by a project's lock, so a switch could install a platform that a registered project cannot run on.

## Decision

Both switch recipes run the fleet preflight after the build and before the activation. It is a body line, not a dependency, because just's `--no-deps` skips dependencies. It runs the tree's own code against the tree's own manifest under the flake's pinned `python3 -B`, so it needs nothing installed and writes no bytecode into a checkout that may itself be registered. Any incompatible or structurally invalid row refuses. An absent registry is the empty fleet, while an unreadable one refuses, a dangling link included. There is no force flag and no environment override, and the preflight only reads, so it needs no elevated rights. The `fleet-preflight` launcher exists for running the check by hand; the switch never uses it.

## Consequences

- The remedy is to migrate the project or remove it from the registry.
- The console's Activate runs the same recipe, so it is refused the same way.
- The first preflight on a host may fetch python3 from the binary cache.
- Every caller of the shared registry reader now refuses a dangling registry link.
