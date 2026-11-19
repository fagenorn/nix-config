"""`owner_port_check`: the held check that the owner port answers only the owner (#1294, ADR-console-076).

`python -m agent_tools.console.owner_port_check --as USER [--port N]` run as the console's owner
(`--port`, default `service.DEFAULT_PORT`) shows three things on the owner port, in this order:

1. another local account, `USER` (a CI runner account, say), is refused: its `GET /` through
   `sudo -n -u USER curl` answers `403` with the body exactly `peer.NOT_OWNER_TEXT` and a newline;
2. the owner's page loads through an SSH local forward, the way the owner's browser reaches the
   console: a forward from the owner to `127.0.0.1` opened by this check, whose listening end the
   owner's `sshd-session` serves, so the peer rule sees the owner's uid on the connection;
3. that forward's listening end is shown unusable by `USER`: a connect attempt to it as `USER`
   fails with the explicit permission-denied error (`connect_as` is `denied`).

Why the forward listens on a Unix socket. The peer rule judges the uid of the process holding the
connection's client end, and through an SSH forward that is the owner's `sshd-session`. An
`ssh -L 127.0.0.1:<port>:...` would put an owner-held relay on a loopback TCP port that every local
account can reach while it is up, which reopens the hole #1294 closes. So the forward listens on
`<tmp>/console.sock` inside this check's own mode-0700 temporary directory (under `/tmp`, which
keeps the path within the Unix socket length limit); the destination is the console's real TCP port,
reached by `sshd-session` over `direct-tcpip`; and leg 3 shows `USER` cannot open that socket.

The rules, read in this order, each printing one line:

1. the other user's request could not be made (no sudo rule, curl could not connect, no real HTTP
   status): `cannot_request_as_other_user`, exit 75;
2. the answer is not `403` with that exact body: `not_refused`, exit 1; the forward is not opened;
3. the forward could not be opened or its page not read: `no_forward`, exit 75;
4. the owner's page through the forward is not `200`: `owner_page_not_loaded`, exit 1;
5. `USER` connected to the forward's socket: `forward_reachable_by_other_user`, 1;
6. `USER`'s attempt gave no permission-denied proof (a timeout, a failed sudo, any other connect
   error, or the forward gone before the attempt): `isolation_not_proven`, exit 75;
7. otherwise (permission denied) `met`, exit 0.

Output: exactly one stdout line, `json.dumps(result, sort_keys=True)`, with `forward_other_status`,
`other_status`, `owner_status` (each an integer or null) and `status` (`met`, `not_met` or
`not_yet`), and `reason` when not met. It prints no body and no header. A usage error exits 2.

It writes nothing outside its temporary directory, which it removes, and the ssh process is always
terminated. The seams of `main` are `as_other` and `through_forward`; the module imports only the
standard library and `agent_tools.console` (`peer`, `service`).
"""

import argparse
import getpass
import http.client
import json
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from typing import NamedTuple

from agent_tools.console import peer, service

SUDO = "/usr/bin/sudo"
CURL = "/usr/bin/curl"
SSH = "/usr/bin/ssh"
FORWARD_WAIT_SECONDS = 15
SOCKET_NAME = "console.sock"
NOT_YET = 75
PROBE = ("import socket, sys\n"
         "s = socket.socket(socket.AF_UNIX)\n"
         "try:\n"
         "    s.connect(sys.argv[1])\n"
         "except PermissionError:\n"
         "    sys.exit(13)\n"
         "except OSError:\n"
         "    sys.exit(14)\n")
PYTHON = "/usr/bin/python3"
DENIED = "denied"
CONNECTED = "connected"
UNKNOWN = "unknown"


def request_as(user: str, port: int, *, unix_socket: str | None = None,
               run=subprocess.run) -> tuple[int, bytes] | None:
    """`GET /` on the owner port as `user` (through `unix_socket` when given); None when not made."""
    argv = [SUDO, "-n", "-u", user, CURL, "-q", "--noproxy", "*", "-sS", "--max-time", "5"]
    if unix_socket is not None:
        argv += ["--unix-socket", unix_socket]
    argv += ["-H", f"Host: {service.HOST}:{port}", "-w", "\n%{http_code}",
             f"http://{service.HOST}:{port}/"]
    try:
        done = run(argv, capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    head, newline, tail = done.stdout.rpartition(b"\n")
    if not newline or len(tail) != 3 or not tail.isdigit() or not tail.isascii() or tail == b"000":
        return None
    return int(tail), head


def connect_as(user: str, sock: str, *, run=subprocess.run) -> str:
    """Try to connect to `sock` as `user`: `denied` only on the explicit permission-denied exit.

    The probe runs isolated (`-I`) from `/`: the check's own working folder can be unreadable to
    `user`, and Python would otherwise put it on its import path and exit 1 before connecting.
    """
    argv = [SUDO, "-n", "-u", user, PYTHON, "-I", "-c", PROBE, sock]
    try:
        done = run(argv, capture_output=True, timeout=15, check=False, cwd="/")
    except (OSError, subprocess.TimeoutExpired):
        return UNKNOWN
    if done.returncode == 13:
        return DENIED
    if done.returncode == 0:
        return CONNECTED
    return UNKNOWN


def forward_argv(sock: str, port: int, owner: str, known_hosts: str) -> list[str]:
    """The ssh command: a local forward listening on the Unix socket `sock`, to the TCP `port`."""
    return [SSH, "-N", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
            "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={known_hosts}",
            "-L", f"{sock}:{service.HOST}:{port}", f"{owner}@{service.HOST}"]


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, host: str, sock: socket.socket) -> None:
        super().__init__(host, timeout=10)
        self._unix = sock

    def connect(self) -> None:
        self.sock = self._unix


def unix_get(sock: str, port: int, proc, *, wait: float = FORWARD_WAIT_SECONDS) -> int | None:
    """The status of `GET /` through the forward's socket, or None when it never became ready."""
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline and proc.poll() is None:
        client = socket.socket(socket.AF_UNIX)
        client.settimeout(10)
        try:
            client.connect(sock)
        except OSError:
            client.close()
            time.sleep(0.2)
            continue
        connection = _UnixConnection(f"{service.HOST}:{port}", client)
        try:
            connection.request("GET", "/", headers={"Host": f"{service.HOST}:{port}",
                                                    "Connection": "close"})
            return connection.getresponse().status
        except (OSError, http.client.HTTPException):
            return None
        finally:
            connection.close()
    return None


class Forward(NamedTuple):
    owner_status: int
    isolation: str
    other: tuple[int, bytes] | None


def request_through_forward(port: int, user: str, *, owner: str | None = None,
                            popen=subprocess.Popen, get=unix_get, connect=connect_as,
                            other=request_as) -> Forward | None:
    """Open the forward, read the owner's page through it, and try it as `user`; None if no forward."""
    owner = owner or getpass.getuser()
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="owner-port-") as tmp:
        sock = f"{tmp}/{SOCKET_NAME}"
        try:
            proc = popen(forward_argv(sock, port, owner, f"{tmp}/known_hosts"),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        except OSError:
            return None
        try:
            status = get(sock, port, proc)
            if status is None:
                return None
            isolation = connect(user, sock)
            if isolation == DENIED and proc.poll() is not None:
                isolation = UNKNOWN
            answer = other(user, port, unix_socket=sock) if isolation == CONNECTED else None
            return Forward(status, isolation, answer)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="owner_port_check", description=__doc__.splitlines()[0])
    parser.add_argument("--as", dest="user", required=True,
                        help="another local account that must be refused")
    parser.add_argument("--port", type=int, default=service.DEFAULT_PORT,
                        help="the owner's console port")
    return parser


def main(argv: list[str] | None = None, *, as_other=request_as,
         through_forward: Callable[[int, str], Forward | None] = request_through_forward) -> int:
    args = build_parser().parse_args(argv)
    shown: dict = {"forward_other_status": None, "other_status": None, "owner_status": None}

    def finish(status: str, code: int, reason: str | None = None) -> int:
        print(json.dumps({**shown, "status": status, **({"reason": reason} if reason else {})},
                         sort_keys=True))
        return code

    answer = as_other(args.user, args.port)
    if answer is None:
        return finish("not_yet", NOT_YET, "cannot_request_as_other_user")
    shown["other_status"] = answer[0]
    if answer != (403, peer.NOT_OWNER_TEXT.encode() + b"\n"):
        return finish("not_met", 1, "not_refused")
    forward = through_forward(args.port, args.user)
    if forward is None:
        return finish("not_yet", NOT_YET, "no_forward")
    shown["owner_status"] = forward.owner_status
    if forward.owner_status != 200:
        return finish("not_met", 1, "owner_page_not_loaded")
    if forward.isolation == CONNECTED:
        if forward.other is not None:
            shown["forward_other_status"] = forward.other[0]
        return finish("not_met", 1, "forward_reachable_by_other_user")
    if forward.isolation != DENIED:
        return finish("not_yet", NOT_YET, "isolation_not_proven")
    return finish("met", 0)


if __name__ == "__main__":
    sys.exit(main())
