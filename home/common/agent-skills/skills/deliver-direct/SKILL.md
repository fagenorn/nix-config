---
name: deliver-direct
description: Delivers one small, concrete issue to merge with no spec or plan. Use for direct-lane issues.
---

# deliver-direct

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. Use `bindings.tracker`, `bindings.vcs`, `bindings.commands`, `bindings.workflow.review.code` and `bindings.workflow.verification`.

One issue, worktree and PR; no spec, plan, ledger or lifecycle helper. `<slug>` is `bindings.tracker.repo_slug`, `<int>` is `vcs.integration_branch`, `<branch>` follows `vcs.branch_pattern`, `<dir>` is the worktree.

**Eligibility.** Every criterion is concrete and checkable, the fix touches a few files and needs no open design decision or user preference. Else stop and recommend `from-issue`.

1. **Claim.** Refuse if `gh issue view <n> --repo <slug>` shows an assignee or an `in-progress` or `needs-verification` label, or `gh pr list --repo <slug> --search <n>` an open PR. Else add `in-progress` (create it if missing); remove it when you finish. Then fetch and confirm the issue still applies at `origin/<int>`; if not, comment the evidence, remove `in-progress` and close it.
2. **Worktree.** After a fetch, `git -C <checkout> worktree add --no-track -b <branch> <vcs.worktree.root>/<branch> origin/<int>`; work only there. Never `git stash` or `sed -i`.
3. **Test first.** Write the criteria's tests, see them fail, implement. Run targeted tests and any changed script or recipe once. Remove each new code branch in turn, run its test id (`module.Class.test`) and confirm it ran and failed; zero tests run is not a pass.
4. **Review.** One fresh reviewer in the foreground: `reviewer-lite` with `lane: direct`, the criteria and `git -C <dir> diff origin/<int>...HEAD`, for Important+ defects and unmet criteria only; the full `reviewer` when the diff touches authentication or authorization, permission or command guards, secrets or credentials, CI/CD or deploy config, or data migrations. Never self-review. When `capabilities.review.code` is `available`, also run `bindings.workflow.review.code` on that range through `codex-collaboration`'s `diff-review` with no review package; `blocked`, or it cannot run: stop and report; never skip it. Fix real Important+ findings from both; re-review if behaviour changed. After review and any fixes, run each `workflow.verification` id once, in the foreground with a long timeout, as its `bindings.commands` argv with cwd rebased from `project.root` to `<dir>`, skipping one whose `verification_conditions` `when_changed` globs match no changed path (record its `skip_reason`).
5. **Ship.** Each lifecycle command alone in one Bash call, with no `cd` prelude, chain, `;`, pipe or redirect; read output with a follow-up call; the only prefix unsets the names in `tracker.credential_env.unset_before_invocation`:
   - `git -C <dir> push origin <branch>`
   - `gh pr create --repo <slug> --base <int> --head <branch> --title '<title>' --body '<body>'`: this flag order, inline body, no double quote, dollar, backtick or backslash. Body: why, changes, evidence, merge danger; `Closes #<n>` only when this PR's tests or commands show every criterion, else `Refs #<n>` (any criterion needing a deployed or installed tool, a host activation or observation over time; see step 7).
   - `gh pr merge <pr> --repo <slug> --<vcs.merge.strategy>`, plus `--delete-branch` when `vcs.merge.delete_branch`

   No sleep workaround. On a second guard refusal, stop and report.
6. **Wait in-turn.** Never end the turn while a test, reviewer or CI run is pending; wait with `gh pr checks <pr> --repo <slug> --watch` or Monitor. `--required --watch` can return early: take the required names from `gh api repos/<slug>/rules/branches/<int>` (its `required_status_checks` rules) or classic branch protection, and wait until each has passed; if neither source answers, wait for every check. Never treat a partial list as green. Merge on a branch up to date with `<int>`; else merge `origin/<int>`, rerun only targeted tests for files the resolution touched, push, wait again. Resync at most twice, then report the contention.
7. **Close out.** `git -C <checkout> worktree remove <dir>`; fetch, and if the checkout is clean and on `<int>`, `git -C <checkout> merge --ff-only origin/<int>` so `-d` sees the merge; then `git -C <checkout> branch -d <branch>`, each separately. If `-d` refuses, leave the branch and report (never `-D`). Criteria left open: keep the issue open, add the `needs-verification` label to the issue (create it if missing) and comment what remains.

**Report** under 150 words: PR and merge state, tests, mutation result, review verdict, what is open, wall time, tokens, friction.
