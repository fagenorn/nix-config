"""The `console-release-rerun` verify check.

`console-release-rerun --since SHA [--log PATH] [--repo-root DIR]` (`console_release_rerun`), run through the
wrapper `home/common/verify-pending/checks/console-release-rerun` as
`python -m agent_tools.verification.console_release_rerun`, is met when a sprint's manager was allowed to rerun the
failed jobs of a release pull request's run or of the candidate's push run, after the change was activated. It
reads the console's event log read-only (`--log`, default `events.sqlite3` under the console's state directory)
and the repository at `--repo-root` (default `.`); the anchor is `console-manager-merge`'s, and with none the
check is `not_yet` (75). The window is from the anchor's time to twenty-one days after it. It is met (0) when,
inside the window, a `permit.judged` row with verb `rerun`, decision `allow`, a `target` of integer `run` and a
`release` of `pull_request` or `push`, and a string `sprint_id` and `session_id` is in the log. No `session.seen`
listing is required: the console writes an allowed row only for a manager session, so the row is the proof of the
manager. Otherwise it is `not_yet` (75) while the verifier's clock is inside the window and `not_met` (1) once
it is past. The report is `{"met", "verdict", "run", "release", "judged_at", "activated_at"}`, the last four null
unless met, and names no project, sprint or session. A malformed `--since` is a usage error (2) before any read;
an unreadable log or git is 2.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

from agent_tools.project_contract import agent_platform
from agent_tools.verification.verify_checks import (
    GitError, ToolError, _is_int, _log_rows, _manager_merge_anchor, _merge_sha, _utcnow)

RELEASE_RERUN_WINDOW = timedelta(days=21)
_RELEASE_RERUN_EMPTY = {"run": None, "release": None, "judged_at": None, "activated_at": None}
_RELEASE_EVENTS = ("pull_request", "push")


def console_release_rerun(since: str, *, log: Path | None = None,
                          repo_root: Path = Path(".")) -> tuple[int, dict]:
    """A manager was allowed to rerun a release run's failed jobs, after activation."""
    store = log if log is not None else agent_platform.state_root() / "console" / "events.sqlite3"
    rows = _log_rows(store, ("activation.finished", "permit.judged"))
    start = _manager_merge_anchor(rows, since, repo_root)
    if start is None:
        return 75, {"met": False, "verdict": "not_yet", **_RELEASE_RERUN_EMPTY}
    end = start + RELEASE_RERUN_WINDOW
    for judged_at, kind, judged in rows:
        target = judged.get("target")
        if (kind != "permit.judged" or not start <= judged_at <= end or judged.get("verb") != "rerun"
                or judged.get("decision") != "allow" or not isinstance(target, dict)
                or not _is_int(target.get("run")) or target.get("release") not in _RELEASE_EVENTS
                or not isinstance(judged.get("sprint_id"), str)
                or not isinstance(judged.get("session_id"), str)):
            continue
        return 0, {"met": True, "verdict": "met", "run": target["run"], "release": target["release"],
                   "judged_at": judged_at.isoformat(), "activated_at": start.isoformat()}
    if _utcnow() <= end:
        return 75, {"met": False, "verdict": "not_yet", **_RELEASE_RERUN_EMPTY}
    return 1, {"met": False, "verdict": "not_met", **_RELEASE_RERUN_EMPTY}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="console-release-rerun")
    parser.add_argument("--since", type=_merge_sha, required=True)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    try:
        code, report = console_release_rerun(args.since, log=args.log, repo_root=args.repo_root)
    except (ToolError, GitError) as error:
        print(f"verify-checks: {getattr(error, 'kind', 'git_error')}: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
