"""Compile the lifecycle guard's policy from the fleet registry (issue 126).

`guard-policy compile --base <path> --output <path>` reads the base policy, the
fleet registry (`agent_platform.read_registry`) and, for each registered
project, the contract on its registered branch of `origin`, through
`adopt_verify.remote_source` with the resolver run in process (issue 126 D13):
the checkout's working tree, index and local branches are never read. Each
branch is read at the commit `origin` lists for it, through
`adopt_verify.SourceReader`: `adopt_inspection.pin_listed` fetches the branch
only when the checkout lacks that commit, and `contract_export.export_contract`
exports the contract and its projection files (`resolve_project.projection_paths`)
sparsely (`contract_export`), with no tree inventory. The base policy must be an
object with exactly the five trusted members `authorized_owners`,
`integration_bases`, `git_bin`, `gh_bin` and `jq_bin`, where the owners and
branches are non-empty strings and the three tools are absolute paths; anything
else, an unreadable file included, is the cause `base_invalid`.

Row derivation. A project earns a derived row only when twelve steps all hold in
this run and the guard can load the row, and the first of those to fail names
the reason code of its refusal (one of `REASON_CODES`). `derive` runs steps 1 to
10: the registered root is a git repository (`root_unavailable`); `origin`'s
fetch url and its single push url name one `github.com` slug, spelt as
`github_remote.github_slug` reads it and never case-folded (`origin_unproven`,
issue 126 D9); `origin` yields a default branch and the contract's branch
(`branch_unresolved` for `adopt.registration.remote_default_unknown` and
`adopt.registration.integration_branch_unresolved`, `fetch_failed` for every
other `AdoptError`); the resolver accepts that contract (`contract_unresolved`,
with its repair id in the detail). `target_profiles` runs steps 5 to 8 on the
resolved snapshot: the contract's project id is the registered one
(`identity_mismatch`), its tracker is the `github` repository named by the slug
(`tracker_mismatch`), it has a `github_repository` release target
(`no_forge_target`), and every such target names the slug and the default
branch (`target_mismatch`); each selected profile then compiles through
`release_profile.compile_profile` (`profile_inadmissible`). Step 9 requires the
contract's integration and default branches to be the branch read and
`origin`'s default (`branch_mismatch`), and step 10 that `gh api repos/<slug>
--jq .full_name` answers the slug (`provider_unproven`). `compile_policy` runs
steps 11 and 12 over the projects that passed: a slug derived by more than one
is `duplicate_repository` for each, and a slug that is also a key of the base
`integration_bases` is `literal_conflict`: that project gets no row and the
literal row stays in the base policy, and each compile reports the conflict
(issue 377 D5). A project that passed all twelve is then refused
`name_unsupported` when `unsupported_name` finds its slug or either of its
branches outside the shapes the guard's `load_compiled_policy` demands of a
derived row: git and the contract grammar take a branch such as `dev+ci`, and
the guard drops the whole compiled policy over one such row, which removes every
derived row and blocks nothing the base policy allows (issue 377 D4). The guard
is a standalone file the package cannot import, so this module restates its two
shapes as `GUARD_SLUG` and `GUARD_REF_NAME`, and a guard-suite test holds them
to the built guard by loading a policy compiled from a fleet that has such a
branch.

Every child of the identity steps, the two `git remote get-url` reads and the
`gh api` read, runs by name with `cwd` at the registered root, stdin at
`/dev/null`, `GIT_TERMINAL_PROMPT=0`, `GH_PROMPT_DISABLED=1`, a 30-second timeout
and `GITHUB_TOKEN` and `GH_TOKEN` removed, so `gh` answers with the keyring
credential (issue 126 D7); the fetch and the listing are bounded at the same 30
seconds. A timeout or a missing executable is a failed read. A failed read puts
its reason in the refusal's detail (`timed out`, the executable error, or `exit
<n>` with the child's stderr), and a `gh` answer other than the slug puts the
name it gave.

The compiled policy. A row is `{default_branch, integration_branch,
required_checks, evidence}`. `required_checks` is the contract's
`bindings.vcs.merge.required_checks`, read from the resolved snapshot of the
pinned contract as the two branches are, sorted, or `[]` when the contract
declares none; the guard's loader accepts exactly the entries the resolver
accepts, so `unsupported_name` does not check them. The evidence is identity
only (issue 126 D11): the project id, the digest of the registry entry
(`canonical.telemetry_digest`), the pinned `ref` and `commit`, the contract's
blob id at that commit, the provider's `full_name` and each compiled profile's
`id`, `version` and `digest`. No resolved snapshot and no contract body is
persisted. The written document has exactly two members, the rows under
`derived_repositories` and `derivation`: `{schema_version, platform_version,
registry_digest}`, where `schema_version` is `DERIVATION_SCHEMA_VERSION` (3) and
the digest is `null` when no registry file exists. The base policy is only
validated and consulted for `literal_conflict`, and none of its members is
copied into the output. The lifecycle guard reads its trusted members
(`authorized_owners`, `integration_bases` and the three tools) from the base
policy only and takes nothing but a row's two branches and its required checks
from this file. The only repository writes are the remote-tracking refs of the
branches fetched and the fetched objects. The write is atomic
(`agent_platform.write_atomically`), so a reader sees the old file or the new
one.

`bindings.vcs.merge.required_checks` (issue 552) is an optional
`resolve-project` member beside `strategy` and `delete_branch`; absent or `null`
means the project declares no required checks, and the resolver never inserts
it, so the project schema version stays 1. A present value is a non-empty list
of distinct non-empty strings, each the exact name GitHub shows for a check (a
check run's `name` or a commit status's `context`), with no character
restricted. A value that is not a list is `contract.vcs.not_list`, an empty list
`contract.vcs.empty_required_checks`, an entry that is not a non-empty string
`contract.vcs.not_string` at that entry's pointer, and a repeated entry
`contract.vcs.duplicate_required_check` at its second occurrence's pointer. The
snapshot passes the member through unchanged.

Outcomes. The three outcomes are the exit statuses: 0 when every entry derived
(an absent registry is the empty fleet) and the file was written (`complete`),
1 when the file was written but at least one project has no row, one stderr line
each (`written_with_refusals`), and 2 when no policy could be compiled, in which
case no file is left at `--output` (`refused`). Exit 1 is also `kept_previous`:
every registered project was refused and the file at `--output` already held a
derived row, so it is left byte-identical rather than replaced by an empty
policy (issue 470: a shell that cannot reach the forge refuses every project,
and the guard re-derives a row before it trusts it anyway); the refusals are
still reported. Exit 2 removes the previous file whatever it held: a missing
file or a parent that is not a directory counts as removed, and any other
failure to remove it is appended to the cause's detail without replacing the
cause. The cause is one of `CAUSES`: `base_invalid`, `registry_invalid`,
`platform_unavailable`, `output_unwritable` (issue 126 D14) or `internal`, which
carries the exception's type and message. The report, one line of sorted-key
JSON on stdout, has `schema_version`, `outcome`, `derived` (the sorted slugs),
`refused` (`project_id`, `root`, `reason_code` and a `detail` cut to 240
characters) and `cause` (`null` or `{reason_code, detail}`). Any argument after
the fixed ones of `claude-guard-policy` reaches `compile`, so
`claude-guard-policy --help` prints usage and writes nothing.

`guard-policy derive --repository <slug>` re-derives one repository's row
(issue 377), the check the lifecycle guard runs before it trusts a compiled row.
It reads the registry, runs the first two proof steps for every entry
(`entry_slug`) and the rest (`prove`) only for entries whose `origin` names the
slug, so an entry naming another repository is never fetched and never asks the
provider; then the duplicate and name checks among them (`_admit`). It reads each
branch the same way `compile` does, so it writes no file beyond the fetched
objects and the remote-tracking refs of the branches fetched; it reads no base
policy, so it never reports `literal_conflict`. The report, one line of JSON on
stdout, has the members `schema_version` (`DERIVE_REPORT_SCHEMA_VERSION`, 2),
`repository` (the argument), `outcome`, `row`, `refused` and `cause`. Exit 0 is
`derived` with the row `compile` would write; exit 1 is `refused`, with the
`refused` entries that name the slug (empty when none does); exit 2 is
`unavailable`, with a `cause` from `CAUSES` (`registry_invalid`,
`platform_unavailable` or `internal`).

The row check. `claude-guard-row-check` is the store script the lifecycle guard
runs as `<derive-bin> --repository <slug>` for a repository that has a compiled
row. It is a bash script under `-p`, which ignores `BASH_ENV` and exported
functions; it unsets `BASH_ENV` and `ENV`, puts the store `git`, `gh` and `ssh`
first on `PATH`, as `claude-guard-policy` does, and execs the `guard-policy`
launcher, itself a bash script under `-p`, as `guard-policy derive` with its
arguments; it is not installed on `PATH`. That launcher, and the one
`claude-guard-policy` execs, come from the `agentTools` module argument, which
`home/common/agent-tools/default.nix` sets as the one application of
`lib/agent-tools.nix` per home configuration, so the row check, the compile
wrapper and every `~/.agents/bin` launcher exec one agent_tools environment
(issue 467). `home/common/claude-code/lifecycle_guard.py` documents what the
guard checks against the report and how it bounds the run.

The activation step. The installed `claude-guard-policy` runs `compile` with
fixed arguments, the base policy and the compiled path, and takes none of its
own; the home-manager activation step `claudeGuardPolicy` runs that command on
every home-manager activation, after `linkGeneration` and before the settings
copy, and never aborts the activation. It treats the compiler's three outcomes
as follows. Status 0 leaves the complete compiled policy. Status 1 leaves a
compiled policy without the refused projects' rows, and the compiler's stderr
line names each refused project with its reason code. Any other status removes
the compiled policy, and the step says that registered projects have lost their
derived guard row and with it their derived integration branch. In both cases
only a repository that relies on a derived row for its authorization is refused
until `claude-guard-policy` succeeds; authorization from the base policy (an
authorized owner or a literal integration row) still applies, and no call is
blocked by it. If the removal fails, the step reports that the path could not be
removed, and the guard reads whatever is there: a directory or an unreadable or
malformed file contributes no row, and a readable earlier policy stays in
force, its rows still rechecked at use. The repair is `claude-guard-policy`, run
from a shell that can fetch each project's `origin` and whose `gh` keyring
credential reaches the provider; a rerun repairs only the refusals a missing
network or credential causes, which are `fetch_failed` and `provider_unproven`,
because it can only re-derive from the registry and `origin`, and the other
codes name a registry, contract or remote that has to change first.

Tests. `tests/test_guard_policy.py` drives the commands as `python -m
agent_tools.guard.guard_policy compile` and `derive` over
`tests/guard_policy_world.py`, and calls two functions directly for the checks no
command input reaches: `target_profiles` on a hand-built snapshot for the one
step the release grammar hides (issue 126 D10, D15), and `unsupported_name` on a
hand-built row for the slug, because `github_remote.github_slug` already reads
no slug the guard would refuse.
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

from agent_tools import canonical, forge_adapter, release_profile
from agent_tools.guard import contract_export
from agent_tools.project_contract import (adopt_inspection, adopt_verify, agent_platform,
                                          resolve_project)
from agent_tools.system import github_remote

REPORT_SCHEMA_VERSION = 1
DERIVE_REPORT_SCHEMA_VERSION = 2
DERIVATION_SCHEMA_VERSION = 3

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
# round trip holds them to what the built guard loads. Its rule for a row's
# required_checks, a list of distinct non-empty strings, is the resolver's own rule
# for the contract member (issue 552 D4), so unsupported_name has no case for it.
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
    required_checks = sorted(vcs["merge"].get("required_checks") or [])
    return {"default_branch": vcs["default_branch"], "integration_branch": vcs["integration_branch"],
            "required_checks": required_checks,
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


# How the proof reads `origin` (issue 385): each branch is pinned to the commit
# `origin` lists for it, fetched only when the checkout lacks it, and exported as
# the contract and its projection files alone, with no tree inventory. Handed to
# `adopt_verify.remote_source`, which imports neither of these modules (D26).
CONTRACT_READER = adopt_verify.SourceReader(
    pin=adopt_inspection.pin_listed, export=contract_export.export_contract,
    inventory=False)


def prove(entry: dict, root: Path, slug: str) -> dict:
    """Steps 3 to 10 for one registry entry at `root` whose origin names `slug`: the row."""
    override = entry.get("branch_override")
    try:
        with adopt_verify.remote_source(
                root, resolver, override["branch"] if override else None,
                network_timeout=forge_adapter.CHILD_TIMEOUT_SECONDS,
                reader=CONTRACT_READER) as source:
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


def _holds_rows(output: Path) -> bool:
    """Whether `output` is a readable compiled policy with at least one derived row."""
    try:
        document = json.loads(output.read_bytes())
    except (OSError, ValueError):
        return False
    rows = document.get("derived_repositories") if isinstance(document, dict) else None
    return isinstance(rows, dict) and bool(rows)


def _write(base: dict, entries: list[dict], platform_version: str,
           output: Path) -> tuple[int, dict]:
    rows, refusals = compile_policy(base, entries)
    if not rows and refusals and _holds_rows(output):
        # Issue 470: every derive failing is far likelier a shell that cannot reach the
        # forge (sandboxed, unauthenticated, offline) than a fleet that lost every row.
        # Keep the last populated policy; the guard re-derives a row before it trusts it.
        return 1, _report("kept_previous", [], refusals, None)
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
        if report["outcome"] == "kept_previous":
            print(f"guard-policy: every registered project's derive failed, so the policy "
                  f"was not rewritten: kept the previous policy at {args.output}",
                  file=sys.stderr)
        if report["cause"] is not None:
            print(f"guard-policy: no policy was written: {report['cause']['reason_code']}: "
                  f"{report['cause']['detail']}", file=sys.stderr)
    print(json.dumps(report, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
