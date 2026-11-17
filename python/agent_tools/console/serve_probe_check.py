"""`serve_probe_check`: the probe that a client-sent login header does not pass Tailscale Serve as sent (#1237, AC6).

`python -m agent_tools.console.serve_probe_check [--port N]` reads the owner's `GET /api/state` for
`sharing.tailnet`, then sends `GET https://<tailnet>/api/whoami` through the real Serve with a forged
`Tailscale-User-Login` (`FORGED`, an invented login) and reads what the guest port received, from
`GET /api/whoami` (guest port only). It proves that Serve, which fronts the guest port, replaces a
client-sent login header with its own instead of passing it on, and which `Host` the guest port sees.
The guest door of ADR-console-066 D2 admits a request whose `Host` is the configured tailnet name and
that carries exactly one login header of a listed colleague; the probe confirms that rule against the
real Serve, and the rule is amended by its result when the two differ.

The forged value is also sent as `X-Console-Probe`, a header Serve does not touch: `/api/whoami`
reports whether the login named by `X-Console-Probe` arrived as a login header
(`probe_login_arrived`), so the answer says whether the forged login passed Serve as sent without the
service ever repeating a login. `--port` (default `service.DEFAULT_PORT`) is the owner's port, read
only for the tailnet name.

The host form is `exact` when the answer's `host`, lowercased, equals the tailnet name, `with_port`
when it equals the tailnet name followed by `:443`, else `other` (the backend's own address, or no
`Host` at all).

Met (exit 0) exactly when the host form is `exact` or `with_port`, `login_headers` is 1 (Serve put
exactly one login of its own; none means Serve adds no login and the door could admit nobody, which
ADR-console-066 D1 does not expect) and `probe_login_arrived` is false. Otherwise not met (exit 1).

Exits: 0 met; 1 not met, or a bad answer (`{"status": "bad_answer"}` with `http_status` when a status
was read: any status other than 200, a body that is not a JSON object, or a missing or mistyped
member among `host`, `login_headers`, `probe_login_arrived`, `forwarded_for`; a 403 from the guest
port is a bad answer, not an unreachable one); 75 (`NOT_YET`) when there is nothing to probe yet:
the owner's console does not answer (`{"status": "not_running"}`), sharing is off (`{"status":
"sharing_off"}`) or the tailnet name does not answer (`{"status": "unreachable"}`); 2 a usage error.

Output: exactly one stdout line, `json.dumps(result, sort_keys=True)`. Once an answer was read it has
`status` (`met` or `not_met`), `host_form`, `login_headers`, `probe_login_arrived` and
`forwarded_for`. It never prints the tailnet name, the `Host` value or any login, because the output
is recorded on the pull request and in ADR-console-066.

The lead runs it once before merge, against a scratch console started from the branch with Serve
proxying the tailnet name to its guest port (ADR-console-066 D2 and D4), and records the result in
ADR-console-066. It reads only and writes nothing. The seams of `main` are `read_state` and `fetch`.
"""

import argparse
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping

from agent_tools.console import service

FORGED = "forged-probe@example.invalid"
NOT_YET = 75
HOST_FORMS = ("exact", "with_port", "other")


def default_read_state(port: int) -> object | None:
    """The owner's `/api/state` parsed, or None when the console does not answer."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5) as response:
            return json.loads(response.read())
    except (OSError, ValueError):
        return None


def default_fetch(url: str, headers: Mapping[str, str], *,
                  timeout: float = 10.0) -> tuple[int, bytes] | None:
    """`(status, body)` of a GET, a 4xx or 5xx answer included; None when nothing answered."""
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except OSError:
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="serve_probe_check", description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=service.DEFAULT_PORT,
                        help="the owner's console port")
    return parser


def _print(result: dict) -> None:
    print(json.dumps(result, sort_keys=True))


def _well_formed(answer: object) -> bool:
    if not isinstance(answer, dict):
        return False
    host = answer.get("host", 0)
    return ((host is None or isinstance(host, str))
            and type(answer.get("login_headers")) is int
            and isinstance(answer.get("probe_login_arrived"), bool)
            and isinstance(answer.get("forwarded_for"), bool))


def _host_form(host: str | None, tailnet: str) -> str:
    seen = (host or "").lower()
    if seen == tailnet:
        return "exact"
    return "with_port" if seen == tailnet + ":443" else "other"


def main(argv: list[str] | None = None, *,
         read_state: Callable[[int], object | None] = default_read_state,
         fetch: Callable[[str, Mapping[str, str]], tuple[int, bytes] | None] = default_fetch) -> int:
    args = build_parser().parse_args(argv)
    state = read_state(args.port)
    if not isinstance(state, dict):
        _print({"status": "not_running"})
        return NOT_YET
    sharing = state.get("sharing")
    tailnet = sharing.get("tailnet") if isinstance(sharing, dict) else None
    if not isinstance(tailnet, str):
        _print({"status": "sharing_off"})
        return NOT_YET
    read = fetch(f"https://{tailnet}/api/whoami",
                 {"Tailscale-User-Login": FORGED, "X-Console-Probe": FORGED})
    if read is None:
        _print({"status": "unreachable"})
        return NOT_YET
    status, body = read
    try:
        answer = json.loads(body) if status == 200 else None
    except ValueError:
        answer = None
    if not _well_formed(answer):
        _print({"http_status": status, "status": "bad_answer"})
        return 1
    form = _host_form(answer["host"], tailnet.lower())
    met = form != "other" and answer["login_headers"] == 1 and answer["probe_login_arrived"] is False
    _print({"forwarded_for": answer["forwarded_for"], "host_form": form,
            "login_headers": answer["login_headers"],
            "probe_login_arrived": answer["probe_login_arrived"],
            "status": "met" if met else "not_met"})
    return 0 if met else 1


if __name__ == "__main__":
    raise SystemExit(main())
