# ADR-console-049 — A held issue whose only open criterion is an owner review gets an owner check card

- **Status:** accepted
- **Decided in:** #1113

## Context

A delivery run that has finished its work holds its issue with the `needs-verification` label until every acceptance criterion is ticked. When the only criteria still open are `[human]` reviews and the runner has posted no prompt, nothing on the page tells the owner: ADR-console-012 D7 raises an item only from a live runner prompt, so a held issue with none raises no item. #1091 sat in that state. This decision gives such an issue a card the owner can answer from the page, through the write path the other owner checks use.

## Decision

**D1. The read.** The search of ADR-console-003 asks for open items carrying the `owner-action`, `owner-answered` or `needs-verification` label. An Issue node also reads `authorAssociation`, `body` and `labels(first: 100)`; a node without them reads as it did before.

**D2. Which issues.** An issue is read for review cards when it carries `needs-verification`, its author association is OWNER or MEMBER, and it has no live trusted runner prompt, answered or not. A runner prompt keeps its own card (ADR-console-012); the review card never stands beside it.

**D3. Which criteria.** The criteria are the checkbox lines of the first `Acceptance criteria` heading section of the body, outside code fences. One card is raised per unticked `[human]` criterion, and only when no unticked `[code]`, `[evidence]` or untagged criterion remains: the owner is asked only when the owner's review is all that is left. An unticked `[note]` criterion blocks nothing.

**D4. The card.** It is an owner check card of kind `owner-review`, reason `held-review`, with the key `<slug>#<issue>/ac<n>`. It is headed by the criterion's text, and the pictures and missing lines of ADR-console-045 and ADR-console-047 are read from that text. Its answers are Approve and Not yet. Approve asks for no typed confirmation, and the five-second undo of ADR-console-010 applies.

**D5. The write.** The answer is `POST /api/check-answer`, as for every owner check. Approve reads the issue again as the owner and edits its body so that only that criterion's box is ticked (the tick of ADR-console-010, made on the issue body instead of a prompt comment). It is refused when the issue is closed, when the label or the criterion is gone, when another blocking criterion is open, or when the criterion's text changed since the page read it; a criterion already ticked is left alone. Not yet posts one owner comment holding the note, never a verify block, and ticks nothing.

**D6. Not a runner prompt.** The card has no comment id and no prompt marker. Answering it never writes the runner's answer block, and the runner's hold still decides what happens to the issue once the criterion is ticked.

**D7. The page change is held for the owner.** This is a change to how the page looks. The delivery makes before and after PNG screenshots of the review card at 1440 and 480 px, and the pull request merges only after the owner approves them.

## Consequences

- The read returns more nodes, the held issues, and parses their bodies.
- The tick does not close the issue or touch its labels; the runner's hold still decides that.
- GitHub has no conditional update of an issue body, so an issue edited by someone else between the read and the write may lose that edit; the version check narrows the exposure to the criterion line.
- ADR-console-003's search and ADR-console-012 D7's rule of no item without a live prompt are amended.
- Related: ADR-console-003, ADR-console-010, ADR-console-012, ADR-console-045, ADR-console-047.
