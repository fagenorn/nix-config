# ADR-console-060 — A manager that fails to start is a card with its reason and Retry

- **Status:** accepted
- **Decided in:** #1182

## Context

On 16 Nov a sprint's first launch was refused with the client's words, "Workspace not trusted. Run `claude` in the project folder once and accept the trust prompt, then retry." The owner's desk showed a small red line inside the sprint block, the ball read "nothing running, may be stuck" and nothing asked the owner for anything, so the sprint sat for 45 minutes. A failed first launch has no brief behind it and no session to watch; only the owner can mend it, by trusting the folder or retrying, so it must be a card and not a line to find. ADR-console-015 made the failure a state inside the sprint with a retry, ADR-console-042 D4 gave it the ball "nothing running", and ADR-console-002 kept cards for a stall, progress and sign-in; none of them put the owner's attention on it, and the reason was the client's raw text, with host paths in it.

## Decision

**D1. When the card shows.** A sprint has the card exactly when `sprints.failed_start` reads true, the one rule ADR-console-015 gave the block's Retry and the service's retry gate: `manager_status` reads `failed` with retry offered, the manager row is not a takeover's, the sprint has no brief, none of its sessions is listed, it is not stopping, it is not in a stall and managers are available on the host. A later `manager.started` or waiting row, a withdrawal, a brief, a listed session of the sprint, a stop or a stall removes it. The card, the block's Retry and the retry gate therefore never disagree.

**D2. Plain reasons.** The view never shows a failure as the client or the console wrote it. `manager.plain_reason` maps it to a closed set, a case-insensitive substring table in order, first hit wins: "this account does not trust the project's folder", "a program the manager needs is missing on this host", "the launch did not answer in time", "the project's folder is missing", "the console could not write the manager's settings", "the sprint's secret is missing", "managers are not available on this host yet", and for anything else, `None` included, "the client refused to start the manager". The raw reason stays in the `manager.failed` log row and the journal line `console: manager_failed`, and only there. The block's `manager_text` reads `could not start a manager: <plain reason>` for every failed row.

**D3. The line and the ball.** While the card is open the sprint's one line reads `waiting for you: the manager failed to start` and its ball is the owner's, so the sprint no longer reads "nothing running, may be stuck". Its `state` stays `drafting`, because revive and idle read it and no brief was approved. This amends ADR-console-042 D4 in the ball and the line, not in its movement rule.

**D4. The card.** It is an `inbox_item` with `reason: "failed_start"`, key `failed-start/<sprint id>`, `project_id`, `sprint_id`, `title`, the headline `The manager for <title> failed to start.` (one sentence: the title's own closing full stop, question mark or exclamation mark is dropped), `last_reason` the plain reason, `answered: false` and `waiting_since` the time the manager failed. It sits in `inbox.open` after the stall cards and before the progress cards, counts in `inbox_items` and the headline, and the view's sentence reads `Retry to start the manager, or drop the sprint.` after the stall sentence. The page draws the headline, the reason in plain words, "Retry" as the primary and "Drop the sprint" as the other action, like a stall card (ADR-console-019); a failed retry shows its failure on the card.

**D5. A stall keeps its own words.** A sprint whose managers keep failing has its stall card and its raw reason (ADR-console-019); the failed-start card never shows beside it. A failed takeover is a stall's business and adds no card.

**D6. Evidence.** The verify check `console-failed-start` is met by a correct card in the console's view, not met by a wrong one, and waits while none is open. The change also changes what the owner sees, so pictures of the `failed-start` state at 1440 px and 480 px go to the owner on a question card, and the change merges only on the owner's answer.

## Consequences

- This amends ADR-console-002: the Inbox rule names the card and its place. It amends ADR-console-015: a failure is also a card of its own. It amends ADR-console-042: a failed first launch with no brief is the owner's card, so its ball reads waiting on you and its line the failed start.
- The owner sees why a launch was refused, in plain words, without a path or the client's text; the raw text is in the log and the journal for whoever debugs.
- The page gains no write: Retry and "Drop the sprint" are the existing `/api/retry-manager` and withdrawal posts (ADR-console-008).
- Related: ADR-console-034 documents `Workspace not trusted` as the client's `--bg` refusal.
