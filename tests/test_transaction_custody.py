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
    PARKED_CUSTODY_WINDOW_MS, Custody, CustodyMisbound, FenceViolation, GrantInvalid,
    LeaseUnavailable, StaleCustody, StateInvalid, TransactionBusy, TransactionError,
    TransactionStore, TransitionRefused)

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

    def test_a_malformed_credential_subject_path_is_refused_before_any_lock(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        with open(self.root / transaction_id / "lock", "r+") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for path in (123, None, "work/alpha", "/work/../alpha", "/work/alpha/"):
                bad = dataclasses.replace(custody, subject_path=path)
                for call in (self.store.release, self.store.renew):
                    with self.subTest(path=path, call=call.__name__):
                        error = self.assertRefusedUnchanged(StateInvalid, lambda: call(bad))
                        self.assertIn(transaction_id, str(error))
                        self.assertIn("subject_path", str(error))

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

    def test_a_key_taken_after_the_lock_free_check_is_refused_under_the_lease_lock(self):
        first = self.new("a")
        custody = self.acquire(first)
        successor = self.new("b", keys=("project:alpha", "target:beta"))
        successor_store = TransactionStore(self.root, clock=FakeClock(T0 + TTL))
        taken = []

        class Root(type(self.root)):
            """Runs the successor once, when renew joins `leases.lock`: after its lock-free
            fenced check, before it takes the lease lock (pathlib's public subclass hook)."""
            armed = False

            def with_segments(root, *segments):
                if Root.armed and segments[-1] == "leases.lock":
                    Root.armed = False
                    successor_store.acquire(successor, executor_id="exec-b",
                                            subject_path="/work/beta", ttl_ms=TTL)
                    taken.append(self.files())
                return type(root)(*segments)

        store = TransactionStore(Root(self.root), clock=self.clock)
        self.clock.advance(TTL - 1)
        Root.armed = True
        with self.assertRaises(StaleCustody) as caught:
            store.renew(custody)
        self.assertEqual(self.files(), taken[0])
        self.assertIn(first, str(caught.exception))
        self.assertIn("lapsed", str(caught.exception))
        holder = self.store.inspect_lease("project:alpha")["holder"]
        self.assertEqual((holder["executor_id"], holder["term"], holder["expires_at"]),
                         ("exec-b", 1, T0 + 2 * TTL))


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


class EvidenceTest(CustodyCase):
    def test_evidence_is_stamped_with_the_current_fence(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        after = self.store.record_evidence(custody, evidence_id="e1", form="snapshot",
                                           reference="evidence://a")
        event = dict(after.events[-1])
        self.assertEqual(set(event), {"seq", "type", "at", "evidence_id", "form",
                                      "reference", "fence"})
        self.assertEqual(event["fence"], plain(custody.fence))
        [entry] = after.evidence
        self.assertEqual(dict(entry), {
            "evidence_id": "e1", "form": "snapshot", "reference": "evidence://a",
            "fence": plain(custody.fence), "seq": 3, "admissible": True,
            "void_reason": None})
        self.assertEqual(TransactionStore(self.root).load(transaction_id).evidence,
                         after.evidence)

    def test_a_lapse_advances_the_epoch_and_voids_snapshots_while_renewal_does_neither(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        self.store.record_evidence(custody, evidence_id="s1", form="snapshot",
                                   reference="r")
        self.store.record_evidence(custody, evidence_id="e1", form="event", reference="r")
        self.store.open_interval(custody, evidence_id="i1")
        self.store.issue_grant(custody, grant_id="g0", actor="publisher")
        self.clock.advance(TTL // 2 + 1)
        self.store.renew(custody)
        self.store.record_evidence(custody, evidence_id="i1", form="interval",
                                   reference="r")
        self.store.issue_grant(custody, grant_id="g1", actor="publisher")
        renewed = self.store.load(transaction_id)
        self.assertEqual([e["admissible"] for e in renewed.evidence], [True, True, True])
        self.assertEqual([g["valid"] for g in renewed.grants], [True, True])
        for grant_id in ("g0", "g1"):  # a grant issued before the renewal survives it
            self.assertEqual(self.store.check_grant(custody, grant_id)["grant_id"], grant_id)
        self.assertEqual((self.store.inspect_lease(KEYS[0])["epoch"],
                          self.store.inspect_lease(KEYS[0])["holder"]["term"]), (1, 2))
        self.assertEqual([t for t in self.types(transaction_id) if t.startswith("lease_")],
                         ["lease_acquired"])

        self.clock.advance(TTL)
        successor = self.acquire(transaction_id, executor="exec-b")
        self.assertEqual(self.store.inspect_lease(KEYS[0])["epoch"], 2)
        lapsed = self.store.load(transaction_id)
        self.assertEqual([(e["evidence_id"], e["admissible"], e["void_reason"])
                          for e in lapsed.evidence],
                         [("s1", False, "fence_changed"), ("e1", True, None),
                          ("i1", False, "fence_changed")])
        self.assertEqual([g["valid"] for g in lapsed.grants], [False, False])
        for grant_id in ("g0", "g1"):
            self.assertRefusedUnchanged(
                GrantInvalid, lambda: self.store.check_grant(successor, grant_id))
            self.assertRefusedUnchanged(
                StaleCustody, lambda: self.store.check_grant(custody, grant_id))

    def test_an_interval_broken_by_a_custody_event_reads_fence_discontinuity(self):
        transaction_id = self.new()
        first = self.acquire(transaction_id)
        self.store.open_interval(first, evidence_id="i1")
        self.store.release(first)
        second = self.acquire(transaction_id)
        self.store.record_evidence(second, evidence_id="i1", form="interval", reference="r")
        self.store.open_interval(second, evidence_id="i2")
        after = self.store.record_evidence(second, evidence_id="i2", form="interval",
                                           reference="r")
        self.assertEqual([(e["evidence_id"], e["admissible"], e["void_reason"])
                          for e in after.evidence],
                         [("i1", False, "fence_discontinuity"), ("i2", True, None)])

    def test_a_released_span_invalidates_its_grants(self):
        custody = self.acquire(self.new())
        self.store.issue_grant(custody, grant_id="g1", actor="a")
        self.assertEqual([g["valid"] for g in self.store.release(custody).grants], [False])

    def test_reused_ids_and_unopened_intervals_are_refused_before_any_write(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        self.store.record_evidence(custody, evidence_id="e1", form="event", reference="r")
        self.store.open_interval(custody, evidence_id="i1")
        self.store.issue_grant(custody, grant_id="g1", actor="a")
        for call in (
                lambda: self.store.record_evidence(custody, evidence_id="e1", form="event",
                                                   reference="r"),
                lambda: self.store.open_interval(custody, evidence_id="e1"),
                lambda: self.store.open_interval(custody, evidence_id="i1"),
                lambda: self.store.record_evidence(custody, evidence_id="e1",
                                                   form="interval", reference="r"),
                lambda: self.store.record_evidence(custody, evidence_id="i1",
                                                   form="snapshot", reference="r"),
                lambda: self.store.issue_grant(custody, grant_id="g1", actor="a"),
                lambda: self.store.record_evidence(custody, evidence_id="x", form="guess",
                                                   reference="r"),
                lambda: self.store.record_evidence(custody, evidence_id="", form="event",
                                                   reference="r"),
                lambda: self.store.issue_grant(custody, grant_id="g2", actor="")):
            self.assertRefusedUnchanged(StateInvalid, call)
        self.assertRefusedUnchanged(GrantInvalid,
                                    lambda: self.store.check_grant(custody, "nope"))
        self.assertTrue(issubclass(GrantInvalid, FenceViolation))

    def test_stale_or_terminal_writers_are_refused_before_any_write(self):
        transaction_id = self.new()
        stale = self.acquire(transaction_id)

        def writes(credential):
            return (
                lambda: self.store.record_evidence(credential, evidence_id="s",
                                                   form="snapshot", reference="r"),
                lambda: self.store.open_interval(credential, evidence_id="i"),
                lambda: self.store.issue_grant(credential, grant_id="g", actor="a"))

        self.clock.advance(TTL)
        for call in writes(stale):
            self.assertRefusedUnchanged(StaleCustody, call)
        fresh = self.acquire(transaction_id, executor="exec-b")
        for call in writes(stale) + (
                lambda: self.store.advance(transaction_id, "awaiting_verification",
                                           reason="r", custody=stale),
                lambda: self.store.renew(stale),
                lambda: self.store.release(stale)):
            self.assertRefusedUnchanged(StaleCustody, call)  # epoch 1 after epoch 2
        self.store.advance(transaction_id, "abandoned", reason="r", external_state="known",
                           custody=fresh)
        for call in writes(fresh):
            self.assertRefusedUnchanged(TransitionRefused, call)

    def test_hand_edited_evidence_histories_fail_the_named_rule(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        self.store.open_interval(custody, evidence_id="i1")
        self.store.record_evidence(custody, evidence_id="i1", form="interval", reference="r")
        self.store.issue_grant(custody, grant_id="g1", actor="a")
        base = self.state_doc(transaction_id)
        _, acquired, opened, closed, granted = base["events"]
        held = span(acquired)
        foreign = {k: {**v, "epoch": 9} for k, v in opened["fence"].items()}
        self.assertTrue(all(v["epoch"] == 1 for v in granted["fence"].values()))
        boolean = {k: {**v, "epoch": True} for k, v in granted["fence"].items()}
        floating = {k: {**v, "epoch": 1.0} for k, v in granted["fence"].items()}
        cases = {
            "boolean grant epoch": (
                history(base, acquired, opened, closed, {**granted, "fence": boolean},
                        custody=held), "is not an integer >= 1"),
            "float grant epoch": (
                history(base, acquired, opened, closed, {**granted, "fence": floating},
                        custody=held), "is not an integer >= 1"),
            "evidence outside a span": (
                history(base, {**closed, "form": "snapshot"}, custody=None),
                "outside an open custody span"),
            "foreign fence": (
                history(base, acquired, {**opened, "fence": foreign}, closed, granted,
                        custody=held), "fence does not equal the open span's fence"),
            "close without open": (
                history(base, acquired, closed, granted, custody=held),
                "closes no opened interval"),
            "duplicate grant": (
                history(base, acquired, opened, closed, granted, granted, custody=held),
                "grant_id 'g1' is reused"),
            "unknown form": (
                history(base, acquired, opened, {**closed, "form": "guess"}, granted,
                        custody=held), "form is not event, snapshot or interval"),
        }
        for name, (document, fragment) in cases.items():
            with self.subTest(case=name):
                self.assertRuleRefuses(transaction_id, copy.deepcopy(document), fragment)


class ReapTest(CustodyCase):
    def proving(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        for target in ("awaiting_verification", "ready", "publishing", "published",
                       "proving"):
            self.store.advance(transaction_id, target, reason="r", external_state="known",
                               custody=custody)
        return transaction_id, custody

    def test_reap_writes_nothing_without_a_lapse(self):
        bare = self.new("bare", keys=("project:bare",))
        transaction_id, _ = self.proving()
        before = self.files()
        for candidate in (bare, transaction_id):
            self.assertEqual(self.store.reap(candidate, reason="sweep"),
                             self.store.load(candidate))
        self.assertEqual(self.files(), before)

    def test_reaping_a_lapse_parks_with_a_synthesized_stop_once(self):
        transaction_id, custody = self.proving()
        self.clock.advance(TTL)
        reaped = self.store.reap(transaction_id, reason="lease expired")
        tail = [dict(e) for e in reaped.events[-3:]]
        self.assertEqual([e["type"] for e in tail],
                         ["lease_lapse_detected", "stop_synthesized", "transitioned"])
        self.assertEqual((tail[1]["fence"], tail[1]["executor_id"], tail[1]["reason"]),
                         (plain(custody.fence), "exec-a", "lease expired"))
        self.assertEqual((tail[2]["to"], tail[2]["external_state"], tail[2]["reason"]),
                         ("attention_required", "unknown", "lease expired"))
        self.assertEqual((reaped.state, reaped.parked_from, reaped.custody),
                         ("attention_required", "proving", None))
        before = self.files()
        self.assertEqual(self.store.reap(transaction_id, reason="again"), reaped)
        self.assertEqual(self.files(), before)
        for call in (
                lambda: self.store.advance(transaction_id, "proving", reason="r",
                                           custody=custody),
                lambda: self.store.record_evidence(custody, evidence_id="x",
                                                   form="snapshot", reference="r")):
            self.assertRefusedUnchanged(StaleCustody, call)
        fresh = self.acquire(transaction_id, executor="exec-b")
        for call in (
                lambda: self.store.advance(transaction_id, "proving", reason="r",
                                           custody=custody),
                lambda: self.store.record_evidence(custody, evidence_id="x",
                                                   form="snapshot", reference="r"),
                lambda: self.store.renew(custody),
                lambda: self.store.release(custody)):
            self.assertRefusedUnchanged(StaleCustody, call)  # epoch 1 after epoch 2
        self.assertEqual(self.store.advance(transaction_id, "proving", reason="r",
                                            custody=fresh).state, "proving")

    def test_reaping_a_parked_lapse_adds_no_transition(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        self.store.advance(transaction_id, "attention_required", reason="r", custody=custody)
        self.clock.advance(TTL)
        reaped = self.store.reap(transaction_id, reason="lease expired")
        self.assertEqual([e["type"] for e in reaped.events[-2:]],
                         ["lease_lapse_detected", "stop_synthesized"])
        self.assertEqual(reaped.state, "attention_required")


class OwnerResultTest(ReapTest):
    def late(self, transaction_id, custody, **overrides):
        arguments = {"executor_id": custody.executor_id,
                     "subject_path": custody.subject_path, "fence": plain(custody.fence),
                     "result": {"status": "done", "items": [1, 2]}, **overrides}
        return self.store.record_owner_result(transaction_id, **arguments)

    def test_a_late_authentic_result_is_kept_beside_the_synthesized_stop(self):
        transaction_id, custody = self.proving()
        self.clock.advance(TTL)
        reaped = self.store.reap(transaction_id, reason="lease expired")
        stop = next(e for e in reaped.events if e["type"] == "stop_synthesized")
        after = self.late(transaction_id, custody)
        event = dict(after.events[-1])
        self.assertEqual(event, {
            "seq": reaped.revision + 1, "type": "owner_result", "at": event["at"],
            "executor_id": "exec-a", "fence": plain(custody.fence), "custody": "stale",
            "supersedes": stop["seq"], "result": {"status": "done", "items": [1, 2]}})
        self.assertEqual((after.state, after.parked_from, after.custody),
                         (reaped.state, reaped.parked_from, None))
        self.assertIn("stop_synthesized", [e["type"] for e in after.events])
        self.assertRefusedUnchanged(StaleCustody, lambda: self.store.advance(
            transaction_id, "proving", reason="r", custody=custody))

    def test_a_result_under_live_custody_is_current(self):
        transaction_id, custody = self.proving()
        event = self.late(transaction_id, custody).events[-1]
        self.assertEqual((event["custody"], event["supersedes"]), ("current", None))
        self.assertEqual(self.store.load(transaction_id).custody, custody)

    def test_unissued_misbound_or_malformed_results_are_refused_before_any_write(self):
        transaction_id, custody = self.proving()
        bumped = {k: {**v, "epoch": v["epoch"] + 1} for k, v in plain(custody.fence).items()}
        for overrides in ({"fence": bumped}, {"executor_id": "exec-z"}):
            with self.subTest(overrides=overrides):
                self.assertRefusedUnchanged(
                    StaleCustody, lambda: self.late(transaction_id, custody, **overrides))
        self.assertRefusedUnchanged(CustodyMisbound, lambda: self.late(
            transaction_id, custody, subject_path="/work/beta"))
        for result in (["not", "an", "object"], {"x": float("nan")}, {1: "int key"},
                       {"t": (1, 2)}):
            with self.subTest(result=result):
                self.assertRefusedUnchanged(
                    StateInvalid, lambda: self.late(transaction_id, custody, result=result))

    def test_a_terminal_transaction_refuses_late_results(self):
        transaction_id, custody = self.proving()
        self.store.advance(transaction_id, "succeeded", reason="r", external_state="known",
                           custody=custody)
        self.assertRefusedUnchanged(TransitionRefused,
                                    lambda: self.late(transaction_id, custody))

    def test_hand_edited_stop_and_result_histories_fail_the_named_rule(self):
        transaction_id, custody = self.proving()
        self.clock.advance(TTL)
        self.store.reap(transaction_id, reason="lease expired")
        self.late(transaction_id, custody)
        base = self.state_doc(transaction_id)
        _, acquired, *middle, lapse, stop, park, result = base["events"]
        early = [acquired, *middle]
        unlapsed = history(base, *early, stop, park, result, custody=span(acquired))
        unlapsed["events"][-1]["supersedes"] = unlapsed["events"][-3]["seq"]
        cases = {
            "stop without lapse": (unlapsed, "does not follow a lease_lapse_detected"),
            "result names no span": (
                history(base, *early, lapse, stop, park,
                        {**result, "executor_id": "exec-z"}, custody=None),
                "names no custody span"),
            "supersedes no stop": (
                history(base, *early, lapse, stop, park,
                        {**result, "supersedes": park["seq"]}, custody=None),
                "supersedes names no earlier stop_synthesized"),
            "unknown custody word": (
                history(base, *early, lapse, stop, park, {**result, "custody": "maybe"},
                        custody=None), "custody is not current or stale"),
        }
        for name, (document, fragment) in cases.items():
            with self.subTest(case=name):
                self.assertRuleRefuses(transaction_id, copy.deepcopy(document), fragment)


if __name__ == "__main__":
    unittest.main()
