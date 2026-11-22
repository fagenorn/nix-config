"""The engine core: a pure function from a procedure and its events to the next action (#1510).

`replay(procedure, inputs, events)` walks a procedure that passed `engine check` and returns a `Replay`: the next
`Action` and every `Transition` taken. State is never stored; it is derived again from `events` on every call. The
core reads and writes nothing: the shell performs every side effect.

Inputs
    procedure  the parsed procedure document (never mutated).
    inputs     the run inputs, one value per declared name; `run.<n>` reads `inputs[n]` (never mutated).
    events     the ledger so far, oldest first, each a dict of one of two types (`EVENT_TYPES`):
                 {"type": "entered", "step": <id>}   the shell began the pending step.
                 {"type": "outcome", "step": <id>, "outcome": <name>, "result": {...}}
                     the pending step finished; `result` (default `{}`) is the step's reply members or
                     command result. An `<X>.<m>` path reads member `m` of the latest `outcome`
                     result of step X.
               A `decide` step publishes `{"verdict": <outcome>}` as its result each time it grades,
               so `<decide step>.verdict` is readable. Shell outcomes such as `no-reply`,
               `out-of-bounds` and `refused` are ordinary outcomes, followed through the step's `on`.

Actions (`Action`)
    RunCommand    run a `command` step (`visit` is the 1-based entry count).
    StartSession  start an `agent` step's session.
    Stop          the run stopped at a named stop with its `need` and `reenter`.
    Done          the run finished.
    Both step actions carry `args`: one `(path, value)` pair per entry of the step's `in`, in `in`
    order, resolved when the walk reaches the step.

Visits
    Every entry of a step counts a visit. Entry `max_visits + 1` (`max_visits` defaults to 1) takes
    `on["exhausted"]` with no action and records `Transition(step, "exhausted", target)`. A `decide`
    step grades `{path: value for path in in}` with `engine_graders.GRADERS[step["grader"]]` and
    follows the returned outcome; no event is involved.

`CoreError` is raised for: an event that is not a dict or whose type is not in `EVENT_TYPES`, at any position;
an `entered` naming a step but the pending one, or a second one for the same visit; an `outcome` naming a step
but the pending one, or before its `entered`; any event once the run ended in a stop or `done`; an `outcome`
reporting `exhausted`; any outcome (reported, graded or `exhausted`) the step's `on` does not map; a `result`
that is not a dict; an `in` path with no value when the walk reaches the step; entry `max_visits + 2` of a
step (a loop through `exhausted`); entering a `group` or `call` step.

Later slices: `group` and `call` steps, waits and continuing a stopped run.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agent_tools.delivery import engine_graders

EXHAUSTED = "exhausted"
EVENT_TYPES = ("entered", "outcome")
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


def replay(procedure: Mapping, inputs: Mapping[str, object], events: Sequence[Mapping]) -> Replay:
    steps = {item["id"]: item for item in procedure["steps"]}
    visits: dict[str, int] = {}
    results: dict[str, dict] = {}
    transitions: list[Transition] = []
    pending: dict | None = None
    entered = False
    position = procedure["steps"][0]["id"]

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
            elif step["kind"] == "decide":
                grader = engine_graders.GRADERS[step["grader"]]
                graded = grader.grade({path: value(path) for path in step.get("in", [])})
                results[where] = {"verdict": graded}
                where = follow(step, graded)
            elif step["kind"] in ("command", "agent"):
                return where, step, tuple((path, value(path)) for path in step.get("in", []))
            else:
                raise CoreError(f"step {where!r} is a {step['kind']!r} step, which the core does not run yet")
        return where, None, ()

    position, pending, args = settle(position)
    for event in events:
        if not isinstance(event, Mapping) or event.get("type") not in EVENT_TYPES:
            kind = event.get("type") if isinstance(event, Mapping) else event
            raise CoreError(f"unknown event type {kind!r}")
        if pending is None:
            raise CoreError(f"event {event['type']!r} after the run ended at {position!r}")
        if event.get("step") != pending["id"]:
            raise CoreError(f"event {event['type']!r} names {event.get('step')!r}, pending step is {pending['id']!r}")
        if event["type"] == "entered":
            if entered:
                raise CoreError(f"step {pending['id']!r} entered twice in one visit")
            entered = True
            continue
        if not entered:
            raise CoreError(f"outcome for {pending['id']!r} before its entered event")
        outcome = event.get("outcome")
        if outcome == EXHAUSTED:
            raise CoreError(f"step {pending['id']!r} reported the reserved outcome {EXHAUSTED!r}")
        result = event.get("result", {})
        if not isinstance(result, dict):
            raise CoreError(f"result of {pending['id']!r} is not an object")
        results[pending["id"]] = result
        position, pending, args = settle(follow(pending, outcome))
        entered = False

    if pending is not None:
        if pending["kind"] == "command":
            return Replay(
                RunCommand(pending["id"], visits[pending["id"]], pending["command"], pending.get("subcommand"), args),
                tuple(transitions),
            )
        return Replay(
            StartSession(
                pending["id"], visits[pending["id"]], pending["role"], pending["prompt"], pending["reply"], args
            ),
            tuple(transitions),
        )
    if position == "done":
        return Replay(Done(), tuple(transitions))
    stop = procedure["stops"][position]
    return Replay(Stop(position, stop["need"], stop["reenter"]), tuple(transitions))


def next_action(procedure: Mapping, inputs: Mapping[str, object], events: Sequence[Mapping]) -> Action:
    return replay(procedure, inputs, events).action
