# ADR-console-092 — A consequential card opens with nothing picked

- **Status:** accepted
- **Decided in:** #1265

## Context

A fresh look card was seen with "Approve this head" already picked, so one stray Enter could give an approval the owner never chose. ADR-console-019 and ADR-console-072 D5 preselect the recommended option on every question card. ADR-console-074 D2 only kept the approving option of a look card unpicked, so a look card whose recommendation was another option still opened picked.

## Decision

**D1. A question may be marked consequential.** A round question may carry `consequential: true`. The key is optional and absent is today's behaviour, so existing managers keep working. It is not implied by `owner_only`: whether only the owner may answer and whether the card opens unpicked are separate questions.

**D2. A look card is consequential without the mark.** Every look card, a question with a `look` or one carrying a before and an after picture, is consequential whether or not the manager marked it. The console passes the mark to the card.

**D3. A consequential card opens with no option picked.** Send answer is unavailable until the owner picks an option or types words. The Recommended badge stays, and an option the owner already chose still shows. This amends ADR-console-072 D5 and ADR-console-074 D2.

**D4. Tracker decision prompts keep their preselection.** The owner-action decision prompts of ADR-console-010 are not a sprint question and are unchanged.

## Consequences

- A consequential card costs the owner one more click.
- A manager that never marks a question keeps today's cards, except a look card, which now never opens picked.
- Related: ADR-console-010, ADR-console-019, ADR-console-072, ADR-console-074.
