"""Host agent-slot admission vocabulary: the host declaration and its terms (#150).

This module is the one home of the declaration vocabulary: the declaration's
schema, the route-name grammar, the fixed role sets, the supported-route slot
floor and the closed reason codes (D18). It is imported by the conformance
evaluator, never run, so it carries no entry point.

The declaration is authored host policy installed at exactly
`$HOME/.agents/share/host-declaration.json` (D2). It declares, per route,
whether the route is supported and, when it is, the agent slots one root
session may hold at once. It also states, optionally, the host's verify slot
count (`verify_slots`), which `agent_tools.delivery.verify_slot` reads,
`verify_budget_seconds`, the hold in seconds a repository's median verify run
should stay within, which `verify-slot report` reads,
`verify_repository_slots`, a map of `owner/repo` to the number of that
repository's runs that may hold verify slots at once, which
`agent_tools.delivery.verify_slot` reads (`DEFAULT_REPOSITORY_VERIFY_SLOTS` for
a repository it does not name), and `verify_short_lane`, which
names, per repository, the short commands that run beside the verify slots in
their own lane, with that lane's slot count and time bound (a command's entry may
carry its own bound instead);
`agent_tools.delivery.verify_slot` reads it through `short_command`. Nothing else is
declared: admission reasons over declared `agent_slots` only, never CPU, memory
or load.
The `engine` route has no role sets: it counts one slot per live engine
session, so a supported engine route is valid with one slot or more.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import threading
from types import MappingProxyType
from typing import Sequence

HOST_ADMISSION_INTERFACE_VERSION = 1
DECLARATION_SCHEMA_VERSION = 1

# `direct` is reserved by the runtime for single-owner control; it never
# appears in the declaration (D3).
DIRECT_ROUTE = "direct"
ROUTE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")

# The role sets are fixed here rather than declared (D4): one controller per
# run, and every owner launch claims an owner with one worker and one reviewer.
CONTROLLER_ROLES = MappingProxyType({"controller": 1})
OWNER_ROLE_SET = MappingProxyType({"owner": 1, "worker": 1, "reviewer": 1})
ROLE_NAMES = ("controller", "owner", "worker", "reviewer")
# A supported route must host the controller plus one full owner role set, so
# no declaration can admit an owner without its reviewer.
MINIMUM_SUPPORTED_SLOTS = sum(CONTROLLER_ROLES.values()) + sum(OWNER_ROLE_SET.values())
# The engine route has no role sets: it counts one slot per live engine session.
ENGINE_ROUTE = "engine"
ENGINE_SESSION_SLOTS = 1


def minimum_slots(route: str) -> int:
    """The fewest agent slots a supported `route` may declare."""
    return ENGINE_SESSION_SLOTS if route == ENGINE_ROUTE else MINIMUM_SUPPORTED_SLOTS


REASON_CODES = (
    "declared_unsupported",
    "route_undeclared",
    "declaration_missing",
    "declaration_invalid",
)
UNSUPPORTED_ALTERNATIVE = "/deliver-standard <issue>"

DEFAULT_VERIFY_SLOTS = 1
DEFAULT_REPOSITORY_VERIFY_SLOTS = 1
# The lowercased `owner/repo` slug: an owner never begins with a dot, a
# repository name may (`example/.github`) but is never `.` or `..`.
REPOSITORY_NAME_PATTERN = re.compile(r"[a-z0-9_-][a-z0-9_.-]*/(?!\.{1,2}$)[a-z0-9_.-]+")

_DECLARATION_MEMBERS = frozenset({"schema_version", "routes"})
SHORT_LANE_MEMBERS = frozenset({"slots", "bound_seconds", "commands"})
SHORT_COMMAND_MEMBERS = frozenset({"argv", "bound_seconds"})

_OPTIONAL_DECLARATION_MEMBERS = frozenset(
    {"verify_slots", "verify_budget_seconds", "verify_repository_slots", "verify_short_lane"})
_SUPPORTED_MEMBERS = frozenset({"support", "agent_slots"})
_UNSUPPORTED_MEMBERS = frozenset({"support"})


class DeclarationError(Exception):
    """The declaration cannot be used; `reason_code` names why.

    `reason_code` is a member of `REASON_CODES`.
    """

    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        super().__init__(detail or reason_code)
        self.reason_code = reason_code


def declaration_path() -> Path | None:
    """The one installed location, or `None` when `HOME` is unset or empty."""
    home = os.environ.get("HOME")
    if not home:
        return None
    return Path(home) / ".agents/share/host-declaration.json"


def _invalid(detail: str) -> DeclarationError:
    return DeclarationError("declaration_invalid", detail)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    """`object_pairs_hook`: a duplicate key is refused, never last-wins."""
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise _invalid(f"duplicate key: {key}")
        result[key] = value
    return result


def _reject_non_finite(token: str) -> object:
    """`parse_constant`: the bare `NaN`/`Infinity`/`-Infinity` tokens are refused."""
    raise _invalid(f"non-finite number: {token}")


def _bound_valid(bound: object) -> bool:
    """Whether `bound` is a plain int >= 1 that a timer can count down."""
    return type(bound) is int and 1 <= bound <= threading.TIMEOUT_MAX


def _argv_valid(argv: object) -> bool:
    return isinstance(argv, list) and bool(argv) and all(
        isinstance(word, str) and word for word in argv)


def _short_entry(entry: object) -> tuple[list, int | None] | None:
    """`(argv, own bound or None)` of a short-command entry, `None` when it is not of the declared shape.

    An entry is an argv list, which takes the lane's bound, or exactly `{argv, bound_seconds}`.
    """
    if isinstance(entry, dict):
        if set(entry) != SHORT_COMMAND_MEMBERS or not _argv_valid(entry["argv"]) \
                or not _bound_valid(entry["bound_seconds"]):
            return None
        return entry["argv"], entry["bound_seconds"]
    return (entry, None) if _argv_valid(entry) else None


def _short_lane_valid(lane: object) -> bool:
    """Whether `lane` is exactly `{slots, bound_seconds, commands}` of the declared shape."""
    if not isinstance(lane, dict) or set(lane) != SHORT_LANE_MEMBERS:
        return False
    if type(lane["slots"]) is not int or lane["slots"] < 1 or not _bound_valid(lane["bound_seconds"]):
        return False
    commands = lane["commands"]
    if not isinstance(commands, dict):
        return False
    return all(
        isinstance(repository, str) and REPOSITORY_NAME_PATTERN.fullmatch(repository)
        and isinstance(entries, list) and entries
        and all(_short_entry(entry) is not None for entry in entries)
        and _bounds_agree(entries, lane["bound_seconds"])
        for repository, entries in commands.items())


def _bounds_agree(entries: list, lane_bound: int) -> bool:
    """Whether no argv among `entries` is declared with two different effective bounds."""
    bounds: dict[tuple, int] = {}
    for entry in entries:
        argv, own = _short_entry(entry)
        if bounds.setdefault(tuple(argv), lane_bound if own is None else own) \
                != (lane_bound if own is None else own):
            return False
    return True


def validate_declaration(value: object) -> dict:
    """Return `value` when it is a valid declaration; raise `DeclarationError`.

    Exact members at every level (D2): the top is `{schema_version, routes}`
    plus the optional `verify_slots` and `verify_budget_seconds`, each a plain
    int >= 1, `verify_repository_slots`, an object whose keys are
    lowercase `owner/repo` and whose values are plain ints >= 1, and
    `verify_short_lane`, `{slots, bound_seconds, commands}` with
    two such ints and `commands` mapping `owner/repo` to non-empty lists of
    entries, each a non-empty argv list (the lane's bound applies) or exactly
    `{argv, bound_seconds}` (its own bound applies);
    `schema_version` is a plain int equal to 1; `routes` is a non-empty object
    whose keys match the route grammar and are not `direct`; a supported route
    is exactly `{"support": "supported", "agent_slots": <int >= floor>}` and an
    unsupported one exactly `{"support": "unsupported"}`.
    """
    if not isinstance(value, dict):
        raise _invalid("declaration members")
    if not (_DECLARATION_MEMBERS <= set(value)
            <= _DECLARATION_MEMBERS | _OPTIONAL_DECLARATION_MEMBERS):
        raise _invalid("declaration members")
    if "verify_slots" in value:
        count = value["verify_slots"]
        if type(count) is not int or count < 1:
            raise _invalid("verify_slots")
    if "verify_budget_seconds" in value:
        budget = value["verify_budget_seconds"]
        if type(budget) is not int or budget < 1:
            raise _invalid("verify_budget_seconds")
    if "verify_short_lane" in value and not _short_lane_valid(value["verify_short_lane"]):
        raise _invalid("verify_short_lane")
    if "verify_repository_slots" in value:
        limits = value["verify_repository_slots"]
        if not isinstance(limits, dict) or any(
                not REPOSITORY_NAME_PATTERN.fullmatch(name)
                or type(limit) is not int or limit < 1
                for name, limit in limits.items()):
            raise _invalid("verify_repository_slots")
    version = value["schema_version"]
    if type(version) is not int or version != DECLARATION_SCHEMA_VERSION:
        raise _invalid("schema_version")
    routes = value["routes"]
    if not isinstance(routes, dict) or not routes:
        raise _invalid("routes")
    for name, route in routes.items():
        if not ROUTE_NAME_PATTERN.fullmatch(name) or name == DIRECT_ROUTE:
            raise _invalid(f"route name: {name!r}")
        if not isinstance(route, dict):
            raise _invalid(f"route {name}")
        support = route.get("support")
        if support == "supported":
            slots = route.get("agent_slots")
            if (set(route) != _SUPPORTED_MEMBERS or type(slots) is not int
                    or slots < minimum_slots(name)):
                raise _invalid(f"route {name}")
        elif support == "unsupported":
            if set(route) != _UNSUPPORTED_MEMBERS:
                raise _invalid(f"route {name}")
        else:
            raise _invalid(f"route {name} support")
    return value


def load_declaration() -> dict:
    """Read, parse and validate the installed declaration; return a deep copy.

    Symlinks are followed (the installed file is a store link). Only an absent
    entry (no such file, or a parent that is not a directory) is
    `declaration_missing`; an entry that cannot be inspected (a parent that
    denies traversal) or is not a readable file (a directory, a dangling
    symlink), and anything unparseable or refused by `validate_declaration`,
    is `declaration_invalid`.
    """
    path = declaration_path()
    if path is None:
        raise DeclarationError("declaration_missing")
    try:
        path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        raise DeclarationError("declaration_missing") from None
    except OSError as error:
        raise _invalid(f"unreadable: {error}") from None
    try:
        usable = path.is_file()
    except OSError as error:
        raise _invalid(f"unreadable: {error}") from None
    if not usable:
        raise _invalid("not a file")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise _invalid(f"unreadable: {error}") from None
    try:
        value = json.loads(text, object_pairs_hook=_unique_object,
                           parse_constant=_reject_non_finite)
    except (ValueError, RecursionError) as error:
        # `JSONDecodeError` is a `ValueError`, as is an integer literal past
        # CPython's conversion limit; deep nesting raises `RecursionError`.
        # Each is unparseable input, never a crash.
        raise _invalid(f"not JSON: {error}") from None
    return copy.deepcopy(validate_declaration(value))


def verify_slots(declaration: dict) -> int:
    """The host's verify slot count, or `DEFAULT_VERIFY_SLOTS` when undeclared.

    `declaration` is one `validate_declaration` already accepted.
    """
    return declaration.get("verify_slots", DEFAULT_VERIFY_SLOTS)


def verify_budget_seconds(declaration: dict) -> int | None:
    """The host's verify hold budget in seconds, or `None` when undeclared."""
    return declaration.get("verify_budget_seconds")


def short_command(declaration: dict, repository: str | None,
                  argv: Sequence[str]) -> tuple[int, int] | None:
    """`(slots, bound_seconds)` when `argv` is a declared short command of `repository`, else `None`.

    Matching is exact: a prefix, a longer argv or another repository never matches.
    `declaration` is one `validate_declaration` already accepted.
    """
    lane = declaration.get("verify_short_lane")
    if lane is None or repository is None:
        return None
    for entry in lane["commands"].get(repository, ()):
        declared, own = _short_entry(entry)
        if declared == list(argv):
            return lane["slots"], lane["bound_seconds"] if own is None else own
    return None


def repository_verify_slots(declaration: dict, repository: str) -> int:
    """The verify slots `repository` may hold at once, `DEFAULT_REPOSITORY_VERIFY_SLOTS` if unnamed.

    `declaration` is one `validate_declaration` already accepted.
    """
    return declaration.get("verify_repository_slots", {}).get(
        repository, DEFAULT_REPOSITORY_VERIFY_SLOTS)


def route_slots(declaration: dict, route: str) -> int:
    """The agent slots `route` declares; raise `DeclarationError` when it admits none.

    `declaration` is one `validate_declaration` already accepted. An absent
    route is `route_undeclared`; an `unsupported` one is `declared_unsupported`.
    """
    entry = declaration["routes"].get(route)
    if entry is None:
        raise DeclarationError("route_undeclared", route)
    if entry["support"] == "unsupported":
        raise DeclarationError("declared_unsupported", route)
    return entry["agent_slots"]
