# ADR-console-003 — The inbox is read from the tracker every two minutes, for active projects only

- **Status:** accepted
- **Decided in:** #838, #859

## Context

The inbox lists what waits on the owner: the live owner-action markers of open issues and pull requests, which live on the tracker and nowhere in the console's log. The console must show them without reading the tracker for projects nobody is touching, without spending the rate limit, and without ever saying "Nothing needs you" when it simply could not look.

## Decision

- **Activity rule.** A project is read only while it is active: its last log event or the newest git write of its checkout (`FETCH_HEAD`, `logs/HEAD`, `index`, of the common git dir and every linked worktree) is at most 86400 seconds old. A project without a GitHub checkout is never read. The poll runs every 120 seconds and reads one project after another, outside the ingest lock.
- **One search, at most four calls.** One GraphQL search per repository asks for open items carrying the `owner-action` or `owner-answered` label, 25 a page and the last 100 comments each, and pages at most four times (`inbox.MAX_CALLS`); more is a failed read. Markers decide, labels filter: only comments of a trusted author association (owner, member, collaborator) are parsed, so a stranger's comment never raises an item. A comment's id is `fullDatabaseId` (the 32-bit `databaseId` is too small for current ids) and a node's kind is its `__typename`.
- **Held work.** An issue holds one plus the issues it blocks (`issueDependenciesSummary.blocking`), a pull request holds one; open items are ordered by it.
- **Seen, changed, gone.** A read is folded onto the log as `inbox.seen` (new key), `inbox.changed` (same key, different content) and `inbox.gone` (key no longer read), so an unchanged re-read appends nothing and "waiting since" is the time of the `seen` event, which survives a restart.
- **Read health is logged only on change.** `inbox.health` is appended when a project's read goes from good to failed or back, never on a repeat. A failed read keeps the last items, marks them stale with the time of the last good read, and is stderr `console: tracker_failed <project> <Type>: <message>`. With nothing known the headline says the tracker cannot be read, never "Nothing needs you". Because the health is in the log, a restart shows a failed read as failed before any poll.
- **The link is built locally** from the slug, the issue and the comment id; it is never read from the answer.
- **Cancellation.** `close()` sets the stop flag before anything else; the poll checks it between projects and the reader before every page, so closing waits for at most the one `gh` call already running, and a read that ends after the stop or after its project was unregistered appends nothing.

## Consequences

- An issue with more than 100 comments fails its project's read (stale) until its comments drop below the window.
- An idle project's items are not refreshed until it is active again, but a failed read stays stale across restarts.
- A change of read health is a log event, so it keeps that project active for one more day.
- After a restart and before the next successful read, a stale item's read time is that of the last logged health change, which is never later than the true last read.
- One call costs one GraphQL point, so 30 calls an hour per active project keeps eight active single-page projects under 5% of a 5,000-point hourly allowance.
