"""`console`: serve the lead console on loopback until stopped (#855).

`console [--port N]` binds 127.0.0.1 only, on N (default 27184; 0 picks a free port), and serves
the desk page, `GET /api/state` and the `GET /api/stream` update stream
(`agent_tools.console.service` holds the routes and the stream's frame). The event log is
`~/.agents/state/console/events.sqlite3`; the fleet registry it follows, and never writes, is
`~/.agents/state/fleet/registry.json`. The page's write token is created once in
`~/.agents/state/console/page-token` (mode 0600) and kept across restarts. Every two minutes it also reads the owner-action items of
each active project from the tracker into the log (`agent_tools.console.service` holds the rules).

Once serving it prints exactly one stdout line, `console: serving http://127.0.0.1:<port>/`.
SIGTERM or SIGINT closes the service and exits 0. A port that cannot be bound is stderr
`console: cannot listen on 127.0.0.1:<port>: <error>` and exit 1; an event log that cannot be
used (a schema version this build does not read, a database error) is stderr
`console: event log unusable: <error>` and exit 1; a page token that cannot be read or is malformed is
stderr `console: page token unusable: <error>` and exit 1. A bad argument is exit 2.

The service is given `manager.launcher_for(sys.platform)`: on Linux a stated goal starts that
sprint's manager (`agent_tools.console.manager`), elsewhere there is no launcher and every sprint
says managers are not available on this host yet.

It is also given `nudge.nudger_for(sys.platform)`: on Linux a message the owner leaves a sprint with a
running manager is relayed to it (or its stopped session is woken in place) by one fixed sentence
(`agent_tools.console.nudge`); elsewhere there is no nudger and no nudge is made. It is given
`nudge.full_lister_for(sys.platform)` too (#949): before a wake the service reads the manager
profile's full session listing, and a wake of a session it no longer shows passes the sprint's
session name and settings file again; elsewhere every wake is bare.

Last, it is given `manager.stopper_for(sys.platform)` (#892): on Linux the owner's stop of a sprint
ends its manager's background session (`manager.stop_session`); elsewhere there is no stopper and a
stop is recorded without a call.

It is also given `probe.prober_for(sys.platform)` (#1009): on Linux every listed profile is read every
10 minutes by one small request under it (`agent_tools.console.probe`); elsewhere no probe is made.

It is also given `signin.reader_for(sys.platform)` (#1010): on Linux each probe job first reads the
profile's sign-in from the client's status command (`agent_tools.console.signin`); elsewhere none is read.

The service keeps the console's profile choice for new sessions in `$CLAUDE_ACCOUNTS_DIR/chosen-profile`
(else `~/.claude-accounts/chosen-profile`) and answers it on `GET /api/profile` (#1011).
"""

from __future__ import annotations

import argparse
import signal
import sqlite3
import sys
import threading

from agent_tools.console import inbox, manager, nudge, probe, service, signin
from agent_tools.console.event_log import EventLogError
from agent_tools.console.write_guard import TokenError


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
            service.default_store(), service.default_registry(), port=args.port,
            tracker=inbox.read_items, launcher=manager.launcher_for(sys.platform),
            nudger=nudge.nudger_for(sys.platform), stopper=manager.stopper_for(sys.platform),
            full_listing=nudge.full_lister_for(sys.platform),
            prober=probe.prober_for(sys.platform), signin_reader=signin.reader_for(sys.platform),
            choice_file=service.default_choice_file())
    except TokenError as error:
        print(f"console: page token unusable: {error}", file=sys.stderr)
        return 1
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
