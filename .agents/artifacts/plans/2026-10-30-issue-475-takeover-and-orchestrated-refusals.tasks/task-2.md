# Task 2: Issue hold pointers

Spec § Decisions (Issue hold pointers), per D5, D6, D11 and D12. This task builds the index that leads from an issue to the orchestrated runs holding it, and writes it on every locked write of an orchestrated run. Nothing reads it yet; Task 3 does.

**Files:**
- Modify: `python/agent_tools/attempt_identity.py` (hold grammar beside `creation_arguments`; module docstring)
- Modify: `python/agent_tools/attempt_custody.py` (`holds_issue` after the constant block, before `def stall_count`)
- Modify: `python/agent_tools/attempt_store.py` (imports; `_hold_subject`, `_hold_slot`, `settle_holds` and `hold_runs` just above `def unmigrated_direct`; module docstring)
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (`commit_state` calls `settle_holds`; `issue_set_reusable` calls `holds_issue`; import)
- Test: `tests/test_attempt_identity.py` (new classes `HoldGrammarTest` and `HoldPointerStoreTest`)
- Test: `tests/test_attempt_custody.py` (new class `HoldsIssueTest`)
- Test: `home/common/agent-skills/tests/test_workflow_state.py` (new class `HoldPointerWriteTest`, appended)

**Interfaces:**
- Consumes: `RunPlan`, `RunIdentity`, `creation_arguments`, `_is_int`, `_MAX_ISSUE` and `is_id` (`attempt_identity`); `LIVE_STATES` (`attempt_custody`); `lookup_run`, `run_handle`, `writing`, `mint_run`, `creation_key_plan`, `StoreRefused` and `StoreFault` (`attempt_store`); `commit_state`'s `store`, `state`, `identity` and `now_ms`.
- Produces:
  - `attempt_identity.HOLD_SCHEMA = "issue-hold/v1"`.
  - `attempt_identity.hold_key(issue: int, ordinal: int) -> str`, returning `"issue-hold/v1:<issue>:<ordinal>"`.
  - `attempt_identity.hold_violation(subject: object) -> str | None`.
  - `attempt_identity.hold_plan(issue: int, ordinal: int, run: str) -> RunPlan`.
  - `attempt_custody.holds_issue(issue_state: Mapping) -> bool`.
  - `attempt_store.settle_holds(store: Path, state: dict, identity: RunIdentity, *, now_ms: int) -> None`.
  - `attempt_store.hold_runs(store: Path, issue: int) -> Iterator[str]`.

**Invariants:**
- A hold subject is exactly `{"schema": "issue-hold/v1", "issue": <int 1..9999999, not bool>, "run": <core transaction id>}`. `hold_violation` returns a reason for anything else. `hold_plan` raises `ValueError` for an ordinal that is not an int of at least 1 (a bool included) and for a subject `hold_violation` refuses. A pointer is created with `creation_arguments(plan)`, the arguments run transactions use (D5).
- `holds_issue` is true exactly when the latest attempt or the latest delivery remainder has a `state` in `LIVE_STATES` (D7, D12). `issue_set_reusable`'s live clause becomes `holds_issue(entry)`, with no change in behaviour.
- `settle_holds` returns at once for a direct identity. For an orchestrated one it plans, without a lock, every issue in `state["issues"]` (ascending) that `holds_issue` and that has no pointer naming `state["transaction_id"]`. With nothing planned it creates nothing, not even the store. Otherwise, under `writing(store, now_ms)`, it decides each planned issue's slot again and creates its pointer at the first free ordinal (D6, D11).
- A slot probe walks `hold_key(issue, k)` from `k = 1`. A miss is the free slot. A pointer naming the run means no slot is needed. An index entry whose subject is not a hold subject is a `StoreRefused`.
- Pointers are never removed. `commit_state` calls `settle_holds` after `settle_delivery` and before `atomic_write_state`, so a refused custody settle creates no pointer (D11).
- `hold_runs` yields `run_handle(store, subject["run"])` for each pointer, in ordinal order, until the first miss. It is lazy, takes no lock, creates nothing and never lists a directory. It raises `StoreRefused` when a pointer names a transaction that is not an attempt run (D5).

- [ ] **Step 1: Write the failing tests**

`tests/test_attempt_identity.py`: below `from agent_tools import attempt_identity as ai`, add `from agent_tools import attempt_store`. Append:

```python
class HoldGrammarTest(unittest.TestCase):
    """Issue 475 D5: the issue-hold/v1 key and closed subject."""

    def test_the_key_and_subject_name_the_issue_and_the_run(self):
        plan = ai.hold_plan(73, 2, CORE_ID)
        self.assertEqual((plan.creation_key, plan.subject_json()), (
            "issue-hold/v1:73:2", {"schema": "issue-hold/v1", "issue": 73, "run": CORE_ID}))
        self.assertIsNone(ai.hold_violation(plan.subject_json()))
        self.assertEqual(ai.creation_arguments(plan)["concurrency_keys"],
                         ["attempt-run:issue-hold/v1:73:2"])

    def test_anything_else_is_not_a_hold_subject(self):
        good = {"schema": "issue-hold/v1", "issue": 73, "run": CORE_ID}
        for subject in ({**good, "extra": 1}, {**good, "schema": "attempt-run/v1"},
                        {**good, "issue": 0}, {**good, "issue": True}, {**good, "issue": "73"},
                        {**good, "run": "orchestrate-73"}, [], None):
            with self.subTest(subject=subject):
                self.assertIsNotNone(ai.hold_violation(subject))
        for ordinal in (0, True, "1"):
            with self.subTest(ordinal=ordinal):
                with self.assertRaises(ValueError):
                    ai.hold_plan(73, ordinal, CORE_ID)


class HoldPointerStoreTest(unittest.TestCase):
    """Issue 475 D5, D6: `settle_holds` writes the pointers `hold_runs` reads."""

    ORCHESTRATED = ai.RunIdentity("orchestrated", None, None)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Path(directory.name) / "attempt-transactions"

    def run_transaction(self, key):
        return attempt_store.mint_run(self.store, attempt_store.creation_key_plan(key))

    @staticmethod
    def state(run, **states):
        return {"transaction_id": run, "issues": {
            str(issue): {"attempts": [{"state": state}], "delivery_remainders": []}
            for issue, state in ((int(name[1:]), value) for name, value in states.items())}}

    def settle(self, state, identity=ORCHESTRATED):
        attempt_store.settle_holds(self.store, state, identity, now_ms=1_790_000_000_000)

    def pointers(self, issue):
        core = TransactionStore(self.store)
        found, ordinal = [], 1
        while (transaction_id := core.lookup(ai.hold_key(issue, ordinal))) is not None:
            found.append(core.load(transaction_id).subject["run"])
            ordinal += 1
        return found

    def test_each_held_issue_gets_one_pointer_however_often_the_run_writes(self):
        run = self.run_transaction("first")
        for _ in range(2):
            self.settle(self.state(run, i73="suspended", i74="merged", i75="active"))
        self.assertEqual((self.pointers(73), self.pointers(74), self.pointers(75)),
                         ([run], [], [run]))
        self.assertEqual(list(attempt_store.hold_runs(self.store, 73)), [run])

    def test_a_second_run_holding_the_issue_takes_the_next_ordinal(self):
        first, second = self.run_transaction("first"), self.run_transaction("second")
        self.settle(self.state(first, i73="active"))
        self.settle(self.state(second, i73="handed_off"))
        self.settle(self.state(first, i73="active"))
        self.assertEqual(self.pointers(73), [first, second])
        self.assertEqual(list(attempt_store.hold_runs(self.store, 73)), [first, second])

    def test_a_direct_run_and_a_settled_run_create_nothing(self):
        self.settle(self.state(CORE_ID, i73="active"), ai.RunIdentity("direct", 73, 1))
        self.assertFalse(self.store.exists())
        run = self.run_transaction("first")
        self.settle(self.state(run, i73="active"))
        before = sorted(path for path in self.store.rglob("*"))
        self.settle(self.state(run, i73="active"))
        self.assertEqual(sorted(path for path in self.store.rglob("*")), before)
        self.assertEqual(list(attempt_store.hold_runs(self.store, 99)), [])

    def test_an_index_entry_that_is_not_a_hold_pointer_is_refused(self):
        run = self.run_transaction("first")
        plan = ai.hold_plan(73, 1, run)
        TransactionStore(self.store).create(plan.creation_key, {"schema": "other"},
                                            **ai.creation_arguments(plan))
        with self.assertRaises(attempt_store.StoreRefused):
            list(attempt_store.hold_runs(self.store, 73))
```

`tests/test_attempt_custody.py` (its module alias is `ac`), append:

```python
class HoldsIssueTest(unittest.TestCase):
    """Issue 475 D7: a run holds an issue while its latest attempt or remainder is live."""

    def test_the_latest_attempt_or_remainder_decides(self):
        def entry(attempts, remainders=()):
            return {"attempts": [{"state": state} for state in attempts],
                    "delivery_remainders": [{"state": state} for state in remainders]}

        for value, held in ((entry([]), False), (entry(["active"]), True),
                            (entry(["suspended", "failed"]), False),
                            (entry(["handed_off"]), True),
                            (entry(["merged"], ["suspended"]), True),
                            (entry(["merged"], ["active", "stopped"]), False)):
            with self.subTest(value=value):
                self.assertIs(ac.holds_issue(value), held)
```

`home/common/agent-skills/tests/test_workflow_state.py`, append:

```python
class HoldPointerWriteTest(LifecycleHarness, unittest.TestCase):
    """Issue 475 D6: a locked write of an orchestrated run gives each issue it holds a pointer."""

    def test_an_orchestrated_write_points_at_its_run_and_a_direct_one_does_not(self):
        self.init_run()
        self.spawn(issue=73, worktree=self.root / "wt-73")
        self.suspend(issue=73, attempt=1, blocked_on="transport", now="2026-08-13T20:05:00Z")
        self.assertEqual(list(attempt_store.hold_runs(self.store_root, 73)), [self.run_id])
        self.acquire_direct(issue=74)
        self.assertEqual(list(attempt_store.hold_runs(self.store_root, 74)), [])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (Unit run), once for each: `tests/test_attempt_identity.py`, `tests/test_attempt_custody.py`, and `home/common/agent-skills/tests/test_workflow_state.py -k HoldPointerWriteTest`.
Expected: each FAILED with errors (`has no attribute 'hold_plan'`, `'holds_issue'`, `'hold_runs'`).

- [ ] **Step 3: Write the implementation**

`attempt_identity.py`: below `_MAX_SEQUENCE`, add `HOLD_SCHEMA = "issue-hold/v1"` and `_HOLD_KEYS = frozenset({"schema", "issue", "run"})`. Just above `def creation_arguments`, add `hold_key`, then `hold_violation`, then `hold_plan`, per the Interfaces and Invariants. `hold_violation` checks these in order: a `Mapping` with keys exactly `_HOLD_KEYS`; `schema == HOLD_SCHEMA`; `_is_int(issue, 1, _MAX_ISSUE)`; `is_id(run)`. `hold_plan` checks the ordinal first (`type(ordinal) is not int or ordinal < 1`), builds the subject, raises `ValueError(violation)` when one exists, and returns `RunPlan(hold_key(issue, ordinal), subject)`. In the module docstring, change "Grammar, plan, subject and report:" to "Grammar, plan, subject and report, and the key and closed subject of an issue hold pointer (issue 475):".

`attempt_custody.py`: just above `def stall_count`, add:

```python
def holds_issue(issue_state: Mapping) -> bool:
    """Whether a run still holds an issue: its latest attempt or latest delivery remainder is
    in `LIVE_STATES` (issue 475 D7)."""
    return any(records and records[-1]["state"] in LIVE_STATES
               for records in (issue_state["attempts"], issue_state["delivery_remainders"]))
```

`attempt_store.py`: add `hold_key, hold_plan, hold_violation` to the `agent_tools.attempt_identity` import. Just above `def unmigrated_direct`, add the four functions:

```python
def _hold_subject(store: Path, transaction_id: str) -> Mapping[str, Any]:
    """The closed issue-hold/v1 subject of the pointer `transaction_id`, read without a lock."""
    try:
        subject = TransactionStore(store).load(transaction_id).subject
    except UnknownTransaction as error:
        raise StoreRefused(f"issue hold store: {error}") from error
    except TransactionError as error:
        raise StoreFault(f"issue hold store: {error}") from error
    violation = hold_violation(subject)
    if violation is not None:
        raise StoreRefused(f"issue hold index entry is not a hold pointer: {violation}")
    return subject


def _hold_slot(store: Path, issue: int, run: str) -> int | None:
    """The first free pointer ordinal of `issue`, or None when a pointer already names `run`."""
    ordinal = 0
    while True:
        ordinal += 1
        transaction_id = lookup_run(store, hold_key(issue, ordinal))
        if transaction_id is None:
            return ordinal
        if _hold_subject(store, transaction_id)["run"] == run:
            return None


def settle_holds(store: Path, state: dict, identity: RunIdentity, *, now_ms: int) -> None:
    """Give each issue an orchestrated run's `state` holds a pointer naming its run (issue 475
    D6, D11).

    The read phase takes no lock: with every pointer in place (or for a direct run, which the
    direct index already finds) it creates nothing, not even the store. Otherwise, under the
    store lock, each missing pointer's slot is decided again and created at the first free
    ordinal with the run transactions' creation arguments. Pointers are never removed.
    """
    if identity.direct:
        return
    run = state["transaction_id"]
    held = [int(key) for key in sorted(state["issues"], key=int)
            if custody_rules.holds_issue(state["issues"][key])]
    missing = [issue for issue in held if _hold_slot(store, issue, run) is not None]
    if not missing:
        return
    with writing(store, now_ms) as core:
        for issue in missing:
            ordinal = _hold_slot(store, issue, run)
            if ordinal is not None:
                plan = hold_plan(issue, ordinal, run)
                core.create(plan.creation_key, plan.subject_json(), **creation_arguments(plan))


def hold_runs(store: Path, issue: int) -> Iterator[str]:
    """The handle of each run a hold pointer of `issue` names, in pointer order, read without a
    lock and never by listing `workflows`; nothing is created (issue 475 D5). A pointer that
    names no attempt run is a `StoreRefused`."""
    ordinal = 0
    while True:
        ordinal += 1
        transaction_id = lookup_run(store, hold_key(issue, ordinal))
        if transaction_id is None:
            return
        handle = run_handle(store, _hold_subject(store, transaction_id)["run"])
        if handle is None:
            raise StoreRefused("issue hold pointer does not name a run transaction")
        yield handle
```

In `attempt_store`'s module docstring, after the sentence ending "…and the direct index probe.", add: "It also keeps the issue hold pointers that lead from an issue to the orchestrated runs holding it (`settle_holds`, `hold_runs`; issue 475)."

`workflow-state.py`:
- Add `holds_issue,` to the `from agent_tools.attempt_custody import (…)` list, between `at_ms,` and `launch_id,`.
- In `commit_state`, directly after the `settle_delivery(...)` call and before `atomic_write_state(...)`, add `attempt_store.settle_holds(store, state, identity, now_ms=now_ms)`. In its docstring, after "…settles custody in the core (…)", add ", ensures the issue hold pointers of an orchestrated run (issue 475)".
- In `issue_set_reusable`, replace the `if any(records and records[-1]["state"] in {"active", "handed_off", "suspended"} for records in (…)):` condition with `if holds_issue(entry):`.

- [ ] **Step 4: Verify**

Run (Unit run), once for each: `tests/test_attempt_identity.py`; `tests/test_attempt_custody.py`; `home/common/agent-skills/tests/test_workflow_state.py -k HoldPointerWriteTest`; `home/common/agent-skills/tests/test_attempt_custody.py`; `home/common/agent-skills/tests/test_control_cutover.py` (its `init-run --issue-set` cases cover `issue_set_reusable`); `tests/test_orchestrate_control.py`.
Expected: OK for each, no failures or errors.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/attempt_identity.py python/agent_tools/attempt_custody.py python/agent_tools/attempt_store.py home/common/agent-skills/scripts/workflow-state.py tests/test_attempt_identity.py tests/test_attempt_custody.py home/common/agent-skills/tests/test_workflow_state.py
launch-commit … -- -m "feat(attempt-store): keep issue hold pointers for orchestrated runs (issue 475)"
```
