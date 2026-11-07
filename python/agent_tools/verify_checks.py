"""The committed read-only checks that verify blocks name (issue 638).

Each check is a pure function plus one `main` subcommand, run through a wrapper in
`home/common/verify-pending/checks/`. Every check prints one JSON line and exits 0 when met,
1 when not met, 75 when not yet, and 2 on a usage error or an unreadable input.

`required-checks --repo R --base B --since T` is met when the first pull request merged into B
after T had every required check pass before its merge, each from the app its protection binds
it to. It only reads the forge, across every page of each listing, and refuses an incomplete or
truncated listing rather than judging it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from urllib.parse import quote

from agent_tools import forge_markers
from agent_tools.agent_costs import parse_rfc3339_utc

REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_STAMP = "%Y-%m-%dT%H:%M:%SZ"


def _invalid(detail: str) -> forge_markers.ForgeError:
    return forge_markers.ForgeError("payload_invalid", detail)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _forge_time(value: object, what: str) -> datetime:
    try:
        return parse_rfc3339_utc(value)  # type: ignore[arg-type]
    except ValueError:
        raise _invalid(f"{what} is not an RFC 3339 instant") from None


def _counted_pages(pages: Sequence[object], key: str, what: str) -> list[object]:
    """The items of `key` over every page, refused when fewer than the first page's total_count."""
    found: list[object] = []
    total = None
    for page in pages:
        if (not isinstance(page, dict) or not isinstance(page.get(key), list)
                or not _is_int(page.get("total_count"))):
            raise _invalid(f"{what} page has no {key} list and total_count")
        if total is None:
            total = page["total_count"]
        found.extend(page[key])
    if total is not None and len(found) < total:
        raise _invalid(f"{what} is truncated: {len(found)} of {total}")
    return found


def _merged_pull_numbers(repo: str, base: str, since: datetime) -> list[int]:
    since_z = since.astimezone(timezone.utc).strftime(_STAMP)
    query = quote(f"repo:{repo} is:pr is:merged base:{base} merged:>{since_z}", safe="")
    pages = forge_markers.api_pages(
        f"search/issues?q={query}&sort=created&order=asc&per_page=100")
    for page in pages:
        if isinstance(page, dict) and page.get("incomplete_results") is not False:
            raise _invalid("search listing reports incomplete results")
    numbers = []
    for item in _counted_pages(pages, "items", "search listing"):
        if not isinstance(item, dict) or not _is_int(item.get("number")):
            raise _invalid("search item has no number")
        numbers.append(item["number"])
    return numbers


Requirement = tuple[str, int | None]  # (context, app_id); None accepts any app


def _required_checks(repo: str, base: str) -> list[Requirement]:
    """The protection's required checks: `checks` entries keep their app binding (an absent,
    null or -1 `app_id` is any app), and a `contexts` name already in `checks` adds nothing,
    since that legacy list carries no app and must not loosen a bound check."""
    payload = forge_markers.api_get(
        f"repos/{repo}/branches/{base}/protection/required_status_checks")
    if not isinstance(payload, dict):
        raise _invalid("required_status_checks is not an object")
    found: set[Requirement] = set()
    for entry in payload.get("checks") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("context"), str):
            continue
        app_id = entry.get("app_id")
        if app_id is not None and not _is_int(app_id):
            raise _invalid("required check app_id is not an integer or null")
        found.add((entry["context"], None if app_id == -1 else app_id))
    named = {context for context, _ in found}
    for context in payload.get("contexts") or []:
        if isinstance(context, str) and context not in named:
            found.add((context, None))
    return sorted(found, key=lambda item: (item[0], item[1] is not None, item[1] or 0))


def _context_met(requirement: Requirement, runs: Sequence[object], statuses: Sequence[object],
                 merged_at: datetime) -> bool:
    context, app_id = requirement
    for run in runs:
        if not isinstance(run, dict) or run.get("name") != context:
            continue
        app = run.get("app")
        if app_id is not None and not (isinstance(app, dict) and app.get("id") == app_id):
            continue
        if (run.get("status") == "completed" and run.get("conclusion") == "success"
                and _forge_time(run.get("completed_at"), "check run completed_at") <= merged_at):
            return True
    if app_id is not None:
        return False  # a commit status names no app, so it cannot satisfy a bound check
    latest = None
    for status in statuses:
        if not isinstance(status, dict) or status.get("context") != context:
            continue
        updated = _forge_time(status.get("updated_at"), "status updated_at")
        if updated <= merged_at and (latest is None or updated > latest[0]):
            latest = (updated, status.get("state"))
    return latest is not None and latest[1] == "success"


def required_checks(repo: str, base: str, since: datetime) -> tuple[int, dict]:
    """Met when the first pull request merged into `base` after `since` passed every required check."""
    report: dict = {"pr": None, "merged_at": None, "required": [], "missing": []}
    first = None
    for number in _merged_pull_numbers(repo, base, since):
        pull = forge_markers.api_get(f"repos/{repo}/pulls/{number}")
        if not isinstance(pull, dict):
            raise _invalid(f"pull request {number} is not an object")
        if pull.get("merged_at") is None:
            continue
        merged_at = _forge_time(pull["merged_at"], "merged_at")
        if merged_at > since and (first is None or merged_at < first[0]):
            first = (merged_at, number, pull)
    if first is None:
        return 75, report
    merged_at, number, pull = first
    head = pull.get("head")
    sha = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(sha, str) or not sha:
        raise _invalid("pull request has no head sha")
    report.update(pr=number, merged_at=pull["merged_at"])
    required = _required_checks(repo, base)
    report["required"] = sorted({context for context, _ in required})
    if not required:
        return 1, report
    runs = _counted_pages(forge_markers.api_pages(
        f"repos/{repo}/commits/{sha}/check-runs?per_page=100"), "check_runs", "check-run listing")
    status_pages = forge_markers.api_pages(f"repos/{repo}/commits/{sha}/statuses?per_page=100")
    if not all(isinstance(page, list) for page in status_pages):
        raise _invalid("status page is not a list")
    statuses = [entry for page in status_pages for entry in page]
    report["missing"] = sorted({r[0] for r in required
                                if not _context_met(r, runs, statuses, merged_at)})
    return (0 if not report["missing"] else 1), report


def _repo(value: str) -> str:
    if not REPO.match(value):
        raise argparse.ArgumentTypeError("must be OWNER/NAME")
    return value


def _rfc3339(value: str) -> datetime:
    try:
        return parse_rfc3339_utc(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an RFC 3339 instant with Z or an offset") from None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify-checks")
    checks = parser.add_subparsers(dest="check", required=True)
    required = checks.add_parser("required-checks",
                                 help="issue 627: required checks passed before the merge")
    required.add_argument("--repo", type=_repo, required=True)
    required.add_argument("--base", required=True)
    required.add_argument("--since", type=_rfc3339, required=True)
    args = parser.parse_args(argv)
    try:
        code, report = required_checks(args.repo, args.base, args.since)
    except forge_markers.ForgeError as error:
        print(f"verify-checks: forge_error: {error.code}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
