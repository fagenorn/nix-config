# ADR-console-062 — A follow-up carries its thread in its prompt and continues only an answered thread

- **Status:** accepted
- **Decided in:** #1178

## Context

ADR-console-058 gave the console a read-only question session and ADR-console-059 D4 decided that a follow-up continues its question's thread: its session receives the thread's earlier questions and answers under the same read-only rules, model and cap, and threads are rows of the console's event log only. This ADR records how a follow-up is admitted, recorded and launched, and what it refuses.

## Decision

**D1. A follow-up names its thread and carries it in its prompt.** `POST /api/project-question` takes an optional non-empty string `thread_id` beside `project_id` and `question`; a body with any other member, or a `thread_id` that is not a non-empty string, is 400 `bad question`. The follow-up's `project_question.asked` row adds exactly `thread_id`, and the session gets the thread's earlier questions and answers as turns in its prompt, between the routes paragraph and the question. Nothing else about the session changes: its routes, model, flags, settings document and cap are a first question's (ADR-console-059 D3). A thread is a log fold, never a session: `--resume` is refused, because a follow-up may run under another profile than the question it continues and the console's log, not a client transcript, is the thread's home (ADR-console-001).

**D2. Only an answered thread is continued.** A follow-up is refused, appending and counting nothing, when its `thread_id` is not a thread of that project's folded questions (`THREAD_UNKNOWN`) and when the thread's last question is not answered (`THREAD_UNANSWERED`): a working question has no answer to carry, and a failed or timed-out one has none either, so the owner asks a new question. The checks run under the ingest lock after the question's own checks and before the profile choice.

**D3. The thread is bounded in bytes.** The prompt is one argument string, and Linux refuses to start a program whose single argument string exceeds `MAX_ARG_STRLEN`, 131072 bytes. `MAX_THREAD_BYTES` bounds the thread's text plus the new question in UTF-8 bytes below that, with room for the lead, the routes paragraph and the question mark; a follow-up past it is refused `THREAD_TOO_LONG` and the owner asks a new question. The oldest turns are never dropped to make a thread fit, since a silently shortened thread would answer from context the owner cannot see.

**D4. Admission reads what the log still holds.** The folded questions a follow-up is checked against are rebuilt from the retained log by a retention pass that removed rows, inside the same ingest-lock section and beside the other folds, as a restart builds them. A follow-up to a thread whose first question retention removed is therefore refused `THREAD_UNKNOWN`, a thread's remaining questions group as a restart would group them, and a running console and a restarted one never disagree about a thread (ADR-console-009).

## Considered Options

- `--resume` of the earlier question's session: no transcript to rebuild, but it ties a follow-up to the profile that holds the transcript, to a session the question's settings file and `--session-id` do not describe, and to a store the console does not own.
- A follow-up after a failed or timed-out question: it would continue a thread with a missing answer, so the session would be told a question it never answered.
- Dropping the oldest turns to fit the bound: the follow-up would always be admitted, but its context would silently differ from the thread the owner reads.

## Consequences

- A thread's follow-ups run under the profile the console chooses for each, not necessarily the profile of the question they continue.
- A follow-up costs a prompt as long as its thread, up to `MAX_THREAD_BYTES`.
- A follow-up whose root retention removed becomes its own thread, and each such kept follow-up can be continued as one when answered; the remaining questions do not group among themselves.
- The asked row's payload gains an optional `thread_id`; the schema stays 10 and the spend fold reads only `session_id` and `profile`.
- Related: ADR-console-001, ADR-console-058, ADR-console-059.
