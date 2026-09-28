# Task 1: Recovery declaration — compile, bind and materialize

**Files:**
- Create: `python/agent_tools/transaction_recovery_plan.py`
- Modify: `python/agent_tools/transaction_storage.py` (`RecoveryPlanRejected`)
- Modify: `python/agent_tools/transaction_core.py` (re-exports only)
- Create: `tests/test_transaction_recovery_plan.py`
- Modify: `tests/test_transaction_core_sweep.py` (`NEUTRAL_MODULES`)
- Modify: `justfile` (add the new test file after `tests/test_transaction_proof.py`)

**Interfaces:**
- Consumes: `transaction_invocation.action_id`, `action_violation`;
  `transaction_storage.json_object_violation`, `serialize`, `TransactionError`;
  `transaction_plan.compile_proof`, `declaration_of`; `agent_tools.canonical.telemetry_digest`.
- Produces (`agent_tools.transaction_recovery_plan`, all re-exported by `transaction_core`
  except `recovery_rejected`, `recovery_declaration_of` and `recovery_plan_violation`):
  - `RECOVERY_PLAN_SCHEMA = "transaction-recovery-plan/v1"`, `POSTURES`, `EDGE_ACTIONS`,
    `RECOVERY_REJECTION_REASONS = ("malformed", "posture_violation", "unknown_effect",
    "unsupported_operation", "unit_mismatch", "unsupported_check")`.
  - `recovery_rejected(where: str, reason: str, detail: str) -> RecoveryPlanRejected`,
    whose message is `f"{where}: recovery plan rejected: {reason}: {detail}"`; an unknown
    reason raises `ValueError`.
  - `compile_recovery(declaration: Any, *, where: str = "recovery") -> dict` returns a
    deep copy with the same shape and never mutates its input.
  - `bind_recovery(compiled: dict, compiled_proof: dict, *, where: str = "recovery") -> dict`
    returns `{"effects", "units"}` with the units in the proof declaration's unit order.
  - `materialize_recovery(bound: dict, transaction_id: str) -> dict`.
  - `recovery_declaration_of(plan: Any) -> dict | None` never raises.
  - `recovery_plan_violation(plan: Any, proof_plan: Any, transaction_id: str) -> str | None`.
- Produces (`agent_tools.transaction_storage`): `class RecoveryPlanRejected(TransactionError)`
  with `__init__(self, message, *, reason)` and a `.reason` attribute, shaped like
  `ProofPlanRejected`.

**Invariants:**
- The declaration is exactly `{"effects", "units"}` (per the spec's schema table). `effects`
  maps a non-empty handle to exactly `{"operations": [...]}`, a list of distinct non-empty
  strings. A unit has exactly `name, parameters, effect, operation, posture, anchor,
  compatibility, edges`. `anchor` and `compatibility` are each null or exactly
  `{predicate: non-empty str, parameters: JSON object}`. An edge has exactly `action,
  operation, parameters, residue`.
- Rule order, first failure wins. Each rule runs over every unit, in declaration order,
  before the next rule starts (per D5, D21):
  1. `malformed`: any shape or type violation, an unknown posture or edge action, a residue
     that does not match its action (a `restore` edge needs null, a `compensate` edge a
     non-empty string), and two identities that coincide. The identities are each unit's
     `(name, telemetry_digest(parameters))` and each edge's `(operation,
     telemetry_digest(parameters))`, all in one set.
  2. `posture_violation`: the posture table (per D3, D4). `restorable` needs a non-null
     anchor and compatibility, and its edges must be one `restore` first, then zero or more
     `compensate`. `compensatable` needs both null and one or more edges, all `compensate`.
     `supersedable_only` and `manual_only` need both null and no edges.
  3. `unknown_effect`: a unit's `effect` is not a declared handle.
  4. `unsupported_operation`: a unit's `operation`, then each of its edges' operations, is not
     in its effect's `operations`. The detail is exactly
     `f"unit {name!r} operation {operation!r} is not offered by effect {handle!r}"`.
- `bind_recovery` refuses `unit_mismatch` when the recovery units' identity multiset differs
  from the proof units'. It refuses `unsupported_check` when a non-null anchor or
  compatibility predicate is not in `compiled_proof["collectors"][<the proof unit's
  collector>]["predicates"]`.
- `materialize_recovery` returns exactly `{"schema", "effects", "units"}`. Each unit is its
  declared fields plus `action_id = action_id(transaction_id, name, parameters)`. Each edge
  is its declared fields plus `action_id = action_id(transaction_id, operation,
  parameters)` (per D6).
- `recovery_plan_violation` is None exactly when `serialize(plan)` equals the serialization
  of `materialize_recovery(bind_recovery(compile_recovery(recovery_declaration_of(plan)),
  compile_proof(declaration_of(proof_plan))), transaction_id)`. Otherwise it returns a rule
  string that starts with `recovery_plan`, including when a rejection or `TypeError`
  occurs. It is the validator's single rule home (per D6).
- The module is pure: no file, lock or clock.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_transaction_recovery_plan.py`
  (Tasks 2, 3 and 6 import its constants):

```python
"""Transaction core slice 5: the recovery declaration and its plan (#208).

Run: just agent-workflow-tests
"""

import copy
import unittest

from agent_tools import transaction_core, transaction_recovery_plan
from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_core import (
    EDGE_ACTIONS, POSTURES, RECOVERY_PLAN_SCHEMA, RECOVERY_REJECTION_REASONS,
    RecoveryPlanRejected, TransactionError, action_id, bind_recovery, compile_proof,
    compile_recovery, materialize_recovery)

TID = "rel_01890a5d-ac96-7abc-8def-0123456789ab"
C = {"basis": "deterministic", "max_collection_latency_ms": 30_000,
     "predicates": ["publication_visible", "running_subject_identity", "rollback_anchor",
                    "compatibility"]}
UNITS = [{"name": "build", "parameters": {"n": 1}, "phase": "publication", "collector": "c"},
         {"name": "start", "parameters": {"n": 2}, "phase": "activation", "collector": "c"},
         {"name": "pin", "parameters": {"n": 3}, "phase": "activation", "collector": "c"}]
PROOF = {"units": UNITS, "obligations": [], "collectors": {"c": C}}
EMPTY_PROOF = {"units": [], "obligations": [], "collectors": {}}
EMPTY_RECOVERY = {"effects": {}, "units": []}
ANCHOR = {"predicate": "rollback_anchor", "parameters": {"prior": "gen-1"}}
COMPATIBLE = {"predicate": "compatibility", "parameters": {"prior": "gen-1"}}


def edge(action, unit, residue=None):
    return {"action": action, "operation": action, "parameters": {"unit": unit},
            "residue": residue}


def runit(name, n, posture, operation="make", edges=(), anchor=None, compatibility=None):
    return {"name": name, "parameters": {"n": n}, "effect": "e", "operation": operation,
            "posture": posture, "anchor": anchor, "compatibility": compatibility,
            "edges": list(edges)}


RECOVERY = {"effects": {"e": {"operations": ["make", "apply", "restore", "compensate"]}},
            "units": [
                runit("build", 1, "compensatable",
                      edges=[edge("compensate", "build", "old build stays cached")]),
                runit("start", 2, "restorable", "apply",
                      [edge("restore", "start"), edge("compensate", "start", "cache cleared")],
                      ANCHOR, COMPATIBLE),
                runit("pin", 3, "manual_only", "apply")]}


def with_unit(index, **fields):
    declaration = copy.deepcopy(RECOVERY)
    declaration["units"][index].update(fields)
    return declaration


REJECTIONS = {
    "malformed": [
        ["not", "an", "object"], {**RECOVERY, "extra": 1},
        {"effects": {"e": {"operations": ["make", "make"]}}, "units": []},
        with_unit(0, posture="irreversible"),
        with_unit(0, edges=[{**edge("compensate", "build", "r"), "action": "undo"}]),
        with_unit(0, edges=[edge("compensate", "build")]),
        with_unit(1, edges=[edge("restore", "start", "r")]),
        with_unit(0, edges=[edge("compensate", "build", "r"), edge("compensate", "build", "s")]),
        with_unit(1, anchor={"predicate": "rollback_anchor"}),
    ],
    "posture_violation": [
        with_unit(0, edges=[edge("restore", "build")]),
        with_unit(2, edges=[edge("restore", "pin")]),
        with_unit(1, anchor=None),
        with_unit(1, edges=[edge("compensate", "start", "r"), edge("restore", "start")]),
        with_unit(0, edges=[]),
        with_unit(2, anchor=ANCHOR),
    ],
    "unknown_effect": [with_unit(0, effect="elsewhere")],
    "unsupported_operation": [
        with_unit(0, operation="promote"),
        with_unit(0, edges=[{**edge("compensate", "build", "r"), "operation": "erase"}])],
}


def bound(declaration=RECOVERY, proof=PROOF):
    return bind_recovery(compile_recovery(declaration), compile_proof(proof))


class CompileTest(unittest.TestCase):
    def test_every_rejection_names_its_reason_and_leaves_the_input_alone(self):
        for reason, declarations in REJECTIONS.items():
            for declaration in declarations:
                with self.subTest(reason=reason, declaration=declaration):
                    before = copy.deepcopy(declaration)
                    with self.assertRaises(RecoveryPlanRejected) as caught:
                        compile_recovery(declaration, where="probe")
                    self.assertEqual(caught.exception.reason, reason)
                    self.assertIn(f"probe: recovery plan rejected: {reason}: ",
                                  str(caught.exception))
                    self.assertEqual(declaration, before)

    def test_each_rule_runs_over_every_unit_before_the_next(self):
        declaration = with_unit(1, operation="promote")
        declaration["units"][2]["effect"] = "elsewhere"
        with self.assertRaises(RecoveryPlanRejected) as caught:
            compile_recovery(declaration)
        self.assertEqual(caught.exception.reason, "unknown_effect")

    def test_an_unsupported_operation_names_the_unit_the_operation_and_the_effect(self):
        with self.assertRaises(RecoveryPlanRejected) as caught:
            compile_recovery(with_unit(0, operation="promote"))
        self.assertIn("unit 'build' operation 'promote' is not offered by effect 'e'",
                      str(caught.exception))

    def test_a_valid_declaration_compiles_to_an_equal_copy(self):
        compiled = compile_recovery(RECOVERY)
        self.assertEqual(compiled, RECOVERY)
        compiled["units"][0]["edges"].clear()
        self.assertEqual(len(RECOVERY["units"][0]["edges"]), 1)


class BindTest(unittest.TestCase):
    def test_bind_refuses_a_unit_set_that_differs_or_an_unlisted_check(self):
        for reason, declaration in (
                ("unit_mismatch", {**RECOVERY, "units": RECOVERY["units"][:2]}),
                ("unit_mismatch", with_unit(2, parameters={"n": 9})),
                ("unsupported_check", with_unit(1, anchor={"predicate": "vibe",
                                                           "parameters": {}}))):
            with self.subTest(reason=reason, declaration=declaration):
                with self.assertRaises(RecoveryPlanRejected) as caught:
                    bind_recovery(compile_recovery(declaration), compile_proof(PROOF),
                                  where="probe")
                self.assertEqual(caught.exception.reason, reason)

    def test_the_empty_declaration_binds_to_the_empty_proof(self):
        self.assertEqual(materialize_recovery(bound(EMPTY_RECOVERY, EMPTY_PROOF), TID),
                         {"schema": RECOVERY_PLAN_SCHEMA, "effects": {}, "units": []})


class MaterializeTest(unittest.TestCase):
    def test_the_plan_follows_the_proof_unit_order_and_carries_action_ids(self):
        declaration = copy.deepcopy(RECOVERY)
        declaration["units"].reverse()
        plan = materialize_recovery(bound(declaration), TID)
        self.assertEqual(set(plan), {"schema", "effects", "units"})
        self.assertEqual(plan["schema"], "transaction-recovery-plan/v1")
        self.assertEqual([unit["name"] for unit in plan["units"]], ["build", "start", "pin"])
        start = plan["units"][1]
        self.assertEqual(start["action_id"], action_id(TID, "start", {"n": 2}))
        self.assertEqual([(e["action"], e["action_id"]) for e in start["edges"]],
                         [("restore", action_id(TID, "restore", {"unit": "start"})),
                          ("compensate", action_id(TID, "compensate", {"unit": "start"}))])
        self.assertEqual({k: v for k, v in start.items() if k not in ("action_id", "edges")},
                         {k: v for k, v in RECOVERY["units"][1].items() if k != "edges"})

    def test_materialization_is_deterministic_and_leaves_its_inputs_alone(self):
        compiled, proof = compile_recovery(RECOVERY), compile_proof(PROOF)
        before = copy.deepcopy((compiled, proof))
        first = materialize_recovery(bind_recovery(compiled, proof), TID)
        second = materialize_recovery(bind_recovery(compiled, proof), TID)
        self.assertEqual(telemetry_digest(first), telemetry_digest(second))
        self.assertEqual((compiled, proof), before)


class VocabularyTest(unittest.TestCase):
    def test_the_core_re_exports_the_plan_names(self):
        for name in ("RECOVERY_PLAN_SCHEMA", "RECOVERY_REJECTION_REASONS", "POSTURES",
                     "EDGE_ACTIONS", "compile_recovery", "bind_recovery",
                     "materialize_recovery"):
            with self.subTest(name=name):
                self.assertIs(getattr(transaction_core, name),
                              getattr(transaction_recovery_plan, name))
        self.assertEqual(RECOVERY_REJECTION_REASONS, (
            "malformed", "posture_violation", "unknown_effect", "unsupported_operation",
            "unit_mismatch", "unsupported_check"))
        self.assertEqual(POSTURES, ("restorable", "compensatable", "supersedable_only",
                                    "manual_only"))
        self.assertEqual(EDGE_ACTIONS, ("restore", "compensate"))
        self.assertTrue(issubclass(RecoveryPlanRejected, TransactionError))


if __name__ == "__main__":
    unittest.main()
```

  In `tests/test_transaction_core_sweep.py`, import `transaction_recovery_plan` beside the
  other modules and add it to `NEUTRAL_MODULES`.

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_recovery_plan.py 2>&1 | tail -3`.
  Expected: an `ImportError` naming `EDGE_ACTIONS` (or another new name).

- [ ] **Step 3: Implement** the invariants. Mirror `transaction_plan`'s structure: a
  `_shape_violation` for rule 1 and one pass per later rule, with `recovery_rejected` as the
  only raise site. Write the module docstring from the resulting code, naming its rules,
  their order and its purity. Add `RecoveryPlanRejected` to `transaction_storage` beside
  `ProofPlanRejected`. Add the re-exports and `RecoveryPlanRejected` to `transaction_core`'s
  imports without changing any behaviour. Add the test file to the `justfile` list.

- [ ] **Step 4: Verify.**
  Run: `PYTHONPATH=python python3 -m unittest $SLICE tests/test_transaction_recovery_plan.py 2>&1 | tail -3`.
  Expected: `OK`.

```bash
grep -q "tests/test_transaction_recovery_plan.py" justfile || exit 1
test -f python/agent_tools/transaction_recovery_plan.py || exit 1
if grep -nE "import.*transaction_(core|history|recovery)\b" python/agent_tools/transaction_recovery_plan.py; then exit 1; fi
```

  Run: `git add -A python tests justfile && just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.** Stage exactly this task's **Files**, then:

```bash
git commit -m "feat(transaction-core): compile and materialize recovery declarations (#208)"
```

- [ ] **Step 6: Check the review budget** with `FILES="python/agent_tools/transaction_recovery_plan.py python/agent_tools/transaction_storage.py python/agent_tools/transaction_core.py tests/test_transaction_recovery_plan.py"`.
  Expected: exit 0.

Decisions: per D1, D2, D3, D4, D5, D6, D21.
