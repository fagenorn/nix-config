"""The engine core: a pure function from a procedure and its events to the next action (#1510).

`replay(procedure, inputs, events)` walks a procedure that passed `engine check` and returns a `Replay`: the next
`Action` and every `Transition` taken. State is never stored; it is derived again from `events` on every call. The
core reads and writes nothing: the shell performs every side effect.

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
    An arrival is the walk reaching a `command`, `agent`, `decide`, `group` or `call` step within
    its visit bound (a group's members have none of their own); `decide` arrivals are recorded too. An action's `visit` is
    the count of every arrival of the step in the run, rewound ones included,
    so a number is never reused. Every entry of a step counts a visit. Entry `max_visits + 1` (`max_visits`
    defaults to 1) takes `on["exhausted"]` with no action and records
    `Transition(step, "exhausted", target, visit)` (every transition names the visit it left). A `decide` step grades
    `{path: value for path in in}` with `engine_graders.GRADERS[step["grader"]]`
    and follows the returned outcome; no event is involved.

Groups
    Entering a group counts a visit of the group and of every member (each member visit number is
    the member's total arrivals, never reused). A member
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
    graded. A `decide` step reads `None` for a member of a group member's result that is absent:
    no reply, a fired bound, a refusal or `exhausted` store none.

Continuing
    `continued(X, v)` rewinds the walk to the arrival of X's visit v: the visit
    counts, stored results, recorded heads and transitions return to their
    values at that arrival, which is then arrived at again under a new visit
    number without counting a visit (a `command`, `agent`, `group` or `call` step is pending and
    not entered; a `decide` step is graded again and the walk settles from its
    target). Rewinding to the pending arrival that has no `entered` event
    changes nothing. `continued(X, None)` enters X fresh and is valid only at a
    stop. A rewind owes a check for every entered arrival it discards:
    `owed[step, args]` grows by those arrivals (keyed by the step and the
    arguments resolved at the arrival), shrinks by one at each later `entered`
    event of the same step and arguments and is never restored by a snapshot;
    `RunCommand.recheck` is true exactly for a pending `command` step, or a
    waiting `command` member of a pending group, with `mutates` true whose
    `owed` for its step is above zero; a group member entered in a discarded
    group arrival is owed too. `RunCall.recheck` is true exactly for a pending
    `call` step whose `owed` is above zero: the shell then checks the first
    visit of every mutating command in the call's child runs.
    `reentry(procedure, inputs, events, head, heads, bases)` answers where a continue
    should re-enter: the earliest stale result by arrival order (`live` is
    always stale; `head` is stale when its recorded head is absent or differs
    from `head`, or, when its outcome event names a `repository`, from
    `heads[repository]` (stale if absent there; `head` is not used), and, for
    a step that names a `base`, when the recorded base `sha` is absent or differs
    from `bases[(repository, ref)]`, `ref` being the recorded base's; `run`
    never; only a step's latest outcome is judged), else the
    pending step, else the stop's `reenter` step with its latest arrival's visit
    (None when never reached); a run at a stop declared `pinned` skips the stale rule and
    re-enters at the stop's `reenter` step with an empty `stale` (the stop comes after an effect no
    earlier step may redo, such as a merge). `stale` lists every stale step in arrival order; a stale
    group member names its group and the group's visit, once.

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
when the walk reaches the step (a decide's read of a group member's result excepted); entry `max_visits + 2` of a step (a loop through
`exhausted`); an `each` that is not a list or holds an item that is not a string
or an integer; a call outcome that disagrees with its ends or a call result
without one entry per item; a group member that is a `call` step; a `continued`
after `done`, naming no step of the procedure or no step at all, naming an
arrival the current walk lacks, or with no visit while a step is pending;
`reentry` on a run that reached `done`.

Later slices: waits.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agent_tools.delivery import engine_graders

EXHAUSTED = "exhausted"
EVENT_TYPES = ("entered", "outcome", "continued")
CORE_KINDS = ("command", "agent", "decide", "group", "call")


class CoreError(ValueError):
    """The procedure, inputs and events do not describe a walk of the core.

    `graded` holds the group grades the walk reached before it raised, so the shell can still record them.
    """

    graded: tuple["Graded", ...] = ()


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
    recheck: bool = False


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
    visit: int = field(default=0, compare=False)  # the step's visit number the transition left


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


def _run_step(step: Mapping, visit: int, args: tuple[tuple[str, object], ...],
              recheck: bool = False) -> RunCommand | StartSession:
    if step["kind"] == "command":
        return RunCommand(step["id"], visit, step["command"], step.get("subcommand"), args, recheck)
    return StartSession(step["id"], visit, step["role"], step["prompt"], step["reply"], args)




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
    args: tuple[tuple[str, object], ...] = ()
    entered: bool = False
    members: list[tuple[str, tuple[tuple[str, object], ...]]] = field(default_factory=list)


@dataclass
class _Walk:
    position: str
    pending: _Pending | None
    transitions: list[Transition]
    arrivals: list[_Arrival]
    produced: dict[str, tuple[int, int, object, object, object]]
    total: dict[str, int]
    owed: dict[tuple[str, str], int] = field(default_factory=dict)


def _owed_key(step: str, args: tuple[tuple[str, object], ...]) -> tuple[str, str]:
    return step, repr(args)


def _owes(step: Mapping, owed: Mapping[tuple[str, str], int]) -> bool:
    """Whether `step` is a mutating command that a rewind owes a check for."""
    return step["kind"] == "command" and step.get("mutates") is True and any(
        count > 0 and name == step["id"] for (name, _), count in owed.items())


def _walk(procedure: Mapping, inputs: Mapping[str, object], events: Sequence[Mapping],
          graded: list[Graded]) -> _Walk:
    steps = {item["id"]: item for item in procedure["steps"]}
    visits: dict[str, int] = {}
    total: dict[str, int] = {}
    results: dict[str, dict] = {}
    produced: dict[str, tuple[int, int, object, object, object]] = {}
    owed: dict[tuple[str, str], int] = {}
    transitions: list[Transition] = []
    arrivals: list[_Arrival] = []
    members = {member["step"] for item in procedure["steps"] if item["kind"] == "group"
               for member in item["members"]}

    def value(path: str) -> object:
        source, _, member = path.partition(".")
        table = inputs if source == "run" else results.get(source, {})
        if member not in table:
            raise CoreError(f"no value for {path!r}")
        return table[member]

    def absent_ok(path: str) -> object:
        source, _, member = path.partition(".")
        if source in members and member not in results.get(source, {}):
            return None
        return value(path)

    def follow(step: Mapping, outcome: str, visit: int) -> str:
        target = step["on"].get(outcome) if isinstance(outcome, str) else None
        if target is None:
            raise CoreError(f"step {step['id']!r} does not map outcome {outcome!r}")
        transitions.append(Transition(step["id"], outcome, target, visit))
        return target

    def args_of(step: Mapping) -> tuple[tuple[str, object], ...]:
        return tuple((path, value(path)) for path in step.get("in", []))

    def grade_decide(step: Mapping) -> str:
        grader = engine_graders.GRADERS[step["grader"]]
        outcome = grader.grade({path: absent_ok(path) for path in step.get("in", [])})
        results[step["id"]] = {"verdict": outcome}
        return outcome

    def grade_group(pending: _Pending) -> str:
        step = pending.step
        every = all(pending.outcomes[member["step"]] in member["pass"] for member in step["members"])
        outcome = "pass" if every else "blocked"
        visit = total[step["id"]]
        target = follow(step, outcome, visit)
        graded.append(Graded(step["id"], visit, outcome, target))
        return target

    def open_group(step: dict, args: tuple[tuple[str, object], ...]) -> _Pending:
        pending = _Pending(step, args)
        for member in step["members"]:
            owner = steps[member["step"]]
            name = owner["id"]
            visits[name] = visits.get(name, 0) + 1
            total[name] = total.get(name, 0) + 1
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
            total[where] = total.get(where, 0) + 1
            if visits[where] > bound:
                where = follow(step, EXHAUSTED, total[where])
                continue
            if step["kind"] not in CORE_KINDS:
                raise CoreError(f"step {where!r} is a {step['kind']!r} step, which the core does not run yet")
            snapshot = (dict(visits), dict(results), dict(produced), len(transitions))
            if step["kind"] == "decide":
                arrivals.append(_Arrival(where, total[where], snapshot))
                where = follow(step, grade_decide(step), total[where])
                continue
            args = args_of(step)
            arrivals.append(_Arrival(where, total[where], snapshot, args))
            if step["kind"] == "group":
                pending = open_group(step, args)
                if pending.waiting:
                    return where, pending
                where = grade_group(pending)
            elif step["kind"] == "call":
                return where, _Pending(step, args, resolve_items(step))
            else:
                return where, _Pending(step, args)
        return where, None

    def report(pending: _Pending, event: Mapping, current: _Arrival) -> str:
        """The step the walk moves to after the pending step's `outcome` event."""
        step = pending.step
        name = event["step"]
        outcome = event.get("outcome")
        if outcome == EXHAUSTED:
            raise CoreError(f"step {name!r} reported the reserved outcome {EXHAUSTED!r}")
        result = event.get("result", {})
        if not isinstance(result, dict):
            raise CoreError(f"result of {name!r} is not an object")
        if step["kind"] == "group":
            if not isinstance(outcome, str):
                raise CoreError(f"outcome of {name!r} is not a string")
            results[name] = result
            produced[name] = (len(arrivals) - 1, total[name], event.get("head"), event.get("repository"),
                              event.get("base"))
            pending.outcomes[name] = outcome
            del pending.waiting[name]
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
        produced[step["id"]] = (len(arrivals) - 1, current.visit, event.get("head"), event.get("repository"),
                                event.get("base"))
        return follow(step, outcome, current.visit)

    def rewind(arrival: _Arrival) -> tuple[str, _Pending | None]:
        index = arrivals.index(arrival)
        for later in arrivals[index:]:
            if later.entered:
                key = _owed_key(later.step, later.args)
                owed[key] = owed.get(key, 0) + 1
            for member, args in later.members:
                key = _owed_key(member, args)
                owed[key] = owed.get(key, 0) + 1
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

    def continue_at(event: Mapping, position: str, pending: _Pending | None) -> tuple[str, _Pending | None]:
        if pending is None and position == "done":
            raise CoreError("event 'continued' after the run finished")
        step_id, visit = event.get("step"), event.get("visit")
        if not isinstance(step_id, str) or step_id not in steps:
            raise CoreError(f"continued names {step_id!r}, which is no step of the procedure")
        if visit is None:
            if pending is not None:
                raise CoreError(f"continued without a visit while {pending.step['id']!r} is pending")
            return settle(step_id)
        arrival = next((a for a in arrivals if (a.step, a.visit) == (step_id, visit)), None)
        if isinstance(visit, bool):
            arrival = None
        if arrival is None:
            raise CoreError(f"continued to {step_id!r} visit {visit!r}, which the walk never reached")
        if pending is not None and arrival is arrivals[-1] and not arrival.entered:
            return position, pending
        return rewind(arrival)

    position, pending = settle(procedure["steps"][0]["id"])
    for event in events:
        if not isinstance(event, Mapping) or event.get("type") not in EVENT_TYPES:
            kind = event.get("type") if isinstance(event, Mapping) else event
            raise CoreError(f"unknown event type {kind!r}")
        if event["type"] == "continued":
            position, pending = continue_at(event, position, pending)
            continue
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
        current = arrivals[-1]
        if event["type"] == "entered":
            if name in pending.entered:
                raise CoreError(f"step {name!r} entered twice in one visit")
            pending.entered.add(name)
            if name == pending_id:
                current.entered = True
                key = _owed_key(current.step, current.args)
            else:
                current.members.append((name, pending.waiting[name]))
                key = _owed_key(name, pending.waiting[name])
            if owed.get(key, 0) > 0:
                owed[key] -= 1
            continue
        if name not in pending.entered:
            raise CoreError(f"outcome for {name!r} before its entered event")
        if group and name == pending_id:
            raise CoreError(f"outcome for group {pending_id!r}: the group follows its members")
        where = report(pending, event, current)
        if group and where == "":
            continue
        position, pending = settle(where)

    return _Walk(position, pending, transitions, arrivals, produced, total, owed)


def replay(procedure: Mapping, inputs: Mapping[str, object], events: Sequence[Mapping]) -> Replay:
    graded: list[Graded] = []
    try:
        walk = _walk(procedure, inputs, events, graded)
    except CoreError as error:
        error.graded = tuple(graded)
        raise
    steps = {item["id"]: item for item in procedure["steps"]}
    transitions, pending = tuple(walk.transitions), walk.pending
    if pending is not None:
        step, visit = pending.step, walk.arrivals[-1].visit
        if step["kind"] == "group":
            members = tuple(
                _run_step(steps[member["step"]], walk.total[member["step"]], pending.waiting[member["step"]],
                          _owes(steps[member["step"]], walk.owed))
                for member in step["members"]
                if member["step"] in pending.waiting
            )
            action: Action = RunGroup(step["id"], visit, members)
        elif step["kind"] == "call":
            owes = any(count > 0 and name == step["id"] for (name, _), count in walk.owed.items())
            action = RunCall(step["id"], visit, step["procedure"], pending.items, step.get("parallel", 1),
                             pending.args, owes)
        else:
            action = _run_step(step, visit, pending.args, _owes(step, walk.owed))
    elif walk.position == "done":
        action = Done()
    else:
        stop = procedure["stops"][walk.position]
        action = Stop(walk.position, stop["need"], stop["reenter"])
    return Replay(action, transitions, tuple(graded))


def reentry(
    procedure: Mapping, inputs: Mapping[str, object], events: Sequence[Mapping], head: str | None,
    heads: Mapping[str, str | None] | None = None,
    bases: Mapping[tuple[str, str], str | None] | None = None,
) -> Reentry:
    walk = _walk(procedure, inputs, events, [])
    if walk.pending is None and walk.position == "done":
        raise CoreError("a run that reached done has no re-entry point")
    steps = {item["id"]: item for item in procedure["steps"]}
    stale: list[tuple[str, int]] = []
    for step_id, (index, _visit, recorded, repository, base) in sorted(
        walk.produced.items(), key=lambda item: (item[1][0], item[1][1], item[0])
    ):
        holds = steps[step_id]["holds"]
        current = head if repository is None else (heads or {}).get(repository)
        moved = steps[step_id].get("base") is not None and (
            not isinstance(base, dict) or base["sha"] != (bases or {}).get((repository, base["ref"])))
        if holds == "live" or (holds == "head" and (current is None or recorded != current or moved)):
            arrival = walk.arrivals[index]
            if (arrival.step, arrival.visit) not in stale:
                stale.append((arrival.step, arrival.visit))
    names = tuple(name for name, _ in stale)
    pinned = walk.pending is None and bool(procedure["stops"][walk.position].get("pinned"))
    if stale and not pinned:
        return Reentry(stale[0][0], stale[0][1], names)
    if walk.pending is not None:
        return Reentry(walk.pending.step["id"], walk.arrivals[-1].visit, names)
    target = procedure["stops"][walk.position]["reenter"]
    latest = next((a.visit for a in reversed(walk.arrivals) if a.step == target), None)
    return Reentry(target, latest, () if pinned else names)


def next_action(procedure: Mapping, inputs: Mapping[str, object], events: Sequence[Mapping]) -> Action:
    return replay(procedure, inputs, events).action
