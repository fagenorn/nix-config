# Task 6: The full sweep gate, and CLAUDE.md

**Files:**
- Modify: `tests/transaction_core_world.py` (the `unobservable_after_invoke` fault)
- Modify: `tests/transaction_core_sweep_support.py` (the `unknown_external_state` row,
  the executor's dispositions, `PROTOTYPE_SCENARIOS`, `GAP_CELLS`, docstring)
- Modify: `tests/test_transaction_core_sweep.py` (`DISPOSALS`, the receipt assertions,
  the gate and gap-cell tests, docstring)
- Modify: `CLAUDE.md` (the `agent_tools.transaction_core` sentence)

**Interfaces:**
- Consumes (Tasks 1–5): `dispose_failed`, `DispositionRefused` (message `"<id>:
  disposition refused: <reason>: <detail>"`), `read_receipt`, the receipt's `outcome`
  and `postconditions`, `AUTHORITY_CLASS` in the sweep support, and the existing
  `drive`, `SCENARIOS`, `SWEEP`, `LANDINGS`, `RECOVERIES`, `CUSTODY_EVENTS`,
  `PUB_PARK`, `states_passed` and `transitions`.
- Produces: `PROTOTYPE_SCENARIOS: tuple[str, ...]` and `GAP_CELLS: dict[str, str]` in
  `tests/transaction_core_sweep_support.py`, and `DISPOSALS` in
  `tests/test_transaction_core_sweep.py`.

**Invariants:**
- `FAULTS` gains `"unobservable_after_invoke"` with the comment `# the first applied
  invoke leaves every later inspection unknown`. `SimAdapter.invoke` arms it on each
  path that returns `accepted`: right after it writes `World.effects[key]`, when that
  fault is in `World.faults`, it adds `"unknown_inspection"` (per D14).
- `SCENARIOS["unknown_external_state"] = {"faults":
  frozenset({"unobservable_after_invoke"}), "recover": True, "note": ...}`. The note says
  that the first publication action is applied and then becomes unobservable, and that
  recovery and both dispositions are refused. The comment above the last rows gains
  that it comes from `dc98ba9` in #209 (D14).
- In `recover()`, a `begin_recovery` refused `effect_uncertain`, and only that reason,
  runs `dispose()`. That tries `dispose_failed` twice under grant `recovery-1`, and each
  `DispositionRefused` is appended to `world.notes`. The first try is
  `{"ground": "no_recovery_path", "reference": "fixture: no recovery path",
  "occurred_at": None, "successor": None, "units": []}`. The second is `{"ground":
  "authority_retired", "reference": "fixture: authority retired", "occurred_at":
  world.clock * 1000, "successor": None, "units": [{"unit": <id>, "consequence":
  "effects_possibly_live_unobservable", "residue_bound": "unbounded", "recheck":
  "fixture: re-read the target"} for each action whose view has attempts]}`. Any other
  exception propagates. The executor never issues a `human` grant (per D14).
- `PROTOTYPE_SCENARIOS` is the fourteen `dc98ba9` names, in `SCENARIOS` order, without
  `lease_renewal` and `lease_lapse`. `GAP_CELLS = {"subject identity":
  "stale_false_positive_health", "lease loss": "resume_after_crash", "convergence
  livelock": "expired_snapshot", "unobservable release": "unknown_external_state"}`
  (per D15).
- `DISPOSALS = {(shape, "unknown_external_state"): ("attention_required", PUB_PARK) for
  every shape}` joins the disjoint-cover test's tables.
- `assertReceipt(root, persisted)` on `SweepTableTest` works as follows. A terminal
  state (`succeeded`, `rolled_back`, `abandoned`) must have `receipt_sealed` as its last
  event, a `read_receipt` whose `outcome` is the state, and a receipt file whose bytes
  minus the final newline hash to the digest. A `succeeded` cell must also have every
  postcondition `observed` and `effected`. Any other state must have no
  `receipt_sealed`. It is called right after each `load` in
  `test_every_cell_lands_where_the_table_says`,
  `test_every_new_row_lands_where_the_committed_table_says`,
  `test_every_recovery_row_lands_where_the_committed_table_says` (every non-rejected row)
  and the new `DISPOSALS` test. No earlier expectation changes.
- The sweep support's module docstring gains the `unknown_external_state` executor
  behavior. The sweep test's module docstring says every terminal cell's receipt is
  asserted against its bytes.
- CLAUDE.md, in the `agent_tools.transaction_core` sentence: `with the
  \`transaction-state/v5\` validator` becomes `v6`. After the slice-5 clause, and before
  `, with the`, insert `; slice 6 (#209) seals a permanent, content-addressed terminal
  receipt under the store root's \`receipts/\` in the same write that enters every
  terminal, and reads it back on every load (\`agent_tools.transaction_receipt\`), and
  makes \`dispose_failed\` the only way into \`failed\`: it takes a fresh grant and one
  closed ground, and it yields an \`effects_unobservable\` qualifier with per-key hazard
  markers only when a human grant at the transaction's authority class asserts an
  observability ground (\`agent_tools.transaction_disposition\`)`. Check every clause
  against the shipped code before committing, and reword to match the code where it
  differs. The #204–#208 specs stay unedited.

- [ ] **Step 1: Write the failing tests.** In `tests/test_transaction_core_sweep.py`,
  add `import hashlib`, import `GAP_CELLS` and `PROTOTYPE_SCENARIOS` from the sweep
  support, add `DISPOSALS` after `RECOVERIES`, add `set(DISPOSALS)` to `tables` in
  `test_the_table_covers_every_shape_for_every_ported_scenario`, insert the
  `assertReceipt` calls, and add to `SweepTableTest`:

```python
    def assertReceipt(self, root, persisted):
        types = [e["type"] for e in persisted.events]
        if persisted.state not in ("succeeded", "rolled_back", "abandoned"):
            self.assertNotIn("receipt_sealed", types)
            return
        seal = persisted.events[-1]
        self.assertEqual(seal["type"], "receipt_sealed")
        receipt = TransactionStore(root).read_receipt(seal["receipt_digest"])
        self.assertEqual(receipt["outcome"], persisted.state)
        path = root / "receipts" / (seal["receipt_digest"].removeprefix("sha256:") + ".json")
        self.assertEqual("sha256:" + hashlib.sha256(path.read_bytes()[:-1]).hexdigest(),
                         seal["receipt_digest"])
        if persisted.state == "succeeded":
            self.assertTrue(receipt["postconditions"])
            self.assertTrue(all(p["observed"] is not None and p["effected"]
                                for p in receipt["postconditions"]))

    def test_an_unobservable_release_parks_and_no_disposition_is_admitted(self):
        for (shape, scenario), (final, path) in DISPOSALS.items():
            with self.subTest(shape=shape), tempfile.TemporaryDirectory() as tmp:
                root, world = Path(tmp), World()
                transaction_id = drive(root, shape, scenario, world=world)
                persisted = TransactionStore(root).load(transaction_id)
                self.assertReceipt(root, persisted)
                self.assertEqual((persisted.state, states_passed(persisted)), (final, path))
                self.assertEqual(transitions(persisted)[-1]["external_state"], "unknown")
                first = next(e["action_id"] for e in persisted.events
                             if e["type"] == "action_declared")
                self.assertIn(first, {u["action_id"] for u in persisted.proof_plan["units"]
                                      if u["phase"] == "publication"})
                self.assertEqual(world.invokes, {first: 1})
                self.assertEqual({a["action_id"]: a["status"] for a in persisted.actions
                                  if a["attempts"]}, {first: "unknown"})
                self.assertEqual([note.split(" refused: ")[1].split(":")[0]
                                  for note in world.notes],
                                 ["effect_uncertain", "effect_uncertain", "human_required"])
                types = [e["type"] for e in persisted.events]
                self.assertNotIn("failure_disposed", types)
                self.assertFalse((root / "receipts").exists())
                self.assertIsNotNone(persisted.custody)

    def test_the_gate_is_the_fourteen_prototype_scenarios_by_four_shapes(self):
        self.assertEqual(PROTOTYPE_SCENARIOS, (
            "success", "throttled_retry", "resume_after_crash", "partial_publication",
            "failed_activation", "stale_false_positive_health", "expired_snapshot",
            "fleet_stall", "rollback", "irreversible_migration", "incompatible_restore",
            "missing_rollback_anchor", "unsupported_operation", "unknown_external_state"))
        self.assertEqual(set(SCENARIOS) - set(PROTOTYPE_SCENARIOS),
                         {"lease_renewal", "lease_lapse"})
        self.assertEqual((len(SHAPES) * len(PROTOTYPE_SCENARIOS), len(SHAPES) * len(SCENARIOS)),
                         (56, 64))

    def test_the_four_gap_cells_sit_on_the_rows_that_exhibit_them(self):
        self.assertEqual(GAP_CELLS, {
            "subject identity": "stale_false_positive_health", "lease loss": "resume_after_crash",
            "convergence livelock": "expired_snapshot",
            "unobservable release": "unknown_external_state"})
        self.assertTrue(set(GAP_CELLS.values()) <= set(PROTOTYPE_SCENARIOS))
        self.assertEqual(LANDINGS[("platform", GAP_CELLS["subject identity"])][2]["reason"],
                         "proof_rejected")
        self.assertIn("lease_reacquired", CUSTODY_EVENTS[GAP_CELLS["lease loss"]])
        self.assertEqual(LANDINGS[("platform", GAP_CELLS["convergence livelock"])][2]["reason"],
                         "proof_did_not_converge")
        self.assertIn(("platform", GAP_CELLS["unobservable release"]), DISPOSALS)
```

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core_sweep.py 2>&1 | tail -3`.
  Expected: ERROR (`GAP_CELLS` cannot be imported).

- [ ] **Step 3: Implement** the world fault, the scenario row, `dispose()` inside `drive`
  (it imports `DispositionRefused` from `agent_tools.transaction_core`), the two
  constants, the docstrings and the CLAUDE.md sentence.

- [ ] **Step 4: Verify.**
  Run the slice unit command. Expected: `OK`.

```bash
grep -q "transaction-state/v6" CLAUDE.md || exit 1
grep -q "agent_tools.transaction_disposition" CLAUDE.md || exit 1
if grep -q "transaction-state/v5" CLAUDE.md; then exit 1; fi
grep -q '"unobservable_after_invoke"' tests/transaction_core_world.py || exit 1
```

  Run: `just agent-workflow-tests 2>&1 | tail -3`. Expected: success.
  Run: `git add -A tests CLAUDE.md && just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.** Stage exactly this task's **Files**, then:

```bash
git commit -m "test(transaction-core): port unknown_external_state and assert every terminal receipt (#209)"
```

- [ ] **Step 6: Check the review budget** with `FILES="tests/transaction_core_world.py tests/transaction_core_sweep_support.py tests/test_transaction_core_sweep.py CLAUDE.md"`.
  Expected: exit 0.

Decisions: per D4, D14, D15, D16.
