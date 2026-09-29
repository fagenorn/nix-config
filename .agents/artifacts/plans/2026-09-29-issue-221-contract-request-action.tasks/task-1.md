# Task 1: Control returns `delivery_contract` instead of `finalize`

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (the terminal-action block of the `control` sweep, near line 2793, and the admission comment near line 2757)
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py` (class `ContractLifecycleTest`, line ~2596)

**Interfaces:**
- Consumes: the existing `ContractLifecycleTest` helpers `project`, `write_run`, `attempt`, `control`, `control_request`, `build`, `contract_input`, `workflow`, `model`; module constants `NOW`, `LATER`, `NO_PR`.
- Produces (Task 2 relies on these exact names):
  - `ContractLifecycleTest.FOLLOW_UP = "worktree-issue-172-chained-follow-up"`
  - `ContractLifecycleTest.contract_chain(self) -> tuple[Path, dict, str]` returning `(ledger_state_path, control_request, follow_up_worktree_path)`.
  - Module constant `CONTRACT_REQUIRED_172` (the issue-172 twin of `CONTRACT_REQUIRED`).
  - Control reply action `{"id": "delivery_contract", "kind": "delivery_contract", "issues": [...]}` as its last and only terminal action.

**Invariants:**
- `next_deadline` non-null → the last action is `wait`, whatever summaries ask (per D2).
- `next_deadline` null and at least one requested issue has `planned[issue]["operation"] == "contract"` → last action is `delivery_contract` with those issues in `request["issues"]` order (per D1).
- Otherwise the last action is `finalize`, unchanged.
- A `delivery_contract` sweep persists no new controller claim and releases a held one `finalized`, exactly as a `finalize` sweep does (per D4); planning, persistence, deltas, summaries and `next_deadline` (null) are unchanged.

- [ ] **Step 1: Write the failing tests**

Add next to `CONTRACT_REQUIRED` (after line ~2594):

```python
CONTRACT_REQUIRED_172 = [{"kind": "delivery_contract", "subject_id": "172",
                          "reason_code": "delivery_contract_required", "detail_pointer": None}]
```

Add to `ContractLifecycleTest`:

```python
    FOLLOW_UP = "worktree-issue-172-chained-follow-up"

    def contract_chain(self):
        """172 was blocked by 171; 171 is delivered and closed, 172 has no contract (#221 D11).

        171's merged attempt is seeded into the ledger, so nothing is live. The
        tracker reports 171 closed, so 172 has no open blocker left, and 172 has
        a verified-absent candidate worktree but no installed contract.
        """
        self.project()
        merged = self.workflow.reconciled_result(171, "https://example.invalid/pr/1", "b" * 40)
        path = self.write_run("chain", [self.attempt(171, state="merged", result=merged,
                                                     result_source="superseded", finished_at=NOW)])
        follow_up = str(self.root / ".worktrees" / self.FOLLOW_UP)
        request = self.control_request([171, 172], now=LATER,
            worktrees=[{"issue": 172, "recorded": None,
                        "candidate": {"path": follow_up, "state": "absent"}}],
            forge={"171": {"state": "merged", "url": "https://example.invalid/pr/1",
                           "merge_sha": "b" * 40}, "172": copy.deepcopy(NO_PR)})
        request["tracker"][0]["state"] = "closed"
        return path, request, follow_up

    def test_an_unblocked_issue_without_a_contract_is_asked_for_it_not_finalized(self):
        """T1 (#221 AC1): the reply names 172 as needing a contract and never finalizes."""
        _, request, _ = self.contract_chain()
        response = self.control("chain", request)
        self.assertEqual(response["actions"], [
            {"id": "delivery_contract", "kind": "delivery_contract", "issues": [172]}])
        self.assertIsNone(response["next_deadline"])
        summaries = {item["issue"]: item for item in response["summaries"]}
        self.assertEqual((summaries[171]["state"], summaries[171]["requirements"]),
                         ("merged", []))
        self.assertEqual((summaries[172]["state"], summaries[172]["contract_digest"],
                          summaries[172]["requirements"]),
                         ("queued", None, CONTRACT_REQUIRED_172))

    def test_sending_the_asked_contract_spawns_the_issue(self):
        """T2 (#221 AC2): the follow-up call with 172's built contract spawns 172."""
        _, request, follow_up = self.contract_chain()
        self.control("chain", request)
        built = self.build("contract", self.contract_input(issue=172, worktree=follow_up,
                                                           now=LATER))
        request["delivery_contracts"]["172"] = built["contract"]
        request["authorization_intents"]["172"] = [built["initial_intent"]]
        response = self.control("chain", request)
        self.assertEqual([(item["kind"], item.get("issue")) for item in response["actions"]],
                         [("spawn", 172), ("wait", None)])
        spawn = response["actions"][0]
        self.assertEqual((spawn["worktree"], spawn["contract"]), (follow_up, built["contract"]))

    def test_a_run_that_cannot_progress_still_finalizes(self):
        """T3 (#221 AC3): 171 is closed and 172 is blocked, so nothing asks and control finalizes."""
        _, request, _ = self.contract_chain()
        request["tracker"][1]["open_blockers"] = [173]
        response = self.control("chain", request)
        self.assertEqual(response["actions"], [{"id": "finalize", "kind": "finalize"}])
        self.assertEqual([(item["issue"], item["state"], item["requirements"])
                          for item in response["summaries"]],
                         [(171, "merged", []), (172, "blocked", [])])

    def test_an_armed_deadline_keeps_wait_while_an_issue_asks(self):
        """T4 (#221 D2): live 171 custody arms a deadline, so 172's ask rides on `wait`."""
        self.project()
        self.write_run("chain", [self.attempt(171)])
        follow_up = str(self.root / ".worktrees" / self.FOLLOW_UP)
        response = self.control("chain", self.control_request([171, 172], now=LATER,
            worktrees=[{"issue": 172, "recorded": None,
                        "candidate": {"path": follow_up, "state": "absent"}}]))
        self.assertEqual([(item["kind"], item.get("deadline_at")) for item in response["actions"]],
                         [("wait", "2026-09-21T01:00:00Z")])
        self.assertEqual(response["summaries"][1]["requirements"], CONTRACT_REQUIRED_172)

    def test_replaying_a_contract_request_changes_nothing(self):
        """T6 (#221 D4): no controller claim is kept, so a replay is byte-identical."""
        path, request, _ = self.contract_chain()
        first = self.control("chain", request)
        after = path.read_bytes()
        self.assertEqual(json.loads(after)["admission"]["claims"], [])
        self.assertEqual(self.control("chain", request), first)
        self.assertEqual(path.read_bytes(), after)

    def test_a_contract_request_releases_a_held_controller_claim(self):
        """T7 (#221 D4, Phase-5 SF-3): the real chain shape, where the sweep before
        171 closes ends in `wait` holding the controller claim, and the next
        sweep's `delivery_contract` releases it `finalized` as `finalize` would."""
        # TODO(implementer): start from T4's shape (171 live, 172 asking), sweep
        # once and assert the reply is `wait` with a held controller claim in the
        # ledger; then move 171 to its merged, closed state (tracker closed, forge
        # merged, and 171's attempt recorded merged — through the same ledger seam
        # contract_chain uses, keeping the ledger's admission block as the first
        # sweep left it) and sweep again. Assert the reply's actions are exactly
        # `[{"id": "delivery_contract", "kind": "delivery_contract", "issues": [172]}]`
        # and that the ledger's controller claim now has `release_event ==
        # "finalized"` with no unreleased controller claim left (mirror
        # `assert_controller_finalized` in test_workflow_state.py:727).
```

- [ ] **Step 2: Run the tests and watch T1 fail at base**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k unblocked_issue_without_a_contract -k asked_contract_spawns -k cannot_progress_still -k armed_deadline_keeps_wait -k replaying_a_contract_request -k releases_a_held_controller_claim 2>&1 | tail -15`
Expected: exactly two failures, T1 (`test_an_unblocked_issue_without_a_contract_is_asked_for_it_not_finalized`) and T7 (`test_a_contract_request_releases_a_held_controller_claim`), each diff showing the actions are `[{'id': 'finalize', 'kind': 'finalize'}]`; T7's claim assertion already holds at base (write it before the action assertion to confirm). T2, T3, T4 and T6 pass at base (they pin behavior that must survive the change; a scratch run at base confirmed each).

- [ ] **Step 3: Write the minimal implementation**

In the `control` sweep of `workflow-state.py`, replace the terminal-action block (currently `if next_deadline is None: actions.append({"id": "finalize", ...}) else: actions.append({... "wait" ...})`, line ~2797) with the three-way choice below, and rewrite the comment above it. The code block is dictated because the ordering of the three branches is the decision (per D1, D2):

```python
        # A wait must name the instant it ends, so with a deadline armed control
        # waits and any contract a summary asks for goes out on the next wake
        # (per D9, D12; #221 D2). With no deadline armed nothing will wake the
        # run: when some issue is stopped only by its missing delivery contract,
        # control asks for those contracts instead of ending the run (#221 D1);
        # otherwise it renders the summaries and returns `finalize`.
        contract_requests = [
            issue for issue in request["issues"]
            if issue in planned and planned[issue]["operation"] == "contract"
        ]
        if next_deadline is not None:
            actions.append({
                "id": f"wait:{next_deadline}", "kind": "wait",
                "wake_on": sorted(CONTROL_WAKE_EVENTS),
                "deadline_at": next_deadline,
            })
        elif contract_requests:
            actions.append({"id": "delivery_contract", "kind": "delivery_contract",
                            "issues": contract_requests})
        else:
            actions.append({"id": "finalize", "kind": "finalize"})
```

Compute `contract_requests` once, before the `summaries` list (Phase-5 D-5), and have `control_summary(..., contract_required=...)` use `issue in contract_requests or (issue in waiting and contract_missing(issue))` so "every listed issue's summary asks" holds by construction; the block above then only reads it.

Change the admission comment at line ~2756 from "a sweep ending in `finalize` keeps no controller claim (D19, D20)." to "a sweep with no deadline armed, ending in `finalize` or `delivery_contract`, keeps no controller claim (D19, D20; #221 D4)." Do not change the `if next_deadline is None:` release logic itself.

- [ ] **Step 4: Verify**

Run the Step 2 command. Expected: 6 tests, `OK`.
Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_host_admission.py home/common/agent-skills/tests/test_admission_replay.py 2>&1 | tail -4`
Expected: `OK` (in particular `test_contractless_retry_on_an_absent_path_asks_for_its_contract` stays green: its `asked` sweep now returns `delivery_contract` and still keeps no controller claim).
Falsifiable gate: `grep -c '"id": "delivery_contract"' home/common/agent-skills/scripts/workflow-state.py` prints `1` (it prints `0` at base, where the command exits 1).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_delivery_workflow.py
git commit -m "feat(workflow-state): ask for a missing delivery contract instead of finalizing (#221)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
