# Task 6: Control forge reconciliation and the selection-gated remainder

Decisions: D13, D14, D19, D24, D25. Spec §5.

**Files:**
- Modify: `S/workflow-state.py` (`_apply_one_issue_policy` reconcile guard, `command_control` forge wiring and reconcile lane)
- Modify: `S/workflow_delivery.py` (`delivery_policy` historical path for control, `finish_outcome`)
- Modify: `S/workflow_delivery_wire.py` (`historical_direct_requested` → `historical_requested`)
- Test: `T/test_delivery_workflow.py`, `T/test_workflow_state.py` (re-pins only)

**Interfaces:**
- Consumes: Task 4's effective contract, `"contract"` operation and
  `control_transitions(..., installing)`; Task 5's `ContractLifecycleTest.merged`
  and `legacy_finish`; Task 3's builder kinds.
- Produces: `DeliveryProjection.historical_requested(issue_state, *, forge, contract, new_run) -> bool`
  (the old direct predicate with the forge and contract passed in, so control can
  use it with `request["forge"][str(issue)]` and the effective contract).

**Invariants:**
- A merged forge reconciles the latest attempt only when nobody holds live custody
  (not `active` with `now < deadline_at`, unless a current owner-unavailable fact
  names its launch) and the attempt is nonterminal (`active`, `handed_off`,
  `suspended`) or retryable (`failed`/`owner`, `stopped`/`expiry`). The same guard
  applies to direct and control. An owner verdict is never overwritten and a live
  owner's later `finish` is never raced (D13).
- Reconciliation writes the existing `reconcile_merged_attempt` closeout
  (`merged`, `superseded`, `issue_closed: false`, detail pointer carried forward).
  The forge triple never becomes a `pr_merged` delivery observation.
- In control, reconciliation is persisted with no action, no delta and no capacity
  use. A contracted issue whose delivery is still pending and has no remainder
  then gets remainder 1 through the historical path when capacity allows, returned
  as a `delivery_remainder` action (with a `resumed` delta, as direct's historical
  remainder has); without capacity a later sweep mints it. A contractless issue
  gets only the closeout (D24).
- A `terminal_failed` summary mints remainder 1 only when every
  `select_reviewed_output` stage fact is `observed` after the summary's reduction;
  otherwise the response is `terminal_failed` and control's retry lane owns the
  issue (D14). Reconciliation's remainder is not gated on selection.

- [ ] **Step 1: Write the failing tests**

Add to `ContractLifecycleTest` in `T/test_delivery_workflow.py`:

```python
    MERGED_PR = {"state": "merged", "url": "https://example.invalid/pr/9", "merge_sha": "e" * 40}

    def forge_request(self, **changes):
        return self.control_request([171], now=LATER, forge={"171": self.MERGED_PR}, **changes)

    def failed_summary(self, custody_value, digest, observations=()):
        historical = {"issue": 171, "state": "failed", "pr_url": None, "merge_sha": None,
            "issue_closed": False, "discussion_items": [], "detail_state": "none",
            "report_path": None, "notes": "failed"}
        return {"interface_version": 2, "issue": 171, "state": "terminal_failed",
            "custody": custody_value, "historical_owner_result": historical,
            "delivery_contract_digest": digest,
            "delivery_observations": sorted(observations, key=lambda item: item["id"]),
            "authority_observations": [], "reevaluation_evidence": [],
            "detail_state": "none", "report_path": None, "notes": "failed"}

    def spawn_contracted(self, run_id):
        self.cli("init-run", "--repo-root", self.root, "--run-id", run_id, "--now", NOW)
        built = self.build("contract", self.contract_input())
        response = self.control(run_id, self.control_request([171],
            contracts={"171": built["contract"]}, intents={"171": [built["initial_intent"]]},
            worktrees=[{"issue": 171, "recorded": None,
                        "candidate": {"path": self.worktree, "state": "absent"}}]))
        return built["contract"], response["actions"][0]["custody"]

    def latest(self, path):
        return json.loads(path.read_text())["issues"]["171"]["attempts"][-1]

    def test_control_reconciles_a_merged_forge_only_without_live_custody(self):
        self.project()
        suspended = self.attempt(171)
        self.workflow.suspend_attempt(suspended, blocked_on="external", now=NOW)
        path = self.write_run("forge-suspended", [suspended])
        response = self.control("forge-suspended", self.forge_request())
        self.assertEqual([item["kind"] for item in response["actions"]], ["finalize"])
        self.assertEqual((self.latest(path)["state"], self.latest(path)["result_source"],
                          self.latest(path)["result"]["issue_closed"]),
                         ("merged", "superseded", False))
        report = ".superpowers/issue-delivery/171/run-1/ship-review.json"
        verdict = {"issue": 171, "state": "failed", "pr_url": None, "merge_sha": None,
            "issue_closed": False, "discussion_items": [], "detail_state": "present",
            "report_path": report, "notes": f"owner verdict; details: {report}"}
        path = self.write_run("forge-detail", [self.attempt(171, state="failed",
            result=verdict, result_source="owner", finished_at=NOW)])
        self.control("forge-detail", self.forge_request())
        self.assertEqual((self.latest(path)["result_source"],
                          self.latest(path)["result"]["report_path"]), ("superseded", report))
        path = self.write_run("forge-live", [self.attempt(171)]); before = path.read_bytes()
        self.control("forge-live", self.forge_request())
        self.assertEqual(path.read_bytes(), before)
        self.legacy_finish("forge-live", 171)
        path = self.write_run("forge-verdict", [self.attempt(171, state="merged",
            result=self.merged(171), result_source="owner", finished_at=NOW)])
        before = path.read_bytes()
        self.control("forge-verdict", self.forge_request())
        self.assertEqual(path.read_bytes(), before)

    def test_contracted_reconciliation_mints_remainder_one(self):
        self.project()
        self.spawn_contracted("forge-v2")
        self.cli("suspend", "--repo-root", self.root, "--run-id", "forge-v2", "--now", LATER,
                 "--issue", 171, "--attempt", 1, "--blocked-on", "external")
        response = self.control("forge-v2", self.forge_request())
        remainder = next(item for item in response["actions"]
                         if item["kind"] == "delivery_remainder")
        self.assertEqual((remainder["custody"]["action_id"], remainder["pending_stage_ids"][0]),
                         ("171:r1:1", "select_reviewed_output"))
        path = self.root / ".superpowers/workflows/forge-v2/state.json"
        self.assertEqual(self.latest(path)["result_source"], "superseded")

    def test_failure_before_selection_keeps_the_retry_lane(self):
        self.project()
        contract, custody_value = self.spawn_contracted("orch-fail")
        digest = self.model.canonical_digest(contract)
        run = ("--repo-root", self.root, "--run-id", "orch-fail", "--now", LATER)
        failed = json.loads(self.cli("finish", *run, "--summary-file", "-", stdin=json.dumps(
            self.failed_summary(custody_value, digest)).encode()).stdout)
        self.assertEqual(failed["kind"], "terminal_failed")
        retried = self.control("orch-fail", self.control_request([171], now=LATER,
            worktrees=[{"issue": 171, "recorded": {"path": self.worktree, "state": "absent"},
                        "candidate": None}]))
        action = retried["actions"][0]
        self.assertEqual((action["kind"], action["attempt"], action["worktree"]),
                         ("retry", 2, self.worktree))
        selection = self.build("selected-output", {"contract": contract, "head": "a" * 40,
            "tree": "c" * 40, "acceptance_ref": "spec", "review_ref": "clean",
            "test_ref": "checks"})
        selected = self.build("observation", {"contract": contract,
            "observation_kind": "selected_output", "selection": selection,
            "source_kind": "repository", "source_reference": "probe", "observed_at": NOW,
            "evidence": "selected"})
        minted = json.loads(self.cli("finish", *run, "--summary-file", "-", stdin=json.dumps(
            self.failed_summary(action["custody"], digest, [selected])).encode()).stdout)
        self.assertEqual((minted["kind"], minted["custody"]["action_id"]),
                         ("delivery_remainder", "171:r1:1"))
```

Re-pins (assertions that encode "a failed finish always mints remainder 1"):
`test_direct_checkpoint_and_failure_remainder_round_trip`,
`test_remainder_two_requires_closed_recovery_proof_and_replays`,
`test_control_resumes_remainder_without_spending_implementation_attempt`,
`test_control_allocates_only_one_proven_second_remainder`, and any
`T/test_workflow_state.py` case the suite shows minting remainder 1 from a
`terminal_failed` summary. Each adds
`observation(self.model, contract, "selected_output", {"selected_output": selection(self.model, digest)})`
to that summary's `delivery_observations` (sorted by id) and drops the selection
stage from its expected `pending_stage_ids`; nothing else changes.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k reconcil -k retry_lane 2>&1 | tail -5`
Expected: FAIL — control ignores `forge` (the suspended attempt stays suspended,
the retryable one raises for want of a worktree observation) and the pre-selection
failure answers `delivery_remainder`.

- [ ] **Step 3: Implement**

1. Policy: hoist the `expired`/`active_unexpired` computation above the reconcile
   branch and guard it as the invariants state; direct keeps its live-owner check.
2. `command_control`: pass `forge=request["forge"][str(issue)]` (with
   `require_forge=False`) into both `_apply_one_issue_policy` calls; before the
   recover pass, persist every analysis `"reconcile"` through
   `apply_policy(issue, False)`; for such an issue with an installed contract,
   incomplete delivery and no remainder, and while `capacity > 0`, re-plan it with
   dispatch permitted so `delivery_policy`'s historical path creates remainder 1,
   add it to `proposal_order`, and spend one slot.
3. `delivery_policy`: take the historical path for `control` as well as `direct`,
   reading the issue's forge from the request shape and requiring
   `dispatch_permitted` for control.
4. `finish_outcome`: before `_create_first_remainder` on the failed path, return
   the `terminal` response unless every `select_reviewed_output` fact in
   `issue_state["delivery"]["stage_facts"]` is `observed`.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_workflow_state.py 2>&1 | tail -3` → `OK`.
Run: `just agent-workflow-tests 2>&1 | tail -3` → `OK (skipped=1)`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/{workflow-state.py,workflow_delivery.py,workflow_delivery_wire.py} \
  home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_workflow_state.py
git commit -m "fix(workflow-state): reconcile merged forges in control and gate remainders on selection"
```
