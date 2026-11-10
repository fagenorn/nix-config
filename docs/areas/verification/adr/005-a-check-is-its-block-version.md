# ADR-verification-005 — A check is identified by block version and index, never by its ac

- **Status:** accepted
- **Decided in:** issue 630 P15

## Context

A hold comment can be edited or its checks reordered after a result was recorded. If a result were keyed by the acceptance criterion id (`ac`), an edit that changed what a check does would inherit the earlier verdict.

## Decision

A check is identified by its block version and index. The version is the block comment's id and a digest of the block's content, so editing or reordering the checks of a comment keeps the comment id but starts a new version. Every marker carries the version in its `block` field, and a result recorded for an earlier version is never read back. The `ac` field labels a check and is never part of its identity.

## Consequences

- Editing a held block starts afresh: results, leases and windows of the earlier version are not read back, and a replacement block is run again from the start.
- A window belongs to a merge and an event, not to a block, so a replacement block does inherit its `window-open` marker.
- Reordering checks is a new version even when nothing else changed.
