# ADR-console-049 — Spend is read from transcripts into memory and never logged

- **Status:** accepted
- **Decided in:** #1134

## Context

The owner cannot see where the host's tokens and dollars go: which project, sprint, delivery run, phase or account used them. The Claude Code transcripts under each profile's `projects` tree hold every message's usage, 5 GB over 30 days on this host. The event log (ADR-console-001) is the console's truth, but a row per message would bury the rows that matter and double what the transcripts already hold.

## Decision

**D1. Derived, in memory.** Spend is derived from the transcripts and kept in memory, never written to the event log (ADR-console-001). A restart reads up to 30 days of transcripts once, on the `console-spend` thread, so construction, `start()` and the session poll never wait on it. The view's spend is absent until the first poll ends.

**D2. Incremental and counted once.** Reading is incremental per file, as ADR-console-005 reads run journals: a file whose size has not moved is not opened, and only appended bytes are read. Each message id counts once, across files and reads; a repeat of an id only raises the count to the larger of each usage field. Profiles that share one `projects` tree count once, because the directories are deduplicated by their real path and walked through it, so cursors survive a change of alias. Only a confirmed-absent directory forgets its files' cursors; any other listing error keeps them, so recovery reads only the bytes appended since.

**D3. Attribution at view time.** Totals are kept per day, session, run, agent and source, and project, sprint, account, run and phase are resolved when the view is derived, not when a line is read, so a journal or name line read after a message still attributes it. The account comes from the log's `session.seen` and `session.profile` rows, kept past `session.gone`; a session without such a row carrying a profile reads `unattributed`, the key for anything unresolved.

**D4. Subagents.** A session-level subagent transcript, outside any workflow, counts as its session's spend. A workflow agent's transcript counts as its run's.

**D5. Phases.** A delivery agent's phase follows the role mapping of the #1104 cost measurement, grouped into the issue's phases, and not the stage tables of ADR-console-005, so the check against that measurement compares like with like. A label no row matches reads `other`.

**D6. Days and dollars.** A day is the UTC date of a message's timestamp, and the view holds today and the 29 days before. Dollars are estimates at list prices from `model_pricing`, flagged approximate when the table only approximates a model.

**D7. Pings.** Keepalive pings come from the darwin ping log only; a host with no ping log file shows none.

## Consequences

- The first poll, `spend_seconds` after a restart, reads the whole 30-day window.
- Accounts of sessions with no retained `session.seen` or `session.profile` row carrying a profile read `unattributed`.
- The phase table must follow label renames in the delivery programs; an unknown label reads `other` until it does.
- Dollars are estimates and may be approximate.
- The page is unchanged.
- Related: ADR-console-001, ADR-console-005.
