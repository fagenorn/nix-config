# Phase 5 — Review mechanics

Phase 5's review mechanics; `SKILL.md` Phase 5 holds the dispatch sites and the rung choice.

## Codex correctness route

For configured code review, the correctness axis reaches Codex only through `codex-collaboration`'s
`diff-review`, which alone owns the review binding shape, its invocation and its validation. A
binding shape error it reports stops this review with no Codex call, no retry and no native
fallback. `blocked` stops. On the `available` route, a capacity rejection has no retry and no native
fallback, and a completed non-capacity runtime/output failure uses the existing single native
fallback and records why. A Codex call made under `unsupported` is a routing error, never a capacity
rejection.

## Full two-axis review — templates

Same machinery and rubrics as sdd's final review, over the range SKILL.md's Phase 5 selected. The
conformance axis uses sdd's `conformance-reviewer-prompt.md`, deployed beside its SKILL.md; the
native correctness form uses `correctness-reviewer-prompt.md`. At ship there is no sdd ledger or
diff package: omit the ledger-triage placeholder and `[ACCEPTANCE_CRITERIA]`, and let each reviewer
fetch the range per its template's fallback. Verdicts ≤400 words each, Critical/Important/Minor,
never merged.

sdd templates unavailable → still use the two isolated native dispatches in SKILL.md, never one
combined: one briefed with a pasted one-paragraph conformance rubric (delivered-vs-promised against
issue/spec/plan, doc conformance, stale-prose audit, message-format parity), one with a pasted
one-paragraph correctness rubric (bugs, boundary error handling, dead branches, assertions-that-pin,
DRY, cross-task integration); same output contract, reports kept separate.

When the correctness axis came through `codex-collaboration`'s `diff-review`, it returns a scope
alongside its verdict: `full` | `scoped: <N> of <M> product files` | `unmeasured`. Record that scope
in the PR body beside the correctness verdict and Phase 5's `review range:` record.

## Delta route

On `delta`, both axes run the templates above over `<review_base>..$HEAD_SHA`. The conformance brief
adds three things to the template's issue, spec and plan paths. First, the final-review head R, with
the statement that sdd's final review already graded delivered-vs-promised for the branch at R.
Second, its job: judge whether each delta change — a fix commit resolving a finding, a sync
resolution, a learning doc — keeps the branch consistent with the issue, spec, plan and standards
without breaking a promise R already kept, with Phase 1's scope-creep categories (retirement /
addition) and every review hint path passed in the retained snapshot as its checklist. Third, a
stale-prose audit limited to files the delta touches.

**Range record.** Phase 5 records its route in the PR body as
`review range: delta <review_base7>..<head7> since final-review <R7> (<L> lines, <F> files)`,
`review range: empty since final-review <R7>`, or `review range: full (<reason>)`,
where `<reason>` is `review-range`'s `reason`, `review-range unavailable`, or the
name of the failed prerequisite.

## Severity mapping (full path)

The apply/push flow below speaks Blocking / Should-fix; map per axis, never merging reports:
Critical ≙ Blocking (apply inline via the five steps), Important ≙ Should-fix (same five steps in
`--auto`, surfaced otherwise), Minor ≙ Discussion-grade (record; surface only when user-facing).
Retain every Minor or Discussion finding with its axis in the delivery-detail package; the single
durable `report_path` is the only terminal transport and `discussion_items` remains empty.

## The five-step apply/push flow

Apply Blocking fixes inline — `apply` and `push` are separate steps. Follow this order:

1. Edit the file(s).
2. Run Phase 2's verification step (SKILL.md's `## Phase 2 — Verify locally`) on the modified
   worktree, before the commit.
3. `git add` the changed files; commit `fix(issue-<num>): address PR review — <short blocker>`
   (follow retained `bindings.vcs.commit.co_authored_by`), through `launch-commit` when this run
   holds a `Lifecycle worker:` line (SKILL.md's `### Local commits`).
4. Run `check-launch` (SKILL.md's `## Launch guard`); on anything but `current: true`, stop without
   pushing and take the no-write stop. Then `git push`.
5. Verify the push landed: `gh pr view <pr-num> --json headRefOid` must equal `git rev-parse HEAD`.
   Diverged → the push didn't take; retry before Phase 6. Once they match, re-fix `HEAD_SHA` to that
   observed `headRefOid`.

In `--auto`, apply Should-fix items inline through the same five steps and log each as a PR comment
with a one-line rationale. Only Discussion items stay user-facing — surface those with a
doc-grounded prompt. Then continue.

## Durable Minor/Discussion detail

Before Phase 8 may remove anything, collect every Minor/Discussion item from either review path as
the strict non-empty findings input. First, write the retained candidate at
`.superpowers/ship-review/<issue>/retained-detail.json` in the feature worktree. That path is
deliberately worktree-local: a publication failure re-reads it and keeps the worktree, so never
relocate it to `$TMPDIR` or the primary checkout. Run `artifact-budget validate-detail-input` on
that no-follow file and consume canonical stdout before invoking review-package's `delivery-detail`
mode (`~/.agents/bin/review-package`). Supply issue/branch/run/head identity only; the producer
derives the per-run leaf beneath the primary checkout's `.superpowers/issue-delivery/` home and
enforces no-clobber publication.

On success, independently check the returned review-package root, set `detail_state: "present"`, put
its single main-root-relative path in `report_path` and notes, and return no inline items. On
publication failure, re-read the retained source with `validate-detail-input`, consume canonical
stdout, compare it with the submitted candidate, and require non-empty findings before setting
`detail_state: "unpublished"`. That `report_path` is the retained candidate's **worktree-relative**
path, written above, never resolved against the primary checkout: `workflow-state finish` resolves a
`present` path against `--repo-root` and an `unpublished` one against the recorded worktree. Name
the root in notes. Then keep the worktree; return only `stopped` or `failed`. Missing, unreadable,
malformed, wrong-schema, or empty findings cannot support unpublished detail. With no
Minor/Discussion items, use `detail_state: "none"` and a null path.
