"""`sprint`: a manager sends its sprint's brief, report and closing report and reads the owner's answer.

    sprint brief [--sprint <id>] [--secret-file <path>] --brief-file <path | -> [--port N]
    sprint report [--sprint <id>] [--secret-file <path>] --report-file <path | -> [--port N]
    sprint ask [--sprint <id>] [--secret-file <path>] --round-file <path | -> [--port N]
    sprint close [--sprint <id>] [--secret-file <path>] --closing-file <path | -> [--port N]
    sprint inbox [--sprint <id>] [--secret-file <path>] [--port N]
    sprint recap [--sprint <id>] [--secret-file <path>] [--port N]
    sprint withdraw-question [--sprint <id>] [--secret-file <path>] --round <id> --index <n> [--port N]
    sprint notice [--sprint <id>] [--secret-file <path>] --notice-file <path | -> [--port N]
    sprint notices [--sprint <id>] [--secret-file <path>] [--port N]
    sprint withdraw-notice [--sprint <id>] [--secret-file <path>] --notice <id> [--port N]
    sprint reply [--sprint <id>] [--secret-file <path>] --message <id> --reply-file <path | -> [--port N]
    sprint picture [--sprint <id>] [--secret-file <path>] --file <path> [--port N]
    sprint status [--sprint <id>] [--secret-file <path>] [--port N]
    sprint contract

`--sprint` is the sprint id (16 lowercase hex characters, `agent_tools.console.sprints.SPRINT_ID`),
else exit 2. Without `--sprint` the id is `$CONSOLE_SPRINT_ID`, the variable the console sets in
the manager session it starts; without `--secret-file` the secret is `$CONSOLE_SPRINT_SECRET`
(one trailing newline is removed, as from the file). A flag always wins over the environment. No id is stderr
`sprint: no sprint id: pass --sprint or set CONSOLE_SPRINT_ID`, an id from the environment that
is not a sprint id is stderr `sprint: CONSOLE_SPRINT_ID is not a sprint id (16 lowercase hex
characters)`, and, for `brief`, `report`, `ask`, `withdraw-question`, `notice`, `notices`, `withdraw-notice`, `close`, `inbox`, `recap`, `reply` and `picture`, no secret is stderr `sprint: no secret: pass --secret-file or set
CONSOLE_SPRINT_SECRET`; each is exit 2 with no request sent. `--port` is the console's loopback
port (0-65535; default 27184); the command only ever talks to 127.0.0.1.

`sprint brief` reads the sprint's secret from `--secret-file` (the file the console made for the
sprint; one trailing newline is removed) or the environment, and the brief from `--brief-file` (`-` reads stdin), a JSON
object of six parts, `title` first (one line of at most 60 characters), then `done`, `excluded`,
`slices`, `risks` and `asks`, and optionally `pictures`, and sends `POST /api/brief` with
`{"sprint_id", "secret", "brief"}`, no `Origin`. On success it prints `sprint: brief version <n>
sent` and exit 0. The command validates no part beyond the pictures' own rules: the console
decides, in one place.

`sprint report` reads the secret the same way and the report from `--report-file` (`-` reads stdin),
a JSON object, and sends `POST /api/report` with `{"sprint_id", "secret", "report"}`, no `Origin`.
On success it prints `sprint: report sent` and exit 0. The command validates no member beyond the
pictures' own rules: the console decides, in one place.

`pictures` is optional on a brief and on a report, at most 8, each member
`{"file": "<path>", "line": "<one line, at most 140 characters>", "pair": "before" | "after"}`
with `pair` optional. As `sprint ask` does for a round, the command uploads each `file` and sends
the member with `"picture": "<id>"` in place of `"file"`; a member with `"picture"` and no `"file"`
is sent as given, and a brief or report with no `file` member goes as given with no local check. With
a `file` member, in this order and stopping at the first refusal: it checks the brief or report with
the console's own rules (`agent_tools.console.sprints.checked_brief` or `checked_report`) and the
size of the whole request with each picture's id in place (the console takes at most 32768 bytes
for a brief and 65536 for a report), and a refusal is stderr `sprint: refused before sending:
<reason>` and exit 1, including
`the brief is larger than <limit> bytes` and
`the report is larger than <limit> bytes`; it checks that the secret is printable ASCII, because
the uploads carry it in a header (stderr `sprint: the secret is not printable ASCII, so it cannot
go in a header: no request sent`, exit 2, nothing uploaded or sent; a brief or report with no
`file` member carries the secret in its body and is not subject to this check); it reads every file
before it uploads any, and a file that cannot be read, or one over 2 MiB, is exit 2 with nothing
uploaded or sent; before it uploads anything it asks the
console to check the brief or report with its `file` members left out (`"dry_run": true`, which
writes nothing), and a refusal there is exit 1 with nothing uploaded; then it uploads each file in
order. A picture refused while uploading (for example one that is not a PNG) is exit 1, and the
brief or report is not sent: a picture refused while uploading stops the command before the brief
or report is sent; the pictures uploaded before it stay stored, named by nothing, until the console's
sweep removes them.

`sprint ask` reads the secret the same way and the round from `--round-file` (`-` reads stdin), a
JSON object, and sends `POST /api/ask` with `{"sprint_id", "secret", "round"}`, no `Origin`. The
round is

    {"questions": [{"question": "<the ask, at most 140 characters>",
                    "context": "<optional, at most 400 characters>", "blocks": "<one line>",
                    "options": ["<one line, at most 80 characters>", ...],
                    "recommended": "<exact text of one option>",
                    "pictures": [{"file": "<path>", "line": "<one line, at most 140 characters>",
                                  "pair": "before" | "after"}, ...],
                    "replaces": {"round": <id>, "index": <n>}}, ...],
     "blocker": true | false}                   (blocker optional, default false)

`replaces` is optional: it names one open question of this sprint by its round id and its index (from 0,
in the order the round was sent), and the console takes that question back in the write that
accepts the new one. The command sends it as given and validates no more than it did: the console decides.

`pictures` is optional, at most 8 to a question, and `pair` is optional; a question whose ask or context
names screenshots, a `.png` file or a screenshots folder must carry one, else the console refuses the
round with the question named (`sprint: refused 409: ...`), and a round with `file` members is
refused before sending. The command uploads each
`file` as `sprint picture` does (a relative path is read from the current directory) and sends the
member with `"picture": "<id>"` in place of `"file"`; a member with `"picture"` and no `"file"` is
sent as given. Before it reads or sends anything it checks the round's pictures with the console's
own rules (`agent_tools.console.sprints.checked_round`) and the size of the whole request with
each picture's id in place (the console takes at most 65536 bytes): a refusal is stderr `sprint:
refused before sending: <reason>` and exit 1. It then reads every file before it uploads any: a file that
cannot be read, or one over 2 MiB, is exit 2 and nothing is uploaded or sent. Whether a picture
belongs to the sprint, and the sprint's state, stay the console's to decide: before it uploads
anything it asks the console to check the round with its `file` members left out (`"dry_run":
true`, which writes nothing), and a refusal there is exit 1 with nothing uploaded.

On success it prints `sprint: round <id> sent, <n> questions` (`1 question` when n is 1) and exit
0; a 200 answer without integer `round` and `questions` is `sprint: refused 200: unreadable
answer: <error>` and exit 1. Beyond the pictures' own rules the command validates no member of the
round: the console decides, in one place.

`sprint withdraw-question` reads the secret the same way and sends `POST /api/withdraw-question` with
`{"sprint_id", "secret", "round", "index"}`, no `Origin`, for the question `--index` (an integer of at
least 0, counting from 0 in the order the round was sent) of the round `--round` (an integer of at
least 1); anything else is exit 2 with no request sent. On success it prints `sprint: round <r>
question <i> withdrawn` and exit 0; a refusal (an answered question, one already withdrawn, another
sprint's question, a wrong secret) is `sprint: refused <status>: <text>` and exit 1, and a 200 answer
without integer `round` and `index` is `sprint: refused 200: unreadable answer: <error>` and exit 1.

`sprint notice` reads the secret the same way and the notice from `--notice-file` (`-` reads stdin),
a JSON object (`kind` and the members of that kind), and sends `POST /api/notice` with
`{"sprint_id", "secret", "notice"}`, no `Origin`. On success it prints `sprint: notice <id> posted`
and exit 0. The command validates no member of the notice: the console decides, in one place, and a
refusal is `sprint: refused <status>: <text>` and exit 1. A file that cannot be read or is not a JSON
object is exit 2 with no request sent; a 200 answer without an integer `notice` is `sprint: refused
200: unreadable answer: <error>` and exit 1.

`sprint notices` reads the secret the same way and sends `POST /api/notices` with `{"sprint_id",
"secret"}`, no `Origin`. It prints the console's answer as returned, one JSON line `{"notices":
[...]}` of the open notices of the sprint's project, oldest first, and exit 0.

`sprint withdraw-notice` reads the secret the same way and sends `POST /api/withdraw-notice` with
`{"sprint_id", "secret", "notice"}`, no `Origin`, for the notice `--notice` (an integer of at least
1, the id `sprint notice` printed); anything else is exit 2 with no request sent. On success it prints
`sprint: notice <id> withdrawn` and exit 0; a refusal (a notice already ended, another sprint's
notice, a wrong secret) is `sprint: refused <status>: <text>` and exit 1, and a 200 answer without an
integer `notice` is `sprint: refused 200: unreadable answer: <error>` and exit 1.

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
`{"messages": []}`. Before the inbox request the command sends `POST /api/notices` with the same body
and, after the JSON line, prints `sprints.notice_block` of that answer: the open notices of the
project's other sprints, the head line and then one line each, and nothing when there are none, so
the JSON line stays line 1. A refused notices request is the command's refusal and no message is read.

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

`sprint picture` reads the secret the same way and the picture's bytes from `--file`, refuses a file
larger than 2 MiB (2097152 bytes) before sending (the console closes such a connection unread), and
sends `POST /api/picture` with the bytes as `Content-Type: image/png`, the sprint id in
`X-Console-Sprint` and the secret in `X-Console-Secret`, no `Origin`. On success it prints the
picture's id (64 lowercase hex characters) alone and exit 0; a 200 answer whose `picture` is not
64 lowercase hex characters is `sprint: refused 200: unreadable answer: <error>` and exit 1. The
command checks nothing about the PNG: the console decides, in one place.

`sprint status` sends `GET /api/sprint-status?sprint_id=<id>` and prints the console's answer as one
line of JSON, `{"decision", "reply", "sprint_id", "version"}`, and exit 0. `decision` is `none`
(no answer yet), `approved`, `changes` (the owner's exact words are `reply`) or `withdrawn`. The
secret is `--secret-file`'s file, else `$CONSOLE_SPRINT_SECRET` only when the sprint id also comes
from `$CONSOLE_SPRINT_ID` (not beside `--sprint`), else none; with none, or when `decision` is
`withdrawn`, the line is all it prints and no secret is read. With a secret it also sends `POST
/api/notices` as `sprint inbox` does and prints the same `sprints.notice_block` after the line;
a refused notices request is exit 1. A status with no secret is not an error.

`sprint contract` prints the manager's contract, the document `manager-contract.md` packaged
beside this module, to stdout exactly as packaged and exit 0. It takes no sprint id, secret or
port, reads no environment and sends no request; the console's launch prompt tells the manager to
run it first (ADR-console-015).

Any other HTTP status is stderr `sprint: refused <status>: <text>` (the console's reason) and
exit 1. A console that cannot be reached is stderr
`sprint: console unreachable on 127.0.0.1:<port>: <error>` and exit 1. A secret, brief, report, closing report, round or reply file
or a picture file that cannot be read, or a brief, report, closing report or round that is not a JSON object, is stderr `sprint: cannot read <path>:
<reason>` and exit 2, with no request sent, as is a picture file larger than 2 MiB, stderr
`sprint: cannot send <path>: it is larger than 2 MiB` (a `sprint ask`, `sprint brief` or
`sprint report` picture file is the same exit 2, before any upload); a `picture` or `ask` secret,
or a `brief` or `report` secret when the object names a `file` member, that is not printable
ASCII (it travels in a header) is stderr `sprint: the secret is not printable ASCII, so it cannot go
in a header: no request sent` and exit 2, with no request sent; bad arguments are exit 2. The secret is printed nowhere.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sys
import time
from pathlib import Path

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.console import manager, service, sprints
from agent_tools.console.console import port_number

TIMEOUT_SECONDS = 10
PICTURE_ID = re.compile(r"[0-9a-f]{64}")
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

optional:
  pictures:    at most 8, [{"file": "<path to a PNG>", "line": "<one line, at most 140
               characters>", "pair": "before" | "after"}, ...]; the command uploads each file
               and sends its id

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


def round_id(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not a round id (an integer of at least 1)")
    return value


def notice_id(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not a notice id (an integer of at least 1)")
    return value


def question_index(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = -1
    if value < 0:
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a question index (an integer of at least 0)")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sprint", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (("brief", "send the sprint's brief to the console"),
                       ("report", "send the sprint's report to the console"),
                       ("ask", "send one round of questions to the owner"),
                       ("withdraw-question", "take back one of the sprint's open questions"),
                       ("notice", "post one notice for the sprint's project"),
                       ("notices", "print the project's open notices"),
                       ("withdraw-notice", "take back one of the sprint's notices"),
                       ("close", "send the sprint's closing report"),
                       ("inbox", "print the owner's unread messages to the sprint"),
                       ("recap", "print what a manager needs to pick the sprint up"),
                       ("reply", "answer one of the owner's messages"),
                       ("picture", "send one PNG picture to the console"),
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
        each.add_argument("--secret-file", type=Path, default=None,
                          help="the file holding the sprint's secret "
                               f"(default: ${manager.SECRET_ENV})")
        if name != "status":
            if name in ("brief", "report", "ask"):
                flag, what = (("--round-file", "round") if name == "ask"
                              else (f"--{name}-file", name))
                each.add_argument(flag, required=True,
                                  help=f"the {what} as a JSON object; - reads stdin")
            if name == "notice":
                each.add_argument("--notice-file", required=True,
                                  help="the notice as a JSON object; - reads stdin")
            if name == "close":
                each.add_argument("--closing-file", required=True,
                                  help="the closing report as a JSON object; - reads stdin")
        if name == "picture":
            each.add_argument("--file", type=Path, required=True, help="the PNG file to send")
        if name == "withdraw-question":
            each.add_argument("--round", type=round_id, required=True,
                              help="the id of the round holding the question")
            each.add_argument("--index", type=question_index, required=True,
                              help="the question's index in its round, counting from 0")
        if name == "withdraw-notice":
            each.add_argument("--notice", type=notice_id, required=True,
                              help="the id of the notice being taken back")
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


def ask(port: int, method: str, path: str, body: bytes | None = None,
        headers: dict[str, str] | None = None) -> str:
    """The console's answer text to one request, or `Refused` carrying the stderr line.

    Given `headers`, exactly those are sent; otherwise a body is sent as JSON."""
    if headers is None:
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


def part_pictures(value: dict) -> list[dict]:
    """The members of a brief's or report's `pictures` list that name a `file`, in order."""
    listed = value.get("pictures")
    return [m for m in listed if isinstance(m, dict) and isinstance(m.get("file"), str)
            ] if isinstance(listed, list) else []


def with_part_ids(value: dict, ids: dict[int, str]) -> dict:
    """A copy of `value` in which each picture member (by `id()`) names its picture id, not its file."""
    def named(member):
        if id(member) not in ids:
            return member
        return {**{k: v for k, v in member.items() if k != "file"}, "picture": ids[id(member)]}
    if not isinstance(value.get("pictures"), list):
        return dict(value)
    return {**value, "pictures": [named(m) for m in value["pictures"]]}


def without_part_files(value: dict) -> dict:
    """A copy of `value` keeping only the picture members that already name a picture id."""
    if not isinstance(value.get("pictures"), list):
        return dict(value)
    return {**value, "pictures": [m for m in value["pictures"]
                                  if not (isinstance(m, dict) and isinstance(m.get("file"), str))]}


def send_part(args: argparse.Namespace, sprint: str, secret: str, what: str, value: dict) -> str:
    """Send a brief or a report (`what`), uploading each picture `file` first; the 200 answer text."""
    path = service.BRIEF_PATH if what == "brief" else service.REPORT_PATH
    members = part_pictures(value)
    if members:
        check = sprints.checked_brief if what == "brief" else sprints.checked_report
        named = with_part_ids(value, {id(m): "0" * 64 for m in members})
        try:
            check(named)
        except sprints.Refused as error:
            raise Refused(f"sprint: refused before sending: {error}") from error
        limit = service.MAX_BRIEF_BYTES if what == "brief" else service.MAX_REPORT_BYTES
        # An id is as long as its placeholder, so the whole request's size is known before an upload.
        if len(json.dumps({"sprint_id": sprint, "secret": secret, what: named}).encode()) > limit:
            raise Refused(f"sprint: refused before sending: the {what} is larger than {limit} bytes")
        check_header_secret(secret)
        files = [read_picture(Path(m["file"])) for m in members]
        # The console judges the named pictures and the sprint's state now, so a refusal leaves
        # nothing uploaded; the uploads are the first write.
        ask(args.port, "POST", path, json.dumps(
            {"sprint_id": sprint, "secret": secret, what: without_part_files(value),
             "dry_run": True}).encode())
        ids = {id(m): upload(args.port, sprint, secret, data) for m, data in zip(members, files)}
        value = with_part_ids(value, ids)
    body = json.dumps({"sprint_id": sprint, "secret": secret, what: value}).encode()
    return ask(args.port, "POST", path, body)


def send_brief(args: argparse.Namespace, sprint: str) -> str:
    secret = resolve_secret(args)
    brief = read_object(args.brief_file, "brief")
    text = send_part(args, sprint, secret, "brief", brief)
    try:
        return f"sprint: brief version {json.loads(text)['version']} sent"
    except (ValueError, KeyError, TypeError) as error:
        raise Refused(f"sprint: refused 200: unreadable answer: {error}") from error


def round_pictures(round_: dict) -> list[dict]:
    """The members of a round's `pictures` lists that name a `file`, in question then picture order."""
    questions = round_.get("questions")
    members: list[dict] = []
    for question in questions if isinstance(questions, list) else ():
        listed = question.get("pictures") if isinstance(question, dict) else None
        for member in listed if isinstance(listed, list) else ():
            if isinstance(member, dict) and isinstance(member.get("file"), str):
                members.append(member)
    return members


def with_ids(round_: dict, ids: dict[int, str]) -> dict:
    """A copy of `round_` in which each member (by `id()`) names its picture id, not its file."""
    def named(member):
        if id(member) not in ids:
            return member
        return {**{k: v for k, v in member.items() if k != "file"}, "picture": ids[id(member)]}
    return {**round_, "questions": [
        {**question, "pictures": [named(m) for m in question["pictures"]]}
        if isinstance(question, dict) and isinstance(question.get("pictures"), list) else question
        for question in round_["questions"]]}


def without_files(round_: dict) -> dict:
    """A copy of `round_` keeping only the picture members that already name a picture id."""
    return {**round_, "questions": [
        {**question, "pictures": [m for m in question["pictures"]
                                  if not (isinstance(m, dict) and isinstance(m.get("file"), str))]}
        if isinstance(question, dict) and isinstance(question.get("pictures"), list) else question
        for question in round_["questions"]]}


def send_round(args: argparse.Namespace, sprint: str) -> str:
    secret = resolve_secret(args)
    round_ = read_object(args.round_file, "round")
    members = round_pictures(round_)
    if members:
        named = with_ids(round_, {id(m): "0" * 64 for m in members})
        try:
            sprints.checked_round(named)
        except sprints.Refused as error:
            raise Refused(f"sprint: refused before sending: {error}") from error
        # An id is as long as its placeholder, so the whole request's size is known before an upload.
        if len(json.dumps({"sprint_id": sprint, "secret": secret, "round": named}).encode()
               ) > service.MAX_ASK_BYTES:
            raise Refused("sprint: refused before sending: the round is larger than "
                          f"{service.MAX_ASK_BYTES} bytes")
        check_header_secret(secret)
        files = [read_picture(Path(m["file"])) for m in members]
        # The console judges the named pictures and the sprint's state now, so a refusal leaves
        # nothing uploaded; the uploads are the first write.
        ask(args.port, "POST", service.ASK_PATH, json.dumps(
            {"sprint_id": sprint, "secret": secret, "round": without_files(round_),
             "dry_run": True}).encode())
        ids = {id(m): upload(args.port, sprint, secret, data) for m, data in zip(members, files)}
        round_ = with_ids(round_, ids)
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


def send_withdrawal(args: argparse.Namespace, sprint: str) -> str:
    secret = resolve_secret(args)
    body = json.dumps({"sprint_id": sprint, "secret": secret, "round": args.round,
                       "index": args.index}).encode()
    text = ask(args.port, "POST", service.WITHDRAW_QUESTION_PATH, body)
    try:
        answer = json.loads(text)
        round_, index = answer["round"], answer["index"]
        if any(type(n) is not int for n in (round_, index)):
            raise TypeError("round and index are not both integers")
    except (ValueError, KeyError, TypeError) as error:
        raise Refused(f"sprint: refused 200: unreadable answer: {error}") from error
    return f"sprint: round {round_} question {index} withdrawn"


def send_notice(args: argparse.Namespace, sprint: str) -> str:
    secret = resolve_secret(args)
    notice = read_object(args.notice_file, "notice")
    body = json.dumps({"sprint_id": sprint, "secret": secret, "notice": notice}).encode()
    text = ask(args.port, "POST", service.NOTICE_PATH, body)
    return f"sprint: notice {answered_notice(text)} posted"


def answered_notice(text: str) -> int:
    try:
        notice = json.loads(text)["notice"]
        if type(notice) is not int:
            raise TypeError("notice is not an integer")
    except (ValueError, KeyError, TypeError) as error:
        raise Refused(f"sprint: refused 200: unreadable answer: {error}") from error
    return notice


def read_notices(args: argparse.Namespace, sprint: str) -> str:
    secret = resolve_secret(args)
    body = json.dumps({"sprint_id": sprint, "secret": secret}).encode()
    return ask(args.port, "POST", service.NOTICES_PATH, body)


def send_notice_withdrawal(args: argparse.Namespace, sprint: str) -> str:
    secret = resolve_secret(args)
    body = json.dumps({"sprint_id": sprint, "secret": secret, "notice": args.notice}).encode()
    text = ask(args.port, "POST", service.WITHDRAW_NOTICE_PATH, body)
    return f"sprint: notice {answered_notice(text)} withdrawn"


def send_report(args: argparse.Namespace, sprint: str) -> str:
    secret = resolve_secret(args)
    report = read_object(args.report_file, "report")
    send_part(args, sprint, secret, "report", report)
    return "sprint: report sent"


def send_closing(args: argparse.Namespace, sprint: str) -> str:
    secret = resolve_secret(args)
    closing = read_object(args.closing_file, "closing report")
    body = json.dumps({"sprint_id": sprint, "secret": secret, "closing": closing}).encode()
    ask(args.port, "POST", service.CLOSE_PATH, body)
    return "sprint: closing report sent"


def read_notice_block(port: int, sprint: str, secret: str) -> str:
    """The open-notice block of the sprint's project, or `""` when no other sprint has a notice."""
    body = json.dumps({"sprint_id": sprint, "secret": secret}).encode()
    text = ask(port, "POST", service.NOTICES_PATH, body)
    try:
        entries = json.loads(text)["notices"]
        if not isinstance(entries, list):
            raise TypeError("notices is not a list")
        return sprints.notice_block(entries, sprint, int(time.time() * 1000))
    except (ValueError, KeyError, TypeError) as error:
        raise Refused(f"sprint: refused 200: unreadable answer: {error}") from error


def with_block(line: str, block: str) -> str:
    return line if block == "" else f"{line}\n{block}"


def read_inbox(args: argparse.Namespace, sprint: str) -> str:
    secret = resolve_secret(args)
    block = read_notice_block(args.port, sprint, secret)
    body = json.dumps({"sprint_id": sprint, "secret": secret}).encode()
    return with_block(ask(args.port, "POST", service.INBOX_PATH, body), block)


def read_status(args: argparse.Namespace, sprint: str) -> str:
    line = ask(args.port, "GET", f"{service.STATUS_PATH}?sprint_id={sprint}")
    try:
        decision = json.loads(line)["decision"]
    except (ValueError, KeyError, TypeError) as error:
        raise Refused(f"sprint: refused 200: unreadable answer: {error}") from error
    if decision == "withdrawn":
        return line
    if args.secret_file is not None:
        secret = read_secret(args.secret_file)
    elif args.sprint is None and manager.SECRET_ENV in os.environ:
        secret = os.environ[manager.SECRET_ENV].removesuffix("\n")
    else:
        return line
    return with_block(line, read_notice_block(args.port, sprint, secret))


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


def check_header_secret(secret: str) -> None:
    if not (secret.isascii() and secret.isprintable()):
        # A header cannot carry a newline or a non-ASCII character; naming the value would print it.
        raise Unreadable("sprint: the secret is not printable ASCII, so it cannot go in a header: "
                         "no request sent")


def read_picture(path: Path) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise Unreadable(f"sprint: cannot read {path}: {error}") from error
    if len(data) > service.MAX_PICTURE_BYTES:
        raise Unreadable(f"sprint: cannot send {path}: it is larger than 2 MiB")
    return data


def upload(port: int, sprint: str, secret: str, data: bytes) -> str:
    """Send one picture's bytes and return its id; the secret is checked as a header value."""
    check_header_secret(secret)
    text = ask(port, "POST", service.PICTURE_PATH, data,
               {"Content-Type": "image/png", service.SPRINT_HEADER: sprint,
                service.SECRET_HEADER: secret})
    try:
        picture = json.loads(text)["picture"]
        if not isinstance(picture, str) or PICTURE_ID.fullmatch(picture) is None:
            raise ValueError(f"{picture!r} is not a picture id (64 lowercase hex characters)")
    except (ValueError, KeyError, TypeError) as error:
        raise Refused(f"sprint: refused 200: unreadable answer: {error}") from error
    return picture


def send_picture(args: argparse.Namespace, sprint: str) -> str:
    secret = resolve_secret(args)
    check_header_secret(secret)
    return upload(args.port, sprint, secret, read_picture(args.file))


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
        elif args.command == "withdraw-question":
            line = send_withdrawal(args, sprint)
        elif args.command == "notice":
            line = send_notice(args, sprint)
        elif args.command == "notices":
            line = read_notices(args, sprint)
        elif args.command == "withdraw-notice":
            line = send_notice_withdrawal(args, sprint)
        elif args.command == "close":
            line = send_closing(args, sprint)
        elif args.command == "inbox":
            line = read_inbox(args, sprint)
        elif args.command == "recap":
            line = read_recap(args, sprint)
        elif args.command == "reply":
            line = send_reply(args, sprint)
        elif args.command == "picture":
            line = send_picture(args, sprint)
        else:
            line = read_status(args, sprint)
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
