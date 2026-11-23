"""Project schema 3: the platform constants and derived values a contract no longer authors.

Schema 3 is schema 2 minus everything the platform decides or the repository
states. `fill(source, derived)` returns a copy of a schema-3 contract with each
constant written at the schema-2 pointer it always had, the derived values
(`DERIVED`) written from `derived`, each retired member removed and every
authored command given the platform's `cwd` and `env`, so the resolver
validates and resolves the result with the schema-2 rules. The snapshot is
therefore schema 2 without the retired members (`RETIRED`).

`refusals(source)` is the other half: a contract that authors a constant, a
derived value, a retired member or a platform command is refused by name,
never silently overwritten.

The derived values are the four the repository's files state, derived by
`derived_values` (ADR-project-contract-014), and the attempt budget with its
basis, which the resolver reads from the recorded attempt history through
`resolve_project.derive_for` (ADR-project-contract-016). The basis is a
snapshot member only: `fill` never writes it into the view.

The module imports only `copy` and `agent_platform`, never the resolver or
`derived_values`, so adoption can import it later (ADR-project-contract-010 D1).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping

from agent_tools.project_contract import agent_platform

SCHEMA_VERSION = 3

# JSON pointer -> the value as a contract authors it (paths stay relative to
# the repository root; the resolver makes them absolute).
CONSTANTS: dict[str, object] = {
    "/bindings/vcs/kind": "git",
    "/bindings/vcs/default_branch": "main",
    "/bindings/vcs/branch_pattern": "issue-<num>-<slug>",
    "/bindings/vcs/worktree/root": ".worktrees",
    "/bindings/vcs/worktree/prefix": "worktree-",
    "/bindings/vcs/commit/signed": True,
    "/bindings/vcs/commit/environment": "commit-environment",
    "/bindings/vcs/merge/strategy": "merge",
    "/bindings/vcs/merge/delete_branch": True,
    "/bindings/tracker/kind": "github",
    "/bindings/tracker/cli": "gh",
    "/bindings/tracker/credential_env/unset_before_invocation": [
        "GITHUB_TOKEN", "GH_TOKEN"],
    "/bindings/paths/context": ["docs/CONTEXT-MAP.md"],
    "/bindings/paths/standards": ["docs/standards"],
    "/bindings/paths/architecture": ["docs/guides/architecture.md"],
    "/bindings/paths/operations": ["docs/operations"],
    "/bindings/paths/hints": [".agents/knowledge/hints"],
    "/bindings/paths/rejections": [".agents/knowledge/rejections"],
    "/bindings/workflow/verification": ["lint", "test"],
    "/bindings/workflow/review/plan": "codex-plan-review",
    "/bindings/workflow/review/code": "codex-diff-review",
    "/bindings/workflow/orchestration/max_parallel": 2,
}

# The objects whose every member is a constant or retired: a contract that
# authors one as a non-object has it replaced.
CONSTANT_CONTAINERS = (
    "/bindings/paths",
    "/bindings/vcs/worktree",
    "/bindings/vcs/commit",
    "/bindings/tracker/credential_env",
    "/bindings/workflow/review",
)

# The attempt budget and the basis it was derived from. The basis is carried by the snapshot only.
ATTEMPT_BUDGET = "/bindings/workflow/orchestration/attempt_budget_minutes"
ATTEMPT_BUDGET_BASIS = "/bindings/workflow/orchestration/attempt_budget_basis"

# The four values the repository states and the attempt budget with its basis, as the
# schema-2 pointers they fill.
DERIVED = (
    "/project/id",
    "/bindings/tracker/repo_slug",
    "/bindings/vcs/merge/required_checks",
    "/platform",
    ATTEMPT_BUDGET,
    ATTEMPT_BUDGET_BASIS,
)

# Objects a contract may not author because the derived value is its only member.
DERIVED_CONTAINERS = ("/project",)

# What every authored command carries instead of its own.
COMMAND_CONSTANTS = {"cwd": ".", "env": []}

# Schema 2's platform commands plus the one only schema 3 defines: the
# environment an adoption commit runs through (ADR-project-contract-008).
COMMANDS: dict[str, dict] = {
    **copy.deepcopy(agent_platform.PLATFORM_COMMANDS),
    "commit-environment": {"argv": ["devenv", "shell", "--"], "cwd": ".", "env": []},
}

# Members schema 2 authors and schema 3 no longer has (#1430, #1418, #1449).
RETIRED = (
    "/project/name",
    "/bindings/paths/artifacts",
    "/bindings/vcs/commit/co_authored_by",
    "/bindings/workflow/light_lane",
)

NAMESPACES = ("vcs", "tracker", "paths", "commands", "workflow")

# The members a schema-3 contract authors: the only ones a tool that drafts one may write.
AUTHORED = (
    "/bindings/vcs/integration_branch",
    "/bindings/commands",
    "/bindings/workflow/verification_conditions",
    "/bindings/workflow/verification_before_pull_request",
    "/bindings/workflow/orchestration/stall_minutes",
    "/capabilities",
    "/projections",
    "/release",
    "/production",
)


def declares(source: object) -> bool:
    """Whether `source` declares schema 3 as an integer; `3.0` and `true` do not."""
    if not isinstance(source, dict):
        return False
    version = source.get("schema_version")
    return (isinstance(version, int) and not isinstance(version, bool)
            and version == SCHEMA_VERSION)


def _escaped(token: str) -> str:
    """One reference token of an RFC 6901 JSON pointer."""
    return token.replace("~", "~0").replace("/", "~1")


def _within(pointer: str, ancestor: str) -> bool:
    return pointer == ancestor or pointer.startswith(ancestor + "/")


def authored(pointer: str) -> bool:
    """Whether a contract may author `pointer`: the ownership `refusals` enforces, as a question.

    True when `pointer` is in `AUTHORED`, touches no platform value (a constant, derived value, retired
    member or container) and is, under `/bindings/commands`, no platform command or constant member.
    """
    if not any(_within(pointer, member) for member in AUTHORED):
        return False
    platform = (*CONSTANTS, *DERIVED, *RETIRED, *CONSTANT_CONTAINERS, *DERIVED_CONTAINERS)
    if any(_within(pointer, other) or _within(other, pointer) for other in platform):
        return False
    keys = _segments(pointer)
    if keys[:2] == ["bindings", "commands"] and len(keys) > 2:
        if keys[2].replace("~1", "/").replace("~0", "~") in COMMANDS:
            return False
        if len(keys) > 3 and keys[3] in COMMAND_CONSTANTS:
            return False
    return True


def _segments(pointer: str) -> list[str]:
    return pointer.split("/")[1:]


def _write(view: dict, pointer: str, value: object) -> None:
    """Write `value` at `pointer`, creating the objects on the way.

    An intermediate that is present but not an object is replaced only when it
    is a constant or derived container; otherwise it carries authored members, is
    left as authored for the shape check to report, and the value is not written.
    """
    keys = _segments(pointer)
    node = view
    for depth, key in enumerate(keys[:-1]):
        child = node.get(key)
        if not isinstance(child, dict):
            if key in node and "/" + "/".join(keys[:depth + 1]) not in CONSTANT_CONTAINERS + DERIVED_CONTAINERS:
                return
            child = node[key] = {}
        node = child
    node[keys[-1]] = copy.deepcopy(value)


def remove_at(view: dict, pointer: str) -> None:
    keys = _segments(pointer)
    node = view
    for key in keys[:-1]:
        node = node.get(key)
        if not isinstance(node, dict):
            return
    node.pop(keys[-1], None)


def fill(source: dict, derived: Mapping[str, object]) -> dict:
    """A new dict: `source` with the constants and `derived` values filled and the retired members removed.

    The input is never mutated. An authored member of `DERIVED` is removed, and written back
    only from `derived`. Only `project` and `platform` may be created at
    the top level, and only from `derived`; the project id and the platform are
    written even when `bindings` is not an object, the rest of the filling is
    skipped then. The keys of `derived` are members of `DERIVED`.
    """
    view = copy.deepcopy(source)
    # An authored derived value is refused by `refusals`; it is never read as the value, so a
    # value the repository cannot state stays absent instead of falling back to the authored one.
    for pointer in RETIRED + DERIVED:
        remove_at(view, pointer)
    for pointer in ("/project/id", "/platform"):
        if pointer in derived:
            _write(view, pointer, derived[pointer])
    bindings = view.get("bindings")
    if not isinstance(bindings, dict):
        return view
    for namespace in NAMESPACES:
        bindings.setdefault(namespace, {})
    for pointer, value in CONSTANTS.items():
        _write(view, pointer, value)
    for pointer in ("/bindings/tracker/repo_slug", "/bindings/vcs/merge/required_checks",
                    ATTEMPT_BUDGET):
        if pointer in derived:
            _write(view, pointer, derived[pointer])
    commands = bindings["commands"]
    if isinstance(commands, dict):
        for command_id in list(commands):
            if command_id in COMMANDS:
                del commands[command_id]
            elif isinstance(commands[command_id], dict):
                commands[command_id].update(copy.deepcopy(COMMAND_CONSTANTS))
    return view


ABSENT = object()


def authored_at(source: dict, pointer: str) -> object:
    """The value authored at `pointer`, or `ABSENT` when an object on the way lacks it."""
    node: object = source
    for key in _segments(pointer):
        if not isinstance(node, dict) or key not in node:
            return ABSENT
        node = node[key]
    return node


def _section(pointer: str) -> str:
    keys = _segments(pointer)
    return keys[0] if keys[0] in ("project", "platform") else keys[1]


def refusals(source: dict) -> list[dict]:
    """The violations of a schema-3 contract that authors what the platform decides.

    Walks the authored `source`, never the filled view. Each entry is
    `{"pointer", "message", "repair_id"}`, the shape of the resolver's
    violations, and the list is unsorted. An authored constant or platform
    command is `contract.<section>.platform_constant`, an authored derived
    value (`DERIVED`, or a `project` that is empty or not an object) is
    `contract.<section>.derived_value`, an authored retired
    member is `contract.<section>.retired_member`, and an absent `lint` or
    `test` (every id of the verification constant) is
    `contract.commands.member_missing`, where `<section>` is the pointer's
    namespace under `/bindings`, or `project` or `platform`.
    """
    found: list[dict] = []

    messages = {
        "platform_constant": "is a platform constant from project schema 3 on, so a contract "
                             "does not author it",
        "derived_value": "is derived from the repository from project schema 3 on, so a "
                         "contract does not author it",
        "retired_member": "was retired in project schema 3",
    }

    def refuse(pointer: str, kind: str) -> None:
        message = messages[kind]
        found.append({"pointer": pointer, "message": message,
                      "repair_id": f"contract.{_section(pointer)}.{kind}"})

    if not isinstance(source, dict):
        return found
    for pointer in RETIRED:
        if authored_at(source, pointer) is not ABSENT:
            refuse(pointer, "retired_member")
    for pointer in CONSTANTS:
        if authored_at(source, pointer) is not ABSENT:
            refuse(pointer, "platform_constant")
    for pointer in DERIVED:
        if authored_at(source, pointer) is not ABSENT:
            refuse(pointer, "derived_value")
    for pointer, kind in ([(c, "platform_constant") for c in CONSTANT_CONTAINERS]
                          + [(c, "derived_value") for c in DERIVED_CONTAINERS]):
        value = authored_at(source, pointer)
        if value is not ABSENT and (not isinstance(value, dict) or not value):
            refuse(pointer, kind)
    bindings = source.get("bindings")
    if not isinstance(bindings, dict):
        return found
    commands = bindings.get("commands")
    if isinstance(commands, dict):
        for command_id, entry in commands.items():
            token = _escaped(command_id)
            if command_id in COMMANDS:
                refuse(f"/bindings/commands/{token}", "platform_constant")
            elif isinstance(entry, dict):
                for member in COMMAND_CONSTANTS:
                    if member in entry:
                        refuse(f"/bindings/commands/{token}/{member}",
                               "platform_constant")
    if "commands" not in bindings or isinstance(commands, dict):
        for command_id in CONSTANTS["/bindings/workflow/verification"]:
            if not isinstance(commands, dict) or command_id not in commands:
                found.append({
                    "pointer": f"/bindings/commands/{command_id}",
                    "message": "required member is absent",
                    "repair_id": "contract.commands.member_missing"})
    return found
