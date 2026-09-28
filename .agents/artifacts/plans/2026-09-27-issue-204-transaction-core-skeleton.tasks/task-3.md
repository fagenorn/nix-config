# Task 3: Ported fixtures, fixture executor and the asserted `success` sweep row

**Files:**
- Create: `tests/transaction_core_world.py` (port of `prototype-release-transactions/world.py`)
- Create: `tests/transaction_core_shapes.py` (port of `prototype-release-transactions/profiles.py`)
- Create: `tests/transaction_core_sweep_support.py` (scenario fixture + fixture executor)
- Create: `tests/test_transaction_core_sweep.py`
- Modify: `justfile` (recipe `agent-workflow-tests`)

**Interfaces:**
- Consumes: `agent_tools.transaction_core.TransactionStore` with
  `create(creation_key: str, subject: dict) -> Transaction`,
  `load(transaction_id: str) -> Transaction`,
  `advance(transaction_id: str, target: str, *, reason: str, external_state: str | None = None) -> Transaction`;
  `Transaction.transaction_id`, `.creation_key`, `.state`, `.events` (event mappings with
  `seq`, `type`, `to`, `external_state`).
- Produces:
  - `tests/transaction_core_world.py`: `World`, `SimAdapter` and the `hook_*` factories,
    behavior identical to the prototype at `dc98ba9`.
  - `tests/transaction_core_shapes.py`: `SHAPES: dict[str, Callable[[World], tuple[dict, dict, dict]]]`
    with keys `platform`, `product`, `daemon`, `library`, each returning
    `(subject, profile, registry)` exactly as the prototype authors them.
  - `tests/transaction_core_sweep_support.py`: `SCENARIOS: dict[str, dict]` (only
    `"success"`) and `drive(store: TransactionStore, shape: str, scenario: str) -> str`
    returning the transaction id.
  - `tests/test_transaction_core_sweep.py`: `SWEEP` table and `SweepTableTest`; Task 4
    appends a neutrality class to this file.

**Invariants:**
- Nothing under `tests/transaction_core_*.py` is imported by, or copied into,
  `python/` (D6, D14).
- The executor touches the core only through the three public store methods (seam 2).
- `SWEEP`'s key set equals `{(shape, scenario) for shape in SHAPES for scenario in
  SCENARIOS}` — no scenario is ported unasserted (D6).
- Each cell is asserted against a fresh `TransactionStore(root).load(...)`, never the
  executor's in-memory result.

- [ ] **Step 1: Port the two prototype fixtures verbatim**

```bash
git show dc98ba9:prototype-release-transactions/world.py > tests/transaction_core_world.py
git show dc98ba9:prototype-release-transactions/profiles.py > tests/transaction_core_shapes.py
```

Then make exactly these edits and no others:
- In both files, add as the docstring's second paragraph:
  `Test fixture ported from prototype-release-transactions/<world|profiles>.py at dc98ba9 (#204 D6). It stays under tests/: provider names belong in fixtures, never in the core.`
- In `tests/transaction_core_shapes.py`, change `from world import (` to
  `from .transaction_core_world import (` (the import list stays the same).

Gate: `git show dc98ba9:prototype-release-transactions/world.py | diff - tests/transaction_core_world.py`
shows only the added docstring lines; the same for profiles shows only those lines and
the import line.

- [ ] **Step 2: Write the failing sweep test** — create
`tests/test_transaction_core_sweep.py`:

```python
"""Asserted sweep of the transaction core across four unlike project shapes (#204 D6, D17).

The prototype's autopilot printed where each (shape, scenario) cell landed; this table
asserts it against persisted history. Only the success row exists in this slice.

Run: just agent-workflow-tests
"""

import tempfile
import unittest
from pathlib import Path

from agent_tools.transaction_core import TransactionStore

from .transaction_core_shapes import SHAPES
from .transaction_core_sweep_support import SCENARIOS, drive

WITH_ACTIVATION = ("created", "awaiting_verification", "ready", "publishing", "published",
                   "activating", "proving", "succeeded")
WITHOUT_ACTIVATION = tuple(s for s in WITH_ACTIVATION if s != "activating")

# (shape, scenario) -> (final state, every state the persisted history passes through)
SWEEP = {
    ("platform", "success"): ("succeeded", WITH_ACTIVATION),
    ("product", "success"): ("succeeded", WITH_ACTIVATION),
    ("daemon", "success"): ("succeeded", WITH_ACTIVATION),
    ("library", "success"): ("succeeded", WITHOUT_ACTIVATION),
}


def states_passed(transaction):
    return ("created",) + tuple(event["to"] for event in transaction.events[1:])


class SweepTableTest(unittest.TestCase):
    def test_the_table_covers_every_shape_for_every_ported_scenario(self):
        self.assertEqual(set(SWEEP), {(shape, scenario) for shape in SHAPES
                                      for scenario in SCENARIOS})

    def test_every_cell_lands_where_the_table_says(self):
        for (shape, scenario), (final, path) in SWEEP.items():
            with self.subTest(shape=shape, scenario=scenario), \
                    tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                transaction_id = drive(TransactionStore(root), shape, scenario)
                persisted = TransactionStore(root).load(transaction_id)
                self.assertEqual(persisted.creation_key, f"{shape}:{scenario}")
                self.assertEqual(persisted.state, final)
                self.assertEqual(states_passed(persisted), path)
                self.assertEqual({e["external_state"] for e in persisted.events[1:]},
                                 {"known"})

    def test_recreating_a_driven_cell_returns_its_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TransactionStore(Path(tmp))
            first = drive(store, "library", "success")
            subject = dict(store.load(first).subject)
            again = store.create("library:success", subject)
            self.assertEqual(again.transaction_id, first)
            self.assertEqual(len(again.events), len(store.load(first).events))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run it and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_core_sweep.py 2>&1 | tail -3`
Expected: FAIL — `ModuleNotFoundError: No module named 'tests.transaction_core_sweep_support'`.

- [ ] **Step 4: Write the scenario fixture and executor** — create
`tests/transaction_core_sweep_support.py`. The walk embodies D17, so its code is given
whole:

```python
"""Scenario fixture and fixture executor for the transaction core sweep (#204 D6, D17).

The executor is a happy-path walker over the simulated world that asks the shipped core
to advance at each lifecycle boundary through the public store API. It deliberately
carries none of the prototype's lease, retry, authorization or recovery logic; later
slices move that into the core and this walker shrinks. Any observation other than
satisfied parks the transaction in attention_required with the observation as reason.
"""

from .transaction_core_shapes import SHAPES
from .transaction_core_world import World

# Ported from prototype-release-transactions/scenarios.py at dc98ba9: only the scenarios
# whose sweep rows this slice asserts.
SCENARIOS = {
    "success": {"faults": frozenset(),
                "note": "clean path: publish, activate, prove, seal a terminal receipt."},
}


class _Parked(Exception):
    pass


def _in_dependency_order(nodes):
    """Stable topological order: repeatedly take the first node whose deps are done."""
    done, ordered, pending = set(), [], list(nodes)
    while pending:
        for node in pending:
            if all(dep in done for dep in node.get("deps", [])):
                ordered.append(node)
                done.add(node["id"])
                pending.remove(node)
                break
        else:
            raise ValueError(f"dependency cycle among {[n['id'] for n in pending]}")
    return ordered


def drive(store, shape, scenario):
    world = World()
    world.faults = set(SCENARIOS[scenario]["faults"])
    subject, profile, registry = SHAPES[shape](world)
    transaction_id = store.create(f"{shape}:{scenario}", subject).transaction_id
    definite = {"all": True}

    def adapter(alias):
        return registry[profile["bindings"][alias]["adapter"]]

    def external_state():
        return "known" if definite["all"] else "unknown"

    def advance(target, reason):
        store.advance(transaction_id, target, reason=reason, external_state=external_state())

    def observe(result, what):
        if result["outcome"] == "unknown":
            definite["all"] = False
        if result["outcome"] != "satisfied":
            raise _Parked(f"{what}: {result['outcome']} ({result['reason']})")

    def run_phase(nodes):
        for node in _in_dependency_order(nodes):
            env = {"action_id": node["id"], "expected_subject": node["expected_subject"]}
            unit = adapter(node["binding"])
            before = unit.inspect(node["mode"], env)
            if before["outcome"] == "satisfied":
                continue
            if before["outcome"] != "absent":
                observe(before, f"{node['id']} pre-inspect")
            invoked = unit.invoke(node["mode"], env)
            if invoked["result"] != "accepted":
                raise _Parked(f"{node['id']} invoke {invoked['result']}: "
                              f"{invoked.get('error_class')}")
            observe(unit.inspect(node["mode"], env), f"{node['id']} post-inspect")

    try:
        advance("awaiting_verification", "candidate verification requested")
        check = profile["target"]["verification"]
        observe(adapter(check["binding"]).inspect(check["predicate"],
                                                  {"expected_subject": subject}),
                "candidate verification")
        advance("ready", "candidate verification satisfied")
        advance("publishing", "publication started")
        run_phase(profile["publication"])
        advance("published", "every publication unit satisfied")
        activation = [] if profile["activation"] == "none" else profile["activation"]
        if activation:
            advance("activating", "activation started")
            run_phase(activation)
            advance("proving", "every activation unit satisfied")
        else:
            advance("proving", "profile declares activation none")
        obligations = (
            [("floor:publication:" + n["id"], "publication_visible", n, [])
             for n in profile["publication"]]
            + [("floor:activation:" + n["id"], "running_subject_identity", n, [])
               for n in activation]
            + [(o["id"], o["predicate"], o, o.get("deps", []))
               for o in profile["proof"] if o["required"]])
        accepted = set()
        for obligation_id, predicate, source, deps in obligations:
            unmet = [dep for dep in deps if dep not in accepted]
            if unmet:
                raise _Parked(f"{obligation_id}: prerequisite not accepted {unmet}")
            observe(adapter(source["binding"]).inspect(
                predicate, {"expected_subject": source["expected_subject"]}), obligation_id)
            accepted.add(obligation_id)
        advance("succeeded", "every required obligation satisfied")
    except _Parked as parked:
        advance("attention_required", str(parked))
    return transaction_id
```

Then add `    tests/test_transaction_core_sweep.py \` to the `justfile` recipe
`agent-workflow-tests`, directly after `    tests/test_transaction_core.py \`.

- [ ] **Step 5: Verify**

Run: `PYTHONPATH=python python3 -m unittest -v tests/test_transaction_core_sweep.py 2>&1 | tail -4`
Expected: `OK` (3 tests).

Falsifiability check (do not commit): temporarily change `SWEEP[("library",
"success")]` to `WITH_ACTIVATION`, rerun, and confirm it FAILS on the `library` subtest;
restore it.

Run: `grep -c 'tests/test_transaction_core_sweep.py' justfile` — Expected: `1`.

Run: `if grep -rqE 'transaction_core_(world|shapes|sweep_support)' python/; then exit 1; fi` — Expected: exit 0.

Run: `just agent-workflow-tests 2>&1 | tail -3` — Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add tests/transaction_core_world.py tests/transaction_core_shapes.py \
  tests/transaction_core_sweep_support.py tests/test_transaction_core_sweep.py justfile
git commit -m "test(transaction-core): assert the success sweep row across four shapes (#204)"
```
