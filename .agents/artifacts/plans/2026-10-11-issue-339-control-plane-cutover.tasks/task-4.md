# Task 4: The delivery transaction and its journal

Each installed delivery contract gets one core transaction whose subject is the contract and whose `event` evidence is every delivery object the ledger holds, appended by the settle step as the last core operations before the ledger is published. Nothing reads the journal as a decision and nothing seals yet (Task 6). Decisions: D2, D7, D14, D17, D21, D22.

**Files:**
- Create: `python/agent_tools/attempt_delivery_store.py`
- Modify: `python/agent_tools/attempt_store.py` (two public seams)
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (`commit_state`)
- Modify: `home/common/agent-skills/tests/test_control_cutover.py` (add), `home/common/agent-skills/tests/test_control_decisions.py` (rows 1 and 7)
- Modify (floor, D22): `home/common/agent-skills/tests/test_attempt_custody.py`

**Interfaces:**
- Consumes: Task 1's delivery keys, subject, creation arguments, `journal_entries`, `journaled` and `HELPER_TTL_MS`; `attempt_custody.span_lapsed`.
- Produces in `agent_tools.attempt_store`, the only names `attempt_delivery_store` takes from it besides `StoreRefused` and `StoreFault`:

```python
@contextlib.contextmanager
def reading(store: Path, now_ms: int) -> Iterator[TransactionStore | None]:
    """The core on a clock that reads `now_ms`, for lock-free reads; None when the store
    directory does not exist. Creates nothing; a core error is a `StoreFault`."""


@contextlib.contextmanager
def writing(store: Path, now_ms: int) -> Iterator[TransactionStore]:
    """The core on a clock that reads `now_ms`, under the store lock (which creates the
    store); core errors are raised as the refusals `_core_errors` maps them to."""
```

- Produces in `agent_tools.attempt_delivery_store`:

```python
def delivery_of(core: TransactionStore, run: str, issue: int,
                digest: str) -> tuple[int, Transaction | None]:
    """Probe `delivery_key(issue, digest, n)` for n = 1, 2, ...: the first ordinal whose
    transaction names `run`, with that transaction, or the first unused ordinal with None.
    A probed subject that is not the closed delivery subject is a `StoreRefused`."""


def settle_delivery(store: Path, state: dict, *, now_ms: int,
                    canonical_text: Callable[[Any], str]) -> None:
    """Create the delivery transaction of each installed contract of `state` that has
    none, and append the journal entries each transaction lacks."""
```

- Produces in `workflow-state.py`: `commit_state` calls `settle_delivery(store, state, now_ms=now_ms, canonical_text=…)` after `settle_custody` and before `atomic_write_state`; the function it passes returns `_delivery().model.canonical_bytes(value).decode("utf-8")`.

**Invariants:**
- One transaction per `(run, issue, installed contract)`, created in the write that installs the contract: key `delivery_key(issue, contract_digest, n)` with `n` from `delivery_of` under the store lock, subject `delivery_subject(run=state["transaction_id"], …)`, arguments `delivery_creation_arguments(subject)`. An issue with no contract has none.
- After every committed write the journal of a non-terminal delivery transaction is exactly the ledger's objects: each `journal_entries` item is one `event` evidence entry with that id and reference, recorded once. A terminal transaction is left alone in this task.
- Entries are appended under a span whose executor is `delivery_executor(issue)`, whose bound path is the ledger root (`str(store.parents[1])`) and whose window is `HELPER_TTL_MS`, released in the same call. An open span of that executor that has not lapsed is reused; over a lapsed one `acquire` is called directly (the core records the lapse).
- The read phase takes no lock: with no contract, or no transaction missing and no entry lacking, `settle_delivery` creates no store, lock file or directory. The write phase runs under `writing`, issues ascending.
- A write cut after the journal leaves entries the ledger lacks; no reader consults them.
- `attempt_delivery_store` imports no private name of `attempt_store`.

- [ ] **Step 1: Write the failing tests**

Append to `home/common/agent-skills/tests/test_control_cutover.py`:

```python
class DeliveryJournalTest(Cutover, unittest.TestCase):
    def expected(self):
        delivery = self.ledger_document()["issues"][str(DELIVERED)]["delivery"]
        return {f"{kind}:{item['id']}": ("event", self.model.canonical_bytes(item).decode())
                for kind in ad.JOURNAL_KINDS for item in delivery[kind]}

    def journal(self):
        return {entry["evidence_id"]: (entry["form"], entry["reference"])
                for entry in self.delivery(DELIVERED).evidence}

    def test_an_installed_contract_has_a_transaction_holding_every_delivery_object(self):
        custody = self.spawn(DELIVERED)[DELIVERED]
        document = self.ledger_document()
        delivery = document["issues"][str(DELIVERED)]["delivery"]
        held = self.delivery(DELIVERED)
        self.assertIsNotNone(held)
        self.assertEqual(dict(held.subject), ad.delivery_subject(
            run=document["transaction_id"], issue=DELIVERED,
            contract_digest=delivery["contract_digest"], contract=delivery["contract"]))
        self.assertEqual(
            (held.state, held.custody, [o["obligation_id"] for o in held.proof["obligations"]]),
            ("created", None, list(ad.POSTCONDITIONS)))
        first = self.expected()
        self.assertTrue(first)
        self.assertEqual(self.journal(), first)
        self.merge_checkpoint(custody, 5)
        self.assertGreater(len(self.expected()), len(first))
        self.assertEqual(self.journal(), self.expected())
        lease = self.core().inspect_lease(
            ad.delivery_lease_key(document["transaction_id"], DELIVERED))
        self.assertEqual((lease["holder"], self.delivery(DELIVERED, 2)), (None, None))

    def test_the_bind_journals_the_delivery_of_a_schema_9_ledger(self):
        self.generation = "base"
        self.merge_checkpoint(self.spawn(DELIVERED)[DELIVERED], 5)
        self.generation = "head"
        self.assertIsNone(self.delivery(DELIVERED))
        self.cli("migrate", "--repo-root", self.root, "--apply")
        self.assertIsNotNone(self.delivery(DELIVERED))
        self.assertEqual(self.journal(), self.expected())
```

In `test_control_decisions.py`, the two rows whose store column names the delivery transaction gain it. At the end of `test_01_spawn`:

```python
        journal = self.delivery(DELIVERED)
        self.assertTrue(journal is not None and journal.evidence)
```

At the end of `test_07_reconcile` (the reconcile itself journals no delivery observation, D19):

```python
        journal = self.delivery(DELIVERED)
        self.assertIsNotNone(journal)
        self.assertFalse([entry for entry in journal.evidence
                          if entry["evidence_id"].startswith("delivery_observations:")])
```

- [ ] **Step 2: Run them and watch them fail**

Run: `PYTEST T/test_control_cutover.py T/test_control_decisions.py -k DeliveryJournalTest -k test_01_spawn -k test_07_reconcile`
Expected: FAIL, 4 tests, no error: no delivery transaction exists for the installed contract (`unexpectedly None`, and `False is not true` in `test_01_spawn`).

- [ ] **Step 3: Implement**

The two seams, the new module and the call in `commit_state`. The module docstring says which effects the module owns and which seams it uses.

- [ ] **Step 4: Apply the declared floor change**

Package 2's `LateSummaryTest.test_ac4_merged_and_closed_are_observed_apart_from_custody` compared every core file across a control write that adds a tracker observation; that write now appends a journal entry. Compare the attempt's custody events (`self.events(DELIVERED)`) instead and keep the postcondition assertions (D22).

- [ ] **Step 5: Verify**

Run: `PYTEST T/test_control_cutover.py T/test_control_decisions.py T/test_attempt_custody.py T/test_delivered_control.py T/test_admission_replay.py tests/test_transaction_core_sweep.py`
Expected: `OK`; `test_control_cutover.py` runs 12 tests.

Run: `PYTEST T/test_delivery_workflow.py T/test_workflow_state.py`
Expected: `OK`.

Run: `if grep -n "attempt_store\._" python/agent_tools/attempt_delivery_store.py; then exit 1; fi`
Expected: exit 0, no output.

- [ ] **Step 6: Commit**

```bash
git add python home
launch-commit … -- -m "feat(attempt-delivery): the delivery transaction and its journal (#339)"
```
