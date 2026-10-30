# Task 1: Takeover refusal over live workers (R1)

Spec § Decisions (Live worker for takeover; Refusal R1: takeover with live workers), per D1, D2 and D3. The AC1 case is this task's failing test. At its starting commit the takeover proceeds: exit 0, with a `73:1:2` owner reply.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (new `TAKEOVER_REFUSAL` and `takeover_blockers` just above `live_worker_ids`; one check in `command_direct_owner`; the `fence_owner_exit` docstring)
- Test: `home/common/agent-skills/tests/test_workflow_state.py` (new classes `DirectTakeoverWorkerTest` and `TakeoverBlockersTest`, appended at the end of the file)

**Interfaces:**
- Consumes: `worker_verdict(runtime, state, worker_id) -> (current_action_id, reason)`, `parse_action_id(value) -> (issue, attempt, launch)`, `parse_utc(value, label) -> datetime`, `WorkflowError` and `_delivery()`, all existing in `workflow-state.py`. From `LifecycleHarness`: `init_worktree`, `acquire_direct(*, issue=73, now="2026-08-20T10:00:00Z", worktree=None, attempt_budget_minutes=180)`, `mark_progress`, `register_worker`, `release_worker`, `check_worker`, `direct_owner_raw`, `worktree_fact`, `tree_snapshot`, `empty_delivery` and `load_source_module`.
- Produces:
  - `TAKEOVER_REFUSAL: str`, a module-level literal equal to `"owner_unavailable refused: live workers: "`. Task 4's contract test reads it by AST (D13).
  - `takeover_blockers(runtime: Any, state: dict[str, Any], now: datetime) -> list[str]`.

**Invariants:**
- A worker blocks when `worker_verdict` reads it `live` and the record its launch belongs to has `deadline_at` strictly after `now`. That record is the issue's latest delivery remainder for a launch id containing `:r`, else its latest attempt. A live worker's launch is current, so the latest record is its record. The result is in `state["workers"]` order (D1).
- `mark-progress` is not read and gains nothing (D1).
- `command_direct_owner` checks the predicate once, only when `request["owner_unavailable"]` is true and `state` is not `None`. The check comes after the existing `owner_unavailable is not applicable`, active-owner and time-backward checks and before `_apply_one_issue_policy` (D2).
- On a non-empty result it raises `WorkflowError(TAKEOVER_REFUSAL + ", ".join(blocking))`. The CLI prints `workflow-state: owner_unavailable refused: live workers: <id>[, <id>…]` on stderr and exits 2 with empty stdout. Nothing under `.superpowers` changes (D3).
- `control`, the deadline reaper and every other `direct-owner` path behave as before. A takeover at or past the deadline takes the expiry path, as today (#310 D18).

- [ ] **Step 1: Write the failing tests**

Append to `home/common/agent-skills/tests/test_workflow_state.py`:

```python
class DirectTakeoverWorkerTest(LifecycleHarness, unittest.TestCase):
    """Issue 475 R1: an `owner_unavailable` takeover never fences a live worker inside its bound."""

    def setUp(self):
        super().setUp()
        self.worktree = self.root / "worktree-issue-73"
        self.init_worktree(self.worktree, branch="issue-73")
        owner = self.acquire_direct(worktree=self.worktree)
        self.run_id = owner["run_id"]
        self.assertEqual((owner["action_id"], owner["deadline_at"]),
                         ("73:1:1", "2026-08-20T13:00:00Z"))
        self.assertEqual(self.mark_progress(action_id="73:1:1", now="2026-08-20T10:01:00Z")[
            "outcome"], "baseline")
        self.register_worker(action_id="73:1:1", now="2026-08-20T10:02:00Z")
        self.register_worker(action_id="73:1:1", now="2026-08-20T10:02:00Z",
                             parent="73:1:1:w1")

    def takeover(self, now, *, ok=True):
        return self.direct_owner_raw(
            now=now, owner_unavailable=True, ok=ok,
            worktree=self.worktree_fact(73, recorded={
                "path": os.path.abspath(self.worktree), "state": "matching_issue_branch"}))

    def test_a_takeover_inside_the_deadline_names_every_live_worker(self):
        before = self.tree_snapshot()
        refused = self.takeover("2026-08-20T11:00:00Z", ok=False)
        self.assertEqual((refused.returncode, refused.stdout, refused.stderr), (
            2, "", "workflow-state: owner_unavailable refused: live workers: "
                   "73:1:1:w1, 73:1:1:w2\n"))
        self.assertEqual(self.tree_snapshot(), before)

    def test_a_takeover_proceeds_once_every_worker_is_released(self):
        self.release_worker(worker_id="73:1:1:w1", event="stopped",
                            now="2026-08-20T10:30:00Z")
        resumed = json.loads(self.takeover("2026-08-20T11:00:00Z").stdout)
        self.assertEqual((resumed["kind"], resumed["action_id"], resumed["launch_kind"]),
                         ("owner", "73:1:2", "resume"))

    def test_a_takeover_past_the_deadline_takes_the_expiry_path(self):
        resumed = json.loads(self.takeover("2026-08-20T13:00:00Z").stdout)
        self.assertEqual((resumed["kind"], resumed["action_id"], resumed["launch_kind"]),
                         ("owner", "73:1:2", "resume"))
        self.assertEqual(self.check_worker("73:1:1:w1")["reason"], "superseded_launch")


class TakeoverBlockersTest(LifecycleHarness, unittest.TestCase):
    """Issue 475 D1: the takeover predicate over attempt and remainder launches."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workflow_state = load_source_module(SCRIPT, "workflow_state_test_takeover")

    @staticmethod
    def worker(launch, ordinal=1, released_at=None):
        return {"worker_id": f"{launch}:w{ordinal}", "launch": launch, "parent": None,
                "registered_at": "2026-08-20T10:00:00Z", "released_at": released_at,
                "release_event": None if released_at is None else "stopped"}

    def state(self, workers):
        record = {"state": "active", "deadline_at": "2026-08-20T13:00:00Z",
                  "launches": [{}, {}]}
        return {"issues": {"73": {
            "attempts": [{**record, "issue": 73, "attempt": 1}],
            "delivery_remainders": [{**record, "remainder": 1}],
            "outcome": None, "delivery": self.empty_delivery()}}, "workers": workers}

    def blockers(self, workers, now="2026-08-20T11:00:00Z"):
        module = self.workflow_state
        return module.takeover_blockers(module._delivery(), self.state(workers),
                                        module.parse_utc(now, "now"))

    def test_only_live_workers_of_a_current_launch_inside_the_deadline_block(self):
        workers = [self.worker("73:1:1"), self.worker("73:r1:2"), self.worker("73:1:2"),
                   self.worker("73:1:2", 2, "2026-08-20T10:30:00Z")]
        self.assertEqual(self.blockers(workers), ["73:r1:2:w1", "73:1:2:w1"])
        self.assertEqual(self.blockers(workers, "2026-08-20T13:00:00Z"), [])
```

In the predicate test, `73:1:1:w1` sits under a superseded launch and `73:1:2:w2` is released. Neither blocks. At 13:00 the deadline has passed, so nothing blocks.

- [ ] **Step 2: Run the tests and watch them fail**

Run (Unit run): `home/common/agent-skills/tests/test_workflow_state.py -k DirectTakeoverWorkerTest -k TakeoverBlockersTest`
Expected: FAILED (failures=1, errors=1). `test_a_takeover_inside_the_deadline_names_every_live_worker` fails because exit 0 carries a `73:1:2` owner reply, and `TakeoverBlockersTest` errors with `has no attribute 'takeover_blockers'`. The two other `DirectTakeoverWorkerTest` cases pass, which pins today's behaviour.

- [ ] **Step 3: Write the implementation**

In `workflow-state.py`, just above `def live_worker_ids`, add:

```python
# The refusal a direct-owner takeover prints while live workers would be fenced; from-issue's
# acquire-direct.md branches on it, so it is a literal the skill-contract test reads (issue 475).
TAKEOVER_REFUSAL = "owner_unavailable refused: live workers: "


def takeover_blockers(runtime: Any, state: dict[str, Any], now: datetime) -> list[str]:
    """The live workers a `direct-owner` takeover at ``now`` would fence, in ledger order.

    A worker blocks while ``worker_verdict`` reads it live and the record its launch belongs
    to (the issue's latest delivery remainder for an ``:r`` launch, else its latest attempt)
    has ``deadline_at`` after ``now``; past the deadline the expiry reap recovers the run
    (issue 475 D1, D2; #310 D18).
    """
    blocking = []
    for worker in state.get("workers", []):
        if worker_verdict(runtime, state, worker["worker_id"])[1] != "live":
            continue
        issue, _, _ = parse_action_id(worker["launch"])
        issue_state = state["issues"][str(issue)]
        record = (issue_state["delivery_remainders"][-1] if ":r" in worker["launch"]
                  else issue_state["attempts"][-1])
        if now < parse_utc(record["deadline_at"], "attempt deadline"):
            blocking.append(worker["worker_id"])
    return blocking
```

In `command_direct_owner`, in the `else:` branch, directly after the `raise backward_refusal("direct owner time must not move backward", …)` block and before `policy = _apply_one_issue_policy(`, add at the same indentation as the `if issue_state is not None and issue_state["attempts"]:` line:

```python
                if request["owner_unavailable"] and state is not None:
                    blocking = takeover_blockers(
                        runtime, state, parse_utc(request["now"], "direct owner now"))
                    if blocking:
                        raise WorkflowError(TAKEOVER_REFUSAL + ", ".join(blocking))
```

In `fence_owner_exit`'s docstring, after the sentence ending "…whose owner died with workers live.", insert: "A ``direct-owner`` takeover refuses on its own while a live worker's launch is inside its deadline (``takeover_blockers``)."

- [ ] **Step 4: Verify**

Run (Unit run): `home/common/agent-skills/tests/test_workflow_state.py -k DirectTakeoverWorkerTest -k TakeoverBlockersTest -k WorkerRegistryTest -k OwnerExitFenceTest -k DelegatedShipLaunchTest -k test_direct_owner`
Expected: OK, no failures or errors.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
launch-commit … -- -m "feat(workflow-state): refuse a direct takeover that would fence live workers (issue 475)"
```
