"""The guest door's policy (#1237): the access list, admission, scoping, the owner-port rule and the probe.

A guest is a listed colleague who reaches the console through Tailscale Serve, which proxies to the
console's guest socket (ADR-console-066, ADR-console-077). This module holds the pure rules only; `service.py` documents the
routes and applies them. It uses the standard library alone.

The access list is kept in the event log as three kinds (`event_log` records them and keeps the
newest rows in force through the retention pass): `sharing.tailnet` (`{"tailnet"}`: the one
tailnet name the console is shared at, or null for off), `sharing.colleague` (`{"login",
"projects"}`: the login's whole project list) and `sharing.removed` (`{"login"}`). `access_list`
folds rows in sequence order on top of a previous `Access` and never mutates it. A tailnet
payload that is not a valid name turns sharing off; a colleague row whose login is not already in
normal form (lowercase) or whose projects are not a non-empty list of non-empty strings removes
that login (fail closed); a row whose login is not a string is ignored.

`admit(access, hosts, forwarded_hosts, logins)` returns `(login, None)` for an admitted request and
`(None, text)` for a refused one (ADR-console-077 D4). The checks run in this order: sharing is off
(`SHARING_OFF_TEXT`); the request carries exactly one `Host` that, lowercased, is `LOCAL_HOST`
(`localhost`, no port) and exactly one `X-Forwarded-Host` (`FORWARDED_HOST_HEADER`) that, lowercased,
is the configured tailnet name exactly, with no port form (`HOST_TEXT`); it carries exactly one login
header (`LOGIN_HEADER`) whose normal form is a listed colleague (`NOT_SHARED_TEXT`). No text names a
project or echoes a login or a host.
Each text is answered as `403 text/plain` with a trailing newline.

The guest door is a Unix socket (ADR-console-077). `door_refusal(folder, sock, owner_uid)` takes the
`os.lstat` of the socket's folder and of the socket (None when absent) and returns None only when the
folder is a directory and the socket a socket, both the owner's, the folder with no mode bit outside
`FOLDER_MODE` (0700) and the socket none outside `SOCKET_MODE` (0600); a narrower mode is not wider,
and an execute bit on the socket, setuid, setgid or sticky is. Anything else is `DOOR_WIDER`. It
reads the two stat results only. On macOS an ACL is kept beside the mode bits and can grant another
account a folder whose mode is 0700, so `acl_grants(path)` (`acl_reader_for(sys.platform)`; None
elsewhere, where the group bits already hold an ACL's mask) is True when the path itself, never what
a symlink names, carries an allow entry; a deny-only ACL grants nothing. It raises `OSError` when the
ACL cannot be read, which the service treats as a grant.

The owner's port refuses a request that carries any header whose name, lowercased, starts with
`tailscale-` or is `x-forwarded-for` (`owner_port_refusal`, `OWNER_PORT_TEXT`): a request through
Serve must never reach the owner's port, and a forged header gains a local process nothing.

`whoami` is the probe's answer (`PROBE_HEADER` carries a forged login the probe sends to learn
whether Serve strips it): the `Host` and the forwarded host it saw (each only when exactly one
arrived), how many of each arrived, and counts and flags only for the logins, never their values.

A guest sees a scoped copy of the owner's view (`scoped`, `scrub`). `scoped(inputs, projects)`
takes the keyword inputs of `view.derive_view` and a guest's project ids and returns inputs that
hold only those projects: `states`, `records`, `health`, `movement`, `owner_notices`, `sprints` and
`pending` keep the members of a listed project; `sessions` keep only those whose repository is a
kept project's root (so no unmanaged entry, no other repository); `deliveries` keep only those of a
kept session. `PASSED_INPUTS` pass as given and every `OWNER_ONLY_INPUTS` key is reset to its listed
empty value whether or not it was given. The input set is closed: a key of none of the three sets
is refused with `ValueError("unscoped view input <name>")`, so a view input added later must be
classified before a guest can see it. `scrub(view)` then drops what the inputs cannot: the `sharing`
member, the unmanaged list, the per-profile session counts, the sign-in, account, pin and
registration members, the digest, the activation line, the spend view and the capacity profiles.
`picture_ids(view)` is the set of every picture id in the scoped view, found by walking every list
stored under a key `pictures`: a picture read is answered to a guest only for an id this walk
finds in that guest's scoped view.

`reading(access, hosts, forwarded_hosts, logins, forwarded, probes)` is what one guest-door request
showed, for the owner's `sharing.last_request` (`READING_MEMBERS`): whether it was admitted and, if
not, the `REASON_CODES` code (`sharing_off`, `host`, `not_shared`); how many `Host`, `X-Forwarded-Host`
and login headers arrived; each of the `Host` and the forwarded host only when exactly one arrived and
it is a hostname of letters, digits, dots and hyphens with an optional port (so an `@` or a long
value is never kept); `host_local` (exactly one `Host`, `localhost` lowercased); and the
`forwarded_host_form` (`HOST_FORMS`: `exact` the tailnet name, `with_port` the name with `:443`,
`other`, `none`) of the forwarded host; whether
`X-Forwarded-For` arrived; `probe` (exactly one probe header carrying `PROBE_LOGIN`) and
`probe_login_arrived` (`PROBE_LOGIN` arrived as a login, whatever the probe header said); `login_valid`
(at least one login header arrived and every one is a well-formed login, so a combined value such as
two logins joined by a comma is false). No member is
ever a login or a probe value. It does not change admission, and `whoami` is unchanged.

`sharing_entry(access, state, last_request, socket)` is the owner's `sharing` view member; `last_request` is
the latest `reading` or None and `socket` the bound guest socket path or None. `state` is one of
`SERVE_STATES`: `off` (no tailnet is configured), `unchecked` (the Serve status was not read),
`not_proxying` (it was read and does not proxy the tailnet name on 443 to the guest socket) and
`serving`. `serve_state(status, tailnet, guest_socket)` reads the parsed `tailscale serve status
--json` ServeConfig, `{"Web": {"<tailnet>:443": {"Handlers": {"/": {"Proxy":
"unix:<guest socket>"}}}}}`, and treats any other shape, or a proxy that is not exactly
`unix:` plus the bound socket path, as not proxying.

`serve_reader(path)` is the reader of that status: a callable that runs this host's Tailscale client
at `path` as `serve status --json` (no shell, no other argument, `SERVE_TIMEOUT_SECONDS`) and returns
the parsed JSON, or None on a nonzero exit, output that is not JSON, an `OSError` or a timeout; it
never raises.

`parse_tailnet`, `parse_colleague` and `parse_removal` read the owner's write bodies as strict
JSON (a duplicate key, a non-object or an extra or missing key is refused) and raise
`ValueError` on a malformed body. Whether each project of a colleague is registered is checked by
the service, which raises `Refused` for a write refused on its merits.
"""

import ctypes
import errno
import json
import os
import re
import stat
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.console.capacity import EMPTY
from agent_tools.console.event_log import (
    SHARING_COLLEAGUE, SHARING_REMOVED, SHARING_TAILNET, Event)
from agent_tools.console.view import project_for

OWNER_ONLY_INPUTS: Mapping[str, object] = MappingProxyType({
    "capacity": None, "digest": None, "spend": None, "activation": None,
    "activation_run": None, "signin_runs": None, "accounts_added": (), "pin": None,
    "pin_launches": (), "registration": None, "adoption_items": (), "retry_items": (),
    "apply_items": (), "confirm_items": (), "trust_items": (), "failure_items": (),
    "project_questions": None, "sharing": None})
PASSED_INPUTS = frozenset({"now_ms", "managers", "nudges", "looked"})
FILTERED_INPUTS = frozenset({"states", "records", "health", "sessions", "deliveries", "sprints",
                             "pending", "movement", "owner_notices"})
SERVE_TIMEOUT_SECONDS = 15.0
SERVE_STATES = ("off", "unchecked", "not_proxying", "serving")
DOOR_WIDER = "door_wider"
FOLDER_MODE = 0o700
SOCKET_MODE = 0o600

LOGIN_HEADER = "Tailscale-User-Login"
PROBE_HEADER = "X-Console-Probe"
PROBE_LOGIN = "forged-probe@example.invalid"

LOCAL_HOST = "localhost"
FORWARDED_HOST_HEADER = "X-Forwarded-Host"

SHARING_OFF_TEXT = "Sharing is off on this console."
HOST_TEXT = "This console is shared only at its tailnet name."
NOT_SHARED_TEXT = "This console is not shared with you. Ask its owner to add your Tailscale login."
OWNER_ONLY_TEXT = "Only the console's owner can do that."
OWNER_PORT_TEXT = ("This is the console owner's port. "
                   "Point Tailscale Serve at the console's guest socket.")

HOST_FORMS = ("exact", "with_port", "other", "none")
REASON_CODES: Mapping[str, str] = MappingProxyType({
    SHARING_OFF_TEXT: "sharing_off", HOST_TEXT: "host", NOT_SHARED_TEXT: "not_shared"})
READING_MEMBERS = ("admitted", "forwarded_for", "forwarded_host", "forwarded_host_form",
                   "forwarded_hosts", "host", "host_local", "hosts", "login_headers", "login_valid",
                   "probe", "probe_login_arrived", "reason")

TAILNET_MAX = 253
LOGIN_MAX = 254
PROJECTS_MAX = 50
PROJECT_MAX = 200

_TAILNET = re.compile(r"([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.){2,}ts\.net")
_LOGIN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+")
_HOST = re.compile(r"[A-Za-z0-9.-]{1,253}(:[0-9]{1,5})?")


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


def admit(access: Access, hosts: Sequence[str], forwarded_hosts: Sequence[str],
          logins: Sequence[str]) -> tuple[str | None, str | None]:
    if access.tailnet is None:
        return None, SHARING_OFF_TEXT
    if len(hosts) != 1 or hosts[0].lower() != LOCAL_HOST:
        return None, HOST_TEXT
    if len(forwarded_hosts) != 1 or forwarded_hosts[0].lower() != access.tailnet:
        return None, HOST_TEXT
    if len(logins) != 1:
        return None, NOT_SHARED_TEXT
    login = normal_login(logins[0])
    if login is None or login not in access.colleagues:
        return None, NOT_SHARED_TEXT
    return login, None


def reading(access: Access, hosts: Sequence[str], forwarded_hosts: Sequence[str],
            logins: Sequence[str], forwarded: Sequence[str], probes: Sequence[str]) -> dict:
    """What one guest-door request showed, for the owner's `sharing.last_request`; never a login."""
    _, text = admit(access, hosts, forwarded_hosts, logins)
    host = hosts[0] if len(hosts) == 1 else None
    one = forwarded_hosts[0] if len(forwarded_hosts) == 1 else None
    if one is None:
        form = "none"
    elif access.tailnet is not None and one.lower() == access.tailnet:
        form = "exact"
    elif access.tailnet is not None and one.lower() == access.tailnet + ":443":
        form = "with_port"
    else:
        form = "other"
    return {"admitted": text is None,
            "forwarded_for": bool(forwarded),
            "forwarded_host": one if one is not None and _HOST.fullmatch(one) else None,
            "forwarded_host_form": form,
            "forwarded_hosts": len(forwarded_hosts),
            "host": host if host is not None and _HOST.fullmatch(host) else None,
            "host_local": host is not None and host.lower() == LOCAL_HOST,
            "hosts": len(hosts),
            "login_headers": len(logins),
            "login_valid": bool(logins) and all(normal_login(value) is not None for value in logins),
            "probe": len(probes) == 1 and normal_login(probes[0]) == PROBE_LOGIN,
            "probe_login_arrived": any(normal_login(value) == PROBE_LOGIN for value in logins),
            "reason": None if text is None else REASON_CODES[text]}


def owner_port_refusal(names: Iterable[str]) -> str | None:
    for name in names:
        lowered = name.lower()
        if lowered.startswith("tailscale-") or lowered == "x-forwarded-for":
            return OWNER_PORT_TEXT
    return None


def whoami(hosts: Sequence[str], forwarded_hosts: Sequence[str], logins: Sequence[str],
           forwarded: Sequence[str], probes: Sequence[str]) -> dict:
    return {"host": hosts[0] if len(hosts) == 1 else None,
            "hosts": len(hosts),
            "forwarded_host": forwarded_hosts[0] if len(forwarded_hosts) == 1 else None,
            "forwarded_hosts": len(forwarded_hosts),
            "login_headers": len(logins),
            "forwarded_for": bool(forwarded),
            "probe_login_arrived": len(probes) == 1 and probes[0] in logins}


def scoped(inputs: Mapping[str, object], projects: frozenset[str]) -> dict:
    for name in inputs:
        if name not in FILTERED_INPUTS | PASSED_INPUTS | OWNER_ONLY_INPUTS.keys():
            raise ValueError(f"unscoped view input {name}")
    result: dict = {name: inputs[name] for name in PASSED_INPUTS if name in inputs}
    result.update(OWNER_ONLY_INPUTS)
    states = [state for state in inputs.get("states") or () if state.project_id in projects]
    kept = {state.project_id: state for state in states}
    sessions = [session for session in inputs.get("sessions") or ()
                if session.repo is not None and project_for(session.repo, kept) is not None]
    session_ids = {session.session_id for session in sessions}

    def keep(name: str, wanted) -> None:
        folded = inputs.get(name)
        if name in inputs:
            result[name] = None if folded is None else {
                key: value for key, value in folded.items() if wanted(key, value)}

    result["states"] = states
    result["sessions"] = sessions
    keep("records", lambda key, _: key[0] in projects)
    keep("health", lambda key, _: key in projects)
    keep("movement", lambda key, _: key in projects)
    keep("owner_notices", lambda key, _: key in projects)
    keep("sprints", lambda _, value: value.project_id in projects)
    keep("pending", lambda _, value: value.project_id in projects)
    keep("deliveries", lambda _, value: value.session_id in session_ids)
    return result


def scrub(view: Mapping) -> dict:
    scrubbed = {name: member for name, member in view.items() if name != "sharing"}
    scrubbed.update({"unmanaged": [], "profile_sessions": {}, "signin_runs": {},
                     "accounts_added": [], "pin": None, "pin_launches": [],
                     "registration": None, "digest": None, "activation": None, "spend": None,
                     "capacity": dict(EMPTY)})
    return scrubbed


def picture_ids(view: object) -> frozenset[str]:
    found: set[str] = set()

    def walk(node: object, pictures: bool) -> None:
        if isinstance(node, Mapping):
            if pictures:
                identifier = node.get("id")
                if isinstance(identifier, str):
                    found.add(identifier)
            for key, member in node.items():
                if key == "pictures" and isinstance(member, list):
                    for picture in member:
                        walk(picture, True)
                else:
                    walk(member, False)
        elif isinstance(node, list):
            for member in node:
                walk(member, False)

    walk(view, False)
    return frozenset(found)


def door_refusal(folder: os.stat_result | None, sock: os.stat_result | None,
                 owner_uid: int) -> str | None:
    if (folder is not None and stat.S_ISDIR(folder.st_mode) and folder.st_uid == owner_uid
            and stat.S_IMODE(folder.st_mode) & ~FOLDER_MODE == 0
            and sock is not None and stat.S_ISSOCK(sock.st_mode) and sock.st_uid == owner_uid
            and stat.S_IMODE(sock.st_mode) & ~SOCKET_MODE == 0):
        return None
    return DOOR_WIDER


ACL_TYPE_EXTENDED = 0x100
ACL_FIRST_ENTRY, ACL_NEXT_ENTRY = 0, -1
ACL_EXTENDED_ALLOW = 1


def acl_grants(path: str) -> bool:
    """Whether the macOS ACL of `path` (not what a symlink names) has an allow entry."""
    libc = ctypes.CDLL(None, use_errno=True)
    libc.acl_get_link_np.argtypes = [ctypes.c_char_p, ctypes.c_int]
    libc.acl_get_link_np.restype = ctypes.c_void_p
    libc.acl_get_entry.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
    libc.acl_get_entry.restype = ctypes.c_int
    libc.acl_get_tag_type.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    libc.acl_get_tag_type.restype = ctypes.c_int
    libc.acl_free.argtypes = [ctypes.c_void_p]
    libc.acl_free.restype = ctypes.c_int
    ctypes.set_errno(0)
    acl = libc.acl_get_link_np(os.fsencode(path), ACL_TYPE_EXTENDED)
    if not acl:
        code = ctypes.get_errno()
        if code in (0, errno.ENOENT):
            return False
        raise OSError(code, os.strerror(code), path)
    try:
        entry, which = ctypes.c_void_p(), ACL_FIRST_ENTRY
        while libc.acl_get_entry(acl, which, ctypes.byref(entry)) == 0:
            which = ACL_NEXT_ENTRY
            tag = ctypes.c_int()
            if libc.acl_get_tag_type(entry, ctypes.byref(tag)) != 0:
                raise OSError(errno.EIO, "an ACL entry has no readable tag", path)
            if tag.value == ACL_EXTENDED_ALLOW:
                return True
        return False
    finally:
        libc.acl_free(acl)


def acl_reader_for(platform: str) -> Callable[[str], bool] | None:
    return acl_grants if platform == "darwin" else None


def serve_state(status: object, tailnet: str | None, guest_socket: str | None) -> str:
    if tailnet is None:
        return "off"
    if status is None:
        return "unchecked"
    node: object = status
    for step in ("Web", f"{tailnet}:443", "Handlers", "/", "Proxy"):
        node = node.get(step) if isinstance(node, Mapping) else None
    if isinstance(guest_socket, str) and guest_socket and node == "unix:" + guest_socket:
        return "serving"
    return "not_proxying"


def serve_reader(path: str, run: Callable[..., subprocess.CompletedProcess] = subprocess.run
                 ) -> Callable[[], object | None]:
    def read() -> object | None:
        try:
            done = run([path, "serve", "status", "--json"], capture_output=True, text=True,
                       timeout=SERVE_TIMEOUT_SECONDS, check=False)
            if done.returncode != 0:
                return None
            return json.loads(done.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError, RecursionError):
            return None

    return read


def sharing_entry(access: Access, state: str, last_request: Mapping | None = None,
                  socket: str | None = None) -> dict:
    return {"tailnet": access.tailnet,
            "colleagues": [{"login": login, "projects": sorted(access.colleagues[login])}
                           for login in sorted(access.colleagues)],
            "state": state,
            "last_request": last_request,
            "socket": socket}
