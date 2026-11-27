"""The guest door's policy (#1237): the access list, admission, scoping, the owner-port rule and the probe.

A guest is a listed colleague who reaches the console through Tailscale Serve, which proxies to the
console's guest socket (ADR-console-066, ADR-console-077). This module holds the pure rules only; `service.py` documents the
routes and applies them. It uses the standard library alone.

The access list is kept in the event log as three kinds (`event_log` records them and keeps the
newest rows in force through the retention pass): `sharing.tailnet` (`{"shared"}`: the switch, true
for on and false for off; a legacy `{"tailnet": <valid name>}` row still folds to on and the name it
carries is never used), `sharing.colleague` (`{"login", "projects"}`: the login's whole project
list) and `sharing.removed` (`{"login"}`). `access_list` folds rows in sequence order on top of a
previous `Access(shared, colleagues)` and never mutates it. A switch row with a `shared` member is
on only when that member is exactly `True`; a row without one is on only when its `tailnet` is a
valid name; a payload that is not an object is off. A colleague row whose login is not already in
normal form (lowercase) or whose projects are not a non-empty list of non-empty strings removes
that login (fail closed); a row whose login is not a string is ignored.

The tailnet name the door admits is never configured and never stored: it is read from this host's
Tailscale client (ADR-console-078). `self_name(status)` takes the parsed `tailscale status
--json` and returns `Self.DNSName` with exactly one trailing dot removed and lowercased, only when
the raw string is ASCII (checked before any case change, because `str.lower` maps U+212A to an
ASCII `k`) and the result is exactly `<host>.<tailnet>.ts.net`, two labels before `.ts.net` and no
more (a name with an extra label admits nothing); every other shape is None.
The owner's access-list writes (#1237) are three page writes, `POST /api/share-tailnet`, `POST
/api/share-colleague` and `POST /api/share-remove` (`SHARE_TAILNET_PATH`, `SHARE_COLLEAGUE_PATH`,
`SHARE_REMOVE_PATH`), each behind the `_page_write` guard and then `_json_body(MAX_SHARE_BYTES)`
(4096; 411, 415, 411, 413 as every JSON page write). Their bodies are the exactly-keyed objects
`guest.parse_sharing` (`{"shared": true|false}`), `guest.parse_colleague`
(`{"login", "projects"}`) and `guest.parse_removal` (`{"login"}`) read; a body they refuse is `400`
`bad sharing`, `bad colleague` or `bad removal`. A write refused on its merits (`guest.Refused`:
a project that is not registered, a login that is not listed) is one stderr line `console:
share_refused <reason>` and `409` with the reason; any other failure is `console: share_failed
<Type>: <message>` and `500` `share failed`; no stderr line carries a login or a tailnet name.
Success appends one row under the console's ingest lock, applies it and answers an empty `204`:
`ConsoleService.set_sharing` a `sharing.tailnet` row (`{"shared"}`), `set_colleague` a `sharing.colleague` row
that replaces the login's whole project list, `remove_colleague` a `sharing.removed` row. A
refusal appends nothing and publishes nothing. Each write publishes, and the guest stream
re-admits on every publish, so a removed colleague's open stream and a switched-off one's end before any further frame
(a moved or gone name ends one on the Serve thread's publish), and the next guest request is `403`.

`status_reader(path)` is the reader of that status: a callable that runs the client at `path` as
`status --json` (no shell, no other argument, `SERVE_TIMEOUT_SECONDS`) and returns the parsed JSON,
or None on a nonzero exit, output that is not JSON, an `OSError` or a timeout; it never raises. The
name is kept in memory only, never in the log and never printed. The same status gives this host's own
addresses (ADR-console-079): `own_addresses(status)` is the set of `Self.TailscaleIPs` addresses, an
IPv4-mapped IPv6 address as its IPv4 address, and is empty unless that member is a non-empty list of
strings that all parse as addresses without a zone; they are kept in memory only, never in the log, the
reading, a view or stderr. `Policy(access, name, addresses)` is one immutable snapshot of the switch,
the list, the read name and the own addresses (`NO_POLICY` is off with no name and no address; a change
of addresses alone revokes nothing and changes no admission, but the service drops the reading and the
`other_device_seen` flag judged under the old ones); a request is judged by one policy.
`Snapshot(policy, views, pictures, revoked)` carries with that policy
the colleagues' scoped views, their picture ids and `revoked`, a count the service raises each time
the read name changes or sharing goes off, so a request is answered from the one snapshot that
admitted it and an open stream can tell a revocation that came and went while it was blocked.

`admit(access, name, hosts, forwarded_hosts, logins)` returns `(login, None)` for an admitted request
and `(None, text)` for a refused one (ADR-console-077, ADR-console-078). The checks run in this
order: sharing is off (`SHARING_OFF_TEXT`); the name is unread (`NAME_UNREAD_TEXT`); the request
carries exactly one `Host` that, lowercased, is `LOCAL_HOST` (`localhost`, no port) and exactly one
`X-Forwarded-Host` (`FORWARDED_HOST_HEADER`) that, lowercased, is the read name exactly, with no port
form (`HOST_TEXT`); it carries exactly one login header (`LOGIN_HEADER`) whose normal form is a
listed colleague (`NOT_SHARED_TEXT`). No text names a project or echoes a login or a host. Each text
is answered as `403 text/plain` with a trailing newline.

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
kept session; `prompted_sprints` (the ids of sprints with an open permission card, never the card) keeps
the ids of a kept sprint, so a guest's view raises no held-sprint card for a sprint the owner already has a
card for; `engine_runs` keeps the runs of a listed project, and `engine_lines` is reset so a guest
sees no engine run line while its sprint reads their movement. `PASSED_INPUTS` pass as given and every `OWNER_ONLY_INPUTS` key is reset to its listed
empty value whether or not it was given. The input set is closed: a key of none of the three sets
is refused with `ValueError("unscoped view input <name>")`, so a view input added later must be
classified before a guest can see it. `scrub(view, pool, sprint_accounts)` then drops what the inputs
cannot: the `sharing` member, the unmanaged list, the per-profile session counts, the sign-in,
account, pin and registration members, the digest, the activation line, the spend view and the
capacity profiles, and puts in their place the `pool` member (#1341, ADR-console-086). `pool_view`
builds it from the owner's capacity view: `POOL_MEMBERS` are `state`, `tight`, `all_out`,
`resumes_at`, `no_reading` and `accounts`; each account row carries exactly `ACCOUNT_MEMBERS`: a
neutral `label` (`Account <n>`, or `yours` on the page of a colleague holding a profile of that
account, ADR-console-087), the account's `number` (an `int`, the `<n>` of `Account <n>`, and
the number of a `yours` row's account too: how a guest names an account in a write, #1345), its
`ident` (a `yours` row's token, `own_tokens` of the account's profiles' recorded directory identities, each with its
profile's sign-in generation, through `account_token`, else None: a number is recycled and a profile can be signed in
again as another account, so a destructive write sends both and acts only when the token still names his account), `state`, the percent left and reset of the week and the session,
`next_reset`, `out_until` and `in_use` (not signed out and not excluded). One row stands for one
account: a profile whose `duplicate_of` is set (signed in to an address another profile counts) has
no row and shares its account's label. `tight`, `all_out`, `resumes_at` and `no_reading` are the
capacity view's own; `state` is None while no row in use has a reading, else `out`, `tight` or
`fine`. A number belongs to an account, not a profile (`account_numbers`): the accounts that hold a
number in the previous numbering keep it, those with an address first, then by their smallest
profile name, and every other account takes the smallest positive integer none holds, so an alias,
a pin or a removal never moves a label. When several profiles of one account hold numbers (a profile
numbered before it signed in, then signed in to an address another already holds), the number of a
profile in `established` (those that had an address at the previous numbering) is kept over a
smaller one, so the established account and its running sprints keep their label. When several
accounts claim one number (an alias moved from one account to another, or a profile left a shared
account for a new address), it goes to the account whose profiles holding it kept their address
(`established` given as a Mapping of profile to the address it had), then to the one with more
holders, then to the one whose counted profile held it, then by the order above; the others keep
another number they held or take a free one. The numbering lives in `NUMBERS_FILE`, beside the event
log (`read_numbers`, `read_retired`, `write_numbers`; an unreadable file numbers afresh). The file
holds the numbers and, for each running sprint whose profile was removed, the number and address
its sprint keeps while another profile still holds that address, with the removed profile's name
(`retired`, by sprint id, so a restart keeps the label and a profile name given to another account
later never moves it); once no profile holds the address, or none did, the entry stays with a None
number, so the sprint is detached from the name for good and has no label. The entry ends when the
sprint's manager runs on another profile than the one named in it, and the sprint is then labelled
by that profile's account.
`sprint_labels` gives the label of the account each running sprint's manager is on, a `retired` one
first (a detached one has none), and `scrub` adds it as `account_label` to
every sprint node (None for a sprint it does not know) and replaces a sprint's `stop_text` with
`STOP_FAILED_TEXT`, and each `unstopped` item's `text` with `UNSTOPPED_TEXT`, which carry no reason: a stop failure's reason can name a profile. A stalled sprint's `manager_text` is likewise cut to `STALLED_TEXT` and the stall card's `last_reason` becomes `MANAGER_REASON_TEXT`, since a recorded stall can read `<profile> is being removed` (a failed start's text is already `manager.plain_reason`, never the reason). `scrub` also sets `own_signin`, a copy of its argument or None:
the run of the profiles the guest added that his page shows, the newest running one else the newest (`own_signin`: `state`, `at`, `attempt`, never
a profile name). `profile_labels(numbers, mine)` and `retired_labels(retired, numbers, mine)` apply
the `yours` rule to a sprint's label as `pool_view` does to a row's, so every profile of a
colleague's account, counted or duplicate, reads `yours` for him. No profile name, address,
organisation or
proxy account id reaches a guest, and `spend` stays None: money is the owner's bill, and a spend
per account or per project would show work on projects the colleague is not listed for.
`picture_ids(view)` is the set of every picture id in the scoped view, found by walking every list
stored under a key `pictures`: a picture read is answered to a guest only for an id this walk
finds in that guest's scoped view.

`reading(access, name, hosts, forwarded_hosts, logins, forwarded, probes)` is what one guest-door request
showed, for the owner's `sharing.last_request` (`READING_MEMBERS`): whether it was admitted and, if
not, the `REASON_CODES` code (`sharing_off`, `name_unread`, `host`, `not_shared`); how many `Host`, `X-Forwarded-Host`
and login headers arrived; each of the `Host` and the forwarded host only when exactly one arrived and
it is one of the names the door knows (`localhost`, the read name, or the read name with `:443`, case
aside); any other value is recorded by its `forwarded_host_form` or `host_local` alone and never by its
text, so no address in any spelling, and no name built on one, is ever kept (no check of a client-sent
name can tell every spelling of an address from a name);
`host_local` (exactly one `Host`, `localhost` lowercased); and the
`forwarded_host_form` (`HOST_FORMS`: `exact` the read name, `with_port` the name with `:443`,
`other`, `none`) of the forwarded host; whether
`X-Forwarded-For` arrived; `probe` (exactly one probe header carrying `PROBE_LOGIN`) and
`probe_login_arrived` (`PROBE_LOGIN` arrived as a login, whatever the probe header said); `login_valid`
(at least one login header arrived and every one is a well-formed login, so a combined value such as
two logins joined by a comma is false); and `client` (`CLIENT_FORMS`, `client_of(forwarded, own)`,
ADR-console-079; a value is trimmed of spaces and tabs only): `this_host` when exactly one `X-Forwarded-For` value is one of this host's own
addresses, `other_device` when it is one address and not one of them, and `unknown` otherwise (none,
more than one header, a list, a value that is no address, one carrying an IPv6 zone, or no own address
read); an IPv4-mapped IPv6 value compares as its IPv4 address. Only that comparison is kept, never an
address. No member is ever a login, a probe value or an address. It does not change admission. `whoami` is unchanged; the service
refuses the probe `NAME_UNREAD_TEXT` when sharing is on and no name is read.

`sharing_entry(access, name, state, last_request, socket, other_device_seen)` is the owner's `sharing`
view member (`shared`, `tailnet` the read name or None, `colleagues`, `state`, `last_request`,
`socket`, `other_device_seen`); `last_request` is the latest `reading` or None, `socket` the bound
guest socket path or None and `other_device_seen` whether any reading since this service began had
`client` `other_device` (memory only, false after a restart; ADR-console-079).
`state` is one of `SERVE_STATES`: `off` (sharing is off), `unreadable` (sharing is on and no name is
read), `unchecked` (the Serve status was not read), `not_proxying` (it was read and does not proxy
the read name on 443 to the guest socket) and `serving`. `serve_state(shared, name, status,
guest_socket)` reads the parsed `tailscale serve status --json` ServeConfig, `{"Web":
{"<name>:443": {"Handlers": {"/": {"Proxy": "unix:<guest socket>"}}}}}`, and treats any other shape,
or a proxy that is not exactly `unix:` plus the bound socket path, as not proxying.

`serve_reader(path)` is the reader of that status: a callable that runs this host's Tailscale client
at `path` as `serve status --json` (no shell, no other argument, `SERVE_TIMEOUT_SECONDS`) and returns
the parsed JSON, or None on a nonzero exit, output that is not JSON, an `OSError` or a timeout; it
never raises.

A guest's writes (#1263) are decided by `write_refusal(policy, actor, project_id)`, where `actor` is
a `GuestActor` (the login and the read tailnet name the request was admitted under). The checks run in
this order and the first that fails gives its text: sharing is off (`SHARING_OFF_TEXT`); no tailnet
name is read from this host's Tailscale client (`NAME_UNREAD_TEXT`); the name read from this host's
Tailscale client is not the one the request was admitted under (`HOST_TEXT`); the login is no longer
listed (`NOT_SHARED_TEXT`); the project is not on the login's list (`NOT_YOUR_PROJECT_TEXT`);
otherwise None. The service adds a last check under its ingest lock: the actor's `epoch` is the count of
revocations (`revokes`: sharing switched off, a colleague or one of their projects removed, or the read
name changed) when its request was admitted, and a write whose epoch is no longer the current count is
refused with `REVOKED_TEXT` even when sharing, the name, the login and the project look as they did, so a
write admitted before a revocation never lands after the access came back. `Snapshot.epoch` carries the
count the admitting snapshot was published with. `steer_refusal(login, started_by)` is None
exactly when the sprint was started by that login (`NOT_YOUR_SPRINT_TEXT`; a sprint with no starter
is the owner's). A question that carries a before-and-after pair or a `look` is a look before merge
and stays the owner's (`is_look` for the pair, `OWNER_LOOK_TEXT`; ADR-console-074), as does a question the manager marked `owner_only`
(`OWNER_ONLY_TEXT`); tracker items (release confirmations, paid approvals,
production holds) are never steerable. The service answers a write refused on these merits as
`409`. No text names a project or a login.

Three more guest writes (#1343, ADR-console-087), `POST /api/guest-account`, `/api/guest-signin-code` and
`/api/guest-signin-cancel`, let a listed colleague add his own account and sign it in. The first four checks of
`write_refusal` are `account_refusal(policy, actor)`, which they use alone (sharing off, no name read, another
name, login not listed). The add takes `{"consent": true}` and at most the `attempt` the page shows with no link yet: without the tick it is
refused with `CONSENT_TEXT` before anything is created, and with an attempt it creates and starts nothing, only handing
out that live sign-in's link (any other attempt is `NO_OWN_SIGNIN_TEXT`). The service picks the profile: the colleague's own live
sign-in (the newest, the one his page shows), else one of his own profiles that is not signed in, else a new
`colleague-<n>` it names itself; no body names a profile, the code and the cancel carry the attempt the add
answered and act on that attempt only, and no sign-in of a profile that is not his own is ever started, passed a code or
cancelled. A refusal is read by a guest only as one of the fixed texts `CONSENT_TEXT`, `NO_OWN_SIGNIN_TEXT`,
`ACCOUNT_BUSY_TEXT`, `ACCOUNT_UNAVAILABLE_TEXT`, `NOT_SHARED_TEXT`, `REVOKED_TEXT`, `NOT_YOUR_ACCOUNT_TEXT`
(the number names no account of his) or `CHANGE_UNAVAILABLE_TEXT` (signing out or removing is not available on this
host; `account_reason` names them `not_yours` and `unavailable`) (`account_text` maps any
other text, such as one that names a profile, to `ACCOUNT_BUSY_TEXT`). No answer names a profile, a login, a
code or the client's output.

`mark_steer(view, login)` returns a copy of a scrubbed guest view in which every sprint mapping
gains `steer` (started by that login) and every `inbox.open` and `inbox.answered` item gains `steer`
(a brief or a question started by that login that is neither a look (a before-and-after pair or a
`look`, ADR-console-074) nor `owner_only`). The marks are the server's and
are applied to a scrubbed guest view only; it adds the login nowhere and never mutates its argument.
A message's `action_text` that is `NUDGE_ACTION_TEXT` reads `NUDGE_ACTION_TEXT_GUEST` ("Tell the
manager again.") in the copy: a colleague cannot drop a sprint, so the line offers no drop.

`parse_sharing` (`{"shared": true|false}`, nothing else), `parse_colleague` and `parse_removal` read the owner's write bodies as strict
JSON (a duplicate key, a non-object or an extra or missing key is refused) and raise
`ValueError` on a malformed body. Whether each project of a colleague is registered is checked by
the service, which raises `Refused` for a write refused on its merits.
"""

import ctypes
import errno
import ipaddress
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.console.capacity import EMPTY
from agent_tools.console.event_log import (
    LOGIN_MAX, SHARING_COLLEAGUE, SHARING_REMOVED, SHARING_TAILNET, Event, normal_login)
from agent_tools.console.sprints import (
    NUDGE_ACTION_TEXT, STALLED_TEXT, STARTED, SprintState, ended_at, is_look)
from agent_tools.console.view import project_for

OWNER_ONLY_INPUTS: Mapping[str, object] = MappingProxyType({
    "capacity": None, "digest": None, "spend": None, "activation": None,
    "activation_run": None, "signin_runs": None, "accounts_added": (), "pin": None,
    "pin_launches": (), "registration": None, "adoption_items": (), "release_items": (), "prompt_items": (), "retry_items": (),
    "apply_items": (), "confirm_items": (), "trust_items": (), "failure_items": (),
    "project_questions": None, "sharing": None, "engine_lines": False,
    "moves": None, "host_alerts": None})
PASSED_INPUTS = frozenset({"now_ms", "managers", "nudges", "looked"})
FILTERED_INPUTS = frozenset({"states", "records", "health", "sessions", "deliveries", "sprints",
                             "pending", "movement", "owner_notices", "engine_runs", "issue_titles",
                             "prompted_sprints"})
SERVE_TIMEOUT_SECONDS = 15.0
SERVE_STATES = ("off", "unreadable", "unchecked", "not_proxying", "serving")
DOOR_WIDER = "door_wider"
FOLDER_MODE = 0o700
SOCKET_MODE = 0o600

LOGIN_HEADER = "Tailscale-User-Login"
PROBE_HEADER = "X-Console-Probe"
PROBE_LOGIN = "forged-probe@example.invalid"

LOCAL_HOST = "localhost"
FORWARDED_HOST_HEADER = "X-Forwarded-Host"

SHARING_OFF_TEXT = "Sharing is off on this console."
NAME_UNREAD_TEXT = "This console cannot read its tailnet name, so it lets nobody in."
HOST_TEXT = "This console is shared only at its tailnet name."
NOT_SHARED_TEXT = "This console is not shared with you. Ask its owner to add your Tailscale login."
OWNER_ONLY_TEXT = "Only the console's owner can do that."
NUDGE_ACTION_TEXT_GUEST = "Tell the manager again."
NOT_YOUR_PROJECT_TEXT = "That project is not shared with you."
NOT_YOUR_SPRINT_TEXT = "You can steer only the sprints you started."
OWNER_LOOK_TEXT = "Only the console's owner approves how a change looks before it merges."
REVOKED_TEXT = "Your access changed while you were sending that. Reload the page and try again."
CONSENT_TEXT = "Tick that you agree before you sign in."
NO_OWN_SIGNIN_TEXT = "No sign-in of yours is running."


def colleague_signin_text(profile: str, login: str) -> str:
    """The owner's refusal to start a sign-in of a profile a colleague added (#1361, ADR-console-087)."""
    return f"{profile} is {login}'s account, so only {login} can sign it in. You can sign it out or remove it."
ACCOUNT_BUSY_TEXT = "That cannot be done right now. Try again in a moment."
NOT_YOUR_ACCOUNT_TEXT = "That account is not yours."
CHANGE_UNAVAILABLE_TEXT = "Signing out or removing an account is not available on this host."
ACCOUNT_UNAVAILABLE_TEXT = "Adding an account is not available on this host."
OWNER_PORT_TEXT = ("This is the console owner's port. "
                   "Point Tailscale Serve at the console's guest socket.")

HOST_FORMS = ("exact", "with_port", "other", "none")
THIS_HOST = "this_host"
OTHER_DEVICE = "other_device"
UNKNOWN_CLIENT = "unknown"
CLIENT_FORMS = (THIS_HOST, OTHER_DEVICE, UNKNOWN_CLIENT)
REASON_CODES: Mapping[str, str] = MappingProxyType({
    SHARING_OFF_TEXT: "sharing_off", NAME_UNREAD_TEXT: "name_unread", HOST_TEXT: "host",
    NOT_SHARED_TEXT: "not_shared"})
READING_MEMBERS = ("admitted", "client", "forwarded_for", "forwarded_host", "forwarded_host_form",
                   "forwarded_hosts", "host", "host_local", "hosts", "login_headers", "login_valid",
                   "probe", "probe_login_arrived", "reason")

TAILNET_MAX = 253
PROJECTS_MAX = 50
PROJECT_MAX = 200

_TAILNET = re.compile(r"([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.){2,}ts\.net")
_SELF_NAME = re.compile(r"([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.){2}ts\.net")


class Refused(Exception):
    """A write refused on its merits (an unregistered project, a name that cannot be kept)."""


@dataclass(frozen=True)
class Access:
    shared: bool
    colleagues: Mapping[str, frozenset[str]]


NO_ACCESS = Access(False, MappingProxyType({}))


@dataclass(frozen=True)
class Policy:
    """One immutable snapshot of the switch, the list and the name read from Tailscale."""
    access: Access
    name: str | None
    addresses: frozenset = frozenset()


NO_POLICY = Policy(NO_ACCESS, None)


@dataclass(frozen=True)
class Snapshot:
    """One policy with the views and picture ids derived under it, and the revocation count."""
    policy: Policy
    views: Mapping[str, bytes]
    pictures: Mapping[str, frozenset[str]]
    revoked: int
    epoch: int = 0


NO_SNAPSHOT = Snapshot(NO_POLICY, MappingProxyType({}), MappingProxyType({}), 0)


@dataclass(frozen=True)
class GuestActor:
    """Who acts on the guest port: the login, the tailnet name and the revocation epoch the request was admitted under.

    `epoch` is the service's count of revocations at admission (None for a caller that has no admission, which is
    never checked); a write whose epoch is not the service's current one is refused with `REVOKED_TEXT`.
    """

    login: str
    tailnet: str
    epoch: int | None = None


def valid_tailnet(text: object) -> bool:
    return (isinstance(text, str) and len(text) <= TAILNET_MAX
            and _TAILNET.fullmatch(text) is not None)


def self_name(status: object) -> str | None:
    node: object = status
    for step in ("Self", "DNSName"):
        node = node.get(step) if isinstance(node, Mapping) else None
    if not isinstance(node, str) or not node.isascii():
        return None
    name = node.removesuffix(".").lower()
    return name if valid_tailnet(name) and _SELF_NAME.fullmatch(name) is not None else None


_OWS = " \t"  # HTTP optional whitespace; no other character pads a field value


def _address(text: object) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """One address from `text`, an IPv4-mapped one as its IPv4 address; `ValueError` for a zone or no address."""
    if not isinstance(text, str):
        raise ValueError("not a string")
    found = ipaddress.ip_address(text.strip(_OWS))
    if isinstance(found, ipaddress.IPv6Address):
        if found.scope_id is not None:
            raise ValueError("zoned address")
        if found.ipv4_mapped is not None:
            return found.ipv4_mapped
    return found


def _kept_host(value: str, allowed: Sequence[str]) -> bool:
    """Whether a host value is one of the `allowed` names, ignoring case: the only forms the reading keeps (ADR-console-079).

    Anything else is recorded by its form alone, never by its text, because no check of a client-sent
    name can tell every spelling of an address from a name (hex, octal, integer, padded or unpadded dash forms).
    """
    return value.lower() in allowed


def own_addresses(status: object) -> frozenset:
    """This host's own tailnet addresses from the parsed `status --json`; empty unless all of them read."""
    node: object = status
    for step in ("Self", "TailscaleIPs"):
        node = node.get(step) if isinstance(node, Mapping) else None
    if not isinstance(node, list) or not node:
        return frozenset()
    try:
        return frozenset(_address(member) for member in node)
    except ValueError:
        return frozenset()


def client_of(forwarded: Sequence[str], own: frozenset) -> str:
    """Whether the one forwarded address is this host's, another device's or unknown; never the address."""
    if len(forwarded) != 1 or not own:
        return UNKNOWN_CLIENT
    try:
        found = _address(forwarded[0])
    except ValueError:
        return UNKNOWN_CLIENT
    return THIS_HOST if found in own else OTHER_DEVICE


def _switch(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    if "shared" in payload:
        return payload["shared"] is True
    return valid_tailnet(payload.get("tailnet"))


def _projects_in_force(projects: object) -> bool:
    return (isinstance(projects, list) and bool(projects)
            and all(isinstance(project, str) and project for project in projects))


def access_list(events: Iterable[Event], previous: Access = NO_ACCESS) -> Access:
    shared = previous.shared
    colleagues = dict(previous.colleagues)
    for event in events:
        payload = event.payload
        if event.kind == SHARING_TAILNET:
            shared = _switch(payload)
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
    return Access(shared, MappingProxyType(colleagues))


def _object(body: bytes, members: set[str]) -> dict:
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except RecursionError as error:
        raise ValueError("the body is nested too deeply") from error
    if not isinstance(value, dict) or set(value) != members:
        raise ValueError(f"the body must be an object of exactly {', '.join(sorted(members))}")
    return value


def parse_sharing(body: bytes) -> bool:
    shared = _object(body, {"shared"})["shared"]
    if type(shared) is not bool:
        raise ValueError("shared must be true or false")
    return shared


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


def admit(access: Access, name: str | None, hosts: Sequence[str], forwarded_hosts: Sequence[str],
          logins: Sequence[str]) -> tuple[str | None, str | None]:
    if not access.shared:
        return None, SHARING_OFF_TEXT
    if name is None:
        return None, NAME_UNREAD_TEXT
    if len(hosts) != 1 or hosts[0].lower() != LOCAL_HOST:
        return None, HOST_TEXT
    if len(forwarded_hosts) != 1 or forwarded_hosts[0].lower() != name:
        return None, HOST_TEXT
    if len(logins) != 1:
        return None, NOT_SHARED_TEXT
    login = normal_login(logins[0])
    if login is None or login not in access.colleagues:
        return None, NOT_SHARED_TEXT
    return login, None


ACCESS_TEXTS = frozenset({SHARING_OFF_TEXT, NAME_UNREAD_TEXT, HOST_TEXT, NOT_SHARED_TEXT, REVOKED_TEXT})
ACCOUNT_TEXTS = frozenset({CONSENT_TEXT, NO_OWN_SIGNIN_TEXT, ACCOUNT_BUSY_TEXT,
                           ACCOUNT_UNAVAILABLE_TEXT, NOT_SHARED_TEXT, REVOKED_TEXT,
                           NOT_YOUR_ACCOUNT_TEXT, CHANGE_UNAVAILABLE_TEXT})


def account_refusal(policy: Policy, actor: GuestActor) -> str | None:
    if not policy.access.shared:
        return SHARING_OFF_TEXT
    if policy.name is None:
        return NAME_UNREAD_TEXT
    if policy.name != actor.tailnet:
        return HOST_TEXT
    if actor.login not in policy.access.colleagues:
        return NOT_SHARED_TEXT
    return None


def account_text(text: str) -> str:
    """The text a guest reads for a refusal of an account write: only a fixed guest text, else the busy text."""
    return text if text in ACCOUNT_TEXTS else ACCOUNT_BUSY_TEXT


def account_reason(text: str) -> str:
    """The stderr reason of a refused account write: one of consent, access, no_run, busy, unavailable, not_yours."""
    return {CONSENT_TEXT: "consent", NO_OWN_SIGNIN_TEXT: "no_run",
            ACCOUNT_UNAVAILABLE_TEXT: "unavailable", CHANGE_UNAVAILABLE_TEXT: "unavailable",
            NOT_YOUR_ACCOUNT_TEXT: "not_yours", ACCOUNT_BUSY_TEXT: "busy"}.get(
                text, "access" if text in ACCESS_TEXTS else "busy")


def write_refusal(policy: Policy, actor: GuestActor, project_id: str) -> str | None:
    text = account_refusal(policy, actor)
    if text is not None:
        return text
    if project_id not in policy.access.colleagues[actor.login]:
        return NOT_YOUR_PROJECT_TEXT
    return None


def revokes(before: Access, after: Access) -> bool:
    """Whether going from `before` to `after` takes something away: the switch goes off, or a login or one of its projects goes."""
    if before.shared and not after.shared:
        return True
    return any(login not in after.colleagues or not projects <= after.colleagues[login]
               for login, projects in before.colleagues.items())


def steer_refusal(login: str, started_by: str | None) -> str | None:
    return None if started_by == login else NOT_YOUR_SPRINT_TEXT


def reading(access: Access, name: str | None, hosts: Sequence[str], forwarded_hosts: Sequence[str],
            logins: Sequence[str], forwarded: Sequence[str], probes: Sequence[str],
            *, own: frozenset = frozenset()) -> dict:
    """What one guest-door request showed, for the owner's `sharing.last_request`; never a login or an address."""
    _, text = admit(access, name, hosts, forwarded_hosts, logins)
    known = (LOCAL_HOST,) if name is None else (LOCAL_HOST, name, name + ":443")
    host = hosts[0] if len(hosts) == 1 else None
    one = forwarded_hosts[0] if len(forwarded_hosts) == 1 else None
    if one is None:
        form = "none"
    elif name is not None and one.lower() == name:
        form = "exact"
    elif name is not None and one.lower() == name + ":443":
        form = "with_port"
    else:
        form = "other"
    return {"admitted": text is None,
            "client": client_of(forwarded, own),
            "forwarded_for": bool(forwarded),
            "forwarded_host": one if one is not None and _kept_host(one, known) else None,
            "forwarded_host_form": form,
            "forwarded_hosts": len(forwarded_hosts),
            "host": host if host is not None and _kept_host(host, known) else None,
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
    keep("issue_titles", lambda key, _: key in projects)
    keep("sprints", lambda _, value: value.project_id in projects)
    keep("pending", lambda _, value: value.project_id in projects)
    keep("deliveries", lambda _, value: value.session_id in session_ids)
    if "prompted_sprints" in inputs:
        kept_sprints = result.get("sprints") or {}
        result["prompted_sprints"] = tuple(
            sprint_id for sprint_id in inputs["prompted_sprints"] or () if sprint_id in kept_sprints)
    if "engine_runs" in inputs:
        result["engine_runs"] = tuple(s for s in inputs["engine_runs"] or () if s.project in projects)
    return result


ACCOUNT_MEMBERS = ("label", "number", "ident", "state", "week_left", "five_hour_left", "week_reset",
                   "five_hour_reset", "next_reset", "out_until", "in_use")
POOL_MEMBERS = ("state", "tight", "all_out", "resumes_at", "no_reading", "accounts")
NUMBERS_FILE = "account-numbers.json"
STOP_FAILED_TEXT = "could not stop the manager; trying again"
MANAGER_REASON_TEXT = "the owner has the details"
UNSTOPPED_TEXT = "The manager of a dropped sprint could not be stopped; trying again"


def _accounts(capacity: Mapping) -> list[tuple[bool, list[str], str]]:
    """Each account as (has an address, its profiles sorted, its counted profile), in no order."""
    accounts = []
    for entry in capacity["profiles"]:
        if entry["duplicate_of"] is None:
            accounts.append((entry["account"] is not None,
                             sorted({entry["profile"], *entry["same_account_as"]}),
                             entry["profile"]))
    return accounts


def account_numbers(capacity: Mapping, previous: Mapping[str, int],
                    established: Collection[str] = ()) -> dict[str, int]:
    accounts = sorted(_accounts(capacity), key=lambda account: (not account[0], account[1][0]))
    address = {entry["profile"]: entry["account"] for entry in capacity["profiles"]}
    before = established if isinstance(established, Mapping) else {}
    claims = []
    for index, (_, profiles, counted) in enumerate(accounts):
        for number in {previous[name] for name in profiles if name in previous}:
            holders = [name for name in profiles if previous.get(name) == number]
            claims.append((
                not any(name in established for name in holders),
                -sum(address[name] is not None and before.get(name) == address[name]
                     for name in holders),
                -len(holders), previous.get(counted) != number, number, index))
    numbered: dict[int, int] = {}
    taken: set[int] = set()
    for *_, number, index in sorted(claims):
        if index not in numbered and number not in taken:
            numbered[index] = number
            taken.add(number)
    for index, _ in sorted(enumerate(accounts), key=lambda item: item[1][1][0]):
        if index not in numbered:
            number = 1
            while number in taken:
                number += 1
            numbered[index] = number
            taken.add(number)
    return {name: numbered[index] for index, (_, profiles, _) in enumerate(accounts)
            for name in profiles}


YOURS = "yours"


def _label(number: int, own: Collection[int]) -> str:
    return YOURS if number in own else f"Account {number}"


def _own_numbers(numbers: Mapping[str, int], mine: Collection[str]) -> set[int]:
    return {numbers[profile] for profile in mine if profile in numbers}


def profile_labels(numbers: Mapping[str, int],
                   mine: Collection[str] = frozenset()) -> dict[str, str]:
    """Each profile's label: `yours` when its account's number is one a profile of `mine` holds."""
    own = _own_numbers(numbers, mine)
    return {profile: _label(number, own) for profile, number in numbers.items()}


def retired_labels(retired: Mapping[str, tuple[int | None, str, str]], numbers: Mapping[str, int],
                   mine: Collection[str] = frozenset()) -> dict[str, str | None]:
    """The `retired` argument of `sprint_labels` for one page: None for a detached sprint, else the
    label of its kept number, `yours` when a profile of `mine` holds that account."""
    own = _own_numbers(numbers, mine)
    return {sprint_id: None if number is None else _label(number, own)
            for sprint_id, (number, _, _) in retired.items()}


def own_signin(signin_runs: Mapping[str, Mapping], owners: Mapping[str, str],
               login: str) -> dict | None:
    """The run a colleague's page shows among the profiles `login` added: the highest `attempt` of the
    running ones, else of all, as a copy of its `state`, `at` and `attempt`; None when there is none.
    It never carries a profile name."""
    runs = [signin_runs[profile] for profile, owner in owners.items()
            if owner == login and profile in signin_runs]
    if not runs:
        return None
    latest = max(runs, key=lambda run: (run["state"] == "running", run["attempt"]))
    return {key: latest[key] for key in ("state", "at", "attempt")}


def account_token(identities: Iterable[str]) -> str:
    """An opaque token of the directories behind one account of his (their recorded identities, in any order)."""
    return hashlib.sha256("\n".join(sorted(identities)).encode()).hexdigest()[:32]


def own_tokens(numbers: Mapping[str, int], identities: Mapping[str, str],
               mine: Collection[str]) -> dict[int, str]:
    """The token of each account of `mine`, by its number; a profile with no recorded identity gives none."""
    held: dict[int, list[str]] = {}
    for profile in mine:
        if profile in numbers and identities.get(profile) is not None:
            held.setdefault(numbers[profile], []).append(identities[profile])
    return {number: account_token(found) for number, found in held.items()}


def pool_view(capacity: Mapping, numbers: Mapping[str, int],
              mine: Collection[str] = frozenset(),
              tokens: Mapping[int, str] = MappingProxyType({})) -> dict:
    own = _own_numbers(numbers, mine)
    entries = sorted((entry for entry in capacity["profiles"] if entry["duplicate_of"] is None),
                     key=lambda entry: (numbers[entry["profile"]], entry["profile"]))
    rows = [{"label": _label(numbers[entry["profile"]], own), "number": numbers[entry["profile"]],
             "ident": tokens.get(numbers[entry["profile"]]), "state": entry["state"],
             "week_left": entry["week_left"], "five_hour_left": entry["five_hour_left"],
             "week_reset": entry["week_reset"], "five_hour_reset": entry["five_hour_reset"],
             "next_reset": entry["next_reset"], "out_until": entry["out_until"],
             "in_use": entry["signin"]["state"] != "signed_out" and not entry["excluded"]}
            for entry in entries]
    read = any(row["in_use"] and row["state"] != "unknown" for row in rows)
    state = (None if not read else "out" if capacity["all_out"]
             else "tight" if capacity["tight"] else "fine")
    return {"state": state, "tight": capacity["tight"], "all_out": capacity["all_out"],
            "resumes_at": capacity["resumes_at"], "no_reading": capacity["no_reading"],
            "accounts": rows}


EMPTY_POOL: dict = pool_view(EMPTY, {})


def running_managers(sprints: Mapping[str, SprintState]) -> dict[str, str]:
    """Each running sprint's id with the profile its manager is on."""
    return {sprint_id: state.manager.profile for sprint_id, state in sprints.items()
            if state.manager is not None and state.manager.state == STARTED
            and ended_at(state) is None}


def sprint_labels(sprints: Mapping[str, SprintState], labels: Mapping[str, str],
                  retired: Mapping[str, str | None] = MappingProxyType({})) -> dict[str, str]:
    """The account label of each running sprint: `retired[sprint_id]` when the sprint's profile left
    while it ran (a profile name can be given to another account since; a None one is detached and
    has no label, never its name's), else its profile's label."""
    found = {}
    for sprint_id, profile in running_managers(sprints).items():
        label = retired[sprint_id] if sprint_id in retired else labels.get(profile)
        if label is not None:
            found[sprint_id] = label
    return found


def _read_numbering(path: Path) -> tuple[dict[str, int], dict[str, tuple[int | None, str, str]]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=reject_duplicate_keys,
                              parse_constant=reject_nonfinite_literal)
    except (OSError, ValueError, RecursionError):
        return {}, {}

    def number(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 1

    numbers = document.get("numbers") if isinstance(document, dict) else None
    retired = document.get("retired") if isinstance(document, dict) else None
    if (not isinstance(numbers, dict) or not isinstance(retired, dict)
            or not all(isinstance(key, str) and number(value) for key, value in numbers.items())
            or not all(isinstance(key, str) and isinstance(value, list) and len(value) == 3
                       and (value[0] is None or number(value[0])) and isinstance(value[1], str)
                       and isinstance(value[2], str)
                       for key, value in retired.items())):
        return {}, {}
    return dict(numbers), {key: (value[0], value[1], value[2]) for key, value in retired.items()}


def read_numbers(path: Path) -> dict[str, int]:
    return _read_numbering(path)[0]


def read_retired(path: Path) -> dict[str, tuple[int | None, str, str]]:
    return _read_numbering(path)[1]


def write_numbers(path: Path, numbers: Mapping[str, int],
                  retired: Mapping[str, tuple[int | None, str, str]] = MappingProxyType({})) -> None:
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps({"numbers": dict(numbers), "retired": dict(retired)},
                                sort_keys=True))
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def scrub(view: Mapping, pool: Mapping | None = None,
          sprint_accounts: Mapping[str, str] | None = None,
          own_signin: Mapping | None = None) -> dict:
    accounts = sprint_accounts or {}

    def labelled(node: object) -> object:
        if isinstance(node, Mapping):
            result = {key: labelled(member) for key, member in node.items()}
            if node.get("type") == "sprint":
                result["account_label"] = accounts.get(node.get("sprint_id"))
                if result.get("stop_text") is not None:
                    result["stop_text"] = STOP_FAILED_TEXT
                if node.get("manager_state") == "stalled":
                    result["manager_text"] = STALLED_TEXT
            if node.get("type") == "inbox_item" and node.get("reason") == "manager":
                result["last_reason"] = MANAGER_REASON_TEXT
            return result
        if isinstance(node, list):
            return [labelled(member) for member in node]
        return node

    scrubbed = labelled({name: member for name, member in view.items() if name != "sharing"})
    scrubbed["unstopped"] = [{**item, "text": UNSTOPPED_TEXT} for item in view.get("unstopped", ())]
    shown = EMPTY_POOL if pool is None else pool
    scrubbed.update({"unmanaged": [], "profile_sessions": {}, "signin_runs": {},
                     "accounts_added": [], "pin": None, "pin_launches": [],
                     "registration": None, "digest": None, "activation": None, "spend": None,
                     "host_alerts": None, "capacity": dict(EMPTY),
                     "own_signin": None if own_signin is None else dict(own_signin),
                     "pool": {**shown, "accounts": [dict(row) for row in shown["accounts"]]}})
    return scrubbed


def mark_steer(view: Mapping, login: str) -> dict:
    def steers(item: Mapping) -> bool:
        reason = item.get("reason")
        return (reason in ("brief", "question") and item.get("started_by") == login
                and not (reason == "question"
                         and (item.get("owner_only") is True or item.get("look") is not None
                              or is_look(picture.get("pair") for picture in item.get("pictures", [])))))

    def copy(node: object) -> object:
        if isinstance(node, Mapping):
            result = {key: copy(member) for key, member in node.items()}
            if result.get("action_text") == NUDGE_ACTION_TEXT:
                result["action_text"] = NUDGE_ACTION_TEXT_GUEST
            if node.get("type") == "sprint":
                result["steer"] = node.get("started_by") == login
            return result
        if isinstance(node, list):
            return [copy(member) for member in node]
        return node

    marked = copy(view)
    inbox = view.get("inbox")
    if isinstance(inbox, Mapping):
        for part in ("open", "answered"):
            if part in inbox:
                marked["inbox"][part] = [
                    {**copy(item), "steer": steers(item)} for item in inbox[part]]
    return marked


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


def serve_state(shared: bool, name: str | None, status: object, guest_socket: str | None) -> str:
    if not shared:
        return "off"
    if name is None:
        return "unreadable"
    if status is None:
        return "unchecked"
    node: object = status
    for step in ("Web", f"{name}:443", "Handlers", "/", "Proxy"):
        node = node.get(step) if isinstance(node, Mapping) else None
    if isinstance(guest_socket, str) and guest_socket and node == "unix:" + guest_socket:
        return "serving"
    return "not_proxying"


def _json_reader(path: str, args: Sequence[str],
                 run: Callable[..., subprocess.CompletedProcess]) -> Callable[[], object | None]:
    def read() -> object | None:
        try:
            done = run([path, *args], capture_output=True, text=True,
                       timeout=SERVE_TIMEOUT_SECONDS, check=False)
            if done.returncode != 0:
                return None
            return json.loads(done.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError, RecursionError):
            return None

    return read


def serve_reader(path: str, run: Callable[..., subprocess.CompletedProcess] = subprocess.run
                 ) -> Callable[[], object | None]:
    return _json_reader(path, ("serve", "status", "--json"), run)


def status_reader(path: str, run: Callable[..., subprocess.CompletedProcess] = subprocess.run
                  ) -> Callable[[], object | None]:
    return _json_reader(path, ("status", "--json"), run)


def sharing_entry(access: Access, name: str | None, state: str, last_request: Mapping | None = None,
                  socket: str | None = None, other_device_seen: bool = False) -> dict:
    return {"shared": access.shared,
            "tailnet": name,
            "colleagues": [{"login": login, "projects": sorted(access.colleagues[login])}
                           for login in sorted(access.colleagues)],
            "state": state,
            "last_request": last_request,
            "socket": socket,
            "other_device_seen": other_device_seen}
