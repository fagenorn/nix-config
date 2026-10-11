# Fixture reviewer template

Text outside the fence is never rendered: [NOT_A_SLOT].

```
Subagent (fixture):
  description: "Review Task N"
  prompt: |
    Review one task.

    Brief: [BRIEF_FILE]
    Report: [REPORT_FILE]
    Plan: [PLAN_ROOT] ([PLAN_ROOT_BYTES], [PLAN_TOTAL_BYTES], [PLAN_FILE_COUNT], [PLAN_LARGEST_MEMBER_BYTES])

    Constraints:
    [GLOBAL_CONSTRAINTS]

    Range: [BASE_SHA]..[HEAD_SHA]
    Manifest: [MANIFEST_ROOT] ([ROOT_BYTES], [TOTAL_BYTES], [FILE_COUNT], [LARGEST_MEMBER_BYTES])

    ## Standards

    [STANDARDS]

    Stacks: [STACKS_DIR]

      Verdict: [Approved | Needs fixes]
```
