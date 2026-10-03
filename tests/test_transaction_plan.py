"""Transaction core slice 4: proof plans (#207).

Run: just agent-workflow-tests
"""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from agent_tools import transaction_storage
from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_core import (
    COHORT_MARGIN_FLOOR_MS, DEFAULT_CONVERGENCE_WINDOW_MS, MAX_COHORT_ATTEMPTS,
    MAX_COLLECTION_LATENCY_MS, MAX_CONVERGENCE_WINDOW_MS, MAX_FRESHNESS_MS,
    PLAN_REJECTION_REASONS, PLAN_SCHEMA, RUNNING_IDENTITY_FRESHNESS_MS, CreationConflict,
    ProofPlanRejected, StateInvalid, TransactionError, TransactionStore, action_id,
    compile_proof, materialize_plan)

from .test_transaction_custody import AUTHORITY
from .test_transaction_recovery_plan import EMPTY_RECOVERY, inert_recovery

TID = "rel_01890a5d-ac96-7abc-8def-0123456789ab"
EMPTY_PROOF = {"units": [], "obligations": [], "collectors": {}}
PUB, ACT = "published_artifact_identity", "running_subject_identity"


def collector(*predicates, basis="deterministic", latency=30_000, **extra):
    return {"basis": basis, "predicates": list(predicates),
            "max_collection_latency_ms": latency, **extra}


def unit(name, phase="publication", collector="c"):
    return {"name": name, "parameters": {"n": name}, "phase": phase, "collector": collector}


def obligation(identity, *, semantic="liveness", form="snapshot", predicate="health",
               collector="c", required=True, deps=(), freshness=600_000):
    entry = {"id": identity, "semantic": semantic, "form": form, "predicate": predicate,
             "collector": collector, "required": required, "deps": list(deps),
             "parameters": {"of": identity}}
    if form == "snapshot":
        entry["freshness_ms"] = freshness
    return entry


COLLECTORS = {"c": collector("publication_visible", "running_subject_identity", "health",
                             "migrated", "smoke", "ready"),
              "d": collector("health", "ready"),
              "m": collector("vibe", basis="model")}


def declaration(units=(), obligations=(), collectors=None, **extra):
    return {"units": list(units), "obligations": list(obligations),
            "collectors": copy.deepcopy(COLLECTORS if collectors is None else collectors),
            **extra}


FULL = declaration(
    [unit("build"), unit("start", phase="activation")],
    [obligation("migrated", semantic="readiness", form="event", predicate="migrated"),
     obligation("health", deps=["migrated"]),
     obligation("smoke", semantic="product_smoke", form="interval", predicate="smoke",
                deps=[f"derived:{ACT}:start"]),
     obligation("vibe", semantic="observability", predicate="vibe", collector="m",
                required=False)])


def edit(**changes):
    """A copy of FULL with top-level keys replaced."""
    return {**copy.deepcopy(FULL), **changes}


def with_obligation(index, **fields):
    changed = copy.deepcopy(FULL)
    changed["obligations"][index].update(fields)
    return changed


REJECTIONS = {
    "derived_class_named": [
        with_obligation(1, semantic=ACT), with_obligation(1, derived_class=PUB),
        with_obligation(1, obligation_kind="profile_declared"),
        with_obligation(1, id=f"derived:{ACT}:x")],
    "malformed": [
        edit(extra=1), {k: v for k, v in FULL.items() if k != "units"}, edit(units={}),
        edit(units=[{**unit("a"), "phase": "staging"}]), edit(units=[unit("a"), unit("a")]),
        edit(units=[{**unit("a"), "name": ""}]), with_obligation(1, semantic="vibes"),
        with_obligation(1, form="stream"), with_obligation(1, required="yes"),
        with_obligation(0, freshness_ms=5), with_obligation(1, parameters={"x": float("nan")}),
        edit(collectors={**COLLECTORS, "c": {**COLLECTORS["c"], "basis": "oracle"}}),
        edit(collectors={**COLLECTORS, "c": {**COLLECTORS["c"],
                                             "max_concurrent_collections": 0}}),
        edit(convergence_window_ms="30m"), "not a declaration"],
    "reserved_predicate": [with_obligation(1, predicate="publication_visible"),
                           with_obligation(1, predicate="running_subject_identity")],
    "unknown_collector": [with_obligation(1, collector="nope"),
                          edit(units=[unit("build", collector="nope"),
                                      unit("start", phase="activation")])],
    "duplicate_id": [with_obligation(1, id="migrated")],
    "unknown_dependency": [
        with_obligation(1, deps=["ghost"]), with_obligation(1, deps=[f"derived:{ACT}:build"]),
        with_obligation(1, deps=[f"derived:{PUB}:ghost"]),
        edit(units=[unit("start", phase="activation"),
                    {**unit("start", phase="activation"), "parameters": {"n": 2}}])],
    "dependency_cycle": [with_obligation(0, deps=["health"])],
    "advisory_prerequisite": [
        with_obligation(1, deps=["vibe"]),
        edit(obligations=[obligation("soft", predicate="ready", required=False),
                          obligation("mid", predicate="ready", deps=["soft"]),
                          obligation("top", deps=["mid"])])],
    "required_unsupported": [with_obligation(1, collector="m"),
                             edit(units=[unit("build", collector="d"),
                                         unit("start", phase="activation")])],
    "required_model_judgment": [
        edit(collectors={**COLLECTORS, "m": collector("health", basis="model")},
             obligations=[obligation("h", collector="m")]),
        edit(collectors={**COLLECTORS, "m": collector("publication_visible", basis="model")},
             units=[unit("build", collector="m")], obligations=[])],
    "latency_out_of_bounds": [
        edit(collectors={**COLLECTORS, "c": {**COLLECTORS["c"],
                                             "max_collection_latency_ms": 0}}),
        edit(collectors={**COLLECTORS, "c": collector(
            *COLLECTORS["c"]["predicates"], latency=MAX_COLLECTION_LATENCY_MS + 1)}),
        edit(collectors={**COLLECTORS, "c": {k: v for k, v in COLLECTORS["c"].items()
                                             if k != "max_collection_latency_ms"}}),
        with_obligation(1, freshness_ms=None), with_obligation(1, freshness_ms=0),
        with_obligation(1, freshness_ms=MAX_FRESHNESS_MS + 1),
        edit(convergence_window_ms=MAX_CONVERGENCE_WINDOW_MS + 1),
        edit(convergence_window_ms=0)],
    "infeasible_cohort": [
        declaration([], [obligation("a", collector="d"), obligation("b", collector="d")],
                    {"d": collector("health", latency=290_000)}),
        edit(convergence_window_ms=60_000)],
}
# Each spelled-out case above was checked against the root's precedence: the edited field
# is the only rule it breaks (e.g. the `unknown_dependency` duplicate unit name has
# distinct parameters, so it is not `malformed`).


class RejectionTest(unittest.TestCase):
    def test_every_case_is_refused_with_its_reason(self):
        for reason, cases in REJECTIONS.items():
            for index, case in enumerate(cases):
                with self.subTest(reason=reason, case=index):
                    frozen = copy.deepcopy(case)
                    with self.assertRaises(ProofPlanRejected) as caught:
                        compile_proof(case)
                    self.assertEqual(caught.exception.reason, reason)
                    self.assertIn(reason, str(caught.exception))
                    self.assertEqual(case, frozen)

    def test_the_rejection_reasons_are_exactly_the_exercised_ones(self):
        self.assertEqual(set(PLAN_REJECTION_REASONS), set(REJECTIONS) | {"malformed"})
        self.assertEqual(PLAN_REJECTION_REASONS[0], "malformed")

    def test_the_error_is_a_transaction_error_homed_in_storage(self):
        self.assertIs(ProofPlanRejected, transaction_storage.ProofPlanRejected)
        self.assertTrue(issubclass(ProofPlanRejected, TransactionError))

    def test_an_advisory_obligation_may_depend_on_required_proof(self):
        compiled = compile_proof(edit(obligations=[
            obligation("h"), obligation("soft", predicate="ready", required=False,
                                        deps=["h", f"derived:{PUB}:build"])]))
        self.assertEqual(compiled["obligations"][1]["deps"], ["h", f"derived:{PUB}:build"])

    def test_the_empty_declaration_and_the_full_one_compile(self):
        self.assertEqual(compile_proof(EMPTY_PROOF)["convergence_window_ms"],
                         DEFAULT_CONVERGENCE_WINDOW_MS)
        compiled = compile_proof(FULL)
        self.assertEqual(compiled["collectors"]["c"]["max_concurrent_collections"], 1)
        self.assertIsNone(compiled["obligations"][0]["freshness_ms"])


class MaterializeTest(unittest.TestCase):
    def setUp(self):
        self.plan = materialize_plan(compile_proof(FULL), TID)
        self.build = action_id(TID, "build", {"n": "build"})
        self.start = action_id(TID, "start", {"n": "start"})

    def test_the_constants(self):
        self.assertEqual((MAX_COLLECTION_LATENCY_MS, MAX_FRESHNESS_MS, MAX_COHORT_ATTEMPTS,
                          COHORT_MARGIN_FLOOR_MS, RUNNING_IDENTITY_FRESHNESS_MS,
                          DEFAULT_CONVERGENCE_WINDOW_MS, MAX_CONVERGENCE_WINDOW_MS),
                         (300_000, 7_200_000, 3, 5_000, 600_000, 1_800_000, 7_200_000))

    def test_the_plan_is_closed_and_orders_derived_obligations_first(self):
        plan = self.plan
        self.assertEqual(set(plan), {"schema", "convergence_window_ms", "units", "collectors",
                                     "obligations", "cohort"})
        self.assertEqual(plan["schema"], PLAN_SCHEMA)
        self.assertEqual([u["action_id"] for u in plan["units"]], [self.build, self.start])
        self.assertEqual([o["obligation_id"] for o in plan["obligations"]],
                         [f"derived:{PUB}:{self.build}", f"derived:{ACT}:{self.start}",
                          "migrated", "health", "smoke", "vibe"])

    def test_derived_obligations_carry_the_core_floor(self):
        publication, activation = self.plan["obligations"][:2]
        self.assertEqual(publication, {
            "obligation_id": f"derived:{PUB}:{self.build}", "obligation_kind": "core_derived",
            "semantic": None, "derived_class": PUB, "form": "event",
            "predicate": "publication_visible", "collector": "c", "required": True,
            "deps": [], "parameters": {"name": "build", "parameters": {"n": "build"}},
            "freshness_ms": None})
        self.assertEqual((activation["form"], activation["predicate"],
                          activation["freshness_ms"]),
                         ("snapshot", "running_subject_identity", 600_000))

    def test_declared_obligations_keep_their_fields_and_rewrite_derived_deps(self):
        smoke = self.plan["obligations"][4]
        self.assertEqual((smoke["obligation_kind"], smoke["semantic"], smoke["derived_class"],
                          smoke["deps"], smoke["freshness_ms"]),
                         ("profile_declared", "product_smoke", None,
                          [f"derived:{ACT}:{self.start}"], None))

    def test_declared_obligations_are_placed_after_their_deps(self):
        swapped = declaration([], [obligation("b", deps=["a"]), obligation("a")])
        plan = materialize_plan(compile_proof(swapped), TID)
        self.assertEqual([o["obligation_id"] for o in plan["obligations"]], ["a", "b"])

    def test_the_cohort_is_the_required_snapshots_serially_scheduled(self):
        self.assertEqual(self.plan["cohort"], {
            "members": [f"derived:{ACT}:{self.start}", "health"], "makespan_ms": 60_000,
            "margin_ms": 12_000, "governing_window_ms": 600_000})

    def test_the_schedule_honours_concurrency_and_prerequisites(self):
        cases = {
            "concurrent": (declaration([], [obligation("a"), obligation("b")],
                                       {"c": collector("health",
                                                       max_concurrent_collections=2)}),
                           30_000, 6_000),
            "huge concurrency": (declaration([], [obligation("a"), obligation("b")],
                                             {"c": collector("health",
                                                             max_concurrent_collections=2**63)}),
                                 30_000, 6_000),
            "chained": (declaration([], [obligation("a"), obligation("b", collector="d",
                                                                     deps=["a"])]),
                        60_000, 12_000),
            "through an event": (declaration([], [
                obligation("a"), obligation("e", form="event", deps=["a"]),
                obligation("b", collector="d", deps=["e"])]), 60_000, 12_000),
            "rounded up": (declaration([], [obligation("a")],
                                       {"c": collector("health", latency=30_001)}),
                           30_001, 6_001),
            "floor": (declaration([], [obligation("a")],
                                  {"c": collector("health", latency=1_000)}), 1_000, 5_000),
        }
        for name, (case, makespan, margin) in cases.items():
            with self.subTest(case=name):
                cohort = materialize_plan(compile_proof(case), TID)["cohort"]
                self.assertEqual((cohort["makespan_ms"], cohort["margin_ms"]),
                                 (makespan, margin))

    def test_an_empty_cohort_has_the_floor_margin_and_no_window(self):
        plan = materialize_plan(compile_proof(EMPTY_PROOF), TID)
        self.assertEqual(plan["cohort"], {"members": [], "makespan_ms": 0,
                                          "margin_ms": 5_000, "governing_window_ms": None})

    def test_materialization_is_deterministic_and_bound_to_the_transaction(self):
        compiled = compile_proof(FULL)
        self.assertEqual(materialize_plan(compiled, TID), self.plan)
        other = materialize_plan(compiled, TID[:-1] + "c")
        self.assertNotEqual(other["units"], self.plan["units"])
        self.assertEqual(compile_proof(FULL), compiled)


class CreationTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = TransactionStore(self.root)

    def create(self, proof, key="k"):
        return self.store.create(key, {"s": 1}, concurrency_keys=["key:a"], proof=proof,
                                 recovery=inert_recovery(proof), authority_class=AUTHORITY)

    def tree(self):
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))

    def files(self):
        return {p: p.read_bytes() for p in sorted(self.root.rglob("*")) if p.is_file()}

    def state(self, transaction_id):
        return self.root / transaction_id / "state.json"

    def test_the_plan_is_stored_once_with_its_digest_pinned_in_created(self):
        created = self.create(FULL)
        document = json.loads(self.state(created.transaction_id).read_text())
        self.assertEqual(document["schema"], "transaction-state/v6")
        self.assertEqual(document["proof_plan"],
                         materialize_plan(compile_proof(FULL), created.transaction_id))
        first = document["events"][0]
        self.assertEqual(set(first), {"seq", "type", "at", "proof_plan_digest",
                                      "recovery_plan_digest", "recovers", "authority_class"})
        self.assertEqual(first["proof_plan_digest"], telemetry_digest(document["proof_plan"]))
        self.assertEqual(dict(created.proof_plan), document["proof_plan"])
        self.assertEqual(TransactionStore(self.root).load(created.transaction_id), created)

    def test_proof_has_no_default(self):
        with self.assertRaises(TypeError):
            self.store.create("k", {"s": 1}, concurrency_keys=["key:a"],
                              recovery=EMPTY_RECOVERY, authority_class=AUTHORITY)
        self.assertEqual(self.tree(), [])

    def test_every_rejection_writes_nothing(self):
        for reason, cases in REJECTIONS.items():
            for index, case in enumerate(cases):
                with self.subTest(reason=reason, case=index):
                    with self.assertRaises(ProofPlanRejected) as caught:
                        self.create(case)
                    self.assertEqual(caught.exception.reason, reason)
                    self.assertIn("'k'", str(caught.exception))
                    self.assertEqual(self.tree(), [])

    def test_a_same_key_create_with_another_plan_is_a_conflict(self):
        transaction_id = self.create(FULL).transaction_id
        self.assertEqual(self.create(copy.deepcopy(FULL)).transaction_id, transaction_id)
        before = self.files()
        for other in (EMPTY_PROOF, edit(convergence_window_ms=1_700_000)):
            with self.subTest(other=other), self.assertRaises(CreationConflict) as caught:
                self.create(other)
            self.assertIn("proof plan", str(caught.exception))
            self.assertEqual(self.files(), before)

    def test_hand_edited_plans_and_digests_are_state_invalid(self):
        transaction_id = self.create(FULL).transaction_id
        pristine = json.loads(self.state(transaction_id).read_text())

        def redigest(document):
            document["events"][0]["proof_plan_digest"] = telemetry_digest(
                document["proof_plan"])

        def cohort(document):
            document["proof_plan"]["cohort"]["makespan_ms"] = 1
            redigest(document)

        def unit_parameters(document):
            document["proof_plan"]["units"][0]["parameters"] = {"n": "other"}
            redigest(document)

        def extra_key(document):
            document["proof_plan"]["extra"] = 1
            redigest(document)

        def dropped_floor(document):
            del document["proof_plan"]["obligations"][0]
            redigest(document)

        def digest(document):
            document["events"][0]["proof_plan_digest"] = "sha256:" + "0" * 64

        def missing(document):
            del document["proof_plan"]

        def version(document):
            document["schema"] = "transaction-state/v3"

        materialization = "proof_plan is not the materialization of its own declaration"
        for name, change, rule in (
                ("cohort", cohort, materialization),
                ("unit parameters", unit_parameters, materialization),
                ("extra key", extra_key, materialization),
                ("dropped floor", dropped_floor, materialization),
                ("digest", digest, "proof_plan_digest is not the digest of proof_plan"),
                ("missing", missing, "closed transaction-state/v6 key set"),
                ("v3", version, "transaction-state/v3")):
            with self.subTest(edit=name):
                document = copy.deepcopy(pristine)
                change(document)
                self.state(transaction_id).write_text(json.dumps(
                    document, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                    allow_nan=False) + "\n")
                with self.assertRaises(StateInvalid) as caught:
                    TransactionStore(self.root).load(transaction_id)
                self.assertIn(transaction_id, str(caught.exception))
                self.assertIn(rule, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
