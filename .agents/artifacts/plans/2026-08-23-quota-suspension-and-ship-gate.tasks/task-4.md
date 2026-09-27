# Task 4: Control sweep, wait policy, resume-gate widening

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes (Tasks 1–2): `"suspended"`, `blocked_on`, `resume_attempt(...)`.
- Consumes (existing): `command_control` (~1601), `_apply_one_issue_policy` resume gate (~1424–1444: `absent_phase_zero_direct_reservation`), trailing-action assembly (~1888–1901), `next_deadline` computation (~1856–1867), summary assembly (the `summaries` entries in the control response), `CONTROL_DELTA_KINDS` (~162), `CONTROL_WAIT_FIELDS` (~178).
- Produces:
  - Control auto-resume: an issue whose latest attempt is `suspended` is dispatch-eligible exactly like `handed_off` — subject to `max_parallel` and the recorded-worktree observation ladder — emitting a `resume` action and a `resumed` delta. No request flag gates it (per D9).
  - `next_deadline` still ranges over `active`/`handed_off` only; suspended attempts carry stale deadlines and must not arm timers.
  - Trailing-action policy (per D12): the deadline-less external wait branch (~1890–1895) is DELETED. New closed rule: `next_deadline` non-null → wait with that `deadline_at`; otherwise → `{"id": "finalize", "kind": "finalize"}` — control NEVER emits a wait whose `deadline_at` is null.
  - Control `summaries` entries gain one field: `blocked_on` (str|None — the latest attempt's value, null for non-suspended). The summary field set is exact; update its validator/assembly together.
  - Resume-gate widening (per D7): replace `absent_phase_zero_direct_reservation` with `absent_phase_zero_pause` = `latest["phase"] == 0 and latest["state"] in {"handed_off", "suspended"} and recorded is not None and recorded["state"] == "absent"` — the `is_reserved_direct_run_id(run_dir.name)` conjunct is dropped, so orchestrated runs can resume a Phase-0 handoff/suspension whose worktree never existed.

**Invariants:**
- `command_control`'s hard error `resume control action requires a matching recorded worktree observation` (~1701–1704) no longer fires for a Phase-0 absent-worktree handoff on an orchestrated run id.
- A suspended issue with `blocked_on` ∈ `{human_gate, external}` is NOT auto-resumed by control (resuming cannot clear a human gate); it is reported via its summary's `blocked_on` and contributes to finalize, not to a deadline-less wait. Auto-resume applies to `{usage_limit, transport, unknown}` only (per D9 — resumes are for environmental interruptions the retry itself can survive).
- Every control response still carries exactly one trailing `wait` or `finalize` action.

- [ ] **Step 1: Write the failing tests** (the `control`/`control_raw`, `spawn`, `expire` helpers exist):

```python
def test_control_auto_resumes_suspended_attempts(self):
    self.init_run()
    worktree = str(Path(self.root) / "wt-41")
    self.spawn(issue=41, worktree=worktree, budget_minutes=10)
    self.expire(issue=41, worktree=worktree, now="2026-08-13T20:10:00Z")  # -> suspended(unknown)
    response = self.control(issues=[41], worktrees={41: self.matching(worktree)},
                            now="2026-08-13T21:00:00Z")
    body = json.loads(response.stdout)
    kinds = [(a["kind"], a.get("issue")) for a in body["actions"]]
    self.assertIn(("resume", 41), kinds)
    self.assertIn({"issue": 41, "attempt": 1, "kind": "resumed", "state": "active"}, body["deltas"])

def test_control_never_emits_a_deadline_less_wait(self):
    self.init_run()
    worktree = str(Path(self.root) / "wt-42")
    self.spawn(issue=42, worktree=worktree, budget_minutes=10)
    self.suspend(issue=42, attempt=1, blocked_on="human_gate", now="2026-08-13T20:05:00Z")
    response = self.control(issues=[42], worktrees={42: self.matching(worktree)},
                            now="2026-08-13T20:06:00Z")
    body = json.loads(response.stdout)
    trailing = body["actions"][-1]
    self.assertEqual(trailing["kind"], "finalize")
    for action in body["actions"]:
        if action["kind"] == "wait":
            self.assertIsNotNone(action["deadline_at"])
    summary = next(s for s in body["summaries"] if s["issue"] == 42)
    self.assertEqual(summary["blocked_on"], "human_gate")

def test_human_gate_suspension_is_not_auto_resumed(self):
    self.init_run()
    worktree = str(Path(self.root) / "wt-43")
    self.spawn(issue=43, worktree=worktree, budget_minutes=10)
    self.suspend(issue=43, attempt=1, blocked_on="external", now="2026-08-13T20:05:00Z")
    response = self.control(issues=[43], worktrees={43: self.matching(worktree)},
                            now="2026-08-13T20:06:00Z")
    body = json.loads(response.stdout)
    self.assertEqual([a for a in body["actions"] if a["kind"] == "resume"], [])
    attempt = self.read_state()["issues"]["43"]["attempts"][-1]
    self.assertEqual(attempt["state"], "suspended")

def test_orchestrated_phase_zero_handoff_resumes_with_absent_worktree(self):
    self.init_run()
    worktree = str(Path(self.root) / "wt-44")
    self.spawn(issue=44, worktree=worktree, budget_minutes=10)
    self.hand_off_at_phase_zero(issue=44)  # helper: progress with handoff inputs + --handoff-path, phase 0
    response = self.control(issues=[44],
                            worktrees={44: {"recorded": {"state": "absent", "path": worktree}}},
                            now="2026-08-13T20:30:00Z")
    self.assertEqual(response.returncode, 0, response.stderr)
    body = json.loads(response.stdout)
    self.assertIn("resume", [a["kind"] for a in body["actions"]])
```

(`self.matching(worktree)` returns the `{"recorded": {"state": "matching_issue_branch", ...}}` observation literal existing tests use; `hand_off_at_phase_zero` composes the existing `progress` wrapper with `--phase 0`, near-ceiling usage inputs that derive `handoff`, and a valid `--handoff-path` under the run's `handoffs/` dir — copy the arrangement from the existing handoff tests.)

- [ ] **Step 2: Run and watch them fail**

Run: `python3 -m unittest -v -k control_auto -k deadline_less -k phase_zero home/common/agent-skills/tests/test_workflow_state.py` (one invocation per `-k`)
Expected: FAIL — suspended issues idle; trailing action is a deadline-less `wait:external`; orchestrated absent-worktree resume raises the matching-observation error.

- [ ] **Step 3: Implement** per Interfaces. The blocked_on-gated auto-resume split lives where `_apply_one_issue_policy` chooses `desired` for a suspended latest: `{usage_limit, transport, unknown}` → resume path; `{human_gate, external}` → idle-with-summary (`pending_external` true so finalize fires when nothing else is live). Update any existing test that pinned the `wait:external`/`deadline_at: None` shape to the finalize expectation — do not delete coverage, repoint it.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_state.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
git commit -m "feat(agent-skills): control-plane suspension sweep, mandatory wait deadlines, phase-zero resume widening"
```

**Verification (falsifiable):** at base, `grep -c '"wait:external"' home/common/agent-skills/scripts/workflow-state.py` prints ≥1; after, `if grep -q '"wait:external"' home/common/agent-skills/scripts/workflow-state.py; then exit 1; fi` passes and the four tests above pass. Cite: D7, D9, D12.
