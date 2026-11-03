---
name: deliver-direct
description: Delivers one small, concrete issue to merge with no spec or plan. Use for direct-lane issues.
---

# deliver-direct

One issue, worktree and PR; no spec, plan, ledger or lifecycle helper. `<repo>` is the tracker slug, `<dir>` the worktree.

**Eligibility.** Every acceptance criterion is concrete and checkable, the fix is local (a few files) and no open design decision or user preference is needed. Else stop and recommend `from-issue`.

1. **Claim.** Refuse if `gh issue view <n> --repo <repo>` shows an assignee or an `in-progress` or `needs-verification` label, or `gh pr list --repo <repo> --search <n>` an open PR. Else add `in-progress` (create the label if missing); remove it when you finish.
2. **Worktree.** After a fetch, `git -C <checkout> worktree add .worktrees/direct-<n> -b direct-<n> origin/main`; work only there. Never `git stash` (shared by all worktrees) or `sed -i`.
3. **Test first.** Write the criteria's tests, see them fail, implement. Run the targeted tests and `just build`, not the full suite, and any changed `just` recipe once. Remove each new code branch in turn: its test must fail.
4. **Review.** One fresh-context reviewer in the foreground: `reviewer-lite` with `lane: direct`, the criteria and `git -C <dir> diff origin/main...HEAD`, for Important+ defects and unmet criteria only. Use the full `reviewer` when it touches `lifecycle_guard.py`, `claude-code/default.nix` settings, secrets or any permission surface. Never self-review instead. Fix real findings; re-review if behaviour changed.
5. **Ship.** Each command alone in one Bash call (only prefix: `unset GITHUB_TOKEN && `), with no `cd` prelude, pipe or redirect:
   - `git -C <dir> push origin direct-<n>`
   - `gh pr create --repo <repo> --base main --head direct-<n> --title '<title>' --body '<body>'`: this flag order, inline body, no double quote, dollar, backtick or backslash. Body: why, changes, evidence, merge danger; `Closes #<n>` only if this PR meets every criterion in code, else `Refs #<n>`.
   - `gh pr merge <pr> --repo <repo> --merge --delete-branch`

   Never `git branch -D` or a sleep workaround. On a second guard refusal, stop and report.
6. **Wait in-turn.** Never end the turn while a test, reviewer or CI run is pending; poll `gh pr checks` with Monitor. Merge once `Nix Eval` and `Instruction Budget` pass on a branch up to date with main; else merge `origin/main`, push, wait again.
7. **Close out.** `git -C <checkout> worktree remove <dir>`, then `git -C <checkout> branch -d direct-<n>`, separately. Evidence criteria left (a switch, days of use): keep the issue open, labelled `needs-verification`, commenting what remains.

**Report** under 150 words: PR and merge state, tests, mutation result, review verdict, what is open, wall time, tokens, friction.
