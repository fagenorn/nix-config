"""Transaction core slice 1: store, identity and closed schema (#204 D1-D5, D9, D13, D16).

Run: just agent-workflow-tests
"""

import copy
import datetime
import fcntl
import hashlib
import json
import re
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from agent_tools import transaction_core, transaction_history, transaction_storage
from agent_tools.transaction_core import (
    STATES, TERMINALS, TRANSITIONS, CreationConflict, StateInvalid, Transaction,
    TransactionBusy, TransactionError, TransactionStore, TransitionRefused,
    UnknownTransaction)

ID_PATTERN = re.compile(
    r"^rel_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
AT_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
SUBJECT = {"candidate": "sha256:abc", "n": 1}
KEYS = ["project:demo", "target:demo"]
FORWARD = ("created", "awaiting_verification", "ready", "publishing", "published",
           "activating", "proving")
EXPECTED_EDGES = {
    "created": {"awaiting_verification", "attention_required", "abandoned"},
    "awaiting_verification": {"ready", "attention_required", "abandoned"},
    "ready": {"publishing", "attention_required", "abandoned"},
    "publishing": {"published", "attention_required"},
    "published": {"activating", "proving", "attention_required"},
    "activating": {"proving", "attention_required"},
    "proving": {"succeeded", "attention_required"},
    "attention_required": set(FORWARD) | {"recovering", "abandoned", "failed"},
    "recovering": {"rolled_back", "attention_required", "abandoned", "failed"},
    "succeeded": set(), "abandoned": set(), "rolled_back": set(), "failed": set(),
}


def serialize(document):
    return json.dumps(document, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False) + "\n"


def with_history(document, *targets, external_state="known"):
    """Append transitioned events by hand, recomputing the projection honestly."""
    document = copy.deepcopy(document)
    state, parked = document["state"], document["parked_from"]
    for target in targets:
        document["events"].append({
            "seq": len(document["events"]) + 1, "type": "transitioned",
            "at": document["events"][0]["at"], "from": state, "to": target,
            "reason": "test step", "external_state": external_state})
        if target == "attention_required":
            parked = state
        elif state == "attention_required":
            parked = None
        state = target
    document.update(state=state, parked_from=parked, revision=len(document["events"]))
    return document


class StoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = TransactionStore(self.root)

    def state_path(self, transaction_id):
        return self.root / transaction_id / "state.json"

    def index_path(self, key):
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / "creation-keys" / f"{digest}.json"

    def tree(self):
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))

    def document(self, transaction_id):
        return json.loads(self.state_path(transaction_id).read_text())

    def write(self, transaction_id, document):
        self.state_path(transaction_id).write_text(serialize(document))


class VocabularyTest(unittest.TestCase):
    def test_the_edge_table_is_exactly_the_specified_one(self):
        self.assertEqual(len(STATES), 13)
        self.assertEqual(TERMINALS, {"succeeded", "abandoned", "rolled_back", "failed"})
        self.assertEqual({k: set(v) for k, v in TRANSITIONS.items()}, EXPECTED_EDGES)
        with self.assertRaises(TypeError):
            TRANSITIONS["created"] = frozenset()

    def test_every_refusal_is_a_transaction_error(self):
        for error in (StateInvalid, TransactionBusy, TransitionRefused, CreationConflict,
                      UnknownTransaction):
            self.assertTrue(issubclass(error, TransactionError))


class RootTest(unittest.TestCase):
    def test_relative_missing_or_file_roots_are_refused_and_nothing_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            a_file = Path(tmp) / "file"
            a_file.write_text("x")
            for root in (Path("relative/root"), missing, a_file):
                with self.subTest(root=str(root)), self.assertRaises(TransactionError):
                    TransactionStore(root)
            self.assertFalse(missing.exists())
            self.assertFalse(Path("relative").exists())


class CreateTest(StoreCase):
    def test_create_mints_a_rel_uuid7_id_and_writes_state_and_index(self):
        before = time.time_ns() // 1_000_000
        created = self.store.create("demo:success", SUBJECT, concurrency_keys=KEYS)
        after = time.time_ns() // 1_000_000
        transaction_id = created.transaction_id
        self.assertRegex(transaction_id, ID_PATTERN)
        millis = int(transaction_id[4:].replace("-", "")[:12], 16)
        self.assertTrue(before <= millis <= after)
        self.assertEqual(self.tree(), sorted([
            "creation.lock", "creation-keys", str(self.index_path("demo:success")
                                                   .relative_to(self.root)),
            transaction_id, f"{transaction_id}/lock", f"{transaction_id}/state.json"]))
        raw = self.state_path(transaction_id).read_text()
        document = json.loads(raw)
        self.assertEqual(raw, serialize(document))
        self.assertEqual(set(document), {"schema", "transaction_id", "creation_key", "subject",
                                         "state", "parked_from", "revision", "events",
                                         "concurrency_keys", "custody"})
        self.assertEqual(document["schema"], "transaction-state/v2")
        self.assertEqual((document["concurrency_keys"], document["custody"]), (KEYS, None))
        self.assertEqual(created.concurrency_keys, tuple(KEYS))
        self.assertEqual(document["transaction_id"], transaction_id)
        self.assertEqual(document["subject"], SUBJECT)
        self.assertEqual((document["state"], document["parked_from"], document["revision"]),
                         ("created", None, 1))
        [event] = document["events"]
        self.assertEqual(set(event), {"seq", "type", "at"})
        self.assertEqual((event["seq"], event["type"]), (1, "created"))
        self.assertRegex(event["at"], AT_PATTERN)
        index = self.index_path("demo:success").read_text()
        self.assertEqual(index, serialize({"schema": "transaction-creation-key/v1",
                                           "creation_key": "demo:success",
                                           "transaction_id": transaction_id}))
        self.assertIsInstance(created, Transaction)
        self.assertEqual(created.events[0]["type"], "created")

    def test_same_key_and_subject_returns_the_same_id_and_writes_nothing(self):
        first = self.store.create("k", SUBJECT, concurrency_keys=KEYS)
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        again = TransactionStore(self.root).create("k", copy.deepcopy(SUBJECT),
                                                   concurrency_keys=KEYS)
        after = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(again.transaction_id, first.transaction_id)
        self.assertEqual(before, after)
        self.assertEqual(len(again.events), 1)

    def test_same_key_with_a_different_subject_is_a_conflict(self):
        self.store.create("k", {"n": 1}, concurrency_keys=KEYS)
        for other in ({"n": 1.0}, {"n": True}, {"n": 2}):
            with self.subTest(other=other), self.assertRaises(CreationConflict):
                self.store.create("k", other, concurrency_keys=KEYS)

    def test_an_index_naming_another_keys_transaction_is_state_invalid_and_unchanged(self):
        other = self.store.create("b", SUBJECT, concurrency_keys=KEYS)
        self.index_path("a").write_text(serialize({
            "schema": "transaction-creation-key/v1", "creation_key": "a",
            "transaction_id": other.transaction_id}))
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with self.assertRaises(StateInvalid) as caught:
            self.store.create("a", copy.deepcopy(SUBJECT), concurrency_keys=KEYS)
        after = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertIn(other.transaction_id, str(caught.exception))
        self.assertEqual(before, after)

    def test_an_index_without_state_is_completed_under_the_indexed_id(self):
        first = self.store.create("k", SUBJECT, concurrency_keys=KEYS)
        shutil.rmtree(self.root / first.transaction_id)
        resumed = self.store.create("k", SUBJECT, concurrency_keys=KEYS)
        self.assertEqual(resumed.transaction_id, first.transaction_id)
        self.assertEqual([e["type"] for e in resumed.events], ["created"])
        self.assertTrue((self.root / first.transaction_id / "lock").is_file())

    def test_arguments_that_cannot_form_a_v1_state_are_refused_before_anything_exists(self):
        for key, subject in (("", SUBJECT), ("k", ["not", "an", "object"]),
                             ("k", {"x": float("nan")}), ("k", {1: "int key"}),
                             ("k", {"t": (1, 2)}), ("\ud800", SUBJECT)):
            with self.subTest(key=key, subject=subject), self.assertRaises(StateInvalid):
                self.store.create(key, subject, concurrency_keys=KEYS)
        self.assertEqual(self.tree(), [])


class LoadTest(StoreCase):
    def test_load_returns_a_read_only_snapshot_of_the_persisted_state(self):
        created = self.store.create("k", SUBJECT, concurrency_keys=KEYS)
        loaded = TransactionStore(self.root).load(created.transaction_id)
        self.assertEqual(loaded, created)
        with self.assertRaises(TypeError):
            loaded.subject["n"] = 2
        with self.assertRaises(TypeError):
            loaded.events[0]["seq"] = 9
        self.assertEqual(self.document(created.transaction_id)["subject"], SUBJECT)

    def test_unknown_or_malformed_ids_are_unknown_and_nothing_is_created(self):
        self.store.create("k", SUBJECT, concurrency_keys=KEYS)
        before = self.tree()
        for transaction_id in ("rel_0190f0e0-0000-7000-8000-000000000000", "rel_../../etc",
                               "rel_0190F0E0-0000-7000-8000-000000000000", "creation-keys",
                               "rel_0190f0e0-0000-7000-8000-000000000000\n"):
            with self.subTest(id=transaction_id), self.assertRaises(UnknownTransaction):
                self.store.load(transaction_id)
        self.assertEqual(self.tree(), before)

    def test_a_valid_hand_built_history_loads(self):
        transaction_id = self.store.create("k", SUBJECT, concurrency_keys=KEYS).transaction_id
        base = self.document(transaction_id)
        for targets in (("attention_required", "created", "abandoned"),
                        ("attention_required", "recovering", "rolled_back"),
                        FORWARD[1:] + ("succeeded",)):
            with self.subTest(targets=targets):
                self.write(transaction_id, with_history(base, *targets))
                self.assertEqual(self.store.load(transaction_id).state, targets[-1])

    def test_documents_violating_the_closed_schema_are_state_invalid(self):
        transaction_id = self.store.create("k", SUBJECT, concurrency_keys=KEYS).transaction_id
        base = self.document(transaction_id)

        def gap(doc):
            doc = with_history(doc, "awaiting_verification")
            doc["events"][1]["seq"] = 3
            return doc

        cases = {
            "extra key": lambda d: {**d, "extra": 1},
            "missing key": lambda d: {k: v for k, v in d.items() if k != "parked_from"},
            "wrong schema": lambda d: {**d, "schema": "transaction-state/v3"},
            "forged state": lambda d: {**d, "state": "ready"},
            "bool revision": lambda d: {**d, "revision": True},
            "seq gap": gap,
            "illegal edge": lambda d: with_history(d, "published"),
            "park resumes elsewhere": lambda d: with_history(d, "attention_required", "ready"),
            "terminal on unknown": lambda d: with_history(d, "abandoned",
                                                          external_state="unknown"),
            "terminal unstated": lambda d: with_history(d, "abandoned", external_state=None),
            "event after terminal": lambda d: with_history(d, "abandoned", "created"),
            "extra event key": lambda d: {**d, "events": [{**d["events"][0], "x": 1}]},
            "bad timestamp": lambda d: {**d, "events": [{**d["events"][0], "at": "yesterday"}]},
            "wrong id": lambda d: {**d, "transaction_id": "rel_0190f0e0-0000-7000-8000-00000000000a"},
            "unsorted keys": lambda d: {**d, "concurrency_keys": KEYS[::-1]},
            "duplicate keys": lambda d: {**d, "concurrency_keys": [KEYS[0], KEYS[0]]},
            "empty keys": lambda d: {**d, "concurrency_keys": []},
            "non-string key": lambda d: {**d, "concurrency_keys": [1]},
            "forged custody": lambda d: {**d, "custody": {"executor_id": "x"}},
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                self.write(transaction_id, mutate(copy.deepcopy(base)))
                raw = self.state_path(transaction_id).read_bytes()
                with self.assertRaises(StateInvalid) as caught:
                    self.store.load(transaction_id)
                self.assertIn(transaction_id, str(caught.exception))
                self.assertEqual(self.state_path(transaction_id).read_bytes(), raw)

    def test_duplicate_keys_and_nonfinite_literals_are_state_invalid(self):
        transaction_id = self.store.create("k", SUBJECT, concurrency_keys=KEYS).transaction_id
        raw = self.state_path(transaction_id).read_text()
        for text in ('{"schema":"x",' + raw[1:], raw.replace('"n":1', '"n":NaN'),
                     raw.replace('"n":1', '"n":1e400'), raw.replace('"n":1', '"n":-1e400')):
            with self.subTest(text=text[:30]):
                self.state_path(transaction_id).write_text(text)
                with self.assertRaises(StateInvalid):
                    self.store.load(transaction_id)

    def test_layout_damage_is_state_invalid(self):
        transaction_id = self.store.create("k", SUBJECT, concurrency_keys=KEYS).transaction_id
        good = self.state_path(transaction_id).read_bytes()
        (self.root / transaction_id / "lock").unlink()
        with self.assertRaises(StateInvalid):
            self.store.load(transaction_id)
        self.assertFalse((self.root / transaction_id / "lock").exists())
        (self.root / transaction_id / "lock").write_text("")
        self.index_path("k").write_text(serialize({
            "schema": "transaction-creation-key/v1", "creation_key": "k",
            "transaction_id": "rel_0190f0e0-0000-7000-8000-000000000000"}))
        with self.assertRaises(StateInvalid):
            self.store.load(transaction_id)
        self.assertEqual(self.state_path(transaction_id).read_bytes(), good)


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
    def setUp(self):
        super().setUp()
        self.held = {}

    def reach(self, key, path):
        transaction_id = self.store.create(
            key, SUBJECT, concurrency_keys=[f"key:{key}"]).transaction_id
        self.held[transaction_id] = self.store.acquire(
            transaction_id, executor_id="exec", subject_path="/work/demo",
            ttl_ms=3_600_000).custody
        for target in path:
            self.store.advance(transaction_id, target, reason=f"to {target}",
                               external_state="known", custody=self.held[transaction_id])
        return transaction_id

    def assertRefusedUnchanged(self, error, transaction_id, target, **kwargs):
        raw = self.state_path(transaction_id).read_bytes()
        listing = self.tree()
        with self.assertRaises(error) as caught:
            self.store.advance(transaction_id, target, reason=kwargs.pop("reason", "try"),
                               custody=kwargs.pop("custody", self.held.get(transaction_id)),
                               **kwargs)
        self.assertIn(transaction_id, str(caught.exception))
        self.assertEqual(self.state_path(transaction_id).read_bytes(), raw)
        self.assertEqual(self.tree(), listing)


class AdvanceTest(AdvanceCase):
    def test_the_forward_chain_persists_one_event_per_transition(self):
        transaction_id = self.reach("k", PATHS_TO_TERMINAL["succeeded"])
        persisted = TransactionStore(self.root).load(transaction_id)
        transitions = [e for e in persisted.events if e["type"] == "transitioned"]
        self.assertEqual(persisted.state, "succeeded")
        self.assertEqual(persisted.revision, 10)
        self.assertEqual([e["seq"] for e in persisted.events], list(range(1, 11)))
        self.assertEqual([e["to"] for e in transitions], list(PATHS_TO_TERMINAL["succeeded"]))
        self.assertEqual(transitions[-1]["external_state"], "known")
        self.assertEqual(transitions[0]["reason"], "to awaiting_verification")
        self.assertEqual(persisted.events[-1]["type"], "lease_released")

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
                                                   external_state="known",
                                                   custody=self.held[transaction_id])
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
        resumed = self.store.advance(transaction_id, "publishing", reason="resume",
                                     custody=self.held[transaction_id])
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
                                      external_state="known",
                                      custody=self.held[transaction_id])
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
        self.store.advance(transaction_id, "awaiting_verification", reason="now free",
                           custody=self.held[transaction_id])

    def test_a_held_creation_lock_refuses_create_before_any_write(self):
        with open(self.root / "creation.lock", "a+") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(TransactionBusy):
                self.store.create("k", SUBJECT, concurrency_keys=KEYS)
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

    def test_a_symlinked_transaction_directory_is_never_followed(self):
        transaction_id = self.reach("k", ())
        with tempfile.TemporaryDirectory() as outside:
            moved = Path(outside) / "moved"
            (self.root / transaction_id).rename(moved)
            (self.root / transaction_id).symlink_to(moved, target_is_directory=True)
            raw = (moved / "state.json").read_bytes()
            listing = sorted(p.name for p in moved.iterdir())
            for call in (lambda: self.store.load(transaction_id),
                         lambda: self.store.advance(transaction_id, "awaiting_verification",
                                                    reason="x", external_state="known")):
                with self.assertRaises(UnknownTransaction) as caught:
                    call()
                self.assertIn(transaction_id, str(caught.exception))
            self.assertEqual((moved / "state.json").read_bytes(), raw)
            self.assertEqual(sorted(p.name for p in moved.iterdir()), listing)


T0 = 1_800_000_000_000  # 2027-01-15T08:00:00.000Z


class FakeClock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


class ClockTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_event_times_come_from_the_injected_clock_and_ids_from_the_wall(self):
        clock = FakeClock()
        store = TransactionStore(self.root, clock=clock)
        before = time.time_ns() // 1_000_000
        created = store.create("k", SUBJECT, concurrency_keys=KEYS)
        after = time.time_ns() // 1_000_000
        self.assertEqual(created.events[0]["at"], "2027-01-15T08:00:00.000Z")
        millis = int(created.transaction_id[4:].replace("-", "")[:12], 16)
        self.assertTrue(before <= millis <= after)
        clock.now = T0 + 1234
        moved = store.advance(created.transaction_id, "awaiting_verification", reason="r")
        self.assertEqual(moved.events[-1]["at"], "2027-01-15T08:00:01.234Z")

    def test_a_malformed_clock_reading_is_refused_before_any_state_exists(self):
        for reading in (1.5, True, -1, "0", None, 253_402_300_800_000):
            with self.subTest(reading=reading), tempfile.TemporaryDirectory() as tmp:
                store = TransactionStore(Path(tmp), clock=lambda value=reading: value)
                with self.assertRaises(TransactionError) as caught:
                    store.create("k", SUBJECT, concurrency_keys=KEYS)
                self.assertIn(tmp, str(caught.exception))
                self.assertEqual(list(Path(tmp).rglob("state.json")), [])

    def test_the_default_clock_is_the_wall_clock(self):
        before = time.time_ns() // 1_000_000
        at = TransactionStore(self.root).create(
            "k", SUBJECT, concurrency_keys=KEYS).events[0]["at"]
        after = time.time_ns() // 1_000_000
        stamp = datetime.datetime.strptime(at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=datetime.timezone.utc)
        self.assertTrue(before <= int(stamp.timestamp() * 1000 + 0.5) <= after)

    def test_the_largest_representable_reading_is_accepted(self):
        store = TransactionStore(self.root, clock=lambda: 253_402_300_799_999)
        self.assertEqual(store.create("k", SUBJECT, concurrency_keys=KEYS).events[0]["at"],
                         "9999-12-31T23:59:59.999Z")


class StorageModuleTest(unittest.TestCase):
    def test_the_core_re_exports_the_storage_error_hierarchy(self):
        for name in ("TransactionError", "StateInvalid", "TransactionBusy",
                     "TransitionRefused", "CreationConflict", "UnknownTransaction"):
            with self.subTest(name=name):
                self.assertIs(getattr(transaction_core, name),
                              getattr(transaction_storage, name))

    def test_the_core_re_exports_the_history_surface(self):
        for name in ("SCHEMA", "FORWARD", "PARKINGS", "TERMINALS", "STATES",
                     "TRANSITIONS", "Custody", "Transaction"):
            with self.subTest(name=name):
                self.assertIs(getattr(transaction_core, name),
                              getattr(transaction_history, name))


class ConcurrencyKeysTest(StoreCase):
    def test_keys_are_stored_sorted_and_deduplication_compares_them(self):
        created = self.store.create("k", SUBJECT, concurrency_keys={"b:2", "a:1"})
        self.assertEqual(created.concurrency_keys, ("a:1", "b:2"))
        again = self.store.create("k", SUBJECT, concurrency_keys=("b:2", "a:1"))
        self.assertEqual(again.transaction_id, created.transaction_id)
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        for keys in (["a:1"], ["a:1", "b:2", "c:3"]):
            with self.subTest(keys=keys), self.assertRaises(CreationConflict):
                self.store.create("k", SUBJECT, concurrency_keys=keys)
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()},
                         before)

    def test_malformed_key_sets_are_refused_before_anything_exists(self):
        for keys in ((), [], "ab", ["a", "a"], [""], [1], ["\ud800"], None):
            with self.subTest(keys=keys), self.assertRaises(StateInvalid):
                self.store.create("k", SUBJECT, concurrency_keys=keys)
        self.assertEqual(self.tree(), [])

    def test_keys_are_required(self):
        with self.assertRaises(TypeError):
            self.store.create("k", SUBJECT)

    def test_a_v1_document_fails_closed_naming_its_version(self):
        transaction_id = self.store.create("k", SUBJECT, concurrency_keys=KEYS).transaction_id
        document = self.document(transaction_id)
        v1 = {key: value for key, value in document.items()
              if key not in ("concurrency_keys", "custody")}
        self.write(transaction_id, {**v1, "schema": "transaction-state/v1"})
        with self.assertRaises(StateInvalid) as caught:
            self.store.load(transaction_id)
        self.assertIn("transaction-state/v1", str(caught.exception))
        self.assertIn(transaction_id, str(caught.exception))

    def test_an_unknown_event_type_is_refused_by_name(self):
        transaction_id = self.store.create("k", SUBJECT, concurrency_keys=KEYS).transaction_id
        document = self.document(transaction_id)
        document["events"].append({"seq": 2, "type": "lease_renewed",
                                   "at": document["events"][0]["at"]})
        self.write(transaction_id, {**document, "revision": 2})
        with self.assertRaises(StateInvalid) as caught:
            self.store.load(transaction_id)
        self.assertIn("unknown event type 'lease_renewed'", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
