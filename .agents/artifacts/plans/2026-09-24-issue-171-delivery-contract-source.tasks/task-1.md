# Task 1: Slot PR binding in the delivery model

Decisions: D7, D12, D19. Spec §2. Work from the worktree root; `S`/`T` as in the
plan root.

**Files:**
- Modify: `S/delivery_model/_objects.py` (`_scope`, `_pr_numbers`)
- Test: `T/test_delivery_model.py`

**Interfaces:**
- Consumes: the existing fixtures `contract_and_delivery`, `stage_scope`,
  `intent`, `seal`, `rebind_contract`, `with_observed`, `observation`,
  `selection`, `pr_subject`, `evaluation`, `stage_state`, `post_state`.
- Produces: the scope-target grammar `pr_ref ∈ {none, literal, {"kind":"slot","slot_id":<str>}}`,
  where the slot form is valid only when `target.output_ref == {"kind":"slot","slot_id":<same>}`.
  Tasks 2–3 emit that form for `open_pr`/`merge_pr` scopes.

**Invariants:**
- Matching stays exact: `_scope_mismatch` is unchanged, so a declared slot
  `pr_ref` admits only a requested slot `pr_ref` with the same `slot_id`.
- Under a declared slot `pr_ref`, `_pr_numbers` admits exactly the PR numbers of
  `pr_opened` observations whose subject matches the open stage on repository
  (`provider_repository_id == contract.project.repository_id`), head
  (`expected_head == _selected_head(delivery, selected)`) and base
  (`base == selected["base"]`); it never reads a `pr_number` to decide admission.
- Two distinct matching `pr_opened` subjects still reject through the existing
  conflicting-stage-observation rule in `reduce_delivery`.
- The literal `pr_ref` path and every existing model test are unchanged.

- [ ] **Step 1: Write the failing tests**

Add `pr_subject` to the `from ._delivery_model_fixtures import (...)` list, then
add to `DeliveryModelTest`:

```python
    def slot_pr_delivery(self):
        """The fixture contract under an initial intent whose open/merge scopes bind the slot PR."""
        contract, delivery = contract_and_delivery(self.model)
        declared = []
        for stage_id in ("open", "merge"):
            value = stage_scope(self.model, contract, stage_id)
            value["target"]["pr_ref"] = {"kind": "slot", "slot_id": "reviewed"}
            declared.append(seal(self.model, value))
        first = intent(self.model, declared[0])
        first["scopes"] = sorted(declared, key=lambda item: item["id"])
        seal(self.model, first)
        contract["initial_authorization_intent_id"] = first["id"]
        contract["initial_authorization_intent_digest"] = self.model.canonical_digest(first)
        delivery = rebind_contract(self.model, contract, delivery)
        delivery["authorization_intents"] = [first]
        delivery["authorization_chain_digest"] = self.model.canonical_digest(
            {"intent_ids": [first["id"]]})
        return contract, delivery, first, declared

    def test_slot_pr_ref_grammar_requires_the_same_output_slot(self):
        _, _, _, declared = self.slot_pr_delivery()
        for item in declared:
            self.assertEqual(self.validate(item, "scope-tuple"), item)
        for output_ref in ({"kind": "none"}, {"kind": "slot", "slot_id": "other"}):
            bad = copy.deepcopy(declared[0])
            bad["target"]["output_ref"] = output_ref
            seal(self.model, bad)
            with self.subTest(output_ref=output_ref):
                self.assert_invalid(bad, "scope-tuple")
        bad = copy.deepcopy(declared[0])
        bad["target"]["pr_ref"] = {"kind": "slot", "slot_id": "reviewed", "extra": 1}
        seal(self.model, bad)
        self.assert_invalid(bad, "scope-tuple")

    def test_slot_pr_ref_matches_only_the_slot_form(self):
        contract, _, first, declared = self.slot_pr_delivery()
        selected = selection(self.model, self.model.canonical_digest(contract))
        at = {"selected_outputs": [selected], "at_time": "2026-09-21T00:00:00Z",
              "revocation_observations": []}
        self.assertEqual(self.model.match_scope(
            contract, first, declared[0], **at)["reason_code"], "matched")
        literal = copy.deepcopy(declared[0])
        literal["target"]["pr_ref"] = {"kind": "literal", "value": "17"}
        seal(self.model, literal)
        self.assertEqual(self.model.match_scope(
            contract, first, literal, **at)["reason_code"], "scope_target_mismatch")

    def test_slot_pr_ref_binds_the_opened_pr_without_a_successor(self):
        contract, delivery, _, _ = self.slot_pr_delivery()
        observed = with_observed(self.model, contract, delivery,
                                 ["select", "publish", "open", "merge"])
        reduced = self.model.reduce_delivery(contract, observed, evaluation=evaluation())
        self.assertEqual(
            (stage_state(reduced, "open"), stage_state(reduced, "merge"),
             post_state(reduced, "pr_merged")),
            ("observed", "observed", "observed"))
        self.assertEqual(len(reduced["next_delivery"]["authorization_intents"]), 1)

        second = observation(self.model, contract, "pr_opened",
                             pr_subject("pr_opened", pr=18))
        conflicting = copy.deepcopy(observed)
        conflicting["delivery_observations"] = sorted(
            conflicting["delivery_observations"] + [second], key=lambda item: item["id"])
        with self.assertRaises(self.model.DeliveryModelError):
            self.model.reduce_delivery(contract, conflicting, evaluation=evaluation())

        foreign = with_observed(self.model, contract, delivery, ["select", "publish"])
        foreign["delivery_observations"] = sorted(
            foreign["delivery_observations"] + [observation(
                self.model, contract, "pr_opened",
                pr_subject("pr_opened", head="c" * 40))],
            key=lambda item: item["id"])
        reduced = self.model.reduce_delivery(contract, foreign, evaluation=evaluation())
        self.assertEqual(stage_state(reduced, "open"), "pending")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run from the worktree root:
`python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py -k slot_pr 2>&1 | tail -5`

Expected: FAIL/ERROR in all three new tests — the slot `pr_ref` is rejected by
`_ref` ("invalid pr ref kind"). Confirm this at the starting commit.

- [ ] **Step 3: Implement**

In `_scope` (`S/delivery_model/_objects.py`), replace the single
`_ref(target["pr_ref"], "pr ref")` call with: if `target["pr_ref"].get("kind") == "slot"`,
require exact members `{"kind","slot_id"}` (reuse `_slot_ref(..., constraints=False)`)
and require `target["output_ref"] == {"kind": "slot", "slot_id": target["pr_ref"]["slot_id"]}`,
else `_reject()`; otherwise call `_ref` as today.

In `_pr_numbers`, after the existing target and `output_ref` filters, keep the
literal branch and add the slot branch:

```python
            ref = target["pr_ref"]
            if ref["kind"] == "literal" and ref["value"].isdigit():
                values.add(int(ref["value"]))
            elif ref == {"kind": "slot", "slot_id": selected["slot_id"]}:
                head = _selected_head(delivery, selected)
                values.update(
                    item["subject"]["pr_number"]
                    for item in delivery["delivery_observations"]
                    if item["observation_kind"] == "pr_opened"
                    and item["subject"]["provider_repository_id"]
                    == contract["project"]["repository_id"]
                    and head is not None and item["subject"]["expected_head"] == head
                    and item["subject"]["base"] == selected["base"])
```

This is the one admission change (per D7); `_scope_mismatch`,
`_stage_observation_matches` and `reduce_delivery` stay as they are.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py 2>&1 | tail -3`
Expected: `OK`, including the three new tests and the unchanged
`test_slot_narrowing_and_literal_pr_are_exact`.

Run: `just agent-workflow-tests 2>&1 | tail -3`
Expected: `OK (skipped=1)`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/delivery_model/_objects.py \
  home/common/agent-skills/tests/test_delivery_model.py
git commit -m "feat(delivery-model): bind the slot PR through its opened observation"
```
