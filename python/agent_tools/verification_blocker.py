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
- the content identity of a failure (issue 543 D3).

A validator returns its argument itself, never a copy, and never mutates it.
Every refusal is one `BlockerRefused` whose message is one line,
`<field>: <reason>`.
"""

import json
import re
import unicodedata

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

_FACT_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_OBJECT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_BLOCKER_ID = re.compile(r"sha256:[0-9a-f]{64}")

_SECRET_PREFIXES = (".env", "id_rsa", "id_ecdsa", "id_ed25519")
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
_SECRET_PARTS = ("secret", "token", "password", "passwd", "credential",
                 "private-key", "private_key", "api-key", "api_key", "apikey")


class BlockerRefused(ValueError):
    """A refusal, worded as one line `<field>: <reason>`."""


def _refuse(label: str, reason: str) -> BlockerRefused:
    return BlockerRefused(f"{label}: {reason}")


def strict_load(raw: bytes) -> object:
    """Decode UTF-8 JSON, refusing repeated keys and non-finite literals."""
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                          parse_constant=reject_nonfinite_literal)
    except (UnicodeError, ValueError) as error:
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
            _closed(entry, where, {"path", "object"})
            if entry["path"] != path:
                raise _refuse(f"{where}.path", "must equal the source path")
            if entry["object"] is not None and (
                    not isinstance(entry["object"], str)
                    or not _OBJECT_ID.fullmatch(entry["object"])):
                raise _refuse(f"{where}.object", "must be null or 40 or 64 lowercase hex")
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
    return {"command_id": value["command_id"], "failure_class": value["failure_class"],
            "worktree": worktree, "facts": _sources(value["facts"], "facts", normalize=True)}


def blocker_id(failure: object) -> str:
    """The content identity of a valid failure (issue 543 D3); an invalid one gets none."""
    validate_failure(failure)
    return telemetry_digest({member: failure[member] for member in
                             ("command", "failure_class", "facts", "repository")})
