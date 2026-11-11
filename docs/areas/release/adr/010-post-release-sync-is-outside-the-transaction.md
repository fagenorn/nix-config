# ADR-release-010 — The post-release sync runs outside the transaction and never merges

- **Status:** accepted
- **Decided in:** issue 845

## Context

A two-branch release leaves the default branch one merge commit ahead of the integration branch, and the next release refuses `release_pr_behind` until that commit is back. A fast-forward push of the integration branch is refused by the forge where that branch requires a check that only runs on pull requests, and the guard admits no refspec push. Modelling the sync as profile actions would let a failed sync park a release that is already published, would need a publication mode the grammar does not have, and would change the forge descriptor digest that pins every profile and every confirmation token.

## Decision

The sync is two forge requests, `sync_branch` and `sync_pr`, that no profile node can bind: the descriptor does not list them. The driver derives the sync from the project (integration branch differs from the default branch, a forge node consumes `merge`) and runs it through `release_sync` once every publication action is satisfied. It pushes a disposable branch `sync-<default>-into-<integration>-after-<version>` at the release merge commit and opens one pull request from it into the integration branch, each through the guard in a spelling the guard already admits for any agent. Nothing is stored: each `run` reads the forge again, reports the outcome as the result's `sync` member, and a `run` with no candidate on a finished release finishes a sync left half done. The core never merges the sync pull request.

## Consequences

- A failed sync is reported with its reason and the commands that finish it by hand, and changes no state, action, token or receipt of the release.
- The two mutations run under no grant, custody or recorded intent of the core: they are reversible, pass the guard and the same-repository check, and are settled by inspection alone. They are not core admissions in the sense of ADR-guard-008. Their spellings are rows of the one spelling fixture, which the forge suite renders and the guard suite runs against the real guard: both are admitted where the integration branch is distinct, and the pull request is refused where it is not.
- The local sync branch stays in the main checkout until the owner's `gh pr merge --delete-branch` removes it.
- `release_pr_behind` names the open sync pull requests by the branch name alone, so a hand-made branch of the same name is named too.
