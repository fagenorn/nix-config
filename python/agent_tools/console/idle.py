"""Whether an idle manager is told to go on (#929): one pure decision over a folded sprint.

A sprint's manager is a background session. When it ends a turn with the sprint still having work
(it is idle, or at its usage limit), the console sends it one fixed sentence to go on, and after
too many such nudges without a report opens an item for the owner. This module only decides which;
the service sends the nudge and writes the rows `sprints` folds. It reads no clock, file or
environment (the caller passes every time in milliseconds), and `sprints` does not import it or
`view`.

`has_work(state, waiting)` says whether the sprint needs its manager: `view.sprint_state(state,
None, waiting)[0]` is `STARTING` or `ON_TRACK`. It is quota-blind (three arguments) on purpose.

`next_step(state, waiting, session, active_ms, out, now_ms, forced=False, run_ms=None)` returns
`NUDGE`, `GIVE_UP` or `None` (do nothing). `session` is the manager's session (`sessions.SessionState`) or
None, `active_ms` the latest time, other than the session's own `last_at`, that shows the manager
active (the last movement of a run of its session, kept after the run ends, or the console's last
launch, nudge or wake of the sprint) or None, `out` whether the manager's profile is out of quota,
`run_ms` the latest movement of a delivery run of the manager's session that is still in progress
(ended or unseen runs do not count) or None (#974).
The first rule that matches wins:

1. The sprint has no manager, the manager's state is not `STARTED`, the sprint is stalled or
   `no_progress_at` is set (an item is open for the owner): `None`.
2. `has_work(state, waiting)` is false: `None`.
3. `session` is None or its state is not in `IDLE_STATES` (`idle`, `limit`): `None`.
4. `out`: `None`, forced or not.
5. Unless `forced`: `now_ms - max(session.last_at, active_ms or 0)` is under `IDLE_AFTER_MS`:
   `None`.
6. Unless `forced`: `run_ms` is set and under `RUN_STILL_MS` old: `None`. A manager waiting on its
   own delivery is waiting on purpose, and one step of a delivery can run long with no journal row.
7. Unless `forced`: `idle_nudged_at` is set and `NUDGE_EVERY_MS` have not passed since it: `None`.
8. `idle_nudges >= LIMIT`: `GIVE_UP`.
9. `NUDGE`.

`last_moved(events, moved=None)` folds `delivery.seen` rows into a dict of session id to the largest
`moved_ms` any row of that session carried. A row whose payload is not a dict, whose `session_id`
is not a string or whose `moved_ms` is not an int (a bool is not) changes nothing, and so does every
other kind, `delivery.gone` included: a run's movement outlives the run. Folding `a + b` equals
folding `b` onto the fold of `a`.
"""

from collections.abc import Iterable, Mapping

from agent_tools.console import deliveries, sessions, sprints, view
from agent_tools.console.event_log import Event
from agent_tools.console.sessions import SessionState
from agent_tools.console.sprints import SprintState

IDLE_AFTER_MS = 300_000
NUDGE_EVERY_MS = 600_000
RUN_STILL_MS = 1_800_000
LIMIT = 3
NUDGE = "nudge"
GIVE_UP = "give_up"
IDLE_STATES = (sessions.IDLE, sessions.LIMIT)


def has_work(state: SprintState, waiting: int) -> bool:
    return view.sprint_state(state, None, waiting)[0] in (sprints.STARTING, sprints.ON_TRACK)


def next_step(state: SprintState, waiting: int, session: SessionState | None,
              active_ms: int | None, out: bool, now_ms: int, forced: bool = False,
              run_ms: int | None = None) -> str | None:
    manager = state.manager
    if (manager is None or manager.state != sprints.STARTED or state.stalled is not None
            or state.no_progress_at is not None):
        return None
    if not has_work(state, waiting):
        return None
    if session is None or session.state not in IDLE_STATES:
        return None
    if out:
        return None
    if not forced:
        if now_ms - max(sprints._ms(session.last_at), active_ms or 0) < IDLE_AFTER_MS:
            return None
        if run_ms is not None and now_ms - run_ms < RUN_STILL_MS:
            return None
        if state.idle_nudged_at is not None \
                and now_ms - sprints._ms(state.idle_nudged_at) < NUDGE_EVERY_MS:
            return None
    return GIVE_UP if state.idle_nudges >= LIMIT else NUDGE


def last_moved(events: Iterable[Event], moved: Mapping[str, int] | None = None) -> dict[str, int]:
    folded = dict(moved or {})
    for event in events:
        if event.kind != deliveries.DELIVERY_SEEN or not isinstance(event.payload, dict):
            continue
        session_id, moved_ms = event.payload.get("session_id"), event.payload.get("moved_ms")
        if isinstance(session_id, str) and isinstance(moved_ms, int) \
                and not isinstance(moved_ms, bool):
            folded[session_id] = max(folded.get(session_id, moved_ms), moved_ms)
    return folded
