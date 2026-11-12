"""`message_check`: the verify checks that an approval on the page reaches the sprint's manager, and how fast (#889).

`python -m agent_tools.console.message_check start --project ID [--url URL] [--state-file PATH]
[--result-file PATH] [--token-file PATH] [--budget SECONDS]` is the gating check;
`python -m agent_tools.console.message_check timing [--result-file PATH] [--deadline SECONDS]` is
the timing metric. `--url` is the console's base URL (default `http://127.0.0.1:27184`; `http` on a
loopback host, `127.0.0.1` or `localhost`, else exit 2). The default state file is
`<state_root()>/console/checks/owner-message.json`, the result file
`<state_root()>/console/checks/owner-message-result.json`, the token file
`<state_root()>/console/page-token`; `--budget` is 540 seconds and `--deadline` 300. Each prints one
stdout line of JSON with sorted keys; exit 0 met, 1 not met, 75 not yet, 2 a bad argument.

`start` states `GOAL` for `--project` through `POST /api/goal` (the page's write guard: `Origin` is
the console's own origin, `X-Console-Token` the token file's text). The goal tells the manager to
brief one slice, to answer the approval with `sprint reply` once it has read it, and to cut no
issues and deliver nothing. Without a state file: a console that does not answer is 75
`not_running`, a view without `managers` is 75 `not_deployed`, `managers` false is 1
`managers_unavailable`, no readable token is 75 `no_token`; none of them posts anything. Otherwise
it deletes the previous result file, writes the state file `{"project", "unresolved": true}`, states
the goal, and writes `{"project", "sprint_id", "stated_at", "approved_versions": []}` (parents
created 0700) for the sprint it finds by its goal. An `unresolved` state file reuses the sprint
found by its goal and states no second goal; any other state file is a resumed run that states no
goal and continues from what it records.

It polls the view every 10 seconds (`POLL_SECONDS`), every 2 seconds (`READ_POLL_SECONDS`) once an
approval message exists, up to `--budget`. The approval is read from the view only: the sprint's
earliest message of kind `approved`; the HTTP status of `/api/approve` never records one. With no
approval message and an open `brief/<sprint id>` item at a version not in `approved_versions`,
`POST /api/approve` is sent `{"project_id", "sprint_id", "version"}`: 204 or 409 continue the
polling (409 means the version was replaced, already decided or asked to change, and the next poll
reads which) and only then is the version added to that list in the state file, any other status
is not met (`the console refused the approval: <status> <text>`), no answer continues without
recording the version (an attempt the console never confirmed is not a refusal: the next poll or
run sends it again). An open brief at a version already in `approved_versions` with no approval
message is not met (`the console refused the approval of version <v>`): the console still shows it
waiting after it answered. So a replaced version is followed by an approval of the new one, and no
version the console answered is approved twice, across runs too. With the approval message, `state` `read` is met with `read_seconds` the
console's `read_at` minus its `at`; `reach_text` not null is not met (`manager not reachable`); otherwise the
polling continues. An unread approval is never a failure however long ago it was sent: `start` has
no time bound of its own, so a budget spent while it is unread is 75 `{"status": "waiting",
"phase": "read", "sprint_id"}` and the hold's expiry bounds the wait. A slow read is never not met
here; speed is `timing`'s alone. A budget spent before the approval message is the same with phase
`brief`, and the state file is kept for the next run.

Not met (exit 1) only for a functional failure: the sprint is gone (`the sprint is gone`), a
`failed` or `missing` manager (its `manager_text`), a refused approval, or an unreachable manager.
A sprint entry with no `messages` member is 75 `not_deployed`, after the finish below.

The finish (any met or not met outcome, and the `not_deployed` one) runs in this order. First it
stops the test manager: the registry is read fresh and each listed session named
`manager.session_name(project, sprint_id)` is stopped with `claude-account run stop <id>` under
its own profile (`manager.stop_session`, which gives the stop the first eight characters of the
session id, the only id it accepts); a manager not listed needs no stop. Each stopped session's id
and profile is recorded in the state file's `stopped`, because the fresh registry stops listing a
session once it is stopped. The stop comes before the withdrawal so the check leaves nothing
running whatever the console does: a withdrawal appends `goal.withdrawn`, drops the secret and then
stops the manager's session itself (ADR-console-018), which finds nothing listed after this stop.
A failed stop keeps the outcome (and any stop that succeeded) in the state file and the run is 75
`{"status": "waiting", "reason": "the test manager is not stopped yet: <the stop's one-line
reason>", "sprint_id"}`; the next run retries from the stop. Second it removes each recorded
session with `claude-account run rm <short id>` under its own profile (`manager.remove_session`).
A failed removal keeps the outcome and `stopped` and the run is 75 `waiting` (`the test manager's
session is not removed yet: <reason>`); the next run removes the recorded sessions, even ones the
registry no longer lists, does not remove one twice, then withdraws and finishes with the kept
outcome. Before each stop and each removal the outcome and `stopped` are written to the state
file, and a call that could end past `max(manager.FINISH_LIMIT, budget + manager.FINISH_SECONDS)`
seconds of the run (590 with the default budget) is left to the next run (75 with
`manager.OUT_OF_TIME_TEXT` as the reason), because verify-pending kills a run after 600 seconds.
Third it withdraws the sprint (204 or 409 is done); otherwise the outcome stays in the state file
and the run is 75 `waiting` (`the test sprint is not withdrawn yet`) and the next run retries from
the stop. Fourth it writes the result file `{"status": "met" | "not_met", "reason"?,
"read_seconds": int | null, "cleared": {"project", "names", "profiles"}}` (`cleared` is the
project, the test sprint's session name and the stopped sessions' profiles), removes the state file
and prints the outcome: met `{"read_seconds", "status"}`, not met `{"read_seconds", "reason",
"status"}`. The `not_deployed` finish writes no result file.

`timing` only reads the result file (a new run deletes the previous one, so it never reports an
earlier run): an absent or unreadable file is 75 `no_result`; `read_seconds` null or above
`--deadline` is 1 `{"read_seconds", "reason": "slow", "status": "not_met"}`; else 0 `{"read_seconds",
"status": "met"}`. It changes no file.

The registry, stop, remove, clock and sleep of `main` are seams for tests.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

from agent_tools.console import manager
from agent_tools.console.manager_check import (
    DEFAULT_URL,
    NOT_YET,
    Console,
    _loopback_url,
    _newest_with_goal,
    _positive,
    _print,
    _project_sprints,
    _seconds,
    _state_dir,
    _write_json,
    default_registry,
)

DEFAULT_BUDGET = 540
DEFAULT_DEADLINE = 300
POLL_SECONDS = 10
READ_POLL_SECONDS = 2
RETURN_SECONDS = 60
GOAL = ("[verify #889] check that an approval reaches the manager: brief one slice, and once you "
        "have read the approval answer it with sprint reply and end your turn; cut no issues and "
        "deliver nothing; withdraw me")
NOT_STOPPED_TEXT = "the test manager is not stopped yet"
NOT_REMOVED_TEXT = "the test manager's session is not removed yet"
NOT_WITHDRAWN_TEXT = "the test sprint is not withdrawn yet"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="message_check", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="state a goal, approve its brief, wait for the read")
    start.add_argument("--project", required=True, help="the project id to state the goal for")
    start.add_argument("--url", type=_loopback_url, default=DEFAULT_URL)
    start.add_argument("--state-file", type=Path, default=None)
    start.add_argument("--result-file", type=Path, default=None)
    start.add_argument("--token-file", type=Path, default=None)
    start.add_argument("--budget", type=_positive, default=DEFAULT_BUDGET,
                       help="seconds one run waits (default: %(default)s)")
    timing = commands.add_parser("timing", help="check the read time `start` recorded")
    timing.add_argument("--result-file", type=Path, default=None)
    timing.add_argument("--deadline", type=_positive, default=DEFAULT_DEADLINE,
                        help="the slowest read allowed, in seconds (default: %(default)s)")
    return parser


def _result_file(args) -> Path:
    return args.result_file or _state_dir() / "checks" / "owner-message-result.json"


def _start(args, registry, stop, remove, clock, sleep) -> int:
    state_file = args.state_file or _state_dir() / "checks" / "owner-message.json"
    result_file = _result_file(args)
    token_file = args.token_file or _state_dir() / "page-token"
    run_start = clock()
    console = Console(args.url)
    project = args.project
    state: dict = {}
    unresolved = False

    def read_token() -> bool:
        try:
            console.token = token_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            _print({"status": "no_token"})
            return False
        return True

    def checkpoint(**more) -> None:
        _write_json(state_file, {**state, **more})

    def await_console() -> dict | None:
        deadline = clock() + RETURN_SECONDS
        while True:
            view = console.state()
            if view is not None or clock() >= deadline:
                return view
            sleep(5)

    def settle(code: int, reason: str | None, seconds: int | None) -> int:
        """Stop the test manager, remove its session, withdraw the sprint, then record the outcome."""
        sprint_id = state.get("sprint_id")
        stopped = state.setdefault("stopped", [])
        outcome = {"code": code, "reason": reason, "seconds": seconds}
        guard = manager.finish_guard(clock, run_start, args.budget,
                                     lambda: checkpoint(outcome=outcome))
        if sprint_id is not None:
            try:
                manager.stop_listed([manager.session_name(project, sprint_id)], registry, stop,
                                    stopped, guard)
            except Exception as error:
                checkpoint(outcome=outcome)
                waiting = f"{NOT_STOPPED_TEXT}: {error}" if str(error) else NOT_STOPPED_TEXT
                _print({"status": "waiting", "reason": waiting, "sprint_id": sprint_id})
                return NOT_YET
            try:
                manager.remove_stopped(stopped, remove, guard)
            except Exception as error:
                checkpoint(outcome=outcome)
                waiting = f"{NOT_REMOVED_TEXT}: {error}" if str(error) else NOT_REMOVED_TEXT
                _print({"status": "waiting", "reason": waiting, "sprint_id": sprint_id})
                return NOT_YET
            checkpoint(outcome=outcome)
            status, _ = console.post("/api/withdraw",
                                     {"project_id": project, "sprint_id": sprint_id})
            if status not in (204, 409):
                checkpoint(outcome=outcome)
                _print({"status": "waiting", "reason": NOT_WITHDRAWN_TEXT,
                        "sprint_id": sprint_id})
                return NOT_YET
        state_file.unlink(missing_ok=True)
        if code == NOT_YET:
            _print({"status": "not_deployed"})
            return NOT_YET
        cleared = {"project": project,
                   "names": [manager.session_name(project, sprint_id)] if sprint_id else [],
                   "profiles": sorted({entry["profile"] for entry in stopped})}
        if code == 0:
            document = {"status": "met", "read_seconds": seconds}
        else:
            document = {"status": "not_met", "reason": reason, "read_seconds": seconds}
        _write_json(result_file, {**document, "cleared": cleared})
        _print(document)
        return code

    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            project = state["project"]
            unresolved = bool(state.get("unresolved"))
            state.setdefault("approved_versions", [])
            outcome = state.get("outcome")
            if outcome is not None:
                outcome = (outcome["code"], outcome["reason"], outcome["seconds"])
        except (OSError, ValueError, KeyError, TypeError):
            _print({"status": "bad_state_file", "path": str(state_file)})
            return 1
        if not read_token():
            return NOT_YET
        if outcome is not None:
            return settle(*outcome)
    if not state_file.exists() or unresolved:
        view = console.state()
        if view is None:
            _print({"status": "not_running"})
            return NOT_YET
        if "managers" not in view:
            _print({"status": "not_deployed"})
            return NOT_YET
        if not view["managers"]:
            _print({"status": "managers_unavailable"})
            return 1
        if not read_token():
            return NOT_YET
        if not unresolved:
            result_file.unlink(missing_ok=True)
            state = {"project": project, "unresolved": True, "approved_versions": []}
            checkpoint()
        stated = None
        if unresolved:
            stated = _newest_with_goal(view, project, GOAL)
        if stated is None:
            status, _ = console.post("/api/goal", {"project_id": project, "goal": GOAL})
            view = await_console()
            if view is None or status is None:
                _print({"status": "not_running"})
                return NOT_YET
            stated = _newest_with_goal(view, project, GOAL)
        if stated is None:
            return settle(1, "the sprint is gone", None)
        state = {"project": project, "sprint_id": stated["sprint_id"],
                 "stated_at": stated.get("stated_at"),
                 "approved_versions": list(state["approved_versions"])}
        checkpoint()

    sprint_id = state["sprint_id"]
    approved: list[int] = state["approved_versions"]
    phase = "brief"
    while True:
        if clock() - run_start >= args.budget:
            _print({"status": "waiting", "phase": phase, "sprint_id": sprint_id})
            return NOT_YET
        pause = POLL_SECONDS
        view = console.state()
        if view is not None:
            row = _project_sprints(view, project).get(sprint_id)
            if row is None:
                return settle(1, "the sprint is gone", None)
            if row.get("manager_state") in ("failed", "missing"):
                return settle(1, row.get("manager_text"), None)
            if "messages" not in row:
                return settle(NOT_YET, None, None)
            approvals = [m for m in row["messages"]
                         if isinstance(m, dict) and m.get("kind") == "approved"]
            if approvals:
                phase, pause = "read", READ_POLL_SECONDS
                message = approvals[0]
                if message.get("state") == "read":
                    seconds = _seconds(message.get("read_at"), message.get("at"))
                    if seconds is None:
                        return settle(1, "the read time is unreadable", None)
                    return settle(0, None, seconds)
                if row.get("reach_text") is not None:
                    return settle(1, row["reach_text"], None)
            else:
                items = {item.get("key"): item
                         for item in (view.get("inbox") or {}).get("open") or []
                         if isinstance(item, dict)}
                item = items.get("brief/" + sprint_id)
                if item is not None:
                    version = item.get("version")
                    if version in approved:
                        return settle(1, f"the console refused the approval of version {version}",
                                      None)
                    status, text = console.post("/api/approve", {
                        "project_id": project, "sprint_id": sprint_id, "version": version})
                    if status not in (None, 204, 409):
                        return settle(1, f"the console refused the approval: {status} {text}",
                                      None)
                    if status is not None:
                        approved.append(version)
                        checkpoint(approved_versions=approved)
        sleep(pause)


def _timing(args) -> int:
    try:
        seconds = json.loads(_result_file(args).read_text(encoding="utf-8"))["read_seconds"]
    except (OSError, ValueError, KeyError, TypeError):
        _print({"status": "no_result"})
        return NOT_YET
    if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds > args.deadline:
        _print({"read_seconds": seconds, "reason": "slow", "status": "not_met"})
        return 1
    _print({"read_seconds": seconds, "status": "met"})
    return 0


def main(argv: list[str] | None = None, *,
         registry: Callable[[], dict] = default_registry,
         stop: Callable[[str, str], None] = manager.stop_session,
         remove: Callable[[str, str], None] = manager.remove_session,
         clock: Callable[[], float] = time.time,
         sleep: Callable[[float], None] = time.sleep) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "timing":
        return _timing(args)
    return _start(args, registry, stop, remove, clock, sleep)


if __name__ == "__main__":
    sys.exit(main())
