"""Proof plans (#207): the proof declaration's vocabularies, the D19 plan constants, the
compiler that refuses a declaration with one closed `ProofPlanRejected` reason, the
materializer that binds a compiled declaration to one transaction's action ids and derived
identity obligations, and the deterministic cohort schedule that decides feasibility.

`compile_proof` checks its rules in D26's order, first failure wins, and returns a normalized,
transaction-independent deep copy. `materialize_plan` produces the stored `proof_plan`, and
`declaration_of` and `plan_violation` invert and re-check it for the validator (D24). Every
function here is pure: the module reads no file, lock or clock.
"""

import copy
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import Any

from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_custody import EVIDENCE_FORMS
from agent_tools.transaction_invocation import action_id, action_violation
from agent_tools.transaction_storage import (
    ProofPlanRejected, TransactionError, json_object_violation, serialize)

PLAN_SCHEMA = "transaction-proof-plan/v1"
MAX_COLLECTION_LATENCY_MS = 300_000
MAX_FRESHNESS_MS = 7_200_000
MAX_COHORT_ATTEMPTS = 3
COHORT_MARGIN_PERCENT = 20
COHORT_MARGIN_FLOOR_MS = 5_000
RUNNING_IDENTITY_FRESHNESS_MS = 600_000
DEFAULT_CONVERGENCE_WINDOW_MS = 1_800_000
MAX_CONVERGENCE_WINDOW_MS = 7_200_000

SEMANTICS = ("liveness", "readiness", "product_smoke", "observability", "rollback_readiness")
PHASES = ("publication", "activation")
BASES = ("deterministic", "model")
DERIVED_CLASSES = ("published_artifact_identity", "running_subject_identity")
PHASE_CLASS = MappingProxyType({"publication": "published_artifact_identity",
                                "activation": "running_subject_identity"})
RESERVED_PREDICATES = MappingProxyType({"published_artifact_identity": "publication_visible",
                                        "running_subject_identity": "running_subject_identity"})
DERIVED_FORMS = MappingProxyType({"published_artifact_identity": "event",
                                  "running_subject_identity": "snapshot"})
DERIVED_REASONS = MappingProxyType({
    "published_artifact_identity": ("ref_absent", "ref_not_immutable", "digest_mismatch",
                                    "subject_mismatch", "store_unreachable"),
    "running_subject_identity": ("subject_absent", "subject_mismatch",
                                 "unrelated_subject_running", "attempt_mismatch",
                                 "identity_unobservable")})
PLAN_REJECTION_REASONS = (
    "malformed", "derived_class_named", "reserved_predicate", "unknown_collector",
    "duplicate_id", "unknown_dependency", "dependency_cycle", "advisory_prerequisite",
    "required_unsupported", "required_model_judgment", "latency_out_of_bounds",
    "infeasible_cohort")

_DECLARATION_KEYS = frozenset({"units", "obligations", "collectors"})
_UNIT_KEYS = frozenset({"name", "parameters", "phase", "collector"})
_OBLIGATION_KEYS = frozenset({"id", "semantic", "form", "predicate", "collector", "required",
                              "deps", "parameters"})
_COLLECTOR_KEYS = frozenset({"basis", "predicates"})
_COLLECTOR_OPTIONAL = frozenset({"max_collection_latency_ms", "max_concurrent_collections"})
_DERIVED_PREFIX = "derived:"


def plan_rejected(where: str, reason: str, detail: str) -> ProofPlanRejected:
    """The one construction path for `ProofPlanRejected`; a `reason` outside
    `PLAN_REJECTION_REASONS` is a programming error (`ValueError`) (#206 D21)."""
    if reason not in PLAN_REJECTION_REASONS:
        raise ValueError(f"plan_rejected: {reason!r} is not a plan rejection reason")
    return ProofPlanRejected(f"{where}: proof plan rejected: {reason}: {detail}",
                             reason=reason)


def derived_id(derived_class: str, identity: str) -> str:
    return f"{_DERIVED_PREFIX}{derived_class}:{identity}"


def _is_text(value: Any) -> bool:
    return type(value) is str and bool(value)


def _is_int(value: Any) -> bool:
    return type(value) is int


def _texts_violation(values: Any, what: str) -> str | None:
    if type(values) is not list:
        return f"{what} is not a list"
    if not all(_is_text(value) for value in values):
        return f"{what} holds a value that is not a non-empty string"
    if len(set(values)) != len(values):
        return f"{what} repeats a value"
    return None


def _named_derived(entry: Any) -> bool:
    """Whether a declared obligation names the derived floor it may never author (D26)."""
    return type(entry) is dict and (
        entry.get("semantic") in DERIVED_CLASSES or "derived_class" in entry
        or "obligation_kind" in entry
        or (type(entry.get("id")) is str and entry["id"].startswith(_DERIVED_PREFIX)))


def _unit_violation(index: int, unit: Any) -> str | None:
    if type(unit) is not dict or set(unit) != _UNIT_KEYS:
        return f"units[{index}] is not an object keyed exactly {sorted(_UNIT_KEYS)}"
    violation = action_violation(unit["name"], unit["parameters"])
    if violation is not None:
        return f"units[{index}] {violation}"
    if unit["phase"] not in PHASES:
        return f"units[{index}] phase {unit['phase']!r} is not one of {PHASES}"
    if not _is_text(unit["collector"]):
        return f"units[{index}] collector is not a non-empty string"
    return None


def _obligation_violation(index: int, entry: Any) -> str | None:
    where = f"obligations[{index}]"
    if type(entry) is not dict or not _OBLIGATION_KEYS <= set(entry) <= (
            _OBLIGATION_KEYS | {"freshness_ms"}):
        return f"{where} is not an object keyed {sorted(_OBLIGATION_KEYS)} (+ freshness_ms)"
    for key in ("id", "predicate", "collector"):
        if not _is_text(entry[key]):
            return f"{where} {key} is not a non-empty string"
    if entry["semantic"] not in SEMANTICS:
        return f"{where} semantic {entry['semantic']!r} is not one of {SEMANTICS}"
    if entry["form"] not in EVIDENCE_FORMS:
        return f"{where} form {entry['form']!r} is not one of {EVIDENCE_FORMS}"
    if type(entry["required"]) is not bool:
        return f"{where} required is not a boolean"
    violation = _texts_violation(entry["deps"], f"{where} deps")
    if violation is not None:
        return violation
    violation = json_object_violation(entry["parameters"])
    if violation is not None:
        return f"{where} parameters {violation}"
    freshness = entry.get("freshness_ms")
    if freshness is not None and not _is_int(freshness):
        return f"{where} freshness_ms is not an integer"
    if freshness is not None and entry["form"] != "snapshot":
        return f"{where} freshness_ms is set on a non-snapshot obligation"
    return None


def _collector_violation(name: Any, spec: Any) -> str | None:
    if not _is_text(name):
        return f"collector handle {name!r} is not a non-empty string"
    where = f"collectors[{name!r}]"
    if type(spec) is not dict or not _COLLECTOR_KEYS <= set(spec) <= (
            _COLLECTOR_KEYS | _COLLECTOR_OPTIONAL):
        return f"{where} is not an object keyed {sorted(_COLLECTOR_KEYS)} (+ optional caps)"
    if spec["basis"] not in BASES:
        return f"{where} basis {spec['basis']!r} is not one of {BASES}"
    violation = _texts_violation(spec["predicates"], f"{where} predicates")
    if violation is not None:
        return violation
    if "max_collection_latency_ms" in spec and not _is_int(spec["max_collection_latency_ms"]):
        return f"{where} max_collection_latency_ms is not an integer"
    concurrency = spec.get("max_concurrent_collections", 1)
    if not _is_int(concurrency) or concurrency < 1:
        return f"{where} max_concurrent_collections is not an integer of at least 1"
    return None


def _shape_violation(declaration: Any) -> str | None:
    """The first `malformed` rule the declaration breaks, or None."""
    violation = json_object_violation(declaration)
    if violation is not None:
        return f"declaration {violation}"
    if not _DECLARATION_KEYS <= set(declaration) <= (
            _DECLARATION_KEYS | {"convergence_window_ms"}):
        return (f"declaration keys {sorted(declaration)} are not "
                f"{sorted(_DECLARATION_KEYS)} (+ convergence_window_ms)")
    units, obligations, collectors = (declaration["units"], declaration["obligations"],
                                      declaration["collectors"])
    if type(units) is not list:
        return "units is not a list"
    seen = set()
    for index, unit in enumerate(units):
        violation = _unit_violation(index, unit)
        if violation is not None:
            return violation
        identity = (unit["name"], telemetry_digest(unit["parameters"]))
        if identity in seen:
            return f"units[{index}] repeats name {unit['name']!r} with the same parameters"
        seen.add(identity)
    if type(obligations) is not list:
        return "obligations is not a list"
    for index, entry in enumerate(obligations):
        violation = _obligation_violation(index, entry)
        if violation is not None:
            return violation
    if type(collectors) is not dict:
        return "collectors is not an object"
    for name, spec in collectors.items():
        violation = _collector_violation(name, spec)
        if violation is not None:
            return violation
    if "convergence_window_ms" in declaration and not _is_int(
            declaration["convergence_window_ms"]):
        return "convergence_window_ms is not an integer"
    return None


def _dependency_violation(obligations: list[dict], units: list[dict]) -> str | None:
    """The first dep that names neither a declared obligation nor one unit's derived id."""
    declared = {entry["id"] for entry in obligations}
    for entry in obligations:
        for dep in entry["deps"]:
            if dep in declared:
                continue
            derived_class, _, name = dep[len(_DERIVED_PREFIX):].partition(":")
            matches = [unit for unit in units if unit["name"] == name]
            if not (dep.startswith(_DERIVED_PREFIX) and len(matches) == 1
                    and PHASE_CLASS[matches[0]["phase"]] == derived_class):
                return f"{entry['id']} -> {dep}"
    return None


def _cycle(obligations: list[dict]) -> list[str]:
    """The declared ids left unplaced by a topological pass: those on or behind a cycle."""
    declared = {entry["id"]: entry for entry in obligations}
    placed: set[str] = set()
    progress = True
    while progress:
        progress = False
        for identity, entry in declared.items():
            if identity not in placed and all(dep in placed or dep not in declared
                                              for dep in entry["deps"]):
                placed.add(identity)
                progress = True
    return [identity for identity in declared if identity not in placed]


def _support_violation(obligations: list[dict], units: list[dict],
                       collectors: dict) -> tuple[str, str] | None:
    """The first (reason, detail) of the D9 support and model-judgment rules, or None."""
    for entry in obligations:
        if entry["required"] and entry["predicate"] not in (
                collectors[entry["collector"]]["predicates"]):
            return "required_unsupported", (f"{entry['id']}: collector {entry['collector']!r} "
                                            f"lacks predicate {entry['predicate']!r}")
    for unit in units:
        predicate = RESERVED_PREDICATES[PHASE_CLASS[unit["phase"]]]
        if predicate not in collectors[unit["collector"]]["predicates"]:
            return "required_unsupported", (f"unit {unit['name']!r}: collector "
                                            f"{unit['collector']!r} lacks {predicate!r}")
    bound = [(f"obligation {entry['id']!r}", entry["collector"])
             for entry in obligations if entry["required"]]
    bound += [(f"unit {unit['name']!r}", unit["collector"]) for unit in units]
    for what, handle in bound:
        if collectors[handle]["basis"] == "model":
            return "required_model_judgment", f"{what} is bound to model collector {handle!r}"
    return None


def _bounds_violation(declaration: dict) -> str | None:
    for name, spec in declaration["collectors"].items():
        latency = spec.get("max_collection_latency_ms")
        if latency is None or not 1 <= latency <= MAX_COLLECTION_LATENCY_MS:
            return (f"collector {name!r} max_collection_latency_ms {latency!r} is not in "
                    f"[1, {MAX_COLLECTION_LATENCY_MS}]")
    for entry in declaration["obligations"]:
        freshness = entry.get("freshness_ms")
        if entry["form"] == "snapshot" and (freshness is None
                                            or not 1 <= freshness <= MAX_FRESHNESS_MS):
            return (f"{entry['id']} freshness_ms {freshness!r} is not in "
                    f"[1, {MAX_FRESHNESS_MS}]")
    window = declaration.get("convergence_window_ms", DEFAULT_CONVERGENCE_WINDOW_MS)
    if not 1 <= window <= MAX_CONVERGENCE_WINDOW_MS:
        return f"convergence_window_ms {window} is not in [1, {MAX_CONVERGENCE_WINDOW_MS}]"
    return None


def _normalized(declaration: dict) -> dict:
    return {
        "units": copy.deepcopy(declaration["units"]),
        "obligations": [{**copy.deepcopy(entry), "freshness_ms": entry.get("freshness_ms")}
                        for entry in declaration["obligations"]],
        "collectors": {name: {"max_concurrent_collections": 1, **copy.deepcopy(spec)}
                       for name, spec in declaration["collectors"].items()},
        "convergence_window_ms": declaration.get("convergence_window_ms",
                                                 DEFAULT_CONVERGENCE_WINDOW_MS),
    }


def _plan_obligations(compiled: dict, identity: Callable[[int], str]) -> list[dict]:
    """The materialized obligations in plan order, each unit identified by `identity(i)`."""
    derived: dict[str, list[dict]] = {phase: [] for phase in PHASES}
    rewrite: dict[str, str] = {}
    for index, unit in enumerate(compiled["units"]):
        derived_class = PHASE_CLASS[unit["phase"]]
        obligation_id = derived_id(derived_class, identity(index))
        rewrite[derived_id(derived_class, unit["name"])] = obligation_id
        derived[unit["phase"]].append({
            "obligation_id": obligation_id, "obligation_kind": "core_derived",
            "semantic": None, "derived_class": derived_class,
            "form": DERIVED_FORMS[derived_class],
            "predicate": RESERVED_PREDICATES[derived_class], "collector": unit["collector"],
            "required": True, "deps": [],
            "parameters": {"name": unit["name"],
                           "parameters": copy.deepcopy(unit["parameters"])},
            "freshness_ms": (RUNNING_IDENTITY_FRESHNESS_MS
                             if derived_class == "running_subject_identity" else None)})
    ordered = [*derived["publication"], *derived["activation"]]
    placed = {entry["obligation_id"] for entry in ordered}
    remaining = [{
        "obligation_id": entry["id"], "obligation_kind": "profile_declared",
        "semantic": entry["semantic"], "derived_class": None, "form": entry["form"],
        "predicate": entry["predicate"], "collector": entry["collector"],
        "required": entry["required"], "deps": [rewrite.get(dep, dep) for dep in entry["deps"]],
        "parameters": copy.deepcopy(entry["parameters"]),
        "freshness_ms": entry["freshness_ms"]} for entry in compiled["obligations"]]
    while remaining:
        entry = next(entry for entry in remaining
                     if all(dep in placed for dep in entry["deps"]))
        remaining.remove(entry)
        ordered.append(entry)
        placed.add(entry["obligation_id"])
    return ordered


def cohort_schedule(obligations: Sequence[Mapping], collectors: Mapping) -> dict:
    """The required snapshots, in plan order, list-scheduled under per-collector caps along
    their transitive prerequisites; the makespan, its margin and the governing window (D9)."""
    by_id = {entry["obligation_id"]: entry for entry in obligations}
    members = [entry for entry in obligations
               if entry["required"] and entry["form"] == "snapshot"]
    finish: dict[str, int] = {}
    uses = [member["collector"] for member in members]
    slots = {name: [0] * min(collectors[name]["max_concurrent_collections"], uses.count(name))
             for name in set(uses)}
    for member in members:
        ready, stack, seen = 0, list(member["deps"]), set()
        while stack:
            dep = stack.pop()
            if dep in seen:
                continue
            seen.add(dep)
            ready = max(ready, finish.get(dep, 0))
            stack.extend(by_id[dep]["deps"] if dep in by_id else ())
        spec = collectors[member["collector"]]
        free = slots[member["collector"]]
        slot = free.index(min(free))
        done = max(ready, free[slot]) + spec["max_collection_latency_ms"]
        free[slot] = finish[member["obligation_id"]] = done
    makespan = max(finish.values(), default=0)
    return {"members": [member["obligation_id"] for member in members],
            "makespan_ms": makespan,
            "margin_ms": max(-(-makespan * COHORT_MARGIN_PERCENT // 100),
                             COHORT_MARGIN_FLOOR_MS),
            "governing_window_ms": min((member["freshness_ms"] for member in members),
                                       default=None)}


def compile_proof(declaration: Any, *, where: str = "proof") -> dict:
    """The normalized, transaction-independent declaration; raises `ProofPlanRejected` with
    the first failing rule in D26's order, and never mutates `declaration`."""
    if type(declaration) is dict and type(declaration.get("obligations")) is list:
        for entry in declaration["obligations"]:
            if _named_derived(entry):
                raise plan_rejected(where, "derived_class_named",
                                    f"obligation {entry.get('id')!r} names a derived class")
    violation = _shape_violation(declaration)
    if violation is not None:
        raise plan_rejected(where, "malformed", violation)
    units, obligations = declaration["units"], declaration["obligations"]
    collectors = declaration["collectors"]
    for entry in obligations:
        if entry["predicate"] in RESERVED_PREDICATES.values():
            raise plan_rejected(where, "reserved_predicate",
                                f"{entry['id']} declares {entry['predicate']!r}")
    for what, handle in ([(f"unit {unit['name']!r}", unit["collector"]) for unit in units]
                         + [(entry["id"], entry["collector"]) for entry in obligations]):
        if handle not in collectors:
            raise plan_rejected(where, "unknown_collector", f"{what} names {handle!r}")
    ids = [entry["id"] for entry in obligations]
    for identity in ids:
        if ids.count(identity) > 1:
            raise plan_rejected(where, "duplicate_id", f"{identity!r} is declared twice")
    violation = _dependency_violation(obligations, units)
    if violation is not None:
        raise plan_rejected(where, "unknown_dependency", violation)
    cycle = _cycle(obligations)
    if cycle:
        raise plan_rejected(where, "dependency_cycle", ", ".join(cycle))
    required = {entry["id"]: entry["required"] for entry in obligations}
    for entry in obligations:
        for dep in entry["deps"] if entry["required"] else ():
            if required.get(dep) is False:
                raise plan_rejected(where, "advisory_prerequisite", f"{entry['id']} -> {dep}")
    support = _support_violation(obligations, units, collectors)
    if support is not None:
        raise plan_rejected(where, *support)
    violation = _bounds_violation(declaration)
    if violation is not None:
        raise plan_rejected(where, "latency_out_of_bounds", violation)
    compiled = _normalized(declaration)
    cohort = cohort_schedule(_plan_obligations(compiled, lambda index: f"unit{index}"),
                             compiled["collectors"])
    needed = cohort["makespan_ms"] + cohort["margin_ms"]
    for name, window in (("governing window", cohort["governing_window_ms"]),
                         ("convergence window", compiled["convergence_window_ms"])):
        if window is not None and needed > window:
            raise plan_rejected(where, "infeasible_cohort",
                                f"makespan {cohort['makespan_ms']} + margin "
                                f"{cohort['margin_ms']} exceeds the {name} {window}")
    return compiled


def materialize_plan(compiled: dict, transaction_id: str) -> dict:
    """The stored `proof_plan`: the compiled declaration bound to `transaction_id`'s action
    ids, with its derived obligations and cohort (D3)."""
    units = [{**copy.deepcopy(unit),
              "action_id": action_id(transaction_id, unit["name"], unit["parameters"])}
             for unit in compiled["units"]]
    obligations = _plan_obligations(compiled, lambda index: units[index]["action_id"])
    collectors = copy.deepcopy(compiled["collectors"])
    return {"schema": PLAN_SCHEMA, "convergence_window_ms": compiled["convergence_window_ms"],
            "units": units, "collectors": collectors, "obligations": obligations,
            "cohort": cohort_schedule(obligations, collectors)}


def _declaration_of(plan: dict) -> dict:
    names = {derived_id(PHASE_CLASS[unit["phase"]], unit["action_id"]):
             derived_id(PHASE_CLASS[unit["phase"]], unit["name"]) for unit in plan["units"]}
    obligations = []
    for entry in plan["obligations"]:
        if entry["obligation_kind"] != "profile_declared":
            continue
        declared = {"id": entry["obligation_id"], "semantic": entry["semantic"],
                    "form": entry["form"], "predicate": entry["predicate"],
                    "collector": entry["collector"], "required": entry["required"],
                    "deps": [names.get(dep, dep) for dep in entry["deps"]],
                    "parameters": entry["parameters"]}
        if entry["freshness_ms"] is not None:
            declared["freshness_ms"] = entry["freshness_ms"]
        obligations.append(declared)
    return copy.deepcopy({
        "units": [{key: value for key, value in unit.items() if key != "action_id"}
                  for unit in plan["units"]],
        "obligations": obligations, "collectors": plan["collectors"],
        "convergence_window_ms": plan["convergence_window_ms"]})


def declaration_of(plan: Any) -> dict | None:
    """The declaration a stored plan materializes, or None for any shape it cannot read;
    never raises (D24)."""
    try:
        return _declaration_of(plan)
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
        return None


def plan_violation(plan: Any, transaction_id: str) -> str | None:
    """None exactly when `plan` is byte-identical to the materialization of its own
    declaration for `transaction_id`, else the rule it breaks (D24)."""
    declaration = declaration_of(plan)
    if declaration is None:
        return "proof_plan is not a readable materialized proof plan"
    try:
        expected = serialize(materialize_plan(compile_proof(declaration, where="proof_plan"),
                                              transaction_id))
        stored = serialize(plan)
    except ProofPlanRejected as error:
        return str(error)
    except (TransactionError, TypeError, ValueError) as error:
        return f"proof_plan cannot be materialized ({error})"
    if stored != expected:
        return "proof_plan is not the materialization of its own declaration"
    return None
