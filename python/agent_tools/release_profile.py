"""The release profile grammar and admissibility compiler (#124 D2 to D5, D7, D17, D19, D20,
D23).

`grammar_violations(release, contract, descriptors)` is the one function that judges the
authored `release` member against spec section 2. It returns the resolver's
`{pointer, message, repair_id}` violations, unsorted, and collects every violation rather
than stopping at the first. It never raises on any JSON value: every input is read through
an `isinstance` guard, and a rule whose input is already reported malformed adds no second
violation for it.

Every object in a profile is closed. The grammar checks shapes, references and adapter
support read from the registered descriptors. It deliberately does not judge the proof
`semantic`/`form`/`predicate` vocabularies, the recovery `posture` and edge `action`
vocabularies, or the presence or range of `observation_deadline_ms` (D2): the core
compilers and admissibility rules own those, so a derived class or a missing deadline is
observable as a compile rejection and never as `invalid_contract`.

Besides the authored `release` the function reads only
`contract["bindings"]["tracker"]`, `contract["bindings"]["vcs"]["default_branch"]` and
`contract["capabilities"]["deploy"]`. It imports `release_adapter` and `agent_platform`.

The compiler half judges a grammar-valid profile. `admissibility_findings` runs the four
`RULES` over every node and reports every finding (unlike the core's first-failure
compilers); rule 4 lowers the profile to a proof and a recovery declaration and reports the
core compilers' reasons verbatim. `compile_profile` returns the deep-frozen
`ResolvedReleaseProfile`, and `bind_candidate` turns it plus one candidate into exactly the
inputs `TransactionStore.create` takes. Every function here is pure: it reads no file,
clock, network or environment.
"""

import copy
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from agent_tools import release_adapter
from agent_tools.agent_platform import parse_semver
from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_plan import MAX_CONVERGENCE_WINDOW_MS, compile_proof
from agent_tools.transaction_recovery_plan import bind_recovery, compile_recovery
from agent_tools.transaction_storage import ProofPlanRejected, RecoveryPlanRejected

ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
GRAMMAR_REPAIR_IDS = (
    "contract.release.invalid",
    "contract.release.reference_unknown",
    "contract.release.adapter_unsupported",
    "contract.release.config_invalid",
    "contract.release.effect_unsupported",
    "contract.release.same_repository",
    "contract.release.deploy_conflict",
)

PROFILE_MEMBERS = frozenset((
    "profile_version", "target", "requirements", "bindings", "publication", "activation",
    "proof", "recovery", "limits"))
BINDING_GROUPS = ("adapters", "targets", "principals", "credentials")
NODE_MEMBERS = frozenset((
    "id", "mode", "adapter", "operation", "target", "principal", "credential", "effect",
    "config_schema_version", "config", "deps"))
NODE_TEXT_MEMBERS = ("adapter", "operation", "target", "principal", "credential")
OBLIGATION_MEMBERS = frozenset((
    "id", "semantic", "form", "predicate", "collector", "required", "deps", "parameters"))
OBLIGATION_TEXT_MEMBERS = ("id", "semantic", "form", "predicate", "collector")
UNIT_MEMBERS = frozenset(("posture", "anchor", "compatibility", "edges"))
EDGE_MEMBERS = frozenset(("action", "operation", "parameters", "residue"))
GITHUB_REPOSITORY_KIND = "github_repository"
BOUNDED_SPEND = "reversible_bounded_spend"
SCHEMA = "release-profile/v1"
RULES = ("observation_deadline", "rolled_back_reachable", "restore_anchor", "core_plans")
RULE_CHECKS = MappingProxyType({
    "observation_deadline": ("repository.release_profile.observation_deadline",
                             "observation_deadline_optional", "release_profile.deadline.require"),
    "rolled_back_reachable": ("repository.release_profile.rolled_back_reachable",
                              "rolled_back_unreachable", "release_profile.compensate.add"),
    "restore_anchor": ("repository.release_profile.restore_anchor", "restore_anchor_destroyed",
                       "release_profile.materialize.add")})
VERSION_PATTERN = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
TITLE_FORBIDDEN = frozenset('"$`\\\0\r\n')
CANDIDATE_KEYS = frozenset(("version", "commit", "title", "notes"))
PHASE_MODES = {"publication": release_adapter.PUBLICATION_MODES,
               "activation": release_adapter.ACTIVATION_MODES}


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_text(value: object) -> bool:
    return isinstance(value, str) and value != ""


def _is_id(value: object) -> bool:
    return isinstance(value, str) and ID_PATTERN.match(value) is not None


def _pointer(*parts: object) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


class _Grammar:
    """One run of the grammar over one `release` value."""

    def __init__(self, contract: object, descriptors: Mapping[str, dict]) -> None:
        self.found: list[dict[str, str]] = []
        self.descriptors = descriptors
        self.contract = contract if isinstance(contract, dict) else {}

    def add(self, pointer: str, message: str, suffix: str) -> None:
        self.found.append({"pointer": pointer, "message": message,
                           "repair_id": "contract.release." + suffix})

    def closed(self, value: object, members: frozenset[str] | set[str], pointer: str,
               what: str) -> bool:
        """True when `value` is an object with exactly `members`; else report why."""
        if not isinstance(value, dict):
            self.add(pointer, f"{what} must be an object", "invalid")
            return False
        missing = sorted(members - set(value))
        unknown = sorted(set(value) - members, key=str)
        if missing:
            self.add(pointer, f"{what} is missing {', '.join(missing)}", "invalid")
        if unknown:
            self.add(pointer, f"{what} has unknown members {', '.join(map(str, unknown))}",
                     "invalid")
        return not missing and not unknown

    def release(self, release: object) -> None:
        if release == "unsupported":
            return
        if not self.closed(release, {"profiles"}, "/release", "release"):
            return
        profiles = release["profiles"]
        if not isinstance(profiles, dict) or not profiles:
            self.add("/release/profiles", "profiles must be a non-empty object", "invalid")
            return
        for profile_id in sorted(profiles, key=str):
            base = _pointer("release", "profiles", profile_id)
            if not _is_id(profile_id):
                self.add(base, "profile id must match " + ID_PATTERN.pattern, "invalid")
            _Profile(self, base, profiles[profile_id]).run()
        deploy = self.contract.get("capabilities")
        deploy = deploy.get("deploy") if isinstance(deploy, dict) else None
        if isinstance(deploy, dict) and "support" in deploy and deploy["support"] != "unsupported":
            self.add("/capabilities/deploy/support",
                     "capabilities.deploy must be unsupported while release profiles exist",
                     "deploy_conflict")


class _Profile:
    """The rules for one profile, in the order G2 to G19."""

    def __init__(self, grammar: _Grammar, base: str, profile: object) -> None:
        self.g, self.base, self.profile = grammar, base, profile
        self.ranges: dict[str, tuple[Any, Any]] = {}
        # A registry stays None until its bindings group is a well-formed object, so a
        # malformed group is reported once and never again as unknown references.
        self.aliases: dict[str, Any] | None = None
        self.targets: dict[str, Any] | None = None
        self.principals: dict[str, Any] | None = None
        self.credentials: dict[str, Any] | None = None
        self.nodes: list[dict[str, Any]] = []

    def at(self, *parts: object) -> str:
        return self.base + _pointer(*parts)

    def run(self) -> None:
        if not self.g.closed(self.profile, PROFILE_MEMBERS, self.base, "profile"):
            if not isinstance(self.profile, dict):
                return
        profile = self.profile
        if "profile_version" in profile and not (
                _is_int(profile["profile_version"]) and profile["profile_version"] >= 1):
            self.g.add(self.at("profile_version"), "profile_version must be a positive integer",
                       "invalid")
        if "target" in profile:
            self.target(profile["target"])
        if "requirements" in profile:
            self.requirements(profile["requirements"])
        if "bindings" in profile:
            self.bindings(profile["bindings"])
        self.references_and_support()
        self.phases()
        self.node_rules()
        if "proof" in profile:
            self.proof(profile["proof"])
        if "recovery" in profile:
            self.recovery(profile["recovery"])
        self.same_repository()
        if "limits" in profile and profile["limits"] != {}:
            self.g.add(self.at("limits"), "limits must be {} in v1", "invalid")

    # G2-G5: target, requirements, bindings

    def target(self, target: object) -> None:
        if not self.g.closed(target, {"environment", "concurrency_keys"}, self.at("target"),
                             "target"):
            return
        if not _is_id(target["environment"]):
            self.g.add(self.at("target", "environment"),
                       "environment must match " + ID_PATTERN.pattern, "invalid")
        keys = target["concurrency_keys"]
        if (not isinstance(keys, list) or not keys or not all(_is_text(k) for k in keys)
                or len(set(keys)) != len(keys)):
            self.g.add(self.at("target", "concurrency_keys"),
                       "concurrency_keys must be a non-empty list of unique non-empty strings",
                       "invalid")

    def requirements(self, requirements: object) -> None:
        if not self.g.closed(requirements, {"adapters"}, self.at("requirements"),
                             "requirements"):
            return
        adapters = requirements["adapters"]
        where = self.at("requirements", "adapters")
        if not isinstance(adapters, dict):
            self.g.add(where, "requirements.adapters must be an object", "invalid")
            return
        for alias, bounds in adapters.items():
            here = self.at("requirements", "adapters", alias)
            if not _is_id(alias):
                self.g.add(here, "adapter alias must match " + ID_PATTERN.pattern, "invalid")
            if not self.g.closed(bounds, {"min_inclusive", "max_exclusive"}, here, "range"):
                continue
            low, high = (parse_semver(bounds[k]) for k in ("min_inclusive", "max_exclusive"))
            if low is None or high is None:
                self.g.add(here, "both bounds must be strict SemVer", "invalid")
            elif not low < high:
                self.g.add(here, "min_inclusive must be less than max_exclusive", "invalid")
            else:
                self.ranges[alias] = (low, high)

    def bindings(self, bindings: object) -> None:
        if not self.g.closed(bindings, set(BINDING_GROUPS), self.at("bindings"), "bindings"):
            if not isinstance(bindings, dict):
                return
        for group in BINDING_GROUPS:
            entries = bindings.get(group)
            if group not in bindings:
                continue
            if not isinstance(entries, dict):
                self.g.add(self.at("bindings", group), f"bindings.{group} must be an object",
                           "invalid")
                continue
            for handle, entry in entries.items():
                here = self.at("bindings", group, handle)
                if not _is_id(handle):
                    self.g.add(here, "handle must match " + ID_PATTERN.pattern, "invalid")
                self.binding_entry(group, here, entry)
            setattr(self, "aliases" if group == "adapters" else group, entries)

    def binding_entry(self, group: str, here: str, entry: object) -> None:
        if group == "adapters":
            members = {"adapter"}
        elif group == "principals":
            members = {"class"}
        elif group == "credentials":
            members = {"adapter", "class"}
        else:
            kind = entry.get("kind") if isinstance(entry, dict) else None
            declared = self.kind_members(entry.get("adapter") if isinstance(entry, dict) else None,
                                         kind)
            members = {"adapter", "kind"} | (set(declared) if declared is not None else set())
            if declared is None:
                # The kind is unknown or unjudgeable: only the common shape is checked here.
                if not isinstance(entry, dict):
                    self.g.add(here, "target must be an object", "invalid")
                    return
                for name in ("adapter", "kind"):
                    if name not in entry:
                        self.g.add(here, f"target is missing {name}", "invalid")
                for name, value in entry.items():
                    if not _is_text(value):
                        self.g.add(here, f"target member {name} must be a non-empty string",
                                   "invalid")
                return
        if not self.g.closed(entry, members, here, group.rstrip("s") or group):
            if not isinstance(entry, dict):
                return
        for name, value in entry.items():
            if name in members and not _is_text(value):
                self.g.add(here, f"member {name} must be a non-empty string", "invalid")

    def descriptor_of(self, alias: object) -> dict[str, Any] | None:
        entry = self.aliases.get(alias) if isinstance(self.aliases, dict) and _is_text(alias) \
            else None
        name = entry.get("adapter") if isinstance(entry, dict) else None
        return self.g.descriptors.get(name) if _is_text(name) else None

    def kind_members(self, alias: object, kind: object) -> list[str] | None:
        descriptor = self.descriptor_of(alias)
        if descriptor is None or not _is_text(kind):
            return None
        members = descriptor["target_kinds"].get(kind)
        return list(members) if members is not None else None

    # G6, G7: alias references and adapter support

    def references_and_support(self) -> None:
        if not isinstance(self.aliases, dict):
            return
        required = set(self.ranges) | self.requirement_aliases()
        for alias in sorted(required - set(self.aliases), key=str):
            self.g.add(self.at("requirements", "adapters", alias),
                       f"requirement {alias} has no bindings.adapters entry", "reference_unknown")
        if self.has_requirements():
            for alias in sorted(set(self.aliases) - required, key=str):
                self.g.add(self.at("bindings", "adapters", alias),
                           f"adapter {alias} has no requirements.adapters entry",
                           "reference_unknown")
        for group in ("targets", "credentials"):
            for handle, entry in self.entries(group):
                alias = entry.get("adapter") if isinstance(entry, dict) else None
                if _is_text(alias) and alias not in self.aliases:
                    self.g.add(self.at("bindings", group, handle, "adapter"),
                               f"{group[:-1]} {handle} names unknown adapter alias {alias}",
                               "reference_unknown")
        for alias, entry in sorted(self.aliases.items(), key=lambda item: str(item[0])):
            name = entry.get("adapter") if isinstance(entry, dict) else None
            if not _is_text(name):
                continue
            descriptor = self.g.descriptors.get(name)
            if descriptor is None:
                self.g.add(self.at("bindings", "adapters", alias, "adapter"),
                           f"adapter {name!r} is not registered", "adapter_unsupported")
                continue
            if alias in self.ranges:
                low, high = self.ranges[alias]
                if not low <= parse_semver(descriptor["adapter_contract_version"]) < high:
                    self.g.add(self.at("requirements", "adapters", alias),
                               f"adapter {name} {descriptor['adapter_contract_version']} is "
                               "outside the required range", "adapter_unsupported")
        for handle, entry in self.entries("targets"):
            descriptor = self.descriptor_of(entry.get("adapter") if isinstance(entry, dict)
                                            else None)
            kind = entry.get("kind") if isinstance(entry, dict) else None
            if descriptor is not None and _is_text(kind) and kind not in descriptor["target_kinds"]:
                self.g.add(self.at("bindings", "targets", handle, "kind"),
                           f"target kind {kind} is not declared by the adapter",
                           "adapter_unsupported")
        for handle, entry in self.entries("credentials"):
            descriptor = self.descriptor_of(entry.get("adapter") if isinstance(entry, dict)
                                            else None)
            klass = entry.get("class") if isinstance(entry, dict) else None
            if (descriptor is not None and _is_text(klass)
                    and klass not in descriptor["credential_classes"]):
                self.g.add(self.at("bindings", "credentials", handle, "class"),
                           f"credential class {klass} is not declared by the adapter",
                           "adapter_unsupported")

    def requirement_aliases(self) -> set[str]:
        requirements = self.profile.get("requirements")
        adapters = requirements.get("adapters") if isinstance(requirements, dict) else None
        return {a for a in adapters if isinstance(a, str)} if isinstance(adapters, dict) \
            else set()

    def has_requirements(self) -> bool:
        requirements = self.profile.get("requirements")
        return isinstance(requirements, dict) and isinstance(requirements.get("adapters"), dict)

    def entries(self, group: str) -> list[tuple[Any, Any]]:
        entries = getattr(self, group)
        return sorted(entries.items(), key=lambda item: str(item[0])) \
            if isinstance(entries, dict) else []

    # G8: phases and node shapes

    def phases(self) -> None:
        profile = self.profile
        if "publication" in profile:
            publication = profile["publication"]
            if self.g.closed(publication, {"actions"}, self.at("publication"), "publication"):
                self.node_list("publication", ("publication", "actions"), publication["actions"])
        if "activation" in profile:
            activation = profile["activation"]
            if activation == "none":
                return
            if not isinstance(activation, dict):
                self.g.add(self.at("activation"), 'activation must be "none" or {units}',
                           "invalid")
            elif self.g.closed(activation, {"units"}, self.at("activation"), "activation"):
                self.node_list("activation", ("activation", "units"), activation["units"])

    def node_list(self, phase: str, path: tuple[str, str], nodes: object) -> None:
        if not isinstance(nodes, list) or not nodes:
            self.g.add(self.at(*path), f"{path[1]} must be a non-empty list", "invalid")
            return
        for index, node in enumerate(nodes):
            self.node_shape(phase, self.at(*path, index), node)

    def node_shape(self, phase: str, here: str, node: object) -> None:
        if not isinstance(node, dict):
            self.g.add(here, "node must be an object", "invalid")
            return
        members = set(NODE_MEMBERS) | ({"observation_deadline_ms"}
                                       if "observation_deadline_ms" in node else set())
        self.g.closed(node, members, here, "node")
        checked: dict[str, Any] = {"phase": phase, "pointer": here, "node": node, "ok": set()}
        ok: set[str] = checked["ok"]

        def judge(name: str, good: bool, message: str) -> None:
            if name not in node:
                return
            if good:
                ok.add(name)
            else:
                self.g.add(here + _pointer(name), message, "invalid")

        judge("id", _is_id(node.get("id")), "id must match " + ID_PATTERN.pattern)
        judge("mode", node.get("mode") in PHASE_MODES[phase],
              f"mode must be one of {', '.join(PHASE_MODES[phase])}")
        for name in NODE_TEXT_MEMBERS:
            judge(name, _is_text(node.get(name)), f"{name} must be a non-empty string")
        judge("effect", node.get("effect") in release_adapter.EFFECT_CLASSES,
              "effect must be one of " + ", ".join(release_adapter.EFFECT_CLASSES))
        judge("config_schema_version", _is_int(node.get("config_schema_version")),
              "config_schema_version must be an integer")
        judge("config", isinstance(node.get("config"), dict), "config must be an object")
        judge("deps", isinstance(node.get("deps"), list)
              and all(_is_text(d) for d in node["deps"]), "deps must be a list of ids")
        judge("observation_deadline_ms", _is_int(node.get("observation_deadline_ms")),
              "observation_deadline_ms must be an integer")
        self.nodes.append(checked)
        # `id` uniqueness across phases
        node_id = node.get("id")
        if "id" in ok and any(other["node"].get("id") == node_id and "id" in other["ok"]
                              for other in self.nodes[:-1]):
            self.g.add(here + "/id", f"node id {node_id} is declared twice", "invalid")

    # G9-G12: node references, effect, adapter support, config

    def node_rules(self) -> None:
        for phase in ("publication", "activation"):
            self.dependency_rules(phase)
        for checked in self.nodes:
            self.reference_rules(checked)
            self.support_rules(checked)

    def dependency_rules(self, phase: str) -> None:
        nodes = [n for n in self.nodes if n["phase"] == phase]
        ids = {n["node"]["id"] for n in nodes if "id" in n["ok"]}
        edges: dict[str, list[str]] = {}
        for checked in nodes:
            node, here = checked["node"], checked["pointer"]
            if "deps" not in checked["ok"]:
                continue
            own = node["id"] if "id" in checked["ok"] else None
            for dep in node["deps"]:
                if dep == own:
                    self.g.add(here + "/deps", f"node {own} depends on itself",
                               "reference_unknown")
                elif dep not in ids:
                    self.g.add(here + "/deps",
                               f"dep {dep} is not a {phase} node id", "reference_unknown")
            if own is not None:
                edges.setdefault(own, [])
                edges[own] += [d for d in node["deps"] if d in ids and d != own]
        for checked in nodes:
            own = checked["node"]["id"] if "id" in checked["ok"] else None
            if own is not None and self.reaches(edges, own, own):
                self.g.add(checked["pointer"] + "/deps",
                           f"node {own} is on a dependency cycle", "reference_unknown")
                break

    @staticmethod
    def reaches(edges: dict[str, list[str]], start: str, goal: str) -> bool:
        seen: set[str] = set()
        stack = list(edges.get(start, []))
        while stack:
            current = stack.pop()
            if current == goal:
                return True
            if current not in seen:
                seen.add(current)
                stack.extend(edges.get(current, []))
        return False

    def reference_rules(self, checked: dict[str, Any]) -> None:
        node, here, ok = checked["node"], checked["pointer"], checked["ok"]
        for member, group in (("target", "targets"), ("principal", "principals"),
                              ("credential", "credentials"), ("adapter", "aliases")):
            registry = getattr(self, group)
            if member in ok and isinstance(registry, dict) and node[member] not in registry:
                self.g.add(here + _pointer(member), f"{member} {node[member]} is not bound",
                           "reference_unknown")
        for member, group in (("target", "targets"), ("credential", "credentials")):
            registry = getattr(self, group)
            entry = registry.get(node[member]) if member in ok and isinstance(registry, dict) \
                else None
            owner = entry.get("adapter") if isinstance(entry, dict) else None
            if _is_text(owner) and "adapter" in ok and owner != node["adapter"]:
                self.g.add(here + _pointer(member),
                           f"{member} {node[member]} belongs to adapter {owner}, not "
                           f"{node['adapter']}", "reference_unknown")

    def support_rules(self, checked: dict[str, Any]) -> None:
        node, here, ok = checked["node"], checked["pointer"], checked["ok"]
        if "effect" in ok and node["effect"] == BOUNDED_SPEND:
            self.g.add(here + "/effect",
                       "reversible_bounded_spend has no spend-grant consumer in v1",
                       "effect_unsupported")
        descriptor = self.descriptor_of(node["adapter"]) if "adapter" in ok else None
        if descriptor is None or "operation" not in ok:
            return
        operation = descriptor["operations"].get(node["operation"])
        if operation is None:
            self.g.add(here + "/operation", f"operation {node['operation']} is not declared",
                       "adapter_unsupported")
            return
        if operation["support"] != "supported":
            self.g.add(here + "/operation",
                       f"operation {node['operation']} is unsupported: {operation['reason']}",
                       "adapter_unsupported")
        if "mode" in ok and node["mode"] != operation["mode"]:
            self.g.add(here + "/mode",
                       f"operation {node['operation']} carries mode {operation['mode']}",
                       "adapter_unsupported")
        if ("effect" in ok and node["effect"] != BOUNDED_SPEND
                and node["effect"] not in operation["effects"]):
            self.g.add(here + "/effect",
                       f"operation {node['operation']} does not declare effect {node['effect']}",
                       "adapter_unsupported")
        if ("config_schema_version" in ok
                and node["config_schema_version"] != operation["config_schema_version"]):
            self.g.add(here + "/config_schema_version",
                       f"operation {node['operation']} expects config_schema_version "
                       f"{operation['config_schema_version']}", "config_invalid")
        if "config" in ok:
            for problem in release_adapter.config_problems(operation["config_schema"],
                                                           node["config"]):
                self.g.add(here + "/config", problem, "config_invalid")

    # G13, G14: proof

    def proof(self, proof: object) -> None:
        here = self.at("proof")
        if not self.g.closed(proof, {"convergence_window_ms", "obligations"}, here, "proof"):
            if not isinstance(proof, dict):
                return
        window = proof.get("convergence_window_ms")
        if "convergence_window_ms" in proof and not (_is_int(window) and window >= 1):
            self.g.add(here + "/convergence_window_ms",
                       "convergence_window_ms must be a positive integer", "invalid")
        obligations = proof.get("obligations")
        if "obligations" not in proof:
            return
        if not isinstance(obligations, list):
            self.g.add(here + "/obligations", "obligations must be a list", "invalid")
            return
        for index, obligation in enumerate(obligations):
            self.obligation(here + _pointer("obligations", index), obligation)

    def obligation(self, here: str, obligation: object) -> None:
        members = set(OBLIGATION_MEMBERS) | (
            {"freshness_ms"} if isinstance(obligation, dict) and "freshness_ms" in obligation
            else set())
        if not self.g.closed(obligation, members, here, "obligation"):
            if not isinstance(obligation, dict):
                return
        for name in OBLIGATION_TEXT_MEMBERS:
            if name in obligation and not _is_text(obligation[name]):
                self.g.add(here + _pointer(name), f"{name} must be a non-empty string",
                           "invalid")
        if "required" in obligation and not isinstance(obligation["required"], bool):
            self.g.add(here + "/required", "required must be a bool", "invalid")
        if "deps" in obligation and not (isinstance(obligation["deps"], list)
                                         and all(_is_text(d) for d in obligation["deps"])):
            self.g.add(here + "/deps", "deps must be a list of non-empty strings", "invalid")
        if "parameters" in obligation and not isinstance(obligation["parameters"], dict):
            self.g.add(here + "/parameters", "parameters must be an object", "invalid")
        if "freshness_ms" in obligation and not _is_int(obligation["freshness_ms"]):
            self.g.add(here + "/freshness_ms", "freshness_ms must be an integer", "invalid")
        collector = obligation.get("collector")
        if (_is_text(collector) and isinstance(self.aliases, dict)
                and collector not in self.aliases):
            self.g.add(here + "/collector", f"collector {collector} is not a bound adapter alias",
                       "reference_unknown")

    # G15, G16: recovery

    def recovery(self, recovery: object) -> None:
        here = self.at("recovery")
        if not self.g.closed(recovery, {"units"}, here, "recovery"):
            return
        units = recovery["units"]
        if not isinstance(units, dict):
            self.g.add(here + "/units", "recovery.units must be an object", "invalid")
            return
        for key in sorted(units, key=str):
            self.unit(here + _pointer("units", key), units[key])
        declared = {n["node"]["id"] for n in self.nodes if "id" in n["ok"]}
        if declared - set(units):
            self.g.add(here + "/units",
                       f"recovery has no entry for {', '.join(sorted(declared - set(units)))}",
                       "reference_unknown")
        for key in sorted(set(units) - declared, key=str):
            self.g.add(here + _pointer("units", key),
                       f"recovery key {key} names no action or unit", "reference_unknown")

    def unit(self, here: str, unit: object) -> None:
        if not self.g.closed(unit, UNIT_MEMBERS, here, "recovery unit"):
            if not isinstance(unit, dict):
                return
        if "posture" in unit and not _is_text(unit["posture"]):
            self.g.add(here + "/posture", "posture must be a non-empty string", "invalid")
        if "anchor" in unit and unit["anchor"] is not None:
            anchor = unit["anchor"]
            if self.g.closed(anchor, {"target", "predicate", "parameters"}, here + "/anchor",
                             "anchor"):
                for name in ("target", "predicate"):
                    if not _is_text(anchor[name]):
                        self.g.add(here + _pointer("anchor", name),
                                   f"{name} must be a non-empty string", "invalid")
                if not isinstance(anchor["parameters"], dict):
                    self.g.add(here + "/anchor/parameters", "parameters must be an object",
                               "invalid")
            if isinstance(anchor, dict) and _is_text(anchor.get("target")) \
                    and isinstance(self.targets, dict) and anchor["target"] not in self.targets:
                self.g.add(here + "/anchor/target",
                           f"anchor target {anchor['target']} is not a bound target",
                           "reference_unknown")
        if "compatibility" in unit and unit["compatibility"] is not None:
            compatibility = unit["compatibility"]
            if self.g.closed(compatibility, {"predicate", "parameters"}, here + "/compatibility",
                             "compatibility"):
                if not _is_text(compatibility["predicate"]):
                    self.g.add(here + "/compatibility/predicate",
                               "predicate must be a non-empty string", "invalid")
                if not isinstance(compatibility["parameters"], dict):
                    self.g.add(here + "/compatibility/parameters",
                               "parameters must be an object", "invalid")
        if "edges" in unit:
            if not isinstance(unit["edges"], list):
                self.g.add(here + "/edges", "edges must be a list", "invalid")
            else:
                for index, edge in enumerate(unit["edges"]):
                    self.edge(here + _pointer("edges", index), edge)

    def edge(self, here: str, edge: object) -> None:
        if not self.g.closed(edge, EDGE_MEMBERS, here, "edge"):
            return
        for name in ("action", "operation"):
            if not _is_text(edge[name]):
                self.g.add(here + _pointer(name), f"{name} must be a non-empty string", "invalid")
        if not isinstance(edge["parameters"], dict):
            self.g.add(here + "/parameters", "parameters must be an object", "invalid")
        if edge["residue"] is not None and not isinstance(edge["residue"], str):
            self.g.add(here + "/residue", "residue must be a string or null", "invalid")

    # G17: same repository

    def same_repository(self) -> None:
        tracker = self.g.contract.get("bindings")
        vcs = tracker.get("vcs") if isinstance(tracker, dict) else None
        tracker = tracker.get("tracker") if isinstance(tracker, dict) else None
        slug = tracker.get("repo_slug") if isinstance(tracker, dict) else None
        tracker_kind = tracker.get("kind") if isinstance(tracker, dict) else None
        branch = vcs.get("default_branch") if isinstance(vcs, dict) else None
        for handle, entry in self.entries("targets"):
            if not isinstance(entry, dict) or entry.get("kind") != GITHUB_REPOSITORY_KIND:
                continue
            here = self.at("bindings", "targets", handle)
            if _is_text(tracker_kind) and tracker_kind != "github":
                self.g.add(here + "/kind", "the tracker is not GitHub", "same_repository")
            if _is_text(slug) and _is_text(entry.get("repository")) \
                    and entry["repository"] != slug:
                self.g.add(here + "/repository",
                           f"repository must equal the tracker repo_slug {slug}",
                           "same_repository")
            if _is_text(branch) and _is_text(entry.get("branch")) and entry["branch"] != branch:
                self.g.add(here + "/branch",
                           f"branch must equal the default branch {branch}", "same_repository")


def grammar_violations(release: object, contract: object,
                       descriptors: Mapping[str, dict] = release_adapter.DESCRIPTORS
                       ) -> list[dict[str, str]]:
    """Every grammar violation in `release`, as `{pointer, message, repair_id}`, unsorted."""
    grammar = _Grammar(contract, descriptors)
    grammar.release(release)
    return grammar.found


# Admissibility compiler (#124 D3, D5, D17, D20, D23)


class ProfileInadmissible(Exception):
    """A grammar-valid profile the compiler refuses; `findings` is never empty."""

    def __init__(self, findings: list[dict[str, str]]) -> None:
        self.findings = tuple(findings)
        super().__init__("; ".join(f"{f['rule']}: {f['reason']}" for f in self.findings))


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def thaw(value: Any) -> Any:
    """A plain deep copy of a frozen value: mappings become dicts, tuples become lists."""
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw(item) for item in value]
    return copy.deepcopy(value)


_BUILD = object()


class ResolvedReleaseProfile(Mapping):
    """The deep-frozen compiled profile; only `compile_profile` builds one (D20)."""

    __slots__ = ("_members",)

    def __init__(self, members: Mapping[str, Any], *, _token: object = None) -> None:
        if _token is not _BUILD:
            raise TypeError("ResolvedReleaseProfile is built by compile_profile only")
        self._members = _freeze(members)

    def __getitem__(self, key: str) -> Any:
        return self._members[key]

    def __iter__(self):
        return iter(self._members)

    def __len__(self) -> int:
        return len(self._members)


def _pointer_base(profile_id: str) -> str:
    return _pointer("release", "profiles", profile_id)


def _authored(profile: Mapping[str, Any]) -> list[tuple[str, int, dict[str, Any]]]:
    """`(phase, authored index, node)` for every publication action, then activation unit."""
    found = [("publication", index, node)
             for index, node in enumerate(profile["publication"]["actions"])]
    if profile["activation"] != "none":
        found += [("activation", index, node)
                  for index, node in enumerate(profile["activation"]["units"])]
    return found


def _descriptor(profile: Mapping[str, Any], descriptors: Mapping[str, dict],
                alias: str) -> dict[str, Any]:
    return descriptors[profile["bindings"]["adapters"][alias]["adapter"]]


def _operation(profile: Mapping[str, Any], descriptors: Mapping[str, dict],
               node: Mapping[str, Any]) -> dict[str, Any]:
    return _descriptor(profile, descriptors, node["adapter"])["operations"][node["operation"]]


def _rule_observation_deadline(profile_id, profile, contract, descriptors):
    base, found = _pointer_base(profile_id), []
    for phase, index, node in _authored(profile):
        here = base + _pointer(phase, "actions" if phase == "publication" else "units", index)
        if "observation_deadline_ms" not in node:
            found.append(_finding("observation_deadline", here, "observation_deadline_optional",
                                  f"node {node['id']} declares no observation_deadline_ms"))
        elif not 1 <= node["observation_deadline_ms"] <= MAX_CONVERGENCE_WINDOW_MS:
            found.append(_finding("observation_deadline", here + "/observation_deadline_ms",
                                  "observation_deadline_out_of_bounds",
                                  f"node {node['id']} observation_deadline_ms "
                                  f"{node['observation_deadline_ms']} is not in "
                                  f"[1, {MAX_CONVERGENCE_WINDOW_MS}]"))
    return found


def _rule_rolled_back_reachable(profile_id, profile, contract, descriptors):
    units = profile["recovery"]["units"]
    if not any(unit["posture"] == "restorable" for unit in units.values()):
        return []
    found = []
    for _, _, node in _authored(profile):
        if _operation(profile, descriptors, node)["mutability"] != "create_if_absent":
            continue
        unit = units[node["id"]]
        if not (unit["posture"] == "compensatable" and unit["edges"]
                and all(edge["action"] == "compensate" and isinstance(edge["residue"], str)
                        and edge["residue"] != "" for edge in unit["edges"])):
            found.append(_finding(
                "rolled_back_reachable",
                _pointer_base(profile_id) + _pointer("recovery", "units", node["id"]),
                "rolled_back_unreachable",
                f"node {node['id']} creates if absent and is not compensatable with "
                "residue-bearing compensate edges beside a restorable unit"))
    return found


def _rule_restore_anchor(profile_id, profile, contract, descriptors):
    in_place = {node["target"] for _, _, node in _authored(profile)
                if _operation(profile, descriptors, node)["mutability"] == "in_place"}
    found = []
    for name, unit in profile["recovery"]["units"].items():
        anchor = unit["anchor"]
        if unit["posture"] == "restorable" and anchor is not None \
                and anchor["target"] in in_place:
            found.append(_finding(
                "restore_anchor",
                _pointer_base(profile_id) + _pointer("recovery", "units", name, "anchor",
                                                     "target"),
                "restore_anchor_destroyed",
                f"anchor target {anchor['target']} is overwritten in place by another node"))
    return found


def _rule_core_plans(profile_id, profile, contract, descriptors):
    proof_declaration, recovery_declaration = lower(profile_id, profile, descriptors)
    base, found = _pointer_base(profile_id), []
    proof = recovery = None
    try:
        recovery = compile_recovery(recovery_declaration, where=base + "/recovery")
    except RecoveryPlanRejected as error:
        found.append(_finding("core_plans", base + "/recovery", "recovery." + error.reason,
                              str(error)))
    try:
        proof = compile_proof(proof_declaration, where=base + "/proof")
    except ProofPlanRejected as error:
        found.append(_finding("core_plans", base + "/proof", "proof." + error.reason,
                              str(error)))
    if proof is not None and recovery is not None:
        try:
            bind_recovery(recovery, proof, where=base + "/recovery")
        except RecoveryPlanRejected as error:
            found.append(_finding("core_plans", base + "/recovery", "recovery." + error.reason,
                                  str(error)))
    return found


_RULE_FUNCTIONS = {"observation_deadline": _rule_observation_deadline,
                   "rolled_back_reachable": _rule_rolled_back_reachable,
                   "restore_anchor": _rule_restore_anchor,
                   "core_plans": _rule_core_plans}


def _finding(rule: str, pointer: str, reason: str, detail: str) -> dict[str, str]:
    return {"rule": rule, "pointer": pointer, "reason": reason, "detail": detail}


def rule_findings(rule: str, profile_id: str, profile: Mapping[str, Any], contract: object,
                  descriptors: Mapping[str, dict] = release_adapter.DESCRIPTORS
                  ) -> list[dict[str, str]]:
    """Every finding of one admissibility rule over a grammar-valid profile."""
    return _RULE_FUNCTIONS[rule](profile_id, profile, contract, descriptors)


def admissibility_findings(profile_id: str, profile: Mapping[str, Any], contract: object,
                           descriptors: Mapping[str, dict] = release_adapter.DESCRIPTORS
                           ) -> list[dict[str, str]]:
    """The four rules' findings in `RULES` order, concatenated."""
    return [finding for rule in RULES
            for finding in rule_findings(rule, profile_id, profile, contract, descriptors)]


def adapter_identities(profile: Mapping[str, Any],
                       descriptors: Mapping[str, dict] = release_adapter.DESCRIPTORS
                       ) -> dict[str, dict[str, str]]:
    """Alias to the adapter name, contract version and descriptor digest the profile binds."""
    identities = {}
    for alias, entry in profile["bindings"]["adapters"].items():
        descriptor = descriptors[entry["adapter"]]
        identities[alias] = {"adapter": entry["adapter"],
                             "adapter_contract_version": descriptor["adapter_contract_version"],
                             "descriptor_digest": release_adapter.descriptor_digest(descriptor)}
    return identities


def profile_digest(profile: Mapping[str, Any],
                   descriptors: Mapping[str, dict] = release_adapter.DESCRIPTORS) -> str:
    return telemetry_digest({"profile": profile,
                             "adapters": adapter_identities(profile, descriptors)})


def ordered_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Kahn's algorithm, always taking the earliest-authored ready node."""
    remaining, placed, ordered = list(nodes), set(), []
    while remaining:
        ready = next((node for node in remaining if all(dep in placed for dep in node["deps"])),
                     None)
        if ready is None:
            raise ValueError("nodes contain a dependency cycle or an unknown dependency")
        remaining.remove(ready)
        placed.add(ready["id"])
        ordered.append(ready)
    return ordered


def _normalized_target(profile: Mapping[str, Any], descriptors: Mapping[str, dict],
                       handle: str) -> dict[str, Any]:
    target = profile["bindings"]["targets"][handle]
    members = _descriptor(profile, descriptors, target["adapter"])["target_kinds"][target["kind"]]
    return {"handle": handle, "kind": target["kind"], **{m: target[m] for m in members}}


def lower(profile_id: str, profile: Mapping[str, Any],
          descriptors: Mapping[str, dict] = release_adapter.DESCRIPTORS
          ) -> tuple[dict[str, Any], dict[str, Any]]:
    """The candidate-independent proof and recovery declarations of a grammar-valid profile."""
    publication = ordered_nodes(list(profile["publication"]["actions"]))
    activation = [] if profile["activation"] == "none" \
        else ordered_nodes(list(profile["activation"]["units"]))
    proof_units, recovery_units = [], []
    for phase, nodes in (("publication", publication), ("activation", activation)):
        for node in nodes:
            parameters = {"action": node["id"], "operation": node["operation"],
                          "target": _normalized_target(profile, descriptors, node["target"])}
            unit = profile["recovery"]["units"][node["id"]]
            anchor = unit["anchor"]
            if anchor is not None:
                anchor = {"predicate": anchor["predicate"],
                          "parameters": {**anchor["parameters"],
                                         "target": _normalized_target(
                                             profile, descriptors, anchor["target"])}}
            proof_units.append({"name": node["id"], "parameters": parameters, "phase": phase,
                                "collector": node["adapter"]})
            recovery_units.append({
                "name": node["id"], "parameters": copy.deepcopy(parameters),
                "effect": node["adapter"], "operation": node["operation"],
                "posture": unit["posture"], "anchor": anchor,
                "compatibility": unit["compatibility"], "edges": unit["edges"]})
    aliases = {alias: descriptors[entry["adapter"]]
               for alias, entry in profile["bindings"]["adapters"].items()}
    collectors = {alias: {"basis": "deterministic",
                          "predicates": sorted(name for name, entry in d["predicates"].items()
                                               if entry["support"] == "supported"),
                          **d["collector"]} for alias, d in aliases.items()}
    effects = {alias: {"operations": sorted(
        name for name, entry in d["operations"].items()
        if entry["support"] == "supported" or entry["recovery_capable"])}
        for alias, d in aliases.items()}
    proof = {"units": proof_units, "obligations": profile["proof"]["obligations"],
             "collectors": collectors,
             "convergence_window_ms": profile["proof"]["convergence_window_ms"]}
    recovery = {"effects": effects, "units": recovery_units}
    return copy.deepcopy(proof), copy.deepcopy(recovery)


def compile_profile(profile_id: str, profile: Mapping[str, Any], contract: object,
                    descriptors: Mapping[str, dict] = release_adapter.DESCRIPTORS
                    ) -> ResolvedReleaseProfile:
    """The frozen compiled profile; `ValueError` for a grammar violation (callers resolve
    first), `ProfileInadmissible` for any admissibility finding."""
    profile = copy.deepcopy(profile)
    release = {"profiles": {profile_id: profile}}
    violations = grammar_violations(release, contract, descriptors)
    if violations:
        raise ValueError(f"profile {profile_id!r} violates the grammar: "
                         f"{violations[0]['pointer']}: {violations[0]['message']}")
    findings = admissibility_findings(profile_id, profile, contract, descriptors)
    if findings:
        raise ProfileInadmissible(findings)
    proof, recovery = lower(profile_id, profile, descriptors)
    nodes = {phase: ordered_nodes(list(profile[phase]["actions" if phase == "publication"
                                                  else "units"]))
             if profile[phase] != "none" else [] for phase in ("publication", "activation")}
    everything = nodes["publication"] + nodes["activation"]
    return ResolvedReleaseProfile({
        "schema": SCHEMA, "profile_id": profile_id,
        "profile_version": profile["profile_version"],
        "digest": profile_digest(profile, descriptors),
        "target": profile["target"],
        "adapters": adapter_identities(profile, descriptors),
        "publication": nodes["publication"], "activation": nodes["activation"],
        "deadlines": {node["id"]: node["observation_deadline_ms"] for node in everything},
        "proof_declaration": proof, "recovery_declaration": recovery,
        "limits": profile["limits"],
        "candidate_members": {node["id"]: _operation(profile, descriptors, node)[
            "candidate_members"] for node in everything}}, _token=_BUILD)


def _candidate_problem(candidate: object) -> str | None:
    if not isinstance(candidate, dict) or set(candidate) != CANDIDATE_KEYS:
        return f"candidate must be an object with exactly {', '.join(sorted(CANDIDATE_KEYS))}"
    version, commit, title = candidate["version"], candidate["commit"], candidate["title"]
    if not isinstance(version, str) or VERSION_PATTERN.fullmatch(version) is None:
        return "candidate version must match vMAJOR.MINOR.PATCH"
    if not isinstance(commit, str) or COMMIT_PATTERN.fullmatch(commit) is None:
        return "candidate commit must be 40 lowercase hex digits"
    if not isinstance(title, str) or title == "" or TITLE_FORBIDDEN & set(title):
        return "candidate title must be a non-empty string free of quotes, $, backtick, " \
               "backslash, NUL, CR and LF"
    if not isinstance(candidate["notes"], str):
        return "candidate notes must be a string"
    return None


def bind_candidate(compiled: ResolvedReleaseProfile, candidate: dict) -> dict[str, Any]:
    """The exact `TransactionStore.create` inputs for one candidate, as plain values (D5)."""
    if not isinstance(compiled, ResolvedReleaseProfile):
        raise TypeError("bind_candidate takes a ResolvedReleaseProfile")
    problem = _candidate_problem(candidate)
    if problem is not None:
        raise ValueError(problem)
    identity = {"version": candidate["version"], "commit": candidate["commit"]}
    configs = {node["id"]: node["config"] for node in
               (*compiled["publication"], *compiled["activation"])}
    proof, recovery = thaw(compiled["proof_declaration"]), thaw(compiled["recovery_declaration"])
    for unit in (*proof["units"], *recovery["units"]):
        name = unit["name"]
        unit["parameters"].update({"candidate": dict(identity), "config": thaw(configs[name])})
        for member in compiled["candidate_members"][name]:
            unit["parameters"][member] = candidate[member]
    return {"proof": proof, "recovery": recovery,
            "concurrency_keys": list(compiled["target"]["concurrency_keys"]),
            "subject": {"profile_id": compiled["profile_id"],
                        "profile_version": compiled["profile_version"],
                        "profile_digest": compiled["digest"], "candidate": identity}}
