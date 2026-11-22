# ADR-console-103 — A manager's permission prompt with no reason is sent back for one

- **Status:** accepted
- **Decided in:** #1622

## Context

A permission card reached the owner reading "It did not say why", because the manager's call carried no description. The owner had to guess the purpose of the command from the command alone.

## Decision

**D1. A prompt with no reason raises no card.** A Bash prompt whose call has no description, or a blank one, is not recorded: the console answers `unexplained`, appends nothing, and the hook refuses it back to the manager, asking it to state why and run it again. With a reason the card is as before. This amends ADR-console-100 D1.

**D2. The console judges.** No hook raises a reasonless card. A prompt the console refuses for its session or sprint is refused first and is never asked for a reason.

**D3. Every Bash prompt needs a reason today, a read included.** The hook sends every Bash prompt it holds to the console, so a read with no description is sent back like any other. If the hook later allows a read without asking the console (issue 1620), that read never reaches this check and needs no reason; until then no read is exempt.

**D4. The manager's contract says so.** It tells the manager to give every Bash call a description that says why it runs the command, on the first attempt, and to run a refused reasonless call again with a description.

## Consequences

- A manager that forgets a description costs one retry.
- Every card recorded from this change on carries the manager's own words. A card asked before it, which a restarted console can show again while its hook waits, may still read "It did not say why".
- The lifecycle guard and the page are unchanged.
- Related: ADR-console-021, ADR-console-100.
