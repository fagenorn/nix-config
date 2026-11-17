# Look before merge

Read on demand when `look-approval status --repo <slug> --issue <n> --pr <pr> --head <head>` prints a verdict other than `unmarked` (`deliver-direct` step 6, whose placeholders this file uses). An issue whose body carries a look marker line merges only after the owner's look approval names the issue, its pull request and that pull request's current head; the merge guard refuses any other merge.

## Stop at awaiting look

On `needed`, take no land lock. If the branch is behind, merge `origin/<int>`, rerun the touched files' tests, run `forge-claim renew` (step 1's flags) and `git -C <dir> push origin <branch>`, and run `look-approval status --repo <slug> --issue <n> --pr <pr> --head <head>` again for the new head. Then stop: merge nothing, post no hold, run `forge-claim release`, keep the worktree and the pull request, and report the stage `awaiting look`, the issue, the pull request, the head and the reason `issue <n> needs the owner's look before merge`.

## Resume on the owner's answer

A session told the owner's answer resumes at step 6 after step 1's `forge-claim acquire` (stop unless `acquired` or `already_held`), past step 1's open-PR refusal. It is one of two.

- **approve**, with the head it was given for. Read `gh pr view <pr> --repo <slug> --json headRefOid`; only while it is that head, run `look-approval post --repo <slug> --issue <n> --pr <pr> --head <head> --answer approved --message session-<id>`, go on only on `posted` and land as below. Once the head has moved, post and merge nothing: stop at awaiting look again with the new head, which needs a new look.
- **changes**, with the owner's words. Fix once on the same branch with those words as the findings: step 3's tests, step 4's review and verification, then `forge-claim renew` (step 1's flags) and `git -C <dir> push origin <branch>` to the open pull request. Open no other pull request, merge nothing, and stop at awaiting look again with the new head.

## Land a marked issue

On `error`, merge nothing: run `forge-claim release` and report it. On `approved`, land as step 6 does, plus two things. After every resync under the lock, run `look-approval status --repo <slug> --issue <n> --pr <pr> --head <head>` again for the new head; when it is not `approved`, run `forge-claim land release --repo <slug> --branch <int> --sha <lock sha>` and stop at awaiting look. The merge is `gh pr merge <pr> --repo <slug> --<vcs.merge.strategy> --match-head-commit <head>`, plus `--delete-branch` when `vcs.merge.delete_branch`, because the guard admits a marked merge only on the approved head.

After the merge, before the close-out holds the issue, run `look-approval tick --repo <slug> --issue <n> --pr <pr> --head <head>` once: it ticks the look marker's box under the owner's approval of the merged head. `ticked`, `already` and `unmarked` are fine; report any other verdict in the close-out and tick nothing by hand.
