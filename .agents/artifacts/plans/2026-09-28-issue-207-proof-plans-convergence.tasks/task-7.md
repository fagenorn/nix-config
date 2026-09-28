# Task 7: Five new sweep rows, `slow_collection` and CLAUDE.md

**Files:**
- Modify: `tests/transaction_core_world.py` (one fault)
- Modify: `tests/transaction_core_sweep_support.py` (five scenarios, the slow observer)
- Modify: `tests/test_transaction_core_sweep.py` (the landing table)
- Modify: `CLAUDE.md` (the `agent_tools.transaction_core` sentence)

**Interfaces:**
- Consumes (Task 6): `drive(root, shape, scenario, world=None) -> str`, `_Observer`,
  `SCENARIOS`, `shape_declaration`, and the proving stage (first pass, converge loop,
  renewal after every cohort collection). From the fixtures, it uses the faults
  `partial_publication`, `activation_failure`, `stale_health` and `member_stale`, which
  are already in `FAULTS` and already wired into the shapes' adapters.
- Produces (fixtures only, per D14):
  - `FAULTS` gains `"slow_collection",  # every collection inside a cohort takes 250 s`.
  - In `_Observer.observe`, first thing: when `"slow_collection"` is in
    `world.faults` and `request["cohort"] is not None`, `world.tick(250)`.
  - `SCENARIOS` gains, after `resume_after_crash`:
    - `partial_publication` (faults `{"partial_publication"}`);
    - `failed_activation` (`{"activation_failure"}`);
    - `stale_false_positive_health` (`{"stale_health"}`);
    - `expired_snapshot` (`{"slow_collection"}`);
    - `fleet_stall` (`{"member_stale"}`).

    Each gets a `note` (the prototype's, reworded to this executor). The comment above
    `SCENARIOS` says these five come from `dc98ba9` in #207, with `expired_snapshot`'s 250 s
    tick moved into cohort collection.

**Invariants:**
- The committed landing table below is the spec's `#### Expected landings`, asserted
  cell for cell against a freshly loaded store (per D14, D16, D17). The earlier twenty
  cells keep their own table and assertions.
- Every parked cell:
  - ends in `attention_required`;
  - holds its single `lease_acquired` custody, with no `lease_released` and a non-None
    `custody`;
  - reaches no `recovering`, `rolled_back` or `failed`;
  - makes at most one invoke per action.
- A proof park carries `settle_proof`'s reserved reason on its last transition. The
  executor never advances after `settle_proof` parks.
- The CLAUDE.md sentence names slice 4 (#207), `agent_tools.transaction_plan`,
  `agent_tools.transaction_proof` and `transaction-state/v4`, and keeps "no command-table
  row and no caller until #125's cutover".

- [ ] **Step 1: Write the failing tests.** In `tests/test_transaction_core_sweep.py`, add
  after `CUSTODY_EVENTS`:

```python
PUB_PARK = WITH_ACTIVATION[:4] + ("attention_required",)
ACT_PARK = WITH_ACTIVATION[:6] + ("attention_required",)
PROOF_PARK = WITH_ACTIVATION[:7] + ("attention_required",)


def succeeded(shape, **expect):
    return ("succeeded", WITHOUT_ACTIVATION if shape == "library" else WITH_ACTIVATION,
            expect)


def published(first, second, **more):
    return {first: "satisfied", second: "satisfied", **more}


# (shape, scenario) -> (final state, path, expectations): #207's committed landings.
LANDINGS = {
    ("platform", "partial_publication"): ("attention_required", PUB_PARK, {
        "actions": {"build_closure": "satisfied", "tag_release": "diverged"}}),
    ("product", "partial_publication"): ("attention_required", PUB_PARK, {
        "actions": {"build_image": "satisfied", "index_channel": "diverged"}}),
    ("daemon", "partial_publication"): ("attention_required", PUB_PARK, {
        "actions": {"build_helpers": "satisfied", "stage_helpers": "diverged"}}),
    ("library", "partial_publication"): ("attention_required", PUB_PARK, {
        "actions": {"upload_artifact": "satisfied", "bind_version": "diverged"}}),
    ("platform", "failed_activation"): ("attention_required", ACT_PARK, {
        "actions": published("build_closure", "tag_release", switch_host_a="diverged")}),
    ("product", "failed_activation"): ("attention_required", ACT_PARK, {
        "actions": published("build_image", "index_channel", deploy_api="diverged")}),
    ("daemon", "failed_activation"): ("attention_required", ACT_PARK, {
        "actions": published("build_helpers", "stage_helpers", install_job="diverged")}),
    ("library", "failed_activation"): succeeded("library"),
    ("platform", "stale_false_positive_health"): ("attention_required", PROOF_PARK, {
        "reason": "proof_rejected", "rejected": ["switch_host_a", "switch_host_b"],
        "satisfied": []}),
    ("product", "stale_false_positive_health"): ("attention_required", PROOF_PARK, {
        "reason": "proof_rejected", "rejected": ["deploy_api", "deploy_admin"],
        "satisfied": ["api_liveness", "admin_liveness"]}),
    ("daemon", "stale_false_positive_health"): ("attention_required", PROOF_PARK, {
        "reason": "proof_rejected", "rejected": ["install_job", "restart_job"],
        "satisfied": ["job_liveness"]}),
    ("library", "stale_false_positive_health"): succeeded("library"),
    ("platform", "expired_snapshot"): ("attention_required", PROOF_PARK, {
        "reason": "proof_did_not_converge", "failed": ["cohort_expired"] * 3,
        "exhausted_by": "budget"}),
    ("product", "expired_snapshot"): ("attention_required", PROOF_PARK, {
        "reason": "proof_did_not_converge", "failed": ["cohort_expired"] * 2,
        "exhausted_by": "window"}),
    ("daemon", "expired_snapshot"): ("attention_required", PROOF_PARK, {
        "reason": "proof_did_not_converge", "failed": ["cohort_expired"] * 2,
        "exhausted_by": "window"}),
    ("library", "expired_snapshot"): succeeded("library", members=[]),
    ("platform", "fleet_stall"): succeeded("platform"),
    ("product", "fleet_stall"): ("attention_required", ACT_PARK, {
        "actions": published("build_image", "index_channel", deploy_api="satisfied",
                             deploy_admin="satisfied", converge_fleet="in_progress")}),
    ("daemon", "fleet_stall"): succeeded("daemon"),
    ("library", "fleet_stall"): succeeded("library"),
}
```

  Change `test_the_table_covers_every_shape_for_every_ported_scenario` to compare
  `set(SWEEP) | set(LANDINGS)` with the full product, and assert `set(SWEEP) &
  set(LANDINGS) == set()`. Add to `SweepTableTest`:

```python
    def test_every_new_row_lands_where_the_committed_table_says(self):
        for (shape, scenario), (final, path, expect) in LANDINGS.items():
            with self.subTest(shape=shape, scenario=scenario), \
                    tempfile.TemporaryDirectory() as tmp:
                world = World()
                transaction_id = drive(Path(tmp), shape, scenario, world=world)
                persisted = TransactionStore(Path(tmp)).load(transaction_id)
                types = [e["type"] for e in persisted.events]
                self.assertEqual((persisted.state, states_passed(persisted)), (final, path))
                self.assertTrue(set(world.invokes.values()) <= {1})
                names = {u["action_id"]: u["name"] for u in persisted.proof_plan["units"]}
                observed = [e for e in persisted.events if e["type"] == "obligation_observed"]
                cohorts = persisted.proof["cohorts"]
                if final == "succeeded":
                    self.assertEqual(CUSTODY_EVENTS["success"],
                                     [t for t in types if t.startswith("lease_")])
                    self.assertEqual([c["status"] for c in cohorts], ["sealed"])
                    if "members" in expect:
                        self.assertEqual(persisted.proof_plan["cohort"]["members"],
                                         expect["members"])
                    continue
                self.assertEqual([t for t in types if t.startswith("lease_")],
                                 ["lease_acquired"])
                self.assertIsNotNone(persisted.custody)
                last = transitions(persisted)[-1]
                if "actions" in expect:
                    self.assertEqual({a["name"]: a["status"] for a in persisted.actions},
                                     expect["actions"])
                    self.assertEqual(observed, [])
                    stuck = [a["action_id"] for a in persisted.actions
                             if a["status"] != "satisfied"]
                    self.assertEqual([world.invokes[a] for a in stuck], [1])
                    continue
                self.assertEqual(last["reason"], expect["reason"])
                self.assertEqual(last["external_state"], "known")
                if expect["reason"] == "proof_rejected":
                    [rejected] = [e for e in persisted.events if e["type"] == "proof_rejected"]
                    self.assertEqual([names[i.rsplit(":", 1)[1]] for i in rejected["obligations"]],
                                     expect["rejected"])
                    self.assertEqual(cohorts, [])
                    latest = {o["obligation_id"]: o["latest_outcome"]
                              for o in persisted.proof["obligations"]}
                    for obligation_id in expect["satisfied"]:
                        self.assertEqual(latest[obligation_id], "satisfied")
                else:
                    self.assertEqual([(c["status"], c["reason"]) for c in cohorts],
                                     [("failed", r) for r in expect["failed"]])
                    [exhausted] = [e for e in persisted.events
                                   if e["type"] == "proof_convergence_exhausted"]
                    self.assertEqual((exhausted["cohorts"], exhausted["exhausted_by"]),
                                     (len(expect["failed"]), expect["exhausted_by"]))
                    park = last["seq"]
                    self.assertFalse([e for e in persisted.events if e["seq"] > park])
```

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core_sweep.py 2>&1 | tail -3`.
  Expected: FAIL, `KeyError: 'partial_publication'` (the scenario is not in `SCENARIOS`).

- [ ] **Step 3: Implement** the fixture changes under **Produces**. In `CLAUDE.md`, after
  slice 3's clause of the `agent_tools.transaction_core` sentence, add that slice 4 (#207)
  adds an immutable proof plan compiled at creation (`agent_tools.transaction_plan`),
  core-collected obligations, and one convergence cohort that `settle_proof` alone seals
  into `succeeded` or parks (`agent_tools.transaction_proof`); name `transaction-state/v4`
  instead of `v3`. Rewrite the support module's
  docstring from the implemented executor, adding the slow cohort collection.

- [ ] **Step 4: Verify.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core_sweep.py 2>&1 | tail -3`.
  Expected: `OK` (twenty earlier cells plus twenty new ones).

```bash
[ "$(grep -c 'agent_tools.transaction_proof' CLAUDE.md)" = 1 ] || exit 1
[ "$(grep -c 'agent_tools.transaction_plan' CLAUDE.md)" = 1 ] || exit 1
if grep -q 'transaction-state/v3' CLAUDE.md; then exit 1; fi
grep -q '"slow_collection"' tests/transaction_core_world.py || exit 1
```

  Final gate for the whole plan:
  Run: `just agent-workflow-tests 2>&1 | tail -3`. Expected: `OK`.
  Run: `just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.** Stage exactly this task's **Files**, then:

```bash
git commit -m "test(transaction-core): sweep proof rejection and non-convergence (#207)"
```

- [ ] **Step 6: Check the review budget for the whole slice** (after the commit): run
  the root's review-budget block with `FILES="python/agent_tools/transaction_*.py tests/test_transaction_plan.py tests/test_transaction_proof.py tests/test_transaction_core.py tests/test_transaction_custody.py tests/test_transaction_invocation.py tests/transaction_core_world.py tests/transaction_core_sweep_support.py tests/test_transaction_core_sweep.py CLAUDE.md justfile"`.
  Expected: exit 0.

Decisions: per D14, D16, D17, D29.
