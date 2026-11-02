# Task 3: Issue 207 is delivered once per migration test class

This task implements spec § The attempt-migration fixture (D4, D9) and test seam 3 (D6). Today, `MigrationFixtures.delivered_207()` runs the whole #220 issue-207 delivery on every call: 10 calls in `MigrateOnWriteTest` and `MigrationAcceptanceTest`, each only to read the finished ledger. After this task, the first call in a concrete test class runs the driver. The method keeps the ledger as text and removes the driver's directories at once, and every call returns a fresh parse. The guard test fails before the change and passes after it (D11): at base every call delivers into a fresh temporary project, so two calls' ledgers name different roots and compare unequal. The scratch driver-run counter and a scratch mutation are this task's further falsifiable checks.

**Files:**
- Modify: `home/common/agent-skills/tests/test_attempt_migration.py`

**Interfaces:**
- Consumes (base): `DeliveredControlHarness` (`setUpClass()`, `deliver_through_remainder()`, `ledger`, the per-instance cleanups that remove the driver's root and HOME), imported from `.test_delivered_control`; `unittest.TestCase.addClassCleanup`.
- Produces: `MigrationFixtures.delivered_207(self) -> dict`, with the same name and return value: the issue-207 ledger's parsed state, a new object on every call. Also a module-level `_DELIVERED_207: dict[type, str]`, the ledger text keyed by the concrete test class (D9).

**Invariants:**
- The driver runs at most once per concrete test class per class run. A failed driver run caches nothing and still removes its directories, so the next call runs it again and fails in the same way, out loud (D4).
- Only an immutable string is shared. Every call returns `json.loads` of it, so mutating one result never reaches another (R3).
- The driver's root and HOME are removed before `delivered_207` returns. The parsed ledger names paths in that removed root, and no test reads them (D4).
- The class's entry is popped by a class cleanup on that class, never stored as a class attribute (D9).
- Every existing `test_*` body is unchanged (Coverage gate). `install_orchestrated`, `install_refusal_fixtures` and `install_all` are unchanged.

**Scratch driver-run counter.** Write this to `$SCRATCH/count-driver-runs.py` and never commit it (262 D6, D10). Run it from the worktree root. It prints `DRIVER_RUNS <n>` and exits non-zero when a test fails.

```python
"""Scratch only (262 D6): run test_attempt_migration and count #220 driver runs."""
import importlib, os, sys, unittest
sys.path.insert(0, os.getcwd())  # run from the tree root
harness = importlib.import_module("home.common.agent-skills.tests.test_delivered_control").DeliveredControlHarness
runs, deliver = [], harness.deliver_through_remainder
def counted(self, *args, **kwargs):
    runs.append(1)
    return deliver(self, *args, **kwargs)
harness.deliver_through_remainder = counted
program = unittest.main(module=None, exit=False, argv=["unittest", "home/common/agent-skills/tests/test_attempt_migration.py"])
print(f"DRIVER_RUNS {len(runs)}", file=sys.stderr)
sys.exit(0 if program.result.wasSuccessful() else 1)
```

Counter command (timeout 1800 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 "$SCRATCH/count-driver-runs.py" 2>&1 | grep -E "^Ran |^OK|^FAILED|^DRIVER_RUNS"'`

- [ ] **Step 1: Write the guard test**

In `class MigrateOnWriteTest(MigrationFixtures, unittest.TestCase):`, insert this method directly before `def test_a_schema_8_ledger_whose_binding_breaks_is_refused(self):`:

```python
    def test_each_delivered_207_call_is_the_callers_own_copy(self):
        """Issue 500 D4, D6: a mutation of one call's state never reaches the next call's."""
        first = self.delivered_207()
        self.assertTrue(first["issues"]["207"]["attempts"])
        expected = json.dumps(first, sort_keys=True)
        second = self.delivered_207()
        second["mutated"] = True
        second["issues"]["207"]["attempts"][0]["mutated"] = True
        second["issues"]["207"]["attempts"].append({"mutated": True})
        second["issues"]["207"]["delivery_remainders"].clear()
        self.assertEqual(json.dumps(self.delivered_207(), sort_keys=True), expected)
```

- [ ] **Step 2: Run the guard and the counter before the change**

1. Focused test form (timeout 1800 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_migration.py -k test_each_delivered_207_call 2>&1 | tail -6'`. Expected: `FAILED (failures=1)`. At base every call re-runs the driver in a fresh temporary project, so the second call's ledger names a different root than the first's and the equality fails (red before, D11).
2. The counter command. Expected: `Ran 27 tests`, `FAILED (failures=1)` (the Step 1 guard) and `DRIVER_RUNS 13`: the 10 existing calls plus this test's 3; the command exits non-zero. This is the observation Step 4 must change.

- [ ] **Step 3: Write the minimal implementation**

1. Directly after the `CORE = re.compile(...)` statement, add:

```python
# The issue-207 ledger text per concrete test class (issue 500 D4, D9).
_DELIVERED_207: dict[type, str] = {}
```

2. Replace `delivered_207` with:

```python
    def delivered_207(self):
        """The issue-207 ledger's parsed state, a fresh parse on every call (issue 500 D4).

        The first call in a concrete test class runs the #220 driver and keeps the
        ledger's text for that class; the driver's root and HOME are removed before
        this method returns, and a failed run keeps nothing.
        """
        owner = type(self)
        text = _DELIVERED_207.get(owner)
        if text is None:
            class Driver(DeliveredControlHarness, unittest.TestCase):
                def runTest(self):
                    pass

            Driver.setUpClass()
            driver = Driver()
            try:
                driver.deliver_through_remainder()
                text = driver.ledger.read_text(encoding="utf-8")
            finally:
                driver.doCleanups()
            _DELIVERED_207[owner] = text
            owner.addClassCleanup(_DELIVERED_207.pop, owner, None)
        return json.loads(text)
```

The `finally` runs the driver's own cleanups, which remove its root and HOME, on success and on failure. The cache entry and its class cleanup are written only after a successful read. The old `self.addCleanup(driver.doCleanups)` is gone, because nothing is left to clean at test end.

- [ ] **Step 4: Verify**

All from the worktree root, through `launch-scope exec`:
1. The counter command. Expected: `Ran 27 tests`, `OK` and `DRIVER_RUNS 2`, one per consuming class. A count above 2 means the cache is not keyed per concrete class.
2. The Step 2 guard command. Expected: `OK`.
3. Mutation check, never committed. In `delivered_207`, temporarily replace `_DELIVERED_207[owner] = text` with `_DELIVERED_207[owner] = text = json.loads(text)` and the final `return json.loads(text)` with `return text if isinstance(text, dict) else json.loads(text)`, so every call shares one dict. Run the guard command. Expected: `FAILED (failures=1)`. Then restore the file, and confirm with `git diff --stat -- home/common/agent-skills/tests/test_attempt_migration.py` that only the Step 1 and Step 3 changes remain.
4. The Coverage gate (Global Constraints). Expected: `COVERAGE-GATE-OK base 3575 head 3579 test ids`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_attempt_migration.py
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "test(issue-500): deliver issue 207 once per migration test class" -m "<the session's trailer lines>"
```
