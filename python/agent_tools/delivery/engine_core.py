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
    RunGroup      run a `group` step's members beside each other: `members` are
                  the `RunCommand`/`StartSession` of every member with no
                  outcome yet this visit, in the group's `members` order.
    RunCall       run a `call` step's child procedure: `procedure`, `items`
                  (the resolved `each` list as a tuple, `None` for a call
                  without `each`), `parallel` (default 1) and `args`.
    Stop          the run stopped at a named stop with its `need` and `reenter`.
    Done          the run finished.
    Every action that runs a step carries `args`: one `(path, value)` pair per entry of the step's
    `in`, in `in` order, resolved when the walk reaches the step.
    An `entered` event for the pending step does not change the action.

Visits
    Every entry of a step counts a visit. Entry `max_visits + 1` (`max_visits` defaults to 1) takes
    `on["exhausted"]` with no action and records `Transition(step, "exhausted", target)`. A `decide`
    step grades `{path: value for path in in}` with `engine_graders.GRADERS[step["grader"]]` and
    follows the returned outcome; no event is involved.

Groups
    Entering a group counts a visit of the group and of every member. A member
    past its own `max_visits` takes the outcome `exhausted` with no action; a
    `decide` member is graded at once and publishes `{"verdict": ...}` under
    its own id; a member that is a `call` raises `CoreError`. The members left
    run beside each other. The shell reports the group's `entered` first, then
    for each member in any order its `entered` and `outcome`; a member's
    `result` is stored under the member's own id. When no member waits, the
    group follows `pass` if every member outcome is in that member's `pass`,
    else `blocked`, and records `Transition(group, outcome, target)`. A group
    with no member to run is graded at once. `Replay.graded` lists every group
    grade, one `Graded(group, visit, outcome, target)` per graded visit, in
    order; it never holds `exhausted`, since a group past its bound is not
    graded.

Calls
    A call's items are the list `each` reads: every item is a string or a
    non-boolean integer (a child run input), checked before the action is
    returned. The shell reports `entered` then an `outcome` whose `result` is
    `{"items": [{"end": <end>, ...}, ...]}`, one entry per item (one entry for
    a call without `each`). The outcome must be `call_outcome` of those ends:
    `done` when every end is `done` (and for no ends), else the first end that
    is not `done`, in list order.

`CoreError` is raised for: an event that is not a dict or whose type is not in
`EVENT_TYPES`, at any position; an `entered` naming a step but the pending one
(for a pending group: the group itself, then a waiting member), or a second
`entered` for the same visit; an `outcome` naming a step but the pending one,
or before its `entered`; an `outcome` naming a pending group; any event once the
run ended in a stop or `done`; an `outcome` reporting `exhausted`; any outcome
(reported, graded or `exhausted`) the step's `on` does not map; a member outcome
that is not a string; a `result` that is not a dict; an `in` path with no value
when the walk reaches the step; entry `max_visits + 2` of a step (a loop through
`exhausted`); an `each` that is not a list or holds an item that is not a string
or an integer; a call outcome that disagrees with its ends or a call result
without one entry per item; a group member that is a `call` step.

Later slices: waits and continuing a stopped run.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agent_tools.delivery import engine_graders

EXHAUSTED = "exhausted"
EVENT_TYPES = ("entered", "outcome")
CORE_KINDS = ("command", "agent", "decide", "group", "call")


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
class RunGroup:
    step: str
    visit: int
    members: tuple[RunCommand | StartSession, ...]


@dataclass(frozen=True)
class RunCall:
    step: str
    visit: int
    procedure: str
    items: tuple[object, ...] | None
    parallel: int
    args: tuple[tuple[str, object], ...]


@dataclass(frozen=True)
class Stop:
    name: str
    need: str
    reenter: str


@dataclass(frozen=True)
class Done:
    pass


Action = RunCommand | StartSession | RunGroup | RunCall | Stop | Done


@dataclass(frozen=True)
class Transition:
    step: str
    outcome: str
    target: str


@dataclass(frozen=True)
class Graded:
    step: str
    visit: int
    outcome: str
    target: str


@dataclass(frozen=True)
class Replay:
    action: Action
    transitions: tuple[Transition, ...]
    graded: tuple[Graded, ...] = ()


@dataclass
class _Pending:
    """The step the walk waits on: what has been entered, and for a group what each member did."""

    step: dict
    args: tuple[tuple[str, object], ...] = ()
    items: tuple[object, ...] | None = None
    waiting: dict[str, tuple[tuple[str, object], ...]] = field(default_factory=dict)
    outcomes: dict[str, str] = field(default_factory=dict)
    entered: set[str] = field(default_factory=set)


def call_outcome(ends: Sequence[str]) -> str:
    """`done` when every end is `done`, else the first end that is not, in list order."""
    return next((end for end in ends if end != "done"), "done")


def _run_step(step: Mapping, visit: int, args: tuple[tuple[str, object], ...]) -> RunCommand | StartSession:
    if step["kind"] == "command":
        return RunCommand(step["id"], visit, step["command"], step.get("subcommand"), args)
    return StartSession(step["id"], visit, step["role"], step["prompt"], step["reply"], args)


def replay(procedure: Mapping, inputs: Mapping[str, object], events: Sequence[Mapping]) -> Replay:
    steps = {item["id"]: item for item in procedure["steps"]}
    visits: dict[str, int] = {}
    results: dict[str, dict] = {}
    transitions: list[Transition] = []
    graded: list[Graded] = []

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

    def args_of(step: Mapping) -> tuple[tuple[str, object], ...]:
        return tuple((path, value(path)) for path in step.get("in", []))

    def grade_decide(step: Mapping) -> str:
        grader = engine_graders.GRADERS[step["grader"]]
        outcome = grader.grade({path: value(path) for path in step.get("in", [])})
        results[step["id"]] = {"verdict": outcome}
        return outcome

    def grade_group(pending: _Pending) -> str:
        step = pending.step
        every = all(pending.outcomes[member["step"]] in member["pass"] for member in step["members"])
        outcome = "pass" if every else "blocked"
        target = follow(step, outcome)
        graded.append(Graded(step["id"], visits[step["id"]], outcome, target))
        return target

    def open_group(step: dict) -> _Pending:
        pending = _Pending(step)
        for member in step["members"]:
            owner = steps[member["step"]]
            name = owner["id"]
            visits[name] = visits.get(name, 0) + 1
            if owner["kind"] not in ("command", "agent", "decide"):
                raise CoreError(f"group {step['id']!r} member {name!r} is a {owner['kind']!r} step")
            if visits[name] > owner.get("max_visits", 1):
                pending.outcomes[name] = EXHAUSTED
            elif owner["kind"] == "decide":
                pending.outcomes[name] = grade_decide(owner)
            else:
                pending.waiting[name] = args_of(owner)
        return pending

    def resolve_items(step: Mapping) -> tuple[object, ...] | None:
        if "each" not in step:
            return None
        listed = value(step["each"])
        if not isinstance(listed, list):
            raise CoreError(f"{step['each']!r} of call {step['id']!r} is not a list")
        for item in listed:
            if isinstance(item, bool) or not isinstance(item, (str, int)):
                raise CoreError(f"item {item!r} of call {step['id']!r} is not a string or an integer")
        return tuple(listed)

    def settle(where: str) -> tuple[str, _Pending | None]:
        while where in steps:
            step = steps[where]
            visits[where] = visits.get(where, 0) + 1
            bound = step.get("max_visits", 1)
            if visits[where] > bound + 1:
                raise CoreError(f"step {where!r} entered {visits[where]} times, past its exhausted entry")
            if visits[where] > bound:
                where = follow(step, EXHAUSTED)
            elif step["kind"] == "decide":
                where = follow(step, grade_decide(step))
            elif step["kind"] in ("command", "agent"):
                return where, _Pending(step, args_of(step))
            elif step["kind"] == "group":
                pending = open_group(step)
                if pending.waiting:
                    return where, pending
                where = grade_group(pending)
            elif step["kind"] == "call":
                return where, _Pending(step, args_of(step), resolve_items(step))
            else:
                raise CoreError(f"step {where!r} is a {step['kind']!r} step, which the core does not run yet")
        return where, None

    def report(pending: _Pending, event: Mapping) -> str:
        """The step the walk moves to after the pending step's `outcome` event."""
        step = pending.step
        outcome = event.get("outcome")
        if outcome == EXHAUSTED:
            raise CoreError(f"step {event['step']!r} reported the reserved outcome {EXHAUSTED!r}")
        result = event.get("result", {})
        if not isinstance(result, dict):
            raise CoreError(f"result of {event['step']!r} is not an object")
        if step["kind"] == "group":
            if not isinstance(outcome, str):
                raise CoreError(f"outcome of {event['step']!r} is not a string")
            results[event["step"]] = result
            pending.outcomes[event["step"]] = outcome
            del pending.waiting[event["step"]]
            return "" if pending.waiting else grade_group(pending)
        if step["kind"] == "call":
            wanted = 1 if pending.items is None else len(pending.items)
            entries = result.get("items")
            if not isinstance(entries, list) or len(entries) != wanted:
                raise CoreError(f"call {step['id']!r} must report {wanted} entries in 'items'")
            if not all(isinstance(entry, dict) and isinstance(entry.get("end"), str) for entry in entries):
                raise CoreError(f"call {step['id']!r} reported an entry without an 'end'")
            if call_outcome([entry["end"] for entry in entries]) != outcome:
                raise CoreError(f"call {step['id']!r} outcome {outcome!r} disagrees with its ends")
        results[step["id"]] = result
        return follow(step, outcome)

    position, pending = settle(procedure["steps"][0]["id"])
    for event in events:
        if not isinstance(event, Mapping) or event.get("type") not in EVENT_TYPES:
            kind = event.get("type") if isinstance(event, Mapping) else event
            raise CoreError(f"unknown event type {kind!r}")
        if pending is None:
            raise CoreError(f"event {event['type']!r} after the run ended at {position!r}")
        name = event.get("step")
        group = pending.step["kind"] == "group"
        pending_id = pending.step["id"]
        if group and name != pending_id:
            if pending_id not in pending.entered:
                raise CoreError(f"event {event['type']!r} for {name!r} before the entered event of group {pending_id!r}")
            if not isinstance(name, str) or name not in pending.waiting:
                raise CoreError(f"event {event['type']!r} names {name!r}, which is not a waiting member of {pending_id!r}")
        elif name != pending_id:
            raise CoreError(f"event {event['type']!r} names {name!r}, pending step is {pending_id!r}")
        if event["type"] == "entered":
            if name in pending.entered:
                raise CoreError(f"step {name!r} entered twice in one visit")
            pending.entered.add(name)
            continue
        if name not in pending.entered:
            raise CoreError(f"outcome for {name!r} before its entered event")
        if group and name == pending_id:
            raise CoreError(f"outcome for group {pending_id!r}: the group follows its members")
        where = report(pending, event)
        if group and where == "":
            continue
        position, pending = settle(where)

    if pending is not None:
        step, visit = pending.step, visits[pending.step["id"]]
        if step["kind"] == "group":
            members = tuple(
                _run_step(steps[member["step"]], visits[member["step"]], pending.waiting[member["step"]])
                for member in step["members"]
                if member["step"] in pending.waiting
            )
            action: Action = RunGroup(step["id"], visit, members)
        elif step["kind"] == "call":
            action = RunCall(step["id"], visit, step["procedure"], pending.items, step.get("parallel", 1), pending.args)
        else:
            action = _run_step(step, visit, pending.args)
    elif position == "done":
        action = Done()
    else:
        stop = procedure["stops"][position]
        action = Stop(position, stop["need"], stop["reenter"])
    return Replay(action, tuple(transitions), tuple(graded))


def next_action(procedure: Mapping, inputs: Mapping[str, object], events: Sequence[Mapping]) -> Action:
    return replay(procedure, inputs, events).action
