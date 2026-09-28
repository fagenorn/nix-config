# Task 7: Renewal and lapse sweep rows, voided-forms column, CLAUDE.md

**Files:**
- Modify: `tests/transaction_core_sweep_support.py`
- Modify: `tests/test_transaction_core_sweep.py`
- Modify: `CLAUDE.md` (the "Agent helper package" paragraph's `transaction_core` sentence)

**Interfaces:**
- Consumes (Tasks 1–6, `agent_tools.transaction_core`): `TransactionStore(root, *,
  clock=)`, `.create(key, subject, *, concurrency_keys=)`, `.acquire(id, *, executor_id,
  subject_path, ttl_ms) -> Transaction` (`.custody`), `.advance(id, target, *, reason,
  external_state, custody)`, `.renew(custody)`, `.open_interval(custody, *,
  evidence_id)`, `.record_evidence(custody, *, evidence_id, form, reference)`,
  `.reap(id, *, reason)`, `.inspect_lease(key)`, `.load(id)` (`.evidence` entries with
  `evidence_id`, `form`, `seq`, `admissible`, `void_reason`), `FenceViolation`,
  `StaleCustody`. Fixtures: `World` (`clock` int seconds, `tick(seconds)`), `SHAPES`
  (profile `target.concurrency_keys`, `proof[*].temporal`).
- Produces: `drive(root: Path, shape: str, scenario: str) -> str` (the store is built
  inside, on the world clock); `SCENARIOS` gains `lease_renewal` and `lease_lapse`;
  `SWEEP` values become `(final, path, voided_forms)`.

**Invariants:**
- The store's clock is `lambda: world.clock * 1000`; TTL is `600_000` ms (per D22, D29).
- Evidence ids are `f"{obligation_id}@{n}"`, `n` counting that obligation's records from
  1; floor obligations use form `snapshot`, profile obligations their declared
  `temporal`; an `interval` obligation opens its interval before being observed.
- `lease_renewal`: tick 301 s on entering `proving` and again after half the obligations
  (`len // 2`), renewing each time; before sealing, every key's lease `term` must read 3
  or the executor parks (so a regression changes the landing).
- `lease_lapse`: after every obligation but the last is recorded, tick 601 s; the next
  write raises `StaleCustody`; the reaper reaps (`attention_required`, parked from
  `proving`); the executor reacquires (epoch 2), resumes to `proving`, recollects every
  obligation whose latest record is not admissible or is missing, and seals (D29).
- Every landing is asserted against a fresh `TransactionStore(root).load(id)`.

- [ ] **Step 1: Write the failing tests** — in `tests/test_transaction_core_sweep.py`
  replace the table, helpers and `SweepTableTest` with:

```python
LAPSED = WITH_ACTIVATION[:-1] + ("attention_required", "proving", "succeeded")
LAPSED_LIBRARY = WITHOUT_ACTIVATION[:-1] + ("attention_required", "proving", "succeeded")

# (shape, scenario) -> (final state, states the history passes through,
#                       temporal forms voided by the scenario)
SWEEP = {
    **{(shape, scenario): ("succeeded", path, frozenset())
       for shape, path in (("platform", WITH_ACTIVATION), ("product", WITH_ACTIVATION),
                           ("daemon", WITH_ACTIVATION), ("library", WITHOUT_ACTIVATION))
       for scenario in ("success", "lease_renewal")},
    ("platform", "lease_lapse"): ("succeeded", LAPSED, frozenset({"snapshot"})),
    ("product", "lease_lapse"): ("succeeded", LAPSED, frozenset({"snapshot"})),
    ("daemon", "lease_lapse"): ("succeeded", LAPSED, frozenset({"snapshot", "interval"})),
    ("library", "lease_lapse"): ("succeeded", LAPSED_LIBRARY, frozenset({"snapshot"})),
}
CUSTODY_EVENTS = {
    "success": ["lease_acquired", "lease_released"],
    "lease_renewal": ["lease_acquired", "lease_released"],
    "lease_lapse": ["lease_acquired", "lease_lapse_detected", "lease_reacquired",
                    "lease_released"],
}


def transitions(transaction):
    return [event for event in transaction.events if event["type"] == "transitioned"]


def states_passed(transaction):
    return ("created",) + tuple(event["to"] for event in transitions(transaction))


class SweepTableTest(unittest.TestCase):
    def test_the_table_covers_every_shape_for_every_ported_scenario(self):
        self.assertEqual(set(SWEEP), {(shape, scenario) for shape in SHAPES
                                      for scenario in SCENARIOS})

    def test_every_cell_lands_where_the_table_says(self):
        for (shape, scenario), (final, path, voided) in SWEEP.items():
            with self.subTest(shape=shape, scenario=scenario), \
                    tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                transaction_id = drive(root, shape, scenario)
                persisted = TransactionStore(root).load(transaction_id)
                self.assertEqual(persisted.creation_key, f"{shape}:{scenario}")
                self.assertEqual(persisted.state, final)
                self.assertEqual(states_passed(persisted), path)
                self.assertEqual({e["external_state"] for e in transitions(persisted)
                                  if e["to"] != "attention_required"}, {"known"})
                self.assertEqual([e["type"] for e in persisted.events
                                  if e["type"].startswith("lease_")],
                                 CUSTODY_EVENTS[scenario])
                self.assertEqual({e["form"] for e in persisted.evidence
                                  if not e["admissible"]}, voided)
                latest = {}
                for entry in persisted.evidence:
                    latest[entry["evidence_id"].rsplit("@", 1)[0]] = entry
                self.assertTrue(latest)
                self.assertTrue(all(entry["admissible"] for entry in latest.values()))
                if scenario == "lease_lapse":
                    lapse = next(e["seq"] for e in persisted.events
                                 if e["type"] == "lease_lapse_detected")
                    for entry in persisted.evidence:
                        if entry["seq"] < lapse:
                            self.assertEqual(entry["admissible"], entry["form"] == "event")
                            if not entry["admissible"]:
                                self.assertEqual(entry["void_reason"], "fence_changed")
                    self.assertIsNone(persisted.custody)
                for key in persisted.concurrency_keys:
                    record = TransactionStore(root).inspect_lease(key)
                    self.assertEqual((record["epoch"], record["holder"]),
                                     (2 if scenario == "lease_lapse" else 1, None))

    def test_the_lapse_row_exercises_every_temporal_form_before_the_lapse(self):
        with tempfile.TemporaryDirectory() as tmp:
            forms = set()
            for shape in ("product", "daemon"):
                (Path(tmp) / shape).mkdir()
                transaction_id = drive(Path(tmp) / shape, shape, "lease_lapse")
                persisted = TransactionStore(Path(tmp) / shape).load(transaction_id)
                lapse = next(e["seq"] for e in persisted.events
                             if e["type"] == "lease_lapse_detected")
                forms |= {e["form"] for e in persisted.evidence if e["seq"] < lapse}
            self.assertEqual(forms, {"event", "snapshot", "interval"})

    def test_recreating_a_driven_cell_returns_its_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = drive(Path(tmp), "library", "success")
            store = TransactionStore(Path(tmp))
            persisted = store.load(first)
            again = store.create("library:success", dict(persisted.subject),
                                 concurrency_keys=list(persisted.concurrency_keys))
            self.assertEqual(again.transaction_id, first)
            self.assertEqual(len(again.events), len(persisted.events))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core_sweep.py 2>&1 | tail -3`
Expected: FAIL — the coverage test fails (`SCENARIOS` lacks the two new scenarios) and
cells fail because `drive` still takes a store.

- [ ] **Step 3: Write the minimal implementation** — in `tests/transaction_core_sweep_support.py`:

1. `SCENARIOS` gains `"lease_renewal": {"faults": frozenset(), "note": "the lease is
   renewed twice in place during proving."}` and `"lease_lapse": {"faults": frozenset(),
   "note": "the lease lapses before the last obligation; reap, reacquire, recollect."}`.
   Update the module docstring: the walker now holds custody, renews and recollects;
   state it as the code behaves.
2. `drive(root, shape, scenario)`: `world = World()`; `store = TransactionStore(root,
   clock=lambda: world.clock * 1000)`; create with the profile's concurrency keys; hold
   the credential in `held["custody"]`, acquired before `ready → publishing` with
   `executor_id="fixture-executor"`, `subject_path=f"/fixture/{shape}"`, `ttl_ms=TTL_MS`.
3. Replace the obligation loop with a `prove(obligations)` pass over the obligation
   list (each obligation now also carries its form) that, for each obligation whose
   latest record is missing or not admissible (read from `store.load(id).evidence` by
   `evidence_id` prefix; an obligation whose latest record is admissible is skipped and
   counts as accepted for prerequisites): checks prerequisites as before, opens the interval for
   `interval`, observes via the adapter, and records with the next `@n` id and
   `reference=result["payload_ref"]`. Scenario hooks run inside it: `lease_renewal`
   ticks 301 s and renews on entry and after `len(obligations) // 2` records;
   `lease_lapse` ticks 601 s once, after `len(obligations) - 1` records.
4. Around `prove`: on `StaleCustody` (only possible in `lease_lapse`), call
   `store.reap(id, reason="lease expired during proving")`, reacquire with the same
   executor and path, `advance("proving", "resumed after reacquisition")` under the new
   credential, then run `prove` once more (no second lapse).
5. `lease_renewal`: before `advance("succeeded", …)`, raise `_Parked` unless every
   key's `inspect_lease(key)["holder"]["term"] == 3`.

6. Replace the comment above `SCENARIOS` with: "# `success` is ported from
   prototype-release-transactions/scenarios.py at dc98ba9; `lease_renewal` and
   `lease_lapse` are new in #205 (D22, D29)." In `tests/test_transaction_core_sweep.py`
   rewrite the module docstring's second paragraph to: "The prototype's autopilot printed
   where each (shape, scenario) cell landed; this table asserts it against persisted
   history, including each scenario's custody events and the evidence forms it voids."

In `CLAUDE.md`, replace the sentence beginning "`agent_tools.transaction_core` is the
transaction core's first slice (#204)" with: "`agent_tools.transaction_core` is the
transaction core's library surface, with no command-table row and no caller until #125's
cutover: slice 1 (#204) holds caller-rooted transaction state under a closed schema and
lifecycle, and slice 2 (#205) adds fenced custody — a lease authority over concurrency
keys in `agent_tools.transaction_custody`, epoch-fenced writes, and evidence and grant
admissibility derived from the fence — over the durable-file primitives in
`agent_tools.transaction_storage`."

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core_sweep.py 2>&1 | tail -3`
Expected: `OK`.

Run: `grep -c 'agent_tools.transaction_custody' CLAUDE.md` — Expected: `1`.

Run: `just agent-workflow-tests 2>&1 | tail -3` — Expected: `OK`.

Run: `just build 2>&1 | tail -3` — Expected: success (the Nix import check loads all
three modules).

- [ ] **Step 5: Commit**

```bash
git add tests/transaction_core_sweep_support.py tests/test_transaction_core_sweep.py CLAUDE.md
git commit -m "test(transaction-core): sweep lease renewal and lapse across shapes (#205)"
```
