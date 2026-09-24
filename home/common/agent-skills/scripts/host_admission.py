"""Host agent-slot admission vocabulary: the host declaration and its terms (#150).

This module is the one home of the declaration vocabulary: the declaration's
schema, the route-name grammar, the fixed role sets, the supported-route slot
floor and the closed reason codes (D18). It is imported by `workflow-state` and
by the conformance evaluator, never run, so it carries no entry point. Claim
policy is not here; it stays in `workflow-state.py`, so conformance never holds
a claim API (D13).

The declaration is authored host policy installed at exactly
`$HOME/.agents/share/host-declaration.json` (D2). It declares, per route,
whether the route is supported and, when it is, the agent slots one root
session may hold at once. Nothing else is declared: admission reasons over
declared `agent_slots` only, never CPU, memory or load.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
from types import MappingProxyType

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

REASON_CODES = (
    "declared_unsupported",
    "route_undeclared",
    "declaration_missing",
    "declaration_invalid",
)
UNSUPPORTED_ALTERNATIVE = "/from-issue <issue> --auto"

_DECLARATION_MEMBERS = frozenset({"schema_version", "routes"})
_SUPPORTED_MEMBERS = frozenset({"support", "agent_slots"})
_UNSUPPORTED_MEMBERS = frozenset({"support"})


class DeclarationError(Exception):
    """The declaration cannot be used; `reason_code` names why.

    `reason_code` is `declaration_missing` or `declaration_invalid`.
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


def validate_declaration(value: object) -> dict:
    """Return `value` when it is a valid declaration; raise `DeclarationError`.

    Exact members at every level (D2): the top is `{schema_version, routes}`;
    `schema_version` is a plain int equal to 1; `routes` is a non-empty object
    whose keys match the route grammar and are not `direct`; a supported route
    is exactly `{"support": "supported", "agent_slots": <int >= floor>}` and an
    unsupported one exactly `{"support": "unsupported"}`.
    """
    if not isinstance(value, dict) or set(value) != _DECLARATION_MEMBERS:
        raise _invalid("declaration members")
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
                    or slots < MINIMUM_SUPPORTED_SLOTS):
                raise _invalid(f"route {name}")
        elif support == "unsupported":
            if set(route) != _UNSUPPORTED_MEMBERS:
                raise _invalid(f"route {name}")
        else:
            raise _invalid(f"route {name} support")
    return value


def load_declaration() -> dict:
    """Read, parse and validate the installed declaration; return a deep copy.

    Symlinks are followed (the installed file is a store link). An absent file
    is `declaration_missing`; anything unreadable, unparseable or refused by
    `validate_declaration` is `declaration_invalid`.
    """
    path = declaration_path()
    try:
        present = path is not None and path.is_file()
    except OSError as error:
        raise _invalid(f"unreadable: {error}") from None
    if not present:
        raise DeclarationError("declaration_missing")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise _invalid(f"unreadable: {error}") from None
    try:
        value = json.loads(text, object_pairs_hook=_unique_object,
                           parse_constant=_reject_non_finite)
    except json.JSONDecodeError as error:
        raise _invalid(f"not JSON: {error}") from None
    return copy.deepcopy(validate_declaration(value))
