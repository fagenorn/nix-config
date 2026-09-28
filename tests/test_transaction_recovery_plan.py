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
