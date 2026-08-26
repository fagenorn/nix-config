# Final review — two axes (controller instructions)

Loaded by `SKILL.md` when all tasks are complete. This gate runs for **every**
risk lane — lanes narrow per-task review, never this one.

Run `scripts/review-package PLAN_FILE MERGE_BASE HEAD` (MERGE_BASE = `git merge-base <integration-branch> HEAD`) once. Capture its stdout unchanged and pass those bytes through
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
- **Correctness axis** — is it built right: bugs, boundary error handling, dead branches, assertions that pin the documented contract, DRY, cross-task integration. When the `codex-collaboration` skill is available, invoke its `diff-review` operation for this axis; that skill solely owns the isolated Codex transport launch and one-time native fallback, while the external Codex reviewer keeps its independently configured model. Unavailable → use the Opus/high native reviewer selected in [correctness-reviewer-prompt.md](correctness-reviewer-prompt.md). Either way the axis is never skipped.

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
`scripts/review-package PLAN_FILE FIX_BASE HEAD` (FIX_BASE = the head that
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
