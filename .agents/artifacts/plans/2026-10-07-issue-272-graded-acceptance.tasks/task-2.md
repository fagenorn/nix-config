# Task 2: `acceptance_state` on `ship-handoff/v2`

Lane: full (a report-boundary schema, which is a public contract). Decisions:
per D8, D9, D11 and D16 of the spec's ledger. The delivery model only admits the
key, and artifact-budget applies the one pairing to it. The delivery contract
and its digest do not change.

**Files:**
- Modify: `home/common/agent-skills/scripts/delivery_model/_wire.py`
- Modify: `home/common/agent-skills/scripts/artifact_budget.py`
- Modify: `home/common/agent-skills/tests/_delivery_model_fixtures.py`
- Modify: `home/common/agent-skills/tests/test_delivery_workflow.py`
- Test: `home/common/agent-skills/tests/test_delivery_model.py`
- Test: `home/common/agent-skills/tests/test_artifact_budget.py`

**Interfaces:**
- Consumes (Task 1): `artifact_budget.ACCEPTANCE_STATES` and
  `artifact_budget.acceptance_pairs_with_review(review_state, acceptance_state) -> bool`.
  It is true exactly for `clean` → {`met`, `human_pending`,
  `not_applicable`}, `residuals` → any of the four values, and `unknown` →
  {`not_applicable`}. Consumes the existing `_ship_handoff(value, notes_max)`
  in `_wire.py` and `validate_delivery_model_report(value, notes_max_characters, boundary)`
  in `artifact_budget.py`.
- Produces: `ship-handoff/v2` has exactly one more key, `acceptance_state`. The
  model checks that it is a non-empty string. The shared fixture
  `ship_handoff(model, contract, delivery)` returns it as `"met"`.

**Invariants:**
- The model's `_ship_handoff` key set is the old set plus
  `acceptance_state`. A v2 handoff without the key, or with a non-string
  value, raises `DeliveryModelError`.
- The model never names the closed set or the pairing. Those appear only in
  `artifact_budget.py` (per D9).
- `artifact-budget validate-report --boundary ship-handoff` on a v2 handoff
  exits 2 with empty stdout when the pair (`review_state`,
  `acceptance_state`) is outside the table. That includes a `review_state`
  outside `clean`, `residuals` and `unknown` (per D11). It also exits 2 for
  `acceptance_state: unmet` with a null `report_path` (per D16). The accepted
  residual fixtures carry a durable `report_path` named in `notes`.
- `canonical_digest(contract)` of every fixture contract is unchanged.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_delivery_model.py`, add this test to
the class that holds `test_ship_handoff_cross_references_and_contract_order`,
directly after that test:

```python
    def test_ship_handoff_admits_acceptance_state_as_a_string(self):
        """#272 D9: the model admits the key; artifact-budget owns its values."""
        contract, delivery = contract_and_delivery(self.model)
        handoff = ship_handoff(self.model, contract, delivery)
        self.assertEqual(handoff["acceptance_state"], "met")
        self.assertEqual(self.validate(handoff, "ship-handoff"), handoff)
        missing = copy.deepcopy(handoff)
        missing.pop("acceptance_state")
        self.assert_invalid(missing, "ship-handoff")
        for value in (None, 1, True, ["met"], ""):
            bad = copy.deepcopy(handoff)
            bad["acceptance_state"] = value
            with self.subTest(value=value):
                self.assert_invalid(bad, "ship-handoff")
```

In `home/common/agent-skills/tests/test_artifact_budget.py`, extend the
fixture import to
`from ._delivery_model_fixtures import contract_and_delivery, custody, ship_handoff, workflow_responses`.
Then add to `ArtifactBudgetCliTest`:

```python
    def test_ship_handoff_v2_acceptance_state_is_required_closed_and_paired(self):
        """#272 D8, D9, D11: the v2 handoff gets the same pairing as the legacy one."""
        model = artifact_budget._delivery_model()
        contract, delivery = contract_and_delivery(model)
        handoff = ship_handoff(model, contract, delivery)
        detail = ".superpowers/issue-delivery/151/run-1/sdd-a.json"
        residual = {**handoff, "review_state": "residuals", "report_path": detail,
                    "notes": f"details: {detail}"}
        accepted = [
            *({**handoff, "acceptance_state": v} for v in ("met", "human_pending", "not_applicable")),
            *({**residual, "acceptance_state": v}
              for v in ("met", "unmet", "human_pending", "not_applicable")),
            {**handoff, "review_state": "unknown", "acceptance_state": "not_applicable"},
        ]
        for index, payload in enumerate(accepted):
            with self.subTest(accepted=index):
                result = self.run_validate("ship-handoff", payload, use_stdin=True)
                self.assertEqual(result.returncode, 0, result.stderr)
        rejected = [
            {key: value for key, value in handoff.items() if key != "acceptance_state"},
            {**handoff, "acceptance_state": "unmet"},
            {**handoff, "acceptance_state": "partially_met"},
            {**handoff, "review_state": "unknown", "acceptance_state": "met"},
            {**handoff, "review_state": "partial", "acceptance_state": "met"},
            {**residual, "acceptance_state": "unmet", "report_path": None,
             "notes": "no durable detail"},
        ]
        for index, payload in enumerate(rejected):
            with self.subTest(rejected=index):
                result = self.run_validate("ship-handoff", payload, use_stdin=True)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, b"", b"artifact-budget: invalid report\n"))
```

In `home/common/agent-skills/tests/_delivery_model_fixtures.py`, in
`ship_handoff`, add `"acceptance_state": "met",` directly after
`"review_state": "clean",`. In
`home/common/agent-skills/tests/test_delivery_workflow.py`, in `handoff`
(the Phase-7 `ship-handoff/v2` builder), add `"acceptance_state": "met",` in
the same position.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py home/common/agent-skills/tests/test_artifact_budget.py 2>&1 | tail -5`
Expected: FAIL. Every test that validates the shared `ship_handoff` fixture
now fails on its unknown `acceptance_state` key, and so do the two new tests.

- [ ] **Step 3: Write the minimal implementation**

`_wire.py`, `_ship_handoff`:
- Add `"acceptance_state"` to `keys`.
- Add `"acceptance_state"` to the tuple of names that the existing loop
  passes to `_string(value[name], f"handoff {name}")`. The loop starts
  `for name in ("state", …, "review_state")`. Add no other check, because the
  closed set lives in artifact-budget (per D9).

`artifact_budget.py`, `validate_delivery_model_report`: inside the existing
`try`, after `model.validate_delivery_object(...)` returns, add:

```python
        if boundary == "ship-handoff" and isinstance(value, dict) and (
                not acceptance_pairs_with_review(value["review_state"], value["acceptance_state"])
                or (value["acceptance_state"] == "unmet" and value["report_path"] is None)):
            # The model only admits the key; the closed pairing is ours (#272 D9),
            # and an unmet criterion travels only with its durable detail (#272 D16).
            raise ArtifactBudgetError("acceptance_state does not pair with review_state")
```

The existing `except Exception` re-raises it as `invalid ship-handoff`, and
`main` turns that into exit 2. Change nothing else.

- [ ] **Step 4: Verify**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py home/common/agent-skills/tests/test_artifact_budget.py home/common/agent-skills/tests/test_delivery_workflow.py 2>&1 | tail -3`
Expected: `OK`.

Run: `if ! grep -q '"acceptance_state"' home/common/agent-skills/scripts/delivery_model/_wire.py; then exit 1; fi`
Expected: exit 0. At the base commit this exits 1.

Run: `if grep -q 'human_pending' home/common/agent-skills/scripts/delivery_model/_wire.py; then exit 1; fi`
Expected: exit 0, because the closed set is not restated in the model.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/delivery_model/_wire.py home/common/agent-skills/scripts/artifact_budget.py home/common/agent-skills/tests/_delivery_model_fixtures.py home/common/agent-skills/tests/test_delivery_model.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_artifact_budget.py
git commit -m "feat(delivery-model): admit acceptance_state on ship-handoff/v2 and pair it (#272)"
```
Under a `Lifecycle worker:` line, commit with
`launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- -m "<message>"`
instead of `git commit`.
