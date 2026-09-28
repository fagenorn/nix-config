"""Transaction core slice 5: the recovery declaration and its plan (#208).

Run: just agent-workflow-tests
"""

import copy
import unittest

from agent_tools import transaction_core, transaction_recovery_plan
from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_core import (
    EDGE_ACTIONS, POSTURES, RECOVERY_PLAN_SCHEMA, RECOVERY_REJECTION_REASONS, CreationConflict,
    ProofPlanRejected, RecoveryPlanRejected, TransactionError, action_id, bind_recovery,
    compile_proof, compile_recovery, materialize_recovery)

from .test_transaction_custody import KEYS, SUBJECT, CustodyCase

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


def inert_recovery(proof):
    """Every unit of a compilable `proof` as a `manual_only` recovery unit, with no anchor
    and no edge; empty when `proof` is itself rejected, so its own rejection still wins."""
    try:
        compile_proof(proof)
    except ProofPlanRejected:
        return EMPTY_RECOVERY
    return {"effects": {"inert": {"operations": ["make"]}},
            "units": [{"name": unit["name"], "parameters": unit["parameters"],
                       "effect": "inert", "operation": "make", "posture": "manual_only",
                       "anchor": None, "compatibility": None, "edges": []}
                      for unit in proof["units"]]}


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


class CreationTest(CustodyCase):
    def create(self, key="k", recovery=RECOVERY, proof=PROOF):
        return self.store.create(key, SUBJECT, concurrency_keys=KEYS, proof=proof,
                                 recovery=recovery)

    def test_the_plan_is_stored_and_pinned_on_the_created_event(self):
        created = self.create()
        document = self.state_doc(created.transaction_id)
        self.assertEqual(document["schema"], "transaction-state/v5")
        plan = document["recovery_plan"]
        self.assertEqual(plan, materialize_recovery(bound(), created.transaction_id))
        first = document["events"][0]
        self.assertEqual((first["recovery_plan_digest"], first["recovers"]),
                         (telemetry_digest(plan), None))
        self.assertEqual(dict(created.recovery), {
            "plan_digest": telemetry_digest(plan), "recovers": None,
            "effect_snapshot": None, "selected": [], "children": []})
        self.assertEqual(created.recovery_plan["units"][0]["name"], "build")
        with self.assertRaises(TypeError):
            created.recovery_plan["schema"] = "x"

    def test_recovery_is_required(self):
        with self.assertRaises(TypeError):
            self.store.create("k", SUBJECT, concurrency_keys=KEYS, proof=PROOF)

    def test_a_rejected_declaration_leaves_the_root_untouched(self):
        for declaration in (with_unit(0, operation="promote"),
                            {**RECOVERY, "units": RECOVERY["units"][:2]}):
            with self.subTest(declaration=declaration):
                self.assertRefusedUnchanged(RecoveryPlanRejected,
                                            lambda: self.create(recovery=declaration))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_recovery_compiles_before_proof(self):
        with self.assertRaises(RecoveryPlanRejected):
            self.create(recovery=with_unit(0, operation="promote"), proof={"units": "bad"})

    def test_a_same_key_create_with_another_recovery_declaration_conflicts(self):
        created = self.create()
        before = self.files()
        other = with_unit(0, edges=[edge("compensate", "build", "a different residue")])
        with self.assertRaises(CreationConflict) as caught:
            self.create(recovery=other)
        self.assertIn("recovery plan", str(caught.exception))
        self.assertEqual(self.files(), before)
        self.assertEqual(self.create().transaction_id, created.transaction_id)

    def test_a_hand_edited_plan_digest_or_backlink_is_state_invalid(self):
        transaction_id = self.create().transaction_id
        document = self.state_doc(transaction_id)

        def reidentified(d):
            d["recovery_plan"]["units"][0]["action_id"] = "act_" + "0" * 32
            d["events"][0]["recovery_plan_digest"] = telemetry_digest(d["recovery_plan"])

        cases = (
            (reidentified, "recovery_plan is not the materialization of its own declaration"),
            (lambda d: d["recovery_plan"]["units"][0]["edges"][0].update(residue="none"),
             "recovery_plan_digest"),
            (lambda d: d["events"][0].update(recovery_plan_digest="sha256:" + "0" * 64),
             "recovery_plan_digest"),
            (lambda d: d["events"][0].update(recovers=transaction_id), "recovers"),
            (lambda d: d["events"][0].update(recovers="not-an-id"), "recovers"),
            (lambda d: d.update(schema="transaction-state/v4"), "transaction-state/v4"))
        for edit, fragment in cases:
            with self.subTest(fragment=fragment):
                edited = copy.deepcopy(document)
                edit(edited)
                self.assertRuleRefuses(transaction_id, edited, fragment)


if __name__ == "__main__":
    unittest.main()
