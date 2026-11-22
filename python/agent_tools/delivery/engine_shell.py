"""The engine's shell: `engine deliver` runs or continues command steps (#1512).

`deliver(issue, procedures_dir)` is the imperative half over the pure core: it
refuses what it cannot run before anything is changed, creates the run directory
(or finds the issue's open run), then loops (replay the run's events through
`engine_core.replay`, act on the next action, record it) until the walk is `Done`
or a `Stop`.

Every refusal raises `Refused`, before a run directory exists and before any
process starts: the project contract must resolve from the current directory; a
held run lock answers `EXIT_RUNNING` first; the procedure must pass
`procedure_check.check_directory` against the platform declarations plus every
project command, hold only `command` and `decide` steps, and no input
but `issue` (a mutating command step needs its `check`, which the checker requires). A new
run checks `<procedures_dir>/deliver.json`, and the same checks run again on the run's
staged copy, which is the copy the loop reads (`<run>/procedure/deliver.json`).

An outcome the step's `on` does not map is a `Fault`. A run ends with `run_done`
or `stop_reached`.

Single writer: under the issue's creation lock the shell takes `<run>/lock`, an
exclusive `flock` held until `deliver` returns. The probe for a held run lock and
every lock taking (a new run's and a continued run's renewal) happen under the
creation lock, so no probe reads a lock file between a lock and its write. A run
whose lock is held makes the call exit `EXIT_RUNNING`.

Continuing: the issue's runs that are not done are found under the creation lock.
Two or more are refused, naming them. One is continued on its own procedure copy
(`procedures_dir` is not read) with the inputs of its `run.json`: a visit whose
result is stored with its outcome but lacks its grading or its transition (either may
be the one a kill left) is first completed from the stored outcome; unless the walk is already `Done`, `engine_core.reentry` (given the
current repository head) names the step to re-enter and a `run_continued` event
records it; the loop then runs as for a new run. A mutating command step's `check`
runs first on every visit that replays one a continue discarded (`RunCommand.recheck`):
the outcome `absent` runs the command, any other outcome stands for it, its document
stored as the visit's result. The keep-alive before a mutating step is not run yet
(issue 1518). A `run_continued` carries no
`head`; a `result_stored` of a step that holds `head` carries the repository head
only when it is the same before and after the step's process. None are open: a
new run is created.

Exit codes: `engine.py` lists them; `Fault` and `Refused` print nothing on stdout.
"""

from __future__ import annotations

import fcntl
import json
import os
import socket
import subprocess
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
EXIT_RUNNING = 4
LOCK_NAME = "lock"
ENTRY = "deliver"
SUPPLIED_INPUTS = ("issue",)
RUNNABLE_KINDS = ("command", "decide")
ABSENT = "absent"
REPOSITORY_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                  "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE",
                  "GIT_PREFIX", "GIT_IMPLICIT_WORK_TREE")
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
    for name in procedure["inputs"]:
        if name not in SUPPLIED_INPUTS:
            raise Refused(f"input {name} is not supplied by the engine")


def core_events(run_dir: Path, ledger: list[dict]) -> list[dict]:
    """The core's events for a run's ledger events; every other ledger event is skipped."""
    heads = {(e["step"], e["visit"]): e for e in ledger if e["event"] == "result_stored"}
    stored = {key: e["result"] for key, e in heads.items()}
    events: list[dict] = []
    for event in ledger:
        if event["event"] == "step_entered":
            events.append({"type": "entered", "step": event["step"]})
        elif event["event"] == "run_continued":
            events.append({"type": "continued", "step": event.get("step"),
                           "visit": event.get("visit")})
        elif event["event"] == "outcome_graded":
            relative = stored[(event["step"], event["visit"])]
            outcome = {"type": "outcome", "step": event["step"],
                       "outcome": event["outcome"], "result": _load(run_dir / relative)}
            if "head" in heads[(event["step"], event["visit"])]:
                outcome["head"] = heads[(event["step"], event["visit"])]["head"]
            events.append(outcome)
    return events


def read_head(root: str) -> str | None:
    """The full commit id `HEAD` names in `root`, or None when it cannot be read.

    The repository is the one `root` is in: a variable that selects another is not passed on.
    """
    environ = {key: value for key, value in os.environ.items() if key not in REPOSITORY_ENV}
    try:
        done = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "HEAD"], cwd=root, env=environ,
                              stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    head = done.stdout.strip()
    return head if done.returncode == 0 and engine_ledger.HEAD_RE.fullmatch(head) else None


def _resolve() -> tuple[dict, CommandTable]:
    try:
        snapshot = resolve_project.resolve(None)
    except resolve_project.ContractError as error:
        raise Refused(f"{error.code}: {error.repair_id}") from error
    try:
        return snapshot, CommandTable.from_snapshot(snapshot)
    except procedure_check.DeclarationError as error:
        raise Refused(str(error)) from error


def check_declarations() -> dict[str, procedure_check.CommandDeclaration | None]:
    """The declarations `engine check` checks against: `engine deliver`'s inside an onboarded project."""
    try:
        snapshot = resolve_project.resolve(None)
    except resolve_project.ContractError as error:
        if error.code == "not_onboarded":
            return procedure_check.load_commands()
        raise Refused(f"{error.code}: {error.repair_id}") from error
    return CommandTable.from_snapshot(snapshot).declarations()


def _validate(directory: Path, table: CommandTable) -> dict:
    """The entry procedure of `directory`, checked and runnable, or `Refused`."""
    if not directory.is_dir() or not (directory / f"{ENTRY}.json").is_file():
        raise Refused(f"no {ENTRY}.json in the procedures directory {directory}")
    try:
        result = procedure_check.check_directory(directory, table.declarations())
    except (ValueError, OSError) as error:
        raise Refused(str(error)) from error
    if result.refusals:
        first = result.refusals[0]
        raise Refused(f"procedure {first.procedure}, step {first.step}: "
                      f"{first.defect}, {first.detail}")
    try:
        procedure = _load(directory / f"{ENTRY}.json")
    except (ValueError, OSError) as error:
        raise Refused(str(error)) from error
    _refuse_unrunnable(procedure)
    return procedure


def creation_lock_path(root: Path, issue: int) -> Path:
    return Path(root) / f".{issue}.deliver.lock"


def lock_holder(run_dir: Path) -> dict | None:
    """The `{"pid", "started"}` of the process holding `run_dir/lock`, or None (never creates it)."""
    try:
        descriptor = os.open(Path(run_dir) / LOCK_NAME, os.O_RDONLY)
    except FileNotFoundError:
        return None
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            with os.fdopen(os.dup(descriptor), encoding="utf-8") as handle:
                document = json.load(handle)
            return {"pid": document["pid"], "started": document["started"]}
        return None
    finally:
        os.close(descriptor)


def _take_run_lock(run_dir: Path, at: str) -> int:
    descriptor = os.open(run_dir / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(descriptor, 0)
        os.write(descriptor, json.dumps({"pid": os.getpid(), "started": at},
                                        sort_keys=True, separators=(",", ":")).encode("utf-8"))
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _running(runs: list[Path], issue: int) -> tuple[int, dict] | None:
    """The `EXIT_RUNNING` answer when a lock of any of `runs` is held, else None."""
    for existing in runs:
        holder = lock_holder(existing)
        if holder is not None:
            return EXIT_RUNNING, {
                "detail": f"The {ENTRY} procedure of issue {issue} is already running "
                          f"as process {holder['pid']}.",
                "end": None, "need": None,
                "process": {"pid": holder["pid"], "started": holder["started"]},
                "run": existing.name}
    return None


def _open_runs(runs: list[Path]) -> list[Path]:
    return [existing for existing in runs
            if not engine_ledger.fold(
                engine_ledger.read_run(existing),
                engine_ledger.replay(existing / "events.jsonl"), engine_ledger.process_alive).done]


def deliver(issue: int, procedures_dir: Path) -> tuple[int, dict]:
    procedures_dir = Path(procedures_dir)
    snapshot, table = _resolve()
    project = snapshot["project"]["id"]
    held: list[int] = []
    continued = False

    def stage(staged: Path) -> None:
        # The copy that runs is the copy checked; the lock is held before the run is visible.
        if _validate(staged / "procedure", table)["inputs"] != procedure["inputs"]:
            raise Refused(f"the {ENTRY} procedure changed while its run was created")
        held.append(_take_run_lock(staged, _now()))

    try:
        creation = _lock_creation(issue)
        try:
            # Run ids order only to the second, so no one run is the newest: every
            # run of the issue is checked, a held lock before an unfinished run.
            runs = engine_ledger.find_runs(engine_ledger.runs_root(), issue, project)
            running = _running(runs, issue)
            if running is not None:
                return running
            open_runs = _open_runs(runs)
            if len(open_runs) > 1:
                raise Refused(f"runs {', '.join(run.name for run in open_runs)} of issue "
                              f"{issue} are all open; the engine continues one run only")
            if open_runs:
                run_dir = open_runs[0]
                procedure = _validate(run_dir / "procedure", table)
                inputs = engine_ledger.read_run(run_dir)["inputs"]
                held.append(_take_run_lock(run_dir, _now()))
                continued = True
            else:
                procedure = _validate(procedures_dir, table)
                inputs = {name: issue for name in procedure["inputs"]}
                run_dir = engine_ledger.create_run(
                    project=project, issue=issue, procedure=ENTRY,
                    procedures_dir=procedures_dir,
                    platform_revision=platform_revision(os.environ),
                    host=_host(), inputs=inputs, now=datetime.now(timezone.utc),
                    before_publish=stage)
        finally:
            os.close(creation)
    except (engine_ledger.LedgerError, OSError, KeyError) as error:
        _release(held)
        raise Refused(str(error)) from error
    except BaseException:
        _release(held)
        raise
    try:
        if continued:
            _continue(run_dir, table, inputs)
        return _walk(run_dir, table, inputs)
    except (engine_ledger.LedgerError, engine_core.CoreError, UnknownCommand,
            OSError, ValueError, KeyError) as error:
        raise Fault(str(error)) from error
    finally:
        _release(held)


def _continue(run_dir: Path, table: CommandTable, inputs: dict) -> None:
    """Record where the run's next walk re-enters; a stored but ungraded visit is graded first."""
    procedure = _load(run_dir / "procedure" / f"{ENTRY}.json")
    steps = {item["id"]: item for item in procedure["steps"]}
    ledger = engine_ledger.replay(run_dir / "events.jsonl")
    entered = [e for e in ledger if e["event"] == "step_entered"]
    if entered:
        name, visit = entered[-1]["step"], entered[-1]["visit"]
        stored = [e for e in ledger if e["event"] == "result_stored"
                  and (e["step"], e["visit"]) == (name, visit) and "outcome" in e]
        here = [e for e in ledger if e["event"] in ("outcome_graded", "transition_taken")
                and (e["step"], e["visit"]) == (name, visit)]
        graded = any(e["event"] == "outcome_graded" for e in here)
        moved = any(e["event"] == "transition_taken" for e in here)
        if (stored or graded) and not (graded and moved):
            outcome = next(e["outcome"] for e in here) if graded else stored[0]["outcome"]
            _grade(run_dir, steps[name], visit, outcome, graded=graded, moved=moved)
            ledger = engine_ledger.replay(run_dir / "events.jsonl")
    events = core_events(run_dir, ledger)
    action = engine_core.replay(procedure, inputs, events).action
    if isinstance(action, engine_core.Done):
        return
    if isinstance(action, engine_core.Stop) and (not ledger or ledger[-1]["event"] != "stop_reached"):
        return  # the owner never saw this stop: the walk reports it before anything is re-entered
    point = engine_core.reentry(procedure, inputs, events, read_head(table.root))
    event = {"event": "run_continued", "at": _now(), "step": point.step}
    if point.visit is not None:
        event["visit"] = point.visit
    engine_ledger.append_event(run_dir, event)


def _lock_creation(issue: int) -> int:
    root = engine_ledger.runs_root()
    engine_ledger.make_root(root)
    descriptor = os.open(creation_lock_path(root, issue), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _release(held: list[int]) -> None:
    while held:
        os.close(held.pop())


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

    before = read_head(table.root) if step["holds"] == "head" else None
    ran = None
    if action.recheck:
        check = step["check"]
        ran = engine_commands.run(table, check["command"], check.get("subcommand"),
                                  action.args, on_start=started)
        if ran.outcome == ABSENT:
            ran = None
    if ran is None:
        ran = engine_commands.run(table, action.command, action.subcommand, action.args,
                                  on_start=started)
    after = read_head(table.root) if step["holds"] == "head" else None
    engine_ledger.store_result(run_dir, step=name, visit=visit, result=ran.result, at=_now(),
                               wall_seconds=ran.wall_seconds, turns=0, tokens=dict(NO_TOKENS),
                               spend_usd=0, head=before if before == after else None,
                               outcome=ran.outcome)
    _grade(run_dir, step, visit, ran.outcome)


def _grade(run_dir: Path, step: dict, visit: int, outcome: str, *,
           graded: bool = False, moved: bool = False) -> None:
    """Record the grading and the transition of a visit; `graded` and `moved` name the one a kill left."""
    name = step["id"]
    if outcome == engine_core.EXHAUSTED or outcome not in step["on"]:
        raise Fault(f"step {name} has no mapping for the outcome {outcome}")
    if not graded:
        engine_ledger.append_event(run_dir, {"event": "outcome_graded", "at": _now(), "step": name,
                                             "visit": visit, "outcome": outcome})
    if not moved:
        engine_ledger.append_event(run_dir, {"event": "transition_taken", "at": _now(),
                                             "step": name, "visit": visit, "outcome": outcome,
                                             "to": step["on"][outcome]})
