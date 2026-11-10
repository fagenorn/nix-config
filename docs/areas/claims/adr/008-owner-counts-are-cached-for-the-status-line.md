# ADR-claims-008 — The status line reads a per-repository cache and never the network

- **Status:** accepted
- **Decided in:** #624, issue 670

## Context

The Claude Code status line renders often, and a GraphQL search over a repository's labels and label events takes seconds and can fail. A render that waited on it, or printed a half-read count, would make the status line slow or wrong.

## Decision

`refresh` rebuilds one cache file per repository, and `statusline` only reads it. A refresh publishes only a complete answer: a truncated label or label-event connection, a search still unfinished after ten pages, or fewer nodes than the search's `issueCount` fails that repository and leaves its cache untouched. A stale read prints the cached value at once and starts at most one detached refresh, guarded by an exclusive `flock` on a file next to the entry that also records the last attempt, so a failing refresh is retried no faster than every 120 seconds.

## Consequences

- The count can lag by up to the 15-minute staleness plus one refresh.
- A repository with more than 1,000 matching items never gets a cache entry, because GitHub caps a search at 1,000 results and the refresh refuses the truncated answer.
- Deleting a cache entry loses nothing; the next stale read schedules a refresh.
