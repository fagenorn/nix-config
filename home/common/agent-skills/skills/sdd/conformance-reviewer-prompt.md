# Conformance Reviewer Prompt Template (final review, conformance axis)

<!-- agent-dispatch: id=sdd-final-conformance-review role=conformance-reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") performs the first-pass whole-branch conformance review.

```
Subagent (reviewer, Opus/high as selected above):
  description: "Final review — conformance axis"
  prompt: |
    You are reviewing a completed feature branch for CONFORMANCE: did the diff
    deliver what the issue, spec, and plan promised, honoring the project's
    documented decisions and standards? A parallel reviewer grades code
    correctness (bugs, tests, integration); do not grade that here.

    ## Ground first

    Receive the phase owner's retained snapshot. Ground map-first using its
    selected `bindings.paths.context` entry, open only the area `CONTEXT.md` files whose `governs:`
    globs intersect the diff's paths or whose terms appear in the issue; ADRs
    (from the loaded areas' `adr/` dirs, plus `system`) only when cited by the
    issue, spec, plan, or a selected area file; and the standards shards whose
    globs intersect the diff. With no selected map, use only passed context and standards paths.

    ## Requirements

    Issue: [ISSUE_REF]
    Spec: [SPEC_FILE]
    Plan: [PLAN_FILE]

    ## Acceptance criteria

    [ACCEPTANCE_CRITERIA]

    ## Diff Under Review

    **Base:** [MERGE_BASE_SHA]  **Head:** [HEAD_SHA]
    **Manifest:** [MANIFEST_ROOT]
    **Metrics:** [ROOT_BYTES], [TOTAL_BYTES], [FILE_COUNT], [LARGEST_MEMBER_BYTES]

    An SDD dispatch supplies the manifest root and the four metrics
    (`root_bytes`, `total_bytes`, `file_count`, `largest_member_bytes`).
    Read the strict manifest first, validate complete coverage and declared
    bytes against those metrics, then read every shard exactly once in
    manifest order. Report an unreadable or mismatched shard as unreadable
    review evidence; do not fetch a fallback diff or report a clean axis.
    Version 3: honor the declared `packaging.context_lines` and
    `stable-first-fit-whole-file` packaging, treat every changed line as
    covered, and read the live file when the bounded context is short.
    Version 2, or version 3 with non-empty `generated_evidence`: also check
    each bounded auto-generated EF designer evidence entry against the
    companion migration and snapshot diff, and require the
    reported no-pending-model-change, generated-SQL and provider-backed migration
    evidence the plan promised; the generated entry is never a review waiver. A non-SDD
    dispatcher that supplies no manifest may fetch the range itself:
    `git diff --stat [MERGE_BASE_SHA]..[HEAD_SHA]` then
    `git diff [MERGE_BASE_SHA]..[HEAD_SHA]`.
    When checking a finding, read the live file at HEAD, not a snapshot. Your
    review is read-only on this checkout: do not mutate the working tree, the
    index, HEAD, or branch state in any way.

    ## What to Check

    - **Delivered vs promised:** every spec requirement and plan-task deliverable
      is in the diff; deviations are justified improvements, not silent
      departures. Missing, extra, or misunderstood scope is a finding.
    - **Doc conformance:** the diff honors the ADRs and canonical area terms you
      grounded in; terminology it retires is purged from adjacent code and docs.
    - **Stale-prose audit:** re-read every context-doc sentence, ADR clause,
      docstring, and comment adjacent to the diff's footprint; any the diff
      falsifies must have been updated with it.
    - **Message-format parity:** operator-facing strings, error messages,
      audit-trail formats, and labels the spec promises match the implementation
      byte-for-byte, or the deviation is explicitly justified.
    - **Acceptance criteria:** skip this bullet when the dispatch has no Acceptance
      criteria section. Otherwise grade every criterion in the Acceptance
      criteria section, `AC1`…`ACn` in order, as exactly one of `met`,
      `unmet`, `unverified` or `human_pending`. Take each criterion's kind
      (`code`, `evidence` or `human`) from the plan's `## Acceptance map`
      when it has one, else from the inline tag. Classify an untagged line
      yourself; one you cannot classify is `unverified`.
      - `code`: `met` when its named check exists at HEAD and is part of the
        Declared verification line, which the final verification runs. A
        named check outside that line is `met` only when you ran it at HEAD
        and cite the command and its pass; otherwise it is `unverified`. A
        named check that is absent, or that you ran and saw fail, is `unmet`.
      - `evidence`: `met` only when its row in the acceptance record
        (`<plan stem>.acceptance.md`, beside the plan) shows a value inside
        the criterion's literal threshold, and the commits after the
        measured commit leave the measured surface alone. An evidence `met`
        must cite the observed value and the threshold; rounding or "close
        enough" never counts. A missing row is `unverified`, a stale row is
        `unverified`, and a value outside the threshold is `unmet`.
      - `human`: always `human_pending`. Never attest a human criterion.
      Every `unmet` or `unverified` row is an acceptance finding: list it
      under Important, labelled `conformance` and its `ACn`. An acceptance
      finding is never parked with a ruling.
    - **Ledger triage:** [DEFERRED_AND_PARKED_LINES] — for each, verdict:
      must-fix-before-merge or defer-with-reason. Parked rulings deserve
      skepticism, not deference.

    Launch any subagent by type only, never by name: a subagent cannot spawn a
    named teammate, and a named launch returns an error instead of work. Read an
    existing file before writing to it: overwriting content you have not read
    destroys work you cannot see. Run each long command, every verification
    command included, in the foreground with an explicit timeout above its
    expected duration. If the host moves one to the background anyway, wait for
    it in the same turn: never end your turn while a command or agent you
    started still runs.
    Never write an `until` or `while` loop around `sleep` to wait for something:
    if a wait is truly needed, run one bounded foreground `sleep N`, then check
    once.

    ## Output Format

    ≤400 words total, not counting the `### Acceptance` table. Your FIRST
    line is the axis verdict:
    `**Conformance:** Clean | Findings — 1–2 sentence assessment.`
    It is `Findings` whenever any Acceptance row is `unmet` or `unverified`.
    Then the sections below — every line a verdict, a finding with
    file:line, or a check you ran; no preamble, no closing summary.

    ### Coverage
    ✅ | ❌ per spec requirement / plan task, one line each.

    ### Acceptance (omit this section when the dispatch supplied no acceptance criteria)
    | AC | Kind | Verdict | Citation |
    One row per `ACn`, in order. `Citation` for a `code` row is the check name
    and either `in final verification` or the command you ran with its result;
    for an `evidence` row it is `observed <value> at <sha7> vs threshold <literal>`;
    for an `unmet` or `unverified` row it names what is missing or failing.

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
`[SPEC_FILE]` (omit when no spec exists), `[PLAN_FILE]`, `[MERGE_BASE_SHA]`, `[HEAD_SHA]`, `[MANIFEST_ROOT]`,
`[ROOT_BYTES]`, `[TOTAL_BYTES]`, `[FILE_COUNT]`, `[LARGEST_MEMBER_BYTES]` (the
manifest root and four metrics from SDD's validated producer report; a
dispatcher without the sdd scripts omits them and
the reviewer uses the body's fallback), `[ACCEPTANCE_CRITERIA]` (written by
sdd's controller per final-review.md: one line
`AC<n>: <the issue's criterion line verbatim, without its checkbox>` per
criterion, in issue order, then one line
`Declared verification: <each declared verification command, in order>`, or
`Declared verification: none`. With no criterion source (no issue, an
intent-statement `[ISSUE_REF]`, an issue without acceptance-criteria lines, or
ship-issue's full review) omit the `## Acceptance criteria` heading, this
placeholder AND the `### Acceptance` output section),
`[DEFERRED_AND_PARKED_LINES]` (copied verbatim from the ledger; with no ledger
lines, as at ship, omit the line AND the Ledger Triage section).
