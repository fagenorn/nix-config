# Task 5: Lifecycle gates, and `succeeded` only through `settle_proof`

**Files:**
- Modify: `python/agent_tools/transaction_proof.py` (the gate predicate and the seal pairing)
- Modify: `python/agent_tools/transaction_history.py` (the validator calls the gate)
- Modify: `python/agent_tools/transaction_core.py` (`advance`)
- Modify: `tests/test_transaction_proof.py` (append)
- Modify: `tests/test_transaction_core.py`, `tests/test_transaction_custody.py`
  (their `succeeded` paths go through `settle_proof`)
- Modify: `tests/transaction_core_sweep_support.py` (the final step settles)

**Interfaces:**
- Consumes (Tasks 1–4): the plan's `units` (with `phase` and `action_id`),
  `transaction_invocation.fold_actions`, `status`, `ActionFold`, `RESERVED_REASONS`,
  `pairing_violation`, and `TransactionStore.start_cohort`/`settle_proof`. Also the
  Task 3 test helpers `ProofCase`, `FakeEffect` and `renumbered`.
- Produces (`agent_tools.transaction_proof`): `gate_violation(plan: Mapping, actions:
  Mapping[str, ActionFold], source: str, target: str) -> str | None`.

**Invariants:**
- `gate_violation` is the one gate home, and both `advance` and `validate_state` call it
  (per D12):
  - `publishing → published` needs every `publication` unit's action present with
    `status == "satisfied"`. Otherwise it returns `f"publication unit {name}
    ({action_id}) is {status or 'undeclared'}"`.
  - `activating → proving` needs the same for every `activation` unit.
  - `published → proving` needs a plan with no `activation` unit.
  - Every other edge returns None, including every resume from `attention_required` to
    its `parked_from`. With the empty declaration every gate is vacuous.
- `advance` refuses with `TransitionRefused`, before any write and after the existing edge,
  reason and external-state checks:
  - any `succeeded` target, with the message `"<id>: <source> -> 'succeeded': succeeded is
    entered only through settle_proof"`;
  - a `proving → attention_required` whose reason is in `RESERVED_REASONS` (per D27);
  - a failing `gate_violation`, whose rule it names.
- `pairing_violation` gains the converse seal rule: a transition to `succeeded` must
  immediately follow `proof_sealed` (per D10), with a rule message containing
  `proof_sealed` (e.g. `"transition to succeeded does not immediately follow
  proof_sealed"`). `validate_state` applies `gate_violation`
  to every `transitioned` event, using the actions folded before it.
- Existing tests change only where the `succeeded` gate demands it (per D23); only event
  counts grow, by the two cohort events.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_transaction_proof.py`
  (above `OBSERVED_PROOF_REASONS`):

```python
class GateTest(ProofCase):
    def test_succeeded_is_reachable_only_through_settle_proof(self):
        self.proving()
        self.collect_required()
        error = self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("succeeded"))
        self.assertIn("settle_proof", str(error))

    def test_published_needs_every_publication_unit_satisfied(self):
        self.to("awaiting_verification", "ready", "publishing")
        error = self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("published"))
        self.assertIn("undeclared", str(error))
        self.store.inspect_action(self.custody, name="build", parameters={"n": 1},
                                  effect=FakeEffect(self.world))
        error = self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("published"))
        self.assertIn("absent", str(error))
        self.satisfy("build", {"n": 1})
        self.assertEqual(self.to("published").state, "published")

    def test_proving_after_activation_needs_every_activation_unit_satisfied(self):
        self.to("awaiting_verification", "ready", "publishing")
        self.satisfy("build", {"n": 1})
        self.to("published", "activating")
        self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("proving"))
        self.satisfy("start", {"n": 2})
        self.assertEqual(self.to("proving").state, "proving")

    def test_proving_straight_from_published_needs_no_activation_unit(self):
        self.to("awaiting_verification", "ready", "publishing")
        self.satisfy("build", {"n": 1})
        self.to("published")
        error = self.assertRefusedUnchanged(TransitionRefused, lambda: self.to("proving"))
        self.assertIn("activation", str(error))
        self.transaction_id = self.store.create(
            "no-activation", SUBJECT, concurrency_keys=("key:solo",),
            proof={**DECLARATION, "units": UNITS[:1], "obligations": []}).transaction_id
        self.custody = self.acquire(self.transaction_id)
        self.to("awaiting_verification", "ready", "publishing")
        self.satisfy("build", {"n": 1})
        self.assertEqual(self.to("published", "proving").state, "proving")

    def test_a_resume_to_the_parked_state_is_ungated(self):
        self.to("awaiting_verification", "ready", "publishing")
        self.satisfy("build", {"n": 1})
        self.to("published")
        self.store.inspect_action(self.custody, name="build", parameters={"n": 1},
                                  effect=FakeEffect(self.world, inspect_outcome="diverged"))
        self.to("attention_required")
        self.assertEqual(self.to("published").state, "published")

    def test_advance_never_writes_a_reserved_reason(self):
        self.proving()
        for reason in ("proof_rejected", "proof_did_not_converge"):
            with self.subTest(reason=reason):
                self.assertRefusedUnchanged(TransitionRefused, lambda: self.store.advance(
                    self.transaction_id, "attention_required", reason=reason,
                    custody=self.custody))
        after = self.store.advance(self.transaction_id, "attention_required",
                                   reason="operator asked", custody=self.custody)
        self.assertEqual(after.state, "attention_required")

    def test_hand_built_gate_breaches_are_state_invalid(self):
        def appended(document, source, target):
            document = copy.deepcopy(document)
            document["events"].append({
                "seq": 0, "type": "transitioned", "at": document["events"][-1]["at"],
                "from": source, "to": target, "reason": "r", "external_state": "known"})
            document.update(state=target, parked_from=None)
            return renumbered(document)

        self.to("awaiting_verification", "ready", "publishing")
        self.store.inspect_action(self.custody, name="build", parameters={"n": 1},
                                  effect=FakeEffect(self.world))
        publishing = self.state_doc(self.transaction_id)
        self.assertRuleRefuses(self.transaction_id,
                               appended(publishing, "publishing", "published"),
                               "publication unit build")
        (self.root / self.transaction_id / "state.json").write_text(serialize(publishing))
        self.store.invoke_action(self.custody, name="build", parameters={"n": 1},
                                 effect=FakeEffect(self.world))
        self.to("published", "activating")
        self.satisfy("start", {"n": 2})
        self.to("proving")
        self.collect_required()
        proving = self.state_doc(self.transaction_id)
        unsealed = appended(proving, "proving", "succeeded")
        unsealed["events"].append({
            "seq": len(unsealed["events"]) + 1, "type": "lease_released",
            "at": unsealed["events"][-1]["at"], "fence": proving["custody"]["fence"],
            "reason": "terminal"})
        unsealed.update(custody=None, revision=len(unsealed["events"]))
        self.assertRuleRefuses(self.transaction_id, unsealed, "proof_sealed")
```

  Then update the existing tests (per D23):
  - `tests/test_transaction_core.py`:
    - In `AdvanceCase.reach`, a `"succeeded"` target calls
      `self.store.start_cohort(custody)` then `self.store.settle_proof(custody)` instead
      of `advance`.
    - In `test_the_forward_chain_persists_one_event_per_transition`, expect `revision` 12
      and seqs `range(1, 13)`.
    - In `test_every_allowed_edge_is_accepted_and_every_other_target_refused`, subtract
      `"succeeded"` from `allowed` (advance now refuses it everywhere).
    - In `test_a_terminal_target_requires_known_external_state`, reach `succeeded` through
      the two settle calls instead of the final `advance`.
    - In `test_a_valid_hand_built_history_loads`, drop the `FORWARD[1:] + ("succeeded",)`
      target list, and add beside it:

```python
    def test_a_hand_built_succeeded_without_a_seal_is_refused(self):
        transaction_id = self.store.create("k", SUBJECT, concurrency_keys=KEYS,
                                           proof=EMPTY_PROOF).transaction_id
        self.write(transaction_id, with_history(self.document(transaction_id),
                                                *FORWARD[1:], "succeeded"))
        with self.assertRaises(StateInvalid) as caught:
            self.store.load(transaction_id)
        self.assertIn("proof_sealed", str(caught.exception))
```

  - `tests/test_transaction_custody.py`: `FencedAdvanceTest.step` reaches a `"succeeded"`
    target through `start_cohort` + `settle_proof` with the passed custody. In
    `test_a_terminal_transaction_refuses_late_results`, replace the `advance(...,
    "succeeded", ...)` with the same two calls.
  - `tests/transaction_core_sweep_support.py`: replace `advance("succeeded", ...)` with
    `store.start_cohort(held["custody"])` followed by `store.settle_proof(held["custody"])`
    (the sweep still passes the empty declaration until Task 6).

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_proof.py 2>&1 | tail -3`.
  Expected: FAIL, in `GateTest` (for example `succeeded` is still accepted by `advance`).

- [ ] **Step 3: Implement** the invariants. Update the `advance` docstring and the
  `transaction_core` module docstring from the resulting code: `advance` never enters
  `succeeded`, never writes a reserved reason, and applies the publication and activation
  gates.

- [ ] **Step 4: Verify.**
  Run the root's slice unit command. Expected: `OK`.

```bash
if grep -n 'advance("succeeded"' tests/transaction_core_sweep_support.py; then exit 1; fi
grep -q "def gate_violation" python/agent_tools/transaction_proof.py || exit 1
```

  Run: `just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.** Stage exactly this task's **Files**, then:

```bash
git commit -m "feat(transaction-core): gate publication, proving and success on the plan (#207)"
```

- [ ] **Step 6: Check the review budget** (after the commit): run the root's review-budget block with `FILES="python/agent_tools/transaction_*.py tests/test_transaction_proof.py tests/test_transaction_plan.py tests/test_transaction_core.py tests/test_transaction_custody.py"`.
  Expected: exit 0.

Decisions: per D10, D12, D23, D27.
