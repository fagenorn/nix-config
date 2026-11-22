"""The engine's shell: `engine deliver` runs a procedure of command steps (#1512).

`deliver(issue, procedures_dir)` is the imperative half over the pure core. It
refuses what it cannot run before anything exists, creates the run directory,
then loops: replay the run's events through `engine_core.replay`, act on the
next action, record what happened, until the walk is `Done` or a `Stop`.

Before a run exists (every refusal raises `Refused`, creates no run directory
and starts no process): the project contract must resolve from the current
directory; `<procedures_dir>/deliver.json` must exist; the directory must pass
`procedure_check.check_directory` against the platform declarations plus every
project command (outcomes `ok`/`failed`); then `deliver.json` must hold only
`command` and `decide` steps, no step with `mutates: true`, and no input but
`issue`.

The loop reads the run's own copy, `<run>/procedure/deliver.json`, never the
source directory. One command visit appends exactly `step_entered`,
`process_started` (absent when the command cannot start), `result_stored`,
`outcome_graded` and `transition_taken`. An outcome the step's `on` does not map
is a `Fault` with no `outcome_graded`. `decide` steps are walked by the core and
record nothing. The run ends with `run_done`, or `stop_reached` naming the step
of the last core transition.

Exit codes and the result line (one compact sorted-key JSON line on stdout for
0 and 3, nothing for 1 and 2):

- `EXIT_DONE` 0: `{"detail", "end": "done", "need": null, "run"}`;
- `EXIT_FAULT` 1: a fault during the run (`Fault`);
- `EXIT_REFUSED` 2: refused before a run exists (`Refused`);
- `EXIT_STOP` 3: `{"detail", "end": <stop name>, "need": <stop need>, "run"}`.

`detail` is one sentence ending in a full stop.
"""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.delivery import engine_commands, engine_core, engine_ledger, procedure_check
from agent_tools.delivery.engine_commands import CommandTable, UnknownCommand
from agent_tools.project_contract import resolve_project

EXIT_DONE = 0
EXIT_FAULT = 1
EXIT_REFUSED = 2
EXIT_STOP = 3
ENTRY = "deliver"
SUPPLIED_INPUTS = ("issue",)
RUNNABLE_KINDS = ("command", "decide")
NO_TOKENS = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}


class Refused(Exception):
    """The procedure or the project cannot be run; nothing was created."""


class Fault(Exception):
    """The run could not continue; its events stay as recorded."""


def platform_revision(environ: Mapping[str, str]) -> str:
    """The package directory name above `AGENT_PLATFORM_ROOT`, or `source`."""
    root = environ.get("AGENT_PLATFORM_ROOT", "")
    return Path(root).parent.parent.name if root else "source"


def _host() -> str:
    return socket.gethostname().split(".")[0] or "unknown"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"),
                          object_pairs_hook=reject_duplicate_keys,
                          parse_constant=reject_nonfinite_literal)
    if not isinstance(document, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return document


def _refuse_unrunnable(procedure: dict) -> None:
    for item in procedure["steps"]:
        if item["kind"] not in RUNNABLE_KINDS:
            raise Refused(f"step {item['id']} is a {item['kind']} step, "
                          "which the engine does not run yet")
    for item in procedure["steps"]:
        if item.get("mutates") is True:
            raise Refused(f"step {item['id']} mutates, which the engine does not run yet")
    for name in procedure["inputs"]:
        if name not in SUPPLIED_INPUTS:
            raise Refused(f"input {name} is not supplied by the engine")


def core_events(run_dir: Path, ledger: list[dict]) -> list[dict]:
    """The core's events for a run's ledger events; every other ledger event is skipped."""
    stored = {(e["step"], e["visit"]): e["result"]
              for e in ledger if e["event"] == "result_stored"}
    events: list[dict] = []
    for event in ledger:
        if event["event"] == "step_entered":
            events.append({"type": "entered", "step": event["step"]})
        elif event["event"] == "outcome_graded":
            relative = stored[(event["step"], event["visit"])]
            events.append({"type": "outcome", "step": event["step"],
                           "outcome": event["outcome"], "result": _load(run_dir / relative)})
    return events


def _prepare(procedures_dir: Path) -> tuple[dict, CommandTable]:
    try:
        snapshot = resolve_project.resolve(None)
    except resolve_project.ContractError as error:
        raise Refused(f"{error.code}: {error.repair_id}") from error
    try:
        table = CommandTable.from_snapshot(snapshot)
    except procedure_check.DeclarationError as error:
        raise Refused(str(error)) from error
    if not procedures_dir.is_dir() or not (procedures_dir / f"{ENTRY}.json").is_file():
        raise Refused(f"no {ENTRY}.json in the procedures directory {procedures_dir}")
    try:
        result = procedure_check.check_directory(procedures_dir, table.declarations())
        procedure = _load(procedures_dir / f"{ENTRY}.json")
    except (ValueError, OSError) as error:
        raise Refused(str(error)) from error
    if result.refusals:
        first = result.refusals[0]
        raise Refused(f"procedure {first.procedure}, step {first.step}: "
                      f"{first.defect}, {first.detail}")
    _refuse_unrunnable(procedure)
    return snapshot, table


def deliver(issue: int, procedures_dir: Path) -> tuple[int, dict]:
    snapshot, table = _prepare(Path(procedures_dir))
    source = _load(Path(procedures_dir) / f"{ENTRY}.json")
    inputs = {name: issue for name in source["inputs"]}
    try:
        run_dir = engine_ledger.create_run(
            project=snapshot["project"]["id"], issue=issue, procedure=ENTRY,
            procedures_dir=Path(procedures_dir), platform_revision=platform_revision(os.environ),
            host=_host(), inputs=inputs, now=datetime.now(timezone.utc))
    except (engine_ledger.LedgerError, OSError) as error:
        raise Refused(str(error)) from error
    try:
        return _walk(run_dir, table, inputs)
    except (engine_ledger.LedgerError, engine_core.CoreError, UnknownCommand,
            OSError, ValueError, KeyError) as error:
        raise Fault(str(error)) from error


def _walk(run_dir: Path, table: CommandTable, inputs: dict) -> tuple[int, dict]:
    procedure = _load(run_dir / "procedure" / f"{ENTRY}.json")
    steps = {item["id"]: item for item in procedure["steps"]}
    run_id = run_dir.name
    ran = 0
    while True:
        ledger = engine_ledger.replay(run_dir / "events.jsonl")
        walk = engine_core.replay(procedure, inputs, core_events(run_dir, ledger))
        action = walk.action
        if isinstance(action, engine_core.Done):
            engine_ledger.append_event(run_dir, {"event": "run_done", "at": _now()})
            return EXIT_DONE, {
                "detail": f"The {ENTRY} procedure reached done after {ran} command "
                          f"{'visit' if ran == 1 else 'visits'}.",
                "end": "done", "need": None, "run": run_id}
        if isinstance(action, engine_core.Stop):
            step = walk.transitions[-1].step
            engine_ledger.append_event(run_dir, {
                "event": "stop_reached", "at": _now(), "step": step,
                "stop": action.name, "need": action.need})
            return EXIT_STOP, {
                "detail": f"The {ENTRY} procedure stopped at step {step} with "
                          f"{action.name}, which needs {action.need}.",
                "end": action.name, "need": action.need, "run": run_id}
        if not isinstance(action, engine_core.RunCommand):
            raise Fault(f"step {action.step} needs a session, which the engine does not run yet")
        _visit(run_dir, table, steps[action.step], action)
        ran += 1


def _visit(run_dir: Path, table: CommandTable, step: dict,
           action: engine_core.RunCommand) -> None:
    name, visit = action.step, action.visit
    engine_ledger.append_event(run_dir, {"event": "step_entered", "at": _now(), "step": name,
                                         "visit": visit, "stage": step["stage"]})

    def started(pid: int) -> None:
        engine_ledger.append_event(run_dir, {"event": "process_started", "at": _now(),
                                             "step": name, "visit": visit, "pid": pid,
                                             "started": _now()})

    ran = engine_commands.run(table, action.command, action.subcommand, action.args,
                              on_start=started)
    engine_ledger.store_result(run_dir, step=name, visit=visit, result=ran.result, at=_now(),
                               wall_seconds=ran.wall_seconds, turns=0, tokens=dict(NO_TOKENS),
                               spend_usd=0)
    if ran.outcome == engine_core.EXHAUSTED or ran.outcome not in step["on"]:
        raise Fault(f"step {name} has no mapping for the outcome {ran.outcome}")
    engine_ledger.append_event(run_dir, {"event": "outcome_graded", "at": _now(), "step": name,
                                         "visit": visit, "outcome": ran.outcome})
    engine_ledger.append_event(run_dir, {"event": "transition_taken", "at": _now(),
                                         "step": name, "visit": visit, "outcome": ran.outcome,
                                         "to": step["on"][ran.outcome]})
