# ADR-console-084 — A registration whose project is unregistered gives way to the registration it replaced

- **Status:** accepted
- **Decided in:** #1334

## Context

The page shows one registration, the last `registration.ended` row (ADR-console-028, ADR-console-035 D4). The live check's throwaway rows replaced the owner's open registration on 19 Nov and stayed shown once the check removed its project from the registry.

## Decision

**D1. The chain fold.** `register.fold(events, state)` keeps, beside the shown registration, the registrations shown before it (`before`, oldest first, one per root) and each registered project's root (`roots`, from its `project.registered` row). An ended row naming another root pushes the shown registration onto `before` and drops that root's older entry, so the chain holds distinct roots. A `project.unregistered` row names the root in its payload `root`, else the root its project was registered with (rows written before #1334 carry no payload root), else it names nothing; a rootless row whose project has no known root, or whose known root is another checkout's, changes nothing. It drops that root from `before` and, when it is the shown registration's root, folds back to the last entry of `before` (None when there is none). Rows of the shown root push nothing. An owner's cancel of the shown registration folds to none and clears the chain. `register.latest` is `fold(...).latest`.

## Considered options

- One level of `before`: a completed check between the owner's rows would change what a later removal shows.
- A project-id match for rootless rows: two checkouts can share a project id.
- Cancel reverting to the previous registration: would change ADR-console-037 D7 for the owner.
- Marking check rows by project id: a check literal in console code.
- Folding to None on removal: loses a registration the check ran over.

## Consequences

- Amends ADR-console-028 (which registration the page shows).
- An owner's project removed from the registry no longer leaves its stale `registered` row on the page.
- An older registration can return to the page after such a removal.
- The chain is bounded by the distinct roots the retained log holds and is rebuilt by retention as by a restart.
