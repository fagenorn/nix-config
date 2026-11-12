"""`sprint`: a manager sends its sprint's brief, report and closing report and reads the owner's answer.

    sprint brief [--sprint <id>] [--secret-file <path>] --brief-file <path | -> [--port N]
    sprint report [--sprint <id>] [--secret-file <path>] --report-file <path | -> [--port N]
    sprint ask [--sprint <id>] [--secret-file <path>] --round-file <path | -> [--port N]
    sprint close [--sprint <id>] [--secret-file <path>] --closing-file <path | -> [--port N]
    sprint inbox [--sprint <id>] [--secret-file <path>] [--port N]
    sprint recap [--sprint <id>] [--secret-file <path>] [--port N]
    sprint reply [--sprint <id>] [--secret-file <path>] --message <id> --reply-file <path | -> [--port N]
    sprint status [--sprint <id>] [--port N]
    sprint contract

`--sprint` is the sprint id (16 lowercase hex characters, `agent_tools.console.sprints.SPRINT_ID`),
else exit 2. Without `--sprint` the id is `$CONSOLE_SPRINT_ID`, the variable the console sets in
the manager session it starts; without `--secret-file` the secret is `$CONSOLE_SPRINT_SECRET`
(one trailing newline is removed, as from the file). A flag always wins over the environment. No id is stderr
`sprint: no sprint id: pass --sprint or set CONSOLE_SPRINT_ID`, an id from the environment that
is not a sprint id is stderr `sprint: CONSOLE_SPRINT_ID is not a sprint id (16 lowercase hex
characters)`, and, for `brief`, `report`, `ask`, `close`, `inbox`, `recap` and `reply`, no secret is stderr `sprint: no secret: pass --secret-file or set
CONSOLE_SPRINT_SECRET`; each is exit 2 with no request sent. `--port` is the console's loopback
port (0-65535; default 27184); the command only ever talks to 127.0.0.1.

`sprint brief` reads the sprint's secret from `--secret-file` (the file the console made for the
sprint; one trailing newline is removed) or the environment, and the brief from `--brief-file` (`-` reads stdin), a JSON
object, and sends `POST /api/brief` with `{"sprint_id", "secret", "brief"}`, no `Origin`. On success
it prints `sprint: brief version <n> sent` and exit 0. The command validates no part of the brief:
the console decides, in one place.

`sprint report` reads the secret the same way and the report from `--report-file` (`-` reads stdin),
a JSON object, and sends `POST /api/report` with `{"sprint_id", "secret", "report"}`, no `Origin`.
On success it prints `sprint: report sent` and exit 0. The command validates no member of the
report: the console decides, in one place.

`sprint ask` reads the secret the same way and the round from `--round-file` (`-` reads stdin), a
JSON object, and sends `POST /api/ask` with `{"sprint_id", "secret", "round"}`, no `Origin`. The
round is

    {"questions": [{"question": "<text>", "blocks": "<one line>", "options": ["<one line>", ...],
                    "recommended": "<exact text of one option>"}, ...],
     "blocker": true | false}                   (blocker optional, default false)

On success it prints `sprint: round <id> sent, <n> questions` (`1 question` when n is 1) and exit
0; a 200 answer without integer `round` and `questions` is `sprint: refused 200: unreadable
answer: <error>` and exit 1. The command validates no member of the round: the console decides,
in one place.

`sprint report --help` and `sprint close --help` list the members of the report and of the closing
report, each with one line and an example, the same lists `sprint contract` prints.

`sprint close` reads the secret the same way and the closing report from `--closing-file` (`-` reads
stdin), a JSON object, and sends `POST /api/close` with `{"sprint_id", "secret", "closing"}`, no
`Origin`. On success it prints `sprint: closing report sent` and exit 0. The command validates no
member of the closing report: the console decides, in one place.

`sprint inbox` reads the secret the same way and sends `POST /api/inbox` with
`{"sprint_id", "secret"}`, no `Origin`. It prints the console's answer as one line of JSON,
`{"messages": [{"id", "kind", "version", "text", "at"}, ...]}`: the owner's messages the manager has
not read, in id order, each once, and exit 0. An answer to one of the manager's questions (kind
`answer`) also carries `"question"` (the question's text), `"round"` (the round id) and `"chosen"`
(the option's text, or null for the owner's own words). An inbox with nothing unread is
`{"messages": []}`.

`sprint recap` reads the secret the same way and sends `POST /api/recap` with `{"sprint_id",
"secret"}`, no `Origin`. It prints the console's answer as one line of JSON, `{"sprint_id", "goal",
"brief", "report", "unread"}`, and exit 0: the goal, the latest brief (`version`, `decision`,
`reply`, `parts`, or null), the last report (or null) and the number of the owner's unread
messages. It marks nothing read; a manager that was restarted or takes a sprint over runs it, then
`sprint inbox`.

`sprint reply` reads the secret the same way and the reply from `--reply-file` (`-` reads stdin) as
UTF-8 text with one trailing newline removed, and sends `POST /api/message-reply` with
`{"sprint_id", "secret", "message", "reply"}`, no `Origin`. `--message` is the id of a message
`sprint inbox` printed: an integer of at least 1, else exit 2. On success it prints
`sprint: reply to message <id> sent` and exit 0. The command validates nothing about a message or a
reply beyond reading it: the console decides, in one place.

`sprint status` sends `GET /api/sprint-status?sprint_id=<id>` and prints the console's answer as one
line of JSON, `{"decision", "reply", "sprint_id", "version"}`, and exit 0. `decision` is `none`
(no answer yet), `approved`, `changes` (the owner's exact words are `reply`) or `withdrawn`.

`sprint contract` prints the manager's contract, the document `manager-contract.md` packaged
beside this module, to stdout exactly as packaged and exit 0. It takes no sprint id, secret or
port, reads no environment and sends no request; the console's launch prompt tells the manager to
run it first (ADR-console-015).

Any other HTTP status is stderr `sprint: refused <status>: <text>` (the console's reason) and
exit 1. A console that cannot be reached is stderr
`sprint: console unreachable on 127.0.0.1:<port>: <error>` and exit 1. A secret, brief, report, closing report, round or reply file
that cannot be read, or a brief, report, closing report or round that is not a JSON object, is stderr `sprint: cannot read <path>:
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
REPORT_HELP = """the report's members, all required:
  status:      one line, at most 500 characters; it names no issue number (no # and a digit)
  phase:       one of running, closing, done
  milestone:   one line, the tracker milestone of the sprint's issues
  tracker_url: the milestone's link, starting with https://
  issues:      every issue of the sprint, [{"issue": 12, "stage": "building"}, ...], no issue
               twice; a stage is one of queued, planning, plan review, building, final review,
               verifying, landing, working, landed, held
  inbox:       the numbers of the issues waiting on the owner, [12], empty when none
  next:        one line, what the manager does next

example:
  {"status": "two slices are building and one has landed", "phase": "running",
   "milestone": "Importer resumes after a crash",
   "tracker_url": "https://github.com/example/importer/milestone/3",
   "issues": [{"issue": 12, "stage": "building"}, {"issue": 13, "stage": "landed"}],
   "inbox": [12], "next": "start the resume slice when 12 lands"}
"""
CLOSING_HELP = """the closing report's members, all required:
  summary:     what the sprint did, at most 4000 characters; its first line is at most
               500 characters and one plain sentence with no issue number (no # and a digit)
  issues:      every issue of the sprint, [{"issue": 12, "stage": "landed"}, ...], no issue
               twice; a stage is one of landed, held, dropped, and every issue of the last
               report needs one
  differently: what the manager would do differently next time, at most 4000 characters

example:
  {"summary": "The importer resumes after a crash.\\nSlice 12 landed and slice 13 was dropped.",
   "issues": [{"issue": 12, "stage": "landed"}, {"issue": 13, "stage": "dropped"}],
   "differently": "I would cut the checkpoint slice smaller."}
"""
CONTRACT = Path(__file__).with_name("manager-contract.md")


class Unreadable(Exception):
    """An input the command cannot read; `str` is the stderr line."""


class Refused(Exception):
    """The console answered with something other than 200, or could not be reached."""


def sprint_id(text: str) -> str:
    if sprints.SPRINT_ID.fullmatch(text) is None:
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a sprint id (16 lowercase hex characters)")
    return text


def message_id(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not a message id (an integer of at least 1)")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sprint", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (("brief", "send the sprint's brief to the console"),
                       ("report", "send the sprint's report to the console"),
                       ("ask", "send one round of questions to the owner"),
                       ("close", "send the sprint's closing report"),
                       ("inbox", "print the owner's unread messages to the sprint"),
                       ("recap", "print what a manager needs to pick the sprint up"),
                       ("reply", "answer one of the owner's messages"),
                       ("status", "print the owner's answer to the sprint's brief")):
        epilog = {"report": REPORT_HELP, "close": CLOSING_HELP}.get(name)
        each = commands.add_parser(
            name, help=text, epilog=epilog,
            formatter_class=argparse.RawDescriptionHelpFormatter if epilog else
            argparse.HelpFormatter)
        each.add_argument("--sprint", type=sprint_id, default=None,
                          help=f"the sprint id (default: ${manager.ID_ENV})")
        each.add_argument("--port", type=port_number, default=service.DEFAULT_PORT,
                          help="the console's loopback port (default: %(default)s)")
        if name != "status":
            each.add_argument("--secret-file", type=Path, default=None,
                              help="the file holding the sprint's secret "
                                   f"(default: ${manager.SECRET_ENV})")
            if name in ("brief", "report", "ask"):
                flag, what = (("--round-file", "round") if name == "ask"
                              else (f"--{name}-file", name))
                each.add_argument(flag, required=True,
                                  help=f"the {what} as a JSON object; - reads stdin")
            if name == "close":
                each.add_argument("--closing-file", required=True,
                                  help="the closing report as a JSON object; - reads stdin")
        if name == "reply":
            each.add_argument("--message", type=message_id, required=True,
                              help="the id of the message being answered")
            each.add_argument("--reply-file", required=True,
                              help="the reply as text; - reads stdin")
    commands.add_parser("contract", help="print the manager's contract")
    return parser


def read_secret(path: Path) -> str:
    try:
        return path.read_text().removesuffix("\n")
    except (OSError, UnicodeDecodeError) as error:
        raise Unreadable(f"sprint: cannot read {path}: {error}") from error


def read_text(name: str) -> str:
    """The reply text, stdin for `-`, with one trailing newline removed."""
    try:
        text = sys.stdin.read() if name == "-" else Path(name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise Unreadable(f"sprint: cannot read {name}: {error}") from error
    return text.removesuffix("\n")


def read_object(name: str, what: str) -> dict:
    try:
        text = sys.stdin.read() if name == "-" else Path(name).read_text()
        value = json.loads(text, object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except (OSError, ValueError) as error:
        raise Unreadable(f"sprint: cannot read {name}: {error}") from error
    if not isinstance(value, dict):
        raise Unreadable(f"sprint: cannot read {name}: the {what} is not a JSON object")
    return value


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
    brief = read_object(args.brief_file, "brief")
    body = json.dumps({"sprint_id": sprint, "secret": secret, "brief": brief}).encode()
    text = ask(args.port, "POST", service.BRIEF_PATH, body)
    try:
        return f"sprint: brief version {json.loads(text)['version']} sent"
    except (ValueError, KeyError, TypeError) as error:
        raise Refused(f"sprint: refused 200: unreadable answer: {error}") from error


def send_round(args: argparse.Namespace, sprint: str) -> str:
    secret = resolve_secret(args)
    round_ = read_object(args.round_file, "round")
    body = json.dumps({"sprint_id": sprint, "secret": secret, "round": round_}).encode()
    text = ask(args.port, "POST", service.ASK_PATH, body)
    try:
        answer = json.loads(text)
        sent, questions = answer["round"], answer["questions"]
        if any(type(n) is not int for n in (sent, questions)):
            raise TypeError("round and questions are not both integers")
    except (ValueError, KeyError, TypeError) as error:
        raise Refused(f"sprint: refused 200: unreadable answer: {error}") from error
    noun = "question" if questions == 1 else "questions"
    return f"sprint: round {sent} sent, {questions} {noun}"


def send_report(args: argparse.Namespace, sprint: str) -> str:
    secret = resolve_secret(args)
    report = read_object(args.report_file, "report")
    body = json.dumps({"sprint_id": sprint, "secret": secret, "report": report}).encode()
    ask(args.port, "POST", service.REPORT_PATH, body)
    return "sprint: report sent"


def send_closing(args: argparse.Namespace, sprint: str) -> str:
    secret = resolve_secret(args)
    closing = read_object(args.closing_file, "closing report")
    body = json.dumps({"sprint_id": sprint, "secret": secret, "closing": closing}).encode()
    ask(args.port, "POST", service.CLOSE_PATH, body)
    return "sprint: closing report sent"


def read_inbox(args: argparse.Namespace, sprint: str) -> str:
    secret = resolve_secret(args)
    body = json.dumps({"sprint_id": sprint, "secret": secret}).encode()
    return ask(args.port, "POST", service.INBOX_PATH, body)


def read_recap(args: argparse.Namespace, sprint: str) -> str:
    secret = resolve_secret(args)
    body = json.dumps({"sprint_id": sprint, "secret": secret}).encode()
    return ask(args.port, "POST", service.RECAP_PATH, body)


def send_reply(args: argparse.Namespace, sprint: str) -> str:
    secret = resolve_secret(args)
    reply = read_text(args.reply_file)
    body = json.dumps({"sprint_id": sprint, "secret": secret, "message": args.message,
                       "reply": reply}).encode()
    ask(args.port, "POST", service.MESSAGE_REPLY_PATH, body)
    return f"sprint: reply to message {args.message} sent"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "contract":
        sys.stdout.write(CONTRACT.read_text(encoding="utf-8"))
        return 0
    try:
        sprint = resolve_sprint(args)
        if args.command == "brief":
            line = send_brief(args, sprint)
        elif args.command == "report":
            line = send_report(args, sprint)
        elif args.command == "ask":
            line = send_round(args, sprint)
        elif args.command == "close":
            line = send_closing(args, sprint)
        elif args.command == "inbox":
            line = read_inbox(args, sprint)
        elif args.command == "recap":
            line = read_recap(args, sprint)
        elif args.command == "reply":
            line = send_reply(args, sprint)
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
