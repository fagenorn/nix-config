# ADR-console-046 — An owner check card captions its pictures and reads its reading under the question

- **Status:** accepted
- **Decided in:** #1131

## Context

The owner kept the card of ADR-console-045 on 16 Nov 2026 and asked for two changes. The line under each thumbnail was the raw file name (`before-1440.png`), which is file-system noise on a card read by a person. And the `Reading:` line sat low, between the held line and the answer buttons, where it was easy to miss.

## Decision

**D1. The caption.** The page captions each owner check thumbnail from its picture's `line`, which stays the file name (ADR-console-045 D1); the console, the data and the stored pictures are unchanged. The page drops the `.png` and splits the name into words. A trailing word of three or four digits, with or without `px`, is a width and reads `, <width> px` after the lead. A `before` or `after` word leads, with its first letter capital. Any other name leads with its words in sentence case. A name with no words left reads `Picture`. So `before-1440.png` reads `Before, 1440 px` and `owner-check-viewer-480.png` reads `Owner check viewer, 480 px`. A caption with no before or after word is in sentence case whatever the file name's casing (the file name keeps its own casing in `line`), so `OWNER-CHECK-VIEWER-480.png` also reads `Owner check viewer, 480 px`. The thumbnail's alt text is its caption.

**D2. Only the owner check.** A question's, a brief's and a report's lines are written by the manager and show as written (ADR-console-038, ADR-console-041). Owner check pictures keep `pair` null, so a Before and an After caption are not a side-by-side pair.

**D3. The viewer keeps the full file name.** The viewer of ADR-console-038 D4 shows the picture's `line`, the full file name, so the owner can still tell which file a thumbnail is.

**D4. The reading.** `Reading: <instruction>` is the line right after the check's question, on the lead card and on a row, above the pictures, the missing lines and the answer box with its note box; it is no longer in the answer box.

**D5. Held for the owner.** As ADR-console-045 D6: the delivery makes before and after PNG screenshots of the owner check card at 1440 and 480 px, and the pull request merges only after the owner approves them.

## Consequences

- ADR-console-045 D5's thumbnail line (the file name) and the reading's place (in the answer box, right before the answer buttons) are replaced by D1 and D4.
- A name whose last word is three or four digits reads that word as a width; other numbers, such as dates and versions, read as words.
- A caption can hide which file a thumbnail is; the viewer shows the full file name (D3).
- Related: ADR-console-038, ADR-console-045.
