"""The `console-production-rerun` verify check.

`console-production-rerun --since SHA [--log PATH] [--repo-root DIR]` (`console_production_rerun`),
run through the wrapper `home/common/verify-pending/checks/console-production-rerun` as
`python -m agent_tools.verification.console_production_rerun`, is met when a sprint's manager was allowed to rerun
its own pull request's check run in a project whose guard policy declares `gh run rerun` as a production change,
and the rerun ran, after the change was activated. It reads the console's event log read-only (`--log`, default
`events.sqlite3` under the console's state directory), the repository at `--repo-root` (default `.`) and the
forge; it reads no policy file, because each activation rewrites that file. The anchor is
`console-manager-merge`'s, and with none the check is `not_yet` (75). The window is from the anchor's time to
twenty-one days after it. A `permit.judged` row in the window is a candidate when its verb is `rerun`, its decision
`allow`, its `target` holds integer `run` and `pr` and no `release`, its `sprint_id` and `session_id` are strings,
its `tool_use_id` is a non-empty string and its `repo` is a string. It counts when all of these hold:

- the verdict records, as `rule`, the `production.changes` entry of its project that the guard's policy, loaded
  whole, held when the verdict was given, and that entry's `argv`, with the program replaced by its basename, is
  `gh run rerun`: the console records it with the verdict, so a later activation changes nothing;
- a `permit.landed` row in the window, at or after the verdict, has verb `rerun` and the verdict's `sprint_id`,
  `session_id`, `tool_use_id` and `repo`, and a `target` whose `run` is the verdict's: the console posts it
  after the manager's call has run, so a rerun started by hand after the guard refused the call has none;
- the forge lists an attempt of that run that started from one minute before the verdict to fifteen minutes
  after it, and inside the window.

The forge is read only for a row that passed the earlier tests. A forge that cannot be read is a tool failure (2).
The result is met (0), else `not_yet` (75) while the verifier's clock is inside the window and `not_met` (1) once it
is past. The report is `{"met", "verdict", "run", "pr", "judged_at", "landed_at", "attempt_started_at",
"activated_at"}`, the last six null unless met, and names no project, sprint or session. A malformed `--since` is a
usage error (2) before any read; an unreadable log, git or forge is 2.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path

from agent_tools.console import permission
from agent_tools.project_contract import agent_platform
from agent_tools.system import forge_api
from agent_tools.verification.verify_checks import (
    GitError, ToolError, _forge_time, _is_int, _log_rows, _manager_merge_anchor, _merge_sha, _utcnow)

PRODUCTION_RERUN_WINDOW = timedelta(days=21)
ATTEMPT_EARLIEST = timedelta(minutes=1)
ATTEMPT_LATEST = timedelta(minutes=15)
_EMPTY = {"run": None, "pr": None, "judged_at": None, "landed_at": None, "attempt_started_at": None,
          "activated_at": None}


def attempt_starts(slug: str, run_id: int) -> list[datetime]:
    """The start times of the reruns (attempts 2 and later) of a run, as the forge records them.

    A run or attempt the forge no longer has (HTTP 404) shows no rerun, so it is skipped, not a failure."""
    try:
        run = forge_api.api_get(f"repos/{slug}/actions/runs/{run_id}", allow=(404,))
        if run is None:
            return []
        count = run.get("run_attempt") if isinstance(run, dict) else None
        if not _is_int(count) or count < 1:
            raise forge_api.ForgeError("payload_invalid", "run_attempt is not a positive integer")
        starts = []
        for number in range(2, count + 1):
            attempt = forge_api.api_get(f"repos/{slug}/actions/runs/{run_id}/attempts/{number}", allow=(404,))
            if attempt is None:
                continue
            if not isinstance(attempt, dict):
                raise forge_api.ForgeError("payload_invalid", "an attempt is not an object")
            starts.append(_forge_time(attempt.get("run_started_at"), "run_started_at"))
        return starts
    except forge_api.ForgeError as error:
        raise ToolError("forge_unreadable", str(error)) from error


def console_production_rerun(since: str, *, log: Path | None = None, repo_root: Path = Path("."),
                             read_attempts: Callable[[str, int], list[datetime]] | None = None
                             ) -> tuple[int, dict]:
    """A manager's allowed rerun of its own pull request's run, in a declaring project, ran after activation."""
    store = log if log is not None else agent_platform.state_root() / "console" / "events.sqlite3"
    read = read_attempts if read_attempts is not None else attempt_starts
    rows = _log_rows(store, ("activation.finished", "permit.judged", "permit.landed"))
    start = _manager_merge_anchor(rows, since, repo_root)
    if start is None:
        return 75, {"met": False, "verdict": "not_yet", **_EMPTY}
    end = start + PRODUCTION_RERUN_WINDOW
    landings = [(when, payload) for when, kind, payload in rows
                if kind == "permit.landed" and start <= when <= end]
    for judged_at, kind, judged in rows:
        target = judged.get("target")
        repo, call = judged.get("repo"), judged.get("tool_use_id")
        sprint, session = judged.get("sprint_id"), judged.get("session_id")
        if (kind != "permit.judged" or not start <= judged_at <= end or judged.get("verb") != "rerun"
                or judged.get("decision") != "allow" or not isinstance(target, dict)
                or not _is_int(target.get("run")) or not _is_int(target.get("pr")) or "release" in target
                or not isinstance(sprint, str) or not isinstance(session, str)
                or not isinstance(call, str) or not call or not isinstance(repo, str)
                or not permission.is_rerun_change(judged.get("rule"))):
            continue
        landed_at = next((when for when, landed in landings
                          if when >= judged_at and landed.get("verb") == "rerun"
                          and landed.get("sprint_id") == sprint and landed.get("session_id") == session
                          and landed.get("tool_use_id") == call and landed.get("repo") == repo
                          and isinstance(landed.get("target"), dict)
                          and landed["target"].get("run") == target["run"]), None)
        if landed_at is None:
            continue
        for started in read(repo, target["run"]):
            if (judged_at - ATTEMPT_EARLIEST <= started <= judged_at + ATTEMPT_LATEST
                    and start <= started <= end):
                return 0, {"met": True, "verdict": "met", "run": target["run"], "pr": target["pr"],
                           "judged_at": judged_at.isoformat(), "landed_at": landed_at.isoformat(),
                           "attempt_started_at": started.isoformat(), "activated_at": start.isoformat()}
    if _utcnow() <= end:
        return 75, {"met": False, "verdict": "not_yet", **_EMPTY}
    return 1, {"met": False, "verdict": "not_met", **_EMPTY}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="console-production-rerun")
    parser.add_argument("--since", type=_merge_sha, required=True)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    try:
        code, report = console_production_rerun(args.since, log=args.log, repo_root=args.repo_root)
    except (ToolError, GitError) as error:
        print(f"verify-checks: {getattr(error, 'kind', 'git_error')}: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
