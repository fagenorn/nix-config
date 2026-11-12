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

`next_step(state, waiting, last_listed_ms, now_ms, can_wake, out=False)` returns `sprints.WAKE`,
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
7. Otherwise `WAKE`, or `None` while `out` (the manager's profile is out of quota, #929: nothing
   is sent to it; `STALL` and `TAKEOVER` are unchanged).

`stall_reason(state)` is the last revival's `reason` when that revival is not ok and has one, else
`GONE_AGAIN_TEXT`.
"""

from agent_tools.console import sprints, view
from agent_tools.console.sprints import SprintState

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
              can_wake: bool, out: bool = False) -> str | None:
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
    return None if out else sprints.WAKE


def stall_reason(state: SprintState) -> str:
    last = state.revivals[-1] if state.revivals else None
    if last is not None and not last.ok and last.reason:
        return last.reason
    return GONE_AGAIN_TEXT
