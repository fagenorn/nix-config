"""Issue claims on GitHub issue comments (issue 623): acquire, renew and release.

A claim is a `claim` marker (`agent_tools.forge_markers`) and the `in-progress` label is only
a filter over it. Contention is settled by the marker contest (D2): the smallest live claim
comment id of the issue wins, and `acquire` never steals a claim, stale or not.

D3, a renewal changes the body: `renew` rewrites the claim's first line with `renewed=<n+1>`
so the edit always moves the server's `updated_at`, then re-lists and reports `not_held` when
the claim was ended meanwhile.

D7, labels: a label is ensured (HTTP 422 means it exists) before it is added; removing a label
that is not there is success.

D8, output: every call, a usage error included, prints exactly one JSON object on one stdout
line. Exit 0 success, 3 contention or `not_held`, 1 forge error, 2 usage.

D9, ending is append-only: `release` posts an `end` marker first and then edits the claim to
`released=<reason>`, so a delayed `renew` PATCH can drop that field but never the `end`, and a
released claim cannot come back.

D10, owner-action retirement: `renew` and `release` end every live `owner-action` marker that
names their claim, and the `owner-action` label goes when none remains live on the issue.

The module reads no host clock.
"""
import argparse
import json
import re
import sys
from typing import Any

from agent_tools import forge_markers as fm
from agent_tools.forge_markers import ForgeError, Marker

CLAIM_KIND = "claim"
IN_PROGRESS = ("in-progress", "FBCA04")
OWNER_ACTION = ("owner-action", "D93F0B")
OWNER_ACTION_KIND = "owner-action"

CONTENDED, FORGE_ERROR, USAGE = 3, 1, 2


class UsageError(Exception):
    """The command line was rejected; carries the parser's message."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise UsageError(message)


def _pattern(regex: str, what: str):
    def check(value: str) -> str:
        if not re.fullmatch(regex, value):
            raise argparse.ArgumentTypeError(f"{what} {value!r} is outside {regex}")
        return value
    return check


def _issue(value: str) -> int:
    if not re.fullmatch(r"[0-9]+", value) or int(value) < 1:
        raise argparse.ArgumentTypeError(f"issue {value!r} is not an integer of at least 1")
    return int(value)


REPO = _pattern(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", "repo")
HOLDER = _pattern(r"[A-Za-z0-9][A-Za-z0-9.-]*/[A-Za-z0-9][A-Za-z0-9._-]*", "holder")
BRANCH = _pattern(r"[A-Za-z0-9_][A-Za-z0-9_./-]*", "branch")
REASON = _pattern(r"[A-Za-z0-9._:/@+-]+", "reason")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="forge-claim", description="Claim a forge issue so one session delivers it.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("acquire", "renew", "release"):
        sub = commands.add_parser(name)
        sub.add_argument("--repo", required=True, type=REPO)
        sub.add_argument("--issue", required=True, type=_issue)
        sub.add_argument("--holder", required=True, type=HOLDER)
        if name != "release":
            sub.add_argument("--branch", type=BRANCH, default=None)
        else:
            sub.add_argument("--reason", type=REASON, default="done")
    return parser


def _result(args: argparse.Namespace, verdict: str, comment_id: int | None = None,
            by: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"command": args.command, "repo": args.repo, "issue": args.issue, "holder": args.holder,
            "verdict": verdict, "comment_id": comment_id, "by": by, **extra}


def _holder_of(marker: Marker | None) -> str | None:
    return marker.fields.get("holder") if marker is not None else None


def _mark_in_progress(args: argparse.Namespace) -> None:
    fm.ensure_label(args.repo, *IN_PROGRESS)
    fm.add_label(args.repo, args.issue, IN_PROGRESS[0])


def retire_owner_actions(slug: str, issue: int, markers: list[Marker], claim_id: int | None,
                         reason: str) -> list[int]:
    """End the live `owner-action` markers naming `claim_id` (all when None) with `reason` (D10).

    When at least one was ended and no live `owner-action` of the issue remains, judged on
    `markers` plus the ids ended here, the `owner-action` label is removed. Returns the ended
    marker ids, ascending."""
    live = [m for m in markers if m.kind == OWNER_ACTION_KIND and fm.is_live(m, markers)]
    named = sorted(m.comment_id for m in live
                   if claim_id is None or m.fields.get("claim") == str(claim_id))
    for comment_id in named:
        fm.end(slug, issue, comment_id, reason)
    if named and not any(m.comment_id not in named for m in live):
        fm.remove_label(slug, issue, OWNER_ACTION[0])
    return named


def acquire(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    markers = fm.list_markers(args.repo, args.issue)
    match = {"issue": str(args.issue)}
    held = fm.contest(markers, CLAIM_KIND, match)
    winner = held[0] if held else None
    if winner is None:
        fields = {"issue": str(args.issue), "holder": args.holder}
        if args.branch:
            fields["branch"] = args.branch
        written = fm.write(args.repo, args.issue, CLAIM_KIND, fields, f"Claimed by {args.holder}.", match)
        if written.won:
            _mark_in_progress(args)
            return 0, _result(args, "acquired", written.own_id)
        winner = written.winner
        comment_id = winner.comment_id if winner is not None else None
        if _holder_of(winner) == args.holder:
            return 0, _result(args, "already_held", comment_id)
        return CONTENDED, _result(args, "lost_to", comment_id, _holder_of(winner))
    if _holder_of(winner) == args.holder:
        _mark_in_progress(args)
        return 0, _result(args, "already_held", winner.comment_id)
    return CONTENDED, _result(args, "held_by", winner.comment_id, _holder_of(winner))


def renew(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    markers = fm.list_markers(args.repo, args.issue)
    held = fm.contest(markers, CLAIM_KIND, {"issue": str(args.issue)})
    winner = held[0] if held else None
    if winner is None or _holder_of(winner) != args.holder:
        return CONTENDED, _result(args, "not_held", None, _holder_of(winner))
    previous = winner.fields.get("renewed", "0")
    count = int(previous) if previous.isdigit() else 0
    updates = {"renewed": str(count + 1)}
    if args.branch:
        updates["branch"] = args.branch
    fm.edit(args.repo, winner.comment_id, fm.with_fields(winner, **updates))
    again = fm.list_markers(args.repo, args.issue)
    if not any(m.comment_id == winner.comment_id and fm.is_live(m, again) for m in again):
        return CONTENDED, _result(args, "not_held", winner.comment_id)
    retire_owner_actions(args.repo, args.issue, again, winner.comment_id, "renewed")
    return 0, _result(args, "renewed", winner.comment_id)


def release(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    markers = fm.list_markers(args.repo, args.issue)
    mine = [m for m in fm.contest(markers, CLAIM_KIND, {"issue": str(args.issue)})
            if _holder_of(m) == args.holder]
    if not mine:
        return CONTENDED, _result(args, "not_held")
    claim = mine[0]
    fm.end(args.repo, args.issue, claim.comment_id, args.reason)
    fm.edit(args.repo, claim.comment_id, fm.with_fields(claim, released=args.reason))
    retire_owner_actions(args.repo, args.issue, markers, claim.comment_id, "released")
    remaining = fm.contest(fm.list_markers(args.repo, args.issue), CLAIM_KIND,
                           {"issue": str(args.issue)})
    label_removed = not remaining
    if label_removed:
        fm.remove_label(args.repo, args.issue, IN_PROGRESS[0])
    return 0, _result(args, "released", claim.comment_id, label_removed=label_removed)


COMMANDS = {"acquire": acquire, "renew": renew, "release": release}


def _emit(result: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        args = build_parser().parse_args(argv)
    except UsageError as error:
        _emit({"command": argv[0] if argv and argv[0] in COMMANDS else None, "repo": None,
               "issue": None, "holder": None, "verdict": "error", "comment_id": None, "by": None,
               "error": "usage", "detail": str(error)})
        return USAGE
    except SystemExit as stop:  # -h/--help: argparse printed the help text
        return stop.code if isinstance(stop.code, int) else 0
    try:
        code, result = COMMANDS[args.command](args)
    except ForgeError as error:
        code, result = FORGE_ERROR, _result(args, "error", error=error.code, detail=error.detail)
    _emit(result)
    return code


if __name__ == "__main__":
    sys.exit(main())
