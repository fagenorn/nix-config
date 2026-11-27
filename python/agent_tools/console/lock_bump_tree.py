"""`lock_bump_tree`: the file side of a lock bump, pure edits first.

`pinned_revision` and `bumped_lock` read the lock through `adopt_conformance.lock_with_platform(lock, None)`,
so only a kept `agent-platform` entry is ever edited and a missing or foreign one is `BumpRefused`, never a
new entry. `bumped_lock` replaces that node's `locked` member with the proven revision's record and nothing
else, serialised as the adoption does (sorted, indented, a trailing newline only when the input had one).
`required_migrations` names the migrations a proven revision needs a contract to take, in order.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from agent_tools.canonical import reject_duplicate_keys
from agent_tools.project_contract import adopt_conformance
from agent_tools.project_contract.adopt_inspection import AdoptError
from agent_tools.project_contract.adopt_planning import select_forward_step
from agent_tools.project_contract.agent_platform import valid_revision

BRANCH_PREFIX = "lock-bump-"
BRANCH = re.compile(r"lock-bump-([0-9a-f]{40})")
REVISION = re.compile(r"[0-9a-f]{40}")


class BumpRefused(Exception):
    """A bump that cannot be made, in plain words."""


def branch_for(revision: str) -> str:
    if not isinstance(revision, str) or REVISION.fullmatch(revision) is None:
        raise ValueError("a bump branch names a revision in full")
    return BRANCH_PREFIX + revision


def revision_of_branch(ref: str) -> str | None:
    found = BRANCH.fullmatch(ref) if isinstance(ref, str) else None
    return found[1] if found else None


def _entry(lock: bytes) -> adopt_conformance.LockEntry:
    try:
        return adopt_conformance.lock_with_platform(lock, None)
    except adopt_conformance.Undeclarable as error:
        raise BumpRefused(f"the lock cannot be bumped: {error.repair_id}") from None


def pinned_revision(lock: bytes) -> str:
    return _entry(lock).locked["rev"]


def bumped_lock(lock: bytes, record: Mapping[str, object]) -> bytes:
    entry = _entry(lock)
    if not valid_revision(record):
        raise BumpRefused("the proven revision's record is malformed")
    if (record["owner"], record["repo"]) != (entry.locked["owner"], entry.locked["repo"]):
        raise BumpRefused("the proven revision's record names another repository than the lock")
    document = json.loads(lock.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    document["nodes"][entry.node]["locked"] = dict(record)
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False)
    if lock.endswith(b"\n"):
        text += "\n"
    return text.encode("utf-8")


def required_migrations(manifest: Mapping, schema_version: int) -> list[str]:
    supported = manifest["project_schema_versions"]
    steps: list[str] = []
    schema = schema_version
    while schema not in supported:
        try:
            step = select_forward_step(dict(manifest), schema)
        except AdoptError as error:
            raise BumpRefused(f"no single migration steps forward from schema {schema}: "
                              f"{error.repair_id}") from None
        if step is None:
            raise BumpRefused(f"no migration steps forward from schema {schema}")
        steps.append(step["id"])
        schema = step.get("to_schema")
        if len(steps) > len(manifest["migrations"]):
            raise BumpRefused("the migrations of the proven revision do not reach a supported schema")
    return steps
