"""Project schema 3: the platform constants a contract no longer authors.

Schema 3 is schema 2 minus everything the platform decides. `fill(source)`
returns a copy of a schema-3 contract with each constant written at the
schema-2 pointer it always had, each retired member removed and every authored
command given the platform's `cwd` and `env`, so the resolver validates and
resolves the result with the schema-2 rules. The snapshot is therefore schema 2
without the retired members (`RETIRED`).

The module imports only `copy` and `agent_platform`, never the resolver, so
adoption can import it later (ADR-project-contract-010 D1).
"""

from __future__ import annotations

import copy

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
    "/bindings/workflow/orchestration/attempt_budget_minutes": 240,
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


def _segments(pointer: str) -> list[str]:
    return pointer.split("/")[1:]


def _write(view: dict, pointer: str, value: object) -> None:
    """Write `value` at `pointer`, creating the objects on the way.

    An intermediate that is present but not an object is replaced only when it
    is a constant container; otherwise it carries authored members, is left as
    authored for the shape check to report, and the constant is not written.
    """
    keys = _segments(pointer)
    node = view
    for depth, key in enumerate(keys[:-1]):
        child = node.get(key)
        if not isinstance(child, dict):
            if key in node and "/" + "/".join(keys[:depth + 1]) not in CONSTANT_CONTAINERS:
                return
            child = node[key] = {}
        node = child
    node[keys[-1]] = copy.deepcopy(value)


def _delete(view: dict, pointer: str) -> None:
    keys = _segments(pointer)
    node = view
    for key in keys[:-1]:
        node = node.get(key)
        if not isinstance(node, dict):
            return
    node.pop(keys[-1], None)


def fill(source: dict) -> dict:
    """A new dict: `source` with the schema-3 constants filled and the retired members removed.

    The input is never mutated. No top-level member is created or removed, and
    nothing changes when `bindings` is not an object.
    """
    view = copy.deepcopy(source)
    bindings = view.get("bindings")
    if not isinstance(bindings, dict):
        return view
    for namespace in NAMESPACES:
        bindings.setdefault(namespace, {})
    for pointer, value in CONSTANTS.items():
        _write(view, pointer, value)
    commands = bindings["commands"]
    if isinstance(commands, dict):
        for command_id in list(commands):
            if command_id in COMMANDS:
                del commands[command_id]
            elif isinstance(commands[command_id], dict):
                commands[command_id].update(copy.deepcopy(COMMAND_CONSTANTS))
    for pointer in RETIRED:
        _delete(view, pointer)
    return view
