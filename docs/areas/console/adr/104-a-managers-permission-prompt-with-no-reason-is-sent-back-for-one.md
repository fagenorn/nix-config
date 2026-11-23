# ADR-console-104 — A manager's permission prompt with no reason is sent back for one

- **Status:** accepted
- **Decided in:** #1622

## Context

A permission card reached the owner reading "It did not say why", because the manager's call carried no description. The owner had to guess the purpose of the command from the command alone.

## Decision

**D1. A prompt with no reason raises no card.** A Bash prompt whose call has no description, or a blank one, is not recorded: the console answers `unexplained`, appends nothing, and the hook refuses it back to the manager, asking it to state why and run it again. With a reason the card is as before. This amends ADR-console-100 D1.

**D2. The console judges.** No hook raises a reasonless card. A prompt the console refuses for its session or sprint is refused first and is never asked for a reason.

**D3. Every Bash prompt that reaches the console needs a reason, a read included, except a read ADR-console-103 admits.** A read that `own_reads.allowed` admits (its own saved tool output or its project root) is allowed before the console is asked and before the description is read, so it needs no reason and never gets the unexplained reply. Every other Bash prompt the hook holds, a read outside those places included, is sent to the console, so one with no description is sent back like any other.

**D4. The manager's contract says so.** It tells the manager to give every Bash call a description that says why it runs the command, on the first attempt, and to run a refused reasonless call again with a description.

## Consequences

- A manager that forgets a description costs one retry.
- Every card recorded from this change on carries the manager's own words. A card asked before it, which a restarted console can show again while its hook waits, may still read "It did not say why".
- The lifecycle guard and the page are unchanged.
- Related: ADR-console-021, ADR-console-100, ADR-console-103.
