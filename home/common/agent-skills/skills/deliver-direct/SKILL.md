---
name: deliver-direct
description: Delivers one small, concrete issue to merge with no spec or plan. Use for direct-lane issues.
---

# deliver-direct

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. Use `bindings.tracker`, `bindings.vcs`, `bindings.commands` and `bindings.workflow.verification`.

One issue, worktree and PR; no spec, plan, ledger or lifecycle helper. `<slug>` is `bindings.tracker.repo_slug` (the origin remote's owner/name), `<int>` is `vcs.integration_branch`, `<branch>` follows `vcs.branch_pattern`, `<dir>` is the worktree.

**Eligibility.** Every acceptance criterion is concrete and checkable, the fix is local (a few files) and no open design decision or user preference is needed. Else stop and recommend `from-issue`.

1. **Claim.** Refuse if `gh issue view <n> --repo <slug>` shows an assignee or an `in-progress` or `needs-verification` label, or `gh pr list --repo <slug> --search <n>` an open PR. Else add `in-progress` (create the label if missing); remove it when you finish.
2. **Worktree.** After a fetch, `git -C <checkout> worktree add -b <branch> <vcs.worktree.root>/<branch> origin/<int>`; work only there. Never `git stash` (shared by all worktrees) or `sed -i`.
3. **Test first.** Write the criteria's tests, see them fail, implement. Run the targeted tests, then each `workflow.verification` id as its `bindings.commands` argv, its cwd rebased from `project.root` to `<dir>`, skipping one whose `verification_conditions` `when_changed` globs match no changed path (record its `skip_reason`). Run any changed script or recipe once. Remove each new code branch in turn: its test must fail.
4. **Review.** One fresh-context reviewer in the foreground: `reviewer-lite` with `lane: direct`, the criteria and `git -C <dir> diff origin/<int>...HEAD`, for Important+ defects and unmet criteria only. Use the full `reviewer` when the diff touches authentication or authorization, permission or command guards, secrets or credentials, CI/CD or deploy config, or data migrations. Never self-review instead. Fix real findings; re-review if behaviour changed.
5. **Ship.** Each command alone in one Bash call, with no `cd` prelude, chain, pipe or redirect; the only prefix unsets the names in `tracker.credential_env.unset_before_invocation`:
   - `git -C <dir> push origin <branch>`
   - `gh pr create --repo <slug> --base <int> --head <branch> --title '<title>' --body '<body>'`: this flag order, inline body, no double quote, dollar, backtick or backslash. Body: why, changes, evidence, merge danger; `Closes #<n>` only if this PR meets every criterion in code, else `Refs #<n>`.
   - `gh pr merge <pr> --repo <slug> --<vcs.merge.strategy>`, plus `--delete-branch` when `vcs.merge.delete_branch`

   Never `git branch -D` or a sleep workaround. On a second guard refusal, stop and report.
6. **Wait in-turn.** Never end the turn while a test, reviewer or CI run is pending; wait with `gh pr checks <pr> --repo <slug> --watch` or Monitor. Merge once every `--required` check passes (every check, if none is required) on a branch up to date with `<int>`; else merge `origin/<int>`, push, wait again.
7. **Close out.** `git -C <checkout> worktree remove <dir>`, then `git -C <checkout> branch -d <branch>`, separately. Evidence criteria left (a deploy, days of use): keep the issue open, labelled `needs-verification`, commenting what remains.

**Report** under 150 words: PR and merge state, tests, mutation result, review verdict, what is open, wall time, tokens, friction.
