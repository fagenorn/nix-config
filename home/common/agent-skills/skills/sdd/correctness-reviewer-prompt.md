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
    not a snapshot. If no diff file was supplied, fetch the range yourself with
    `git diff --stat [MERGE_BASE_SHA]..[HEAD_SHA]` then
    `git diff [MERGE_BASE_SHA]..[HEAD_SHA]` — both of them, unless the packet
    states the review is scoped and lists the paths under review, in which case
    neither of those two commands runs: those listed paths are the whole of the
    range to fetch, so run
    `git diff [MERGE_BASE_SHA]..[HEAD_SHA] -- ':(literal)<path>'` once per listed
    path and fetch nothing wider — one invocation per path, the path passed as a
    single literal argument after `--`, never shell-joined with the other listed
    paths into one command line, and pathspec magic disabled by the `:(literal)`
    prefix. A listed path carries whatever bytes Git records, so it may hold a
    space, a newline, a non-UTF-8 byte, or a leading `:`; treated as anything but
    one literal argument it splits or is reinterpreted, and you silently read a
    diff that is not the one the packet bounded. Inspect code outside the diff only
    to evaluate a concrete risk you can name — cross-task contract drift, changed
    lock ordering, shared mutable state — one focused check per named risk, named
    in your report. Your review is read-only on this checkout: do not mutate the
    working tree, the index, HEAD, or branch state in any way. Do not re-run the
    full test suite — the implementers' reported runs are the evidence; run at
    most one focused test to resolve a specific doubt reading the code raised.

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
    When the packet supplied to you states the review is scoped, that assessment
    clause opens with `scoped to <N> of <M> product files;` — after the em dash,
    never between the verdict word and the dash. When the packet says nothing about
    scoping, write the verdict exactly as above.
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
the Codex rubric, the `diff-review` packet supplies the same values — with one
deliberate exception: on a scoped dispatch that packet leaves `[DIFF_FILE]`
unsupplied, because the full-range package it names is exactly what scoping bounds.
That is what routes the reviewer into the fallback branch above, where the packet's
listed paths are the whole of the range to fetch.
