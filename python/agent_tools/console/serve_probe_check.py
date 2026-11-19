"""`serve_probe_check`: the held check of the guest door's last request (#1237, AC8).

`python -m agent_tools.console.serve_probe_check [--port N]` reads the owner's `GET /api/state` on
loopback (`--port`, default `service.DEFAULT_PORT`) and judges `sharing.last_request`, the console's
one diagnostics reading of the last request on the guest door (`guest.reading`, never a login value).
It makes one loopback GET and no other network call, and it writes nothing.

What it shows: the guest door (a Unix socket, ADR-console-077 D4) admits a request only when its
`Host` is exactly `localhost`, its one `X-Forwarded-Host` is exactly the tailnet name the console reads
from this host's Tailscale client (ADR-console-078), with no port form, and exactly one
`Tailscale-User-Login` header names a listed colleague. Nobody could
probe Serve before that slice merged, so this check settles the rule afterwards, from the first real
request: Serve sent `Host: localhost`, the tailnet name as its one `X-Forwarded-Host`, exactly one
login header of its own, and a client-sent forged login did not arrive as sent.

The trigger: with sharing on, the console reading its tailnet name, and Serve proxying it to the
guest socket (ADR-console-077
D5), from another tailnet node send, as the last request on the guest door,
`curl -sS -H 'Tailscale-User-Login: forged-probe@example.invalid' -H 'X-Console-Probe:
forged-probe@example.invalid' https://<host>.<tailnet>.ts.net/api/whoami`. The probe value is the one
fixed `guest.PROBE_LOGIN` (`FORGED`): the reading recognizes exactly that value in the probe header
(`probe`) and among the login headers (`probe_login_arrived`), so the check compares no client value
and keeps no probe or login value; a forged login that arrives under any other probe value cannot pass
as met.

The rules, read in this order, each printing one line:

1. the state is not a JSON object: `not_running`, exit 75;
2. `sharing` is not an object or `sharing.shared` is not exactly `true` (a console from before the
   switch has no `shared`): `sharing_off`, 75;
3. `sharing.tailnet` is not a string, the console reads no name from this host's Tailscale client:
   `name_unread`, 75 (the name may become readable);
4. `sharing.last_request` is absent or null: `no_request`, 75;
5. the reading is not well formed (exactly the members of `guest.READING_MEMBERS`; `admitted`,
   `forwarded_for`, `host_local`, `login_valid`, `probe`, `probe_login_arrived` booleans;
   `forwarded_hosts`, `hosts` and `login_headers` integers; `forwarded_host` a string or null, a
   string when `forwarded_host_form` is `exact` or `with_port`; `host` a string or null;
   `forwarded_host_form` one of `guest.HOST_FORMS`; `reason` null or one of `guest.REASON_CODES`;
   `client` one of `guest.CLIENT_FORMS`): `bad_reading`, exit 1;
6. `forwarded_for` is false, a local request and not one through Serve: `not_through_serve`, 75;
7. `client` is `this_host`, a request this host sent to itself, which proves nothing about the
   tailnet's access rules (ADR-console-079 D5): `from_this_host`, 75; `client` is `unknown`, the
   console could not tell this host's address from another device's: `client_unknown`, 75; only
   `other_device` goes on;
8. the reading's `reason` is `sharing_off` or `name_unread`: it was taken while sharing was off or the
   name unread, and rules 2 and 3 show both have changed since; or the reading's kept
   `forwarded_host` is a string and its `forwarded_host_form` disagrees with the current tailnet
   name: the form is `exact` or `with_port` and the forwarded host, lowercased, is neither the
   current name nor that name followed by `:443`, or the form is `other` and it is one of them:
   `stale`, 75. The form was judged against the name in force when the request arrived (no name
   read, or an older one, reads `other`) and the name read may have changed since, so the check
   compares the kept forwarded host with the current name and waits for a request at it;
9. `forwarded_host_form` is not `exact`, or `forwarded_hosts`, `hosts` or `login_headers` is not 1,
   or `host_local` is false: `not_met`, exit 1;
10. `probe_login_arrived` is true, the prescribed forged login reached the service as a login whatever
   probe header came with it, or `login_valid` is false, a login header arrived that is not one
   well-formed login (a combined value can carry the forged login without matching it): `not_met`, 1;
11. `probe` is false, the Host half is shown and the prescribed probe value is still awaited:
    `no_probe`, 75;
12. otherwise `met`, exit 0.

A `with_port` or other result, or a `Host` that is not `localhost`, is not met: it shows the strict
rule refuses what Serve sends, and the owner decides any change to the rule (ADR-console-077 D4),
never this check.

Output: exactly one stdout line, `json.dumps(result, sort_keys=True)`. From rule 6 on it has
`admitted`, `client`, `forwarded_for`, `forwarded_host_form`, `host_local`, `login_headers`, `login_valid`,
`probe`, `probe_login_arrived`, `reason` and `status`, and nothing else: it never prints a host value, the tailnet name or any login,
because the output is recorded on the pull request. A usage error exits 2.

The seam of `main` is `read_state`, the loopback read. The module imports only the standard library
and `agent_tools.console` (`guest`, `service`).
"""

import argparse
import http.client
import json
import urllib.request
from collections.abc import Callable

from agent_tools.console import guest, service

FORGED = guest.PROBE_LOGIN
NOT_YET = 75
_FLAGS = ("admitted", "forwarded_for", "host_local", "login_valid", "probe", "probe_login_arrived")
_STALE_REASONS = (guest.REASON_CODES[guest.SHARING_OFF_TEXT],
                  guest.REASON_CODES[guest.NAME_UNREAD_TEXT])
_COUNTS = ("forwarded_hosts", "hosts", "login_headers")


def default_read_state(port: int) -> object | None:
    """The owner's `/api/state` parsed, or None when the console does not answer."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5) as response:
            return json.loads(response.read())
    except (OSError, ValueError, http.client.HTTPException):
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="serve_probe_check", description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=service.DEFAULT_PORT,
                        help="the owner's console port")
    return parser


def _print(result: dict) -> None:
    print(json.dumps(result, sort_keys=True))


def _well_formed(reading: object) -> bool:
    if not isinstance(reading, dict) or set(reading) != set(guest.READING_MEMBERS):
        return False
    host, form = reading["forwarded_host"], reading["forwarded_host_form"]
    reason = reading["reason"]
    return (all(isinstance(reading[name], bool) for name in _FLAGS)
            and all(type(reading[name]) is int for name in _COUNTS)
            and (host is None or isinstance(host, str))
            and (reading["host"] is None or isinstance(reading["host"], str))
            and (isinstance(host, str) or form not in ("exact", "with_port"))
            and form in guest.HOST_FORMS
            and reading["client"] in guest.CLIENT_FORMS
            and (reason is None or reason in guest.REASON_CODES.values()))


def main(argv: list[str] | None = None, *,
         read_state: Callable[[int], object | None] = default_read_state) -> int:
    args = build_parser().parse_args(argv)
    state = read_state(args.port)
    if not isinstance(state, dict):
        _print({"status": "not_running"})
        return NOT_YET
    sharing = state.get("sharing")
    if not isinstance(sharing, dict) or sharing.get("shared") is not True:
        _print({"status": "sharing_off"})
        return NOT_YET
    if not isinstance(sharing.get("tailnet"), str):
        _print({"status": "name_unread"})
        return NOT_YET
    reading = sharing.get("last_request")
    if reading is None:
        _print({"status": "no_request"})
        return NOT_YET
    if not _well_formed(reading):
        _print({"status": "bad_reading"})
        return 1
    shown = {name: reading[name] for name in
             (*_FLAGS, "client", "forwarded_host_form", "login_headers", "reason")}
    form = reading["forwarded_host_form"]
    tailnet = sharing["tailnet"].lower()
    if not reading["forwarded_for"]:
        status, code = "not_through_serve", NOT_YET
    elif reading["client"] == guest.THIS_HOST:
        status, code = "from_this_host", NOT_YET
    elif reading["client"] == guest.UNKNOWN_CLIENT:
        status, code = "client_unknown", NOT_YET
    elif reading["reason"] in _STALE_REASONS or isinstance(reading["forwarded_host"], str) and (
            reading["forwarded_host"].lower() in (tailnet, tailnet + ":443")) != (form != "other"):
        status, code = "stale", NOT_YET
    elif (form != "exact" or reading["forwarded_hosts"] != 1 or not reading["host_local"]
          or reading["hosts"] != 1 or reading["login_headers"] != 1):
        status, code = "not_met", 1
    elif not reading["login_valid"] or reading["probe_login_arrived"]:
        status, code = "not_met", 1
    elif not reading["probe"]:
        status, code = "no_probe", NOT_YET
    else:
        status, code = "met", 0
    _print({**shown, "status": status})
    return code


if __name__ == "__main__":
    raise SystemExit(main())
