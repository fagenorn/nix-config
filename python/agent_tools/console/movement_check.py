"""`movement_check`: the verify script that session output moves a sprint the console reads (#1185).

`python -m agent_tools.console.movement_check [--url URL]` reads the console's `/api/state` once
and judges every running sprint. Nothing is written and nothing is posted.

Sprints. The running sprints are the sprint entries in `sprints` of every project entry whose
`ended_at` is null, both the top-level project entries and those inside a `quiet_group`'s
`projects`. Finished sprints are not read.

Sessions. A sprint's sessions are exactly its `movement.sessions[]`, the console's own
associations (the manager by name or by `manager_session`, and the deliveries on a report `issues`
or `inbox` issue). The check never rebuilds membership from `sessions[]` or `outside_sprints`: they
miss a manager known only by `manager_session` and a delivery on an inbox issue.

Output. For each association `W = movement.session_output_ms(projects(), session_id)`. W counts
when W is not None, `now_ms - W < FRESH_MS`, and it is not the case that the association is the
manager, `nudged_at` is set and `nudged <= W < nudged + view.NUDGE_REPLY_MS` (a manager's reply to
an idle nudge, which the console leaves out too). W is seen when it counts, the association's
`read_at` is not null and `W <= read_at`: a session read that started after the write has completed.
A write newer than the console's last read is never judged.

Exits, one JSON line with sorted keys.
- 1 not met: some running sprint has a seen association and reads `state == "quiet"` or `ball ==
  "nobody"`: `{"status": "not_met", "stuck": [{"output_age_s", "project_id", "session_id",
  "sprint_id"}]}`.
- 0 met: no sprint is stuck and some running sprint has a counted association, `state != "quiet"`
  and `ball == "manager"`, a `status_at` and a `movement.base_at` both older than `OLD_MS` (so the
  goal, approval, report and run movement would not move it), a `now_text` that is not one of
  `WAIT_TEXTS`, no `sessions[]` entry in state `working`, and no delivery entry with a `moved_at`
  younger than `OLD_MS`. That covers every delivery entry of a session entry of the project (the
  sprint's `sessions[]` and `outside_sprints.sessions[]`) whose `session_id` is one of the sprint's
  associations or whose `issues[].issue` meets the sprint's `issues[].issue`. Only the session
  signals of this change can then be moving it: `{"status": "met", "moving": [<same members>]}`.
- 75 not yet: `{"status": "waiting"}`, or `{"status": "no_console"}` when the console does not
  answer.
- 2 a usage error, including a URL that is not http on loopback.

The seams of `main` are `state`, `clock` (seconds) and `projects`.
"""

import argparse
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.console import manager_check, movement, service, view
from agent_tools.console.deliveries import QUIET_AFTER_MS
from agent_tools.console.sprints import NOW_CI_TEXT, NOW_COMMITTING_TEXT, NOW_RELEASE_TEXT

FRESH_MS = QUIET_AFTER_MS - 3 * 60_000
OLD_MS = QUIET_AFTER_MS
WAIT_TEXTS = (NOW_CI_TEXT, NOW_COMMITTING_TEXT, NOW_RELEASE_TEXT)
NOT_YET = manager_check.NOT_YET


def _ms(text) -> int | None:
    if not isinstance(text, str):
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return int(stamp.timestamp() * 1000)


def default_projects() -> list[Path]:
    seen: list[Path] = []
    for directory in service.default_session_dirs():
        projects = directory.parent / "projects"
        if projects not in seen:
            seen.append(projects)
    return seen


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _running(document: dict) -> Iterator[tuple[dict, dict]]:
    """`(project entry, sprint entry)` for every running sprint, quiet groups included."""
    for entry in _list(document.get("entries")):
        entry = _dict(entry)
        inside = _list(entry.get("projects")) if entry.get("type") == "quiet_group" else [entry]
        for project in inside:
            project = _dict(project)
            for sprint in _list(project.get("sprints")):
                if isinstance(sprint, dict) and sprint.get("ended_at") is None:
                    yield project, sprint


def _issues(entries) -> set:
    return {_dict(i).get("issue") for i in _list(entries)} - {None}


def _associations(sprint: dict, now_ms: int, dirs: list[Path]) -> list[dict]:
    moved = _dict(sprint.get("movement"))
    nudged = _ms(moved.get("nudged_at"))
    found = []
    for assoc in _list(moved.get("sessions")):
        assoc = _dict(assoc)
        session_id = assoc.get("session_id")
        if not isinstance(session_id, str):
            continue
        written = movement.session_output_ms(dirs, session_id)
        counts = (written is not None and now_ms - written < FRESH_MS
                  and not (assoc.get("manager") is True and nudged is not None
                           and nudged <= written < nudged + view.NUDGE_REPLY_MS))
        read = _ms(assoc.get("read_at"))
        found.append({"session_id": session_id, "counts": counts,
                      "seen": counts and read is not None and written <= read,
                      "output_age_s": 0 if written is None else (now_ms - written) // 1000})
    return found


def _report(project: dict, sprint: dict, assoc: dict) -> dict:
    return {"output_age_s": assoc["output_age_s"], "project_id": project.get("project_id"),
            "session_id": assoc["session_id"], "sprint_id": sprint.get("sprint_id")}


def _old(text, now_ms: int) -> bool:
    stamp = _ms(text)
    return stamp is not None and now_ms - stamp > OLD_MS


def _reads_moving(project: dict, sprint: dict, found: list[dict], now_ms: int) -> bool:
    if not (any(a["counts"] for a in found) and sprint.get("state") != "quiet"
            and sprint.get("ball") == "manager"
            and _old(sprint.get("status_at"), now_ms)
            and _old(_dict(sprint.get("movement")).get("base_at"), now_ms)
            and sprint.get("now_text") not in WAIT_TEXTS):
        return False
    own = [_dict(s) for s in _list(sprint.get("sessions"))]
    if any(s.get("state") == "working" for s in own):
        return False
    ids = {a["session_id"] for a in found}
    issues = _issues(sprint.get("issues"))
    outside = [_dict(s) for s in _list(_dict(project.get("outside_sprints")).get("sessions"))]
    for entry in (*own, *outside):
        for delivery in _list(entry.get("deliveries")):
            delivery = _dict(delivery)
            if entry.get("session_id") in ids or issues & _issues(delivery.get("issues")):
                moved = _ms(delivery.get("moved_at"))
                if moved is None or now_ms - moved < OLD_MS:
                    return False
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="movement_check", description=__doc__.splitlines()[0])
    parser.add_argument("--url", type=manager_check._loopback_url,
                        default=manager_check.DEFAULT_URL)
    return parser


def main(argv=None, *, state: Callable[[], dict | None] | None = None,
         clock: Callable[[], float] = time.time,
         projects: Callable[[], list[Path]] = default_projects) -> int:
    args = build_parser().parse_args(argv)
    document = (state or manager_check.Console(args.url).state)()
    if document is None:
        manager_check._print({"status": "no_console"})
        return NOT_YET
    now_ms = int(clock() * 1000)
    dirs = projects()
    stuck, moving = [], []
    for project, sprint in _running(document):
        found = _associations(sprint, now_ms, dirs)
        if sprint.get("state") == "quiet" or sprint.get("ball") == "nobody":
            stuck += [_report(project, sprint, a) for a in found if a["seen"]]
        elif _reads_moving(project, sprint, found, now_ms):
            moving += [_report(project, sprint, a) for a in found if a["counts"]]
    if stuck:
        manager_check._print({"status": "not_met", "stuck": stuck})
        return 1
    if moving:
        manager_check._print({"moving": moving, "status": "met"})
        return 0
    manager_check._print({"status": "waiting"})
    return NOT_YET


if __name__ == "__main__":
    raise SystemExit(main())
