# Phase 5 — Review mechanics

Read this when Phase 5 picks its path. It owns the reviewer templates, severity
mapping, and the apply/push fix flow. The dispatch selections themselves live in
SKILL.md — never inline a review.

For configured code review, the correctness axis reaches Codex only through `codex-collaboration`'s `diff-review`, which alone owns the review binding shape, its invocation and its validation; a binding shape error it reports stops this review with no Codex call, no retry and no native fallback. `blocked` stops. On the `available` route, a capacity rejection has no retry and no native fallback. A Codex call made under `unsupported` is a routing error, never a capacity rejection. Authored `unsupported` takes the caller's native correctness route directly and makes no Codex call. On the `available` route, a completed non-capacity runtime/output failure uses the existing single native fallback and records why.

## Merge-delta check (post-selection sync)

CI-MERGE.md's `## Post-selection sync` runs this for each later sync merge;
Phase 5 never does. The reviewable delta is that sync-merge commit's combined
diff (`git show --cc <merge-commit>` — conflict resolutions and scope-creep
sweeps). Dispatch SKILL.md's merge-delta reviewer over only that delta
(SKILL.md's Phase-0 reviewer-dispatch probe has already confirmed this context
can launch it), with Phase 1's
scope-creep categories (retirement /
addition, see SYNC.md) as its checklist plus every review hint path passed in
the retained snapshot. Findings come back Blocking / Should-fix /
Discussion, ≤400 words, file:line anchors.

## Full two-axis review — templates

Same machinery and rubrics as sdd's final review, over the range SKILL.md's
Phase 5 selected. The conformance axis uses sdd's
`conformance-reviewer-prompt.md`, deployed beside its SKILL.md; the native
correctness form uses `correctness-reviewer-prompt.md`. At ship there is no
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
same surface as Phase 5's `review range:` record. A scoped
Clean that reaches the PR body without its scope reads as full coverage, which is
exactly what this record prevents. ship-issue records no reviewer identity; this records
the scope only.

## Delta route

On `delta`, both axes run the templates above over `<review_base>..$HEAD_SHA`,
the range `review-range` printed. Correctness keeps its unchanged rubric and
correctness route. The conformance brief adds three things to the template's
issue, spec and plan paths. First, the final-review head R, with the statement
that sdd's final review already graded delivered-vs-promised for the branch at
R. Second, its job: judge whether each delta change — a fix commit resolving a
finding, a sync resolution, a learning doc — keeps the branch consistent with
the issue, spec, plan and standards without breaking a promise R already kept,
with Phase 1's scope-creep categories (retirement / addition, see SYNC.md) and
every review hint path passed in the retained snapshot as its checklist. Third,
a stale-prose audit limited to files the delta touches. It never grades the
whole branch's delivery again.

**Range record.** Phase 5 records its route in the PR body as
`review range: delta <review_base7>..<head7> since final-review <R7> (<L> lines, <F> files)`,
`review range: empty since final-review <R7>`, or `review range: full (<reason>)`,
where `<reason>` is `review-range`'s `reason`, `review-range unavailable`, or the
name of the failed prerequisite.

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
2. Run Phase 2's verification step (SKILL.md's `## Phase 2 — Verify locally`)
   on the modified worktree, before the commit.
3. `git add` the changed files; commit `fix(issue-<num>): address PR review —
   <short blocker>` (follow retained `bindings.vcs.commit.co_authored_by`),
   through `launch-commit` when this run holds a `Lifecycle worker:` line
   (SKILL.md's `### Local commits`).
4. Run `check-launch` (SKILL.md's `## Launch guard`); on anything but
   `current: true`, stop without pushing and take the no-write stop. Then
   `git push`.
5. Verify the push landed: `gh pr view <pr-num> --json headRefOid` must equal
   `git rev-parse HEAD`. Diverged → the push didn't take; retry before Phase 6.
   Once they match, re-fix `HEAD_SHA` to that observed `headRefOid`: the
   reviewed head advances only when a fix has actually landed on the PR, and
   Phase 6 compares against it.

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
before setting `detail_state: "unpublished"`. That `report_path` is the retained
candidate's **worktree-relative** path — the same
`.superpowers/ship-review/<issue>/retained-detail.json` written above, resolved
against the feature worktree — the one recorded on the attempt — and never
against the primary checkout. The two detail states are rooted differently on
purpose, and `workflow-state finish` enforces exactly that split: it resolves a
`present` path against `--repo-root` and an `unpublished` one against the
attempt's recorded worktree. Name the root in notes so a reader never has to
guess which one a bare relative path means.
Then keep the worktree and do not remove it; return only `stopped` or
`failed`. Missing, unreadable, malformed,
wrong-schema, or empty findings cannot support unpublished detail. With no
Minor/Discussion items, use `detail_state: "none"` and a null path.

## Delivery interface version 2

Review fix pushes precede selection, so they are pre-selection publication:
they run under `## Launch guard`'s `check-launch` fence, with no checkpoint.
Everything the ledger records about delivery — the selection whose
`review_ref` is this phase's durable report path (else the literal review
state), and every later effect — belongs to SKILL.md's `## Delivery loop`.
