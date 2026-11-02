"""The shared verification blocker's pure rules (issue 543 D1).

This module touches no file, clock, process, network or environment variable.
It is the one home of:

- the vocabulary: the object kinds, the schema version, the closed failure
  classes and the limits;
- the three closed wire shapes and their validators: `verification-failure`,
  `verification-observation` and the `verification` requirement (issue 543 D2);
- order normalization of a declared selection (issue 543 D5);
- the secret-shape rule (issue 543 D4);
- strict loading and canonical bytes;
- the content identity of a failure (issue 543 D3);
- the ledger's schema-11 rules (issue 544 D2-D5, D9): `park`, which records an attempt
  parked on a failure in the run's blocker map, `validate_blockers`, which checks that map
  against the run's attempt pointers, and `upgrade_ten`, the strict 10 -> 11 step.

A shape validator returns its argument itself, never a copy, and never mutates
it; `validate_blockers` returns None and mutates nothing. Every refusal is one
`BlockerRefused` whose message is one line, `<field>: <reason>`, with any map key
or pointer it names JSON-escaped.
"""

import copy
import json
import re
import unicodedata
from collections.abc import Mapping

from agent_tools.canonical import (
    reject_duplicate_keys,
    reject_nonfinite_literal,
    telemetry_digest,
)

SCHEMA_VERSION = 1
FAILURE_KIND = "verification-failure"
OBSERVATION_KIND = "verification-observation"
REQUIREMENT_KIND = "verification"
FAILURE_CLASSES = ("command_input", "dependency", "environment", "external_service")
MAX_FACTS = 4
MAX_PATHS = 8
MAX_PATH_BYTES = 255
MAX_FAILURE_BYTES = 2048
# The tree-entry modes Git writes (a tree, a file, an executable file, a symlink, a
# submodule commit); `git ls-tree` prints them canonicalized, so no other mode occurs.
ENTRY_MODES = ("040000", "100644", "100755", "120000", "160000")

_FACT_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_OBJECT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_BLOCKER_ID = re.compile(r"sha256:[0-9a-f]{64}")

# The identity digests these members of a failure and a ledger record keeps the same
# ones, so a record can be re-identified from its own content (issue 543 D3).
_IDENTITY_MEMBERS = ("command", "failure_class", "facts", "repository")
_RECORD_MEMBERS = {"id", "attempts", "state", "resolution", *_IDENTITY_MEMBERS}
_REFERENCE_MEMBERS = {"issue", "attempt"}

_SECRET_PREFIXES = (".env", "id_rsa", "id_ecdsa", "id_ed25519")
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
_SECRET_PARTS = ("secret", "token", "password", "passwd", "credential",
                 "private-key", "private_key", "api-key", "api_key", "apikey")


class BlockerRefused(ValueError):
    """A refusal, worded as one line `<field>: <reason>`."""


def _refuse(label: str, reason: str) -> BlockerRefused:
    return BlockerRefused(f"{label}: {reason}")


def _shown(value: object) -> str:
    """A value as a refusal names it: escaped, so a newline cannot split the line (issue 544 D20)."""
    text = json.dumps(value, ensure_ascii=True, default=repr)
    return text[1:-1] if isinstance(value, str) else text


def strict_load(raw: bytes) -> object:
    """Decode UTF-8 JSON, refusing repeated keys, non-finite literals and runaway nesting."""
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                          parse_constant=reject_nonfinite_literal)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise BlockerRefused(f"input: {error}") from error


def canonical_bytes(value: object) -> bytes:
    """Sorted, compact, ASCII-escaped JSON with no trailing newline."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def secret_shaped(name: str) -> bool:
    """Whether a fact name or one path component looks like a credential (issue 543 D4)."""
    lowered = name.lower()
    return (lowered == "private"
            or lowered.startswith(_SECRET_PREFIXES)
            or lowered.endswith(_SECRET_SUFFIXES)
            or any(part in lowered for part in _SECRET_PARTS))


def _closed(value: object, label: str, members: set[str]) -> dict:
    if not isinstance(value, dict):
        raise _refuse(label, "must be an object")
    if set(value) != members:
        raise _refuse(label, f"missing {sorted(members - set(value))}, "
                             f"unknown {sorted(set(value) - members)}")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise _refuse(label, "must be a non-empty string")
    return value


def _has_control(text: str) -> bool:
    return any(unicodedata.category(char) == "Cc" for char in text)


def _items(value: object, label: str, low: int, high: int) -> list:
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise _refuse(label, f"must be a list of {low} to {high} items")
    return value


def _header(value: object, label: str, kind: str, members: set[str],
            versioned: bool = True) -> dict:
    _closed(value, label, members)
    if value["kind"] != kind:
        raise _refuse(f"{label}.kind", f"must be {kind}")
    if versioned and (type(value["schema_version"]) is not int
                      or value["schema_version"] != SCHEMA_VERSION):
        raise _refuse(f"{label}.schema_version", f"must be {SCHEMA_VERSION}")
    return value


def _blocker_id(value: object, label: str) -> None:
    if not isinstance(value, str) or not _BLOCKER_ID.fullmatch(value):
        raise _refuse(label, "must be sha256: and 64 lowercase hex characters")


def _failure_class(value: object, label: str) -> None:
    if not isinstance(value, str) or value not in FAILURE_CLASSES:
        raise _refuse(label, "unclassified")


def _structural(path: str, label: str) -> None:
    if (path.startswith("/") or path.endswith("/") or "\\" in path
            or any(segment in ("", ".", "..") for segment in path.split("/"))
            or _has_control(path)):
        raise _refuse(label, "not a canonical relative path")


def _selected_path(path: object, label: str) -> None:
    _text(path, label)
    try:
        size = len(path.encode("utf-8"))
    except UnicodeEncodeError:
        raise _refuse(label, "not UTF-8") from None
    if size > MAX_PATH_BYTES:
        raise _refuse(label, f"longer than {MAX_PATH_BYTES} bytes")
    _structural(path, label)
    for component in path.split("/"):
        if component.lower() == ".git":
            raise _refuse(label, "names .git")
        if secret_shaped(component):
            raise _refuse(label, "secret-shaped")


def _paths(value: object, label: str, normalize: bool = False) -> list:
    """Check a fact's paths; `normalize` sorts them first, a repeat still refuses."""
    paths = _items(value, label, 1, MAX_PATHS)
    for index, path in enumerate(paths):
        _selected_path(path, f"{label}[{index}]")
    if normalize:
        paths = sorted(paths)
    if any(left >= right for left, right in zip(paths, paths[1:])):
        raise _refuse(label, "must be sorted and unique")
    return paths


def _name(value: object, label: str) -> None:
    if not isinstance(value, str) or not _FACT_NAME.fullmatch(value):
        raise _refuse(label, "must match [a-z0-9][a-z0-9-]{0,63}")
    if secret_shaped(value):
        raise _refuse(label, "secret-shaped")


def _selection(facts: list[tuple[str, list]], label: str) -> None:
    """Names strictly increasing, and no path selected by two facts."""
    seen: set[str] = set()
    for index, (name, paths) in enumerate(facts):
        if index and facts[index - 1][0] >= name:
            raise _refuse(f"{label}[{index}].name", "must be sorted and unique")
        if seen.intersection(paths):
            raise _refuse(f"{label}[{index}].paths", "selected by another fact")
        seen.update(paths)


def _valued_facts(value: object, label: str) -> None:
    selection = []
    for index, fact in enumerate(_items(value, label, 1, MAX_FACTS)):
        at = f"{label}[{index}]"
        _closed(fact, at, {"name", "source", "value"})
        _name(fact["name"], f"{at}.name")
        source = _closed(fact["source"], f"{at}.source", {"paths"})
        paths = _paths(source["paths"], f"{at}.source.paths")
        held = _closed(fact["value"], f"{at}.value", {"objects"})
        objects = held["objects"]
        if not isinstance(objects, list) or len(objects) != len(paths):
            raise _refuse(f"{at}.value.objects", "must hold one entry per path")
        for place, (path, entry) in enumerate(zip(paths, objects)):
            where = f"{at}.value.objects[{place}]"
            _closed(entry, where, {"path", "mode", "object"})
            if entry["path"] != path:
                raise _refuse(f"{where}.path", "must equal the source path")
            if entry["object"] is not None and (
                    not isinstance(entry["object"], str)
                    or not _OBJECT_ID.fullmatch(entry["object"])):
                raise _refuse(f"{where}.object", "must be null or 40 or 64 lowercase hex")
            if entry["object"] is None:
                if entry["mode"] is not None:
                    raise _refuse(f"{where}.mode", "must be null when the object is null")
            elif not isinstance(entry["mode"], str) or entry["mode"] not in ENTRY_MODES:
                raise _refuse(f"{where}.mode", "must be one of " + ", ".join(ENTRY_MODES))
        selection.append((fact["name"], paths))
    _selection(selection, label)


def _repository(value: object, label: str) -> None:
    _closed(value, label, {"project_id", "integration_branch"})
    for member in ("project_id", "integration_branch"):
        text = _text(value[member], f"{label}.{member}")
        try:
            size = len(text.encode("utf-8"))
        except UnicodeEncodeError:
            raise _refuse(f"{label}.{member}", "not UTF-8") from None
        if size > MAX_PATH_BYTES or _has_control(text) or any(c.isspace() for c in text):
            raise _refuse(f"{label}.{member}",
                          "must be at most 255 bytes with no control or space character")


def _command(value: object, label: str) -> None:
    _closed(value, label, {"id", "argv", "cwd", "env"})
    _text(value["id"], f"{label}.id")
    argv = value["argv"]
    if not isinstance(argv, list) or not argv:
        raise _refuse(f"{label}.argv", "must be a non-empty list")
    for index, word in enumerate(argv):
        _text(word, f"{label}.argv[{index}]")
    cwd = _text(value["cwd"], f"{label}.cwd")
    if cwd != ".":
        _structural(cwd, f"{label}.cwd")
    env = value["env"]
    if not isinstance(env, list) or any(
            not isinstance(name, str) or not _ENV_NAME.fullmatch(name) for name in env):
        raise _refuse(f"{label}.env", "must be a list of variable names")
    if len(set(env)) != len(env):
        raise _refuse(f"{label}.env", "must not repeat a name")


def validate_failure(value: object) -> dict:
    """Check a `verification-failure`; returns `value` itself."""
    if isinstance(value, dict) and "failure_class" not in value:
        raise _refuse("failure_class", "unclassified")
    _header(value, "failure", FAILURE_KIND,
            {"kind", "schema_version", "repository", "command", "failure_class", "facts"})
    _repository(value["repository"], "repository")
    _command(value["command"], "command")
    _failure_class(value["failure_class"], "failure_class")
    _valued_facts(value["facts"], "facts")
    if len(canonical_bytes(value)) > MAX_FAILURE_BYTES:
        raise _refuse("failure", f"longer than {MAX_FAILURE_BYTES} canonical bytes")
    return value


def validate_observation(value: object) -> dict:
    """Check a `verification-observation`; returns `value` itself."""
    _header(value, "observation", OBSERVATION_KIND,
            {"kind", "schema_version", "blocker_id", "repository", "facts"})
    _blocker_id(value["blocker_id"], "blocker_id")
    _repository(value["repository"], "repository")
    _valued_facts(value["facts"], "facts")
    return value


def _sources(items: object, label: str, normalize: bool) -> list:
    """Check `{name, paths}` selections; returns them, normalized when asked."""
    checked = []
    for index, item in enumerate(_items(items, label, 1, MAX_FACTS)):
        at = f"{label}[{index}]"
        _closed(item, at, {"name", "paths"})
        _name(item["name"], f"{at}.name")
        checked.append({"name": item["name"],
                        "paths": _paths(item["paths"], f"{at}.paths", normalize)})
    if normalize:
        checked.sort(key=lambda item: item["name"])
    _selection([(item["name"], item["paths"]) for item in checked], label)
    return checked


def validate_requirement(value: object) -> dict:
    """Check a `verification` requirement; returns `value` itself."""
    _header(value, "requirement", REQUIREMENT_KIND, {"kind", "blocker_id", "sources"},
            versioned=False)
    _blocker_id(value["blocker_id"], "blocker_id")
    _sources(value["sources"], "sources", normalize=False)
    return value


def normalize_declaration(value: object) -> dict:
    """The declared selection in order (issue 543 D5); spelling is never rewritten."""
    if isinstance(value, dict) and "failure_class" not in value:
        raise _refuse("failure_class", "unclassified")
    _closed(value, "declaration", {"command_id", "failure_class", "worktree", "facts"})
    _text(value["command_id"], "command_id")
    _failure_class(value["failure_class"], "failure_class")
    worktree = _text(value["worktree"], "worktree")
    if not worktree.startswith("/") or _has_control(worktree):
        raise _refuse("worktree", "must be an absolute path with no control character")
    try:
        worktree.encode("utf-8")
    except UnicodeEncodeError:
        raise _refuse("worktree", "must encode as UTF-8") from None
    return {"command_id": value["command_id"], "failure_class": value["failure_class"],
            "worktree": worktree, "facts": _sources(value["facts"], "facts", normalize=True)}


def blocker_id(failure: object) -> str:
    """The content identity of a valid failure (issue 543 D3); an invalid one gets none."""
    validate_failure(failure)
    return telemetry_digest({member: failure[member] for member in _IDENTITY_MEMBERS})


def _positive(value: object, label: str) -> int:
    """A positive `int`; a `bool` is not one."""
    if type(value) is not int or value < 1:
        raise _refuse(label, "must be a positive integer")
    return value


def park(blockers: dict, failure: object, issue: int, attempt: int) -> str:
    """Record that `issue`:`attempt` is parked on `failure`; returns the blocker id.

    A new id gets a record holding deep copies of the failure's identity members; a known
    id only gains the reference (kept sorted, listed once) and is reopened, its content
    never rewritten (issue 544 D3, D4). Everything is checked before `blockers` changes.
    """
    _positive(issue, "issue")
    _positive(attempt, "attempt")
    identity = blocker_id(failure)
    reference = {"issue": issue, "attempt": attempt}
    record = blockers.get(identity)
    if record is None:
        blockers[identity] = {"id": identity,
                              **{member: copy.deepcopy(failure[member])
                                 for member in _IDENTITY_MEMBERS},
                              "attempts": [reference], "state": "open", "resolution": None}
        return identity
    if reference not in record["attempts"]:
        record["attempts"].append(reference)
        record["attempts"].sort(key=lambda each: (each["issue"], each["attempt"]))
    record["state"] = "open"
    record["resolution"] = None
    return identity


def _references(value: object, label: str, attempts: Mapping) -> None:
    """R3: a non-empty, strictly increasing list of attempts that belong to this run."""
    if not isinstance(value, list) or not value:
        raise _refuse(label, "must be a non-empty list")
    keys = []
    for index, entry in enumerate(value):
        at = f"{label}[{index}]"
        _closed(entry, at, _REFERENCE_MEMBERS)
        key = (_positive(entry["issue"], f"{at}.issue"),
               _positive(entry["attempt"], f"{at}.attempt"))
        if keys and keys[-1] >= key:
            raise _refuse(label, "must be strictly increasing by issue and attempt")
        if key not in attempts:
            raise _refuse(at, "names no attempt of this run")
        keys.append(key)


def _resolution(record: dict, label: str) -> None:
    """R4: an open record has no resolution; a resolved one carries changed facts."""
    state, resolution = record["state"], record["resolution"]
    if state == "open":
        if resolution is not None:
            raise _refuse(f"{label}.resolution", "must be null while open")
        return
    if state != "resolved":
        raise _refuse(f"{label}.state", "must be open or resolved")
    at = f"{label}.resolution"
    _closed(resolution, at, {"facts"})
    _valued_facts(resolution["facts"], f"{at}.facts")
    held, now = record["facts"], resolution["facts"]
    if ([(each["name"], each["source"]) for each in held]
            != [(each["name"], each["source"]) for each in now]):
        raise _refuse(f"{at}.facts", "must keep the record's names and sources")
    if all(old["value"] == new["value"] for old, new in zip(held, now)):
        raise _refuse(f"{at}.facts", "must change at least one value")


def validate_blockers(blockers: object, pointers: Mapping[tuple[int, int], str | None]) -> None:
    """Check a run's blocker map against its attempts' pointers (issue 544 D3-D5).

    `pointers` maps every `(issue, attempt)` of the run to its blocker id or None.
    Returns None and mutates nothing; the first broken rule is the refusal.
    """
    if not isinstance(blockers, dict):
        raise _refuse("verification_blockers", "must be an object")
    for key, record in blockers.items():
        label = f"verification_blockers[{_shown(key)}]"
        _closed(record, label, _RECORD_MEMBERS)
        if record["id"] != key:
            raise _refuse(f"{label}.id", "must equal its key")
        try:
            identity = blocker_id({"kind": FAILURE_KIND, "schema_version": SCHEMA_VERSION,
                                   **{member: record[member] for member in _IDENTITY_MEMBERS}})
        except BlockerRefused as error:
            raise _refuse(label, str(error)) from error
        if identity != key:
            raise _refuse(f"{label}.id", "must be the identity of its content")
        _references(record["attempts"], f"{label}.attempts", pointers)
        _resolution(record, label)
    for (issue, attempt), pointer in pointers.items():
        if pointer is None:
            continue
        listed = blockers.get(pointer, {}).get("attempts", [])
        if {"issue": issue, "attempt": attempt} not in listed:
            raise _refuse("verification_blockers",
                          f"attempt {_shown(issue)}:{_shown(attempt)} points at "
                          f"{_shown(pointer)}, which does not list it")


def upgrade_ten(document: object) -> dict:
    """The strict schema 10 -> 11 step (issue 544 D9): adds the empty blocker map and a null
    pointer to every attempt, refusing a document that already holds either. The input is
    checked in full, then copied; it is never mutated."""
    if (not isinstance(document, dict) or type(document.get("schema_version")) is not int
            or document["schema_version"] != 10):
        raise _refuse("schema_version", "must be 10")
    if "verification_blockers" in document:
        raise _refuse("verification_blockers", "present before schema 11")
    issues = document.get("issues")
    if not isinstance(issues, dict):
        raise _refuse("issues", "must be an object")
    for key, entry in issues.items():
        label = f"issues[{_shown(key)}]"
        if not isinstance(entry, dict) or not isinstance(entry.get("attempts"), list):
            raise _refuse(label, "must be an object with an attempts list")
        for index, attempt in enumerate(entry["attempts"]):
            at = f"{label}.attempts[{index}]"
            if not isinstance(attempt, dict):
                raise _refuse(at, "must be an object")
            if "verification_blocker" in attempt:
                raise _refuse(f"{at}.verification_blocker", "present before schema 11")
    upgraded = copy.deepcopy(document)
    upgraded["schema_version"] = 11
    upgraded["verification_blockers"] = {}
    for entry in upgraded["issues"].values():
        for attempt in entry["attempts"]:
            attempt["verification_blocker"] = None
    return upgraded
