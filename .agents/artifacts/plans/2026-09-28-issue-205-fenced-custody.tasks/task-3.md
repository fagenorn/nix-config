# Task 3: Lease authority, `acquire`/`release`/`inspect_lease`, the fenced check and custody validation

**Files:**
- Create: `python/agent_tools/transaction_custody.py`
- Create: `tests/test_transaction_custody.py`
- Modify: `python/agent_tools/transaction_storage.py` (new error classes)
- Modify: `python/agent_tools/transaction_core.py`
- Modify: `tests/test_transaction_core_sweep.py` (`NEUTRAL_MODULES` gains `transaction_custody`)
- Modify: `justfile` (add `tests/test_transaction_custody.py \` after `tests/test_transaction_core.py \` in `agent-workflow-tests`)

**Interfaces:**
- Consumes (Tasks 1–2): storage primitives (`read_json`, `atomic_write`, `open_lock`,
  `require_directory`, `lstat_mode`, `fsync_directory`), `self._now()`, `_format_at`,
  `self._transaction_locked(id)`, `self._validated_document(id)`, v2 `_validate_state`
  with its `custody` fold variable, `Transaction.custody`.
- Produces, `transaction_storage`: `FenceViolation(TransactionError)`,
  `StaleCustody(FenceViolation)`, `CustodyMisbound(FenceViolation)`,
  `GrantInvalid(FenceViolation)`, `LeaseUnavailable(TransactionError)`, all re-exported by
  `transaction_core`.
- Produces, `transaction_custody`: `LEASE_SCHEMA = "transaction-lease/v1"`,
  `CUSTODY_EVENTS = frozenset({"lease_acquired", "lease_reacquired", "lease_released",
  "lease_lapse_detected"})`, `renewal_margin_ms(ttl_ms: int) -> int`, and
  `LeaseAuthority(root: Path)` with: `locked()` (context manager over
  `open_lock(root / "leases.lock")`), `record(key) -> dict | None` (validated
  `<root>/leases/<sha256(key)>.json`, `None` if absent), `span_lapsed(fence, now) -> bool`,
  `first_live_key(keys, now) -> str | None`, `next_fence(keys) -> dict` (reads epochs,
  mints one `lin_` instance), `hold(fence, *, transaction_id, executor_id, ttl_ms, now)`,
  `clear(fence)`. `hold`/`clear` require the caller to hold `locked()`.
- Produces, `transaction_core`: frozen `Custody(transaction_id: str, executor_id: str,
  subject_path: str, fence: Mapping[str, Mapping[str, Any]])`;
  `TransactionStore.acquire(self, transaction_id, *, executor_id: str, subject_path: str, ttl_ms: int) -> Transaction`;
  `TransactionStore.release(self, custody: Custody) -> Transaction`;
  `TransactionStore.inspect_lease(self, key: str) -> Mapping[str, Any] | None`; private
  `self._check_custody(prior: dict, custody: Custody, now: int) -> None` and
  `_require_custody_shape(custody) -> None` — Tasks 4–6 call both.

**Invariants:**
- Lease record: closed `{schema, key, epoch, holder}`; `holder` null or closed
  `{transaction_id, executor_id, instance, term, ttl_ms, acquired_at, expires_at,
  renewal_count, last_renewed_at}`; live iff `now < expires_at` (D6).
- `acquire` is all-or-nothing over the whole key set: any live key — including this
  transaction's own live custody — is `LeaseUnavailable` with nothing written; every
  acquisition sets each key's epoch to prior + 1 (1 if never held), one fresh instance,
  term 1 (D7).
- Write order: acquisition validates its candidate, then writes records, then
  `state.json`; release writes `state.json`, then clears records (D8). Locks: transaction
  then lease, non-blocking.
- `span_lapsed(fence, now)` is true when any key's record is missing, holds no holder, names
  another instance or epoch, or has `now >= expires_at`; reap (Task 6) and acquisition
  use only this predicate (D24).
- `clear` nulls `holder` only on records whose holder instance equals the fence's (D24).
- Fenced check order, under the transaction lock, before any write: projection is `None`
  or credential `transaction_id`/`executor_id`/fence differs → `StaleCustody`;
  `subject_path` differs → `CustodyMisbound`; `span_lapsed` → `StaleCustody`. It reads
  records without the lease lock at one `now` (D12, D25). A refusal records nothing.
- Terminal transactions refuse `acquire` and `release` with `TransitionRefused` before
  the fence check (D27).
- Shape errors are `StateInvalid` before any lock: empty `executor_id`; `subject_path`
  not a `str`, not absolute, or `!= os.path.normpath(subject_path)`; `ttl_ms` not a
  positive `int` (`bool` refused); `custody` not a `Custody` or a malformed fence (D21).

- [ ] **Step 1: Write the failing tests** — create `tests/test_transaction_custody.py`:

```python
"""Transaction core slice 2: fenced custody (#205).

Run: just agent-workflow-tests
"""

import copy
import dataclasses
import fcntl
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from agent_tools.transaction_core import (
    Custody, CustodyMisbound, FenceViolation, GrantInvalid, LeaseUnavailable, StaleCustody,
    StateInvalid, TransactionBusy, TransactionError, TransactionStore, TransitionRefused)

T0 = 1_800_000_000_000
TTL = 600_000
KEYS = ("target:alpha", "project:alpha")
SUBJECT = {"candidate": "sha256:abc"}
PATH = "/work/alpha"
INSTANCE = re.compile(r"lin_[0-9a-f]{32}")


class FakeClock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, ms):
        self.now += ms


def plain(fence):
    return {key: dict(value) for key, value in fence.items()}


def serialize(document):
    return json.dumps(document, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False) + "\n"


class CustodyCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.clock = FakeClock()
        self.store = TransactionStore(self.root, clock=self.clock)

    def new(self, key="k", keys=KEYS):
        return self.store.create(key, SUBJECT, concurrency_keys=keys).transaction_id

    def acquire(self, transaction_id, executor="exec-a", path=PATH, ttl=TTL):
        return self.store.acquire(transaction_id, executor_id=executor, subject_path=path,
                                  ttl_ms=ttl).custody

    def lease_path(self, key):
        return self.root / "leases" / f"{hashlib.sha256(key.encode()).hexdigest()}.json"

    def files(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in sorted(self.root.rglob("*")) if p.is_file()}

    def assertRefusedUnchanged(self, error, call):
        before = self.files()
        with self.assertRaises(error) as caught:
            call()
        self.assertEqual(self.files(), before)
        return caught.exception

    def types(self, transaction_id):
        return [e["type"] for e in self.store.load(transaction_id).events]

    def state_doc(self, transaction_id):
        return json.loads((self.root / transaction_id / "state.json").read_text())

    def assertRuleRefuses(self, transaction_id, document, fragment):
        (self.root / transaction_id / "state.json").write_text(serialize(document))
        with self.assertRaises(StateInvalid) as caught:
            self.store.load(transaction_id)
        self.assertIn(transaction_id, str(caught.exception))
        self.assertIn(fragment, str(caught.exception))


class AcquireTest(CustodyCase):
    def test_a_first_acquisition_grants_epoch_one_and_appends_one_event(self):
        transaction_id = self.new()
        after = self.store.acquire(transaction_id, executor_id="exec-a", subject_path=PATH,
                                   ttl_ms=TTL)
        custody = after.custody
        self.assertEqual(sorted(custody.fence), sorted(KEYS))
        instances = {entry["instance"] for entry in custody.fence.values()}
        self.assertEqual(len(instances), 1)
        [instance] = instances
        self.assertRegex(instance, INSTANCE)
        self.assertEqual({entry["epoch"] for entry in custody.fence.values()}, {1})
        self.assertEqual((custody.transaction_id, custody.executor_id, custody.subject_path),
                         (transaction_id, "exec-a", PATH))
        self.assertEqual((after.state, after.revision), ("created", 2))
        event = dict(after.events[-1])
        self.assertEqual(event["type"], "lease_acquired")
        self.assertEqual(set(event), {"seq", "type", "at", "executor_id", "subject_path",
                                      "fence"})
        self.assertEqual(event["fence"], plain(custody.fence))
        self.assertEqual(self.state_doc(transaction_id)["custody"], {
            "executor_id": "exec-a", "subject_path": PATH, "fence": plain(custody.fence)})
        for key in KEYS:
            self.assertEqual(dict(self.store.inspect_lease(key)), {
                "schema": "transaction-lease/v1", "key": key, "epoch": 1, "holder": {
                    "transaction_id": transaction_id, "executor_id": "exec-a",
                    "instance": instance, "term": 1, "ttl_ms": TTL, "acquired_at": T0,
                    "expires_at": T0 + TTL, "renewal_count": 0, "last_renewed_at": None}})
        self.assertIsNone(self.store.inspect_lease("never:held"))
        self.assertEqual(TransactionStore(self.root).load(transaction_id).custody, custody)

    def test_a_live_key_refuses_every_acquirer_including_its_own_holder(self):
        first = self.new("a")
        self.acquire(first)
        sharing = self.new("b", keys=("project:alpha", "target:beta"))
        self.assertRefusedUnchanged(LeaseUnavailable, lambda: self.acquire(first))
        error = self.assertRefusedUnchanged(LeaseUnavailable, lambda: self.acquire(sharing))
        self.assertIn("project:alpha", str(error))
        disjoint = self.new("c", keys=("project:gamma",))
        self.assertIsNotNone(self.acquire(disjoint))

    def test_release_keeps_the_epoch_and_every_reacquisition_advances_it(self):
        transaction_id = self.new()
        first = self.acquire(transaction_id)
        released = self.store.release(first)
        self.assertIsNone(released.custody)
        self.assertEqual(dict(released.events[-1]), {
            "seq": 3, "type": "lease_released", "at": released.events[-1]["at"],
            "fence": plain(first.fence), "reason": "released"})
        for key in KEYS:
            self.assertEqual((self.store.inspect_lease(key)["epoch"],
                              self.store.inspect_lease(key)["holder"]), (1, None))
        second = self.acquire(transaction_id, executor="exec-b")
        event = dict(self.store.load(transaction_id).events[-1])
        self.assertEqual((event["type"], event["reason"], event["prior_executor_id"]),
                         ("lease_reacquired", "released", "exec-a"))
        self.assertEqual(event["prior_fence"], plain(first.fence))
        self.assertEqual({entry["epoch"] for entry in second.fence.values()}, {2})
        self.assertNotEqual(plain(second.fence), plain(first.fence))

    def test_acquisition_over_an_unreaped_lapse_records_the_lapse_first(self):
        transaction_id = self.new()
        first = self.acquire(transaction_id)
        self.clock.advance(TTL)
        second = self.acquire(transaction_id, executor="exec-b")
        events = self.store.load(transaction_id).events
        self.assertEqual([e["type"] for e in events[-2:]],
                         ["lease_lapse_detected", "lease_reacquired"])
        self.assertEqual((events[-2]["fence"], events[-2]["executor_id"]),
                         (plain(first.fence), "exec-a"))
        self.assertEqual(events[-1]["reason"], "expired")
        self.assertEqual({entry["epoch"] for entry in second.fence.values()}, {2})

    def test_a_stale_release_never_evicts_a_successor_on_a_shared_key(self):
        first = self.new("a")
        stale = self.acquire(first)
        self.clock.advance(TTL)
        successor = self.new("b", keys=("project:alpha", "target:beta"))
        taken = self.acquire(successor, executor="exec-b", path="/work/beta")
        self.assertEqual(taken.fence["project:alpha"]["epoch"], 2)
        self.assertEqual(taken.fence["target:beta"]["epoch"], 1)
        self.assertRefusedUnchanged(StaleCustody, lambda: self.store.release(stale))
        self.assertRefusedUnchanged(LeaseUnavailable, lambda: self.acquire(first))
        self.assertEqual(self.store.inspect_lease("project:alpha")["holder"]["instance"],
                         taken.fence["project:alpha"]["instance"])

    def test_an_unrecorded_grant_blocks_its_keys_only_until_its_ttl(self):
        transaction_id = self.new()
        self.lease_path(KEYS[0]).parent.mkdir()
        (self.root / "leases.lock").touch()  # the lock file itself is not a write
        self.lease_path(KEYS[0]).write_text(serialize({
            "schema": "transaction-lease/v1", "key": KEYS[0], "epoch": 4, "holder": {
                "transaction_id": transaction_id, "executor_id": "ghost",
                "instance": "lin_" + "0" * 32, "term": 1, "ttl_ms": TTL,
                "acquired_at": T0, "expires_at": T0 + TTL, "renewal_count": 0,
                "last_renewed_at": None}}))
        self.assertRefusedUnchanged(LeaseUnavailable, lambda: self.acquire(transaction_id))
        self.clock.advance(TTL)
        custody = self.acquire(transaction_id)
        self.assertEqual(custody.fence[KEYS[0]]["epoch"], 5)
        self.assertEqual(self.types(transaction_id)[-1], "lease_acquired")


class FenceCheckTest(CustodyCase):
    def test_a_stale_or_forged_credential_is_refused_before_any_write(self):
        transaction_id = self.new()
        other = self.new("other", keys=("project:other",))
        custody = self.acquire(transaction_id)
        bumped = {k: {**v, "epoch": v["epoch"] + 1} for k, v in plain(custody.fence).items()}
        for forged in (dataclasses.replace(custody, executor_id="exec-z"),
                       dataclasses.replace(custody, transaction_id=other),
                       dataclasses.replace(custody, fence=bumped)):
            with self.subTest(forged=forged):
                self.assertRefusedUnchanged(StaleCustody, lambda: self.store.release(forged))
        self.store.release(custody)
        self.assertRefusedUnchanged(StaleCustody, lambda: self.store.release(custody))
        self.assertTrue(issubclass(StaleCustody, FenceViolation))
        self.assertTrue(issubclass(FenceViolation, TransactionError))

    def test_a_lapsed_lease_is_refused_and_the_lapse_is_not_recorded(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        self.clock.advance(TTL)
        self.assertRefusedUnchanged(StaleCustody, lambda: self.store.release(custody))
        self.assertEqual(self.types(transaction_id), ["created", "lease_acquired"])

    def test_the_first_acquisition_binds_the_subject_path(self):
        transaction_id = self.new()
        self.store.release(self.acquire(transaction_id))
        self.assertRefusedUnchanged(CustodyMisbound,
                                    lambda: self.acquire(transaction_id, path="/work/beta"))
        custody = self.acquire(transaction_id)
        moved = dataclasses.replace(custody, subject_path="/work/beta")
        self.assertRefusedUnchanged(CustodyMisbound, lambda: self.store.release(moved))
        self.assertTrue(issubclass(CustodyMisbound, FenceViolation))

    def test_argument_shapes_are_refused_before_any_lock(self):
        transaction_id = self.new()
        for kwargs in ({"executor_id": ""}, {"subject_path": "work/alpha"},
                       {"subject_path": "/work/../alpha"}, {"subject_path": "/work/alpha/"},
                       {"ttl_ms": 0}, {"ttl_ms": -1}, {"ttl_ms": True}, {"ttl_ms": 1.5}):
            arguments = {"executor_id": "e", "subject_path": PATH, "ttl_ms": TTL, **kwargs}
            with self.subTest(kwargs=kwargs):
                self.assertRefusedUnchanged(
                    StateInvalid, lambda: self.store.acquire(transaction_id, **arguments))
        for bad in ("not custody", Custody(transaction_id, "e", PATH, {"k": {"epoch": 1}})):
            with self.subTest(bad=bad):
                self.assertRefusedUnchanged(StateInvalid, lambda: self.store.release(bad))

    def test_lock_contention_is_busy_and_writes_nothing(self):
        transaction_id = self.new()
        self.store.release(self.acquire(transaction_id))
        for lock in (self.root / transaction_id / "lock", self.root / "leases.lock"):
            with self.subTest(lock=lock.name), open(lock, "r+") as holder:
                fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertRefusedUnchanged(TransactionBusy,
                                            lambda: self.acquire(transaction_id))

    def test_terminal_transactions_refuse_acquisition(self):
        transaction_id = self.new()
        self.store.advance(transaction_id, "abandoned", reason="r", external_state="known")
        self.assertRefusedUnchanged(TransitionRefused, lambda: self.acquire(transaction_id))


def span(event):
    """The custody projection an opening event folds to."""
    return {"executor_id": event["executor_id"], "subject_path": event["subject_path"],
            "fence": event["fence"]}


def history(base, *events, custody):
    """`base` with `events` after its created event, seqs, revision and projection honest."""
    numbered = [base["events"][0]] + [{**event, "seq": seq}
                                      for seq, event in enumerate(events, start=2)]
    return {**base, "events": numbered, "revision": len(numbered), "custody": custody}


class CustodyValidatorTest(CustodyCase):
    def test_hand_edited_custody_histories_fail_the_named_rule(self):
        transaction_id = self.new()
        first = self.acquire(transaction_id)
        self.store.release(first)
        self.acquire(transaction_id, executor="exec-b")
        base = self.state_doc(transaction_id)
        acquired, released, reacquired = base["events"][1:4]
        low = {k: {**v, "epoch": 1} for k, v in reacquired["fence"].items()}
        rebound = {**reacquired, "subject_path": "/work/beta"}
        lowered = {**reacquired, "fence": low}
        cases = {
            "custody projection forged": (
                {**base, "custody": None}, "custody does not equal the folded custody"),
            "second open span": (
                history(base, acquired, acquired, custody=span(acquired)),
                "follows an earlier custody span"),
            "prior fence mismatch": (
                history(base, acquired, released, {**reacquired,
                                                   "prior_fence": reacquired["fence"]},
                        custody=span(reacquired)), "prior_fence"),
            "epoch not increasing": (
                history(base, acquired, released, lowered, custody=span(lowered)),
                "epoch does not increase"),
            "rebound path": (
                history(base, acquired, released, rebound, custody=span(rebound)),
                "subject_path differs from the bound path"),
            "false reason": (
                history(base, acquired, released, {**reacquired, "reason": "expired"},
                        custody=span(reacquired)),
                "reason does not match how the prior span closed"),
            "false prior executor": (
                history(base, acquired, released, {**reacquired,
                                                   "prior_executor_id": "exec-z"},
                        custody=span(reacquired)), "prior_executor_id"),
            "release without span": (
                history(base, released, custody=None), "closes no open custody span"),
            "unknown type": (
                history(base, {**acquired, "type": "lease_renewed"}, custody=None),
                "unknown event type 'lease_renewed'"),
            "extra field": (
                history(base, {**acquired, "term": 2}, custody=span(acquired)),
                "is not the closed lease_acquired event"),
        }
        for name, (document, fragment) in cases.items():
            with self.subTest(case=name):
                self.assertRuleRefuses(transaction_id, copy.deepcopy(document), fragment)


if __name__ == "__main__":
    unittest.main()
```

Each case keeps seqs, `revision` and the `custody` projection honest (`history`), so only
the named rule can fire; the fragment is part of that rule's message (step 3.4). `span`,
`history` and `CustodyCase.assertRuleRefuses` are reused by Tasks 5 and 6.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_custody.py 2>&1 | tail -3`
Expected: FAIL — `ImportError: cannot import name 'Custody'`.

- [ ] **Step 3: Write the minimal implementation**

1. Errors in `transaction_storage` with one-line docstrings from the spec's Errors
   section; re-export from `transaction_core`.
2. `transaction_custody`: records at `<root>/leases/<sha256(key utf-8)>.json`; the
   directory is created on first `hold` like slice 1's `creation-keys` (lstat-guarded,
   parent fsynced). `record(key)` refuses a record whose `key` differs, non-int or
   `bool` integers, `epoch < 1`, or a malformed holder, as `StateInvalid` naming the
   path. `next_fence(keys)` → `{key: {"epoch": (record epoch or 0) + 1, "instance":
   "lin_" + secrets.token_hex(16)}}` with one instance. `hold` writes each record with
   `term 1, renewal_count 0, last_renewed_at None, acquired_at now, expires_at now +
   ttl_ms`. `clear(fence)` rewrites each record whose holder instance matches with
   `holder: None`, keeping `epoch`. `renewal_margin_ms` per Global Constraints.
3. `Custody` frozen dataclass; snapshots carry `fence` as a `MappingProxyType` over deep
   copies (top level read-only, like slice 1's `subject`). `_require_custody_shape`:
   `isinstance(custody, Custody)`, non-empty `str` ids, fence a `Mapping` of `str` →
   `Mapping` with exactly `{"epoch", "instance"}`, `epoch` an `int >= 1` (not `bool`),
   `instance` matching `lin_[0-9a-f]{32}`.
4. Validator fold (extend Task 2's per-type dispatch; `_EVENT_KEYS` maps each type to
   its closed key set): track `custody` (open span or `None`), `bound_path`, `spans`
   (list of `(executor_id, fence)`), `last_close` (`"released"`/`"lapsed"`/`None`).
   `lease_acquired` only with no span ever; `lease_reacquired` only with spans and none
   open, `prior_fence`/`prior_executor_id` equal to the last span, every key's epoch
   strictly greater, `subject_path == bound_path`, `reason == "expired"` iff
   `last_close == "lapsed"` else `"released"` (D30). Every fence has exactly the
   `concurrency_keys`, one shared instance, epochs `>= 1`; `subject_path` absolute and
   normalized; `executor_id` non-empty. `lease_released` needs an open span with an equal
   fence and `reason` in `released`/`quiesced`/`terminal` — `quiesced` only while the
   folded state is a parking, `terminal` only as the event immediately after a
   transition into a terminal. `lease_lapse_detected` needs an open span with equal fence
   and executor. After a terminal, the only event allowed is that one `terminal`
   release; a terminal with custody still open at the end is refused. The folded
   custody `{executor_id, subject_path, fence}` must equal `document["custody"]`.
   Messages follow slice 1's `f"event {seq} …"` shape and contain these exact fragments,
   which the tests assert: `custody does not equal the folded custody`, `follows an
   earlier custody span`, `prior_fence`, `prior_executor_id`, `epoch does not increase`,
   `subject_path differs from the bound path`, `reason does not match how the prior span
   closed`, `closes no open custody span`, and `is not the closed <type> event` for a
   key-set mismatch. The dispatch's default branch (Task 2) already refuses
   `unknown event type '<type>'`.
5. `acquire`: shape checks → `_transaction_locked` → `prior` → terminal refusal →
   `bound_path` (from the first `lease_acquired`) differs → `CustodyMisbound` →
   `LeaseAuthority.locked()` → `now = self._now()` → if `prior["custody"]` is open and
   `span_lapsed`, queue `lease_lapse_detected {fence, executor_id}`; if open and live,
   `LeaseUnavailable` → `first_live_key` → `LeaseUnavailable` naming it → `next_fence` →
   build and `_validate_state` the candidate (`lease_acquired` or `lease_reacquired`
   with `reason` per the fold, `custody` projection set) → `hold` → `atomic_write`
   state → snapshot.
6. `release(custody)`: shape → lock → `prior` → terminal refusal → `_check_custody` →
   `locked()` → candidate with `lease_released {fence, reason: "released"}`, `custody:
   None` → validate → write state → `clear(fence)`.
7. `inspect_lease(key)`: non-empty `str` else `StateInvalid`; returns
   `MappingProxyType(copy.deepcopy(record))` or `None`; no lock, no write.
8. `_snapshot` builds `Custody(transaction_id, **projection)` when the projection is set.
   Rewrite the `Transaction` docstring's second paragraph to: "`subject`, each event and
   `custody.fence` (with each fence entry) are `types.MappingProxyType` views over deep
   copies. Only those levels are read-only: nested values stay mutable, but they are
   copies, so mutating them cannot reach disk." Rewrite the `StateInvalid` docstring (in
   `transaction_storage`) to: "A stored file, the layout, or an operation's arguments fail
   the closed schema."
9. Add `transaction_custody` to `NEUTRAL_MODULES`; add the test file to the justfile.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_custody.py tests/test_transaction_core.py tests/test_transaction_core_sweep.py 2>&1 | tail -3`
Expected: `OK` (Task 2 count + 13 tests).

Run: `grep -c 'tests/test_transaction_custody.py' justfile` — Expected: `1`.

Run: `just agent-workflow-tests 2>&1 | tail -3` — Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/transaction_custody.py python/agent_tools/transaction_storage.py \
  python/agent_tools/transaction_core.py tests/test_transaction_custody.py \
  tests/test_transaction_core_sweep.py justfile
git commit -m "feat(transaction-core): add the fenced lease authority and custody (#205)"
```
