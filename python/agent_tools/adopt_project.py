"""Adopt a repository into the shared agent platform.

`plan` inspects a target checkout inside a bounded, read-only boundary,
classifies every candidate it finds under one closed action set, routes the
repository to exactly one of five closed outcomes, and emits the eight-member
adoption plan document: `schema_version`, `plan`, `evidence`, `decisions`,
`changes`, `link_rewrites`, `verification`, `handoff` (R4.3).

The document is content-addressed. `plan_id` is the SHA-256 of canonical JSON
over exactly `{adopt_schema_version, project_id, base_revision, platform,
evidence, decisions.answered, link_rewrites}` (D15), so two checkouts of one
revision on one platform produce one identifier and any change to a source
byte, the base revision or a platform input produces another. The absolute
checkout path is deliberately outside that source and appears only in
`handoff`.

`plan` mutates nothing: it runs `git` and the resolver as child processes,
reads tracked object ids, and the base revision's Markdown blobs through git,
rather than the working tree's bytes, and writes only under
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

`verify` answers the conformance question read-only against one pinned
revision — the contract resolves, every projection is in sync, no agent path is
unclassified, and exactly one adoption evidence record is discoverable in it
with the migration map it names (D34). Plain `verify` reads `HEAD`: the
resolver runs on the working tree, the inventory comes from the index, and
records are read at the `HEAD` commit it pins (D10). All three answers are
reports on exit 0. `--register` is the one write to the user-scope fleet
registry, and it reads nothing from the checkout's branches or files: it lists
`origin`, fetches the remote default branch and, when the contract there names
another integration branch, that branch too, each into
`refs/remotes/origin/<branch>` (the fetched objects and those remote-tracking
refs are the only repository writes), exports the pinned commit with
`git archive` into a temporary directory removed on every exit, and runs every
check there. It refuses `not_integrated` when that commit carries no evidence
record or the adoption commit derived from it is not its ancestor (D19). What
it stores is `{project_id, root}` with the real root and nothing else (#148
D18).

The resolver is consumed **only** as a child process, never imported (D26):
`run_resolver` runs `agent_tools.resolve_project` under this process's own
interpreter through `agent_tools.siblings.sibling_argv` (#177 D5), so
contract validation has one home and an installed run is answered by the
resolver of its own store environment. The shared platform library
`agent_platform` is imported directly — it is the one home for the manifest
loader, the state root and the atomic writer (D37).

A structural refusal prints exactly one JSON object carrying an `error` member
on stdout and exits 2 (D12). An argparse usage error also exits 2 but prints no
JSON, which is how a caller tells the two apart (D16).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from agent_tools import adopt_apply, adopt_inspection, adopt_links, adopt_planning, adopt_verify, agent_platform
from agent_tools.siblings import sibling_argv


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


def run_resolver(root: Path, *args: str) -> tuple[int, object]:
    """The resolver's exit code and parsed JSON, or a refusal.

    Exit 0 carries the documented success document and exit 2 the documented
    D12 error object; any other exit, or output that will not parse, is an
    adoption failure rather than a guess.
    """
    try:
        proc = subprocess.run([*sibling_argv("resolve_project"), *args, "--repo-root", str(root)],
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
    inspected sources, planned destinations and on-disk inputs of a planned
    write that an uncommitted change must not sit inside; neither belongs in
    the published document, and both are what `apply` needs from the very
    derivation the plan id was taken over.
    """

    def __init__(self, document: dict, contents: dict[str, bytes],
                 overlap: list[str]) -> None:
        self.document = document
        self.contents = contents
        self.overlap = overlap


def compose_plan(root: Path, manifest: dict,
                 answered: list[dict]) -> Composition:
    """The one derivation both `plan` and `apply` read a repository through.

    `apply` re-runs exactly this to recompute the input digest and regenerate
    the canonical operation list (D33), so a second, subtly different
    derivation cannot exist to disagree with it. It writes nothing.
    `answered` is the operator's answers to open `candidate-class` questions,
    applied before anything else is derived, so they enter `plan_id`.
    """
    inventory = inspect_repository(root)
    found = adopt_inspection.classify_inventory(root, inventory)
    answered = adopt_planning.apply_answers(found, inventory, answered)
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
    links = adopt_links.derive_link_rewrites(
        root, inventory.base_revision, found.moves,
        [path for path, _ in adopt_planning.evidence_record_members(found)],
        adopt_planning.generated_targets(contract_source))
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
    open_questions = sorted(
        open_questions + adopt_planning.candidate_questions(found),
        key=lambda entry: (
            adopt_inspection.QUESTION_IDS.index(entry["id"]),
            entry.get("subject", "")))
    decisions = {"recommended": recommended, "answered": answered,
                 "open": open_questions}

    platform_block = {
        "platform_version": manifest["platform_version"],
        "project_schema_versions": list(manifest["project_schema_versions"]),
        "resolved_schema_version": manifest["resolved_schema_version"],
    }
    plan_id = adopt_planning.compute_plan_id(
        project_id, inventory.base_revision, platform_block, evidence,
        decisions["answered"], links.summary)

    ready_gates = adopt_planning.evaluate_ready_gates(
        root, found, contract_source, contract_resolves, unfixable, untracked,
        decisions, links.summary)
    head, tail, contents = adopt_planning.build_operations(
        root, found, manifest, contract_source, plan_id, links)

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
            decisions, ready_gates, links.summary)
        contents.update(written)
        changes = head + bookkeeping + tail
        adopt_planning.check_markdown_writes(changes, set(links.files))
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
        "link_rewrites": links.summary,
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

    return Composition(document, contents, adopt_inspection.dirty_targets(
        found))


def command_plan(args: argparse.Namespace) -> int:
    manifest = require_manifest()
    root = adopt_inspection.require_repository(args.repo_root)
    answers = [{"id": question, "subject": subject, "value": value}
               for question, subject, value in args.answer]
    document = compose_plan(root, manifest, answers).document
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
    rewrites = document["link_rewrites"]
    inbound, outbound = rewrites["inbound"], rewrites["outbound"]
    lines = [
        f"outcome: {plan['outcome']}",
        f"state:   {plan['state']}",
        f"project: {plan['project_id']}",
        f"base:    {plan['base_revision']}",
        f"plan id: {plan['plan_id']}",
        f"evidence: {len(document['evidence'])} entries",
        f"changes:  {len(document['changes'])} operations",
        f"links: inbound {inbound['links']} in {len(inbound['files'])} "
        f"files, outbound {outbound['links']} in {len(outbound['files'])} "
        f"files, unrewritable {len(rewrites['unrewritable'])}, "
        f"already broken {rewrites['already_broken']}",
    ]
    for entry in document["decisions"]["recommended"]:
        lines.append(f"recommended {entry['id']}: {entry['value']}")
    for entry in document["decisions"]["answered"]:
        lines.append(f"answered {entry['id']} {entry['subject']}: "
                     f"{entry['value']}")
    for entry in document["decisions"]["open"]:
        if entry["id"] == "candidate-class":
            answer = "none" if entry["value"] is None else entry["value"]
            lines.append(f"open {entry['id']} {entry['subject']} "
                         f"(answer: {answer}): {entry['recommendation']}")
        else:
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
# The operator's answers travel inside the stored plan and are re-applied here;
# the recomputed digest is what authenticates them, so `apply` takes no answer
# of its own.
# --------------------------------------------------------------------------


def command_apply(args: argparse.Namespace) -> int:
    manifest = require_manifest()
    digest = adopt_apply.plan_digest(args.plan_id)
    document = adopt_apply.load_stored_plan(digest)
    answers = adopt_apply.stored_answers(document)
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

    composed = compose_plan(root, manifest, answers)
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
# The conformance question, answered read-only against one pinned revision,
# and — only with `--register` — the one write to the user-scope fleet
# registry. Plain `verify` reads `HEAD` (resolver on the working tree,
# inventory from the index, records at the `HEAD` commit it pins). `--register`
# reads nothing from the checkout's branches or files: `adopt_verify.
# remote_source` lists `origin`, fetches the remote default branch and, when
# the contract there names another integration branch, that branch too, each
# into `refs/remotes/origin/<branch>` (the fetched objects and those
# remote-tracking refs are the only repository writes), and exports the pinned
# commit with `git archive` into a temporary directory that is removed on every
# exit, and every check runs there. The checks, the report and the
# registration transaction live in `adopt_verify`; what is left here is the
# order they run in.
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
    if not args.register:
        verification = adopt_verify.verify_repository(
            root, adopt_verify.head_source(root), run_resolver)
    else:
        with adopt_verify.remote_source(root, run_resolver) as source:
            verification = adopt_verify.verify_repository(
                root, source, run_resolver)
        adopt_verify.require_integrated(verification)
        if adopt_verify.registration_allowed(verification.report["result"]):
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
    plan.add_argument("--answer", action="append", nargs=3, default=[],
                      metavar=("QUESTION", "SUBJECT", "VALUE"),
                      help="settle one open candidate-class question; "
                           "repeatable")
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
                             "registry; conformance and integration are "
                             "proven against the contract's integration "
                             "branch fetched from origin, never the local "
                             "checkout")
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
