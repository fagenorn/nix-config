# Task 1: Store vocabulary, identity, validator, `create` and `load`

**Files:**
- Create: `python/agent_tools/transaction_core.py`
- Create: `tests/test_transaction_core.py`
- Modify: `justfile` (recipe `agent-workflow-tests`)

**Interfaces:**
- Consumes: `agent_tools.canonical.telemetry_digest`, `reject_duplicate_keys`,
  `reject_nonfinite_literal`.
- Produces (all importable from `agent_tools.transaction_core`; Task 2, 3, 4 rely on the
  exact names):
  - `SCHEMA = "transaction-state/v1"`, `INDEX_SCHEMA = "transaction-creation-key/v1"`.
  - `STATES: frozenset[str]` — the 13 states of the spec's Lifecycle section.
  - `TERMINALS: frozenset[str]` — `{"succeeded", "abandoned", "rolled_back", "failed"}`.
  - `TRANSITIONS: Mapping[str, frozenset[str]]` — a `types.MappingProxyType`, one key per
    member of `STATES`, per D15 (table below).
  - `class TransactionError(Exception)` and its five subclasses `StateInvalid`,
    `TransactionBusy`, `TransitionRefused`, `CreationConflict`, `UnknownTransaction` (D9).
  - `@dataclass(frozen=True) class Transaction` with fields, in order:
    `transaction_id: str`, `creation_key: str`, `subject: Mapping[str, Any]`,
    `state: str`, `parked_from: str | None`, `revision: int`,
    `events: tuple[Mapping[str, Any], ...]`. `subject` and each event are
    `types.MappingProxyType` over deep copies; only the top level is read-only (nested values stay mutable but cannot reach disk, because they are copies) — say exactly that in the class docstring.
  - `class TransactionStore` with `__init__(self, root: pathlib.Path)`,
    `create(self, creation_key: str, subject: dict) -> Transaction`,
    `load(self, transaction_id: str) -> Transaction`, and a `root` attribute.
  - Private helpers Task 2 reuses (names fixed so Task 2 can call them): `_edge_allowed(source: str, parked_from: str | None, target: str) -> bool`,
    `_validated_document(self, transaction_id: str) -> dict` (reads + fully validates
    `state.json`, raising as D16 says), `_snapshot(document: dict) -> Transaction`,
    `_atomic_write(directory: Path, path: Path, document: dict) -> None`,
    `_timestamp() -> str`, `_serialize(document: dict) -> str`, `_validate_state(document, transaction_id, root) -> None`.

**Invariants:**
- `TransactionStore(root)` raises `TransactionError` (base class is enough) when `root`
  is relative, missing, or not a directory, and creates nothing (D2).
- Ids match `^rel_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`;
  the first 48 bits are the creation wall-clock Unix milliseconds (D3). Any id is matched
  against this pattern before it is joined onto a path.
- Repeat `create` with the same key and a subject of equal `telemetry_digest` returns the
  same id and leaves every byte under `root` unchanged; a different digest raises
  `CreationConflict` (D4).
- `load` writes nothing, creates nothing and takes no lock (D13).
- A document failing any rule of the spec's `transaction-state/v1` table or event rules is
  `StateInvalid` (D5); refusal classification per D16.

- [ ] **Step 1: Write the failing tests** — create `tests/test_transaction_core.py`:

```python
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
```

Note: `fcntl` and `TransactionBusy` are imported now because Task 2 adds its lock tests
to this same file.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core.py 2>&1 | tail -3`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_tools.transaction_core'`.

- [ ] **Step 3: Write the minimal implementation** in
`python/agent_tools/transaction_core.py`.

Module docstring: state it is the transaction core's first slice (#204) — a caller-rooted
store of closed-schema transactions with a closed lifecycle — and that it has no command
and no caller yet. Keep it free of the D11 words even though docstrings are exempt.

Vocabulary: `FORWARD` (the seven in order), `PARKINGS = ("attention_required",
"recovering")`, `TERMINALS`, `STATES = frozenset(FORWARD) | frozenset(PARKINGS) | TERMINALS` (a bare tuple `|` a frozenset raises `TypeError`).
`TRANSITIONS = MappingProxyType({...})` exactly `EXPECTED_EDGES` above, as frozensets
(per D7, D15). One edge predicate shared by the validator's fold and Task 2's `advance`:

```python
def _edge_allowed(source: str, parked_from: str | None, target: str) -> bool:
    """Contract: `target` is in TRANSITIONS[source]; from a parking, a forward-state
    target must be the recorded `parked_from` (D15)."""
    if target not in TRANSITIONS.get(source, frozenset()):
        return False
    if source == "attention_required" and target in FORWARD:
        return target == parked_from
    return True
```

Identity (per D3): mint with `ms = time.time_ns() // 1_000_000`,
`value = (ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | secrets.randbits(12) << 64 | 0b10 << 62 | secrets.randbits(62)`,
id `"rel_" + str(uuid.UUID(int=value))`. The id regex above is the only id check, applied with `re.fullmatch` (never `re.match` with `$`, which accepts a trailing newline).

Serialization: `_serialize` is the Global Constraints expression. `_timestamp()` returns
UTC now as `YYYY-MM-DDTHH:MM:SS.mmmZ`; the validator accepts `at` only when it matches
`AT_PATTERN` and `datetime.strptime(at, "%Y-%m-%dT%H:%M:%S.%fZ")` parses it.

Strict read (`_read_json(path) -> Any`): refuse (StateInvalid) when `os.lstat(path)` is a symlink or
not a regular file (`stat.S_ISREG`); decode UTF-8; `json.loads(text, object_pairs_hook=reject_duplicate_keys, parse_constant=reject_nonfinite_literal)`;
map `UnicodeDecodeError`/`ValueError` to `StateInvalid` naming the path.

`_atomic_write(directory, path, document)`: mirror
`home/common/agent-skills/scripts/workflow-state.py` `atomic_write_state` —
`tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, prefix="." + path.name + ".", suffix=".tmp", delete=False)`,
write `_serialize(document)`, flush, `os.fsync`, `os.replace`, then fsync the directory
(`os.open(directory, os.O_RDONLY)` + `os.fsync` + close); on any exception unlink the
temporary file and re-raise.

Validator `_validate_state(document, transaction_id, root)` raises `StateInvalid` naming
the id and the rule; checks in order: exact key set; `schema`; id pattern and equality
with the directory name; `creation_key` non-empty `str`, and its index entry (read with
`_read_json`, exact keys `schema`/`creation_key`/`transaction_id`, `schema ==
INDEX_SCHEMA`) matches both key and id; `type(subject) is dict`; `events` a non-empty list;
event 1 has exactly `{"seq","type","at"}`, `seq == 1`, `type == "created"`; every later
event has exactly `{"seq","type","at","from","to","reason","external_state"}`, `type ==
"transitioned"`, `type(seq) is int and seq == position + 1`; the fold starts at
(`created`, `None`), refuses any event after a terminal, requires `from` equal the fold
state, `to` in `STATES`, `_edge_allowed(state, parked, to)`, `reason` a non-empty `str`,
`external_state in ("known", "unknown", None)`, and `external_state == "known"` when `to`
is terminal (D8); entering `attention_required` sets `parked = state`, leaving it clears
it; finally `state`, `parked_from` and `revision` (`type(...) is int`) equal the fold and
`len(events)`.

`_validated_document(transaction_id)` (per D13, D16): id fails the pattern →
`UnknownTransaction`; `os.lstat(root / id)` missing, a symlink or not a directory → `UnknownTransaction`; lock file
missing, a symlink or not a regular file (by `lstat`) → `StateInvalid`; `state.json` via `_read_json` (missing →
`StateInvalid`); `_validate_state`; return the dict.

`_snapshot(document)`: builds `Transaction` with `MappingProxyType(copy.deepcopy(...))`
for `subject` and each event.

`TransactionStore.__init__`: `root.is_absolute()` and `root.is_dir()` else
`TransactionError`; store `self.root = root`.

`load(id)`: `_snapshot(self._validated_document(id))`.

`create(creation_key, subject)` (per D4, D10, D16):
1. Before touching disk: `creation_key` must be a non-empty `str` that `creation_key.encode("utf-8")` accepts (a lone surrogate is `StateInvalid`); `type(subject) is
   dict`; `_serialize(subject)` must not raise and must round-trip through the strict
   loader to a value `== subject` whose `telemetry_digest` equals the subject's; any
   failure → `StateInvalid`.
2. Open `root/"creation.lock"` with `os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)` (a symlinked or non-regular lock, found by `lstat` or `OSError` from the open, → `StateInvalid`);
   `fcntl.flock(fd, LOCK_EX | LOCK_NB)`; `BlockingIOError` → `TransactionBusy`. Close
   the descriptor in a `finally`.
3. Index at `root/"creation-keys"/<sha256 hex of key utf-8>.json`. If it exists
   (`_read_json`, exact keys, schema, key equal, id pattern) take its id; else mint an id,
   `mkdir(exist_ok=True)` the index directory (refusing, by `lstat`, a symlinked or non-directory
   `creation-keys` with `StateInvalid`), fsync `root` when the directory was new, and `_atomic_write` the entry.
4. Complete: `mkdir(exist_ok=True)` `root/id` (then refuse, by `lstat`, a symlinked or non-directory
   `root/id` with `StateInvalid`; fsync `root` when the directory was new); open `root/id/"lock"` with `O_RDWR |
   O_CREAT | O_NOFOLLOW` and take it non-blocking (`TransactionBusy` on contention); if `state.json`
   exists, `_validated_document(id)` and compare `telemetry_digest` of stored vs requested
   subject: equal → return its snapshot, unequal → `CreationConflict`; else build the
   initial document (`state: "created"`, `parked_from: None`, `revision: 1`, one created
   event), `_validate_state` it, `_atomic_write` it, return its snapshot.

Then wire the recipe: in `justfile` `agent-workflow-tests`, add
`    tests/test_transaction_core.py \` directly after `tests/test_agent_tools_canonical.py \`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core.py 2>&1 | tail -3`
Expected: `OK` (14 tests).

Run: `grep -c 'tests/test_transaction_core.py' justfile`
Expected: `1` (the base commit prints `0`).

Run: `just agent-workflow-tests 2>&1 | tail -3` — Expected: `OK`.

Run: `just build 2>&1 | tail -5` — Expected: success; a broken import of
`agent_tools.transaction_core` fails `pythonImportsCheck` here.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/transaction_core.py tests/test_transaction_core.py justfile
git commit -m "feat(transaction-core): add the store, identity and closed schema (#204)"
```
