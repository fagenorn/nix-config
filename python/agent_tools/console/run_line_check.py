"""`run_line_check`: the verify script that a run line under a sprint waiting its turn to merge never reads quiet (#1212).

`python -m agent_tools.console.run_line_check --project ID --repo SLUG [--port N] [--pattern P]`
reads the land lock's queue on the forge and the delivery run lines on this host's console, and
reports whether every run line of a sprint waiting its turn to merge reads moving, none "quiet".

The rules are read in this order:

1. The queue is read exactly as `lock_wait_check` reads it: the holders (`holding` true) united with
   the live waiters, every one an open pull request. Fewer than two queued, or no long waiter among
   them, prints `{"queued": [...], "status": "no_queue"}` and exits 75; a forge error
   (`ForgeError`) prints `{"reason", "status": "forge_unreadable"}` and exits 75.
2. A console that does not answer (`OSError`, a non-JSON body, a response cut short:
   `http.client.HTTPException`) prints `{"reason", "status": "no_console"}` and exits 75.
3. The waiting sprints are the running sprints (`ended_at` null) of the project entry whose
   `project_id` is `--project` in `/api/state` (an entry or a `quiet_group`'s `projects`) whose
   `now_text == sprints.NOW_LOCK_TEXT`. None prints `{"queued", "status": "no_wait_shown"}`, exit 75.
4. The judged run lines are the delivery entries of that project entry, in
   `outside_sprints.sessions[].deliveries[]` and in each running sprint's
   `sessions[].deliveries[]`, that carry one issue common to all three of the union of the `issues` of
   the queued pull requests, the issues of one waiting sprint (`issues[].issue` united with
   `movement.issues`) and the run's own `issues[].issue`. None prints `{"queued", "status":
   "no_run"}` and exits 75.
5. Any judged run line with `quiet` exactly true is not met: `{"queued", "quiet": [sorted run ids],
   "status": "not_met"}`, exit 1.
6. Any other judged run line whose `quiet` is not exactly false (absent, null or not a boolean) is
   evidence not read: `{"queued", "runs": [sorted run ids], "status": "unreadable_run"}`, exit 75.
7. Otherwise met: `{"queued", "runs": [{"run_id", "moved_text"}] sorted by run id, "status":
   "met"}`, exit 0.

A usage error exits 2. `--pattern` defaults to `deliveries.configured_branch_pattern(os.getcwd())`;
`--port` defaults to `service.DEFAULT_PORT`. It reads only (one GraphQL and one REST call through
`read_pulls`, one REST listing of the waiters, one forge clock read, one loopback GET) and writes
nothing. The seams of `main` are `read_pulls`, `read_waiters`, `forge_now` and `read_state`.
"""

import argparse
import http.client
import os

from agent_tools.claims import forge_land_lock
from agent_tools.console import deliveries, lock_wait_check, manager_check, movement, service, sprints
from agent_tools.system.forge_api import ForgeError

NOT_YET = manager_check.NOT_YET


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run_line_check", description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True, help="the project id of the console entry")
    parser.add_argument("--repo", required=True, help="the repository slug, owner/name")
    parser.add_argument("--port", type=int, default=service.DEFAULT_PORT)
    parser.add_argument("--pattern", default=None, help="the branch pattern; default the checkout's")
    return parser


def _project_entries(state: dict, project: str) -> list[dict]:
    found: list[dict] = []

    def visit(entries) -> None:
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            if entry.get("type") == "quiet_group":
                visit(entry.get("projects"))
            elif entry.get("type") == "project" and entry.get("project_id") == project:
                found.append(entry)

    visit(state.get("entries") if isinstance(state, dict) else None)
    return found


def _session_runs(sessions) -> list[dict]:
    return [d for s in sessions if isinstance(s, dict) for d in s.get("deliveries") or []
            if isinstance(d, dict)] if isinstance(sessions, list) else []


def _run_issues(run: dict) -> set[int]:
    return {i["issue"] for i in run.get("issues") or [] if isinstance(i, dict)
            and isinstance(i.get("issue"), int)}


def main(argv=None, *, read_pulls=movement.read_pulls,
         read_waiters=lock_wait_check.default_read_waiters, forge_now=forge_land_lock.forge_now,
         read_state=lock_wait_check.default_read_state) -> int:
    args = build_parser().parse_args(argv)
    pattern = args.pattern if args.pattern is not None else deliveries.configured_branch_pattern(
        os.getcwd())
    try:
        pulls = {pull.number: pull for pull in read_pulls(args.repo, pattern)}
        registrations = read_waiters(args.repo)
        now = forge_now()
    except ForgeError as error:
        manager_check._print({"reason": str(error), "status": "forge_unreadable"})
        return NOT_YET
    holders = {number for number, pull in pulls.items() if pull.holding}
    waiters = lock_wait_check.live_waiters(registrations, set(pulls), now)
    queued = sorted(holders | set(waiters))
    if len(queued) < 2 or not any(waiters.values()):
        manager_check._print({"queued": queued, "status": "no_queue"})
        return NOT_YET
    try:
        state = read_state(args.port)
    except (OSError, ValueError, http.client.HTTPException) as error:
        manager_check._print({"reason": str(error), "status": "no_console"})
        return NOT_YET
    waiting = [s for s in lock_wait_check.running_sprints(state, args.project)
               if s.get("now_text") == sprints.NOW_LOCK_TEXT]
    if not waiting:
        manager_check._print({"queued": queued, "status": "no_wait_shown"})
        return NOT_YET
    queue_issues = set().union(*(pulls[n].issues for n in queued))
    waiting_issues = [lock_wait_check.sprint_issues(s) for s in waiting]
    judged: list[dict] = []
    for entry in _project_entries(state, args.project):
        outside = entry.get("outside_sprints")
        runs = _session_runs(outside.get("sessions") if isinstance(outside, dict) else None)
        for sprint in entry.get("sprints") or []:
            if isinstance(sprint, dict) and sprint.get("ended_at") is None:
                runs += _session_runs(sprint.get("sessions"))
        judged += [run for run in runs
                   if any(_run_issues(run) & queue_issues & issues for issues in waiting_issues)]
    if not judged:
        manager_check._print({"queued": queued, "status": "no_run"})
        return NOT_YET
    quiet = sorted(str(run.get("run_id")) for run in judged if run.get("quiet") is True)
    if quiet:
        manager_check._print({"queued": queued, "quiet": quiet, "status": "not_met"})
        return 1
    unreadable = sorted(str(run.get("run_id")) for run in judged if run.get("quiet") is not False)
    if unreadable:
        manager_check._print({"queued": queued, "runs": unreadable, "status": "unreadable_run"})
        return NOT_YET
    shown = sorted(({"run_id": run.get("run_id"), "moved_text": run.get("moved_text")}
                    for run in judged), key=lambda row: str(row["run_id"]))
    manager_check._print({"queued": queued, "runs": shown, "status": "met"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
