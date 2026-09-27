# Task 2: Direct-owner resume of suspended attempts

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes (Task 1): `"suspended"` state, `blocked_on`, `suspend_phase`, `stalled_resumes`, `reentry_command(issue)`.
- Consumes (existing): `command_direct_owner` (~1982), `direct_run_is_terminal` (~1917), `_apply_one_issue_policy` (~1257), `direct_terminal` (~1944), `direct_owner_response` (~1960), the "direct run has an active owner" refusal (~2134), launch-event machinery (`launches`, `launch_kind`, `LAUNCH_FIELDS`).
- Produces:
  - `direct_run_is_terminal` treats `suspended` as non-terminal AND resume-eligible (like retryable states, it must not count as "terminal" for the `new_run` gate, and unlike `active` it must not trigger the active-owner refusal).
  - `_apply_one_issue_policy`: a latest `suspended` attempt yields `desired="resume"` through the same recorded-worktree observation ladder as `handed_off`.
  - Resume mutation (exact): `state="active"`, `blocked_on=None`, append launch `{"kind": "resume", "owner": <request owner>, "worktree": <attempt worktree>, "at": now}`, `launch_kind="resume"`, `deadline_at = now + attempt_budget_minutes`, `last_progress_at = now`. No attempt increment, `prior_attempt` untouched, `new_run` NOT required (per D2, D8).
  - The `direct-owner` terminal-replay envelope (`direct_terminal`) gains a `"reentry"` field = `reentry_command(issue)`; the observe and owner envelopes are unchanged in shape except the owner envelope's existing fields now reflect the resumed attempt.

**Invariants:**
- Resuming requires neither `new_run: true` nor `owner_unavailable: true`; both `false` must succeed against a suspended run (per D2 — resumes are free).
- After resume, every launch event's `at` lies within `[started_at, deadline_at]` (the fresh deadline satisfies the existing validation; do not relax `validate_attempt`).
- A second `direct-owner` call while the resumed attempt is `active` and unexpired produces the existing `direct run has an active owner` error with zero state mutation — this is the idempotence guarantee of the re-entry command (#101; per D9).
- A suspended attempt never contributes to the `new_run` allocation gate: `new_run: true` against a run whose latest attempt is suspended is rejected (`WorkflowError`, message contains `suspended attempt is resumable`) — suspension must not be an escape hatch into run fan-out (per D5, D13).

- [ ] **Step 1: Write the failing tests** (helpers: `direct_owner`/`direct_owner_raw` wrappers exist; suspend wrapper from Task 1):

```python
def test_direct_owner_resumes_suspended_attempt_without_new_run(self):
    issue = 21
    first = self.direct_owner_bootstrap(issue=issue)  # helper below
    self.suspend_direct(issue=issue, run_id=first["run_id"], attempt=1,
                        blocked_on="usage_limit", now="2026-08-13T20:30:00Z")
    resumed = self.direct_owner(issue=issue, new_run=False, owner_unavailable=False,
                                now="2026-08-13T23:00:00Z",
                                worktree_observation=self.matching_worktree_observation(first))
    envelope = json.loads(resumed.stdout)
    self.assertEqual(envelope["kind"], "owner")
    attempt = self.read_direct_state(issue, first["run_id"])["issues"][str(issue)]["attempts"][-1]
    self.assertEqual(attempt["state"], "active")
    self.assertEqual(attempt["launch_kind"], "resume")
    self.assertEqual(attempt["launches"][-1]["at"], "2026-08-13T23:00:00Z")
    self.assertEqual(attempt["deadline_at"], "2026-08-14T02:00:00Z")  # 180-minute budget in request
    self.assertEqual(attempt["attempt"], 1)

def test_second_reentry_while_active_refuses_without_mutation(self):
    issue = 22
    first = self.direct_owner_bootstrap(issue=issue)
    self.suspend_direct(issue=issue, run_id=first["run_id"], attempt=1,
                        blocked_on="transport", now="2026-08-13T20:30:00Z")
    self.direct_owner(issue=issue, new_run=False, owner_unavailable=False,
                      now="2026-08-13T21:00:00Z",
                      worktree_observation=self.matching_worktree_observation(first))
    before = self.read_direct_state_bytes(issue, first["run_id"])
    again = self.direct_owner(issue=issue, new_run=False, owner_unavailable=False,
                              now="2026-08-13T21:05:00Z",
                              worktree_observation=self.matching_worktree_observation(first))
    self.assertNotEqual(again.returncode, 0)
    self.assertIn("direct run has an active owner", again.stderr)
    self.assertEqual(before, self.read_direct_state_bytes(issue, first["run_id"]))

def test_terminal_replay_envelope_carries_reentry(self):
    issue = 23
    first = self.direct_owner_bootstrap(issue=issue)
    self.finish_direct(issue=issue, run_id=first["run_id"], attempt=1, state="stopped",
                       source_notes="semantic stop", now="2026-08-13T21:00:00Z")
    replay = self.direct_owner(issue=issue, new_run=False, owner_unavailable=False,
                               now="2026-08-13T22:00:00Z")
    envelope = json.loads(replay.stdout)
    self.assertEqual(envelope["kind"], "terminal")
    self.assertEqual(envelope["reentry"], f"/from-issue {issue} --auto")

def test_new_run_is_rejected_while_latest_attempt_is_suspended(self):
    issue = 24
    first = self.direct_owner_bootstrap(issue=issue)
    self.suspend_direct(issue=issue, run_id=first["run_id"], attempt=1,
                        blocked_on="human_gate", now="2026-08-13T20:30:00Z")
    refused = self.direct_owner(issue=issue, new_run=True, owner_unavailable=False,
                                now="2026-08-13T21:00:00Z")
    self.assertNotEqual(refused.returncode, 0)
    self.assertIn("suspended attempt is resumable", refused.stderr)
```

Add small test-file helpers where missing: `direct_owner_bootstrap` walks the observe ladder to a first `owner` envelope and returns `{"run_id", "worktree"}` (compose from the existing `direct_owner_raw` wrapper and observation dicts the current direct-owner tests already build — reuse their literals); `suspend_direct`/`finish_direct` shell out to the `suspend`/`finish` subcommands against `.superpowers/workflows/<run_id>`; `read_direct_state[_bytes]` read that run's `state.json`; `matching_worktree_observation` returns the `{"recorded": {"state": "matching_issue_branch", ...}}` shape existing tests use.

- [ ] **Step 2: Run and watch them fail**

Run: `python3 -m unittest -v -k resume home/common/agent-skills/tests/test_workflow_state.py`
Expected: FAIL — direct-owner raises `direct run has an active owner` or misroutes the suspended attempt to observe/terminal.

- [ ] **Step 3: Implement** — in `direct_run_is_terminal`, suspended → non-terminal; in `command_direct_owner`, before the `new_run` allocation gate, reject `new_run` while latest is suspended (exact message above); in `_apply_one_issue_policy`, extend the `handed_off` resume branch to also accept `suspended` (same observation ladder; on dispatch, apply the resume mutation pinned in Interfaces — factor a `resume_attempt(attempt, *, owner, now, attempt_budget_minutes)` helper both call sites share); add `"reentry"` to `direct_terminal`.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_state.py`
Expected: PASS, all tests including Task 1's.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
git commit -m "feat(agent-skills): resume suspended attempts through direct-owner without authorization phrases"
```

**Verification (falsifiable):** at the base commit the first test fails with the active-owner error path unreached (suspended routes to observe). After: `if ! grep -q 'suspended attempt is resumable' home/common/agent-skills/scripts/workflow-state.py; then exit 1; fi`. Cite: D2, D5, D8, D9.
