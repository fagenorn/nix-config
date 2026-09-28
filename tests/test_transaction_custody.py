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
