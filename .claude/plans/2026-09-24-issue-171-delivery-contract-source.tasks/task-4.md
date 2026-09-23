# Task 4: Contract-last acquisition and null-contract semantics

Decisions: D8, D9, D10, D12, D19, D24, D25. Spec §3 and §4 ("Control and legacy
issues", "Wire").

**Files:**
- Modify: `S/workflow-state.py` (`_apply_one_issue_policy`, `command_control`, `command_direct_owner`)
- Modify: `S/workflow_delivery.py` (effective contract, `control_transitions`, historical path; drop `contractless_control`)
- Modify: `S/workflow_delivery_wire.py` (`bootstrap`, drop `contractless_control`)
- Modify: `S/delivery_model/_wire.py` (`_control_response`, bootstrap members)
- Test: `T/test_delivery_workflow.py`, `T/test_artifact_budget.py`, `T/test_workflow_state.py` (re-pins only)

**Interfaces:**
- Consumes: `BuilderHarness` (`project`, `cli`, `build`, `contract_input`,
  `control_request`, `direct_request`), `LATER`, the builder CLI.
- Produces:
  - `DeliveryRuntime.effective_contract(issue_state: dict | None, supplied: dict | None) -> dict | None`
    — the installed contract when one exists (a non-null `supplied` must equal it,
    else `ValueError("delivery contract is immutable")`), otherwise `supplied`.
  - `_apply_one_issue_policy(..., contract: dict | None)`: the new operation
    `"contract"` (with `desired` ∈ `spawn|resume|retry`) means "a dispatch would
    follow but no contract governs"; it mutates nothing beyond an expiry reap.
  - `DeliveryRuntime.control_transitions(state, request, installing: set[int])`.
  - Bootstrap requirement members `{issue, owner, custody, recorded_worktree, contract_digest}`.
  - Task 6 builds its reconcile lane on these names.

**Invariants:**
- No contract governs (D10): with a null effective contract, reap, stall terminal,
  tracker halt, forge reconcile (as direct already does) and `refuse` run and
  persist, and nothing installs a contract (D24). A would-be spawn/resume/retry
  becomes `"contract"`: direct answers `observe` with exactly
  `[{"kind":"delivery_contract","subject_id":"<n>","reason_code":"delivery_contract_required","detail_pointer":null}]`
  and `run_id` = the selected existing run it would continue, else `null`; control
  emits no action, spends no capacity, and its summary carries that requirement.
  The policy's own observation requirements (tracker, forge, recorded/candidate
  worktree) come first (D9).
- A direct call with a null contract never creates a `direct-<n>-*` run directory.
- The `contractless_control` shortcut is gone; control never reports `queued` or
  `finalize` for an issue with ledger state that is live.
- A supplied contract is installed only by spawn, resume, retry, recover, and
  direct's existing historical remainder (D24). A contract differing from the
  installed one refuses the whole call before any write.
- D25: when the effective contract declares `remove_worktree` with literal `L`, a
  first spawn takes the candidate only if it equals `L`; retry and a direct
  `new_run` spawn use the recorded path when it is `matching_issue_branch` or
  `absent` (re-created in place, `uses_candidate` false) and raise on `mismatch`;
  resume keeps today's recorded-worktree requirement; any selected path `!= L`
  raises `WorkflowError("custody worktree does not match the delivery contract")`
  before any mutation. Without that stage, selection is exactly today's.
- Wire (D12): a control summary with `contract_digest: null` may carry any valid
  custody (or null) but still has `pending_stage_ids: []`, exactly the one
  `delivery_contract` requirement, and no action naming its issue.

- [ ] **Step 1: Write the failing tests**

Add to `T/test_delivery_workflow.py`:

```python
TRACKER = {"issue": 171, "state": "open", "open_blockers": [], "decision_blockers": []}
NO_PR = {"state": "none", "url": None, "merge_sha": None}
CONTRACT_REQUIRED = [{"kind": "delivery_contract", "subject_id": "171",
                      "reason_code": "delivery_contract_required", "detail_pointer": None}]


class ContractLifecycleTest(BuilderHarness, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load(MODEL, "delivery_model_lifecycle", package=True)
        cls.workflow = load(WORKFLOW, "workflow_state_lifecycle")

    def direct(self, *, ok=True, **changes):
        completed = self.cli("direct-owner", "--repo-root", self.root, "--request-file", "-",
            stdin=json.dumps(self.direct_request(**changes)).encode(), ok=ok)
        return json.loads(completed.stdout) if ok else completed

    def control(self, run_id, request, *, ok=True):
        completed = self.cli("control", "--repo-root", self.root, "--run-id", run_id,
            "--request-file", "-", stdin=json.dumps(request).encode(), ok=ok)
        return json.loads(completed.stdout) if ok else completed

    def write_run(self, run_id, attempts, *, schema=3):
        state = self.workflow.new_run_state(run_id=run_id, now=NOW, issues={})
        issue = {"issue": attempts[0]["issue"], "attempts": attempts,
                 "outcome": attempts[-1]["result"]}
        if schema == 3:
            issue.update(delivery=self.workflow._delivery().empty_delivery(),
                         delivery_remainders=[])
        state["schema_version"] = schema
        state["issues"][str(issue["issue"])] = issue
        path = self.root / f".superpowers/workflows/{run_id}/state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
        (path.parent / "state.lock").touch()
        return path

    def attempt(self, issue, number=1, **changes):
        value = self.workflow.new_control_attempt(issue=issue, attempt_number=number,
            worktree=self.worktree, now=NOW, deadline_at="2026-09-21T01:00:00Z")
        value.update(changes)
        return value

    def direct_runs(self, issue):
        return sorted((self.root / ".superpowers/workflows").glob(f"direct-{issue}-*"))

    def test_direct_acquisition_asks_for_the_contract_last(self):
        self.project()
        facts = {}
        for key, value, expected in (("tracker", TRACKER, [{"kind": "tracker"}]),
                ("forge", NO_PR, [{"kind": "forge_pr", "path": "issue-171-"}]),
                ("worktree", {"issue": 171, "recorded": None, "candidate": {
                    "path": self.worktree, "state": "absent"}}, [{"kind": "candidate_worktree"}])):
            response = self.direct(**facts)
            self.assertEqual((response["kind"], response["requirements"]), ("observe", expected))
            facts[key] = value
        self.assertEqual(self.direct(**facts), {"interface_version": 2, "kind": "observe",
            "issue": 171, "run_id": None, "requirements": CONTRACT_REQUIRED})
        self.assertEqual(self.direct_runs(171), [])
        other = self.build("contract", self.contract_input(
            worktree=str(self.root / ".worktrees/worktree-issue-171-other")))
        refused = self.direct(ok=False, delivery_contract=other["contract"],
                              authorization_intents=[other["initial_intent"]], **facts)
        self.assertEqual((refused.returncode, self.direct_runs(171)), (2, []))
        built = self.build("contract", self.contract_input())
        owner = self.direct(delivery_contract=built["contract"],
                            authorization_intents=[built["initial_intent"]], **facts)
        self.assertEqual((owner["kind"], owner["worktree"], owner["contract"]),
                         ("owner", self.worktree, built["contract"]))
        self.cli("suspend", "--repo-root", self.root, "--run-id", owner["run_id"], "--now",
                 LATER, "--issue", 171, "--attempt", 1, "--blocked-on", "usage_limit")
        resumed = self.direct(now=LATER, tracker=TRACKER, forge=NO_PR, worktree={
            "issue": 171, "recorded": {"path": self.worktree,
                                       "state": "matching_issue_branch"}, "candidate": None})
        self.assertEqual((resumed["kind"], resumed["launch_kind"], resumed["contract_digest"]),
                         ("owner", "resume", owner["contract_digest"]))

    def test_contractless_direct_runs_replay_and_reconcile_without_a_contract(self):
        self.project()
        merged = self.workflow.reconciled_result(172, "https://example.invalid/pr/1", "b" * 40)
        self.write_run("direct-172-000001", [self.attempt(172, state="merged", result=merged,
            result_source="superseded", finished_at=NOW)], schema=2)
        replay = self.direct(issue=172)
        self.assertEqual((replay["kind"], replay["reason"], replay["result"]),
                         ("terminal", "merged", merged))
        suspended = self.attempt(173)
        self.workflow.suspend_attempt(suspended, blocked_on="external", now=NOW)
        path = self.write_run("direct-173-000001", [suspended], schema=2)
        recorded = {"issue": 173, "recorded": {"path": self.worktree,
                    "state": "matching_issue_branch"}, "candidate": None}
        tracker = {**TRACKER, "issue": 173}
        waiting = self.direct(issue=173, tracker=tracker, forge=NO_PR, worktree=recorded)
        self.assertEqual((waiting["run_id"], waiting["requirements"][0]["kind"]),
                         ("direct-173-000001", "delivery_contract"))
        pr = {"state": "merged", "url": "https://example.invalid/pr/2", "merge_sha": "c" * 40}
        closed = self.direct(issue=173, tracker=tracker, forge=pr, worktree=recorded)
        self.assertEqual((closed["kind"], closed["reason"]), ("terminal", "merged"))
        stored = json.loads(path.read_text())["issues"]["173"]
        self.assertEqual((stored["attempts"][0]["result_source"], stored["delivery"]["contract"]),
                         ("superseded", None))

    def test_control_installs_a_built_contract_only_at_spawn_and_keeps_it(self):
        self.project()
        self.cli("init-run", "--repo-root", self.root, "--run-id", "orch", "--now", NOW)
        built = self.build("contract", self.contract_input())
        digest = self.model.canonical_digest(built["contract"])
        spawned = self.control("orch", self.control_request([171],
            contracts={"171": built["contract"]}, intents={"171": [built["initial_intent"]]},
            worktrees=[{"issue": 171, "recorded": None, "candidate": {
                "path": self.worktree, "state": "absent"}}]))
        action = spawned["actions"][0]
        self.assertEqual((action["kind"], action["contract"], action["worktree"]),
                         ("spawn", built["contract"], self.worktree))
        boot = json.loads(self.cli("init-run", "--repo-root", self.root, "--run-id", "orch",
                                   "--now", LATER).stdout)
        self.assertEqual([item["contract_digest"] for item in boot["requirements"]], [digest])
        governed = self.control("orch", self.control_request([171], now=LATER))
        self.assertEqual(governed["summaries"][0]["contract_digest"], digest)
        state = self.root / ".superpowers/workflows/orch/state.json"; before = state.read_bytes()
        other = self.build("contract", self.contract_input(now=LATER))
        refused = self.control("orch", self.control_request([171], now=LATER,
            contracts={"171": other["contract"]}, intents={"171": [other["initial_intent"]]}),
            ok=False)
        self.assertEqual((refused.returncode, state.read_bytes()), (2, before))

    def test_control_leaves_live_contractless_custody_idle(self):
        self.project()
        path = self.write_run("legacy", [self.attempt(171)])
        before = path.read_bytes()
        built = self.build("contract", self.contract_input())
        for label, contracts, intents in (("null", None, None), ("supplied",
                {"171": built["contract"]}, {"171": [built["initial_intent"]]})):
            with self.subTest(contract=label):
                raw = self.cli("control", "--repo-root", self.root, "--run-id", "legacy",
                    "--request-file", "-", stdin=json.dumps(self.control_request(
                        [171], now=LATER, contracts=contracts, intents=intents)).encode()).stdout
                response = json.loads(raw); summary = response["summaries"][0]
                self.assertEqual((summary["state"], summary["custody"]["action_id"],
                    summary["contract_digest"], summary["pending_stage_ids"],
                    summary["requirements"]), ("active", "171:1:1", None, [], CONTRACT_REQUIRED))
                self.assertEqual([(item["kind"], item.get("deadline_at"))
                                  for item in response["actions"]],
                                 [("wait", "2026-09-21T01:00:00Z")])
                self.assertEqual(path.read_bytes(), before)
                wire = subprocess.run([sys.executable, str(ARTIFACT_BUDGET), "validate-report",
                    "--boundary", "workflow-response", "--input", "-", "--policy", str(POLICY)],
                    input=raw, capture_output=True, check=False)
                self.assertEqual(wire.returncode, 0, wire.stderr)

    def test_contractless_refusal_is_lifecycle_only(self):
        self.project()
        failed = {"state": "failed", "result_source": "owner", "finished_at": NOW}
        path = self.write_run("refuse", [
            self.attempt(171, 1, result=self.workflow.terminal_result(171, "failed", "one"), **failed),
            self.attempt(171, 2, result=self.workflow.terminal_result(171, "failed", "two"), **failed)])
        response = self.control("refuse", self.control_request([171], now=LATER))
        self.assertEqual([delta["kind"] for delta in response["deltas"]], ["retry_refused"])
        stored = json.loads(path.read_text())["issues"]["171"]
        self.assertEqual((stored["attempts"][-1]["result_source"], stored["delivery"]["contract"]),
                         ("refused", None))
```

Add to `T/test_artifact_budget.py` (`ArtifactBudgetCliTest`):

```python
    def test_null_digest_summary_carries_legacy_custody_and_bootstrap_reports_digest(self):
        model = artifact_budget._delivery_model()
        response = deepcopy(workflow_responses(model)["control"])
        response["summaries"][0].update(contract_digest=None, pending_stage_ids=[],
            requirements=[{"kind": "delivery_contract", "subject_id": "151",
                           "reason_code": "delivery_contract_required",
                           "detail_pointer": None}])
        response["actions"] = [item for item in response["actions"] if item.get("issue") != 151]
        self.assertIsNotNone(response["summaries"][0]["custody"])
        accepted = self.run_validate("workflow-response", response, use_stdin=True)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        requirement = {"issue": 151, "owner": "151:1", "custody": custody(),
                       "recorded_worktree": "/worktree"}
        for digest, code in ((None, 0), ("sha256:" + "a" * 64, 0), ("absent", 2)):
            value = dict(requirement) if digest == "absent" else {**requirement, "contract_digest": digest}
            bootstrap = {"interface_version": 2, "kind": "workflow_bootstrap",
                         "run_id": "r", "requirements": [value]}
            with self.subTest(digest=digest):
                self.assertEqual(self.run_validate("workflow-response", bootstrap,
                                                   use_stdin=True).returncode, code)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_artifact_budget.py -k Contract -k null_digest 2>&1 | tail -5`
Expected: FAIL — direct answers `delivery_contract` first, control takes the
`contractless_control` shortcut (`queued`, `finalize`), the wire refuses custody
with a null digest, and bootstrap has no `contract_digest`.

- [ ] **Step 3: Implement**

1. `_wire.py`: in `_control_response` drop only the `item["custody"] is not None`
   clause of the null-digest rule; add `contract_digest` to the bootstrap
   requirement members (`None` or `_digest`).
2. Projection: `bootstrap` adds `contract_digest`; delete `contractless_control`
   here and its `DeliveryRuntime` wrapper.
3. Runtime: add `effective_contract`; `apply_transition` resolves the contract
   through it; `historical_direct_requested` accepts an installed contract as well
   as a supplied one; `control_transitions` runs only for issues with an installed
   contract or in `installing`.
4. Policy: add the `contract` parameter; insert the D25 checks at candidate and
   recorded-path selection and the `"contract"` return immediately before
   `resume_attempt(...)` and before `new_control_attempt(...)`.
5. `command_control`: under the lock, compute each issue's effective contract
   (refusing a mismatch), pass it to both policy calls, skip `"contract"` results
   in every dispatch pass, and call `control_transitions` with the issues whose
   planned operation is spawn/resume/retry/recover.
6. `command_direct_owner`: delete the early null-contract return; compute the
   effective contract for the selected run; answer `"contract"` as specified; a
   contractless `refuse` persists the lifecycle verdict and replays it as
   `direct_terminal(reason="failed")` without `complete_direct_policy`; persist an
   expiry reap that precedes a `"contract"` answer.
7. Re-pins (assertions describing the retired behavior only):
   `test_contractless_public_outputs_are_requirement_only` (direct now answers
   `[{"kind":"tracker"}]`; the control request gains a candidate worktree and
   keeps its no-dispatch assertions); `issue_contract(issue, worktree)` sets the
   `remove_worktree` literal to the candidate path its caller spawns at;
   `test_bootstrap_uses_exact_custody_and_remainder_precedence` and the
   `bootstrap(count)` fixture in `test_artifact_budget.py` gain `contract_digest`.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_artifact_budget.py home/common/agent-skills/tests/test_delivery_model.py 2>&1 | tail -3` → `OK`.
Run: `if grep -q "contractless_control" home/common/agent-skills/scripts/*.py; then exit 1; fi` → exit 0 (fails at the starting commit).
Run: `just agent-workflow-tests 2>&1 | tail -3` → `OK (skipped=1)`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/{workflow-state.py,workflow_delivery.py,workflow_delivery_wire.py} \
  home/common/agent-skills/scripts/delivery_model/_wire.py home/common/agent-skills/tests
git commit -m "feat(workflow-state): acquire contracts last and keep contractless custody lifecycle-only"
```
