# Task 4: Renewal duty, custody quiesce, fenced `advance` and terminal release

**Files:**
- Modify: `python/agent_tools/transaction_custody.py`
- Modify: `python/agent_tools/transaction_core.py`
- Modify: `tests/test_transaction_custody.py` (append classes before `if __name__`)
- Modify: `tests/test_transaction_core.py` (`AdvanceCase` holds custody; one assertion rewrite)
- Modify: `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py`
  (the executor acquires custody before publishing; history helpers skip custody events)

**Interfaces:**
- Consumes (Task 3): `Custody`, `LeaseAuthority` (`locked`, `record`, `span_lapsed`,
  `clear`), `renewal_margin_ms`, `self._check_custody(prior, custody, now)`,
  `_require_custody_shape(custody)`, `self._transaction_locked(id)`, `self._now()`,
  `_parse_at(at)`, `StaleCustody`, `CustodyMisbound`, `TransitionRefused`; test helpers
  `CustodyCase`, `FakeClock`, `plain`, `T0`, `TTL`, `KEYS`, `PATH`.
- Produces: `PARKED_CUSTODY_WINDOW_MS = 900_000` (exported from `transaction_core`);
  `LeaseAuthority.extend_if_due(fence, now: int) -> bool`;
  `TransactionStore.renew(self, custody: Custody) -> Transaction`;
  `TransactionStore.advance(self, transaction_id, target, *, reason, external_state=None, custody: Custody | None = None) -> Transaction`;
  private `_parked_since(events) -> int | None`. Task 8's executor calls `renew` and
  `advance(..., custody=...)` exactly so.

**Invariants:**
- `renew` never appends an event and never writes `state.json`; it writes lease records
  only when the group's earliest remaining validity (`expires_at - now`) is below
  `renewal_margin_ms(ttl_ms)`, then bumps every key's `term` and `renewal_count`, sets
  `last_renewed_at = now`, `expires_at = now + ttl_ms`, keeping `epoch` and `instance`
  (D13). Outside the margin it writes nothing at all.
- `renew` runs the full fenced check first: a lapsed lease is `StaleCustody`, never
  silently reacquired.
- While parked, once `now - _parked_since(events) > PARKED_CUSTODY_WINDOW_MS`, `renew`
  instead appends `lease_released {fence, reason: "quiesced"}`, writes state, then clears
  records, and returns a snapshot with `custody is None` (D19, D28).
- `advance` requires custody when the target is `publishing`, any prior `transitioned`
  event reached `publishing`, or the transaction holds custody; a required custody that
  is `None` is `StaleCustody`; a presented custody is always checked (D14, D26, D27).
- A terminal source refuses `advance`, `renew` and `release` with `TransitionRefused`
  before the fence check (D27).
- Entering a terminal while custody is held appends `transitioned` then
  `lease_released {fence, reason: "terminal"}` in one state write, then clears records.

- [ ] **Step 1: Write the failing tests**

1. Append to `tests/test_transaction_custody.py` (add `PARKED_CUSTODY_WINDOW_MS` to the
   `agent_tools.transaction_core` import):

```python
class RenewTest(CustodyCase):
    def test_outside_the_margin_renewal_writes_nothing(self):
        custody = self.acquire(self.new())
        self.clock.advance(TTL // 2 - 1)
        before = self.files()
        self.assertEqual(self.store.renew(custody).custody, custody)
        self.assertEqual(self.files(), before)

    def test_inside_the_margin_renewal_extends_in_place_without_history(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        state = (self.root / transaction_id / "state.json").read_bytes()
        for turn in (1, 2):
            self.clock.advance(TTL // 2 + 1)
            after = self.store.renew(custody)
            self.assertEqual((after.custody, after.revision), (custody, 2))
            for key in KEYS:
                record = self.store.inspect_lease(key)
                holder = record["holder"]
                self.assertEqual(record["epoch"], 1)
                self.assertEqual(
                    (holder["instance"], holder["term"], holder["renewal_count"],
                     holder["last_renewed_at"], holder["expires_at"], holder["acquired_at"]),
                    (custody.fence[key]["instance"], 1 + turn, turn, self.clock.now,
                     self.clock.now + TTL, T0))
        self.assertEqual((self.root / transaction_id / "state.json").read_bytes(), state)

    def test_the_margin_is_half_the_ttl_floored_at_a_minute_and_capped_at_the_ttl(self):
        for ttl, quiet, due in ((90_000, 29_999, 2), (30_000, 0, 1), (200_000, 99_999, 2)):
            with self.subTest(ttl=ttl):
                key = f"key:{ttl}"
                custody = self.acquire(self.new(key, keys=(key,)), ttl=ttl)
                self.clock.advance(quiet)
                self.store.renew(custody)
                self.assertEqual(self.store.inspect_lease(key)["holder"]["term"], 1)
                self.clock.advance(due)
                self.store.renew(custody)
                self.assertEqual(self.store.inspect_lease(key)["holder"]["term"], 2)

    def test_a_lapsed_lease_is_never_renewed(self):
        custody = self.acquire(self.new())
        self.clock.advance(TTL)
        self.assertRefusedUnchanged(StaleCustody, lambda: self.store.renew(custody))


class QuiesceTest(CustodyCase):
    def park(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        self.store.advance(transaction_id, "attention_required", reason="wait",
                           custody=custody)
        return transaction_id, custody

    def test_parked_custody_is_renewed_up_to_the_window_then_quiesced(self):
        self.assertEqual(PARKED_CUSTODY_WINDOW_MS, 900_000)
        transaction_id, custody = self.park()
        for step in (400_000, 400_000, 100_000):
            self.clock.advance(step)
            self.assertEqual(self.store.renew(custody).custody, custody)
        self.clock.advance(1)
        after = self.store.renew(custody)
        self.assertIsNone(after.custody)
        self.assertEqual((after.events[-1]["type"], after.events[-1]["reason"]),
                         ("lease_released", "quiesced"))
        self.assertEqual({self.store.inspect_lease(k)["holder"] is None for k in KEYS}, {True})
        resumed = self.acquire(transaction_id)
        self.assertEqual(self.store.load(transaction_id).events[-1]["reason"], "released")
        self.assertEqual({entry["epoch"] for entry in resumed.fence.values()}, {2})

    def test_moving_between_parkings_does_not_restart_the_window(self):
        transaction_id, custody = self.park()
        self.clock.advance(400_000)
        self.store.renew(custody)
        self.store.advance(transaction_id, "recovering", reason="try", custody=custody)
        self.clock.advance(400_000)
        self.store.renew(custody)
        self.clock.advance(100_001)
        self.assertIsNone(self.store.renew(custody).custody)

    def test_an_unparked_transaction_is_never_quiesced(self):
        custody = self.acquire(self.new())
        for _ in range(4):
            self.clock.advance(400_000)
            self.assertEqual(self.store.renew(custody).custody, custody)


class FencedAdvanceTest(CustodyCase):
    def step(self, transaction_id, *targets, custody=None):
        for target in targets:
            after = self.store.advance(transaction_id, target, reason="r",
                                       external_state="known", custody=custody)
        return after

    def test_publishing_and_everything_after_it_requires_custody(self):
        transaction_id = self.new()
        self.step(transaction_id, "awaiting_verification", "ready")
        self.assertRefusedUnchanged(StaleCustody, lambda: self.step(transaction_id,
                                                                    "publishing"))
        custody = self.acquire(transaction_id)
        self.step(transaction_id, "publishing", "attention_required", custody=custody)
        self.store.release(custody)
        self.assertRefusedUnchanged(StaleCustody, lambda: self.step(transaction_id,
                                                                    "publishing"))
        again = self.acquire(transaction_id)
        self.assertEqual(self.step(transaction_id, "publishing", custody=again).state,
                         "publishing")

    def test_held_custody_is_required_even_before_publishing(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        self.assertRefusedUnchanged(StaleCustody, lambda: self.step(transaction_id,
                                                                    "abandoned"))
        self.assertEqual(self.step(transaction_id, "awaiting_verification",
                                   custody=custody).state, "awaiting_verification")

    def test_a_presented_custody_is_checked_where_none_is_required(self):
        transaction_id = self.new()
        foreign = self.acquire(self.new("o", keys=("project:other",)))
        forged = dataclasses.replace(foreign, transaction_id=transaction_id)
        self.assertRefusedUnchanged(StaleCustody, lambda: self.step(
            transaction_id, "awaiting_verification", custody=forged))
        self.assertRefusedUnchanged(StateInvalid, lambda: self.step(
            transaction_id, "awaiting_verification", custody="not custody"))

    def test_a_stale_or_misbound_holder_is_refused_and_no_lapse_is_recorded(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        moved = dataclasses.replace(custody, subject_path="/work/beta")
        self.assertRefusedUnchanged(CustodyMisbound, lambda: self.step(
            transaction_id, "awaiting_verification", custody=moved))
        self.clock.advance(TTL)
        self.assertRefusedUnchanged(StaleCustody, lambda: self.step(
            transaction_id, "awaiting_verification", custody=custody))
        self.assertEqual(self.types(transaction_id), ["created", "lease_acquired"])

    def test_entering_a_terminal_releases_custody_in_the_same_write(self):
        for terminal, path in (
                ("succeeded", ("awaiting_verification", "ready", "publishing", "published",
                               "proving", "succeeded")),
                ("abandoned", ("abandoned",))):
            with self.subTest(terminal=terminal):
                key = f"key:{terminal}"
                transaction_id = self.new(terminal, keys=(key,))
                custody = self.acquire(transaction_id)
                after = self.step(transaction_id, *path, custody=custody)
                self.assertIsNone(after.custody)
                self.assertEqual([e["type"] for e in after.events[-2:]],
                                 ["transitioned", "lease_released"])
                self.assertEqual(after.events[-1]["reason"], "terminal")
                self.assertIsNone(self.store.inspect_lease(key)["holder"])
                for call in (lambda: self.step(transaction_id, "created", custody=custody),
                             lambda: self.store.renew(custody),
                             lambda: self.store.release(custody),
                             lambda: self.acquire(transaction_id)):
                    self.assertRefusedUnchanged(TransitionRefused, call)
```

2. `tests/test_transaction_core.py`, `AdvanceCase`: add `setUp` calling `super().setUp()`
   and `self.held = {}`; `reach` creates with `concurrency_keys=[f"key:{key}"]`, then
   `self.held[transaction_id] = self.store.acquire(transaction_id, executor_id="exec",
   subject_path="/work/demo", ttl_ms=3_600_000).custody` before its loop, and passes
   `custody=self.held[transaction_id]` to each advance. `assertRefusedUnchanged` passes
   `custody=kwargs.pop("custody", self.held.get(transaction_id))`. Every other direct
   `self.store.advance(transaction_id, …)` inside an `AdvanceCase` subclass gains
   `custody=self.held[transaction_id]` (the unknown-id and symlink calls stay as they
   are). In `test_the_forward_chain_persists_one_event_per_transition`, take
   `transitions = [e for e in persisted.events if e["type"] == "transitioned"]` and assert
   `persisted.revision == 10`, seqs `1..10`, `[e["to"] for e in transitions] ==
   list(PATHS_TO_TERMINAL["succeeded"])`, `transitions[-1]["external_state"] == "known"`,
   `transitions[0]["reason"] == "to awaiting_verification"` and
   `persisted.events[-1]["type"] == "lease_released"`.
3. Sweep: in `drive`, keep a `held = {"custody": None}`; `advance()` passes
   `custody=held["custody"]`; immediately before `advance("publishing", …)` set
   `held["custody"] = store.acquire(transaction_id, executor_id="fixture-executor",
   subject_path=f"/fixture/{shape}", ttl_ms=600_000).custody`. In the sweep test,
   `states_passed` and the `external_state` assertion read only events whose `type` is
   `"transitioned"`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_custody.py 2>&1 | tail -3`
Expected: FAIL — `ImportError: cannot import name 'PARKED_CUSTODY_WINDOW_MS'`.

- [ ] **Step 3: Write the minimal implementation**

1. `extend_if_due(fence, now)`: read every key's record; if
   `min(expires_at) - now >= renewal_margin_ms(ttl_ms)` return `False` without writing;
   otherwise rewrite every record per the invariant and return `True`. Caller holds
   `locked()` and has already passed the fenced check.
2. `_parked_since(events)`: walk `transitioned` events keeping `start`: set it to
   `_parse_at(at)` when a transition enters a parking from a non-parking source, clear it
   when a transition leaves the parkings; return `start` (D28).
3. `renew(custody)`: shape → `_transaction_locked` → `prior` → terminal refusal →
   `now` → `_check_custody` → `locked()` → if `prior["state"]` is a parking and
   `now - _parked_since(...) > PARKED_CUSTODY_WINDOW_MS`: quiesce per the invariant;
   else `extend_if_due` and return `_snapshot(prior)`.
4. `advance(..., custody=None)`: `custody` not `None` → `_require_custody_shape` before
   the lock. Under the lock, after `prior` and the terminal-source refusal: compute
   `required`; `required and custody is None` → `StaleCustody`; `custody is not None` →
   `_check_custody(prior, custody, now)`; then slice 1's lifecycle refusals unchanged.
   When the target is terminal and custody is held, take `locked()`, append the terminal
   release, set `custody: None`, validate, write state, then `clear(fence)`. One `now`
   stamps every event of the write.
5. Docstrings of `renew` and `advance` state these rules as implemented.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_custody.py tests/test_transaction_core.py tests/test_transaction_core_sweep.py 2>&1 | tail -3`
Expected: `OK` (Task 3 count + 12 tests).

Run: `just agent-workflow-tests 2>&1 | tail -3` — Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/transaction_custody.py python/agent_tools/transaction_core.py \
  tests/test_transaction_custody.py tests/test_transaction_core.py \
  tests/transaction_core_sweep_support.py tests/test_transaction_core_sweep.py
git commit -m "feat(transaction-core): renew, quiesce and fence lifecycle advances (#205)"
```
