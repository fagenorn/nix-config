# Task 3: Orchestrated-hold refusal (R2)

Spec § Decisions (Orchestrated hold and refusal R2), per D5, D7, D8, D12 and D13. The AC2 case is this task's failing test: at its starting commit `direct-owner` answers an `observe` reply (exit 0) for an issue an orchestrated run holds.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (`ORCHESTRATED_RESUME`, `HOLD_REFUSAL`, `orchestrated_resume_command` and `refuse_orchestrated_hold` just above `def refuse_unmigrated_direct`; one call in `command_direct_owner`)
- Test: `home/common/agent-skills/tests/test_workflow_state.py` (new class `OrchestratedHoldTest`, appended)

**Interfaces:**
- Consumes: Task 2's `attempt_store.hold_runs(store, issue)` and `holds_issue` (already imported into `workflow-state.py`). Also `attempt_store.store_root`, `require_regular_path(path, label, allow_missing=True) -> bool`, `read_state_unlocked(state_path, run_id)` and `WorkflowError`. From `LifecycleHarness`: `init_run`, `spawn`, `suspend`, `fail_owner`, `direct_owner_raw`, `direct_owner`, `tree_snapshot`, `state_path`, `store_root`; and `TransactionStore` and `attempt_identity` (already imported by the test module).
- Produces:
  - `ORCHESTRATED_RESUME: str`, equal to `"orchestrate-control start --repo-root {repo_root} {issue} --run-id {run_id}"`.
  - `HOLD_REFUSAL: str`, equal to `"issue {issue} is held by orchestrated run {run_id}; resume it through orchestrate-issues: {resume}"`.
  - `orchestrated_resume_command(repo_root: str, issue: str, run_id: str) -> str`.
  - `refuse_orchestrated_hold(repo_root: Path, issue: int) -> None`.
  - Both constants are module-level string literals, so Task 4 reads them by AST (D13).

**Invariants:**
- `command_direct_owner` calls `refuse_orchestrated_hold(repo_root, issue)` right after the first `refuse_unmigrated_direct(...)` and before `ensure_workflows_directory`. That is before the issue lock, any bind or mint, whatever `new_run` and `owner_unavailable` are, and whatever any direct run's state is (D8).
- The check takes the handles `hold_runs` yields, in order. For each, it reads `<root>/.superpowers/workflows/<handle>/state.json`. An absent file is skipped. Otherwise the file is read with `read_state_unlocked(path, handle)`, whose error propagates unchanged (D7). An issue entry that is absent, or for which `holds_issue` is false, does not hold the issue.
- The first holder refuses with `WorkflowError(HOLD_REFUSAL.format(issue=issue, run_id=handle, resume=orchestrated_resume_command(str(repo_root), str(issue), handle)))`, where `repo_root` is the resolved root `direct-owner` already derives. The CLI prints that line after `workflow-state: ` and exits 2 with empty stdout. No file or directory under `.superpowers` is created or changed, and no `direct:<issue>:1` index entry is minted.
- It lists no directory. `test_control_cutover.py`'s AC1 tests stay green unmodified (D5).

- [ ] **Step 1: Write the failing tests**

Append to `home/common/agent-skills/tests/test_workflow_state.py`:

```python
class OrchestratedHoldTest(LifecycleHarness, unittest.TestCase):
    """Issue 475 R2: a direct acquisition of an issue an orchestrated run holds is refused
    with the command that re-enters that run, and writes nothing."""

    def setUp(self):
        super().setUp()
        self.init_run()
        self.spawn(issue=73, worktree=self.root / "wt-73")

    def expected(self):
        root = self.root.resolve()
        return (f"workflow-state: issue 73 is held by orchestrated run {self.run_id}; resume it "
                f"through orchestrate-issues: orchestrate-control start --repo-root {root} 73 "
                f"--run-id {self.run_id}\n")

    def test_every_direct_request_for_a_held_issue_is_refused_naming_the_resume_command(self):
        self.suspend(issue=73, attempt=1, blocked_on="human_gate",
                     now="2026-08-13T20:05:00Z")
        self.assertEqual(list(attempt_store.hold_runs(self.store_root, 73)), [self.run_id])
        before = self.tree_snapshot()
        for flags in ({}, {"owner_unavailable": True}, {"new_run": True}):
            with self.subTest(**flags):
                refused = self.direct_owner_raw(issue=73, ok=False, **flags)
                self.assertEqual((refused.returncode, refused.stdout, refused.stderr),
                                 (2, "", self.expected()))
                self.assertEqual(self.tree_snapshot(), before)
        self.assertIsNone(TransactionStore(self.store_root).lookup(
            attempt_identity.direct_key(73, 1)))

    def test_an_issue_the_run_no_longer_holds_is_acquired_directly(self):
        self.fail_owner(issue=73, attempt=1, now="2026-08-13T20:05:00Z")
        self.assertEqual(self.direct_owner(issue=73), {
            "interface_version": 1, "kind": "observe", "issue": 73,
            "run_id": None, "requirements": [{"kind": "tracker"}]})

    def test_an_invalid_holding_ledger_fails_loudly(self):
        self.state_path.write_text("{}\n", encoding="utf-8")
        refused = self.direct_owner_raw(issue=73, ok=False)
        self.assertEqual((refused.returncode, refused.stdout), (2, ""))
        self.assertEqual(refused.stderr, "workflow-state: workflow state refused: unknown_schema: "
                                         "unsupported workflow state schema version: None\n")
        self.assertIsNone(TransactionStore(self.store_root).lookup(
            attempt_identity.direct_key(73, 1)))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (Unit run): `home/common/agent-skills/tests/test_workflow_state.py -k OrchestratedHoldTest`
Expected: FAILED (failures=5). Each of the positive case's three flag subtests fails, the positive case fails once more at the end, and the invalid-ledger case fails. Each gets exit 0 with an `observe` reply where it expects the refusal. `test_an_issue_the_run_no_longer_holds_is_acquired_directly` passes, which pins today's behaviour.

- [ ] **Step 3: Write the implementation**

In `workflow-state.py`, just above `def refuse_unmigrated_direct`, add:

```python
# The orchestrate-control argv that re-enters one run for one issue, and the refusal that names
# it; from-issue's acquire-direct.md and orchestrate-issues branch on them, so they are literals
# the skill-contract test reads (issue 475 D8, D10).
ORCHESTRATED_RESUME = "orchestrate-control start --repo-root {repo_root} {issue} --run-id {run_id}"
HOLD_REFUSAL = ("issue {issue} is held by orchestrated run {run_id}; resume it through "
                "orchestrate-issues: {resume}")


def orchestrated_resume_command(repo_root: str, issue: str, run_id: str) -> str:
    """The `orchestrate-control start` argv that re-enters run `run_id` for `issue` alone."""
    return ORCHESTRATED_RESUME.format(repo_root=repo_root, issue=issue, run_id=run_id)


def refuse_orchestrated_hold(repo_root: Path, issue: int) -> None:
    """Refuse a direct acquisition of an issue an orchestrated run holds; writes nothing.

    The runs come from the issue's hold pointers, never from listing `workflows`. A run whose
    ledger is absent, or no longer holds the issue, does not hold it; a ledger that does not
    validate refuses the call with the reader's error (issue 475 D5, D7, D8).
    """
    superpowers = repo_root / ".superpowers"
    for handle in attempt_store.hold_runs(attempt_store.store_root(superpowers), issue):
        state_path = superpowers / "workflows" / handle / "state.json"
        if not require_regular_path(state_path, "workflow state", allow_missing=True):
            continue
        entry = read_state_unlocked(state_path, handle)["issues"].get(str(issue))
        if entry is not None and holds_issue(entry):
            raise WorkflowError(HOLD_REFUSAL.format(
                issue=issue, run_id=handle,
                resume=orchestrated_resume_command(str(repo_root), str(issue), handle)))
```

In `command_direct_owner`, directly after the first `refuse_unmigrated_direct(attempts, workflows_dir, issue)` (the one before `ensure_workflows_directory(repo_root)`), add `refuse_orchestrated_hold(repo_root, issue)`. Extend the comment above it to: "Refused before anything is created: a legacy ledger no index entry names is bound by `migrate --apply`, not on the spot (D22), and an issue an orchestrated run holds is resumed through that run (issue 475)."

- [ ] **Step 4: Verify**

Run (Unit run), once for each: `home/common/agent-skills/tests/test_workflow_state.py -k OrchestratedHoldTest -k HoldPointerWriteTest -k test_direct_owner`; `home/common/agent-skills/tests/test_control_cutover.py`; `home/common/agent-skills/tests/test_attempt_migration.py`.
Expected: OK for each, no failures or errors.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
launch-commit … -- -m "feat(workflow-state): refuse a direct acquisition of an orchestrated-held issue (issue 475)"
```
