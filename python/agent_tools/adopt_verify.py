"""Answering the conformance question, and recording the answer in the fleet.

Everything `adopt-project verify` is made of below its command function: the
ordered conformance checks and the report they compose (R6.4, D34), the closed
result set's exit codes and registration policy, and the one write to the
user-scope fleet registry (D18, D19).

It reads one pinned revision and nothing else, as a `VerificationSource`:
plain `verify` reads `HEAD` (the resolver runs on the working tree, the
inventory comes from the index, and every record is read at the `HEAD` commit
it pins), while `--register` reads nothing from the checkout's branches or
files. It lists `origin`, fetches the remote default branch and, when the
contract there names another integration branch, that branch too, each into
`refs/remotes/origin/<branch>` (the fetched objects and those remote-tracking
refs are the only repository writes), exports the pinned commit with
`git archive` into a temporary directory removed on every exit and runs every
check there. No snapshot of a `ResolvedProject` and no capability verdict is
kept anywhere. What registration persists is exactly an identity and a
location: `{project_id, root}` with the real root (#148 D18).

The resolver is not reached from this module. `adopt-project` owns the one
seam it is consumed through — invoked as a child process through
`agent_tools.siblings.sibling_argv`, never imported (D26) — and hands that
call in.

Like its sibling libraries it is imported, never run: no `main` and no
argparse. It is a module of the `agent_tools` package, and every name it reads
from `adopt_inspection` is named in the `from` import below.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
import tempfile

from agent_tools import agent_platform
from agent_tools.adopt_inspection import (
    AdoptError,
    EVIDENCE_RECORD_DIR,
    REMOTE,
    VERIFY_RESULTS,
    blob_at,
    classify,
    commit_is_ancestor,
    evidence_records_at,
    export_commit,
    fetch_pinned,
    git_or_fail,
    has_remote,
    introducing_commit,
    is_agent_path,
    parses_as_evidence_record,
    parses_as_migration_map,
    refuse,
    remote_heads,
    resolver_error_code,
    resolver_violation_pointers,
    tracked_inventory,
    tree_inventory,
    verify_check_entry,
)

# The entry point's resolver call, as this layer receives it: `(root, *args)`
# to the resolver's exit code and its parsed JSON, or an `AdoptError`.
Resolver = Callable[..., tuple[int, object]]

VERIFY_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class VerificationSource:
    """The one revision a verification reads, pinned once.

    `ref` is the report's label for it and `commit` the 40-hex id every record
    is read at. `resolver_root` is the directory the resolver is called on and
    `inventory` the `(path, object id)` pairs the unclassified-path check
    reads. `branch` is the fetched branch name; it is always `None` for `HEAD`.
    """

    ref: str
    commit: str
    resolver_root: Path
    inventory: list[tuple[str, str]]
    branch: str | None = None


def head_source(root: Path) -> VerificationSource:
    """The source plain `verify` reads: the checkout's own `HEAD` commit."""
    commit = git_or_fail(root, "rev-parse", "--verify",
                         "HEAD^{commit}").decode("ascii", "strict").strip()
    return VerificationSource(
        ref="HEAD", commit=commit, resolver_root=root,
        inventory=tracked_inventory(root), branch=None)


@contextlib.contextmanager
def remote_source(root: Path,
                  run_resolver: Resolver) -> Iterator[VerificationSource]:
    """The source `--register` reads: the contract's integration branch.

    Nothing is read from the checkout's branches or files. `origin` is listed,
    its default branch `D` fetched into `refs/remotes/origin/D` and pinned to
    its commit `R`, and `R` exported with `git archive` into a scratch
    directory the resolver runs on. If the contract there names another
    integration branch `B`, that is the one hop made: `B` must be listed by
    `origin`, is fetched and pinned to `R2` the same way, exported, and its own
    contract must still name `B`, so there is no second hop. Every later check
    reads the one pinned commit, and the scratch directory lives as long as the
    caller's `with` block and is removed on success and on every refusal.

    No `origin` refuses `not_integrated` with `adopt.registration.no_remote`,
    an `origin` that advertises no default branch with
    `adopt.registration.remote_default_unknown`, and a `B` that `origin` does
    not list, whose contract does not resolve or does not name `B` with
    `adopt.registration.integration_branch_unresolved`. A default branch whose
    contract does not resolve is yielded as it is: `contract-resolves` then
    fails in the report.
    """
    if not has_remote(root):
        raise refuse(
            "not_integrated", "adopt.registration.no_remote", "",
            "the repository has no `origin` remote to register against")
    heads = remote_heads(root)
    default = heads.default
    if default is None:
        raise refuse(
            "not_integrated", "adopt.registration.remote_default_unknown", "",
            "`origin` does not name a default branch it also lists")
    with tempfile.TemporaryDirectory() as scratch:
        branch = default
        pinned = fetch_pinned(root, default)
        exported = Path(scratch) / "default"
        export_commit(root, pinned, exported)
        exit_code, payload = run_resolver(exported, "resolve")
        named = integration_branch(payload) if exit_code == 0 else None
        if named is not None and named != default:
            if named not in heads.branches:
                raise unresolved_integration_branch(
                    "the contract's integration branch is not a branch "
                    "`origin` lists")
            branch = named
            pinned = fetch_pinned(root, branch)
            exported = Path(scratch) / "integration"
            export_commit(root, pinned, exported)
            exit_code, payload = run_resolver(exported, "resolve")
            if exit_code != 0 or integration_branch(payload) != branch:
                raise unresolved_integration_branch(
                    "the contract on the integration branch does not resolve "
                    "or does not name that branch")
        yield VerificationSource(
            ref=f"refs/remotes/{REMOTE}/{branch}", commit=pinned,
            resolver_root=exported, inventory=tree_inventory(root, pinned),
            branch=branch)


def unresolved_integration_branch(message: str) -> AdoptError:
    return refuse(
        "not_integrated", "adopt.registration.integration_branch_unresolved",
        "", message)


def require_integrated(verification: Verification) -> None:
    """Refuse `not_integrated` when the pinned commit carries no adoption.

    Called only under `--register`, before `registration_allowed`: a remote
    revision with no adoption evidence record is not an integrated adoption
    whatever else the report says (D7).
    """
    if not verification.evidence_candidates:
        raise refuse(
            "not_integrated", "adopt.registration.not_integrated", "",
            "the remote integration branch carries no adoption evidence "
            "record")


def registration_allowed(result: str) -> bool:
    """Whether `result` may register. Every member named, default raises."""
    if result == "adopted":
        return True
    if result == "adopted_with_blockers":
        return True
    if result == "not_conformant":
        return False
    raise ValueError(f"unknown verify result: {result!r}")


def verify_exit_code(result: str) -> int:
    """The exit code each result publishes. Every member named, default raises.

    All three are 0 on purpose and each is written out rather than folded into
    one return, so a fourth result added to the closed set has to be given an
    answer here instead of inheriting a plausible success.
    """
    if result == "adopted":
        return 0
    if result == "adopted_with_blockers":
        return 0
    if result == "not_conformant":
        return 0
    raise ValueError(f"unknown verify result: {result!r}")


def resolved_project_id(payload: object) -> str | None:
    project = payload.get("project") if isinstance(payload, dict) else None
    identifier = project.get("id") if isinstance(project, dict) else None
    return identifier if isinstance(identifier, str) and identifier else None


def integration_branch(payload: object) -> str | None:
    """The contract's declared integration branch, out of the resolver's view.

    Read from the validated snapshot rather than from the contract file, for
    the reason D26 exists: the resolver is the only reader of contract policy.
    """
    bindings = payload.get("bindings") if isinstance(payload, dict) else None
    vcs = bindings.get("vcs") if isinstance(bindings, dict) else None
    branch = vcs.get("integration_branch") if isinstance(vcs, dict) else None
    return branch if isinstance(branch, str) and branch else None


def blocked_capabilities(payload: object) -> list[dict]:
    """Every declared capability the host cannot deliver, and its repair id.

    `unsupported` is a deliberate absence and never a blocker; only `blocked`
    is a capability the contract claims and the machine withholds (R6.4).
    """
    capabilities = payload.get("capabilities") if isinstance(payload, dict) \
        else None
    if not isinstance(capabilities, dict):
        return []
    return [{"capability": name, "repair_id": entry.get("repair_id")}
            for name, entry in sorted(capabilities.items())
            if isinstance(entry, dict) and entry.get("state") == "blocked"]


def projection_check(root: Path,
                     run_resolver: Resolver) -> tuple[str, str | None]:
    """The `projections-in-sync` verdict and the reason it failed.

    Drift is the resolver's `invalid_projection` refusal, whose violation
    pointers name each drifted projection by id, so the reason published here
    is the resolver's own answer rather than a second opinion about it.
    """
    exit_code, payload = run_resolver(root, "check-projections")
    if exit_code == 0 and isinstance(payload, dict):
        entries = payload.get("projections")
        if isinstance(entries, list) and all(
                isinstance(entry, dict) and entry.get("action") == "unchanged"
                for entry in entries):
            return "passed", None
    code = resolver_error_code(payload)
    # Drift is one refusal — `invalid_projection`, whose pointers name the
    # drifted projections by id. Every other refusal carries pointers too
    # (`not_onboarded` carries one empty pointer), so reading them as drift
    # would put a false claim in the row a diagnostic verb exists to publish.
    if code == "invalid_projection":
        return "failed", ("the projection targets have drifted: "
                          + ", ".join(resolver_violation_pointers(payload)))
    return "failed", f"the projections could not be checked: {code}"


class Verification:
    """One repository's conformance verdict, and what registration needs.

    `report` is exactly what is printed. `resolve_payload` is kept beside it
    rather than folded in, because the integration branch registration checks
    is contract policy the report has no business publishing. `source` is the
    pinned revision the report was read at, which registration walks ancestry
    from, and `evidence_candidates` every adoption evidence record path found
    in it, which `require_integrated` reads: an empty list is no adoption.
    """

    def __init__(self, report: dict, resolve_payload: object,
                 source: VerificationSource,
                 evidence_candidates: list[str]) -> None:
        self.report = report
        self.resolve_payload = resolve_payload
        self.source = source
        self.evidence_candidates = evidence_candidates


def verify_repository(root: Path, source: VerificationSource,
                      run_resolver: Resolver) -> Verification:
    """Run the ordered conformance checks and build the report.

    Every check runs where its inputs exist and is recorded as `not_run` where
    they do not, so a report always carries one row per declared check: an
    absent evidence record is a named failure with two consequences, never two
    silent omissions.
    """
    checks: list[dict] = []

    def record(check_id: str, status: str, detail: str | None) -> None:
        checks.append(verify_check_entry(
            check_id, status, detail))

    exit_code, payload = run_resolver(source.resolver_root, "resolve")
    resolves = exit_code == 0 and isinstance(payload, dict)
    record("contract-resolves", "passed" if resolves else "failed",
           None if resolves else
           f"the contract does not resolve: {resolver_error_code(payload)}")

    # Asked even when `resolve` refused, because the commonest reason it
    # refuses *is* projection drift: reporting the drift as "not run" would
    # hide the one check that names which projection went stale.
    record("projections-in-sync",
           *projection_check(source.resolver_root, run_resolver))

    unclassified = sorted(
        path for path, _ in source.inventory
        if classify(path) is None
        and is_agent_path(path))
    record("no-unclassified-agent-path",
           "failed" if unclassified else "passed",
           ("no lifecycle class covers: " + ", ".join(unclassified))
           if unclassified else None)

    record_path, map_path = None, None
    candidates = evidence_records_at(root, source.commit)
    if not candidates:
        record("adoption-evidence-record", "failed",
               "no adoption evidence record is committed under "
               f"{EVIDENCE_RECORD_DIR}/")
    elif len(candidates) > 1:
        record("adoption-evidence-record", "failed",
               "more than one adoption evidence record is committed: "
               + ", ".join(candidates))
    else:
        found = parses_as_evidence_record(
            blob_at(root, source.commit, candidates[0]))
        if found is None:
            record("adoption-evidence-record", "failed",
                   "the committed file does not parse as an adoption "
                   f"evidence record: {candidates[0]}")
        else:
            record_path = candidates[0]
            map_path = found["path_migration_map"]
            record("adoption-evidence-record", "passed", None)

    commit = None
    if record_path is None:
        record("adoption-commit-derived", "not_run",
               "no adoption evidence record was discovered")
    else:
        commit = introducing_commit(root, source.commit, record_path)
        record("adoption-commit-derived",
               "failed" if commit is None else "passed",
               None if commit is not None else
               "git records no commit introducing the adoption evidence "
               f"record: {record_path}")

    if record_path is None:
        record("path-migration-map", "not_run",
               "no adoption evidence record was discovered")
        map_path = None
    elif not isinstance(map_path, str) or not map_path:
        record("path-migration-map", "failed",
               "the evidence record names no path migration map")
        map_path = None
    elif parses_as_migration_map(
            blob_at(root, source.commit, map_path)) is None:
        record("path-migration-map", "failed",
               f"the path migration map is absent or does not parse: "
               f"{map_path}")
    else:
        record("path-migration-map", "passed", None)

    blockers = blocked_capabilities(payload) if resolves else []
    if any(entry["status"] != "passed" for entry in checks):
        result = "not_conformant"
    elif blockers:
        result = "adopted_with_blockers"
    else:
        result = "adopted"
    # Defence in depth behind the two exhaustive dispatches below: a result
    # invented here crashes rather than reaching an operator.
    if result not in VERIFY_RESULTS:
        raise ValueError(f"unknown verify result: {result!r}")

    return Verification({
        "schema_version": VERIFY_SCHEMA_VERSION,
        "result": result,
        "project_id": resolved_project_id(payload),
        "root": str(root),
        "revision": {"ref": source.ref, "commit": source.commit},
        "adoption_commit": commit,
        "evidence_record": record_path,
        "migration_map": map_path,
        "checks": checks,
        "blockers": blockers,
        "registered": False,
    }, payload, source, candidates)


def register_project(root: Path, verification: Verification) -> None:
    """Record `{project_id, root}` in the fleet, or refuse and change nothing.

    The root is the real checkout's, not the temporary directory the checks ran
    in. The ancestry check is the ordering #67 documents and D19 makes checked:
    a commit that lives only on a feature branch names a state the integration
    branch does not have. It is walked from the pinned commit id of the fetched
    remote branch, never a branch name (D7); an adoption commit that is not its
    ancestor refuses `not_integrated`. The duplicate check and the
    replacement then happen inside one exclusive lock over a registry reread
    underneath it, so two registrations racing under one `HOME` serialize
    instead of one overwriting the other.
    """
    report = verification.report
    source = verification.source
    project_id = report["project_id"]
    commit = report["adoption_commit"]
    branch = integration_branch(verification.resolve_payload)
    if branch is None or project_id is None or commit is None:
        raise refuse(
            "adopt_failure", "adopt.registration.incomplete", "",
            "registration needs a project id, an adoption commit and a "
            "declared integration branch")
    if source.branch is None or branch != source.branch:
        raise refuse(
            "not_integrated", "adopt.registration.integration_branch_unresolved",
            "", "the contract's integration branch is not the remote branch "
            "the verification read")
    if not commit_is_ancestor(root, commit, source.commit):
        raise refuse(
            "not_integrated", "adopt.registration.not_integrated", "",
            "the adoption commit is not reachable from the remote "
            "integration branch")
    try:
        with agent_platform.registry_transaction() as entries:
            for entry in entries:
                if entry["project_id"] != project_id:
                    continue
                if Path(entry["root"]).resolve() != root:
                    raise refuse(
                        "duplicate_project_id", "adopt.registry.duplicate",
                        "/projects",
                        "the fleet registry already holds this project id at "
                        "another root")
            agent_platform.write_registry(
                [entry for entry in entries
                 if entry["project_id"] != project_id]
                + [{"project_id": project_id, "root": str(root)}])
    except agent_platform.PlatformManifestError as error:
        raise AdoptError(
            "adopt_failure", "adopt.registry.invalid",
            error.violations) from None
    report["registered"] = True
