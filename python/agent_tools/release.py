"""The `release` command: release inspection (#124 D5, D15, D17, D18, D23) and the release
transaction (#128 spec §1, §4–§7; D3, D18, D19).

`release profile inspect <profile-id>` resolves the project exactly as `resolve-project
resolve` does, so a resolver refusal reaches the caller unchanged, then reports one authored
profile as a `ReleaseProfileInspection`: the subject, the profile, the compiled graphs, the
bindings, the conformance verdicts and one repair per finding. It never calls an adapter,
writes nothing and uses no network; the only child process is `git rev-parse HEAD` in the
project root. An inadmissible profile is still reported in full (#69: diagnosis never
mutates), so the report is built from the authored profile and the admissibility findings,
not from `compile_profile`, which refuses what is inadmissible. A publication-free profile
(one that authors no publication actions) is reported with empty graphs and no handoff, and
the command still exits 0.

`release adapter inspect <adapter> <operation> --parameters <json>` is the one project-free
adapter read (D15): it resolves no project, calls the registered adapter's `inspect` for one
effect and prints the observation.

`release transaction status|preview|run|abandon` drives one release through the transaction
core (the contract is the docstring of `release_driver`). Adapter `invoke` is reachable
only through `release transaction run`, which drives the core (§9). The command resolves the
project with `release` required, so a resolver refusal reaches the caller unchanged, and
prints one document; a driver `Refusal` prints `{"error": ...}` and exits 3.

`release profile inspect <profile-id> [--repo-root PATH]` (#124 D15, D18) exits 0 whether the
profile is admissible or not, because diagnosis never mutates (#69), and prints one compact
sorted-key JSON `ReleaseProfileInspection`. A publication-free profile is reported with empty
`publication` and `activation` graphs and an empty `handoffs` list (#368 D7). The child process
is bounded to 10 seconds, and a failure of `git rev-parse HEAD` reports `source_revision: null`.
`"unsupported"` is the refusal `release_unsupported` (repair `release.profile.declare`) and an
unknown id is `profile_unknown` (repair `release.profile.unknown`), both exit 2. The report has
exactly seven members:

- `schema_version`;
- `subject`: project, root, revision and installed platform;
- `profile`: id, version, digest, target, per-node deadlines, limits and `admissible`;
- `graphs`: the ordered publication and activation nodes, the handoff, the derived and
  authored proof obligations and the recovery units;
- `bindings`: adapter identities with each node's config, targets, principals and credential
  handles and classes, never credential material;
- `conformance`: per-adapter operation, predicate and executable support, the three linted
  checks and every finding;
- `repairs`: one per finding, then one per missing executable, all `user_action`.

The transaction verbs each take `[--profile P] [--repo-root R]`; `preview` and `run` also take
`[--commit C --version V --title T --notes-file F]`, and `run` takes `--confirm TOKEN` once per
token. The four candidate flags are all absent (no candidate) or all present: some absent
refuses `candidate_required` naming them, and a notes file that cannot be read as UTF-8 refuses
`candidate_invalid`. The candidate is `{version, commit, title, notes}`. A driver refusal prints
`{"error": {"code", "repair_id", "detail"}}` (`repair_id` null where none is named) and exits 3;
a resolver refusal is untouched with exit 2, and any other failure keeps the `release`
command's `resolver_failure` envelope (D18).
"""

import argparse
import json
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

from agent_tools import release_adapter, release_profile, transaction_plan
from agent_tools.release_driver import Driver, Project, Refusal, main_checkout, require_cwd
from agent_tools.project_contract.resolve_project import (
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
    publication, activation = (
        release_profile.ordered_nodes(release_profile.phase_nodes(profile, phase))
        for phase in release_profile.PHASES)

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
            "handoffs": [{"from": "publication", "to": "activation", "receipt": receipt}]
            if publication else [],
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
        release_profile.phase_nodes(profile, "publication")
        + release_profile.phase_nodes(profile, "activation"))
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


def _adapter_error(code: str, repair_id: str, pointer: str, message: str) -> ContractError:
    return ContractError(code, repair_id, [{"pointer": pointer, "message": message}])


def command_adapter_inspect(args: argparse.Namespace) -> int:
    adapter = release_adapter.REGISTRY.get(args.adapter)
    if adapter is None:
        raise _adapter_error("adapter_unknown", "release.adapter.unknown", "/adapter",
                             f"no adapter is registered as {args.adapter}")
    operation = release_adapter.DESCRIPTORS[args.adapter]["operations"].get(args.operation)
    if operation is None or operation["inspect"] != "supported":
        raise _adapter_error("operation_unknown", "release.adapter.operation_unknown", "/operation",
                             f"{args.adapter} cannot inspect an operation {args.operation}")
    try:
        parameters = json.loads(args.parameters)
    except ValueError:
        parameters = None
    if not isinstance(parameters, dict):
        raise _adapter_error("parameters_invalid", "release.adapter.parameters_invalid",
                             "/parameters", "--parameters must be a JSON object")
    return emit_json(adapter.inspect(
        {"kind": "effect", "operation": args.operation, "parameters": parameters}))


CANDIDATE_FLAGS = ("commit", "version", "title", "notes_file")
REFUSAL_EXIT = 3


def _candidate(args: argparse.Namespace) -> dict[str, str] | None:
    """The candidate the four flags name: `None` when none is given, refused when only some are."""
    given = {name: getattr(args, name) for name in CANDIDATE_FLAGS}
    if all(value is None for value in given.values()):
        return None
    missing = ["--" + name.replace("_", "-") for name, value in given.items() if value is None]
    if missing:
        raise Refusal("candidate_required", "a candidate needs " + ", ".join(missing))
    try:
        notes = Path(args.notes_file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise Refusal("candidate_invalid", f"cannot read {args.notes_file}: {error}") from error
    return {"version": args.version, "commit": args.commit, "title": args.title,
            "notes": notes}


def _project(snapshot: dict[str, Any], root: Path) -> Project:
    vcs = snapshot["bindings"]["vcs"]
    return Project(project_id=snapshot["project"]["id"], root=root, common_dir=main_checkout(root),
                   integration_branch=vcs["integration_branch"],
                   default_branch=vcs["default_branch"],
                   contract=load_contract(root))


def command_transaction(args: argparse.Namespace) -> int:
    """`release transaction <verb>`: resolve, gate, then hand one verb to the driver (D18, D19)."""
    snapshot = resolve(args.repo_root, ["release"])
    root = Path(snapshot["project"]["root"])
    project = _project(snapshot, root)
    if args.action in ("run", "abandon"):
        require_cwd(root, Path.cwd())
    driver = Driver(project, profile_id=args.profile)
    if args.action == "status":
        return emit_json(driver.status())
    if args.action == "abandon":
        return emit_json(driver.abandon())
    candidate = _candidate(args)
    if args.action == "run":
        return emit_json(driver.run(candidate, args.confirm))
    document = driver.preview(candidate)
    emit_json(document)
    return 0 if document["runnable"] else REFUSAL_EXIT


def _transaction_parser(areas: Any) -> None:
    transaction = areas.add_parser("transaction", help="drive one release through the core")
    verbs = transaction.add_subparsers(dest="action", required=True)
    for name, help_text in (("status", "print the release in flight or the last one"),
                            ("preview", "print the plan and the confirmations it needs"),
                            ("run", "drive the release as far as it can go"),
                            ("abandon", "end the release in flight")):
        verb = verbs.add_parser(name, help=help_text)
        verb.add_argument("--profile", help="the release profile id; optional when only one "
                                            "profile publishes")
        if name in ("preview", "run"):
            verb.add_argument("--commit", help="the commit to release, 40 lowercase hex characters")
            verb.add_argument("--version", help="the version, which is the tag")
            verb.add_argument("--title", help="the release title")
            verb.add_argument("--notes-file", help="a UTF-8 file holding the release notes")
        if name == "run":
            verb.add_argument("--confirm", action="append", default=[], metavar="TOKEN",
                              help="a confirmation token from preview; repeat per token")
        add_repo_root(verb)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="release",
        description="Release inspection: profiles and adapters. Adapter "
                    "invoke is reachable only through `release transaction run`, which "
                    "drives the transaction core.")
    areas = parser.add_subparsers(dest="area", required=True)
    profile = areas.add_parser("profile", help="release profile inspection")
    actions = profile.add_subparsers(dest="action", required=True)
    inspect = actions.add_parser(
        "inspect", help="print the ReleaseProfileInspection of one profile on stdout")
    inspect.add_argument("profile_id", help="the release profile id")
    add_repo_root(inspect)
    adapter = areas.add_parser("adapter", help="adapter inspection")
    adapter_actions = adapter.add_subparsers(dest="action", required=True)
    adapter_inspect = adapter_actions.add_parser(
        "inspect", help="print the effect observation of one adapter operation on stdout")
    adapter_inspect.add_argument("adapter", help="the registered adapter name")
    adapter_inspect.add_argument("operation", help="the operation to inspect")
    adapter_inspect.add_argument("--parameters", required=True,
                                 help="the operation parameters, a JSON object")
    _transaction_parser(areas)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return {"profile": command_profile_inspect, "adapter": command_adapter_inspect,
                "transaction": command_transaction}[args.area](args)
    except Refusal as refusal:
        emit_json({"error": refusal.as_object()})
        return REFUSAL_EXIT
    except ContractError as error:
        return emit_error(error.code, error.repair_id, error.violations, error.reason_code)
    except Exception:
        # The envelope below is the contract; the original error goes to stderr first so a
        # failure after `run` has written is never reported as only a resolver problem.
        traceback.print_exc()
        return emit_error("resolver_failure", "resolver.internal",
                          [{"pointer": "", "message": "the resolver failed unexpectedly"}])


if __name__ == "__main__":
    sys.exit(main())
