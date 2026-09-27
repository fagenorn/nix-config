# Task 1: Suspension state core (schema, suspend verb, reaper demotion)

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes: existing constants `ATTEMPT_STATES` (line ~22), `RESULT_SOURCES` (~24), `ATTEMPT_FIELDS` (~55), `validate_attempt` (~444), `stop_attempt(attempt, *, reason, now, source)` (~940), the four expiry call sites in `_apply_one_issue_policy` (~1466, ~1484, ~1506, ~1573), `build_parser` (~2389).
- Produces (later tasks rely on these exact names):
  - `ATTEMPT_STATES` gains `"suspended"` (non-terminal). `RESULT_SOURCES` gains `"stalled"`.
  - `BLOCKED_ON_VALUES = frozenset({"usage_limit", "transport", "human_gate", "external", "unknown"})`.
  - `ATTEMPT_FIELDS` gains exactly three fields: `blocked_on` (str|None), `suspend_phase` (int|None), `stalled_resumes` (int ≥ 0).
  - `suspend_attempt(attempt, *, blocked_on, now) -> bool` — mutates the attempt to `state="suspended"` per the stall algorithm below; returns `False` when it escalated to a terminal stop instead.
  - `reentry_command(issue: int) -> str` returning exactly `f"/from-issue {issue} --auto"`.
  - New CLI subcommand `suspend` with flags `--repo-root --run-id --now --issue --attempt --blocked-on {usage_limit,transport,human_gate,external}` (`unknown` is reaper-reserved and NOT an accepted CLI choice). Emits compact JSON `{"kind": "suspended", "issue": <int>, "attempt": <int>, "blocked_on": <str>, "stalled_resumes": <int>, "reentry": <str>}` on suspension, or the persisted terminal attempt dict when the stall rule escalated.
  - Bumped `schema_version` (read the current value, increment by 1) with an upgrade-on-load path.

**Invariants:**
- A `suspended` attempt has `result`, `finished_at`, `result_source` all `None` and `blocked_on` ∈ `BLOCKED_ON_VALUES`; every non-suspended state has `blocked_on = None`. `suspend_phase`/`stalled_resumes` persist across states as history (per D2).
- A suspended attempt may carry a non-null `handoff_path` (an expired `handed_off` attempt demotes without losing it).
- No code path writes `state="stopped"` with `result_source="expiry"` anymore: all four expiry call sites call `suspend_attempt(..., blocked_on="unknown", ...)` instead, write NO issue `outcome`, and the control delta for an expiry demotion is `{"kind": "expired", "state": "suspended"}`. Legacy on-disk records with `stopped`/`expiry` still validate (D15).
- Stall algorithm (per D8, exact): on suspend of an attempt at phase `P` — if `suspend_phase == P` then `stalled_resumes += 1` else `stalled_resumes = 0`; then `suspend_phase = P`. If the increment would make `stalled_resumes == 3`, do NOT suspend: call `stop_attempt(attempt, reason="suspension stalled without phase progress", now=now, source="stalled")` and stash its return as the issue `outcome`.
- Loading a state file whose `schema_version` is the previous value upgrades every attempt in memory (defaults above) and validates; a `schema_version` greater than the new value raises `WorkflowError`; the upgraded shape is persisted on the next write.
- The `suspend` CLI rejects an attempt that is not `active` (message contains `only an active attempt can suspend`), leaving state bytes unchanged.

- [ ] **Step 1: Write the failing tests** (append to `WorkflowStateLifecycleTest`, using the existing `self.init_run()`, `self.spawn(issue=, worktree=, budget_minutes=)`, `self.expire(issue=, worktree=, now=)`, `self.read_state()`, `run_cli` helpers; add a thin `self.suspend(issue, attempt, blocked_on, now)` wrapper mirroring the `finish` wrapper):

```python
def test_expiry_demotes_active_attempt_to_suspended(self):
    self.init_run()
    worktree = str(Path(self.root) / "wt-14")
    self.spawn(issue=14, worktree=worktree, budget_minutes=10)
    response = self.expire(issue=14, worktree=worktree, now="2026-08-13T20:10:00Z")
    deltas = json.loads(response.stdout)["deltas"]
    self.assertEqual(deltas, [{"issue": 14, "attempt": 1, "kind": "expired", "state": "suspended"}])
    state = self.read_state()
    attempt = state["issues"]["14"]["attempts"][-1]
    self.assertEqual(attempt["state"], "suspended")
    self.assertEqual(attempt["blocked_on"], "unknown")
    self.assertIsNone(attempt["result"])
    self.assertIsNone(attempt["result_source"])
    self.assertIsNone(state["issues"]["14"]["outcome"])

def test_suspend_subcommand_records_blocked_on_and_reentry(self):
    self.init_run()
    worktree = str(Path(self.root) / "wt-15")
    self.spawn(issue=15, worktree=worktree, budget_minutes=10)
    completed = self.suspend(issue=15, attempt=1, blocked_on="usage_limit", now="2026-08-13T20:05:00Z")
    self.assertEqual(completed.returncode, 0, completed.stderr)
    envelope = json.loads(completed.stdout)
    self.assertEqual(envelope["kind"], "suspended")
    self.assertEqual(envelope["blocked_on"], "usage_limit")
    self.assertEqual(envelope["reentry"], "/from-issue 15 --auto")
    attempt = self.read_state()["issues"]["15"]["attempts"][-1]
    self.assertEqual(attempt["state"], "suspended")

def test_third_stalled_suspension_escalates_to_synthetic_stop(self):
    # Arrange an attempt that suspends at the same phase four times with a
    # resume between each (resume plumbing lands in Task 2; until then, flip
    # the persisted attempt back to active by direct state edit in the test).
    self.init_run()
    worktree = str(Path(self.root) / "wt-16")
    self.spawn(issue=16, worktree=worktree, budget_minutes=10)
    for index in range(3):
        completed = self.suspend(issue=16, attempt=1, blocked_on="usage_limit",
                                 now=f"2026-08-13T20:0{index + 1}:00Z")
        self.assertEqual(json.loads(completed.stdout)["kind"], "suspended")
        self.reactivate(issue=16)  # test helper: rewrite state, attempt back to "active"
    final = self.suspend(issue=16, attempt=1, blocked_on="usage_limit", now="2026-08-13T20:08:00Z")
    attempt = json.loads(final.stdout)
    self.assertEqual(attempt["state"], "stopped")
    self.assertEqual(attempt["result_source"], "stalled")
    self.assertIn("stalled without phase progress", attempt["result"]["notes"])

def test_prior_schema_ledger_upgrades_on_load(self):
    self.init_run()
    worktree = str(Path(self.root) / "wt-17")
    self.spawn(issue=17, worktree=worktree, budget_minutes=10)
    state = self.read_state()
    state["schema_version"] = state["schema_version"] - 1
    for attempt in state["issues"]["17"]["attempts"]:
        for field in ("blocked_on", "suspend_phase", "stalled_resumes"):
            attempt.pop(field, None)
    self.write_state(state)  # test helper: dump back to state.json
    completed = self.suspend(issue=17, attempt=1, blocked_on="external", now="2026-08-13T20:02:00Z")
    self.assertEqual(completed.returncode, 0, completed.stderr)
    upgraded = self.read_state()
    self.assertEqual(upgraded["issues"]["17"]["attempts"][-1]["stalled_resumes"], 0)
```

(`self.reactivate`/`self.write_state` are small test-file helpers to add beside `read_state`; `reactivate` rewrites the latest attempt to `state="active"`, `blocked_on=None`, appends a `{"kind": "resume", "owner": <same>, "worktree": <same>, "at": <next minute>}` launch, sets `launch_kind="resume"`, and extends `deadline_at` past the new launch time.)

- [ ] **Step 2: Run and watch them fail**

Run: `python3 -m unittest -v -k suspend home/common/agent-skills/tests/test_workflow_state.py`
Expected: FAIL/ERROR — `suspend` is an invalid CLI choice; `blocked_on` unknown field.

- [ ] **Step 3: Implement** — constants, `ATTEMPT_FIELDS`, `validate_attempt` rules (suspended ⇒ result triple all-None, `blocked_on` member check, non-suspended ⇒ `blocked_on is None`, suspended may keep `handoff_path`), `suspend_attempt` + stall algorithm exactly as pinned, `reentry_command`, the `suspend` subcommand (locks `state.lock` like `progress` does, validates identity, rejects non-active attempts), replace the four `stop_attempt(..., source="expiry")` call sites with `suspend_attempt(..., blocked_on="unknown", now=now)` (dropping their `outcome` stash), update the `expired` delta emission to `"state": "suspended"`, and the schema bump + upgrade-on-load in the state loader (single choke point where `schema_version` is checked today).

- [ ] **Step 4: Full-suite check and legacy fallout** — existing tests that pin `stopped`/`expiry` reaper behavior (e.g. `test_owner_death_expiry_stops_active_attempt_with_worktree` ~line 1811, `test_expiry_result_is_provisional_until_the_owner_reports`) must be UPDATED to the new suspended expectation, not deleted; keep one renamed variant asserting the legacy record still validates on load. Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_state.py`
Expected: PASS, ≥ 96 tests (Task 2 may temporarily see the direct-owner suspended path unhandled — only if a pre-existing test exercises direct-owner over an expired attempt; if so, update that test's expectation to the suspended observation and note it for Task 2).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
git commit -m "feat(agent-skills): add non-terminal suspension to the workflow lifecycle"
```

**Verification (falsifiable):** at the base commit, `grep -c '"suspended"' home/common/agent-skills/scripts/workflow-state.py` prints 0; after the task, `if ! grep -q 'BLOCKED_ON_VALUES' home/common/agent-skills/scripts/workflow-state.py; then exit 1; fi` passes and the four named tests pass. Cite: D2, D8, D11, D15.
