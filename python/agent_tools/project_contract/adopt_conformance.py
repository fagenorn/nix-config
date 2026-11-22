"""The file side of adopting a project into conformance: three pure byte edits.

An adopted project's CI runs the platform at a revision its own tree locks. This
module computes the three file changes that make that so, each from the bytes of
one file at the plan's base commit and each a pure function: no file is read, no
process runs, and the resolver is never imported (D26). The plan side (reading
the base commit, composing operations and the ready gate) is `adopt_project` and
`adopt_planning`; the forge side (the required check on the integration branch)
is the apply step.

- `lock_with_platform` adds the platform's node to `devenv.lock` and points the
  root node's `agent-platform` input at it, in the shape the resolver reads
  (`nodes[nodes[root].inputs["agent-platform"]].locked`). An entry the lock
  already holds is kept as found when it is well formed (a non-flake github node
  whose `locked` record is a valid revision and whose `original` names the same
  owner and repository) and is refused otherwise, never replaced. The bytes keep
  `json.dumps(indent=2, sort_keys=True)` style, with a trailing newline only when
  the input had one, which reproduces a devenv or flake lock byte for byte.
- `declare_input` declares the same input in `devenv.yaml` as a text edit, with no
  YAML parser. It handles a plain block-mapping document only (every column-0
  line is a bare `key:` line, a comment or blank), inserts the declaration after
  the last child of an `inputs:` block, or appends the block, and keeps a
  compatible existing declaration as found. A flow-style document, a document
  marker, an `inputs` carrying an inline value, a duplicated `inputs:` line or a
  tab-indented child is refused rather than edited.
- `require_in_protection_file` appends the `Conformance` check to the branch
  protection file in the shape the resolver reads (`required_status_checks.checks`
  of objects with a unique `context`), keeping every existing entry, its
  `app_id` included, and every other member. A file outside that shape is
  refused, never normalised.

A refusal is `Undeclarable` carrying one of the `adopt.conformance.*` repair ids
below; the plan's ready gate reports it.
"""

from __future__ import annotations

import copy
import json
import re
from typing import NamedTuple

from agent_tools.canonical import reject_duplicate_keys
from agent_tools.project_contract.agent_platform import valid_revision

CONTEXT = "Conformance"
LOCK_FILE = "devenv.lock"
INPUT_FILE = "devenv.yaml"
PROTECTION_FILE = ".github/branch-protection.json"
WORKFLOW_TARGET = ".github/workflows/conformance.yaml"
INPUT = "agent-platform"
PROJECTION_ENTRY = {"id": "conformance.workflow", "kind": "conformance_workflow",
                    "target": WORKFLOW_TARGET}

REVISION_UNKNOWN = "adopt.conformance.revision_unknown"
TRACKER_UNNAMED = "adopt.conformance.tracker_unnamed"
ORIGIN_MISMATCH = "adopt.conformance.origin_mismatch"
PROJECTION_COLLIDES = "adopt.conformance.projection_collides"
LOCK_UNREADABLE = "adopt.conformance.lock_unreadable"
LOCK_ENTRY_INCOMPATIBLE = "adopt.conformance.lock_entry_incompatible"
PIN_INCOMPATIBLE = "adopt.conformance.pin_incompatible"
INPUT_UNDECLARABLE = "adopt.conformance.input_undeclarable"
INPUT_INCOMPATIBLE = "adopt.conformance.input_incompatible"
PROTECTION_FILE_UNREQUIRED = "adopt.conformance.protection_file_unrequired"
CONTRACT_REFUSED = "adopt.conformance.contract_refused"

_KEY_LINE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*:([ \t]+\S.*|[ \t]*(#.*)?)$")
_INPUTS_OPEN = re.compile(r"^inputs:[ \t]*(#.*)?$")
_DECLARATION = re.compile(
    r"""^(?:agent-platform|"agent-platform"|'agent-platform')[ \t]*:(?:[ \t].*)?$""")


class Undeclarable(Exception):
    """A file the adoption cannot edit; `repair_id` names the repair."""

    def __init__(self, repair_id: str):
        super().__init__(repair_id)
        self.repair_id = repair_id


class LockEntry(NamedTuple):
    """The lock after the edit (None when an entry is kept) and the entry's node."""

    after: bytes | None
    node: str
    locked: dict
    kept: bool


# --------------------------------------------------------------------------
# devenv.lock
# --------------------------------------------------------------------------


def _parse_lock(data: bytes) -> tuple[dict, dict, dict]:
    try:
        document = json.loads(data.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (ValueError, RecursionError):
        raise Undeclarable(LOCK_UNREADABLE) from None
    nodes = document.get("nodes") if isinstance(document, dict) else None
    if not isinstance(nodes, dict):
        raise Undeclarable(LOCK_UNREADABLE)
    root_name = document["root"]
    root = nodes.get(root_name) if isinstance(root_name, str) else None
    if not isinstance(root, dict):
        raise Undeclarable(LOCK_UNREADABLE)
    if "inputs" in root and not isinstance(root["inputs"], dict):
        raise Undeclarable(LOCK_UNREADABLE)
    return document, nodes, root


def _kept_entry(nodes: dict, reference: object) -> tuple[dict, str]:
    node = nodes.get(reference) if isinstance(reference, str) else None
    if not isinstance(node, dict) or node.get("flake") is not False:
        raise Undeclarable(LOCK_ENTRY_INCOMPATIBLE)
    locked = node.get("locked")
    original = node.get("original")
    if (not valid_revision(locked) or not isinstance(original, dict)
            or original.get("type") != "github"
            or original.get("owner") != locked["owner"]
            or original.get("repo") != locked["repo"]):
        raise Undeclarable(LOCK_ENTRY_INCOMPATIBLE)
    return locked, reference


def lock_with_platform(data: bytes, revision: dict) -> LockEntry:
    """The lock with the platform's node and root input added, or its kept entry."""
    document, nodes, root = _parse_lock(data)
    inputs = root.get("inputs", {})
    if INPUT in inputs:
        locked, node = _kept_entry(nodes, inputs[INPUT])
        return LockEntry(None, node, locked, True)
    node = INPUT
    suffix = 2
    while node in nodes:
        node = f"{INPUT}_{suffix}"
        suffix += 1
    locked = copy.deepcopy(revision)
    nodes[node] = {"flake": False, "locked": locked,
                   "original": {"owner": locked["owner"], "repo": locked["repo"],
                                "type": "github"}}
    root["inputs"] = {**inputs, INPUT: node}
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False)
    if data.endswith(b"\n"):
        text += "\n"
    return LockEntry(text.encode("utf-8"), node, locked, False)


# --------------------------------------------------------------------------
# devenv.yaml
# --------------------------------------------------------------------------


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_blank(line: str) -> bool:
    return not line.strip()


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def _split_lines(text: str) -> list[str]:
    parts = text.split("\n")
    return [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def _declaration_block(indent: str, owner: str, repo: str) -> list[str]:
    return [f"{indent}{INPUT}:\n", f"{indent}{indent}url: github:{owner}/{repo}\n",
            f"{indent}{indent}flake: false\n"]


def _checked_body(body: list[str], owner: str, repo: str) -> None:
    pairs = [line for line in body if not _is_blank(line) and not _is_comment(line)]
    url = re.compile(rf"^url:[ \t]+github:{re.escape(owner)}/{re.escape(repo)}[ \t]*(#.*)?$")
    flake = re.compile(r"^flake:[ \t]+false[ \t]*(#.*)?$")
    if len(pairs) != 2 or _indent(pairs[0]) != _indent(pairs[1]):
        raise Undeclarable(INPUT_INCOMPATIBLE)
    texts = [line.strip() for line in pairs]
    shapes = sorted(("url" if url.match(text) else "flake" if flake.match(text) else "")
                    for text in texts)
    if shapes != ["flake", "url"]:
        raise Undeclarable(INPUT_INCOMPATIBLE)


def declare_input(data: bytes | None, owner: str, repo: str) -> bytes | None:
    """The `devenv.yaml` bytes declaring the platform input, or None when declared."""
    if data is None:
        raise Undeclarable(INPUT_UNDECLARABLE)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Undeclarable(INPUT_UNDECLARABLE) from None
    lines = _split_lines(text)
    stripped = [line.rstrip("\n") for line in lines]
    for line in stripped:
        if (not _is_blank(line) and not line.startswith(" ") and not line.startswith("#")
                and not _KEY_LINE.match(line)):
            raise Undeclarable(INPUT_UNDECLARABLE)
    openers = [number for number, line in enumerate(stripped) if _INPUTS_OPEN.match(line)]
    if len(openers) > 1 or any(
            line.startswith("inputs:") and number not in openers
            for number, line in enumerate(stripped)):
        raise Undeclarable(INPUT_UNDECLARABLE)
    if not openers:
        prefix = text if not text or text.endswith("\n") else text + "\n"
        block = "inputs:\n" + "".join(_declaration_block("  ", owner, repo))
        return (prefix + block).encode("utf-8")
    opener = openers[0]
    end = len(stripped)
    for number in range(opener + 1, len(stripped)):
        line = stripped[number]
        if not _is_blank(line) and not line.startswith(" ") and not line.startswith("#"):
            end = number
            break
    children = [number for number in range(opener + 1, end)
                if not _is_blank(stripped[number]) and not _is_comment(stripped[number])]
    if not children:
        indent = "  "
        last = opener
    else:
        first = stripped[children[0]]
        indent = first[:len(first) - len(first.lstrip())]
        if indent.strip(" "):
            raise Undeclarable(INPUT_UNDECLARABLE)
        last = children[-1]
    for number in children:
        line = stripped[number]
        if _indent(line) != len(indent):
            continue
        if not _DECLARATION.match(line[len(indent):]):
            continue
        body = []
        for later in range(number + 1, end):
            if not _is_blank(stripped[later]) and _indent(stripped[later]) <= len(indent):
                break
            body.append(stripped[later])
        _checked_body(body, owner, repo)
        return None
    if not lines[last].endswith("\n"):
        lines[last] += "\n"
    lines[last + 1:last + 1] = _declaration_block(indent, owner, repo)
    return "".join(lines).encode("utf-8")


# --------------------------------------------------------------------------
# .github/branch-protection.json
# --------------------------------------------------------------------------


def require_in_protection_file(data: bytes) -> bytes | None:
    """The protection file requiring the `Conformance` check, or None when it does."""
    try:
        document = json.loads(data.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (ValueError, RecursionError):
        raise Undeclarable(PROTECTION_FILE_UNREQUIRED) from None
    section = document.get("required_status_checks") if isinstance(document, dict) else None
    checks = section.get("checks") if isinstance(section, dict) else None
    if not isinstance(checks, list):
        raise Undeclarable(PROTECTION_FILE_UNREQUIRED)
    seen: list[str] = []
    for entry in checks:
        context = entry.get("context") if isinstance(entry, dict) else None
        if not isinstance(context, str) or not context or context in seen:
            raise Undeclarable(PROTECTION_FILE_UNREQUIRED)
        seen.append(context)
    contexts = section.get("contexts")
    if "contexts" in section and (
            not isinstance(contexts, list)
            or not all(isinstance(item, str) for item in contexts)):
        raise Undeclarable(PROTECTION_FILE_UNREQUIRED)
    changed = False
    if CONTEXT not in seen:
        checks.append({"context": CONTEXT})
        changed = True
    if contexts is not None and CONTEXT not in contexts:
        contexts.append(CONTEXT)
        changed = True
    if not changed:
        return None
    text = json.dumps(document, indent=2, ensure_ascii=False)
    if data.endswith(b"\n"):
        text += "\n"
    return text.encode("utf-8")
