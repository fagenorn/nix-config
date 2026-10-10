# Task 1: Ledger tests for a delegated ship launch

Issue: https://github.com/fagenorn/nix-config/issues/352. Spec: `.agents/artifacts/specs/2026-10-10-issue-352-delegated-ship-routing-design.md` (`## Test seams` item 1; ledger rows D1, D3, D5, D11).

Background for a reader with no context. A from-issue owner holds one launch identity, the `action_id` string `<issue>:<attempt>:<launch>` (here `14:1:1`). When its phase gate answers `delegate`, it hands the remaining phases to a fresh owner that adopts the same `action_id`: the ledger records no delegation, no new attempt and no new launch. After this issue's change, that delegated owner returns after Phase 6 and the first owner registers and launches the ship owner as a worker of the same launch. This task proves, at the `workflow-state` command line, that the ledger as it stands today admits that sequence and still fences it. It changes no product code.

**Files:**
- Modify: `home/common/agent-skills/tests/test_workflow_state.py` (one new class, inserted immediately before `class PhaseGateReplyTest(LifecycleHarness, unittest.TestCase):`)

**Interfaces:**
- Consumes, all existing `LifecycleHarness` methods: `init_run()`, `spawn(issue=, worktree=) -> {"id": ...}`, `progress(issue=, phase=, now=, remainder_self_contained=) -> {"action": ...}`, `register_worker(action_id=, now=, parent=None, ok=True)`, `release_worker(worker_id=, event=, now=)`, `check_worker(worker_id)`, `check_launch(action_id=)`, `resume(issue=, worktree=, now=, owner_unavailable=)`, `read_state()`, `write_state(state)`, `empty_delivery()`, `merged_result()`, `run_cli(*args, ok=)`, and the properties `root`, `run_id`, `state_path`.
- Produces: `DelegatedShipLaunchTest` with three tests. No later task uses it.

**Invariants:**
- Only `test_workflow_state.py` changes. `home/common/agent-skills/scripts/workflow-state.py` is not touched (D5).
- No existing test, helper or assertion is edited.
- After a persisted `delegate` and a released worker, one attempt and one launch exist, and the next registered worker is `14:1:1:w2` with a null parent.
- `finish` is refused with `live workers: 14:1:1:w2` while the ship worker is live and accepted after its release; afterwards the launch answers `inactive_attempt` and registers nothing.
- After a relaunch to `14:1:2`, a registration under `14:1:1` is refused as `superseded_launch` and writes nothing.

- [ ] **Step 1: Confirm the starting observation**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k DelegatedShipLaunchTest; echo "exit=$?"` (timeout 1800 s)
Expected at the commit you start from: `Ran 0 tests`, `NO TESTS RAN`, `exit=5`. That non-zero exit is this task's incomplete state.

- [ ] **Step 2: Add the test class**

These are characterization tests (D11): the helper already behaves this way, so there is no red step beyond Step 1. Insert the class below, followed by two blank lines, immediately before the line `class PhaseGateReplyTest(LifecycleHarness, unittest.TestCase):`.

```python
class DelegatedShipLaunchTest(LifecycleHarness, unittest.TestCase):
    """#352: a delegated owner returns after Phase 6 and its delegator ships.

    The ledger records no delegation, so both owners act under one launch.
    """

    def return_from_the_delegated_owner(self):
        self.init_run()
        spawned = self.spawn(issue=14, worktree=str(self.root / "wt-14"))
        self.assertEqual(spawned["id"], "14:1:1")
        gate = self.progress(issue=14, phase=5, now="2026-08-13T20:01:00Z",
                             remainder_self_contained=True)
        self.assertEqual(gate["action"], "delegate")
        attempt = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual(attempt["phase_action"], "delegate")
        implementer = self.register_worker(action_id="14:1:1",
                                           now="2026-08-13T20:02:00Z")["worker_id"]
        self.release_worker(worker_id=implementer, event="returned",
                            now="2026-08-13T20:03:00Z")
        self.progress(issue=14, phase=6, now="2026-08-13T20:04:00Z",
                      remainder_self_contained=True)
        return implementer

    def legacy_finish(self, now, ok):
        # The harness `finish` round-trips through schema 2, which drops the
        # registry, so this writes the contractless state directly.
        state = self.read_state()
        state["issues"]["14"]["delivery"] = self.empty_delivery()
        state["issues"]["14"]["delivery_remainders"] = []
        self.write_state(state)
        result_path = self.root / "result-14-1.json"
        result_path.write_text(json.dumps(self.merged_result()), encoding="utf-8")
        return self.run_cli("finish", "--repo-root", self.root, "--run-id",
                            self.run_id, "--issue", 14, "--attempt", 1,
                            "--result-file", result_path, "--now", now, ok=ok)

    def test_the_delegator_registers_the_ship_owner_under_the_same_launch(self):
        implementer = self.return_from_the_delegated_owner()
        ship_owner = self.register_worker(action_id="14:1:1",
                                          now="2026-08-13T20:05:00Z")
        self.assertEqual(ship_owner, {"worker_id": "14:1:1:w2", "launch": "14:1:1",
                                      "parent": None})
        attempts = self.read_state()["issues"]["14"]["attempts"]
        self.assertEqual((len(attempts), len(attempts[0]["launches"])), (1, 1))
        self.assertEqual(
            [w["worker_id"] for w in self.read_state()["workers"]
             if w["released_at"] is None], ["14:1:1:w2"])
        self.assertEqual(self.check_worker(implementer)["reason"], "released")
        self.assertEqual(self.check_worker("14:1:1:w2"), {
            "worker_id": "14:1:1:w2", "live": True,
            "current_action_id": "14:1:1", "reason": "live"})
        self.assertIs(self.check_launch(action_id="14:1:1")["current"], True)

    def test_finish_waits_for_the_ship_owner_and_then_ends_the_launch(self):
        self.return_from_the_delegated_owner()
        ship_owner = self.register_worker(action_id="14:1:1",
                                          now="2026-08-13T20:05:00Z")["worker_id"]
        refused = self.legacy_finish("2026-08-13T20:06:00Z", False)
        self.assertEqual((refused.returncode, refused.stdout), (2, ""))
        self.assertIn("live workers: " + ship_owner, refused.stderr)
        self.release_worker(worker_id=ship_owner, event="returned",
                            now="2026-08-13T20:07:00Z")
        finished = json.loads(self.legacy_finish("2026-08-13T20:07:00Z", True).stdout)
        self.assertEqual(finished["state"], "merged")
        self.assertEqual(self.check_launch(action_id="14:1:1")["reason"],
                         "inactive_attempt")
        late = self.register_worker(action_id="14:1:1", now="2026-08-13T20:08:00Z",
                                    ok=False)
        self.assertEqual(late.returncode, 2)
        self.assertIn("inactive_attempt", late.stderr)

    def test_a_relaunch_fences_the_earlier_owners_ship_registration(self):
        self.return_from_the_delegated_owner()
        resumed = self.resume(issue=14, worktree=str(self.root / "wt-14"),
                              now="2026-08-13T20:06:00Z", owner_unavailable=True)
        self.assertEqual(resumed["id"], "14:1:2")
        before = self.state_path.read_bytes()
        stale = self.register_worker(action_id="14:1:1", now="2026-08-13T20:07:00Z",
                                     ok=False)
        self.assertEqual((stale.returncode, stale.stdout), (2, ""))
        self.assertIn("superseded_launch", stale.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertEqual(self.check_launch(action_id="14:1:1")["reason"],
                         "superseded_launch")


```

Why the non-direct run matters: `self.run_id` is `issue-14-test`, not a reserved direct run id, so `progress` with measured usage and `remainder_self_contained=True` selects `delegate` through the non-direct order. `legacy_finish` repeats the pattern of `OwnerExitFenceTest.test_legacy_finish_refuses_until_the_worker_returns`, because the harness `finish` helper drops the worker registry.

- [ ] **Step 3: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k DelegatedShipLaunchTest -k WorkerRegistryTest -k OwnerExitFenceTest 2>&1 | tail -4` (timeout 1800 s)
Expected: `OK`. Then the Step 1 command prints `Ran 3 tests`, `OK` and `exit=0`.

If a test fails, the ledger does not admit the route as D5 assumed. Do not edit `workflow-state.py` and do not weaken the assertion: report the failing assertion and its output as BLOCKED, because that reverses D5 and needs a design decision.

Run: `git diff --stat "$(git merge-base origin/main HEAD)" -- home/common/agent-skills/scripts/workflow-state.py | wc -l`
Expected: `0`.

- [ ] **Step 4: Commit**

```bash
git add home/common/agent-skills/tests/test_workflow_state.py
git commit -m "test(workflow-state): a delegated owner's delegator registers the ship owner (#352)"
```
