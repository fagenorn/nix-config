"""Which step brings a gone manager back (#893): one pure decision over a folded sprint.

A sprint's manager is a background session. When it stops while the sprint still has work, the
console brings it back, first by waking the same session (`sprints.WAKE`), then by starting a new
manager in its place (`sprints.TAKEOVER`), and gives up after too many tries (`STALL`). This module
only decides which; the service carries the step out and writes the rows `sprints` folds. It reads
no clock, file or environment (the caller passes every time in milliseconds), and `sprints` does
not import it or `view`.

`has_work(state, waiting)` says whether the sprint needs a manager. It is the shown state without
the clock: `name = view.sprint_state(state, None, waiting)[0]`. `DRAFTING` is work only when the
sprint has no brief or its brief's decision is `changes` (a brief waiting on the owner is not);
`STARTING` and `ON_TRACK` are work; `WAITING` (on the owner), `CLOSING`, `DONE` and `QUIET` are not.

`counted(state, now_ms)` is how many revivals count against the limit: those whose time is within
`WINDOW_MS` before `now_ms` (strictly after `now_ms - WINDOW_MS`) that are takeovers, or wakes
that are `ok` and `back`. A wake has failed when `not (ok and back)`.

`next_step(state, waiting, last_listed_ms, now_ms, can_wake, out=False, room_elsewhere=False)` returns `sprints.WAKE`,
`sprints.TAKEOVER`, `STALL` or `None` (no step). The first rule that matches wins:

1. The sprint has no manager, it is stalled, or `no_progress_at` is set (an item is open for the
   owner, #929; `sprint.continued` clears it): `None`.
2. The manager is neither `STARTED` nor (`FAILED` or `WAITING` with `takeover` true): `None`. A
   first launch that failed or waits is the owner's retry, not a bring-back.
3. `has_work(state, waiting)` is false: `None`.
4. `since` is the latest of `last_listed_ms` (when the manager was last listed), the manager row's
   time and the last revival's time; while `now_ms - since < GONE_AFTER_MS` the manager is not
   gone: `None`. A takeover `WAITING` manager with a string `until` also gets `None` while
   `now_ms < until`.
5. `counted(state, now_ms) >= LIMIT`: `STALL`.
6. The manager is `FAILED` or `WAITING` (a takeover), or `not can_wake`, or the sprint has no
   `manager_session`, or the last `FAILED_WAKES` revivals are all wakes that failed: `TAKEOVER`.
7. Otherwise `WAKE`. While `out` (the manager's profile is out of quota, #929) nothing is sent to
   it: the step is `TAKEOVER` when `room_elsewhere` (a new session would get a profile with room,
   #1278), else `None`; `STALL` and the `TAKEOVER` of step 6 are unchanged.

`stall_reason(state)` is the last revival's `reason` when that revival is not ok and has one, else
`GONE_AGAIN_TEXT`.

`unheld(state, runs, live, engine=())` is what the service calls when it prepares a takeover launch.
It returns, ascending, an `(issue, stage)` for each issue of `state.report.issues` whose effective
stage (`view.effective_stages` with the sprint's engine runs: the stage the console shows, so a run
seen after the report or a moving engine run counts) is not `queued`, `landed`, `held`, `dropped` or
`closed out` and that no holder holds; `stage` is that effective stage. With no report it returns
`()`. A holder is a session run in `runs` that lists the issue while its `project` is the sprint's
`project_id` and its `session_id` is in `live`, or an engine run in `engine` for the issue with the
sprint's project whose `engine_runs.reading` is `moving` or `waiting` (a live engine process that is
neither done nor stopped).

`unheld_block(found)` is the text a takeover prompt carries about those `(issue, stage)` pairs: `""`
for none; else `UNHELD_HEAD`, one `UNHELD_LINE` per pair in the given order, then `UNHELD_TAIL`,
joined by newlines. No line holds `The goal: `, which the prompt's goal parsing looks for.
"""

from collections.abc import Collection, Iterable, Sequence

from agent_tools.console import deliveries, engine_runs, sprints, view
from agent_tools.console.sprints import SprintState
from agent_tools.delivery.engine_ledger import RunState

UNHELD_HEAD = "No running session holds these deliveries any more, though your sprint lists them as in work:"
UNHELD_LINE = "- issue {issue} at stage {stage}"
UNHELD_TAIL = ("Before anything else, name each of them in your next report: say in its status line, "
               "in plain words and without their numbers, that they stopped, and in its next step "
               "how you resume each one.")
GONE_AFTER_MS = 120_000
LIMIT = 3
WINDOW_MS = 3_600_000
FAILED_WAKES = 2
STALL = "stall"
GONE_AGAIN_TEXT = "the manager stopped again after it was brought back"


def has_work(state: SprintState, waiting: int) -> bool:
    name = view.sprint_state(state, None, waiting)[0]
    if name == sprints.DRAFTING:
        return state.brief is None or state.brief.decision == sprints.CHANGES
    return name in (sprints.STARTING, sprints.ON_TRACK)


def counted(state: SprintState, now_ms: int) -> int:
    return sum(sprints._ms(r.at) > now_ms - WINDOW_MS
               and (r.how == sprints.TAKEOVER or (r.how == sprints.WAKE and r.ok and r.back))
               for r in state.revivals)


def _failed_wake(revival: sprints.Revival) -> bool:
    return revival.how == sprints.WAKE and not (revival.ok and revival.back)


def next_step(state: SprintState, waiting: int, last_listed_ms: int, now_ms: int,
              can_wake: bool, out: bool = False, room_elsewhere: bool = False) -> str | None:
    manager = state.manager
    if manager is None or state.stalled is not None or state.no_progress_at is not None:
        return None
    retried = manager.state in (sprints.FAILED, sprints.WAITING) and manager.takeover
    if manager.state != sprints.STARTED and not retried:
        return None
    if not has_work(state, waiting):
        return None
    since = max(last_listed_ms, sprints._ms(manager.at))
    if state.revivals:
        since = max(since, sprints._ms(state.revivals[-1].at))
    if now_ms - since < GONE_AFTER_MS:
        return None
    if retried and manager.state == sprints.WAITING and manager.until is not None \
            and now_ms < sprints._ms(manager.until):
        return None
    if counted(state, now_ms) >= LIMIT:
        return STALL
    last = state.revivals[-FAILED_WAKES:]
    if (retried or not can_wake or state.manager_session is None
            or (len(last) == FAILED_WAKES and all(_failed_wake(r) for r in last))):
        return sprints.TAKEOVER
    if out:
        # The manager's account is out (#929). Another account with room takes the sprint over
        # (#1278); with none, the sprint waits for the reset.
        return sprints.TAKEOVER if room_elsewhere else None
    return sprints.WAKE


def unheld(state: SprintState, runs: Iterable[deliveries.DeliveryState], live: Collection[str],
           engine: Iterable[RunState] = ()) -> tuple[tuple[int, str], ...]:
    if state.report is None:
        return ()
    engine = tuple(engine)
    held = {stage.issue for run in runs
            if run.project == state.project_id and run.session_id in live
            for stage in run.issues}
    held |= {run.issue for run in engine if run.project == state.project_id
             and engine_runs.reading(run) in ("moving", "waiting")}
    shown = engine_runs.sprint_engine(engine, state.project_id,
                                      {issue for issue, _ in state.report.issues}, None)
    idle = (deliveries.QUEUED, sprints.LANDED, sprints.HELD, sprints.DROPPED, sprints.CLOSED_OUT)
    return tuple((issue, stage) for issue, stage, _ in view.effective_stages(state, shown)
                 if stage not in idle and issue not in held)


def unheld_block(found: Sequence[tuple[int, str]]) -> str:
    if not found:
        return ""
    lines = [UNHELD_LINE.format(issue=issue, stage=stage) for issue, stage in found]
    return "\n".join([UNHELD_HEAD, *lines, UNHELD_TAIL])


def stall_reason(state: SprintState) -> str:
    last = state.revivals[-1] if state.revivals else None
    if last is not None and not last.ok and last.reason:
        return last.reason
    return GONE_AGAIN_TEXT
