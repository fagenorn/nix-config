# Task 2: Optional `now` in `control` and `direct-owner` requests, stamped under the lock

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py` (extend `LedgerClockTest`)

**Interfaces:**
- Consumes, from Task 1, in `workflow-state.py`: `ledger_clock() -> datetime`, `supplied_time(value: str | None, label: str) -> datetime | None` and `backward_refusal(prefix: str, now: datetime, field: str, stored: str) -> WorkflowError`. Consumes, in `test_delivery_workflow.py`: `CLOCK_ENV`, `PINNED`, `SKEW`, and the `LedgerClockTest` helpers `pin()`, `at(base, seconds)`, `clock_text()`, `assert_clock_stamp(stamp)`, `run_args`, `worktree(issue)` and `spawn_two(now) -> {issue: spawn action}`. `LedgerClockTest` inherits `LifecycleHarness`, so `control_request`, `control_raw`, `direct_request`, `direct_owner_at_root`, `direct_state_path`, `tracker_fact`, `worktree_fact` and `read_state` are available.
- Produces: `stamp_request(request: dict[str, Any]) -> datetime` in `workflow-state.py`.

**Invariants:**
- A request without a `now` member is valid. A present `now` that is not a string, `null` included, is still refused with today's `invalid control now` / `invalid direct owner now` text. Every other member is still required, an unknown member is still refused, and neither interface version changes (D3).
- A supplied request `now` is skew-checked inside `validate_control_request` / `validate_direct_owner_request`, with the labels `control now` and `direct owner now`, before any lock is taken (D6, D11).
- After validation, an omitted `now` is held as `request["now"] = None`. That is an internal value only, never accepted from a caller. `stamp_request` replaces it with `format_utc(ledger_clock())` (D7):
  - `control` calls it as the first statement of its `transact` mutation. It then rebinds the command-scope `now` and `now_value` through `nonlocal`, so every nested closure and the response's `now` echo use the stamped value.
  - `direct-owner` calls it right after the `for sequence, run_id, run_dir in sorted(claimed):` lock loop. At that point the issue lock and every existing direct run's state lock are held, and no line above it reads `request["now"]` (D11).
- The control response's `now` equals the stamped time, which is also the run's `updated_at` when the sweep writes.
- The `control` and `direct-owner` backward refusals keep their prefixes and gain the suffix, with the field `run updated_at` (D8).

- [ ] **Step 1: Write the failing tests**

Append these methods to `LedgerClockTest`:

```python
    def omitted(self, request):
        request = copy.deepcopy(request)
        del request["now"]
        return request

    def control_without_now(self, issues, *, ok=True, **facts):
        request = self.omitted(self.control_request(now=PINNED, issues=issues, **facts))
        completed = self.control_raw(request=request, legacy=False, ok=ok)
        return json.loads(completed.stdout) if ok else completed

    def recorded_facts(self, issues):
        return {"tracker": [self.tracker_fact(issue) for issue in issues],
                "worktrees": [self.worktree_fact(issue, recorded={
                    "path": self.worktree(issue), "state": "matching_issue_branch"})
                    for issue in issues],
                "max_parallel": 100}

    def test_a_control_time_over_the_bound_is_refused_and_writes_nothing(self):
        self.pin()
        self.run_cli("init-run", *self.run_args)
        self.spawn_two(PINNED)
        before = self.state_path.read_bytes()
        ahead = self.at(PINNED, 900)
        request = self.control_request(now=ahead, issues=[14, 15],
                                       **self.recorded_facts([14, 15]))
        refused = self.control_raw(request=request, legacy=False, ok=False)
        self.assertEqual(
            (refused.returncode, refused.stdout, refused.stderr),
            (2, "", SKEW.format(label="control now", supplied=ahead, lead=900, clock=PINNED)))
        self.assertEqual(self.state_path.read_bytes(), before)
        direct = self.direct_request(issue=73, now=ahead)
        refused = self.direct_owner_at_root(self.root, direct, ok=False)
        self.assertEqual(
            (refused.returncode, refused.stdout, refused.stderr),
            (2, "", SKEW.format(label="direct owner now", supplied=ahead, lead=900,
                                clock=PINNED)))
        self.assertFalse(self.direct_state_path("direct-73-000001").exists())

    def test_a_present_null_now_is_still_refused(self):
        self.pin()
        self.run_cli("init-run", *self.run_args)
        request = self.control_request(now=None, issues=[14], **self.recorded_facts([14]))
        refused = self.control_raw(request=request, legacy=False, ok=False)
        self.assertEqual((refused.returncode, refused.stderr),
                         (2, "workflow-state: invalid control now: expected an RFC3339 UTC "
                             "timestamp\n"))

    def test_control_and_direct_owner_without_now_stamp_the_clock(self):
        self.run_cli("init-run", *self.run_args)
        response = self.control_without_now(
            [14], tracker=[self.tracker_fact(14)],
            worktrees=[self.worktree_fact(14, candidate={
                "path": self.worktree(14), "state": "absent"})],
            max_parallel=100)
        self.assertEqual([action["kind"] for action in response["actions"]][:1], ["spawn"])
        self.assert_clock_stamp(response["now"])
        self.assertEqual(self.read_state()["updated_at"], response["now"])
        candidate = os.path.abspath(self.root / "worktree-issue-73")
        common = {"issue": 73, "now": PINNED, "attempt_budget_minutes": 180}
        for extra in ({}, {"tracker": self.tracker_fact(73)},
                      {"tracker": self.tracker_fact(73), "worktree": self.worktree_fact(
                          73, candidate={"path": candidate, "state": "absent"})}):
            completed = self.direct_owner_at_root(
                self.root, self.omitted(self.direct_request(**common, **extra)))
            self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["kind"], "owner")
        self.assert_clock_stamp(json.loads(
            self.direct_state_path("direct-73-000001").read_text(encoding="utf-8"))["updated_at"])

    def test_a_pinned_clock_stamps_control_exactly(self):
        self.pin()
        self.run_cli("init-run", *self.run_args)
        response = self.control_without_now(
            [14], tracker=[self.tracker_fact(14)],
            worktrees=[self.worktree_fact(14, candidate={
                "path": self.worktree(14), "state": "absent"})],
            max_parallel=100)
        self.assertEqual((response["now"], self.read_state()["updated_at"]), (PINNED, PINNED))

    def test_control_and_direct_owner_backward_refusals_name_the_wait(self):
        self.pin()
        self.run_cli("init-run", *self.run_args)
        self.spawn_two(PINNED)
        earlier = self.at(PINNED, -37)
        before = self.state_path.read_bytes()
        request = self.control_request(now=earlier, issues=[14, 15],
                                       **self.recorded_facts([14, 15]))
        refused = self.control_raw(request=request, legacy=False, ok=False)
        self.assertEqual(
            (refused.returncode, refused.stdout, refused.stderr),
            (2, "", f"workflow-state: control time must not move backward: {earlier} is "
                    f"before the run updated_at {PINNED}; it would succeed in 37 seconds\n"))
        self.assertEqual(self.state_path.read_bytes(), before)
        candidate = os.path.abspath(self.root / "worktree-issue-73")
        common = {"issue": 73, "attempt_budget_minutes": 180}
        for extra in ({}, {"tracker": self.tracker_fact(73)},
                      {"tracker": self.tracker_fact(73), "worktree": self.worktree_fact(
                          73, candidate={"path": candidate, "state": "absent"})}):
            self.direct_owner_at_root(self.root, self.omitted(
                self.direct_request(**common, now=PINNED, **extra)))
        direct_state = self.direct_state_path("direct-73-000001")
        direct_before = direct_state.read_bytes()
        refused = self.direct_owner_at_root(self.root, self.direct_request(
            **common, now=earlier, owner_unavailable=True, tracker=self.tracker_fact(73),
            worktree=self.worktree_fact(73, recorded={
                "path": candidate, "state": "matching_issue_branch"})), ok=False)
        self.assertEqual(
            (refused.returncode, refused.stderr),
            (2, f"workflow-state: direct owner time must not move backward: {earlier} is "
                f"before the run updated_at {PINNED}; it would succeed in 37 seconds\n"))
        self.assertEqual(direct_state.read_bytes(), direct_before)
```

The assertions are the contract, as in Task 1. If a fixture fact needs a small adjustment to reach the asserted refusal, the implementer may make it, for example the recorded worktree fact of the direct-owner backward case. The refusal texts, the byte-equality checks and the stamp assertions may not change.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k LedgerClockTest`
Expected: FAIL. A request without `now` is refused with `invalid control request fields` / `invalid direct owner request fields`. The 900-second-ahead request is accepted. The backward refusals lack the suffix. The Task 1 tests still pass.

- [ ] **Step 3: Implement**

In `workflow-state.py`:

1. Add, beside the Task 1 helpers:

```python
def stamp_request(request: dict[str, Any]) -> datetime:
    """Fill a request's omitted ``now`` from the clock and return the request's time (#309 D7, D11).

    Call it under the ledger lock. A supplied ``now`` was already skew-checked
    by request validation and is kept.
    """
    if request["now"] is None:
        request["now"] = format_utc(ledger_clock())
    return parse_utc(request["now"], "request now")
```

2. In `validate_control_request` and `validate_direct_owner_request`, before `require_exact_fields`: on a `dict` input without a `"now"` key, insert `"now": None` and remember that it was omitted. Keep the existing `isinstance(request["now"], str)` refusal for a present member. Replace `request["now"] = format_utc(parse_utc(request["now"], "<label>"))` with `request["now"] = format_utc(supplied_time(request["now"], "<label>"))`, where the label is `control now` or `direct owner now`. Skip both steps when `now` was omitted.

3. In `command_control`, replace `now = request["now"]` and `now_value = parse_utc(now, "control now")` with `now: str | None = None` and `now_value: datetime | None = None`. Make the first statements of the inner `control(state)`:

```python
        nonlocal now, now_value
        now_value = stamp_request(request)
        now = request["now"]
```

Then replace `raise WorkflowError("control time must not move backward")` with `raise backward_refusal("control time must not move backward", now_value, "run updated_at", state["updated_at"])`.

4. In `command_direct_owner`, insert `stamp_request(request)` as the first statement after the `for sequence, run_id, run_dir in sorted(claimed):` loop body ends, before `nonterminal = [`. Replace `raise WorkflowError("direct owner time must not move backward")` with `raise backward_refusal("direct owner time must not move backward", parse_utc(request["now"], "direct owner now"), "run updated_at", state["updated_at"])`.

5. Check by grep that every other `request["now"]` read in `command_control` and `command_direct_owner` sits after the stamp. That covers `workflow_delivery.py` too, which reads `request["now"]` only from methods those mutations call.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_delivered_control.py home/common/agent-skills/tests/test_admission_replay.py home/common/agent-skills/tests/test_host_admission.py 2>&1 | tail -5` (timeout 1200 s)
Expected: `OK`. That includes `test_control_rejects_bad_observations_without_rewriting_the_ledger`, whose `control time must not move backward` case still matches by prefix.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_delivery_workflow.py
git commit -m "feat(workflow-state): make request now optional and stamp it under the lock (#309)"
```
