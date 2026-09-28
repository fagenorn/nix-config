"""Recovery plans (#208): the recovery declaration's vocabularies, the compiler that refuses a
declaration with one closed `RecoveryPlanRejected` reason, the binder that pairs it with a
compiled proof declaration, and the materializer that fixes one transaction's action ids.

`compile_recovery` checks four rules in this order, first failure wins, and each rule runs
over every unit, in declaration order, before the next starts (D5, D21): `malformed` (shape,
closed keys, an unknown posture or edge action, a residue that does not match its edge
action, or one action identity shared by two units or edges), `posture_violation` (D3, D4's
table of anchor, compatibility and edges per posture), `unknown_effect` and
`unsupported_operation` (a unit's forward operation, then its edges' operations, that its
effect does not offer). It returns a deep copy and never mutates its input.
`bind_recovery` then refuses `unit_mismatch` when the recovery units are not exactly the
proof units by `(name, parameters)`, and `unsupported_check` when an anchor or compatibility
predicate is not listed by that unit's proof collector; it orders the units as the proof
declaration does. `materialize_recovery` produces the stored `recovery_plan` (D6), and
`recovery_declaration_of` and `recovery_plan_violation` invert and re-check it for the
validator, the single home of that rule. Every function here is pure: the module reads no
file, lock or clock.
"""

import copy
from collections import Counter
from typing import Any

from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_invocation import action_id, action_violation
from agent_tools.transaction_plan import compile_proof, declaration_of
from agent_tools.transaction_storage import (
    RecoveryPlanRejected, TransactionError, json_object_violation, serialize)

RECOVERY_PLAN_SCHEMA = "transaction-recovery-plan/v1"
POSTURES = ("restorable", "compensatable", "supersedable_only", "manual_only")
EDGE_ACTIONS = ("restore", "compensate")
RECOVERY_REJECTION_REASONS = ("malformed", "posture_violation", "unknown_effect",
                              "unsupported_operation", "unit_mismatch", "unsupported_check")

_DECLARATION_KEYS = frozenset({"effects", "units"})
_UNIT_KEYS = frozenset({"name", "parameters", "effect", "operation", "posture", "anchor",
                        "compatibility", "edges"})
_CHECK_KEYS = frozenset({"predicate", "parameters"})
_EDGE_KEYS = frozenset({"action", "operation", "parameters", "residue"})
_CHECKS = ("anchor", "compatibility")


def recovery_rejected(where: str, reason: str, detail: str) -> RecoveryPlanRejected:
    """The one construction path for `RecoveryPlanRejected`; a `reason` outside
    `RECOVERY_REJECTION_REASONS` is a programming error (`ValueError`)."""
    if reason not in RECOVERY_REJECTION_REASONS:
        raise ValueError(f"recovery_rejected: {reason!r} is not a recovery rejection reason")
    return RecoveryPlanRejected(f"{where}: recovery plan rejected: {reason}: {detail}",
                                reason=reason)


def _is_text(value: Any) -> bool:
    return type(value) is str and bool(value)


def _effect_violation(handle: str, spec: Any) -> str | None:
    if not _is_text(handle):
        return f"effect handle {handle!r} is not a non-empty string"
    where = f"effects[{handle!r}]"
    if type(spec) is not dict or set(spec) != {"operations"}:
        return f"{where} is not an object keyed exactly ['operations']"
    operations = spec["operations"]
    if type(operations) is not list:
        return f"{where} operations is not a list"
    if not all(_is_text(operation) for operation in operations):
        return f"{where} operations holds a value that is not a non-empty string"
    if len(set(operations)) != len(operations):
        return f"{where} operations repeats a value"
    return None


def _check_violation(where: str, check: Any) -> str | None:
    if check is None:
        return None
    if type(check) is not dict or set(check) != _CHECK_KEYS:
        return f"{where} is neither null nor an object keyed exactly {sorted(_CHECK_KEYS)}"
    if not _is_text(check["predicate"]):
        return f"{where} predicate is not a non-empty string"
    violation = json_object_violation(check["parameters"])
    return None if violation is None else f"{where} parameters {violation}"


def _edge_violation(where: str, edge: Any) -> str | None:
    if type(edge) is not dict or set(edge) != _EDGE_KEYS:
        return f"{where} is not an object keyed exactly {sorted(_EDGE_KEYS)}"
    if edge["action"] not in EDGE_ACTIONS:
        return f"{where} action {edge['action']!r} is not one of {EDGE_ACTIONS}"
    violation = action_violation(edge["operation"], edge["parameters"])
    if violation is not None:
        return f"{where} {violation}"
    if edge["action"] == "restore" and edge["residue"] is not None:
        return f"{where} is a restore edge whose residue is not null"
    if edge["action"] == "compensate" and not _is_text(edge["residue"]):
        return f"{where} is a compensate edge whose residue is not a non-empty string"
    return None


def _unit_violation(index: int, unit: Any) -> str | None:
    where = f"units[{index}]"
    if type(unit) is not dict or set(unit) != _UNIT_KEYS:
        return f"{where} is not an object keyed exactly {sorted(_UNIT_KEYS)}"
    violation = action_violation(unit["name"], unit["parameters"])
    if violation is not None:
        return f"{where} {violation}"
    for key in ("effect", "operation"):
        if not _is_text(unit[key]):
            return f"{where} {key} is not a non-empty string"
    if unit["posture"] not in POSTURES:
        return f"{where} posture {unit['posture']!r} is not one of {POSTURES}"
    for key in _CHECKS:
        violation = _check_violation(f"{where} {key}", unit[key])
        if violation is not None:
            return violation
    if type(unit["edges"]) is not list:
        return f"{where} edges is not a list"
    for position, edge in enumerate(unit["edges"]):
        violation = _edge_violation(f"{where} edges[{position}]", edge)
        if violation is not None:
            return violation
    return None


def _shape_violation(declaration: Any) -> str | None:
    """The first `malformed` rule the declaration breaks, or None."""
    violation = json_object_violation(declaration)
    if violation is not None:
        return f"declaration {violation}"
    if set(declaration) != _DECLARATION_KEYS:
        return f"declaration keys {sorted(declaration)} are not {sorted(_DECLARATION_KEYS)}"
    effects, units = declaration["effects"], declaration["units"]
    if type(effects) is not dict:
        return "effects is not an object"
    for handle, spec in effects.items():
        violation = _effect_violation(handle, spec)
        if violation is not None:
            return violation
    if type(units) is not list:
        return "units is not a list"
    seen = set()
    for index, unit in enumerate(units):
        violation = _unit_violation(index, unit)
        if violation is not None:
            return violation
        actions = [(f"units[{index}]", unit["name"], unit["parameters"])]
        actions += [(f"units[{index}] edges[{position}]", edge["operation"], edge["parameters"])
                    for position, edge in enumerate(unit["edges"])]
        for where, name, parameters in actions:
            identity = (name, telemetry_digest(parameters))
            if identity in seen:
                return f"{where} repeats action {name!r} with the same parameters"
            seen.add(identity)
    return None


def _posture_violation(unit: dict) -> str | None:
    """How a well-shaped unit breaks its posture's row of the D4 table, or None."""
    posture, declared = unit["posture"], [unit[key] is not None for key in _CHECKS]
    actions = [edge["action"] for edge in unit["edges"]]
    if posture == "restorable":
        if not all(declared):
            return "is restorable without both an anchor and a compatibility check"
        if actions[:1] != ["restore"] or "restore" in actions[1:]:
            return "is restorable without exactly one leading restore edge"
        return None
    if any(declared):
        return f"is {posture} yet declares an anchor or a compatibility check"
    if posture == "compensatable" and (not actions or "restore" in actions):
        return "is compensatable without one or more edges, all compensate"
    if posture != "compensatable" and actions:
        return f"is {posture} yet declares edges"
    return None


def compile_recovery(declaration: Any, *, where: str = "recovery") -> dict:
    """A deep copy of a valid declaration; raises `RecoveryPlanRejected` with the first
    failing rule in the module's order, and never mutates `declaration`."""
    violation = _shape_violation(declaration)
    if violation is not None:
        raise recovery_rejected(where, "malformed", violation)
    effects, units = declaration["effects"], declaration["units"]
    for unit in units:
        violation = _posture_violation(unit)
        if violation is not None:
            raise recovery_rejected(where, "posture_violation",
                                    f"unit {unit['name']!r} {violation}")
    for unit in units:
        if unit["effect"] not in effects:
            raise recovery_rejected(where, "unknown_effect",
                                    f"unit {unit['name']!r} names undeclared effect "
                                    f"{unit['effect']!r}")
    for unit in units:
        handle = unit["effect"]
        for operation in [unit["operation"], *(edge["operation"] for edge in unit["edges"])]:
            if operation not in effects[handle]["operations"]:
                raise recovery_rejected(where, "unsupported_operation",
                                        f"unit {unit['name']!r} operation {operation!r} is "
                                        f"not offered by effect {handle!r}")
    return copy.deepcopy(declaration)


def _identity(unit: dict) -> tuple[str, str]:
    return unit["name"], telemetry_digest(unit["parameters"])


def bind_recovery(compiled: dict, compiled_proof: dict, *, where: str = "recovery") -> dict:
    """`{"effects", "units"}` with the units in the proof declaration's unit order; raises
    `unit_mismatch` or `unsupported_check`, and never mutates its inputs."""
    recovery_ids = Counter(_identity(unit) for unit in compiled["units"])
    proof_ids = Counter(_identity(unit) for unit in compiled_proof["units"])
    if recovery_ids != proof_ids:
        unpaired = sorted(name for name, _ in recovery_ids - proof_ids)
        unmatched = sorted(name for name, _ in proof_ids - recovery_ids)
        raise recovery_rejected(where, "unit_mismatch",
                                f"recovery units {unpaired} have no proof unit and proof "
                                f"units {unmatched} have no recovery unit")
    proof_units = {_identity(unit): unit for unit in compiled_proof["units"]}
    for unit in compiled["units"]:
        collector = proof_units[_identity(unit)]["collector"]
        listed = compiled_proof["collectors"][collector]["predicates"]
        for key in _CHECKS:
            if unit[key] is not None and unit[key]["predicate"] not in listed:
                raise recovery_rejected(where, "unsupported_check",
                                        f"unit {unit['name']!r} {key} predicate "
                                        f"{unit[key]['predicate']!r} is not listed by "
                                        f"collector {collector!r}")
    recovery_units = {_identity(unit): unit for unit in compiled["units"]}
    return copy.deepcopy({"effects": compiled["effects"],
                          "units": [recovery_units[_identity(unit)]
                                    for unit in compiled_proof["units"]]})


def materialize_recovery(bound: dict, transaction_id: str) -> dict:
    """The stored `recovery_plan`: the bound declaration with each unit's and each edge's
    `action_id` for `transaction_id` (D6)."""
    units = []
    for unit in bound["units"]:
        edges = [{**copy.deepcopy(edge),
                  "action_id": action_id(transaction_id, edge["operation"], edge["parameters"])}
                 for edge in unit["edges"]]
        units.append({**copy.deepcopy(unit), "edges": edges,
                      "action_id": action_id(transaction_id, unit["name"], unit["parameters"])})
    return {"schema": RECOVERY_PLAN_SCHEMA, "effects": copy.deepcopy(bound["effects"]),
            "units": units}


def _recovery_declaration_of(plan: dict) -> dict:
    units = [{**{key: value for key, value in unit.items() if key not in ("action_id", "edges")},
              "edges": [{key: value for key, value in edge.items() if key != "action_id"}
                        for edge in unit["edges"]]}
             for unit in plan["units"]]
    return copy.deepcopy({"effects": plan["effects"], "units": units})


def recovery_declaration_of(plan: Any) -> dict | None:
    """The declaration a stored recovery plan materializes, or None for any shape it cannot
    read; never raises."""
    try:
        return _recovery_declaration_of(plan)
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
        return None


def recovery_plan_violation(plan: Any, proof_plan: Any, transaction_id: str) -> str | None:
    """None exactly when `plan` is byte-identical to the materialization of its own
    declaration, bound to `proof_plan`'s declaration, for `transaction_id`; else the rule it
    breaks, always starting with `recovery_plan` (D6, D25)."""
    declaration = recovery_declaration_of(plan)
    if declaration is None:
        return "recovery_plan is not a readable materialized recovery plan"
    proof = declaration_of(proof_plan)
    if proof is None:
        return "recovery_plan cannot be bound: proof_plan is not a readable proof plan"
    try:
        expected = serialize(materialize_recovery(
            bind_recovery(compile_recovery(declaration, where="recovery_plan"),
                          compile_proof(proof, where="proof_plan"), where="recovery_plan"),
            transaction_id))
        stored = serialize(plan)
    except RecoveryPlanRejected as error:
        return str(error)
    except (TransactionError, TypeError, ValueError) as error:
        return f"recovery_plan cannot be materialized ({error})"
    if stored != expected:
        return "recovery_plan is not the materialization of its own declaration"
    return None
