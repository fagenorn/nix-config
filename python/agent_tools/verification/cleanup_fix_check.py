"""The first cleanup fix change reports its required checks within the window after the run that picked it.

Met (exit 0) when the lowest-numbered pull request whose trusted author carries the fix marker has
a check run, in any status, for every check the base branch requires (an app-bound check needs a
run of that app). Not yet (exit 75): `waiting` (a check unreported for under 60 minutes since the
pull request opened), `queue_held` (a trusted cleanup issue is open, so no clock runs), `no_run`
(the slot is free but the workflow has not run since) or `deferred` (the window has not elapsed).
Not met (exit 1): `no_required_checks`, `not_met` (a check still unreported after 60 minutes) or
`not_opened` (the window elapsed with no fix change, or the slot was never freed). Exit 2 is a
forge error. The window counts from the first workflow run created at or after the latest trusted
cleanup issue close, never from a merge. The check is read-only: it never files an issue.
"""
import argparse
import json
import re
import sys
from collections.abc import Sequence
from datetime import timedelta

from agent_tools.claims.forge_markers import body_markers, trusted_author
from agent_tools.system import forge_api
from agent_tools.verification.verify_checks import (
    _STAMP, _counted_pages, _forge_time, _invalid, _is_int, _required_checks, _ruleset_checks,
)

FIX_KIND = "cleanup-fix"
CLEANUP_KIND = "cleanup"
FILER = "github-actions[bot]"
TRUSTED = ("OWNER", "MEMBER")
WAIT = timedelta(minutes=60)
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _items(pages: Sequence[object], what: str) -> list[dict]:
    found: list[dict] = []
    for page in pages:
        if not isinstance(page, list) or not all(isinstance(item, dict) for item in page):
            raise _invalid(f"{what} page is not a list of objects")
        found.extend(page)
    return found


def _marked(item: dict, kind: str, logins: Sequence[str]) -> bool:
    return (trusted_author(item, logins, TRUSTED)
            and any(set(fields) == {"rule"}
                    for fields in body_markers(item.get("body") or "", kind)))


def _cleanup_issues(items: Sequence[dict]) -> list[dict]:
    return [item for item in items
            if "pull_request" not in item and _marked(item, CLEANUP_KIND, (FILER,))]


def _number(item: dict) -> int:
    if not _is_int(item.get("number")):
        raise _invalid("listed item has no number")
    return item["number"]


def _judge_fix_change(repo: str, base: str, item: dict, report: dict) -> int:
    head = item.get("head")
    sha = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(sha, str) or not sha:
        raise _invalid("fix change has no head sha")
    required = {*_required_checks(repo, base), *_ruleset_checks(repo, base)}
    report.update(pr=_number(item), head=sha, required=sorted({context for context, _ in required}))
    if not required:
        report["status"] = "no_required_checks"
        return 1
    runs = _counted_pages(forge_api.api_pages(
        f"repos/{repo}/commits/{sha}/check-runs?per_page=100"), "check_runs", "check-run listing")
    reported = set()
    for context, app_id in required:
        for run in runs:
            app = run.get("app") if isinstance(run, dict) else None
            if (isinstance(run, dict) and run.get("name") == context
                    and (app_id is None or (isinstance(app, dict) and app.get("id") == app_id))):
                reported.add((context, app_id))
                break
    report["missing"] = sorted({context for context, app_id in required
                                if (context, app_id) not in reported})
    if not report["missing"]:
        report["status"] = "met"
        return 0
    opened = _forge_time(item.get("created_at"), "fix change created_at")
    if forge_api.server_now() - opened < WAIT:
        report["status"] = "waiting"
        return 75
    report["status"] = "not_met"
    return 1


def cleanup_fix_checks(repo: str, base: str, workflow: str, window_days: int) -> tuple[int, dict]:
    report: dict = {"pr": None, "head": None, "required": [], "missing": [], "held": None,
                    "freed": None, "picked": None, "status": None}
    pulls = _items(forge_api.api_pages(f"repos/{repo}/pulls?state=all&base={base}&per_page=100"),
                   "pull request listing")
    fixes = sorted((item for item in pulls if _marked(item, FIX_KIND, ())), key=_number)
    if fixes:
        return _judge_fix_change(repo, base, fixes[0], report), report
    held = _cleanup_issues(_items(forge_api.api_pages(
        f"repos/{repo}/issues?state=open&per_page=100"), "open issue listing"))
    if held:
        report.update(held=min(_number(item) for item in held), status="queue_held")
        return 75, report
    now = forge_api.server_now()
    since = (now - timedelta(days=2 * window_days)).strftime(_STAMP)
    closed = _cleanup_issues(_items(forge_api.api_pages(
        f"repos/{repo}/issues?state=closed&since={since}&per_page=100"), "closed issue listing"))
    if not closed:
        report["status"] = "not_opened"
        return 1, report
    freed = max(_forge_time(item.get("closed_at"), "cleanup issue closed_at") for item in closed)
    freed_z = freed.strftime(_STAMP)
    report["freed"] = freed_z
    runs = _counted_pages(forge_api.api_pages(
        f"repos/{repo}/actions/workflows/{workflow}/runs?branch={base}"
        f"&created=%3E%3D{freed_z}&per_page=100"), "workflow_runs", "workflow run listing")
    if not runs:
        report["status"] = "no_run"
        return 75, report
    picked = min(_forge_time(run.get("created_at") if isinstance(run, dict) else None,
                             "workflow run created_at") for run in runs)
    report["picked"] = picked.strftime(_STAMP)
    if now - picked < timedelta(days=window_days):
        report["status"] = "deferred"
        return 75, report
    report["status"] = "not_opened"
    return 1, report


def _repo(value: str) -> str:
    if not REPO.match(value):
        raise argparse.ArgumentTypeError("must be OWNER/NAME")
    return value


def _days(value: str) -> int:
    try:
        days = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer") from None
    if days < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return days


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cleanup-fix-checks")
    parser.add_argument("--repo", type=_repo, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--window-days", type=_days, required=True)
    args = parser.parse_args(argv)
    try:
        code, report = cleanup_fix_checks(args.repo, args.base, args.workflow, args.window_days)
    except forge_api.ForgeError as error:
        print(f"cleanup-fix-checks: forge_error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
