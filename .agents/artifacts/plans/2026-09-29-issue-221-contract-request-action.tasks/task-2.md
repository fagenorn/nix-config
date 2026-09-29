# Task 2: Workflow-response validator accepts the coupled `delivery_contract`

**Files:**
- Modify: `home/common/agent-skills/scripts/delivery_model/_wire.py` (`_control_response`, lines ~191-218)
- Test: `home/common/agent-skills/tests/test_delivery_model.py` (class `DeliveryModelTest`, next to `test_control_summaries_admit_one_closed_unresumable_worktree_fact`, line ~1079)
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py` (class `ContractLifecycleTest`)

**Interfaces:**
- Consumes: Task 1's `ContractLifecycleTest.contract_chain()` → `(path, request, follow_up)` and the reply action `{"id": "delivery_contract", "kind": "delivery_contract", "issues": [...]}`; module constants `WORKFLOW`, `ARTIFACT_BUDGET`, `POLICY` in `test_delivery_workflow.py`; `workflow_responses(model)["control"]` from `_delivery_model_fixtures.py`; `self.validate` / `self.assert_invalid` in `DeliveryModelTest`.
- Produces: `validate_delivery_object(value, expected_kind="workflow-response", ...)` accepts a control reply carrying `delivery_contract`, and `artifact-budget validate-report --boundary workflow-response` passes it through.

**Invariants (per D6):** a control reply carrying `delivery_contract` is accepted only when all hold:
- the action's members are exactly `id`, `kind`, `issues`; `id == "delivery_contract"`;
- `issues` is a non-empty list of integers ≥ 1 (booleans rejected), unique, in summary order;
- every listed issue has a summary with `contract_digest` null whose `requirements` include `{"kind": "delivery_contract", "subject_id": str(issue), "reason_code": "delivery_contract_required", "detail_pointer": None}`;
- no listed issue is in `admission.waiting` (per D3);
- it is the last action and the only `delivery_contract`; `next_deadline` is null; no action is `wait` or `finalize`.
- Replies without `delivery_contract` validate exactly as before.

- [ ] **Step 1: Write the failing tests**

In `test_delivery_model.py`, `DeliveryModelTest`:

```python
    def test_control_delivery_contract_is_coupled_to_its_summaries(self):
        """#221 D6: `delivery_contract` lists only asking issues, last and alone."""
        fixtures = workflow_responses(self.model)

        def asking(issue):
            return {"kind": "delivery_contract", "subject_id": str(issue),
                    "reason_code": "delivery_contract_required", "detail_pointer": None}

        def reply():
            value = copy.deepcopy(fixtures["control"])
            template = value["summaries"][0]
            value["summaries"] = [{**copy.deepcopy(template), "issue": issue, "state": "queued",
                "custody": None, "owner": None, "worktree": None, "deadline_at": None,
                "contract_digest": None, "pending_stage_ids": [],
                "requirements": [asking(issue)]} for issue in (152, 151)]
            value.update(deltas=[], next_deadline=None, actions=[
                {"id": "delivery_contract", "kind": "delivery_contract", "issues": [152, 151]}])
            value["admission"].update(available=7, reserved={
                "controller": 0, "owner": 0, "worker": 0, "reviewer": 0})
            return value

        def mutated(change):
            value = reply(); change(value); return value

        def action(value):
            return value["actions"][-1]

        def not_last(value):
            # Only the last-position rule may reject this (Phase-5 SF-2): append a
            # non-terminal action no other rule refuses. TODO(implementer): build it
            # from the fixture's contracted summary 151 and its `control_owner`
            # action (fixtures["control"]["actions"][0], with its delta and
            # admission reservation), moving the asking issues to ids that do not
            # collide, and keep `next_deadline` null; adjust until Step 4's
            # guard-deletion check shows this subtest is the only one it turns red.
            ...

        self.assertEqual(self.validate(reply(), "workflow-response"), reply())
        only_152 = mutated(lambda value: action(value).update(issues=[152]))
        self.assertEqual(self.validate(only_152, "workflow-response"), only_152)
        digest = fixtures["control"]["summaries"][0]["contract_digest"]
        finalize = {"id": "finalize", "kind": "finalize"}
        wait = {"id": "wait:2026-09-21T01:00:00Z", "kind": "wait", "wake_on": ["deadline"],
                "deadline_at": "2026-09-21T01:00:00Z"}
        for name, change in {
                "extra_member": lambda value: action(value).update(issue=151),
                "missing_issues": lambda value: action(value).pop("issues"),
                "other_id": lambda value: action(value).update(id="delivery_contract:151"),
                "empty": lambda value: action(value).update(issues=[]),
                "not_a_list": lambda value: action(value).update(issues=151),
                "boolean_issue": lambda value: action(value).update(issues=[True]),
                "duplicate": lambda value: action(value).update(issues=[152, 152]),
                "out_of_order": lambda value: action(value).update(issues=[151, 152]),
                "unknown_issue": lambda value: action(value).update(issues=[152, 153]),
                "not_asking": lambda value: value["summaries"][1].update(requirements=[]),
                "contracted": lambda value: value["summaries"][0].update(
                    contract_digest=digest, requirements=[]),
                "waiting": lambda value: value["admission"].update(waiting=[152]),
                "not_last": not_last,
                "with_finalize": lambda value: value["actions"].insert(0, copy.deepcopy(finalize)),
                "with_wait": lambda value: value["actions"].insert(0, copy.deepcopy(wait)),
                "deadline_armed": lambda value: value.update(next_deadline="2026-09-21T01:00:00Z"),
                "twice": lambda value: value["actions"].insert(0, copy.deepcopy(action(value))),
        }.items():
            with self.subTest(rejected=name):
                self.assert_invalid(mutated(change), "workflow-response")
```

In `test_delivery_workflow.py`, `ContractLifecycleTest`:

```python
    def test_a_contract_request_passes_the_workflow_response_boundary(self):
        """#221 D6: the T1 reply is what the adapter's pipe accepts, byte for byte."""
        _, request, _ = self.contract_chain()
        raw = self.cli("control", "--repo-root", self.root, "--run-id", "chain",
                       "--request-file", "-", stdin=json.dumps(request).encode()).stdout
        self.assertEqual(json.loads(raw)["actions"][-1]["kind"], "delivery_contract")
        wire = subprocess.run([sys.executable, str(ARTIFACT_BUDGET), "validate-report",
            "--boundary", "workflow-response", "--input", "-", "--policy", str(POLICY)],
            input=raw, capture_output=True, check=False)
        self.assertEqual((wire.returncode, wire.stderr), (0, b""))
        self.assertEqual(wire.stdout, raw)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py -k delivery_contract_is_coupled 2>&1 | tail -6; PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k contract_request_passes_the_workflow 2>&1 | tail -6`
Expected: both FAIL — the fixture test raises `DeliveryModelError` on the accepted `reply()` (unknown action kind), and the boundary test sees a non-zero `validate-report` exit.

- [ ] **Step 3: Write the minimal implementation**

In `_control_response` in `_wire.py`:
1. In the summary loop, inside the existing `if item["contract_digest"] is None:` block, after the `remaining` check, record the asking issues: `if expected in remaining: asking.add(issue)` (declare `asking = set()` beside `missing_contracts`).
2. In the action loop add a branch before the final `else: _reject()`:
   `elif item["kind"] == "delivery_contract":` → `_object(item, _members("id kind issues"))`; reject unless `item["id"] == "delivery_contract"`, `item["issues"]` is a non-empty `list`, each member passes `_integer(..., "contract issue", minimum=1)`, it equals `[issue for issue in order if issue in item["issues"]]` (this order equality also refuses duplicates, so no separate duplicate clause is written — Phase-5 SF-2), and `set(item["issues"]) <= asking`.
3. After `waiting = _admission_report(...)`, add the reply-level couplings: let `requests` be the actions whose `kind` is `delivery_contract`; when non-empty, reject unless `len(requests) == 1`, `value["actions"][-1] is requests[0]`, `value["next_deadline"] is None`, no action has kind `wait` or `finalize`, and `not set(requests[0]["issues"]) & waiting`.
Do not change any other branch; the existing `action.get("issue")` checks do not see `issues` and need no change.

- [ ] **Step 4: Verify**

Run the Step 2 commands. Expected: both `OK` (1 test each; the fixture test's 17 rejection subtests all pass).
Guard-deletion check (Phase-5 SF-2, the-bar *Tests that can fail*): temporarily delete the `value["actions"][-1] is requests[0]` clause and rerun the fixture test — exactly the `not_last` subtest must fail; restore the clause. Likewise temporarily replace the order-equality clause with a sorted-order comparison (`sorted(item["issues"]) == item["issues"]`) — the positive `reply()` (summary order 152, 151) and `out_of_order` must fail; restore. Record both observations in the task report, and do not commit either mutation.
Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_workflow_delivery.py 2>&1 | tail -4`
Expected: `OK`.
Falsifiable gate: `grep -c 'id kind issues' home/common/agent-skills/scripts/delivery_model/_wire.py` prints `1` (it prints `0` at base, where the command exits 1).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/delivery_model/_wire.py home/common/agent-skills/tests/test_delivery_model.py home/common/agent-skills/tests/test_delivery_workflow.py
git commit -m "feat(delivery-model): validate control's delivery_contract action (#221)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
