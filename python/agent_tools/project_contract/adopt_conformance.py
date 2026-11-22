"""The file side of adopting a project into conformance: three pure byte edits.

An adopted project's CI runs the platform at a revision its own tree locks. This
module computes the three file changes that make that so, each from the bytes of
one file at the plan's base commit and each a pure function: no file is read, no
process runs, and the resolver is never imported (D26). The plan side (reading
the base commit, composing operations and the ready gate) is `adopt_project` and
`adopt_planning`; the forge side (the required check on the integration branch)
is the apply step and is the last section of this module.

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
  compatible existing declaration as found (an inline value on the
  `agent-platform` key, whatever follows it, is incompatible). A flow-style document, a document
  marker, an `inputs` carrying an inline value, a duplicated `inputs:` line or a
  tab-indented child, or a child of `inputs:` that is not a mapping key (an indented
  `{}` or a sequence item) is refused rather than edited.
- `require_in_protection_file` appends the `Conformance` check to the branch
  protection file in the shape the resolver reads (`required_status_checks.checks`
  of objects with a unique `context`), keeping every existing entry, its
  `app_id` included, and every other member. A file outside that shape is
  refused, never normalised.

The forge side (`required_check_state`, `add_required_check`, `preflight`,
`settle_required_check`) runs only for a plan that carries `plan.conformance`;
a plan without it makes no `gh` call and writes no pending record. It reaches
the forge only through `agent_tools.system.forge_api` (no token variable reaches
`gh`), reads one endpoint and writes one, and never removes or narrows a
protection: `GET repos/<repo>/branches/<branch>/protection/required_status_checks`
and `POST .../required_status_checks/contexts` with `contexts[]=Conformance`.
The order of an apply is:

1. Before anything is mutated, and after the dirty-overlap refusal, `preflight`
   requires both effective URLs of `origin` (fetch and push, as git reports them)
   to name the plan's `required_check.repo` on `github.com`
   (`adopt.required_check.origin_mismatch`, no `gh` call) and reads the state.
   A 404, or a readable answer that lists no context, is
   `adopt.required_check.unprotected` (the owner turns on required status checks
   and adopts again; adoption never creates or widens a protection); an
   unreadable or malformed answer is `adopt.required_check.unreadable`. `Conformance`
   already listed is `already_required`: no request is made, unless a listed
   `Conformance` check is bound to a GitHub App other than Actions
   (`adopt.required_check.app_mismatch`), which the generated job cannot satisfy.
2. After the commit's bytes are proved and the worktree is removed, a state of
   `missing` writes the pending record (`pending_path`) and `settle_required_check`
   makes the one POST. `added` is success. A refused or lost POST is followed by
   one re-read: present is success; a readable answer without the context (an
   empty list or a 404 included) is a confirmed absence, so the adoption branch is deleted by a compare-and-delete
   whose result is read back and apply refuses `adopt.required_check.refused`
   (`adopt.required_check.rollback_failed` when the branch could not be deleted);
   a re-read that raises is an unknown outcome, so the branch and the record are
   kept and apply refuses `adopt.required_check.unknown`.
3. Applying the same plan again with a pending record present skips planning,
   the worktree and the commit: the branch must still be the recorded commit
   (`adopt.required_check.pending_mismatch`), and the same origin check, read and
   settlement run, so a POST that landed is never repeated. The record is removed
   once the result is emitted. While the record exists, `discard` refuses
   `adopt.required_check.pending` and changes nothing, and `--discard-retained`
   is never reached (apply reconciles first), so the branch and the record are
   only ever kept or removed together. The record is bound to the plan first: its
   plan id, branch name (`adopt-<digest[:12]>`), repository and integration branch
   must be the plan's and its commit must carry the plan's evidence record, else
   `adopt.required_check.pending_mismatch`, so a misplaced record can never name
   another branch for the rollback to delete. A record whose branch no longer
   exists (deleted by hand after `adopt.required_check.rollback_failed`) is stale:
   apply and `discard` drop it and go on.
4. Apply and `discard` of one plan hold one per-plan lock (`plan_lock`); a second
   holder is refused `adopt.required_check.pending` and changes nothing.

A refusal is `Undeclarable` carrying one of the `adopt.conformance.*` repair ids
below; the plan's ready gate reports it.

The plan side is `plan_conformance`. It reads every input from the plan's base
commit through `base_entry` (a blob of mode `100644` or `100755`, read by
`git cat-file` after `git ls-tree` named it), never from the working tree, so an
untracked manifest, a staged deletion or an uncommitted edit cannot change what
it returns, and it starts no process other than `git` through
`adopt_inspection.run_git`. A repository whose base commit has no `devenv.lock`,
or holds the platform's own tree marker in any mode, is `NOT_PLANNED`: none of
the three writes, the workflow projection or the required check is planned for
it. Otherwise it is planned, and the first failing cause, in the order of the
`adopt.conformance.*` ids' use below, is the plan's `repair_id`: no installed
revision, an unnamed tracker (not `github`, a slug that is not `owner/repo`, or no
integration branch), an `origin` that is not the tracker's slug, a projection of
another kind that holds the workflow's id or target, a lock or `devenv.yaml` that
cannot take its edit, a kept lock entry that is not the installed revision, a
branch protection file that cannot take the check. With no cause the plan carries
a `member`, the one record of what the adoption locks and requires, which the plan
document publishes as `plan.conformance` and the evidence record repeats; the new
bytes of each of the three files that change are `contents`, their base bytes
`before`, and `projection` says whether the contract gains the workflow's entry.
`outstanding` is whether the repository still has conformance work: the plan
writes something, or the one committed evidence record does not carry the
member the plan would write. The member is computed whenever the lock parses and
the tracker is named, even when a later cause fails; a repository whose kept
lock entry, declaration, projection and record are all in place is settled
despite a cause that is about the host or the clone (an unknown revision, an
`origin` that is not the tracker's slug, a pin that differs from the running
revision), so those causes never block it behind a repair it does not need.
"""

from __future__ import annotations

import copy
import fcntl
import json
import os
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

from agent_tools.canonical import reject_duplicate_keys
from agent_tools.project_contract import adopt_inspection, agent_platform, derived_values
from agent_tools.project_contract.agent_platform import valid_revision
from agent_tools.system import forge_api
from agent_tools.system.github_remote import github_slug

CONTEXT = "Conformance"
LOCK_FILE = "devenv.lock"
INPUT_FILE = "devenv.yaml"
PROTECTION_FILE = ".github/branch-protection.json"
WORKFLOW_TARGET = ".github/workflows/conformance.yaml"
INPUT = "agent-platform"
PROJECTION_ENTRY = {"id": "conformance.workflow", "kind": "conformance_workflow",
                    "target": WORKFLOW_TARGET}
CONFORMANCE_TARGETS = (PROTECTION_FILE, LOCK_FILE, INPUT_FILE, WORKFLOW_TARGET)
REGULAR_MODES = ("100644", "100755")
_SLUG = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")

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

REQUIRED_ORIGIN_MISMATCH = "adopt.required_check.origin_mismatch"
REQUIRED_UNPROTECTED = "adopt.required_check.unprotected"
REQUIRED_UNREADABLE = "adopt.required_check.unreadable"
REQUIRED_REFUSED = "adopt.required_check.refused"
REQUIRED_ROLLBACK_FAILED = "adopt.required_check.rollback_failed"
REQUIRED_UNKNOWN = "adopt.required_check.unknown"
REQUIRED_PENDING_MISMATCH = "adopt.required_check.pending_mismatch"
REQUIRED_PENDING = "adopt.required_check.pending"
REQUIRED_APP_MISMATCH = "adopt.required_check.app_mismatch"
ACTIONS_APP_ID = 15368
REQUIRED_POINTER = "/plan/conformance/required_check"
PENDING_MEMBERS = ("plan_id", "branch", "commit", "repo", "integration_branch", "result")

_KEY_LINE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*:([ \t]+\S.*|[ \t]*(#.*)?)$")
_INPUTS_OPEN = re.compile(r"^inputs:[ \t]*(#.*)?$")
_DECLARATION = re.compile(
    r"""^(?:agent-platform|"agent-platform"|'agent-platform')[ \t]*:(?P<value>(?:[ \t].*)?)$""")
_CHILD_KEY = re.compile(
    r"""^(?:[A-Za-z_][A-Za-z0-9_.-]*|"[^"]*"|'[^']*')[ \t]*:(?:[ \t].*)?$""")
_EMPTY_VALUE = re.compile(r"^[ \t]*(#.*)?$")


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
    root_name = document.get("root")
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


def lock_with_platform(data: bytes, revision: dict | None) -> LockEntry:
    """The lock with the platform's node and root input added, or its kept entry.

    A kept entry needs no installed revision; adding one without a revision is
    the refusal `adopt.conformance.revision_unknown`.
    """
    document, nodes, root = _parse_lock(data)
    inputs = root.get("inputs", {})
    if INPUT in inputs:
        locked, node = _kept_entry(nodes, inputs[INPUT])
        return LockEntry(None, node, locked, True)
    if revision is None:
        raise Undeclarable(REVISION_UNKNOWN)
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
        # Every child at or left of the first child's column must be a mapping key:
        # a flow value (`{}`) or a sequence item there cannot take a sibling key.
        level = _indent(stripped[number])
        if level < len(indent) or (
                level == len(indent) and not _CHILD_KEY.match(stripped[number].lstrip(" "))):
            raise Undeclarable(INPUT_UNDECLARABLE)
    for number in children:
        line = stripped[number]
        if _indent(line) != len(indent):
            continue
        declaration = _DECLARATION.match(line[len(indent):])
        if not declaration:
            continue
        if not _EMPTY_VALUE.match(declaration.group("value")):
            raise Undeclarable(INPUT_INCOMPATIBLE)
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


# --------------------------------------------------------------------------
# The plan side
# --------------------------------------------------------------------------


class ConformancePlan(NamedTuple):
    """What the adoption plan does about conformance (see the module docstring)."""

    planned: bool
    outstanding: bool
    repair_id: str | None
    member: dict | None
    contents: dict[str, bytes]
    before: dict[str, bytes]
    projection: bool


NOT_PLANNED = ConformancePlan(False, False, None, None, {}, {}, False)


def base_entry(root: Path, revision: str, path: str) -> tuple[str, bytes | None] | None:
    """The `(mode, bytes)` of `path` in the commit `revision`, or None when absent.

    The bytes are those of a blob of mode `100644` or `100755` and None for any
    other mode, a symlink, a submodule or a tree included. A git failure is the
    refusal `adopt.git.failed`.
    """
    code, out = adopt_inspection.run_git(
        root, "--literal-pathspecs", "ls-tree", "-z", "--full-tree", revision, "--", path,
        local_only=True)
    if code != 0:
        raise _git_failed()
    for record in out.split(b"\0"):
        head, separator, name = record.partition(b"\t")
        if not separator or name.decode("utf-8", "surrogateescape") != path:
            continue
        fields = head.decode("ascii", "replace").split(" ")
        if len(fields) != 3:
            raise _git_failed()
        mode, kind, object_id = fields
        if mode not in REGULAR_MODES or kind != "blob":
            return mode, None
        code, data = adopt_inspection.run_git(root, "cat-file", "blob", object_id, local_only=True)
        if code != 0:
            raise _git_failed()
        return mode, data
    return None


def _git_failed() -> Exception:
    return adopt_inspection.refuse("adopt_failure", "adopt.git.failed", "",
                                   "a git inspection command did not succeed")


def _tracker(contract_source: dict | None) -> tuple[str, str] | None:
    """The tracker's `repo_slug` and the integration branch, or None when unnamed."""
    bindings = contract_source.get("bindings") if isinstance(contract_source, dict) else None
    if not isinstance(bindings, dict):
        return None
    tracker, vcs = bindings.get("tracker"), bindings.get("vcs")
    if not isinstance(tracker, dict) or not isinstance(vcs, dict):
        return None
    slug, branch = tracker.get("repo_slug"), vcs.get("integration_branch")
    if (tracker.get("kind") != "github" or not isinstance(slug, str)
            or _SLUG.fullmatch(slug) is None or not isinstance(branch, str) or not branch):
        return None
    return slug, branch


def _projection_state(contract_source: dict) -> tuple[bool, bool]:
    """`(collides, declared)`: the workflow's id or target is another kind's, and
    a `conformance_workflow` entry exists."""
    projections = contract_source.get("projections")
    if projections is None:
        return False, False
    if not isinstance(projections, list):
        return True, False
    collides = declared = False
    for entry in projections:
        if not isinstance(entry, dict):
            continue
        if entry.get("kind") == "conformance_workflow":
            declared = True
        elif entry.get("id") == PROJECTION_ENTRY["id"] or entry.get("target") == WORKFLOW_TARGET:
            collides = True
    return collides, declared


def _settled(root: Path, base_revision: str, candidate: dict) -> bool:
    """Whether the one committed evidence record carries exactly `candidate`."""
    records = adopt_inspection.evidence_records_at(root, base_revision)
    if len(records) != 1:
        return False
    data = adopt_inspection.blob_at(root, base_revision, records[0])
    try:
        record = json.loads(data.decode("utf-8")) if data is not None else None
    except (ValueError, UnicodeDecodeError, RecursionError):
        return False
    return isinstance(record, dict) and record.get("conformance") == candidate


def plan_conformance(root: Path, base_revision: str, contract_source: dict | None,
                     reference_after: Mapping[str, bytes]) -> ConformancePlan:
    """The conformance work of adopting `root` at `base_revision`.

    `reference_after[path]` replaces the base bytes of that target as its input,
    because an answered path reference edits the same file and the two edits
    must be one write.
    """
    lock = base_entry(root, base_revision, LOCK_FILE)
    if lock is None or base_entry(root, base_revision, derived_values.TREE_MANIFEST) is not None:
        return NOT_PLANNED

    def inputs(path: str, entry: tuple[str, bytes | None]) -> bytes:
        return reference_after.get(path, entry[1])

    revision = agent_platform.platform_revision()
    named = _tracker(contract_source)
    collides, declared = (_projection_state(contract_source)
                          if named is not None and isinstance(contract_source, dict)
                          else (False, False))
    # Every stage runs even after an earlier one failed: the first cause is the
    # plan's repair, but whether the repository is settled depends on the work
    # each stage would still plan, which a failing environment cause (an unknown
    # revision, a foreign origin, a pin that differs) does not change.
    causes: list[str] = []
    if revision is None:
        causes.append(REVISION_UNKNOWN)
    if named is None:
        causes.append(TRACKER_UNNAMED)
    else:
        try:
            origin = derived_values.remote_slug(root)
        except derived_values.Underivable:
            origin = None
        if origin != named[0]:
            causes.append(ORIGIN_MISMATCH)
        if collides:
            causes.append(PROJECTION_COLLIDES)
    entry: LockEntry | None = None
    try:
        if lock[1] is None:
            raise Undeclarable(LOCK_UNREADABLE)
        entry = lock_with_platform(inputs(LOCK_FILE, lock), revision)
    except Undeclarable as refused:
        causes.append(refused.repair_id)
    candidate: dict | None = None
    if entry is not None and named is not None:
        candidate = {
            "revision": entry.locked,
            "lock": {"path": LOCK_FILE, "input": INPUT, "node": entry.node},
            "workflow": WORKFLOW_TARGET,
            "required_check": {"repo": named[0], "branch": named[1], "context": CONTEXT},
        }
        if entry.kept and revision is not None and (
                entry.locked["rev"] != revision["rev"]
                or entry.locked["narHash"] != revision["narHash"]):
            causes.append(PIN_INCOMPATIBLE)
    declared_after: bytes | None = None
    declaration = base_entry(root, base_revision, INPUT_FILE)
    if entry is not None:
        try:
            if declaration is None or declaration[1] is None:
                raise Undeclarable(INPUT_UNDECLARABLE)
            declared_after = declare_input(
                inputs(INPUT_FILE, declaration), entry.locked["owner"], entry.locked["repo"])
        except Undeclarable as refused:
            causes.append(refused.repair_id)
    protection = base_entry(root, base_revision, PROTECTION_FILE)
    protection_after: bytes | None = None
    try:
        if protection is not None:
            if protection[1] is None:
                raise Undeclarable(PROTECTION_FILE_UNREQUIRED)
            protection_after = require_in_protection_file(inputs(PROTECTION_FILE, protection))
    except Undeclarable as refused:
        causes.append(refused.repair_id)
    contents: dict[str, bytes] = {}
    before: dict[str, bytes] = {}
    for path, source, after in ((PROTECTION_FILE, protection, protection_after),
                                (LOCK_FILE, lock, entry.after if entry is not None else None),
                                (INPUT_FILE, declaration, declared_after)):
        if after is not None:
            contents[path] = after
            before[path] = source[1]
    projection = not declared
    repair = causes[0] if causes else None
    settled = (candidate is not None and not contents and not projection
               and set(causes) <= {REVISION_UNKNOWN, ORIGIN_MISMATCH, PIN_INCOMPATIBLE}
               and _settled(root, base_revision, candidate))
    if repair is not None:
        contents, before, projection = {}, {}, False
    return ConformancePlan(True, not settled, repair,
                           candidate if repair is None else None, contents, before, projection)


# --------------------------------------------------------------------------
# The forge side
# --------------------------------------------------------------------------


def _required_failure(repair_id: str, message: str, pointer: str = REQUIRED_POINTER):
    return adopt_inspection.refuse("adopt_failure", repair_id, pointer, message)


def _answer_contexts(answer: object, branch: str) -> list[str]:
    """Every context a `required_status_checks` answer lists, or the refusal `unreadable`."""
    def unreadable() -> Exception:
        return _required_failure(
            REQUIRED_UNREADABLE,
            f"the required status checks of {branch} could not be read as a list of contexts")

    if not isinstance(answer, dict) or ("checks" not in answer and "contexts" not in answer):
        raise unreadable()
    found: list[str] = []
    if "contexts" in answer:
        contexts = answer["contexts"]
        if not isinstance(contexts, list) or not all(isinstance(item, str) for item in contexts):
            raise unreadable()
        found.extend(contexts)
    if "checks" in answer:
        checks = answer["checks"]
        if not isinstance(checks, list) or not all(
                isinstance(item, dict) and isinstance(item.get("context"), str) and item["context"]
                for item in checks):
            raise unreadable()
        found.extend(item["context"] for item in checks)
    return found


def _bound_elsewhere(answer: dict) -> bool:
    """Whether a listed `Conformance` check is bound to an app other than Actions."""
    checks = answer.get("checks")
    return isinstance(checks, list) and any(
        isinstance(item, dict) and item.get("context") == CONTEXT
        and item.get("app_id") not in (None, ACTIONS_APP_ID) for item in checks)


def required_check_state(repo: str, branch: str) -> str:
    """`required` when `Conformance` is a required check of `branch`, else `missing`.

    A branch with no protection, or whose protection requires no status check, is
    the refusal `adopt.required_check.unprotected`; a forge failure or an answer of
    another shape is `adopt.required_check.unreadable`; a `Conformance` check bound
    to a GitHub App other than Actions is `adopt.required_check.app_mismatch`.
    """
    path = f"repos/{repo}/branches/{branch}/protection/required_status_checks"
    try:
        answer = forge_api.gh_json(["api", path], allow=(404,))
    except forge_api.ForgeError:
        raise _required_failure(
            REQUIRED_UNREADABLE,
            f"the required status checks of {branch} could not be read from the forge") from None
    unprotected = _required_failure(
        REQUIRED_UNPROTECTED,
        f"the integration branch {branch} has no protection or requires no status checks; "
        f"turn on required status checks for {branch} and adopt again")
    if answer is None:
        raise unprotected
    contexts = _answer_contexts(answer, branch)
    if not contexts:
        raise unprotected
    if CONTEXT not in contexts:
        return "missing"
    if _bound_elsewhere(answer):
        raise _required_failure(
            REQUIRED_APP_MISMATCH,
            f"{CONTEXT} is required on {branch} by another GitHub App than Actions, which the "
            "generated workflow cannot satisfy; require it from any source or from Actions and "
            "adopt again")
    return "required"


def add_required_check(repo: str, branch: str) -> str:
    """Add `Conformance` to the required checks: `added`, or `refused` on a forge refusal.

    Any other failure (a timeout, a transport failure, a 5xx) propagates as an unknown outcome.
    """
    path = f"repos/{repo}/branches/{branch}/protection/required_status_checks/contexts"
    status, _ = forge_api.run_gh(
        ["api", "--method", "POST", path, "-f", f"contexts[]={CONTEXT}"], allow=(403, 404, 422))
    return "refused" if status else "added"


def pending_path(digest: str) -> Path:
    """The one home of an adoption's pending required-check record."""
    return agent_platform.state_root() / "adopt" / "worktrees" / f"{digest}.required-check.json"


def write_pending(digest: str, record: dict) -> None:
    path = pending_path(digest)
    agent_platform.ensure_directory(path.parent)
    agent_platform.write_atomically(path, adopt_inspection.canonical_json(record) + b"\n")


def read_pending(digest: str) -> dict:
    """The pending record, or the refusal `adopt.required_check.pending_mismatch`."""
    try:
        record = json.loads(pending_path(digest).read_bytes())
    except (OSError, ValueError):
        record = None
    if (not isinstance(record, dict) or sorted(record) != sorted(PENDING_MEMBERS)
            or not all(isinstance(record[key], str) and record[key] for key in PENDING_MEMBERS[:5])
            or not isinstance(record["result"], dict)):
        raise _required_failure(
            REQUIRED_PENDING_MISMATCH,
            "the pending required-check record of this plan cannot be read", "")
    return record


def preflight(root: Path, repo: str, branch: str) -> str:
    """The origin check, then the state read, before anything is mutated or requested.

    Both effective URLs of `origin` (fetch and push) must name `repo` on `github.com`.
    """
    slugs = []
    for arguments in (("get-url", "origin"), ("get-url", "--push", "origin")):
        code, out = adopt_inspection.run_git(root, "remote", *arguments, local_only=True)
        slugs.append(github_slug(out.decode("utf-8", "replace")) if code == 0 else None)
    if any(slug != repo for slug in slugs):
        raise _required_failure(
            REQUIRED_ORIGIN_MISMATCH,
            f"the remote origin is not {repo}, the repository the required check is requested on",
            f"{REQUIRED_POINTER}/repo")
    return required_check_state(repo, branch)


def settle_required_check(root: Path, digest: str, record: dict) -> dict:
    """The forge step after a proved commit: request the check and settle its outcome.

    Returns the `required_check` result member, or raises the refusals of the
    module docstring. The pending record is removed here only when the adoption
    branch was deleted; the caller removes it once the result is emitted.
    """
    repo, branch = record["repo"], record["integration_branch"]
    member = {"repo": repo, "branch": branch, "context": CONTEXT, "state": "added"}
    try:
        if add_required_check(repo, branch) == "added":
            return member
    except forge_api.ForgeError:
        pass
    adopt_branch, commit = record["branch"], record["commit"]
    try:
        state = required_check_state(repo, branch)
    except adopt_inspection.AdoptError as error:
        # A readable answer with no context (an empty list, a 404) is a confirmed absence.
        if error.repair_id != REQUIRED_UNPROTECTED:
            raise _required_failure(
                REQUIRED_UNKNOWN,
                f"the forge's answer to adding {CONTEXT} to {branch} is unknown; the adoption "
                f"branch {adopt_branch} at {commit} is kept, and applying this plan again "
                "settles it") from None
        state = "missing"
    if state == "required":
        return member
    ref = f"refs/heads/{adopt_branch}"
    deleted, _ = adopt_inspection.run_git(root, "update-ref", "-d", ref, commit)
    remaining, _ = adopt_inspection.run_git(root, "rev-parse", "--verify", "--quiet", ref)
    if deleted == 0 and remaining != 0:
        pending_path(digest).unlink(missing_ok=True)
        raise _required_failure(
            REQUIRED_REFUSED,
            f"the forge did not add {CONTEXT} to {branch}; the adoption branch was deleted, "
            "so nothing is committed")
    raise _required_failure(
        REQUIRED_ROLLBACK_FAILED,
        f"the forge did not add {CONTEXT} to {branch} and the adoption branch {adopt_branch} at "
        f"{commit} could not be deleted; delete it by hand")


def bind_pending(root: Path, digest: str, record: dict, document: dict) -> None:
    """The pending record belongs to this plan, or the refusal `pending_mismatch`.

    Its plan id, branch name, repository and integration branch are the stored
    plan's, and the commit it names carries the plan's evidence record with the
    plan's conformance member, so a misplaced or edited record can never make
    the settlement delete a branch that is not this adoption's.
    """
    plan = document["plan"]
    member = plan.get("conformance")
    target = member.get("required_check") if isinstance(member, dict) else None
    evidence = document["handoff"]["evidence_record"]
    result = record["result"]
    branch = f"adopt-{digest[:12]}"
    bound = (isinstance(target, dict) and record["plan_id"] == plan["plan_id"]
             and record["branch"] == branch and record["repo"] == target["repo"]
             and record["integration_branch"] == target["branch"]
             and result.get("plan_id") == plan["plan_id"] and result.get("branch") == branch
             and result.get("commit") == record["commit"]
             and result.get("evidence_record") == evidence)
    if bound:
        data = adopt_inspection.blob_at(root, record["commit"], evidence)
        try:
            committed = json.loads(data.decode("utf-8")) if data is not None else None
        except (ValueError, UnicodeDecodeError, RecursionError):
            committed = None
        bound = isinstance(committed, dict) and committed.get("conformance") == member
    if not bound:
        raise _required_failure(
            REQUIRED_PENDING_MISMATCH,
            "the pending required-check record does not belong to this plan's adoption", "")


def drop_stale_pending(root: Path, digest: str) -> None:
    """Remove the pending record of a plan whose adoption branch no longer exists.

    The branch is `adopt-<digest[:12]>`, the only branch a record of this plan may
    name. Deleted by hand after `adopt.required_check.rollback_failed`, it leaves a
    record that nothing can settle; a git failure other than an absent ref keeps it.
    """
    if not pending_path(digest).exists():
        return
    code, _ = adopt_inspection.run_git(
        root, "rev-parse", "--verify", "--quiet", f"refs/heads/adopt-{digest[:12]}")
    if code == 1:
        pending_path(digest).unlink(missing_ok=True)


@contextmanager
def plan_lock(digest: str) -> Iterator[None]:
    """Hold the plan's one lock, or refuse when another apply or discard holds it."""
    path = agent_platform.state_root() / "adopt" / "locks" / f"{digest}.lock"
    agent_platform.ensure_directory(path.parent)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise _required_failure(
                REQUIRED_PENDING,
                "another apply or discard of this plan is running; wait for it to finish", "") from None
        yield
    finally:
        os.close(descriptor)
