# Correctness Reviewer Prompt Template (final review, correctness axis)

The native form of the correctness axis — dispatched directly when
`codex-collaboration` is unavailable. When that skill IS available, its `diff-review`
operation carries this file by absolute path as the Codex reviewer's rubric, so keep
the body reviewer-agnostic: nothing in it may assume which model is reading it.

When the native fallback owns this first-pass whole-branch axis, it uses the
explicit full reviewer tier:

<!-- agent-dispatch: id=sdd-final-correctness-review role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") performs the native first-pass whole-branch correctness review.

```
Subagent (reviewer, Opus/high for the native path selected above):
  description: "Final review — correctness axis"
  prompt: |
    You are reviewing a completed feature branch for CORRECTNESS: is it built
    right? A parallel reviewer grades conformance to issue/spec/docs — do not
    grade delivered-vs-promised scope here.

    ## Inputs

    Plan (routing context for what the tasks were): [PLAN_FILE]
    Verify commands: [VERIFY_COMMANDS]
    Standards: read `~/.agents/standards/the-bar.md`, its `stacks/` shards
    matching the diff's file types, and the project's `docs/standards/` shards
    whose globs intersect the diff.

    ## Diff Under Review

    **Base:** [MERGE_BASE_SHA]  **Head:** [HEAD_SHA]
    **Diff file:** [DIFF_FILE]

    Read the diff file once; when checking a finding, read the live file at HEAD,
    not a snapshot. If no diff file was supplied, fetch the range yourself:
    `git diff --stat [MERGE_BASE_SHA]..[HEAD_SHA]` then
    `git diff [MERGE_BASE_SHA]..[HEAD_SHA]`. Inspect code outside the diff only to
    evaluate a concrete risk you can name — cross-task contract drift, changed lock
    ordering, shared mutable state — one focused check per named risk, named in your
    report. Your review is read-only on this checkout: do not mutate the working
    tree, the index, HEAD, or branch state in any way. Do not re-run the full test
    suite — the implementers' reported runs are the evidence; run at most one
    focused test to resolve a specific doubt reading the code raised.

    ## What to Check

    - **Bugs and boundaries:** error handling at boundaries,
      unfamiliar-principal / missing-entity fallbacks, edge cases, half-finished
      branches that assume the happy path.
    - **Dead branches:** stranded `else` arms, unused props, flag arms no code
      path reaches — plan pivots leave these behind.
    - **Assertions that pin:** would the tests fail if the documented contract
      broke? Assertions that pass under any 400 emitter, any non-null array, or
      a substring of a transformed value pin nothing.
    - **DRY:** new helpers that duplicate ones the codebase already has.
    - **Cross-task integration:** interfaces one task defines and another
      consumes actually match; naming consistent across tasks; no task undone by
      a later one.

    ## Output Format

    ≤400 words total. Your FIRST line is the axis verdict:
    `**Correctness:** Clean | Findings — 1–2 sentence assessment.`
    Then exactly three top-level sections — every line a finding or a check you
    ran; no preamble, no closing summary. Every finding carries a stable ID,
    live `path:line` evidence, confidence (`high` / `medium` / `low`), and
    unknowns (`none` when empty). Write `None.` under an empty section. Report
    unreadable artifacts explicitly.

    ### Critical (Must Fix)
    ### Important (Should Fix)
    ### Minor
```

**Placeholders:** `[PLAN_FILE]`, `[VERIFY_COMMANDS]` (from the project bindings /
manifest detection), `[MERGE_BASE_SHA]`, `[HEAD_SHA]`, `[DIFF_FILE]` (from
`scripts/review-package`; a dispatcher without the sdd scripts omits it, and the
reviewer fetches the range itself per the body's fallback). When this file rides as
the Codex rubric, the `diff-review` packet supplies the same values.
