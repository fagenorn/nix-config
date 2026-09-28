# Task 8: Five recovery rows in the sweep, and CLAUDE.md

**Files:**
- Modify: `tests/transaction_core_sweep_support.py` (scenarios, mutations, the recovery step)
- Modify: `tests/test_transaction_core_sweep.py` (the committed recovery table)
- Modify: `CLAUDE.md` (the transaction-core sentence)

**Interfaces:**
- Consumes (Tasks 1–7): `TransactionStore.issue_grant`, `begin_recovery`,
  `invoke_action`, `inspect_action`, `settle_recovery`, `roll_forward`, `advance`;
  `Transaction.recovery_plan`, `.recovery`; `RecoveryRefused`, `RecoveryPlanRejected`;
  sweep support's `recovery_declaration`, `_Router`, `_Effect`, `World.notes`.
- Produces: `SCENARIOS` entries `rollback`, `irreversible_migration`,
  `incompatible_restore`, `missing_rollback_anchor` and `unsupported_operation`, each with
  `"recover": True`. The last also carries `"mutate": _add_unsupported_publication`, and
  `irreversible_migration` carries `"mutate": _first_activation_supersedable`. There is one
  committed `RECOVERIES` table.

**Invariants:**
- Faults (per D14): `rollback` is `{"activation_failure"}`, `irreversible_migration` is
  `{"activation_failure"}`, `incompatible_restore` is `{"activation_failure",
  "restore_incompatible"}`, `missing_rollback_anchor` is `{"missing_anchor"}`, and
  `unsupported_operation` has none. The ten earlier scenarios carry no `recover` and no
  `mutate`, so they land exactly as before (per D13).
- `drive` applies `mutate(profile, registry)` right after building the shape. It builds
  `proof` and `recovery` once, from the mutated profile. `RecoveryPlanRejected` from
  `create` propagates, so nothing is written (per D23).
- After a `_Parked` park, and only when `SCENARIOS[scenario].get("recover")`, the recovery
  step runs (per D13, D14):
  1. `issue_grant(grant_id="recovery-1", actor="fixture-operator")`, then `begin_recovery`
     with the router observer.
  2. On `RecoveryRefused`, append `str(refused)` to `world.notes`. Then: `no_effect` →
     `advance("abandoned", "no release effect exists")`; `unit_not_restorable` or
     `restore_incompatible` → `roll_forward(grant_id="recovery-1", reason=refused.reason,
     creation_key=f"{shape}:{scenario}:forward", subject={**subject, "candidate":
     subject["candidate"] + "-forward"}, concurrency_keys=keys, proof=proof,
     recovery=recovery)`; any other reason → stay parked.
  3. Once admitted: for each id in `recovery["selected"]`, find its edge and unit in
     `recovery_plan`. Drive it through `effects[unit["effect"]]` with `name =
     edge["operation"]` and `parameters = edge["parameters"]`, as `run_phase` drives a node,
     finding the view by `action_id`. Stop driving that edge at any status other than
     `absent`. Then call `settle_recovery`; a refusal there propagates.
- `_add_unsupported_publication(profile, registry)` ports `dc98ba9`'s mutation. It adds a
  publication node `{"id": "unsupported_promote", "mode": "promote", "binding": <first
  non-`_` binding whose adapter's `modes["promote"] != "supported"`>, "deps": [],
  "effect_class": "reversible_no_incremental_spend", "expected_subject": {"note":
  "authored against an unsupported mode"}}`. It adds a recovery entry `{"posture":
  "manual_only", "binding": <that alias>}`. With no such binding it raises `ValueError`.
- `_first_activation_supersedable(profile, registry)`: with activation `"none"` it changes
  nothing. Otherwise the first activation node's recovery entry becomes `{"posture":
  "supersedable_only", "binding": <its binding>}`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_transaction_core_sweep.py`, import
  `RecoveryPlanRejected` from `agent_tools.transaction_core`, add beside `ACT_PARK`:

```python
ROLLED = ACT_PARK + ("recovering", "rolled_back")
ABANDON = WITH_ACTIVATION[:3] + ("attention_required", "abandoned")
TS, DV, NE = "target_satisfied", "diverged", "no_effect"


def rolled(snapshot, selected, checked, restored, residue):
    return ("rolled_back", ROLLED, {"snapshot": snapshot, "selected": selected,
                                    "checked": checked, "restored": restored,
                                    "residue": residue})


def forward(reason, named, anchors=None):
    return ("attention_required", ACT_PARK, {"forward": reason, "named": named,
                                             "anchors": anchors})


# (shape, scenario) -> (final, path, expectations): #208's committed recovery landings.
RECOVERIES = {
    ("platform", "rollback"): rolled(
        {"build_closure": TS, "tag_release": TS, "switch_host_a": DV, "switch_host_b": NE},
        [("build_closure", "compensate"), ("tag_release", "compensate"),
         ("switch_host_a", "restore"), ("switch_host_a", "compensate")],
        ["switch_host_a"], ["switch_host_a"], ["build_closure", "tag_release", "switch_host_a"]),
    ("product", "rollback"): rolled(
        {"build_image": TS, "index_channel": TS, "deploy_api": DV, "deploy_admin": NE,
         "converge_fleet": NE},
        [("build_image", "compensate"), ("index_channel", "restore"), ("deploy_api", "restore")],
        ["index_channel", "deploy_api"], ["index_channel", "deploy_api"], ["build_image"]),
    ("daemon", "rollback"): rolled(
        {"build_helpers": TS, "stage_helpers": TS, "install_job": DV, "restart_job": NE},
        [("build_helpers", "compensate"), ("stage_helpers", "restore"),
         ("install_job", "restore")],
        ["stage_helpers", "install_job"], ["stage_helpers", "install_job"], ["build_helpers"]),
    ("platform", "irreversible_migration"): forward("unit_not_restorable", "switch_host_a",
                                                    ["switch_host_b"]),
    ("product", "irreversible_migration"): forward(
        "unit_not_restorable", "deploy_api", ["index_channel", "deploy_admin", "converge_fleet"]),
    ("daemon", "irreversible_migration"): forward("unit_not_restorable", "install_job",
                                                  ["stage_helpers", "restart_job"]),
    ("platform", "incompatible_restore"): forward("restore_incompatible", "switch_host_a"),
    ("product", "incompatible_restore"): forward("restore_incompatible", "index_channel"),
    ("daemon", "incompatible_restore"): forward("restore_incompatible", "stage_helpers"),
    **{(shape, "missing_rollback_anchor"): ("abandoned", ABANDON, {"missing": unit})
       for shape, unit in (("platform", "switch_host_a"), ("product", "index_channel"),
                           ("daemon", "stage_helpers"))},
    **{("library", scenario): succeeded("library")
       for scenario in ("rollback", "irreversible_migration", "incompatible_restore",
                        "missing_rollback_anchor")},
    **{(shape, "unsupported_operation"): ("rejected", None, {"binding": binding})
       for shape, binding in (("platform", "nix"), ("product", "api"), ("daemon", "job"),
                              ("library", "index"))},
}
```

  Make `test_the_table_covers_every_shape_for_every_ported_scenario` assert that `SWEEP`,
  `LANDINGS` and `RECOVERIES` are pairwise disjoint and together cover every
  `(shape, scenario)`. Then add to `SweepTableTest`:

```python
    def test_every_recovery_row_lands_where_the_committed_table_says(self):
        for (shape, scenario), (final, path, expect) in RECOVERIES.items():
            with self.subTest(shape=shape, scenario=scenario), \
                    tempfile.TemporaryDirectory() as tmp:
                root, world = Path(tmp), World()
                if final == "rejected":
                    with self.assertRaises(RecoveryPlanRejected) as caught:
                        drive(root, shape, scenario, world=world)
                    self.assertEqual(caught.exception.reason, "unsupported_operation")
                    self.assertIn(f"unit 'unsupported_promote' operation 'promote' is not "
                                  f"offered by effect {expect['binding']!r}",
                                  str(caught.exception))
                    self.assertEqual((list(root.iterdir()), world.invokes), ([], {}))
                    continue
                transaction_id = drive(root, shape, scenario, world=world)
                store = TransactionStore(root)
                persisted = store.load(transaction_id)
                types = [e["type"] for e in persisted.events]
                self.assertEqual((persisted.state, states_passed(persisted)),
                                 (final, path or WITHOUT_ACTIVATION))
                self.assertTrue(set(world.invokes.values()) <= {1})
                if final == "succeeded":
                    self.assertNotIn("recovery_started", types)
                    continue
                plan = persisted.recovery_plan
                names = {u["action_id"]: u["name"] for u in plan["units"]}
                edges = {e["action_id"]: (u["name"], e["action"])
                         for u in plan["units"] for e in u["edges"]}
                last = {e["type"]: e for e in persisted.events}
                leases = [t for t in types if t.startswith("lease_")]
                if final == "rolled_back":
                    started, settled = last["recovery_started"], last["recovery_settled"]
                    self.assertEqual({names[i]: c for i, c in started["effect_snapshot"].items()},
                                     expect["snapshot"])
                    self.assertEqual([edges[i] for i in started["selected"]], expect["selected"])
                    self.assertEqual([names[c["unit"]] for c in started["checks"]],
                                     expect["checked"])
                    self.assertEqual([names[i] for i in settled["restored"]], expect["restored"])
                    self.assertEqual([names[r["unit"]] for r in settled["residue"]],
                                     expect["residue"])
                    self.assertEqual([world.invokes.get(i) for i in started["selected"]],
                                     [1] * len(started["selected"]))
                    self.assertEqual(leases, ["lease_acquired", "lease_released"])
                elif final == "abandoned":
                    self.assertIn(f"{expect['missing']} (", transitions(persisted)[-2]["reason"])
                    self.assertIn("rollback_anchor_missing", world.notes[0])
                    self.assertIn("no_effect", world.notes[-1])
                    self.assertEqual((persisted.actions, world.invokes), ((), {}))
                    self.assertEqual(leases, ["lease_acquired", "lease_released"])
                else:
                    link = persisted.events[-1]
                    self.assertEqual((link["type"], link["reason"]),
                                     ("roll_forward_linked", expect["forward"]))
                    self.assertIn(f"{expect['named']} (", world.notes[-1])
                    self.assertEqual(leases, ["lease_acquired"])
                    self.assertNotIn("recovery_started", types)
                    self.assertTrue({a["name"] for a in persisted.actions} <= set(names.values()))
                    child = store.load(link["child_transaction_id"])
                    self.assertNotEqual(child.transaction_id, transaction_id)
                    self.assertEqual((child.state, child.recovery["recovers"], child.creation_key),
                                     ("created", transaction_id, f"{shape}:{scenario}:forward"))
                    if expect["anchors"] is not None:
                        [anchors] = [e for e in persisted.events if e["type"] == "anchors_verified"]
                        self.assertEqual([names[a["unit"]] for a in anchors["anchors"]],
                                         expect["anchors"])
```

  In the sweep support, add the five scenarios, the two mutations, the `drive` changes and
  the recovery step as the invariants say. Rewrite the module docstring's sentence
  "It carries none of the prototype's authorization or recovery logic". It should say
  instead that the recovery step runs only in `recover`-flagged scenarios, and that
  `drive` lets a rejected recovery declaration propagate.

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core_sweep.py 2>&1 | tail -3`.
  Expected: FAIL or ERROR (the new scenarios are not in `SCENARIOS`).

- [ ] **Step 3: Implement** the invariants. In `CLAUDE.md`, replace the sentence tail
  `, with the \`transaction-state/v4\` validator and snapshot fold in
  \`agent_tools.transaction_history\`, over the durable-file primitives in
  \`agent_tools.transaction_storage\`.` with:

  `; slice 5 (#208) adds an immutable recovery plan compiled at creation beside it (\`agent_tools.transaction_recovery_plan\`), rollback anchors verified in \`ready\` before publication, \`abandoned\` only while no action has had an effect, and \`begin_recovery\`, \`settle_recovery\` and \`roll_forward\` as the only ways into \`recovering\`, into \`rolled_back\` and to a linked child transaction (\`agent_tools.transaction_recovery\`), with the \`transaction-state/v5\` validator and snapshot fold in \`agent_tools.transaction_history\`, over the durable-file primitives in \`agent_tools.transaction_storage\`.`

- [ ] **Step 4: Verify.**
  Run the slice unit command with all three recovery test files. Expected: `OK`.
  Run: `just agent-workflow-tests 2>&1 | tail -3`. Expected: `OK`.

```bash
grep -q "transaction-state/v5" CLAUDE.md || exit 1
if grep -q "transaction-state/v4" CLAUDE.md; then exit 1; fi
grep -q '"missing_rollback_anchor"' tests/transaction_core_sweep_support.py || exit 1
```

  Run: `just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.** Stage exactly this task's **Files**, then:

```bash
git commit -m "test(transaction-core): sweep five recovery rows across the four shapes (#208)"
```

- [ ] **Step 6: Check the review budget** with `FILES="tests/transaction_core_sweep_support.py tests/test_transaction_core_sweep.py CLAUDE.md"`.
  Expected: exit 0.

Decisions: per D13, D14, D18, D23.
