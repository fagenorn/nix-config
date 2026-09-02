#!/usr/bin/env python3
"""Resolve this repository's authored project contract into a ResolvedProject.

`.agents/project.json` is the only input. `resolve` loads it, validates its
whole shape in one pass, normalizes every authored repository-relative path
against the discovered project root, computes each capability's readiness
from the filesystem and `PATH`, and prints the snapshot as compact sorted JSON
on stdout. No project policy is defaulted, inferred, or sniffed from the
environment (D5); a missing, unexpected or malformed member is a refusal, never
an implied value. Readiness observes the machine but never executes anything:
the subcommand opens no file for writing, creates no directory, and starts no
child process.

A structural refusal prints exactly one JSON object carrying an `error` member
on stdout and exits 2 (D12). An argparse usage error also exits 2 but prints no
JSON, which is how a caller tells the two apart (D16).
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import re
import shutil
import sys


SCHEMA_VERSION = 1
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
    "deploy",
)
BINDING_NAMESPACES = ("vcs", "tracker", "paths", "commands", "workflow", "deploy")
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
)
PROJECTION_KINDS = ("generated_file", "managed_import")
AGENT_IDS = ("claude", "codex")
CONTRACT_FILENAME = ".agents/project.json"

TOP_LEVEL_MEMBERS = (
    "schema_version",
    "project",
    "bindings",
    "capabilities",
    "projections",
)
VCS_MEMBERS = (
    "kind",
    "default_branch",
    "integration_branch",
    "branch_pattern",
    "worktree",
    "commit",
    "merge",
)
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
WORKFLOW_MEMBERS = ("verification", "orchestration", "review", "release")
DEPLOY_MEMBERS = ("adapter", "command", "config")
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
    "release": ((("workflow", "release"), lambda value: value is not None),),
    "deploy": (
        (("deploy", "adapter"), lambda value: value != "none"),
        (("deploy", "command"), lambda value: value is not None),
    ),
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


class ContractError(Exception):
    """One refusal: a closed code, a stable repair id, and ordered violations."""

    def __init__(self, code: str, repair_id: str, violations: list[dict]) -> None:
        super().__init__(f"{code}: {repair_id}")
        self.code = code
        self.repair_id = repair_id
        self.violations = violations


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
                        section: str, violations: list[dict]) -> None:
    """Report every absent required member and every unexpected one."""
    for name in expected:
        if name not in value:
            violations.append(violation(
                f"{pointer}/{name}", "required member is absent",
                f"contract.{section}.member_missing"))
    for name in sorted(value):
        if name not in expected:
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
        source = json.loads(text)
    except json.JSONDecodeError:
        raise refuse(".agents/project.json is not valid JSON") from None
    if not isinstance(source, dict):
        raise refuse(".agents/project.json must hold a JSON object")
    return source


# --------------------------------------------------------------------------
# One-pass structural validation
# --------------------------------------------------------------------------


def validate_schema_version(source: dict, violations: list[dict]) -> None:
    """Version first, but only an unsupported integer version short-circuits.

    An absent, non-integer or boolean version contributes its violation to the
    same one-pass list as every other shape violation: `invalid_contract` owes
    the caller every violation it can see. An integer that is not this
    schema aborts immediately instead, because the schema-1 shape rules the
    rest of this pass applies do not describe another schema (D8, D19).
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
    if value != SCHEMA_VERSION:
        raise ContractError(
            "unsupported_schema",
            "contract.schema_version.unsupported",
            [{
                "pointer": "/schema_version",
                "message": "this resolver supports schema version 1 only",
            }],
        )


def validate_project(source: dict, violations: list[dict]) -> None:
    value = source.get("project")
    if not check_object(value, "/project", "project", violations):
        return
    check_exact_members(value, "/project", ("id", "name"), "project", violations)
    for name in ("id", "name"):
        if name in value:
            check_string(value[name], f"/project/{name}", "project", violations)


def validate_vcs(vcs: dict, violations: list[dict]) -> None:
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
            commit, "/bindings/vcs/commit", ("co_authored_by", "signed"),
            "vcs", violations)
        for name in ("co_authored_by", "signed"):
            if name in commit:
                check_boolean(
                    commit[name], f"/bindings/vcs/commit/{name}", "vcs", violations)
    if "merge" in vcs and check_object(
            vcs["merge"], "/bindings/vcs/merge", "vcs", violations):
        merge = vcs["merge"]
        check_exact_members(
            merge, "/bindings/vcs/merge", ("strategy", "delete_branch"),
            "vcs", violations)
        if "strategy" in merge:
            check_string(
                merge["strategy"], "/bindings/vcs/merge/strategy", "vcs", violations)
        if "delete_branch" in merge:
            check_boolean(
                merge["delete_branch"], "/bindings/vcs/merge/delete_branch",
                "vcs", violations)


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


def validate_paths(paths: dict, violations: list[dict]) -> None:
    check_exact_members(paths, "/bindings/paths", PATHS_MEMBERS, "paths", violations)
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
            for index, word in enumerate(entry["argv"]):
                if not isinstance(word, str):
                    violations.append(violation(
                        f"{pointer}/argv/{index}", "must be a string",
                        "contract.commands.not_string"))
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
                     violations: list[dict]) -> None:
    """A non-empty command id that is a key of `/bindings/commands`."""
    if not check_string(value, pointer, "workflow", violations):
        return
    if commands is not None and value not in commands:
        violations.append(violation(
            pointer, "names no entry of bindings.commands",
            "contract.workflow.unknown_command_id"))


def validate_workflow(workflow: dict, commands: dict | None,
                      violations: list[dict]) -> None:
    check_exact_members(
        workflow, "/bindings/workflow", WORKFLOW_MEMBERS, "workflow", violations)
    pointer = "/bindings/workflow/verification"
    if "verification" in workflow and check_list(
            workflow["verification"], pointer, "workflow", violations):
        for index, value in enumerate(workflow["verification"]):
            check_command_id(value, f"{pointer}/{index}", commands, violations)
    pointer = "/bindings/workflow/orchestration"
    if "orchestration" in workflow and check_object(
            workflow["orchestration"], pointer, "workflow", violations):
        orchestration = workflow["orchestration"]
        check_exact_members(
            orchestration, pointer, ("max_parallel", "attempt_budget_minutes"),
            "workflow", violations)
        for name in ("max_parallel", "attempt_budget_minutes"):
            if name in orchestration:
                check_positive_int(
                    orchestration[name], f"{pointer}/{name}", "workflow", violations)
    pointer = "/bindings/workflow/review"
    if "review" in workflow and check_object(
            workflow["review"], pointer, "workflow", violations):
        review = workflow["review"]
        check_exact_members(review, pointer, ("plan", "code"), "workflow", violations)
        for name in ("plan", "code"):
            if name in review and review[name] is not None:
                check_command_id(
                    review[name], f"{pointer}/{name}", commands, violations)
    if "release" in workflow and workflow["release"] is not None:
        check_command_id(
            workflow["release"], "/bindings/workflow/release", commands, violations)


def validate_deploy(deploy: dict, commands: dict | None,
                    violations: list[dict]) -> None:
    check_exact_members(
        deploy, "/bindings/deploy", DEPLOY_MEMBERS, "deploy", violations)
    if "adapter" in deploy:
        check_string(deploy["adapter"], "/bindings/deploy/adapter", "deploy",
                     violations)
    if "command" in deploy and deploy["command"] is not None:
        check_command_id(
            deploy["command"], "/bindings/deploy/command", commands, violations)
    if "config" in deploy:
        check_object(deploy["config"], "/bindings/deploy/config", "deploy", violations)


def validate_bindings(source: dict, violations: list[dict]) -> None:
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
    if "vcs" in present:
        validate_vcs(present["vcs"], violations)
    if "tracker" in present:
        validate_tracker(present["tracker"], violations)
    if "paths" in present:
        validate_paths(present["paths"], violations)
    if commands is not None:
        validate_commands(commands, violations)
    if "workflow" in present:
        validate_workflow(present["workflow"], commands, violations)
    if "deploy" in present:
        validate_deploy(present["deploy"], commands, violations)


def validate_capabilities(source: dict, violations: list[dict]) -> None:
    capabilities = source.get("capabilities")
    if not check_object(capabilities, "/capabilities", "capabilities", violations):
        return
    check_exact_members(
        capabilities, "/capabilities", CAPABILITY_NAMES, "capabilities", violations)
    for name in CAPABILITY_NAMES:
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
    for name in CAPABILITY_NAMES:
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


def validate_projections(source: dict, violations: list[dict]) -> None:
    projections = source.get("projections")
    if not check_list(projections, "/projections", "projections", violations):
        return
    seen: set[str] = set()
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
            if name in entry:
                check_safe_path(
                    entry[name], f"{pointer}/{name}", "projections", violations)


def validate_contract(source: dict) -> list[dict]:
    """Every shape violation of the authored source, collected in one pass.

    Each returned violation carries `pointer`, `message` and the internal
    `repair_id` that `raise_for_violations` publishes for the first violation
    in pointer order. The list is returned unsorted; the caller orders it.
    """
    violations: list[dict] = []
    validate_schema_version(source, violations)
    for name in TOP_LEVEL_MEMBERS:
        # `schema_version` reports its own absence above, with the repair id
        # that names the version rather than the generic missing-member one.
        if name != "schema_version" and name not in source:
            violations.append(violation(
                f"/{name}", "required member is absent",
                "contract.top_level.member_missing"))
    for name in sorted(source):
        if name not in TOP_LEVEL_MEMBERS:
            violations.append(violation(
                f"/{name}", "member is not part of this schema",
                "contract.top_level.member_unexpected"))
    if "project" in source:
        validate_project(source, violations)
    if "bindings" in source:
        validate_bindings(source, violations)
    if "capabilities" in source:
        validate_capabilities(source, violations)
    if "projections" in source:
        validate_projections(source, violations)
    violations.extend(validate_capability_bindings(source))
    return violations


# --------------------------------------------------------------------------
# Normalization and snapshot assembly
# --------------------------------------------------------------------------


def normalize_bindings(source_bindings: dict, root: Path) -> dict:
    """The source bindings with every authored path made absolute under `root`.

    Exactly the artifact paths, the six knowledge path lists and each command's
    `cwd` are rewritten; every other value is passed through byte-for-byte.
    """
    bindings = copy.deepcopy(source_bindings)
    paths = bindings["paths"]
    artifacts = paths["artifacts"]
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
        # `vcs.worktree.root` names the directory every created worktree is
        # placed under, so it is that parent which must exist and accept a
        # new entry.
        parent = root / bindings["vcs"]["worktree"]["root"]
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
    elif name == "release":
        ids = [bindings["workflow"]["release"]]
    elif name == "deploy":
        ids = [bindings["deploy"]["command"]]
    else:
        raise ValueError(f"unknown capability name: {name!r}")
    return None if commands_resolve(bindings, ids) else "command_missing"


def compute_capabilities(bindings: dict, root: Path, declarations: dict) -> dict:
    """Contract: eleven entries, each {"state", "reason_code", "repair_id"}."""
    resolved = {}
    for name in CAPABILITY_NAMES:
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


def build_snapshot(root: Path, source: dict) -> dict:
    # Readiness reads the normalized bindings, so each command's `cwd` is
    # already the absolute base a relative argv[0] resolves against (D22).
    bindings = normalize_bindings(source["bindings"], root)
    return {
        "schema_version": SCHEMA_VERSION,
        "project": {
            "root": str(root),
            "id": source["project"]["id"],
            "name": source["project"]["name"],
        },
        "bindings": bindings,
        "capabilities": compute_capabilities(
            bindings, root, source["capabilities"]),
    }


def unavailable_reason(entry: dict) -> str:
    """The repair-id suffix a non-available capability contributes."""
    return entry["reason_code"] if entry["state"] == "blocked" else "unsupported"


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
            "message": (
                f"required capability is blocked: {entry['reason_code']}"
                if entry["state"] == "blocked"
                else "required capability is unsupported by this project"
            ),
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
# Output
# --------------------------------------------------------------------------


def emit_json(value: object) -> int:
    json.dump(value, sys.stdout, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


def emit_error(code: str, repair_id: str, violations: list[dict]) -> int:
    emit_json({
        "error": {"code": code, "repair_id": repair_id, "violations": violations},
    })
    return 2


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------


def command_resolve(args: argparse.Namespace) -> int:
    root = discover_root(args.repo_root)
    source = load_contract(root)
    raise_for_violations(validate_contract(source))
    snapshot = build_snapshot(root, source)
    raise_for_unavailable(args.require, snapshot["capabilities"])
    return emit_json(snapshot)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resolve-project",
        description="Resolve the authored project contract into a ResolvedProject.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    resolve = subparsers.add_parser(
        "resolve", help="print the ResolvedProject snapshot on stdout")
    resolve.add_argument(
        "--repo-root",
        help="the project root; without it the nearest ancestor holding "
             f"{CONTRACT_FILENAME} is used",
    )
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
    return parser


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "resolve":
        return command_resolve(args)
    raise ValueError(f"unknown subcommand: {args.command!r}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return dispatch(args)
    except ContractError as error:
        return emit_error(error.code, error.repair_id, error.violations)
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
