# ADR-release-006 — The forge merge runs only above the protection floor

- **Status:** accepted
- **Decided in:** issue 554 D4-D7, D13, D17

## Context

A release that merges the integration branch into the default branch through the forge could be defeated by a missing protection rule, by head-branch auto-deletion, by a pull request that moved, or by a base branch that advanced past the previewed plan. The provider answers a failed merge ambiguously.

## Decision

`pr_merge` makes four precondition reads before the guard and the merge: strict branch protection with required contexts and enforced admins, `delete_branch_on_merge` off, an open pull request on the target branch at the candidate commit, and a base tip equal to the candidate's bound `merge.base_tip`. A miss is `rejected` with `precondition_failed`. The one mutation is `gh pr merge <pr> --repo <slug> --merge --match-head-commit <commit>`, and it never renders `--admin`, `--auto`, `--delete-branch`, `--squash` or `--rebase`. Its inspection is `satisfied` only when the merge commit's parents are exactly `[merge.base_tip, candidate.commit]`.

## Consequences

- A repository without the protection floor cannot be released through this operation, however green its checks are.
- Four extra reads precede every merge, and a failed `gh pr merge` is `unknown`, which the core settles by inspecting the merge commit.
