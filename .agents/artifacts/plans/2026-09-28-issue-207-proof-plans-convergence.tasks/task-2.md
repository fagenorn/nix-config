# Task 2: Schema v4: the stored plan, `create(proof=)` and plan validation

**Files:**
- Modify: `python/agent_tools/transaction_history.py`
- Modify: `python/agent_tools/transaction_core.py`
- Modify: `tests/test_transaction_plan.py` (append one class)
- Modify: `tests/test_transaction_core.py`, `tests/test_transaction_custody.py`,
  `tests/test_transaction_invocation.py` (the required `proof` argument and schema strings)
- Modify: `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py`
  (pass the empty declaration)

**Interfaces:**
- Consumes (Task 1): `compile_proof(declaration, *, where) -> dict`,
  `materialize_plan(compiled, transaction_id) -> dict`, `plan_violation(plan,
  transaction_id) -> str | None`, `ProofPlanRejected` (with `.reason`), and
  `agent_tools.canonical.telemetry_digest`.
- Produces:
  - `transaction_history.SCHEMA = "transaction-state/v4"`. The state key set gains
    `proof_plan`, and the `created` event's closed keys become
    `{"seq", "type", "at", "proof_plan_digest"}`.
  - `Transaction.proof_plan: Mapping[str, Any]`, a `MappingProxyType` over a deep copy of
    the stored plan, added as the dataclass's last field (after `actions`).
  - `TransactionStore.create(creation_key: str, subject: dict, *, concurrency_keys:
    Collection[str], proof: dict) -> Transaction`, where `proof` is keyword-only with no
    default (per D2).

**Invariants:**
- `create` refuses, before `creation.lock` is opened and so before any file exists,
  a declaration `compile_proof` rejects. It uses `where=f"{root}: creation_key
  {creation_key!r}"`, so the message names the key. The key, subject and key-set checks
  still come first (`StateInvalid`).
- A new transaction's `state.json` holds `proof_plan = materialize_plan(compiled, id)` and
  a `created` event carrying `proof_plan_digest = telemetry_digest(proof_plan)` (per D3).
- A repeated `create` under an existing key materializes the new declaration under the
  existing id. A digest that differs from the stored `created.proof_plan_digest` is
  `CreationConflict`, with "proof plan" in its differing-fields list (`subject`,
  `concurrency key set`, `proof plan`, joined by " and "), and nothing written. An equal
  digest returns the snapshot.
- `validate_state` checks, in order: the schema string (a v3 document fails naming
  `transaction-state/v3`, per D13), the closed key set, the id, then `proof_plan` through
  `plan_violation` (per D24), then the `created` event's closed shape, with
  `proof_plan_digest == telemetry_digest(document["proof_plan"])`. Each failure is
  `StateInvalid` naming the transaction id and the rule.
- No lifecycle behavior changes in this task: every existing test passes once it supplies
  `proof=EMPTY_PROOF` and expects v4.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_transaction_plan.py`:
  add `import json, tempfile` and `from pathlib import Path` to the imports, add
  `CreationConflict, StateInvalid, TransactionStore` to the `transaction_core` import, and
  add `from agent_tools.canonical import telemetry_digest`. Then append:

```python
class CreationTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = TransactionStore(self.root)

    def create(self, proof, key="k"):
        return self.store.create(key, {"s": 1}, concurrency_keys=["key:a"], proof=proof)

    def tree(self):
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))

    def files(self):
        return {p: p.read_bytes() for p in sorted(self.root.rglob("*")) if p.is_file()}

    def state(self, transaction_id):
        return self.root / transaction_id / "state.json"

    def test_the_plan_is_stored_once_with_its_digest_pinned_in_created(self):
        created = self.create(FULL)
        document = json.loads(self.state(created.transaction_id).read_text())
        self.assertEqual(document["schema"], "transaction-state/v4")
        self.assertEqual(document["proof_plan"],
                         materialize_plan(compile_proof(FULL), created.transaction_id))
        first = document["events"][0]
        self.assertEqual(set(first), {"seq", "type", "at", "proof_plan_digest"})
        self.assertEqual(first["proof_plan_digest"], telemetry_digest(document["proof_plan"]))
        self.assertEqual(dict(created.proof_plan), document["proof_plan"])
        self.assertEqual(TransactionStore(self.root).load(created.transaction_id), created)

    def test_proof_has_no_default(self):
        with self.assertRaises(TypeError):
            self.store.create("k", {"s": 1}, concurrency_keys=["key:a"])
        self.assertEqual(self.tree(), [])

    def test_every_rejection_writes_nothing(self):
        for reason, cases in REJECTIONS.items():
            for index, case in enumerate(cases):
                with self.subTest(reason=reason, case=index):
                    with self.assertRaises(ProofPlanRejected) as caught:
                        self.create(case)
                    self.assertEqual(caught.exception.reason, reason)
                    self.assertIn("'k'", str(caught.exception))
                    self.assertEqual(self.tree(), [])

    def test_a_same_key_create_with_another_plan_is_a_conflict(self):
        transaction_id = self.create(FULL).transaction_id
        self.assertEqual(self.create(copy.deepcopy(FULL)).transaction_id, transaction_id)
        before = self.files()
        for other in (EMPTY_PROOF, edit(convergence_window_ms=1_700_000)):
            with self.subTest(other=other), self.assertRaises(CreationConflict) as caught:
                self.create(other)
            self.assertIn("proof plan", str(caught.exception))
            self.assertEqual(self.files(), before)

    def test_hand_edited_plans_and_digests_are_state_invalid(self):
        transaction_id = self.create(FULL).transaction_id
        pristine = json.loads(self.state(transaction_id).read_text())

        def redigest(document):
            document["events"][0]["proof_plan_digest"] = telemetry_digest(
                document["proof_plan"])

        def cohort(document):
            document["proof_plan"]["cohort"]["makespan_ms"] = 1
            redigest(document)

        def unit_parameters(document):
            document["proof_plan"]["units"][0]["parameters"] = {"n": "other"}
            redigest(document)

        def extra_key(document):
            document["proof_plan"]["extra"] = 1
            redigest(document)

        def dropped_floor(document):
            del document["proof_plan"]["obligations"][0]
            redigest(document)

        def digest(document):
            document["events"][0]["proof_plan_digest"] = "sha256:" + "0" * 64

        def missing(document):
            del document["proof_plan"]

        def version(document):
            document["schema"] = "transaction-state/v3"

        for name, change in (("cohort", cohort), ("unit parameters", unit_parameters),
                             ("extra key", extra_key), ("dropped floor", dropped_floor),
                             ("digest", digest), ("missing", missing), ("v3", version)):
            with self.subTest(edit=name):
                document = copy.deepcopy(pristine)
                change(document)
                self.state(transaction_id).write_text(json.dumps(
                    document, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                    allow_nan=False) + "\n")
                with self.assertRaises(StateInvalid) as caught:
                    TransactionStore(self.root).load(transaction_id)
                self.assertIn(transaction_id, str(caught.exception))
                if name == "v3":
                    self.assertIn("transaction-state/v3", str(caught.exception))
```

  Update the earlier tests. The edits below are exactly what the schema string and the
  required argument demand:
  - `tests/test_transaction_core.py`: define `EMPTY_PROOF = {"units": [], "obligations":
    [], "collectors": {}}` beside `KEYS`, and pass `proof=EMPTY_PROOF` to every `.create(`
    call. In `test_create_mints_a_rel_uuid7_id_and_writes_state_and_index`, add
    `"proof_plan"` to the expected key set, expect `transaction-state/v4`, and expect the
    event keys `{"seq", "type", "at", "proof_plan_digest"}`.
  - `tests/test_transaction_custody.py`: define the same `EMPTY_PROOF`, and pass it in
    `CustodyCase.new` and in the file's other `.create(` call.
  - `tests/test_transaction_invocation.py`: in `SchemaTest`, rename the test to
    `test_new_state_is_v4_and_a_v3_document_fails_closed_naming_its_version`, expect
    `transaction-state/v4`, and refuse a `transaction-state/v3` document naming
    `transaction-state/v3`.
  - `tests/transaction_core_sweep_support.py`: pass
    `proof={"units": [], "obligations": [], "collectors": {}}` to `store.create`.
    `tests/test_transaction_core_sweep.py`: pass the same literal in
    `test_recreating_a_driven_cell_returns_its_transaction`. Task 6 replaces both.

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_plan.py 2>&1 | tail -3`.
  Expected: FAIL, `TypeError: ... unexpected keyword argument 'proof'`.

- [ ] **Step 3: Implement.**
  1. History: import `plan_violation` from `transaction_plan` and `telemetry_digest` from
     `agent_tools.canonical`. Set `SCHEMA` to v4, add `proof_plan` to `_STATE_KEYS`, and
     make `_CREATED_KEYS` `{"seq", "type", "at", "proof_plan_digest"}`. In
     `validate_state`, after the transaction-id check, refuse
     `f"proof_plan {violation}"` when `plan_violation(document["proof_plan"],
     transaction_id)` returns a rule. After event 1's closed-shape checks, refuse `"event 1
     proof_plan_digest is not the digest of proof_plan"` when the digest differs. Add
     `proof_plan` to `Transaction` and fill it in `snapshot`. Rewrite the module docstring
     from the resulting code: it validates `transaction-state/v4`, and the stored plan must
     be the materialization of its own declaration.
  2. Core: `create` gains `proof`. It calls `compile_proof(proof, where=...)` right after
     `_require_creatable` and before `open_lock`, and passes the compiled declaration to
     `_create_locked`. That method materializes the plan once the id is known. For an
     existing document it compares `telemetry_digest(plan)` with the stored
     `created.proof_plan_digest`, adding `"proof plan"` to `differs`. For a new one it
     writes `proof_plan` and the digest-bearing `created` event. Update the `create`
     docstring from the resulting code: the proof declaration is compiled before any lock,
     and a same-key create with a different plan digest is a conflict. Replace "v3" in
     `_require_creatable`'s docstring with "v4".

- [ ] **Step 4: Verify.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_plan.py tests/test_transaction_core.py tests/test_transaction_custody.py tests/test_transaction_invocation.py tests/test_transaction_core_sweep.py 2>&1 | tail -3`.
  Expected: `OK`.

```bash
if grep -q 'transaction-state/v3"' python/agent_tools/transaction_history.py; then exit 1; fi
grep -q 'proof_plan_digest' python/agent_tools/transaction_core.py || exit 1
```

  Run: `just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.**

```bash
git add python/agent_tools/transaction_history.py python/agent_tools/transaction_core.py \
  tests/test_transaction_plan.py tests/test_transaction_core.py \
  tests/test_transaction_custody.py tests/test_transaction_invocation.py \
  tests/transaction_core_sweep_support.py tests/test_transaction_core_sweep.py
git commit -m "feat(transaction-core): store an immutable proof plan per transaction (#207)"
```

Decisions: per D2, D3, D13, D23, D24.
