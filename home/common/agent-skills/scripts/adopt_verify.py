"""Answering the conformance question, and recording the answer in the fleet.

Everything `adopt-project verify` is made of below its command function: the
ordered conformance checks and the report they compose (R6.4, D34), the closed
result set's exit codes and registration policy, and the one write to the
user-scope fleet registry (D18, D19).

It reads the *committed* state and nothing else: no working-tree bytes, no
snapshot of a `ResolvedProject`, no capability verdict kept anywhere. What
registration persists is exactly an identity and a location.

The resolver is not reached from this module. `adopt-project` owns the one
seam it is consumed through — invoked as a child process at the absolute path
`$HOME/.agents/bin/resolve-project`, never imported (D26) — and hands that
call in.

Like its sibling libraries it is imported, never run: no `main` and no
argparse. It is installed at `$HOME/.agents/lib/python/` behind the entry
point's member guard, and every name it reads from `adopt_inspection` is named
in the `from` import below, so an installation pairing an older library with a
newer binary refuses as `adopt.library.missing` through the D12 error object
rather than as an `AttributeError`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import agent_platform
from adopt_inspection import (
    AdoptError,
    EVIDENCE_RECORD_DIR,
    VERIFY_RESULTS,
    blob_at_head,
    classify,
    commit_is_ancestor,
    introducing_commit,
    is_agent_path,
    parses_as_evidence_record,
    parses_as_migration_map,
    refuse,
    resolver_error_code,
    resolver_violation_pointers,
    tracked_evidence_records,
    tracked_inventory,
    verify_check_entry,
)

# The entry point's resolver call, as this layer receives it: `(root, *args)`
# to the resolver's exit code and its parsed JSON, or an `AdoptError`.
Resolver = Callable[..., tuple[int, object]]

VERIFY_SCHEMA_VERSION = 1


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
    is contract policy the report has no business publishing.
    """

    def __init__(self, report: dict, resolve_payload: object) -> None:
        self.report = report
        self.resolve_payload = resolve_payload


def verify_repository(root: Path, run_resolver: Resolver) -> Verification:
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

    exit_code, payload = run_resolver(root, "resolve")
    resolves = exit_code == 0 and isinstance(payload, dict)
    record("contract-resolves", "passed" if resolves else "failed",
           None if resolves else
           f"the contract does not resolve: {resolver_error_code(payload)}")

    # Asked even when `resolve` refused, because the commonest reason it
    # refuses *is* projection drift: reporting the drift as "not run" would
    # hide the one check that names which projection went stale.
    record("projections-in-sync", *projection_check(root, run_resolver))

    unclassified = sorted(
        path for path, _ in tracked_inventory(root)
        if classify(path) is None
        and is_agent_path(path))
    record("no-unclassified-agent-path",
           "failed" if unclassified else "passed",
           ("no lifecycle class covers: " + ", ".join(unclassified))
           if unclassified else None)

    record_path, map_path = None, None
    candidates = tracked_evidence_records(root)
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
            blob_at_head(root, candidates[0]))
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
        commit = introducing_commit(root, record_path)
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
            blob_at_head(root, map_path)) is None:
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
        "adoption_commit": commit,
        "evidence_record": record_path,
        "migration_map": map_path,
        "checks": checks,
        "blockers": blockers,
        "registered": False,
    }, payload)


def register_project(root: Path, verification: Verification) -> None:
    """Record `{project_id, root}` in the fleet, or refuse and change nothing.

    The ancestry check comes first because it is the ordering #67 documents and
    D19 makes checked: a commit that lives only on a feature branch names a
    state the integration branch does not have. The duplicate check and the
    replacement then happen inside one exclusive lock over a registry reread
    underneath it, so two registrations racing under one `HOME` serialize
    instead of one overwriting the other.
    """
    report = verification.report
    branch = integration_branch(verification.resolve_payload)
    project_id = report["project_id"]
    commit = report["adoption_commit"]
    if branch is None or project_id is None or commit is None:
        raise refuse(
            "adopt_failure", "adopt.registration.incomplete", "",
            "registration needs a project id, an adoption commit and a "
            "declared integration branch")
    if not commit_is_ancestor(root, commit, branch):
        raise refuse(
            "not_integrated", "adopt.registration.not_integrated", "",
            "the adoption commit is not reachable from the contract's "
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
