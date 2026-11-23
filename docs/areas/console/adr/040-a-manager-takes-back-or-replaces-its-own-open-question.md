# ADR-console-040 — A manager takes back or replaces its own open question

- **Status:** accepted
- **Decided in:** #1099

## Context

ADR-console-019 lets a manager send a round of questions and refuses a second round while one is open. A manager that wanted to fix a question (add the pictures it forgot, reword it, change an option) had no way to do it: asking again was refused, or, in a blocker round, left the stale card beside the new one, and the owner could answer the stale copy. The owner's rule is that a manager withdraws or replaces its own question, the act is logged, it reaches only its own sprint, and the card goes from the page without a page change.

## Decision

**D1. A kept kind and schema 9.** A withdrawal is one `question.withdrawn` row with `sprint_id`, `goal`, `round`, `index` and `question`. The kind is a kept kind (ADR-console-001), because `questions.asked` is kept and a withdrawal the retention pass dropped would bring the question back as open after 90 days. Adding a kept kind is a schema step, as every earlier one was: the event log is at schema 9 and a store at schema 2 to 8 is migrated in place, keeping every event. An older build refuses a store migrated to schema 9, the same one-way step ADR-console-001 took before.

**D2. A replacement is the replacing round's one row.** A question of a round may carry `"replaces"`, an object of the `round` and the `index` of an open question of the same sprint. It is logged on the replacing `questions.asked` row, and the sprint fold withdraws the named question while folding that row. The round and the withdrawal are one write, so no `question.withdrawn` row is appended for a replacement and the owner never sees both cards.

**D3. The index counts from 0.** The `index` of a withdrawal and of `replaces` is the logged index of the question in its round, the one in the question's inbox key and in a round answer. It counts from 0: the first question of a round is 0.

**D4. The route.** `POST /api/withdraw-question` is a manager write under the sprint's secret (ADR-console-013, ADR-console-019), listed in ADR-console-008 beside `POST /api/ask`. Its body is `sprint_id`, `secret`, `round` and `index`, at most 4096 bytes. Any `Origin` is refused, as for every manager write: a page does not take a manager's question back. It is not `POST /api/withdraw`, which is the owner's withdrawal of a goal. A withdrawal nudges nobody.

**D5. What is refused.** A withdrawal or a `replaces` mark is refused, with the reason and nothing appended, when the question is unknown, when it is answered already, when it is withdrawn already (`this question is already withdrawn`) or when it is another sprint's question (`this question belongs to another sprint`). A sprint takes back only its own questions. A `replaces` mark that is not an object of round and index, or a second question of the round naming the same question, is a malformed round and is refused with the first bad member named (ADR-console-019).

**D6. Another sprint's question.** A round and index that is not one of the manager's sprint's questions but is a question of another sprint the console folds is another sprint's question; any other is unknown. A sprint whose goal was withdrawn is no longer folded, so its question reads as unknown.

**D7. The one-open-round rule.** The rule of ADR-019 and ADR-027 does not count a question the new round replaces: a round that is not a blocker is refused only when an open question the round does not replace remains. A replacement that leaves another question of the open round open is still refused.

**D8. The digest.** Each event gives one moment: `The manager of <title> took back a question: <ask>` for a withdrawal, and `The manager of <title> replaced a question: <ask>` for a round that replaces one, `The manager of <title> replaced <n> questions` for more. A withdrawal the sprint fold ignores says nothing.

**D9. The page is unchanged.** `page.html` draws an inbox card only from the question list of the view, and the sprint fold leaves a withdrawn or replaced question out of its open questions, so the card, the waiting count and the sprint's end all follow without a page change. An answer state whose card left the view is dropped by the page already.

**D10. An answer to a taken-back question is refused.** The owner who answers a question the manager took back is refused with `the manager took this question back`, and no message is stored. The check comes before the check that the sprint has ended, because withdrawing the last open question of a sprint with a done report ends the sprint, and the owner must still read why.

**D11. No Instruction Budget raise.** The manager's contract says to replace a question rather than ask it again and gives `sprint withdraw-question`. The contract is outside the instruction corpus (ADR-console-015), so the change needs no Instruction Budget raise.

## Consequences

- ADR-console-019's one open round and refusal of a malformed round are extended, not changed: a round that replaces nothing behaves as before.
- A store at schema 9 is not readable by an older build, so a rollback of the console needs the store of the older schema.
- A withdrawn question stays in the log for good, so what the manager took back is never lost to retention.
- Related: ADR-console-001, ADR-console-008, ADR-console-015, ADR-console-019, ADR-console-027.
