# Task 2: Lifecycle `advance` with lock, terminal and unknown-state guards

**Files:**
- Modify: `python/agent_tools/transaction_core.py`
- Modify: `tests/test_transaction_core.py` (append the classes below before the
  `if __name__ == "__main__":` block)

**Interfaces:**
- Consumes (Task 1, `agent_tools.transaction_core`): `STATES`, `TERMINALS`, `TRANSITIONS`,
  `TransactionStore(root)`, `.create(creation_key, subject) -> Transaction`,
  `.load(transaction_id) -> Transaction`, `Transaction` fields, the error classes, and
  the private helpers `_edge_allowed(source, parked_from, target) -> bool`,
  `self._validated_document(transaction_id) -> dict`, `_snapshot(document) -> Transaction`,
  `_atomic_write(directory, path, document) -> None`, `_timestamp() -> str`,
  `_validate_state(document, transaction_id, root) -> None`. In the test file:
  `StoreCase` (`self.root`, `self.store`, `state_path`, `tree`, `document`, `write`),
  `SUBJECT`, `FORWARD`, `EXPECTED_EDGES`.
- Produces: `TransactionStore.advance(self, transaction_id: str, target: str, *, reason: str, external_state: str | None = None) -> Transaction`
  — Task 3's executor calls exactly this signature.

**Invariants:**
- Every refusal (`UnknownTransaction`, `TransactionBusy`, `StateInvalid`,
  `TransitionRefused`) happens before any write: `state.json` bytes and the transaction
  directory listing are identical afterwards, and no `.tmp` file remains (D9, D10).
- A terminal source refuses every target; a terminal target needs `external_state ==
  "known"`; a refusal never reroutes to `attention_required` (D8).
- `advance` never creates a path: the lock file is opened without `O_CREAT` (D13).
- The lock is non-blocking; contention raises `TransactionBusy` immediately (D10).
- A successful `advance` appends exactly one `transitioned` event with `seq = revision +
  1`, and the prior events are the new history's exact prefix (D5).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_transaction_core.py`:

```python
PATHS_TO = {  # a legal path from `created` to each nonterminal source
    **{state: FORWARD[1:i + 1] for i, state in enumerate(FORWARD)},
    "attention_required": ("attention_required",),
    "recovering": ("attention_required", "recovering"),
}
PATHS_TO_TERMINAL = {
    "succeeded": FORWARD[1:] + ("succeeded",),
    "abandoned": ("abandoned",),
    "failed": ("attention_required", "failed"),
    "rolled_back": ("attention_required", "recovering", "rolled_back"),
}


class AdvanceCase(StoreCase):
    def reach(self, key, path):
        transaction_id = self.store.create(key, SUBJECT).transaction_id
        for target in path:
            self.store.advance(transaction_id, target, reason=f"to {target}",
                               external_state="known")
        return transaction_id

    def assertRefusedUnchanged(self, error, transaction_id, target, **kwargs):
        raw = self.state_path(transaction_id).read_bytes()
        listing = self.tree()
        with self.assertRaises(error):
            self.store.advance(transaction_id, target, reason=kwargs.pop("reason", "try"),
                               **kwargs)
        self.assertEqual(self.state_path(transaction_id).read_bytes(), raw)
        self.assertEqual(self.tree(), listing)


class AdvanceTest(AdvanceCase):
    def test_the_forward_chain_persists_one_event_per_transition(self):
        transaction_id = self.reach("k", PATHS_TO_TERMINAL["succeeded"])
        persisted = TransactionStore(self.root).load(transaction_id)
        self.assertEqual(persisted.state, "succeeded")
        self.assertEqual(persisted.revision, 8)
        self.assertEqual([e["seq"] for e in persisted.events], list(range(1, 9)))
        self.assertEqual([e["to"] for e in persisted.events[1:]],
                         list(PATHS_TO_TERMINAL["succeeded"]))
        self.assertEqual(persisted.events[-1]["external_state"], "known")
        self.assertEqual(persisted.events[1]["reason"], "to awaiting_verification")

    def test_the_library_path_skips_activation(self):
        transaction_id = self.reach("k", FORWARD[1:5] + ("proving", "succeeded"))
        self.assertEqual(self.store.load(transaction_id).state, "succeeded")

    def test_every_allowed_edge_is_accepted_and_every_other_target_refused(self):
        for source, path in PATHS_TO.items():
            allowed = EXPECTED_EDGES[source]
            if source == "attention_required":
                allowed = {"created", "recovering", "abandoned", "failed"}
            for target in sorted(STATES | {"not_a_state"}):
                with self.subTest(source=source, target=target):
                    transaction_id = self.reach(f"{source}->{target}", path)
                    if target in allowed:
                        after = self.store.advance(transaction_id, target, reason="edge",
                                                   external_state="known")
                        self.assertEqual(after.state, target)
                    else:
                        self.assertRefusedUnchanged(TransitionRefused, transaction_id,
                                                    target, external_state="known")

    def test_a_park_resumes_only_where_it_left(self):
        transaction_id = self.reach("k", FORWARD[1:4] + ("attention_required",))
        parked = self.store.load(transaction_id)
        self.assertEqual((parked.state, parked.parked_from),
                         ("attention_required", "publishing"))
        self.assertRefusedUnchanged(TransitionRefused, transaction_id, "ready")
        self.assertRefusedUnchanged(TransitionRefused, transaction_id, "published")
        resumed = self.store.advance(transaction_id, "publishing", reason="resume")
        self.assertEqual((resumed.state, resumed.parked_from), ("publishing", None))


class TerminalTest(AdvanceCase):
    def test_every_terminal_refuses_every_target(self):
        for terminal, path in PATHS_TO_TERMINAL.items():
            transaction_id = self.reach(terminal, path)
            for target in sorted(STATES | {"not_a_state"}):
                with self.subTest(terminal=terminal, target=target):
                    self.assertRefusedUnchanged(TransitionRefused, transaction_id, target,
                                                external_state="known")

    def test_a_terminal_target_requires_known_external_state(self):
        for terminal, path in PATHS_TO_TERMINAL.items():
            transaction_id = self.reach(terminal, path[:-1])
            for external_state in ("unknown", None):
                with self.subTest(terminal=terminal, external_state=external_state):
                    self.assertRefusedUnchanged(TransitionRefused, transaction_id, terminal,
                                                external_state=external_state)
            self.assertRefusedUnchanged(TransitionRefused, transaction_id, terminal)
            source = (("created",) + path[:-1])[-1]
            self.assertEqual(self.store.load(transaction_id).state, source)  # no reroute
            done = self.store.advance(transaction_id, terminal, reason="grounded",
                                      external_state="known")
            self.assertEqual(done.state, terminal)

    def test_malformed_reason_or_external_state_is_refused(self):
        transaction_id = self.reach("k", ())
        for kwargs in ({"reason": ""}, {"reason": "ok", "external_state": "maybe"}):
            with self.subTest(kwargs=kwargs):
                self.assertRefusedUnchanged(TransitionRefused, transaction_id,
                                            "awaiting_verification", **kwargs)


class LockAndSchemaGuardTest(AdvanceCase):
    def test_a_held_transaction_lock_refuses_advance_before_any_write(self):
        transaction_id = self.reach("k", ())
        with open(self.root / transaction_id / "lock", "r+") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertRefusedUnchanged(TransactionBusy, transaction_id,
                                        "awaiting_verification")
        self.store.advance(transaction_id, "awaiting_verification", reason="now free")

    def test_a_held_creation_lock_refuses_create_before_any_write(self):
        with open(self.root / "creation.lock", "a+") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(TransactionBusy):
                self.store.create("k", SUBJECT)
            self.assertEqual(self.tree(), ["creation.lock"])

    def test_a_schema_invalid_state_refuses_advance_before_any_write(self):
        transaction_id = self.reach("k", ())
        self.write(transaction_id, {**self.document(transaction_id), "extra": 1})
        self.assertRefusedUnchanged(StateInvalid, transaction_id, "awaiting_verification")

    def test_unknown_ids_and_missing_locks_create_nothing(self):
        transaction_id = self.reach("k", ())
        listing = self.tree()
        for unknown in ("rel_0190f0e0-0000-7000-8000-000000000000", "rel_../x"):
            with self.subTest(id=unknown), self.assertRaises(UnknownTransaction):
                self.store.advance(unknown, "awaiting_verification", reason="x")
        self.assertEqual(self.tree(), listing)
        (self.root / transaction_id / "lock").unlink()
        self.assertRefusedUnchanged(StateInvalid, transaction_id, "awaiting_verification")
        self.assertFalse((self.root / transaction_id / "lock").exists())
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core.py 2>&1 | tail -3`
Expected: FAIL — `AttributeError: 'TransactionStore' object has no attribute 'advance'`
(Task 1's 14 tests still pass).

- [ ] **Step 3: Write the minimal implementation** — add `TransactionStore.advance`:

1. First, with no path created: id fails Task 1's id pattern or `root/id` is not a
   directory → `UnknownTransaction` (D16). Share this check with `_validated_document`
   rather than copying it.
2. `fd = os.open(root/id/"lock", os.O_RDWR)` — no `O_CREAT`; `FileNotFoundError` →
   `StateInvalid` naming the missing lock file (D13). Refuse a non-regular lock file as
   Task 1's reader does. Close `fd` in a `finally`.
3. `fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)`; `BlockingIOError` →
   `TransactionBusy` (D10). No retry and no sleep.
4. `prior = self._validated_document(transaction_id)` (raises `StateInvalid`).
5. Refuse with `TransitionRefused`, each message naming the id, source and target:
   source in `TERMINALS`; `target not in STATES`; `not _edge_allowed(prior["state"],
   prior["parked_from"], target)`; `reason` not a non-empty `str`; `external_state not in
   ("known", "unknown", None)`; `target in TERMINALS and external_state != "known"` (D7,
   D8, D15).
6. Build the candidate from a deep copy: append `{"seq": prior["revision"] + 1, "type":
   "transitioned", "at": _timestamp(), "from": prior["state"], "to": target, "reason":
   reason, "external_state": external_state}`; set `parked_from` to the source when
   `target == "attention_required"`, to `None` when leaving `attention_required`, else
   unchanged; `state = target`; `revision = len(events)`.
7. Assert `candidate["events"][:-1] == prior["events"]`, then `_validate_state(candidate,
   transaction_id, self.root)`; a failure here is `StateInvalid` (a core defect, not a
   caller error) and nothing is written.
8. `_atomic_write(root/id, root/id/"state.json", candidate)`; return
   `_snapshot(candidate)`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core.py 2>&1 | tail -3`
Expected: `OK` (25 tests).

Run: `just agent-workflow-tests 2>&1 | tail -3` — Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/transaction_core.py tests/test_transaction_core.py
git commit -m "feat(transaction-core): add guarded lifecycle transitions (#204)"
```
