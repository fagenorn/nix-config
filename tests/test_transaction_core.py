"""Transaction core slice 1: store, identity and closed schema (#204 D1-D5, D9, D13, D16).

Run: just agent-workflow-tests
"""

import copy
import fcntl
import hashlib
import json
import re
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from agent_tools.transaction_core import (
    STATES, TERMINALS, TRANSITIONS, CreationConflict, StateInvalid, Transaction,
    TransactionBusy, TransactionError, TransactionStore, TransitionRefused,
    UnknownTransaction)

ID_PATTERN = re.compile(
    r"^rel_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
AT_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
SUBJECT = {"candidate": "sha256:abc", "n": 1}
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
        created = self.store.create("demo:success", SUBJECT)
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
                                         "state", "parked_from", "revision", "events"})
        self.assertEqual(document["schema"], "transaction-state/v1")
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
        first = self.store.create("k", SUBJECT)
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        again = TransactionStore(self.root).create("k", copy.deepcopy(SUBJECT))
        after = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(again.transaction_id, first.transaction_id)
        self.assertEqual(before, after)
        self.assertEqual(len(again.events), 1)

    def test_same_key_with_a_different_subject_is_a_conflict(self):
        self.store.create("k", {"n": 1})
        for other in ({"n": 1.0}, {"n": True}, {"n": 2}):
            with self.subTest(other=other), self.assertRaises(CreationConflict):
                self.store.create("k", other)

    def test_an_index_without_state_is_completed_under_the_indexed_id(self):
        first = self.store.create("k", SUBJECT)
        shutil.rmtree(self.root / first.transaction_id)
        resumed = self.store.create("k", SUBJECT)
        self.assertEqual(resumed.transaction_id, first.transaction_id)
        self.assertEqual([e["type"] for e in resumed.events], ["created"])
        self.assertTrue((self.root / first.transaction_id / "lock").is_file())

    def test_arguments_that_cannot_form_a_v1_state_are_refused_before_anything_exists(self):
        for key, subject in (("", SUBJECT), ("k", ["not", "an", "object"]),
                             ("k", {"x": float("nan")}), ("k", {1: "int key"}),
                             ("k", {"t": (1, 2)}), ("\ud800", SUBJECT)):
            with self.subTest(key=key, subject=subject), self.assertRaises(StateInvalid):
                self.store.create(key, subject)
        self.assertEqual(self.tree(), [])


class LoadTest(StoreCase):
    def test_load_returns_a_read_only_snapshot_of_the_persisted_state(self):
        created = self.store.create("k", SUBJECT)
        loaded = TransactionStore(self.root).load(created.transaction_id)
        self.assertEqual(loaded, created)
        with self.assertRaises(TypeError):
            loaded.subject["n"] = 2
        with self.assertRaises(TypeError):
            loaded.events[0]["seq"] = 9
        self.assertEqual(self.document(created.transaction_id)["subject"], SUBJECT)

    def test_unknown_or_malformed_ids_are_unknown_and_nothing_is_created(self):
        self.store.create("k", SUBJECT)
        before = self.tree()
        for transaction_id in ("rel_0190f0e0-0000-7000-8000-000000000000", "rel_../../etc",
                               "rel_0190F0E0-0000-7000-8000-000000000000", "creation-keys",
                               "rel_0190f0e0-0000-7000-8000-000000000000\n"):
            with self.subTest(id=transaction_id), self.assertRaises(UnknownTransaction):
                self.store.load(transaction_id)
        self.assertEqual(self.tree(), before)

    def test_a_valid_hand_built_history_loads(self):
        transaction_id = self.store.create("k", SUBJECT).transaction_id
        base = self.document(transaction_id)
        for targets in (("attention_required", "created", "abandoned"),
                        ("attention_required", "recovering", "rolled_back"),
                        FORWARD[1:] + ("succeeded",)):
            with self.subTest(targets=targets):
                self.write(transaction_id, with_history(base, *targets))
                self.assertEqual(self.store.load(transaction_id).state, targets[-1])

    def test_documents_violating_the_closed_schema_are_state_invalid(self):
        transaction_id = self.store.create("k", SUBJECT).transaction_id
        base = self.document(transaction_id)

        def gap(doc):
            doc = with_history(doc, "awaiting_verification")
            doc["events"][1]["seq"] = 3
            return doc

        cases = {
            "extra key": lambda d: {**d, "extra": 1},
            "missing key": lambda d: {k: v for k, v in d.items() if k != "parked_from"},
            "wrong schema": lambda d: {**d, "schema": "transaction-state/v2"},
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
        transaction_id = self.store.create("k", SUBJECT).transaction_id
        raw = self.state_path(transaction_id).read_text()
        for text in ('{"schema":"x",' + raw[1:], raw.replace('"n":1', '"n":NaN')):
            with self.subTest(text=text[:30]):
                self.state_path(transaction_id).write_text(text)
                with self.assertRaises(StateInvalid):
                    self.store.load(transaction_id)

    def test_layout_damage_is_state_invalid(self):
        transaction_id = self.store.create("k", SUBJECT).transaction_id
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


if __name__ == "__main__":
    unittest.main()
