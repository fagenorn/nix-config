# ADR-console-041 — A manager's brief and report show their pictures on the card

- **Status:** accepted
- **Decided in:** #1091

## Context

ADR-console-038 let a manager's question carry pictures, showed them on the question's card and opened them full size in one shared viewer, and said the brief and report cards of #1091 would reuse that gallery and viewer. A manager that has built or checked something has the same screenshots to show with its brief, before the owner approves it, and with its report, after a batch. This decision gives the brief and the report the pictures a question has: what they may carry, how the log keeps them, how the commands send them, and where the page shows them.

## Decision

**D1. The pictures.** A brief or a report may carry `pictures`, at most 8, each `{"picture": <id>, "line": <text>, "pair": "before" | "after"}` with `pair` optional, under ADR-console-038 D1's rules: the `line` is one line of at most 140 characters, at most one picture is marked `before` and at most one `after`, and the list is refused when it breaks a rule. Only the sprint's own stored pictures (ADR-console-036) may be named: an id this sprint never stored, one another sprint stored, and one whose file is gone or is not a regular file are each refused. Each reason names the brief or the report.

**D2. The rows.** The checked list rides in the `brief` of `brief.sent` and in the `report` of `sprint.reported`. A top-level `pictures` id list on each row keeps the files from every sweep, and a kept row keeps its pictures the sprint's after retention (ADR-console-036 D5). A brief or a report with no pictures logs exactly the row it logged before. `sprint recap` shows the parts only, not the pictures.

**D3. Order.** A brief is refused in this order: the sprint is not open, then the secret, then the six parts, then the picture list's shape, then each picture's ownership and presence. A report is refused in this order: the sprint is not open, then the secret, then not started, then the seven members, then the list's shape, then each picture's ownership and presence. Every refusal appends nothing and touches no picture's age. The presence check reads the store and changes nothing, and it runs under the ingest lock that every retention sweep also holds.

**D4. The commands.** `sprint brief` and `sprint report` take a `file` for each picture. They check the request locally, check the whole request's size, read every file, ask the console for a dry run (`"dry_run": true`, answered `{"checked":true}`), upload each file in order, then send the brief or the report with each `file` replaced by the id the console returned. A refusal before the first upload leaves nothing uploaded. A picture refused while uploading stops the command before the brief or the report is sent; the pictures uploaded before it stay stored, named by nothing, until the sweep removes them.

**D5. The brief card.** Its thumbnails close its parts, in the shared gallery of ADR-console-038 D3, and open the same viewer. A newer version of the brief closes an open viewer.

**D6. The report.** Its thumbnails sit in its Detail fold after its next step, only while the sprint shows its report, and nothing else in the Work column changes. A newer report closes an open viewer.

**D7. Upkeep.** After every redraw of the page, one step keeps a focused thumbnail's focus, closes a viewer whose card left, and revokes unused object URLs.

**D8. Read-back.** A logged list that fails the read-back folds as none: the brief or the report shows no pictures, and nothing else about it changes.

## Consequences

- ADR-console-013 and ADR-console-014 are amended: a brief and a report may carry pictures, and their rows keep them.
- ADR-console-038's D3 rule that the Work column is untouched gains one exception, the thumbnails of D6 in the report's Detail fold.
- A manager's contract names `pictures` in its brief and its report; one that carries none is unchanged.
- Related: ADR-console-013, ADR-console-014, ADR-console-036, ADR-console-038.
