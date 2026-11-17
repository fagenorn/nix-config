# ADR-console-059 — A project question is spent under its project, threaded in the log and can fill a goal

- **Status:** accepted
- **Decided in:** #1180

## Context

ADR-console-058 gave the console a read-only question session, but the Spend page counted its tokens as an outside-sprint session's, and the console's docs recorded nothing of the rest of the milestone that lets the owner ask a project a question (#1176 to #1180): the Ask box, follow-ups and turning an answer into a goal.

## Decision

**D1. Questions are a spend aspect.** A question session's own and subagent transcripts are the aspect `questions` on the Spend page, read from the transcripts like every other session's (ADR-console-049). Its project is the project of its working directory, as for any session. The Spend page labels the aspect Questions and still only reads (ADR-console-052).

**D2. A question names its session.** The console gives every question a fresh UUID, records it as `session_id` in its `project_question.asked` row and passes it to the session as `--session-id`; this amends ADR-console-058 D2. The spend fold maps that id to the row's profile, so the session's spend is a question's, and its account is that profile when no `session.seen` or `session.profile` row names one. No spend is written to the log (ADR-console-049 D1).

**D3. The session is unchanged.** The read-only session and its enforcement, the declared read-only commands, the `sonnet` model, the 300 s cap, the answer's shape and the two log rows stay as ADR-console-058 decides. Nothing about a question reaches a tracker (ADR-console-011), and a question is not an inbox item and changes no count (#1177).

**D4. Threads live in the log.** A follow-up continues its question's thread: its session receives the thread's earlier questions and answers under the same read-only rules, model and cap. Threads are rows of the console's event log only (ADR-console-001). A project's past threads are a closed "Questions (n)" fold, newest first, that counts in nothing needing the owner (ADR-console-002). #1178 builds it.

**D5. An answer can fill a goal.** Make it a goal, on an answered question, fills its project's goal box with the question and the answer's plain-words summary, never the answer's command output, and states nothing: the owner edits it and states it as any goal (ADR-console-011, ADR-console-015). #1179 builds it.

## Considered Options

- Naming the session with `--name`, as the manager is named: whether the pinned client writes a name record for a `-p` run is unconfirmed, and a missing record would silently count questions as outside-sprint sessions.
- Matching the prompt's lead in the transcript: no new argument, but it reads message text and breaks whenever the lead changes.

## Consequences

- A question asked before this change has no `session_id`, so its spend stays an outside-sprint session's.
- The question sessions are folded into memory from the log's rows; retention removes a row after 90 days, past the 30-day spend window.
- The Ask box landed with #1177; follow-ups (#1178) and Make it a goal (#1179) are built by their own issues.
- Related: ADR-console-001, ADR-console-002, ADR-console-011, ADR-console-015, ADR-console-049, ADR-console-052, ADR-console-058.
