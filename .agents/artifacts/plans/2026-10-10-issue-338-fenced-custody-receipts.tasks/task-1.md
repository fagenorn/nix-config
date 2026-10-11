# Task 1: Core `renew(ttl_ms=…)`

Per D12 this is the one change to the transaction core in this package. Read the root's Global Constraints first.

**Files:**
- Modify: `python/agent_tools/transaction_core.py` (`TransactionStore.renew`)
- Modify: `python/agent_tools/transaction_custody.py` (`LeaseAuthority`)
- Test: `tests/test_transaction_custody.py` (class `RenewTest`)

**Interfaces:**
- Consumes: `TransactionStore.renew(custody)`, `LeaseAuthority.extend_if_due(fence, now)`, `LeaseAuthority.span_lapsed(fence, now)`, as shipped.
- Produces: `TransactionStore.renew(custody: Custody, *, ttl_ms: int | None = None) -> Transaction` and `LeaseAuthority.extend_to(fence: Mapping[str, Mapping[str, Any]], now: int, ttl_ms: int) -> bool`. Task 3's settle step calls `renew(custody, ttl_ms=…)`.

**Invariants:**
- `renew(custody)` with no `ttl_ms` behaves exactly as before: the existing `RenewTest` and `QuiesceTest` cases stay green unedited.
- A `ttl_ms` that is not an `int` of at least 1 (`True` included) is `StateInvalid` before any lock, with no file changed.
- With a valid `ttl_ms` the order is the shipped one: terminal refusal, fenced check, then under the lease lock the parked-window quiesce rule, then the extension. A span that `span_lapsed` reports at that clock reading is `StaleCustody` with nothing written.
- The extension rewrites every lease record of the fence: `ttl_ms` becomes the argument, `expires_at` becomes `now + ttl_ms`, `term` and `renewal_count` gain one, `last_renewed_at` becomes `now`; `epoch`, `instance` and `acquired_at` are kept, whatever the renewal margin says. `state.json` is not written and no event is appended.
- `tests/test_transaction_core_sweep.py` stays green: no attempt word and no provider verb enters a `transaction_*` module. The lease method is named `extend_to` because the neutrality check forbids the identifier `rebase`.

- [ ] **Step 1: Write the failing tests**

Add both methods to `RenewTest` in `tests/test_transaction_custody.py`, before `test_a_lapsed_lease_is_never_renewed`:

```python
    def test_renew_with_a_ttl_rebases_the_lease_in_place_whatever_the_margin(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        state = (self.root / transaction_id / "state.json").read_bytes()
        self.clock.advance(1)  # far outside the renewal margin
        after = self.store.renew(custody, ttl_ms=90_000)
        self.assertEqual((after.custody, after.revision), (custody, 2))
        for key in KEYS:
            record = self.store.inspect_lease(key)
            holder = record["holder"]
            self.assertEqual(record["epoch"], 1)
            self.assertEqual(
                (holder["instance"], holder["term"], holder["renewal_count"],
                 holder["ttl_ms"], holder["last_renewed_at"], holder["expires_at"],
                 holder["acquired_at"]),
                (custody.fence[key]["instance"], 2, 1, 90_000, self.clock.now,
                 self.clock.now + 90_000, T0))
        self.assertEqual((self.root / transaction_id / "state.json").read_bytes(), state)

    def test_renew_with_a_ttl_refuses_a_bad_ttl_and_a_lapsed_span(self):
        custody = self.acquire(self.new())
        for ttl in (0, -1, True, 1.5, "1"):
            with self.subTest(ttl=ttl):
                self.assertRefusedUnchanged(
                    StateInvalid, lambda: self.store.renew(custody, ttl_ms=ttl))
        self.clock.advance(TTL)
        self.assertRefusedUnchanged(
            StaleCustody, lambda: self.store.renew(custody, ttl_ms=90_000))
```

- [ ] **Step 2: Run them and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_transaction_custody.py -k renew_with_a_ttl`
Expected: both fail with `TypeError: TransactionStore.renew() got an unexpected keyword argument 'ttl_ms'`.

- [ ] **Step 3: Implement**

`LeaseAuthority.extend_to` is called under `locked()` after the lock-free fenced check, like `extend_if_due`: it returns `False` with nothing written when `span_lapsed(fence, now)`, else rewrites each record as the invariant above states and returns `True`.

`TransactionStore.renew` validates `ttl_ms` before `_transaction_locked`, keeps its body, and in the final branch calls `extend_if_due` when `ttl_ms is None` and `extend_to` otherwise; a `False` from either raises the existing `StaleCustody`. Extend `renew`'s docstring with what a supplied `ttl_ms` does, and give `extend_to` a docstring; write both from the implemented code.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_transaction_custody.py tests/test_transaction_core_sweep.py`
Expected: `OK`. The task is incomplete if any `RenewTest`, `QuiesceTest` or `NeutralityTest` case fails.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/transaction_core.py python/agent_tools/transaction_custody.py tests/test_transaction_custody.py
launch-commit … -- -m "feat(transaction-core): renew a lease to a declared ttl in place (#338)"
```
