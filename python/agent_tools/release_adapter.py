"""The adapter contract's descriptor half (#124 D7, D19).

Owns the vocabularies every adapter shares, the `Descriptor` schema and its validator
(`descriptor_problems`), the closed registry of adapters (`REGISTRY`) and the descriptors
built from it (`DESCRIPTORS`), and the closed config-schema check (`config_problems`).
An unknown adapter name is a grammar violation, never a lookup fallback (D7), so the
registry is a fixed mapping and `build_descriptors` refuses a descriptor that is malformed
or whose `name` differs from its registry key. `DESCRIPTORS` is built at import: a bad
descriptor fails the import check that `just build` runs.

Reserved predicate handles and the collector latency cap are read from `transaction_plan`,
never copied. Obligation ids are not pattern-checked here or in the grammar (D23).

The result half (#124 D7, D17, D24) holds the closed typed results an adapter returns
(`effect_observation_problems`, `predicate_observation_problems`, `invoke_result_problems`)
and `core_binding`, which projects them onto the shapes the transaction core already accepts.
The binding adds no retry, ordering or outcome policy: it pins the adapter implementation to
the compiled profile by descriptor digest, refuses a request that is not exactly a compiled
node of its alias, and validates what the adapter returns.
"""

import copy
import json
import re
from collections.abc import Mapping
from types import MappingProxyType, ModuleType
from typing import Any

from agent_tools import forge_adapter, transaction_invocation, transaction_plan
from agent_tools.agent_platform import parse_semver
from agent_tools.canonical import telemetry_digest

PUBLICATION_MODES = ("materialize", "promote", "index")
ACTIVATION_MODES = ("local_apply", "provider_deploy", "publication_triggered", "convergent_pull")
EFFECT_CLASSES = ("reversible_no_incremental_spend", "reversible_bounded_spend", "irreversible")
MUTABILITIES = ("create_if_absent", "pointer_cas", "in_place")
SUPPORT = ("supported", "unsupported")
HOST_CAPACITY = ("not_required", "required")
CONFIG_TYPES = ("string", "integer", "boolean")

ADAPTER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
OPERATION_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
CANDIDATE_MEMBERS = ("notes", "title")
DESCRIPTOR_MEMBERS = frozenset((
    "name", "adapter_contract_version", "operations", "predicates", "collector",
    "target_kinds", "credential_classes", "executables", "host_capacity"))
OPERATION_MEMBERS = frozenset((
    "mode", "support", "inspect", "reason", "mutability", "config_schema_version",
    "config_schema", "effects", "recovery_capable", "candidate_members"))
RESERVED_TARGET_MEMBERS = ("adapter", "kind")
EFFECT_OUTCOMES = transaction_invocation.OUTCOMES
PREDICATE_OUTCOMES = ("satisfied", "unsatisfied", "unknown")
INVOKE_RESULTS = ("accepted", "rejected", "unknown")
EFFECT_OBSERVATION_MEMBERS = frozenset((
    "outcome", "reason", "observed_subject", "references", "observed_at", "facts"))
PREDICATE_OBSERVATION_MEMBERS = frozenset(("outcome", "reason", "references", "observed_at"))
INVOKE_RESULT_MEMBERS = frozenset(("result", "error_class", "reference"))
BOUND_MEMBERS = ("operation", "target", "config")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_text(value: object) -> bool:
    return isinstance(value, str) and value != ""


def _closed(value: object, members: frozenset[str] | set[str], where: str,
            problems: list[str]) -> bool:
    """True when `value` is an object with exactly `members`; else record why."""
    if not isinstance(value, dict):
        problems.append(f"{where} must be an object")
        return False
    missing = sorted(members - set(value))
    unknown = sorted(set(value) - members, key=str)
    if missing:
        problems.append(f"{where} is missing {', '.join(missing)}")
    if unknown:
        problems.append(f"{where} has unknown members {', '.join(map(str, unknown))}")
    return not missing and not unknown


def _reason_problem(entry: dict[str, Any], where: str, problems: list[str]) -> None:
    support = entry.get("support")
    if support not in SUPPORT:
        problems.append(f"{where}.support must be one of {', '.join(SUPPORT)}")
        return
    reason = entry.get("reason")
    if support == "unsupported" and not _is_text(reason):
        problems.append(f"{where}.reason must be a non-empty string when unsupported")
    if support == "supported" and reason is not None:
        problems.append(f"{where}.reason must be null when supported")


def _sorted_unique_text(value: object, where: str, problems: list[str]) -> None:
    if (not isinstance(value, list) or not value or not all(_is_text(item) for item in value)
            or value != sorted(set(value))):
        problems.append(f"{where} must be a non-empty sorted unique list of non-empty strings")


def _config_schema_problems(schema: object, where: str, problems: list[str]) -> None:
    if not _closed(schema, {"members", "required"}, where, problems):
        return
    members, required = schema["members"], schema["required"]
    if not isinstance(members, dict) or not all(
            _is_text(name) and kind in CONFIG_TYPES for name, kind in members.items()):
        problems.append(f"{where}.members must map names to {', '.join(CONFIG_TYPES)}")
        return
    if not isinstance(required, list) or not all(
            isinstance(name, str) and name in members for name in required):
        problems.append(f"{where}.required must list declared members")


def _operation_problems(name: str, entry: object, problems: list[str]) -> None:
    where = f"operations.{name}"
    if not _closed(entry, OPERATION_MEMBERS, where, problems):
        return
    mode = entry["mode"]
    if mode is not None and mode not in PUBLICATION_MODES + ACTIVATION_MODES:
        problems.append(f"{where}.mode is not a known mode")
    if mode is None and entry["recovery_capable"] is not True:
        problems.append(f"{where}.mode may be null only when recovery_capable")
    _reason_problem(entry, where, problems)
    if entry["inspect"] not in SUPPORT:
        problems.append(f"{where}.inspect must be one of {', '.join(SUPPORT)}")
    if entry["mutability"] not in MUTABILITIES:
        problems.append(f"{where}.mutability must be one of {', '.join(MUTABILITIES)}")
    effects = entry["effects"]
    if (not isinstance(effects, list) or not effects or len(set(map(str, effects))) != len(effects)
            or not all(item in EFFECT_CLASSES for item in effects)):
        problems.append(f"{where}.effects must be a non-empty unique list of effect classes")
    if not isinstance(entry["recovery_capable"], bool):
        problems.append(f"{where}.recovery_capable must be a bool")
    version = entry["config_schema_version"]
    if not _is_int(version) or version < 1:
        problems.append(f"{where}.config_schema_version must be a positive integer")
    _config_schema_problems(entry["config_schema"], f"{where}.config_schema", problems)
    candidates = entry["candidate_members"]
    if (not isinstance(candidates, list) or not all(item in CANDIDATE_MEMBERS for item in candidates)
            or candidates != sorted(set(candidates))):
        problems.append(f"{where}.candidate_members must be a sorted unique subset of "
                        f"{', '.join(CANDIDATE_MEMBERS)}")


def _predicate_problems(descriptor: dict[str, Any], problems: list[str]) -> None:
    predicates = descriptor["predicates"]
    if not isinstance(predicates, dict):
        problems.append("predicates must be an object")
        return
    for name, entry in predicates.items():
        if _closed(entry, {"support", "reason"}, f"predicates.{name}", problems):
            _reason_problem(entry, f"predicates.{name}", problems)
    for handle in transaction_plan.RESERVED_PREDICATES.values():
        if handle not in predicates:
            problems.append(f"predicates must declare the reserved handle {handle}")
    operations = descriptor["operations"]
    carries_publication = isinstance(operations, dict) and any(
        isinstance(op, dict) and op.get("support") == "supported"
        and op.get("mode") in PUBLICATION_MODES for op in operations.values())
    visible = predicates.get("publication_visible")
    if carries_publication and not (isinstance(visible, dict)
                                    and visible.get("support") == "supported"):
        problems.append("publication_visible must be supported by an adapter that can publish")


def _collector_problems(collector: object, problems: list[str]) -> None:
    if not _closed(collector, {"max_collection_latency_ms", "max_concurrent_collections"},
                   "collector", problems):
        return
    latency = collector["max_collection_latency_ms"]
    cap = transaction_plan.MAX_COLLECTION_LATENCY_MS
    if not _is_int(latency) or not 1 <= latency <= cap:
        problems.append(f"collector.max_collection_latency_ms must be an integer in [1, {cap}]")
    concurrent = collector["max_concurrent_collections"]
    if not _is_int(concurrent) or concurrent < 1:
        problems.append("collector.max_concurrent_collections must be a positive integer")


def descriptor_problems(descriptor: object) -> list[str]:
    """Every schema violation in `descriptor` (#124 D19), `[]` when it is valid."""
    problems: list[str] = []
    if not _closed(descriptor, DESCRIPTOR_MEMBERS, "descriptor", problems):
        return problems
    if not (isinstance(descriptor["name"], str) and ADAPTER_ID_PATTERN.match(descriptor["name"])):
        problems.append("name must match the adapter id pattern")
    if parse_semver(descriptor["adapter_contract_version"]) is None:
        problems.append("adapter_contract_version must be strict SemVer")
    operations = descriptor["operations"]
    if not isinstance(operations, dict) or not operations:
        problems.append("operations must be a non-empty object")
    else:
        for name, entry in operations.items():
            if not (isinstance(name, str) and OPERATION_KEY_PATTERN.match(name)):
                problems.append(f"operations key {name!r} must match the operation pattern")
            _operation_problems(str(name), entry, problems)
    _predicate_problems(descriptor, problems)
    _collector_problems(descriptor["collector"], problems)
    kinds = descriptor["target_kinds"]
    if not isinstance(kinds, dict) or not kinds:
        problems.append("target_kinds must be a non-empty object")
    else:
        for kind, members in kinds.items():
            if (not _is_text(kind) or not isinstance(members, list)
                    or not all(_is_text(m) for m in members) or members != sorted(set(members))
                    or any(m in RESERVED_TARGET_MEMBERS for m in members)):
                problems.append(f"target_kinds.{kind} must be a sorted unique list of member "
                                "names, none of them adapter or kind")
    _sorted_unique_text(descriptor["credential_classes"], "credential_classes", problems)
    _sorted_unique_text(descriptor["executables"], "executables", problems)
    if descriptor["host_capacity"] not in HOST_CAPACITY:
        problems.append(f"host_capacity must be one of {', '.join(HOST_CAPACITY)}")
    return problems


def descriptor_digest(descriptor: dict[str, Any]) -> str:
    """The canonical digest of one descriptor."""
    return telemetry_digest(descriptor)


def build_descriptors(modules: Mapping[str, ModuleType]) -> MappingProxyType:
    """`{name: describe()}` for each adapter module, refusing the first bad descriptor."""
    built: dict[str, dict[str, Any]] = {}
    for key, module in modules.items():
        descriptor = module.describe()
        problems = descriptor_problems(descriptor)
        if problems:
            raise ValueError(f"adapter {key!r} descriptor is invalid: {problems[0]}")
        if descriptor["name"] != key:
            raise ValueError(f"adapter registered as {key!r} describes itself as "
                             f"{descriptor['name']!r}")
        built[key] = descriptor
    return MappingProxyType(built)


def config_problems(schema: dict[str, Any], config: object) -> list[str]:
    """Every way `config` departs from a closed config schema, `[]` when it conforms."""
    if not isinstance(config, dict):
        return ["config must be an object"]
    members, problems = schema["members"], []
    for name in sorted(set(config) - set(members), key=str):
        problems.append(f"config member {name!r} is not declared")
    for name in schema["required"]:
        if name not in config:
            problems.append(f"config member {name!r} is required")
    for name, kind in members.items():
        if name not in config:
            continue
        value = config[name]
        ok = {"string": isinstance(value, str), "integer": _is_int(value),
              "boolean": isinstance(value, bool)}[kind]
        if not ok:
            problems.append(f"config member {name!r} must be a {kind}")
    return problems


def _observation_problems(observation: object, members: frozenset[str], outcomes: tuple[str, ...],
                          where: str) -> list[str]:
    problems: list[str] = []
    if not _closed(observation, members, where, problems):
        return problems
    if not (isinstance(observation["outcome"], str) and observation["outcome"] in outcomes):
        problems.append(f"{where}.outcome must be one of {', '.join(outcomes)}")
    if not _is_text(observation["reason"]):
        problems.append(f"{where}.reason must be a non-empty string")
    references = observation["references"]
    if not isinstance(references, list) or not all(isinstance(item, str) for item in references):
        problems.append(f"{where}.references must be a list of strings")
    at = observation["observed_at"]
    if not _is_int(at) or at < 0:
        problems.append(f"{where}.observed_at must be a non-negative integer of epoch milliseconds")
    for name in ("observed_subject", "facts"):
        if name in members and not isinstance(observation[name], dict):
            problems.append(f"{where}.{name} must be an object")
    return problems


def effect_observation_problems(observation: object) -> list[str]:
    """Every way `observation` departs from the closed effect `Observation`, `[]` when valid."""
    return _observation_problems(observation, EFFECT_OBSERVATION_MEMBERS, EFFECT_OUTCOMES,
                                 "effect observation")


def predicate_observation_problems(observation: object) -> list[str]:
    """Every way `observation` departs from the closed predicate `Observation`, `[]` when valid."""
    return _observation_problems(observation, PREDICATE_OBSERVATION_MEMBERS, PREDICATE_OUTCOMES,
                                 "predicate observation")


def invoke_result_problems(result: object) -> list[str]:
    """Every way `result` departs from the closed `InvokeResult`, `[]` when valid."""
    problems: list[str] = []
    if not _closed(result, INVOKE_RESULT_MEMBERS, "invoke result", problems):
        return problems
    if not (isinstance(result["result"], str) and result["result"] in INVOKE_RESULTS):
        problems.append(f"invoke result.result must be one of {', '.join(INVOKE_RESULTS)}")
    error_class = result["error_class"]
    if result["result"] == "accepted":
        if error_class is not None:
            problems.append("invoke result.error_class must be null when accepted")
    elif not (isinstance(error_class, str) and error_class in transaction_invocation.ERROR_CLASSES):
        problems.append("invoke result.error_class must be one of "
                        + ", ".join(transaction_invocation.ERROR_CLASSES))
    if not _is_text(result["reference"]):
        problems.append("invoke result.reference must be a non-empty string")
    return problems


def reference_text(observation: Mapping[str, Any]) -> str:
    """The canonical reference string for one observation: its reason and typed references."""
    return json.dumps({"reason": observation["reason"], "references": observation["references"]},
                      sort_keys=True, separators=(",", ":"))


def _plain(value: Any) -> Any:
    """A plain deep copy of a frozen value: mappings become dicts, tuples become lists."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


def _validated(problems: list[str], where: str) -> None:
    if problems:
        raise ValueError(f"{where} returned an invalid result: {problems[0]}")


class CoreBinding:
    """The effect and observer the core accepts, over one adapter and one compiled profile."""

    def __init__(self, adapter: ModuleType, expected: dict[str, dict[str, Any]]) -> None:
        self._adapter = adapter
        self._expected = expected

    def _parameters(self, parameters: object, where: str) -> dict[str, Any]:
        """The request parameters as a plain dict, when they are exactly a compiled node's."""
        if not isinstance(parameters, Mapping):
            raise ValueError(f"{where}: parameters must be an object")
        action = parameters.get("action")
        expected = self._expected.get(action) if isinstance(action, str) else None
        if expected is None:
            raise ValueError(f"{where}: action {action!r} is not a node bound to this alias")
        for member in BOUND_MEMBERS:
            if _plain(parameters.get(member)) != expected[member]:
                raise ValueError(f"{where}: {member} differs from the compiled node {action!r}")
        return _plain(parameters)

    def inspect(self, request: Mapping[str, Any]) -> dict[str, str]:
        """The effect's `{outcome, reference}` for one action request."""
        parameters = self._parameters(request["parameters"], "inspect")
        observation = self._adapter.inspect(
            {"kind": "effect", "operation": parameters["operation"], "parameters": parameters})
        _validated(effect_observation_problems(observation), "inspect")
        return {"outcome": observation["outcome"], "reference": reference_text(observation)}

    def invoke(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """The adapter's `invoke` result for one action request, unchanged."""
        parameters = self._parameters(request["parameters"], "invoke")
        result = self._adapter.invoke(
            {"kind": "effect", "operation": parameters["operation"], "parameters": parameters})
        _validated(invoke_result_problems(result), "invoke")
        return result

    def observe(self, request: Mapping[str, Any]) -> dict[str, str]:
        """The `{outcome, reason, reference}` of one derived predicate request."""
        try:
            predicate, nested = request["predicate"], request["parameters"]["parameters"]
        except (KeyError, TypeError):
            raise ValueError("observe: request is not a derived predicate request") from None
        parameters = self._parameters(nested, "observe")
        observation = self._adapter.inspect(
            {"kind": "predicate", "predicate": predicate, "operation": parameters["operation"],
             "parameters": parameters})
        _validated(predicate_observation_problems(observation), "observe")
        return {"outcome": observation["outcome"], "reason": observation["reason"],
                "reference": reference_text(observation)}


def core_binding(adapter: ModuleType, profile: Mapping[str, Any], alias: str) -> CoreBinding:
    """The core-facing binding of `adapter` for adapter `alias` of a compiled profile.

    `ValueError` when the adapter is not the implementation the profile pins (its name or
    descriptor digest differs, D5, D17). Every later request must be exactly one of the
    alias's compiled nodes in `operation`, `target` and `config` (D24).
    """
    identity = profile["adapters"].get(alias)
    if identity is None:
        raise ValueError(f"profile binds no adapter alias {alias!r}")
    descriptor = adapter.describe()
    if (descriptor["name"] != identity["adapter"]
            or descriptor_digest(descriptor) != identity["descriptor_digest"]):
        raise ValueError(f"adapter {descriptor['name']!r} is not the implementation the profile "
                         f"pins for {alias!r}")
    targets = {unit["name"]: unit["parameters"]["target"]
               for unit in profile["proof_declaration"]["units"]}
    expected = {node["id"]: {"operation": node["operation"], "target": _plain(targets[node["id"]]),
                             "config": _plain(node["config"])}
                for node in (*profile["publication"], *profile["activation"])
                if node["adapter"] == alias}
    return CoreBinding(adapter, expected)


REGISTRY = MappingProxyType({"github-forge": forge_adapter})
DESCRIPTORS = build_descriptors(REGISTRY)
