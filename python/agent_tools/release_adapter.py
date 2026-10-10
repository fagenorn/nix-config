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
"""

import re
from collections.abc import Mapping
from types import MappingProxyType, ModuleType
from typing import Any

from agent_tools import forge_adapter, transaction_plan
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


REGISTRY = MappingProxyType({"github-forge": forge_adapter})
DESCRIPTORS = build_descriptors(REGISTRY)
