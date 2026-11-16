# ADR-guard-009 — A merge of a marked issue needs the owner's look at its head

- **Status:** accepted
- **Decided in:** issue 1138

## Context

An issue can hold a merge for the owner's own look, and until now that hold was prose: nothing bound a merge to it, and four slices of one issue merged unseen. The merge is the one step the guard already adjudicates, and it already reads the pull request and its forge state before it admits a merge.

## Decision

An issue whose body carries a look marker line is a criterion, not a label: markers decide and labels filter, as ADR-claims-001 records. The guard refuses a merge of a pull request whose issues are marked unless a look approval names that issue, that pull request and its current head.

- Only a trusted author's approval counts, `OWNER` or `MEMBER`, the rule of ADR-verification-004. A collaborator's or contributor's comment is read and ignored.
- One approval covers one head. A new commit to the pull request needs a new look, and the latest answer for a head decides, so a later request for changes withdraws an earlier approval.
- Both merge arms run the gate, right after the mergeability check and before their first gate, so a pull request merged onto an integration base meets it before the exemption, and a release pull request meets it before its rollup predicate.
- The guard stays standard-library only and imports nothing from `agent_tools`. It reads the pull request body, each referenced issue and its comments with its own store `gh`, then runs the shared reader as a child the wrapper names with `--look-bin`, as it runs the row check through `--derive-bin`.
- A failed, timed-out or unreadable lookup refuses, and so does a missing `--look-bin`: the gate fails closed.

## Consequences

- A merge made outside the guard stays outside it, as ADR-guard-005 and ADR-guard-008 record for the other forge-state gates.
- Every merge pays one pull request body read, two reads per referenced issue and one child; a pull request that settles no issue pays the body read alone.
- A pull request's issues are those its head branch names and its body closes, fixes, resolves or refers to; an issue named nowhere on the pull request is not read.
- A new commit after the owner's look needs a new look before the merge, which is the point.
