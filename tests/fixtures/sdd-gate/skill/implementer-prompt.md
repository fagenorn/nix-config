# Fixture implementer template

```
Subagent (fixture):
  description: "Implement Task N"
  prompt: |
    Task [TASK_NUMBER]: [TASK_NAME]

    Brief: [BRIEF_FILE]
    Report: [REPORT_FILE]

    [CONTEXT]

    Plan: [PLAN_ROOT] ([PLAN_ROOT_BYTES], [PLAN_TOTAL_BYTES], [PLAN_FILE_COUNT], [PLAN_LARGEST_MEMBER_BYTES])

    Constraints:
    [GLOBAL_CONSTRAINTS]

    Seams:
    [TEST_SEAMS]

    ## Standards

    [STANDARDS]

    Stacks: [STACKS_DIR]

    ## Worker

    [LIFECYCLE_WORKER]

    End.
```
