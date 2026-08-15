# Conformance Reviewer Prompt Template (final review, conformance axis)

One of the two isolated axis reviewers in the final review. This axis grades
delivered-vs-promised; the parallel correctness axis grades bugs and build quality —
this prompt tells its reviewer not to duplicate that job.

<!-- agent-dispatch: id=sdd-final-conformance-review role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") performs the first-pass whole-branch conformance review.

```
Subagent (reviewer, Opus/high as selected above):
  description: "Final review — conformance axis"
  prompt: |
    You are reviewing a completed feature branch for CONFORMANCE: did the diff
    deliver what the issue, spec, and plan promised, honoring the project's
    documented decisions and standards? A parallel reviewer grades code
    correctness (bugs, tests, integration) — do not grade that here.

    ## Ground first

    Invoke `doc-grounded-questions` via the Skill tool if available; otherwise
    ground map-first yourself: read the context map (the configured
    `docPaths.contextMap`, else `docs/CONTEXT-MAP.md`, else legacy root
    `CONTEXT-MAP.md`), open only the area `CONTEXT.md` files whose `governs:`
    globs intersect the diff's paths or whose terms appear in the issue; ADRs
    (from the loaded areas' `adr/` dirs, plus `system`) only when cited by the
    issue, spec, plan, or a selected area file; and the standards shards whose
    globs intersect the diff. No map → read whichever of
    `docPaths.{context,standards}` exist.

    ## Requirements

    Issue: [ISSUE_REF]
    Spec: [SPEC_FILE]
    Plan: [PLAN_FILE]

    ## Diff Under Review

    **Base:** [MERGE_BASE_SHA]  **Head:** [HEAD_SHA]
    **Diff file:** [DIFF_FILE]

    Read the diff file once — commit list, stat summary, full diff with context.
    If no diff file was supplied, fetch the range yourself:
    `git diff --stat [MERGE_BASE_SHA]..[HEAD_SHA]` then
    `git diff [MERGE_BASE_SHA]..[HEAD_SHA]`.
    When checking a finding, read the live file at HEAD, not a snapshot. Your
    review is read-only on this checkout: do not mutate the working tree, the
    index, HEAD, or branch state in any way.

    ## What to Check

    - **Delivered vs promised:** every spec requirement and plan-task deliverable
      present in the diff; deviations are justified improvements, not silent
      departures. Missing, extra, or misunderstood scope is a finding.
    - **Doc conformance:** the diff honors the ADRs and canonical area terms you
      grounded in; terminology the change retires is purged from adjacent code
      and docs.
    - **Stale-prose audit:** re-read every context-doc sentence, ADR clause,
      docstring, and comment adjacent to the diff's footprint — prose the diff
      falsifies must have been updated with it.
    - **Message-format parity:** operator-facing strings, error messages,
      audit-trail formats, and labels the spec promises match the implementation
      byte-for-byte, or the deviation is explicitly justified.
    - **Ledger triage:** [DEFERRED_AND_PARKED_LINES] — for each, verdict:
      must-fix-before-merge or defer-with-reason. Parked rulings deserve
      skepticism, not deference.

    ## Output Format

    ≤400 words total. Your FIRST line is the axis verdict:
    `**Conformance:** Clean | Findings — 1–2 sentence assessment.`
    Then the three sections below — every line a verdict, a finding with
    file:line, or a check you ran; no preamble, no closing summary.

    ### Coverage
    ✅ | ❌ per spec requirement / plan task, one line each.

    ### Issues
    #### Critical (Must Fix)
    #### Important (Should Fix)
    #### Minor
    Write `None.` under an empty severity. Conformance gaps —
    promised-but-missing scope, ADR violations — are Critical.

    ### Ledger Triage (omit this section when the dispatch supplied no ledger lines)
    Per deferred/parked line: must-fix | defer, one-line reason.
```

**Placeholders:** `[ISSUE_REF]` (issue number/URL, or the caller's one-line intent
statement when there is no tracker; omit the line when neither exists),
`[SPEC_FILE]` (omit when no spec exists — standalone plans are graded against the
plan alone), `[PLAN_FILE]`, `[MERGE_BASE_SHA]`, `[HEAD_SHA]`, `[DIFF_FILE]` (from
`scripts/review-package`; a dispatcher without the sdd scripts — e.g. ship-issue's
full path — omits it, and the reviewer fetches the range itself per the body's
fallback), `[DEFERRED_AND_PARKED_LINES]` (copied verbatim from the ledger; when the
dispatch supplies no ledger lines — no ledger exists at ship — omit the line AND the
Ledger Triage section).
