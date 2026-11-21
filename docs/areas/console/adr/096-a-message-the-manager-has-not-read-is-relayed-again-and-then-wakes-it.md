# ADR-console-096 — A message the manager has not read is relayed again and then wakes it

- **Status:** accepted
- **Decided in:** #1379

## Context

ADR-console-016 relays a stored message to a running manager once and re-nudges only a message that was never delivered. On 20 Nov an answered question card was relayed to an idle manager and sat unread for 30 minutes, until stopping the session made the console bring back one that read it. A relay the client reports sent proves the sentence reached the session, not that the manager acted on it, and `--resume <id> --bg` cannot be sent to a session that is still running, because it starts a copy.

## Decision

**D1. Once more, then a wake.** A message the manager has not read (`sprint inbox` has not returned it) five minutes after the last relay that reached it is relayed once more. Still unread five minutes after that second relay, the manager is woken in place. There is never a third relay. A message read meanwhile gets nothing further, and a message any wake reached gets no escalation.

**D2. Five minutes each.** Both waits are five minutes (`sprints.UNREAD_AGAIN_MS`), counted from the last relay that reached the message, and every step also waits five minutes after a failed nudge attempt. A message already relayed twice keeps both counts, so later messages and their relays never move its wake. Five minutes is when the page already reads "not picked up after 5 min" and the idle time of ADR-console-020. A manager that acts on a relay reads within seconds, and the longest wait from a message to a wake is ten minutes.

**D3. The wake stops a listed manager first.** The wake is the one a gone manager gets: the manager's own session resumed in place with the fixed inbox sentence, its settings file written again and passed when its record is gone (ADR-console-016). A manager the running listing still shows is first stopped through the console's stopper, the same call a stop uses. Only the one session the wake resumes is stopped: a replacement session, a second one or one on another profile stops nothing. It is woken only when a fresh, conclusive listing taken just before the send no longer shows it, and a message the manager read meanwhile ends the wake before the stop. A session still listed after the stop, a host with no stopper, a stop that fails and a wake that fails are failed attempts on the sprint's `sprint.nudged` row with route `wake`. They count toward "manager not reachable" as every failed nudge does, and no wake is sent. A listed manager that is not idle, by a fresh listing or by its hooks, is neither stopped nor woken, and that poll records nothing. That covers a manager that is working and one waiting at a permission or answer prompt: it cannot read its inbox until the prompt is answered, and a stop would lose the pending prompt.

**D4. No new rows.** The count of relays that reached each message, the last one's time and whether a wake reached it are folded from the `route` of the existing `sprint.nudged` rows. The store's schema and kept kinds are unchanged.

**D5. The sprint line.** While a delivered message is unread, a sprint with nothing more pressing to say reads "waiting for the manager to read your message".

## Consequences

- An unread message costs at most one more print-mode relay and one stop and resume of the manager's session.
- A stopped manager that is woken resumes its own conversation, not a new one. A stop whose session takes longer to leave the listing is a failed attempt, retried five minutes later; the bring-back of ADR-console-017 may wake the stopped session first, with its own sentence.
- Amends ADR-console-016 ("Re-nudge and unreachable": a delivered message is now followed up).
- Related: ADR-console-017, ADR-console-020.
