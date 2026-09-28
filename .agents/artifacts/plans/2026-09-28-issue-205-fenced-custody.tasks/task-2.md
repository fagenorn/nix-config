# Task 2: Schema v2 — immutable concurrency keys, custody projection, v1 refused

**Files:**
- Modify: `python/agent_tools/transaction_core.py`
- Modify: `tests/test_transaction_core.py`
- Modify: `tests/transaction_core_sweep_support.py` (one `create` call)
- Modify: `tests/test_transaction_core_sweep.py` (`test_recreating_a_driven_cell_…`)

**Interfaces:**
- Consumes (Task 1): `TransactionStore(root, *, clock=None)`, `_format_at`, `_now`,
  `transaction_storage` primitives, `_validate_state(document, transaction_id, root)`,
  `_require_creatable(root, creation_key, subject)`, `_snapshot(document)`.
- Produces: `SCHEMA = "transaction-state/v2"`;
  `TransactionStore.create(self, creation_key: str, subject: dict, *, concurrency_keys: Collection[str]) -> Transaction`;
  `Transaction` gains, after `events`, `concurrency_keys: tuple[str, ...]` and
  `custody: "Custody | None"` (always `None` in this task; Task 3 defines `Custody` and
  fills it — declare the field with the annotation `Any` now and narrow it in Task 3).
  The closed state key set becomes `{schema, transaction_id, creation_key, subject,
  state, parked_from, revision, events, concurrency_keys, custody}`.

**Invariants:**
- `concurrency_keys` must be a `list`, `tuple`, `set` or `frozenset` (never a `str`),
  non-empty, of distinct non-empty UTF-8-encodable `str`; otherwise `StateInvalid` raised
  before any lock and with nothing created. Stored as `sorted(...)` (D4).
- A repeated `create` with the same creation key and a different subject **or** a
  different key set (compared sorted) raises `CreationConflict` and writes nothing (D4).
- The validator checks `schema` before the key set, so a v1 document is refused with a
  `StateInvalid` whose message contains `transaction-state/v1` (D9). No migration code.
- The validator requires `concurrency_keys` sorted, distinct, non-empty strings, and
  `custody` equal to the folded custody — `None` until Task 3 adds custody events.
- `revision` still equals the event count.

- [ ] **Step 1: Write the failing tests** — in `tests/test_transaction_core.py`:

1. Add `KEYS = ["project:demo", "target:demo"]` beside `SUBJECT`, and add
   `concurrency_keys=KEYS` to every existing `create(...)` call in the file (the
   `test_arguments_that_cannot_form…` loop included).
2. In `CreateTest.test_create_mints…` change the expected key set to include
   `"concurrency_keys", "custody"`, the schema to `"transaction-state/v2"`, and add
   `self.assertEqual((document["concurrency_keys"], document["custody"]), (KEYS, None))`
   and `self.assertEqual(created.concurrency_keys, tuple(KEYS))`.
3. In `LoadTest.test_documents_violating…` change the `"wrong schema"` case value to
   `"transaction-state/v3"` and add these cases to `cases`:

```python
            "unsorted keys": lambda d: {**d, "concurrency_keys": KEYS[::-1]},
            "duplicate keys": lambda d: {**d, "concurrency_keys": [KEYS[0], KEYS[0]]},
            "empty keys": lambda d: {**d, "concurrency_keys": []},
            "non-string key": lambda d: {**d, "concurrency_keys": [1]},
            "forged custody": lambda d: {**d, "custody": {"executor_id": "x"}},
```

4. Append:

```python
class ConcurrencyKeysTest(StoreCase):
    def test_keys_are_stored_sorted_and_deduplication_compares_them(self):
        created = self.store.create("k", SUBJECT, concurrency_keys={"b:2", "a:1"})
        self.assertEqual(created.concurrency_keys, ("a:1", "b:2"))
        again = self.store.create("k", SUBJECT, concurrency_keys=("b:2", "a:1"))
        self.assertEqual(again.transaction_id, created.transaction_id)
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        for keys in (["a:1"], ["a:1", "b:2", "c:3"]):
            with self.subTest(keys=keys), self.assertRaises(CreationConflict):
                self.store.create("k", SUBJECT, concurrency_keys=keys)
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()},
                         before)

    def test_malformed_key_sets_are_refused_before_anything_exists(self):
        for keys in ((), [], "ab", ["a", "a"], [""], [1], ["\ud800"], None):
            with self.subTest(keys=keys), self.assertRaises(StateInvalid):
                self.store.create("k", SUBJECT, concurrency_keys=keys)
        self.assertEqual(self.tree(), [])

    def test_keys_are_required(self):
        with self.assertRaises(TypeError):
            self.store.create("k", SUBJECT)

    def test_a_v1_document_fails_closed_naming_its_version(self):
        transaction_id = self.store.create("k", SUBJECT, concurrency_keys=KEYS).transaction_id
        document = self.document(transaction_id)
        v1 = {key: value for key, value in document.items()
              if key not in ("concurrency_keys", "custody")}
        self.write(transaction_id, {**v1, "schema": "transaction-state/v1"})
        with self.assertRaises(StateInvalid) as caught:
            self.store.load(transaction_id)
        self.assertIn("transaction-state/v1", str(caught.exception))
        self.assertIn(transaction_id, str(caught.exception))
```

5. `tests/transaction_core_sweep_support.py`: `store.create(f"{shape}:{scenario}", subject,
   concurrency_keys=profile["target"]["concurrency_keys"])`.
   `tests/test_transaction_core_sweep.py`, `test_recreating_a_driven_cell…`: pass
   `concurrency_keys=list(store.load(first).concurrency_keys)` to its `create`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core.py 2>&1 | tail -3`
Expected: FAIL — `TypeError: … unexpected keyword argument 'concurrency_keys'`.

- [ ] **Step 3: Write the minimal implementation**

1. `SCHEMA = "transaction-state/v2"`; add the two keys to `_STATE_KEYS`.
2. `_require_creatable(root, creation_key, subject, concurrency_keys)` gains the key-set
   rules of the invariants, each refusal naming the root, the creation key and the rule.
3. `create(..., *, concurrency_keys)`: validate, then `keys = sorted(concurrency_keys)`.
   New document adds `"concurrency_keys": keys, "custody": None`. On an existing
   document: `CreationConflict` when the subject digest differs **or**
   `document["concurrency_keys"] != keys`, message naming which differs.
4. `_validate_state`: after the `dict` check and before the key-set check, refuse
   `schema != SCHEMA` with `f"schema {document.get('schema')!r} is not {SCHEMA}"`. Add
   the `concurrency_keys` rule. Introduce a local fold variable `custody = None` beside
   `state, parked` and, after the loop, refuse unless `document["custody"] == custody`
   (compare with `type(...) is dict or is None` first so `False`/`0` never equal `None`).
   Task 3 extends this fold; keep the event loop a per-type dispatch so new types slot in.
5. `_snapshot` fills `concurrency_keys=tuple(document["concurrency_keys"])` and
   `custody=None`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core.py tests/test_transaction_core_sweep.py 2>&1 | tail -3`
Expected: `OK` (Task 1 count + 4 tests).

Run: `if grep -n 'transaction-state/v1' python/agent_tools/transaction_core.py; then exit 1; fi`
Expected: no output (no v1 constant or migration remains).

Run: `just agent-workflow-tests 2>&1 | tail -3` — Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/transaction_core.py tests/test_transaction_core.py \
  tests/transaction_core_sweep_support.py tests/test_transaction_core_sweep.py
git commit -m "feat(transaction-core): add immutable concurrency keys under state v2 (#205)"
```
