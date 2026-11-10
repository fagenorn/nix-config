# ADR-verification-004 — Only OWNER and MEMBER blocks and markers count

- **Status:** accepted
- **Decided in:** issue 630 P3

## Context

The repository may be public, so anyone can comment on a held issue. A block or a marker is the only input the runner acts on, and a marker also decides contests such as the `verify-run` lease and the `verify-closed` close.

## Decision

Only a comment whose author association is `OWNER` or `MEMBER` carries a block or marker the runner reads, a contest re-read included. Another author's block is never selected, and another author's marker neither wins nor ends a contest. A pass that writes first checks that its own `gh` account would be trusted, since it reads back only trusted markers: the owner of a user-owned repository or an active member of the owning organization. Any other account ends the project with one `runner_untrusted` line before any write or run.

## Consequences

- A collaborator account cannot run the verification pass, even though it can comment: it would write markers it could not read back.
- The association is the only trust check, so the authority of the repository's owners and members is the boundary.
- Another author's marker is invisible rather than reported, so such a comment leaves no trace in a pass.
