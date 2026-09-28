# Task 2: Schema v5 — the stored plan, `create(recovery=)` and `recovers`

**Files:**
- Create: `python/agent_tools/transaction_recovery.py` (the `recovery` view only, for now)
- Modify: `python/agent_tools/transaction_history.py` (v5 validator, `Transaction`, `snapshot`)
- Modify: `python/agent_tools/transaction_core.py` (`create`, `_create`, `_create_locked`)
- Modify: `tests/test_transaction_recovery_plan.py` (append)
- Modify: `tests/test_transaction_core.py`, `tests/test_transaction_custody.py`,
  `tests/test_transaction_invocation.py`, `tests/test_transaction_plan.py`,
  `tests/test_transaction_proof.py` (the required argument and the schema string only)
- Modify: `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py`

**Interfaces:**
- Consumes (Task 1): `compile_recovery`, `bind_recovery`, `materialize_recovery`,
  `recovery_plan_violation`, `RecoveryPlanRejected`; test constants `PROOF`, `RECOVERY`,
  `EMPTY_RECOVERY`, `edge`, `with_unit`, `bound`.
- Produces:
  - `TransactionStore.create(creation_key, subject, *, concurrency_keys, proof, recovery)
    -> Transaction`, and the private `_create(creation_key, subject, concurrency_keys,
    proof, recovery, recovers: str | None) -> Transaction` that `create` calls with None.
    Task 7's `roll_forward` calls it with the parent's id.
  - `agent_tools.transaction_recovery.recovery_view(document: dict) -> dict`.
  - `Transaction.recovery_plan: Mapping` (a read-only view over a deep copy) and
    `Transaction.recovery: Mapping` (a read-only view over `recovery_view`).
  - `tests/transaction_core_sweep_support.py`: `recovery_declaration(profile, registry)`
    and `shape_recovery(shape)`; `tests/test_transaction_recovery_plan.py`:
    `inert_recovery(proof)`.

**Invariants:**
- `create` compiles in this order before any lock (per D5): `_require_creatable`, then
  `compile_recovery`, `compile_proof` and `bind_recovery`, all with
  `where=f"{root}: creation_key {creation_key!r}"`. A rejection leaves the root's listing
  unchanged.
- `SCHEMA = "transaction-state/v5"`. The state key set gains `recovery_plan`, and the
  `created` event's key set gains `recovery_plan_digest` and `recovers`. `validate_state`
  checks, right after the proof plan, `recovery_plan_violation(recovery_plan, proof_plan,
  transaction_id)`. Then, beside the proof digest check, it checks that
  `recovery_plan_digest == telemetry_digest(recovery_plan)` and refuses with a rule
  containing `recovery_plan_digest`. `recovers` must be None or an `is_id` other than the
  transaction's own id, else a rule containing `recovers`. A v4 document is refused by the
  existing schema rule, naming `transaction-state/v4` (per D12).
- A same-key `create` computes the materialized recovery plan under the stored id and adds
  two conflicts to the existing `differs` list, after `proof plan`: `recovery plan` (the
  digest differs from `recovery_plan_digest`) and `recovers` (the stored `recovers`
  differs). Nothing is written (per D6, D11).
- `recovery_view(document)` returns exactly `{"plan_digest": created recovery_plan_digest,
  "recovers": created recovers, "effect_snapshot": <the latest recovery_started's
  effect_snapshot, else None>, "selected": <its selected, else []>, "children": [every
  roll_forward_linked's child_transaction_id, in order]}`. Those events do not exist yet,
  so the view reads them by type only (per D12).
- Existing tests change only by the added `recovery=` argument and
  `transaction-state/v4` → `v5`. A create whose proof has units passes
  `inert_recovery(<that proof>)`, because the unit sets must match (per D2). Those creates are
  in `tests/test_transaction_proof.py` (two) and `tests/test_transaction_plan.py`
  (`CreationTest.create`). Every other create passes `EMPTY_RECOVERY`. `tests/test_transaction_core.py` also adds
  `recovery_plan` to its asserted key set and defines its own `EMPTY_RECOVERY` beside
  `EMPTY_PROOF`. `tests/test_transaction_custody.py` does the same, and the files that
  import from it reuse its constant. The `v3`-fails-closed tests keep `v3`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_transaction_recovery_plan.py`
  (add `from agent_tools.transaction_core import CreationConflict` and
  `from .test_transaction_custody import KEYS, SUBJECT, CustodyCase` to its imports):

```python
class CreationTest(CustodyCase):
    def create(self, key="k", recovery=RECOVERY, proof=PROOF):
        return self.store.create(key, SUBJECT, concurrency_keys=KEYS, proof=proof,
                                 recovery=recovery)

    def test_the_plan_is_stored_and_pinned_on_the_created_event(self):
        created = self.create()
        document = self.state_doc(created.transaction_id)
        self.assertEqual(document["schema"], "transaction-state/v5")
        plan = document["recovery_plan"]
        self.assertEqual(plan, materialize_recovery(bound(), created.transaction_id))
        first = document["events"][0]
        self.assertEqual((first["recovery_plan_digest"], first["recovers"]),
                         (telemetry_digest(plan), None))
        self.assertEqual(dict(created.recovery), {
            "plan_digest": telemetry_digest(plan), "recovers": None,
            "effect_snapshot": None, "selected": [], "children": []})
        self.assertEqual(created.recovery_plan["units"][0]["name"], "build")
        with self.assertRaises(TypeError):
            created.recovery_plan["schema"] = "x"

    def test_recovery_is_required(self):
        with self.assertRaises(TypeError):
            self.store.create("k", SUBJECT, concurrency_keys=KEYS, proof=PROOF)

    def test_a_rejected_declaration_leaves_the_root_untouched(self):
        for declaration in (with_unit(0, operation="promote"),
                            {**RECOVERY, "units": RECOVERY["units"][:2]}):
            with self.subTest(declaration=declaration):
                self.assertRefusedUnchanged(RecoveryPlanRejected,
                                            lambda: self.create(recovery=declaration))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_recovery_compiles_before_proof(self):
        with self.assertRaises(RecoveryPlanRejected):
            self.create(recovery=with_unit(0, operation="promote"), proof={"units": "bad"})

    def test_a_same_key_create_with_another_recovery_declaration_conflicts(self):
        created = self.create()
        before = self.files()
        other = with_unit(0, edges=[edge("compensate", "build", "a different residue")])
        with self.assertRaises(CreationConflict) as caught:
            self.create(recovery=other)
        self.assertIn("recovery plan", str(caught.exception))
        self.assertEqual(self.files(), before)
        self.assertEqual(self.create().transaction_id, created.transaction_id)

    def test_a_hand_edited_plan_digest_or_backlink_is_state_invalid(self):
        transaction_id = self.create().transaction_id
        document = self.state_doc(transaction_id)
        cases = (
            (lambda d: d["recovery_plan"]["units"][0].update(action_id="act_" + "0" * 32),
             "recovery_plan"),
            (lambda d: d["recovery_plan"]["units"][0]["edges"][0].update(residue="none"),
             "recovery_plan_digest"),
            (lambda d: d["events"][0].update(recovery_plan_digest="sha256:" + "0" * 64),
             "recovery_plan_digest"),
            (lambda d: d["events"][0].update(recovers=transaction_id), "recovers"),
            (lambda d: d["events"][0].update(recovers="not-an-id"), "recovers"),
            (lambda d: d.update(schema="transaction-state/v4"), "transaction-state/v4"))
        for edit, fragment in cases:
            with self.subTest(fragment=fragment):
                edited = copy.deepcopy(document)
                edit(edited)
                self.assertRuleRefuses(transaction_id, edited, fragment)
```

  Add this helper beside `bound` (import `ProofPlanRejected` from `transaction_core`):

```python
def inert_recovery(proof):
    """Every unit of a compilable `proof` as a `manual_only` recovery unit, with no anchor
    and no edge; empty when `proof` is itself rejected, so its own rejection still wins."""
    try:
        compile_proof(proof)
    except ProofPlanRejected:
        return EMPTY_RECOVERY
    return {"effects": {"inert": {"operations": ["make"]}},
            "units": [{"name": unit["name"], "parameters": unit["parameters"],
                       "effect": "inert", "operation": "make", "posture": "manual_only",
                       "anchor": None, "compatibility": None, "edges": []}
                      for unit in proof["units"]]}
```

  Also change the existing test files as the invariants say (a mechanical sweep; nothing
  else changes). In `tests/test_transaction_core_sweep.py`, import `transaction_recovery`
  and add it to `NEUTRAL_MODULES`. In the sweep support, add:

```python
def recovery_declaration(profile, registry):
    """The recovery declaration a shape's profile implies (#208, spec "Sweep fixture")."""
    activation = [] if profile["activation"] == "none" else profile["activation"]
    entries = profile["recovery"]["units"]
    effects = {alias: {"operations": sorted(mode for mode, support
                                            in registry[binding["adapter"]].modes.items()
                                            if support == "supported")}
               for alias, binding in profile["bindings"].items() if not alias.startswith("_")}
    units = []
    for node in [*profile["publication"], *activation]:
        entry = entries[node["id"]]
        anchor = entry.get("anchor")
        restorable = entry["posture"] == "restorable"
        units.append({
            "name": node["id"],
            "parameters": {"mode": node["mode"], "expected_subject": node["expected_subject"]},
            "effect": node["binding"], "operation": node["mode"], "posture": entry["posture"],
            "anchor": ({"predicate": "rollback_anchor",
                        "parameters": {"expected_subject": anchor}} if restorable else None),
            "compatibility": ({"predicate": "compatibility",
                               "parameters": {"expected_subject": anchor}}
                              if restorable else None),
            "edges": [{"action": e["action"], "operation": e["op"],
                       "parameters": {"mode": e["op"], "unit": node["id"],
                                      "expected_subject": anchor or {}},
                       "residue": e.get("residue")} for e in entry.get("edges", [])]})
    return {"effects": effects, "units": units}


def shape_recovery(shape):
    """The recovery declaration `drive` passes for `shape`."""
    _, profile, registry = SHAPES[shape](World())
    return recovery_declaration(profile, registry)
```

  `drive` passes `recovery=recovery_declaration(profile, registry)` to `create`. In
  `tests/test_transaction_core_sweep.py`, import `shape_recovery`. Pass
  `recovery=shape_recovery(shape)` in `test_every_shape_declares_a_feasible_plan_whose_units_are_its_nodes`
  and add `self.assertEqual(sorted(u["name"] for u in created.recovery_plan["units"]),
  declared_nodes(shape))` there. Pass `recovery=shape_recovery("library")` in
  `test_recreating_a_driven_cell_returns_its_transaction`.

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_recovery_plan.py 2>&1 | tail -3`.
  Expected: FAIL or ERROR in `CreationTest` (`create` takes no `recovery`).

- [ ] **Step 3: Implement** the invariants. `transaction_recovery.py` starts with a module
  docstring saying what it holds now: the derived `recovery` view. Later tasks extend that
  docstring. Thread the recovery plan through `_create_locked` beside the proof plan.
  Update the `create` docstring and the `transaction_history` module docstring from the
  resulting code.

- [ ] **Step 4: Verify.**
  Run the slice unit command with `tests/test_transaction_recovery_plan.py`. Expected: `OK`.

```bash
if grep -rn "transaction-state/v4" tests/test_transaction_core.py tests/test_transaction_invocation.py tests/test_transaction_plan.py; then exit 1; fi
grep -q 'SCHEMA = "transaction-state/v5"' python/agent_tools/transaction_history.py || exit 1
```

  Run: `git add -A python tests && just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.** Stage exactly this task's **Files**, then:

```bash
git commit -m "feat(transaction-core): store the recovery plan under transaction-state/v5 (#208)"
```

- [ ] **Step 6: Check the review budget** with `FILES="python/agent_tools/transaction_recovery.py python/agent_tools/transaction_history.py python/agent_tools/transaction_core.py tests/test_transaction_recovery_plan.py tests/test_transaction_core.py tests/test_transaction_custody.py tests/transaction_core_sweep_support.py"`.
  Expected: exit 0.

Decisions: per D2, D5, D6, D11, D12, D16.
