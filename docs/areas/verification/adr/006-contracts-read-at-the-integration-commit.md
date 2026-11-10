# ADR-verification-006 — A run reads each contract at the integration-branch commit origin lists

- **Status:** accepted
- **Decided in:** issue 630 P16, P17

## Context

The runner checks several projects on a host whose checkouts may hold any branch, local edits or an unrelated state. What a check may run is decided by a contract (`bindings.commands`, `workflow.verification`), and a checkout's working tree, index or local branches are not the integration branch.

## Decision

Each project's contract is read per run at the integration branch commit `origin` lists, through the guard-policy reader, never from the checkout (P17). A `command` run executes at that commit; a `script` or `at` run executes at the commit the lint checked (the block's `merge` unless `at` names another), in a detached worktree that is removed afterwards. Every git child, the source reader's included, runs without `GITHUB_TOKEN` and `GH_TOKEN`, and no adapter runs in process (P16).

## Consequences

- The runner fetches a commit the checkout lacks before it reads it, so a pass writes objects into the registered checkouts.
- A contract change takes effect for verification only once it is on `origin`'s integration branch, not when it is edited locally.
- A forge reading that needs a token goes through `forge_markers`, so a child process can never leak one to a committed script.
