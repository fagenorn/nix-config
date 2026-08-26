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
    **Manifest:** [MANIFEST_ROOT]
    **Metrics:** [ROOT_BYTES], [TOTAL_BYTES], [FILE_COUNT], [LARGEST_MEMBER_BYTES]

    The SDD packet supplies the manifest root path and all four metrics:
    `root_bytes`, `total_bytes`, `file_count`, and
    `largest_member_bytes`. Read the strict manifest and validate its complete
    coverage and declared bytes against those checker metrics. For an unscoped
    review, read every shard exactly once in manifest order. Explicitly report
    an unreadable or mismatched shard as unreadable review evidence; do not
    fetch a fallback diff or report a clean axis. A version-3 manifest declares
    adaptive unchanged context and `stable-first-fit-whole-file` packaging while
    preserving every whole file diff and changed line; validate those fields and
    read the live file when the bounded context is insufficient. A version-2
    manifest, or version 3 with non-empty generated evidence, may carry bounded
    evidence for an oversized auto-generated EF migration designer; inspect its
    identities and model-shape counts with the companion
    migration/snapshot diff and require the report's no-pending-model-change,
    generated-SQL, and provider-backed migration evidence. It is not a waiver.
    When the packet states the
    review is scoped and lists the paths under review, retain the manifest root
    and metrics only as range-coverage evidence: do not read its shards.
    Instead, those listed paths are the whole of the range to fetch, so run
    `git diff [MERGE_BASE_SHA]..[HEAD_SHA] -- ':(literal)<path>'` once per listed
    path and fetch nothing wider — one invocation per path, the path passed as a
    single literal argument after `--`, never shell-joined with the other listed
    paths into one command line, and pathspec magic disabled by the `:(literal)`
    prefix. A listed path carries whatever bytes Git records, so it may hold a
    space, a newline, a non-UTF-8 byte, or a leading `:`; treated as anything but
    one literal argument it splits or is reinterpreted, and you silently read a
    diff that is not the one the packet bounded. A non-SDD dispatcher that
    supplies no manifest may fetch the full range with
    `git diff --stat [MERGE_BASE_SHA]..[HEAD_SHA]` then
    `git diff [MERGE_BASE_SHA]..[HEAD_SHA]`. When checking a finding, read the
    live file at HEAD, not a snapshot. Inspect code outside the diff only
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
manifest detection), `[MERGE_BASE_SHA]`, `[HEAD_SHA]`, `[MANIFEST_ROOT]`, and
`[ROOT_BYTES]`, `[TOTAL_BYTES]`, `[FILE_COUNT]`,
`[LARGEST_MEMBER_BYTES]`. SDD and the Codex `diff-review` packet always supply
the manifest root path and all four metrics from the validated producer report.
On a scoped dispatch they remain range-coverage evidence, but the packet directs
the reviewer to do not read its shards and instead fetch the selected literal
paths once each. A dispatcher without the sdd scripts omits the manifest inputs
and uses the non-SDD fallback above.
