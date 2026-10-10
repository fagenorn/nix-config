"""The `release` command: read-only release profile inspection (#124 D5, D15, D17, D18, D23).

`release profile inspect <profile-id>` resolves the project exactly as `resolve-project
resolve` does, so a resolver refusal reaches the caller unchanged, then reports one authored
profile as a `ReleaseProfileInspection`: the subject, the profile, the compiled graphs, the
bindings, the conformance verdicts and one repair per finding. It never calls an adapter,
writes nothing and uses no network; the only child process is `git rev-parse HEAD` in the
project root. An inadmissible profile is still reported in full (#69: diagnosis never
mutates), so the report is built from the authored profile and the admissibility findings,
not from `compile_profile`, which refuses what is inadmissible.
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_tools import release_adapter, release_profile, transaction_plan
from agent_tools.resolve_project import (
    ContractError, add_repo_root, emit_error, emit_json, load_contract,
    require_platform_manifest, resolve, resolves_on_path)

SCHEMA_VERSION = 1
GIT_TIMEOUT_SECONDS = 10
UNAVAILABLE_REPAIR = "capability.release.release_adapter_unavailable"
HANDOFF_RECEIPTS = ("publication_receipt", "activation_not_applicable")


def _pointer(*parts: object) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def source_revision(root: Path) -> str | None:
    """`git rev-parse HEAD` in `root`, or `None` when git cannot answer within the bound."""
    try:
        result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None
    revision = result.stdout.strip()
    return revision if result.returncode == 0 and revision else None


def _profile_error(source: dict, profile_id: str) -> ContractError | None:
    release = source["release"]
    if release == "unsupported":
        return ContractError(
            "release_unsupported", "release.profile.declare",
            [{"pointer": "/release", "message": "the project declares no release profile"}])
    if profile_id not in release["profiles"]:
        return ContractError(
            "profile_unknown", "release.profile.unknown",
            [{"pointer": _pointer("release", "profiles", profile_id),
              "message": f"the project declares no release profile {profile_id}"}])
    return None


def _graphs(profile: dict[str, Any]) -> dict[str, Any]:
    publication = release_profile.ordered_nodes(list(profile["publication"]["actions"]))
    activation = [] if profile["activation"] == "none" \
        else release_profile.ordered_nodes(list(profile["activation"]["units"]))

    def node(entry: dict[str, Any]) -> dict[str, Any]:
        return {name: entry[name]
                for name in ("id", "mode", "adapter", "operation", "target", "deps")}

    proof = []
    for phase, nodes in (("publication", publication), ("activation", activation)):
        derived_class = transaction_plan.PHASE_CLASS[phase]
        proof += [{"id": transaction_plan.derived_id(derived_class, entry["id"]),
                   "derived": True, "class": derived_class,
                   "form": transaction_plan.DERIVED_FORMS[derived_class],
                   "predicate": transaction_plan.RESERVED_PREDICATES[derived_class],
                   "roots": entry["id"]} for entry in nodes]
    proof += [{"id": obligation["id"], "derived": False, "semantic": obligation["semantic"],
               "form": obligation["form"], "predicate": obligation["predicate"],
               "collector": obligation["collector"], "required": obligation["required"],
               "deps": obligation["deps"]} for obligation in profile["proof"]["obligations"]]
    units = profile["recovery"]["units"]
    receipt = HANDOFF_RECEIPTS[0] if activation else HANDOFF_RECEIPTS[1]
    return {"phases": ["publication", "activation"],
            "publication": [node(entry) for entry in publication],
            "activation": [node(entry) for entry in activation],
            "handoffs": [{"from": "publication", "to": "activation", "receipt": receipt}],
            "proof": proof,
            "recovery": [{"unit": entry["id"], "posture": units[entry["id"]]["posture"],
                          "anchor": units[entry["id"]]["anchor"],
                          "compatibility": units[entry["id"]]["compatibility"],
                          "edges": units[entry["id"]]["edges"]}
                         for entry in publication + activation]}


def _bindings(profile: dict[str, Any], nodes: list[dict[str, Any]]) -> dict[str, Any]:
    identities = release_profile.adapter_identities(profile)
    adapters = {alias: {**identity,
                        "config": {entry["id"]: entry["config"]
                                   for entry in nodes if entry["adapter"] == alias}}
                for alias, identity in identities.items()}
    groups = profile["bindings"]
    return {"adapters": adapters, "targets": groups["targets"],
            "principals": groups["principals"], "credentials": groups["credentials"]}


def _conformance(root: Path, profile: dict[str, Any], nodes: list[dict[str, Any]],
                 findings: list[dict[str, str]]) -> dict[str, Any]:
    adapters = {}
    for alias, entry in profile["bindings"]["adapters"].items():
        descriptor = release_adapter.DESCRIPTORS[entry["adapter"]]
        operations = sorted({node["operation"] for node in nodes if node["adapter"] == alias})
        executables = {name: resolves_on_path(name, root)
                       for name in descriptor["executables"]}
        adapters[alias] = {
            "modes": {name: descriptor["operations"][name]["support"] for name in operations},
            "predicates": {name: predicate["support"]
                           for name, predicate in descriptor["predicates"].items()},
            "executables": executables}
    checks = {}
    for rule, (check_id, reason, _) in release_profile.RULE_CHECKS.items():
        failed = any(finding["rule"] == rule for finding in findings)
        checks[check_id] = {"status": "failed" if failed else "passed",
                            "reason_code": reason if failed else None}
    return {"adapters": adapters, "checks": checks, "findings": findings}


def _repairs(profile_id: str, findings: list[dict[str, str]],
             conformance: dict[str, Any]) -> list[dict[str, str]]:
    repairs = [{"repair_id": release_profile.RULE_CHECKS[finding["rule"]][2]
                if finding["rule"] in release_profile.RULE_CHECKS
                else "release_profile." + finding["reason"],
                "pointer": finding["pointer"], "safety_class": "user_action"}
               for finding in findings]
    base = _pointer("release", "profiles", profile_id)
    for alias, adapter in conformance["adapters"].items():
        repairs += [{"repair_id": UNAVAILABLE_REPAIR,
                     "pointer": base + _pointer("bindings", "adapters", alias),
                     "safety_class": "user_action"}
                    for found in adapter["executables"].values() if not found]
    return repairs


def inspect_profile(root: Path, source: dict, profile_id: str, manifest: dict,
                    manifest_path: Path) -> dict[str, Any]:
    """The `ReleaseProfileInspection` of one authored profile of a resolved project."""
    error = _profile_error(source, profile_id)
    if error is not None:
        raise error
    profile = source["release"]["profiles"][profile_id]
    graphs = _graphs(profile)
    nodes = release_profile.ordered_nodes(
        list(profile["publication"]["actions"])
        + ([] if profile["activation"] == "none" else list(profile["activation"]["units"])))
    findings = release_profile.admissibility_findings(profile_id, profile, source)
    conformance = _conformance(root, profile, nodes, findings)
    return {
        "schema_version": SCHEMA_VERSION,
        "subject": {"project_id": source["project"]["id"], "project_root": str(root),
                    "source_revision": source_revision(root),
                    "platform": {"manifest_path": str(manifest_path),
                                 "platform_version": manifest["platform_version"]}},
        "profile": {"id": profile_id, "version": profile["profile_version"],
                    "digest": release_profile.profile_digest(profile),
                    "target": profile["target"],
                    "deadlines": {entry["id"]: entry.get("observation_deadline_ms")
                                  for entry in nodes},
                    "limits": profile["limits"], "admissible": not findings},
        "graphs": graphs,
        "bindings": _bindings(profile, nodes),
        "conformance": conformance,
        "repairs": _repairs(profile_id, findings, conformance)}


def command_profile_inspect(args: argparse.Namespace) -> int:
    snapshot = resolve(args.repo_root)
    manifest, manifest_path = require_platform_manifest()
    root = Path(snapshot["project"]["root"])
    source = load_contract(root)
    return emit_json(inspect_profile(root, source, args.profile_id, manifest, manifest_path))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="release", description="Inspect the project's release profiles, read-only.")
    areas = parser.add_subparsers(dest="area", required=True)
    profile = areas.add_parser("profile", help="release profile inspection")
    actions = profile.add_subparsers(dest="action", required=True)
    inspect = actions.add_parser(
        "inspect", help="print the ReleaseProfileInspection of one profile on stdout")
    inspect.add_argument("profile_id", help="the release profile id")
    add_repo_root(inspect)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return command_profile_inspect(args)
    except ContractError as error:
        return emit_error(error.code, error.repair_id, error.violations, error.reason_code)
    except Exception:
        return emit_error("resolver_failure", "resolver.internal",
                          [{"pointer": "", "message": "the resolver failed unexpectedly"}])


if __name__ == "__main__":
    sys.exit(main())
