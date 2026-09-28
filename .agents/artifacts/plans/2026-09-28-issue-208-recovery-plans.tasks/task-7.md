# Task 7: `roll_forward` and the linked child

**Files:**
- Modify: `python/agent_tools/transaction_recovery.py` (admission, link, event rule)
- Modify: `python/agent_tools/transaction_history.py` (the child id is a transaction id)
- Modify: `python/agent_tools/transaction_core.py` (`roll_forward`)
- Modify: `tests/test_transaction_recovery_settle.py` (append)

**Interfaces:**
- Consumes (Tasks 2–6): `TransactionStore._create(creation_key, subject, concurrency_keys,
  proof, recovery, recovers)`, `_fenced`, `_append`, `fresh_grant`, `recovery_refused`,
  `RECOVERY_EVENT_KEYS`, `recovery_view` (whose `children` already reads the link events),
  and `SettleCase`.
- Produces:
  - `transaction_recovery.roll_forward_refusal(document, grant_id) -> None`. It raises
    `state_not_attention`, then `grant_required`, with Task 4's meanings.
  - `transaction_recovery.link_events(document, child_id, grant_id, reason) -> list[dict]`
    returns `[]` when a `roll_forward_linked` already names `child_id`. Otherwise it returns
    `[{"type": "roll_forward_linked", "child_transaction_id", "grant_id", "reason",
    "fence"}]`.
  - `TransactionStore.roll_forward(custody, *, grant_id, reason, creation_key, subject,
    concurrency_keys, proof, recovery) -> Transaction`, which returns the child's snapshot.

**Invariants:**
- `roll_forward` (per D11):
  1. `require_texts(custody, "roll_forward", grant_id=..., reason=...)` runs before any lock.
  2. **Parent, first hold** (`_fenced`, writes=True): `roll_forward_refusal`. Then the lock
     is released, having written nothing.
  3. **The child**: `self._create(creation_key, subject, concurrency_keys, proof, recovery,
     recovers=parent id)`. No parent lock is held, so every compile rule, deduplication and
     `CreationConflict` applies (including `recovers` differing).
  4. **Parent, second hold**: `roll_forward_refusal` again, then `link_events`. It appends
     when the list is non-empty and returns without writing when it is empty. The parent's
     `state`, `parked_from` and custody never change.
- `RECOVERY_EVENT_KEYS["roll_forward_linked"]` is the envelope plus `{child_transaction_id,
  grant_id, reason, fence}`. The rule: the state is `attention_required`; the event is
  fenced by the open span; `fresh_grant(events_before, grant_id, fence)` holds (else a rule
  containing `grant`); the child id differs from the transaction's own and from every
  earlier link (else a rule containing `child_transaction_id`); and `reason` is a non-empty
  string. `transaction_history` additionally refuses a child id that fails `is_id`, with a
  rule containing `child_transaction_id`, because `is_id` lives in the history module.
- The parent's events before the link serialize byte-identically after it.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_transaction_recovery_settle.py`
  (add `import hashlib`, `from agent_tools.transaction_core import CreationConflict,
  StaleCustody, TransactionStore`, `from .test_transaction_custody import KEYS, SUBJECT, TTL,
  plain` and `from .test_transaction_recovery_plan import PROOF`):

```python
class RollForwardTest(SettleCase):
    def forward(self, key="forward", grant_id="g-1", store=None):
        return (store or self.store).roll_forward(
            self.custody, grant_id=grant_id, reason="unit_not_restorable", creation_key=key,
            subject={**SUBJECT, "candidate": "sha256:def"}, concurrency_keys=KEYS,
            proof=PROOF, recovery=RECOVERY)

    def test_the_child_has_its_own_id_and_the_parent_records_the_link_without_rewrite(self):
        self.parked()
        self.grant()
        before = self.state_doc(self.transaction_id)
        child = self.forward()
        parent = self.state_doc(self.transaction_id)
        self.assertNotEqual(child.transaction_id, self.transaction_id)
        self.assertEqual((child.state, child.creation_key), ("created", "forward"))
        self.assertEqual((child.events[0]["recovers"], child.recovery["recovers"]),
                         (self.transaction_id, self.transaction_id))
        self.assertEqual(parent["events"][:len(before["events"])], before["events"])
        link = parent["events"][-1]
        self.assertEqual(link, {
            "seq": len(before["events"]) + 1, "type": "roll_forward_linked", "at": link["at"],
            "child_transaction_id": child.transaction_id, "grant_id": "g-1",
            "reason": "unit_not_restorable", "fence": plain(self.custody.fence)})
        self.assertEqual({k: parent[k] for k in ("state", "parked_from", "custody")},
                         {k: before[k] for k in ("state", "parked_from", "custody")})
        self.assertEqual(list(self.store.load(self.transaction_id).recovery["children"]),
                         [child.transaction_id])

    def test_roll_forward_outside_attention_or_without_a_fresh_grant_creates_nothing(self):
        self.to("awaiting_verification")
        self.grant("early")
        self.refused("state_not_attention", lambda: self.forward(grant_id="early"))
        self.to("attention_required")
        self.refused("grant_required", lambda: self.forward(grant_id="early"))

    def test_the_parents_own_key_can_never_become_its_child(self):
        self.parked()
        self.grant()
        self.assertRefusedUnchanged(CreationConflict, lambda: self.forward(key="recovery"))

    def test_a_retry_after_dying_between_child_and_link_links_once(self):
        self.parked()
        self.grant()
        index = self.root / "creation-keys" / f"{hashlib.sha256(b'forward').hexdigest()}.json"
        lapsing = TransactionStore(self.root,
                                   clock=lambda: self.clock() + (TTL if index.exists() else 0))
        with self.assertRaises(StaleCustody):
            self.forward(store=lapsing)
        self.assertTrue(index.exists())
        self.assertNotIn("roll_forward_linked", self.types(self.transaction_id))
        self.clock.advance(TTL)
        self.store.reap(self.transaction_id, reason="executor lost")
        self.custody = self.acquire(self.transaction_id)
        self.grant("g-2")
        child = self.forward(grant_id="g-2")
        self.assertEqual(self.types(self.transaction_id).count("roll_forward_linked"), 1)
        before = self.files()
        self.assertEqual(self.forward(grant_id="g-2").transaction_id, child.transaction_id)
        self.assertEqual(self.files(), before)

    def test_hand_built_link_breaches_are_state_invalid(self):
        self.parked()
        self.grant()
        child = self.forward()
        document = self.state_doc(self.transaction_id)
        duplicate = copy.deepcopy(document)
        duplicate["events"].append({**copy.deepcopy(document["events"][-1]),
                                    "seq": len(document["events"]) + 1})
        duplicate["revision"] += 1
        for edited, fragment in (
                (lambda d: d["events"][-1].update(child_transaction_id=self.transaction_id),
                 "child_transaction_id"),
                (lambda d: d["events"][-1].update(child_transaction_id="not-an-id"),
                 "child_transaction_id"),
                (lambda d: d["events"][-1].update(grant_id="never-issued"), "grant"),
                (lambda d: d["events"][-1].update(reason=""), "reason")):
            with self.subTest(fragment=fragment):
                changed = copy.deepcopy(document)
                edited(changed)
                self.assertRuleRefuses(self.transaction_id, changed, fragment)
        self.assertRuleRefuses(self.transaction_id, duplicate, "child_transaction_id")
        self.assertEqual(child.recovery["recovers"], self.transaction_id)
```

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_recovery_settle.py 2>&1 | tail -3`.
  Expected: ERRORs, because `TransactionStore` has no `roll_forward`.

- [ ] **Step 3: Implement** the invariants. Write the `roll_forward` docstring from the
  resulting code, including the lock order and the retry that links an existing child once.
  Extend the module docstrings.

- [ ] **Step 4: Verify.**
  Run the slice unit command with all three recovery test files. Expected: `OK`.

```bash
grep -q "def roll_forward" python/agent_tools/transaction_core.py || exit 1
test "$(wc -c < python/agent_tools/transaction_core.py)" -le 64000 || exit 1
```

  Run: `just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.** Stage exactly this task's **Files**, then:

```bash
git commit -m "feat(transaction-core): roll forward into a linked child transaction (#208)"
```

- [ ] **Step 6: Check the review budget** with `FILES="python/agent_tools/transaction_recovery.py python/agent_tools/transaction_history.py python/agent_tools/transaction_core.py tests/test_transaction_recovery_settle.py"`.
  Expected: exit 0.

Decisions: per D11, D12, D19, D20, D24.
