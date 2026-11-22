"""The engine core: a pure function from a procedure and its events to the next action (#1510).

`replay(procedure, inputs, events)` walks a procedure that passed `engine check`
and returns a `Replay`: the next `Action` and every `Transition` taken. State is
never stored; it is derived again from `events` on every call. The core reads
nothing and writes nothing: the shell performs every side effect and appends
the events.

Inputs
    procedure  the parsed procedure document (never mutated).
    inputs     the run inputs, one value per name the procedure declares; a
               `run.<n>` path reads `inputs[n]` (never mutated).
    events     the ledger so far, oldest first, each a dict of one of three types
               (`EVENT_TYPES`):
                 {"type": "entered", "step": <id>}
                     the shell began the pending step.
                 {"type": "outcome", "step": <id>, "outcome": <name>,
                  "result": {...}, "head": <str>}
                     the pending step finished; `result` (default `{}`) is the
                     step's reply members or command result. An `<X>.<m>` path
                     reads member `m` of the latest `outcome` result of step X.
                     The optional `head` is the repository head the result was
                     produced at; `reentry` compares it with the current one.
                 {"type": "continued", "step": <id>, "visit": <int> | None}
                     the run was continued at step X (see Continuing).
               A `decide` step publishes `{"verdict": <outcome>}` as its result
               each time it grades, so `<decide step>.verdict` is readable.
               Shell outcomes such as `no-reply`, `out-of-bounds` and `refused`
               are ordinary outcomes: they are followed through the step's `on`.

Actions (`Action`)
    RunCommand    run a `command` step (`visit` is the 1-based entry count).
    StartSession  start an `agent` step's session.
    Stop          the run stopped at a named stop with its `need` and `reenter`.
    Done          the run finished.
    Both step actions carry `args`: one `(path, value)` pair per entry of the
    step's `in`, in `in` order, resolved when the walk reaches the step. An `entered` event for the pending step does not
    change the action.

Visits
    An arrival is the walk reaching a `command`, `agent` or `decide` step within
    its visit bound; `decide` arrivals are recorded too. An action's `visit` is
    the count of every arrival of the step in the run, rewound ones included,
    so a number is never reused. Every entry of a step counts a visit. Entry `max_visits + 1` (`max_visits`
    defaults to 1) takes `on["exhausted"]` with no action and records
    `Transition(step, "exhausted", target)`. A `decide` step grades
    `{path: value for path in in}` with `engine_graders.GRADERS[step["grader"]]`
    and follows the returned outcome; no event is involved.

Continuing
    `continued(X, v)` rewinds the walk to the arrival of X's visit v: the visit
    counts, stored results, recorded heads and transitions return to their
    values at that arrival, which is then arrived at again under a new visit
    number without counting a visit (a `command` or `agent` step is pending and
    not entered; a `decide` step is graded again and the walk settles from its
    target). Rewinding to the pending arrival that has no `entered` event
    changes nothing. `continued(X, None)` enters X fresh and is valid only at a
    stop. A rewind owes a check for every entered arrival it discards:
    `owed[step]` grows by those arrivals, shrinks by one at each later `entered`
    event of the step and is never restored by a snapshot; `RunCommand.recheck`
    is true exactly for a pending `command` step with `mutates` true whose
    `owed` is above zero.
    `reentry(procedure, inputs, events, head)` answers where a continue should
    re-enter: the earliest stale result by arrival order (`live` is always
    stale, `head` is stale when the recorded head is absent, `head` is None or
    they differ, `run` never; only a step's latest outcome is judged), else the
    pending step, else the stop's `reenter` step with its latest arrival's visit
    (None when never reached). `stale` lists every stale step in arrival order.

`CoreError` is raised for: an event that is not a dict or whose type is not in
`EVENT_TYPES`, at any position; an `entered` naming a step but the pending one,
or a second `entered` for the same visit; an `outcome` naming a step but the
pending one, or before its `entered`; any event once the run ended in a stop or
`done`; an `outcome` reporting `exhausted`; any outcome (reported, graded or
`exhausted`) the step's `on` does not map; a `result` that is not a dict; an
`in` path with no value when the walk reaches the step; entry `max_visits + 2` of a step (a loop through
`exhausted`); entering a `group` or `call` step; a `continued` after `done`, naming no step of
the procedure or no step at all, naming an arrival the current walk lacks, or
with no visit while a step is pending; `reentry` on a run that reached `done`.

Later slices: `group` and `call` steps and waits.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agent_tools.delivery import engine_graders

EXHAUSTED = "exhausted"
EVENT_TYPES = ("entered", "outcome", "continued")
CORE_KINDS = ("command", "agent", "decide")


class CoreError(ValueError):
    """The procedure, inputs and events do not describe a walk of the core."""


@dataclass(frozen=True)
class RunCommand:
    step: str
    visit: int
    command: str
    subcommand: str | None
    args: tuple[tuple[str, object], ...]
    recheck: bool = False


@dataclass(frozen=True)
class StartSession:
    step: str
    visit: int
    role: str
    prompt: str
    reply: str
    args: tuple[tuple[str, object], ...]


@dataclass(frozen=True)
class Stop:
    name: str
    need: str
    reenter: str


@dataclass(frozen=True)
class Done:
    pass


Action = RunCommand | StartSession | Stop | Done


@dataclass(frozen=True)
class Transition:
    step: str
    outcome: str
    target: str


@dataclass(frozen=True)
class Replay:
    action: Action
    transitions: tuple[Transition, ...]


@dataclass(frozen=True)
class Reentry:
    step: str
    visit: int | None
    stale: tuple[str, ...]


@dataclass
class _Arrival:
    step: str
    visit: int
    snapshot: tuple[dict, dict, dict, int]
    entered: bool = False


@dataclass
class _Walk:
    position: str
    pending: dict | None
    args: tuple[tuple[str, object], ...]
    transitions: list[Transition]
    arrivals: list[_Arrival]
    produced: dict[str, tuple[int, int, object]]
    owed: dict[str, int] = field(default_factory=dict)


def _walk(procedure: Mapping, inputs: Mapping[str, object], events: Sequence[Mapping]) -> _Walk:
    steps = {item["id"]: item for item in procedure["steps"]}
    visits: dict[str, int] = {}
    total: dict[str, int] = {}
    results: dict[str, dict] = {}
    produced: dict[str, tuple[int, int, object]] = {}
    owed: dict[str, int] = {}
    transitions: list[Transition] = []
    arrivals: list[_Arrival] = []

    def value(path: str) -> object:
        source, _, member = path.partition(".")
        table = inputs if source == "run" else results.get(source, {})
        if member not in table:
            raise CoreError(f"no value for {path!r}")
        return table[member]

    def follow(step: Mapping, outcome: str) -> str:
        target = step["on"].get(outcome) if isinstance(outcome, str) else None
        if target is None:
            raise CoreError(f"step {step['id']!r} does not map outcome {outcome!r}")
        transitions.append(Transition(step["id"], outcome, target))
        return target

    def settle(where: str) -> tuple[str, dict | None, tuple[tuple[str, object], ...]]:
        while where in steps:
            step = steps[where]
            visits[where] = visits.get(where, 0) + 1
            bound = step.get("max_visits", 1)
            if visits[where] > bound + 1:
                raise CoreError(f"step {where!r} entered {visits[where]} times, past its exhausted entry")
            if visits[where] > bound:
                where = follow(step, EXHAUSTED)
                continue
            if step["kind"] not in CORE_KINDS:
                raise CoreError(f"step {where!r} is a {step['kind']!r} step, which the core does not run yet")
            total[where] = total.get(where, 0) + 1
            snapshot = (dict(visits), dict(results), dict(produced), len(transitions))
            arrivals.append(_Arrival(where, total[where], snapshot))
            if step["kind"] == "decide":
                grader = engine_graders.GRADERS[step["grader"]]
                graded = grader.grade({path: value(path) for path in step.get("in", [])})
                results[where] = {"verdict": graded}
                where = follow(step, graded)
            else:
                return where, step, tuple((path, value(path)) for path in step.get("in", []))
        return where, None, ()

    def rewind(arrival: _Arrival) -> tuple[str, dict | None, tuple[tuple[str, object], ...]]:
        index = arrivals.index(arrival)
        for later in arrivals[index:]:
            if later.entered:
                owed[later.step] = owed.get(later.step, 0) + 1
        seen, kept, made, length = arrival.snapshot
        visits.clear()
        visits.update(seen)
        visits[arrival.step] -= 1
        results.clear()
        results.update(kept)
        produced.clear()
        produced.update(made)
        del transitions[length:]
        del arrivals[index:]
        return settle(arrival.step)

    def continue_at(event: Mapping, position: str, pending: dict | None, args: tuple):
        if pending is None and position == "done":
            raise CoreError("event 'continued' after the run finished")
        step_id, visit = event.get("step"), event.get("visit")
        if not isinstance(step_id, str) or step_id not in steps:
            raise CoreError(f"continued names {step_id!r}, which is no step of the procedure")
        if visit is None:
            if pending is not None:
                raise CoreError(f"continued without a visit while {pending['id']!r} is pending")
            return settle(step_id)
        arrival = next((a for a in arrivals if (a.step, a.visit) == (step_id, visit)), None)
        if isinstance(visit, bool):
            arrival = None
        if arrival is None:
            raise CoreError(f"continued to {step_id!r} visit {visit!r}, which the walk never reached")
        if pending is not None and arrival is arrivals[-1] and not arrival.entered:
            return position, pending, args
        return rewind(arrival)

    position, pending, args = settle(procedure["steps"][0]["id"])
    for event in events:
        if not isinstance(event, Mapping) or event.get("type") not in EVENT_TYPES:
            kind = event.get("type") if isinstance(event, Mapping) else event
            raise CoreError(f"unknown event type {kind!r}")
        if event["type"] == "continued":
            position, pending, args = continue_at(event, position, pending, args)
            continue
        if pending is None:
            raise CoreError(f"event {event['type']!r} after the run ended at {position!r}")
        if event.get("step") != pending["id"]:
            raise CoreError(f"event {event['type']!r} names {event.get('step')!r}, pending step is {pending['id']!r}")
        current = arrivals[-1]
        if event["type"] == "entered":
            if current.entered:
                raise CoreError(f"step {pending['id']!r} entered twice in one visit")
            current.entered = True
            if owed.get(current.step, 0) > 0:
                owed[current.step] -= 1
            continue
        if not current.entered:
            raise CoreError(f"outcome for {pending['id']!r} before its entered event")
        outcome = event.get("outcome")
        if outcome == EXHAUSTED:
            raise CoreError(f"step {pending['id']!r} reported the reserved outcome {EXHAUSTED!r}")
        result = event.get("result", {})
        if not isinstance(result, dict):
            raise CoreError(f"result of {pending['id']!r} is not an object")
        results[pending["id"]] = result
        produced[pending["id"]] = (len(arrivals) - 1, current.visit, event.get("head"))
        position, pending, args = settle(follow(pending, outcome))

    return _Walk(position, pending, args, transitions, arrivals, produced, owed)


def replay(procedure: Mapping, inputs: Mapping[str, object], events: Sequence[Mapping]) -> Replay:
    walk = _walk(procedure, inputs, events)
    pending, transitions = walk.pending, tuple(walk.transitions)
    if pending is not None:
        visit = walk.arrivals[-1].visit
        if pending["kind"] == "command":
            recheck = pending.get("mutates") is True and walk.owed.get(pending["id"], 0) > 0
            return Replay(
                RunCommand(pending["id"], visit, pending["command"], pending.get("subcommand"), walk.args, recheck),
                transitions,
            )
        return Replay(
            StartSession(pending["id"], visit, pending["role"], pending["prompt"], pending["reply"], walk.args),
            transitions,
        )
    if walk.position == "done":
        return Replay(Done(), transitions)
    stop = procedure["stops"][walk.position]
    return Replay(Stop(walk.position, stop["need"], stop["reenter"]), transitions)


def reentry(
    procedure: Mapping, inputs: Mapping[str, object], events: Sequence[Mapping], head: str | None
) -> Reentry:
    walk = _walk(procedure, inputs, events)
    if walk.pending is None and walk.position == "done":
        raise CoreError("a run that reached done has no re-entry point")
    steps = {item["id"]: item for item in procedure["steps"]}
    stale = []
    for index, visit, recorded, step_id in sorted(
        (index, visit, recorded, step_id) for step_id, (index, visit, recorded) in walk.produced.items()
    ):
        holds = steps[step_id]["holds"]
        if holds == "live" or (holds == "head" and (head is None or recorded != head)):
            stale.append((step_id, visit))
    names = tuple(name for name, _ in stale)
    if stale:
        return Reentry(stale[0][0], stale[0][1], names)
    if walk.pending is not None:
        return Reentry(walk.pending["id"], walk.arrivals[-1].visit, names)
    target = procedure["stops"][walk.position]["reenter"]
    latest = next((a.visit for a in reversed(walk.arrivals) if a.step == target), None)
    return Reentry(target, latest, names)


def next_action(procedure: Mapping, inputs: Mapping[str, object], events: Sequence[Mapping]) -> Action:
    return replay(procedure, inputs, events).action
