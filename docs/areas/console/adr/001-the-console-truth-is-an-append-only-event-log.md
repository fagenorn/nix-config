# ADR-console-001 — The console's truth is an append-only event log, served on loopback

- **Status:** accepted
- **Decided in:** #838, #855, #886

## Context

The owner needs one place that says whether they are needed across every registered project. Later slices feed it from session hooks, the proxy and managers, and a view derived on each read would have to ask all of them on every request.

## Decision

Every fact the console learns is one row of an append-only SQLite log at `~/.agents/state/console/events.sqlite3`: a sequence number, a UTC time, a kind, the project it concerns and a JSON payload. Rows are never updated, and are deleted only by the 90-day retention pass (ADR-console-009); triggers refuse every other update or delete. What the page shows is a view derived from the log and held in memory: it is rebuilt from the log at start, and a request reads only that memory. The fleet registry is read at start and whenever it changes, and each difference becomes an event; a registry that is absent or unreadable is no reading and appends nothing, so the view outlives a lost registry. The service binds `127.0.0.1:27184` only, answers only requests addressed to `127.0.0.1` or `localhost` on that port, and no endpoint changes anything.

## Consequences

- One console per host: a second one cannot take the port, and the log format can be merged across hosts later.
- Rows older than 90 days are removed by the retention pass (ADR-console-009), except goal rows, which are kept indefinitely (ADR-console-011).
- Removing a project from the registry file unregisters it; deleting the file does not.
