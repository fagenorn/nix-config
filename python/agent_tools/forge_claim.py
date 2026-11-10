"""Issue claims on GitHub issue comments (issue 623): acquire, renew, release and status.

A claim is a `claim` marker (`agent_tools.forge_markers`) and the `in-progress` label is only
a filter over it. Contention is settled by the marker contest (D2): the smallest live claim
comment id of the issue wins, and `acquire` never steals a claim, stale or not.

D3, a renewal changes the body: `renew` rewrites the claim's first line with `renewed=<n+1>`
so the edit always moves the server's `updated_at`, then re-lists and reports `not_held` when
the claim was ended meanwhile.

D7, labels: a label is ensured (HTTP 422 means it exists) before it is added; removing a label
that is not there is success.

D8, output: every call, a usage error included, prints exactly one JSON object on one stdout
line. Exit 0 success, 3 contention or `not_held`, 1 forge error (carrying `transient`), 2 usage.

D9, ending is append-only: `release` posts an `end` marker first and then edits the claim to
`released=<reason>`, so a delayed `renew` PATCH can drop that field but never the `end`, and a
released claim cannot come back.

D10, owner-action retirement: `renew` and `release` end every live `owner-action` marker that
names their claim, a `status` that finds the issue free or held ends every live stale-claim
`owner-action` whose claim is not the holder, and the `owner-action` label goes when none of any
reason remains live on the issue. An `owner-action` of another reason is never ended here.

D4, branch activity: a claim recorded with `--branch` counts the branch's last push and the
`updated_at` of its pull requests as activity beside its own renewals; a claim with no branch
counts only its own `updated_at`.

D5, server now: "now" is the server's `Date` header (`forge_markers.server_now`); a claim is
stale when `now - activity >= 24 hours`. The module reads no host clock.

D6, owner-action: `status` reports a stale claim by posting one `owner-action` marker whose
checkbox the owner ticks. The next `status` or `acquire` honours a ticked box only while the
claim it names is live and still stale at that moment: the claim is ended (reason
`owner-action`), edited to `released=owner-action`, and the marker ended (reason `released`).
A box ticked on a claim that is no longer stale is ended (reason `renewed`) and releases
nothing. A stale claim is never stolen: `acquire` against it without a ticked box is `held_by`.

The `land` subcommand (`land acquire|release|status`, issue 629) is the cross-host land lock
of `agent_tools.forge_land_lock`: `main` routes it there and reports its usage errors in its
own one-line shape.

The `owner-action` subcommand (`owner-action post|end|status`, issue 636, D6) is
`agent_tools.forge_owner_action`: the decision, conflict and needs-label markers a batch posts
for the owner. They carry no `claim` field, and claim retirement (`retire_obsolete`,
`retire_owner_actions`) ends only owner-action markers that name a claim, so `status`, `renew`
and `release` never end one of them or remove the label while one lives.

D10, residual window, accepted: an honour reads the server time and the branch activity first,
then takes a fresh listing and ends the claim right after judging that listing's `updated_at`, so
a renewal that landed before that listing is never undone. One that lands between that listing
and the end can still lose the claim; the holder's `renew` then reports `not_held` (D3), so
holders run `renew` before each irreversible step and stop on `not_held`.

D11, transport retry (issue 740): `acquire`, `renew`, `release`, `status`, a one-shot `land
acquire`, `land release` and `owner-action status` retry the whole verb when it fails with a
transient `ForgeError` (a `gh` timeout, an HTTP 5xx or a connection failure): three tries, 20 s
then 40 s between them. The verb is retried whole, never one gh call inside it, because each is
idempotent for its holder under a lost reply (#623). `land acquire --wait` keeps its own D8 bound
and is never wrapped; `owner-action post`, `owner-action end` and `land status` run once. Every
exit-1 line carries `transient`: true when the error was a transport error (the tries ran out).
A retried `land acquire` that raised after it sent a create or a swap reports `acquired`, not
`already_held`, for a lock then found at its sha: the programs recheck the base on `acquired`.
A retried `renew` also sheds the `owner-action` label its lost-reply retirement left behind.
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from agent_tools import forge_land_lock
from agent_tools import forge_owner_action
from agent_tools import forge_markers as fm
from agent_tools.forge_markers import ForgeError, Marker

CLAIM_KIND = "claim"
IN_PROGRESS = ("in-progress", "FBCA04")
OWNER_ACTION = ("owner-action", "D93F0B")
OWNER_ACTION_KIND = "owner-action"
STALE_AFTER = timedelta(hours=24)
RELEASE_BOX = "Release this claim"
TICKED = re.compile(rf"\s*[-*] \[[xX]\] {RELEASE_BOX}\s*")

CONTENDED, FORGE_ERROR, USAGE = 3, 1, 2

TRIES = 3
BACKOFF = (20, 40)  # seconds slept after the first and after the second transient failure
sleep = time.sleep  # a module attribute so tests patch it


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
SHA = _pattern(r"[0-9a-f]{40}", "sha")
REASON = _pattern(r"[A-Za-z0-9._:/@+-]+", "reason")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="forge-claim", description="Claim a forge issue so one session delivers it.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("acquire", "renew", "release", "status"):
        sub = commands.add_parser(name)
        sub.add_argument("--repo", required=True, type=REPO)
        sub.add_argument("--issue", required=True, type=_issue)
        sub.add_argument("--holder", required=True, type=HOLDER)
        if name in ("acquire", "renew"):
            sub.add_argument("--branch", type=BRANCH, default=None)
        elif name == "release":
            sub.add_argument("--reason", type=REASON, default="done")
    owner = commands.add_parser("owner-action")
    forge_owner_action.add_actions(owner)
    land = commands.add_parser("land")
    actions = land.add_subparsers(dest="action", required=True)
    for name in forge_land_lock.ACTIONS:
        sub = actions.add_parser(name)
        sub.add_argument("--repo", required=True, type=REPO)
        sub.add_argument("--branch", required=True, type=BRANCH)
        sub.add_argument("--sha", required=True, type=SHA)
        if name == "acquire":
            sub.add_argument("--wait", action="store_true")
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
    """End the live `owner-action` markers naming `claim_id` (every one naming a claim when None)
    with `reason` (D10). A marker with no `claim` field is never ended here (issue 636, D6).

    When at least one was ended and no live `owner-action` of the issue remains, judged on
    `markers` plus the ids ended here, the `owner-action` label is removed. Returns the ended
    marker ids, ascending."""
    live = [m for m in markers if m.kind == OWNER_ACTION_KIND and fm.is_live(m, markers)]
    named = sorted(m.comment_id for m in live if "claim" in m.fields
                   and (claim_id is None or m.fields["claim"] == str(claim_id)))
    for comment_id in named:
        fm.end(slug, issue, comment_id, reason)
    if named and not any(m.comment_id not in named for m in live):
        fm.remove_label(slug, issue, OWNER_ACTION[0])
    return named


def branch_activity(slug: str, claim: Marker) -> list[datetime]:
    """The last push and the newest pull request `updated_at` of the claim's branch, when it
    records one and they exist (D4)."""
    branch = claim.fields.get("branch")
    if not branch:
        return []
    return [m for m in (fm.latest_push(slug, branch), fm.latest_pr_event(slug, branch)) if m is not None]


def activity_at(slug: str, claim: Marker) -> datetime:
    """The claim's latest activity: its `updated_at`, and, only when it records a branch, the
    branch's last push and the newest `updated_at` of the branch's pull requests (D4)."""
    return max([claim.updated_at, *branch_activity(slug, claim)])


def is_stale(activity: datetime, now: datetime) -> bool:
    return now - activity >= STALE_AFTER


def _ticked(marker: Marker) -> bool:
    return any(TICKED.fullmatch(line) for line in marker.body.splitlines()[1:])


def _live_owner_actions(markers: list[Marker]) -> list[Marker]:
    return [m for m in markers if m.kind == OWNER_ACTION_KIND and fm.is_live(m, markers)]


def _claim_named(markers: list[Marker], owner_action: Marker) -> Marker | None:
    return next((m for m in markers if m.kind == CLAIM_KIND
                 and str(m.comment_id) == owner_action.fields.get("claim")), None)


def honour_ticks(slug: str, issue: int, markers: list[Marker]) -> tuple[list[Marker], list[int]]:
    """Honour the ticked release boxes of the issue's live stale-claim `owner-action` markers (D6).

    Returns the markers to continue with (a fresh listing when anything was ended) and the
    claim ids released, ascending. The server clock is read at most once, and only when a
    ticked box exists."""
    ticked = [m for m in _live_owner_actions(markers)
              if m.fields.get("issue") == str(issue) and m.fields.get("reason") == "stale-claim"
              and _ticked(m)]
    if not ticked:
        return markers, []
    now: datetime | None = None
    released: list[int] = []

    def judge(owner_action: Marker, snapshot: list[Marker],
              early: tuple[Marker, list[datetime]] | None = None
              ) -> tuple[Marker | None, str, list[datetime]]:
        """Returns the named claim, the verdict and the branch activity judged. `early` is the
        claim as an earlier listing showed it and its branch activity, read before `snapshot`
        was taken, so only the `updated_at` comparison follows `snapshot`."""
        nonlocal now
        claim = _claim_named(snapshot, owner_action)
        if claim is None or claim.comment_id in released or not fm.is_live(claim, snapshot):
            return claim, "released", []
        now = fm.server_now() if now is None else now
        if early is None:
            moments = branch_activity(slug, claim)
        elif claim.fields.get("branch") != early[0].fields.get("branch"):
            return claim, "renewed", []  # only a renewal since the earlier listing changes the branch
        else:
            moments = early[1]
        return claim, ("stale" if is_stale(max([claim.updated_at, *moments]), now) else "renewed"), moments

    def still_ticked(owner_action: Marker, snapshot: list[Marker]) -> Marker | None:
        return next((m for m in _live_owner_actions(snapshot)
                     if m.comment_id == owner_action.comment_id and _ticked(m)), None)

    for marker in ticked:
        current = still_ticked(marker, markers)
        if current is None:
            continue  # ended, or untick, since the listing this loop started from
        claim, verdict, moments = judge(current, markers)
        if verdict == "stale":
            # The snapshot can be old: a renewal ends the box and moves the claim. The branch
            # activity was read after that snapshot; judge once more, on it and a fresh listing,
            # immediately before the irreversible end of the claim, so no forge read sits between
            # that listing and the end.
            early = (claim, moments)
            markers = fm.list_markers(slug, issue)
            current = still_ticked(current, markers)
            if current is None:
                continue
            claim, verdict, _ = judge(current, markers, early)
        if verdict == "stale":
            fm.end(slug, issue, claim.comment_id, "owner-action")
            fm.edit(slug, claim.comment_id, fm.with_fields(claim, released="owner-action"))
            fm.end(slug, issue, current.comment_id, "released")
            released.append(claim.comment_id)
        else:
            fm.end(slug, issue, current.comment_id, verdict)
    again = fm.list_markers(slug, issue)
    if released:
        # Like release: a claim acquired between `again` and the removal gets its label back.
        _, again = _settle_in_progress(slug, issue, again)
    if not _live_owner_actions(again):
        fm.remove_label(slug, issue, OWNER_ACTION[0])
    return again, sorted(released)


def retire_obsolete(slug: str, issue: int, markers: list[Marker], keep: int | None) -> list[int]:
    """End every live stale-claim `owner-action` of the issue naming a claim other than `keep` (D10).

    An `owner-action` of any other reason (a verify-pending prompt, say) is never ended here
    but still counts as live, and a marker with no `claim` field is never ended and still counts
    as live for the label (issue 636, D6). The reason is `renewed` when that claim is live in
    `markers`, else `released`. When at least one was ended and no live `owner-action` of any
    reason remains, the `owner-action` label goes. Returns the ended ids, ascending."""
    live = _live_owner_actions(markers)
    kept = None if keep is None else str(keep)
    obsolete = [m for m in live if m.fields.get("reason") == "stale-claim"
                and "claim" in m.fields and m.fields["claim"] != kept]
    for marker in obsolete:
        claim_live = any(c.kind == CLAIM_KIND and str(c.comment_id) == marker.fields.get("claim")
                         and fm.is_live(c, markers) for c in markers)
        fm.end(slug, issue, marker.comment_id, "renewed" if claim_live else "released")
    if obsolete and len(obsolete) == len(live):
        fm.remove_label(slug, issue, OWNER_ACTION[0])
    return sorted(m.comment_id for m in obsolete)


def acquire(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    markers, freed = honour_ticks(args.repo, args.issue, fm.list_markers(args.repo, args.issue))
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
            return 0, _result(args, "acquired", written.own_id, released_by_owner=freed)
        winner = written.winner
        comment_id = winner.comment_id if winner is not None else None
        if _holder_of(winner) == args.holder:
            return 0, _result(args, "already_held", comment_id, released_by_owner=freed)
        return CONTENDED, _result(args, "lost_to", comment_id, _holder_of(winner), released_by_owner=freed)
    if _holder_of(winner) == args.holder:
        _mark_in_progress(args)
        return 0, _result(args, "already_held", winner.comment_id, released_by_owner=freed)
    return CONTENDED, _result(args, "held_by", winner.comment_id, _holder_of(winner),
                         released_by_owner=freed)


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
    if not retire_owner_actions(args.repo, args.issue, again, winner.comment_id, "renewed"):
        _retired_owner_action_label(args.repo, args.issue, again, winner.comment_id)  # a retried renew
    return 0, _result(args, "renewed", winner.comment_id)


def _last_release(markers: list[Marker], issue: int, holder: str, reason: str) -> Marker | None:
    """The claim a retried `release` finishes: the issue's newest claim, when it is the holder's
    and an `end` marker with `reason` ended it. Its release may have stopped after the `end`
    (the `released` edit, the owner-action retirement or a label call failed), or a delayed
    `renew` PATCH may have dropped its `released` field (D9); every remaining step is idempotent.
    An older claim of the holder is never one: a later claim means its release is long over."""
    claims = [m for m in markers if m.kind == CLAIM_KIND and m.fields.get("issue") == str(issue)]
    newest = max(claims, key=lambda m: m.comment_id, default=None)
    if newest is None or _holder_of(newest) != holder:
        return None
    ended = any(m.kind == fm.END_KIND and m.fields.get("of") == str(newest.comment_id)
                and m.fields.get("reason") == reason for m in markers)
    return newest if ended else None


def _retired_owner_action_label(slug: str, issue: int, markers: list[Marker], claim_id: int) -> None:
    """Remove the `owner-action` label a retried release's retirement left behind: when the claim
    had an `owner-action` marker and none of the issue is live any more (D10)."""
    named = any(m.kind == OWNER_ACTION_KIND and m.fields.get("claim") == str(claim_id) for m in markers)
    if named and not _live_owner_actions(markers):
        fm.remove_label(slug, issue, OWNER_ACTION[0])


def _settle_in_progress(slug: str, issue: int,
                        markers: list[Marker] | None = None) -> tuple[bool, list[Marker]]:
    """Remove the `in-progress` label when no live claim remains, judged on `markers` (a fresh
    listing when None). Returns whether it stays removed and the newest listing taken.

    Removal is not atomic with the listing that justified it, so a listing after the removal
    restores the label when a claim was acquired in between (that acquirer's own labelling may
    have come first)."""
    match = {"issue": str(issue)}
    markers = fm.list_markers(slug, issue) if markers is None else markers
    if fm.contest(markers, CLAIM_KIND, match):
        return False, markers
    fm.remove_label(slug, issue, IN_PROGRESS[0])
    markers = fm.list_markers(slug, issue)
    if fm.contest(markers, CLAIM_KIND, match):
        fm.ensure_label(slug, *IN_PROGRESS)
        fm.add_label(slug, issue, IN_PROGRESS[0])
        return False, markers
    return True, markers


def release(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    markers = fm.list_markers(args.repo, args.issue)
    mine = [m for m in fm.contest(markers, CLAIM_KIND, {"issue": str(args.issue)})
            if _holder_of(m) == args.holder]
    if mine:
        claim = mine[0]
        fm.end(args.repo, args.issue, claim.comment_id, args.reason)
    else:
        claim = _last_release(markers, args.issue, args.holder, args.reason)
        if claim is None:
            # Nothing of this holder's to end; a free issue still sheds a label an earlier release
            # left behind, and a live claim of anyone else keeps it.
            return CONTENDED, _result(args, "not_held",
                                      label_removed=_settle_in_progress(args.repo, args.issue)[0])
    if mine or "released" not in claim.fields:
        fm.edit(args.repo, claim.comment_id, fm.with_fields(claim, released=args.reason))
    if not retire_owner_actions(args.repo, args.issue, markers, claim.comment_id, "released") and not mine:
        _retired_owner_action_label(args.repo, args.issue, markers, claim.comment_id)
    return 0, _result(args, "released", claim.comment_id,
                      label_removed=_settle_in_progress(args.repo, args.issue)[0])


def status(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    markers, freed = honour_ticks(args.repo, args.issue, fm.list_markers(args.repo, args.issue))
    held = fm.contest(markers, CLAIM_KIND, {"issue": str(args.issue)})
    report = {"released_by_owner": freed, "activity_at": None, "owner_action_comment_id": None,
              "owner_action_posted": False}
    if not held:
        retire_obsolete(args.repo, args.issue, markers, None)
        return 0, _result(args, "free", **report)
    winner = held[0]
    activity = activity_at(args.repo, winner)
    report["activity_at"] = activity.strftime("%Y-%m-%dT%H:%M:%SZ")
    base = (winner.comment_id, _holder_of(winner))
    if not is_stale(activity, fm.server_now()):
        retire_obsolete(args.repo, args.issue, markers, None)
        return 0, _result(args, "held_by", *base, **report)
    retire_obsolete(args.repo, args.issue, markers, winner.comment_id)
    match = {"issue": str(args.issue), "reason": "stale-claim", "claim": str(winner.comment_id)}
    existing = fm.contest(markers, OWNER_ACTION_KIND, match)
    if existing:
        report["owner_action_comment_id"] = existing[0].comment_id
    else:
        written = fm.write(
            args.repo, args.issue, OWNER_ACTION_KIND, match,
            f"The claim of {_holder_of(winner)} has had no renewal, push or pull request activity "
            "for 24 hours.", match, f"- [ ] {RELEASE_BOX}")
        report["owner_action_posted"] = written.won
        report["owner_action_comment_id"] = (written.own_id if written.won else
                                             written.winner.comment_id if written.winner else None)
    fm.ensure_label(args.repo, *OWNER_ACTION)
    fm.add_label(args.repo, args.issue, OWNER_ACTION[0])
    return 0, _result(args, "stale", *base, **report)


COMMANDS = {"acquire": acquire, "renew": renew, "release": release, "status": status}


def _emit(result: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")


def retried(args: argparse.Namespace) -> bool:
    """True for the verbs retried whole on a transport error (issue 740, D3)."""
    if args.command in COMMANDS:
        return True
    if args.command == "land":
        return args.action == "release" or (args.action == "acquire" and not args.wait)
    return args.command == "owner-action" and args.action == "status"


def _error_result(args: argparse.Namespace, error: ForgeError) -> dict[str, Any]:
    fields = {"error": error.code, "detail": error.detail, "transient": error.transient}
    if args.command == "land":
        return forge_land_lock.result(args, "error", **fields)
    if args.command == "owner-action":
        return forge_owner_action.result(args, "error", **fields)
    return _result(args, "error", **fields)


def run_verb(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    """Run the parsed verb once, or up to `TRIES` times when `retried` and the failure is transient."""
    tries = TRIES if retried(args) else 1
    attempts = forge_land_lock.Attempts()
    for attempt in range(tries):
        try:
            return (forge_land_lock.run(args, attempts) if args.command == "land"
                    else forge_owner_action.run(args) if args.command == "owner-action"
                    else COMMANDS[args.command](args))
        except ForgeError as error:
            attempts.failed()
            if not error.transient or attempt + 1 >= tries:
                return FORGE_ERROR, _error_result(args, error)
            sleep(BACKOFF[attempt])
    raise AssertionError("unreachable")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        args = build_parser().parse_args(argv)
    except UsageError as error:
        if argv[:1] == ["owner-action"]:
            _emit(forge_owner_action.usage_result(argv, str(error)))
            return USAGE
        if argv[:1] == ["land"]:
            _emit(forge_land_lock.usage_result(argv, str(error)))
            return USAGE
        _emit({"command": argv[0] if argv and argv[0] in COMMANDS else None, "repo": None,
               "issue": None, "holder": None, "verdict": "error", "comment_id": None, "by": None,
               "error": "usage", "detail": str(error)})
        return USAGE
    except SystemExit as stop:  # -h/--help: argparse printed the help text
        return stop.code if isinstance(stop.code, int) else 0
    code, result = run_verb(args)
    _emit(result)
    return code


if __name__ == "__main__":
    sys.exit(main())
