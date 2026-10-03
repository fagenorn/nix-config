# Task 2: The sealed receipt — `ReceiptStore`, the seal and read-back

**Files:**
- Create: `python/agent_tools/transaction_receipt.py`
- Modify: `python/agent_tools/transaction_storage.py` (`ReceiptInvalid`)
- Modify: `python/agent_tools/transaction_history.py` (`append_events` completes the
  seal's digest; the walk's `receipt_sealed` position and end rules; `Transaction.terminal`)
- Modify: `python/agent_tools/transaction_core.py` (`__init__`, `_append`,
  `_validated_document`, `read_receipt`, re-exports)
- Create: `tests/test_transaction_receipt.py`
- Modify: `justfile` (add `tests/test_transaction_receipt.py` after
  `tests/test_transaction_recovery_settle.py`)
- Modify, only for the trailing `receipt_sealed`: `tests/test_transaction_core.py`,
  `tests/test_transaction_custody.py`, `tests/test_transaction_invocation.py`,
  `tests/test_transaction_proof.py`, `tests/test_transaction_recovery.py`,
  `tests/test_transaction_recovery_settle.py`, `tests/test_transaction_core_sweep.py`
  (`transaction_receipt` joins `NEUTRAL_MODULES`)

**Interfaces:**
- Consumes (Task 1, and `f40c09f`): `append_events(prior, event_fields, *, at)` and the
  walk `_history_projection(document, transaction_id)` in `transaction_history`;
  `_append(prior, now, events)` in the core; `authority_class` on the `created` event; `AUTHORITY`,
  `CustodyCase`, `serialize` (`tests/test_transaction_custody.py`); `CohortCase`
  (`tests/test_transaction_proof.py`); `SettleCase`
  (`tests/test_transaction_recovery_settle.py`); `FakeEffect`, `FakeWorld`
  (`tests/test_transaction_invocation.py`).
- Produces:
  - `transaction_receipt.RECEIPT_SCHEMA = "transaction-terminal-receipt/v1"`, re-exported.
  - `terminal_receipt(document: Mapping, covered: Sequence[Mapping]) -> dict`, a pure
    function of `document`'s immutable metadata (`transaction_id`, `creation_key`,
    `subject`, `concurrency_keys`, `proof_plan`, `recovery_plan`) and `covered`, the
    enveloped events ending in a terminal transition or the terminal `lease_released`
    right after one. It never reads `document["events"]`, `state`, `parked_from`,
    `custody` or `revision`, and raises `ValueError` when `covered` ends any other way
    (per D25, D29).
  - `RECEIPT_EVENT_KEYS = frozenset({"seq", "type", "at", "receipt_digest"})` and
    `receipt_event_violation(event: dict, events_before: Sequence[Mapping], document:
    dict) -> str | None`.
  - `terminal_view(document: dict) -> Mapping | None`, and the `Transaction.terminal`
    field it fills on every load.
  - `receipt_invalid(where: str, detail: str) -> ReceiptInvalid`, the one construction
    path, and `transaction_storage.ReceiptInvalid(StateInvalid)`, re-exported.
  - `class ReceiptStore(root: Path)` with `seal(receipt: dict, digest: str) -> None` and
    `read(digest: Any) -> Mapping[str, Any]`, plus a private exclusive-create helper that
    Task 5 reuses for markers and observations (per D29).
  - `TransactionStore.read_receipt(receipt_digest: str) -> Mapping[str, Any]`.
  - Tests: the `Sealed` mixin with `receipt_files()` and `assertSealed(after, outcome,
    qualifier=None) -> Mapping`, and the `ENVELOPE` key set, which Task 3 extends.
    Tasks 4–5 pass `qualifier` for `failed`.

**Invariants:**
- The receipt this task derives has exactly `ENVELOPE`'s keys: `schema`,
  `transaction_id`, `creation_key`, `recovers`, `authority_class`, `concurrency_keys`,
  `subject_digest`, `proof_plan_digest`, `recovery_plan_digest`, `outcome`,
  `terminal_qualifier`, `sealed_at`, `revision`, `history_digest` and `outcome_proof`.
  Their values follow spec "The receipt". `outcome` is the last transition's `to` in
  `covered`. `sealed_at` is `covered[-1]["at"]`. `revision` is `len(covered)`.
  `history_digest` is `telemetry_digest(list(covered))`. `terminal_qualifier` is None.
  Task 3 adds the four remaining keys, and Task 4 adds `failed` and its qualifier (per
  D3).
- `outcome_proof` per outcome. `succeeded` gets `{proof_sealed_seq, proof_cutoff_at,
  advisory_warnings}` from the `proof_sealed`. `abandoned` gets `{effect_snapshot}`: each
  `fold_actions` entry's `effect_class`, keyed by action id in declaration order (per
  D20). `rolled_back` gets `{recovery_settled_seq, effect_snapshot, selected, restored,
  residue}`, with `effect_snapshot` and `selected` from the latest `recovery_started` and
  the rest from the `recovery_settled`. Any other outcome is a `ValueError` until Task 4.
- The recipe (per D24). In `_append`, when some field is a `transitioned` into a
  terminal, the fields gain `lease_released` reason `terminal` if custody is held (as
  today), then `{"type": "receipt_sealed"}`, whether custody is held or not. Nothing else
  in `_append`'s recipe changes.
- The constructor (per D24, D29). `append_events` envelopes each field in order as today.
  For a field whose type is `receipt_sealed` it first requires the field to be exactly
  `{"type": "receipt_sealed"}`, else `StateInvalid` naming the transaction and
  `receipt_sealed fields carry more than their type`; it then appends `{"seq", "at",
  "type": "receipt_sealed", "receipt_digest": telemetry_digest(terminal_receipt(candidate,
  <the candidate's events so far>))}`. The one walk then runs once over the whole
  candidate, as today, and re-derives that digest. No second walk runs.
- The seal (per D2, D24, D29). After `append_events` returns, when `candidate["state"]` is
  terminal, `_append` calls `self._receipts.seal(terminal_receipt(candidate,
  candidate["events"][:-1]), candidate["events"][-1]["receipt_digest"])` before it takes
  the lease lock or writes `state.json`, then writes and clears the lease records exactly
  as today. Any exception from the seal propagates before `state.json` is written, so the
  transaction stays nonterminal and its lease records stay untouched.
- `ReceiptStore.seal(receipt, digest)` first refuses `ReceiptInvalid` unless
  `telemetry_digest(receipt) == digest`. It writes `receipts/<hex>.json`, where `digest =
  "sha256:<hex>"`. The bytes are `serialize(receipt)` and the mode is `0444`
  (per D6, D20). The write is exclusive: create `receipts/` if missing (fsync the root),
  refusing a non-directory or symlink. Open a temporary sibling with `O_CREAT | O_EXCL |
  O_WRONLY | O_NOFOLLOW`, mode `0o444`, write, fsync, `os.link` it to the final name,
  unlink the temporary in `finally`, then fsync the directory. On `FileExistsError` the
  existing bytes must equal the expected bytes, else `ReceiptInvalid`. The seal then
  reads the file back through `read(digest)` and requires `serialize(dict(read)) ==
  serialize(receipt)`. Every `OSError`, `StateInvalid` or mismatch is `ReceiptInvalid`
  naming the path (per D20).
- `read(digest)` refuses `ReceiptInvalid` for a digest that is not a
  `sha256:<64 lowercase hex>` string, a missing, non-regular or unparseable file, bytes
  that differ from `serialize` of the strict parse, a parse whose `telemetry_digest`
  differs from `digest`, or a `schema` other than `RECEIPT_SCHEMA`; each message names the
  receipt file's path (`receipts/<hex>.json`, or the digest when it is malformed). It returns
  `MappingProxyType` over the parse. It reads no lock or clock.
- The walk (per D7, D26). These rules live in `_history_projection`, so construction and
  load apply them alike. Its post-terminal guard, which today admits only the terminal
  `lease_released` right after the transition, also admits a `receipt_sealed` while the
  folded state is terminal and no `receipt_sealed` came before. Any other event after a
  terminal keeps the rule `event <seq> follows the terminal state <state>`. A
  `receipt_sealed` dispatch runs `_check_envelope` with `RECEIPT_EVENT_KEYS` first (so an
  extra key reads `is not the closed receipt_sealed event`), then refuses a nonterminal
  folded state with `receipt_sealed outside a terminal state`, then calls
  `receipt_event_violation(event, events[:seq - 1], document)`, which returns
  `receipt_sealed at is not the terminal transition's at` or `receipt_sealed
  receipt_digest is not the digest of the terminal receipt`, the latter through
  `terminal_receipt(document, events_before)`. After the loop, a terminal state whose last
  event is not `receipt_sealed` is refused `terminal state <state> has no receipt_sealed
  as its last event`.
- `_validated_document` reads a terminal document's receipt through
  `self._receipts.read(document["events"][-1]["receipt_digest"])` after `_validate_state`.
  So `load`, `_fenced`, `_advance_locked` and a same-key `create` all refuse a missing or
  altered receipt, before any terminal refusal (per D26).
- `terminal_view` returns None unless the last event is `receipt_sealed`. Otherwise it
  returns `MappingProxyType({"receipt_digest", "outcome": state, "terminal_qualifier":
  None})`. Task 4 fills the qualifier. `snapshot` fills `Transaction.terminal`, a new last
  field of the dataclass, from it; nothing stores it.
- Existing tests change only by the trailing `receipt_sealed`: exact trailing-type lists
  gain it, `events[-1]`/`[-2]`/`[-3]` indexes shift by one, and exact revision and seq
  counts grow by one. `tests/test_transaction_core.py`'s forward chain becomes
  `revision == 13`, seqs `1..13`, `events[-2]` the `lease_released` and `events[-1]` the
  `receipt_sealed`.
- One existing fixture changes beyond that (Phase-5 B1).
  `tests/test_transaction_core.py`'s `test_a_valid_hand_built_history_loads` hand-builds
  an `abandoned` terminal with no `receipt_sealed`, which this task's validator refuses.
  It keeps its nonterminal half: `with_history(base, "attention_required")` must still
  load as `attention_required`. Its terminal half becomes a refusal: `with_history(base,
  "attention_required", "created", "abandoned")` raises `StateInvalid`, asserted the way
  the neighbouring `test_a_hand_built_succeeded_without_a_seal_is_refused` asserts its
  missing seal, and the existing `rolled_back` refusal stays.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_transaction_receipt.py`:

```python
"""Transaction core slice 6: terminal receipts (#209).

Run: just agent-workflow-tests
"""

import hashlib
import json
import os
import stat
import tempfile
import unittest

from agent_tools import transaction_core, transaction_receipt, transaction_storage
from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_core import RECEIPT_SCHEMA, ReceiptInvalid, StateInvalid

from .test_transaction_custody import AUTHORITY, CustodyCase, serialize
from .test_transaction_invocation import FakeEffect, FakeWorld
from .test_transaction_proof import CohortCase
from .test_transaction_recovery_settle import SettleCase

ENVELOPE = {"schema", "transaction_id", "creation_key", "recovers", "authority_class",
            "concurrency_keys", "subject_digest", "proof_plan_digest", "recovery_plan_digest",
            "outcome", "terminal_qualifier", "sealed_at", "revision", "history_digest",
            "outcome_proof"}


class Sealed:
    """Assertions over the one receipt a terminal snapshot sealed, read from its file."""

    def receipt_files(self):
        directory = self.root / "receipts"
        return sorted(directory.iterdir()) if directory.is_dir() else []

    def assertSealed(self, after, outcome, qualifier=None):
        seal = dict(after.events[-1])
        self.assertEqual((after.state, seal["type"]), (outcome, "receipt_sealed"))
        digest = seal["receipt_digest"]
        path = self.root / "receipts" / (digest.removeprefix("sha256:") + ".json")
        self.assertIn(path, self.receipt_files())
        raw = path.read_bytes()
        self.assertEqual("sha256:" + hashlib.sha256(raw[:-1]).hexdigest(), digest)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o444)
        receipt = self.store.read_receipt(digest)
        self.assertEqual(serialize(dict(receipt)).encode(), raw)
        self.assertEqual(set(receipt), ENVELOPE)
        events = [dict(e) for e in after.events[:-1]]
        created = events[0]
        at = [e for e in events if e["type"] == "transitioned"][-1]["at"]
        self.assertEqual(seal["at"], at)
        self.assertEqual(
            {k: receipt[k] for k in ENVELOPE - {"outcome_proof"}},
            {"schema": RECEIPT_SCHEMA, "transaction_id": after.transaction_id,
             "creation_key": after.creation_key, "recovers": created["recovers"],
             "authority_class": created["authority_class"],
             "concurrency_keys": list(after.concurrency_keys),
             "subject_digest": telemetry_digest(dict(after.subject)),
             "proof_plan_digest": created["proof_plan_digest"],
             "recovery_plan_digest": created["recovery_plan_digest"], "outcome": outcome,
             "terminal_qualifier": qualifier, "sealed_at": at, "revision": len(events),
             "history_digest": telemetry_digest(events)})
        self.assertEqual(dict(after.terminal), {"receipt_digest": digest, "outcome": outcome,
                                                "terminal_qualifier": qualifier})
        self.assertEqual(dict(self.store.load(after.transaction_id).terminal),
                         dict(after.terminal))
        return receipt


class SucceededReceiptTest(Sealed, CohortCase):
    def test_success_seals_the_proof_seal_as_its_outcome_proof(self):
        self.ready()
        self.start()
        self.members()
        after = self.settle()
        receipt = self.assertSealed(after, "succeeded")
        self.assertEqual(len(self.receipt_files()), 1)
        seal = next(dict(e) for e in after.events if e["type"] == "proof_sealed")
        self.assertEqual(receipt["outcome_proof"], {
            "proof_sealed_seq": seal["seq"], "proof_cutoff_at": seal["proof_cutoff_at"],
            "advisory_warnings": seal["advisory_warnings"]})


class RolledBackReceiptTest(Sealed, SettleCase):
    def test_rollback_seals_its_snapshot_selection_restores_and_residue(self):
        self.recovering()
        self.all_edges()
        after = self.settle()
        receipt = self.assertSealed(after, "rolled_back")
        started = [dict(e) for e in after.events if e["type"] == "recovery_started"][-1]
        settled = next(dict(e) for e in after.events if e["type"] == "recovery_settled")
        self.assertEqual(receipt["outcome_proof"], {
            "recovery_settled_seq": settled["seq"], "effect_snapshot": started["effect_snapshot"],
            "selected": started["selected"], "restored": settled["restored"],
            "residue": settled["residue"]})


class AbandonedReceiptTest(Sealed, CustodyCase):
    def abandon(self, transaction_id, custody=None):
        return self.store.advance(transaction_id, "abandoned", reason="r",
                                  external_state="known", custody=custody)

    def test_abandoning_seals_every_actions_effect_class(self):
        transaction_id = self.new()
        self.assertIsNone(self.store.load(transaction_id).terminal)
        receipt = self.assertSealed(self.abandon(transaction_id), "abandoned")
        self.assertEqual((receipt["outcome_proof"], receipt["authority_class"]),
                         ({"effect_snapshot": {}}, AUTHORITY))
        other = self.new("inspected", keys=("key:inspected",))
        custody = self.acquire(other)
        for target in ("awaiting_verification", "ready", "publishing"):
            self.store.advance(other, target, reason="r", external_state="known",
                               custody=custody)
        inspected = self.store.inspect_action(custody, name="build", parameters={"n": 1},
                                              effect=FakeEffect(FakeWorld()))
        self.store.advance(other, "attention_required", reason="r", external_state="known",
                           custody=custody)
        after = self.abandon(other, custody)
        self.assertEqual([e["type"] for e in after.events[-3:]],
                         ["transitioned", "lease_released", "receipt_sealed"])
        digest = after.terminal["receipt_digest"]
        self.assertEqual(self.store.read_receipt(digest)["outcome_proof"],
                         {"effect_snapshot": {inspected.actions[0]["action_id"]: "no_effect"}})

    def test_an_altered_or_missing_receipt_fails_every_load(self):
        self.assertTrue(issubclass(ReceiptInvalid, StateInvalid))
        transaction_id = self.new()
        self.abandon(transaction_id)
        [path] = self.receipt_files()
        receipt = json.loads(path.read_text())
        os.chmod(path, 0o644)
        for content in (serialize({**receipt, "revision": 99}), serialize(receipt) + " ", None):
            with self.subTest(content=content):
                if content is None:
                    path.unlink()
                else:
                    path.write_text(content)
                for call in (lambda: self.store.load(transaction_id),
                             lambda: self.abandon(transaction_id), self.new):
                    with self.assertRaises(ReceiptInvalid) as caught:
                        call()
                    self.assertIn(path.name, str(caught.exception))

    def test_a_broken_receipts_path_refuses_the_seal_leaving_the_state_nonterminal(self):
        receipts = self.root / "receipts"
        elsewhere = tempfile.TemporaryDirectory()
        self.addCleanup(elsewhere.cleanup)
        self.addCleanup(lambda: receipts.is_dir() and os.chmod(receipts, 0o700))
        setups = {
            "file": (lambda: receipts.write_text("x"), receipts.unlink),
            "symlink": (lambda: receipts.symlink_to(elsewhere.name), receipts.unlink),
            "unwritable": (lambda: (receipts.mkdir(), os.chmod(receipts, 0o500)),
                           lambda: (os.chmod(receipts, 0o700), receipts.rmdir()))}
        for name, (arrange, restore) in setups.items():
            with self.subTest(name=name):
                transaction_id = self.new(name, keys=(f"key:{name}",))
                arrange()
                self.assertRefusedUnchanged(ReceiptInvalid,
                                            lambda: self.abandon(transaction_id))
                persisted = self.store.load(transaction_id)
                self.assertEqual((persisted.state, persisted.terminal), ("created", None))
                restore()
        self.assertEqual(os.listdir(elsewhere.name), [])

    def test_hand_edited_seals_are_state_invalid(self):
        transaction_id = self.new()
        self.abandon(transaction_id)
        document = self.state_doc(transaction_id)
        seal = document["events"][-1]

        def dropped(d):
            d["events"].pop()
            d["revision"] -= 1

        def doubled(d):
            d["events"].append({**seal, "seq": seal["seq"] + 1})
            d["revision"] += 1

        cases = (
            (lambda d: d["events"][-1].update(receipt_digest="sha256:" + "0" * 64),
             "receipt_sealed receipt_digest is not the digest of the terminal receipt"),
            (lambda d: d["events"][-1].update(at="2030-01-01T00:00:00.000Z"),
             "receipt_sealed at is not the terminal transition's at"),
            (lambda d: d["events"][-1].update(extra=1), "closed receipt_sealed event"),
            (dropped, "terminal state abandoned has no receipt_sealed as its last event"),
            (doubled, f"event {seal['seq'] + 1} follows the terminal state abandoned"))
        for edit, fragment in cases:
            with self.subTest(fragment=fragment):
                edited = json.loads(json.dumps(document))
                edit(edited)
                self.assertRuleRefuses(transaction_id, edited, fragment)
        open_id = self.new("open", keys=("key:open",))
        opened = self.state_doc(open_id)
        opened["events"].append({**seal, "seq": 2})
        opened["revision"] = 2
        self.assertRuleRefuses(open_id, opened, "receipt_sealed outside a terminal state")

    def test_read_receipt_refuses_an_unknown_or_malformed_digest(self):
        for digest in ("sha256:" + "0" * 64, "sha256:XYZ", "nope", 7):
            with self.subTest(digest=digest), self.assertRaises(ReceiptInvalid):
                self.store.read_receipt(digest)

    def test_the_receipt_names_are_re_exported(self):
        self.assertEqual(RECEIPT_SCHEMA, "transaction-terminal-receipt/v1")
        self.assertIs(transaction_core.RECEIPT_SCHEMA, transaction_receipt.RECEIPT_SCHEMA)
        self.assertIs(ReceiptInvalid, transaction_storage.ReceiptInvalid)
```

  Then make the existing-test changes the invariants list.

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_receipt.py 2>&1 | tail -3`.
  Expected: ERROR (`RECEIPT_SCHEMA` cannot be imported).

- [ ] **Step 3: Implement** the invariants. `transaction_receipt` imports `transaction_recovery` (`effect_class`),
  `transaction_invocation` (`fold_actions`) and `transaction_storage`
  (`serialize`, `strict_loads`, `lstat_mode`, `fsync_directory`, `require_directory`,
  `ReceiptInvalid`, `StateInvalid`). Keep D19's direction. `transaction_history`
  imports `RECEIPT_EVENT_KEYS`, `receipt_event_violation`, `terminal_receipt` and
  `terminal_view` from it. Write the `transaction_receipt` module docstring from the code:
  what the receipt holds, where the store puts it, and the seal's order. Update the
  `_append`, `_validated_document`, `append_events` and `validate_state` docstrings and the
  `transaction_history` module docstring. If
  `transaction_core.py` passes 64000 bytes, apply the Global Constraints' docstring
  economy first.

- [ ] **Step 4: Verify.**
  Run the slice unit command with `tests/test_transaction_receipt.py`. Expected: `OK`.

```bash
grep -q 'tests/test_transaction_receipt.py' justfile || exit 1
grep -q 'transaction_receipt' tests/test_transaction_core_sweep.py || exit 1
grep -q '"receipt_sealed"' python/agent_tools/transaction_core.py || exit 1
grep -q 'terminal_receipt' python/agent_tools/transaction_history.py || exit 1
if grep -n "import time\|import fcntl\|flock\|time_ns" python/agent_tools/transaction_receipt.py; then exit 1; fi
```

  Run: `git add -A python tests justfile && just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.** Stage exactly this task's **Files**, then:

```bash
git commit -m "feat(transaction-core): seal a content-addressed receipt at every terminal (#209)"
```

- [ ] **Step 6: Check the review budget** with `FILES="python/agent_tools/transaction_receipt.py python/agent_tools/transaction_storage.py python/agent_tools/transaction_history.py python/agent_tools/transaction_core.py tests/test_transaction_receipt.py tests/test_transaction_core.py"`.
  Expected: exit 0.

Decisions: per D2, D3, D6, D7, D16, D19, D20, D24, D25, D26, D29.
