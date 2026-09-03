#!/usr/bin/env python3
"""Plan this repository's adoption into the shared agent platform.

`plan` inspects a target checkout inside a bounded, read-only boundary,
classifies every candidate it finds under one closed action set, routes the
repository to exactly one of five closed outcomes, and emits the seven-member
adoption plan document: `schema_version`, `plan`, `evidence`, `decisions`,
`changes`, `verification`, `handoff` (R4.3).

The document is content-addressed. `plan_id` is the SHA-256 of canonical JSON
over exactly `{adopt_schema_version, project_id, base_revision, platform,
evidence, decisions.answered}` (D15), so two checkouts of one revision on one
platform produce one identifier and any change to a source byte, the base
revision or a platform input produces another. The absolute checkout path is
deliberately outside that source and appears only in `handoff`.

Nothing here mutates the target. `plan` runs `git` and the resolver as child
processes, reads tracked object ids rather than tracked bytes, and writes only
under `~/.agents/state/` (R4.1, D14).

The resolver is consumed **only** as a subprocess at the absolute path
`$HOME/.agents/bin/resolve-project`, never imported (D26): contract validation
has one home, and a stale generation earlier on `PATH` cannot answer. The
shared platform library `agent_platform` is imported directly — it is the one
home for the manifest loader, the state root and the atomic writer (D37).

A structural refusal prints exactly one JSON object carrying an `error` member
on stdout and exits 2 (D12). An argparse usage error also exits 2 but prints no
JSON, which is how a caller tells the two apart (D16).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

# The shared platform library, bound by `bootstrap_platform_library` before any
# subcommand runs, exactly as `resolve-project.py` binds it. It is deliberately
# not imported at module scope: an absent library is a platform installation
# defect and has to reach the caller as the D12 error object on stdout, not as
# an import traceback on stderr.
agent_platform = None

PLATFORM_LIBRARY_MEMBERS = (
    "PlatformManifestError",
    "ensure_directory",
    "load_manifest",
    "parse_semver",
    "read_registry",
    "state_root",
    "write_atomically",
)
PLATFORM_LIBRARY_REPAIR_ID = "platform.library.missing"


def bootstrap_platform_library() -> bool:
    """Bind the shared library from its one installed path, or report failure."""
    global agent_platform
    home = os.environ.get("HOME")
    if not home:
        return False
    sys.path.insert(0, str(Path(home) / ".agents" / "lib" / "python"))
    try:
        import agent_platform as loaded
    except Exception:
        return False
    if (not getattr(loaded, "__file__", None)
            or any(not hasattr(loaded, name)
                   for name in PLATFORM_LIBRARY_MEMBERS)):
        return False
    agent_platform = loaded
    return True

# The two adoption libraries, bound by `bootstrap_adopt_libraries` before any
# subcommand runs. They install beside `agent_platform.py` and are separately
# installed files, so an older library can pair with a newer binary; naming
# every member this script reads is what makes that pairing refuse as
# `adopt.library.missing` through the D12 error object rather than surface as
# an `AttributeError` swallowed into `adopt.internal`.
adopt_inspection = None
adopt_planning = None

ADOPT_INSPECTION_MEMBERS = (
    "ADOPT_SCHEMA_VERSION",
    "AdoptError",
    "COMMIT_GATES",
    "CONTRACT_FILENAME",
    "Inventory",
    "METADATA_ONLY_IGNORED",
    "NOTES",
    "OUTCOMES",
    "PLAN_STATES",
    "READY_GATES",
    "TARGETED_IGNORED",
    "canonical_json",
    "classify_inventory",
    "evidence_entry",
    "gate_entry",
    "head_revision",
    "outcome_is_appliable",
    "overlap_targets",
    "read_bytes_bounded",
    "refuse",
    "registered_worktrees",
    "require_repository",
    "targeted_ignored",
    "tracked_inventory",
    "untracked_under",
)

ADOPT_PLANNING_MEMBERS = (
    "adoption_records",
    "blockers_for",
    "bookkeeping_operations",
    "build_operations",
    "compute_plan_id",
    "derive_identity",
    "evaluate_ready_gates",
    "next_command_for",
    "route_outcome",
)
ADOPT_LIBRARY_REPAIR_ID = "adopt.library.missing"


def bootstrap_adopt_libraries() -> bool:
    """Bind both adoption libraries, or report failure.

    `bootstrap_platform_library` has already put the one installed library
    directory on `sys.path`, so this adds no second lookup path and no
    fallback ladder: the modules are found exactly where Nix installs them or
    they are not found at all.
    """
    global adopt_inspection, adopt_planning
    try:
        import adopt_inspection as inspection
        import adopt_planning as planning
    except Exception:
        return False
    for module, members in ((inspection, ADOPT_INSPECTION_MEMBERS),
                            (planning, ADOPT_PLANNING_MEMBERS)):
        if (not getattr(module, "__file__", None)
                or any(not hasattr(module, name) for name in members)):
            return False
    adopt_inspection = inspection
    adopt_planning = planning
    return True


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def emit_json(value: object) -> int:
    json.dump(value, sys.stdout, sort_keys=True, separators=(",", ":"),
              allow_nan=False)
    sys.stdout.write("\n")
    return 0


def emit_error(code: str, repair_id: str, violations: list[dict]) -> int:
    """The one place an error object reaches stdout (D12)."""
    ordered = sorted(violations, key=lambda item: item["pointer"])
    emit_json({"error": {"code": code, "repair_id": repair_id,
                         "violations": ordered}})
    return 2

# --------------------------------------------------------------------------
# The resolver, as a child process
# --------------------------------------------------------------------------


def resolver_path() -> Path:
    """The one absolute path the resolver is consumed at (D26).

    No `PATH` search: a stale generation earlier on `PATH` must never be able
    to answer a contract question on this platform's behalf.
    """
    return Path(os.environ["HOME"]) / ".agents" / "bin" / "resolve-project"


def run_resolver(root: Path, *args: str) -> tuple[int, object]:
    """The resolver's exit code and parsed JSON, or a refusal.

    Exit 0 carries the documented success document and exit 2 the documented
    D12 error object; any other exit, or output that will not parse, is an
    adoption failure rather than a guess.
    """
    binary = resolver_path()
    try:
        proc = subprocess.run([str(binary), *args, "--repo-root", str(root)],
                              capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.resolver.unavailable", "",
            "the installed resolver could not be started") from None
    if proc.returncode not in (0, 2):
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.resolver.unexpected_exit", "",
            "the resolver exited outside its documented codes")
    try:
        payload = json.loads(proc.stdout)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.resolver.unparseable", "",
            "the resolver did not print parseable JSON") from None
    return proc.returncode, payload


def resolver_error_code(payload: object) -> str | None:
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        code = payload["error"].get("code")
        return code if isinstance(code, str) else None
    return None


def resolver_repair_id(payload: object) -> str | None:
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        repair = payload["error"].get("repair_id")
        return repair if isinstance(repair, str) else None
    return None


def resolver_violation_pointers(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    error = payload.get("error")
    if not isinstance(error, dict) or not isinstance(error.get("violations"),
                                                     list):
        return []
    return [v.get("pointer") for v in error["violations"]
            if isinstance(v, dict) and isinstance(v.get("pointer"), str)]

# --------------------------------------------------------------------------
# Inspection
#
# The whole boundary of R4.2, and nothing wider: tracked object ids, a closed
# list of targeted ignored paths, two metadata-only trees, registered worktree
# names, and untracked files overlapping an inspected source or a planned
# destination. The queries live in `adopt_inspection`; this is the one entry
# point that composes them into an inventory.
# --------------------------------------------------------------------------


def inspect_repository(root: Path) -> adopt_inspection.Inventory:
    """The single inspection entry point (R4.2).

    Untracked overlap is deliberately not gathered here: its target list is a
    function of the classification this inventory feeds, so it is collected
    once the candidate groups and their destinations are known.
    """
    metadata: dict[str, int] = {}
    for target in adopt_inspection.METADATA_ONLY_IGNORED:
        found = adopt_inspection.targeted_ignored(root, (target,))
        if found:
            metadata[target] = len(found)
    return adopt_inspection.Inventory(
        tracked=adopt_inspection.tracked_inventory(root),
        ignored=adopt_inspection.targeted_ignored(
            root, adopt_inspection.TARGETED_IGNORED),
        metadata=metadata,
        worktrees=adopt_inspection.registered_worktrees(root),
        base_revision=adopt_inspection.head_revision(root),
    )

# --------------------------------------------------------------------------
# The plan document
# --------------------------------------------------------------------------


def command_plan(args: argparse.Namespace) -> int:
    manifest = require_manifest()
    root = adopt_inspection.require_repository(args.repo_root)

    inventory = inspect_repository(root)
    found = adopt_inspection.classify_inventory(root, inventory)
    untracked = adopt_inspection.untracked_under(
        root, adopt_inspection.overlap_targets(found))
    for path in untracked:
        found.entries.append(adopt_inspection.evidence_entry(
            path, "untracked-explicit-paths", "untracked-overlap",
            "retain-product", None, 1, None,
            adopt_inspection.NOTES["untracked"]))
    evidence = sorted(found.entries,
                      key=lambda entry: (entry["path"], entry["provenance"]))

    contract_source = load_contract_source(root)
    exit_code, payload = run_resolver(root, "resolve")
    contract_resolves = exit_code == 0
    repair_id = None if contract_resolves else resolver_repair_id(payload)
    projections_drift = (
        not contract_resolves
        and resolver_error_code(payload) == "invalid_projection")
    # What the planned amendment can still put right, which is exactly what it
    # writes. `amended_contract` *adds* `platform` when the member is absent
    # and never rewrites an authored one, so only the absent case may forgive a
    # `/platform` violation: an interval the project declared is its own policy
    # and an out-of-range or malformed one is a repair, not something adoption
    # silently overwrites. Forgiving it unconditionally would let a plan reach
    # `ready` whose applied result the resolver still refuses. A drifted
    # projection is separately repaired by the regeneration operations this
    # plan already carries.
    amendment_writes_platform = (contract_source is not None
                                 and "platform" not in contract_source)
    unfixable = [] if projections_drift else [
        pointer for pointer in resolver_violation_pointers(payload)
        if not (amendment_writes_platform
                and pointer.startswith("/platform"))]

    contract_id = None
    if contract_resolves and isinstance(payload, dict):
        project = payload.get("project")
        if isinstance(project, dict) and isinstance(project.get("id"), str):
            contract_id = project["id"]
    project_id, recommended, open_questions = adopt_planning.derive_identity(
        root, contract_id)
    decisions = {"recommended": recommended, "answered": [],
                 "open": open_questions}

    platform_block = {
        "platform_version": manifest["platform_version"],
        "project_schema_versions": list(manifest["project_schema_versions"]),
        "resolved_schema_version": manifest["resolved_schema_version"],
    }
    plan_id = adopt_planning.compute_plan_id(
        project_id, inventory.base_revision, platform_block, evidence,
        decisions["answered"])

    ready_gates = adopt_planning.evaluate_ready_gates(
        root, found, contract_source, contract_resolves, unfixable, untracked,
        decisions)
    head, tail = adopt_planning.build_operations(
        root, found, manifest, contract_source, plan_id)

    agent_surface = any(
        entry["lifecycle_class"] != "runtime-residue"
        and entry["provenance"] != "untracked-explicit-paths"
        for entry in evidence)
    # What counts as work left to do (routing rules 5 and 6). A projection
    # regeneration is an idempotent safety re-run that a conformant checkout
    # would perform to no effect, so counting it as work would make `no_change`
    # unreachable; the two adoption records are excluded for the same reason,
    # by being built only after this decision.
    substantive = [op for op in head + tail
                   if op["op"] != "regenerate-projection"]
    pending_work = bool(substantive) or projections_drift or any(
        entry["action"] == "needs-decision" for entry in evidence)

    outcome, forward_migration = adopt_planning.route_outcome(
        manifest, contract_source, contract_resolves, agent_surface,
        pending_work)

    if adopt_inspection.outcome_is_appliable(outcome):
        state = "ready" if all(gate["status"] == "passed"
                               for gate in ready_gates) else "draft"
        blockers = adopt_planning.blockers_for(ready_gates)
        records = adopt_planning.adoption_records(plan_id)
        changes = head + adopt_planning.bookkeeping_operations(
            found, plan_id, outcome, inventory.base_revision, platform_block,
            decisions, ready_gates) + tail
        evidence_record = records["evidence_record"]
        migration_map = records["migration_map"]
    else:
        state = "not_applicable"
        blockers = []
        changes = []
        ready_gates = [adopt_inspection.gate_entry(gate, "not_run", None)
                       for gate in adopt_inspection.READY_GATES]
        evidence_record = None
        migration_map = None

    # Both values are produced by an exhaustive dispatch above, so this is
    # defence in depth: a member added to either closed tuple without a home
    # in the routing or state logic crashes here rather than reaching a caller.
    if outcome not in adopt_inspection.OUTCOMES:
        raise ValueError(f"unknown adoption outcome: {outcome!r}")
    if state not in adopt_inspection.PLAN_STATES:
        raise ValueError(f"unknown plan state: {state!r}")

    plan_path = store_plan_path(plan_id)
    document = {
        "schema_version": adopt_inspection.ADOPT_SCHEMA_VERSION,
        "plan": {
            "state": state,
            "outcome": outcome,
            "project_id": project_id,
            "base_revision": inventory.base_revision,
            "platform": platform_block,
            "input_digest": plan_id,
            "plan_id": plan_id,
            "blockers": blockers,
        },
        "evidence": evidence,
        "decisions": decisions,
        "changes": changes,
        "verification": {
            "ready_gates": ready_gates,
            "commit_gates": [adopt_inspection.gate_entry(gate, "not_run", None)
                             for gate in adopt_inspection.COMMIT_GATES],
        },
        "handoff": {
            "state": state,
            "repo_root": str(root),
            "plan_path": str(plan_path),
            "next_command": adopt_planning.next_command_for(
                state, outcome, root, plan_id, forward_migration, repair_id),
            "evidence_record": evidence_record,
            "migration_map": migration_map,
        },
    }

    agent_platform.ensure_directory(plan_path.parent)
    agent_platform.write_atomically(
        plan_path, adopt_inspection.canonical_json(document) + b"\n")
    if args.format == "human":
        return emit_human(document)
    return emit_json(document)


def store_plan_path(plan_id: str) -> Path:
    return (agent_platform.state_root() / "adopt" / "plans"
            / (plan_id.split(":", 1)[1] + ".json"))


def load_contract_source(root: Path) -> dict | None:
    """The authored contract as JSON, or None when there is none to amend.

    This is the one place `adopt-project` reads `.agents/project.json` itself,
    because amending that file is what adoption *is*; its validity remains the
    resolver's verdict alone (D26).
    """
    data = adopt_inspection.read_bytes_bounded(
        root / adopt_inspection.CONTRACT_FILENAME)
    if data is None:
        return None
    try:
        source = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return source if isinstance(source, dict) else None


def emit_human(document: dict) -> int:
    """A bounded semantic view. What is stored is unchanged (R4.8)."""
    plan = document["plan"]
    lines = [
        f"outcome: {plan['outcome']}",
        f"state:   {plan['state']}",
        f"project: {plan['project_id']}",
        f"base:    {plan['base_revision']}",
        f"plan id: {plan['plan_id']}",
        f"evidence: {len(document['evidence'])} entries",
        f"changes:  {len(document['changes'])} operations",
    ]
    for entry in document["decisions"]["recommended"]:
        lines.append(f"recommended {entry['id']}: {entry['value']}")
    for entry in document["decisions"]["open"]:
        lines.append(f"open {entry['id']}: {entry['recommendation']}")
    for blocker in plan["blockers"]:
        lines.append(f"blocked by {blocker['id']}: {blocker['message']}")
    lines.append(f"next: {document['handoff']['next_command'] or '(none)'}")
    lines.append(f"stored at {document['handoff']['plan_path']}")
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


def require_manifest() -> dict:
    """The installed manifest, before the target is touched.

    A broken platform installation is an adoption failure with a stable repair
    id: `adopt-project` has no `resolver_failure` code (D20), and a manifest
    that will not load is never replaced by an assumed version.
    """
    try:
        manifest, _ = agent_platform.load_manifest()
    except agent_platform.PlatformManifestError as error:
        raise adopt_inspection.AdoptError(
            "adopt_failure", "adopt.manifest.invalid",
            error.violations) from None
    return manifest

# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adopt-project",
        description="Plan a repository's adoption into the agent platform.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser(
        "plan", help="inspect a repository and emit its adoption plan")
    plan.add_argument("--repo-root", required=True,
                      help="the top level of the repository to inspect")
    plan.add_argument("--format", choices=("json", "human"), default="json",
                      help="the view printed on stdout; the stored document "
                           "is the same either way")
    return parser


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "plan":
        return command_plan(args)
    raise ValueError(f"unknown subcommand: {args.command!r}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not bootstrap_platform_library():
        return emit_error(
            "adopt_failure",
            PLATFORM_LIBRARY_REPAIR_ID,
            [{
                "pointer": "",
                "message": (
                    "the shared platform library was not found at "
                    "~/.agents/lib/python/agent_platform.py"
                ),
            }],
        )
    # After the platform library, whose path insertion these two share, and
    # before dispatch: one refusal shape for every half of the installation.
    if not bootstrap_adopt_libraries():
        return emit_error(
            "adopt_failure",
            ADOPT_LIBRARY_REPAIR_ID,
            [{
                "pointer": "",
                "message": (
                    "the adoption libraries were not found at "
                    "~/.agents/lib/python/adopt_inspection.py and "
                    "~/.agents/lib/python/adopt_planning.py"
                ),
            }],
        )
    try:
        return dispatch(args)
    except adopt_inspection.AdoptError as error:
        return emit_error(error.code, error.repair_id, error.violations)
    except Exception:
        # One fixed sentence: refusal bytes stay deterministic and no internal
        # detail — no exception text, no traceback — reaches the caller.
        return emit_error(
            "adopt_failure",
            "adopt.internal",
            [{"pointer": "", "message": "adoption failed unexpectedly"}],
        )


if __name__ == "__main__":
    sys.exit(main())
