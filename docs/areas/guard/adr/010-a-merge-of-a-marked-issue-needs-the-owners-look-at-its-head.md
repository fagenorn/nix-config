# ADR-guard-010 — A merge of a marked issue needs the owner's look at its head

- **Status:** accepted; amended in #1211
- **Decided in:** issue 1138

## Context

An issue can hold a merge for the owner's own look, and until now that hold was prose: nothing bound a merge to it, and four slices of one issue merged unseen. The merge is the one step the guard already adjudicates, and it already reads the pull request and its forge state before it admits a merge.

## Decision

An issue whose body carries a look marker line is a criterion, not a label: markers decide and labels filter, as ADR-claims-001 records. The guard refuses a merge of a pull request whose issues are marked unless a look approval names that issue, that pull request and either its current head or an earlier head of that pull request that its current head keeps.

- Only a trusted author's approval counts, `OWNER` or `MEMBER`, the rule of ADR-verification-004. A collaborator's or contributor's comment is read and ignored.
- A look approval covers its head and every later head of the same pull request that keeps it (#1211); the latest answer for a head decides, and a later request for changes on any head withdraws it.
- A later head keeps an approval when the approved head is its ancestor and no commit of the pull request after it changed the look file set: the path globs `.github/look-files.json` declares at the base commit the guard reads. Every such commit is checked, not only the final diff. Each touches no look file, or is a merge of the integration branch that brings into each look file exactly the other parent's change, as a clean merge does. A look file changed after the look (an edit and its revert included), a conflict resolved inside one, an edit dropped by a merge, a side branch of the pull request's own commits, a force-push or a rebase needs a new look.
- An approval may carry one worded fix (answer `fix`), which approves no head itself and keeps the approval across exactly one later commit that changes the look files; a second needs a new look.
- The set is read at the base commit, never from the pull request, so a pull request cannot shrink the set it is judged by; an area or repository with no set keeps one approval per head.
- The guard reads the base commit, the set and the compares with its own `gh` and does not judge: the look check names the reads it needs, and the guard runs it at most three more times, at most 48 reads, each read path checked against a fixed grammar. A failed, partial or unreadable read refuses as before.
- Both merge arms run the gate, right after the mergeability check and before their first gate, so a pull request merged onto an integration base meets it before the exemption, and a release pull request meets it before its rollup predicate.
- The guard stays standard-library only and imports nothing from `agent_tools`. It reads the pull request body, each referenced issue and its comments with its own store `gh`, then runs the shared reader as a child the wrapper names with `--look-bin`, as it runs the row check through `--derive-bin`.
- A merge that settles a marked issue must carry `--match-head-commit`, the rule of the plan-gated floor: the guard's read of the head is seconds older than the merge, and only GitHub's atomic head match makes the approved head the head that merges. The mergeability check has already held the flag equal to the head read, so the flag names the approved head.
- A pull request's issues are found by every keyword GitHub closes an issue on, plus `Refs`, and by this repository's issue URLs, read in the pull request title and body, in every commit message, in the head branch name and in the `--subject` of the merge, and by the issues the forge links to it (`closingIssuesReferences`, the Development sidebar and `gh issue develop`), so the gate is no narrower than the forge's own closing. GitHub also closes on the merge commit, whose default body is the pull request title, so the title and the subject are scanned too. A pull request of 100 commits or more is refused, because the lookup returns no more than 100 and a keyword past them could go unread.
- A failed, timed-out or unreadable lookup refuses, an issue or pull request object with no `body` key included, and so does a missing `--look-bin`: the gate fails closed.

## Consequences

- A merge made outside the guard stays outside it, as ADR-guard-005 and ADR-guard-008 record for the other forge-state gates.
- Every merge pays one pull request read (body, commits and linked issues), two reads per referenced issue and one child; a pull request that settles no issue pays the pull request read alone.
- A pull request's issues are those its head branch names and its body or commits close, fix, resolve or refer to, and the forge links to it; an issue named nowhere on the pull request is not read.
- A kept merge pays one base read, one set read and three compare reads, plus one compare read per later commit and up to four per merge.
- A commit after the owner's look that changes the look files needs a new look, which is the point.
