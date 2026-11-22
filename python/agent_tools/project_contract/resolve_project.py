"""Resolve this repository's authored project contract into a ResolvedProject.

`.agents/project.json` is the only input of a schema-2 contract. `resolve` loads it, validates its
whole shape in one pass, normalizes every authored repository-relative path
against the discovered project root, computes each capability's readiness
from the filesystem and `PATH`, and prints the snapshot as compact sorted JSON
on stdout. No project policy is defaulted, inferred, or sniffed from the
environment (D5); a missing, unexpected or malformed member is a refusal, never
an implied value. Readiness observes the machine but never executes anything:
the subcommand opens no file for writing, creates no directory, and starts no
child process.

The snapshot's `release` member is derived, not authored: its `targets` list
the targets the authored `release` member binds, with the operations each one
runs (`release_profile.release_targets`).

The contract may carry an optional top-level `production` member, in one of two
forms. `{"none": true}` declares that the project has no production, and no
rule member may stand beside it. `{"none": false, ...}` declares the rules:
`changes` (the command ids, key-file globs and MCP tool names that change
production, at least one in all), `read_only` (the command ids and MCP tool
names that only read it) and `release_profile` (the one profile of
`release.profiles` through which a change is allowed). `none` is always
required, so neither form is implied. The rules form may also carry
`console_activation`, the id of one `changes.commands` entry whose approved
path is the console's Activate (issue 1193); it is refused beside `none: true`
(`none_with_rules`) and when it names no changing command
(`console_activation_not_a_change`). A command id must name a
`bindings.commands` entry, an MCP tool is spelled `mcp__<server>__<tool>`, a
key file follows the contract glob rule, and no command or tool may be both a
changing and a read-only route. The snapshot always carries a derived
`production` member: `{"status": "not_declared"}` when the section is absent,
`{"status": "none"}` for the no-production form, and
`{"status": "declared", "changes", "read_only", "release_profile"}` otherwise
(plus `console_activation` exactly when authored), with ids and globs returned as authored (they are not bindings, so no glob is
made absolute). An absent section is not the same as declaring no production.

`bindings.vcs.commit` may carry `environment`, the id of one `bindings.commands`
entry through which `adopt-project apply` runs its commit (ADR-project-contract-008);
it must be a non-empty string naming a commands entry (`contract.vcs.not_string`,
`contract.vcs.unknown_command_id`), is returned as authored, and is never inserted
when absent.

`check-projections` judges each declared target against its source and
refuses on drift; `resolve` runs the same check before it builds anything, so
a hand-edited target is a structural refusal rather than a stale snapshot
(D10).

`platform-status` is the administrative operation: it reports the installed
platform's version facts, and — when asked — one project's declared interval
and compatibility verdict, or one verdict row per registered fleet member. It
is never normal workflow context (R3.1).

`platform-status` republishes `platform.deprecations` verbatim and adds
`deprecated_uses` to the `project` block and to each `fleet` row: the ascending
ids of the `project_file` entries whose `subject` exists under that root by
`os.lstat` (a dangling symlink counts) and of the `project_schema` entries
whose `subject` equals the `schema_version` of that root's
`.agents/project.json` read as JSON, or `null` when the root is not a
directory, a subject cannot be inspected, or a `project_schema` entry is
declared and the contract file is missing, unreadable or carries a non-integer
version (only ENOENT and ENOTDIR mean absent; EACCES or EIO never read as a
clean report). It never changes `compatible`, `reason_code`, `repair_id` or the
exit code, and `resolve` never reads it. `removed_uses` (`removed_uses`, issue
579 P2) applies exactly those rules to `removals`, in the `project` block and in
every fleet row. The report is interface version 3
(`PLATFORM_STATUS_SCHEMA_VERSION`).

`platform-status --manifest PATH` (issue 579 P7) judges against the manifest at
`PATH` instead of the installed one: it is loaded and validated by the
installed loader's rules, `platform.manifest_path` is `PATH` resolved, and a
missing or invalid `PATH` refuses `resolver_failure` exactly as a broken
installed manifest does. The cutover preflight runs the candidate's own code
this way against the candidate's own manifest.

Platform 2.1.0 reads project schemas 2 and 3 (`project_schema_versions` is
`[2, 3]`) and resolves to schema 2 (`resolved_schema_version` is 2). It
declares the migration `bindings-deploy.retire` from schema 1 to 2 (issue 579). Schema 2 is schema 1
without the deploy watch: `bindings.deploy` and `capabilities.deploy` are not
members of it, so an authored one is refused like any member outside the
schema, and the resolved snapshot has neither. A schema-1 contract is refused
`unsupported_schema` with reason `project_schema_unsupported`. The projection
header records the contract's own schema, so a schema-2 contract's `AGENTS.md`
says `(project schema 2)`. The resolver and adoption tests read a pinned
schema-2 contract, `home/common/agent-skills/tests/fixtures/project-contract-schema-2.json`
(P11).

The platform defines two commands every snapshot carries in `bindings.commands`:
`codex-plan-review` and `codex-diff-review` (`agent_platform.PLATFORM_COMMANDS`,
ADR-project-contract-010). The resolver adds each one the contract does not
author under its id, with `cwd` made absolute like any other; an entry the
contract authors under a platform id is read as authored and replaces the
platform's whole. A reference to a command id (verification, review, the commit
environment, production commands) is checked against the authored and platform
ids together, so a contract may name a platform command without authoring it.
Schema 2 is unchanged: a supported `review.plan` or `review.code` still needs
its authored `bindings.workflow.review` id.

Project schema 3 authors only what the platform cannot decide. The resolver
fills the constants from `schema_three` and the four derived values from
`derived_values` (`contract_view`), validates that view with the schema-2
rules, and builds the snapshot from it, so the snapshot is schema 2 without the
four retired members (`schema_three.RETIRED`). The derived values are the
project id and the tracker repo slug (the `owner/repo` of the git remote
`origin`, read from the repository's git config), the merge's required checks
(the contexts of `.github/branch-protection.json`) and the platform range (up
to the next major from the `platform_version` of the platform manifest: the
tree's own when it holds one, as the platform's own repository does, else that
of the revision `devenv.lock` pins as `agent-platform`, found in the Nix
store). They are read from files, never through a child process or the network.
A contract that authors one is refused `contract.<section>.derived_value`, and
one the repository cannot state is refused `contract.<section>.not_derivable`
at its pointer (ADR-project-contract-014). Schema 3
also defines the platform command `commit-environment` (`platform_commands`),
which the filled commit environment names. A schema-3 contract that authors a
platform constant, a retired member, a platform command id or a command's `cwd`
or `env` is refused by name, not overwritten (`schema_three.refusals`): the
repair id is `contract.<section>.platform_constant` or
`contract.<section>.retired_member`. Because the verification list is a
constant, a contract must author the commands `lint` and `test`; an absent one
is `contract.commands.member_missing` at `/bindings/commands/<id>`.

`write-projections` is the tool's only writer. It renders each declared
projection from the single instruction source and brings its native entry
target into sync: a wholly generated file for one agent, one managed import
line inside an otherwise authored file for the other (D11). Rendering is a
pure function of the source bytes, the projection id and the schema version,
so two machines regenerate byte-identical targets; a target already in sync is
left untouched, mtime included.

Every subcommand loads and validates the installed platform manifest before it
looks at the repository, so a missing or malformed platform installation always
surfaces as `resolver_failure` and can never be masked by `not_onboarded` or a
contract error (R1.3).

A structural refusal prints exactly one JSON object carrying an `error` member
on stdout and exits 2 (D12). An argparse usage error also exits 2 but prints no
JSON, which is how a caller tells the two apart (D16).
"""

from __future__ import annotations

import argparse
import copy
import fnmatch
import json
import os
from pathlib import Path
import re
import shutil
import sys

from agent_tools.release import release_adapter, release_profile
from agent_tools.project_contract import agent_platform, derived_values, schema_three
from agent_tools.system import semver


CAPABILITY_NAMES = (
    "tracker",
    "worktrees",
    "knowledge.context",
    "knowledge.standards",
    "knowledge.architecture",
    "knowledge.hints",
    "verification",
    "review.plan",
    "review.code",
    "release",
)
# D1: `capabilities.release` is derived from the `release` member, never
# authored, so an authored contract declares these ten and the snapshot all
# ten.
AUTHORED_CAPABILITY_NAMES = tuple(
    name for name in CAPABILITY_NAMES if name != "release")
BINDING_NAMESPACES = ("vcs", "tracker", "paths", "commands", "workflow")
CAPABILITY_STATES = ("available", "unsupported", "blocked")
AUTHORED_SUPPORT = ("supported", "unsupported")
ERROR_CODES = (
    "not_onboarded",
    "invalid_contract",
    "unsupported_schema",
    "invalid_projection",
    "capability_unavailable",
    "resolver_failure",
)
REASON_CODES = (
    "tracker_cli_missing",
    "vcs_worktree_unsupported",
    "knowledge_path_missing",
    "command_missing",
    "release_profile_inadmissible",
    "release_adapter_unavailable",
)
PROJECTION_KINDS = ("generated_file", "managed_import")
PROJECTION_STATUSES = ("in_sync", "missing", "stale")
AGENT_IDS = ("claude", "codex")
CONTRACT_FILENAME = ".agents/project.json"

# The `platform-status` report's own interface version, independent of the
# project schema and of `ResolvedProject.schema_version`: those two are
# answered by the manifest (D8) and appear inside the report's `platform`
# block, so reusing either here would publish one fact twice under two names.
# Version 2 adds `deprecated_uses` to the `project` block and to every fleet
# row (issue 580 D4). Version 3 adds `removed_uses` to both (issue 579 P2).
PLATFORM_STATUS_SCHEMA_VERSION = 3

# The manifest members the `platform` block republishes, in the manifest's own
# order. The manifest's `schema_version` is not among them: it versions the
# manifest file, which is the loader's concern and not a platform fact a
# caller can act on.
PLATFORM_STATUS_MANIFEST_MEMBERS = (
    "platform_version",
    "project_schema_versions",
    "resolved_schema_version",
    "migrations",
    "deprecations",
    "removals",
)

TOP_LEVEL_MEMBERS = (
    "schema_version",
    "project",
    "bindings",
    "capabilities",
    "projections",
    "platform",
    "release",
)
# Members a contract may carry but need not: absent means undeclared, and the
# resolver never inserts one into the source.
TOP_LEVEL_OPTIONAL_MEMBERS = ("production",)
# The `production` section's members beside `none`, and the lists inside two of
# them. `PRODUCTION_STATUSES` is the closed set of the snapshot member's status.
PRODUCTION_RULE_MEMBERS = ("changes", "read_only", "release_profile")
# A rule-form member that may be absent: the changing command the console's Activate runs.
PRODUCTION_OPTIONAL_MEMBERS = ("console_activation",)
PRODUCTION_CHANGE_MEMBERS = ("commands", "key_files", "mcp_tools")
PRODUCTION_READ_ONLY_MEMBERS = ("commands", "mcp_tools")
PRODUCTION_STATUSES = ("not_declared", "none", "declared")
# R2.1: the interval's exact members. The closed schema-compatibility reason
# codes are `agent_platform.SCHEMA_REASON_CODES` — one home for that set (D7),
# read through the library rather than copied here.
PLATFORM_MEMBERS = ("min_inclusive", "max_exclusive")
VCS_MEMBERS = (
    "kind",
    "default_branch",
    "integration_branch",
    "branch_pattern",
    "worktree",
    "commit",
    "merge",
)
MERGE_MEMBERS = ("strategy", "delete_branch")
# Issue 552 D1: the one `vcs.merge` member an author may leave out. `null` and
# absent both mean the project declares no required checks, and the resolver
# never inserts it.
MERGE_OPTIONAL_MEMBERS = ("required_checks",)
COMMIT_MEMBERS = ("co_authored_by", "signed")
# Issue 1449 (decided in #1430): attribution is decided only by the generated
# Claude Code settings, so nothing reads or asks for a co-author setting.
# Schema 2 still requires the member, so a writer of a schema-2 contract writes
# it with this value; schema 3 does not have it (`schema_three.RETIRED`).
RETIRED_COMMIT_MEMBERS: dict[str, bool] = {"co_authored_by": False}
# Issue 1249 / ADR-project-contract-008: the id of the `bindings.commands`
# entry the adoption commit runs through. Absent means the commit runs git
# alone, and the resolver never inserts it.
COMMIT_OPTIONAL_MEMBERS = ("environment",)
TRACKER_MEMBERS = ("kind", "cli", "repo_slug", "credential_env")
PATHS_LIST_MEMBERS = (
    "context",
    "standards",
    "architecture",
    "operations",
    "hints",
    "rejections",
)
PATHS_MEMBERS = ("artifacts",) + PATHS_LIST_MEMBERS
COMMAND_MEMBERS = ("argv", "cwd", "env")
WORKFLOW_MEMBERS = ("verification", "orchestration", "review")
# The workflow members an author may leave out: `light_lane` (#279) and
# `verification_conditions` (issue 437). For each, `null` and absent both mean
# none (every declared verification id runs), and the resolver never inserts
# either member itself. `light_lane` is accepted on a schema-2 contract, and no
# tool reads it; schema 3 does not have it (`schema_three.RETIRED`).
WORKFLOW_OPTIONAL_MEMBERS = ("light_lane", "verification_conditions")
# What a schema-3 contract may leave out: `light_lane` is retired.
SCHEMA_THREE_WORKFLOW_OPTIONAL_MEMBERS = ("verification_conditions",)
# #310: the one orchestration member an author may leave out; never defaulted.
ORCHESTRATION_OPTIONAL_MEMBERS = ("stall_minutes",)
LIGHT_LANE_MEMBERS = ("mode", "budget_minutes", "risk_paths")
VERIFICATION_CONDITION_MEMBERS = ("when_changed", "skip_reason")
# Issue 771: a fast pre-commit check; deliver-standard names it to implementers.
VERIFICATION_CONDITION_OPTIONAL_MEMBERS = ("pre_commit",)
LIGHT_LANE_MODES = ("shadow", "active")
PROJECTION_MEMBERS = ("id", "agent", "kind", "target", "source")

# D6: what each capability demands of the bindings when it is declared
# `supported`. A row is the binding member's path under `/bindings` and the
# predicate the authored value must satisfy; failing one is `invalid_contract`,
# never `blocked`. Only a declared `supported` capability is walked, so an
# `unsupported` one imposes none of its rows on the bindings.
CAPABILITY_BINDING_REQUIREMENTS = {
    "tracker": (
        (("tracker", "kind"), lambda value: value != "none"),
        (("tracker", "cli"), lambda value: isinstance(value, str) and value != ""),
    ),
    "worktrees": ((("vcs", "kind"), lambda value: value == "git"),),
    "knowledge.context": ((("paths", "context"), bool),),
    "knowledge.standards": ((("paths", "standards"), bool),),
    "knowledge.architecture": ((("paths", "architecture"), bool),),
    "knowledge.hints": ((("paths", "hints"), bool),),
    "verification": ((("workflow", "verification"), bool),),
    "review.plan": (
        (("workflow", "review", "plan"), lambda value: value is not None),),
    "review.code": (
        (("workflow", "review", "code"), lambda value: value is not None),),
}

# The `paths` list each `knowledge.*` capability reads its prerequisite from.
KNOWLEDGE_PATH_MEMBERS = {
    "knowledge.context": "context",
    "knowledge.standards": "standards",
    "knowledge.architecture": "architecture",
    "knowledge.hints": "hints",
}

# `env` carries variable names only, never values (D13); an entry holding an
# `=` or any other non-name character is a violation rather than a value the
# snapshot passes on.
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# One MCP tool as Claude Code names it: `mcp__<server>__<tool>`. A server-level
# name (`mcp__<server>`) has no tool part and is not a tool.
MCP_TOOL_NAME_PATTERN = re.compile(r"^mcp__[A-Za-z0-9_-]+__[A-Za-z0-9_-]+$")

# The two rendered forms (D11). Both read only the entry and the schema
# version, so nothing machine-specific can reach a generated target.
GENERATED_HEADER_TEMPLATE = (
    "<!-- generated by resolve-project from {source} (project schema {version}). "
    "Do not edit; edit the source and run `resolve-project write-projections`. -->"
)
MANAGED_IMPORT_TEMPLATE = "@{source}"


class ContractError(Exception):
    """One refusal: a closed code, a stable repair id, and ordered violations."""

    def __init__(self, code: str, repair_id: str, violations: list[dict],
                 *, reason_code: str | None = None) -> None:
        super().__init__(f"{code}: {repair_id}")
        self.code = code
        self.repair_id = repair_id
        self.violations = violations
        # D7: carried only by `unsupported_schema`; `emit_error` is where that
        # positional rule is enforced, so no caller can publish it elsewhere.
        self.reason_code = reason_code


# --------------------------------------------------------------------------
# Violation collection
#
# A collected violation carries a third `repair_id` key that the published
# error object never shows: the error publishes exactly one repair id, the one
# belonging to the first violation in pointer order, and `emit_error` receives
# the list already stripped down to `{pointer, message}`.
# --------------------------------------------------------------------------


def violation(pointer: str, message: str, repair_id: str) -> dict:
    return {"pointer": pointer, "message": message, "repair_id": repair_id}


def raise_for_violations(violations: list[dict]) -> None:
    """Publish a non-empty violation list as one ordered `invalid_contract`."""
    if not violations:
        return
    ordered = sorted(violations, key=lambda item: item["pointer"])
    raise ContractError(
        "invalid_contract",
        ordered[0]["repair_id"],
        [{"pointer": v["pointer"], "message": v["message"]} for v in ordered],
    )


def is_safe_relative_path(value: object) -> bool:
    """A non-empty relative string with no leading `/` and no `..` segment."""
    if not isinstance(value, str) or not value:
        return False
    if value.startswith("/") or Path(value).is_absolute():
        return False
    return ".." not in Path(value).parts


CANONICAL_PATH_MESSAGE = ("must be spelled canonically: '/'-separated, with no "
                          "backslash, no empty or '.' segment and no trailing '/'")


def is_canonical_path(path: str) -> bool:
    """The one spelling contract path globs are matched in: '/'-separated, with no backslash,
    no empty or `.` segment and no trailing `/` (#279 D11).

    Contract globs and the paths they are matched against both meet it,
    because `fnmatchcase` compares the strings unchanged.
    """
    return "\\" not in path and all(segment not in ("", ".") for segment in path.split("/"))


def any_path_matches(paths: list[str], globs: list[str]) -> bool:
    """True when some path matches some glob under `fnmatch.fnmatchcase`.

    Both are compared as spelled, so `*` also crosses `/` (#279 D4, issue 437
    D3). It is the one matcher for contract path globs; `verified-tree` calls it
    for `when_changed`.
    """
    return any(fnmatch.fnmatchcase(path, glob) for path in paths for glob in globs)


def is_conditional(condition: object) -> bool:
    """False only for a dict holding neither `when_changed` nor `skip_reason`.

    The one conditionality test for the resolver and `verified-tree` (issue 771
    D3): an entry holding only the `pre_commit` flag leaves its id unconditional,
    and any other value, a malformed non-dict included, counts as conditional.
    """
    return not (isinstance(condition, dict)
                and "when_changed" not in condition and "skip_reason" not in condition)


def check_string(value: object, pointer: str, section: str,
                 violations: list[dict]) -> bool:
    if isinstance(value, str) and value:
        return True
    violations.append(violation(
        pointer, "must be a non-empty string", f"contract.{section}.not_string"))
    return False


def check_boolean(value: object, pointer: str, section: str,
                  violations: list[dict]) -> bool:
    # `isinstance(x, bool)` before any `int` test: a truthy int is not a
    # boolean the contract may declare.
    if isinstance(value, bool):
        return True
    violations.append(violation(
        pointer, "must be a boolean", f"contract.{section}.not_boolean"))
    return False


def check_positive_int(value: object, pointer: str, section: str,
                       violations: list[dict]) -> bool:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        violations.append(violation(
            pointer, "must be a positive integer",
            f"contract.{section}.not_positive_int"))
        return False
    return True


def check_safe_path(value: object, pointer: str, section: str,
                    violations: list[dict]) -> bool:
    if is_safe_relative_path(value):
        return True
    violations.append(violation(
        pointer,
        "must be a non-empty repository-relative path with no '..' segment",
        f"contract.{section}.unsafe_path",
    ))
    return False


def check_contract_glob(value: object, pointer: str, violations: list[dict], *,
                        section: str = "workflow") -> bool:
    """A contract path glob: a safe repository-relative path, spelled canonically (#279 D4)."""
    if not check_safe_path(value, pointer, section, violations):
        return False
    if is_canonical_path(value):
        return True
    violations.append(violation(
        pointer, CANONICAL_PATH_MESSAGE, f"contract.{section}.noncanonical_path"))
    return False


def check_object(value: object, pointer: str, section: str,
                 violations: list[dict]) -> bool:
    if isinstance(value, dict):
        return True
    violations.append(violation(
        pointer, "must be an object", f"contract.{section}.not_object"))
    return False


def check_list(value: object, pointer: str, section: str,
               violations: list[dict]) -> bool:
    if isinstance(value, list):
        return True
    violations.append(violation(
        pointer, "must be a list", f"contract.{section}.not_list"))
    return False


def check_exact_members(value: dict, pointer: str, expected: tuple[str, ...],
                        section: str, violations: list[dict], *,
                        optional: tuple[str, ...] = ()) -> None:
    """Report every absent required member and every unexpected one.

    A name in `optional` may be present or absent: it is never reported as
    missing and never as unexpected.
    """
    for name in expected:
        if name not in value:
            violations.append(violation(
                f"{pointer}/{name}", "required member is absent",
                f"contract.{section}.member_missing"))
    for name in sorted(value):
        if name not in expected and name not in optional:
            violations.append(violation(
                f"{pointer}/{name}", "member is not part of this schema",
                f"contract.{section}.member_unexpected"))


# --------------------------------------------------------------------------
# Root discovery and loading
# --------------------------------------------------------------------------


def not_onboarded() -> ContractError:
    # The message never embeds a path, so two runs refusing for this reason
    # emit identical bytes.
    return ContractError(
        "not_onboarded",
        "onboarding.contract.missing",
        [{
            "pointer": "",
            "message": (
                ".agents/project.json was not found at or above "
                "the start directory"
            ),
        }],
    )


def discover_root(repo_root: str | None) -> Path:
    """The one project root: the given `--repo-root`, or the nearest ancestor.

    With `--repo-root` the named directory *is* the root and no walk-up
    occurs; without it the search starts at the process working directory and
    stops at the first ancestor holding the contract.
    """
    if repo_root is not None:
        root = Path(repo_root).resolve()
        if (root / CONTRACT_FILENAME).is_file():
            return root
        raise not_onboarded()
    start = Path.cwd().resolve()
    for candidate in (start, *start.parents):
        if (candidate / CONTRACT_FILENAME).is_file():
            return candidate
    raise not_onboarded()


class NonFiniteNumber(Exception):
    """A bare `NaN`, `Infinity` or `-Infinity` token in the authored JSON."""


def reject_non_finite(token: str) -> object:
    """`parse_constant` for `json.loads`: the three bare tokens are refused.

    Python's decoder accepts them as an extension, and an adapter `config` is an
    unconstrained dict, so an accepted token would travel through validation
    untouched and land in a snapshot that no standards JSON parser can read —
    from a tool whose whole contract is that its output can be trusted. The
    emit side carries the matching `allow_nan=False` guard instead of relying
    on this one: the boundary is checked from both directions.
    """
    raise NonFiniteNumber(token)


def load_contract(root: Path) -> dict:
    """Read and parse the authored contract, or refuse with `contract.parse`."""
    def refuse(message: str) -> ContractError:
        return ContractError(
            "invalid_contract",
            "contract.parse",
            [{"pointer": "", "message": message}],
        )

    try:
        text = (root / CONTRACT_FILENAME).read_text(encoding="utf-8")
    except OSError:
        raise refuse(".agents/project.json could not be read") from None
    except UnicodeDecodeError:
        raise refuse(".agents/project.json is not valid UTF-8") from None
    try:
        source = json.loads(text, parse_constant=reject_non_finite)
    except NonFiniteNumber:
        raise refuse(
            ".agents/project.json holds NaN, Infinity or -Infinity, which "
            "JSON has no value for"
        ) from None
    except json.JSONDecodeError:
        raise refuse(".agents/project.json is not valid JSON") from None
    if not isinstance(source, dict):
        raise refuse(".agents/project.json must hold a JSON object")
    return source


# --------------------------------------------------------------------------
# One-pass structural validation
# --------------------------------------------------------------------------


def schema_reason_repair_id(reason_code: str) -> str:
    """The stable repair id each `SCHEMA_REASON_CODES` member publishes.

    Exhaustive over the closed set with a raising default: a member added to
    the tuple without an id here is a crash, never a plausible-looking blank.
    """
    if reason_code == "platform_too_old":
        return "contract.platform.too_old"
    if reason_code == "platform_too_new":
        return "contract.platform.too_new"
    if reason_code == "project_schema_unsupported":
        return "contract.schema_version.unsupported"
    if reason_code == "project_identity_mismatch":
        return "registry.project_id.mismatch"
    raise ValueError(f"unknown schema reason code: {reason_code!r}")


def schema_reason_message(reason_code: str) -> str:
    """The fixed sentence each `SCHEMA_REASON_CODES` member publishes.

    Fixed, because nothing here embeds a version or a path: two runs refusing
    for the same reason emit identical bytes (D12). Exhaustive over the closed
    set with a raising default, like `schema_reason_repair_id`.
    """
    if reason_code == "platform_too_old":
        return ("the installed platform version is below this contract's "
                "min_inclusive bound")
    if reason_code == "platform_too_new":
        return ("the installed platform version has reached this contract's "
                "max_exclusive bound")
    if reason_code == "project_schema_unsupported":
        return ("the declared project schema version is not one this platform "
                "supports")
    if reason_code == "project_identity_mismatch":
        return ("the contract at the registered root declares a different "
                "project id than the one the registry recorded")
    raise ValueError(f"unknown schema reason code: {reason_code!r}")


def unsupported_schema(reason_code: str, pointer: str) -> ContractError:
    """The one constructor for `unsupported_schema` (R2.3, R2.4).

    Both the repair id and the message come from the exhaustive dispatches
    above, so a reason code outside `SCHEMA_REASON_CODES` cannot reach the
    caller as a refusal at all.
    """
    return ContractError(
        "unsupported_schema",
        schema_reason_repair_id(reason_code),
        [{"pointer": pointer, "message": schema_reason_message(reason_code)}],
        reason_code=reason_code,
    )


def validate_schema_version(source: dict, violations: list[dict],
                            supported: list) -> None:
    """Version first, but only an unsupported integer version short-circuits.

    An absent, non-integer or boolean version contributes its violation to the
    same one-pass list as every other shape violation: `invalid_contract` owes
    the caller every violation it can see. An integer outside the manifest's
    `project_schema_versions` aborts immediately instead, because the shape
    rules the rest of this pass applies describe only the schemas this platform
    publishes (D8, D19). `supported` is that published set — the resolver holds
    no schema literal of its own.
    """
    value = source.get("schema_version")
    if ("schema_version" not in source
            or isinstance(value, bool)
            or not isinstance(value, int)):
        violations.append(violation(
            "/schema_version",
            "must be the integer schema version this resolver supports",
            "contract.schema_version.invalid",
        ))
        return
    if value not in supported:
        raise unsupported_schema("project_schema_unsupported", "/schema_version")


def validate_platform(source: dict, violations: list[dict]) -> None:
    """Shape-check the contract's `[min, max)` platform interval (R2.1, R2.2).

    Shape only, and every finding joins the same one-pass list as the rest of
    the contract's violations. Whether the installed platform version falls
    inside the interval is a separate question answered by
    `raise_for_platform_range`, and only once this pass has found nothing (D4).
    """
    value = source.get("platform")
    if not check_object(value, "/platform", "platform", violations):
        return
    check_exact_members(
        value, "/platform", PLATFORM_MEMBERS, "platform", violations)
    bounds: dict[str, str] = {}
    for name in PLATFORM_MEMBERS:
        if name not in value:
            continue
        # A non-string bound and a loose spelling are one violation at one
        # pointer: `parse_semver` returns None for both, and for a pre-release
        # or build-metadata suffix (D9).
        if semver.parse_semver(value[name]) is None:
            violations.append(violation(
                f"/platform/{name}",
                "must be a strict MAJOR.MINOR.PATCH version string",
                f"contract.platform.{name}.not_semver"))
            continue
        bounds[name] = value[name]
    if len(bounds) != len(PLATFORM_MEMBERS):
        return
    # R2.2: strictly greater. An exact pin (equal bounds) and a minimum-only
    # range (an absent `max_exclusive`, reported above) are both invalid.
    if semver.compare_semver(
            bounds["max_exclusive"], bounds["min_inclusive"]) <= 0:
        violations.append(violation(
            "/platform/max_exclusive",
            "must be strictly greater than min_inclusive",
            "contract.platform.max_exclusive.not_above_min"))


def raise_for_platform_range(platform: dict, platform_version: str) -> None:
    """Refuse when the installed platform version is outside the interval (R2.3).

    Runs only after `validate_platform` has passed, so all three versions
    parse and `interval_verdict` answers the range question alone.
    """
    verdict = agent_platform.interval_verdict(
        platform_version, platform["min_inclusive"], platform["max_exclusive"])
    if verdict is None:
        return
    raise unsupported_schema(verdict, "/platform")


def validate_project(source: dict, violations: list[dict], *,
                     members: tuple[str, ...] = ("id", "name")) -> None:
    value = source.get("project")
    if not check_object(value, "/project", "project", violations):
        return
    check_exact_members(value, "/project", members, "project", violations)
    for name in members:
        if name in value:
            check_string(value[name], f"/project/{name}", "project", violations)


def validate_vcs(vcs: dict, commands: dict | None, violations: list[dict], *,
                 commit_members: tuple[str, ...] = COMMIT_MEMBERS) -> None:
    check_exact_members(vcs, "/bindings/vcs", VCS_MEMBERS, "vcs", violations)
    for name in ("kind", "default_branch", "integration_branch", "branch_pattern"):
        if name in vcs:
            check_string(vcs[name], f"/bindings/vcs/{name}", "vcs", violations)
    if "worktree" in vcs and check_object(
            vcs["worktree"], "/bindings/vcs/worktree", "vcs", violations):
        worktree = vcs["worktree"]
        check_exact_members(
            worktree, "/bindings/vcs/worktree", ("root", "prefix"), "vcs", violations)
        if "root" in worktree:
            check_safe_path(
                worktree["root"], "/bindings/vcs/worktree/root", "vcs", violations)
        if "prefix" in worktree:
            check_string(
                worktree["prefix"], "/bindings/vcs/worktree/prefix", "vcs", violations)
    if "commit" in vcs and check_object(
            vcs["commit"], "/bindings/vcs/commit", "vcs", violations):
        commit = vcs["commit"]
        check_exact_members(
            commit, "/bindings/vcs/commit", commit_members, "vcs", violations,
            optional=COMMIT_OPTIONAL_MEMBERS)
        for name in commit_members:
            if name in commit:
                check_boolean(
                    commit[name], f"/bindings/vcs/commit/{name}", "vcs", violations)
        if "environment" in commit:
            check_command_id(
                commit["environment"], "/bindings/vcs/commit/environment",
                commands, violations, section="vcs")
    if "merge" in vcs and check_object(
            vcs["merge"], "/bindings/vcs/merge", "vcs", violations):
        merge = vcs["merge"]
        check_exact_members(
            merge, "/bindings/vcs/merge", MERGE_MEMBERS, "vcs", violations,
            optional=MERGE_OPTIONAL_MEMBERS)
        if "strategy" in merge:
            check_string(
                merge["strategy"], "/bindings/vcs/merge/strategy", "vcs", violations)
        if "delete_branch" in merge:
            check_boolean(
                merge["delete_branch"], "/bindings/vcs/merge/delete_branch",
                "vcs", violations)
        validate_required_checks(merge, violations)


def validate_required_checks(merge: dict, violations: list[dict]) -> None:
    """Issue 552 D1: the optional `bindings.vcs.merge.required_checks` member."""
    pointer = "/bindings/vcs/merge/required_checks"
    checks = merge.get("required_checks")
    if checks is None or not check_list(checks, pointer, "vcs", violations):
        return
    if not checks:
        violations.append(violation(
            pointer, "must be a non-empty list",
            "contract.vcs.empty_required_checks"))
    seen: set[str] = set()
    for index, check in enumerate(checks):
        entry = f"{pointer}/{index}"
        if not check_string(check, entry, "vcs", violations):
            continue
        if check in seen:
            violations.append(violation(
                entry, "required check is declared more than once",
                "contract.vcs.duplicate_required_check"))
        seen.add(check)


def validate_tracker(tracker: dict, violations: list[dict]) -> None:
    check_exact_members(
        tracker, "/bindings/tracker", TRACKER_MEMBERS, "tracker", violations)
    for name in ("kind", "cli", "repo_slug"):
        if name in tracker:
            check_string(
                tracker[name], f"/bindings/tracker/{name}", "tracker", violations)
    pointer = "/bindings/tracker/credential_env"
    if "credential_env" in tracker and check_object(
            tracker["credential_env"], pointer, "tracker", violations):
        credential_env = tracker["credential_env"]
        check_exact_members(
            credential_env, pointer, ("unset_before_invocation",),
            "tracker", violations)
        names = credential_env.get("unset_before_invocation")
        entries_pointer = f"{pointer}/unset_before_invocation"
        if "unset_before_invocation" in credential_env and check_list(
                names, entries_pointer, "tracker", violations):
            for index, entry in enumerate(names):
                check_string(
                    entry, f"{entries_pointer}/{index}", "tracker", violations)


def validate_paths(paths: dict, violations: list[dict], *,
                   members: tuple[str, ...] = PATHS_MEMBERS) -> None:
    check_exact_members(paths, "/bindings/paths", members, "paths", violations)
    if "artifacts" in paths and check_object(
            paths["artifacts"], "/bindings/paths/artifacts", "paths", violations):
        artifacts = paths["artifacts"]
        check_exact_members(
            artifacts, "/bindings/paths/artifacts", ("specs", "plans"),
            "paths", violations)
        for name in ("specs", "plans"):
            if name in artifacts:
                check_safe_path(
                    artifacts[name], f"/bindings/paths/artifacts/{name}",
                    "paths", violations)
    for name in PATHS_LIST_MEMBERS:
        if name not in paths:
            continue
        pointer = f"/bindings/paths/{name}"
        if not check_list(paths[name], pointer, "paths", violations):
            continue
        for index, entry in enumerate(paths[name]):
            check_safe_path(entry, f"{pointer}/{index}", "paths", violations)


def validate_commands(commands: dict, violations: list[dict]) -> None:
    for command_id in sorted(commands):
        pointer = f"/bindings/commands/{command_id}"
        entry = commands[command_id]
        if not check_object(entry, pointer, "commands", violations):
            continue
        check_exact_members(
            entry, pointer, COMMAND_MEMBERS, "commands", violations)
        if "argv" in entry and check_list(
                entry["argv"], f"{pointer}/argv", "commands", violations):
            if not entry["argv"]:
                violations.append(violation(
                    f"{pointer}/argv", "must name at least one executable",
                    "contract.commands.empty_argv"))
            # Every word is a non-empty string, at its own pointer: an empty
            # `argv[0]` names no executable and an empty later word is an
            # argument the callee cannot have meant, so both are as broken as
            # the empty `argv` list above.
            for index, word in enumerate(entry["argv"]):
                check_string(
                    word, f"{pointer}/argv/{index}", "commands", violations)
        if "cwd" in entry:
            check_safe_path(entry["cwd"], f"{pointer}/cwd", "commands", violations)
        if "env" in entry and check_list(
                entry["env"], f"{pointer}/env", "commands", violations):
            for index, name in enumerate(entry["env"]):
                if not isinstance(name, str) or not ENV_NAME_PATTERN.match(name):
                    violations.append(violation(
                        f"{pointer}/env/{index}",
                        "must name an environment variable and carry no value",
                        "contract.commands.not_variable_name"))


def check_command_id(value: object, pointer: str, commands: dict | None,
                     violations: list[dict], *, section: str = "workflow") -> None:
    """A non-empty command id that is a key of `/bindings/commands`."""
    if not check_string(value, pointer, section, violations):
        return
    if commands is not None and value not in commands:
        violations.append(violation(
            pointer, "names no entry of bindings.commands",
            f"contract.{section}.unknown_command_id"))


def validate_workflow(workflow: dict, commands: dict | None,
                      violations: list[dict], *,
                      optional: tuple[str, ...] = WORKFLOW_OPTIONAL_MEMBERS,
                      check_verification_ids: bool = True) -> None:
    check_exact_members(
        workflow, "/bindings/workflow", WORKFLOW_MEMBERS, "workflow", violations,
        optional=optional)
    pointer = "/bindings/workflow/verification"
    if "verification" in workflow and check_list(
            workflow["verification"], pointer, "workflow", violations):
        for index, value in enumerate(workflow["verification"]):
            if check_verification_ids:
                check_command_id(value, f"{pointer}/{index}", commands, violations)
    pointer = "/bindings/workflow/orchestration"
    if "orchestration" in workflow and check_object(
            workflow["orchestration"], pointer, "workflow", violations):
        orchestration = workflow["orchestration"]
        check_exact_members(
            orchestration, pointer, ("max_parallel", "attempt_budget_minutes"),
            "workflow", violations, optional=ORCHESTRATION_OPTIONAL_MEMBERS)
        for name in ("max_parallel", "attempt_budget_minutes"):
            if name in orchestration:
                check_positive_int(
                    orchestration[name], f"{pointer}/{name}", "workflow", violations)
        if orchestration.get("stall_minutes") is not None:
            check_positive_int(
                orchestration["stall_minutes"], f"{pointer}/stall_minutes",
                "workflow", violations)
    pointer = "/bindings/workflow/review"
    if "review" in workflow and check_object(
            workflow["review"], pointer, "workflow", violations):
        review = workflow["review"]
        check_exact_members(review, pointer, ("plan", "code"), "workflow", violations)
        for name in ("plan", "code"):
            if name in review and review[name] is not None:
                check_command_id(
                    review[name], f"{pointer}/{name}", commands, violations)
    pointer = "/bindings/workflow/light_lane"
    if "light_lane" in workflow and workflow["light_lane"] is not None and check_object(
            workflow["light_lane"], pointer, "workflow", violations):
        light_lane = workflow["light_lane"]
        check_exact_members(
            light_lane, pointer, LIGHT_LANE_MEMBERS, "workflow", violations)
        if "mode" in light_lane and (
                not isinstance(light_lane["mode"], str)
                or light_lane["mode"] not in LIGHT_LANE_MODES):
            violations.append(violation(
                f"{pointer}/mode", "must be one of shadow, active",
                "contract.workflow.light_lane_mode"))
        if "budget_minutes" in light_lane:
            check_positive_int(
                light_lane["budget_minutes"], f"{pointer}/budget_minutes",
                "workflow", violations)
        if "risk_paths" in light_lane and check_list(
                light_lane["risk_paths"], f"{pointer}/risk_paths", "workflow",
                violations):
            for index, entry in enumerate(light_lane["risk_paths"]):
                check_contract_glob(entry, f"{pointer}/risk_paths/{index}", violations)
    validate_verification_conditions(workflow, violations)


def validate_verification_conditions(workflow: dict, violations: list[dict]) -> None:
    """Issues 437 D2 and 771 D2: the optional `bindings.workflow.verification_conditions` member."""
    pointer = "/bindings/workflow/verification_conditions"
    conditions = workflow.get("verification_conditions")
    if conditions is None or not check_object(conditions, pointer, "workflow", violations):
        return
    declared = workflow.get("verification")
    declared = declared if isinstance(declared, list) else None
    for verification_id, condition in conditions.items():
        entry = f"{pointer}/{verification_id}"
        if declared is not None and verification_id not in declared:
            violations.append(violation(
                entry, "names no id of bindings.workflow.verification",
                "contract.workflow.unknown_verification_id"))
        if not check_object(condition, entry, "workflow", violations):
            continue
        flag_only = "pre_commit" in condition and not is_conditional(condition)
        check_exact_members(
            condition, entry, () if flag_only else VERIFICATION_CONDITION_MEMBERS,
            "workflow", violations,
            optional=VERIFICATION_CONDITION_MEMBERS + VERIFICATION_CONDITION_OPTIONAL_MEMBERS)
        if "pre_commit" in condition:
            check_boolean(condition["pre_commit"], f"{entry}/pre_commit", "workflow",
                          violations)
        if "when_changed" in condition and check_list(
                condition["when_changed"], f"{entry}/when_changed", "workflow",
                violations):
            if not condition["when_changed"]:
                violations.append(violation(
                    f"{entry}/when_changed", "must be a non-empty list",
                    "contract.workflow.empty_path_list"))
            for index, glob in enumerate(condition["when_changed"]):
                check_contract_glob(glob, f"{entry}/when_changed/{index}", violations)
        if "skip_reason" in condition:
            check_string(condition["skip_reason"], f"{entry}/skip_reason", "workflow",
                         violations)
    if declared and all(isinstance(verification_id, str) and verification_id in conditions
                        and is_conditional(conditions[verification_id])
                        for verification_id in declared):
        violations.append(violation(
            pointer, "must leave at least one bindings.workflow.verification id "
                     "unconditional", "contract.workflow.no_unconditional_verification"))


def validate_bindings(source: dict, violations: list[dict], *,
                      schema: int = 2) -> None:
    three = schema == schema_three.SCHEMA_VERSION
    bindings = source.get("bindings")
    if not check_object(bindings, "/bindings", "bindings", violations):
        return
    check_exact_members(
        bindings, "/bindings", BINDING_NAMESPACES, "bindings", violations)
    present = {}
    for namespace in BINDING_NAMESPACES:
        if namespace not in bindings:
            continue
        if check_object(
                bindings[namespace], f"/bindings/{namespace}", "bindings",
                violations):
            present[namespace] = bindings[namespace]
    commands = present.get("commands")
    known = effective_commands(commands, platform_commands(source))
    if "vcs" in present:
        validate_vcs(
            present["vcs"], known, violations,
            **({"commit_members": ("signed",)} if three else {}))
    if "tracker" in present:
        validate_tracker(present["tracker"], violations)
    if "paths" in present:
        validate_paths(
            present["paths"], violations,
            **({"members": PATHS_LIST_MEMBERS} if three else {}))
    if commands is not None:
        validate_commands(commands, violations)
    if "workflow" in present:
        validate_workflow(
            present["workflow"], known, violations,
            **({"optional": SCHEMA_THREE_WORKFLOW_OPTIONAL_MEMBERS,
               "check_verification_ids": False} if three else {}))


def validate_capabilities(source: dict, violations: list[dict]) -> None:
    capabilities = source.get("capabilities")
    if not check_object(capabilities, "/capabilities", "capabilities", violations):
        return
    check_exact_members(
        capabilities, "/capabilities", AUTHORED_CAPABILITY_NAMES, "capabilities",
        violations)
    for name in AUTHORED_CAPABILITY_NAMES:
        if name not in capabilities:
            continue
        pointer = f"/capabilities/{name}"
        entry = capabilities[name]
        if not check_object(entry, pointer, "capabilities", violations):
            continue
        check_exact_members(
            entry, pointer, ("support",), "capabilities", violations)
        if "support" in entry and entry["support"] not in AUTHORED_SUPPORT:
            violations.append(violation(
                f"{pointer}/support",
                "must be either 'supported' or 'unsupported'",
                "contract.capabilities.invalid_support"))


def find_binding(bindings: dict, path: tuple[str, ...]) -> tuple[bool, object]:
    """The value at `path`, and whether the walk reached it through objects."""
    value: object = bindings
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return False, None
        value = value[key]
    return True, value


def validate_capability_bindings(source: dict) -> list[dict]:
    """D6 contradictions: a `supported` capability whose binding is incomplete.

    Only declared support is read, so an `unsupported` capability imposes no
    requirement at all, and only a member the walk actually reaches is judged:
    a namespace already reported malformed contributes no second violation.
    """
    violations: list[dict] = []
    capabilities = source.get("capabilities")
    bindings = source.get("bindings")
    if not isinstance(capabilities, dict) or not isinstance(bindings, dict):
        return violations
    for name in AUTHORED_CAPABILITY_NAMES:
        declaration = capabilities.get(name)
        if (not isinstance(declaration, dict)
                or declaration.get("support") != "supported"):
            continue
        for path, is_complete in CAPABILITY_BINDING_REQUIREMENTS[name]:
            found, value = find_binding(bindings, path)
            if found and not is_complete(value):
                violations.append(violation(
                    "/bindings/" + "/".join(path),
                    f"must be complete: capability '{name}' is declared supported",
                    f"contract.capabilities.{name}.binding_incomplete",
                ))
    return violations


def validate_projection_entries(source: dict, violations: list[dict]) -> None:
    """Every shape violation of the declared projection entries.

    Named for the entries rather than the member because `validate_projections`
    below judges the same projections against the filesystem.
    """
    projections = source.get("projections")
    if not check_list(projections, "/projections", "projections", violations):
        return
    seen: set[str] = set()
    targets: dict[str, int] = {}
    sources: set[str] = set()
    for index, entry in enumerate(projections):
        pointer = f"/projections/{index}"
        if not check_object(entry, pointer, "projections", violations):
            continue
        check_exact_members(
            entry, pointer, PROJECTION_MEMBERS, "projections", violations)
        if "id" in entry and check_string(
                entry["id"], f"{pointer}/id", "projections", violations):
            if entry["id"] in seen:
                violations.append(violation(
                    f"{pointer}/id", "projection id is declared more than once",
                    "contract.projections.duplicate_id"))
            seen.add(entry["id"])
        if "agent" in entry and entry["agent"] not in AGENT_IDS:
            violations.append(violation(
                f"{pointer}/agent", "must name a known agent",
                "contract.projections.invalid_agent"))
        if "kind" in entry and entry["kind"] not in PROJECTION_KINDS:
            violations.append(violation(
                f"{pointer}/kind", "must name a known projection kind",
                "contract.projections.invalid_kind"))
        for name in ("target", "source"):
            if name in entry and check_safe_path(
                    entry[name], f"{pointer}/{name}", "projections", violations):
                if name == "source":
                    sources.add(entry[name])
                elif entry[name] in targets:
                    # The writer visits entries in order and never re-reads what
                    # it wrote, so a second entry on one target silently leaves
                    # the first projection stale behind a successful exit.
                    violations.append(violation(
                        f"{pointer}/target",
                        "projection target is declared more than once",
                        "contract.projections.duplicate_target"))
                else:
                    targets[entry[name]] = index
    # A target that is also somebody's source is the same collision one step
    # removed: writing the target would overwrite an authored instruction file.
    for target, index in sorted(targets.items(), key=lambda item: item[1]):
        if target in sources:
            violations.append(violation(
                f"/projections/{index}/target",
                "must not name a projection source: writing the target would "
                "overwrite the authored source it is rendered from",
                "contract.projections.target_is_source"))


def projection_paths(source: object) -> list[str]:
    """The paths beyond the contract file that resolving `source` reads.

    `validate_projections` reads each projection entry's `source` and `target`,
    so this lists, in declaration order (an entry's `source` before its
    `target`), every such member that `is_safe_relative_path` accepts, each path
    once. It never raises: a `source` that is not an object, a `projections`
    that is not a list, an entry that is not an object, and a member that is
    absent or not a safe relative path each contribute nothing, because the
    resolver itself refuses those shapes.
    """
    if not isinstance(source, dict) or not isinstance(source.get("projections"), list):
        return []
    paths: list[str] = []
    for entry in source["projections"]:
        if not isinstance(entry, dict):
            continue
        for name in ("source", "target"):
            path = entry.get(name)
            if is_safe_relative_path(path) and path not in paths:
                paths.append(path)
    return paths


def check_production_entries(
        section: dict, name: str, pointer: str, commands: dict | None,
        changing: list | None, violations: list[dict]) -> None:
    """One list of a `production` route group, entry by entry.

    `changing` is the same-named `changes` list when this group is `read_only`:
    an entry in both is refused, since one route cannot both change and only
    read production.
    """
    if name not in section or not check_list(
            section[name], pointer, "production", violations):
        return
    for index, value in enumerate(section[name]):
        entry = f"{pointer}/{index}"
        if name == "commands":
            check_command_id(value, entry, commands, violations, section="production")
        elif name == "key_files":
            check_contract_glob(value, entry, violations, section="production")
        elif not isinstance(value, str) or not MCP_TOOL_NAME_PATTERN.fullmatch(value):
            violations.append(violation(
                entry, "must name one MCP tool as mcp__<server>__<tool>",
                "contract.production.not_mcp_tool"))
            continue
        if changing is not None and isinstance(value, str) and value in changing:
            violations.append(violation(
                entry, "is also declared as changing production",
                "contract.production.route_both_ways"))


def platform_commands(source: object) -> dict:
    """The platform command table the contract's schema reads: schema 3 adds `commit-environment`."""
    if schema_three.declares(source):
        return schema_three.COMMANDS
    return agent_platform.PLATFORM_COMMANDS


def derive_for(root: Path, source: object) -> derived_values.Derived:
    """The values `root` states for a schema-3 `source`; nothing, and no file read, for any other schema."""
    if schema_three.declares(source):
        return derived_values.derive(root)
    return derived_values.Derived({}, [])


def contract_view(source: dict, derived: derived_values.Derived) -> dict:
    """The contract the shape rules and the snapshot read: schema 3 with its constants and derived values filled, else `source`."""
    if schema_three.declares(source):
        return schema_three.fill(source, derived.values)
    return source


def load_contract_view(root: Path) -> dict:
    """The contract at `root` as its readers outside the resolver see it: `contract_view` of `load_contract`."""
    source = load_contract(root)
    return contract_view(source, derive_for(root, source))


def effective_commands(authored: dict | None,
                       platform: dict = agent_platform.PLATFORM_COMMANDS) -> dict | None:
    """The authored commands plus every platform command the contract does not author.

    None stays None. An authored id always wins whole (ADR-project-contract-010);
    each platform entry is a deep copy, so no caller can change the definition.
    """
    if authored is None:
        return None
    merged = {command_id: copy.deepcopy(entry)
              for command_id, entry in platform.items()
              if command_id not in authored}
    merged.update(authored)
    return merged


def production_commands(source: dict) -> dict | None:
    """The authored `bindings.commands` object with the platform's, or None when it is not one (as `validate_bindings`)."""
    bindings = source.get("bindings")
    commands = bindings.get("commands") if isinstance(bindings, dict) else None
    return effective_commands(
        commands if isinstance(commands, dict) else None, platform_commands(source))


def validate_production(source: dict, violations: list[dict]) -> None:
    """The optional `production` member: no production, or its rules."""
    production = source["production"]
    if not check_object(production, "/production", "production", violations):
        return
    if "none" not in production:
        violations.append(violation(
            "/production/none", "required member is absent",
            "contract.production.member_missing"))
        none = None
    else:
        none = production["none"]
        if not check_boolean(none, "/production/none", "production", violations):
            none = None
    if none is True:
        for name in sorted(production):
            if name in PRODUCTION_RULE_MEMBERS + PRODUCTION_OPTIONAL_MEMBERS:
                violations.append(violation(
                    f"/production/{name}",
                    "must be absent: the contract declares no production",
                    "contract.production.none_with_rules"))
            elif name != "none":
                violations.append(violation(
                    f"/production/{name}", "member is not part of this schema",
                    "contract.production.member_unexpected"))
        return
    if none is not False:
        # An absent or malformed `none` is reported once; the rule forms are
        # not judged against a form the contract did not pick.
        for name in sorted(production):
            if name != "none" and name not in (
                    PRODUCTION_RULE_MEMBERS + PRODUCTION_OPTIONAL_MEMBERS):
                violations.append(violation(
                    f"/production/{name}", "member is not part of this schema",
                    "contract.production.member_unexpected"))
        return
    check_exact_members(
        production, "/production", ("none",) + PRODUCTION_RULE_MEMBERS,
        "production", violations, optional=PRODUCTION_OPTIONAL_MEMBERS)
    commands = production_commands(source)
    changes = production.get("changes")
    if "changes" in production and check_object(
            changes, "/production/changes", "production", violations):
        check_exact_members(
            changes, "/production/changes", PRODUCTION_CHANGE_MEMBERS,
            "production", violations)
        for name in PRODUCTION_CHANGE_MEMBERS:
            check_production_entries(
                changes, name, f"/production/changes/{name}", commands, None,
                violations)
        lists = [changes.get(name) for name in PRODUCTION_CHANGE_MEMBERS]
        if all(isinstance(item, list) and not item for item in lists):
            violations.append(violation(
                "/production/changes",
                "must name at least one command, key file or MCP tool that "
                "changes production",
                "contract.production.no_change_route"))
    if "console_activation" in production and check_string(
            production["console_activation"], "/production/console_activation",
            "production", violations):
        changing = changes.get("commands") if isinstance(changes, dict) else None
        if isinstance(changing, list) and production["console_activation"] not in changing:
            violations.append(violation(
                "/production/console_activation",
                "names no command of production.changes.commands",
                "contract.production.console_activation_not_a_change"))
    read_only = production.get("read_only")
    if "read_only" in production and check_object(
            read_only, "/production/read_only", "production", violations):
        check_exact_members(
            read_only, "/production/read_only", PRODUCTION_READ_ONLY_MEMBERS,
            "production", violations)
        for name in PRODUCTION_READ_ONLY_MEMBERS:
            routes = changes.get(name) if isinstance(changes, dict) else None
            check_production_entries(
                read_only, name, f"/production/read_only/{name}", commands,
                routes if isinstance(routes, list) else None, violations)
    if "release_profile" in production and check_string(
            production["release_profile"], "/production/release_profile",
            "production", violations):
        release = source.get("release")
        profiles = release.get("profiles") if isinstance(release, dict) else None
        # Any other `release` shape is skipped: the release grammar reports it.
        if release == "unsupported" or (
                isinstance(profiles, dict)
                and production["release_profile"] not in profiles):
            violations.append(violation(
                "/production/release_profile",
                "names no profile of release.profiles",
                "contract.production.unknown_release_profile"))


def validate_contract(source: dict, manifest: dict,
                      derived: derived_values.Derived) -> list[dict]:
    """Every shape violation of the authored source, collected in one pass.

    Each returned violation carries `pointer`, `message` and the internal
    `repair_id` that `raise_for_violations` publishes for the first violation
    in pointer order. The list is returned unsorted; the caller orders it.

    `manifest` is the installed platform manifest: it carries the set of
    project schema versions this platform supports (D8), which is the only
    authority for "supported" — the resolver holds no schema literal.

    `derived` is what `derive_for` read for this source. A value it could not
    derive is its own violation, so the shape violation that only restates it
    (the same pointer, one beneath it, or the `project` container whose only
    member is the failed id) is dropped; every other shape violation stays.
    """
    violations: list[dict] = []
    validate_schema_version(
        source, violations, manifest["project_schema_versions"])
    # Schema 3 is judged through its filled view: the shape rules are schema 2's,
    # over the member lists schema 3 keeps. What the contract authors that the
    # platform decides or the repository states is refused from the authored
    # source first.
    three = schema_three.declares(source)
    if three:
        violations.extend(schema_three.refusals(source))
        violations.extend(derived.violations)
    source = contract_view(source, derived)
    shape: list[dict] = []
    for name in TOP_LEVEL_MEMBERS:
        # `schema_version` reports its own absence above, with the repair id
        # that names the version rather than the generic missing-member one.
        if name != "schema_version" and name not in source:
            shape.append(violation(
                f"/{name}", "required member is absent",
                "contract.top_level.member_missing"))
    for name in sorted(source):
        if name not in TOP_LEVEL_MEMBERS and name not in TOP_LEVEL_OPTIONAL_MEMBERS:
            shape.append(violation(
                f"/{name}", "member is not part of this schema",
                "contract.top_level.member_unexpected"))
    if "project" in source:
        validate_project(source, shape, **({"members": ("id",)} if three else {}))
    if "bindings" in source:
        validate_bindings(
            source, shape,
            schema=schema_three.SCHEMA_VERSION if three else 2)
    if "capabilities" in source:
        validate_capabilities(source, shape)
    if "projections" in source:
        validate_projection_entries(source, shape)
    if "platform" in source:
        validate_platform(source, shape)
    if "release" in source:
        # D2: the grammar's violations join the one ordered list; what the
        # admissibility rules refuse is a capability state, never a violation.
        shape.extend(
            release_profile.grammar_violations(source["release"], source))
    if "production" in source:
        validate_production(source, shape)
    shape.extend(validate_capability_bindings(source))
    failed = [entry["pointer"] for entry in derived.violations]
    violations.extend(
        entry for entry in shape
        if not any(entry["pointer"] == pointer
                   or entry["pointer"].startswith(pointer + "/")
                   or (entry["pointer"] in schema_three.DERIVED_CONTAINERS
                       and pointer.startswith(entry["pointer"] + "/"))
                   for pointer in failed))
    return violations


# --------------------------------------------------------------------------
# Normalization and snapshot assembly
# --------------------------------------------------------------------------


def normalize_bindings(source_bindings: dict, root: Path,
                       platform: dict = agent_platform.PLATFORM_COMMANDS) -> dict:
    """The source bindings with every authored path made absolute under `root`.

    The platform commands (`platform`) the contract does not author are added
    first. Exactly the artifact paths (when present), the six knowledge path
    lists and each command's `cwd` are rewritten; every other value is passed
    through byte-for-byte.
    """
    bindings = copy.deepcopy(source_bindings)
    bindings["commands"] = effective_commands(bindings["commands"], platform)
    paths = bindings["paths"]
    artifacts = paths.get("artifacts")
    if artifacts is not None:
        for name in ("specs", "plans"):
            artifacts[name] = str(root / artifacts[name])
    for name in PATHS_LIST_MEMBERS:
        paths[name] = [str(root / entry) for entry in paths[name]]
    for entry in bindings["commands"].values():
        entry["cwd"] = str(root / entry["cwd"])
    return bindings


def resolves_on_path(argv0: str, cwd: Path) -> bool:
    """True when argv0 names a runnable binary, without executing it.

    `cwd` is the base for a relative argv0 and is already absolute.
    """
    if "/" not in argv0:
        return shutil.which(argv0) is not None
    candidate = Path(cwd) / argv0
    return candidate.is_file() and os.access(candidate, os.X_OK)


def commands_resolve(bindings: dict, command_ids: list[str]) -> bool:
    """Every named command's argv[0] resolves, each against its own `cwd` (D22)."""
    for command_id in command_ids:
        entry = bindings["commands"][command_id]
        if not resolves_on_path(entry["argv"][0], Path(entry["cwd"])):
            return False
    return True


def first_unmet_prerequisite(name: str, bindings: dict, root: Path) -> str | None:
    """The first failing prerequisite's reason code, or None when all pass.

    Only the declared `supported` capabilities reach here, and D6 has already
    refused an incomplete binding, so every member read below is present.
    """
    if name == "tracker":
        # The tracker CLI is not a `commands` entry, so its base is the root.
        if not resolves_on_path(bindings["tracker"]["cli"], root):
            return "tracker_cli_missing"
        return None
    if name == "worktrees":
        if not resolves_on_path("git", root):
            return "vcs_worktree_unsupported"
        # The parent of the worktree root, not the root itself: the root is
        # created lazily on first use, so demanding it exist would report a
        # working capability as blocked in every fresh checkout.
        parent = (root / bindings["vcs"]["worktree"]["root"]).parent
        if not (parent.is_dir() and os.access(parent, os.W_OK)):
            return "vcs_worktree_unsupported"
        return None
    if name in KNOWLEDGE_PATH_MEMBERS:
        entries = bindings["paths"][KNOWLEDGE_PATH_MEMBERS[name]]
        if not entries or not all((root / entry).exists() for entry in entries):
            return "knowledge_path_missing"
        return None
    if name == "verification":
        ids = bindings["workflow"]["verification"]
    elif name == "review.plan":
        ids = [bindings["workflow"]["review"]["plan"]]
    elif name == "review.code":
        ids = [bindings["workflow"]["review"]["code"]]
    else:
        raise ValueError(f"unknown capability name: {name!r}")
    return None if commands_resolve(bindings, ids) else "command_missing"


def release_capability(release: object, source: dict, root: Path) -> dict:
    """The derived `capabilities.release` entry (D1, D23).

    `release` is the authored member and the grammar has already accepted it,
    which `admissibility_findings` assumes. It is `unsupported` when authored
    as `"unsupported"` or when no profile has a publication node, before any
    admissibility or executable check. Otherwise profiles are read in sorted id
    order: the first with an admissibility finding blocks as
    `release_profile_inadmissible`; failing that, the first executable some
    bound adapter's descriptor names that does not resolve blocks as
    `release_adapter_unavailable`; otherwise the capability is available.
    """
    if release == "unsupported":
        return {"state": "unsupported", "reason_code": None, "repair_id": None}
    profiles = release["profiles"]
    if not any(release_profile.phase_nodes(profile, "publication")
               for profile in profiles.values()):
        return {"state": "unsupported", "reason_code": None, "repair_id": None}
    reason_code = None
    for profile_id in sorted(profiles):
        if release_profile.admissibility_findings(
                profile_id, profiles[profile_id], source):
            reason_code = "release_profile_inadmissible"
            break
    else:
        for profile_id in sorted(profiles):
            adapters = profiles[profile_id]["bindings"]["adapters"]
            for alias in sorted(adapters):
                descriptor = release_adapter.DESCRIPTORS[adapters[alias]["adapter"]]
                if not all(resolves_on_path(name, root)
                           for name in descriptor["executables"]):
                    reason_code = "release_adapter_unavailable"
                    break
            if reason_code is not None:
                break
    if reason_code is None:
        return {"state": "available", "reason_code": None, "repair_id": None}
    return {"state": "blocked", "reason_code": reason_code,
            "repair_id": f"capability.release.{reason_code}"}


def compute_capabilities(bindings: dict, root: Path, declarations: dict,
                         release: object, source: dict) -> dict:
    """Contract: eleven entries, each {"state", "reason_code", "repair_id"}.

    Ten are read from the authored `declarations`; `release` is derived from
    the `release` member by `release_capability` (D1).
    """
    resolved = {}
    for name in CAPABILITY_NAMES:
        if name == "release":
            resolved[name] = release_capability(release, source, root)
            continue
        support = declarations[name]["support"]
        if support == "unsupported":
            resolved[name] = {
                "state": "unsupported", "reason_code": None, "repair_id": None}
            continue
        if support != "supported":
            raise ValueError(f"unknown authored support value: {support!r}")
        reason_code = first_unmet_prerequisite(name, bindings, root)
        if reason_code is None:
            resolved[name] = {
                "state": "available", "reason_code": None, "repair_id": None}
        else:
            resolved[name] = {
                "state": "blocked",
                "reason_code": reason_code,
                "repair_id": f"capability.{name}.{reason_code}",
            }
    return resolved


def production_rules(source: dict) -> dict:
    """The snapshot's derived `production` member (statuses: PRODUCTION_STATUSES)."""
    if "production" not in source:
        return {"status": "not_declared"}
    production = source["production"]
    if production["none"]:
        return {"status": "none"}
    rules = {
        "status": "declared",
        "changes": copy.deepcopy(production["changes"]),
        "read_only": copy.deepcopy(production["read_only"]),
        "release_profile": production["release_profile"],
    }
    if "console_activation" in production:
        rules["console_activation"] = production["console_activation"]
    return rules


def build_snapshot(root: Path, source: dict, manifest: dict,
                   derived: derived_values.Derived) -> dict:
    # Readiness reads the normalized bindings, so each command's `cwd` is
    # already the absolute base a relative argv[0] resolves against (D22).
    #
    # D8: the snapshot's own interface version is the manifest's
    # `resolved_schema_version`, the schema this platform resolves *to*. It is
    # not the contract's declared `schema_version`, which may legally be an
    # older supported schema (R2.5).
    view = contract_view(source, derived)
    bindings = normalize_bindings(view["bindings"], root, platform_commands(source))
    project = {"root": str(root), "id": view["project"]["id"]}
    if "name" in view["project"]:
        project["name"] = view["project"]["name"]
    return {
        "schema_version": manifest["resolved_schema_version"],
        "project": project,
        "bindings": bindings,
        "capabilities": compute_capabilities(
            bindings, root, view["capabilities"], view["release"], view),
        "release": {"targets": release_profile.release_targets(view["release"])},
        "production": production_rules(view),
    }


def unavailable_reason(entry: dict) -> str:
    """The repair-id suffix a non-available capability contributes.

    Each of the three states is named. `available` never reaches here — only
    an offending entry is asked for a reason — and a state outside the closed
    set is a bug in this module, so both raise rather than defaulting to a
    plausible-looking `unsupported`.
    """
    state = entry["state"]
    if state == "blocked":
        return entry["reason_code"]
    if state == "unsupported":
        return "unsupported"
    raise ValueError(f"unknown capability state: {state!r}")


def unavailable_message(entry: dict) -> str:
    """The violation message a non-available capability contributes."""
    state = entry["state"]
    if state == "blocked":
        return f"required capability is blocked: {entry['reason_code']}"
    if state == "unsupported":
        return "required capability is unsupported by this project"
    raise ValueError(f"unknown capability state: {state!r}")


def raise_for_unavailable(required: list[str] | None, capabilities: dict) -> None:
    """Refuse `capability_unavailable` when a `--require` name is not available.

    Names are visited in sorted order, which is pointer order because every
    pointer shares the `/capabilities/` prefix; the published repair id names
    the first offender in that order.
    """
    offending = [
        (name, capabilities[name])
        for name in sorted(set(required or ()))
        if capabilities[name]["state"] != "available"
    ]
    if not offending:
        return
    violations = [
        {
            "pointer": f"/capabilities/{name}",
            "message": unavailable_message(entry),
        }
        for name, entry in offending
    ]
    first_name, first_entry = offending[0]
    raise ContractError(
        "capability_unavailable",
        f"capability.{first_name}.{unavailable_reason(first_entry)}",
        violations,
    )


# --------------------------------------------------------------------------
# Projections
# --------------------------------------------------------------------------


def read_projection_source(root: Path, entry: dict) -> bytes:
    """Contract: the source bytes, or ContractError when the file is absent.

    An instruction source that is gone is a broken contract, not drift in the
    target it feeds: the authored side is what needs repairing.
    """
    try:
        return (root / entry["source"]).read_bytes()
    except OSError:
        raise ContractError(
            "invalid_contract",
            "contract.projections.source_missing",
            [{
                "pointer": f"/projections/{entry['id']}/source",
                "message": "the declared projection source file cannot be read",
            }],
        ) from None


def render_projection(entry: dict, source_bytes: bytes,
                      schema_version: int) -> bytes:
    """Contract: the exact bytes a generated_file target must hold, or the
    exact single managed line (with its newline) a managed_import must contain.

    A pure function of its three arguments: no clock, no environment, no path
    outside the entry, so regeneration on any machine is byte-identical.
    `schema_version` is the contract's own declared schema — the header records
    which project schema the target was generated from, so a project resting on
    a supported older schema keeps its bytes (R2.5) rather than drifting the
    moment the platform's `resolved_schema_version` moves.
    """
    kind = entry["kind"]
    if kind == "generated_file":
        header = GENERATED_HEADER_TEMPLATE.format(
            source=entry["source"], version=schema_version)
        return header.encode("utf-8") + b"\n\n" + source_bytes
    if kind == "managed_import":
        line = MANAGED_IMPORT_TEMPLATE.format(source=entry["source"])
        return (line + "\n").encode("utf-8")
    raise ValueError(f"unknown projection kind: {kind!r}")


def read_projection_target(root: Path, entry: dict) -> bytes | None:
    """The target's current bytes, or None when there is no readable target."""
    try:
        return (root / entry["target"]).read_bytes()
    except OSError:
        return None


def managed_line_occurrences(target_bytes: bytes, entry: dict) -> int:
    """How many whole lines of the target are the entry's managed import line.

    Decoded leniently: the surrounding file is authored prose the resolver
    never rewrites, and a byte it cannot decode is not the ASCII managed line.
    """
    line = MANAGED_IMPORT_TEMPLATE.format(source=entry["source"])
    return target_bytes.decode("utf-8", errors="replace").splitlines().count(line)


def projection_status(root: Path, entry: dict, schema_version: int) -> str:
    """Contract: exactly one of "in_sync", "missing", "stale".

    The source is read for either kind, so a missing source refuses as
    `invalid_contract` before any target is ever judged.
    """
    source_bytes = read_projection_source(root, entry)
    existing = read_projection_target(root, entry)
    if existing is None:
        return "missing"
    kind = entry["kind"]
    if kind == "generated_file":
        return "in_sync" if existing == render_projection(
            entry, source_bytes, schema_version) else "stale"
    if kind == "managed_import":
        return "in_sync" if managed_line_occurrences(existing, entry) == 1 \
            else "stale"
    raise ValueError(f"unknown projection kind: {kind!r}")


def validate_projections(root: Path, contract: dict) -> None:
    """Contract: returns None when every declared projection is in sync;
    otherwise raises ContractError("invalid_projection", …) with one violation
    per drifted projection, sorted by pointer.

    `projection_status` reads each entry's source before it judges any target,
    so a source that is gone refuses as `invalid_contract` and propagates from
    here before drift is ever considered.
    """
    drifted: list[tuple[str, dict]] = []
    for entry in contract["projections"]:
        # Each of the three statuses is named: a value outside the closed set
        # is a bug in this module, and reclassifying it as drift would hide
        # that behind a plausible refusal.
        status = projection_status(root, entry, contract["schema_version"])
        if status == "in_sync":
            continue
        if status == "missing":
            message = ("the projection target is absent; regenerate it with "
                       "`resolve-project write-projections`")
        elif status == "stale":
            message = ("the projection target no longer matches its source; "
                       "regenerate it with `resolve-project write-projections`")
        else:
            raise ValueError(f"unknown projection status: {status!r}")
        drifted.append((status, {
            "pointer": f"/projections/{entry['id']}",
            "message": message,
        }))
    if not drifted:
        return
    drifted.sort(key=lambda item: item[1]["pointer"])
    first_status, first = drifted[0]
    raise ContractError(
        "invalid_projection",
        f"projection.{first['pointer'].rsplit('/', 1)[-1]}.{first_status}",
        [item for _, item in drifted],
    )


def apply_projection(root: Path, entry: dict, schema_version: int,
                    violations: list[dict]) -> str | None:
    """Bring one target into sync and name the action taken.

    Returns None when the entry is refused rather than resolved: a managed
    import already present more than once is reported, never repaired, because
    only the author knows which of the duplicates was meant (D17).
    """
    rendered = render_projection(
        entry, read_projection_source(root, entry), schema_version)
    target = root / entry["target"]
    status = projection_status(root, entry, schema_version)
    if status == "in_sync":
        return "unchanged"
    if status == "missing":
        agent_platform.write_atomically(target, rendered)
        return "written"
    if status != "stale":
        raise ValueError(f"unknown projection status: {status!r}")
    kind = entry["kind"]
    if kind == "generated_file":
        agent_platform.write_atomically(target, rendered)
        return "written"
    if kind != "managed_import":
        raise ValueError(f"unknown projection kind: {kind!r}")
    existing = target.read_bytes()
    if managed_line_occurrences(existing, entry) > 1:
        violations.append({
            "pointer": f"/projections/{entry['id']}",
            "message": ("the managed import line is present more than once; "
                        "remove the duplicates by hand and rerun"),
        })
        return None
    # Zero occurrences: the authored body is kept verbatim and the managed
    # line is appended, on a line of its own.
    suffix = rendered if existing.endswith(b"\n") or not existing \
        else b"\n" + rendered
    agent_platform.write_atomically(target, existing + suffix)
    return "written"


def raise_for_projection_violations(violations: list[dict]) -> None:
    """Publish collected refusals as one ordered `invalid_projection`."""
    if not violations:
        return
    ordered = sorted(violations, key=lambda item: item["pointer"])
    first_id = ordered[0]["pointer"].rsplit("/", 1)[-1]
    raise ContractError(
        "invalid_projection", f"projection.{first_id}.stale", ordered)


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def emit_json(value: object) -> int:
    # `allow_nan=False`: the parse side already refuses the three non-finite
    # tokens, and this is the second half of that check — nothing this tool
    # prints is JSON another parser would reject. The document is serialized
    # whole before any byte is written, so a value the guard refuses leaves
    # stdout empty for the error object instead of truncating mid-response.
    text = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)
    sys.stdout.write(text + "\n")
    return 0


def emit_error(code: str, repair_id: str, violations: list[dict],
               reason_code: str | None = None) -> int:
    """The one place an error object reaches stdout (D12).

    D7 fixes `reason_code`'s position exactly: present for `unsupported_schema`
    and absent for every other code. That rule is asserted here rather than
    trusted from the caller — a defence in depth, so no future refusal path can
    publish a reason code out of position or one outside the closed set.
    """
    if (reason_code is not None) != (code == "unsupported_schema"):
        raise ValueError(
            "reason_code belongs to unsupported_schema and to no other code: "
            f"got code {code!r} with reason_code {reason_code!r}")
    if reason_code is not None \
            and reason_code not in agent_platform.SCHEMA_REASON_CODES:
        raise ValueError(f"unknown schema reason code: {reason_code!r}")
    error = {"code": code, "repair_id": repair_id, "violations": violations}
    if reason_code is not None:
        error["reason_code"] = reason_code
    emit_json({"error": error})
    return 2


def require_platform_manifest(path: Path | None = None) -> tuple[dict, Path]:
    """The installed platform manifest, or a refusal if it will not load.

    Every subcommand calls this before root discovery and before any contract
    read, so a broken platform installation always surfaces as
    `resolver_failure` and can never be masked by `not_onboarded` or a contract
    error (R1.3). There is no default and no assumed version: the library's
    ordered violations are published verbatim.

    It returns the manifest because the manifest is now read for its values —
    `project_schema_versions` (D8), `resolved_schema_version` and
    `platform_version` (R2.3) — and beside it the absolute resolved path it was
    loaded from, which is the deployment identity `platform-status` publishes
    (D2). One load, one call site: a second `load_manifest()` elsewhere would
    be a second failure surface for one fact.

    `path` names another manifest to judge against (`platform-status
    --manifest`, issue 579 P7); it loads by the same rules and refuses the
    same way.
    """
    try:
        manifest, path = agent_platform.load_manifest(path)
    except agent_platform.PlatformManifestError as error:
        raise ContractError(
            "resolver_failure", error.repair_id, error.violations) from None
    return manifest, path


def require_registry() -> list[dict]:
    """The registered fleet, or a refusal when the registry will not read.

    The registry is platform-written state, so a corrupt one is an installation
    defect and reaches the caller as `resolver_failure`, exactly like a corrupt
    manifest. An absent one is the empty fleet and never gets here.
    """
    try:
        return agent_platform.read_registry()
    except agent_platform.PlatformManifestError as error:
        raise ContractError(
            "resolver_failure", error.repair_id, error.violations) from None


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------


RESOLVER_FAILURE_VIOLATIONS = [
    {"pointer": "", "message": "the resolver failed unexpectedly"}]


def resolve(repo_root: str | None, required: list[str] | None = None) -> dict:
    """The `ResolvedProject` snapshot for `repo_root`, or `ContractError`.

    Exactly the composition `resolve-project resolve` prints (#279 D1);
    `conformance_checks` keeps its own, collecting composition. Any other
    exception (a non-finite number, or an integer past Python's digit limit,
    which `load_contract` does not translate) raises the same fixed
    `resolver_failure` the command's outer handler prints, so no caller
    evaluates, or crashes on, a project the command refuses.
    """
    try:
        return compose_snapshot(repo_root, required)
    except ContractError:
        raise
    except Exception:
        raise ContractError("resolver_failure", "resolver.internal",
                            RESOLVER_FAILURE_VIOLATIONS) from None


def compose_snapshot(repo_root: str | None, required: list[str] | None) -> dict:
    """`resolve()`'s composition; a non-standard-JSON snapshot raises `ValueError`."""
    # Before root discovery, so a broken platform installation can never be
    # masked by `not_onboarded` or a contract error (R1.3).
    manifest, _ = require_platform_manifest()
    root = discover_root(repo_root)
    source = load_contract(root)
    derived = derive_for(root, source)
    raise_for_violations(validate_contract(source, manifest, derived))
    # The range check is the inner half of the manifest gate, and it runs only
    # once interval *shape* validation has succeeded: a malformed interval is
    # `invalid_contract`, an out-of-range one `unsupported_schema` (R2.3).
    raise_for_platform_range(
        contract_view(source, derived)["platform"], manifest["platform_version"])
    # Drift is a structural refusal, not a capability state, and it refuses
    # before a single snapshot member exists (D10).
    validate_projections(root, source)
    snapshot = build_snapshot(root, source, manifest, derived)
    raise_for_unavailable(required, snapshot["capabilities"])
    json.dumps(snapshot, allow_nan=False)
    return snapshot


def command_resolve(args: argparse.Namespace) -> int:
    return emit_json(resolve(args.repo_root, args.require))


def command_write_projections(args: argparse.Namespace) -> int:
    """The tool's only writer: bring every declared target into sync.

    A broken contract still refuses first, so nothing is written on the
    strength of a source the validator would reject. Entries are visited in
    the order they are declared; targets already written before a refusing
    entry keep their new bytes and the refusal names only what it could not
    resolve.
    """
    # Before root discovery, so a broken platform installation can never be
    # masked by `not_onboarded` or a contract error (R1.3).
    manifest, _ = require_platform_manifest()
    root = discover_root(args.repo_root)
    source = load_contract(root)
    raise_for_violations(validate_contract(source, manifest, derive_for(root, source)))
    applied: list[dict] = []
    violations: list[dict] = []
    for entry in source["projections"]:
        action = apply_projection(
            root, entry, source["schema_version"], violations)
        if action is not None:
            applied.append({"id": entry["id"], "action": action})
    raise_for_projection_violations(violations)
    return emit_json({"projections": applied})


def command_check_projections(args: argparse.Namespace) -> int:
    """Report every declared projection as in sync, or refuse on drift.

    A broken contract still refuses first, so drift is only ever reported
    against a source the validator accepts. Like `resolve`, this reads: it
    opens no file for writing and creates no directory.
    """
    # Before root discovery, so a broken platform installation can never be
    # masked by `not_onboarded` or a contract error (R1.3).
    manifest, _ = require_platform_manifest()
    root = discover_root(args.repo_root)
    source = load_contract(root)
    raise_for_violations(validate_contract(source, manifest, derive_for(root, source)))
    validate_projections(root, source)
    return emit_json({"projections": [
        {"id": entry["id"], "action": "unchanged"}
        for entry in source["projections"]
    ]})


# --------------------------------------------------------------------------
# `platform-status`
#
# D6 fixes the split this operation turns on: a contract that cannot be parsed
# into an interval is refused exactly as `resolve` refuses it, while an
# interval that parses and falls outside the range is the verdict the operation
# exists to publish. Everything below reads (R3.6): no file is opened for
# writing, no directory is created — the registry reader reads `state_root()`
# and never makes it — and no child process runs.
# --------------------------------------------------------------------------


def platform_block(manifest: dict, manifest_path: Path) -> dict:
    """The installed platform's facts, verbatim, and where they came from.

    `manifest_path` is the absolute resolved path of the file actually loaded,
    which under Home Manager is the content-addressed store path (D2). It is
    published as it is: shortening it would discard the deployment identity it
    exists to carry.
    """
    block = {name: manifest[name] for name in PLATFORM_STATUS_MANIFEST_MEMBERS}
    block["manifest_path"] = str(manifest_path)
    return block


def compatibility_block(reason_code: str | None) -> dict:
    """One contract's verdict; `reason_code` None is the compatible answer.

    The repair id comes from the same exhaustive dispatch `unsupported_schema`
    publishes, so a reported verdict and the refusal for the same cause always
    name one repair.
    """
    return {
        "compatible": reason_code is None,
        "reason_code": reason_code,
        "repair_id": (None if reason_code is None
                      else schema_reason_repair_id(reason_code)),
    }


def declared_facts(source: object) -> dict:
    """What a contract declares about its identity, schema and interval.

    Read defensively, because this also runs over contracts validation
    rejected: a fleet member's, or one at a schema this platform does not
    publish, whose remaining members were never shape-checked. A member that is
    absent or of the wrong shape is reported as null — a description of what is
    written, never a defaulted value, since nothing here is used as policy.
    """
    facts: dict = {
        "project_id": None,
        "project_schema_version": None,
        "platform_interval": None,
    }
    if not isinstance(source, dict):
        return facts
    identity = source.get("project")
    if isinstance(identity, dict) and isinstance(identity.get("id"), str) \
            and identity["id"]:
        facts["project_id"] = identity["id"]
    version = source.get("schema_version")
    if isinstance(version, int) and not isinstance(version, bool):
        facts["project_schema_version"] = version
    interval = source.get("platform")
    if (isinstance(interval, dict)
            and sorted(interval) == sorted(PLATFORM_MEMBERS)
            and all(isinstance(interval[name], str)
                    for name in PLATFORM_MEMBERS)):
        facts["platform_interval"] = {
            name: interval[name] for name in PLATFORM_MEMBERS}
    return facts


def deprecated_uses(root: Path, manifest: dict) -> list[str] | None:
    """The ids of the manifest's `project_file` and `project_schema`
    deprecations this root holds.

    `removed_uses` applies the same rules to `removals`.

    Null when nothing can be said: the root is not a usable directory
    (including one whose parent cannot be searched: `os.path.isdir` answers
    False for every OSError where `Path.is_dir` re-raises EACCES and EIO), or
    a subject cannot be inspected. Absence is only ENOENT or ENOTDIR from
    `lstat`; `os.path.lexists` would turn EACCES or EIO into False and report
    an existing file as absent. Otherwise the ascending ids whose subject path
    exists under the root. A dangling symlink counts, so presence is an
    `lstat`, which does not follow the link. It is not git tracking, because
    this operation starts no child process (R3.6). A `platform_behavior` entry
    names no path and is never listed. This is a warning, never a verdict: it
    changes neither compatibility nor the exit code (issue 66, D2).

    A `project_schema` entry is held when its subject equals the decimal
    `schema_version` of `<root>/.agents/project.json`, read as JSON. A root
    without that file is null, as is one whose file cannot be read or parsed or
    whose version is not an integer, because nothing can be said of it
    (issue 579, P4).
    """
    return _held_uses(root, manifest["deprecations"])


def removed_uses(root: Path, manifest: dict) -> list[str] | None:
    """The ids of the manifest's `removals` this root still holds.

    The `deprecated_uses` rules, applied to `removals` (issue 579 P2): null
    when nothing can be said, otherwise the ascending ids.
    """
    return _held_uses(root, manifest["removals"])


def _held_uses(root: Path, entries: list[dict]) -> list[str] | None:
    if not os.path.isdir(root):
        return None
    schema_entries = [entry for entry in entries
                      if entry["kind"] == "project_schema"]
    uses = []
    if schema_entries:
        try:
            version = json.loads(
                (root / ".agents" / "project.json").read_text("utf-8")
            )["schema_version"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if not isinstance(version, int) or isinstance(version, bool):
            return None
        uses.extend(entry["id"] for entry in schema_entries
                    if entry["subject"] == str(version))
    for entry in entries:
        if entry["kind"] != "project_file":
            continue
        try:
            os.lstat(root / entry["subject"])
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            return None
        uses.append(entry["id"])
    return sorted(uses)


def evaluate_named_project(root: Path, source: dict,
                           manifest: dict) -> tuple[dict, dict]:
    """The `project` and `compatibility` members for the named repository (R3.3).

    A structural violation refuses from here, by letting `raise_for_violations`
    through: the operator asked about this contract, and one that will not
    parse into an interval cannot be evaluated (R3.5). A schema this platform
    does not publish and an out-of-range interval are the two reported
    verdicts.
    """
    try:
        raise_for_violations(
            validate_contract(source, manifest, derive_for(root, source)))
    except ContractError as error:
        if error.code != "unsupported_schema":
            raise
        reason_code = error.reason_code
    else:
        reason_code = agent_platform.interval_verdict(
            manifest["platform_version"],
            source["platform"]["min_inclusive"],
            source["platform"]["max_exclusive"])
    facts = declared_facts(source)
    project = {
        "project_id": facts["project_id"],
        "root": str(root),
        "project_schema_version": facts["project_schema_version"],
        "platform_interval": facts["platform_interval"],
        "deprecated_uses": deprecated_uses(root, manifest),
        "removed_uses": removed_uses(root, manifest),
    }
    return project, compatibility_block(reason_code)


def fleet_verdict(root: Path, manifest: dict) -> tuple[object, str | None]:
    """One registered project's contract, and its failing reason code or None.

    Nothing here refuses. The registry named this project, not the operator, so
    a root that is gone, an unreadable or unparseable contract and a structural
    violation are all reported as `project_schema_unsupported`: a preflight has
    to be able to describe a broken fleet member (R3.4).
    """
    try:
        source = load_contract(root)
    except ContractError:
        return None, "project_schema_unsupported"
    try:
        violations = validate_contract(source, manifest, derive_for(root, source))
    except ContractError as error:
        return source, error.reason_code or "project_schema_unsupported"
    if violations:
        return source, "project_schema_unsupported"
    return source, agent_platform.interval_verdict(
        manifest["platform_version"],
        source["platform"]["min_inclusive"],
        source["platform"]["max_exclusive"])


def fleet_row(entry: dict, manifest: dict) -> dict:
    """One registry entry's verdict row.

    Identity and location come from the registry, because they are the two
    facts a row still has when its contract will not load at all (D18). That
    is also why the identity is checked rather than trusted: a registered root
    that has been replaced, or whose contract now declares a different id,
    still has a registry entry naming the old one, and reporting that entry
    beside a *live* version verdict would call a row compatible whose stale
    half is the very thing a preflight is asked about.

    The check runs only where the row would otherwise be compatible. A row the
    contract already failed carries a verdict and a repair id for that failure,
    and re-labelling it with the identity question would replace one true
    answer with another.
    """
    source, reason_code = fleet_verdict(Path(entry["root"]), manifest)
    facts = declared_facts(source)
    if reason_code is None and facts["project_id"] != entry["project_id"]:
        reason_code = "project_identity_mismatch"
    return {
        "project_id": entry["project_id"],
        "root": entry["root"],
        "project_schema_version": facts["project_schema_version"],
        "platform_interval": facts["platform_interval"],
        "deprecated_uses": deprecated_uses(Path(entry["root"]), manifest),
        "removed_uses": removed_uses(Path(entry["root"]), manifest),
        **compatibility_block(reason_code),
    }


def command_platform_status(args: argparse.Namespace) -> int:
    """Report the platform's facts, and whatever was asked about beside them.

    The five members are always present, `null` where not applicable. Both
    flags compose and neither suppresses the other. The `project` block and
    every fleet row also carry `deprecated_uses`: the ids of the manifest's
    deprecated project files the root still holds, a warning that never
    changes the verdict, and `removed_uses`, the same for its `removals`.
    `--manifest PATH` judges against that manifest instead of the installed
    one (issue 579 P7).

    Projection drift is deliberately not checked: a stale target is `resolve`'s
    structural refusal (D10), not a fact about platform compatibility.
    """
    # Before root discovery, so a broken platform installation can never be
    # masked by `not_onboarded` or a contract error (R1.3).
    manifest, path = require_platform_manifest(
        None if args.manifest is None else Path(args.manifest))
    status: dict = {
        "schema_version": PLATFORM_STATUS_SCHEMA_VERSION,
        "platform": platform_block(manifest, path),
        "project": None,
        "compatibility": None,
        "fleet": None,
    }
    if args.repo_root is not None:
        root = discover_root(args.repo_root)
        status["project"], status["compatibility"] = evaluate_named_project(
            root, load_contract(root), manifest)
    if args.fleet:
        status["fleet"] = sorted(
            (fleet_row(entry, manifest) for entry in require_registry()),
            key=lambda row: row["project_id"])
    return emit_json(status)


def add_repo_root(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument(
        "--repo-root",
        help="the project root; without it the nearest ancestor holding "
             f"{CONTRACT_FILENAME} is used",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resolve-project",
        description="Resolve the authored project contract into a ResolvedProject.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    resolve = subparsers.add_parser(
        "resolve", help="print the ResolvedProject snapshot on stdout")
    add_repo_root(resolve)
    # A closed `choices` set, so an unknown name is argparse's own usage error
    # rather than a JSON refusal (D16).
    resolve.add_argument(
        "--require",
        action="append",
        dest="require",
        default=None,
        choices=list(CAPABILITY_NAMES),
        metavar="CAPABILITY",
        help="refuse unless the named capability is available; repeatable",
    )
    check_projections = subparsers.add_parser(
        "check-projections",
        help="refuse unless every declared projection target is in sync")
    add_repo_root(check_projections)
    write_projections = subparsers.add_parser(
        "write-projections",
        help="write every declared projection target that is missing or stale")
    add_repo_root(write_projections)
    platform_status = subparsers.add_parser(
        "platform-status",
        help="report the installed platform's version facts",
        description=(
            "Report the installed platform's version facts. With --repo-root, "
            "add that project's declared interval and its compatibility "
            "verdict and the deprecated and removed paths it still holds "
            "(deprecated_uses, removed_uses); with --fleet, add one verdict row per "
            "registered project. Without --repo-root no project is "
            "inspected and no project root is discovered."),
    )
    add_repo_root(platform_status)
    platform_status.add_argument(
        "--fleet",
        action="store_true",
        help="add one compatibility row per project in the fleet registry",
    )
    platform_status.add_argument(
        "--manifest",
        help="judge against the platform manifest at this path instead of "
             "the installed one; it is loaded and validated by the same "
             "rules, and a missing or invalid file refuses resolver_failure",
    )
    return parser


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "resolve":
        return command_resolve(args)
    if args.command == "check-projections":
        return command_check_projections(args)
    if args.command == "write-projections":
        return command_write_projections(args)
    if args.command == "platform-status":
        return command_platform_status(args)
    raise ValueError(f"unknown subcommand: {args.command!r}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return dispatch(args)
    except ContractError as error:
        return emit_error(error.code, error.repair_id, error.violations,
                          error.reason_code)
    except Exception:
        # One fixed sentence: refusal bytes stay deterministic and no internal
        # detail reaches the caller.
        return emit_error(
            "resolver_failure",
            "resolver.internal",
            [{"pointer": "", "message": "the resolver failed unexpectedly"}],
        )


if __name__ == "__main__":
    sys.exit(main())
