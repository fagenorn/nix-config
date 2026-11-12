"""`revive_check`: the verify checks that a gone manager is brought back, and how fast (#893, #949).

`python -m agent_tools.console.revive_check start --project ID [--url URL] [--state-file PATH]
[--result-file PATH] [--token-file PATH] [--budget SECONDS]` is the gating check;
`python -m agent_tools.console.revive_check timing [--result-file PATH] [--deadline SECONDS]` is
the timing metric. `--url` is the console's base URL (default `http://127.0.0.1:27184`; `http` on a
loopback host, `127.0.0.1` or `localhost`, else exit 2). The default state file is
`<state_root()>/console/checks/manager-revive.json`, the result file
`<state_root()>/console/checks/manager-revive-result.json`, the token file
`<state_root()>/console/page-token`; `--budget` is 540 seconds and `--deadline` 180. Each prints
one stdout line of JSON with sorted keys; exit 0 met, 1 not met, 75 not yet, 2 a bad argument.

`start` states `GOAL` for `--project` through `POST /api/goal` (the page's write guard: `Origin`
is the console's own origin, `X-Console-Token` the token file's text). The goal tells the manager
to brief one slice, to send one report once the brief is approved, to cut no issues and to deliver
nothing. Without a state file: a console that does not answer is 75 `not_running`, a view without
`managers` is 75 `not_deployed`, `managers` false is 1 `managers_unavailable`, no readable token is
75 `no_token`; none of them posts anything. Otherwise it deletes the previous result file (so
`timing` never reports an earlier run), writes the state file `{"project", "unresolved": true}`,
states the goal and records the sprint it finds by its goal. An `unresolved` state file reuses the
sprint found by its goal and states no second goal; any other state file is a resumed run that
states no goal and continues from its phase.

A state file with a `sprint_id` and no `after_removal` was written by the previous check (#893):
its sprint is released (the test manager stopped, the sprint withdrawn; a failure is 75 `waiting`
with the file kept, so the next run retries) and the run starts afresh, deleting that file and the
result file, so a result of that check never stands for this one.

The state file is `{"project", "sprint_id", "phase", "approved_versions", "first_session",
"first_profile", "stopped_at", "back_seconds", "removed_at", "after_removal", "messaged_at"}`.
Each phase is resumable by the next run, polls the view every 5 seconds (`POLL_SECONDS`) and ends
75 `{"phase", "sprint_id", "status": "waiting"}` with the state file kept when `--budget` is
spent:

- `brief`: an open `brief/<sprint id>` item at a version not in `approved_versions` gets
  `POST /api/approve` (204 or 409 record the version, any other answer or none is tried again on
  the next poll) and the phase becomes `on_track`.
- `on_track`: wait for the sprint entry's `state` to be `on_track`, or `quiet` with a `status`
  that is not null.
- `stop`: the registry is read fresh and the listed session named
  `manager.session_name(project, sprint id)` is `first_session`; it is stopped with
  `stop(session_id, profile)` and `stopped_at` is `clock()`. A failed stop, or no such session,
  is tried again on the next poll. The stop waits for a run with `STOP_WINDOW` (190) seconds of
  budget left (`DEFAULT_DEADLINE` plus two polls), so the return is polled within the run that
  stopped the manager and `back_seconds` is not the gap to the next scheduled run; a run short of
  it ends 75 in phase `stop` and the next run stops the manager at its start. A `--budget` below
  `STOP_WINDOW` stops at once, as no run could ever have the window.
- `back`: wait until the registry lists that name with `first_session`; `back_seconds` is
  `int(clock() - stopped_at)`.
- `remove`: stop the listed session, then `remove(first_session, first_profile)` (claude-account
  run rm); `removed_at` is `clock()`. A failure is tried again on the next poll.
- `relisted`: wait until the registry lists the name, with `first_session` or with another
  session id; `after_removal` is `"same"` or `"new"` accordingly.
- `message`: `POST /api/message` with `MESSAGE` (204 records `messaged_at`; no answer is tried
  again on the next poll; any other status is not met `the console refused the message: <status>
  <text>`). A resumed run never posts a second message in phase `read`.
- `read`: wait until the sprint row's newest message of kind `text` carrying `MESSAGE` is in state
  `read`; a non-null `reach_text` is not met with that text.

The deadlines are wall-clock times in the state file, so they hold across resumed runs, and they
are checked on every poll, the first of a resumed run included, before any wait: in `back`,
`clock() - stopped_at` above `RETURN_LIMIT` (600) without the return is not met `the manager did
not come back within 600 s of the stop`; in `relisted`, `clock() - removed_at` above
`RELIST_LIMIT` (900) is not met `no manager under the sprint's name within 900 s of the removal`;
in `read`, `clock() - messaged_at` above `READ_LIMIT` (600) is not met `the message was not read
within 600 s`.

Met (exit 0) is `{"after_removal": "same" | "new", "back_seconds": n, "status": "met"}` once the
message is read, whatever `back_seconds` is: speed is `timing`'s alone; the removed session coming
back is no failure. Not met (exit 1) only for a functional failure: the sprint is gone (`the
sprint is gone`), a sprint whose `manager_state` is `stalled` or `unavailable` (its
`manager_text`), the three deadlines above, a refused message or a `reach_text` while waiting for
the read.

The finish (any met or not met outcome) runs in this order. First it stops the test manager:
`manager.stop_listed` on the manager's name, the registry read fresh (a stop is given the first
eight characters of the session id, the only id it accepts). A failed stop keeps the outcome in
the state file and the run is 75 `{"status": "waiting", "reason": "the test manager is not
stopped yet: <the stop's one-line reason>", "sprint_id"}`; the next run retries from the stop.
Second it withdraws the sprint (`POST /api/withdraw`, 204 or 409 is done); otherwise the outcome
stays in the state file and the run is 75 `waiting` (`the test sprint is not withdrawn yet`).
Third it writes the result file `{"back_seconds": int | null, "status": "met" | "not_met",
"reason"?}`, removes the state file and prints the outcome (met with `"after_removal"`).

`timing` only reads the result file: absent or unreadable is 75 `{"status": "no_result"}`;
`back_seconds` null or above `--deadline` is 1 `{"back_seconds", "reason": "slow", "status":
"not_met"}`; else 0 `{"back_seconds", "status": "met"}`. It changes no file.

The default `remove` is `manager.remove_session`, which runs `claude-account run rm <first eight
characters of the id>` under the session's profile within 60 seconds. The `registry`, `stop`,
`remove`, `clock` and `sleep` of `main` are seams for tests.
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
    _state_dir,
    _write_json,
    default_registry,
)
from agent_tools.console.sessions import DEFAULT_PROFILE

DEFAULT_BUDGET = 540
DEFAULT_DEADLINE = 180
POLL_SECONDS = 5
RETURN_SECONDS = 60
STOP_WINDOW = DEFAULT_DEADLINE + 2 * POLL_SECONDS
RETURN_LIMIT = 600
RELIST_LIMIT = 900
READ_LIMIT = 600
GOAL = ("[verify #893] check that a gone manager is brought back: brief one slice; once "
        "approved, send one report with phase running, no issues and next set to wait for the "
        "owner, then end your turn; cut no issues and deliver nothing; withdraw me")
NOT_STOPPED_TEXT = "the test manager is not stopped yet"
NOT_WITHDRAWN_TEXT = "the test sprint is not withdrawn yet"
NO_RETURN_TEXT = f"the manager did not come back within {RETURN_LIMIT} s of the stop"
MESSAGE = "[verify #949] the console checks that you read this; no action needed, end your turn"
NO_RELIST_TEXT = f"no manager under the sprint's name within {RELIST_LIMIT} s of the removal"
UNREAD_TEXT = f"the message was not read within {READ_LIMIT} s"
GONE_TEXT = "the sprint is gone"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="revive_check", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="state a goal, stop its manager, see it replaced")
    start.add_argument("--project", required=True, help="the project id to state the goal for")
    start.add_argument("--url", type=_loopback_url, default=DEFAULT_URL)
    start.add_argument("--state-file", type=Path, default=None)
    start.add_argument("--result-file", type=Path, default=None)
    start.add_argument("--token-file", type=Path, default=None)
    start.add_argument("--budget", type=_positive, default=DEFAULT_BUDGET,
                       help="seconds one run waits (default: %(default)s)")
    timing = commands.add_parser("timing", help="check the return time `start` recorded")
    timing.add_argument("--result-file", type=Path, default=None)
    timing.add_argument("--deadline", type=_positive, default=DEFAULT_DEADLINE,
                        help="the slowest return allowed, in seconds (default: %(default)s)")
    return parser


def _result_file(args) -> Path:
    return args.result_file or _state_dir() / "checks" / "manager-revive-result.json"


def _start(args, registry, stop, remove, clock, sleep) -> int:
    state_file = args.state_file or _state_dir() / "checks" / "manager-revive.json"
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
        state.update(more)
        _write_json(state_file, state)

    def await_console() -> dict | None:
        deadline = clock() + RETURN_SECONDS
        while True:
            view = console.state()
            if view is not None or clock() >= deadline:
                return view
            sleep(5)

    def name() -> str:
        return manager.session_name(project, state["sprint_id"])

    def release() -> int | None:
        """Stop the test manager and withdraw the sprint; `NOT_YET` (printed) when either fails."""
        sprint_id = state["sprint_id"]
        try:
            manager.stop_listed([name()], registry, stop)
        except Exception as error:
            waiting = f"{NOT_STOPPED_TEXT}: {error}" if str(error) else NOT_STOPPED_TEXT
            _print({"status": "waiting", "reason": waiting, "sprint_id": sprint_id})
            return NOT_YET
        status, _ = console.post("/api/withdraw",
                                 {"project_id": project, "sprint_id": sprint_id})
        if status not in (204, 409):
            _print({"status": "waiting", "reason": NOT_WITHDRAWN_TEXT, "sprint_id": sprint_id})
            return NOT_YET
        return None

    def settle(code: int, reason: str | None) -> int:
        """Stop the test manager, withdraw the sprint, then record and print the outcome."""
        seconds = state.get("back_seconds")
        if state.get("sprint_id") is not None and release() is not None:
            checkpoint(outcome={"code": code, "reason": reason})
            return NOT_YET
        state_file.unlink(missing_ok=True)
        if code == 0:
            document = {"back_seconds": seconds, "status": "met"}
            _write_json(result_file, document)
            _print({**document, "after_removal": state["after_removal"]})
        else:
            document = {"back_seconds": seconds, "reason": reason, "status": "not_met"}
            _write_json(result_file, document)
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
                outcome = (outcome["code"], outcome["reason"])
        except (OSError, ValueError, KeyError, TypeError):
            _print({"status": "bad_state_file", "path": str(state_file)})
            return 1
        if not read_token():
            return NOT_YET
        if "sprint_id" in state and "after_removal" not in state:
            if release() is not None:
                return NOT_YET
            state_file.unlink(missing_ok=True)
            result_file.unlink(missing_ok=True)
            state, unresolved = {}, False
        elif outcome is not None:
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
            state = {"project": project, "unresolved": True}
            checkpoint()
        stated = _newest_with_goal(view, project, GOAL) if unresolved else None
        if stated is None:
            status, _ = console.post("/api/goal", {"project_id": project, "goal": GOAL})
            view = await_console()
            if view is None or status is None:
                _print({"status": "not_running"})
                return NOT_YET
            stated = _newest_with_goal(view, project, GOAL)
        if stated is None:
            return settle(1, GONE_TEXT)
        state = {"project": project, "sprint_id": stated["sprint_id"], "phase": "brief",
                 "approved_versions": [], "first_session": None, "first_profile": None,
                 "stopped_at": None, "back_seconds": None, "removed_at": None,
                 "after_removal": None, "messaged_at": None}
        checkpoint()

    sprint_id = state["sprint_id"]
    while True:
        advanced = False
        phase = state["phase"]
        view = console.state()
        row = None
        if view is not None:
            row = _project_sprints(view, project).get(sprint_id)
            if row is None:
                return settle(1, GONE_TEXT)
            if row.get("manager_state") in ("stalled", "unavailable"):
                return settle(1, row.get("manager_text"))
        if phase in ("brief", "on_track"):
            if row is not None:
                items = {item.get("key"): item
                         for item in (view.get("inbox") or {}).get("open") or []
                         if isinstance(item, dict)}
                item = items.get("brief/" + sprint_id)
                version = None if item is None else item.get("version")
                if item is not None and version not in state["approved_versions"]:
                    status, _ = console.post("/api/approve", {
                        "project_id": project, "sprint_id": sprint_id, "version": version})
                    if status in (204, 409):
                        checkpoint(approved_versions=[*state["approved_versions"], version],
                                   phase="on_track")
                        advanced = True
                elif phase == "on_track" and (row.get("state") == "on_track" or (
                        row.get("state") == "quiet" and row.get("status") is not None)):
                    checkpoint(phase="stop")
                    advanced = True
        elif phase == "stop":
            room = args.budget < STOP_WINDOW or args.budget - (clock() - run_start) >= STOP_WINDOW
            found = [o for o in registry().values() if o.name == name()] if room else []
            if found:
                profile = found[0].profile or DEFAULT_PROFILE
                try:
                    stop(found[0].session_id, profile)
                except manager.StopFailed:
                    pass
                else:
                    checkpoint(phase="back", first_session=found[0].session_id,
                               first_profile=profile, stopped_at=clock())
                    advanced = True
        elif phase == "back":
            returned = any(o.name == name() and o.session_id == state["first_session"]
                           for o in registry().values())
            now = clock()
            if now - state["stopped_at"] > RETURN_LIMIT:
                return settle(1, NO_RETURN_TEXT)
            if returned:
                checkpoint(phase="remove", back_seconds=int(now - state["stopped_at"]))
                advanced = True
        elif phase == "remove":
            try:
                manager.stop_listed([name()], registry, stop)
                remove(state["first_session"], state["first_profile"])
            except manager.StopFailed:
                pass
            else:
                checkpoint(phase="relisted", removed_at=clock())
                advanced = True
        elif phase == "relisted":
            ids = {o.session_id for o in registry().values() if o.name == name()}
            if clock() - state["removed_at"] > RELIST_LIMIT:
                return settle(1, NO_RELIST_TEXT)
            if ids:
                checkpoint(after_removal="same" if state["first_session"] in ids else "new",
                           phase="message")
                advanced = True
        elif phase == "message":
            if row is not None:
                status, text = console.post("/api/message", {
                    "project_id": project, "sprint_id": sprint_id, "text": MESSAGE})
                if status == 204:
                    checkpoint(messaged_at=clock(), phase="read")
                    advanced = True
                elif status is not None:
                    return settle(1, f"the console refused the message: {status} {text}".strip())
        else:
            if clock() - state["messaged_at"] > READ_LIMIT:
                return settle(1, UNREAD_TEXT)
            if row is not None:
                sent = [m for m in row.get("messages") or []
                        if isinstance(m, dict) and m.get("kind") == "text"
                        and m.get("text") == MESSAGE]
                if sent and sent[-1].get("state") == "read":
                    return settle(0, None)
                if row.get("reach_text") is not None:
                    return settle(1, row["reach_text"])
        if clock() - run_start >= args.budget:
            _print({"phase": state["phase"], "sprint_id": sprint_id, "status": "waiting"})
            return NOT_YET
        if not advanced:
            sleep(POLL_SECONDS)


def _timing(args) -> int:
    try:
        seconds = json.loads(_result_file(args).read_text(encoding="utf-8"))["back_seconds"]
    except (OSError, ValueError, KeyError, TypeError):
        _print({"status": "no_result"})
        return NOT_YET
    if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds > args.deadline:
        _print({"back_seconds": seconds, "reason": "slow", "status": "not_met"})
        return 1
    _print({"back_seconds": seconds, "status": "met"})
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
