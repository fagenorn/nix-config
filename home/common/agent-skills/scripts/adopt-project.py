#!/usr/bin/env python3
"""Adopt a repository into the shared agent platform.

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

`plan` mutates nothing: it runs `git` and the resolver as child processes,
reads tracked object ids rather than tracked bytes, and writes only under
`~/.agents/state/` (R4.1, D14).

`apply` takes a stored `ready` plan by that id, refuses on any drift, and
carries the whole transformation out in an isolated worktree in the same user
scope — outside the target checkout, so it cannot appear in the target's own
`git status` (D14). Every refusal in it mutates nothing; a failed pre-commit
gate leaves no commit and retains the worktree with its evidence (D17); a
green run produces exactly one commit on one new branch and removes the
worktree only after proving the ref carries it. It never pushes, never merges
and never writes the fleet registry.

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
import re
import subprocess
import sys
import tarfile
import tempfile

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
    "OPERATION_KINDS",
    "OUTCOMES",
    "PLAN_STATES",
    "READY_GATES",
    "RUNTIME_SENTINEL",
    "TARGETED_IGNORED",
    "canonical_json",
    "classify",
    "classify_inventory",
    "evidence_entry",
    "gate_entry",
    "git_or_fail",
    "head_revision",
    "is_agent_path",
    "is_secret_path",
    "matches_group",
    "outcome_is_appliable",
    "overlap_targets",
    "read_bytes_bounded",
    "refuse",
    "registered_worktrees",
    "require_repository",
    "run_git",
    "sha256_hash",
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


class Composition:
    """One derivation of a repository's adoption plan.

    `document` is what `plan` stores and prints. `contents` holds the bytes
    behind every `write-file` operation's `after` hash, and `overlap` the
    inspected sources and planned destinations an uncommitted change must not
    sit inside; neither belongs in the published document, and both are what
    `apply` needs from the very derivation the plan id was taken over.
    """

    def __init__(self, document: dict, contents: dict[str, bytes],
                 overlap: list[str]) -> None:
        self.document = document
        self.contents = contents
        self.overlap = overlap


def compose_plan(root: Path, manifest: dict) -> Composition:
    """The one derivation both `plan` and `apply` read a repository through.

    `apply` re-runs exactly this to recompute the input digest and regenerate
    the canonical operation list (D33), so a second, subtly different
    derivation cannot exist to disagree with it. It writes nothing.
    """
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
    head, tail, contents = adopt_planning.build_operations(
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
        bookkeeping, written = adopt_planning.bookkeeping_operations(
            found, plan_id, outcome, inventory.base_revision, platform_block,
            decisions, ready_gates)
        contents.update(written)
        changes = head + bookkeeping + tail
        evidence_record = records["evidence_record"]
        migration_map = records["migration_map"]
    else:
        state = "not_applicable"
        blockers = []
        changes = []
        contents = {}
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

    return Composition(document, contents, adopt_inspection.overlap_targets(
        found))


def command_plan(args: argparse.Namespace) -> int:
    manifest = require_manifest()
    root = adopt_inspection.require_repository(args.repo_root)
    document = compose_plan(root, manifest).document
    store_document(document["plan"]["plan_id"], document)
    if args.format == "human":
        return emit_human(document)
    return emit_json(document)


def store_document(plan_id: str, document: dict) -> None:
    """Write a plan document to its one user-scope home, atomically (D14)."""
    plan_path = store_plan_path(plan_id)
    agent_platform.ensure_directory(plan_path.parent)
    agent_platform.write_atomically(
        plan_path, adopt_inspection.canonical_json(document) + b"\n")


def stored_plan_path(digest: str) -> Path:
    return agent_platform.state_root() / "adopt" / "plans" / f"{digest}.json"


def store_plan_path(plan_id: str) -> Path:
    return stored_plan_path(plan_id.split(":", 1)[1])


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
# `apply`
#
# The ordered refusals of the spec's apply mechanics, each of which mutates
# nothing, then one transformation carried out entirely inside a worktree in
# user scope (D14) and one commit — or nothing at all.
#
# Naming the content-addressed plan id is the approval (D16), so the whole
# safety of that approval rests on the recomputation below: the digest
# authenticates the plan's *inputs*, and re-deriving the operation list through
# `compose_plan` authenticates the operations, which live outside the digest in
# a mutable stored document (D33). Nothing here trusts a stored operation.
# --------------------------------------------------------------------------

PLAN_ID_PATTERN = re.compile(r"(?:sha256:)?([0-9a-f]{64})")

STORED_PLAN_MEMBERS = ("changes", "handoff", "plan", "verification")
STORED_HANDOFF_MEMBERS = ("evidence_record", "migration_map", "repo_root")
STORED_PLAN_BLOCK_MEMBERS = ("base_revision", "plan_id", "project_id", "state")

# What each operation kind names. `sources` and `targets` are dispatched over
# the closed kind set, so an operation whose arity does not match its kind is
# refused before anything runs rather than raising mid-transformation.
OPERATION_ARITY = {
    "git-mv": (1, 1),
    "write-file": (None, 1),
    "delete-file": (1, None),
    "regenerate-projection": (1, 1),
}


def plan_digest(plan_id: str) -> str:
    """The stored plan's filename stem, or `plan_not_found`.

    `--plan-id` is caller input that becomes a path, so it is matched against
    the one shape a plan id can have — a SHA-256, with or without the `sha256:`
    prefix the plan prints. Anything else names no stored plan.
    """
    match = PLAN_ID_PATTERN.fullmatch(plan_id.strip())
    if match is None:
        raise adopt_inspection.refuse(
            "plan_not_found", "adopt.plan.unknown_id", "",
            "the named plan id is not a stored plan identifier")
    return match.group(1)


def load_stored_plan(digest: str) -> dict:
    """The stored document, or a refusal naming which half is wrong."""
    path = stored_plan_path(digest)
    data = adopt_inspection.read_bytes_bounded(path)
    if data is None:
        raise adopt_inspection.refuse(
            "plan_not_found", "adopt.plan.absent", "",
            "no plan is stored under the named id")
    try:
        document = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.plan.malformed", "",
            "the stored plan is not parseable JSON") from None
    if not isinstance(document, dict) or any(
            member not in document for member in STORED_PLAN_MEMBERS):
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.plan.malformed", "",
            "the stored plan is missing a member apply reads")
    plan = document["plan"]
    handoff = document["handoff"]
    if (not isinstance(plan, dict) or not isinstance(handoff, dict)
            or not isinstance(document["changes"], list)
            or any(member not in plan
                   for member in STORED_PLAN_BLOCK_MEMBERS)
            or any(member not in handoff
                   for member in STORED_HANDOFF_MEMBERS)):
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.plan.malformed", "",
            "the stored plan is missing a member apply reads")
    return document


def contained_relative(root: Path, relative: object) -> bool:
    """Whether `relative` is a repository-relative path inside `root`.

    Resolved rather than merely inspected, so a component that is a symlink
    out of the checkout is caught as well as a literal `..` or a leading `/`.
    `strict=False`: a planned destination does not exist yet.
    """
    if not isinstance(relative, str) or not relative:
        return False
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    try:
        anchor = root.resolve(strict=True)
        resolved = (anchor / candidate).resolve()
    except (OSError, RuntimeError):
        return False
    return resolved != anchor and anchor in resolved.parents


def validate_operations(root: Path, operations: list[object]) -> None:
    """Every operation is a known kind of the right arity over contained paths.

    Run before the digest and the re-derivation, because it is a check on the
    shape of caller-reachable stored input rather than on what the repository
    says; the re-derivation then proves that the list executed is this one.
    """
    for operation in operations:
        if not isinstance(operation, dict):
            raise adopt_inspection.refuse(
                "adopt_failure", "adopt.operation.malformed", "/changes",
                "a stored operation is not an object")
        kind = operation.get("op")
        if kind not in adopt_inspection.OPERATION_KINDS:
            raise adopt_inspection.refuse(
                "adopt_failure", "adopt.operation.unknown_kind", "/changes",
                "a stored operation names no known operation kind")
        sources, targets = operation.get("sources"), operation.get("targets")
        if not isinstance(sources, list) or not isinstance(targets, list):
            raise adopt_inspection.refuse(
                "adopt_failure", "adopt.operation.malformed", "/changes",
                "a stored operation does not carry both path lists")
        wanted_sources, wanted_targets = OPERATION_ARITY[kind]
        if ((wanted_sources is not None and len(sources) != wanted_sources)
                or (wanted_targets is not None
                    and len(targets) != wanted_targets)):
            raise adopt_inspection.refuse(
                "adopt_failure", "adopt.operation.malformed", "/changes",
                "a stored operation names the wrong number of paths for its "
                "kind")
        for path in sources + targets:
            if not contained_relative(root, path):
                raise adopt_inspection.refuse(
                    "adopt_failure", "adopt.operation.uncontained_path",
                    "/changes",
                    "a stored operation names a path outside the repository")
            if adopt_inspection.is_secret_path(path):
                raise adopt_inspection.refuse(
                    "adopt_failure", "adopt.operation.secret_path", "/changes",
                    "a stored operation names a secret-shaped path")


def status_records(root: Path) -> list[tuple[str, tuple[str, ...]]]:
    """`git status --porcelain -z` as `(XY, paths)`, renames carrying both.

    In `-z` mode a rename or copy is two records: the status and the new path,
    then the original path. Parsed rather than pattern-matched, because the
    rename detection this reads is the whole point of the first commit gate.
    """
    fields = adopt_inspection.git_or_fail(
        root, "status", "--porcelain", "-z",
        "--untracked-files=all").split(b"\0")
    records: list[tuple[str, tuple[str, ...]]] = []
    index = 0
    while index < len(fields):
        record = fields[index]
        index += 1
        if not record:
            continue
        text = record.decode("utf-8", "surrogateescape")
        code, path = text[:2], text[3:]
        if code[0] in ("R", "C") or code[1] in ("R", "C"):
            if index >= len(fields):
                raise adopt_inspection.refuse(
                    "adopt_failure", "adopt.git.unparseable_status", "",
                    "a rename status record named no original path")
            original = fields[index].decode("utf-8", "surrogateescape")
            index += 1
            records.append((code, (path, original)))
            continue
        records.append((code, (path,)))
    return records


def expected_status(operations: list[dict]) -> tuple[list[tuple], set[tuple]]:
    """`(required, optional)` status records for a list of operations.

    A projection regeneration is idempotent: it is a no-op on a conformant
    source and a rewrite otherwise, so it is the one operation whose status
    entry is permitted rather than demanded.
    """
    required: list[tuple] = []
    optional: set[tuple] = set()
    for operation in operations:
        kind = operation["op"]
        if kind == "git-mv":
            required.append(("R ", (operation["targets"][0],
                                    operation["sources"][0])))
        elif kind == "write-file":
            target = operation["targets"][0]
            required.append(
                ("A " if operation["before"] is None else "M ", (target,)))
        elif kind == "delete-file":
            required.append(("D ", (operation["sources"][0],)))
        elif kind == "regenerate-projection":
            target = operation["targets"][0]
            optional.update({("M ", (target,)), ("A ", (target,))})
        else:
            raise ValueError(f"unknown operation kind: {kind!r}")
    return required, optional


def staged_object_id(root: Path, relative: str) -> str | None:
    for path, object_id in adopt_inspection.tracked_inventory(root):
        if path == relative:
            return object_id
    return None


def operation_result_matches(worktree: Path, operation: dict) -> bool:
    """Whether the executed operation produced the hash the plan published.

    The two prefixes are two different questions: a `git-object:` hash is
    answered from the index, without reading the file, and a `sha256:` hash
    from the bytes now on disk.
    """
    after = operation["after"]
    if after is None:
        return True
    if not operation["targets"]:
        return False
    target = operation["targets"][0]
    if after.startswith("git-object:"):
        return staged_object_id(worktree, target) == after.split(":", 1)[1]
    if after.startswith("sha256:"):
        data = adopt_inspection.read_bytes_bounded(worktree / target)
        return data is not None and adopt_inspection.sha256_hash(data) == after
    raise ValueError(f"unknown content hash prefix: {after!r}")


def execute_operation(worktree: Path, operation: dict,
                      contents: dict[str, bytes]) -> None:
    """Carry out one typed operation inside the worktree, and stage it."""
    kind = operation["op"]
    if kind == "git-mv":
        source, target = operation["sources"][0], operation["targets"][0]
        (worktree / target).parent.mkdir(parents=True, exist_ok=True)
        # `git mv`, never a copy and never a write-plus-delete: the rename is
        # what carries the file's history across the move.
        code, _ = adopt_inspection.run_git(worktree, "mv", "--", source, target)
        if code != 0:
            raise operation_failure("a planned move did not succeed")
    elif kind == "write-file":
        target = operation["targets"][0]
        data = contents.get(target)
        if data is None:
            raise operation_failure(
                "a planned write named no generated content")
        agent_platform.write_atomically(worktree / target, data)
        # The runtime sentinel ignores itself, so it is the one path that
        # cannot be staged without `-f`.
        force = ["-f"] if target == adopt_inspection.RUNTIME_SENTINEL else []
        code, _ = adopt_inspection.run_git(
            worktree, "add", *force, "--", target)
        if code != 0:
            raise operation_failure("a written file could not be staged")
    elif kind == "delete-file":
        code, _ = adopt_inspection.run_git(
            worktree, "rm", "--quiet", "--", operation["sources"][0])
        if code != 0:
            raise operation_failure("a planned deletion did not succeed")
    elif kind == "regenerate-projection":
        exit_code, _ = run_resolver(worktree, "write-projections")
        if exit_code != 0:
            raise operation_failure("a projection could not be regenerated")
        code, _ = adopt_inspection.run_git(
            worktree, "add", "--", operation["targets"][0])
        if code != 0:
            raise operation_failure(
                "a regenerated projection could not be staged")
    else:
        raise ValueError(f"unknown operation kind: {kind!r}")
    if not operation_result_matches(worktree, operation):
        raise operation_failure(
            "an executed operation did not produce the planned content")


def operation_failure(message: str) -> adopt_inspection.AdoptError:
    return adopt_inspection.refuse(
        "verification_failed", "adopt.operation.failed", "/changes", message)


class GateRun:
    """One evaluation of the commit gates, and what they all read.

    `resolve` is run once and judged by two gates and read by a third, so the
    payload is observed here rather than three times: the gates are three
    independent verdicts over one observation, not three observations.
    """

    def __init__(self, worktree: Path, operations: list[dict]) -> None:
        self.worktree = worktree
        self.operations = operations
        self.resolve_code, self.resolve_payload = run_resolver(
            worktree, "resolve")


def gate_worktree_status_matches(run: GateRun) -> bool:
    required, optional = expected_status(run.operations)
    actual = status_records(run.worktree)
    remaining = list(required)
    for record in actual:
        if record in remaining:
            remaining.remove(record)
            continue
        if record not in optional:
            return False
    return not remaining


def gate_projections_in_sync(run: GateRun) -> bool:
    exit_code, payload = run_resolver(run.worktree, "check-projections")
    if exit_code != 0 or not isinstance(payload, dict):
        return False
    entries = payload.get("projections")
    return isinstance(entries, list) and all(
        isinstance(entry, dict) and entry.get("action") == "unchanged"
        for entry in entries)


def gate_no_unclassified_agent_path(run: GateRun) -> bool:
    return not any(
        adopt_inspection.classify(path) is None
        and adopt_inspection.is_agent_path(path)
        for path, _ in adopt_inspection.tracked_inventory(run.worktree))


def gate_cold_clone_resolves(run: GateRun) -> bool:
    """A tracked-only export of the staged index still resolves.

    `git write-tree` over the index without committing, then `git archive` of
    that tree: what lands in the temporary directory is exactly what a fresh
    clone would see, so an adoption that only works because of an untracked
    file cannot pass.
    """
    tree = adopt_inspection.git_or_fail(
        run.worktree, "write-tree").decode("ascii", "strict").strip()
    with tempfile.TemporaryDirectory() as scratch:
        archive = Path(scratch) / "tree.tar"
        adopt_inspection.git_or_fail(
            run.worktree, "archive", "-o", str(archive), tree)
        export = Path(scratch) / "export"
        export.mkdir()
        try:
            with tarfile.open(archive) as bundle:
                bundle.extractall(export, filter="data")
        except (tarfile.TarError, OSError):
            return False
        exit_code, payload = run_resolver(export, "resolve")
        if exit_code != 0 or not isinstance(payload, dict):
            return False
        exit_code, payload = run_resolver(export, "check-projections")
        if exit_code != 0 or not isinstance(payload, dict):
            return False
        entries = payload.get("projections")
        return isinstance(entries, list) and all(
            isinstance(entry, dict) and entry.get("action") == "unchanged"
            for entry in entries)


def gate_resolve_capabilities_available(run: GateRun) -> bool:
    if run.resolve_code != 0 or not isinstance(run.resolve_payload, dict):
        return False
    capabilities = run.resolve_payload.get("capabilities")
    if not isinstance(capabilities, dict):
        return False
    # Available or deliberately unsupported; `blocked` is a capability the
    # contract claims and the checkout cannot deliver.
    return all(isinstance(entry, dict)
               and entry.get("state") in ("available", "unsupported")
               for entry in capabilities.values())


def gate_workflow_verification_commands(run: GateRun) -> bool:
    """Every declared verification command, in full, in the worktree.

    No timeout and no subset: a verification suite that takes minutes is what
    the contract declared, and cutting it short is the swallowed failure the
    bar forbids.
    """
    if run.resolve_code != 0 or not isinstance(run.resolve_payload, dict):
        return False
    bindings = run.resolve_payload.get("bindings")
    if not isinstance(bindings, dict):
        return False
    workflow = bindings.get("workflow")
    commands = bindings.get("commands")
    if not isinstance(workflow, dict) or not isinstance(commands, dict):
        return False
    for command_id in workflow.get("verification", []):
        entry = commands.get(command_id)
        if not isinstance(entry, dict):
            return False
        try:
            proc = subprocess.run(entry["argv"], cwd=entry["cwd"],
                                  capture_output=True)
        except (OSError, subprocess.SubprocessError):
            return False
        if proc.returncode != 0:
            return False
    return True


COMMIT_GATE_CHECKS = {
    "worktree-status-matches-operations": gate_worktree_status_matches,
    "projections-in-sync": gate_projections_in_sync,
    "no-unclassified-agent-path": gate_no_unclassified_agent_path,
    "cold-clone-resolves": gate_cold_clone_resolves,
    "resolve-capabilities-available": gate_resolve_capabilities_available,
    "workflow-verification-commands": gate_workflow_verification_commands,
}


def run_commit_gates(run: GateRun) -> list[dict]:
    """Every declared gate, in declaration order, each recorded.

    All of them run even once one has failed: the retained evidence is meant
    to say what the whole checkout looks like, not only where inspection
    stopped.
    """
    gates = []
    for gate_id in adopt_inspection.COMMIT_GATES:
        check = COMMIT_GATE_CHECKS.get(gate_id)
        if check is None:
            raise ValueError(f"unknown commit gate: {gate_id!r}")
        passed = check(run)
        gates.append(adopt_inspection.gate_entry(
            gate_id, "passed" if passed else "failed",
            None if passed else f"adopt.gate.{gate_id}"))
    return gates


def commit_message(project_id: str, digest: str, records: dict) -> str:
    """D28's fixed message: a pure function of the plan, with no trailer."""
    return (f"chore(adopt): adopt {project_id} at plan {digest[:12]}\n"
            "\n"
            f"path migration map: {records['migration_map']}\n"
            f"adoption evidence record: {records['evidence_record']}\n")


def retain_failure(digest: str, document: dict, worktree: Path, branch: str,
                   gates: list[dict], repair_id: str) -> None:
    """Record why the worktree is being kept, beside it and never in the
    target repository."""
    document["verification"]["commit_gates"] = gates
    store_document(document["plan"]["plan_id"], document)
    evidence = worktree.parent / f"{digest}.failure.json"
    agent_platform.ensure_directory(evidence.parent)
    agent_platform.write_atomically(evidence, adopt_inspection.canonical_json({
        "schema_version": adopt_inspection.ADOPT_SCHEMA_VERSION,
        "plan_id": document["plan"]["plan_id"],
        "base_revision": document["plan"]["base_revision"],
        "branch": branch,
        "worktree": str(worktree),
        "repair_id": repair_id,
        "gates": gates,
    }) + b"\n")


def command_apply(args: argparse.Namespace) -> int:
    manifest = require_manifest()
    digest = plan_digest(args.plan_id)
    document = load_stored_plan(digest)
    stored_plan = document["plan"]
    if stored_plan["state"] != "ready":
        raise adopt_inspection.refuse(
            "not_ready", "adopt.plan.not_ready", "/plan/state",
            "only a ready plan can be applied")
    changes = document["changes"]
    if any(isinstance(operation, dict)
           and operation.get("op") == "delete-file"
           for operation in changes) and not args.acknowledge_deletions:
        raise adopt_inspection.refuse(
            "unacknowledged_deletion", "adopt.plan.unacknowledged_deletion",
            "/changes",
            "the plan deletes a file and no deletion acknowledgement was "
            "given")

    root = adopt_inspection.require_repository(document["handoff"]["repo_root"])
    validate_operations(root, changes)

    # Before the repository is re-inspected, because a retained worktree is
    # registered in the target and therefore *changes* what the inspection
    # sees: checked after the digest it could never be reached on the retry it
    # exists for, and the caller would be told to re-plan instead of being
    # told that a failed attempt is still there. Never deleted here — #72
    # allows that only under an acknowledged cleanup.
    worktree = agent_platform.state_root() / "adopt" / "worktrees" / digest
    if worktree.exists():
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.worktree.retained", "",
            "a retained worktree for this plan still exists and is never "
            "deleted without an acknowledged cleanup")

    composed = compose_plan(root, manifest)
    if composed.document["plan"]["plan_id"] != stored_plan["plan_id"]:
        raise adopt_inspection.refuse(
            "plan_stale", "adopt.plan.inputs_changed", "/plan/input_digest",
            "the repository no longer hashes to the plan's input digest")
    # The operations sit outside the digest in a mutable stored document, so
    # the identifier alone cannot vouch for them (D33).
    if (adopt_inspection.canonical_json(composed.document["changes"])
            != adopt_inspection.canonical_json(changes)):
        raise adopt_inspection.refuse(
            "plan_stale", "adopt.plan.operations_changed", "/changes",
            "the stored operations are not the operations this repository "
            "derives")

    dirty = dirty_overlap(root, composed.overlap)
    if dirty:
        raise adopt_inspection.refuse(
            "dirty_worktree", "adopt.worktree.dirty", "",
            "an uncommitted change overlaps an inspected source or a planned "
            "destination")

    branch = f"adopt-{digest[:12]}"
    base_revision = stored_plan["base_revision"]
    agent_platform.ensure_directory(worktree.parent)
    code, _ = adopt_inspection.run_git(
        root, "worktree", "add", "--no-checkout", "-b", branch,
        str(worktree), base_revision)
    if code != 0:
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.worktree.unavailable", "",
            "the isolated adoption worktree could not be created")
    code, _ = adopt_inspection.run_git(worktree, "checkout")
    if code != 0:
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.worktree.unavailable", "",
            "the isolated adoption worktree could not be checked out")

    try:
        for operation in changes:
            execute_operation(worktree, operation, composed.contents)
    except adopt_inspection.AdoptError as error:
        retain_failure(digest, document, worktree, branch, [
            adopt_inspection.gate_entry(gate, "not_run", None)
            for gate in adopt_inspection.COMMIT_GATES], error.repair_id)
        raise

    run = GateRun(worktree, changes)
    gates = run_commit_gates(run)
    failed = [gate for gate in gates if gate["status"] == "failed"]
    if failed:
        retain_failure(digest, document, worktree, branch, gates,
                       failed[0]["repair_id"])
        raise adopt_inspection.AdoptError(
            "verification_failed", failed[0]["repair_id"],
            [{"pointer": f"/verification/commit_gates/{gate['id']}",
              "message": "a pre-commit gate did not pass"} for gate in failed])

    records = {"migration_map": document["handoff"]["migration_map"],
               "evidence_record": document["handoff"]["evidence_record"]}
    signed = signing_requested(run.resolve_payload)
    if signed is None:
        retain_failure(digest, document, worktree, branch, gates,
                       "adopt.commit.unresolved_policy")
        raise adopt_inspection.refuse(
            "verification_failed", "adopt.commit.unresolved_policy", "",
            "the worktree's commit signing policy could not be resolved")
    code, _ = adopt_inspection.run_git(
        worktree, "commit", "--quiet", *(["-S"] if signed else []),
        "-m", commit_message(stored_plan["project_id"], digest, records))
    if code != 0:
        # Never retried unsigned: a contract that asks for a signature and a
        # machine that cannot produce one is a failure, not a downgrade.
        retain_failure(digest, document, worktree, branch, gates,
                       "adopt.commit.failed")
        raise adopt_inspection.refuse(
            "verification_failed", "adopt.commit.failed", "",
            "the adoption commit could not be created")

    commit = adopt_inspection.git_or_fail(
        worktree, "rev-parse", "HEAD").decode("ascii", "strict").strip()
    prove_branch_carries_commit(root, worktree, branch, base_revision, commit)
    code, _ = adopt_inspection.run_git(root, "worktree", "remove", str(worktree))
    if code != 0:
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.worktree.not_removed", "",
            "the adoption worktree could not be removed after the commit")

    document["verification"]["commit_gates"] = gates
    store_document(stored_plan["plan_id"], document)
    return emit_json({"branch": branch, "commit": commit,
                      "plan_id": stored_plan["plan_id"], **records})


def signing_requested(payload: object) -> bool | None:
    """Whether the amended contract asks for a signed commit, or None (D28).

    Read out of the resolver's own view of the worktree — the same observation
    the gates were judged over — so the policy comes from the validated
    contract rather than from a second reading of the file. None means the
    policy could not be read at all, which is never silently a `false`.
    """
    bindings = payload.get("bindings") if isinstance(payload, dict) else None
    vcs = bindings.get("vcs") if isinstance(bindings, dict) else None
    commit = vcs.get("commit") if isinstance(vcs, dict) else None
    signed = commit.get("signed") if isinstance(commit, dict) else None
    return signed if isinstance(signed, bool) else None


def prove_branch_carries_commit(root: Path, worktree: Path, branch: str,
                                base_revision: str, commit: str) -> None:
    """The three proofs D17 makes worktree removal conditional on.

    The ref holds this commit, it is the only commit the branch adds, and the
    worktree is clean. Never elapsed time.
    """
    head = adopt_inspection.git_or_fail(
        root, "rev-parse", branch).decode("ascii", "strict").strip()
    count = adopt_inspection.git_or_fail(
        worktree, "rev-list", "--count",
        f"{base_revision}..{branch}").decode("ascii", "strict").strip()
    residue = status_records(worktree)
    if head != commit or count != "1" or residue:
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.commit.unproved", "",
            "the adoption branch could not be proved to carry exactly the "
            "adoption commit")


def dirty_overlap(root: Path, targets: list[str]) -> list[str]:
    """Uncommitted paths sitting inside an inspected source or destination.

    Never repaired, never stashed and never reset: the refusal exists to leave
    the caller's work exactly where they left it.
    """
    overlapping = []
    for _, paths in status_records(root):
        for path in paths:
            if any(adopt_inspection.matches_group(path, target, "prefix")
                   for target in targets):
                overlapping.append(path)
    return sorted(set(overlapping))


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
    apply_plan = subparsers.add_parser(
        "apply", help="carry out a stored ready plan in an isolated worktree")
    # Two flags and no more: naming the content-addressed id is the exact-plan
    # approval (D16), and the commit message is a pure function of the plan
    # (D28), so there is nothing left for a caller to supply.
    apply_plan.add_argument("--plan-id", required=True,
                            help="the content-addressed id of a stored ready "
                                 "plan")
    apply_plan.add_argument("--acknowledge-deletions", action="store_true",
                            help="acknowledge that the plan deletes a file")
    return parser


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "plan":
        return command_plan(args)
    if args.command == "apply":
        return command_apply(args)
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
