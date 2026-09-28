# Phases 6–7 — CI wait and merge mechanics

Read this when Phase 6 starts. It owns the rationale, retry/escalation scripts,
merge quirks and the post-selection sync route behind SKILL.md's Phase 6/7
rules.

## Why the blocking watch is shaped that way

```
timeout 300 gh pr checks <pr-num> --watch --fail-fast --interval 30
```

The 5-minute ceiling forces an assistant turn every ~5 min, which keeps the
subagent stream alive; the harness reaps a subagent that goes silent for ~9+ min
on a blocking Bash (which is what a 540s timeout produced). `--fail-fast` exits
on the first check to flip into a failing bucket, so failures surface without
waiting on parallel checks.

**Foreground only — do NOT background this.** No `run_in_background: true`, no
`Monitor`. The harness yields a subagent indefinitely when it sees a
long-running monitored background Bash and the subagent never wakes to issue the
next turn. The blocking foreground shape is correct: `gh` polls the API at the
network layer every ~30s while Bash blocks, costing zero model turns until it
returns.

**Why improvised polling is banned.** Transcript mining found one session that
ran a bare `gh pr checks <n>`, filtered for a single check, 244 times, plus
sessions burning dozens of `gh run view` re-runs and `true`/`:`/`date` no-op
keep-alive turns;
every such poll is a full model turn that re-reads the entire session prefix.
Never run `gh pr checks` without `--watch` more than once per phase, never
re-run `gh run view`/`tail` on a loop, never emit no-op commands to pass time.
For a single named check, still run the blocking watch and read that check's row
from its final output (or one `--json name,bucket` call afterwards).

## Exit codes

- **`0`** → all checks pass; continue to Phase 7.
- **`124`** (`timeout` fired) → still running past ~5 min. **Emit one short
  narration turn** (`CI: still pending at 5m, retry 2/8`) as the keep-alive, then
  re-run the identical command. Up to **8 times (~40 min)**. Still pending after
  that → escalate: GitHub Actions webhooks can fail to fire silently, leaving a
  PR indefinitely on "expected — Waiting for status to be reported". Prompt:
  "PR #<n> has been pending for ~40 min with no terminal CI state. Options:
  (a) wait another 10 min, (b) close+reopen to re-trigger checks, (c) merge
  without CI if the project allows admin-merge, (d) abort and investigate
  manually."
- **any other non-zero** → a check failed (or `gh` errored). Pull
  `gh run view <run-id> --log-failed`, ground against the failing surface
  (lint → standards doc, test → area spec/plan), surface.

**JSON-field note.** `conclusion` is not a valid field on `gh pr checks` — `gh`
rejects it (`--help` lists the real set). When you need structured output,
`bucket` (pass/fail/pending/skipping/cancel) is the cleanest decision field.

## Merge quirks (Phase 7)

**Do not pass `--no-ff`** — recent `gh` (≥ 2.83) rejects it
(`unknown flag: --no-ff`), and `--merge` alone already produces a true merge
commit (no squash, no rebase, no fast-forward).

**Why the exit code lies in a worktree checkout.** `gh pr merge` runs local
post-merge steps (check out the default branch, delete the local branch) that
fail with `failed to run git: fatal: '<branch>' is already used by worktree at
'<main-root>'` — a non-zero exit **after the merge already landed on the
remote**. Retrying the merge or reporting failure on that exit code is wrong;
run SKILL.md's verify first, and treat the exit code as meaningless until it
disagrees with `gh pr view`.

`--delete-branch` may fail or silently no-op on the remote branch while the
worktree still has it checked out; the remote merge still succeeds — hence
SKILL.md's `git ls-remote --heads` check (PR metadata like `headRefName` is
retained after deletion and proves nothing).

(`merged` is not a valid `gh pr view --json` field — use
`state`/`mergeCommit`/`mergedAt`.)

## Post-selection sync

Under lifecycle identity a selection is immutable, so a PR that needs the
integration branch after selection gets a **sync selection** that extends it and
never replaces it. The route belongs to whoever holds the merge gate: the ship
owner under implementation custody, or a remainder owner. The **current
selection** is the newest link of the ledger's selection chain. An owner that
does not hold it reads it from the ledger with `## Delivery loop`'s builder call
and `--kind current-selection`, fed only the installed `contract`. From the
first sync on, every later step's "selection" is the current selection,
including the `implementation_delivered` observation that `## Delivery loop`
step 7 builds.

**Sync run.** After `git fetch origin`, a PR head is a *sync run* from the
current selection when its first-parent walk back to that selection's head
passes only two-parent merge commits, and for each one
`git merge-base --is-ancestor <second-parent> origin/<integration>` confirms its
second parent. Each merge of a sync run becomes one sync selection, oldest
first, and each is reviewed on its own.

**Trigger.** Before the merge, read
`gh pr view <pr-num> --json state,headRefOid,mergeable`. The route runs when:

- the PR is open with `mergeable: CONFLICTING`, or `gh pr merge` was refused
  because the head conflicts with its base or is behind a base that requires an
  up-to-date head. A head merely behind a base with no such rule merges as it
  is;
- the PR is open and its `headRefOid` is not the current selection's head but a
  sync run from it, which is a crash after the push: resume at step 3;
- the PR has merged at a head that is a sync run from the current selection:
  see **A merge that already landed**.

`mergeable: UNKNOWN` means the provider has not computed it yet. It is no
trigger: proceed to the merge, and if the merge is then refused, the first case
applies.

A merge the provider refuses because the PR cannot merge into its base is a
stale head, not an authority denial: record no `authority-observation` for it.

**Steps.**

Step 3 dispatches a reviewer. An owner that did not run SKILL.md's Phase-0
reviewer-dispatch probe, such as a remainder owner, runs it before step 1, or
before step 3 when the merge already landed.

1. **Sync.** Make one merge of `origin/<integration>` into the current
   selection's head under [`SYNC.md`](./SYNC.md), so its first parent is that
   head, and fold its conflict resolutions and sweeps into that merge commit.
2. **Verify.** Run the Phase 2 verification commands.
3. **Review.** Run REVIEW.md's merge-delta check over that commit's combined
   diff, `git show --cc <merge-sha>`, through SKILL.md's merge-delta reviewer.
   Apply findings by amending the unpushed merge commit, which keeps both
   parents, and after every amend re-run the Phase 2 verification commands before the push.
   The link's `review_ref` is `merge-delta-empty` for an empty delta, and
   `merge-delta-clean` once every Blocking and Should-fix finding is applied
   and re-reviewed. Retain Minor and Discussion findings under REVIEW.md's
   durable-detail rules.
4. **Push.** Run `check-launch` (SKILL.md's `## Launch guard`), then
   `git push origin <branch>`.
5. **Wait for CI.** Run Phase 6's CI wait, with the reviewed head re-fixed to
   the pushed head.
6. **Select.** For each merge of the sync run, oldest first, make
   `## Delivery loop`'s builder call with `--kind sync-selection`, from the
   installed `contract`, the current selection as `prior_selection`, the
   merge's `head`, its `tree` (`git rev-parse <merge-sha>^{tree}`), its
   `parents` (`git rev-list --parents -n 1 <merge-sha>`, first parent first),
   the `review_ref` from step 3, and `test_ref` `checks`. Each result is the
   next one's `prior_selection`, and the first one's is the current selection. Build each link's `selected_output` observation,
   then `branch_published` and `pr_opened` (the same PR) at the newest head, and
   checkpoint them all with the `--kind scope` for `merge_pr`.
7. **Merge.** Continue with `## Delivery loop`'s merge cycle.

Steps 1–5 precede the sync selection. So, like pre-selection publication, they
run under the native guard, repository policy and the `check-launch` fence, with
no checkpoint. After a crash past step 4, resume at step 3 for the pushed sync
run, and step 5 then waits for CI. If the base moves again, the next sync
extends the chain.

**A merge that already landed.** When the PR merged at a sync run from the
current selection, run step 3 for each of its merges, then step 6 without a push
or a CI wait. Add the `pr_merged` observation at that head to the same
checkpoint, and give it the next pending stage's `--kind scope` instead of
`merge_pr`'s. Then continue with the cleanup cycles.

**Stops.** Each stop is Phase 6's genuinely-blocked stop: make no further forge
write, checkpoint nothing, run no cleanup, keep the worktree and the branch,
and a human decides. In `--auto`, a step-1 conflict that `SYNC.md` would
escalate or leave paused is one, taken before any push: note the conflicted
paths, then run `git merge --abort` so the worktree is back at the current
selection's head. So is a Blocking or Should-fix finding on a merge that is
already pushed or already landed, which no amend can apply, a PR head that is
not a sync run from the current selection (a non-merge commit, a first parent
off the chain, or an unconfirmed integration parent), red CI that needs a fix
commit, and a failed reviewer-dispatch probe on either path, which the sync
path takes before step 1 makes any merge. The ship owner returns a `terminal_failed` `ship-summary/v2` whose
legacy `stopped` row's notes name the cause; a remainder owner writes that
summary with its own `finish`, as `## Remainder mode` says.
