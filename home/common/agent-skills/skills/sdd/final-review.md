# Final review — two axes (controller instructions)

Loaded by `SKILL.md` when all tasks are complete. This gate runs for **every**
risk lane — lanes narrow per-task review, never this one.

For configured code review, the correctness axis reaches Codex only through `codex-collaboration`'s `diff-review`, which alone owns the review binding shape, its invocation and its validation; a binding shape error it reports stops this review with no Codex call, no retry and no native fallback. `blocked` stops. On the `available` route, a capacity rejection has no retry and no native fallback. A Codex call made under `unsupported` is a routing error, never a capacity rejection. Authored `unsupported` takes the caller's native correctness route directly and makes no Codex call. On the `available` route, a completed non-capacity runtime/output failure uses the existing single native fallback and records why.

Run `review-package PLAN_FILE DELIVERY_BASE DELIVERY_HEAD` once, using the
full SHA values pinned in the ledger by the cumulative delivery gate. Do not
recompute a merge base against a local integration branch. Capture its stdout unchanged and pass those bytes through
`artifact-budget validate-report --boundary producer --input -` before either
axis is dispatched. Generator exit 0 plus validator exit 0, a strict
`complete` report, and report/checker agreement permits dispatch. Generator
exit 3 records and returns `decompose_required` with no reviewer dispatched.
Generator exit 2, validator exit 2, malformed or unknown output, or disagreement
records and returns `failed` before dispatch.

Pass both axes the manifest root path and all four metrics (`root_bytes`,
`total_bytes`, `file_count`, `largest_member_bytes`), never shard lists or
diff contents. Every unscoped reviewer validates the strict manifest and
coverage, reads every shard once in manifest order, and explicitly reports an
unreadable or mismatched shard. For interface version 3, it verifies the
declared adaptive context and `stable-first-fit-whole-file` packing, treats
every changed line as covered, and opens the live file when the bounded
unchanged context is insufficient. For interface version 2, or version 3 with non-empty generated
evidence, it also inspects each bounded auto-generated EF designer evidence entry with the companion
migration/snapshot diff and requires the implementer's no-pending-model-change,
generated-SQL, and provider-backed migration evidence; this is evidence
decomposition, never a waiver. Then review the branch on two axes **in
parallel, as isolated subagents** over that same package:

- **Conformance axis** — did the diff deliver what issue + spec + plan promised, honoring the project's ADRs, context docs, and standards. Native `reviewer` on the Sonnet/high tier selected in [conformance-reviewer-prompt.md](conformance-reviewer-prompt.md) — delivered-vs-promised grading is checklist-shaped work against written promises; the top tier stays on correctness.
- **Correctness axis** — is it built right: bugs, boundary error handling, dead branches, assertions that pin the documented contract, DRY, cross-task integration. Choose the correctness route from the retained `capabilities.review.code` state before either axis is dispatched, never from how a Codex call failed:
  1. `blocked` stops with its capability reason and repair ID; neither axis is dispatched.
  2. `available`, with `codex-collaboration` installed → invoke its `diff-review` operation for this axis; that skill solely owns the isolated Codex transport launch and one-time native fallback, while the external Codex reviewer keeps its independently configured model. This is the only rung that reaches Codex and the only one where a capacity rejection binds, on the configured-review terms above.
  3. `unsupported`, or `available` without `codex-collaboration` installed → dispatch the Opus/high native reviewer selected in [correctness-reviewer-prompt.md](correctness-reviewer-prompt.md) directly; `codex-collaboration` is never invoked on this rung.

  A Codex call made under `unsupported` anyway is a routing error: discard its outcome — verdict, refusal or failure — record the routing error in the ledger beside the correctness verdict, with the axis's reviewer identity still `native`, and run the rung-3 native dispatch, with no retry, stop or suspension. The axis is never skipped; `blocked` stops the whole review instead.

Point the conformance dispatch at the ledger's deferred-minor and parked lines so it triages what must be fixed before merge. Verdicts come back ≤400 words each, findings Critical/Important/Minor anchored to file:line. **Never merge the two reports** into one narrative — they are independent signals; disposition each on its own, and record both verdicts plus the correctness axis's reviewer identity (`Codex` | `native` | `fallback` + failure class) in the ledger. When that axis came through `codex-collaboration`'s `diff-review`, record the scope it returned as well (`full` | `scoped: <N> of <M> product files` | `unmeasured`); the native reviewer dispatched directly returns no scope, so record none there.

Findings → verify each against the live worktree first (stale or unsupported ones are rejected by you, in the ledger), then use one Opus/high fixer with the complete list labeled by axis:

<!-- agent-dispatch: id=sdd-final-review-fixer role=implementer model=opus effort=high -->
Agent(subagent_type="implementer", model="opus", effort="high") fixes the verified whole-branch findings in one wave.

Where both axes flag the same lines, dedupe at dispatch and credit both axes in the ledger (per-finding fixers each rebuild context and re-run suites; a real session's per-finding fix wave cost more than all its tasks combined). Then run exactly one scoped re-review per axis that had findings, using that axis's unchanged rubric with the named findings and bounded fix-range package:

<!-- agent-dispatch: id=sdd-final-conformance-rereview role=reviewer-lite model=sonnet effort=medium -->
Agent(subagent_type="reviewer-lite", model="sonnet", effort="medium") re-verdicts the named conformance findings against the bounded fix diff.
<!-- agent-dispatch: id=sdd-final-correctness-rereview role=reviewer-lite model=sonnet effort=medium -->
Agent(subagent_type="reviewer-lite", model="sonnet", effort="medium") re-verdicts the named correctness findings against the bounded fix diff.

For either axis, generate a fix-range package with
`review-package PLAN_FILE FIX_BASE HEAD` (FIX_BASE = the head that
axis's first pass reviewed), then apply the same generator/validator exit gate
above before dispatch. Supply (1) the axis's findings list verbatim, (2) the
manifest root path and all four metrics, never shard lists or diff contents, and
(3) the instruction to validate the manifest and coverage, read each shard once
in manifest order, explicitly report an unreadable or mismatched shard, verdict
each finding ADDRESSED / NOT ADDRESSED, and flag new breakage in the fix diff
only — out-of-scope observations go to the ledger as deferred minors; ≤400
words. Ambiguous or branch-wide judgment escapes reviewer-lite through this
explicit full-review dispatch:

<!-- agent-dispatch: id=sdd-final-rereview-escalation role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") adjudicates an ambiguous or branch-wide final-axis re-review escape.

Record the escalation and selected full-review role in the SDD ledger. Adjudicate residuals like the task-loop breaker. There is no second fix wave — residual load-bearing findings surface to the caller.

## Final verification

Run this after the fix wave and its scoped re-reviews, or right after the first
pass when neither axis had findings, and before you choose the terminal state.
It is the plan's one run of the full declared verification: every retained
`bindings.workflow.verification` id, in order, each dereferenced through
`bindings.commands`.

Route on the retained `capabilities.verification` first. A blocked verification
capability stops and reports its `reason_code` and `repair_id`. When it is
authored unsupported, skip this step: append `Final verification: none declared`
to the SDD ledger, and `verification_state` reports the per-task focused tests
as it did before this step existed.

1. **Check.** In the worktree, run `verified-tree check --verification <id>`,
   repeating `--verification` for each id, and keep the `tree` it prints.
   Exit 0 with `verified` means this exact tree already passed these commands
   (a resumed controller, say): skip step 2.
2. **Run and record.** Otherwise run every declared verification command once,
   in the foreground with an explicit timeout above its duration, its output in
   a log on disk and only the tail read back. When every command passes, run
   `verified-tree record --tree <the checked tree>` with the same
   `--verification` ids.
3. **Ledger.** Append
   `Final verification: passed (head <full sha>, tree <tree id>)` to the SDD
   ledger. That line is the readable copy; the record file in the worktree's
   git directory is the one `verified-tree check` reads.
4. **Repair once.** A failing command, a `record` that exits 3 with
   `tree_changed`, or a `check` or `record` that exits 2 is not a pass.
   Dispatch the final-review fixer above once, carrying the failing command and
   its log path, the `git status --porcelain` output for `tree_changed`, or the
   helper's stderr line for an exit 2. Run one scoped correctness re-review of
   that fix diff, through the final correctness re-review above and the same
   fix-range package gate, then run steps 1–3 once more. If verification still
   does not pass, record the failure as a load-bearing correctness finding in
   the retained detail: the terminal state is Residuals and the report carries
   `verification_state: failed` and `correctness_verdict: findings`.
