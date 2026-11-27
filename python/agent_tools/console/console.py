"""`console`: serve the lead console on loopback until stopped (#855).

`console [--port N]` binds 127.0.0.1 only, on N (default 27184; 0 picks a free port), and serves
the desk page, `GET /api/state` and the `GET /api/stream` update stream
(`agent_tools.console.service` holds the routes and the stream's frame). The event log is
`~/.agents/state/console/events.sqlite3`; the fleet registry it follows, and never writes, is
`~/.agents/state/fleet/registry.json`. The page's write token is created once in
`~/.agents/state/console/page-token` (mode 0600) and kept across restarts. Every two minutes it also reads the owner-action items of
each active project from the tracker into the log (`agent_tools.console.service` holds the rules).
The owner port answers only processes of the user the console runs as (`agent_tools.console.peer`,
ADR-console-076).

Once serving it prints exactly one stdout line, `console: serving http://127.0.0.1:<port>/`.
SIGTERM or SIGINT closes the service and exits 0. A port that cannot be bound is stderr
`console: cannot listen on 127.0.0.1:<port>: <error>` and exit 1; an event log that cannot be
used (a schema version this build does not read, a database error) is stderr
`console: event log unusable: <error>` and exit 1; a page token that cannot be read or is malformed is
stderr `console: page token unusable: <error>` and exit 1. A bad argument is exit 2.

The service is given `manager.launcher_for(sys.platform)`: on Linux and macOS a stated goal starts that
sprint's manager (`agent_tools.console.manager`), elsewhere there is no launcher and every sprint
says managers are not available on this host yet.

It is also given `nudge.nudger_for(sys.platform)`: on Linux and macOS a message the owner leaves a sprint with a
running manager is relayed to it (or its stopped session is woken in place) by one fixed sentence
(`agent_tools.console.nudge`); elsewhere there is no nudger and no nudge is made. It is given
`nudge.full_lister_for(sys.platform)` too (#949): before a wake the service reads the manager
profile's full session listing, and a wake of a session it no longer shows passes the sprint's
session name and settings file again; elsewhere every wake is bare.

Last, it is given `manager.stopper_for(sys.platform)` (#892): on Linux and macOS the owner's stop of a sprint
ends its manager's background session (`manager.stop_session`); elsewhere there is no stopper and a
stop is recorded without a call.

It is also given `probe.prober_for(sys.platform)` (#1009): on Linux and macOS every listed profile is read every
10 minutes by one small request under it (`agent_tools.console.probe`); elsewhere no probe is made.

It is also given `signin.reader_for(sys.platform)` (#1010): on Linux and macOS each probe job first reads the
profile's sign-in from the client's status command (`agent_tools.console.signin`); elsewhere none is read.

It is also given `signin_run.runs_for(sys.platform)` (#1026): on Linux and macOS the owner starts, passes
a code to and cancels a profile's own client login from the page (`agent_tools.console.signin_run`);
elsewhere there are no runs and the sign-in routes refuse.

It is also given `account_add.adder_for(sys.platform)` (#1027), so on Linux and macOS the owner adds an account
from the page through `claude-account add` (`agent_tools.console.account_add`).

It is also given `account_remove.signer_out_for(sys.platform)` and `account_remove.remover_for(sys.platform)`
(#1030), so on Linux and macOS the owner removes an account from the page, signed out first
(`agent_tools.console.account_remove`).

It is also given `register.adopter_for(sys.platform)` (#1052), so on Linux and macOS the owner names a
repository on the page and sees what adopting it would change, or registers it when it is adopted
(`agent_tools.console.register`); elsewhere the route refuses.

It is also given `project_question.asker_for(sys.platform)` (#1176): on Linux and macOS a question from the page
about a registered project starts one read-only session under a chosen account
(`agent_tools.console.project_question`) and its answer is recorded in the log; elsewhere the route
refuses.

It is also given `trust_home=Path.home()` (#1078), so the owner's Apply approval grants the folder's
client trust in `~/.claude.json` as well as in every profile (`agent_tools.console.folder_trust`).
It is given `trust_at_start` (#1183), so every registered project is granted its folder trust in every
profile at start.

`--guest-socket PATH` (absolute, no default) makes the guest door a Unix socket at PATH inside a
mode-0700 folder the console creates (#1299, ADR-console-077); a socket that cannot be made, or one
another console still listens on, is `console: cannot listen on unix:<PATH>: <error>`, exit 1. Without
it there is no guest door.

`--tailscale PATH` (no default) names this host's Tailscale client (#1237): it is read with
`serve status --json` every minute to show whether Serve proxies the tailnet name to the guest socket,
and with `status --json` for this host's own tailnet name, the one name the guest door admits
(#1305, ADR-console-078; `agent_tools.console.guest`), and for its own addresses (`Self.TailscaleIPs`),
which tell its own requests from another device's (ADR-console-079). Without it the console never reads Serve, shows
the state as unchecked and its guest door shares with nobody.

It is also given `approve.forge_for(sys.platform)` (#1054), so on Linux and macOS the owner approves a ready
plan and the console pushes its branch and opens its pull request through `gh`; elsewhere the route
refuses.

It is also given `pull_reader=movement.read_pulls` (#1110), so a running sprint's pull requests are read
from the forge to name what it waits on (`agent_tools.console.movement`), and `title_reader=movement.read_titles`,
so a running sprint's issues are named by their titles from the tracker.

Every minute it compares the console's own files, and the files the host's configuration is built from
(from the host's configuration revision), with the integration branch on origin as the console's
checkout last fetched it (`agent_tools.console.activation`), on every platform; the page says when a
`just switch` would change what the host runs.

The service keeps the console's profile choice for new sessions in `$CLAUDE_ACCOUNTS_DIR/chosen-profile`
(else `~/.claude-accounts/chosen-profile`) and answers it on `GET /api/profile` (#1011).

It is also given the `--screenshots` locations (#1112), `--screenshots DIR` repeated for each: a
picture a manual check names inside one of them, beside the project's own checkout, is stored and shown
on the check's card (`agent_tools.console.inbox`). With none given, only the project's checkout is read.

`--lock-bump-project O/N`, `--lock-bump-branch B` and `--platform-repo O/N` (all three or none) make the
console also run a lock bump pass for that one project every ten minutes (`agent_tools.console.lock_bump`):
each proven revision is offered to it as one pull request that is merged on green required checks. The
record of the last bump is `~/.agents/state/console/lock-bumps.json`; each step is a `console: lock_bump` line.
"""

from __future__ import annotations

import argparse
import re
import signal
import sqlite3
import sys
import threading
from pathlib import Path

import agent_tools
from agent_tools.console import (
    account_add, activation, activation_run, account_remove, approve, inbox, lock_bump, manager, movement, nudge,
    probe, guest, project_question, register, service, signin, signin_run)
from agent_tools.delivery import engine_ledger
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


def socket_path(text: str) -> Path:
    path = Path(text)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError(f"{text!r} is not an absolute path")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="console", description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=port_number, default=service.DEFAULT_PORT,
                        help="loopback port to listen on (0 picks a free one; default: %(default)s)")
    parser.add_argument("--guest-socket", type=socket_path, default=None, metavar="PATH",
                        help="absolute path of the guest door, a Unix socket for Tailscale Serve "
                             "(default: no guest door)")
    parser.add_argument("--tailscale", metavar="PATH", default=None,
                        help="this host's Tailscale client, read with `serve status --json` every minute "
                             "to show whether Serve proxies the tailnet name to the guest socket, and "
                             "with `status --json` for this host's tailnet name; without it the guest "
                             "door shares with nobody")
    parser.add_argument("--screenshots", type=Path, action="append", default=[], metavar="DIR",
                        help="a folder whose PNGs a manual check may show (repeatable)")
    parser.add_argument("--lock-bump-project", metavar="O/N", default=None,
                        help="the one registered project whose platform lock the console bumps (needs the "
                             "other two lock bump flags)")
    parser.add_argument("--lock-bump-branch", metavar="B", default=None,
                        help="the integration branch of that project")
    parser.add_argument("--platform-repo", metavar="O/N", default=None,
                        help="the platform repository whose proven revisions are offered")
    return parser


SLUG = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")


def lock_bump_flags(parser: argparse.ArgumentParser, args: argparse.Namespace) -> bool:
    """Whether a lock bump is asked for; a partial or malformed set of its flags is a usage error."""
    given = (args.lock_bump_project, args.lock_bump_branch, args.platform_repo)
    if all(value is None for value in given):
        return False
    if any(value is None for value in given):
        parser.error("--lock-bump-project, --lock-bump-branch and --platform-repo are given together")
    if (SLUG.fullmatch(args.lock_bump_project) is None or SLUG.fullmatch(args.platform_repo) is None
            or not args.lock_bump_branch):
        parser.error("the lock bump project and platform repository are owner/name, the branch is not empty")
    return True


def lock_bumper(args: argparse.Namespace) -> lock_bump.Bumper | None:
    if args.lock_bump_project is None:
        return None
    return lock_bump.Bumper(args.lock_bump_project, args.lock_bump_branch, args.platform_repo)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    lock_bump_flags(parser, args)
    try:
        console = service.ConsoleService(
            service.default_store(), service.default_registry(), port=args.port, guest_socket=args.guest_socket,
            tracker=inbox.read_items, pull_reader=movement.read_pulls,
            title_reader=movement.read_titles, launcher=manager.launcher_for(sys.platform),
            nudger=nudge.nudger_for(sys.platform), stopper=manager.stopper_for(sys.platform),
            full_listing=nudge.full_lister_for(sys.platform),
            prober=probe.prober_for(sys.platform), signin_reader=signin.reader_for(sys.platform),
            signin_runs=signin_run.runs_for(sys.platform),
            account_adder=account_add.adder_for(sys.platform),
            signer_out=account_remove.signer_out_for(sys.platform),
            account_remover=account_remove.remover_for(sys.platform),
            adopter=register.adopter_for(sys.platform),
            project_asker=project_question.asker_for(sys.platform),
            forge=approve.forge_for(sys.platform), trust_home=Path.home(), trust_at_start=True,
            activation_reader=activation.reader_for(
                Path(agent_tools.__file__).resolve().parent.parent, revision=activation_run.host_revision),
            activator=activation_run.Activator(service.default_store().parent),
            choice_file=service.default_choice_file(), screenshot_dirs=args.screenshots,
            serve_reader=None if args.tailscale is None else guest.serve_reader(args.tailscale),
            status_reader=None if args.tailscale is None else guest.status_reader(args.tailscale),
            engine_runs_root=engine_ledger.runs_root())
    except TokenError as error:
        print(f"console: page token unusable: {error}", file=sys.stderr)
        return 1
    except (EventLogError, sqlite3.Error) as error:
        print(f"console: event log unusable: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        where = (f"unix:{error.path}" if isinstance(error, service.GuestSocketError)
                 else f"{service.HOST}:{args.port}")
        print(f"console: cannot listen on {where}: {error}", file=sys.stderr)
        return 1
    stop = threading.Event()
    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, lambda *_: stop.set())
    bumping = None
    try:
        console.start()
        print(f"console: serving http://{service.HOST}:{console.address[1]}/", flush=True)
        bumper = lock_bumper(args)
        if bumper is not None:
            bumping = lock_bump.start(bumper, stop)
        while not stop.wait(1.0):
            pass
    finally:
        stop.set()
        if bumping is not None:
            bumping.join(30.0)
        console.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
