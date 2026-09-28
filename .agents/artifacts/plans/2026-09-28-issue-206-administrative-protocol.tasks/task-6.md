# Task 6: Sweep rows `throttled_retry` and `resume_after_crash`, attempts column, CLAUDE.md

**Files:**
- Modify: `tests/transaction_core_world.py`
- Modify: `tests/transaction_core_sweep_support.py`
- Modify: `tests/test_transaction_core_sweep.py`
- Modify: `CLAUDE.md` (the `agent_tools.transaction_core` sentence)

**Interfaces:**
- Consumes (Tasks 1–5): `TransactionStore.inspect_action`, `invoke_action`,
  `Transaction.actions` entries (`name`, `attempts`, `status`, `retry_eligible`),
  `InvocationRefused.reason`; fixture `SimAdapter.inspect(op, env)` /
  `invoke(op, env)` keyed by `env["action_id"]`, `World.arm_crash()`,
  `World.crash_pending`, the `throttle_once` fault.
- Produces (fixtures only, per D12, D18):
  - `tests/transaction_core_world.py`: `class ExecutorCrash(Exception)`; `World.invokes:
    dict[str, int]`; fault `"crash_before_invoke"` in `FAULTS` (comment: the executor dies
    between its recorded intent and the call). At the top of `SimAdapter.invoke`: when
    that fault is on and `crash_pending` is set, clear `crash_pending` and raise
    `ExecutorCrash(env["action_id"])`; otherwise count the call in `world.invokes` (every
    call the provider sees, throttled and unsupported ones included).
  - `tests/transaction_core_sweep_support.py`: `drive(root, shape, scenario, world=None)
    -> str` (a passed `World` is used, else a fresh one); scenarios `throttled_retry`
    (faults `{"throttle_once"}`) and `resume_after_crash` (faults
    `{"crash_before_invoke"}`), notes as in the spec's sweep section.

**Invariants:**
- One effect per binding wraps the `SimAdapter`: `inspect` returns `{"outcome":
  seen["outcome"], "reference": seen["payload_ref"]}`; `invoke` returns `{"result",
  "error_class": called.get("error_class"), "reference": called.get("correlation") or
  f"{unit.name}:{called['error_class']}"}`; both call the adapter with
  `(parameters["mode"], {"action_id": request["action_id"], "expected_subject":
  parameters["expected_subject"]})`. Action `name` is the node id; `parameters` is
  `{"mode": node["mode"], "expected_subject": node["expected_subject"]}` (per D18).
- `run_phase(nodes)`, in dependency order: `inspect_action`, then while the node's view
  is not `satisfied`: a status other than `absent` parks (and `unknown` makes the external
  state unknown, as the old `observe` did); with `attempts > 0` tick the world 30 s;
  `invoke_action`; an `InvocationRefused` parks with its reason. No adapter is called
  outside the core.
- `resume_after_crash` (per D12): after `advance("publishing")` arm the crash; the first
  `run_phase(publication)` raises `ExecutorCrash` out of `invoke_action`; tick the world
  `TTL_MS // 1000 + 1` seconds, `reap(reason="executor lost during publication")`,
  `acquire()`, `advance("publishing", "resumed after reacquisition")`; a blind
  `invoke_action` on the crashed node must raise `InvocationRefused` reason
  `inspection_required` (any other outcome parks); then `run_phase(publication)` again.
  Every other scenario runs publication once.
- Earlier rows keep their landings; every row now also asserts one attempts pair and
  the world's invoke counts.
- Expected action sets never come from recorded events alone: each cell derives the
  complete publication and activation node ids from the shape's own profile
  (`SHAPES[shape](World())`) and asserts the recorded action names equal them, so a
  skipped node fails. Each `throttled_retry` action's returns read exactly attempt 1
  `rejected`/`provider_throttled`, then attempt 2 `accepted`.

- [ ] **Step 1: Write the failing tests** — in `tests/test_transaction_core_sweep.py`,
  import `World` from `.transaction_core_world`, and replace the table and the cell test's
  head with:

```python
RESUMED = WITH_ACTIVATION[:4] + ("attention_required", "publishing") + WITH_ACTIVATION[4:]
RESUMED_LIBRARY = (WITHOUT_ACTIVATION[:4] + ("attention_required", "publishing")
                   + WITHOUT_ACTIVATION[4:])

# (shape, scenario) -> (final state, states the history passes through,
#                       temporal forms voided, (first action's attempts, others' attempts))
SWEEP = {
    **{(shape, scenario): ("succeeded", path, frozenset(), attempts)
       for shape, path in (("platform", WITH_ACTIVATION), ("product", WITH_ACTIVATION),
                           ("daemon", WITH_ACTIVATION), ("library", WITHOUT_ACTIVATION))
       for scenario, attempts in (("success", (1, 1)), ("lease_renewal", (1, 1)),
                                  ("throttled_retry", (2, 2)))},
    ("platform", "lease_lapse"): ("succeeded", LAPSED, frozenset({"snapshot"}), (1, 1)),
    ("product", "lease_lapse"): ("succeeded", LAPSED, frozenset({"snapshot"}), (1, 1)),
    ("daemon", "lease_lapse"): ("succeeded", LAPSED, frozenset({"snapshot", "interval"}),
                                (1, 1)),
    ("library", "lease_lapse"): ("succeeded", LAPSED_LIBRARY, frozenset({"snapshot"}),
                                 (1, 1)),
    **{(shape, "resume_after_crash"): (
        "succeeded", RESUMED_LIBRARY if shape == "library" else RESUMED, frozenset(), (2, 1))
       for shape in ("platform", "product", "daemon", "library")},
}
LAPSING = ("lease_lapse_detected", "lease_reacquired")
CUSTODY_EVENTS = {
    "success": ["lease_acquired", "lease_released"],
    "lease_renewal": ["lease_acquired", "lease_released"],
    "throttled_retry": ["lease_acquired", "lease_released"],
    "lease_lapse": ["lease_acquired", *LAPSING, "lease_released"],
    "resume_after_crash": ["lease_acquired", *LAPSING, "lease_released"],
}
```

  Add a module-level helper beside the table:

```python
def declared_nodes(shape):
    """Every publication and activation node id the shape's profile declares."""
    _, profile, _ = SHAPES[shape](World())
    activation = [] if profile["activation"] == "none" else profile["activation"]
    return sorted(node["id"] for node in [*profile["publication"], *activation])
```

  In `test_every_cell_lands_where_the_table_says`, unpack `(final, path, voided, (first,
  rest))`, create `world = World()`, call `drive(root, shape, scenario, world=world)`, change
  the lease-record epoch expectation to `2 if CUSTODY_EVENTS[scenario][1] ==
  "lease_lapse_detected" else 1`, and append inside the cell:

```python
                declared = [e["action_id"] for e in persisted.events
                            if e["type"] == "action_declared"]
                attempts = {e["action_id"]: e["attempt"] for e in persisted.events
                            if e["type"] == "invocation_intended"}
                self.assertEqual([attempts[a] for a in declared],
                                 [first] + [rest] * (len(declared) - 1))
                self.assertEqual(sorted(e["name"] for e in persisted.actions),
                                 declared_nodes(shape))
                self.assertEqual({e["status"] for e in persisted.actions}, {"satisfied"})
                self.assertEqual(set(world.invokes), set(declared))
                self.assertEqual(set(world.invokes.values()),
                                 {2 if scenario == "throttled_retry" else 1})
                if scenario == "throttled_retry":
                    for identity in declared:
                        self.assertEqual(
                            [(e["attempt"], e["result"], e["error_class"])
                             for e in persisted.events if e["type"] == "invocation_returned"
                             and e["action_id"] == identity],
                            [(1, "rejected", "provider_throttled"), (2, "accepted", None)])
```

  Add to `SweepTableTest`:

```python
    def test_the_crashed_action_reads_intent_inspection_then_retry(self):
        def epoch(event):
            return min(v["epoch"] for v in event["fence"].values()) if "fence" in event else None

        for shape in SHAPES:
            with self.subTest(shape=shape), tempfile.TemporaryDirectory() as tmp:
                world = World()
                transaction_id = drive(Path(tmp), shape, "resume_after_crash", world=world)
                persisted = TransactionStore(Path(tmp)).load(transaction_id)
                first = next(e["action_id"] for e in persisted.events
                             if e["type"] == "action_declared")
                trail = [(e["type"], e.get("attempt"), e.get("outcome"), epoch(e))
                         for e in persisted.events if e.get("action_id") == first]
                self.assertEqual(trail, [
                    ("action_declared", None, None, None),
                    ("action_inspected", None, "absent", 1),
                    ("invocation_intended", 1, None, 1),
                    ("action_inspected", None, "absent", 2),
                    ("invocation_intended", 2, None, 2),
                    ("invocation_returned", 2, None, 2),
                    ("action_inspected", None, "satisfied", 2)])
                self.assertEqual(world.invokes[first], 1)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core_sweep.py 2>&1 | tail -3`
Expected: FAIL — `drive()` takes no `world` and the new scenarios are missing.

- [ ] **Step 3: Implement** the fixture changes under **Produces** and **Invariants**:
  replace `run_phase`'s direct adapter calls with the core operations, add the resume
  branch around the publication phase, and rewrite the support module's docstring from
  the implemented executor (it now drives every effect through the core, retries
  automatically on the world clock, and resumes a crash through reap, reacquisition and
  inspection). In `CLAUDE.md`, extend the `agent_tools.transaction_core` sentence so it
  says slice 3 (#206) adds the administrative protocol — a durable write intent before
  every external call, inspection before any retry, and an automatic-retry budget — in
  `agent_tools.transaction_invocation`, and so it names `transaction-state/v3` instead of
  `v2`; keep "no command-table row and no caller until #125's cutover".

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core_sweep.py 2>&1 | tail -3`
Expected: `OK` — twenty cells plus the crashed-action trail for four shapes.

```bash
[ "$(grep -c 'agent_tools.transaction_invocation' CLAUDE.md)" = 1 ] || exit 1
if grep -q 'transaction-state/v2' CLAUDE.md; then exit 1; fi
```

Run: `just agent-workflow-tests 2>&1 | tail -3` — Expected: `OK`.
Run: `just build 2>&1 | tail -3` — Expected: success.

- [ ] **Step 5: Commit**

```bash
git add tests/transaction_core_world.py tests/transaction_core_sweep_support.py \
  tests/test_transaction_core_sweep.py CLAUDE.md
git commit -m "test(transaction-core): sweep throttled retries and crash resumption (#206)"
```

- [ ] **Step 6: Check the review budget** (after the commit)

```bash
base=ce33847bd60d4dc40a8a241d9f35b2bbdc9aaae1; fail=0
for f in python/agent_tools/transaction_*.py tests/test_transaction_invocation.py \
    tests/transaction_core_world.py tests/transaction_core_sweep_support.py \
    tests/test_transaction_core_sweep.py tests/test_transaction_core.py CLAUDE.md justfile; do
  n=$(git diff -U10 "$base" HEAD -- "$f" | wc -c); printf '%s %s\n' "$n" "$f"
  [ "$n" -lt 65536 ] || fail=1
done
[ "$(wc -c < python/agent_tools/transaction_core.py)" -le 55000 ] || fail=1
test "$fail" = 0
```

Expected: exit 0. A miss means the task is not done.

Decisions: per D12, D18.
