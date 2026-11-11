"""`console`: serve the lead console on loopback until stopped (#855).

`console [--port N]` binds 127.0.0.1 only, on N (default 27184; 0 picks a free port), and serves
the desk page, `GET /api/state` and the `GET /api/stream` update stream
(`agent_tools.console.service` holds the routes and the stream's frame). The event log is
`~/.agents/state/console/events.sqlite3`; the fleet registry it follows, and never writes, is
`~/.agents/state/fleet/registry.json`.

Once serving it prints exactly one stdout line, `console: serving http://127.0.0.1:<port>/`.
SIGTERM or SIGINT closes the service and exits 0. A port that cannot be bound is stderr
`console: cannot listen on 127.0.0.1:<port>: <error>` and exit 1; an event log that cannot be
used (a schema version this build does not read, a database error) is stderr
`console: event log unusable: <error>` and exit 1. A bad argument is exit 2.
"""

from __future__ import annotations

import argparse
import signal
import sqlite3
import sys
import threading

from agent_tools.console import service
from agent_tools.console.event_log import EventLogError


def port_number(text: str) -> int:
    try:
        port = int(text)
    except ValueError:
        port = -1
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"{text!r} is not a port number (0-65535)")
    return port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="console", description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=port_number, default=service.DEFAULT_PORT,
                        help="loopback port to listen on (0 picks a free one; default: %(default)s)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        console = service.ConsoleService(
            service.default_store(), service.default_registry(), port=args.port)
    except (EventLogError, sqlite3.Error) as error:
        print(f"console: event log unusable: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"console: cannot listen on {service.HOST}:{args.port}: {error}", file=sys.stderr)
        return 1
    stop = threading.Event()
    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, lambda *_: stop.set())
    try:
        console.start()
        print(f"console: serving http://{service.HOST}:{console.address[1]}/", flush=True)
        while not stop.wait(1.0):
            pass
    finally:
        console.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
