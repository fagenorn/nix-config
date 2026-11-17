"""The guest door's policy (#1237): the access list, admission, the owner-port rule and the probe.

A guest is a listed colleague who reaches the console through Tailscale Serve on the console's
guest port (ADR-console-066). This module holds the pure rules only; `service.py` documents the
routes and applies them. It uses the standard library alone.

The access list is kept in the event log as three kinds (`event_log` records them and keeps the
newest rows in force through the retention pass): `sharing.tailnet` (`{"tailnet"}`: the one
tailnet name the console is shared at, or null for off), `sharing.colleague` (`{"login",
"projects"}`: the login's whole project list) and `sharing.removed` (`{"login"}`). `access_list`
folds rows in sequence order on top of a previous `Access` and never mutates it. A tailnet
payload that is not a valid name turns sharing off; a colleague row whose login is not already in
normal form (lowercase) or whose projects are not a non-empty list of non-empty strings removes
that login (fail closed); a row whose login is not a string is ignored.

`admit(access, hosts, logins)` returns `(login, None)` for an admitted request and `(None, text)`
for a refused one. The checks run in this order: sharing is off (`SHARING_OFF_TEXT`); the request
carries exactly one `Host` that, lowercased, is the configured tailnet name exactly, port
included (`HOST_TEXT`); it carries exactly one login header (`LOGIN_HEADER`) whose normal form is
a listed colleague (`NOT_SHARED_TEXT`). No text names a project or echoes a login or a host.
Each text is answered as `403 text/plain` with a trailing newline.

The owner's port refuses a request that carries any header whose name, lowercased, starts with
`tailscale-` or is `x-forwarded-for` (`owner_port_refusal`, `OWNER_PORT_TEXT`): a request through
Serve must never reach the owner's port, and a forged header gains a local process nothing.

`whoami` is the probe's answer (`PROBE_HEADER` carries a forged login the probe sends to learn
whether Serve strips it): counts and flags only, never the login values.

`parse_tailnet`, `parse_colleague` and `parse_removal` read the owner's write bodies as strict
JSON (a duplicate key, a non-object or an extra or missing key is refused) and raise
`ValueError` on a malformed body. Whether each project of a colleague is registered is checked by
the service, which raises `Refused` for a write refused on its merits.
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.console.event_log import (
    SHARING_COLLEAGUE, SHARING_REMOVED, SHARING_TAILNET, Event)

LOGIN_HEADER = "Tailscale-User-Login"
PROBE_HEADER = "X-Console-Probe"

SHARING_OFF_TEXT = "Sharing is off on this console."
HOST_TEXT = "This console is shared only at its tailnet name."
NOT_SHARED_TEXT = "This console is not shared with you. Ask its owner to add your Tailscale login."
OWNER_ONLY_TEXT = "Only the console's owner can do that."
OWNER_PORT_TEXT = ("This is the console owner's port. "
                   "Point Tailscale Serve at the console's guest port.")

TAILNET_MAX = 253
LOGIN_MAX = 254
PROJECTS_MAX = 50
PROJECT_MAX = 200

_TAILNET = re.compile(r"([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.){2,}ts\.net")
_LOGIN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+")


class Refused(Exception):
    """A write refused on its merits (an unregistered project, a name that cannot be kept)."""


@dataclass(frozen=True)
class Access:
    tailnet: str | None
    colleagues: Mapping[str, frozenset[str]]


NO_ACCESS = Access(None, MappingProxyType({}))


def valid_tailnet(text: object) -> bool:
    return (isinstance(text, str) and len(text) <= TAILNET_MAX
            and _TAILNET.fullmatch(text) is not None)


def normal_login(text: object) -> str | None:
    if (not isinstance(text, str) or len(text) > LOGIN_MAX or not text.isascii()
            or _LOGIN.fullmatch(text) is None):
        return None
    return text.lower()


def _projects_in_force(projects: object) -> bool:
    return (isinstance(projects, list) and bool(projects)
            and all(isinstance(project, str) and project for project in projects))


def access_list(events: Iterable[Event], previous: Access = NO_ACCESS) -> Access:
    tailnet = previous.tailnet
    colleagues = dict(previous.colleagues)
    for event in events:
        payload = event.payload
        if event.kind == SHARING_TAILNET:
            name = payload.get("tailnet") if isinstance(payload, dict) else None
            tailnet = name if valid_tailnet(name) else None
        elif event.kind == SHARING_COLLEAGUE:
            login = payload.get("login") if isinstance(payload, dict) else None
            if not isinstance(login, str):
                continue
            projects = payload.get("projects")
            if normal_login(login) == login and _projects_in_force(projects):
                colleagues[login] = frozenset(projects)
            else:
                colleagues.pop(login, None)
        elif event.kind == SHARING_REMOVED:
            login = payload.get("login") if isinstance(payload, dict) else None
            if isinstance(login, str):
                colleagues.pop(login, None)
    return Access(tailnet, MappingProxyType(colleagues))


def _object(body: bytes, members: set[str]) -> dict:
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except RecursionError as error:
        raise ValueError("the body is nested too deeply") from error
    if not isinstance(value, dict) or set(value) != members:
        raise ValueError(f"the body must be an object of exactly {', '.join(sorted(members))}")
    return value


def parse_tailnet(body: bytes) -> str | None:
    name = _object(body, {"tailnet"})["tailnet"]
    if name is None:
        return None
    if not isinstance(name, str) or not valid_tailnet(name.lower()):
        raise ValueError("tailnet must be null or a <host>.<tailnet>.ts.net name")
    return name.lower()


def _login(value: object) -> str:
    login = normal_login(value)
    if login is None:
        raise ValueError("login must be an email-style Tailscale login")
    return login


def parse_colleague(body: bytes) -> tuple[str, tuple[str, ...]]:
    value = _object(body, {"login", "projects"})
    login = _login(value["login"])
    projects = value["projects"]
    if (not isinstance(projects, list) or not 1 <= len(projects) <= PROJECTS_MAX
            or not all(isinstance(project, str) and 0 < len(project) <= PROJECT_MAX
                       for project in projects)
            or len(set(projects)) != len(projects)):
        raise ValueError(
            f"projects must be 1 to {PROJECTS_MAX} distinct non-empty strings")
    return login, tuple(sorted(projects))


def parse_removal(body: bytes) -> str:
    return _login(_object(body, {"login"})["login"])


def admit(access: Access, hosts: Sequence[str],
          logins: Sequence[str]) -> tuple[str | None, str | None]:
    if access.tailnet is None:
        return None, SHARING_OFF_TEXT
    if len(hosts) != 1 or hosts[0].lower() != access.tailnet:
        return None, HOST_TEXT
    if len(logins) != 1:
        return None, NOT_SHARED_TEXT
    login = normal_login(logins[0])
    if login is None or login not in access.colleagues:
        return None, NOT_SHARED_TEXT
    return login, None


def owner_port_refusal(names: Iterable[str]) -> str | None:
    for name in names:
        lowered = name.lower()
        if lowered.startswith("tailscale-") or lowered == "x-forwarded-for":
            return OWNER_PORT_TEXT
    return None


def whoami(hosts: Sequence[str], logins: Sequence[str], forwarded: Sequence[str],
           probes: Sequence[str]) -> dict:
    return {"host": hosts[0] if len(hosts) == 1 else None,
            "hosts": len(hosts),
            "login_headers": len(logins),
            "forwarded_for": bool(forwarded),
            "probe_login_arrived": len(probes) == 1 and probes[0] in logins}
