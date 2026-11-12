# ADR-console-016 — What the owner says to a sprint reaches its manager

- **Status:** accepted
- **Decided in:** #831, #834, #835, #889

## Context

ADR-console-013 carried a manager's brief to the page and the owner's approval or change request back, but left the manager to ask for it: nothing was pushed to the manager, and the owner had no way to say anything else to a sprint. #835 decided that a sprint has one manager and that the console talks to it; #834 decided that the owner can always answer in their own words. #831 found how a running background session can be reached (a print-mode relay that sends to it by session name arrives verbatim, new turn when idle, between tool calls mid-turn) and how a stopped one is woken in place with its saved mode, name, settings and model, and that `--resume <id> --bg` on a running session starts a copy instead. This slice stores what the owner says, tells the manager to read it, and shows the owner where each message stands.

## Decision

**Messages are stored first.** A message is an approval, a change request or free text, and its id is the sequence number of the row that carries it. The approval and the change request are the `brief.approved` and `brief.replied` rows ADR-console-013 already writes, a stale row making no message; free text is a new `sprint.messaged` row, so no row is written twice. `sprint.messaged`, `sprint.read` and `sprint.answered` are kept kinds like the brief rows, and the store moves to schema 6 (ADR-console-009). `sprint.nudged` is not kept, like the manager rows of ADR-console-015: a nudge is an observation. A stored message is never reported unsent: a nudge that cannot be dispatched is recorded as a failed nudge and the write still answers `204`.

**The manager reads, the nudge only points.** `sprint inbox` returns every unread message in id order, once, and in the same locked section records that they were read. `sprint reply --message <id> --reply-file <path | ->` sends what the manager changed, kept exactly as `sprint status` keeps a reply (non-empty, at most 2000 characters); a later reply to the same message replaces the shown one, and every row is kept. The nudge is one fixed sentence that tells the manager to run `sprint inbox`; it carries none of the owner's text, so the owner's words travel only through the inbox, which authenticates with the sprint's secret.

**The route rule.** At nudge time the console reads a fresh, process-validated session listing. A session named `<project id> sprint <sprint id>` that is listed is running and gets a relay: a short `claude -p` session on the manager's profile that sends the sentence to that session by name through `SendMessage` and succeeds only when it exits 0 and prints `SENT`. Otherwise the session id learned from `session.seen` rows is woken in place with `claude-account run --resume <id> --bg <sentence>` inside the `systemd-run --user --scope` of ADR-console-015, never for a listed session, because `--resume --bg` on a running session copies it. With neither, the nudge fails without a command. A nudge is sent only while the sprint's manager row is `started` and the host has a nudger, which is Linux; otherwise the message waits and the manager reads it at the start of its first turn.

**Re-nudge and unreachable.** A stored message nudges at once. The session poll re-nudges a started sprint that has an unread message never delivered, at least a minute old, with no nudge in the last minute and fewer than two failures in a row. Two failed nudges in a row make the sprint read "manager not reachable" with its messages kept; a successful nudge or a read resets the count, and no automatic nudge follows two failures until a new message.

**Routes.** `POST /api/message` is a page write under ADR-console-008: it carries the sprint id and the owner's text and answers an empty `204` once the row is stored. `POST /api/inbox` and `POST /api/message-reply` are the manager's writes under ADR-console-013, guarded by the sprint's secret, refusing any `Origin`, and dispatched before the page writes like `POST /api/brief`.

**The page.** A sprint line has a "Tell the manager" field. Each message shows sent (stored), delivered (a nudge reached the manager) or read (`sprint inbox` returned it), with the manager's reply under it; the ten newest are shown, oldest first. The digest says nothing about messages.

**The contract.** The manager's contract gains an every-turn section (start with `sprint inbox`, answer each message with `sprint reply`) and an after-approval section (check `sprint status` before each batch, end the turn before any tracker action once the sprint is no longer open, report after each batch, and answer a scope change with a new brief). The contract is not in the instruction corpus (ADR-console-015), so there is no Instruction Budget raise.

## Consequences

- ADR-console-013's "Nothing is pushed to the manager yet" no longer holds: a stored message reaches a started manager without its asking.
- A sprint more than 90 days old may lose its `session.seen` rows, and so its session id, and its nudge rows on restart: a wake then fails, and two failures read manager not reachable. The messages stay.
- A relay costs one short print-mode session on the manager's profile.
- macOS sends no nudge: a message waits as sent until the manager's next turn reads it.
- A verification check that states a real goal must stop its test manager before withdrawing the sprint, because a withdrawal removes the secret and does not end the session.
