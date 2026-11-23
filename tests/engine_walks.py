"""Generated edge walks over the engine core (#1510, decision P4 of its plan).

`walk_edges` searches, breadth first, the event sequences a procedure can
produce, driving the real `engine_core.replay` for every prefix. A prefix whose
action runs a step is extended by the step's `entered` event and one `outcome`
event per outcome the checker says the step can produce, each carrying a reply
that conforms to the step's reply schema (`reply_errors` refuses one that does
not, so no edge is credited to a reply the schema rejects); a prefix that ends in
a stop or `done` is a terminal walk. Each edge, a `(step id, outcome)` key of a
core step's `on` map, gets the first terminal walk that takes it (a step mapping `out-of-bounds` is also walked through
it, with the result the shell stores for a fired bound; a walk through a fired bound is credited to an ordinary edge
only when no walk that fires none takes that edge, so it never stands in for an ordinary route but still credits an
edge reachable only after a bound, such as a recovery step); an edge no
terminal walk takes is reported in `Coverage.unwalked`, never dropped.

`no-reply` is the shell's outcome when no valid reply came back, so its event
carries the empty result `{}` the shell stores, not a sampled reply.

Later slices (#1517) reuse `edges`, `step_outcomes`, `reply_schemas`,
`walk_edges` and `describe` to walk further step kinds.
"""

from __future__ import annotations

import itertools
import json
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from agent_tools.delivery import engine_core, procedure_check
from agent_tools.delivery.engine_core import (
    CORE_KINDS,
    Done,
    RunCall,
    RunCommand,
    RunGroup,
    StartSession,
    Stop,
    Transition,
)


@dataclass(frozen=True)
class Walk:
    edge: Transition
    events: tuple[dict, ...]
    transitions: tuple[Transition, ...]
    end: str


@dataclass(frozen=True)
class Coverage:
    walks: tuple[Walk, ...]
    unwalked: tuple[tuple[str, str], ...]


def edges(procedure: Mapping) -> tuple[tuple[str, str], ...]:
    return tuple(
        (item["id"], outcome)
        for item in procedure["steps"]
        if item["kind"] in CORE_KINDS and "on" in item
        for outcome in item["on"]
    )


def step_outcomes(directory: Path, name: str) -> dict[str, tuple[str, ...]]:
    result = procedure_check.check_directory(directory, procedure_check.load_commands())
    if result.refusals:
        raise AssertionError("procedure refused:\n" + "\n".join(str(refusal) for refusal in result.refusals))
    resolved = result.resolved[name]
    doc = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
    return {
        item["id"]: procedure_check.outcomes_of(item, resolved)
        + ((procedure_check.OUT_OF_BOUNDS,) if procedure_check.OUT_OF_BOUNDS in item.get("on", {}) else ())
        for item in doc["steps"]
        if item["kind"] in ("command", "agent", "call")
    }


def reply_schemas(directory: Path, name: str) -> dict[str, dict]:
    doc = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
    return {
        item["id"]: json.loads((directory / item["reply"]).read_text(encoding="utf-8"))
        for item in doc["steps"]
        if item["kind"] == "agent"
    }


def sample(schema: Mapping) -> object:
    """A smallest value of a reply schema's subset: enum, string, integer, number, boolean, array, object."""
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema["type"]
    if kind == "object":
        return {member: sample(schema["properties"][member]) for member in schema.get("required", [])}
    if kind == "array" and "items" in schema:
        return [sample(schema["items"])]
    return {"string": "x", "integer": 0, "number": 0, "boolean": False, "array": []}[kind]


def reply_errors(schema: Mapping, value: object, where: str = "reply") -> list[str]:
    """What keeps `value` from conforming to the schema subset `sample` draws from; empty when it conforms."""
    if "enum" in schema:
        return [] if value in schema["enum"] else [f"{where}: {value!r} is not in the enum"]
    kinds = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
    kind = schema["type"]
    if not isinstance(value, kinds[kind]) or (kind in ("integer", "number") and isinstance(value, bool)):
        return [f"{where}: {value!r} is not a {kind}"]
    errors: list[str] = []
    if kind == "object":
        errors += [f"{where}.{member}: missing" for member in schema.get("required", []) if member not in value]
        for member, member_schema in schema.get("properties", {}).items():
            if member in value:
                errors += reply_errors(member_schema, value[member], f"{where}.{member}")
    if kind == "array" and "items" in schema:
        for index, item in enumerate(value):
            errors += reply_errors(schema["items"], item, f"{where}[{index}]")
    return errors


def result_for(procedure: Mapping, step_id: str, outcome: str, schemas: Mapping[str, Mapping]) -> dict:
    owner = next(item for item in procedure["steps"] if item["id"] == step_id)
    if outcome == procedure_check.OUT_OF_BOUNDS:
        return {"bound": "wall-time"}
    if owner["kind"] != "agent":
        return {"verdict": outcome}
    if outcome == procedure_check.NO_REPLY:
        return {}
    schema = schemas[step_id]
    prefix = f"{step_id}."
    result = sample(schema)
    for item in procedure["steps"]:
        for path in item.get("in", []):
            member = path[len(prefix) :]
            if path.startswith(prefix) and schema["properties"].get(member, {}).get("type") == "string":
                result[member] = path
    result[owner["outcome_from"]] = outcome
    errors = reply_errors(schema, result)
    if errors:
        raise AssertionError(f"the generated reply of {step_id!r} breaks its schema: {errors}")
    return result


RUN = "1-20261121T000000Z-aaaa"


def _entered(step: str) -> dict:
    return {"type": "entered", "step": step}


def _reported(step: str, outcome: str, result: dict) -> tuple[dict, dict]:
    return _entered(step), {"type": "outcome", "step": step, "outcome": outcome, "result": result}


def walk_edges(
    procedure: Mapping,
    inputs: Mapping[str, object],
    outcomes: Mapping[str, tuple[str, ...]],
    schemas: Mapping[str, Mapping],
) -> Coverage:
    wanted = edges(procedure)
    found: dict[tuple[str, str], Walk] = {}
    after_bound: dict[tuple[str, str], Walk] = {}
    queue: deque[tuple[dict, ...]] = deque([()])
    while queue and len(found) < len(wanted):
        events = queue.popleft()
        replayed = engine_core.replay(procedure, inputs, list(events))
        action = replayed.action
        if isinstance(action, (RunCommand, StartSession)):
            for outcome in outcomes[action.step]:
                result = result_for(procedure, action.step, outcome, schemas)
                queue.append(events + _reported(action.step, outcome, result))
            continue
        if isinstance(action, RunGroup):
            listed = [member.step for member in action.members]
            for combination in itertools.product(*(outcomes[name] for name in listed)):
                reported = tuple(
                    event
                    for name, outcome in zip(listed, combination)
                    for event in _reported(name, outcome, result_for(procedure, name, outcome, schemas))
                )
                queue.append(events + (_entered(action.step),) + reported)
            continue
        if isinstance(action, RunCall):
            entries = action.items if action.items is not None else (None,)
            for outcome in ("done",) if not entries else outcomes[action.step]:
                ends = ["done"] * len(entries) if outcome == "done" else [outcome] + ["done"] * (len(entries) - 1)
                result = {"items": [{"end": end, "item": item, "run": RUN} for end, item in zip(ends, entries)]}
                queue.append(events + _reported(action.step, outcome, result))
            continue
        end = "done" if isinstance(action, Done) else action.name
        fired = any(event.get("outcome") == procedure_check.OUT_OF_BOUNDS for event in events)
        for taken in replayed.transitions:
            key = (taken.step, taken.outcome)
            if key not in wanted or key in found:
                continue
            walk = Walk(taken, events, replayed.transitions, end)
            if fired and taken.outcome != procedure_check.OUT_OF_BOUNDS:
                after_bound.setdefault(key, walk)
            else:
                found[key] = walk
    credited = {**after_bound, **found}
    return Coverage(
        tuple(credited[key] for key in wanted if key in credited),
        tuple(key for key in wanted if key not in credited),
    )


def describe(walk: Walk) -> str:
    edge = walk.edge
    reported = " ".join(f"{event['step']}={event['outcome']}" for event in walk.events if event["type"] == "outcome")
    return f"{edge.step}:{edge.outcome} -> {edge.target} | {reported} => {walk.end}"
