# Final review — two axes (controller instructions)

Loaded by `SKILL.md` when all tasks are complete. This gate runs for **every**
risk lane — lanes narrow per-task review, never this one.

## Contents

- First pass
- Fix wave
- Acceptance record
- Final verification

## First pass

Run `review-package PLAN_FILE DELIVERY_BASE DELIVERY_HEAD` once, on the full SHAs
the cumulative delivery gate pinned in the ledger, never a recomputed merge base,
and apply "`SKILL.md`'s `### Review-package gate`" before either axis is
dispatched. Those two pins are the report's `base_sha` and `head_sha`
(`SKILL.md`'s `## Finish`); the fix wave does not move them.

Pass both axes the manifest root path and all four metrics (`root_bytes`,
`total_bytes`, `file_count`, `largest_member_bytes`), never shard lists or diff
contents. Review the branch on two axes **in parallel, as isolated subagents**
over that same package:

- **Conformance axis** — did the diff deliver what issue + spec + plan promised,
  honoring the project's ADRs, context docs, and standards, and does it meet the
  acceptance criteria, which gate delivery. Native `reviewer` on the Opus/high
  tier of [conformance-reviewer-prompt.md](conformance-reviewer-prompt.md).
- **Correctness axis** — is it built right: bugs, boundary error handling, dead
  branches, assertions that pin the documented contract, DRY, cross-task
  integration. Choose the route from the retained `capabilities.review.code`
  state before either axis is dispatched, never from how a Codex call failed:
  1. `blocked` stops with its capability reason and repair ID; neither axis is dispatched.
  2. `available`, with `codex-collaboration` installed → its `diff-review`
     operation, which owns the binding shape, transport, capacity and fallback.
  3. `unsupported`, or not installed → the Opus/high native reviewer selected in
     [correctness-reviewer-prompt.md](correctness-reviewer-prompt.md), directly.

  A Codex call made under `unsupported` is a routing error: discard its outcome,
  ledger the routing error beside the correctness verdict with identity
  `native`, and run rung 3, with no retry. The axis is never skipped.

**Acceptance criteria.** Before dispatching the conformance axis, build its
`[ACCEPTANCE_CRITERIA]` block (see
[conformance-reviewer-prompt.md](conformance-reviewer-prompt.md)). When the
caller supplied an issue and the retained `capabilities.tracker` is `available`,
read the issue once with
`<tracker-cli> issue view <num> --repo <repo_slug> --json body` (from
`bindings.tracker`, prefixed as
`bindings.tracker.credential_env.unset_before_invocation` requires). Copy the
criterion lines under its `## Acceptance criteria` heading, up to the next
heading, verbatim and in issue order, and number them `AC1`…`ACn`. A criterion
line is a checkbox line (`- [ ]` or `- [x]`) or a numbered line (`<n>. `), the
same lines writing-plans' `## Acceptance map` counts. Then add the line
`Declared verification:` followed by the command of each retained
`bindings.workflow.verification` id, in order, or `none` when the verification
capability is authored unsupported. No issue, an intent statement, an
`unsupported` tracker, or an issue without such lines is no criterion source:
omit the block, write no record, and report `acceptance_state: not_applicable`.
A `blocked` tracker capability, or a read that fails, stops the final review
before either axis is dispatched: report `failed` with
`conformance_verdict: not_run` and `acceptance_state: not_applicable`.

Point the conformance dispatch at the ledger's deferred-minor and parked lines. Verdicts come back ≤400 words each
(not counting the `### Acceptance` table), findings Critical/Important/Minor
anchored to file:line. **Never merge the two reports**: disposition each on its
own, and ledger both verdicts plus the correctness reviewer identity
(`Codex` | `native` | `fallback` + failure class). From `diff-review`, ledger its
scope too (`full` | `scoped: <N> of <M> product files` | `unmeasured`).

**Acceptance verdicts.** When the conformance dispatch carried
`[ACCEPTANCE_CRITERIA]`, check its `### Acceptance` table on the first pass,
before recording a verdict:

- An `evidence` `met` without the observed value or the threshold is `unverified`.
- A `code` `met` whose check is not on the Declared verification line and has no
  cited run is `unverified`.
- A missing table or row makes every missing `ACn` `unverified`; there is no
  re-dispatch.

Every `unmet` or `unverified` row is an acceptance finding: an Important finding
labelled `conformance` and its `ACn`, joined to the fixer's list. For an
`evidence` criterion, the fix is to re-measure and write that row's evidence
columns in the acceptance record. An acceptance finding is never parked with a
ruling, and the residual adjudication below never turns one into a parked line.
One that survives the fix wave is load-bearing: it sets
`conformance_verdict: findings` and forces the Residuals terminal state.

## Fix wave

Verify each finding against the live worktree first (reject stale or unsupported
ones in the ledger), then use one Opus/high fixer with the complete list labeled
by axis:

<!-- agent-dispatch: id=sdd-final-review-fixer role=implementer model=opus effort=high -->
Agent(subagent_type="implementer", model="opus", effort="high") fixes the verified whole-branch findings in one wave.

The fixer runs the focused tests covering each fix, and the build check when a
fix changes files the build evaluates, never the full declared verification
Where both axes flag the
same lines, dedupe at dispatch and credit both axes in the ledger. Then run
exactly one scoped re-review per axis that had findings, using that axis's
unchanged rubric with the named findings and bounded fix-range package:

<!-- agent-dispatch: id=sdd-final-conformance-rereview role=reviewer-lite model=sonnet effort=medium -->
Agent(subagent_type="reviewer-lite", model="sonnet", effort="medium") re-verdicts the named conformance findings against the bounded fix diff.
<!-- agent-dispatch: id=sdd-final-correctness-rereview role=reviewer-lite model=sonnet effort=medium -->
Agent(subagent_type="reviewer-lite", model="sonnet", effort="medium") re-verdicts the named correctness findings against the bounded fix diff.

For either axis, generate a fix-range package with
`review-package PLAN_FILE FIX_BASE HEAD` (FIX_BASE = the head that
axis's first pass reviewed) and apply "`SKILL.md`'s `### Review-package gate`"
before dispatch. Supply (1) the axis's findings list verbatim, (2) the
manifest root path and all four metrics, never shard lists or diff contents, and
(3) the instruction to validate the manifest and coverage, read each shard once
in manifest order, report an unreadable or mismatched shard, verdict
each finding ADDRESSED / NOT ADDRESSED (an ADDRESSED `evidence` acceptance
finding cites `observed <value> at <sha7> vs threshold <literal>`), and flag new breakage in the fix diff
only — out-of-scope observations go to the ledger as deferred minors; ≤400
words. Ambiguous or branch-wide judgment escapes reviewer-lite through this
explicit full-review dispatch:

<!-- agent-dispatch: id=sdd-final-rereview-escalation role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") adjudicates an ambiguous or branch-wide final-axis re-review escape.

Record the escalation and selected full-review role in the SDD ledger.

The conformance re-review re-verdicts acceptance findings like any other named
finding, and only those: every `ACn` it was not given keeps its first-pass
verdict, and a named one it returns no verdict for stays `unverified`. An
ADDRESSED `evidence` criterion without its citation
is recorded `unverified`.

Adjudicate residuals like the task-loop breaker. There is no second fix wave — residual load-bearing findings surface to the caller.

## Acceptance record

Write the record after the scoped re-reviews, or right after the first pass when
neither axis had findings, and before the **Final verification** step. Skip this section when the
conformance dispatch carried no `[ACCEPTANCE_CRITERIA]`.

The record is one committed file per plan, beside the plan:
`<plans dir>/<plan stem>.acceptance.md`. Its schema:

```markdown
# Acceptance record — issue #<n>

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
```

- One row per `ACn`, in order. `Criterion` is the issue line verbatim, without
  its checkbox.
- Whoever measured writes the evidence columns (`Observed`, `Commit`,
  `Conditions`): an implementer whose task brief names the measurement, or the
  final-review fixer. For a `code` row, `Observed` is `in final verification` or
  the cited run. For a `human` row the evidence columns hold `—`.
- You, the controller, write `Verdict`, using the four grading tokens
  `met`, `unmet`, `unverified` and `human_pending`; ship-issue Phase 0 may later
  rewrite an attested row to `met (attested)`.

Before writing, check freshness against each `evidence` row's own `Commit`, not
the head the conformance first pass graded. When a commit after the `Commit` of
an `evidence` row recorded `met` touches that row's measured surface, that row
becomes `unverified` (a fixer's re-measurement writes a fresh `Commit`, so only
later commits count). A `code` row recorded `met` on a cited run outside the
Declared verification line follows the same rule from that run's commit, unless
the check was run again and the fresh run cited. A row made `unverified` here is
an acceptance finding that survives the fix wave.

Write each row's final verdict into `Verdict`. When the record has no rows yet,
write the whole record. Commit the acceptance record, then run the **Final
verification** step. Under a lifecycle identity, register yourself for that
commit as `SKILL.md`'s `### Lifecycle workers` describes: run
`workflow-state register-worker --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`,
commit with
`launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <git commit arguments>`,
then run
`workflow-state release-worker --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> --event returned`.
A `launch fence refused: <reason>` takes that section's refusal route.

## Final verification

Run this after the fix wave and its scoped re-reviews (or right after the first
pass when neither axis had findings) and the acceptance record's commit (when there is one), before
you choose the terminal state. It is the plan's one run of the full declared
verification: every retained `bindings.workflow.verification` id, in order, each
dereferenced through `bindings.commands`.

Route on the retained `capabilities.verification` first. A blocked verification
capability stops and reports its `reason_code` and `repair_id`. When it is
authored unsupported, skip this step: append `Final verification: none declared`
to the SDD ledger, and `verification_state` reports the per-task focused tests.

1. **Check.** In the worktree, run `verified-tree check --verification <id>`,
   repeating `--verification` for each id, and keep the `tree` it prints.
   Exit 0 with `verified` means this exact tree already passed these commands:
   skip step 2.
2. **Run and record.** Otherwise run every declared verification command once,
   in the foreground with an explicit timeout above its duration, its output in
   a log on disk and only the tail read back. When every command passes, run
   `verified-tree record --tree <the checked tree>` with the same
   `--verification` ids.
3. **Ledger.** Append
   `Final verification: passed (head <full sha>, tree <tree id>)` to the SDD
   ledger.
4. **Repair once.** A failing command, a `record` that exits 3 with
   `tree_changed`, or a `check` or `record` that exits 2 is not a pass.
   Dispatch the final-review fixer above once, carrying the failing command and
   its log path, the `git status --porcelain` output for `tree_changed`, or the
   helper's stderr line for an exit 2, then run one scoped correctness
   re-review of that fix diff (the final correctness re-review, same fix-range
   package gate). With an acceptance record, every `met` `evidence` row whose
   measured surface the repair's commits touch becomes `unverified` in a record
   commit made the same way, landing before steps 1–3 run again. Then run steps 1–3 once more. If verification
   still does not pass, record the failure as a load-bearing correctness finding
   in the retained detail: the terminal state is Residuals, with
   `verification_state: failed` and `correctness_verdict: findings`. On that
   route, with a record, every `code` row whose check still fails becomes `unmet` in one more
   record commit made the same way, and no verified tree is recorded. Each
   `unverified` or `unmet` row here is an acceptance finding as above.
