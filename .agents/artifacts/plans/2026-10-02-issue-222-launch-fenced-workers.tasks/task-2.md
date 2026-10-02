# Task 2: Owner-exit refusal while workers live

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py` (new `OwnerExitFenceTest`)
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py` (two existing flows extended)

**Interfaces:**
- Consumes (Task 1): `live_worker_ids(runtime, state) -> list[str]`, `worker_verdict(runtime, state, worker_id) -> tuple[str | None, str]`, `WORKER_ID_PATTERN`, and the harness helpers `register_worker`, `release_worker`, `check_worker`.
- Produces:
  - `fence_owner_exit(runtime, mutation, *, excused_worker: str | None = None) -> Mutation`, where `Mutation` is the existing alias.
  - `checkpoint-delivery` gains an optional `--worker-id <worker_id>` (per D11).
  - The refusal is exit 2 with stderr `workflow-state: live workers: <id>[, <id>…]` (ledger order) and empty stdout. Nothing persists.

**Invariants:**
- The fence applies to exactly these: `suspend`, legacy `finish`, `finish --summary-file`, `progress` (all calls, although only a handoff can end a launch) and `checkpoint-delivery`. `control` and `direct-owner` are never wrapped (per D4).
- The live set is computed **before** the mutation. A worker counts as blocking when it was live before and is not live after, excluding only `excused_worker`. Descendants of the excused worker still count.
- `excused_worker` must be in the pre-mutation live set. If it is not, the call is refused with `invalid --worker-id: <reason>` and nothing persists.
- A write that does not end any live worker's launch (plain progress, a non-suspending checkpoint, an idempotent finish replay) behaves exactly as before.
- A worker of another issue never blocks this issue's exit.

- [ ] **Step 1: Write the failing tests**

Add this to `test_workflow_state.py`, after `WorkerRegistryTest`:

```python
class OwnerExitFenceTest(LifecycleHarness, unittest.TestCase):
    """Owner-path writes that end a launch refuse while it has a live worker (#222)."""

    def spawn_with_worker(self):
        self.init_run()
        self.spawn(issue=14, worktree=str(self.root / "wt-14"))
        return self.register_worker(action_id="14:1:1",
                                    now="2026-08-13T20:01:00Z")["worker_id"]

    def assert_refused(self, completed, before, *workers):
        self.assertEqual((completed.returncode, completed.stdout), (2, ""))
        self.assertIn("live workers: " + ", ".join(workers), completed.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_suspend_refuses_until_the_worker_returns(self):
        worker = self.spawn_with_worker()
        before = self.state_path.read_bytes()
        self.assert_refused(
            self.suspend(issue=14, attempt=1, blocked_on="external",
                         now="2026-08-13T20:02:00Z", ok=False), before, worker)
        self.release_worker(worker_id=worker, event="returned",
                            now="2026-08-13T20:03:00Z")
        self.assertEqual(
            self.suspend(issue=14, attempt=1, blocked_on="external",
                         now="2026-08-13T20:03:00Z")["kind"], "suspended")

    def test_suspend_proceeds_once_the_worker_tree_is_stopped(self):
        worker = self.spawn_with_worker()
        child = self.register_worker(action_id="14:1:1", now="2026-08-13T20:01:00Z",
                                     parent=worker)["worker_id"]
        before = self.state_path.read_bytes()
        self.assert_refused(
            self.suspend(issue=14, attempt=1, blocked_on="agent_dispatch",
                         now="2026-08-13T20:02:00Z", ok=False), before, worker, child)
        self.release_worker(worker_id=worker, event="stopped",
                            now="2026-08-13T20:03:00Z")
        self.assertEqual(
            self.suspend(issue=14, attempt=1, blocked_on="agent_dispatch",
                         now="2026-08-13T20:03:00Z")["kind"], "suspended")

    def test_a_handoff_progress_refuses_but_plain_progress_does_not(self):
        worker = self.spawn_with_worker()
        self.progress(issue=14, phase=1, now="2026-08-13T20:02:00Z")
        handoff = self.write_handoff(14)
        before = self.state_path.read_bytes()
        self.assert_refused(
            self.progress(issue=14, phase=1, now="2026-08-13T20:03:00Z",
                          turn_count=118, handoff_path=handoff, ok=False),
            before, worker)
        self.release_worker(worker_id=worker, event="returned",
                            now="2026-08-13T20:04:00Z")
        handed = self.progress(issue=14, phase=1, now="2026-08-13T20:04:00Z",
                               turn_count=118, handoff_path=handoff)
        self.assertEqual(handed["action"], "handoff")

    def test_legacy_finish_refuses_until_the_worker_returns(self):
        worker = self.spawn_with_worker()
        # The harness `finish` round-trips through schema 2, which drops the
        # registry, so this case writes the contractless v5 state directly.
        state = self.read_state()
        state["issues"]["14"]["delivery"] = self.empty_delivery()
        state["issues"]["14"]["delivery_remainders"] = []
        self.write_state(state)
        result_path = self.root / "result-14-1.json"
        result_path.write_text(json.dumps({
            **self.merged_result(), "state": "failed", "pr_url": None,
            "merge_sha": None, "issue_closed": False, "notes": "owner failed"}),
            encoding="utf-8")

        def finish(now, ok):
            return self.run_cli("finish", "--repo-root", self.root, "--run-id",
                                self.run_id, "--issue", 14, "--attempt", 1,
                                "--result-file", result_path, "--now", now, ok=ok)

        before = self.state_path.read_bytes()
        self.assert_refused(finish("2026-08-13T20:02:00Z", False), before, worker)
        self.release_worker(worker_id=worker, event="returned",
                            now="2026-08-13T20:03:00Z")
        self.assertEqual(
            json.loads(finish("2026-08-13T20:03:00Z", True).stdout)["state"], "failed")

    def test_another_issues_worker_never_blocks(self):
        self.init_run()
        self.spawn(issue=14, worktree=str(self.root / "wt-14"))
        self.spawn(issue=15, worktree=str(self.root / "wt-15"))
        self.register_worker(action_id="15:1:1", now="2026-08-13T20:01:00Z")
        self.assertEqual(
            self.suspend(issue=14, attempt=1, blocked_on="external",
                         now="2026-08-13T20:02:00Z")["kind"], "suspended")
```

In `test_delivery_workflow.py`, `test_all_stages_fold_before_delivery_completion`, insert the following immediately before the existing `finished = run("finish", ...)` line, which stays unchanged:

```python
            worker = run("register-worker", "--repo-root", root, "--run-id",
                         action["run_id"], "--now", "2026-09-21T00:00:04Z",
                         "--action-id", custody_value["action_id"])["worker_id"]
            state_file = root / ".superpowers/workflows" / action["run_id"] / "state.json"
            before = state_file.read_bytes()
            refused = subprocess.run(
                [sys.executable, str(WORKFLOW), "finish", "--repo-root", str(root),
                 "--run-id", action["run_id"], "--summary-file",
                 str(write("summary.json", summary)), "--now", "2026-09-21T00:00:05Z"],
                capture_output=True, text=True, check=False)
            self.assertEqual((refused.returncode, refused.stdout), (2, ""))
            self.assertIn(f"live workers: {worker}", refused.stderr)
            self.assertEqual(state_file.read_bytes(), before)
            run("release-worker", "--repo-root", root, "--run-id", action["run_id"],
                "--now", "2026-09-21T00:00:05Z", "--worker-id", worker,
                "--event", "returned")
```

In `test_typed_effect_uses_raw_validation_and_both_launch_fences`, `provider_denial` branch, replace the existing `denied = invoke("checkpoint-delivery", ..., store("denied.json", denied_report), "--now", "2026-09-21T00:00:02Z")` statement with the following. The assertions that follow it stay unchanged:

```python
                    worker = json.loads(invoke(
                        "register-worker", "--repo-root", root, "--run-id",
                        action["run_id"], "--now", "2026-09-21T00:00:02Z",
                        "--action-id", action["custody"]["action_id"]).stdout)["worker_id"]
                    denied_path = store("denied.json", denied_report)
                    state_file = (root / ".superpowers/workflows" / action["run_id"]
                                  / "state.json")
                    before = state_file.read_bytes()
                    for excuse in ((), ("--worker-id", f"{action['custody']['action_id']}:w9")):
                        refused = invoke(
                            "checkpoint-delivery", "--repo-root", root, "--run-id",
                            action["run_id"], "--checkpoint-file", denied_path,
                            "--now", "2026-09-21T00:00:02Z", *excuse)
                        self.assertEqual((refused.returncode, refused.stdout), (2, b""))
                        self.assertEqual(state_file.read_bytes(), before)
                    self.assertIn(f"live workers: {worker}".encode(), invoke(
                        "checkpoint-delivery", "--repo-root", root, "--run-id",
                        action["run_id"], "--checkpoint-file", denied_path,
                        "--now", "2026-09-21T00:00:02Z").stderr)
                    denied = invoke(
                        "checkpoint-delivery", "--repo-root", root, "--run-id",
                        action["run_id"], "--checkpoint-file", denied_path,
                        "--now", "2026-09-21T00:00:02Z", "--worker-id", worker)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k OwnerExitFence 2>&1 | tail -3`
Expected: FAIL. `suspend` succeeds where the test expects exit 2.

- [ ] **Step 3: Implement**

1. Add `fence_owner_exit` next to `transact`. Its docstring says that an owner-path write ending a launch is refused while that launch has a live worker, that controller writes never pass through it, and that `excused_worker` is the calling ship owner of a checkpoint (per D4, D11). The algorithm: `live = live_worker_ids(runtime, state)`. If `excused_worker` is set and not in `live`, raise `WorkflowError(f"invalid --worker-id: {worker_verdict(runtime, state, excused_worker)[1]}")`. Then run `result, changed = mutation(state)`, set `blocking = [w for w in live if w != excused_worker and worker_verdict(runtime, state, w)[1] != "live"]`, raise `WorkflowError("live workers: " + ", ".join(blocking))` when it is non-empty, and otherwise return `(result, changed)`.
2. Wrap the mutation passed to `transact` in `command_suspend`, `command_progress`, `command_finish` (the legacy `finish` closure), `command_finish_delivery` and `command_checkpoint_delivery`. The last one passes `excused_worker=args.worker_id`.
3. Add `checkpoint.add_argument("--worker-id")`. In `command_checkpoint_delivery`, raise `WorkflowError("invalid worker_id")` before any read when the value does not match `WORKER_ID_PATTERN`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_workflow_delivery.py 2>&1 | tail -3`
Expected: `OK`. That includes Task 1's `test_a_resume_after_an_unavailable_owner_fences_its_workers`, which proves that the controller path is not fenced.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py
git commit -m "feat(workflow-state): refuse owner exits while a registered worker is live (#222)"
```

Decisions: per D4, D6, D11.
