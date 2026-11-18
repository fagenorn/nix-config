# Look before merge

Read on demand when `look-approval status --repo <slug> --issue <n> --pr <pr> --head <head>` prints a verdict other than `unmarked` (`deliver-direct` step 6, whose placeholders this file uses). An issue whose body carries a look marker line merges only after the owner's look approval names the issue, its pull request and either that pull request's current head or an earlier head the current head keeps; the merge guard refuses any other merge.

## Stop at awaiting look

On `needed`, take no land lock. If the branch is behind, merge `origin/<int>`, rerun the touched files' tests, run `forge-claim renew` (step 1's flags) and `git -C <dir> push origin <branch>`, and run `look-approval status --repo <slug> --issue <n> --pr <pr> --head <head>` again for the new head. Then stop: merge nothing, post no hold, run `forge-claim release`, keep the worktree and the pull request, and report the stage `awaiting look`, the issue, the pull request, the head and the reason `issue <n> needs the owner's look before merge`.

## Resume on the owner's answer

A session told the owner's answer resumes at step 6 after step 1's `forge-claim acquire` (stop unless `acquired` or `already_held`), past step 1's open-PR refusal. It is one of three.

- **approve**, with the head it was given for. Read `gh pr view <pr> --repo <slug> --json state,headRefOid`; only while it is `OPEN` at that head, run `look-approval status --repo <slug> --issue <n> --pr <pr> --head <head>` and land as below on `approved`. Never record an approval yourself: on `error` or `unmarked` apply the rule below; else merge nothing and stop at awaiting look with the current head, saying the head moved or the owner has not recorded it.
- **fix**, with the head it was given for and the owner's words. Read `gh pr view <pr> --repo <slug> --json headRefOid`; only while it is that head, write the words to a file and run `look-approval post --repo <slug> --issue <n> --pr <pr> --head <head> --answer fix --message session-<id> --words-file <file>`, and go on only on `posted`. Then fix once as for changes, push, and land as below, whose resync rule decides the new head: `look-approval status` answers `approved` for it while the fix is the only later commit that changed what the owner looked at.
- **changes**, with the owner's words. Fix once on the same branch with those words as the findings: step 3's tests, step 4's review and verification, then `forge-claim renew` (step 1's flags) and `git -C <dir> push origin <branch>` to the open pull request. Open no other pull request, merge nothing, and stop at awaiting look again with the new head.

## Land a marked issue

On `error` or `unmarked`, merge nothing: run `forge-claim release` and report it. On `approved`, land as step 6 does, plus two things. An `approved` verdict with a `kept_from` head rests on the owner's approval of that earlier head, plain or with one fix, which the current head keeps: no later commit changed what the owner looked at beyond that one fix. Land it the same way. After every resync under the lock, run `look-approval status --repo <slug> --issue <n> --pr <pr> --head <head>` again for the new head; when it is `approved`, keep landing with the merge below; when it is `needed`, run `forge-claim land release --repo <slug> --branch <int> --sha <lock sha>` and stop at awaiting look; on any other verdict, `error` included, run that land release and `forge-claim release`, merge nothing and report the verdict without asking the owner for a look. The merge is `gh pr merge <pr> --repo <slug> --<vcs.merge.strategy> --match-head-commit <head>`, plus `--delete-branch` when `vcs.merge.delete_branch`.

After the merge, before the close-out holds the issue, run `look-approval tick --repo <slug> --issue <n> --pr <pr> --head <head>` once: it ticks the look marker's box under the owner's approval that covers the merged head. `ticked`, `already` and `unmarked` are fine; report any other verdict in the close-out and tick nothing by hand. `error` means it could not read what it judges a kept approval by: run it once more before you report it.
