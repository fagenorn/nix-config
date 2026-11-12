"""`manager_check`: the verify checks that a stated goal starts a manager that briefs and survives a restart (#888).

`python -m agent_tools.console.manager_check start --project ID [--url URL] [--state-file PATH]
[--result-file PATH] [--token-file PATH] [--budget SECONDS]` is the gating check;
`python -m agent_tools.console.manager_check timing [--result-file PATH] [--deadline SECONDS]` is
the timing metric. `--url` is the console's base URL (default `http://127.0.0.1:27184`; `http` on a
loopback host, `127.0.0.1` or `localhost`, else exit 2). The default state file is
`<state_root()>/console/checks/manager-start.json`, the result file
`<state_root()>/console/checks/manager-start-result.json`, the token file
`<state_root()>/console/page-token`; `--budget` is 540 seconds and `--deadline` 600. Each prints one
stdout line of JSON with sorted keys; exit 0 met, 1 not met, 75 not yet, 2 a bad argument.

`start` states two marked goals for `--project` through `POST /api/goal` (the page's write guard:
`Origin` is the console's own origin, `X-Console-Token` the token file's text), so two managers
chosen from one capacity view land on the same profile, the shared-supervisor case. It writes each
sprint's id and the console's own `stated_at` to the state file (parents created 0700) and waits for
both managers' briefs (`brief/<sprint id>` open inbox items) every 10 seconds, up to the budget.
Whenever a state file exists `start` states no goal: it resumes those sprints. A fresh run deletes the
previous result file and writes the state file `{"unresolved": true}` before its first goal; if the console's
view stays unavailable for 60 seconds after the goals (or a goal's POST finds the console down) the run is 75
`not_running` with that file kept, and the next run reads the view and takes the sprints it finds by their goal
text, stating only a goal that has none. verify-pending runs a
`live` check once per approval and kills a run after 600 seconds, so one approved run is built to
finish in the expected case; a run that spends its budget keeps its state file and answers 75
`{"status": "waiting", "sprints": [{"sprint_id", "manager_state", "manager_until"}]}`, and the next
approved run resumes. `start` has no time bound of its own: a brief that has not arrived, a manager
still working and a sprint parked `waiting` on quota are all 75 however long ago `stated_at` was,
and the hold's expiry bounds the wait. Without a state file: a console that does not answer is 75
`not_running`, one whose view has no `managers` key is 75 `not_deployed`, no readable token is 75
`no_token`, and `managers` false is 1 `managers_unavailable`; nothing is posted in any of them.

Not met (exit 1, `{"status": "not_met", "reason": ..., "brief_seconds": [...]}`) only for a
functional failure: a sprint that is gone (`the sprint is gone`), a `failed` or `missing` manager
(its `manager_text`), a brief at a version other than 1, seen on any poll even before the other sprint has a brief
(`a brief reached another sprint's slot`),
a console that refuses a goal, a failed restart (`restart failed: <error>`), or a manager not
listed after the restart (`the manager is not running after the restart`). A slow brief is never
not met here.

Once both briefs are version 1, `start` restarts the console (`systemctl --user restart
agent-console`), waits 10 seconds and reads the session registry up to three times 5 seconds apart
until each sprint's manager (`manager.session_name`) is listed. The registry is read fresh from the
registry files and filtered by live process, never from the console's view, which replays sessions
from the log and drops a missing one only after two polls: a manager killed by the restart cannot
pass. The met output names the managers it found in `sessions`.

Whenever `start` finishes (the console is given up to 60 seconds to come back from the restart
first) it stops the test managers, then withdraws the test sprints; a 75 `waiting` finish does
neither. Each manager listed in a fresh registry read under its name (`manager.session_name`) is
stopped with `manager.stop_session`, which gives the stop the first eight characters of the
session id and runs it under the session's own profile; every one is tried, and a manager not
listed needs no stop. The stop comes first so the check leaves nothing running whatever the
console's own stop of a withdrawn sprint does (ADR-console-017), which then finds nothing listed. When any stop fails the outcome is kept in the state file, nothing is withdrawn and the
run is 75 `waiting` (`the test managers are not stopped yet: <the stop's one-line reason>`). A
withdrawal counts as done on 204 or 409 (already gone). When any withdrawal fails the outcome is
kept in the state file, nothing else is written and the run is 75 `waiting` (`the test sprints
are not withdrawn yet`); the next run retries the stops and the withdrawals and then finishes
with that outcome. A finish whose sprints are withdrawn writes the
result file `{"status", "brief_seconds": {sprint id: int | null}}`, where a sprint's seconds are its
brief's `waiting_since` minus the sprint's `stated_at`, both console timestamps, so they never
depend on when the check looked, and removes the state file.

`timing` only reads the result file (a new run deletes the previous one, so it never reports an earlier run): absent is 75 `no_result`; any `brief_seconds` null or above
`--deadline` is 1 `slow`; else 0 `met`, each with `brief_seconds`. It changes no file.

The default `restart`, `registry` and `stop` and the `clock` and `sleep` of `main` are seams for tests.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from agent_tools.console import manager, service, sessions
from agent_tools.project_contract import agent_platform

DEFAULT_URL = "http://127.0.0.1:27184"
DEFAULT_BUDGET = 540
DEFAULT_DEADLINE = 600
LOOPBACK = ("127.0.0.1", "localhost")
TIMEOUT = 5.0
NOT_YET = 75
POLL_SECONDS = 10
RETURN_SECONDS = 60
GOALS = ("[verify #888 a] check that a stated goal starts a manager; withdraw me",
         "[verify #888 b] check that a second manager on the same profile keeps its own sprint; "
         "withdraw me")
NOT_RUNNING_TEXT = "the manager is not running after the restart"
NOT_STOPPED_TEXT = "the test managers are not stopped yet"
NOT_WITHDRAWN_TEXT = "the test sprints are not withdrawn yet"


def _loopback_url(text: str) -> str:
    try:
        parts = urlsplit(text)
        parts.port  # noqa: B018  raises ValueError on a bad port
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a URL: {text}") from None
    if (parts.scheme != "http" or parts.hostname not in LOOPBACK or parts.path not in ("", "/") or parts.query or parts.fragment):
        raise argparse.ArgumentTypeError(
            "the URL must be http on 127.0.0.1 or localhost")
    return text


def _positive(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text}") from None
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _state_dir() -> Path:
    return agent_platform.state_root() / "console"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="manager_check", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="state two goals and check their managers")
    start.add_argument("--project", required=True, help="the project id to state the goals for")
    start.add_argument("--url", type=_loopback_url, default=DEFAULT_URL)
    start.add_argument("--state-file", type=Path, default=None)
    start.add_argument("--result-file", type=Path, default=None)
    start.add_argument("--token-file", type=Path, default=None)
    start.add_argument("--budget", type=_positive, default=DEFAULT_BUDGET,
                       help="seconds one run waits (default: %(default)s)")
    timing = commands.add_parser("timing", help="check the brief times `start` recorded")
    timing.add_argument("--result-file", type=Path, default=None)
    timing.add_argument("--deadline", type=_positive, default=DEFAULT_DEADLINE,
                        help="the slowest brief allowed, in seconds (default: %(default)s)")
    return parser


class Console:
    """The console's HTTP API at one loopback base URL."""

    def __init__(self, url: str, token: str = "") -> None:
        parts = urlsplit(url)
        self.host, self.port, self.netloc = parts.hostname, parts.port, parts.netloc
        self.token = token

    def _request(self, method: str, path: str, body: bytes | None = None,
                 headers: dict | None = None) -> tuple[int, bytes] | None:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=TIMEOUT)
        try:
            connection.request(method, path, body=body,
                               headers={"Host": self.netloc, **(headers or {})})
            response = connection.getresponse()
            return response.status, response.read()
        except (OSError, http.client.HTTPException):
            return None
        finally:
            connection.close()

    def state(self) -> dict | None:
        """The `/api/state` view, None when the console does not answer with a JSON object."""
        answer = self._request("GET", "/api/state")
        if answer is None or answer[0] != 200:
            return None
        try:
            document = json.loads(answer[1])
        except ValueError:
            return None
        return document if isinstance(document, dict) else None

    def post(self, path: str, document: dict) -> tuple[int | None, str]:
        """`(status, text)` of a page write; the status is None when the console is unreachable."""
        answer = self._request("POST", path, json.dumps(document).encode(), {
            "Content-Type": "application/json", "Origin": f"http://{self.netloc}",
            "X-Console-Token": self.token})
        if answer is None:
            return None, "the console did not answer"
        return answer[0], answer[1].decode("utf-8", "replace").strip()


def _write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(document, stream, sort_keys=True)
    os.replace(temporary, path)


def _project_sprints(view: dict, project: str) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for entry in view.get("entries") or []:
        if isinstance(entry, dict) and entry.get("project_id") == project:
            for row in entry.get("sprints") or []:
                if isinstance(row, dict) and isinstance(row.get("sprint_id"), str):
                    found[row["sprint_id"]] = row
    return found


def _newest_with_goal(view: dict, project: str, goal: str) -> dict | None:
    rows = [row for row in _project_sprints(view, project).values() if row.get("goal") == goal]
    return max(rows, key=lambda row: str(row.get("stated_at")), default=None)


def _seconds(sent: object, stated: object) -> int | None:
    try:
        return int((datetime.fromisoformat(sent) - datetime.fromisoformat(stated)).total_seconds())
    except (TypeError, ValueError):
        return None


def _print(document: dict) -> None:
    print(json.dumps(document, sort_keys=True))


def default_restart() -> None:
    subprocess.run(["systemctl", "--user", "restart", "agent-console"], check=True, timeout=60)


def default_registry() -> dict:
    return sessions.read_session_registry(service.default_session_dirs())


def _start(args, restart, registry, stop, clock, sleep) -> int:
    state_file = args.state_file or _state_dir() / "checks" / "manager-start.json"
    result_file = args.result_file or _state_dir() / "checks" / "manager-start-result.json"
    token_file = args.token_file or _state_dir() / "page-token"
    run_start = clock()
    console = Console(args.url)

    def read_token() -> bool:
        try:
            console.token = token_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            _print({"status": "no_token"})
            return False
        return True

    def withdraw(sprint_ids) -> bool:
        """Withdraw each sprint; true when every one is withdrawn or already gone."""
        done = True
        for sprint_id in sprint_ids:
            status, _ = console.post("/api/withdraw", {"project_id": project, "sprint_id": sprint_id})
            done = done and status in (204, 409)
        return done

    def await_console() -> dict | None:
        deadline = clock() + RETURN_SECONDS
        while True:
            view = console.state()
            if view is not None or clock() >= deadline:
                return view
            sleep(5)

    def checkpoint(**more) -> None:
        _write_json(state_file, {"project": project, "sprints": [
            {"sprint_id": i, "stated_at": stated[i]} for i in ids], **more})

    def close(code, reason, seconds, listed):
        """Stop the test managers, then withdraw the sprints, then finish.

        A manager that stays running or a sprint that stays open keeps the state file.
        """
        def keep(text):
            checkpoint(outcome={"code": code, "reason": reason, "seconds": seconds,
                                "listed": list(listed)})
            return pending(text)

        try:
            manager.stop_listed([manager.session_name(project, i) for i in ids], registry, stop)
        except Exception as error:
            return keep(f"{NOT_STOPPED_TEXT}: {error}" if str(error) else NOT_STOPPED_TEXT)
        if not withdraw(ids):
            return keep(NOT_WITHDRAWN_TEXT)
        return _finish(code, reason, ids, seconds, list(listed), result_file, state_file)

    def settle(code, reason, seconds, listed=(), restarted=False):
        if restarted:
            await_console()
        return close(code, reason, seconds, listed)

    def pending(text):
        _print({"status": "waiting", "reason": text, "sprints": [{"sprint_id": i} for i in ids]})
        return NOT_YET

    project = args.project
    ids: list[str] = []
    stated: dict[str, str] = {}
    unresolved = False
    if state_file.exists():
        try:
            saved = json.loads(state_file.read_text(encoding="utf-8"))
            project = saved["project"]
            stated = {row["sprint_id"]: row["stated_at"] for row in saved["sprints"]}
            ids = [row["sprint_id"] for row in saved["sprints"]]
            outcome = saved.get("outcome")
            unresolved = bool(saved.get("unresolved"))
            if outcome is not None:
                outcome = (outcome["code"], outcome["reason"], outcome["seconds"],
                           outcome["listed"])
        except (OSError, ValueError, KeyError, TypeError):
            _print({"status": "bad_state_file", "path": str(state_file)})
            return 1
        if not read_token():
            return NOT_YET
        if outcome is not None:
            return close(outcome[0], outcome[1], outcome[2], outcome[3])
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
            _write_json(state_file, {"project": project, "sprints": [], "unresolved": True})
        refused = None
        for goal in GOALS:
            if unresolved and _newest_with_goal(view, project, goal):
                continue
            status, text = console.post("/api/goal", {"project_id": project, "goal": goal})
            if status != 204:
                refused = (status, text)
                break
        view = await_console()
        if view is None or (refused is not None and refused[0] is None):
            _print({"status": "not_running"})
            return NOT_YET
        rows = [_newest_with_goal(view, project, goal) for goal in GOALS]
        ids = [row["sprint_id"] for row in rows if row]
        stated = {row["sprint_id"]: row.get("stated_at") for row in rows if row}
        if refused is not None or len(ids) != len(GOALS):
            reason = (f"the console refused a goal: {refused[0]} {refused[1]}" if refused
                      else "the sprint is gone")
            return settle(1, reason, {i: None for i in ids})
        checkpoint()

    def finish(code, reason, seconds, listed=()):
        return settle(code, reason, seconds, listed, restarted=True)

    latest: dict[str, dict] = {}
    while True:
        view = console.state()
        if view is not None:
            latest = _project_sprints(view, project)
            missing = [i for i in ids if i not in latest]
            if missing:
                return settle(1, "the sprint is gone", {i: None for i in ids})
            for sprint_id in ids:
                row = latest[sprint_id]
                if row.get("manager_state") in ("failed", "missing"):
                    return finish(1, row.get("manager_text"), {i: None for i in ids})
            items = {item.get("key"): item for item in (view.get("inbox") or {}).get("open") or []
                     if isinstance(item, dict)}
            briefs = {i: items.get("brief/" + i) for i in ids}
            seconds = {i: _seconds(briefs[i].get("waiting_since"), stated[i]) if briefs[i] else None
                       for i in ids}
            if any(briefs[i] and briefs[i].get("version") != 1 for i in ids):
                return finish(1, "a brief reached another sprint's slot", seconds)
            if all(briefs.values()):
                break
        if clock() - run_start >= args.budget:
            _print({"status": "waiting", "sprints": [
                {"sprint_id": i, "manager_state": latest.get(i, {}).get("manager_state"),
                 "manager_until": latest.get(i, {}).get("manager_until")} for i in ids]})
            return NOT_YET
        sleep(POLL_SECONDS)

    try:
        restart()
    except Exception as error:
        return finish(1, f"restart failed: {error}", seconds)
    sleep(POLL_SECONDS)
    names = [manager.session_name(project, i) for i in ids]
    listed = False
    for attempt in range(3):
        if attempt:
            sleep(5)
        running = {observation.name for observation in registry().values()}
        listed = all(name in running for name in names)
        if listed:
            break
    if not listed:
        return finish(1, NOT_RUNNING_TEXT, seconds)
    return finish(0, None, seconds, names)


def _finish(code, reason, ids, seconds, listed, result_file, state_file) -> int:
    status = "met" if code == 0 else "not_met"
    _write_json(result_file, {"status": status, "brief_seconds": seconds})
    state_file.unlink(missing_ok=True)
    output = {"status": status, "brief_seconds": [seconds[i] for i in ids]}
    if code == 0:
        output["sessions"] = listed
    else:
        output["reason"] = reason
    _print(output)
    return code


def _timing(args) -> int:
    result_file = args.result_file or _state_dir() / "checks" / "manager-start-result.json"
    try:
        seconds = json.loads(result_file.read_text(encoding="utf-8"))["brief_seconds"]
        values = list(seconds.values())
    except FileNotFoundError:
        _print({"status": "no_result"})
        return NOT_YET
    except (OSError, ValueError, KeyError, AttributeError):
        _print({"status": "bad_result", "path": str(result_file)})
        return 1
    late = not values or any(not isinstance(v, int) or isinstance(v, bool) or v > args.deadline
                             for v in values)
    _print({"status": "slow" if late else "met", "brief_seconds": values})
    return 1 if late else 0


def main(argv: list[str] | None = None, *,
         restart: Callable[[], None] = default_restart,
         registry: Callable[[], dict] = default_registry,
         stop: Callable[[str, str], None] = manager.stop_session,
         clock: Callable[[], float] = time.time,
         sleep: Callable[[float], None] = time.sleep) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "timing":
        return _timing(args)
    return _start(args, restart, registry, stop, clock, sleep)


if __name__ == "__main__":
    sys.exit(main())
