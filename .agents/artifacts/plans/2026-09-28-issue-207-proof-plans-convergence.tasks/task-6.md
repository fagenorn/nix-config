# Task 6: The sweep executor drives proof through the core

**Files:**
- Modify: `tests/transaction_core_sweep_support.py`
- Modify: `tests/test_transaction_core_sweep.py`

**Interfaces:**
- Consumes (Tasks 1–5): `TransactionStore.create(..., proof=)`, `collect_obligation`,
  `start_cohort`, `settle_proof`, `ProofRefused.reason`, and the `Transaction.proof_plan`
  fields (`obligations[*].obligation_id`, `collector` and `required`;
  `cohort.members`), plus `Transaction.proof`. From the fixtures, it uses
  `SimAdapter.inspect(op, env)` (whose predicate hooks return `{outcome, reason,
  observed_subject, payload_ref}`) and `SimAdapter.predicates` (predicate →
  `"supported"` or `"unsupported: …"`).
- Produces (fixtures only, per D14, D29), in `tests/transaction_core_sweep_support.py`:
  - `proof_declaration(profile: dict, registry: dict) -> dict`;
  - `shape_declaration(shape: str) -> dict`, the declaration `drive` passes for that
    shape, built from `SHAPES[shape](World())`;
  - `class _Observer` with `observe(request)`.

**Invariants:**
- `proof_declaration` (per D14):
  - `units`: every publication node, then every activation node, as
    `{"name": node["id"], "parameters": {"mode": node["mode"], "expected_subject":
    node["expected_subject"]}, "phase": "publication" | "activation", "collector":
    node["binding"]}`. That is exactly the `name`/`parameters` pair `action(node)` already
    passes to the core, so the unit's action id is the invoked action's id.
  - `obligations`: each `profile["proof"]` entry as `{"id", "semantic", "form":
    o["temporal"], "predicate", "collector": o["binding"], "required", "deps": list(o.get(
    "deps", [])), "parameters": {"expected_subject": o["expected_subject"]}}`, plus
    `"freshness_ms": o["freshness_seconds"] * 1000` exactly when the form is `snapshot`.
  - `collectors`: one per non-`_` binding, `{"basis": "deterministic", "predicates":
    sorted(p for p, s in adapter.predicates.items() if s == "supported"),
    "max_collection_latency_ms": 30_000}`, with no concurrency key.
- `_Observer.observe(request)` (per D29):
  - For a derived obligation (id starting `derived:`, class = the second `:` field), the
    subject is `request["parameters"]["parameters"]["expected_subject"]`; otherwise it is
    `request["parameters"]["expected_subject"]`.
  - It calls `adapter.inspect(request["predicate"], {"expected_subject": subject})`. An
    outcome outside `satisfied | unsatisfied | unknown` counts as `unknown`.
  - The reason is the outcome word for declared obligations and for `satisfied`. Otherwise
    it is `subject_mismatch` (unsatisfied), or `store_unreachable` /
    `identity_unobservable` (unknown, for `published_artifact_identity` /
    `running_subject_identity`).
  - It returns `{"outcome", "reason", "reference": seen["payload_ref"]}`.
- The proving stage replaces the old `prove`, and no adapter predicate is called outside
  an observer:
  1. **First pass**, in plan order. It skips an obligation whose latest evidence entry
     (by the `evidence_id` prefix before its last `@`) is admissible. Otherwise it calls
     `collect_obligation` with the obligation's collector's observer. A `ProofRefused` whose
     reason is `unsupported_obligation` or `dependency_not_accepted` is skipped; any other
     refusal parks with its reason.
     - In `lease_renewal`, `renew()` (tick 301 s, renew) runs before the pass and again
       once the number of collected required obligations reaches half the required count
       (integer division).
     - In `lease_lapse`'s first pass, the world ticks 601 s just before collecting the
       plan's last required obligation, so that collection raises `StaleCustody`. The
       existing handler then reaps, acquires, advances to `proving` ("resumed after
       reacquisition") and repeats the first pass.
  2. The `lease_renewal` term-3 check runs here, before any cohort.
  3. **Converge** loop:
     - `start_cohort`. A `ProofRefused` of `proof_incomplete` or `convergence_exhausted`
       goes to settlement; any other refusal parks.
     - On a start, collect every `cohort.members` id in order through its observer, calling
       `store.renew(custody)` after each collection.
     - `settle_proof`. A `ProofRefused` parks with its reason. The loop repeats while the
       returned state is `proving`.

  When the loop ends, the transaction is `succeeded` or parked by `settle_proof`. The
  executor never advances it further.
- The executor no longer calls `record_evidence` or `open_interval`.
- Every earlier row keeps its final state, path, custody events and attempts. The one
  change is that library `lease_lapse` voids `∅` instead of `{snapshot}` (per D15).

- [ ] **Step 1: Write the failing tests.** In `tests/test_transaction_core_sweep.py`:
  - Import `shape_declaration` from `.transaction_core_sweep_support`.
  - Change the library `lease_lapse` row's voided set to `frozenset()`.
  - Pass `proof=shape_declaration("library")` in
    `test_recreating_a_driven_cell_returns_its_transaction`.
  - Append inside `test_every_cell_lands_where_the_table_says`'s cell block:

```python
                types = [e["type"] for e in persisted.events]
                self.assertNotIn("evidence_recorded", types)
                self.assertEqual((types.count("proof_cohort_started"),
                                  types.count("proof_sealed")), (1, 1))
                seal = next(e for e in persisted.events if e["type"] == "proof_sealed")
                self.assertEqual(persisted.proof["proof_cutoff_at"], seal["at"])
                required = [o for o in persisted.proof["obligations"] if o["required"]]
                self.assertTrue(required)
                self.assertEqual({o["latest_outcome"] for o in required}, {"satisfied"})
                self.assertEqual(
                    sorted(u["name"] for u in persisted.proof_plan["units"]),
                    declared_nodes(shape))
```

  Add to `SweepTableTest`:

```python
    def test_every_shape_declares_a_feasible_plan_whose_units_are_its_nodes(self):
        for shape in SHAPES:
            with self.subTest(shape=shape), tempfile.TemporaryDirectory() as tmp:
                created = TransactionStore(Path(tmp)).create(
                    "probe", {"s": shape}, concurrency_keys=["k"],
                    proof=shape_declaration(shape))
                plan = created.proof_plan
                self.assertEqual(sorted(u["name"] for u in plan["units"]),
                                 declared_nodes(shape))
                self.assertLessEqual(plan["cohort"]["makespan_ms"], 90_000)
```

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core_sweep.py 2>&1 | tail -3`.
  Expected: FAIL, `ImportError: cannot import name 'shape_declaration'`.

- [ ] **Step 3: Implement** the invariants in `tests/transaction_core_sweep_support.py`:
  - `drive` creates with `proof=proof_declaration(profile, registry)` and builds one
    `_Observer` per non-`_` binding.
  - Replace `prove` and the final `start_cohort`/`settle_proof` pair with the proving stage
    above.
  - Rewrite the module docstring from the implemented executor: it passes each shape's
    proof declaration, collects every obligation through the core, converges through
    cohorts, and lets `settle_proof` seal or park.

- [ ] **Step 4: Verify.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core_sweep.py 2>&1 | tail -3`.
  Expected: `OK`.

```bash
if grep -nE "record_evidence|open_interval|advance\(\"succeeded\"" tests/transaction_core_sweep_support.py; then exit 1; fi
```

  Run: `just agent-workflow-tests 2>&1 | tail -3`. Expected: `OK`.

- [ ] **Step 5: Commit.**

```bash
git add tests/transaction_core_sweep_support.py tests/test_transaction_core_sweep.py
git commit -m "test(transaction-core): drive the sweep's proof through the core (#207)"
```

Decisions: per D14, D15, D29.
