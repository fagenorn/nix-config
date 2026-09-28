# Task 1: Plan vocabulary, compile, materialize and the cohort schedule

**Files:**
- Create: `python/agent_tools/transaction_plan.py`
- Modify: `python/agent_tools/transaction_storage.py` (one error class)
- Modify: `python/agent_tools/transaction_core.py` (re-exports and one docstring sentence only)
- Create: `tests/test_transaction_plan.py`
- Modify: `tests/test_transaction_core_sweep.py` (`NEUTRAL_MODULES`)
- Modify: `justfile` (`agent-workflow-tests` list)

**Interfaces:**
- Consumes (base `dd9f40b`): `transaction_invocation.action_id(transaction_id, name,
  parameters) -> "act_<32 hex>"`, `transaction_invocation.action_violation(name, parameters)
  -> str | None`, `transaction_custody.EVIDENCE_FORMS = ("event", "snapshot", "interval")`,
  `transaction_storage.json_object_violation(value) -> str | None`, `serialize(document) ->
  str`, `TransactionError`, `agent_tools.canonical.telemetry_digest(body) -> "sha256:<hex>"`.
- Produces (`agent_tools.transaction_storage`):
  `class ProofPlanRejected(TransactionError)` with `__init__(self, message: str, *, reason:
  str)` storing `self.reason`. Its docstring: `"""A proof declaration the core refuses to
  compile; `reason` is one of the closed plan rejection reasons, and it is raised before any
  lock or write (#207 D18)."""`.
- Produces (`agent_tools.transaction_plan`; later tasks import these exact names):
  - `PLAN_SCHEMA = "transaction-proof-plan/v1"`;
    `SEMANTICS = ("liveness", "readiness", "product_smoke", "observability",
    "rollback_readiness")`; `PHASES = ("publication", "activation")`;
    `BASES = ("deterministic", "model")`;
    `DERIVED_CLASSES = ("published_artifact_identity", "running_subject_identity")`;
    `PHASE_CLASS = {"publication": "published_artifact_identity", "activation":
    "running_subject_identity"}`;
    `RESERVED_PREDICATES = {"published_artifact_identity": "publication_visible",
    "running_subject_identity": "running_subject_identity"}`;
    `DERIVED_FORMS = {"published_artifact_identity": "event", "running_subject_identity":
    "snapshot"}`;
    `DERIVED_REASONS = {"published_artifact_identity": ("ref_absent", "ref_not_immutable",
    "digest_mismatch", "subject_mismatch", "store_unreachable"), "running_subject_identity":
    ("subject_absent", "subject_mismatch", "unrelated_subject_running", "attempt_mismatch",
    "identity_unobservable")}`. The four mappings are `MappingProxyType`.
  - The nine D19 constants, exactly as named in the root's Global Constraints.
  - `PLAN_REJECTION_REASONS = ("malformed", "derived_class_named", "reserved_predicate",
    "unknown_collector", "duplicate_id", "unknown_dependency", "dependency_cycle",
    "required_unsupported", "required_model_judgment", "latency_out_of_bounds",
    "infeasible_cohort")`.
  - `plan_rejected(where: str, reason: str, detail: str) -> ProofPlanRejected`: the one
    construction path, with message `f"{where}: proof plan rejected: {reason}: {detail}"`.
    A reason outside the tuple is `ValueError` (the #206 D21 pattern).
  - `derived_id(derived_class: str, identity: str) -> str` returns
    `f"derived:{derived_class}:{identity}"`.
  - `compile_proof(declaration: Any, *, where: str = "proof") -> dict`: the normalized,
    transaction-independent declaration. It raises `ProofPlanRejected`.
  - `cohort_schedule(obligations: Sequence[Mapping], collectors: Mapping) -> dict`: over
    materialized-shape obligations, it returns `{"members", "makespan_ms", "margin_ms",
    "governing_window_ms"}`.
  - `materialize_plan(compiled: dict, transaction_id: str) -> dict`: the stored plan.
  - `declaration_of(plan: Any) -> dict | None` and `plan_violation(plan: Any,
    transaction_id: str) -> str | None` (per D24; Task 2 consumes them).
- Produces (`agent_tools.transaction_core` re-exports): `compile_proof`, `materialize_plan`,
  `PLAN_SCHEMA`, `PLAN_REJECTION_REASONS`, the nine constants and `ProofPlanRejected`.

**Invariants:**
- `transaction_plan` imports only the standard library, `agent_tools.canonical`,
  `transaction_invocation`, `transaction_custody` and `transaction_storage`, and reads no
  file, lock or clock.
- `compile_proof` checks the rules in this order, and the first failure wins (per D26):
  1. `derived_class_named`. When `declaration` is a dict whose `obligations` is a list, any
     dict entry whose `semantic` is in `DERIVED_CLASSES`, which has a `derived_class` or
     `obligation_kind` key, or whose `id` is a string starting `derived:`.
  2. `malformed`:
     - `declaration` fails `json_object_violation`, or its keys are not `{units,
       obligations, collectors}` plus optionally `convergence_window_ms`;
     - `units` is not a list of dicts keyed exactly `{name, parameters, phase, collector}`,
       where `action_violation(name, parameters)` is None, `phase` is in `PHASES` and
       `collector` is a non-empty string;
     - two units share a name and a parameters digest;
     - `obligations` is not a list of dicts keyed `{id, semantic, form, predicate,
       collector, required, deps, parameters}` plus optionally `freshness_ms`, where `id`,
       `predicate` and `collector` are non-empty strings, `semantic` is in `SEMANTICS`,
       `form` is in `EVIDENCE_FORMS`, `required` is a bool, `deps` is a list of unique
       non-empty strings, `parameters` passes `json_object_violation`, and `freshness_ms`
       is absent, None or an int (not a bool);
     - a non-snapshot obligation has a non-None `freshness_ms`;
     - `collectors` is not a dict from non-empty strings to dicts with keys between
       `{basis, predicates}` and `{basis, predicates, max_collection_latency_ms,
       max_concurrent_collections}`, where `basis` is in `BASES`, `predicates` is a list
       of unique non-empty strings, the latency (when present) is an int (not a bool), and
       the concurrency (when present) is an int ≥ 1;
     - `convergence_window_ms`, when present, is not an int (or is a bool).
  3. `reserved_predicate`: an obligation whose predicate is in
     `RESERVED_PREDICATES.values()`.
  4. `unknown_collector`: a unit or obligation collector that is not a `collectors` key.
  5. `duplicate_id`: two obligations share an `id`.
  6. `unknown_dependency`. A dep must be a declared obligation id, or
     `derived:<class>:<unit name>` where exactly one unit has that name and
     `PHASE_CLASS[unit.phase] == class`.
  7. `dependency_cycle` among declared obligations.
  8. `required_unsupported`: a required obligation whose collector's `predicates` lacks
     its predicate, or a unit whose collector lacks `RESERVED_PREDICATES[PHASE_CLASS[phase]]`.
  9. `required_model_judgment`: a required obligation, or any unit, whose collector has
     basis `model`.
  10. `latency_out_of_bounds`: a collector latency that is absent or outside
      `[1, MAX_COLLECTION_LATENCY_MS]`; a snapshot `freshness_ms` that is absent, None or
      outside `[1, MAX_FRESHNESS_MS]`; or a `convergence_window_ms` outside
      `[1, MAX_CONVERGENCE_WINDOW_MS]`.
  11. `infeasible_cohort`: the schedule's `makespan_ms + margin_ms` exceeds a non-null
      `governing_window_ms` or the convergence window (per D9, D28).
- The normalized output has exactly the keys `units`, `obligations`, `collectors` and
  `convergence_window_ms` (the default when absent). Every obligation carries
  `freshness_ms` (None unless snapshot). Every collector carries
  `max_concurrent_collections` (1 when absent). Each is a deep copy; the input is never
  mutated.
- `materialize_plan` returns exactly `{"schema": PLAN_SCHEMA, "convergence_window_ms",
  "units", "collectors", "obligations", "cohort"}` (per D3):
  - Each `units[i]` is the compiled unit plus
    `"action_id": action_id(transaction_id, name, parameters)`.
  - Obligations come in one stable topological order: publication-derived, then
    activation-derived (unit order), then declared. The declared ones are ordered by
    repeatedly taking the first remaining obligation in declaration order whose deps are
    all placed.
  - Each obligation is keyed exactly `obligation_id, obligation_kind, semantic,
    derived_class, form, predicate, collector, required, deps, parameters, freshness_ms`.
  - A derived obligation is `{obligation_id: derived_id(class, action id), obligation_kind:
    "core_derived", semantic: None, derived_class: class, form: DERIVED_FORMS[class],
    predicate: RESERVED_PREDICATES[class], collector: unit collector, required: True, deps:
    [], parameters: {"name": unit name, "parameters": unit parameters}, freshness_ms:
    RUNNING_IDENTITY_FRESHNESS_MS if running else None}`.
  - A declared obligation is `obligation_kind: "profile_declared"`, with `derived_class:
    None`, its own fields, and each `derived:<class>:<unit name>` dep rewritten to that
    unit's `derived_id(class, action_id)`.
  - `cohort` is `cohort_schedule(obligations, collectors)`.
- The `cohort_schedule` members are the required `snapshot` obligations, in plan order. To
  schedule them, walk the members in order, keeping one list of slot-free times per
  collector (length = its concurrency, all starting at 0):
  - `ready` is the latest finish among the member prerequisites reachable transitively
    through `deps`, across every obligation (0 when there are none).
  - `start = max(ready, the smallest slot time)`, taking the first slot holding that
    minimum.
  - `finish = start + max_collection_latency_ms`, and the slot's time becomes `finish`.
  - `makespan_ms` is the largest finish (0 when there are no members), and
    `margin_ms = max(-(-makespan_ms * 20 // 100), 5_000)` (a ceiling).
  - `governing_window_ms` is the smallest member `freshness_ms`, or None when there are no
    members.
- `declaration_of(plan)` inverts materialization (units without `action_id`; the declared
  obligations with derived deps mapped back to `derived:<class>:<unit name>` and
  `freshness_ms` omitted when None; `collectors`; `convergence_window_ms`). It returns None
  for any shape it cannot read and never raises. `plan_violation` returns None exactly when
  `serialize(plan) == serialize(materialize_plan(compile_proof(declaration_of(plan)),
  transaction_id))`, and otherwise a rule string naming `proof_plan`. It also returns a
  rule string when `declaration_of` is None or compile raises (per D24).

- [ ] **Step 1: Write the failing tests.** Create `tests/test_transaction_plan.py`:

```python
"""Transaction core slice 4: proof plans (#207).

Run: just agent-workflow-tests
"""

import copy
import unittest

from agent_tools import transaction_storage
from agent_tools.transaction_core import (
    COHORT_MARGIN_FLOOR_MS, DEFAULT_CONVERGENCE_WINDOW_MS, MAX_COHORT_ATTEMPTS,
    MAX_COLLECTION_LATENCY_MS, MAX_CONVERGENCE_WINDOW_MS, MAX_FRESHNESS_MS,
    PLAN_REJECTION_REASONS, PLAN_SCHEMA, RUNNING_IDENTITY_FRESHNESS_MS, ProofPlanRejected,
    TransactionError, action_id, compile_proof, materialize_plan)

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


if __name__ == "__main__":
    unittest.main()
```

  In `tests/test_transaction_core_sweep.py`, add `transaction_plan` to the late import and
  insert it into `NEUTRAL_MODULES` directly before `transaction_invocation`. In `justfile`,
  add `    tests/test_transaction_plan.py \` directly after the
  `tests/test_transaction_invocation.py \` line.

  Before relying on a table case, check that it is single-fault under the precedence above;
  if one also trips an earlier rule, fix the case, never the precedence.

- [ ] **Step 2: Run the tests and watch them fail.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_plan.py 2>&1 | tail -3`.
  Expected: FAIL, `ImportError: cannot import name 'COHORT_MARGIN_FLOOR_MS'`.

- [ ] **Step 3: Implement.**
  1. Storage: add `ProofPlanRejected` after `EffectResultInvalid`, using the docstring
     above.
  2. `transaction_plan.py`: the vocabularies, constants and functions under **Produces**,
     following the invariants. Keep one private helper that builds the materialized
     obligation list from a compiled declaration and a unit-identity function. `compile_proof`
     calls it with provisional identities (`f"unit{i}"`) to run `cohort_schedule` for rule
     11, and `materialize_plan` calls it with real action ids. Give the module a docstring,
     written from the finished code, stating what it holds and that it reads no file, lock
     or clock.
  3. Core: import and re-export the names under **Produces**, and add one module-docstring
     sentence naming `agent_tools.transaction_plan` as the home of the proof declaration's
     compiler and the plan constants.

- [ ] **Step 4: Verify.**
  Run: `PYTHONPATH=python python3 -m unittest tests/test_transaction_plan.py tests/test_transaction_core.py tests/test_transaction_custody.py tests/test_transaction_invocation.py tests/test_transaction_core_sweep.py 2>&1 | tail -3`.
  Expected: `OK` (neutrality now covers six modules).

```bash
if grep -nE "^(from|import) .*transaction_(core|history|proof)" python/agent_tools/transaction_plan.py; then exit 1; fi
[ "$(grep -c 'tests/test_transaction_plan.py' justfile)" = 1 ] || exit 1
```

  Run: `git add -A python tests justfile && just build 2>&1 | tail -3`. Expected: success.

- [ ] **Step 5: Commit.**

```bash
git add python/agent_tools/transaction_plan.py python/agent_tools/transaction_storage.py \
  python/agent_tools/transaction_core.py tests/test_transaction_plan.py \
  tests/test_transaction_core_sweep.py justfile
git commit -m "feat(transaction-core): compile and materialize proof plans (#207)"
```

Decisions: per D1, D2, D4, D5, D9, D19, D24, D26, D28.
