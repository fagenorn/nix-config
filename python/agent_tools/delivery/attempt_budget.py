"""The `attempt-budget` command: read a project's delivered attempts from its tracker.

It reads the integration branch's merged pull requests and the claim comments of their
issues, derives the attempts (ADR-project-contract-016), prints the budget they give,
and with `record` writes them as the project's attempt history, the file a schema-3
resolver derives `attempt_budget_minutes` from. Nothing refreshes the history but
running `record`: a stale history is used as recorded and its `recorded_at` is in the
basis.

Commands, each with a required `--repo-root PATH`:

- `report` prints the result and writes nothing.
- `record` prints the same result and replaces the history file.

Output is one JSON line on stdout with exactly these members: `command`, `repo`,
`integration_branch`, `recorded_at`, `budget_minutes`, `basis`, `percentile_90_minutes`
(minutes, one decimal; null when the basis is a fallback), `attempts` (the attempts the
budget used, latest merge first, each `issue`, `pull`, `claimed_at`, `merged_at`,
`duration_minutes`) and `history` (the written file's absolute path for `record`, null
for `report`). Exit 0 prints it; exit 1 is a forge error or a failed write
(`{"command", "error": {"code", "detail", "transient"}}`, nothing written on a forge
error); exit 2 is a resolver refusal (the error document `resolve-project resolve`
prints), an unsupported branch pattern (`branch_pattern_unsupported`), a tracker that is not
GitHub (`tracker_unsupported`; nothing is read or written) or a usage error.

The attempt rule. An attempt starts at a claim marker comment's `created_at` (a renewal
moves only `updated_at`). A claim is delivered by the earliest merged pull request of
its issue merged in `[created, next claim's created)`, no later than the claim's end
when an `end` marker names it, and headed on the claim's `branch` when it names one;
otherwise the claim stopped or still runs and has no merge. A merge no claim takes is
not an attempt. Everything is judged at the forge time read before any tracker read:
a merge, claim or end marker after it is ignored, so the verify check judges the same
instant.

A pull request counts when it is merged, its base is the integration branch, its head
repository is its base repository (the pull request's own names, compared
case-insensitively; a deleted fork does not count and a missing `head.repo` is a forge
error), and its head matches the snapshot's branch pattern.

Paging. Closed pull requests are read newest-updated first, 100 a page. Reading stops
after the last page, or when the 20 delivered attempts with the latest merges all
started strictly after the oldest `updated_at` read: every unread pull request merged
at or before that horizon, so before those claims. A claim at exactly the horizon keeps
paging.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote

from agent_tools.claims import forge_markers
from agent_tools.delivery import issue_branch
from agent_tools.project_contract import attempt_history, resolve_project
from agent_tools.system import forge_api
from agent_tools.system.forge_api import ForgeError

PAGE_SIZE = 100


class Claim(NamedTuple):
    created_at: datetime
    comment_id: int
    ended_at: datetime | None
    branch: str | None


class Merge(NamedTuple):
    pull: int
    merged_at: datetime
    head: str


def branch_issue(pattern: str) -> re.Pattern[str] | None:
    """The regex of any issue's branch under `pattern` (group 1 is the issue), or None."""
    if "<num>" not in pattern or "<slug>" not in pattern:
        return None
    if "<num><slug>" in pattern or "<slug><num>" in pattern:
        return None
    seen = False
    parts = []
    for part in issue_branch.PLACEHOLDERS.split(pattern):
        if part == "<num>":
            parts.append(r"(?P=issue)" if seen else r"(?P<issue>\d+)")
            seen = True
        else:
            parts.append(issue_branch.SLUG_CLASS if part == "<slug>" else re.escape(part))
    return re.compile("".join(parts))


def invalid(detail: str) -> ForgeError:
    return ForgeError("payload_invalid", detail)


def moment(value: object, what: str) -> datetime:
    try:
        return attempt_history.instant(value)
    except ValueError:
        raise invalid(f"{what} is not a timestamp: {value!r}") from None


def pair(issue: int, claims: Sequence[Claim], merges: Sequence[Merge]) -> list[attempt_history.Attempt]:
    """One attempt per claim of `issue`, paired with the merge that delivered it, if any."""
    ordered = sorted(claims, key=lambda c: (c.created_at, c.comment_id))
    by_merge = sorted(merges, key=lambda m: (m.merged_at, m.pull))
    attempts = []
    for index, claim in enumerate(ordered):
        following = ordered[index + 1].created_at if index + 1 < len(ordered) else None
        taken = next((m for m in by_merge
                      if m.merged_at >= claim.created_at
                      and (following is None or m.merged_at < following)
                      and (claim.ended_at is None or m.merged_at <= claim.ended_at)
                      and (claim.branch is None or m.head == claim.branch)), None)
        attempts.append(attempt_history.Attempt(
            issue, taken and taken.pull, claim.created_at, taken and taken.merged_at))
    return attempts


def same_repository(pull: dict) -> bool | None:
    """Whether the pull request's head repository is its base repository; None for a deleted fork."""
    number = pull.get("number")
    head, base = pull.get("head"), pull.get("base")
    if not isinstance(head, dict) or "repo" not in head:
        raise invalid(f"pull request {number} head repo is missing")
    if not isinstance(base, dict) or not isinstance(base.get("repo"), dict):
        raise invalid(f"pull request {number} base repo is not an object")
    base_name = base["repo"].get("full_name")
    if not isinstance(base_name, str):
        raise invalid(f"pull request {number} base repo full_name is not a string")
    repo = head["repo"]
    if repo is None:
        return None
    if not isinstance(repo, dict) or not isinstance(repo.get("full_name"), str):
        raise invalid(f"pull request {number} head repo is not a named object")
    return repo["full_name"].lower() == base_name.lower()


def claims_of(slug: str, issue: int, now: datetime) -> list[Claim]:
    """The claims of `issue` at `now`, each with the earliest end marker that names it."""
    markers = []
    for comment in forge_markers.list_comments(slug, issue):
        marker = forge_markers.parse(comment)
        if marker is None:
            continue
        created = moment(comment.get("created_at"), f"comment {marker.comment_id} created_at")
        if created <= now:
            markers.append((marker, created))
    ends: dict[str, datetime] = {}
    for marker, created in markers:
        if marker.kind == forge_markers.END_KIND and "of" in marker.fields:
            ends[marker.fields["of"]] = min(created, ends.get(marker.fields["of"], created))
    return [Claim(created, marker.comment_id, ends.get(str(marker.comment_id)), marker.fields.get("branch"))
            for marker, created in markers
            if marker.kind == "claim" and marker.fields.get("issue") == str(issue)]


def tracker_attempts(slug: str, branch: str, head: re.Pattern[str],
                     now: datetime) -> list[attempt_history.Attempt]:
    """Every attempt the tracker shows at `now`, paging only as far as the window needs."""
    merges: dict[int, list[Merge]] = {}
    claims: dict[int, list[Claim]] = {}
    attempts: list[attempt_history.Attempt] = []
    horizon: datetime | None = None
    page_number = 0
    while True:
        page_number += 1
        page = forge_api.api_get(
            f"repos/{slug}/pulls?state=closed&base={quote(branch)}&sort=updated"
            f"&direction=desc&per_page={PAGE_SIZE}&page={page_number}")
        if not isinstance(page, list):
            raise invalid("pull request page is not an array")
        for pull in page:
            if not isinstance(pull, dict):
                raise invalid("pull request is not an object")
            number = pull.get("number")
            if type(number) is not int:
                raise invalid("pull request number is not an integer")
            updated = moment(pull.get("updated_at"), f"pull request {number} updated_at")
            horizon = updated if horizon is None else min(horizon, updated)
            if pull.get("merged_at") is None:
                continue
            merged = moment(pull["merged_at"], f"pull request {number} merged_at")
            base = pull.get("base")
            if merged > now or not isinstance(base, dict) or base.get("ref") != branch:
                continue
            if same_repository(pull) is not True:
                continue
            ref = pull["head"].get("ref")
            found = head.fullmatch(ref) if isinstance(ref, str) else None
            if found is None:
                continue
            merges.setdefault(int(found.group(1)), []).append(Merge(number, merged, ref))
        attempts = []
        for issue, issue_merges in merges.items():
            if issue not in claims:
                claims[issue] = claims_of(slug, issue, now)
            attempts += pair(issue, claims[issue], issue_merges)
        if len(page) < PAGE_SIZE:
            return attempts
        used = attempt_history.budget(attempts, now).used
        if len(used) == attempt_history.WINDOW and all(a.claimed_at > horizon for a in used):
            return attempts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="attempt-budget",
        description="Read a project's delivered attempts from its tracker; optionally record them.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("report", "print the budget the tracker gives, writing nothing"),
                            ("record", "print it and write the attempt history")):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--repo-root", required=True, help="the project root")
    return parser


def failure(command: str, code: str, detail: str, transient: bool = False) -> int:
    resolve_project.emit_json(
        {"command": command, "error": {"code": code, "detail": detail, "transient": transient}})
    return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        snapshot = resolve_project.resolve(args.repo_root)
    except resolve_project.ContractError as error:
        return resolve_project.emit_error(
            error.code, error.repair_id, error.violations, error.reason_code)
    kind = snapshot["bindings"]["tracker"]["kind"]
    if kind != "github":
        resolve_project.emit_json({"command": args.command, "error": {
            "code": "tracker_unsupported",
            "detail": f"tracker kind {kind!r} is not github; the history reads GitHub only",
            "transient": False}})
        return 2
    slug = snapshot["bindings"]["tracker"]["repo_slug"]
    branch = snapshot["bindings"]["vcs"]["integration_branch"]
    pattern = snapshot["bindings"]["vcs"]["branch_pattern"]
    head = branch_issue(pattern)
    if head is None:
        resolve_project.emit_json({"command": args.command, "error": {
            "code": "branch_pattern_unsupported",
            "detail": f"branch pattern {pattern!r} needs a <num> and a <slug> that are not adjacent",
            "transient": False}})
        return 2
    try:
        now = forge_api.server_now()
        attempts = tracker_attempts(slug, branch, head, now)
    except ForgeError as error:
        return failure(args.command, error.code, error.detail, error.transient)
    result = attempt_history.budget(attempts, now)
    written = None
    if args.command == "record":
        root = Path(snapshot["project"]["root"])
        try:
            written = attempt_history.write_history(
                root, attempt_history.render_history(slug, now, attempts))
        except OSError as error:
            return failure(args.command, "write_failed", str(error))
    percentile = result.basis.get("percentile_90_seconds")
    resolve_project.emit_json({
        "command": args.command,
        "repo": slug,
        "integration_branch": branch,
        "recorded_at": attempt_history.stamp(now),
        "budget_minutes": result.minutes,
        "basis": result.basis,
        "percentile_90_minutes": None if percentile is None else round(percentile / 60, 1),
        "attempts": [{
            "issue": a.issue,
            "pull": a.pull,
            "claimed_at": attempt_history.stamp(a.claimed_at),
            "merged_at": attempt_history.stamp(a.merged_at),
            "duration_minutes": round(a.seconds() / 60, 1),
        } for a in result.used],
        "history": None if written is None else str(written),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
