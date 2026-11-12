# ADR-console-009 — Events are kept for 90 days, and only the retention pass deletes

- **Status:** accepted
- **Decided in:** #838, #861, #886, #887, #889, #891

## Context

ADR-console-001 made the event log append-only and left its growth unbounded until a later slice added the 90-day retention #838 decided. The page's digest of what changed since the owner last looked (#861) needs the log to stay bounded without giving up the guarantee that a raw connection cannot rewrite history.

## Decision

Events are kept for 90 days. The store records a retention cutoff in a one-row table, and the cutoff only moves forward: triggers refuse to delete, replace, duplicate or lower it. A trigger refuses every delete of an event that is not strictly older than the cutoff, so an event at the cutoff is kept, and a store whose cutoff row is missing deletes nothing. The retention pass is the one place that deletes: in one transaction it moves the cutoff to the clock minus 90 days and removes the events older than it, so a failure removes nothing, and sequence numbers are never reused. The console runs a pass at start and then daily. The pass never removes a goal row (`goal.stated`, `goal.withdrawn`), a brief row (`brief.sent`, `brief.approved`, `brief.replied`) or a report row (`sprint.reported`) or a message row (`sprint.messaged`, `sprint.read`, `sprint.answered`), because #838 item 8 keeps goals, briefs and reports indefinitely, and the delete trigger refuses a raw delete of any of them whatever its age. A schema 1, schema 2, schema 3, schema 4 or schema 5 store is migrated in place to schema 6 in one transaction and keeps every event. A schema 6 store is migrated the same way to schema 7, which adds the closing kinds (`sprint.closed`, `sprint.stop_requested`, `manager.stopped`) to the kept kinds (#892), and a schema 7 store to schema 8, which adds the two question kinds `questions.asked` and `question.answered` to the kept kinds (#891). A store at any other version is refused and left untouched.

## Consequences

- An inbox item that has waited more than 90 days gets a new "waiting since" after a restart, because the event that began its wait is gone.
- A project registered more than 90 days ago is registered again from the registry at the next read, and stays only while the registry is readable.
- A look older than 90 days counts as a first visit.
- The triggers stop accidents, not a local process that rewrites the cutoff: anything that can drop the triggers can also edit the file.
