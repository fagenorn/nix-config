# Phase 5 — Review mechanics

Read this when Phase 5 picks its path. It owns the reviewer templates, severity
mapping, and the apply/push fix flow. The dispatch selections themselves live in
SKILL.md — never inline a review.

## Merge-delta check (degraded path)

The reviewable delta is the sync-merge commit's combined diff (`git show --cc
<merge-commit>` — conflict resolutions and scope-creep sweeps) plus any commits
made after the head sdd reviewed. Empty → record "merge-delta empty, nothing to
review" in the PR body and continue to Phase 6. Non-empty → dispatch SKILL.md's
merge-delta reviewer over only that delta (nested dispatch works even inside an
`Agent` subagent; if `Agent` isn't in your tool surface, `ToolSearch`
`select:Agent` first), with Phase 1's scope-creep categories (retirement /
addition, see SYNC.md) as its checklist plus the project-hints review paragraph
when `projectHints` exists (a directory → its `review.md`; a single file →
itself; omit silently when absent). Findings come back Blocking / Should-fix /
Discussion, ≤400 words, file:line anchors.

## Full two-axis review — templates

Same machinery and rubrics as sdd's final review, over the post-sync range
`$BASE_SHA..$HEAD_SHA`. The conformance axis uses sdd's
`conformance-reviewer-prompt.md`, deployed beside its SKILL.md; the native
correctness fallback uses `correctness-reviewer-prompt.md`. At ship there is no
sdd ledger or diff package: omit the ledger-triage placeholder and let each
reviewer fetch the range per its template's fallback. Verdicts ≤400 words each,
Critical/Important/Minor, never merged.

sdd templates unavailable → still use the two isolated native dispatches in
SKILL.md, never one combined: one briefed with a pasted one-paragraph conformance
rubric (delivered-vs-promised against issue/spec/plan, doc conformance,
stale-prose audit, message-format parity), one with a pasted one-paragraph
correctness rubric (bugs, boundary error handling, dead branches,
assertions-that-pin, DRY, cross-task integration); same output contract, reports
kept separate.

When the correctness axis came through `codex-collaboration`'s `diff-review`, it returns
a scope alongside its verdict: `full` | `scoped: <N> of <M> product files` |
`unmeasured`. Record that scope in the PR body beside the correctness verdict — the
same surface a degraded run uses for "merge-delta empty, nothing to review". A scoped
Clean that reaches the PR body without its scope reads as full coverage, which is
exactly what this record prevents. ship-issue records no reviewer identity; this records
the scope only.

## Severity mapping (full path)

The apply/push flow below speaks Blocking / Should-fix; map per axis, never
merging reports: Critical ≙ Blocking (apply inline via the five steps),
Important ≙ Should-fix (same five steps in `--auto`, surfaced otherwise), Minor ≙
Discussion-grade (record; surface only when user-facing). Retain every Minor or
Discussion finding with its axis in the delivery-detail package; the single
durable `report_path` is the only terminal transport and `discussion_items`
remains empty.

## The five-step apply/push flow

Apply Blocking fixes inline — but `apply` and `push` are separate steps, not one
verb. The failure mode is "edited files, ran tests, forgot to commit, advanced to
Phase 6 polling CI on the stale tip." Follow this order:

1. Edit the file(s).
2. Re-run `verify.lint` + `verify.test` against the modified surface.
3. `git add` the changed files; commit `fix(issue-<num>): address PR review —
   <short blocker>` (follow `commit.coAuthoredBy`).
4. Run `check-launch` (SKILL.md's `## Launch guard`); on anything but
   `current: true`, stop without pushing and take the no-write stop. Then
   `git push`.
5. Verify the push landed: `gh pr view <pr-num> --json headRefOid` must equal
   `git rev-parse HEAD`. Diverged → the push didn't take; retry before Phase 6.

After step 5, a named finding from the full two-axis path gets SKILL.md's scoped
`reviewer-lite` re-review over only that finding and the bounded fix diff —
never as a first-pass, merge-delta, or whole-branch review. If the fix changes
unrelated behavior or the finding cannot be checked in that bounded diff, stop
the cheap re-review and return to the appropriate full Opus/high axis.

In `--auto`, apply Should-fix items inline through the same five steps and log
each as a PR comment with a one-line rationale. Only Discussion items stay
user-facing — surface those with a doc-grounded prompt. Then continue.

## Durable Minor/Discussion detail

Before Phase 8 may remove anything, collect every Minor/Discussion item from
either review path as the strict non-empty findings input. First, write the retained candidate
at `.superpowers/ship-review/<issue>/retained-detail.json` in the feature
worktree. That worktree-local path is deliberate and is the one exception to
the rule that workflow scratch never lives in a working tree: on publication
failure this flow re-reads the retained candidate and keeps the worktree, so
the candidate's lifetime is meant to be the worktree's. Do not relocate it to
`$TMPDIR` or the primary checkout. Run `artifact-budget validate-detail-input`
on that no-follow file and consume canonical stdout before invoking
review-package's `delivery-detail` mode (`~/.agents/bin/review-package`).
Supply issue/branch/run/head identity only; the producer derives the per-run
leaf beneath the primary checkout's `.superpowers/issue-delivery/` home and
enforces no-clobber publication.

On success, independently check the returned review-package root, set
`detail_state: "present"`, put its single main-root-relative path in
`report_path` and notes, and return no inline items. On publication failure,
re-read the retained source with `validate-detail-input`, consume canonical
stdout, compare it with the submitted candidate, and require non-empty findings
before setting `detail_state: "unpublished"`. Then keep the worktree and do not remove
it; return only `stopped` or `failed`. Missing, unreadable, malformed,
wrong-schema, or empty findings cannot support unpublished detail. With no
Minor/Discussion items, use `detail_state: "none"` and a null path.
