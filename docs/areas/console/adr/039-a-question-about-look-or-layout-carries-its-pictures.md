# ADR-console-039 — A question about look or layout carries its pictures

- **Status:** accepted
- **Decided in:** #1092

## Context

ADR-console-038 lets a manager's question carry pictures, but nothing made it use them: a manager could still ask the owner to "judge the screenshots in <folder>" and attach none, leaving the owner unable to answer from the page. ADR-console-019 already refuses a malformed round with the first bad member named; this decision adds one more malformed shape.

## Decision

**D1. The contract.** The manager's contract (`manager-contract.md`, what `sprint contract` prints) says that a question about look or layout carries its pictures, each with one line saying what to look at, and shows the `pictures` shape. The contract is not part of the instruction corpus (ADR-console-015), so the change needs no Instruction Budget raise.

**D2. The refusal.** The console refuses a round in which a question's ask or its context names screenshots, a `.png` file or a folder with a `screenshots` segment and the question carries no picture. "Names screenshots" is the word screenshot or screenshots in any case, also written "screen shot". The refusal is the ADR-console-019 refusal: the first such question is named by its number and its ask, with the reason and the way out, "attach the pictures with pictures, or reword it", and nothing is appended for a refused round. A question that carries one picture, and a question that names none of these, are accepted.

**D3. Where it applies.** The rule is part of the ask route's own checks, after the question's pictures are read. A round read back from the log is not checked again, so a row logged before this decision still folds whole. `sprint ask` applies the rule to the whole round before uploading anything when it has files to upload, and its early check of the round with the `file` members left out skips the rule, because those members are the pictures that question carries.

## Consequences

- ADR-console-019's refusal of a malformed round and ADR-console-038's question pictures are extended, not changed: a round that names nothing to look at is unchanged.
- The rule is a text match, so a question that mentions a screenshot it does not need shown is reworded or given a picture; it is a guard for the manager, not a judgement of the question.
- Related: ADR-console-015, ADR-console-019, ADR-console-038.
