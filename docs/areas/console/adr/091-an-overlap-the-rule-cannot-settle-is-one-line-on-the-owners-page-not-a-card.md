# ADR-console-091 — An overlap the rule cannot settle is one line on the owner's page, not a card

- **Status:** accepted
- **Decided in:** #1347

## Context

ADR-console-085 ordered two overlapping claims by a default rule and left one overlap, two fixes of a live fault, to the owner as a question card from one asking sprint (D4, D5). The page showed no overlap line, so the owner met the overlap only as a card, and the sprint named by `asks` held its slice until the owner answered. A card is a question with a go-ahead the owner must grant; this overlap needs no permission, only an order the owner may want to state.

## Decision

**D1. The page shows an unsettled overlap as one line.** Under its two sprints the owner's page shows each reading whose `rule` is `unsettled` as one line, and a settled reading (`earlier-started` or `live-fault`) as none.

**D2. No card.** Neither sprint sends a `sprint ask` card about an unsettled overlap and neither holds a slice for an answer: both keep working, the slice that lands second rebases on the first, and a `heads-up from the owner` that states which lands first is followed.

**D3. `asks` leaves the reading.** The overlap reading carries the two claims, the files, `first` and `rule`; with no card there is no asking sprint. The manager's own overlap line for an unsettled overlap says the rule cannot order them and asks nobody.

**D4. The line follows the open claims.** The reading is made from open claims only, so the line goes when either claim is withdrawn or ends (ADR-console-085 D2).

## Considered options

- Keeping the card for the one sprint named by `asks` (ADR-console-085 D5): the owner answers a question whose answer grants nothing, and the asking sprint stops until then.
- Showing no line at all: the owner would not see an overlap the rule cannot order, and could not post the order a heads-up states.
- A card from the page instead of the manager: still a card, and a second source of the same question.

## Consequences

- Amends ADR-console-085 D4 (the reading's `asks` member) and D5 (one asker, the owner-only card, and the clause that the page shows no overlap line until #1347).
- Amends ADR-console-046 D6 (an overlap goes to the owner as a card): it reaches the owner as a page line.
- Amends ADR-console-066 D3: "proceed over another sprint's claim" leaves the list of go-ahead actions a manager marks `owner_only`; the rest of D3 stands.
- Rollback: reverting restores the card, the `asks` member and that go-ahead in the list.
- The manager contract changed outside the instruction corpus (ADR-console-015, ADR-console-044 D10), so no Instruction Budget raise is needed.
