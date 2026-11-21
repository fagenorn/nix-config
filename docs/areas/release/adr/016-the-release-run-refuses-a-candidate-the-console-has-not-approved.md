# ADR-release-016 — The release run refuses a candidate the console has not approved

- **Status:** accepted
- **Decided in:** issue 1401

## Context

`release transaction run` published whatever candidate its caller named, once every
confirmation token of the preview was supplied. A token proves the caller previewed the plan;
it does not prove the owner wanted that commit released at that version, and a yes in a chat
is no record the command can read. The console now holds a release card outside any sprint
(ADR-console-095): the lead posts the pair of a commit and a version, and the owner approves
or declines it on the page. Nothing yet made the release command depend on that answer, so the
removal of the release from the manager's permit (ADR-console-094) left the command itself
unguarded.

## Decision

`run` asks an approval gate after the `confirmation_stale` and `confirmation_required` checks
and before the router, the land lock, the store, `_adopt` and `_create` are touched, so a
refused run writes and holds nothing. The gate applies to a new candidate and to a resumed
transaction whose created event does not carry the authority class `release.approved`. It calls
the driver's `approvals(commit, version)` once with the candidate's own pair (the stored one on
a resume) and refuses `release_unapproved` when no approved card records exactly that pair.

A transaction `run` creates carries `release.approved`, so its resume asks nothing: the
approval was given for that candidate and a card that has since lapsed or been removed does not
strand it. A transaction created before this change carries `release` and asks once for its
stored candidate. `dispose` issues its grant with the held transaction's own created class, so
the core's class check passes for both.

Nothing else is gated: `preview`, the resume of an admitted transaction, the finished-release
reprint, `abandon` and `dispose` never call `approvals`.

The gate fails closed. A driver with no reader, or a reader that raises `ApprovalUnreadable`,
refuses `approval_unreadable`, naming the reason; both refusals are one line.

The driver imports no console module. `release` builds the reader, `console_approvals`, over
`release_card.store_cards` and `release_card.approved`, and reads the host console's store at
`release_card.host_store()`, the password database's home, never `$HOME`: the console that
records the owner's answer runs under that home, and a caller's `HOME` is the caller's to set.

`release` and every one of its sub-parsers set `allow_abbrev=False`. An abbreviation such as
`--disp` is an unrecognized argument and exits 2 before anything runs, so the `--dispose`
option and the `abandon` verb are the only spellings that reach those paths.

## Consequences

- Every project released through this command needs the host's console and its store.
- An approval lapses 90 days after it was posted, at read time; a stopped console's old rows
  are still ignored.
- A chat yes is no longer an approval: only the owner's click on the console page counts.
- A release created before this change asks once, for its stored candidate, when it is resumed.
