# Correctness Reviewer Prompt Template (final review, correctness axis)

The native correctness axis; `codex-collaboration`'s `diff-review` also passes this file by absolute path as the Codex rubric, so nothing here may assume which model reads it.

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

    The SDD packet supplies the manifest root and the four metrics
    (`root_bytes`, `total_bytes`, `file_count`, `largest_member_bytes`).
    Read the strict manifest and validate complete coverage and declared bytes
    against those metrics. For an unscoped review, read every shard exactly
    once in manifest order. Report an unreadable or mismatched shard as
    unreadable review evidence; do not fetch a fallback diff or report a clean
    axis. Version 3: honor the declared `packaging.context_lines` and
    `stable-first-fit-whole-file` packaging, treat every changed line as
    covered, and read the live file when the bounded context is short.
    Version 2, or version 3 with non-empty `generated_evidence`: also check
    each bounded auto-generated EF designer evidence entry's identities and
    model-shape counts against the companion migration and snapshot diff, and
    require the report's no-pending-model-change, generated-SQL and
    provider-backed migration evidence; it is never a waiver.
    When the packet states the review is scoped and lists the paths under
    review, retain the manifest root and metrics only as range-coverage
    evidence: do not read its shards. Those listed paths are the whole of the
    range to fetch, so run
    `git diff [MERGE_BASE_SHA]..[HEAD_SHA] -- ':(literal)<path>'` once per listed
    path and fetch nothing wider: one invocation per path, the path passed as a
    single literal argument after `--`, never shell-joined with the other listed
    paths into one command line, and pathspec magic disabled by the `:(literal)`
    prefix (a path may hold a space, newline, non-UTF-8 byte or leading `:`, and
    anything but one literal argument splits or reinterprets it). A non-SDD
    dispatcher that supplies no manifest may fetch the full range with
    `git diff --stat [MERGE_BASE_SHA]..[HEAD_SHA]` then
    `git diff [MERGE_BASE_SHA]..[HEAD_SHA]`. When checking a finding, read the
    live file at HEAD, not a snapshot. Inspect code outside the diff only to
    evaluate a concrete risk you can name (cross-task contract drift, changed
    lock ordering, shared mutable state), one focused check per named risk,
    named in your report. Your review is read-only on this checkout: do not
    mutate the working tree, the index, HEAD, or branch state in any way. Do not
    re-run the full test suite; run at most one focused test to resolve a specific doubt
    reading the code raised.

    ## What to Check

    - **Bugs and boundaries:** error handling at boundaries,
      unfamiliar-principal / missing-entity fallbacks, edge cases, half-finished
      branches that assume the happy path.
    - **Dead branches:** stranded `else` arms, unused props, flag arms no code
      path reaches.
    - **Assertions that pin:** would the tests fail if the documented contract
      broke? Assertions that pass under any 400 emitter, any non-null array, or
      a substring of a transformed value pin nothing.
    - **DRY:** new helpers that duplicate ones the codebase already has.
    - **Cross-task integration:** interfaces one task defines and another
      consumes actually match; naming consistent across tasks; no task undone by
      a later one.

    Launch any subagent by type only, never by name: a subagent cannot spawn a
    named teammate, and a named launch returns an error instead of work. Read an
    existing file before writing to it: overwriting content you have not read
    destroys work you cannot see. Run each long command, every verification
    command included, in the foreground with an explicit timeout above its
    expected duration. If the host moves one to the background anyway, wait for
    it within the same turn: never end your turn while a command you started is
    still running.
    Never write an `until` or `while` loop around `sleep` to wait for something:
    if a wait is truly needed, run one bounded foreground `sleep N`, then check
    once.

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
manifest detection), `[MERGE_BASE_SHA]`, `[HEAD_SHA]`, `[MANIFEST_ROOT]`,
`[ROOT_BYTES]`, `[TOTAL_BYTES]`, `[FILE_COUNT]`, `[LARGEST_MEMBER_BYTES]`. A
dispatcher without the sdd scripts omits the manifest root and metrics and uses
the non-SDD fallback.
