# Two shells, one task file

## Destination

A decision on what tinytask does when two shells mutate the same task file —
detect it, prevent it, or keep accepting the loss and document it. Ends as a
record under `docs/areas/backlog/adr/`, not as code.

## Notes

Domain language: `docs/areas/backlog/CONTEXT.md`. ADR-backlog-001 already records
that the Store rewrites the whole task file atomically and that concurrent writers
are neither supported nor detected — this effort decides whether that consequence
stands. ADR-system-001 (standard library only) binds every option on the table.
Use `grill-with-docs` for anything that turns on a term.

## Decisions so far

<!-- one line per closed ticket: the gist, then the link for the detail -->

## Not yet specified

- Whether contention is frequent enough in practice to justify anything beyond a
  louder warning — unknown until we can see the failure mode.
- Where a lock, if there turns out to be one, would live relative to `--file`.

## Out of scope

- Sync between machines. A different destination and a different effort; the
  Backlog area rules it out and this map does not redraw that boundary.
