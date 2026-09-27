# Task 1: The control boundary admits the unresumable worktree fact

Decisions: D3, D6, D11 (T5), D8. Spec "Wire: the control response validator
(D6)" and "Test seams". Work from the worktree root. Every shell block starts
with `set -euo pipefail` (`set -uo pipefail` in the watch-it-fail step) and these
abbreviations, which the blocks below omit:

```bash
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
```

**Files:**
- Modify: `home/common/agent-skills/scripts/delivery_model/_wire.py`
  (`_control_response` only)
- Test: `home/common/agent-skills/tests/test_delivery_model.py`
  (`DeliveryModelTest`: one test)

**Interfaces:**
- Consumes (existing): `workflow_responses(model)["control"]` from
  `T/_delivery_model_fixtures.py`. It is a claude-code control response with one
  contracted `active` summary for issue 151 (`worktree` `/worktree`), one
  `spawned` delta and one `spawn` action for 151. Also consumed:
  `self.validate(value, kind)`, `self.assert_invalid(value, kind)` and
  `self.model.canonical_bytes`.
- Produces: `workflow-response` validation of control summaries carrying one
  `{"kind": "worktree_fact", "subject_id": <path>, "reason_code":
  "recorded_worktree_absent" | "recorded_worktree_mismatch", "detail_pointer":
  null}` requirement. Task 2's producer emits exactly this member, and Task 2's
  S3 checks rely on it being accepted.

**Invariants:**
- A control summary carries at most one `worktree_fact`. Its `reason_code` is
  one of the two codes, its `detail_pointer` is null, and its `subject_id`
  equals the summary's `worktree` whenever that is non-null (D6, D11). There is
  no custody-state rule (D11).
- A null `contract_digest` still admits only `[]` or `[delivery_contract_required]`
  once the `worktree_fact` is removed, and still no pending stages.
- No action names an issue whose summary carries a `worktree_fact`. Contractless
  and `waiting` issues keep their existing no-action rules.
- `_requirements` (the generic shape check) and every non-control boundary are
  unchanged.

- [ ] **Step 1: Write the failing test**

In `class DeliveryModelTest` of `$T/test_delivery_model.py`, insert this method
directly after `test_current_launch_and_null_contract_correlations_are_exact`
and before `test_ship_handoff_cross_references_and_contract_order`. Every
fixture is valid apart from the one rule it names. Requirements are sorted in
canonical-bytes order, and a refused issue has no delta and no dispatch.

```python
    def test_control_summaries_admit_one_closed_unresumable_worktree_fact(self):
        """T5 (#194): the per-issue resume refusal's closed rules at the control boundary."""
        fixtures = workflow_responses(self.model)
        fact = {"kind": "worktree_fact", "subject_id": "/worktree",
                "reason_code": "recorded_worktree_absent", "detail_pointer": None}
        contract_required = {"kind": "delivery_contract", "subject_id": "151",
                             "reason_code": "delivery_contract_required",
                             "detail_pointer": None}

        def with_fact(requirements, *, contracted=True, worktree="/worktree", dispatch=False):
            """The control fixture with issue 151 refused: no delta, only `finalize`."""
            value = copy.deepcopy(fixtures["control"])
            summary = value["summaries"][0]
            summary.update(worktree=worktree, requirements=sorted(
                copy.deepcopy(requirements), key=self.model.canonical_bytes))
            if not contracted:
                summary.update(contract_digest=None, pending_stage_ids=[])
            owner = fixtures["control"]["actions"]
            value.update(deltas=[], next_deadline=None, actions=[
                *(copy.deepcopy(owner) if dispatch else []),
                {"id": "finalize", "kind": "finalize"}])
            return value

        mismatch = {**fact, "reason_code": "recorded_worktree_mismatch"}
        for name, value in {
                "contracted_absent": with_fact([fact]),
                "contracted_mismatch": with_fact([mismatch]),
                "contractless": with_fact([fact], contracted=False),
                "contractless_with_its_contract_requirement": with_fact(
                    [contract_required, fact], contracted=False),
                "no_summary_worktree": with_fact(
                    [{**fact, "subject_id": "/removed"}], worktree=None),
        }.items():
            with self.subTest(accepted=name):
                self.assertEqual(self.validate(value, "workflow-response"), value)
        for name, value in {
                "unknown_code": with_fact([{**fact, "reason_code": "recorded_worktree_gone"}]),
                "detail_pointer": with_fact([{**fact, "detail_pointer": "/detail"}]),
                "other_subject": with_fact([{**fact, "subject_id": "/elsewhere"}]),
                "two_facts": with_fact([fact, mismatch]),
                "dispatched": with_fact([fact], dispatch=True),
                "contractless_extra": with_fact([fact, {"kind": "scope_tuple",
                    "subject_id": "select", "reason_code": "scope_tuple_required",
                    "detail_pointer": None}], contracted=False),
        }.items():
            with self.subTest(rejected=name):
                self.assert_invalid(value, "workflow-response")
```

- [ ] **Step 2: Watch it fail**

```bash
set -uo pipefail
PYTHONPATH=python python3 -m unittest $T/test_delivery_model.py \
  -k unresumable_worktree_fact 2>&1 \
  | grep -E '^(FAIL|ERROR):|^Ran|^OK|^FAILED'
```

Expected: `Ran 1 test` and `FAILED (failures=5, errors=2)`. The two errors are
the `contractless` and `contractless_with_its_contract_requirement` acceptances,
which the base contractless rule rejects. The five failures are
`unknown_code`, `detail_pointer`, `other_subject`, `two_facts` and
`dispatched`, which the base accepts. `contractless_extra` passes, because the
existing contractless rule already rejects it. Any other outcome means the
fixture is wrong: stop and report it.

- [ ] **Step 3: Add the closed rules**

In `_control_response` of `$S/delivery_model/_wire.py`, make exactly these three
edits. The full code is given because it is the exact wire rule (D6, D11).

1. Track the refused issues beside the contractless ones:

   ```python
   # before
       issues = set(); missing_contracts = set(); order = []
   # after
       issues = set(); missing_contracts = set(); unresumable = set(); order = []
   ```

2. In the summary loop, directly after the
   `_blockers(...); _pending(...); _requirements(...)` line, replace the
   contractless block:

   ```python
   # before
           if item["contract_digest"] is None:
               expected = {"kind": "delivery_contract", "subject_id": str(issue),
                           "reason_code": "delivery_contract_required", "detail_pointer": None}
               if item["pending_stage_ids"] or item["requirements"] not in ([], [expected]): _reject()
               missing_contracts.add(issue)
   # after
           facts = [entry for entry in item["requirements"] if entry["kind"] == "worktree_fact"]
           if facts:
               if (len(facts) != 1
                       or facts[0]["reason_code"] not in {"recorded_worktree_absent", "recorded_worktree_mismatch"}
                       or facts[0]["detail_pointer"] is not None
                       or (item["worktree"] is not None and facts[0]["subject_id"] != item["worktree"])): _reject()
               unresumable.add(issue)
           if item["contract_digest"] is None:
               expected = {"kind": "delivery_contract", "subject_id": str(issue),
                           "reason_code": "delivery_contract_required", "detail_pointer": None}
               remaining = [entry for entry in item["requirements"] if entry["kind"] != "worktree_fact"]
               if item["pending_stage_ids"] or remaining not in ([], [expected]): _reject()
               missing_contracts.add(issue)
   ```

3. Widen the contractless no-action check to the refused issues:

   ```python
   # before
       if any(action.get("issue") in missing_contracts for action in value["actions"]): _reject()
   # after
       if any(action.get("issue") in missing_contracts | unresumable for action in value["actions"]): _reject()
   ```

- [ ] **Step 4: Verify**

```bash
set -euo pipefail
PYTHONPATH=python python3 -m unittest $T/test_delivery_model.py 2>&1 \
  | grep -E '^(FAIL|ERROR):|^Ran|^OK|^FAILED'
test "$(grep -c 'unresumable' $S/delivery_model/_wire.py)" = 3
```

Expected: `Ran 35 tests` (34 at the base plus this one) and `OK`, and the
`test` exits 0.
`test_workflow_response_validation_is_structural_only` and
`test_current_launch_and_null_contract_correlations_are_exact` pin the unchanged
contractless and `waiting` rules.

- [ ] **Step 5: Commit**

```bash
set -euo pipefail
git add $S/delivery_model/_wire.py $T/test_delivery_model.py
git commit -m "fix(delivery-model): admit the unresumable worktree fact on control summaries (#194)" \
  -m "A control summary may carry one worktree_fact naming its recorded worktree as absent or mismatched. The validator closes its codes, pointer and subject, keeps the contractless rule once the fact is removed, and forbids any action for that issue." \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
