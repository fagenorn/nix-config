# Task 1: Admit `deadline` in the ledger and the wire reply

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (the `blocked_on` constants, lines ~31–44)
- Modify: `home/common/agent-skills/scripts/delivery_model/_wire.py` (the `suspended` branch, line ~304)
- Test: `home/common/agent-skills/tests/test_workflow_state.py`
- Test: `home/common/agent-skills/tests/test_delivery_model.py`

**Interfaces:**
- Consumes: the existing `suspend`, `control`, `direct-owner`, `register-worker` and `release-worker` CLI verbs and the test harness helpers `init_run`, `spawn`, `suspend`, `control`, `assert_control_response_shape`, `assert_controller_finalized`, `worktree_fact`, `tracker_fact`, `acquire_direct`, `direct_owner`, `direct_state_path`, `read_state`, `state_path` (`LifecycleHarness`), and `OwnerExitFenceTest.spawn_with_worker` / `assert_refused`.
- Produces: `workflow-state suspend --blocked-on deadline` (exit 0, v2 `suspended` reply with `blocked_on: "deadline"`), which Task 2's skill text names as `blocked_on=deadline`.

**Invariants:**
- `"deadline" in BLOCKED_ON_VALUES`, `in OWNER_BLOCKED_ON_VALUES` (via the existing derivation, unchanged), and `in AUTO_RESUMABLE_BLOCKED_ON`.
- `unknown` stays reaper-only and `host_capacity` control-only: `OWNER_BLOCKED_ON_VALUES` is still `BLOCKED_ON_VALUES - {"unknown", "host_capacity"}`.
- No `schema_version` change, no migration (D2).
- `_wire.py`'s `suspended` closed set gains exactly `deadline`; every other `blocked_on` set in `_wire.py` (the delivery `checkpoint` response) is unchanged (D3).
- `suspend --blocked-on deadline` passes through the #222 owner-exit fence: with a live registered worker it exits 2, empty stdout, stderr `live workers: <ids>`, ledger bytes unchanged.

- [ ] **Step 1: Write the failing tests**

In `test_workflow_state.py`, inside `WorkflowStateLifecycleTest`, directly after `test_direct_reentry_resumes_an_agent_dispatch_suspension_in_place`, add:

```python
    def test_deadline_suspension_parks_the_attempt_without_spending_it(self):
        # An owner that stops cleanly at an sdd task boundary before its
        # deadline parks the attempt like any environmental pause: it stays
        # resumable and is not consumed (#281 D2).
        self.init_run()
        worktree = str(Path(self.root) / "wt-21")
        self.spawn(issue=21, worktree=worktree, budget_minutes=10)
        envelope = self.suspend(
            issue=21, attempt=1, blocked_on="deadline",
            now="2026-08-13T20:05:00Z",
        )
        self.assertEqual(envelope, {
            "interface_version": 2, "kind": "suspended", "run_id": self.run_id,
            "issue": 21, "custody": {"kind": "implementation", "attempt": 1,
                                     "launch": 1, "action_id": "21:1:1"},
            "blocked_on": "deadline", "reentry": "/from-issue 21 --auto",
        })
        issue = self.read_state()["issues"]["21"]
        self.assertEqual([attempt["attempt"] for attempt in issue["attempts"]], [1])
        attempt = issue["attempts"][-1]
        self.assertEqual(attempt["state"], "suspended")
        self.assertEqual(attempt["blocked_on"], "deadline")
        self.assertEqual(attempt["stalled_resumes"], 0)
        self.assertIsNone(attempt["result"])
        self.assertIsNone(attempt["finished_at"])
        self.assertIsNone(attempt["result_source"])
        self.assertIsNone(issue["outcome"])

    def test_a_label_sweep_resumes_a_deadline_suspension(self):
        # `deadline` is auto-resumable: a sweep that did not name the issue
        # (human_directed false) resumes it on the same attempt and worktree
        # (#281 D2).
        self.init_run()
        worktree = str(Path(self.root) / "wt-49")
        self.spawn(issue=49, worktree=worktree, budget_minutes=10)
        self.suspend(
            issue=49, attempt=1, blocked_on="deadline",
            now="2026-08-13T20:05:00Z",
        )
        observed = [self.worktree_fact(49, recorded={
            "path": os.path.abspath(worktree), "state": "matching_issue_branch",
        })]
        swept = self.control(
            now="2026-08-13T20:06:00Z", issues=[49],
            tracker=[self.tracker_fact(49)], worktrees=observed,
            human_directed=False,
        )
        self.assert_control_response_shape(swept)
        self.assertIn(("resume", 49), [(a["kind"], a.get("issue"))
                                       for a in swept["actions"]])
        issue = self.read_state()["issues"]["49"]
        self.assertEqual([a["attempt"] for a in issue["attempts"]], [1])
        attempt = issue["attempts"][-1]
        self.assertEqual((attempt["state"], attempt["blocked_on"]), ("active", None))
        self.assertEqual(attempt["worktree"], os.path.abspath(worktree))

    def test_direct_reentry_resumes_a_deadline_suspension_in_place(self):
        owner = self.acquire_direct()
        self.run_id = owner["run_id"]
        self.suspend(
            issue=73, attempt=1, blocked_on="deadline",
            now="2026-08-20T10:30:00Z",
        )
        resumed = self.direct_owner(
            now="2026-08-20T15:00:00Z",
            worktree=self.worktree_fact(73, recorded={
                "path": owner["worktree"], "state": "matching_issue_branch",
            }),
        )
        self.assertEqual(resumed, {
            **owner, "action_id": "73:1:2", "launch_kind": "resume",
            "deadline_at": "2026-08-20T18:00:00Z",
        })
        issue = json.loads(
            self.direct_state_path(owner["run_id"]).read_text()
        )["issues"]["73"]
        self.assertEqual([attempt["attempt"] for attempt in issue["attempts"]], [1])
        attempt = issue["attempts"][-1]
        self.assertEqual((attempt["state"], attempt["blocked_on"]), ("active", None))
        self.assertIsNone(attempt["prior_attempt"])
```

If the attempt record's worktree key is not `worktree`, read the key `spawn` writes (grep `def spawn` in the harness) and assert that key instead; the assertion must still compare the recorded path to `os.path.abspath(worktree)`.

In `OwnerExitFenceTest`, after `test_suspend_proceeds_once_the_worker_tree_is_stopped`, add:

```python
    def test_a_deadline_suspend_refuses_until_the_worker_is_released(self):
        worker = self.spawn_with_worker()
        before = self.state_path.read_bytes()
        self.assert_refused(
            self.suspend(issue=14, attempt=1, blocked_on="deadline",
                         now="2026-08-13T20:02:00Z", ok=False), before, worker)
        self.release_worker(worker_id=worker, event="stopped",
                            now="2026-08-13T20:03:00Z")
        self.assertEqual(
            self.suspend(issue=14, attempt=1, blocked_on="deadline",
                         now="2026-08-13T20:03:00Z")["blocked_on"], "deadline")
```

In `test_delivery_model.py::test_suspended_reply_is_closed_and_names_an_owner_cause`, extend the cause tuple to
`("usage_limit", "transport", "human_gate", "external", "agent_dispatch", "deadline")`.

The existing `unknown`-is-refused assertion in the `suspend` test above `test_agent_dispatch_suspension_parks_the_attempt_without_spending_it` stays as is and keeps covering "owner-path writes of `unknown` stay refused".

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest -k deadline -k names_an_owner_cause home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_model.py 2>&1 | tail -5`
Expected: FAILED — the four new `deadline` tests fail (argparse rejects `--blocked-on deadline`, `invalid choice`), and the delivery-model cause loop fails its `deadline` subtest.

- [ ] **Step 3: Write the minimal implementation**

`workflow-state.py`:
- Add `"deadline"` to `BLOCKED_ON_VALUES` and to `AUTO_RESUMABLE_BLOCKED_ON`. Leave `OWNER_BLOCKED_ON_VALUES`'s derivation untouched.
- Append to the comment block above `BLOCKED_ON_VALUES` (this text describes code behavior and must stay true):

```python
# ``deadline`` is an owner value: sdd's headroom rule writes it through
# ``suspend`` when too little time is left before the attempt's
# ``deadline_at`` for its next task. It is auto-resumable, like ``transport``,
# because a resume's fresh window is the remedy (per #281 D2).
```

`delivery_model/_wire.py`: in the `kind == "suspended"` branch only, add `"deadline"` to the closed set `{"usage_limit", "transport", "human_gate", "external", "agent_dispatch"}`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest -k deadline -k names_an_owner_cause -k agent_dispatch -k OwnerExitFence home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_model.py 2>&1 | tail -3`
Expected: `OK`, with no failures.

Run: `if git diff --unified=0 HEAD -- home/common/agent-skills/scripts/delivery_model/_wire.py | grep -E '^[-+].*"deadline"' | grep -v 'agent_dispatch", "deadline"}'; then echo "deadline added outside the suspended set"; exit 1; fi`
Expected: no output, exit 0 (only the `suspended` set gained `deadline`, D3).

Run: `just build` (foreground, timeout 3600000 ms) — the script is packaged into the build.
Expected: exits 0.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/scripts/delivery_model/_wire.py home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_model.py
launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- -m "feat(workflow-state): admit an auto-resumable deadline suspension (#281)" -m "<attribution lines>"
```
