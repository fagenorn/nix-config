# Task 2: Ledger schema 8 — bind on locked reads, check on unlocked reads, `init-run` minting, identity-based direct reservation

> **Status: complete** at commit `aae76ba8`, carried onto `907dba23` by merge `cd7c09f7` (D32). Do not re-run this task. Its full text is `git show cd7c09f7:.agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.tasks/task-2.md` (D35).

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Modify: `home/common/agent-skills/scripts/workflow_delivery.py` (`DeliveryRuntime.migrate` only)
- Modify: `python/agent_tools/transaction_core.py` (module docstring sentence only: "No command and no caller until #125." becomes "Its first caller is `workflow-state`, which mints and binds attempt run transactions (#337).")
- Modify: `python/agent_tools/launch_scope.py` (`SAFE_SEGMENT` only, D18)
- Modify: `home/common/agent-skills/tests/test_workflow_state.py` (harness only: `LifecycleHarness.init_run`, `_as_legacy`, `finish`, new `install_legacy`, `store_root`, `tree_snapshot`)
- Modify: `home/common/agent-skills/tests/test_delivered_control.py` (harness only: `DeliveredControlHarness.setup_run`, D24)
- Create: `home/common/agent-skills/tests/test_attempt_migration.py`
- Modify: `tests/test_launch_scope.py` (one new test)
- Modify: `justfile` (add `home/common/agent-skills/tests/test_attempt_migration.py` to `agent-workflow-tests`, right after `test_workflow_state.py`)

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[],"id":2,"records":[]}}
```
