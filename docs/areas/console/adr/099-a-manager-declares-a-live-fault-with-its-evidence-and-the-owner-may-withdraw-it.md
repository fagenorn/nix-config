# ADR-console-099 — A manager declares a live fault with its evidence and the owner may withdraw it

- **Status:** accepted
- **Decided in:** #1432

## Context

A claim's `live_fault` flag (ADR-console-085) is the manager's own mark on one notice: it orders an overlap, and nothing else in the console knows an issue is a fault live in production. The owner's page showed no such fact, the manager had no way to state what was observed and how it was proven, and nothing told a manager that a fix of a live fault must stay narrow, so the scope of a fix grew like any other slice. The delivery lane for a live fault (#1433) and its test slot (#1434) need a declaration to read.

## Decision

**D1. A declaration with its evidence, with no go-ahead.** A manager declares an issue of its sprint a live fault with `sprint live-fault`, one object of `issue`, `observed`, `when` and `proven`. The owner asked for no card: the declaration needs no go-ahead and the manager never asks about it.

**D2. An issue of the latest report, once while it stands.** The issue must be one the sprint's latest report names, and an issue already declared and not withdrawn is refused. A sprint that is stopping or has ended takes no declaration.

**D3. The owner sees it and only the owner withdraws it.** The declaration shows on the sprint's line with its evidence, and on the finished line once the sprint ends. Only the owner withdraws it, on the page, through an owner-only page write; no message or nudge reaches the manager. `sprint recap` lists the declarations still standing under `live_faults`. A declaration counts in nothing that needs the owner.

**D4. Scope changes go to the follow-up issue.** Once a live fault is declared, a change of scope goes to the follow-up issue, never into the fix: the manager's contract says so under A live fault and in After approval.

**D5. Its own kept rows, not a notice kind.** A declaration and its withdrawal are the event kinds `fault.declared` and `fault.withdrawn`, kept rows like the notice kinds. Event-log schema 13 makes the delete trigger keep them, and a schema-12 store is migrated in place.

**D6. A claim's `live_fault` stays the manager's mark.** The claim's flag is unchanged and so is the overlap rule (ADR-console-085); the declaration does not set it.

## Considered options

- A notice kind: a notice ends with its slice or its sprint, is posted by a manager and withdrawn by it, and is bounded to a line of text; a declaration carries evidence, outlives the claim and is withdrawn only by the owner.
- An owner go-ahead card: the owner refused it, since the declaration states a fact and grants nothing.
- A manager's own withdraw: not asked for; the owner's withdraw is the correction.

## Consequences

- #1433's lane and #1434's slot read `live_faults`.
- ADR-console-085 stands.
- A build older than this one refuses a store this one has opened (schema 13), as every earlier schema bump did.
- The manager contract changed outside the instruction corpus (ADR-console-015, ADR-console-044 D10), so no Instruction Budget raise is needed.
