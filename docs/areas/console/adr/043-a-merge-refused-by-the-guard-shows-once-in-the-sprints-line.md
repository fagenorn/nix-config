# ADR-console-043 — A merge refused by the guard shows once in the sprint's line, never as a question

- **Status:** accepted
- **Decided in:** #1115

## Context

The lifecycle guard refuses a merge it cannot prove safe: the pull request is behind its base, a required check is not green, or the merge state cannot be read. The guard's decisions stand and are not touched here (`docs/areas/guard/adr/`). What the console did with a refusal was wrong. Managers raised a question for it, so the owner met a card they could not act on, and the reason the guard gave sat in a report's prose where nobody read it. A refused merge is not a question for the owner: the manager waits for the pull request to become mergeable and tries again. It is a state of the sprint, and a sprint's state is what its status line and its now-sentence say (ADR-console-014). The inbox is for questions only (ADR-console-019). This decision lets a manager report the refusal in its status line and gives the console one place and one digest sentence for it.

## Decision

**D1. The marker.** A report whose status line starts with `merge refused: <reason>`, read case-blind with a non-empty reason, marks a merge the guard refused. It adds no report member: the status line is the carrier, and every report that passes the existing checks still passes unchanged.

**D2. The now-sentence.** The sprint's now-sentence reads `merge refused: <reason>` after every owner, quota and starting rule, in place of the stage phrase. It takes the `last seen` prefix exactly when the ball is nobody. ADR-console-042 D1 is unchanged: the prefix still follows the ball.

**D3. Ball and waiting.** The ball and the waiting reading are unchanged and follow ADR-console-042's reading of movement. A refusal is never the owner's ball: the owner has nothing to answer.

**D4. Cleared.** A refusal is cleared only by a later report without the marker or by a closing. A run observation never clears it, not even a run that closed out, because the status names no issue and an unrelated issue closing out would hide a refusal that still holds. A landed issue clears it through the manager's next report, which drops the marker.

**D5. The digest.** The digest says `A merge in <title> was refused: <reason>` once for each new or changed reason. An identical repeat is silent, and the sentence speaks again after the refusal was cleared and then returns.

**D6. The contract.** The manager contract tells a manager to put the refusal in its status line at once, not to raise it with `sprint ask`, not to put it in the `inbox`, to keep it while the merge stays refused, and to drop it in the first report after the merge lands.

## Consequences

- The refusal sentence is the one now-sentence that may equal the status line.
- A sprint quiet for fifteen minutes with a refusal reads nothing running beside `last seen merge refused: <reason>`.
- A refusal outlives its merge until the manager reports again, so the console depends on the manager dropping the marker.
- ADR-console-014's digest rule, one sentence only when the shown state changes at a report, gains this sentence; its status line names this decision.
- The contract is not in the instruction corpus, so no Instruction Budget raise follows.
- Related: ADR-console-014, ADR-console-019, ADR-console-042.
