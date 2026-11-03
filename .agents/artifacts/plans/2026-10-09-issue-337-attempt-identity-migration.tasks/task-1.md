# Task 1: Core `lookup` and the pure `attempt_identity` module

> **Status: complete** at commit `1701032a`, carried onto `907dba23` by merge `cd7c09f7` (D32). Do not re-run this task. Its full text is `git show cd7c09f7:.agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.tasks/task-1.md` (D35).

**Files:**
- Modify: `python/agent_tools/transaction_core.py` (add `TransactionStore.lookup`; the module docstring's "No command and no caller until #125" sentence stays until Task 2 makes `workflow-state` a caller)
- Create: `python/agent_tools/attempt_identity.py`
- Modify: `tests/test_transaction_core.py` (one new `LookupTest` class)
- Create: `tests/test_attempt_identity.py`
- Modify: `justfile` (add `tests/test_attempt_identity.py` to `agent-workflow-tests`, right after `tests/test_transaction_core.py`)

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[],"id":1,"records":[]}}
```
