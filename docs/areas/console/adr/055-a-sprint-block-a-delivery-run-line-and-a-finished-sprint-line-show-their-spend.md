# ADR-console-055 — A sprint block, a delivery run line and a finished sprint line show their spend

- **Status:** accepted
- **Decided in:** #1136

## Context

ADR-console-052 gave the owner a Spend page, but the desk page, where the owner watches a sprint or a delivery run, shows nothing of what that sprint or run has cost. The owner has to leave the desk, find the item in the breakdowns and read a row. The desk page must stay quiet, so the figure is one small line, and the page that holds the detail is one link away.

## Decision

**D1. The figure.** A figure reads `<count> tokens, about $<dollars>`: the count is input, cache writes, cache reads and output summed over every day of the view's 30-day spend window, in the Spend page's short form (the integer under 1000, else one decimal with a trailing `.0` dropped and `k`, `M` or `B`), and the dollars have two decimals and thousands commas. It is a link whose title is `Estimated at API list prices`, with `, approximate` added when any part is priced approximately.

**D2. No figure.** An item shows no figure when the view has no `spend`, when no day holds its id, or when its summed tokens are 0. The key `unattributed` never names an item.

**D3. Placement.** A running sprint block draws the figure as its own quiet line in Overlay 2 under its head, and the block's state lines are unchanged. A delivery run's line ends in its figure when its project line (or an unmanaged repository's line) is opened. A finished sprint's figure is the first line of its opened report, before the closing report. A figure is never drawn inside a fold's `summary`, because a link there is interactive content nested in the control that opens the fold.

**D4. Link.** The figure links to `/spend#sprint=<id>` or `/spend#run=<id>`. The Spend page reads the fragment on every render and when it changes, and draws that item above the summary: its heading, its 30-day total and its phase breakdown, sorted by estimated dollars. The total is summed from the item's own entries, the entries the desk figure sums, so both pages show the same cents. A sprint's own manager-session spend is the phase `manager`. An item with no spend says so. A fragment that is neither form, or does not decode, draws nothing. The fragment adds no request.

**D5. View members.** Each spend day gains `sprint_phase` and `run_phase`, each mapping an item's id to its tokens by phase, only for attributed items. A sprint's spend that is not an agent's is phase `manager`. An item's phases sum to its entry of that day in every count field, and in dollars to rounding.

**D6. Frames.** The figure is drawn again with its line on every frame. Open folds and a focused field survive through the page's existing restore.

## Consequences

- This amends ADR-console-002: the Sprints and Projects rules name the figure and its place. It amends ADR-console-052: the Spend page gains the item section for a `#sprint=` or `#run=` fragment.
- The figures are ADR-console-049's estimates, so they are estimates, and the desk page shows none until the first spend poll ends.
- The desk page gains one link target and no write: ADR-console-008's write set is untouched.
- The page change changes what the owner sees, so before and after pictures at 1440 px and 480 px go to the owner on a question card, and the change merges only on the owner's answer.
