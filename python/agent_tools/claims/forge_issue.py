"""forge-issue (issue 697): file an issue and record its blocking edges natively, read back.

Source entry `python -m agent_tools.claims.forge_issue`, library `agent_tools.system.forge_api`. Blocking
edges go through the forge's dependencies endpoints instead of prose.
`create --repo <owner/name> --title <t> --body-file <path> [--label <l>]... [--blocked-by <n>]...
[--blocks <n>]...` files the issue and links it; `link --repo <owner/name> --issue <n>
[--blocked-by <n>]... [--blocks <n>]...` adds the edges an existing issue lacks (and needs at
least one edge). `--blocked-by <n>` records that the issue is blocked by #n, `--blocks <n>` that
#n is blocked by the issue. `read --repo <owner/name> --issue <n>` posts nothing: it prints both
lists of the issue as they stand (`read`, exit 0), with `missing_*` and `unexpected_*` empty, and
is the read a caller that orders work by blockers uses, since an edge `link` added is in no body.

D1, identity on the wire: every link posts `issue_id=<database id>` of the blocker, read from
`repos/<owner/name>/issues/<n>` (`.id`), never an issue number, which the dependencies endpoint
would not accept as one. `create` posts one `blocked_by` link per `--blocked-by` on the new issue
and one per `--blocks` on the blocked issue (the new issue's id as the blocker), in argv order,
`--blocked-by` first; `link` posts only the edges whose blocker id is absent from its first read,
and reads the target's own id only when a `--blocks` edge is missing.

D3, outcomes: exit 1 with `issue` null and an `error` other than `create_unconfirmed` filed
nothing; exit 1 with `issue` set means that issue exists, so rerun `link` with it and never
refile; a `ForgeError` of the filing call itself is `create_unconfirmed` (`issue` null, `detail`
`<original code>: <original detail>`), because the request may have landed: look the title up on
the forge before filing again. Nothing is linked after an unconfirmed filing.

D6, validate first: `create` (and `link`) resolve every requested number to an issue of `--repo`
before any POST, so a 404, a pull request (`not_an_issue`) or a payload answering another number
(`payload_invalid`) files nothing.

D7, read back: after posting, both lists of the issue (`dependencies/blocked_by` and
`dependencies/blocking`) are read back; `create` succeeds (`created`, exit 0) only when each id
set equals the requested one, `link` (`linked`) when it contains it; otherwise the verdict is
`links_differ`, exit 1, with the issue number reported.

D8, output: every call, a usage error included, prints exactly one line,
`json.dumps(result, sort_keys=True)`, with exactly the keys `command`, `repo`, `issue`,
`verdict`, `blocked_by`, `blocks`, `missing_blocked_by`, `missing_blocks`, `unexpected_blocked_by`,
`unexpected_blocks`, `error` and `detail`. `blocked_by` and `blocks` are the read-back entries as
sorted `<owner>/<name>#<n>` references (the owner and name come from each entry's
`repository_url` after `/repos/`; null when no read-back happened); `missing_*` are the requested
numbers of `--repo` whose database id is absent from the read-back, sorted; `unexpected_*` are the
references of read-back entries whose id was not requested, sorted (always empty for `link`).
Exit 0 is `created`, `linked` or `read`, exit 1 a forge error (`verdict: "error"`, `error` the
`ForgeError` code, `detail`) or `links_differ`, exit 2 usage (`error: "usage"`; a repeated number,
`--issue` among its own edges, an empty title, an unreadable body file or a malformed flag, always
before any `gh` call), and `-h`/`--help` prints argparse help and exits 0. Every `gh` child runs
without `GITHUB_TOKEN` and `GH_TOKEN`, so the keyring credential answers.

D11, home repository: a lookup is accepted only when its `repository_url` names `--repo`, because
GitHub redirects a transferred issue's number to its new home, where the same number may be another
issue whose database id would otherwise be posted and read back identically.

D10, identity is the database id: an existing edge (`link`) and the read-back (`create` and
`link`) match requested issues by `id`, never by `number`, so an issue of another repository
sharing a requested number is neither an existing edge nor a confirmed link; it is reported as
`unexpected_*` and the requested number as `missing_*`.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from agent_tools.system import forge_api
from agent_tools.system.forge_api import ForgeError

REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
NUMBER = re.compile(r"[1-9][0-9]*")
KEYS = ("command", "repo", "issue", "verdict", "blocked_by", "blocks", "missing_blocked_by",
        "missing_blocks", "unexpected_blocked_by", "unexpected_blocks", "error", "detail")
OK, FORGE_ERROR, USAGE = 0, 1, 2
# The user-only Instruction Budget raise label: the lifecycle guard sees `gh --add-label`, not this
# helper's API call, and the helper is allowed outright, so it refuses the label itself (COR-001).
RESERVED_LABEL = "instruction-budget-raise"


class UsageError(Exception):
    """The command line was rejected; carries the message."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise UsageError(message)


def _repo(value: str) -> str:
    if not REPO.fullmatch(value):
        raise argparse.ArgumentTypeError(f"repository {value!r} is not <owner>/<name>")
    return value


def _number(value: str) -> int:
    if not NUMBER.fullmatch(value):
        raise argparse.ArgumentTypeError(f"issue number {value!r} is outside {NUMBER.pattern}")
    return int(value)


def _label(value: str) -> str:
    if not value:
        raise argparse.ArgumentTypeError("a label must not be empty")
    if value.strip().casefold() == RESERVED_LABEL:
        raise argparse.ArgumentTypeError(f"label {RESERVED_LABEL!r} is the user's to apply, never the helper's")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="forge-issue",
                     description="File a forge issue and record its blocking edges natively.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "link"):
        sub = commands.add_parser(name)
        sub.add_argument("--repo", required=True, type=_repo)
        sub.add_argument("--blocked-by", dest="blocked_by", action="append", default=[], type=_number)
        sub.add_argument("--blocks", action="append", default=[], type=_number)
        if name == "create":
            sub.add_argument("--title", required=True)
            sub.add_argument("--body-file", required=True)
            sub.add_argument("--label", dest="labels", action="append", default=[], type=_label)
        else:
            sub.add_argument("--issue", required=True, type=_number)
    reading = commands.add_parser("read")
    reading.add_argument("--repo", required=True, type=_repo)
    reading.add_argument("--issue", required=True, type=_number)
    return parser


def _parse(argv: list[str]) -> argparse.Namespace:
    args = _parser().parse_args(argv)
    if args.command == "read":
        return args
    numbers = args.blocked_by + args.blocks
    if len(set(numbers)) != len(numbers):
        raise UsageError("an issue number is repeated within or across --blocked-by and --blocks")
    if args.command == "link":
        if args.issue in numbers:
            raise UsageError("--issue cannot be one of its own blockers or blocked issues")
        if not numbers:
            raise UsageError("link needs at least one --blocked-by or --blocks")
    else:
        if not args.title.strip():
            raise UsageError("--title is empty")
        try:
            args.body = Path(args.body_file).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise UsageError(f"cannot read --body-file {args.body_file}: {error}") from None
    return args


def database_id(slug: str, number: int) -> int:
    """The database id of issue `number` of `slug`; a pull request, another number's or another repository's payload is an error."""
    payload = forge_api.api_get(f"repos/{slug}/issues/{number}")
    answered = payload.get("number") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or isinstance(answered, bool) or answered != number:
        raise ForgeError("payload_invalid", f"#{number} answered as {answered!r}")
    if "pull_request" in payload:
        raise ForgeError("not_an_issue", f"#{number} is a pull request")
    url = payload.get("repository_url")
    home = url.split("/repos/", 1)[1] if isinstance(url, str) and "/repos/" in url else None
    if home is None or home.casefold() != slug.casefold():
        raise ForgeError("payload_invalid", f"#{number} answered from repository {home!r}, not {slug}")
    ident = payload.get("id")
    if isinstance(ident, bool) or not isinstance(ident, int) or ident <= 0:
        raise ForgeError("payload_invalid", f"#{number} has no database id")
    return ident


def _entry(item: Any, path: str) -> tuple[int, str]:
    ident = item.get("id") if isinstance(item, dict) else None
    number = item.get("number") if isinstance(item, dict) else None
    url = item.get("repository_url") if isinstance(item, dict) else None
    if (isinstance(ident, bool) or not isinstance(ident, int) or ident <= 0
            or isinstance(number, bool) or not isinstance(number, int)
            or not isinstance(url, str) or "/repos/" not in url):
        raise ForgeError("payload_invalid", f"{path} holds an entry without id, number and repository_url")
    return ident, f"{url.split('/repos/', 1)[1]}#{number}"


def entries(slug: str, issue: int, side: str) -> dict[int, str]:
    """The `blocked_by` or `blocking` list of an issue: database id -> qualified reference."""
    path = f"repos/{slug}/issues/{issue}/dependencies/{side}?per_page=100"
    found: dict[int, str] = {}
    for page in forge_api.api_pages(path):
        if not isinstance(page, list):
            raise ForgeError("payload_invalid", f"{path} has a page that is not an array")
        for item in page:
            ident, reference = _entry(item, path)
            found[ident] = reference
    return found


def verdict_of(requested: dict[int, int], got: dict[int, str], exact: bool):
    """(missing numbers, unexpected references, reported references) of one read-back side."""
    missing = sorted(n for n, ident in requested.items() if ident not in got)
    unexpected = sorted(r for ident, r in got.items() if ident not in requested.values()) if exact else []
    return missing, unexpected, sorted(got.values())


def result(command=None, repo=None, issue=None, verdict="error", blocked_by=None, blocks=None,
           missing_blocked_by=None, missing_blocks=None, unexpected_blocked_by=None,
           unexpected_blocks=None, error=None, detail=None) -> dict:
    return {"command": command, "repo": repo, "issue": issue, "verdict": verdict,
            "blocked_by": blocked_by, "blocks": blocks, "missing_blocked_by": missing_blocked_by,
            "missing_blocks": missing_blocks, "unexpected_blocked_by": unexpected_blocked_by,
            "unexpected_blocks": unexpected_blocks, "error": error, "detail": detail}


def _read_back(args, issue: int, ids: dict[int, int], exact: bool) -> tuple[dict, int]:
    by = entries(args.repo, issue, "blocked_by")
    blocking = entries(args.repo, issue, "blocking")
    missing_by, unexpected_by, reported_by = verdict_of(
        {n: ids[n] for n in args.blocked_by}, by, exact)
    missing_blocks, unexpected_blocks, reported_blocks = verdict_of(
        {n: ids[n] for n in args.blocks}, blocking, exact)
    differs = missing_by or unexpected_by or missing_blocks or unexpected_blocks
    verdict = "links_differ" if differs else ("created" if exact else "linked")
    return (result(args.command, args.repo, issue, verdict, reported_by, reported_blocks, missing_by,
                   missing_blocks, unexpected_by, unexpected_blocks),
            FORGE_ERROR if differs else OK)


def _create(args, state: dict) -> tuple[dict, int]:
    ids = {n: database_id(args.repo, n) for n in args.blocked_by + args.blocks}
    try:
        issue = forge_api.create_issue(args.repo, args.title, args.body, args.labels)
    except ForgeError as error:
        raise ForgeError("create_unconfirmed", f"{error.code}: {error.detail}") from None
    state["issue"] = issue
    for n in args.blocked_by:
        forge_api.add_blocked_by(args.repo, issue, ids[n])
    if args.blocks:
        own = database_id(args.repo, issue)
        for n in args.blocks:
            forge_api.add_blocked_by(args.repo, n, own)
    return _read_back(args, issue, ids, exact=True)


def _link(args, state: dict) -> tuple[dict, int]:
    issue = state["issue"] = args.issue
    own = database_id(args.repo, issue)  # also proves --issue is this repository's, not a transfer's redirect
    ids = {n: database_id(args.repo, n) for n in args.blocked_by + args.blocks}
    have_by = entries(args.repo, issue, "blocked_by")
    have_blocking = entries(args.repo, issue, "blocking")
    need_by = [n for n in args.blocked_by if ids[n] not in have_by]
    need_blocks = [n for n in args.blocks if ids[n] not in have_blocking]
    for n in need_by:
        forge_api.add_blocked_by(args.repo, issue, ids[n])
    for n in need_blocks:
        forge_api.add_blocked_by(args.repo, n, own)
    return _read_back(args, issue, ids, exact=False)


def _read(args, state: dict) -> tuple[dict, int]:
    issue = state["issue"] = args.issue
    database_id(args.repo, issue)  # proves --issue is this repository's issue, not a transfer's redirect
    by = sorted(entries(args.repo, issue, "blocked_by").values())
    blocking = sorted(entries(args.repo, issue, "blocking").values())
    return result("read", args.repo, issue, "read", by, blocking, [], [], [], []), OK


COMMANDS = {"create": _create, "link": _link, "read": _read}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    state: dict = {"issue": None}
    command = argv[0] if argv and argv[0] in COMMANDS else None
    try:
        args = _parse(argv)
        out, code = COMMANDS[args.command](args, state)
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else OK
    except UsageError as error:
        out, code = result(command, error="usage", detail=str(error)), USAGE
    except ForgeError as error:
        out = result(command, args.repo, state["issue"], error=error.code, detail=error.detail)
        code = FORGE_ERROR
    sys.stdout.write(json.dumps(out, sort_keys=True) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
