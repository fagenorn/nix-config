"""`sprint`: a manager sends its sprint's brief to the console and reads the owner's answer (#887).

    sprint brief [--sprint <id>] [--secret-file <path>] --brief-file <path | -> [--port N]
    sprint status [--sprint <id>] [--port N]

`--sprint` is the sprint id (16 lowercase hex characters, `agent_tools.console.sprints.SPRINT_ID`),
else exit 2. Without `--sprint` the id is `$CONSOLE_SPRINT_ID`, the variable the console sets in
the manager session it starts; without `--secret-file` the secret is `$CONSOLE_SPRINT_SECRET`
(one trailing newline is removed, as from the file). A flag always wins over the environment. No id is stderr
`sprint: no sprint id: pass --sprint or set CONSOLE_SPRINT_ID`, an id from the environment that
is not a sprint id is stderr `sprint: CONSOLE_SPRINT_ID is not a sprint id (16 lowercase hex
characters)`, and, for `brief`, no secret is stderr `sprint: no secret: pass --secret-file or set
CONSOLE_SPRINT_SECRET`; each is exit 2 with no request sent. `--port` is the console's loopback
port (0-65535; default 27184); the command only ever talks to 127.0.0.1.

`sprint brief` reads the sprint's secret from `--secret-file` (the file the console made for the
sprint; one trailing newline is removed) or the environment, and the brief from `--brief-file` (`-` reads stdin), a JSON
object, and sends `POST /api/brief` with `{"sprint_id", "secret", "brief"}`, no `Origin`. On success
it prints `sprint: brief version <n> sent` and exit 0. The command validates no part of the brief:
the console decides, in one place.

`sprint status` sends `GET /api/sprint-status?sprint_id=<id>` and prints the console's answer as one
line of JSON, `{"decision", "reply", "sprint_id", "version"}`, and exit 0. `decision` is `none`
(no answer yet), `approved`, `changes` (the owner's exact words are `reply`) or `withdrawn`.

Any other HTTP status is stderr `sprint: refused <status>: <text>` (the console's reason) and
exit 1. A console that cannot be reached is stderr
`sprint: console unreachable on 127.0.0.1:<port>: <error>` and exit 1. A secret or brief file that
cannot be read, or a brief that is not a JSON object, is stderr `sprint: cannot read <path>:
<reason>` and exit 2, with no request sent; bad arguments are exit 2. The secret is printed nowhere.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
from pathlib import Path

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.console import manager, service, sprints
from agent_tools.console.console import port_number

TIMEOUT_SECONDS = 10


class Unreadable(Exception):
    """An input the command cannot read; `str` is the stderr line."""


class Refused(Exception):
    """The console answered with something other than 200, or could not be reached."""


def sprint_id(text: str) -> str:
    if sprints.SPRINT_ID.fullmatch(text) is None:
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a sprint id (16 lowercase hex characters)")
    return text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sprint", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (("brief", "send the sprint's brief to the console"),
                       ("status", "print the owner's answer to the sprint's brief")):
        each = commands.add_parser(name, help=text)
        each.add_argument("--sprint", type=sprint_id, default=None,
                          help=f"the sprint id (default: ${manager.ID_ENV})")
        each.add_argument("--port", type=port_number, default=service.DEFAULT_PORT,
                          help="the console's loopback port (default: %(default)s)")
        if name == "brief":
            each.add_argument("--secret-file", type=Path, default=None,
                              help="the file holding the sprint's secret "
                                   f"(default: ${manager.SECRET_ENV})")
            each.add_argument("--brief-file", required=True,
                              help="the brief as a JSON object; - reads stdin")
    return parser


def read_secret(path: Path) -> str:
    try:
        return path.read_text().removesuffix("\n")
    except (OSError, UnicodeDecodeError) as error:
        raise Unreadable(f"sprint: cannot read {path}: {error}") from error


def read_brief(name: str) -> dict:
    try:
        text = sys.stdin.read() if name == "-" else Path(name).read_text()
        brief = json.loads(text, object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except (OSError, ValueError) as error:
        raise Unreadable(f"sprint: cannot read {name}: {error}") from error
    if not isinstance(brief, dict):
        raise Unreadable(f"sprint: cannot read {name}: the brief is not a JSON object")
    return brief


def ask(port: int, method: str, path: str, body: bytes | None = None) -> str:
    """The console's answer text to one request, or `Refused` carrying the stderr line."""
    headers = {"Content-Type": "application/json"} if body is not None else {}
    connection = http.client.HTTPConnection(service.HOST, port, timeout=TIMEOUT_SECONDS)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        text = response.read().decode("utf-8", "replace").strip()
    except (OSError, http.client.HTTPException) as error:
        raise Refused(f"sprint: console unreachable on {service.HOST}:{port}: {error}") from error
    finally:
        connection.close()
    if response.status != 200:
        raise Refused(f"sprint: refused {response.status}: {text}")
    return text


def resolve_sprint(args: argparse.Namespace) -> str:
    """The sprint id: the flag, else the manager's environment, else `Unreadable`."""
    if args.sprint is not None:
        return args.sprint
    text = os.environ.get(manager.ID_ENV)
    if text is None:
        raise Unreadable(f"sprint: no sprint id: pass --sprint or set {manager.ID_ENV}")
    if sprints.SPRINT_ID.fullmatch(text) is None:
        raise Unreadable(f"sprint: {manager.ID_ENV} is not a sprint id "
                         "(16 lowercase hex characters)")
    return text


def resolve_secret(args: argparse.Namespace) -> str:
    """The secret: the flag's file, else the manager's environment, else `Unreadable`."""
    if args.secret_file is not None:
        return read_secret(args.secret_file)
    secret = os.environ.get(manager.SECRET_ENV)
    if secret is None:
        raise Unreadable(f"sprint: no secret: pass --secret-file or set {manager.SECRET_ENV}")
    return secret.removesuffix("\n")


def send_brief(args: argparse.Namespace, sprint: str) -> str:
    secret = resolve_secret(args)
    brief = read_brief(args.brief_file)
    body = json.dumps({"sprint_id": sprint, "secret": secret, "brief": brief}).encode()
    text = ask(args.port, "POST", service.BRIEF_PATH, body)
    try:
        return f"sprint: brief version {json.loads(text)['version']} sent"
    except (ValueError, KeyError, TypeError) as error:
        raise Refused(f"sprint: refused 200: unreadable answer: {error}") from error


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        sprint = resolve_sprint(args)
        if args.command == "brief":
            line = send_brief(args, sprint)
        else:
            line = ask(args.port, "GET", f"{service.STATUS_PATH}?sprint_id={sprint}")
    except Unreadable as error:
        print(error, file=sys.stderr)
        return 2
    except Refused as error:
        print(error, file=sys.stderr)
        return 1
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
