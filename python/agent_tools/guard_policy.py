"""Compile the lifecycle guard's policy from the fleet registry (issue 126).

`guard-policy compile --base <path> --output <path>` reads the base policy, the
fleet registry (`agent_platform.read_registry`) and, for each registered
project, the contract on its registered branch of `origin`: the checkout's
working tree, index and local branches are never read. A project earns a
derived row only when all twelve proof steps hold in this run and the guard's
loader accepts the row's slug and two branch names (`unsupported_name`); the
steps are `derive`, `target_profiles` and `compile_policy`, and each refusal
carries one of `REASON_CODES`.

It writes one JSON document with exactly two members, `derived_repositories` and
`derivation` (`derivation.schema_version` is `DERIVATION_SCHEMA_VERSION`),
atomically to `--output`; the base policy is only validated and consulted for
`literal_conflict`, and none of its members is copied into the output. Evidence is identity only: a
digest of the registry entry, the pinned commit and contract blob, the
provider's answer and each profile's version and digest. No resolved snapshot
and no contract body is kept. The only repository writes are the
remote-tracking refs of the branches read and the fetched objects.

Exit statuses: 0 when every entry derived (an absent registry is the empty
fleet), 1 when the file was written but at least one project has no row, and 2
when no policy could be compiled, in which case no file is left at `--output`.
The report, one line of JSON on stdout, names the outcome, the derived slugs,
each refusal and the cause of an exit 2 (`CAUSES`).

`guard-policy derive --repository <slug>` re-derives one repository's row, the
check the lifecycle guard runs before it trusts a compiled row. It reads the
registry, runs the first two proof steps for every entry (`entry_slug`) and the
rest (`prove`) only for entries whose `origin` names the slug, then the duplicate
and name checks among them (`_admit`); it reads no base policy, so it never
reports `literal_conflict`, and it writes no file beyond the fetched objects and
remote-tracking refs. The report, one line of JSON on stdout, has the members
`schema_version`, `repository`, `outcome`, `row`, `refused` and `cause`. Exit 0
is `derived` with the row; exit 1 is `refused`, with the `refused` entries that
name the slug (empty when none does); exit 2 is `unavailable`, with a `cause`
from `CAUSES` (`registry_invalid`, `platform_unavailable` or `internal`).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from agent_tools import (adopt_inspection, adopt_verify, agent_platform, canonical, forge_adapter,
                         github_remote, release_profile, resolve_project)

REPORT_SCHEMA_VERSION = 1
DERIVE_REPORT_SCHEMA_VERSION = 1
DERIVATION_SCHEMA_VERSION = 2

BASE_MEMBERS = ("authorized_owners", "integration_bases", "git_bin", "gh_bin", "jq_bin")
POLICY_MEMBERS = ("derived_repositories", "derivation")
TOOL_MEMBERS = ("git_bin", "gh_bin", "jq_bin")

REASON_CODES = (
    "root_unavailable", "origin_unproven", "branch_unresolved", "fetch_failed",
    "contract_unresolved", "identity_mismatch", "tracker_mismatch", "no_forge_target",
    "target_mismatch", "profile_inadmissible", "branch_mismatch", "provider_unproven",
    "duplicate_repository", "literal_conflict", "name_unsupported",
)
CAUSES = ("base_invalid", "registry_invalid", "platform_unavailable", "output_unwritable",
          "internal")

BRANCH_UNRESOLVED_REPAIRS = ("adopt.registration.remote_default_unknown",
                             "adopt.registration.integration_branch_unresolved")

# The shapes the lifecycle guard's `load_compiled_policy` demands of a derived
# row's key and of its two branches (`SLUG_PATTERN` and `REF_NAME_PATTERN` in
# `home/common/claude-code/lifecycle_guard.py`). The guard drops the whole
# compiled policy over one row outside them, and git and the contract grammar both take
# names it does not, such as `dev+ci`. The guard is a standalone file this
# package cannot import, so the two are restated here and the guard suite's
# round trip holds them to what the built guard loads.
GUARD_SLUG = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")
GUARD_REF_NAME = re.compile(r"[A-Za-z0-9._/-]+")


class ProjectRefused(Exception):
    """One project has no derived row; `reason_code` is a member of `REASON_CODES`."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        if reason_code not in REASON_CODES:
            raise ValueError(f"unknown reason code: {reason_code!r}")
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


class CompileRefused(Exception):
    """No policy can be compiled; `cause` is a member of `CAUSES`."""

    def __init__(self, cause: str, detail: str = "") -> None:
        if cause not in CAUSES:
            raise ValueError(f"unknown cause: {cause!r}")
        super().__init__(f"{cause}: {detail}")
        self.cause = cause
        self.detail = detail


# --------------------------------------------------------------------------
# The base policy
# --------------------------------------------------------------------------


def _strict_load(text: str) -> object:
    return json.loads(text, object_pairs_hook=canonical.reject_duplicate_keys,
                      parse_constant=canonical.reject_nonfinite_literal)


def _is_name(value: object) -> bool:
    return isinstance(value, str) and value != ""


def read_base(path: Path) -> dict:
    """The base policy at `path`; `CompileRefused("base_invalid", ...)` unless it is one."""
    def invalid(detail: str) -> CompileRefused:
        return CompileRefused("base_invalid", f"{path}: {detail}")

    try:
        base = _strict_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise invalid(f"could not be read as JSON ({type(error).__name__})") from None
    if not isinstance(base, dict) or set(base) != set(BASE_MEMBERS):
        raise invalid(f"must be an object with exactly {', '.join(BASE_MEMBERS)}")
    owners, bases = base["authorized_owners"], base["integration_bases"]
    if not isinstance(owners, list) or not all(_is_name(owner) for owner in owners):
        raise invalid("authorized_owners must be a list of non-empty strings")
    if not isinstance(bases, dict) or not all(_is_name(branch) for branch in bases.values()):
        raise invalid("integration_bases must be an object of non-empty strings")
    for member in TOOL_MEMBERS:
        if not (_is_name(base[member]) and Path(base[member]).is_absolute()):
            raise invalid(f"{member} must be an absolute path")
    return base


# --------------------------------------------------------------------------
# The identity children
# --------------------------------------------------------------------------


def _identity_read(argv: list[str], root: Path) -> tuple[str | None, str]:
    """`(stdout, "")` of `argv` run by name in `root`, or `(None, why)` when the read failed.

    The child never sees a token variable, is never prompted for credentials,
    reads nothing from stdin and is killed after `CHILD_TIMEOUT_SECONDS`; a
    timeout or a missing executable is a failed read like a non-zero exit. `why`
    is `timed out`, the `OSError` text, or `exit <n>` with the child's stderr, so a
    refusal says which of them it was.
    """
    env = {name: value for name, value in os.environ.items()
           if name not in forge_adapter.TOKEN_VARIABLES}
    env.update(GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1")
    try:
        done = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                              timeout=forge_adapter.CHILD_TIMEOUT_SECONDS, env=env, cwd=root,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return None, "timed out"
    except (OSError, subprocess.SubprocessError) as error:
        return None, str(error) or type(error).__name__
    if done.returncode == 0:
        return done.stdout, ""
    stderr = done.stderr.strip()[:forge_adapter.DETAIL_LIMIT]
    return None, f"exit {done.returncode}: {stderr}" if stderr else f"exit {done.returncode}"


def origin_slug(root: Path) -> str:
    """Step 2: the one github.com slug origin's fetch url and single push url name."""
    fetch, fetch_why = _identity_read(["git", "remote", "get-url", "origin"], root)
    pushes, push_why = _identity_read(["git", "remote", "get-url", "--push", "--all", "origin"],
                                      root)
    if fetch is None or pushes is None:
        raise ProjectRefused("origin_unproven", "origin's urls could not be read: "
                             + (f"fetch: {fetch_why}" if fetch is None else f"push: {push_why}"))
    push_urls = [line.strip() for line in pushes.splitlines() if line.strip()]
    if len(push_urls) != 1:
        raise ProjectRefused("origin_unproven",
                             f"origin has {len(push_urls)} push urls, not one")
    slug = github_remote.github_slug(fetch)
    if slug is None:
        raise ProjectRefused("origin_unproven", "origin's fetch url is not a github.com url")
    if github_remote.github_slug(push_urls[0]) != slug:
        raise ProjectRefused("origin_unproven",
                             f"origin's push url does not name {slug}, its fetch url's slug")
    return slug


# --------------------------------------------------------------------------
# The proof
# --------------------------------------------------------------------------


def resolver(root: Path, command: str) -> tuple[int, object]:
    """`remote_source`'s resolver seam, in process: `(0, snapshot)` or `(2, error object)`."""
    if command != "resolve":
        raise ValueError(f"unknown resolver command: {command!r}")
    try:
        return 0, resolve_project.resolve(str(root))
    except resolve_project.ContractError as error:
        return 2, {"error": {"code": error.code, "repair_id": error.repair_id}}


def target_profiles(entry: dict, slug: str, snapshot: dict) -> list[str]:
    """Steps 5 to 8: the sorted ids of the profiles whose forge target selects `slug`."""
    if snapshot["project"]["id"] != entry["project_id"]:
        raise ProjectRefused("identity_mismatch", "the contract declares project "
                             f"{snapshot['project']['id']}, not {entry['project_id']}")
    bindings = snapshot["bindings"]
    tracker = bindings["tracker"]
    if tracker.get("kind") != "github" or tracker.get("repo_slug") != slug:
        raise ProjectRefused("tracker_mismatch",
                             f"the contract's tracker is not the github repository {slug}")
    targets = [item for item in snapshot["release"]["targets"]
               if item["target"]["kind"] == "github_repository"]
    if not targets:
        raise ProjectRefused("no_forge_target", "the contract declares no github_repository "
                             "release target")
    for item in targets:
        target = item["target"]
        if target["repository"] != slug or target["branch"] != bindings["vcs"]["default_branch"]:
            raise ProjectRefused(
                "target_mismatch", f"profile {item['profile']} targets {target['repository']} "
                f"on {target['branch']}, not {slug} on the default branch")
    return sorted({item["profile"] for item in targets})


def _compiled_profiles(profile_ids: list[str], contract: dict) -> list[dict]:
    compiled = []
    for profile_id in profile_ids:
        try:
            profile = release_profile.compile_profile(
                profile_id, contract["release"]["profiles"][profile_id], contract)
        except (release_profile.ProfileInadmissible, ValueError) as error:
            raise ProjectRefused("profile_inadmissible", f"{profile_id}: {error}") from None
        compiled.append({"id": profile_id, "version": profile["profile_version"],
                         "digest": profile["digest"]})
    return compiled


def _proof(root: Path, entry: dict, slug: str, source: adopt_verify.VerificationSource) -> dict:
    """Steps 4 and 5 to 10 over the pinned `source`: the row for `slug`."""
    status, payload = resolver(source.resolver_root, "resolve")
    if status != 0:
        raise ProjectRefused("contract_unresolved", "the resolver refused the contract on "
                             f"{source.ref}: {adopt_inspection.resolver_repair_id(payload)}")
    contract = resolve_project.load_contract(source.resolver_root)
    compiled = _compiled_profiles(target_profiles(entry, slug, payload), contract)
    vcs = payload["bindings"]["vcs"]
    if vcs["integration_branch"] != source.branch or vcs["default_branch"] != source.remote_default:
        raise ProjectRefused(
            "branch_mismatch", f"the contract names {vcs['default_branch']} and "
            f"{vcs['integration_branch']}; origin's default is {source.remote_default} and "
            f"the branch read is {source.branch}")
    answer, why = _identity_read(["gh", "api", f"repos/{slug}", "--jq", ".full_name"], root)
    if answer is None:
        raise ProjectRefused("provider_unproven", f"gh api repos/{slug} failed: {why}")
    if answer.strip() != slug:
        raise ProjectRefused("provider_unproven",
                             f"gh api repos/{slug} answered {answer.strip()!r}, not {slug}")
    code, blob = adopt_inspection.run_git(root, "rev-parse", "--verify", "--quiet",
                                          f"{source.commit}:{adopt_inspection.CONTRACT_FILENAME}")
    if code != 0:
        raise ProjectRefused("contract_unresolved", f"{source.commit} holds no contract blob")
    return {"default_branch": vcs["default_branch"], "integration_branch": vcs["integration_branch"],
            "evidence": {
                "project_id": entry["project_id"],
                "registry_entry_digest": canonical.telemetry_digest(entry),
                "source": {"ref": source.ref, "commit": source.commit},
                "contract_blob": blob.decode("ascii", "replace").strip(),
                "provider_full_name": answer.strip(), "profiles": compiled}}


def entry_slug(entry: dict) -> tuple[Path, str]:
    """Steps 1 and 2 for one registry entry: `(root, slug)`, or `ProjectRefused`."""
    root = Path(entry["root"])
    try:
        code, _ = adopt_inspection.run_git(root, "rev-parse", "--git-dir")
    except adopt_inspection.AdoptError:
        code = 1
    if code != 0:
        raise ProjectRefused("root_unavailable", f"{root} is not a git repository")
    return root, origin_slug(root)


def prove(entry: dict, root: Path, slug: str) -> dict:
    """Steps 3 to 10 for one registry entry at `root` whose origin names `slug`: the row."""
    override = entry.get("branch_override")
    try:
        with adopt_verify.remote_source(
                root, resolver, override["branch"] if override else None,
                network_timeout=forge_adapter.CHILD_TIMEOUT_SECONDS) as source:
            return _proof(root, entry, slug, source)
    except adopt_inspection.AdoptError as error:
        reason = ("branch_unresolved" if error.repair_id in BRANCH_UNRESOLVED_REPAIRS
                  else "fetch_failed")
        raise ProjectRefused(reason, f"{error.repair_id}: "
                             f"{error.violations[0]['message']}") from None


def derive(entry: dict) -> tuple[str, dict]:
    """Steps 1 to 10 for one registry entry: `(slug, derived row)`, or `ProjectRefused`."""
    root, slug = entry_slug(entry)
    return slug, prove(entry, root, slug)


# --------------------------------------------------------------------------
# The fleet
# --------------------------------------------------------------------------


def unsupported_name(slug: str, row: dict) -> str | None:
    """The first of `slug` and `row`'s two branches the guard's loader refuses, or None."""
    for member, name, shape in (("repository", slug, GUARD_SLUG),
                                ("default_branch", row["default_branch"], GUARD_REF_NAME),
                                ("integration_branch", row["integration_branch"],
                                 GUARD_REF_NAME)):
        if shape.fullmatch(name) is None:
            return (f"{member} {name!r} is not a name the lifecycle guard loads, and one such "
                    "row would make it drop the whole compiled policy")
    return None


def _refusal(entry: dict, error: ProjectRefused) -> dict:
    return {"project_id": entry["project_id"], "root": entry["root"],
            "reason_code": error.reason_code,
            "detail": error.detail[:forge_adapter.DETAIL_LIMIT]}


def _admit(proven: list[tuple[dict, str, dict]],
           literal_slugs) -> tuple[dict[str, dict], list[dict]]:
    """Step 11 and the rest of admission over the proven `(entry, slug, row)` triples:
    `(rows by slug, refusals)`. A slug in `literal_slugs` is `literal_conflict`."""
    derived_by = [slug for _, slug, _ in proven]
    rows: dict[str, dict] = {}
    refusals: list[dict] = []
    for entry, slug, row in proven:
        if derived_by.count(slug) > 1:
            refusals.append(_refusal(entry, ProjectRefused(
                "duplicate_repository", f"more than one registered project derives {slug}")))
        elif slug in literal_slugs:
            refusals.append(_refusal(entry, ProjectRefused(
                "literal_conflict", f"{slug} is also a literal integration base")))
        elif (unsupported := unsupported_name(slug, row)) is not None:
            refusals.append(_refusal(entry, ProjectRefused("name_unsupported", unsupported)))
        else:
            rows[slug] = row
    return rows, refusals


def derive_repository(entries: list[dict], repository: str) -> tuple[dict | None, list[dict]]:
    """`(row, refusals)` for `repository`: only entries whose origin names it are proven."""
    proven: list[tuple[dict, str, dict]] = []
    refusals: list[dict] = []
    for entry in entries:
        try:
            root, slug = entry_slug(entry)
        except ProjectRefused:
            continue
        if slug != repository:
            continue
        try:
            proven.append((entry, slug, prove(entry, root, slug)))
        except ProjectRefused as error:
            refusals.append(_refusal(entry, error))
    rows, more = _admit(proven, frozenset())
    return rows.get(repository), refusals + more


def compile_policy(base: dict, entries: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    """`(derived rows, refusals)`: `derive` per entry, then steps 11 and 12 and the loader's
    name shapes, so every row returned is one the guard loads. A slug the base policy holds
    as a literal integration base is `literal_conflict`; the literal stays in the base."""
    proven: list[tuple[dict, str, dict]] = []
    refusals: list[dict] = []
    for entry in entries:
        try:
            slug, row = derive(entry)
        except ProjectRefused as error:
            refusals.append(_refusal(entry, error))
        else:
            proven.append((entry, slug, row))
    rows, more = _admit(proven, base["integration_bases"])
    return rows, refusals + more


# --------------------------------------------------------------------------
# The command
# --------------------------------------------------------------------------


def _report(outcome: str, derived: list[str], refused: list[dict],
            cause: dict | None) -> dict:
    return {"schema_version": REPORT_SCHEMA_VERSION, "outcome": outcome,
            "derived": sorted(derived), "refused": refused, "cause": cause}


def _platform_refusal(cause: str, error: agent_platform.PlatformManifestError) -> CompileRefused:
    first = error.violations[0]
    return CompileRefused(cause, f"{error.repair_id}: {first['pointer']}: {first['message']}")


def _write(base: dict, entries: list[dict], platform_version: str,
           output: Path) -> tuple[int, dict]:
    rows, refusals = compile_policy(base, entries)
    registry_digest = None
    if agent_platform.registry_path().exists():
        registry_digest = canonical.telemetry_digest(
            {"schema_version": agent_platform.REGISTRY_SCHEMA_VERSION, "projects": entries})
    document = {"derived_repositories": rows,
                "derivation": {"schema_version": DERIVATION_SCHEMA_VERSION,
                               "platform_version": platform_version,
                               "registry_digest": registry_digest}}
    try:
        agent_platform.write_atomically(
            output, (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    except OSError as error:
        raise CompileRefused("output_unwritable", f"{output}: {error}") from None
    outcome, status = ("written_with_refusals", 1) if refusals else ("complete", 0)
    return status, _report(outcome, list(rows), refusals, None)


def _derive_report(repository: str, outcome: str, row: dict | None, refused: list[dict],
                   cause: dict | None) -> dict:
    return {"schema_version": DERIVE_REPORT_SCHEMA_VERSION, "repository": repository,
            "outcome": outcome, "row": row, "refused": refused, "cause": cause}


def run_derive(repository: str) -> tuple[int, dict]:
    """The exit status and the report of re-deriving `repository`'s row; writes no file."""
    try:
        try:
            agent_platform.load_manifest()
        except agent_platform.PlatformManifestError as error:
            raise _platform_refusal("platform_unavailable", error) from None
        try:
            entries = agent_platform.read_registry()
        except agent_platform.PlatformManifestError as error:
            raise _platform_refusal("registry_invalid", error) from None
        row, refusals = derive_repository(entries, repository)
    except CompileRefused as error:
        cause = {"reason_code": error.cause, "detail": error.detail}
    except Exception as error:  # a closed cause for any failure: the guard reads one report
        cause = {"reason_code": "internal", "detail": f"{type(error).__name__}: {error}"}
    else:
        if row is not None:
            return 0, _derive_report(repository, "derived", row, refusals, None)
        return 1, _derive_report(repository, "refused", None, refusals, None)
    return 2, _derive_report(repository, "unavailable", None, [], cause)


def _remove_previous(output: Path, cause: dict) -> None:
    """Leave no file at `output`; a removal that fails says so in the cause it does not replace."""
    try:
        with contextlib.suppress(FileNotFoundError, NotADirectoryError):
            output.unlink()
    except OSError as error:
        cause["detail"] += f"; could not remove the previous policy: {error}"


def run_compile(base_path: Path, output: Path) -> tuple[int, dict]:
    """The exit status and the report; writes `output` atomically or leaves no file there."""
    try:
        base = read_base(base_path)
        # Before any project: the resolver would read a missing manifest as every
        # project's contract being unresolved, and the cause is the installation's.
        try:
            platform_version = agent_platform.load_manifest()[0]["platform_version"]
        except agent_platform.PlatformManifestError as error:
            raise _platform_refusal("platform_unavailable", error) from None
        try:
            entries = agent_platform.read_registry()
        except agent_platform.PlatformManifestError as error:
            raise _platform_refusal("registry_invalid", error) from None
        return _write(base, entries, platform_version, output)
    except CompileRefused as error:
        cause = {"reason_code": error.cause, "detail": error.detail}
    except Exception as error:  # a closed cause for any failure: the file must still go
        cause = {"reason_code": "internal", "detail": f"{type(error).__name__}: {error}"}
    _remove_previous(output, cause)
    return 2, _report("refused", [], [], cause)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guard-policy", description="Compile the lifecycle guard's policy.")
    commands = parser.add_subparsers(dest="command", required=True)
    compile_command = commands.add_parser("compile", help="write the compiled policy")
    compile_command.add_argument("--base", required=True, type=Path,
                                 help="the base policy file")
    compile_command.add_argument("--output", required=True, type=Path,
                                 help="where the compiled policy is written")
    derive_command = commands.add_parser("derive", help="re-derive one repository's row")
    derive_command.add_argument("--repository", required=True, help="the owner/name slug")
    return parser


def _print_refusals(report: dict) -> None:
    for refusal in report["refused"]:
        print(f"guard-policy: {refusal['project_id']} ({refusal['root']}) has no derived row: "
              f"{refusal['reason_code']}: {refusal['detail']}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "derive":
        status, report = run_derive(args.repository)
        _print_refusals(report)
        if report["cause"] is not None:
            print(f"guard-policy: no row was derived: {report['cause']['reason_code']}: "
                  f"{report['cause']['detail']}", file=sys.stderr)
    else:
        status, report = run_compile(args.base, args.output)
        _print_refusals(report)
        if report["cause"] is not None:
            print(f"guard-policy: no policy was written: {report['cause']['reason_code']}: "
                  f"{report['cause']['detail']}", file=sys.stderr)
    print(json.dumps(report, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
