# Task 1: Optional `stall_minutes` orchestration binding

> **Phase 6 amendment (D15):** author no `stall_minutes` value in `.agents/project.json` or the eval fixture's `project.json`, and drop the `CommittedContractTest` assertion of 90. The installed resolver refuses the unknown member until this change is deployed; authoring the value is a follow-up. Every bullet and step below that edits either `project.json` or asserts the committed 90 is superseded.

**Files:**
- Modify: `python/agent_tools/resolve_project.py`
- Modify: `.agents/project.json`
- Modify: `home/common/agent-skills/evals/fixture-repo/.agents/project.json`
- Test: `home/common/agent-skills/tests/test_resolve_project.py` (new `StallMinutesTest`, one extended `CommittedContractTest` method)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `bindings.workflow.orchestration.stall_minutes` in the resolved snapshot, returned exactly as authored (absent, `null` or a positive integer). Task 5 documents it in orchestrate-issues §1, and Task 6 uses the committed value 90.
- Produces, in `resolve_project.py`: `ORCHESTRATION_OPTIONAL_MEMBERS = ("stall_minutes",)`, next to `WORKFLOW_OPTIONAL_MEMBERS`.

**Invariants:**
- `workflow.orchestration` still requires exactly `max_parallel` and `attempt_budget_minutes`. `stall_minutes` may be present or absent. Any other member is still `contract.workflow.member_unexpected` (D1).
- A present, non-null `stall_minutes` that is not a positive integer (zero, negative, a boolean, a string, a float) is refused with `contract.workflow.not_positive_int` at pointer `/bindings/workflow/orchestration/stall_minutes`, and with no other violation.
- Absent stays absent and `null` stays `null` in the snapshot. No value is defaulted (bootstrap "No project policy is defaulted").
- `.agents/project.json` and the eval fixture's `project.json` both set `"stall_minutes": 90`, placed after `attempt_budget_minutes` (D1).

- [ ] **Step 1: Write the failing tests**

In `test_resolve_project.py`, extend `CommittedContractTest.test_orchestration_values_are_committed_contract_values` with one assertion after the `attempt_budget_minutes` line:

```python
        self.assertEqual(orchestration["stall_minutes"], 90)
```

Then add this class after `LightLaneTest`:

```python
class StallMinutesTest(ResolverTestCase):
    """#310 D1: the optional `bindings.workflow.orchestration.stall_minutes` member."""

    POINTER = "/bindings/workflow/orchestration/stall_minutes"

    def contract_with(self, **members):
        contract = source_contract()
        orchestration = contract["bindings"]["workflow"]["orchestration"]
        orchestration.pop("stall_minutes", None)
        orchestration.update(members)
        return contract

    def test_absent_null_and_positive_values_round_trip(self):
        for members in ({}, {"stall_minutes": None}, {"stall_minutes": 1},
                        {"stall_minutes": 90}):
            with self.subTest(members=members):
                code, snap, err = self.resolve(self.make_root(self.contract_with(**members)))
                self.assertEqual(code, 0, err)
                self.assertEqual(snap["bindings"]["workflow"]["orchestration"],
                                 {"max_parallel": 2, "attempt_budget_minutes": 240, **members})

    def test_each_malformed_value_is_refused_with_its_pointer(self):
        for value in (0, -5, True, False, "90", 1.5, [90]):
            with self.subTest(value=value):
                code, payload, _ = self.resolve(
                    self.make_root(self.contract_with(stall_minutes=value)))
                self.assertEqual(code, 2)
                error = payload["error"]
                self.assertEqual((error["code"], error["repair_id"]),
                                 ("invalid_contract", "contract.workflow.not_positive_int"))
                self.assertEqual([v["pointer"] for v in error["violations"]], [self.POINTER])

    def test_any_other_orchestration_member_is_still_unexpected(self):
        code, payload, _ = self.resolve(
            self.make_root(self.contract_with(stall_seconds=60)))
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["repair_id"], "contract.workflow.member_unexpected")
        self.assertEqual([v["pointer"] for v in payload["error"]["violations"]],
                         ["/bindings/workflow/orchestration/stall_seconds"])

    def test_the_repository_and_the_eval_fixture_resolve_with_ninety(self):
        for root in (REPO_ROOT, EVAL_FIXTURE):
            with self.subTest(root=root.name):
                code, out, err = run("resolve", "--repo-root", str(root), home=self.home)
                self.assertEqual(code, 0, err or out)
                orchestration = json.loads(out)["bindings"]["workflow"]["orchestration"]
                self.assertEqual(orchestration["stall_minutes"], 90)
```

`ResolverTestCase.resolve`, `make_root`, `source_contract`, `run`, `REPO_ROOT` and `EVAL_FIXTURE` already exist in this module. `test_eval_fixture_resolves_with_current_projections` already resolves `EVAL_FIXTURE` with `home=self.home` the same way.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py -k StallMinutes -k test_orchestration_values_are_committed`
Expected: FAIL. `stall_minutes: 1` and `90` are refused as `member_unexpected`, the malformed cases name `member_unexpected` instead of `not_positive_int`, and both committed contracts lack the member (`KeyError`).

- [ ] **Step 3: Write the minimal implementation**

In `resolve_project.py`:
- Add `ORCHESTRATION_OPTIONAL_MEMBERS = ("stall_minutes",)` directly after `WORKFLOW_OPTIONAL_MEMBERS`.
- In `validate_workflow`, pass `optional=ORCHESTRATION_OPTIONAL_MEMBERS` to the orchestration `check_exact_members` call. After the loop that checks `max_parallel` and `attempt_budget_minutes`, add: when `orchestration.get("stall_minutes") is not None`, call `check_positive_int(orchestration["stall_minutes"], f"{pointer}/stall_minutes", "workflow", violations)`.

`check_positive_int` already refuses `bool`, so `True` and `False` give `not_positive_int`.

In both `project.json` files, add `"stall_minutes": 90` as the last member of `bindings.workflow.orchestration`. Keep each file's existing two-space indentation and key order otherwise.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py`
Expected: PASS, the whole module, including `test_the_repository_projections_are_present_and_current`.

Run (timeout 3600 s, because `resolve_project.py` is import-checked by the build): `just build`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/resolve_project.py .agents/project.json \
  home/common/agent-skills/evals/fixture-repo/.agents/project.json \
  home/common/agent-skills/tests/test_resolve_project.py
git commit -m "feat(resolve-project): optional orchestration stall_minutes binding (#310)"
```
