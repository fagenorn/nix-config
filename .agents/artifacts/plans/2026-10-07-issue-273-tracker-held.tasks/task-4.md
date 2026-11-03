# Task 4: Control projects `held` and never relaunches it

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow_delivery_wire.py`
- Modify: `home/common/agent-skills/scripts/delivery_model/_wire.py`
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Modify: `home/common/agent-skills/tests/test_delivered_control.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes:
  - Task 1: the model's `tracker_held` kind.
  - Task 2: `build-delivery --kind observation` for `tracker_held`, with the facts `comment_url`, `record_path`, `acceptance_state` and `observation_identity`.
  - Task 3: `SOURCES["tracker_held"]`, `HELD_COMMENT` and `HELD_RECORD` in `test_delivery_workflow.py`, the owner rule admitting `merged` with `issue_closed: false`, and finish's cross-check.
- Produces:
  - Projection method `held(self, issue_state: dict | None) -> bool` on the class in `workflow_delivery_wire.py` that owns `control_summary` and `delivery_complete`. It returns true only when all of these hold: `issue_state` is non-null, `delivery_complete(issue_state)` is true, its delivery's `tracker_closed` postcondition is `observed`, and the observation that postcondition names has `observation_kind == "tracker_held"` (D15).
  - Control summary state `held`. `control_summary`'s no-latest branch becomes `closed` if the tracker is closed, otherwise `held` if `self.held(issue_state)`, otherwise `fogged`, `blocked` or `queued` as today (D7, D18).
  - `held` in both closed sets: `CONTROL_SUMMARY_STATES` in `workflow-state.py`, and the summary-state set in `delivery_model/_wire.py`'s `_control_response` (D7).
  - Test harness `DeliveredControlHarness(BuilderHarness)` in `test_delivered_control.py`. It is a plain mixin and not a `TestCase`. It carries `setUpClass`, `boundary`, `validated`, `setup_run`, `request`, `control`, `observed`, `fail_after_selection`, `deliver`, `deliver_through_remainder`, `delivered_shape`, `records`, `after_delivery` and `assert_only_live_resumed`. `DeliveredControlTest(DeliveredControlHarness, unittest.TestCase)` keeps its five tests and `isolated_workflow` unchanged (D12).

**Invariants:**
- A held delivery plans no action and no delta for its issue, projects `custody: null` and `owner: null`, and has empty `pending_stage_ids` and empty `requirements`. The issue is absent from `admission.waiting` (criterion 2).
- A held issue that a human has closed reads `closed`. A delivered issue closed through `tracker_closed`, whose tracker reads `open`, does not read `held` (D15, D18).
- A dependent whose tracker `open_blockers` names the held issue reads `blocked` and is not dispatched (parent D7).
- `test_workflow_state.py` imports only the mixin and its constants, never `DeliveredControlTest`, so #220's tests do not run twice (D12).
- `DeliveredControlTest`'s five tests pass unchanged. `delivered_shape` keeps its documented minutes and launch ids.

- [ ] **Step 1: Extract the mixin (behavior-preserving)**

In `home/common/agent-skills/tests/test_delivered_control.py`:
1. Rename the helper half of `DeliveredControlTest` to `class DeliveredControlHarness(BuilderHarness):`, with the docstring `"""The #220 issue-207 driver over the real CLI, shared by #273's held case."""`. The harness covers everything from `setUpClass` through `assert_only_live_resumed`. Then declare `class DeliveredControlTest(DeliveredControlHarness, unittest.TestCase):`, keeping the original docstring, its `test_*` methods and `isolated_workflow`.
2. `request(...)` gains a keyword argument, `blockers=None`, which maps an issue to a list of issue numbers. In its tracker loop, set `item["open_blockers"] = list(blockers[item["issue"]])` when `blockers` names that issue. Add one line about `blockers` to its docstring.
3. `deliver(self, custody, when, *, held=False)`. On a hold, the `close_tracker` fact is `observed("tracker_held", comment_url=HELD_COMMENT, record_path=HELD_RECORD, acceptance_state="unmet", observation_identity=f"github:issue:{issue}:held")`, and the historical row is `"issue_closed": not held`. Its `notes` are `f"held for verification: {HELD_COMMENT}"` on a hold and `"delivered"` otherwise. Import `HELD_COMMENT` and `HELD_RECORD` from `.test_delivery_workflow`.
4. Split `delivered_shape` into two methods. `deliver_through_remainder(self, *, held=False)` holds every statement from `self.setup_run()` through `self.deliver(remainder["custody"], at(95), held=held)`, with all of their assertions. `delivered_shape` calls `self.deliver_through_remainder()` and then runs its minute-250 spawn of 209 unchanged. Move the docstring's first three sentences, about minutes 0–95, to `deliver_through_remainder`.

Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_delivered_control.py 2>&1 | tail -4`
Expected: `Ran 5 tests` and `OK`. The refactor moves no behavior.

- [ ] **Step 2: Write the failing test**

Add this import below the existing imports at the top of `home/common/agent-skills/tests/test_workflow_state.py`:

```python
from .test_delivered_control import DELIVERED, DISPATCH, LIVE, DeliveredControlHarness
```

Then append this class immediately before the module's `if __name__ == "__main__":` line, or at module end if there is none:

```python
class HeldControlTest(DeliveredControlHarness, unittest.TestCase):
    """#273 AC2: a held delivery holds no custody, reads `held`, and is never relaunched."""

    def summaries(self, response):
        return {item["issue"]: item for item in response["summaries"]}

    def test_a_held_delivery_is_never_relaunched_and_reads_held(self):
        self.deliver_through_remainder(held=True)
        before = self.records(DELIVERED)
        # Minute 275 is past r1's deadline (274); 209 depends on held 207.
        response = self.control(275, recorded={DELIVERED: "absent", LIVE: None},
                                contracts=True, blockers={LIVE: [DELIVERED]})
        self.assertEqual([a for a in response["actions"] if a.get("issue") == DELIVERED], [])
        self.assertEqual([d for d in response["deltas"] if d["issue"] == DELIVERED], [])
        self.assertEqual([a for a in response["actions"] if a["kind"] in DISPATCH], [])
        self.assertNotIn(DELIVERED, response["admission"]["waiting"])
        held = self.summaries(response)[DELIVERED]
        # Summary custody keeps #220 D4's diagnostic projection unchanged (it may
        # name a stale nonterminal record); "no current custody" is proven by the
        # empty dispatch actions above and the null owner below (PR273-1).
        self.assertEqual((held["state"], held["owner"],
                          held["pending_stage_ids"], held["requirements"]),
                         ("held", None, [], []))
        self.assertIsNotNone(held["contract_digest"])
        dependent = self.summaries(response)[LIVE]
        self.assertEqual(dependent["state"], "blocked")
        self.assertEqual(dependent["blockers"],
                         [{"kind": "issue", "issue": DELIVERED, "url": None}])
        self.assertEqual(self.records(DELIVERED), before)

    def test_a_held_issue_a_human_closed_reads_closed(self):
        self.deliver_through_remainder(held=True)
        response = self.control(275, recorded={DELIVERED: "absent"}, contracts=True,
                                closed={DELIVERED})
        self.assertEqual(self.summaries(response)[DELIVERED]["state"], "closed")

    def test_only_a_held_observation_projects_held(self):
        # D15, D18: a tracker_closed delivery whose tracker reads open is not held.
        self.deliver_through_remainder(held=False)
        response = self.control(275, recorded={DELIVERED: "absent"}, contracts=True)
        self.assertEqual(self.summaries(response)[DELIVERED]["state"], "queued")
```

- [ ] **Step 3: Run the test and watch it fail**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k HeldControlTest 2>&1 | tail -10`
Expected: `test_a_held_delivery_is_never_relaunched_and_reads_held` fails with `'queued' != 'held'`. The other two pass, and they pin today's behavior.

- [ ] **Step 4: Write the minimal implementation**

1. In `workflow_delivery_wire.py`, add the `held` method with the contract from Interfaces and the docstring `"""A delivered issue whose tracker outcome is a tracker_held observation (#273 D7, D15)."""`. Insert `"held" if self.held(issue_state) else` into `control_summary`'s `state_name` expression, between the `closed` arm and the `fogged` arm.
2. In `delivery_model/_wire.py` `_control_response`, add `"held"` to the summary-state set literal.
3. In `workflow-state.py`, add `"held",` to `CONTROL_SUMMARY_STATES`, after `"closed",`.

- [ ] **Step 5: Verify**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k HeldControlTest 2>&1 | tail -4`
Expected: `Ran 3 tests` and `OK`.

Run: `PYTHONPATH=python timeout 1800 python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivered_control.py home/common/agent-skills/tests/test_host_admission.py home/common/agent-skills/tests/test_delivery_model.py home/common/agent-skills/tests/test_artifact_budget.py 2>&1 | tail -4`
Expected: `OK`.

Run: `if grep -n "class DeliveredControlTest\|import DeliveredControlTest" home/common/agent-skills/tests/test_workflow_state.py; then exit 1; fi`
Expected: no output and exit 0 (D12).

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/scripts/workflow_delivery_wire.py home/common/agent-skills/scripts/delivery_model/_wire.py home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_delivered_control.py home/common/agent-skills/tests/test_workflow_state.py
launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- -m "feat(control): report a held delivery as held and never relaunch it (#273)" -m "<trailers>"
```
