"""`lock_wait_check`: the verify script that a sprint queued for the land lock shows its wait (#1184).

`python -m agent_tools.console.lock_wait_check --project ID --repo SLUG [--port N] [--pattern P]`
reads the land lock's queue on the forge and the running sprints on this host's console, and
reports whether every sprint of the queue reads moving, none "quiet" or with the ball on nobody.

The queue counts only confirmed open pull requests, every one of them among those `read_pulls`
returned: the holders (read with `holding` true), united with the long waiters, the pull requests of
the waiter registrations (`refs/agent-locks/land-wait/<branch>/<since>-<pr>-<beat>`, forge_land_lock
D12) that are live (`-QUEUE_SKEW <= forge_now() - beat <= QUEUE_LIVE`), have waited the quiet window
(`forge_now() - since >= QUIET_AFTER_MS // 1000`: before that a waiting sprint would not read quiet
even at the base, so its reading proves nothing), and whose `<pr>` is one of the read open pull
requests. A registration whose pull request is not among them (closed, merged, or not read) is
unresolved and counts nothing (D12 skips a closed one too). Met or not met is judged only with two
or more queued and at least one long waiter among them; otherwise it prints
`{"queued": [...], "status": "no_queue"}` and exits 75.

The running sprints are those (`ended_at` null) of the project entry whose `project_id` is
`--project` in `/api/state` (an entry or a `quiet_group`'s `projects`).

The waiters' sprints are the running sprints whose `issues[].issue` meets the union of `issues` of
the long waiters' pull requests (the holders' issues do not count here). The check judges only a
wait it has observed on this console: when no long waiter has a running sprint here (its run is on
another host, since `poll_deliveries` scans only this host's sessions, or its issues match no
running sprint), it prints `{"queued", "status": "no_sprint"}` and exits 75, even when a holder's
sprint is here and moving.

The judged sprints are the waiters' sprints united with the running sprints whose issues meet the
holders' issues. Not met (exit 1, `{"queued", "status": "not_met", "stuck": [sprint ids]}`) when any
judged sprint has `state == "quiet"` or `ball == "nobody"`.

Met (exit 0, `{"queued", "sprints": [{"sprint_id", "state", "now_text"}], "status": "met"}`) only
when no judged sprint reads quiet and at least one waiter's sprint has `now_text ==
sprints.NOW_LOCK_TEXT`: the wait itself is shown. When every waiter's sprint reads moving for
another reason (another lane building, an owner question), the reading proves nothing about the
lock wait: it prints `{"queued", "sprints", "status": "no_wait_shown"}` and exits 75.

The rules are read in this order: `no_queue`, `no_sprint`, `not_met`, `no_wait_shown`, `met`.

A forge error (`ForgeError`) prints `{"reason", "status": "forge_unreadable"}` and a console that
does not answer (`OSError`, a non-JSON body) `{"reason", "status": "no_console"}`, both exit 75; a
usage error exits 2.

`--pattern` defaults to `deliveries.configured_branch_pattern(os.getcwd())`; `--port` defaults to
`service.DEFAULT_PORT`. It reads only (one GraphQL and one REST call through `read_pulls`, one REST
listing of the waiters, one forge clock read, one loopback GET) and writes nothing. The seams of
`main` are `read_pulls`, `read_waiters`, `forge_now` and `read_state`.
"""

import argparse
import json
import os
import urllib.request

from agent_tools.claims import forge_land_lock
from agent_tools.claims import forge_markers as fm
from agent_tools.console import deliveries, manager_check, movement, service, sprints
from agent_tools.system.forge_api import ForgeError

NOT_YET = manager_check.NOT_YET


def default_read_waiters(slug: str) -> dict[str, str]:
    return fm.matching_refs(slug, forge_land_lock.WAIT_PREFIX)


def default_read_state(port: int) -> dict:
    url = f"http://127.0.0.1:{port}/api/state"
    return json.loads(urllib.request.urlopen(url, timeout=10).read())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lock_wait_check", description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True, help="the project id of the console entry")
    parser.add_argument("--repo", required=True, help="the repository slug, owner/name")
    parser.add_argument("--port", type=int, default=service.DEFAULT_PORT)
    parser.add_argument("--pattern", default=None, help="the branch pattern; default the checkout's")
    return parser


def _long_waiters(refs, open_numbers: set[int], now: int) -> set[int]:
    """The open pull requests of the live registrations that have waited the quiet window."""
    waiting: set[int] = set()
    for ref in refs:
        found = forge_land_lock.WAITER.fullmatch(ref.rsplit("/", 1)[-1])
        if found is None:
            continue
        since, pr, beat = (int(part) for part in found.groups())
        if (-forge_land_lock.QUEUE_SKEW <= now - beat <= forge_land_lock.QUEUE_LIVE
                and now - since >= deliveries.QUIET_AFTER_MS // 1000 and pr in open_numbers):
            waiting.add(pr)
    return waiting


def _running_sprints(state: dict, project: str) -> list[dict]:
    found: list[dict] = []

    def visit(entries) -> None:
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            if entry.get("type") == "quiet_group":
                visit(entry.get("projects"))
            elif entry.get("type") == "project" and entry.get("project_id") == project:
                found.extend(s for s in entry.get("sprints") or []
                             if isinstance(s, dict) and s.get("ended_at") is None)

    visit(state.get("entries") if isinstance(state, dict) else None)
    return found


def _issues(sprint: dict) -> set[int]:
    return {i["issue"] for i in sprint.get("issues") or [] if isinstance(i, dict)
            and isinstance(i.get("issue"), int)}


def main(argv=None, *, read_pulls=movement.read_pulls, read_waiters=default_read_waiters,
         forge_now=forge_land_lock.forge_now, read_state=default_read_state) -> int:
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
    long_waiters = _long_waiters(registrations, set(pulls), now)
    queued = sorted(holders | long_waiters)
    if len(queued) < 2 or not long_waiters:
        manager_check._print({"queued": queued, "status": "no_queue"})
        return NOT_YET
    try:
        state = read_state(args.port)
    except (OSError, ValueError) as error:
        manager_check._print({"reason": str(error), "status": "no_console"})
        return NOT_YET
    running = _running_sprints(state, args.project)
    waiter_issues = set().union(*(pulls[n].issues for n in long_waiters))
    holder_issues = set().union(*(pulls[n].issues for n in holders))
    waiter_sprints = [s for s in running if _issues(s) & waiter_issues]
    if not waiter_sprints:
        manager_check._print({"queued": queued, "status": "no_sprint"})
        return NOT_YET
    judged = waiter_sprints + [s for s in running
                               if s not in waiter_sprints and _issues(s) & holder_issues]
    stuck = sorted(str(s.get("sprint_id")) for s in judged
                   if s.get("state") == "quiet" or s.get("ball") == "nobody")
    if stuck:
        manager_check._print({"queued": queued, "status": "not_met", "stuck": stuck})
        return 1
    shown = sorted(({"sprint_id": s.get("sprint_id"), "state": s.get("state"),
                     "now_text": s.get("now_text")} for s in waiter_sprints),
                   key=lambda row: str(row["sprint_id"]))
    status = ("met" if any(s.get("now_text") == sprints.NOW_LOCK_TEXT for s in waiter_sprints)
              else "no_wait_shown")
    manager_check._print({"queued": queued, "sprints": shown, "status": status})
    return 0 if status == "met" else NOT_YET


if __name__ == "__main__":
    raise SystemExit(main())
