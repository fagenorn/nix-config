# ADR-guard-007 — A derived row is re-derived at use before the guard relies on it

- **Status:** accepted
- **Decided in:** issue 126 D6, issue 377 D2, D3, D6, D12, issue 385, issue 844

## Context

A derived row is compiled at activation and stored in a file a session can write (ADR-guard-006), and the registry, the contract and the remote can all change after the compile. Trusting the stored row would let a stale or forged row authorize a push, merge or release.

## Decision

For a repository that has a row, the guard re-derives that one row at use with the compiler's own proof, by running the row check, and relies on the row only when `origin/HEAD`, the row check's outcome and the row's branches and required checks all agree with the compiled row. The check runs once per repository context, when the context is built, on every repository-bound verb, nix-config included, and only for a repository that has a row. A repository with a row is judged by the row and never falls back to its owner literal when the check fails.

The check is bounded by a 15-second limit inside a shared 27-second invocation deadline that keeps the verdict ahead of the hook's 30-second timeout, and the guard kills its whole process group on the bound. An unreachable `origin` or provider fails the check and refuses the verb: there is no fallback to a ref already present or to the unchecked row.

The cost of the check per verb is the measurement archived in [guard-row-check-cost-2026-10-13](../../../archive/guard-row-check-cost-2026-10-13.md): a remote listing, a fetch only for a branch whose listed commit the checkout lacks, a sparse export of the contract and one provider read. A provider read that fails is repeated once inside that read's own bound, so no limit above grows; a second failure refuses (issue 844).

## Consequences

- Every repository-bound verb in a repository with a row pays seconds, not milliseconds.
- A registry or contract change that moves a row's branches refuses until the next compile, and a project registered after the last compile has no row until the next one.
- No availability is lost to the offline refusal, because push, pull request creation, merge and release creation each need the same remote or provider to succeed.
- Two sessions judged at once contend for a ref lock only when both fetch a missing commit into the same registered root; the loser fails `fetch_failed` and refuses, and a rerun clears it.
- A row check refused only for `fetch_failed` or `provider_unproven` names the failed read's detail and the rerun as its remedy, not `claude-guard-policy`: the read failed and the policy did not (issue 844).
- Schema 3 of the compiled policy carries `required_checks`: a schema-2 file lacks it and is read as contributing no row, and the activation step recompiles on every switch. A Claude Code session started before the switch that installs a new guard still runs the previous guard, which reads a schema-3 file as contributing no row. In both cases only a repository that relies on a derived row for its authorization is refused, until the recompile or the session restart; a repository authorized by an owner literal keeps its authorization.
