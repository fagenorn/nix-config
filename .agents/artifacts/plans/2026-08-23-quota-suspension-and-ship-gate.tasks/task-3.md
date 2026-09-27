# Task 3: Run lineage, forge reconciliation, finish supersede

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes (Tasks 1–2): `"suspended"`, `"stalled"` source, resume flow.
- Consumes (existing): `command_direct_owner` new-run allocation (~2081–2089), `DIRECT_OWNER_REQUEST_FIELDS` (~95–106), the observe ladder (`direct_observe`, requirement dicts `{"kind": ..., "path": ...}`), `terminal_result(issue, state, notes)` (~893), `RESULT_FIELDS` (~25–35), `command_finish`'s idempotent-replay/override/conflict ladder (~2340–2368), state top-level shape `{schema_version, run_id, created_at, updated_at, issues}`.
- Produces:
  - State top-level gains optional `prior_run` (str|None): `init-run` and control-run creation write `None`; direct-owner `new_run` allocation writes the predecessor run id (`f"direct-{issue}-{greatest_sequence:06d}"`). Validation accepts str|None; schema upgrade (Task 1's path) defaults it to `None` (per D5, D15).
  - `DIRECT_OWNER_REQUEST_FIELDS` gains required key `forge` with value `None` (unobserved) or `{"state": "none"|"open"|"closed"|"merged", "url": str|None, "merge_sha": str|None}`. Ladder position: after the tracker observation is satisfied and before worktree observations, an unobserved forge yields `observe` with requirement `{"kind": "forge_pr", "path": <the issue's branch name per branchPattern, e.g. "issue-<n>-">}`.
  - A `merged` forge observation reconciles: the latest attempt gets `state="merged"`, `finished_at=now`, `result_source="superseded"`, `result` built via a new `reconciled_result(issue, url, merge_sha)` returning the full `RESULT_FIELDS` shape (`state="merged"`, `pr_url=url`, `merge_sha=merge_sha`, `issue_closed=False`, `discussion_items=[]`, `detail_state="none"`, `report_path=None`, `notes="reconciled from forge observation"`); the issue `outcome` is set to the same result; the response is `direct_terminal(source="lifecycle", reason="merged", ...)` including `reentry` (per D3, D11).
  - `command_finish` supersede widening: when the existing attempt result's `result_source` ∈ `{"expiry", "stalled"}`, an owner result REPLACES it wholesale (result, `finished_at=now`, `result_source="owner"`, attempt `state` = new result's state, issue `outcome` = new result) with no content-equality requirement. `owner`/`refused`/`superseded` existing sources keep raising the exact `conflicting terminal result for issue {issue} attempt {attempt}` error, bytes untouched.

**Invariants:**
- `open` and `closed` (unmerged) forge observations do NOT reconcile: `open` continues the ladder/policy unchanged (Phase-0 prose owns the stop decision); `closed` continues unchanged; only `merged` writes ledger state (per D3 — narrow rule).
- Reconciliation happens before ownership: a request that would otherwise earn an `owner` envelope returns `terminal(reason="merged")` when forge says merged.
- The supersede path never resurrects an attempt: the replacement result's `state` must be a member of `RESULT_STATES`; the existing all-null / all-set triple validation still holds after replacement.
- `prior_run` chains are acyclic by construction (always points to a lower sequence).

- [ ] **Step 1: Write the failing tests**

```python
def test_new_run_records_prior_run_link(self):
    issue = 31
    first = self.direct_owner_bootstrap(issue=issue)
    self.finish_direct(issue=issue, run_id=first["run_id"], attempt=1, state="stopped",
                       source_notes="semantic stop", now="2026-08-13T21:00:00Z")
    second = self.direct_owner(issue=issue, new_run=True, owner_unavailable=False,
                               now="2026-08-13T22:00:00Z", forge={"state": "none", "url": None, "merge_sha": None})
    envelope = json.loads(second.stdout)
    self.assertEqual(envelope["kind"], "owner")
    new_state = self.read_direct_state(issue, envelope["run_id"])
    self.assertEqual(new_state["prior_run"], first["run_id"])

def test_merged_forge_observation_reconciles_before_ownership(self):
    issue = 32
    first = self.direct_owner_bootstrap(issue=issue)
    self.suspend_direct(issue=issue, run_id=first["run_id"], attempt=1,
                        blocked_on="human_gate", now="2026-08-13T20:30:00Z")
    reconciled = self.direct_owner(
        issue=issue, new_run=False, owner_unavailable=False, now="2026-08-13T22:00:00Z",
        forge={"state": "merged", "url": "https://github.com/fagenorn/nix-config/pull/78",
               "merge_sha": "f3fac95aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})
    envelope = json.loads(reconciled.stdout)
    self.assertEqual(envelope["kind"], "terminal")
    self.assertEqual(envelope["reason"], "merged")
    attempt = self.read_direct_state(issue, first["run_id"])["issues"][str(issue)]["attempts"][-1]
    self.assertEqual(attempt["state"], "merged")
    self.assertEqual(attempt["result_source"], "superseded")
    self.assertEqual(attempt["result"]["pr_url"], "https://github.com/fagenorn/nix-config/pull/78")

def test_unobserved_forge_yields_forge_pr_requirement(self):
    issue = 33
    response = self.direct_owner(issue=issue, new_run=False, owner_unavailable=False,
                                 now="2026-08-13T20:00:00Z", tracker=self.open_tracker_observation(),
                                 forge=None)
    envelope = json.loads(response.stdout)
    self.assertEqual(envelope["kind"], "observe")
    kinds = [item["kind"] for item in envelope["requirements"]]
    self.assertIn("forge_pr", kinds)

def test_owner_finish_supersedes_synthetic_stop_with_different_content(self):
    self.init_run()
    worktree = str(Path(self.root) / "wt-34")
    self.spawn(issue=34, worktree=worktree, budget_minutes=10)
    self.expire(issue=34, worktree=worktree, now="2026-08-13T20:10:00Z")
    # Task 1 made expiry a suspension; force a legacy synthetic stop for the supersede path:
    state = self.read_state()
    attempt = state["issues"]["34"]["attempts"][-1]
    attempt.update(state="stopped", blocked_on=None,
                   result=self.result_payload(issue=34, state="stopped", notes="reaper stub"),
                   finished_at="2026-08-13T20:10:00Z", result_source="expiry")
    state["issues"]["34"]["outcome"] = attempt["result"]
    self.write_state(state)
    merged = self.finish(issue=34, attempt=1,
                         result=self.result_payload(issue=34, state="merged", notes="real ship",
                                                    pr_url="https://github.com/fagenorn/nix-config/pull/90"),
                         now="2026-08-13T21:00:00Z")
    self.assertEqual(merged.returncode, 0, merged.stderr)
    persisted = self.read_state()["issues"]["34"]["attempts"][-1]
    self.assertEqual(persisted["state"], "merged")
    self.assertEqual(persisted["result_source"], "owner")

def test_owner_finish_never_overwrites_an_owner_record(self):
    self.init_run()
    worktree = str(Path(self.root) / "wt-35")
    self.spawn(issue=35, worktree=worktree, budget_minutes=10)
    self.finish(issue=35, attempt=1, result=self.result_payload(issue=35, state="stopped", notes="first"),
                now="2026-08-13T20:05:00Z")
    conflicting = self.finish(issue=35, attempt=1,
                              result=self.result_payload(issue=35, state="merged", notes="second"),
                              now="2026-08-13T20:06:00Z")
    self.assertNotEqual(conflicting.returncode, 0)
    self.assertIn("conflicting terminal result for issue 35 attempt 1", conflicting.stderr)
```

(`result_payload` / `open_tracker_observation` — reuse or lift the literals the existing finish/direct-owner tests already construct; the `direct_owner` wrapper gains a `forge=` kwarg defaulted to `{"state": "none", "url": None, "merge_sha": None}` so pre-existing direct-owner tests keep passing with one wrapper edit.)

- [ ] **Step 2: Run and watch them fail**

Run: `python3 -m unittest -v -k forge -k prior_run -k supersede home/common/agent-skills/tests/test_workflow_state.py` (three invocations, one per `-k`)
Expected: FAIL — `forge` is an unknown request field; `prior_run` unknown state field; finish conflicts.

- [ ] **Step 3: Implement** per Interfaces. `prior_run` threading: run-state creation takes an optional `prior_run=None` parameter; only the direct-owner `new_run` branch passes a value. Forge ladder: insert between tracker and worktree requirement checks in `_apply_one_issue_policy`'s direct path (control requests do NOT gain a forge field — this is acquisition-only, per D3). Existing direct-owner tests updated only via the wrapper default.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_state.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py
git commit -m "feat(agent-skills): forge reconciliation, run lineage, and synthetic-result supersede"
```

**Verification (falsifiable):** at base, `grep -c 'forge_pr' home/common/agent-skills/scripts/workflow-state.py` prints 0; after, `if ! grep -q 'prior_run' home/common/agent-skills/scripts/workflow-state.py; then exit 1; fi` passes and the five tests above pass. Cite: D3, D5, D11, D15.
