# ADR-console-005 — In-flight delivery stage is read from run journals

- **Status:** accepted
- **Decided in:** #830, #837, #858

## Context

The console shows that a session works but not what it delivers: an owner cannot tell a run still planning from one landing, or one alive from one that has gone quiet. #830 found that every Workflow run keeps a live `journal.jsonl` of started and result lines, one per step, and that those lines carry no time.

## Decision

A run's journal is `<config>/projects/<slug>/<session_id>/subagents/workflows/<run_id>/journal.jsonl`, and the run's final record, `<config>/projects/<slug>/<session_id>/workflows/<run_id>.json`, exists only once the run has ended. The console reads the `projects` directory beside each session directory it already reads (ADR-console-004), for every live session that has a repository.

A journal is read incrementally by byte offset, never from its start again, and a trailing line without its newline waits for the next read. A journal that is truncated or replaced (a different inode, or a size below the offset) is folded again from its start, never onto the old fold.

The stage of an issue comes from the labels of the steps that started. Two label tables bind the console to the delivery programs: one for a single run's own labels and every child's, one for the labels a batch program starts itself. In the batch table only the issue-bearing templates name an issue; the numbers in train and sweep labels are counters and name none. A batch child's issue is the one its setup result's branch names. The plan count, the m of "building task n of m", comes from the plan result. A label the tables do not know reads `working`, never an error. An issue is done only on a successful close-out result, and done is final.

A journal has no timestamp, so a run moved when its journal's mtime says. The view reads "moved just now", "moved N min ago" and, from fifteen minutes, "quiet for N min". It never says stalled: a slow step and a dead one cannot be told apart from the journal, and #837 item 3 keeps "stalled" for a positive signal.

Each run is a row of the log, per ADR-console-001: `delivery.seen` when its issues or its mtime change and `delivery.gone` when it leaves. A run leaves only on a final record or a confirmed absence, meaning a listing that succeeded without it or a read that found it gone. A journal, a final record or a listing that cannot be read is not absence: the last observation stays. Journals are read on the session poll thread, never by a state request.

## Consequences

- The labels couple the console to the delivery programs' label names. A test reads both programs and fails on a label the tables do not classify; a label renamed elsewhere reads `working` until then.
- A close-out that failed leaves the issue landing, because a failed close-out is resumable and not done.
- A plan-mode batch child waiting for a build slot reads plan review.
- A run whose session has left is not shown.
- A restart reads each live journal once from its start.
- The log grows by one row per poll in which a run moved.
