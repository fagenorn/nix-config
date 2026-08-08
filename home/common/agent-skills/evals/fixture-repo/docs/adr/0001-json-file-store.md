# ADR 0001 — The backlog is one JSON file

**Status:** accepted

## Context

tinytask needs to persist a handful of tasks for a single user on a single machine. The
obvious candidates were SQLite (via the stdlib `sqlite3` module), a line-oriented text
format, and a single JSON document.

## Decision

Store the entire backlog as one JSON array in one file, rewritten atomically on every
mutation via a temporary file plus `os.replace`.

## Consequences

- A user can read, diff, and hand-edit the backlog with ordinary tools. This is the
  primary reason the format won.
- There is no schema and no migration story. Adding a field to `Task` means every older
  file must still load — hence `Task.from_dict` defaulting `state` rather than requiring
  it. Any change that cannot be expressed as a defaulted optional field needs its own ADR.
- Every write is O(backlog). Acceptable up to a few thousand tasks; past that this ADR
  should be revisited rather than patched around with partial writes.
- Concurrent writers are not supported and not detected. Two shells mutating the same
  task file will lose one of the writes.
