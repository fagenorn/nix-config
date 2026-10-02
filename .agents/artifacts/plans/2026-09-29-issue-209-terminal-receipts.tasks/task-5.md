# Task 5: Hazard markers and post-terminal observations

**Files:**
- Modify: `python/agent_tools/transaction_receipt.py` (`HAZARD_SCHEMA`,
  `OBSERVATION_SCHEMA`, markers written by `seal`, `hazard_markers`,
  `record_observation`, `observations`)
- Modify: `python/agent_tools/transaction_core.py` (`hazard_markers`,
  `record_post_terminal`, `post_terminal_observations`, re-exports)
- Modify: `tests/test_transaction_disposition.py`

**Interfaces:**
- Consumes (Tasks 2, 4): `ReceiptStore` and its exclusive-create helper, `read`,
  `seal(receipt, digest)`, which `_append` calls before `state.json` is written; `OBSERVABILITY_GROUNDS`; `transaction_proof.closed_result_violation`;
  `DisposeCase`, `destroyed`, `live`, `KEYS`, `AUTHORITY`.
- Produces:
  - `HAZARD_SCHEMA = "transaction-hazard-marker/v1"` and `OBSERVATION_SCHEMA =
    "transaction-post-terminal-observation/v1"`, re-exported.
  - `ReceiptStore.hazard_markers(key: str) -> tuple[str, ...]`,
    `ReceiptStore.record_observation(receipt_digest, observation, contradicts_ground, at:
    str) -> Mapping`, `ReceiptStore.observations(receipt_digest) -> tuple[Mapping, ...]`.
  - `TransactionStore.hazard_markers(key: str) -> tuple[str, ...]`,
    `TransactionStore.record_post_terminal(receipt_digest: str, *, observation: dict,
    contradicts_ground: bool) -> Mapping[str, Any]`,
    `TransactionStore.post_terminal_observations(receipt_digest: str) ->
    tuple[Mapping[str, Any], ...]`.

**Invariants:**
- After the read-back and before it returns, `seal` writes one marker per concurrency
  key when `receipt["terminal_qualifier"] == "effects_unobservable"`. The marker path is
  `hazards/<sha256 hex of the key's UTF-8>/<receipt hex>.json`, and its content is
  exactly `{"schema": HAZARD_SCHEMA, "key", "receipt_digest"}`. It uses the same
  exclusive create (identical bytes accepted) and fsyncs every directory it creates. A
  marker failure is `ReceiptInvalid` and leaves `state.json` untouched. Any receipt it
  already wrote stays inert (per D2, D6, D12, D22).
- `hazard_markers(key)` returns the sorted receipt digests under that key's directory,
  or `()` when it is missing. Each listed file is re-validated: a regular file, strict
  JSON equal to its `serialize` bytes, the closed marker keys, the schema, the `key`,
  and a `receipt_digest` equal to `sha256:<file stem>`. Anything else is
  `ReceiptInvalid`. It reads nothing else and writes nothing. The core wrapper first
  refuses a key that is not a non-empty UTF-8-encodable string with `StateInvalid`, as
  `inspect_lease` does.
- `record_post_terminal` reads the receipt through `read`, so an unknown digest is
  `ReceiptInvalid`. `StateInvalid` comes before any write for these cases: an
  `observation` failing `closed_result_violation(observation, "observation")`, a
  `contradicts_ground` that is not a bool, or `contradicts_ground` true on a receipt
  whose `outcome` is not `failed` or whose `outcome_proof["ground"]` is not in
  `OBSERVABILITY_GROUNDS` (per D12, D22). The observation is a caller argument, so it
  never passes through `_capture_result`; the record copies its three fields (per D26).
  It then writes `observations/<receipt
  hex>/<n>.json` with exactly `{"schema": OBSERVATION_SCHEMA, "receipt_digest", "n",
  "at", "outcome", "reason", "reference", "contradicts_ground"}`. `n` starts at one more
  than the files present, and each exclusive-create collision tries `n + 1`, so no file
  is ever replaced. `at` is `format_at(self._now())`, read by the core. It returns a
  read-only view of the record and never touches the receipt, a ledger or a lease.
- `post_terminal_observations(digest)` reads the receipt first, then returns every
  observation file ordered by `n`. Each is re-validated like a marker: closed keys,
  schema, `receipt_digest`, an `n` equal to its file name, and `serialize` bytes. The
  read also re-applies every value rule `record_post_terminal` enforces at insertion
  (Phase-5 S1): the three observation fields pass the same
  `closed_result_violation(..., "observation")` check, `at` parses as a core timestamp,
  `contradicts_ground` is a bool, and a true `contradicts_ground` again requires the
  receipt's `failed` outcome and an `OBSERVABILITY_GROUNDS` ground. One shared validator
  serves both insertion and read. Anything else is `ReceiptInvalid`.
- `record_owner_result` keeps refusing a terminal. A result that arrives after the seal
  is recorded through `record_post_terminal` (per D18).
- The receipt module's docstring gains the two directories. The core's sibling clause
  names the three new wrappers.

- [ ] **Step 1: Write the failing tests.** Add to the imports of
  `tests/test_transaction_disposition.py`: `import hashlib`, `import json`, `import os`,
  `from agent_tools import transaction_receipt`, and from `agent_tools.transaction_core`,
  `HAZARD_SCHEMA`, `OBSERVATION_SCHEMA` and `ReceiptInvalid`. Then append:

```python
class UnobservableTest(DisposeCase):
    def unobservable_failure(self):
        self.parked(start="unknown")
        self.human()
        after = self.dispose("h-1", disposition=self.unobservable())
        return after, after.terminal["receipt_digest"]

    def marker(self, key, digest):
        return (self.root / "hazards" / hashlib.sha256(key.encode()).hexdigest()
                / (digest.removeprefix("sha256:") + ".json"))

    def test_an_unobservable_disposition_seals_its_qualifier_and_marks_every_key(self):
        after, digest = self.unobservable_failure()
        receipt = self.assertSealed(after, "failed", qualifier="effects_unobservable")
        disposed = next(dict(e) for e in after.events if e["type"] == "failure_disposed")
        start = self.act("start", n=2)
        self.assertEqual(disposed["effect_snapshot"][start], "unknown")
        self.assertEqual(receipt["outcome_proof"]["units"], disposed["units"])
        self.assertEqual(receipt["outcome_proof"]["ground_occurred_at"], T0 - 1)
        moved = [e for e in after.events if e["type"] == "transitioned"][-1]
        self.assertEqual((moved["to"], moved["external_state"]), ("failed", "known"))
        self.assertEqual(HAZARD_SCHEMA, "transaction-hazard-marker/v1")
        self.assertIs(HAZARD_SCHEMA, transaction_receipt.HAZARD_SCHEMA)
        for key in KEYS:
            with self.subTest(key=key):
                self.assertEqual(self.store.hazard_markers(key), (digest,))
                self.assertEqual(json.loads(self.marker(key, digest).read_text()),
                                 {"schema": HAZARD_SCHEMA, "key": key, "receipt_digest": digest})
        self.assertEqual(self.store.hazard_markers("key:unmarked"), ())
        with self.assertRaises(StateInvalid):
            self.store.hazard_markers("")

    def test_every_unit_destroyed_seals_final_state_known_and_marks_nothing(self):
        self.parked()
        self.human()
        build, start = self.act("build", n=1), self.act("start", n=2)
        after = self.dispose("h-1", disposition=self.unobservable(
            units=[destroyed(build), destroyed(start)]))
        self.assertSealed(after, "failed", qualifier="final_state_known")
        self.assertFalse((self.root / "hazards").exists())
        self.assertEqual(self.store.hazard_markers(KEYS[0]), ())

    def test_post_terminal_observations_sit_beside_the_receipt_and_change_nothing(self):
        after, digest = self.unobservable_failure()
        receipt_path = self.root / "receipts" / (digest.removeprefix("sha256:") + ".json")
        before = (receipt_path.read_bytes(), self.state_doc(self.transaction_id))
        self.clock.advance(5)
        seen = {"outcome": "satisfied", "reason": "residue gone", "reference": "ops://recheck/1"}
        first = self.store.record_post_terminal(digest, observation=seen,
                                                contradicts_ground=False)
        second = self.store.record_post_terminal(
            digest, observation={**seen, "outcome": "unsatisfied"}, contradicts_ground=True)
        self.assertEqual((first["n"], second["n"]), (1, 2))
        self.assertEqual(OBSERVATION_SCHEMA, "transaction-post-terminal-observation/v1")
        listed = [dict(o) for o in self.store.post_terminal_observations(digest)]
        self.assertEqual(listed, [dict(first), dict(second)])
        self.assertEqual(listed[0], {
            "schema": OBSERVATION_SCHEMA, "receipt_digest": digest, "n": 1, "at": first["at"],
            "outcome": "satisfied", "reason": "residue gone", "reference": "ops://recheck/1",
            "contradicts_ground": False})
        self.assertGreater(first["at"], after.events[-1]["at"])
        self.assertTrue((self.root / "observations" / digest.removeprefix("sha256:")
                         / "2.json").is_file())
        self.assertEqual((receipt_path.read_bytes(), self.state_doc(self.transaction_id)),
                         before)
        self.assertEqual(self.store.load(self.transaction_id).state, "failed")

    def test_a_bad_post_terminal_observation_is_refused_before_any_write(self):
        after, digest = self.unobservable_failure()
        seen = {"outcome": "satisfied", "reason": "r", "reference": "ops://x"}
        for observation, contradicts in (({**seen, "extra": 1}, False),
                                         ({**seen, "outcome": "maybe"}, False),
                                         (seen, "yes")):
            with self.subTest(observation=observation, contradicts=contradicts):
                self.assertRefusedUnchanged(StateInvalid, lambda: self.store.record_post_terminal(
                    digest, observation=observation, contradicts_ground=contradicts))
        with self.assertRaises(ReceiptInvalid):
            self.store.record_post_terminal("sha256:" + "0" * 64, observation=seen,
                                            contradicts_ground=False)
        self.start_with(RECOVERY, key="known", keys=("key:known",))
        self.parked()
        self.grant()
        known = self.dispose().terminal["receipt_digest"]
        self.assertRefusedUnchanged(StateInvalid, lambda: self.store.record_post_terminal(
            known, observation=seen, contradicts_ground=True))
        self.assertEqual(self.store.record_post_terminal(
            known, observation=seen, contradicts_ground=False)["n"], 1)

    def test_a_tampered_marker_or_observation_fails_its_listing(self):
        after, digest = self.unobservable_failure()
        seen = {"outcome": "satisfied", "reason": "r", "reference": "ops://x"}
        self.store.record_post_terminal(digest, observation=seen, contradicts_ground=False)
        observation = (self.root / "observations" / digest.removeprefix("sha256:") / "1.json")
        for path, listing in ((self.marker(KEYS[0], digest),
                               lambda: self.store.hazard_markers(KEYS[0])),
                              (observation,
                               lambda: self.store.post_terminal_observations(digest))):
            with self.subTest(path=path.name):
                os.chmod(path, 0o644)
                document = json.loads(path.read_text())
                document["receipt_digest"] = "sha256:" + "1" * 64
                path.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
                with self.assertRaises(ReceiptInvalid):
                    listing()

    def test_a_result_after_the_seal_is_a_post_terminal_observation_not_a_ledger_write(self):
        after, digest = self.unobservable_failure()
        self.assertRefusedUnchanged(TransitionRefused, lambda: self.store.record_owner_result(
            self.transaction_id, executor_id="exec-a", subject_path=PATH,
            fence=plain(self.custody.fence), result={"late": True}))
        record = self.store.record_post_terminal(
            digest, observation={"outcome": "satisfied", "reason": "late owner result",
                                 "reference": "owner://exec-a"}, contradicts_ground=False)
        self.assertEqual(record["receipt_digest"], digest)
```

  (Also import `PATH` from `tests/test_transaction_custody.py`.)

  Add two more tests alongside these (Phase-5 S1, S2):
  - `test_a_canonically_reserialized_bad_observation_value_fails_its_listing`: record
    one observation, then for each of `outcome: "maybe"`, `contradicts_ground: "yes"`,
    `contradicts_ground: true` on a non-observability ground, and a malformed `at`,
    rewrite `1.json` with canonical `serialize` bytes (digest and `n` untouched) and
    assert `post_terminal_observations` raises `ReceiptInvalid`.
  - `test_a_marker_failure_leaves_no_terminal_and_a_retry_succeeds`: before the
    `effects_unobservable` disposal, create a regular file at the first key's `hazards/<key
    hex>` path so the marker directory cannot be made. Assert the disposal raises
    `ReceiptInvalid`, `state.json` and the lease bytes are unchanged, and the history has
    no `receipt_sealed`. Then remove the obstruction, dispose again, and assert it
    succeeds with both markers listed. The orphan receipt the first try left is
    tolerated (per D6).

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_disposition.py 2>&1 | tail -3`.
  Expected: ERROR (`HAZARD_SCHEMA` cannot be imported).

- [ ] **Step 3: Implement** the invariants. The exclusive-create helper gains a mode in
  which a collision raises `FileExistsError` to its caller, which the observation loop
  uses. The core wrappers stay one-line calls into `ReceiptStore`, with docstrings that
  point to its methods. If `transaction_core.py` passes 64000 bytes, apply the Global
  Constraints' docstring economy.

- [ ] **Step 4: Verify.**
  Run the slice unit command. Expected: `OK`.

```bash
for name in hazard_markers record_post_terminal post_terminal_observations; do
  grep -q "def $name" python/agent_tools/transaction_core.py || exit 1
done
grep -q "HAZARD_SCHEMA" python/agent_tools/transaction_core.py || exit 1
```

  Run: `git add -A python tests && just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.** Stage exactly this task's **Files**, then:

```bash
git commit -m "feat(transaction-core): hazard markers and post-terminal observations beside receipts (#209)"
```

- [ ] **Step 6: Check the review budget** with `FILES="python/agent_tools/transaction_receipt.py python/agent_tools/transaction_core.py tests/test_transaction_disposition.py"`.
  Expected: exit 0.

Decisions: per D6, D12, D16, D18, D22, D26, D29.
