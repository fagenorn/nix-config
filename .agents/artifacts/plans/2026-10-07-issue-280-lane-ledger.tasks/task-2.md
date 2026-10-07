# Task 2: `declare-lane` verb and lane-aware suspension resume

Per D1, D2, D4, D5, D6 and D8. Spec sections "`declare-lane`" and "Lane-aware resume".

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes (from Task 1, in `workflow-state.py`): `LANES`, `LANE_REASONS`, `LANE_TRANSITION_REASONS: dict[tuple[str | None, str], frozenset[str]]`, and the attempt fields `lane`, `lane_budget_minutes` and `lane_history`. Existing code it uses: `launch_verdict(runtime, state, action_id) -> (current_action_id, reason)`, `parse_action_id`, `attempt_deadline(now: str, minutes: int) -> str`, `require_plain_int(value, label, *, minimum)`, `transact`, `print_json`, `add_run_arguments` (which adds `--repo-root`, `--run-id` and `--now`), and `_delivery()`.
- Produces:
  - CLI `workflow-state declare-lane --repo-root <root> --run-id <id> --now <utc> --action-id <action_id> --lane {full,light} --budget-minutes <int> --reason {important_finding,light_deadline,second_fix_round,triage,unpredicted_risk}`. On success it exits 0 and prints exactly `{"action_id", "lane", "budget_minutes", "deadline_at"}`. A refusal exits 2 with empty stdout, a one-line `workflow-state: declare-lane refused: …` on stderr, and the ledger bytes unchanged.
  - `command_declare_lane(args: argparse.Namespace) -> int`.
  - Test harness `LifecycleHarness.declare_lane(self, *, action_id, now, lane, budget_minutes, reason, ok=True)`.

**Invariants:**
- The deadline is re-based from `attempt["launches"][-1]["at"]`, the current launch's `at`. It is never re-based from `--now` or `started_at`.
- `last_progress_at`, `phase`, `suspend_phase`, `stalled_resumes`, `launches`, `state` and `started_at` are untouched by `declare-lane`.
- The verb does not call `fence_owner_exit`. A live registered worker does not block it.
- The refusal order is fixed: action-id syntax, then `--budget-minutes` ≥ 1, then the remainder launch, then (inside the locked transaction) launch currency, then time moving backward, then the transition, then the reason, then the passed deadline. Every refusal is a `WorkflowError` raised before any field is assigned.
- A suspension resume passes `lane_budget_minutes` when it is set, and the request's `attempt_budget_minutes` otherwise. A resume inside the live window (handoff rollover, dead-owner takeover) still passes `None`.

- [ ] **Step 1: Write the failing tests**

Add this helper to `LifecycleHarness`, after `mark_progress`:

```python
    def declare_lane(self, *, action_id, now, lane, budget_minutes, reason, ok=True):
        completed = self.run_cli(
            "declare-lane", "--repo-root", self.root, "--run-id", self.run_id,
            "--now", now, "--action-id", action_id, "--lane", lane,
            "--budget-minutes", str(budget_minutes), "--reason", reason, ok=ok)
        return json.loads(completed.stdout) if ok else completed
```

Add this class after `LaneSchemaTest`. Every spawn runs at `DEFAULT_NOW` (`2026-08-13T20:00:00Z`) with a 240-minute budget, so the spawn deadline is `2026-08-14T00:00:00Z`.

```python
class DeclareLaneTest(LifecycleHarness, unittest.TestCase):
    """#280: `declare-lane` records an attempt's lane and re-bases its deadline."""

    def setUp(self):
        super().setUp()
        self.init_run()
        self.worktree = str(self.root / "wt-16")
        self.spawn(issue=16, worktree=self.worktree, budget_minutes=240)

    def attempt(self, issue=16):
        return self.read_state()["issues"][str(issue)]["attempts"][-1]

    def declare(self, lane, *, now, budget=None, reason="triage", action_id="16:1:1",
                ok=True):
        if budget is None:
            budget = 90 if lane == "light" else 240
        return self.declare_lane(action_id=action_id, now=now, lane=lane,
                                 budget_minutes=budget, reason=reason, ok=ok)

    def assert_refused(self, clause, lane, **declare):
        before = self.state_path.read_bytes()
        refused = self.declare(lane, ok=False, **declare)
        self.assertEqual(
            (refused.returncode, refused.stdout, self.state_path.read_bytes()),
            (2, "", before))
        self.assertIn(clause, refused.stderr)

    def test_light_rebases_the_deadline_from_the_launch_and_records_history(self):
        before = self.attempt()
        self.assertEqual(before["deadline_at"], "2026-08-14T00:00:00Z")
        reply = self.declare("light", now="2026-08-13T20:05:00Z")
        self.assertEqual(reply, {"action_id": "16:1:1", "lane": "light",
                                 "budget_minutes": 90,
                                 "deadline_at": "2026-08-13T21:30:00Z"})
        after = self.attempt()
        self.assertEqual(
            (after["lane"], after["lane_budget_minutes"], after["deadline_at"],
             after["lane_history"]),
            ("light", 90, "2026-08-13T21:30:00Z",
             [{"lane": "light", "reason": "triage", "at": "2026-08-13T20:05:00Z"}]))
        self.assertEqual(self.read_state()["updated_at"], "2026-08-13T20:05:00Z")
        untouched = ("last_progress_at", "phase", "suspend_phase", "stalled_resumes",
                     "launches", "state", "started_at")
        self.assertEqual({key: after[key] for key in untouched},
                         {key: before[key] for key in untouched})

    def test_light_escalates_to_full_from_the_same_launch(self):
        self.declare("light", now="2026-08-13T20:05:00Z")
        reply = self.declare("full", now="2026-08-13T20:40:00Z",
                             reason="second_fix_round")
        self.assertEqual(reply["deadline_at"], "2026-08-14T00:00:00Z")
        self.assertEqual(
            [(entry["lane"], entry["reason"]) for entry in self.attempt()["lane_history"]],
            [("light", "triage"), ("full", "second_fix_round")])

    def test_full_is_declared_from_triage_with_its_own_budget(self):
        reply = self.declare("full", now="2026-08-13T20:05:00Z", budget=200)
        self.assertEqual((reply["lane"], reply["budget_minutes"], reply["deadline_at"]),
                         ("full", 200, "2026-08-13T23:20:00Z"))

    def test_a_live_worker_does_not_block_a_declaration(self):
        self.register_worker(action_id="16:1:1", now="2026-08-13T20:01:00Z")
        self.assertEqual(self.declare("light", now="2026-08-13T20:02:00Z")["lane"],
                         "light")

    def test_refuses_full_to_light_and_light_to_light(self):
        self.spawn(issue=17, worktree=str(self.root / "wt-17"), budget_minutes=240)
        self.declare("full", now="2026-08-13T20:05:00Z")
        self.assert_refused("declare-lane refused: lane full cannot become light",
                            "light", now="2026-08-13T20:06:00Z")
        self.assert_refused("declare-lane refused: lane full cannot become full",
                            "full", now="2026-08-13T20:06:00Z",
                            reason="important_finding")
        self.declare("light", now="2026-08-13T20:07:00Z", action_id="17:1:1")
        self.assert_refused("declare-lane refused: lane light cannot become light",
                            "light", now="2026-08-13T20:08:00Z", action_id="17:1:1")

    def test_refuses_a_reason_the_transition_does_not_allow(self):
        self.assert_refused(
            "declare-lane refused: reason important_finding does not allow "
            "lane none to become light",
            "light", now="2026-08-13T20:05:00Z", reason="important_finding")
        self.declare("light", now="2026-08-13T20:05:00Z")
        self.assert_refused(
            "declare-lane refused: reason triage does not allow lane light to become full",
            "full", now="2026-08-13T20:06:00Z", reason="triage")
        self.assert_refused("invalid choice", "light", now="2026-08-13T20:06:00Z",
                            reason="whim")

    def test_refuses_a_launch_that_is_not_current(self):
        self.assert_refused("declare-lane refused: launch 99:1:1 is unknown_issue",
                            "light", now="2026-08-13T20:01:00Z", action_id="99:1:1")
        self.suspend(issue=16, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:01:00Z")
        self.assert_refused("declare-lane refused: launch 16:1:1 is inactive_attempt",
                            "light", now="2026-08-13T20:02:00Z")
        self.resume(issue=16, worktree=self.worktree, now="2026-08-13T20:03:00Z")
        self.assert_refused("declare-lane refused: launch 16:1:1 is superseded_launch",
                            "light", now="2026-08-13T20:04:00Z")
        reply = self.declare("light", now="2026-08-13T20:04:00Z", action_id="16:1:2")
        self.assertEqual(reply["deadline_at"], "2026-08-13T21:33:00Z")

    def test_refuses_a_remainder_launch_a_zero_budget_and_time_moving_backward(self):
        self.assert_refused("declare-lane refused: a remainder launch carries no lane",
                            "light", now="2026-08-13T20:01:00Z", action_id="16:r1:1")
        self.assert_refused("invalid --budget-minutes", "light",
                            now="2026-08-13T20:01:00Z", budget=0)
        self.declare("light", now="2026-08-13T20:05:00Z")
        self.assert_refused("declare-lane refused: time must not move backward",
                            "full", now="2026-08-13T20:04:00Z",
                            reason="important_finding")

    def test_refuses_a_rebased_deadline_that_is_not_after_now(self):
        for now in ("2026-08-13T21:30:00Z", "2026-08-13T21:31:00Z"):
            with self.subTest(lane="light", now=now):
                self.assert_refused(
                    f"declare-lane refused: deadline 2026-08-13T21:30:00Z is not after {now}",
                    "light", now=now)
        self.assert_refused(
            "declare-lane refused: deadline 2026-08-13T21:00:00Z is not after "
            "2026-08-13T21:31:00Z",
            "full", now="2026-08-13T21:31:00Z", budget=60)
        self.assertIsNone(self.attempt()["lane"])
        self.assert_refused(
            "declare-lane refused: deadline 2026-08-13T21:31:00Z is not after "
            "2026-08-13T21:31:00Z",
            "light", now="2026-08-13T21:31:00Z", budget=91)
        reply = self.declare("light", now="2026-08-13T21:31:00Z", budget=92)
        self.assertEqual(reply["deadline_at"], "2026-08-13T21:32:00Z")

    def test_a_suspension_resume_uses_the_lane_budget_or_the_request_budget(self):
        for issue in (17, 18):
            self.spawn(issue=issue, worktree=str(self.root / f"wt-{issue}"),
                       budget_minutes=240)
        self.declare("light", now="2026-08-13T20:05:00Z")
        self.declare("full", now="2026-08-13T20:05:00Z", budget=200, action_id="18:1:1")
        for issue in (16, 17, 18):
            self.suspend(issue=issue, attempt=1, blocked_on="usage_limit",
                         now="2026-08-13T20:10:00Z")
        # `resume` sends the harness's default request budget of 30 minutes.
        expected = {16: ("2026-08-13T23:00:00Z", "2026-08-14T00:30:00Z", "light"),
                    17: ("2026-08-13T23:01:00Z", "2026-08-13T23:31:00Z", None),
                    18: ("2026-08-13T23:02:00Z", "2026-08-14T02:22:00Z", "full")}
        for issue, (now, deadline, lane) in expected.items():
            with self.subTest(issue=issue):
                self.resume(issue=issue, worktree=str(self.root / f"wt-{issue}"), now=now)
                attempt = self.attempt(issue)
                self.assertEqual(
                    (attempt["state"], attempt["deadline_at"], attempt["last_progress_at"],
                     attempt["lane"], len(attempt["launches"])),
                    ("active", deadline, now, lane, 2))

    def test_a_takeover_inside_the_window_keeps_the_declared_deadline(self):
        self.declare("light", now="2026-08-13T20:05:00Z")
        self.resume(issue=16, worktree=self.worktree, now="2026-08-13T20:20:00Z",
                    owner_unavailable=True)
        attempt = self.attempt()
        self.assertEqual((attempt["deadline_at"], attempt["lane"], len(attempt["launches"])),
                         ("2026-08-13T21:30:00Z", "light", 2))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest -k DeclareLaneTest home/common/agent-skills/tests/test_workflow_state.py 2>&1 | tail -5`
Expected: FAILED. Every test errors, because argparse rejects `declare-lane` as an `invalid choice`.

- [ ] **Step 3: Implement `declare-lane`**

Add `command_declare_lane` after `command_mark_progress`. The ordering and the messages are the contract, so implement this shape:

```python
def command_declare_lane(args: argparse.Namespace) -> int:
    """Record the current launch's lane and re-base its deadline (#280).

    The deadline becomes the current launch's ``at`` plus ``--budget-minutes``,
    for either lane, and is refused unless it is after ``--now`` (#280 D1).
    Only the transitions and reasons in ``LANE_TRANSITION_REASONS`` are legal
    (#280 D2); a repeated declaration is refused, not replayed (#280 D4). The
    write does not pass ``fence_owner_exit``: this verb ends no launch.
    """
    if not RUN_ID_PATTERN.fullmatch(args.run_id):
        raise WorkflowError("invalid run_id")
    issue, _, _ = parse_action_id(args.action_id)
    now_value = parse_utc(args.now, "--now")
    now = format_utc(now_value)
    budget = require_plain_int(args.budget_minutes, "--budget-minutes", minimum=1)
    if ":r" in args.action_id:
        raise WorkflowError("declare-lane refused: a remainder launch carries no lane")
    runtime = _delivery()

    def declare(state: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
        _, reason = launch_verdict(runtime, state, args.action_id)
        if reason != "current":
            raise WorkflowError(
                f"declare-lane refused: launch {args.action_id} is {reason}")
        assert state is not None
        if now_value < parse_utc(state["updated_at"], "run update time"):
            raise WorkflowError("declare-lane refused: time must not move backward")
        attempt = state["issues"][str(issue)]["attempts"][-1]
        current = attempt["lane"]
        allowed = LANE_TRANSITION_REASONS.get((current, args.lane))
        if allowed is None:
            raise WorkflowError(
                f"declare-lane refused: lane {current or 'none'} cannot become {args.lane}")
        if args.reason not in allowed:
            raise WorkflowError(
                f"declare-lane refused: reason {args.reason} does not allow "
                f"lane {current or 'none'} to become {args.lane}")
        deadline = attempt_deadline(attempt["launches"][-1]["at"], budget)
        if parse_utc(deadline, "re-based deadline") <= now_value:
            raise WorkflowError(
                f"declare-lane refused: deadline {deadline} is not after {now}")
        attempt["lane"] = args.lane
        attempt["lane_budget_minutes"] = budget
        attempt["deadline_at"] = deadline
        attempt["lane_history"].append({"lane": args.lane, "reason": args.reason, "at": now})
        state["updated_at"] = now
        return {"action_id": args.action_id, "lane": args.lane,
                "budget_minutes": budget, "deadline_at": deadline}, True

    print_json(transact(args.repo_root, args.run_id, declare))
    return 0
```

If `transact` refuses a missing ledger before it calls the mutation, keep that behavior. Do not add `allow_missing`.

Register the verb after `mark-progress` in `build_parser`:

```python
    declare_lane = subparsers.add_parser("declare-lane")
    add_run_arguments(declare_lane)
    declare_lane.add_argument("--action-id", required=True)
    declare_lane.add_argument("--lane", required=True, choices=sorted(LANES))
    declare_lane.add_argument("--budget-minutes", required=True, type=int)
    declare_lane.add_argument("--reason", required=True, choices=sorted(LANE_REASONS))
    declare_lane.set_defaults(handler=command_declare_lane)
```

- [ ] **Step 4: Make the suspension resume lane-aware**

At the single `resume_attempt` call site in `_apply_one_issue_policy` (near line 2321), replace `attempt_budget_minutes=attempt_budget_minutes if suspended else None` with this:

```python
        window = (attempt_budget_minutes if latest["lane_budget_minutes"] is None
                  else latest["lane_budget_minutes"])
        resume_attempt(latest, now=now,
                       attempt_budget_minutes=window if suspended else None)
```

In `resume_attempt`'s docstring, replace "a suspension resume passes the fresh full window D8 grants it" with "a suspension resume passes the attempt's declared lane budget, or the request's budget when the attempt has no lane (#280)". Leave the rest of the docstring unchanged. Do not change `resume_attempt`'s signature.

- [ ] **Step 5: Verify**

Run each command and report only the summary line and any failures:
- `PYTHONPATH=python timeout 900 python3 -m unittest -k DeclareLaneTest -k LaneSchemaTest home/common/agent-skills/tests/test_workflow_state.py 2>&1 | tail -3`. Expected: `OK`.
- `PYTHONPATH=python timeout 1800 python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py 2>&1 | tail -3`. Expected: `OK`.
- `cd home/common/agent-skills/scripts && grep -c 'add_parser("declare-lane")' workflow-state.py`. Expected: `1`. At the base commit the count is `0` and grep exits 1.
- `if git diff --name-only HEAD -- CLAUDE.md home/common/agent-skills/skills | grep -q .; then exit 1; fi`. Expected: exit 0, because no instruction text changes (D7).

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(workflow-state): declare-lane and lane-aware suspension resume (#280)"
```
