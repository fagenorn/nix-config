# ADR-console-013 — A manager's brief is approved or redirected on the page

- **Status:** accepted
- **Decided in:** #834, #835, #836, #887

## Context

ADR-console-011 let the owner state a goal, and no manager existed to pick it up. #834 decided that the manager answers a goal with a brief (what done looks like, what is excluded, the slices, the risks and what it expects to ask), that the owner approves it to start the sprint, and that briefs live in the console's store and never on the tracker. #836 decided that anything waiting on the owner is an inbox item and that a reply in the owner's own words is always possible. #835 decided that a sprint has one manager and that a change of scope re-issues the brief. This slice carries a brief from the manager to the page and the owner's answer back.

## Decision

A manager uses the `sprint` command: `sprint brief` sends the brief and `sprint status` reads what became of it. The command validates nothing about the brief; the console decides, in one place.

`POST /api/brief` takes the sprint id, the sprint's secret and the brief. It is not a page write: it carries no token, and the sprint's secret takes the token's place. It refuses any `Origin` (a browser page is never the manager), and it refuses in this order: the sprint is not open, then the secret refused, then the first of the five parts that is missing or empty. A refusal records nothing, and the answer to a wrong secret is the one text `secret refused`, so a caller learns nothing about the secret.

`GET /api/sprint-status` answers a sprint's decision (`none`, `approved`, `changes` or `withdrawn`), its version and the owner's reply, and needs no secret. The secret is removed when a goal is withdrawn, so a manager whose sprint was withdrawn could no longer present it, and `sprint status` is exactly how it finds that out. The route reveals only what the owner decided about the manager's own brief, and loopback trust is the boundary for reads as for writes (ADR-console-008).

A brief has five parts: what done looks like, what is excluded, the slices, the risks and what the manager expects to ask the owner. Each one is required. A sprint's briefs are numbered from 1 (#835): a newer brief replaces the one before it, whatever became of it, and the sprint waits for the owner again.

A waiting brief is an inbox item. The page opens it with the goal above it, its version, and the five parts. `POST /api/approve` and `POST /api/reply` are page writes under ADR-console-008, each carrying the version the owner acted on. Enter starts the same undo as a decision prompt (ADR-console-010), five seconds in which Escape or Undo cancels it, and then approves; the reply field asks for changes instead. Each action is bound to the version shown when the owner acted, so a newer brief makes a late action refuse with the reason, and a newer version cancels an approval that is still waiting. A reply is kept exactly as typed, at most 2000 characters, and is what `sprint status` returns.

A waiting brief sits above every tracker item in the inbox, whatever their held work, and takes the keys before any decision prompt: Enter starts its approval. This narrows the key routing of ADR-console-002 and ADR-console-010, which still govern the decision prompts beneath it. A brief carries no "Answer on the tracker" link, since there is no tracker item to answer. Asking for changes cancels an approval that is still waiting, and neither action starts while the other is being sent, so the two opposing decisions are never both sent.

Approving makes the sprint "starting". The digest says "A brief for <project> arrived, version <n>: <goal>" and "The brief for <project> was approved, version <n>: <goal>"; a reply adds no sentence.

Brief rows (`brief.sent`, `brief.approved`, `brief.replied`) are kept indefinitely like goal rows, and the store moves to schema 4 to protect them (ADR-console-009).

## Consequences

- Nothing is pushed to the manager yet: it asks with `sprint status`.
- A withdrawal stays possible in every state, an approved sprint included, and it removes the secret as before.
- "Every sprint reads drafting" (ADR-console-011) no longer holds once a brief is approved: that sprint reads starting.
- A manager that holds the secret can replace a brief the owner has not yet answered, and the owner sees only the newest version.
- A waiting brief counts as one thing that needs the owner, so it moves the statement.
