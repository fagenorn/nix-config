# Task 4: Control `wait` carries a validated `wait_seconds`

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Modify: `home/common/agent-skills/scripts/delivery_model/_wire.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py` (new `ControlWaitSecondsTest`, one updated assertion)
- Test: `home/common/agent-skills/tests/test_delivery_model.py` (new `ControlWaitResponseTest`, one updated fixture dict)

**Interfaces:**
- Consumes: nothing from other tasks. If Task 2 has landed, `_wire.py` already imports `datetime`; reuse that import.
- Produces: every control `wait` action has exactly the members `id`, `kind`, `wake_on`, `deadline_at` and `wait_seconds`. Task 5's adapter arms `sleep <wait_seconds>` from it.

**Invariants (D9):**
- `wait_seconds = max(0, ceil(deadline_at − now))`, an `int`, where `now` is the control response's own top-level `now` and `deadline_at` is the wait's (equal to `next_deadline`).
- The action id stays `wait:<deadline_at>`, `wake_on` is unchanged, and the control `interface_version` stays 3.
- The workflow-response boundary recomputes `wait_seconds` from those two members and rejects any other value, a missing member, an extra member, a boolean and a negative number.
- Control validates its reply at the boundary before it commits (it already does, #220 D5), so a wrong `wait_seconds` can never be printed or committed.
- `CONTROL_WAIT_FIELDS` in `workflow-state.py` names the five members.

- [ ] **Step 1: Write the failing tests**

In `test_workflow_state.py`, in `test_control_starts_ready_issues_persists_before_emission_and_bounds_output`, add `"wait_seconds": 10800,` to the expected wait action (its `now` is `2026-08-19T12:00:00Z` and its deadline `2026-08-19T15:00:00Z`). Then append:

```python
class ControlWaitSecondsTest(LifecycleHarness, unittest.TestCase):
    """#310 D9: control computes the wait observer's sleep."""

    def wait_action(self, response):
        waits = [a for a in response["actions"] if a["kind"] == "wait"]
        self.assertEqual(len(waits), 1)
        return waits[0]

    def test_the_wait_names_the_seconds_until_its_deadline(self):
        self.init_run()
        worktree = str(self.root / "wt-14")
        response = self.control_validated(
            now=DEFAULT_NOW, issues=[14], max_parallel=100, attempt_budget_minutes=30,
            tracker=[self.tracker_fact(14)],
            worktrees=[self.worktree_fact(14, candidate={"path": worktree,
                                                          "state": "absent"})])
        self.assertEqual(self.wait_action(response), {
            "id": "wait:2026-08-13T20:30:00Z", "kind": "wait",
            "wake_on": ["deadline", "owner_notification", "tracker_change"],
            "deadline_at": "2026-08-13T20:30:00Z", "wait_seconds": 1800})
        later = self.control_validated(
            now="2026-08-13T20:10:07Z", issues=[14], max_parallel=100,
            attempt_budget_minutes=30, tracker=[self.tracker_fact(14)],
            worktrees=[self.worktree_fact(14, recorded={
                "path": os.path.abspath(worktree), "state": "matching_issue_branch"})])
        self.assertEqual(self.wait_action(later)["wait_seconds"], 1193)

    def test_the_boundary_refuses_any_other_wait_seconds(self):
        self.init_run()
        response = self.control_validated(
            now=DEFAULT_NOW, issues=[14], max_parallel=100, attempt_budget_minutes=30,
            tracker=[self.tracker_fact(14)],
            worktrees=[self.worktree_fact(14, candidate={"path": str(self.root / "wt-14"),
                                                          "state": "absent"})])
        for value in (1799, 1801, -1, True, None):
            with self.subTest(wait_seconds=value):
                mutated = json.loads(json.dumps(response))
                self.wait_action(mutated)["wait_seconds"] = value
                checked = subprocess.run(
                    [sys.executable, str(ARTIFACT_BUDGET), "validate-report", "--boundary",
                     "workflow-response", "--input", "-", "--policy", str(BUDGET_POLICY)],
                    input=json.dumps(mutated), capture_output=True, text=True, check=False,
                    env=self.cli_env)
                self.assertEqual(checked.returncode, 2)
```

`control_validated` (in `LifecycleHarness`) sends an interface-3 request, asserts exit 0 and returns the decoded reply that the boundary passed unchanged.

In `test_delivery_model.py`, in the delivery-contract test that builds `wait = {"id": "wait:2026-09-21T01:00:00Z", "kind": "wait", …}`, add `"wait_seconds": 3600` to that dict, so its `with_wait` case is still rejected for the reason it names and not for a missing member. Then append:

```python
class ControlWaitResponseTest(unittest.TestCase):
    """#310 D9: the boundary recomputes a control wait's `wait_seconds`."""

    @classmethod
    def setUpClass(cls):
        cls.model = load_model(SOURCE, "delivery_model_control_wait_test")

    def validate(self, value):
        return self.model.validate_delivery_object(
            value, expected_kind="workflow-response", notes_max_characters=4096)

    def with_wait(self, deadline, seconds):
        value = copy.deepcopy(workflow_responses(self.model)["control"])
        self.assertEqual(value["now"], "2026-09-21T00:00:00Z")
        value["next_deadline"] = deadline
        value["actions"].append({"id": f"wait:{deadline}", "kind": "wait",
                                 "wake_on": ["deadline", "owner_notification", "tracker_change"],
                                 "deadline_at": deadline, "wait_seconds": seconds})
        return value

    def test_the_exact_value_is_accepted(self):
        for deadline, seconds in (("2026-09-21T01:00:00Z", 3600),
                                  ("2026-09-21T00:00:01Z", 1),
                                  ("2026-09-21T00:00:00Z", 0),
                                  ("2026-09-20T23:59:00Z", 0)):
            with self.subTest(deadline=deadline):
                value = self.with_wait(deadline, seconds)
                self.assertEqual(self.validate(copy.deepcopy(value)), value)

    def test_any_other_value_or_shape_is_rejected(self):
        cases = {"one_short": self.with_wait("2026-09-21T01:00:00Z", 3599),
                 "one_over": self.with_wait("2026-09-21T01:00:00Z", 3601),
                 "negative_past": self.with_wait("2026-09-20T23:59:00Z", -60),
                 "boolean": self.with_wait("2026-09-21T00:00:01Z", True),
                 "float": self.with_wait("2026-09-21T01:00:00Z", 3600.0)}
        missing = self.with_wait("2026-09-21T01:00:00Z", 3600)
        del missing["actions"][-1]["wait_seconds"]
        cases["missing"] = missing
        for name, value in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(self.model.DeliveryModelError):
                    self.validate(value)
```

`workflow_responses` is already imported from `._delivery_model_fixtures` in this module; add it to that import list if it is not.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k ControlWaitSeconds -k test_control_starts_ready_issues`
Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py -k ControlWaitResponse`
Expected: FAIL. Control prints no `wait_seconds`, and the boundary rejects a wait that carries one as an extra member.

- [ ] **Step 3: Write the minimal implementation**

In `workflow-state.py`, where `control` appends the wait action (the `if next_deadline is not None:` branch), add `"wait_seconds": max(0, math.ceil((parse_utc(next_deadline, "next deadline") - parse_utc(now, "control now")).total_seconds()))`, and add `"wait_seconds"` to `CONTROL_WAIT_FIELDS`. `now` there is the request's stamped `now` string that the reply prints.

In `_wire.py`, in `_control_response`'s `wait` branch: the member set becomes `id kind wake_on deadline_at wait_seconds`; check `_integer(item["wait_seconds"], "wait seconds", minimum=0)`; then reject unless it equals `max(0, math.ceil((deadline − now).total_seconds()))`, with both times parsed by `datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")` after `_utc` has accepted them (`value["now"]` is already checked at the top of the function). Add `import math`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_host_admission.py home/common/agent-skills/tests/test_admission_replay.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_delivered_control.py`
Expected: PASS. Every suite that drives control still validates its replies, so a wrong `wait_seconds` anywhere fails here.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py \
  home/common/agent-skills/scripts/delivery_model/_wire.py \
  home/common/agent-skills/tests/test_workflow_state.py \
  home/common/agent-skills/tests/test_delivery_model.py
git commit -m "feat(workflow-state): control wait carries the computed wait_seconds (#310)"
```
