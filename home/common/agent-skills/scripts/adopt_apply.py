"""Carrying a stored `ready` adoption plan out, in an isolated worktree.

Everything `adopt-project apply` is made of below its command function: the
stored document's loader, the validation of every caller-reachable operation,
the typed execution of the operations themselves, the six pre-commit gates and
their ordered run, the fixed commit message (D28), the two proofs taken over
the commit once it exists — that it changes exactly the planned paths, and
that the branch carries it and nothing else — and the retention of a failed
attempt beside its worktree (D17).

Every refusal here mutates nothing, and nothing here trusts a stored
operation: the plan id authenticates the plan's *inputs*, and the entry point
re-derives the operation list before any of this runs (D33).

The resolver is not reached from this module. `adopt-project` owns the one
seam it is consumed through — invoked as a child process at the absolute path
`$HOME/.agents/bin/resolve-project`, never imported (D26) — and hands that
call in, so a second, differently-bounded way to ask the resolver a question
cannot exist here.

Like `adopt_inspection` and `adopt_planning` it is imported, never run: no
`main` and no argparse. It is installed at `$HOME/.agents/lib/python/` behind
the entry point's member guard, and every name it reads from its two sibling
libraries is named in the `from` imports below, so an installation pairing an
older library with a newer binary refuses as `adopt.library.missing` through
the D12 error object rather than as an `AttributeError`.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

import agent_platform
from adopt_inspection import (
    ADOPT_SCHEMA_VERSION,
    AdoptError,
    COMMIT_GATES,
    OPERATION_KINDS,
    RUNTIME_SENTINEL,
    canonical_json,
    classify,
    gate_entry,
    git_or_fail,
    is_agent_path,
    is_secret_path,
    matches_group,
    read_bytes_bounded,
    refuse,
    run_git,
    sha256_hash,
    tracked_inventory,
)
from adopt_planning import store_document, stored_plan_path

# The entry point's resolver call, as this layer receives it: `(root, *args)`
# to the resolver's exit code and its parsed JSON, or an `AdoptError`.
Resolver = Callable[..., tuple[int, object]]


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
        raise refuse(
            "plan_not_found", "adopt.plan.unknown_id", "",
            "the named plan id is not a stored plan identifier")
    return match.group(1)


def load_stored_plan(digest: str) -> dict:
    """The stored document, or a refusal naming which half is wrong."""
    path = stored_plan_path(digest)
    data = read_bytes_bounded(path)
    if data is None:
        raise refuse(
            "plan_not_found", "adopt.plan.absent", "",
            "no plan is stored under the named id")
    try:
        document = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise refuse(
            "adopt_failure", "adopt.plan.malformed", "",
            "the stored plan is not parseable JSON") from None
    if not isinstance(document, dict) or any(
            member not in document for member in STORED_PLAN_MEMBERS):
        raise refuse(
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
        raise refuse(
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
            raise refuse(
                "adopt_failure", "adopt.operation.malformed", "/changes",
                "a stored operation is not an object")
        kind = operation.get("op")
        if kind not in OPERATION_KINDS:
            raise refuse(
                "adopt_failure", "adopt.operation.unknown_kind", "/changes",
                "a stored operation names no known operation kind")
        sources, targets = operation.get("sources"), operation.get("targets")
        if not isinstance(sources, list) or not isinstance(targets, list):
            raise refuse(
                "adopt_failure", "adopt.operation.malformed", "/changes",
                "a stored operation does not carry both path lists")
        wanted_sources, wanted_targets = OPERATION_ARITY[kind]
        if ((wanted_sources is not None and len(sources) != wanted_sources)
                or (wanted_targets is not None
                    and len(targets) != wanted_targets)):
            raise refuse(
                "adopt_failure", "adopt.operation.malformed", "/changes",
                "a stored operation names the wrong number of paths for its "
                "kind")
        for path in sources + targets:
            if not contained_relative(root, path):
                raise refuse(
                    "adopt_failure", "adopt.operation.uncontained_path",
                    "/changes",
                    "a stored operation names a path outside the repository")
            if is_secret_path(path):
                raise refuse(
                    "adopt_failure", "adopt.operation.secret_path", "/changes",
                    "a stored operation names a secret-shaped path")


def status_records(root: Path) -> list[tuple[str, tuple[str, ...]]]:
    """`git status --porcelain -z` as `(XY, paths)`, renames carrying both.

    In `-z` mode a rename or copy is two records: the status and the new path,
    then the original path. Parsed rather than pattern-matched, because the
    rename detection this reads is the whole point of the first commit gate.
    """
    fields = git_or_fail(
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
                raise refuse(
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
    for path, object_id in tracked_inventory(root):
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
        data = read_bytes_bounded(worktree / target)
        return data is not None and sha256_hash(data) == after
    raise ValueError(f"unknown content hash prefix: {after!r}")


def execute_operation(worktree: Path, operation: dict,
                      contents: dict[str, bytes],
                      run_resolver: Resolver) -> None:
    """Carry out one typed operation inside the worktree, and stage it."""
    kind = operation["op"]
    if kind == "git-mv":
        source, target = operation["sources"][0], operation["targets"][0]
        (worktree / target).parent.mkdir(parents=True, exist_ok=True)
        # `git mv`, never a copy and never a write-plus-delete: the rename is
        # what carries the file's history across the move.
        code, _ = run_git(worktree, "mv", "--", source, target)
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
        force = ["-f"] if target == RUNTIME_SENTINEL else []
        code, _ = run_git(
            worktree, "add", *force, "--", target)
        if code != 0:
            raise operation_failure("a written file could not be staged")
    elif kind == "delete-file":
        code, _ = run_git(
            worktree, "rm", "--quiet", "--", operation["sources"][0])
        if code != 0:
            raise operation_failure("a planned deletion did not succeed")
    elif kind == "regenerate-projection":
        exit_code, _ = run_resolver(worktree, "write-projections")
        if exit_code != 0:
            raise operation_failure("a projection could not be regenerated")
        code, _ = run_git(
            worktree, "add", "--", operation["targets"][0])
        if code != 0:
            raise operation_failure(
                "a regenerated projection could not be staged")
    else:
        raise ValueError(f"unknown operation kind: {kind!r}")
    if not operation_result_matches(worktree, operation):
        raise operation_failure(
            "an executed operation did not produce the planned content")


def operation_failure(message: str) -> AdoptError:
    return refuse(
        "verification_failed", "adopt.operation.failed", "/changes", message)


class GateRun:
    """One evaluation of the commit gates, and what they all read.

    `resolve` is run once and judged by two gates and read by a third, so the
    payload is observed here rather than three times: the gates are three
    independent verdicts over one observation, not three observations.

    The entry point's resolver call is kept on the run rather than reached for
    globally, so every gate asks the resolver through the one seam this whole
    verb was handed (D26).
    """

    def __init__(self, worktree: Path, operations: list[dict],
                 run_resolver: Resolver) -> None:
        self.worktree = worktree
        self.operations = operations
        self.run_resolver = run_resolver
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
        # Git's rename detection is a similarity heuristic, so a planned
        # deletion and a planned new file with similar content — a superseded
        # evidence record and its successor — can be reported as one rename.
        # That record is exactly the planned pair, and is accepted as such.
        code, paths = record
        if code == "R " and len(paths) == 2:
            pair = [("D ", (paths[1],)), ("A ", (paths[0],))]
            if all(entry in remaining for entry in pair):
                for entry in pair:
                    remaining.remove(entry)
                continue
        if record not in optional:
            return False
    return not remaining


def gate_projections_in_sync(run: GateRun) -> bool:
    exit_code, payload = run.run_resolver(
        run.worktree, "check-projections")
    if exit_code != 0 or not isinstance(payload, dict):
        return False
    entries = payload.get("projections")
    return isinstance(entries, list) and all(
        isinstance(entry, dict) and entry.get("action") == "unchanged"
        for entry in entries)


def gate_no_unclassified_agent_path(run: GateRun) -> bool:
    return not any(
        classify(path) is None
        and is_agent_path(path)
        for path, _ in tracked_inventory(run.worktree))


def gate_cold_clone_resolves(run: GateRun) -> bool:
    """A tracked-only export of the staged index still resolves.

    `git write-tree` over the index without committing, then `git archive` of
    that tree: what lands in the temporary directory is exactly what a fresh
    clone would see, so an adoption that only works because of an untracked
    file cannot pass.
    """
    tree = git_or_fail(
        run.worktree, "write-tree").decode("ascii", "strict").strip()
    with tempfile.TemporaryDirectory() as scratch:
        archive = Path(scratch) / "tree.tar"
        git_or_fail(
            run.worktree, "archive", "-o", str(archive), tree)
        export = Path(scratch) / "export"
        export.mkdir()
        try:
            with tarfile.open(archive) as bundle:
                bundle.extractall(export, filter="data")
        except (tarfile.TarError, OSError):
            return False
        exit_code, payload = run.run_resolver(export, "resolve")
        if exit_code != 0 or not isinstance(payload, dict):
            return False
        exit_code, payload = run.run_resolver(export, "check-projections")
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
    for gate_id in COMMIT_GATES:
        check = COMMIT_GATE_CHECKS.get(gate_id)
        if check is None:
            raise ValueError(f"unknown commit gate: {gate_id!r}")
        passed = check(run)
        gates.append(gate_entry(
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
    agent_platform.write_atomically(evidence, canonical_json({
        "schema_version": ADOPT_SCHEMA_VERSION,
        "plan_id": document["plan"]["plan_id"],
        "base_revision": document["plan"]["base_revision"],
        "branch": branch,
        "worktree": str(worktree),
        "repair_id": repair_id,
        "gates": gates,
    }) + b"\n")


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


def expected_commit_paths(operations: list[dict]) -> tuple[set[str], set[str]]:
    """`(required, optional)` paths a commit of these operations may change.

    The same split `expected_status` makes, over paths rather than status
    records: a projection regeneration is idempotent, so its target is
    permitted rather than demanded, and every other kind names paths the
    commit has to carry. Dispatched exhaustively over the closed kind set.
    """
    required: set[str] = set()
    optional: set[str] = set()
    for operation in operations:
        kind = operation["op"]
        if kind == "git-mv":
            required.update({operation["sources"][0],
                             operation["targets"][0]})
        elif kind == "write-file":
            required.add(operation["targets"][0])
        elif kind == "delete-file":
            required.add(operation["sources"][0])
        elif kind == "regenerate-projection":
            optional.add(operation["targets"][0])
        else:
            raise ValueError(f"unknown operation kind: {kind!r}")
    return required, optional


def commit_paths(worktree: Path, commit: str) -> set[str]:
    """Every path the commit changes against its parent.

    Rename detection is turned off explicitly rather than left to the default,
    so a move reports both its old and its new path — exactly the pair the
    operation declares — whatever `diff.renames` the machine carries.
    """
    out = git_or_fail(worktree, "diff-tree", "--root", "-r", "-z",
                      "--no-renames", "--no-commit-id", "--name-only", commit)
    return {chunk.decode("utf-8", "surrogateescape")
            for chunk in out.split(b"\0") if chunk}


def prove_commit_content(worktree: Path, commit: str,
                         operations: list[dict]) -> None:
    """The commit changes exactly the paths the planned operations declare.

    The gates judge the worktree *before* the commit, and the earliest of them
    — the status gate — runs before the last one executes every declared
    verification command in the checkout. Anything those commands stage, and
    anything a `pre-commit` hook stages after every gate has already passed, is
    in the index when `git commit` reads it and lands in the commit. Counting
    commits and finding the worktree clean afterwards cannot see that: both are
    still true of a commit carrying content no gate ever approved.

    So the commit's own content is proved rather than its shape. Nothing is
    amended and nothing is reset: the refusal retains the worktree and its
    branch exactly as a failed gate does, and the operator inspects what was
    smuggled in (D17).
    """
    required, optional = expected_commit_paths(operations)
    changed = commit_paths(worktree, commit)
    if not required <= changed or not changed <= required | optional:
        raise refuse(
            "verification_failed", "adopt.commit.unplanned_content", "",
            "the adoption commit does not change exactly the paths the "
            "plan's operations declare")


def prove_branch_carries_commit(root: Path, worktree: Path, branch: str,
                                base_revision: str, commit: str) -> None:
    """The three proofs D17 makes worktree removal conditional on.

    The ref holds this commit, it is the only commit the branch adds, and the
    worktree is clean. Never elapsed time.
    """
    head = git_or_fail(
        root, "rev-parse", branch).decode("ascii", "strict").strip()
    count = git_or_fail(
        worktree, "rev-list", "--count",
        f"{base_revision}..{branch}").decode("ascii", "strict").strip()
    residue = status_records(worktree)
    if head != commit or count != "1" or residue:
        raise refuse(
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
            if any(matches_group(path, target, "prefix")
                   for target in targets):
                overlapping.append(path)
    return sorted(set(overlapping))
