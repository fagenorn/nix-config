---
name: deliver-direct
description: Delivers one small, concrete issue to merge with no spec or plan. Use for direct-lane issues.
---

# deliver-direct

Run `resolve-project resolve --repo-root <checkout>`. Resolve once at phase entry, retain the returned `ResolvedProject` in memory, and treat every resolver error as fatal before mutation or external effects. On refusal, preserve and report the resolver's `error.code`, `repair_id`, and ordered `violations` exactly; never translate it into a partial snapshot or fallback. Use `bindings.tracker`, `bindings.vcs`, `bindings.commands`, `bindings.workflow.review.code` and `bindings.workflow.verification`.

One issue, worktree and PR; no spec, plan or ledger. `<slug>` is `bindings.tracker.repo_slug`, `<int>` is `vcs.integration_branch`, `<branch>` follows `vcs.branch_pattern`, `<dir>` is the worktree.

**Eligibility.** Concrete, checkable criteria; a few-file fix needing no open design decision or preference. Else stop and recommend `from-issue`.

1. **Claim.** Refuse on an open PR (`gh pr list --repo <slug> --search <n>`) or a `needs-verification` label. `forge-claim acquire --repo <slug> --issue <n> --holder <host>/session-<id> --branch <branch>`; stop unless `acquired` or `already_held`. `forge-claim release` (no `--branch`) last. Confirm the issue still applies at `origin/<int>`; if not, comment the evidence, release, close it.
2. **Worktree.** After a fetch, `git -C <checkout> worktree add --no-track -b <branch> <vcs.worktree.root>/<branch> origin/<int>`; work only there. Never `git stash` or `sed -i`.
3. **Test first.** Write the criteria's tests, see them fail, implement. Run targeted tests and any changed script or recipe once. Remove each new code branch in turn: its test must run and fail; zero tests run is not a pass.
4. **Review.** One fresh reviewer, never yourself, foreground: `reviewer-lite` with `lane: direct`, the criteria and `git -C <dir> diff origin/<int>...HEAD`, for Important+ defects and unmet criteria; the full `reviewer` when the diff touches auth, permission or command guards, secrets, CI/CD or deploy config, or data migrations. When `capabilities.review.code` is `available`, also run `bindings.workflow.review.code` on that range through `codex-collaboration`'s `diff-review` with no review package; `blocked` or failing to run: stop and report, never skip. Fix real Important+ findings; re-review if behaviour changed. Then run each `workflow.verification` id once in the foreground: its `bindings.commands` argv, cwd rebased from `project.root` to `<dir>`; skip one whose `verification_conditions` `when_changed` globs match no changed path (record `skip_reason`).
5. **Ship.** Each lifecycle command alone in one Bash call: no `cd` prelude, chain, `;`, pipe or redirect; the one prefix unsets `tracker.credential_env.unset_before_invocation`:
   - `git -C <dir> push origin <branch>`
   - `gh pr create --repo <slug> --base <int> --head <branch> --title '<title>' --body '<body>'`: this flag order, inline body, no double quote, dollar, backtick or backslash. Body: why, changes, evidence, merge danger; `Closes #<n>` only when its tests or commands show every criterion, else `Refs #<n>`.
   - `gh pr merge <pr> --repo <slug> --<vcs.merge.strategy>`, plus `--delete-branch` when `vcs.merge.delete_branch`

   `forge-claim renew` (step 1's flags) before each push and the merge; stop unless `renewed`. No sleep workaround; stop on a second guard refusal.
6. **Land in order.** End no turn with a test, reviewer or CI run pending. PR open: `forge-claim land acquire --repo <slug> --branch <int> --sha <head> --wait`; if behind, merge `origin/<int>`, rerun touched files' tests, `git -C <dir> push origin <branch>` then acquire, no `--wait`; wait (`gh pr checks <pr> --repo <slug> --watch` can return early) until each required check from `gh api repos/<slug>/rules/branches/<int>` (or classic protection; else every check) passed, resyncing when behind, twice, then report contention; acquire again, merge only on `already_held` or `moved`; `forge-claim land release --repo <slug> --branch <int> --sha <lock sha>`. Stop on any acquire not `acquired`, `already_held` or `moved`; release `<lock sha>`, the last head held, on any later stop.
7. **Close out.** `git -C <checkout> worktree remove <dir>`; fetch, and if the checkout is clean and on `<int>`, `git -C <checkout> merge --ff-only origin/<int>`; then `git -C <checkout> branch -d <branch>`, each separately. If `-d` refuses, keep it, report (never `-D`). Open criteria: regrade each `code` once required checks pass; none left: close the issue with the evidence. Else hold per `~/.agents/standards/acceptance-planning.md`: a hold comment with a verify block `verify-pending lint` accepts, the `needs-verification` label (create if missing), then `verify-pending run --host <host> --repo <slug> --issue <n>` once.

**Report** under 150 words: PR state, tests, mutation, review verdict, open items, time, tokens, friction.
