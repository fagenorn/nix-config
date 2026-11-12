# ADR-console-010 — The page answers a decision prompt by ticking its box as the owner

- **Status:** accepted
- **Decided in:** #836, #838, #862

## Context

The console sends the owner to the tracker to answer a decision prompt, and half the time the owner accepts the recommendation, so the trip is a tick and a return. The prompt is already a tracker comment whose boxes a delivery reads (ADR-console-003), and the page already makes one guarded write (ADR-console-008). #862 lets the page answer an inbox item that was born on the tracker, without the console becoming a second record of the answer.

## Decision

The item answered is an open decision prompt born on the tracker. The page holds an undo of five seconds and only then sends `POST /api/answer`, a page write under ADR-console-008, with the project, the item key and one chosen option index per question.

The console checks that the parent issue or pull request is still open, re-reads the live trusted marker, and refuses a closed parent or a changed, ended or already answered prompt. It then edits the comment through `gh` so exactly the chosen box under each question is ticked, as the owner, through their own `gh` sign-in (the console passes no token). The tick is the whole write, and nothing is copied anywhere else: the tracker stays the record, and a delivery reads the tick as before.

The console then appends one `inbox.changed` marking the item answered, so it leaves the count at once and leaves the list when the marker is no longer live. A read that began before an answer does not reopen it.

The marker may name a recommended option in `rec=<n1>.<n2>...`, one index per question, written from the planner's recommendation, which is only a hint: a recommendation that matches none of the question's options is dropped by the poster (that question records `0`) and never blocks the prompt; the page opens with the recommended option selected. The keys go to the first answerable decision item wherever it sits, unless a brief is waiting, which takes them first (ADR-console-013), and a pending send keeps its Undo wherever the list moves it. No free-text reply is offered.

## Consequences

- A page closed inside the undo sends nothing.
- A prompt whose poster named no recommendation opens with nothing selected.
- A refused tick is reported to the page and written as one stderr line with the tracker's reason, and the event log records nothing of it.
- The console may now write to the tracker, but only a tick of a box the owner chose, behind the token and origin guard.
