# ADR-project-contract-005 — `adopt-project verify --register` reads one pinned commit of the remote

- **Status:** accepted
- **Decided in:** issue 363

## Context

Registering a project in the fleet registry vouches that its adoption is integrated. A checkout can sit on any branch with any uncommitted state, so reading it would register something the remote never held.

## Decision

`--register` lists `origin`, pins one commit of the remote's default branch, exports it and resolves the contract there; every check then reads that one pinned commit and nothing from the checkout. The default branch's contract stays the authority when it resolves, so `--integration-branch` changes nothing unless the default contract does not resolve, and then it names the branch to read.

## Consequences

- The only repository writes are the fetched objects and their remote-tracking refs.
- A run that selected its branch through the operand records a `branch_override` in its report and registry entry.
