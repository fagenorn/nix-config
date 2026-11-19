"""`guest_socket_check`: the held check that another account cannot open the guest socket (#1299, ADR-console-077).

`python -m agent_tools.console.guest_socket_check --as USER [--port N]` run as the console's owner
(`--port`, default `service.DEFAULT_PORT`) reads the owner's state from the loopback port, takes the
guest socket path from its `sharing.socket` member, and shows two things about that socket:

1. the owner can connect to it, so the door is up;
2. another local account, `USER` (a CI runner account, say), is refused with the explicit
   permission-denied error (`owner_port_check.connect_as` is `denied`).

Why the owner's connect comes first. A refusal by `USER` proves nothing about a socket that is not
listening or not there: a missing path and a refused connection are not permission errors, but a
state that has moved on since it was read could still look like isolation. So the owner's own
connect must succeed before the other user's denial counts.

The rules, read in this order, each printing one line:

1. the owner's state could not be read as an object: `not_yet`, `not_running`, exit 75;
2. `sharing` is not an object or `sharing.socket` is not an absolute-path string: `not_yet`,
   `no_guest_door`, exit 75;
3. the owner's connect to the socket failed: `not_yet`, `door_not_answering`, exit 75;
4. `USER` connected: `not_met`, `reachable_by_other_user`, exit 1;
5. `USER`'s attempt gave no permission-denied proof (a timeout, a failed sudo, any other error):
   `not_yet`, `isolation_not_proven`, exit 75;
6. otherwise (permission denied) `met`, exit 0.

Output: exactly one stdout line, `json.dumps({"status": ..., "reason": ...}, sort_keys=True)`, with
`reason` only when not met. It never carries the socket path, a uid or a login. A usage error
exits 2. The module writes nothing; the seams of `main` are `read_state`, `connect_owner` and
`connect_other`, and it imports only the standard library and `agent_tools.console`
(`owner_port_check`, `serve_probe_check`, `service`).
"""

import argparse
import json
import os
import socket
import sys
from collections.abc import Callable

from agent_tools.console import service
from agent_tools.console.owner_port_check import CONNECTED, DENIED, connect_as
from agent_tools.console.serve_probe_check import default_read_state

NOT_YET = 75
CONNECT_SECONDS = 5


def owner_connects(path: str) -> bool:
    """Whether an `AF_UNIX` connect to `path` succeeds within a few seconds; False on any `OSError`."""
    client = socket.socket(socket.AF_UNIX)
    try:
        client.settimeout(CONNECT_SECONDS)
        client.connect(path)
    except OSError:
        return False
    finally:
        client.close()
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="guest_socket_check", description=__doc__.splitlines()[0])
    parser.add_argument("--as", dest="user", required=True,
                        help="another local account that must not open the guest socket")
    parser.add_argument("--port", type=int, default=service.DEFAULT_PORT,
                        help="the owner's console port")
    return parser


def _print(status: str, reason: str | None = None) -> None:
    print(json.dumps({"status": status, **({"reason": reason} if reason else {})}, sort_keys=True))


def main(argv: list[str] | None = None, *,
         read_state: Callable[[int], object | None] = default_read_state,
         connect_owner: Callable[[str], bool] = owner_connects,
         connect_other: Callable[[str, str], str] = connect_as) -> int:
    args = build_parser().parse_args(argv)
    state = read_state(args.port)
    if not isinstance(state, dict):
        _print("not_yet", "not_running")
        return NOT_YET
    sharing = state.get("sharing")
    path = sharing.get("socket") if isinstance(sharing, dict) else None
    if not isinstance(path, str) or not os.path.isabs(path):
        _print("not_yet", "no_guest_door")
        return NOT_YET
    if not connect_owner(path):
        _print("not_yet", "door_not_answering")
        return NOT_YET
    answer = connect_other(args.user, path)
    if answer == CONNECTED:
        _print("not_met", "reachable_by_other_user")
        return 1
    if answer != DENIED:
        _print("not_yet", "isolation_not_proven")
        return NOT_YET
    _print("met")
    return 0


if __name__ == "__main__":
    sys.exit(main())
