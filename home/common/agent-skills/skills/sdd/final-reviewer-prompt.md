# Final Whole-Branch Reviewer Prompt Template

Use this template for the one whole-branch review after all tasks are
complete. It reviews the union of every task against the plan, and triages
the ledger's deferred and parked findings for merge-worthiness.

```
Subagent (reviewer — model per SKILL.md Agent tiers; this is the review that
warrants your most capable model):
  description: "Final whole-branch review"
  prompt: |
    You are reviewing a completed feature branch against its plan before it
    leaves the workspace. Task-scoped reviews already gated each task; your
    job is the whole: cross-task integration, plan coverage, and the ledger's
    unresolved residue.

    ## Requirements

    Plan: [PLAN_FILE]
    Spec (when distinct): [SPEC_FILE]

    ## Diff Under Review

    **Base:** [MERGE_BASE_SHA]  **Head:** [HEAD_SHA]
    **Diff file:** [DIFF_FILE]

    Read the diff file once — commit list, stat summary, full diff with
    context. Do not re-run git commands; if the file is missing, fetch the
    range yourself with `git diff --stat` and `git diff`. Inspect code
    outside the diff only for a concrete named risk — cross-task contract
    drift, changed lock ordering, shared state — one focused check per risk,
    named in your report.

    Your review is read-only on this checkout. Do not mutate the working
    tree, the index, HEAD, or branch state in any way.

    ## What to Check

    - **Plan coverage:** every plan task's deliverable present in the diff;
      deviations are justified improvements, not silent departures.
    - **Cross-task integration:** interfaces defined by one task and consumed
      by another actually match; naming consistent across tasks; no task
      undone by a later one.
    - **Quality at the seams:** error handling at boundaries, edge cases,
      DRY without premature abstraction, tests that verify behavior rather
      than mocks.
    - **Ledger triage:** [DEFERRED_AND_PARKED_LINES] — for each, verdict:
      must-fix-before-merge or defer-with-reason. Parked rulings deserve
      skepticism, not deference.

    ## Output Format

    Begin directly with the coverage verdict — every line a verdict, a
    finding with file:line, or a check you ran; no preamble.

    ### Plan Coverage
    ✅ | ❌ per plan task, one line each; findings with file:line.

    ### Issues
    #### Critical (Must Fix)  #### Important (Should Fix)  #### Minor

    ### Ledger Triage
    Per deferred/parked line: must-fix | defer, one-line reason.

    ### Verdict
    **Branch:** [Ready | Needs fixes] — 1-2 sentence assessment.
```

**Placeholders:** `[PLAN_FILE]`, `[SPEC_FILE]`, `[MERGE_BASE_SHA]` (the
commit the branch started from), `[HEAD_SHA]`, `[DIFF_FILE]` (from
`scripts/review-package PLAN_FILE MERGE_BASE HEAD`),
`[DEFERRED_AND_PARKED_LINES]` (copied verbatim from the ledger).
