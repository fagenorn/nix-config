# Task 2: The anti-zombie escalation becomes a real terminal

Discharges the second half of AC2. Rests on spec rows D4, D6, D8, D12.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes, from Task 1: `_apply_one_issue_policy` runs `demote_expired_attempt`
  at one site before any lane predicate; the early terminal check returns
  `decision("terminal", changed=expired, expired=expired)`; `command_control`'s
  fallback pass is `elif analysis[issue]["expired"] and issue not in planned:`.
- Produces: `command_direct_owner` handles a `terminal` policy operation that
  carries **no** `tracker_reason`, as a branch placed after the existing
  `elif operation == "terminal" and "tracker_reason" in policy:` branch and
  before `elif operation == "reconcile":`. No new function, no new envelope key.

**Invariants:**
- `suspend_attempt`'s `STALL_LIMIT` escalation, once written, is persisted and
  reported — it is never overwritten by a successor attempt.
- The escalation's direct-owner envelope is **byte-identical** to the envelope
  the next direct call produces from terminal replay.
- An escalated issue has exactly one attempt, `state == "stopped"`,
  `result_source == "stalled"`, and a non-null issue `outcome`.
- `"invalid one-issue policy operation"` stays the closed-set default for every
  other operation name.

---

- [ ] **Step 1: Write the failing tests**

Add both at the end of `WorkflowStateLifecycleTest`, after the tests Task 1 added.

```python
    def test_control_fourth_expiry_at_one_phase_escalates_to_a_synthetic_stop(self):
        # `stalled_resumes` counts 0, 1, 2 across suspensions at an unchanged
        # phase, so three expiry-driven resumes are free and the fourth expiry
        # terminates the attempt (per D4). Before this change the retry lane
        # stamped that terminal and then cleared it.
        self.init_run(now="2026-08-19T12:00:00Z")
        path = str(self.root / "wt-51")
        self.spawn(issue=51, worktree=path, now="2026-08-19T12:00:00Z",
                   budget_minutes=30)
        observed = [self.worktree_fact(51, recorded={
            "path": path, "state": "matching_issue_branch"})]

        def sweep(moment):
            return self.control(
                now=moment, issues=[51], max_parallel=2,
                attempt_budget_minutes=30,
                tracker=[self.tracker_fact(51)], worktrees=observed,
            )

        for moment, launch in (
            ("2026-08-19T12:30:00Z", "51:1:2"),
            ("2026-08-19T13:00:00Z", "51:1:3"),
            ("2026-08-19T13:30:00Z", "51:1:4"),
        ):
            self.assertEqual(self.dispatch_action(sweep(moment), "resume")["id"],
                             launch)

        escalated = sweep("2026-08-19T14:00:00Z")
        self.assertEqual(escalated["deltas"], [
            {"issue": 51, "attempt": 1, "kind": "expired", "state": "stopped"},
        ])
        self.assertEqual(escalated["actions"],
                         [{"id": "finalize", "kind": "finalize"}])
        issue_state = self.read_state()["issues"]["51"]
        attempt = issue_state["attempts"][-1]
        self.assertEqual(len(issue_state["attempts"]), 1)
        self.assertEqual(
            (attempt["state"], attempt["result_source"], attempt["blocked_on"]),
            ("stopped", "stalled", None),
        )
        self.assertIn("stalled without phase progress", attempt["result"]["notes"])
        self.assertEqual(issue_state["outcome"], attempt["result"])

    def test_direct_expiry_escalation_matches_the_next_call_terminal_replay(self):
        owner = self.acquire_direct(attempt_budget_minutes=30)
        tracker = self.tracker_fact(73)
        observed = self.worktree_fact(73, recorded={
            "path": owner["worktree"], "state": "absent"})
        for moment, launch in (
            ("2026-08-20T10:30:00Z", "73:1:2"),
            ("2026-08-20T11:00:00Z", "73:1:3"),
            ("2026-08-20T11:30:00Z", "73:1:4"),
        ):
            resumed = self.direct_owner(
                now=moment, attempt_budget_minutes=30, tracker=tracker,
                worktree=observed,
            )
            self.assertEqual(resumed["action_id"], launch)

        escalated = self.direct_owner_raw(
            now="2026-08-20T12:00:00Z", attempt_budget_minutes=30,
            tracker=tracker, worktree=observed,
        )
        envelope = json.loads(escalated.stdout)
        state = json.loads(self.direct_state_path(owner["run_id"]).read_text())
        outcome = state["issues"]["73"]["outcome"]
        self.assertEqual(envelope, {
            "interface_version": 1, "kind": "terminal", "issue": 73,
            "run_id": owner["run_id"], "source": "lifecycle",
            "reason": "stopped", "blockers": [], "result": outcome,
            "reentry": "/from-issue 73 --auto",
        })
        attempts = state["issues"]["73"]["attempts"]
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[-1]["result_source"], "stalled")

        # The next call reaches the same envelope through terminal replay, so
        # the two must agree byte for byte (per D4).
        replayed = self.direct_owner_raw(
            now="2026-08-20T12:05:00Z", attempt_budget_minutes=30,
            tracker=tracker, worktree=observed,
        )
        self.assertEqual(replayed.stdout, escalated.stdout)
```

- [ ] **Step 2: Run the tests and watch them fail**

```sh
python3 home/common/agent-skills/tests/test_workflow_state.py 2>&1 | tail -30
```
Expected: two failures. The control test fails on the escalation sweep's deltas;
the direct test fails with `workflow-state: invalid one-issue policy operation`
(exit 2) from `run_cli`, because `command_direct_owner`'s chain has no branch for
a `terminal` decision without a `tracker_reason`.

- [ ] **Step 3: Add the lifecycle-terminal branch to `command_direct_owner`**

Insert immediately after the existing
`elif operation == "terminal" and "tracker_reason" in policy:` block and before
`elif operation == "reconcile":`:

```python
                elif operation == "terminal":
                    # The one lifecycle terminal that carries no tracker reason:
                    # the reaper's suspension was the fourth at an unchanged
                    # phase, so `suspend_attempt` stopped the attempt instead
                    # (per D4). The envelope equals the next call's replay,
                    # which `direct_run_is_terminal` will route through
                    # `direct_terminal` from the same stored fields.
                    assert state is not None
                    if policy["changed"]:
                        state["issues"][str(issue)] = policy["issue_state"]
                        state["updated_at"] = request["now"]
                        validate_state(state, run_id=run_id)
                        atomic_write_state(run_dir, state_path, state)
                    response = direct_terminal(
                        issue=issue, run_id=run_id, source="lifecycle",
                        reason=policy["attempt"]["result"]["state"],
                        blockers=[], result=policy["issue_state"]["outcome"],
                    )
```

`policy["attempt"]` is the same object the policy mutated inside
`policy["issue_state"]`, so `["result"]["state"]` is the terminal state the
replay reads back as `latest["result"]["state"]`. The trailing
`else: raise WorkflowError("invalid one-issue policy operation")` stays exactly
as it is — it is the closed-set default (the-bar, *Fail loud*).

`command_control` needs no change: the escalation's `desired` is `"terminal"`,
so the issue never enters `proposal_order` and never reaches the
`{spawn, resume, retry}` delta map; Task 1's guarded fallback pass persists it
and the `expired` delta reports `state: "stopped"` from the written ledger.

- [ ] **Step 4: Verify**

```sh
set -o pipefail
python3 home/common/agent-skills/tests/test_workflow_state.py 2>&1 | tail -5
```
Expected: `OK`, zero failures and zero errors — including
`test_third_stalled_suspension_escalates_to_synthetic_stop`, which drives the
same bound through the explicit `suspend` verb and must stay green untouched.

Then pin the branch:

```sh
S=home/common/agent-skills/scripts/workflow-state.py
if ! grep -q '^                elif operation == "terminal":$' "$S"; then
  echo "the lifecycle-terminal branch is missing"; exit 1
fi
if ! grep -q 'raise WorkflowError("invalid one-issue policy operation")' "$S"; then
  echo "the closed-set default was removed"; exit 1
fi
```
Expected: no output, exit 0. The first check fails at the commit this task starts
from; the second passes there and must keep passing.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py \
        home/common/agent-skills/tests/test_workflow_state.py
git commit -m "fix(issue-133): let the stall escalation terminate for real"
```
Include the `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer.
Never disable commit signing.
