"""The `console-takeover-merge` verify check.

`console-takeover-merge --since SHA [--log PATH] [--repo-root DIR]` (`console_takeover_merge`), run through the
wrapper `home/common/verify-pending/checks/console-takeover-merge` as
`python -m agent_tools.verification.console_takeover_merge`, is met when a takeover manager the console launched
had its own merge allowed by the permit after the change was activated. It reads the console's event log
read-only (`--log`, default `events.sqlite3` under the console's state directory) and the repository at
`--repo-root` (default `.`); the anchor is `console-manager-merge`'s (the earliest ok `activation.finished`
whose commit has `--since` as ancestor or equal), and with none the check is `not_yet` (75). The window is from
the anchor's time to fourteen days after it. It is met (0) when a `permit.judged` row at a time inside the
window, with verb `merge`, decision `allow`, a string `sprint_id` and a string `session_id`, follows (in
sequence order) a `manager.started` row of that sprint, the latest such row, whose `takeover` is exactly true
and whose `short_id` is a string of eight lowercase hex digits that is the first eight characters of the
`session_id`. Otherwise it is `not_yet` (75) while the verifier's clock is inside the window and `not_met` (1)
once it is past. The report is `{"met", "verdict", "judged_at", "started_at", "activated_at"}`, the last three
null unless met, and names no project, root, sprint or session; any project's sprint counts. A malformed
`--since` is a usage error (2) before any read; an unreadable log or git is 2 with one stderr line
`verify-checks: <kind>: <message>`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

from agent_tools.project_contract import agent_platform
from agent_tools.verification.verify_checks import (
    GitError, ToolError, _log_rows, _manager_merge_anchor, _merge_sha, _utcnow)

TAKEOVER_MERGE_WINDOW = timedelta(days=14)
_TAKEOVER_MERGE_EMPTY = {"judged_at": None, "started_at": None, "activated_at": None}


def console_takeover_merge(since: str, *, log: Path | None = None,
                           repo_root: Path = Path(".")) -> tuple[int, dict]:
    """A takeover manager the console launched had its own merge allowed by the permit."""
    store = log if log is not None else agent_platform.state_root() / "console" / "events.sqlite3"
    rows = _log_rows(store, ("activation.finished", "manager.started", "permit.judged"))
    start = _manager_merge_anchor(rows, since, repo_root)
    if start is None:
        return 75, {"met": False, "verdict": "not_yet", **_TAKEOVER_MERGE_EMPTY}
    end = start + TAKEOVER_MERGE_WINDOW
    latest = {}
    for when, kind, payload in rows:
        sprint, session = payload.get("sprint_id"), payload.get("session_id")
        if kind == "manager.started" and isinstance(sprint, str):
            latest[sprint] = (when, payload)
        elif (kind == "permit.judged" and start <= when <= end and payload.get("verb") == "merge"
                and payload.get("decision") == "allow" and isinstance(sprint, str)
                and isinstance(session, str) and sprint in latest):
            started_at, started = latest[sprint]
            short_id = started.get("short_id")
            if (started.get("takeover") is True and isinstance(short_id, str)
                    and re.fullmatch(r"[0-9a-f]{8}", short_id) and session[:8] == short_id):
                return 0, {"met": True, "verdict": "met", "judged_at": when.isoformat(),
                           "started_at": started_at.isoformat(), "activated_at": start.isoformat()}
    if _utcnow() <= end:
        return 75, {"met": False, "verdict": "not_yet", **_TAKEOVER_MERGE_EMPTY}
    return 1, {"met": False, "verdict": "not_met", **_TAKEOVER_MERGE_EMPTY}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="console-takeover-merge")
    parser.add_argument("--since", type=_merge_sha, required=True)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    try:
        code, report = console_takeover_merge(args.since, log=args.log, repo_root=args.repo_root)
    except (ToolError, GitError) as error:
        print(f"verify-checks: {getattr(error, 'kind', 'git_error')}: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
