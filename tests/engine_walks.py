"""Generated edge walks over the engine core (#1510, decision P4 of its plan).

`walk_edges` searches, breadth first, the event sequences a procedure can
produce, driving the real `engine_core.replay` for every prefix. A prefix whose
action runs a step is extended by the step's `entered` event and one `outcome`
event per outcome the checker says the step can produce; a prefix that ends in
a stop or `done` is a terminal walk. Each edge, a `(step id, outcome)` key of a
core step's `on` map, gets the first terminal walk that takes it; an edge no
terminal walk takes is reported in `Coverage.unwalked`, never dropped.

Later slices (#1517) reuse `edges`, `step_outcomes`, `walk_edges` and
`describe` to walk further step kinds.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from agent_tools.delivery import engine_core, procedure_check
from agent_tools.delivery.engine_core import CORE_KINDS, Done, RunCommand, StartSession, Stop, Transition


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
        if item["kind"] in CORE_KINDS
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
        for item in doc["steps"]
        if item["kind"] in ("command", "agent")
    }


def result_for(procedure: Mapping, step_id: str, outcome: str) -> dict:
    prefix = f"{step_id}."
    result: dict = {
        path[len(prefix) :]: path
        for item in procedure["steps"]
        for path in item.get("in", [])
        if path.startswith(prefix)
    }
    owner = next(item for item in procedure["steps"] if item["id"] == step_id)
    result[owner.get("outcome_from", "verdict") if owner["kind"] == "agent" else "verdict"] = outcome
    return result


def walk_edges(procedure: Mapping, inputs: Mapping[str, object], outcomes: Mapping[str, tuple[str, ...]]) -> Coverage:
    wanted = edges(procedure)
    found: dict[tuple[str, str], Walk] = {}
    queue: deque[tuple[dict, ...]] = deque([()])
    while queue and len(found) < len(wanted):
        events = queue.popleft()
        replayed = engine_core.replay(procedure, inputs, list(events))
        action = replayed.action
        if isinstance(action, (RunCommand, StartSession)):
            entered = {"type": "entered", "step": action.step}
            for outcome in outcomes[action.step]:
                reported = {
                    "type": "outcome",
                    "step": action.step,
                    "outcome": outcome,
                    "result": result_for(procedure, action.step, outcome),
                }
                queue.append(events + (entered, reported))
            continue
        end = "done" if isinstance(action, Done) else action.name
        for taken in replayed.transitions:
            key = (taken.step, taken.outcome)
            if key in wanted and key not in found:
                found[key] = Walk(taken, events, replayed.transitions, end)
    return Coverage(
        tuple(found[key] for key in wanted if key in found),
        tuple(key for key in wanted if key not in found),
    )


def describe(walk: Walk) -> str:
    edge = walk.edge
    reported = " ".join(f"{event['step']}={event['outcome']}" for event in walk.events if event["type"] == "outcome")
    return f"{edge.step}:{edge.outcome} -> {edge.target} | {reported} => {walk.end}"
