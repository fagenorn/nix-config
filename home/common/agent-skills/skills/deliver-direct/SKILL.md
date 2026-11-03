---
name: deliver-direct
description: Delivers one small, concrete issue to merge with no spec or plan. Use for direct-lane issues.
---

# deliver-direct

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. Use `bindings.tracker`, `bindings.vcs`, `bindings.commands` and `bindings.workflow.verification`.

One issue, worktree and PR; no spec, plan, ledger or lifecycle helper. `<slug>` is `bindings.tracker.repo_slug` (the origin remote's owner/name), `<int>` is `vcs.integration_branch`, `<branch>` follows `vcs.branch_pattern`, `<dir>` is the worktree.

**Eligibility.** Every acceptance criterion is concrete and checkable, the fix is local (a few files) and no open design decision or user preference is needed. Else stop and recommend `from-issue`. First confirm the issue still applies at the current `origin/<int>` tip; if not, close it with the evidence.

1. **Claim.** Refuse if `gh issue view <n> --repo <slug>` shows an assignee or an `in-progress` or `needs-verification` label, or `gh pr list --repo <slug> --search <n>` an open PR. Else add `in-progress` (if missing, create it with description `Being delivered by an agent` and the default colour); remove it when you finish.
2. **Worktree.** After a fetch, `git -C <checkout> worktree add --no-track -b <branch> <vcs.worktree.root>/<branch> origin/<int>`; work only there. Never `git stash` (shared by all worktrees) or `sed -i`.
3. **Test first.** Write the criteria's tests, see them fail, implement. Run the targeted tests, then each `workflow.verification` id as its `bindings.commands` argv, its cwd rebased from `project.root` to `<dir>`, skipping one whose `verification_conditions` `when_changed` globs match no changed path (record its `skip_reason`). Run any changed script or recipe once. Remove each new code branch in turn and run the specific test ids (`module.Class.test`): confirm the expected test ran and failed; a filter that runs zero tests is not a pass.
4. **Review.** One fresh-context reviewer in the foreground: `reviewer-lite` with `lane: direct`, the criteria and `git -C <dir> diff origin/<int>...HEAD`, for Important+ defects and unmet criteria only. Use the full `reviewer` when the diff touches authentication or authorization, permission or command guards, secrets or credentials, CI/CD or deploy config, or data migrations. Never self-review instead. Fix real findings; re-review if behaviour changed. Full verification can take tens of minutes: run it once, in the foreground with a long timeout, after review fixes.
5. **Ship.** Each lifecycle command alone in one Bash call, with no `cd` prelude, chain, `;`, pipe or redirect (not `2>&1` or `| tail`); read output with a follow-up call; the only prefix unsets the names in `tracker.credential_env.unset_before_invocation`:
   - `git -C <dir> push origin <branch>`
   - `gh pr create --repo <slug> --base <int> --head <branch> --title '<title>' --body '<body>'`: this flag order, inline body, no double quote, dollar, backtick or backslash. Body: why, changes, evidence, merge danger; `Closes #<n>` only when this PR's tests or commands show every criterion, else `Refs #<n>` plus `needs-verification` (any criterion needing a deployed or installed tool, a host activation or observation over time).
   - `gh pr merge <pr> --repo <slug> --<vcs.merge.strategy>`, plus `--delete-branch` when `vcs.merge.delete_branch`

   No sleep workaround. On a second guard refusal, stop and report.
6. **Wait in-turn.** Never end the turn while a test, reviewer or CI run is pending; wait with `gh pr checks <pr> --repo <slug> --watch` or Monitor. `--required --watch` can return before every required check has reported: take the required names from branch protection (or the first `--required` listing once all appear) and wait until each has reported and passed; never treat a partial list as green (every check, if none is required). Merge on a branch up to date with `<int>`; else merge `origin/<int>`, rerun only targeted tests for files the resolution touched (CI covers the rest), push, wait again. If `<int>` keeps moving, resync at most twice, then report the contention.
7. **Close out.** `git -C <checkout> worktree remove <dir>`; fetch, and if the checkout is clean and on `<int>`, `git -C <checkout> merge --ff-only origin/<int>` so `-d` sees the merge; then `git -C <checkout> branch -d <branch>`, each separately. If `-d` refuses, leave the branch and report (never `-D`). Evidence criteria left: keep the issue open with `needs-verification`, commenting what remains.

**Report** under 150 words: PR and merge state, tests, mutation result, review verdict, what is open, wall time, tokens, friction.
