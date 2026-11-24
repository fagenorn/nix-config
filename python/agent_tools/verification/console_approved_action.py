"""The `console-approved-action` verify check.

`console-approved-action --since SHA [--log PATH] [--repo-root DIR]` (`console_approved_action`), run through the
wrapper `home/common/verify-pending/checks/console-approved-action` as
`python -m agent_tools.verification.console_approved_action`, is met when a sprint's manager ran an action the
owner approved on a console card, from its own session, after the change was activated. It reads the console's
event log read-only (`--log`, default `events.sqlite3` under the console's state directory) and the repository at
`--repo-root` (default `.`); the anchor is `console-manager-merge`'s, and with none the check is `not_yet` (75).
The window is from the anchor's time to thirty days after it. It is met (0) when, inside the window, a
`permit.judged` row with verb `action`, decision `allow`, a `target` of integer `round` and `index`, a
`sprint_id`, a `session_id` that a `session.seen` row called `<project> sprint <that row's sprint id>` and a
`tool_use_id` is followed, at or after it and inside the window, by a `permit.landed` row with verb `action` and
the same sprint, session, `tool_use_id` and target. Otherwise it is `not_yet` (75) while the verifier's clock is
inside the window and `not_met` (1) once it is past. The report is `{"met", "verdict", "round", "index",
"judged_at", "landed_at", "activated_at"}`, the last five null unless met, and names no project, sprint, session
or command. A malformed `--since` is a usage error (2) before any read; an unreadable log or git is 2.
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

APPROVED_ACTION_WINDOW = timedelta(days=30)
_APPROVED_ACTION_EMPTY = {"round": None, "index": None, "judged_at": None, "landed_at": None,
                          "activated_at": None}


def console_approved_action(since: str, *, log: Path | None = None,
                            repo_root: Path = Path(".")) -> tuple[int, dict]:
    """A manager ran an action the owner approved on a console card, from its own session."""
    store = log if log is not None else agent_platform.state_root() / "console" / "events.sqlite3"
    rows = _log_rows(store, ("activation.finished", "session.seen", "permit.judged", "permit.landed"))
    start = _manager_merge_anchor(rows, since, repo_root)
    if start is None:
        return 75, {"met": False, "verdict": "not_yet", **_APPROVED_ACTION_EMPTY}
    end = start + APPROVED_ACTION_WINDOW
    named = {(payload.get("session_id"), payload.get("name"))
             for _, kind, payload in rows if kind == "session.seen"}

    def target_of(payload):
        target = payload.get("target")
        if isinstance(target, dict) and _is_int(target.get("round")) and _is_int(target.get("index")):
            return target["round"], target["index"]
        return None

    def in_window(when):
        return start <= when <= end

    landings = [(when, payload, target_of(payload)) for when, kind, payload in rows
                if kind == "permit.landed" and in_window(when) and payload.get("verb") == "action"]
    for judged_at, kind, judged in rows:
        sprint, session, target = judged.get("sprint_id"), judged.get("session_id"), target_of(judged)
        call = judged.get("tool_use_id")
        if (kind != "permit.judged" or not in_window(judged_at) or judged.get("verb") != "action"
                or judged.get("decision") != "allow" or target is None
                or not isinstance(sprint, str) or not isinstance(session, str)
                or not isinstance(call, str) or not call
                or not any(seen == session and isinstance(name, str) and name.endswith(f" sprint {sprint}")
                           and len(name) > len(f" sprint {sprint}") for seen, name in named)):
            continue
        for landed_at, landed, landed_target in landings:
            if (landed_at >= judged_at and landed_target == target and landed.get("sprint_id") == sprint
                    and landed.get("session_id") == session and landed.get("tool_use_id") == call):
                return 0, {"met": True, "verdict": "met", "round": target[0], "index": target[1],
                           "judged_at": judged_at.isoformat(), "landed_at": landed_at.isoformat(),
                           "activated_at": start.isoformat()}
    if _utcnow() <= end:
        return 75, {"met": False, "verdict": "not_yet", **_APPROVED_ACTION_EMPTY}
    return 1, {"met": False, "verdict": "not_met", **_APPROVED_ACTION_EMPTY}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="console-approved-action")
    parser.add_argument("--since", type=_merge_sha, required=True)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    try:
        code, report = console_approved_action(args.since, log=args.log, repo_root=args.repo_root)
    except (ToolError, GitError) as error:
        print(f"verify-checks: {getattr(error, 'kind', 'git_error')}: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
