# Task 1: Move storage primitives and errors; inject the lease-authority clock

**Files:**
- Create: `python/agent_tools/transaction_storage.py`
- Modify: `python/agent_tools/transaction_core.py`
- Modify: `tests/test_transaction_core.py` (append `ClockTest`, `StorageModuleTest` before
  the `if __name__ == "__main__":` block)
- Modify: `tests/test_transaction_core_sweep.py` (`NeutralityTest` covers both modules)

**Interfaces:**
- Consumes (base commit, `transaction_core`): `_serialize`, `_finite_float`,
  `_strict_loads`, `_lstat_mode`, `_read_json`, `_fsync_directory`, `_atomic_write`,
  `_require_directory`, `_open_lock`, the six error classes, and the lock block inside
  `TransactionStore.advance`.
- Produces (`agent_tools.transaction_storage`, public names, bodies moved verbatim):
  `TransactionError`, `StateInvalid`, `TransactionBusy`, `TransitionRefused`,
  `CreationConflict`, `UnknownTransaction`; `serialize(document: dict) -> str`,
  `strict_loads(text: str) -> Any`, `lstat_mode(path: Path) -> int | None`,
  `read_json(path: Path) -> Any`, `fsync_directory(directory: Path) -> None`,
  `atomic_write(directory: Path, path: Path, document: dict) -> None`,
  `require_directory(path: Path, missing_ok: bool) -> bool`,
  `open_lock(path: Path) -> int` (creating, non-blocking; `TransactionBusy` on contention).
  `_finite_float` stays private to storage.
- Produces (`agent_tools.transaction_core`): re-exports the six error classes (same class
  objects); `TransactionStore(root: Path, *, clock: Callable[[], int] | None = None)`;
  private `self._now() -> int`, `_format_at(ms: int) -> str`, `_parse_at(at: str) -> int`
  (exact inverse of `_format_at`); private context manager
  `self._transaction_locked(transaction_id)` — the existing no-`O_CREAT` lock block of
  `advance`, yielding with the transaction lock held. Tasks 3–6 call these three.

**Invariants:**
- `transaction_core`'s import surface is a superset of the base commit's; every existing
  test in `tests/test_transaction_core.py` and the sweep passes unmodified (D1).
- Every event `at` equals `_format_at(clock())` read once per write; `clock=None` means
  `time.time_ns() // 1_000_000` (D3). Ids still come from the wall clock (D31).
- A clock reading that is not a non-negative `int` (a `bool` counts as not an int) raises
  `TransactionError` naming the store root, before any write of that call.
- `_parse_at(_format_at(ms)) == ms` for every `ms >= 0`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_transaction_core.py`
  (add `from agent_tools import transaction_core, transaction_storage` to the imports):

```python
T0 = 1_800_000_000_000  # 2027-01-15T08:00:00.000Z


class FakeClock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


class ClockTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_event_times_come_from_the_injected_clock_and_ids_from_the_wall(self):
        clock = FakeClock()
        store = TransactionStore(self.root, clock=clock)
        before = time.time_ns() // 1_000_000
        created = store.create("k", SUBJECT)
        after = time.time_ns() // 1_000_000
        self.assertEqual(created.events[0]["at"], "2027-01-15T08:00:00.000Z")
        millis = int(created.transaction_id[4:].replace("-", "")[:12], 16)
        self.assertTrue(before <= millis <= after)
        clock.now = T0 + 1234
        moved = store.advance(created.transaction_id, "awaiting_verification", reason="r")
        self.assertEqual(moved.events[-1]["at"], "2027-01-15T08:00:01.234Z")

    def test_a_malformed_clock_reading_is_refused_before_any_state_exists(self):
        for reading in (1.5, True, -1, "0", None):
            with self.subTest(reading=reading), tempfile.TemporaryDirectory() as tmp:
                store = TransactionStore(Path(tmp), clock=lambda value=reading: value)
                with self.assertRaises(TransactionError) as caught:
                    store.create("k", SUBJECT)
                self.assertIn(tmp, str(caught.exception))
                self.assertEqual(list(Path(tmp).rglob("state.json")), [])

    def test_the_default_clock_is_the_wall_clock(self):
        before = time.time_ns() // 1_000_000
        at = TransactionStore(self.root).create("k", SUBJECT).events[0]["at"]
        after = time.time_ns() // 1_000_000
        stamp = datetime.datetime.strptime(at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=datetime.timezone.utc)
        self.assertTrue(before <= int(stamp.timestamp() * 1000 + 0.5) <= after)


class StorageModuleTest(unittest.TestCase):
    def test_the_core_re_exports_the_storage_error_hierarchy(self):
        for name in ("TransactionError", "StateInvalid", "TransactionBusy",
                     "TransitionRefused", "CreationConflict", "UnknownTransaction"):
            with self.subTest(name=name):
                self.assertIs(getattr(transaction_core, name),
                              getattr(transaction_storage, name))
```

Add `import datetime` to the test imports. In `tests/test_transaction_core_sweep.py`
replace `NeutralityTest.setUp` and the first test with:

```python
from agent_tools import transaction_storage

NEUTRAL_MODULES = (transaction_core, transaction_storage)


class NeutralityTest(unittest.TestCase):
    def setUp(self):
        self.source = inspect.getsource(transaction_core)

    def test_the_shipped_modules_name_no_project_provider_or_provider_verb(self):
        for module in NEUTRAL_MODULES:
            with self.subTest(module=module.__name__):
                self.assertEqual(neutrality_findings(inspect.getsource(module)), [])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core.py 2>&1 | tail -3`
Expected: FAIL — `ImportError: cannot import name 'transaction_storage'`.

- [ ] **Step 3: Write the minimal implementation**

1. Create `transaction_storage.py` with a module docstring ("Durable-file primitives and
   the refusal hierarchy shared by the transaction modules (#205 D1)."), and move the
   listed functions and error classes into it verbatim except for dropping the leading
   underscore of each moved function. `transaction_core` imports them and binds the six
   error classes at module level so `from agent_tools.transaction_core import StateInvalid`
   keeps working; delete the moved bodies from `transaction_core` (no second copy).
2. `TransactionStore.__init__(self, root, *, clock=None)`: keep the root check; store
   `self._clock = clock if clock is not None else lambda: time.time_ns() // 1_000_000`.
   A non-callable `clock` raises `TransactionError` naming the root.
3. `_now()`: read the clock once; refuse per the invariant; return the int.
4. `_format_at(ms)`: `datetime.datetime.fromtimestamp(ms // 1000, tz=utc)` formatted
   `%Y-%m-%dT%H:%M:%S` + `f".{ms % 1000:03d}Z"`. `_parse_at(at)`: `strptime` the seconds
   part, `calendar.timegm`-style integer seconds `* 1000 + int(millis)`. Delete
   `_timestamp`; `create` and `advance` stamp `_format_at(self._now())`. In `create`,
   read the clock before taking `creation.lock`, so a malformed reading leaves no state.
5. Extract `advance`'s lock block (lstat check, `O_RDWR | O_NOFOLLOW` open, non-blocking
   `flock`, `TransactionBusy`, close in `finally`) into
   `@contextlib.contextmanager def _transaction_locked(self, transaction_id)` and use it
   in `advance`. Messages stay as they are.
6. Update the module docstring: it now names the injected clock and the storage module.
   Docstrings describe only behavior that exists after this task.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core.py tests/test_transaction_core_sweep.py 2>&1 | tail -3`
Expected: `OK` (base count + 4 tests).

Run: `if grep -nE '^def _(serialize|strict_loads|read_json|atomic_write|open_lock)\b' python/agent_tools/transaction_core.py; then exit 1; fi`
Expected: no output, exit 0 (the moved bodies are gone).

Run: `just agent-workflow-tests 2>&1 | tail -3` — Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/transaction_storage.py python/agent_tools/transaction_core.py \
  tests/test_transaction_core.py tests/test_transaction_core_sweep.py
git commit -m "refactor(transaction-core): move storage primitives and inject the clock (#205)"
```
