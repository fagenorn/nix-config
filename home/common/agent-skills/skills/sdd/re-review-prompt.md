# Scoped Re-Review Prompt Template

Use this template when dispatching a re-review after a fix round. The
re-reviewer verifies the findings were addressed and checks the fix diff for
new breakage. It is not a fresh review — the full review already happened.

**Purpose:** Verify each finding from the previous review was addressed, and
that the fix itself broke nothing.

This role is legal only because the call supplies named prior findings and a
`FIX_BASE_SHA..HEAD_SHA` diff package. It never performs a first pass or expands
its scope to the whole branch.

<!-- agent-dispatch: id=sdd-scoped-task-rereview role=reviewer-lite model=sonnet effort=medium -->
Agent(subagent_type="reviewer-lite", model="sonnet", effort="medium") verifies the named prior findings against the bounded fix diff.

```
Subagent (reviewer-lite, Sonnet/medium as selected above):
  description: "Re-review Task N fix round R"
  model: sonnet
  effort: medium
  prompt: |
    You are re-reviewing one task's fix round. A previous review produced
    findings; an implementer has attempted to fix them. Your job is to
    verdict each finding and inspect the fix diff — nothing else.

    ## The Task

    Read the task brief: [BRIEF_FILE]

    ## The Findings Under Verification

    [FINDINGS]

    ## The Fix

    Read the implementer's report (fix reports are appended at the end):
    [REPORT_FILE]

    **Fix base:** [FIX_BASE_SHA] (the head the previous review saw)
    **Head:** [HEAD_SHA]
    **Manifest:** [MANIFEST_ROOT]
    **Metrics:** [ROOT_BYTES], [TOTAL_BYTES], [FILE_COUNT], [LARGEST_MEMBER_BYTES]

    The dispatch supplies the manifest root path and all four metrics:
    `root_bytes`, `total_bytes`, `file_count`, and
    `largest_member_bytes`. Read the strict manifest first, validate complete
    coverage and declared bytes against the checker metrics, then read every
    shard exactly once in manifest order. A version-2 manifest may replace only
    an individually oversized auto-generated EF migration designer with its
    bounded `generated_evidence`; verify that entry against the companion
    migration/snapshot diff and the report's no-pending-model-change,
    generated-SQL, and provider-backed migration evidence. Explicitly report an
    unreadable, mismatched, or uncorroborated item as unreadable review evidence;
    do not fetch a fallback diff or approve the fix. The shards contain the fix
    commits, stat, and byte-complete handwritten fix diff with surrounding
    context. Do not re-run git commands.

    Your review is read-only on this checkout. Do not mutate the working
    tree, the index, HEAD, or branch state in any way.

    ## Scope

    Your scope is the findings list and the fix diff. Verdict every finding.
    Inspect the fix diff for new problems the fix itself introduced. Do NOT
    re-review code the fix did not touch: if you notice an issue entirely
    outside the fix diff, report it under Out-of-Scope Observations — it
    does not block this task and does not extend the loop. A broad
    whole-branch review happens after all tasks are complete.

    ## Tests

    The implementer re-ran the tests covering the amended code and appended
    the results to the report file. Treat the report as unverified claims:
    confirm the fix report names the covering tests and shows their output,
    and verify the claims against the diff. Do not re-run the suite to
    confirm their report. Run a test only when reading the code raises a
    specific doubt that no existing run answers — and then a focused test,
    never a package-wide suite.

    ## Output Format

    Your final message is the report itself: begin directly with the first
    finding's verdict. Every line is a verdict, a finding with file:line,
    or a check you ran — no preamble, no process narration.

    ### Finding Verdicts

    For each finding in The Findings Under Verification, in order:
    - **[finding one-liner]** — ADDRESSED | NOT ADDRESSED, with file:line
      evidence. "Attempted" is not addressed: the specific defect must no
      longer exist.

    ### New Breakage in the Fix Diff

    Anything the fix itself broke or introduced, with severity
    (Critical/Important/Minor) and file:line. "None" if clean.

    ### Out-of-Scope Observations

    Issues you noticed entirely outside the fix diff. Non-blocking; the
    controller ledgers these for the final review. "None" if none.
    If a finding needs ambiguous adjudication or branch-wide review, do not
    decide it: report it here so the controller can escalate explicitly to a
    full `reviewer` on Opus/high and record the escalation in the SDD ledger.

    ### Verdict

    **Fix round:** [All findings addressed, no new Critical/Important
    breakage | Findings remain open] — list the open ones.
```

**Placeholders:**
- `[BRIEF_FILE]` — the task brief file (same file the implementer worked from)
- `[FINDINGS]` — the Critical/Important findings and spec gaps from the
  previous review, copied verbatim, one per bullet
- `[REPORT_FILE]` — the implementer's report file (fix reports appended)
- `[FIX_BASE_SHA]` — the head the previous review saw
- `[HEAD_SHA]` — current commit
- `[MANIFEST_ROOT]` and `[ROOT_BYTES]`, `[TOTAL_BYTES]`,
  `[FILE_COUNT]`, `[LARGEST_MEMBER_BYTES]` — the manifest root path and all
  four metrics from the validated producer report

**Re-reviewer returns:** per-finding verdicts (ADDRESSED / NOT ADDRESSED),
new breakage in the fix diff, out-of-scope observations, and a round verdict.
