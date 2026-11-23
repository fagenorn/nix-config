# ADR-console-093 — The owner deletes a question thread, and the Ask box refuses a credential

- **Status:** accepted
- **Decided in:** #1272

## Context

A project question and its answer are kept in the console's log for 90 days (ADR-console-001), and a follow-up carries its thread's earlier turns into a new session (ADR-console-062). An owner who pasted a password, token or key into the Ask box had no way to take it back: the text stayed in the log, in the published view and in every later follow-up of that thread. ADR-console-001 lets only the retention pass delete a row.

## Decision

**D1. A credential-shaped question is refused first and nothing of it is kept.** A question whose text looks like a password, token or key is refused before every other check, before a request-key replay and before any row is written, and the refusal does not repeat the text. One list, `project_question.CREDENTIAL_SHAPES`, holds the shapes, and a follow-up whose thread already holds such a turn is refused too. The list is a detector of known shapes, not a guarantee: a secret in a shape it does not name, or one split across words, is not caught, which is why D2 exists.

**D2. The owner deletes a thread.** `POST /api/project-question-delete` is a page write, so owner-only, and names a registered project and one of its threads. The asked and answered rows of every question of the thread are removed in one transaction, their database pages zeroed (`secure_delete`) and the published view dropping the thread, and one `project_question.deleted` record is written that holds only the project, the thread id and the question ids. The record is kept forever, and it is the single exception to ADR-console-001's rule that only the retention pass deletes: the log's delete trigger lets a row go when such a record names its question id.

**D3. A thread being answered waits for its answer.** A thread any of whose questions has a running session is refused, so a session cannot write an answer to a thread that was deleted under it. A question left working by a crash has no running session and can be deleted.

**D4. What stays.** The `project_question.keyed` receipt stays, so a keyed re-send of a deleted question returns its id and starts no session. The session's own transcript outside the log stays. The session's spend stays under Questions until the console restarts: the spend fold keeps the session until a restart rebuilds it from the surviving asked rows, after which it is not known to the log, as after retention.

## Consequences

- A pasted secret can be taken out of the console's log and view by deleting its thread, but not out of a transcript the session wrote elsewhere, nor out of anything the owner's account already received.
- The log holds one small record per deleted thread forever, with ids and no text.
- Amends ADR-console-001, ADR-console-008 and ADR-console-058.
- Related: ADR-console-062, ADR-console-089.
