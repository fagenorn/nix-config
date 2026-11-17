"""`serve_probe_check`: the held check of the guest port's last request (#1237, AC8).

`python -m agent_tools.console.serve_probe_check [--port N]` reads the owner's `GET /api/state` on
loopback (`--port`, default `service.DEFAULT_PORT`) and judges `sharing.last_request`, the console's
one diagnostics reading of the last request on the guest port (`guest.reading`, never a login value).
It makes one loopback GET and no other network call, and it writes nothing.

What it shows: the guest door of ADR-console-066 D2 admits a request only when its `Host` is exactly
the configured tailnet name, with no port form, and exactly one `Tailscale-User-Login` header names a
listed colleague. Nobody could probe Serve before that slice merged, so this check settles the rule
afterwards, from the first real request: Serve sent the tailnet name as `Host`, exactly one login
header of its own, and a client-sent forged login did not arrive as sent.

The trigger: with the console's tailnet name set and Serve proxying it to the guest port (ADR-console-066
D4), from another tailnet node send, as the last request on the guest port,
`curl -sS -H 'Tailscale-User-Login: forged-probe@example.invalid' -H 'X-Console-Probe:
forged-probe@example.invalid' https://<host>.<tailnet>.ts.net/api/whoami`. The probe value is the one
fixed `guest.PROBE_LOGIN` (`FORGED`): the reading recognizes exactly that value in the probe header
(`probe`) and among the login headers (`probe_login_arrived`), so the check compares no client value
and keeps no probe or login value; a forged login that arrives under any other probe value cannot pass
as met.

The rules, read in this order, each printing one line:

1. the state is not a JSON object: `not_running`, exit 75;
2. `sharing` is not an object or `sharing.tailnet` is not a string: `sharing_off`, 75;
3. `sharing.last_request` is absent or null: `no_request`, 75;
4. the reading is not well formed (exactly the members of `guest.READING_MEMBERS`; `admitted`,
   `forwarded_for`, `probe`, `probe_login_arrived` booleans; `hosts` and `login_headers` integers;
   `host` a string or null, a string when `host_form` is `exact` or `with_port`; `host_form` one of
   `guest.HOST_FORMS`; `reason` null or one of `guest.REASON_CODES`): `bad_reading`, exit 1;
5. `forwarded_for` is false, a local request and not one through Serve: `not_through_serve`, 75;
6. the reading's kept `Host` is a string and its `host_form` disagrees with the current tailnet
   name: `host_form` is `exact` or `with_port` and the `Host`, lowercased, is neither the current
   name nor that name followed by `:443`, or `host_form` is `other` and it is one of them: `stale`,
   75. The reading's `host_form` was judged against the name in force when the request arrived (no
   name set, or an older one, reads `other`) and the owner may have changed it since, so the check
   compares the kept `Host` with the current name and waits for a request at it;
7. `host_form` is not `exact`, or `hosts` or `login_headers` is not 1: `not_met`, exit 1;
8. `probe_login_arrived` is true, the prescribed forged login reached the service as a login whatever
   probe header came with it: `not_met`, 1;
9. `probe` is false, the Host half is shown and the prescribed probe value is still awaited:
   `no_probe`, 75;
10. otherwise `met`, exit 0.

A `with_port` or other result is not met: it shows the strict rule refuses what Serve sends, and the
owner decides any change to the rule (ADR-console-066 D2), never this check.

Output: exactly one stdout line, `json.dumps(result, sort_keys=True)`. From rule 5 on it has
`admitted`, `forwarded_for`, `host_form`, `login_headers`, `probe`, `probe_login_arrived`, `reason`
and `status`, and nothing else: it never prints the `Host` value, the tailnet name or any login,
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
_FLAGS = ("admitted", "forwarded_for", "probe", "probe_login_arrived")
_COUNTS = ("hosts", "login_headers")


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
    host, form, reason = reading["host"], reading["host_form"], reading["reason"]
    return (all(isinstance(reading[name], bool) for name in _FLAGS)
            and all(type(reading[name]) is int for name in _COUNTS)
            and (host is None or isinstance(host, str))
            and (isinstance(host, str) or form not in ("exact", "with_port"))
            and form in guest.HOST_FORMS
            and (reason is None or reason in guest.REASON_CODES.values()))


def main(argv: list[str] | None = None, *,
         read_state: Callable[[int], object | None] = default_read_state) -> int:
    args = build_parser().parse_args(argv)
    state = read_state(args.port)
    if not isinstance(state, dict):
        _print({"status": "not_running"})
        return NOT_YET
    sharing = state.get("sharing")
    if not isinstance(sharing, dict) or not isinstance(sharing.get("tailnet"), str):
        _print({"status": "sharing_off"})
        return NOT_YET
    reading = sharing.get("last_request")
    if reading is None:
        _print({"status": "no_request"})
        return NOT_YET
    if not _well_formed(reading):
        _print({"status": "bad_reading"})
        return 1
    shown = {name: reading[name] for name in
             (*_FLAGS, "host_form", "login_headers", "reason")}
    form = reading["host_form"]
    tailnet = sharing["tailnet"].lower()
    if not reading["forwarded_for"]:
        status, code = "not_through_serve", NOT_YET
    elif isinstance(reading["host"], str) and (
            reading["host"].lower() in (tailnet, tailnet + ":443")) != (form != "other"):
        status, code = "stale", NOT_YET
    elif form != "exact" or reading["hosts"] != 1 or reading["login_headers"] != 1:
        status, code = "not_met", 1
    elif reading["probe_login_arrived"]:
        status, code = "not_met", 1
    elif not reading["probe"]:
        status, code = "no_probe", NOT_YET
    else:
        status, code = "met", 0
    _print({**shown, "status": status})
    return code


if __name__ == "__main__":
    raise SystemExit(main())
