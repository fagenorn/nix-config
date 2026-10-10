# Task 3: `direct-owner` on run transactions

> **Status: complete** at commit `b5519a4b`, carried onto `907dba23` by merge `cd7c09f7` (D32). Do not re-run this task. Its full text is `git show cd7c09f7:.agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.tasks/task-3.md` (D35).

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (`command_direct_owner`, `_apply_one_issue_policy` and its three call sites)
- Modify: `home/common/agent-skills/tests/test_workflow_state.py` (harness only: new `direct_run_id`)
- Modify: `home/common/agent-skills/tests/test_attempt_migration.py` (new `DirectOwnerIdentityTest`)

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[],"id":3,"records":[]}}
```
