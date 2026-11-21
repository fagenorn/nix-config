# ADR-console-085 — A claim names files, ends when its slice lands, and a default rule orders overlaps

- **Status:** accepted; amended by ADR-console-091
- **Decided in:** #1337

## Context

A claim notice (ADR-console-044) named "the paths or the area" a sprint worked in and ended only when it was withdrawn or its sprint ended. On 19 Nov one sprint's claim named a whole folder tree and outlived the slice it covered, so every slice another sprint cut in that tree was an overlap, and each overlap (ADR-console-046 D6) went to the owner as a question card. Most of those overlaps were two features touching the same files, which a fixed order settles without the owner.

## Decision

**D1. A claim names files or a narrow path.** `what` is comma-separated paths relative to the project's root. The console refuses a claim whose part is absolute or has a `..` segment (`CLAIM_OUTSIDE`) and, after that check, a claim whose part names a whole folder tree: a trailing slash, the root, a `**`, a last segment `*`, or a directory of the project's root (`CLAIM_FOLDER`). A project with no known root has no folder, so only the textual checks apply. The checks run when a claim is posted, never when the log is folded, so claims posted before this record stay open (ADR-console-044 D5).

**D2. A claim names its slice's issue and ends when the slice lands.** A claim carries `issue` (the slice's tracker issue, required) and `live_fault` (optional, true for a fix of a live fault). A claim ends when the sprint's report lists its `issue` as `landed` or `held`; a claim without an `issue` (posted before this record), a heads-up and a hand-off are never ended that way.

**D3. A default rule orders two overlapping slices.** A fix of a live fault outranks a feature; otherwise the earlier-started slice lands first; the slice that lands second rebases on the first. A slice's start is the lowest notice id among its sprint's claims naming its issue, withdrawn and ended ones included, so a claim withdrawn and posted again keeps its start. A slice not yet started has no claim and starts after every open claim. Two fixes of a live fault are the one overlap the rule cannot settle (`unsettled`), and only that overlap goes to the owner.

**D4. The console reads the overlaps.** `claim_overlaps` reads the open claims of two different sprints: paths are compared segment by segment (`*` never crosses a `/`, a shorter path reads as a folder), and each reading carries the two claims, the files, `first`, `rule` (`earlier-started`, `live-fault` or `unsettled`) and `asks`. `sprint notices` prints it as `overlaps` beside `notices`, and the block a manager reads ends with one overlap line for each overlap of one of its claims.

**D5. One asker and the heads-up.** For an unsettled overlap `asks` names the later-started sprint, which alone sends one `sprint ask` card marked `owner_only`, because a sprint has one open round and an answer reaches only the asking sprint. Once answered it posts a `heads-up` stating the owner's order; the other sprint keeps working and, when that heads-up puts the asker first, merges its overlapping slice only after the asker's claim ends. No card is sent for a settled overlap; the page shows no overlap line until #1347.

**D6. Checking work in delivery.** Before it claims a slice a manager reads the other sprints' open claims and the project's open issues carrying the `in-progress` label, which a delivery's claim on its issue adds. Work that already makes the same change is duplication and is not claimed over; a different slice that only touches the same files is claimed and ordered by the rule.

**D7. Nothing is refused for a claim.** The console still refuses no work because of a claim: it refuses only the notice that is folder-wide, outside the project or malformed (D1, D2).

## Considered options

- A free-text area in `what` (kept before this record): an overlap could not be read by the console, so every one went to the owner.
- A question card for every overlap (ADR-console-046 D6): the owner answers what a rule settles.
- Both managers asking on an unsettled overlap: a second card for one decision, and two answers that can disagree.
- A slice's start as each repost's own id: withdrawing and posting a claim again would send the slice to the back of the order.

## Consequences

- Amends ADR-console-044 D2 and D6 (a claim's members and when it ends) and ADR-console-046 D6 (which overlaps go to the owner).
- Rollback: reverting the change restores the free-text `what`, the end on withdrawal and the card for every overlap. The base revision rejects a claim row carrying `issue` or `live_fault` as an unknown member and skips the whole row on replay, so each claim posted under this change is missing from the older console's board until the change is back.
- The manager contract changed outside the instruction corpus (ADR-console-015, ADR-console-044 D10), so no Instruction Budget raise is needed.
- A manager that posts a claim without `issue` is refused until it names one.
