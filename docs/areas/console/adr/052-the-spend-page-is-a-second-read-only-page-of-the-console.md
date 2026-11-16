# ADR-console-052 — The Spend page is a second, read-only page of the console

- **Status:** accepted; amended by ADR-console-053
- **Decided in:** #1135

## Context

ADR-console-049 keeps the host's spend in the console's view, but the owner has no way to see it. The desk page tells the owner whether they are needed and should stay that; a page of figures does not belong on it. The console served one page until now.

## Decision

**D1. Route.** `GET /spend` serves `spend.html` from memory, on loopback only, with the desk page's content security policy. The page carries no token and sends no write; its only request is the `/api/stream` EventSource. ADR-console-008 is unchanged: the page writes are still exactly the members of `PAGE_WRITES`, all made by the desk page, and the Spend page adds none. This amends ADR-console-001: the console serves two pages, the desk page and the Spend page. The read-only statement is about the Spend page and its route; it claims nothing about the console's other endpoints.

**D2. Links.** The desk page's top bar carries one quiet "Spend" link after the name. The Spend page's top bar carries the name and a "Desk" link back. This amends the Structure of ADR-console-002.

**D3. Spans.** The page offers Today, 7 days and 30 days, with 7 days chosen by default. The summary shows Today and the chosen span, with the tokens shown apart as input, cache writes, cache reads and output. Days are the view's UTC days (ADR-console-049 D6), named "Today" or by weekday, day and month, never a raw date.

**D4. Trend.** The trend has one point per day of the span, oldest first. In the 30-day span only the first and last labels show; each point's title names its day and figure.

**D5. Breakdowns.** The page breaks the span down by project, sprint, phase, account and aspect, each sorted by estimated dollars. "unattributed" is its own row. A sprint is named by its title in the view, else "sprint" and the first eight characters of its id. The aspects read Managers, Deliveries, Outside-sprint sessions and Keepalive pings. A `#sprint=<id>` or `#run=<id>` fragment opens that item above the summary with its 30-day total and phase breakdown, adding no request (ADR-console-053).

**D6. Estimates.** Every dollar figure reads "~$" with the title "Estimated at API list prices", and the page says "Dollar figures (~) are estimates at API list prices." A figure that is priced approximately adds "approximate".

**D7. Design.** The page uses ADR-console-002's palette roles with no new role, never Peach and no state colour. State is never colour alone: the chosen span carries `aria-pressed` and a Lavender border. The page fits 1440 px and 480 px with no horizontal scroll, shown by the `spend-page` state of `just console-screenshots`.

## Consequences

- ADR-console-001 now describes two pages, and ADR-console-002's top bar has a link; both name this record.
- ADR-console-008's write set is untouched: a request to `/spend` other than GET is refused as for any route outside the write sets.
- The figures are ADR-console-049's, so they are estimates, and the page shows nothing until the first spend poll ends.
- The page changes what the owner sees, so before and after pictures at 1440 px and 480 px go to the owner on a question card, and the pull request merges only on the owner's approving answer.
