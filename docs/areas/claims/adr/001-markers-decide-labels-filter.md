# ADR-claims-001 — Issue comments called markers hold every claim fact; labels only filter

- **Status:** accepted
- **Decided in:** #623

## Context

Several sessions, on several hosts, may try to deliver the same forge issue at once. Labels such as `in-progress` and `owner-action` are easy to read, but a label is one bit that anyone can add or remove at any time, and the forge offers no compare-and-set on it. A contest needs a record that is ordered by the forge and that a late, delayed write cannot undo.

## Decision

Every claim fact lives in an issue comment called a marker, and a label is only a filter over the markers. Among the live markers of one kind that match a field set, the smallest comment id wins, because the forge assigns ids in creation order. A writer posts its marker, re-lists, runs the contest over the re-read plus its own id and deletes its own comment when it is not the winner. Ending is append-only: a marker is ended by posting an `end` marker that is never edited or deleted, so a delayed edit that rewrites an older body can drop a field but never the `end`, and a released claim cannot come back.

## Consequences

- The contest is safe only on the assumption that a listing reflects every comment created before the listing started; a forge that lists late would let two writers both think they won.
- A label can drift from the markers (a call can fail between the post and the label call), so each verb repairs the label it owns instead of trusting it.
- The `end` markers accumulate on the issue; they are never garbage-collected, because deleting one would let a stale edit revive a claim.
