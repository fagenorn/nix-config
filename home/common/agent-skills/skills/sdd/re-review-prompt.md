# Scoped Re-Review Prompt Template

Scoped to named prior findings and a `FIX_BASE_SHA..HEAD_SHA` fix diff; never a first pass or a whole-branch review.

<!-- agent-dispatch: id=sdd-scoped-task-rereview role=reviewer-lite model=sonnet effort=medium -->
Agent(subagent_type="reviewer-lite", model="sonnet", effort="medium") verifies the named prior findings against the bounded fix diff.

```
Subagent (reviewer-lite, Sonnet/medium as selected above):
  description: "Re-review Task N fix round R"
  model: sonnet
  effort: medium
  prompt: |
    You are re-reviewing one task's fix round: a previous review produced
    findings and an implementer has attempted to fix them. Verdict each
    finding and inspect the fix diff — nothing else.

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

    The four metrics are `root_bytes`, `total_bytes`, `file_count` and
    `largest_member_bytes`. Read the strict manifest first, validate complete
    coverage and declared bytes against them, then read every shard exactly
    once, in manifest order. Report an unreadable, mismatched or
    uncorroborated item as unreadable review evidence; never fetch a fallback
    diff or approve the fix. Version 3 keeps every whole handwritten file
    diff, declares the adaptive unchanged context and packs with
    `stable-first-fit-whole-file`: validate those fields, and read the live
    file when that context is insufficient. Version 2, and version 3 with
    `generated_evidence`, may replace an oversized auto-generated EF migration
    designer with a bounded entry: verify it against the companion
    migration/snapshot diff and the report's no-pending-model-change,
    generated-SQL and provider-backed migration evidence; that evidence is
    never a waiver. Do not re-run git commands.

    Your review is read-only on this checkout. Do not mutate the working
    tree, the index, HEAD, or branch state.

    ## Scope

    Your scope is the findings list and the fix diff: verdict every finding
    and look for new problems the fix introduced. Do NOT re-review code the
    fix did not touch; an issue entirely outside the fix diff goes under
    Out-of-Scope Observations and does not block this task or extend the loop.

    ## Tests

    The report's fix section is unverified claims: confirm it names the
    covering tests and shows their output, and verify the claims against the
    diff. Do not re-run the suite to confirm them. Run a test only when
    reading the code raises a specific doubt no existing run answers, and then
    a focused test, never a package-wide suite.

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

    Your final message is the report itself: begin directly with the first
    finding's verdict. Every line is a verdict, a finding with file:line, or
    a check you ran — no preamble, no process narration.

    ### Finding Verdicts

    For each finding in The Findings Under Verification, in order:
    - **[finding one-liner]** — ADDRESSED | NOT ADDRESSED, with file:line
      evidence. "Attempted" is not addressed: the specific defect must no
      longer exist.

    ### New Breakage in the Fix Diff

    Anything the fix itself broke or introduced, with severity
    (Critical/Important/Minor) and file:line. "None" if clean.

    ### Out-of-Scope Observations

    Issues entirely outside the fix diff; non-blocking, ledgered for the
    final review. "None" if none. If a finding needs ambiguous adjudication
    or branch-wide review, do not decide it: report it here so the controller
    can escalate explicitly to a full `reviewer` on Opus/high and record the
    escalation in the SDD ledger.

    ### Verdict

    **Fix round:** [All findings addressed, no new Critical/Important
    breakage | Findings remain open] — list the open ones.
```

**Placeholders:**
- `[BRIEF_FILE]` — the task brief file
- `[FINDINGS]` — the Critical/Important findings and spec gaps from the
  previous review, copied verbatim, one per bullet
- `[REPORT_FILE]` — the implementer's report file (fix reports appended)
- `[FIX_BASE_SHA]` — the head the previous review saw
- `[HEAD_SHA]` — current commit
- `[MANIFEST_ROOT]` and `[ROOT_BYTES]`, `[TOTAL_BYTES]`,
  `[FILE_COUNT]`, `[LARGEST_MEMBER_BYTES]` — the manifest root path and all
  four metrics from the validated producer report
