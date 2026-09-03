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
worktree only after proving that the commit changes exactly the paths the plan
declared and that the ref carries it. It never pushes, never merges and never
writes the fleet registry.

`verify` answers the conformance question read-only against the committed
state — the contract resolves, every projection is in sync, no agent path is
unclassified, and exactly one adoption evidence record is discoverable at
`HEAD` with the migration map it names (D34). All three answers are reports on
exit 0. `--register` is the one write to the user-scope fleet registry, and
only once the adoption commit derived from that record is an ancestor of the
contract's declared integration branch (D19); what it stores is an identity
and a location and nothing else (D18).

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
    "registry_transaction",
    "state_root",
    "write_atomically",
    "write_registry",
)
PLATFORM_LIBRARY_REPAIR_ID = "platform.library.missing"


def library_dir() -> Path | None:
    """The one directory every platform library is bound from, or None.

    Without `HOME` there is no installed platform at all, which is the same
    installation defect an absent library is and refuses the same way.
    """
    home = os.environ.get("HOME")
    return Path(home) / ".agents" / "lib" / "python" if home else None


def loaded_from(module: object, directory: Path) -> bool:
    """Whether `module` was loaded from its own installed file in `directory`.

    Importing by name is not the guard: `sys.path` still carries this script's
    own directory behind the insertion, and a `PYTHONPATH` entry or a
    site-packages install of the same name answers the import just as
    willingly. Only the resolved `__file__` says *which* file answered, so an
    absent installation refuses here instead of being silently substituted by
    whatever else the interpreter can reach.

    Both sides are resolved, because Home Manager installs each library as a
    symlink into the Nix store: the module reports the symlink's path and the
    comparison has to be made over the file they both name.
    """
    origin = getattr(module, "__file__", None)
    if not origin:
        return False
    try:
        return (Path(origin).resolve()
                == (directory / f"{module.__name__}.py").resolve())
    except (OSError, RuntimeError, ValueError):
        return False


def bootstrap_platform_library() -> bool:
    """Bind the shared library from its one installed path, or report failure."""
    global agent_platform
    directory = library_dir()
    if directory is None:
        return False
    sys.path.insert(0, str(directory))
    try:
        import agent_platform as loaded
    except Exception:
        return False
    if (not loaded_from(loaded, directory)
            or any(not hasattr(loaded, name)
                   for name in PLATFORM_LIBRARY_MEMBERS)):
        return False
    agent_platform = loaded
    return True

# The four adoption libraries, bound by `bootstrap_adopt_libraries` before
# any subcommand runs. They install beside `agent_platform.py` and are
# separately installed files, so an older library can pair with a newer
# binary; naming every member this script reads is what makes that pairing
# refuse as `adopt.library.missing` through the D12 error object rather than
# surface as an `AttributeError` swallowed into `adopt.internal`. What each
# library reads from the others is guarded the same way, by naming it in
# that library's own `from` imports.
adopt_inspection = None
adopt_planning = None
adopt_apply = None
adopt_verify = None

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
    "git_or_fail",
    "head_revision",
    "outcome_is_appliable",
    "overlap_targets",
    "read_bytes_bounded",
    "refuse",
    "registered_worktrees",
    "require_repository",
    "resolver_error_code",
    "resolver_repair_id",
    "resolver_violation_pointers",
    "run_git",
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
    "require_unclaimed_digest",
    "route_outcome",
    "store_document",
    "store_plan_path",
)

ADOPT_APPLY_MEMBERS = (
    "GateRun",
    "commit_message",
    "dirty_overlap",
    "execute_operation",
    "load_stored_plan",
    "plan_digest",
    "prove_branch_carries_commit",
    "prove_commit_content",
    "retain_failure",
    "run_commit_gates",
    "signing_requested",
    "validate_operations",
)

ADOPT_VERIFY_MEMBERS = (
    "register_project",
    "registration_allowed",
    "verify_exit_code",
    "verify_repository",
)
ADOPT_LIBRARY_REPAIR_ID = "adopt.library.missing"


def bootstrap_adopt_libraries() -> bool:
    """Bind all four adoption libraries, or report failure.

    `bootstrap_platform_library` has already put the one installed library
    directory on `sys.path`, so this adds no second lookup path and no
    fallback ladder: the modules are found exactly where Nix installs them or
    they are not found at all — `loaded_from` holds each of the four to that
    directory for the same reason it holds `agent_platform` there, since the
    path behind the insertion can satisfy these imports too. A library whose
    own `from` import of a sibling cannot be satisfied fails this import too,
    so the guard reaches the names the libraries read from each other as well
    as the ones read here.
    """
    global adopt_inspection, adopt_planning, adopt_apply, adopt_verify
    directory = library_dir()
    if directory is None:
        return False
    try:
        import adopt_inspection as inspection
        import adopt_planning as planning
        import adopt_apply as applying
        import adopt_verify as verifying
    except Exception:
        return False
    for module, members in ((inspection, ADOPT_INSPECTION_MEMBERS),
                            (planning, ADOPT_PLANNING_MEMBERS),
                            (applying, ADOPT_APPLY_MEMBERS),
                            (verifying, ADOPT_VERIFY_MEMBERS)):
        if (not loaded_from(module, directory)
                or any(not hasattr(module, name) for name in members)):
            return False
    adopt_inspection = inspection
    adopt_planning = planning
    adopt_apply = applying
    adopt_verify = verifying
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
    repair_id = (None if contract_resolves
                 else adopt_inspection.resolver_repair_id(payload))
    projections_drift = (
        not contract_resolves
        and adopt_inspection.resolver_error_code(payload)
        == "invalid_projection")
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
        pointer for pointer
        in adopt_inspection.resolver_violation_pointers(payload)
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

    plan_path = adopt_planning.store_plan_path(plan_id)
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
    # Before the write, never after: storing is what binds this id to this
    # checkout, and the binding a stored document already carries is never
    # re-pointed at a second one (D15, D16).
    adopt_planning.require_unclaimed_digest(document["plan"]["plan_id"], root)
    adopt_planning.store_document(
        document["plan"]["plan_id"], document)
    if args.format == "human":
        return emit_human(document)
    return emit_json(document)


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
# user scope (D14) and one commit — or nothing at all. The mechanics
# themselves live in `adopt_apply`; what is left here is the order they run in
# and the resolver call handed to the two of them that need one.
#
# Naming the content-addressed plan id is the approval (D16), so the whole
# safety of that approval rests on the recomputation below: the digest
# authenticates the plan's *inputs*, and re-deriving the operation list through
# `compose_plan` authenticates the operations, which live outside the digest in
# a mutable stored document (D33). Nothing here trusts a stored operation.
# --------------------------------------------------------------------------


def command_apply(args: argparse.Namespace) -> int:
    manifest = require_manifest()
    digest = adopt_apply.plan_digest(args.plan_id)
    document = adopt_apply.load_stored_plan(digest)
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
    adopt_apply.validate_operations(root, changes)

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

    dirty = adopt_apply.dirty_overlap(root, composed.overlap)
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
            adopt_apply.execute_operation(
                worktree, operation, composed.contents, run_resolver)
    except adopt_inspection.AdoptError as error:
        adopt_apply.retain_failure(digest, document, worktree, branch, [
            adopt_inspection.gate_entry(gate, "not_run", None)
            for gate in adopt_inspection.COMMIT_GATES], error.repair_id)
        raise

    run = adopt_apply.GateRun(worktree, changes, run_resolver)
    gates = adopt_apply.run_commit_gates(run)
    failed = [gate for gate in gates if gate["status"] == "failed"]
    if failed:
        adopt_apply.retain_failure(digest, document, worktree, branch,
                                   gates, failed[0]["repair_id"])
        raise adopt_inspection.AdoptError(
            "verification_failed", failed[0]["repair_id"],
            [{"pointer": f"/verification/commit_gates/{gate['id']}",
              "message": "a pre-commit gate did not pass"} for gate in failed])

    records = {"migration_map": document["handoff"]["migration_map"],
               "evidence_record": document["handoff"]["evidence_record"]}
    signed = adopt_apply.signing_requested(run.resolve_payload)
    if signed is None:
        adopt_apply.retain_failure(digest, document, worktree, branch,
                                   gates,
                                   "adopt.commit.unresolved_policy")
        raise adopt_inspection.refuse(
            "verification_failed", "adopt.commit.unresolved_policy", "",
            "the worktree's commit signing policy could not be resolved")
    code, _ = adopt_inspection.run_git(
        worktree, "commit", "--quiet", *(["-S"] if signed else []),
        "-m", adopt_apply.commit_message(
            stored_plan["project_id"], digest, records))
    if code != 0:
        # Never retried unsigned: a contract that asks for a signature and a
        # machine that cannot produce one is a failure, not a downgrade.
        adopt_apply.retain_failure(digest, document, worktree, branch,
                                   gates, "adopt.commit.failed")
        raise adopt_inspection.refuse(
            "verification_failed", "adopt.commit.failed", "",
            "the adoption commit could not be created")

    commit = adopt_inspection.git_or_fail(
        worktree, "rev-parse", "HEAD").decode("ascii", "strict").strip()
    # The gates judged the worktree before the commit; these two judge the
    # commit itself. Content first — a verification command or a `pre-commit`
    # hook can stage after the last gate passed — then the ref.
    try:
        adopt_apply.prove_commit_content(worktree, commit, changes)
    except adopt_inspection.AdoptError as error:
        adopt_apply.retain_failure(digest, document, worktree, branch, gates,
                                   error.repair_id)
        raise
    adopt_apply.prove_branch_carries_commit(
        root, worktree, branch, base_revision, commit)
    code, _ = adopt_inspection.run_git(root, "worktree", "remove", str(worktree))
    if code != 0:
        raise adopt_inspection.refuse(
            "adopt_failure", "adopt.worktree.not_removed", "",
            "the adoption worktree could not be removed after the commit")

    document["verification"]["commit_gates"] = gates
    adopt_planning.store_document(stored_plan["plan_id"], document)
    return emit_json({"branch": branch, "commit": commit,
                      "plan_id": stored_plan["plan_id"], **records})


# --------------------------------------------------------------------------
# `verify`
#
# The conformance question, answered read-only against the *committed* state,
# and — only with `--register` — the one write to the user-scope fleet
# registry. The checks, the report and the registration transaction live in
# `adopt_verify`; what is left here is the order they run in.
#
# Every one of the three answers is a report on exit 0 (R6.4): exit 2 and the
# D12 error object are reserved for the closed `ADOPT_ERROR_CODES`, so
# `not_conformant` reaches the operator as the answer they asked for rather
# than as a refusal they have to parse.
# --------------------------------------------------------------------------


def command_verify(args: argparse.Namespace) -> int:
    # Before the target is touched, so a broken platform installation surfaces
    # as an adoption failure rather than as a non-conformant repository.
    require_manifest()
    root = adopt_inspection.require_repository(args.repo_root)
    verification = adopt_verify.verify_repository(root, run_resolver)
    if args.register and adopt_verify.registration_allowed(
            verification.report["result"]):
        adopt_verify.register_project(root, verification)
    emit_json(verification.report)
    return adopt_verify.verify_exit_code(verification.report["result"])


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
    verify = subparsers.add_parser(
        "verify", help="report a checkout's conformance, and optionally "
                       "register it in the fleet")
    verify.add_argument("--repo-root", required=True,
                        help="the top level of the repository to verify")
    # Registration is opt-in and is the only thing that writes the fleet
    # registry: `apply` never does, and read-only `verify` never registers
    # implicitly (R6.3).
    verify.add_argument("--register", action="store_true",
                        help="record the project in the user-scope fleet "
                             "registry once its adoption commit is on the "
                             "declared integration branch")
    return parser


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "plan":
        return command_plan(args)
    if args.command == "apply":
        return command_apply(args)
    if args.command == "verify":
        return command_verify(args)
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
                    "~/.agents/lib/python/adopt_inspection.py, "
                    "~/.agents/lib/python/adopt_planning.py, "
                    "~/.agents/lib/python/adopt_apply.py and "
                    "~/.agents/lib/python/adopt_verify.py"
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
