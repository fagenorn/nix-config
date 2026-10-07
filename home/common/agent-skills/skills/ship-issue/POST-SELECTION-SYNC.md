# Post-selection sync

Read this when a PR needs the integration branch after selection.

## Current selection and sync run

Under lifecycle identity a selection is immutable, so a PR that needs the integration branch
after selection gets a **sync selection** that extends it and never replaces it. The route
belongs to whoever holds the merge gate: the ship owner under implementation custody, or a
remainder owner. The **current selection** is the newest link of the ledger's selection chain.
An owner that does not hold it reads it from the ledger with `## Delivery loop`'s builder call
and `--kind current-selection`, fed only the installed `contract`. From the first sync on, every
later step's "selection" is the current selection, including the `implementation_delivered`
observation that `## Delivery loop` step 7 builds.

**Sync run.** After `git fetch origin`, a PR head is a *sync run* from the current selection
when its first-parent walk back to that selection's head passes only two-parent merge commits,
and for each one `git merge-base --is-ancestor <second-parent> origin/<integration>` confirms
its second parent. Each merge of a sync run becomes one sync selection, oldest first, and each
is reviewed on its own.

## Trigger

Before the merge, read `gh pr view <pr-num> --json state,headRefOid,mergeable`. The route runs
when:

- the PR is open with `mergeable: CONFLICTING`, or `gh pr merge` was refused because the head
  conflicts with its base or is behind a base that requires an up-to-date head. A head merely
  behind a base with no such rule merges as it is;
- the PR is open and its `headRefOid` is not the current selection's head but a sync run from
  it, which is a crash after the push: resume at step 3;
- the PR has merged at a head that is a sync run from the current selection: see **A merge that
  already landed**.

`mergeable: UNKNOWN` means the provider has not computed it yet. It is no trigger: proceed to
the merge, and if the merge is then refused, the first case applies.

## Steps

Step 3 dispatches a reviewer. An owner that did not run SKILL.md's Phase-0 reviewer-dispatch
probe, such as a remainder owner, runs it before step 1, or before step 3 when the merge already
landed.

1. **Sync.** Make one merge of `origin/<integration>` into the current selection's head under
   Phase 1's sync rules, so its first parent is that head, and fold its conflict resolutions and
   sweeps into that merge commit. With a `Lifecycle worker:` line, make that merge as
   `git merge --no-commit --no-ff origin/<integration>` and commit it through `launch-commit`
   (SKILL.md's ### Local commits).
2. **Verify.** Run Phase 2's verification step.
3. **Review.** Run the merge-delta check below over that commit's combined diff,
   `git show --cc <merge-sha>`, through SKILL.md's merge-delta reviewer. Apply findings by
   amending the unpushed merge commit (through `launch-commit … -- --amend --no-edit` when this
   run holds a `Lifecycle worker:` line), which keeps both parents, and after every amend re-run
   Phase 2's verification step before the push. The link's `review_ref` is `merge-delta-empty`
   for an empty delta, and `merge-delta-clean` once every Blocking and Should-fix finding is
   applied and re-reviewed. Retain Minor and Discussion findings under Phase 5's durable
   Minor/Discussion detail.
4. **Push.** Run `check-launch` (SKILL.md's `## Launch guard`), then `git push origin <branch>`.
5. **Wait for CI.** Run Phase 6's CI wait, with the reviewed head re-fixed to the pushed head.
6. **Select.** For each merge of the sync run, oldest first, make `## Delivery loop`'s builder
   call with `--kind sync-selection`, from the installed `contract`, the current selection as
   `prior_selection`, the merge's `head`, its `tree` (`git rev-parse <merge-sha>^{tree}`), its
   `parents` (`git rev-list --parents -n 1 <merge-sha>`, first parent first), the `review_ref`
   from step 3, and `test_ref` `checks`. Each result is the next one's `prior_selection`, and
   the first one's is the current selection. Build each link's `selected_output` observation,
   then `branch_published` and `pr_opened` (the same PR) at the newest head, and checkpoint them
   all with the `--kind scope` for `merge_pr`.
7. **Merge.** Continue with `## Delivery loop`'s merge cycle.

Steps 1–5 precede the sync selection. So, like pre-selection publication, they run under the
native guard, repository policy and the `check-launch` fence, with no checkpoint.

## Merge-delta check

The reviewable delta is a sync-merge commit's combined diff (`git show --cc <merge-commit>` —
conflict resolutions and scope-creep sweeps). Dispatch SKILL.md's merge-delta reviewer over only
that delta, with Phase 1's scope-creep categories (retirement / addition) as its checklist plus
every review hint path passed in the retained snapshot. Findings come back Blocking / Should-fix
/ Discussion, ≤400 words, file:line anchors.

## A merge that already landed

When the PR merged at a sync run from the current selection, run step 3 for each of its merges,
then step 6 without a push or a CI wait. Add the `pr_merged` observation at that head to the
same checkpoint, and give it the next pending stage's `--kind scope` instead of `merge_pr`'s.
Then continue with the cleanup cycles.

## Stops

Each stop is Phase 6's genuinely-blocked stop: make no further forge write, checkpoint nothing,
run no cleanup, keep the worktree and the branch, and a human decides. In `--auto`, a step-1
conflict that Phase 1's sync rules would escalate or leave paused is one, taken before any push:
note the conflicted paths, then run `git merge --abort` so the worktree is back at the current
selection's head. So is a Blocking or Should-fix finding on a merge that is already pushed or
already landed, which no amend can apply, a PR head that is not a sync run from the current
selection (a non-merge commit, a first parent off the chain, or an unconfirmed integration
parent), red CI that needs a fix commit, and a failed reviewer-dispatch probe on either path,
which the sync path takes before step 1 makes any merge. The ship owner returns a
`terminal_failed` `ship-summary/v2` whose legacy `stopped` row's notes name the cause; a
remainder owner writes that summary with its own `finish`, as `## Remainder mode` says.
