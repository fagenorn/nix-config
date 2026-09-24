# Task 5: Legacy finish continuity and the survival regression

Decisions: D10, D11, D19, D20. Spec §4 ("Legacy custody", "Legacy transport",
"Migration"). D11 supersedes the 151 plan's "Legacy v1 summaries are read-only".

**Files:**
- Modify: `S/workflow-state.py` (`command_finish` legacy branch; drop the now-unused
  `allowed_source_schema_versions` parameter of `read_locked_state` and `transact`)
- Test: `T/test_delivery_workflow.py`, `T/test_workflow_state.py` (re-pins)

**Interfaces:**
- Consumes: Task 4's `ContractLifecycleTest` helpers (`write_run`, `attempt`,
  `control`), `BuilderHarness`, `LATER`; Task 2's `--result-file -`.
- Produces: legacy `finish --issue --attempt --result-file` accepted on schema 1, 2
  or 3 for a contractless issue without remainders; refused with
  `WorkflowError("legacy finish is refused for a contracted issue")` otherwise.

**Invariants:**
- The legacy transport writes only `attempts`/`outcome`; `delivery` stays the
  empty sentinel, so no legacy result is promoted into delivery truth.
- A refusal leaves the ledger byte-identical (the check runs inside the
  `transact` mutation, before any change).
- Migration-on-write is unchanged: no schema-2 writer, no bridge, no repair of any
  existing ledger (D11, D20).
- `progress`, `suspend` and `check-launch` behave exactly as before.

- [ ] **Step 1: Write the failing tests**

Add to `ContractLifecycleTest` in `T/test_delivery_workflow.py`:

```python
    def merged(self, issue):
        return {"issue": issue, "state": "merged", "pr_url": f"https://example.invalid/pr/{issue}",
                "merge_sha": "d" * 40, "issue_closed": True, "discussion_items": [],
                "detail_state": "none", "report_path": None, "notes": "merged"}

    def legacy_finish(self, run_id, issue, *, ok=True):
        return self.cli("finish", "--repo-root", self.root, "--run-id", run_id, "--now", LATER,
                        "--issue", issue, "--attempt", 1, "--result-file", "-",
                        stdin=json.dumps(self.merged(issue)).encode(), ok=ok)

    def test_legacy_finish_lands_only_on_contractless_issues(self):
        self.project()
        path = self.write_run("legacy-finish", [self.attempt(171)])
        persisted = json.loads(self.legacy_finish("legacy-finish", 171).stdout)
        stored = json.loads(path.read_text())["issues"]["171"]
        self.assertEqual((persisted, stored["outcome"], stored["attempts"][0]["state"],
                          stored["delivery"]["contract"]),
                         (self.merged(171), self.merged(171), "merged", None))
        self.cli("init-run", "--repo-root", self.root, "--run-id", "v2", "--now", NOW)
        built = self.build("contract", self.contract_input())
        self.control("v2", self.control_request([171], contracts={"171": built["contract"]},
            intents={"171": [built["initial_intent"]]}, worktrees=[{"issue": 171,
                "recorded": None, "candidate": {"path": self.worktree, "state": "absent"}}]))
        state = self.root / ".superpowers/workflows/v2/state.json"; before = state.read_bytes()
        refused = self.legacy_finish("v2", 171, ok=False)
        self.assertEqual((refused.returncode, state.read_bytes()), (2, before))
        self.assertIn(b"contracted issue", refused.stderr)

    def test_v1_owners_survive_the_migration_to_interface_two(self):
        self.project()
        state = self.workflow.new_run_state(run_id="survive", now=NOW, issues={})
        state["schema_version"] = 2
        for issue in (151, 152):
            state["issues"][str(issue)] = {"issue": issue, "outcome": None, "attempts": [
                self.workflow.new_control_attempt(issue=issue, attempt_number=1,
                    worktree=str(self.root / f"wt-{issue}"), now=NOW,
                    deadline_at="2026-09-21T01:00:00Z")]}
        path = self.root / ".superpowers/workflows/survive/state.json"
        path.parent.mkdir(parents=True); path.write_text(json.dumps(state), encoding="utf-8")
        run = ("--repo-root", self.root, "--run-id", "survive")
        boot = json.loads(self.cli("init-run", *run, "--now", NOW).stdout)
        self.assertEqual([(item["issue"], item["contract_digest"]) for item in boot["requirements"]],
                         [(151, None), (152, None)])
        self.assertEqual(json.loads(path.read_text())["schema_version"], 3)
        swept = self.control("survive", self.control_request([151, 152]))
        self.assertEqual([action["kind"] for action in swept["actions"]], ["wait"])
        self.cli("progress", *run, "--now", LATER, "--issue", 151, "--attempt", 1,
                 "--phase", 3, "--next-needs-context", "false",
                 "--artifacts-sufficient", "true", "--remainder-self-contained", "true")
        launch = json.loads(self.cli("check-launch", *run, "--action-id", "152:1:1").stdout)
        self.assertTrue(launch["current"])
        self.assertEqual(json.loads(self.legacy_finish("survive", 152).stdout), self.merged(152))
        summary = next(item for item in self.control("survive", self.control_request(
            [151, 152], now=LATER))["summaries"] if item["issue"] == 152)
        self.assertEqual((summary["state"], summary["result"]["state"]), ("merged", "merged"))
```

Re-pin in the same step (they encode the retired "read-only for schema 3" rule):
- `T/test_delivery_workflow.py::test_schema_three_refuses_the_legacy_finish_transport_without_a_write`
  becomes `test_schema_three_accepts_the_legacy_finish_transport_on_a_contractless_issue`:
  same setup plus an active attempt for issue 151 (via
  `new_control_attempt`), asserting exit 0 and the persisted `outcome`.
- `T/test_workflow_state.py::concurrent_finish`: drop the stderr assertion and the
  fallback `self.finish(...)` loop; assert
  `all(process.returncode == 0 for *_, process in processes)`. Its users
  `test_control_combined_six_stage_single_ledger_replay` and
  `test_control_demo_4_concurrent_finishes_survive_reopen` change
  `sum(...) == 1` to `== 2`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k legacy_finish -k survive -k schema_three 2>&1 | tail -5`
Expected: FAIL — "legacy finish is read-only for schema 3 runs" (exit 2) on the
schema-3 contractless issue and in the regression's `finish`.

- [ ] **Step 3: Implement**

In `command_finish`'s legacy `finish(state)` mutation, after the issue lookup:
`if issue_state["delivery"]["contract"] is not None or issue_state["delivery_remainders"]: raise WorkflowError("legacy finish is refused for a contracted issue")`.
Call `transact(args.repo_root, args.run_id, finish)` without a source-version gate,
then remove the `allowed_source_schema_versions` parameter from `transact` and
`read_locked_state` (it has no other caller). Update the `command_finish`
docstring's transport sentence to: "The legacy `--issue/--attempt/--result-file`
transport records a v1 owner's result for an attempt launched before interface 2
(a contractless issue) on any schema; a contracted issue refuses it."

- [ ] **Step 4: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_workflow_state.py 2>&1 | tail -3` → `OK`.
Run: `if grep -q "read-only for schema 3" home/common/agent-skills/scripts/workflow-state.py; then exit 1; fi` → exit 0 (fails at the starting commit).
Run: `just agent-workflow-tests 2>&1 | tail -3` → `OK (skipped=1)`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py \
  home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_workflow_state.py
git commit -m "fix(workflow-state): let v1 owners finish contractless issues after migration"
```
