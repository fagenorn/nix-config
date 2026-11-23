"""The engine's shell: `engine deliver` runs a procedure of command, agent and decide steps (#1512, #1514).

`deliver(issue, procedures_dir)` is the imperative half over the pure core: it
refuses what it cannot run before anything exists, creates the run directory,
then loops (replay the run's events through `engine_core.replay`, act on the
next action, record it) until the walk is `Done` or a `Stop`.

Every refusal raises `Refused`, before a run directory exists and before any
process starts: the project contract must resolve from the current directory; a
held run lock answers `EXIT_RUNNING` first; the host's settings must name the lifecycle guard as the one
unconditional Bash hook with no hook switch on (`engine_guard.locate`), checked after that answer;
`<procedures_dir>/deliver.json` must pass `procedure_check.check_directory` against the platform
declarations plus every project command, hold only `command`, `agent` and `decide` steps, a
`mutates: true` step only as a `command` step, and no input but `issue`, and every agent step's role
file must read (`engine_session.read_role`), and the host declaration must admit the engine route (else the
refusal starts with its reason code), checked after the guard. The same checks run again on the run's
staged copy, which is the copy the loop reads (`<run>/procedure/deliver.json`).

An agent step runs as one headless session (`engine_session`) in the project
root: its role body, rendered prompt and a session record are stored under the
run's `sessions/`, the session holds one of the engine route's agent slots (`engine_slots`) from before
`session_starting` to the end of its last launch, waiting with `wait_started` and `wait_ended` (`host-slot`)
when none is free, `session_starting` is on disk before the process is spawned,
and a session that ends normally is graded only by the `outcome_from` member of its
structured reply, so neither the prose nor the exit code selects an outcome. A reading with no
usable reply (none, or one that breaks the schema) is a miss when `engine_session.is_miss` accepts
its stdout: the same session is then resumed once (`session_resuming`, `--resume <session>`,
`REASK_PROMPT`) and a second miss grades `no-reply` with `{}` stored, its measurements the sums of
both launches. Any other reading with no usable reply is a `Fault`, and so is a session denied a
shell command, whose reply may rest on a check it never ran. Before each launch, the resumes included,
the host's settings are read again and a lifecycle guard hook that is gone is a `Fault`. A session ended
by a bound is graded `out-of-bounds` before any fault is considered: the bounds are a turn or spend cap
(`engine_session.CAP_SUBTYPES`) and the wall bound, the engine's own clock per role
(`engine_session.bounds`), past which `engine_session.launch` ends the session's group. Its stored
result names the bound (`wall-time` for the wall bound), its measurements are recorded, and the
engine never resumes or retries the step.

A command step runs within its command's wall bound (`CommandTable.wall_seconds`), counted from the
spawn: past it the step's group is killed, its stored result is `{"bound": "wall-time"}` and it is
graded `out-of-bounds`. A command's stderr is forwarded to the engine's own. A command that prints
the verdict `out-of-bounds` is a `Fault`: only the engine grades a fired bound.

A session that hit a usage limit does not end the visit: the shell opens a `usage-limit` wait, then
launches the same session again (`--resume`, the same prompt, `session_resuming`) in the same visit, so
the visit is counted once. Each launch passes `CLAUDE_ACCOUNT_ANSWER`, the file the launcher answers in
(`engine_session.read_answer`), and a launch whose process started records `session_answered`. An
inherited `CLAUDE_ACCOUNT` goes to every launch before the first limit and is removed from every launch
after it, so the launcher chooses the next account. The wait ends right before the result is stored. The
run ends at the engine's own stop `quota-wait` (need `retry`, exit 3, the wait left open) when the launcher
answers that every account is out (the wait then carries the resume time), or when an account that
already hit a limit in this visit hits one again; the engine opens no connection of its own for this.
Any other API error is retried once in the visit, after `API_RETRY_SECONDS`, the same way (`--resume`, no new
visit); a usage limit never consumes that retry and an API error never opens a wait, and a retried API error
leaves an open `usage-limit` wait open, so every `quota-wait` stop has one open. A second API error in the visit
is the outcome `no-reply`: the stored result is `{}` and the step's `on` must map it, else the run is a `Fault`.

Before each visit of a `mutates: true` command step, in a procedure naming a `keep_alive`,
the shell runs it (`KEEP_ALIVE_SECONDS`), recording a `keep_alive_ran` per call. It renews
only on the verdict `renewed` with exit 0; an `error` whose `transient` is the boolean
`true` is called once more. Otherwise the run ends at `claim-lost` without entering the
step, its detail carrying the verdict and what the call printed on stdout and stderr.

Before every command it runs, keep-alive included, the shell has the lifecycle guard judge it, and a
refusal is the outcome `refused` (issue 1515).

An outcome the step's `on` does not map is a `Fault` (a fired bound is graded first). A run ends with `run_done` or `stop_reached`.

Once the run exists and before its first step, `engine_housekeeping.housekeep` prunes the history and
sweeps expired run directories; a run that ends in done or a stop then appends one history line
(`_record_history`) before its lock is released. Neither changes the call's code or result line.

Single writer: under the issue's creation lock the shell takes `<run>/lock`, an exclusive `flock` held
until `deliver` returns. A run whose lock is held makes the call exit `EXIT_RUNNING`; a run not done and
not locked is refused (continuing a run is a later slice).

A stop request (`engine stop`, `engine_stop`) is the file `<run>/stop-request` naming this lock's holder
(`pid` and `started`). While a step's process runs (a command, an agent session or the keep-alive),
the shell polls it; a request for this holder ends that process's group, appends `stop_reached` named
`stopped-by-request` (need `retry`) for the pending step, then removes the file, and the call exits
`EXIT_STOP` with the run left open. The cut visit records no result, grade or transition.
The API-error retry pause is polled too: a request in it ends the visit at once, with no resume.
A request is published (`request_stop`) under one lock with the engine's recording of every end of
the run (`run_done` and each stop) and removal of the file, and the engine checks for a pending
request under that lock, so a request that was accepted is honored and none outlives the run.

Exit codes: `engine.py` lists them; `Fault` and `Refused` print nothing on stdout.
"""

from __future__ import annotations

import fcntl
import json
import os
import socket
import sys
import tempfile
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.delivery import (
    engine_commands, engine_core, engine_guard, engine_housekeeping, engine_ledger, engine_reply,
    engine_session, engine_slots, engine_stop, host_admission, procedure_check,
)
from agent_tools.delivery.engine_commands import CommandTable, UnknownCommand
from agent_tools.delivery.engine_ledger import creation_lock_path
from agent_tools.project_contract import resolve_project

EXIT_DONE = 0
EXIT_FAULT = 1
EXIT_REFUSED = 2
EXIT_STOP = 3
EXIT_RUNNING = 4
KEEP_ALIVE_SECONDS = 1200
API_RETRY_SECONDS = 30
LOCK_NAME = "lock"
ENTRY = "deliver"
SUPPLIED_INPUTS = ("issue",)
RUNNABLE_KINDS = ("command", "agent", "decide")
QUOTA_NEED = "retry"
NO_TOKENS = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}


class Refused(Exception):
    """The procedure or the project cannot be run; nothing was created."""


class Fault(Exception):
    """The run could not continue; its events stay as recorded."""


def platform_revision(environ: Mapping[str, str]) -> str:
    """The package directory name above `AGENT_PLATFORM_ROOT`, or `source`."""
    root = environ.get("AGENT_PLATFORM_ROOT", "")
    return Path(root).parent.parent.name if root else "source"


def _guard() -> engine_guard.Hook | engine_guard.Unavailable:
    return engine_guard.locate(engine_guard.settings_path(os.environ))


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
        if item.get("mutates") is True and item["kind"] != "command":
            raise Refused(f"step {item['id']} is a {item['kind']} step marked mutates, and the "
                          "engine renews the claim only before a command step")
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


def _resolve() -> tuple[dict, CommandTable]:
    try:
        snapshot = resolve_project.resolve(None)
    except resolve_project.ContractError as error:
        raise Refused(f"{error.code}: {error.repair_id}") from error
    try:
        return snapshot, CommandTable.from_snapshot(snapshot)
    except procedure_check.DeclarationError as error:
        raise Refused(str(error)) from error


def _admitted() -> int:
    try:
        return engine_slots.declared_slots()
    except host_admission.DeclarationError as error:
        raise Refused(f"{error.reason_code}: the host declaration does not admit the "
                      f"{host_admission.ENGINE_ROUTE} route, so no run starts") from error


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
    for item in procedure["steps"]:
        if item["kind"] == "agent":
            try:
                engine_session.read_role(engine_session.roles_dir(os.environ), item["role"])
            except engine_session.RoleError as error:
                raise Refused(str(error)) from error
    return procedure


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
            try:  # a holder that wrote no document (a housekeeping sweep) is no deliver process
                with os.fdopen(os.dup(descriptor), encoding="utf-8") as handle:
                    document = json.load(handle)
                return {"pid": document["pid"], "started": document["started"]}
            except (ValueError, KeyError, TypeError):
                return None
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


def deliver(issue: int, procedures_dir: Path, *, clock: Callable[[], datetime] | None = None,
            tracker: engine_housekeeping.Tracker | None = None) -> tuple[int, dict]:
    procedures_dir = Path(procedures_dir)
    snapshot, table = _resolve()
    project = snapshot["project"]["id"]
    clock = clock or (lambda: datetime.now(timezone.utc))
    identity = engine_housekeeping.tracker_identity(snapshot["bindings"]["tracker"])
    tracker_factory = ((lambda: tracker) if tracker is not None else
                       (lambda: engine_housekeeping.default_tracker(
                           snapshot["bindings"]["tracker"], snapshot["project"]["root"])))
    try:
        running = _running(engine_ledger.find_runs(engine_ledger.runs_root(), issue, project),
                           issue)
    except (engine_ledger.LedgerError, OSError, KeyError) as error:
        raise Refused(str(error)) from error
    if running is not None:
        return running
    guard = _guard()
    if isinstance(guard, engine_guard.Unavailable):
        raise Refused(f"the host's settings load no lifecycle guard hook, so no run starts: "
                      f"{guard.reason}")
    slots = _admitted()
    procedure = _validate(procedures_dir, table)
    inputs = {name: issue for name in procedure["inputs"]}
    holder = {"pid": os.getpid(), "started": _now()}
    held: list[int] = []

    def stage(staged: Path) -> None:
        # The copy that runs is the copy checked; the lock is held before the run is visible.
        if _validate(staged / "procedure", table)["inputs"] != procedure["inputs"]:
            raise Refused(f"the {ENTRY} procedure changed while its run was created")
        held.append(_take_run_lock(staged, holder["started"]))

    try:
        creation = _lock_creation(issue)
        try:
            # Run ids order only to the second, so no one run is the newest: every
            # run of the issue is checked, a held lock before an unfinished run.
            runs = engine_ledger.find_runs(engine_ledger.runs_root(), issue, project)
            running = _running(runs, issue)
            if running is not None:
                return running
            for existing in runs:
                state = engine_ledger.fold(
                    engine_ledger.read_run(existing),
                    engine_ledger.replay(existing / "events.jsonl"), engine_ledger.process_alive)
                if not state.done:
                    raise Refused(f"run {existing.name} is not done, and continuing a run is a "
                                  "later slice of the engine")
            run_dir = engine_ledger.create_run(
                project=project, issue=issue, procedure=ENTRY,
                procedures_dir=procedures_dir,
                platform_revision=platform_revision(os.environ),
                host=_host(), inputs=inputs, now=datetime.now(timezone.utc),
                tracker=identity, before_publish=stage)
        finally:
            os.close(creation)
    except (engine_ledger.LedgerError, OSError, KeyError) as error:
        _release(held)
        raise Refused(str(error)) from error
    except BaseException:
        _release(held)
        raise
    try:
        engine_housekeeping.housekeep(project=project, run=run_dir.name, clock=clock,
                                      tracker=tracker_factory, identity=identity)
        code, line = _walk(run_dir, table, inputs, holder, slots)
        if code in (EXIT_DONE, EXIT_STOP):
            _record_history(run_dir, clock)
        return code, line
    except (engine_ledger.LedgerError, engine_core.CoreError, UnknownCommand,
            OSError, ValueError, KeyError) as error:
        raise Fault(str(error)) from error
    finally:
        _release(held)


def _record_history(run_dir: Path, clock: Callable[[], datetime]) -> None:
    """Append the run's history line; a failure is one stderr line, never the delivery's result."""
    try:
        state = engine_ledger.fold(engine_ledger.read_run(run_dir),
                                   engine_ledger.replay(run_dir / "events.jsonl"),
                                   lambda pid, started: False)
        engine_housekeeping.append_history(engine_housekeeping.history_line(state, clock()),
                                           engine_housekeeping.history_path())
    except Exception as error:
        sys.stderr.write(f"engine: the history line of run {run_dir.name} was not recorded: "
                         f"{type(error).__name__}: {' '.join(str(error).split())}\n")


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


def _walk(run_dir: Path, table: CommandTable, inputs: dict, holder: Mapping[str, object],
          slots: int) -> tuple[int, dict]:
    procedure = _load(run_dir / "procedure" / f"{ENTRY}.json")

    def stop() -> bool:
        return engine_stop.requested(run_dir, holder)

    steps = {item["id"]: item for item in procedure["steps"]}
    ran = 0
    while True:
        ledger = engine_ledger.replay(run_dir / "events.jsonl")
        walk = engine_core.replay(procedure, inputs, core_events(run_dir, ledger))
        _record_core_transitions(run_dir, ledger, walk)
        action = walk.action
        if isinstance(action, engine_core.Done):
            with engine_stop.publication(run_dir):  # a request is honored or published after
                if stop():
                    return _record_stop(run_dir, walk.transitions[-1].step, "", "", "", True)
                engine_ledger.append_event(run_dir, {"event": "run_done", "at": _now()})
            return EXIT_DONE, {
                "detail": f"The {ENTRY} procedure reached done after {ran} step "
                          f"{'visit' if ran == 1 else 'visits'}.",
                "end": "done", "need": None, "run": run_dir.name}
        if isinstance(action, engine_core.Stop):
            step = walk.transitions[-1].step
            return _stop(run_dir, step, action.name, action.need,
                         f"The {ENTRY} procedure stopped at step {step} with "
                         f"{action.name}, which needs {action.need}.", stop)
        if isinstance(action, engine_core.StartSession):
            try:
                stopped = _visit_session(run_dir, table.root, steps[action.step], action, stop,
                                         slots)
            except engine_stop.Stopped:
                return _stopped(run_dir, action.step)
            if stopped is not None:
                return stopped
        elif isinstance(action, engine_core.RunCommand):
            try:
                if steps[action.step].get("mutates") is True and "keep_alive" in procedure:
                    lost = _renew(run_dir, table, procedure, inputs, action, stop)
                    if lost is not None:
                        return lost
                _visit(run_dir, table, steps[action.step], action, stop)
            except engine_stop.Stopped:
                return _stopped(run_dir, action.step)
        else:
            raise Fault(f"step {action.step} needs {type(action).__name__}, "
                        "which the engine does not run yet")
        ran += 1


def _record_core_transitions(run_dir: Path, ledger: list[dict], walk: engine_core.Replay) -> None:
    """Append the `transition_taken` of each walk transition the ledger lacks, in order.

    A command visit writes its own in `_visit`; the core resolves a `decide` step and an
    exhausted entry with no command, so the ledger holds the rest of the walk's transitions here.
    """
    taken = sum(1 for event in ledger if event["event"] == "transition_taken")
    for index, transition in enumerate(walk.transitions[taken:], start=taken):
        visit = sum(1 for earlier in walk.transitions[:index + 1] if earlier.step == transition.step)
        engine_ledger.append_event(run_dir, {
            "event": "transition_taken", "at": _now(), "step": transition.step, "visit": visit,
            "outcome": transition.outcome, "to": transition.target})


def _record_stop(run_dir: Path, step: str, name: str, need: str, detail: str,
                requested: bool) -> tuple[int, dict]:
    """Record the stop, the caller holding the publication lock; `requested` says a request ended it.

    A request pending for this run is honored in place of `name`, so a request accepted late is
    never left behind; the file goes once the stop is recorded."""
    if requested:
        name, need = engine_stop.STOPPED_BY_REQUEST, engine_stop.STOP_NEED
        detail = (f"The {ENTRY} procedure stopped at step {step} on request, "
                  "which needs a retry.")
    engine_ledger.append_event(run_dir, {"event": "stop_reached", "at": _now(), "step": step,
                                         "stop": name, "need": need})
    if requested:
        engine_stop.clear(run_dir)
    return EXIT_STOP, {"detail": detail, "end": name, "need": need, "run": run_dir.name}


def _stop(run_dir: Path, step: str, name: str, need: str, detail: str,
          stop: Callable[[], bool]) -> tuple[int, dict]:
    """The stop that ends the run; recording and the request's removal are one step under the
    publication lock, so no request is published between and a pending one wins."""
    with engine_stop.publication(run_dir):
        return _record_stop(run_dir, step, name, need, detail, stop())


def _stopped(run_dir: Path, step: str) -> tuple[int, dict]:
    """The stop a request ended `step`'s process with."""
    return _stop(run_dir, step, "", "", "", lambda: True)


def request_stop(run_dir: Path) -> dict | None:
    """Publish a stop request for the holder of `run_dir`'s lock; its `{"pid", "started"}`, or None.

    None when no process holds the lock or the run already ended (`stop_reached` or `run_done`
    recorded), so a request is never left behind by an engine that has finished."""
    with engine_stop.publication(run_dir):
        holder = lock_holder(run_dir)
        if holder is None:
            return None
        events = engine_ledger.replay(run_dir / "events.jsonl")
        if events and events[-1]["event"] in ("stop_reached", "run_done"):
            return None
        engine_stop.write_request(run_dir, holder)
        return holder


def _renew(run_dir: Path, table: CommandTable, procedure: dict, inputs: dict,
           action: engine_core.RunCommand, stop: Callable[[], bool]) -> tuple[int, dict] | None:
    """None when the claim is renewed before `action`'s step, else the `claim-lost` stop."""
    keep_alive = procedure["keep_alive"]
    args = tuple((path, inputs[path.split(".", 1)[1]]) for path in keep_alive["in"])
    for attempt in (1, 2):
        ran = engine_commands.run(table, keep_alive["command"], keep_alive.get("subcommand"),
                                  args, guard=_guard(), on_start=lambda pid: None,
                                  timeout=KEEP_ALIVE_SECONDS, stop=stop)
        verdict = "failed" if ran.outcome == "renewed" and ran.exit_code != 0 else ran.outcome
        engine_ledger.append_event(run_dir, {
            "event": "keep_alive_ran", "at": _now(), "step": action.step,
            "visit": action.visit, "attempt": attempt, "verdict": verdict})
        if verdict == "renewed":
            return None
        if verdict != "error" or ran.result.get("transient") is not True:
            break
    if ran.exit_code is None:
        text = " ".join(ran.result["reason"].split())
    else:
        text = " ".join(ran.stdout.decode("utf-8", "replace").split()
                        + ran.stderr.decode("utf-8", "replace").split()) or "no output"
    need = procedure["stops"][procedure_check.CLAIM_LOST]["need"]
    return _stop(run_dir, action.step, procedure_check.CLAIM_LOST, need,
                 f"The claim was not renewed before step {action.step}, the keep-alive "
                 f"answered {verdict}: {text}.", stop)


def _graded(run_dir: Path, step: dict, visit: int, outcome: str, *, bound: bool = False) -> None:
    """Record the grade of a visit and the transition it takes.

    A reply or a printed verdict (`bound=False`) must be mapped by the step's `on`, else it is a
    `Fault` before any event. The engine's own grade of a fired bound (`bound=True`) is always
    recorded, because `core_events` reads it from `outcome_graded`, and then faults when `on`
    does not map it, with no `transition_taken`.
    """
    name = step["id"]
    unmapped = outcome == engine_core.EXHAUSTED or outcome not in step["on"]
    if unmapped and not bound:
        raise Fault(f"step {name} has no mapping for the outcome {outcome}")
    engine_ledger.append_event(run_dir, {"event": "outcome_graded", "at": _now(), "step": name,
                                         "visit": visit, "outcome": outcome})
    if unmapped:
        raise Fault(f"step {name} has no mapping for the outcome {outcome}")
    engine_ledger.append_event(run_dir, {"event": "transition_taken", "at": _now(),
                                         "step": name, "visit": visit, "outcome": outcome,
                                         "to": step["on"][outcome]})


def _visit(run_dir: Path, table: CommandTable, step: dict, action: engine_core.RunCommand,
           stop: Callable[[], bool]) -> None:
    name, visit = action.step, action.visit
    engine_ledger.append_event(run_dir, {"event": "step_entered", "at": _now(), "step": name,
                                         "visit": visit, "stage": step["stage"]})

    def started(pid: int) -> None:
        engine_ledger.append_event(run_dir, {"event": "process_started", "at": _now(),
                                             "step": name, "visit": visit, "pid": pid,
                                             "started": _now()})

    ran = engine_commands.run(table, action.command, action.subcommand, action.args,
                              guard=_guard(), on_start=started,
                              timeout=table.wall_seconds(action.command), stop=stop)
    try:
        _grade_command(run_dir, step, name, visit, ran)
    finally:  # forwarding a diagnostic never decides whether the step is graded
        _forward(ran.stderr)


def _forward(diagnostic: bytes) -> None:
    """Pass a command's stderr on to the engine's; a closed stream loses it, nothing more."""
    try:
        sys.stderr.buffer.write(diagnostic)
        sys.stderr.buffer.flush()
    except OSError:
        pass


def _grade_command(run_dir: Path, step: dict, name: str, visit: int,
                   ran: engine_commands.Ran) -> None:
    if ran.timed_out:
        engine_ledger.store_result(run_dir, step=name, visit=visit, result={"bound": "wall-time"},
                                   at=_now(), wall_seconds=ran.wall_seconds, turns=0,
                                   tokens=dict(NO_TOKENS), spend_usd=0)
        _graded(run_dir, step, visit, procedure_check.OUT_OF_BOUNDS, bound=True)
        return
    engine_ledger.store_result(run_dir, step=name, visit=visit, result=ran.result, at=_now(),
                               wall_seconds=ran.wall_seconds, turns=0, tokens=dict(NO_TOKENS),
                               spend_usd=0)
    if ran.outcome == procedure_check.OUT_OF_BOUNDS:  # only the engine grades a fired bound
        raise Fault(f"step {name} has no mapping for the outcome {ran.outcome}")
    _graded(run_dir, step, visit, ran.outcome)


def _visit_session(run_dir: Path, root: str, step: dict, action: engine_core.StartSession,
                   stop: Callable[[], bool], slots: int) -> tuple[int, dict] | None:
    """Run the step's session to its result; the `quota-wait` stop when no account can answer."""
    name, visit = action.step, action.visit
    engine_ledger.append_event(run_dir, {"event": "step_entered", "at": _now(), "step": name,
                                         "visit": visit, "stage": step["stage"]})
    role = engine_session.read_role(engine_session.roles_dir(os.environ), step["role"])
    staged = run_dir / "procedure"
    schema = _load(staged / action.reply)
    prompt = engine_session.render_prompt(
        (staged / action.prompt).read_text(encoding="utf-8"), action.args)
    session = str(uuid.uuid4())
    system = engine_ledger.store_session_file(run_dir, f"{name}.{visit}.system.md",
                                              role.body.encode("utf-8"))
    engine_ledger.store_session_file(run_dir, f"{name}.{visit}.prompt.md", prompt.encode("utf-8"))

    def waiting() -> None:
        engine_ledger.append_event(run_dir, {"event": "wait_started", "at": _now(),
                                             "wait": engine_slots.WAIT, "until": None})

    def waited() -> None:
        engine_ledger.append_event(run_dir, {"event": "wait_ended", "at": _now(),
                                             "wait": engine_slots.WAIT})

    with engine_slots.hold(run_dir, slots, on_wait=waiting, on_waited=waited):
        engine_ledger.append_event(run_dir, {
            "event": "session_starting", "at": _now(), "step": name, "visit": visit,
            "session": session, "role": role.name,
            "account": os.environ.get("CLAUDE_ACCOUNT") or "console"})
        launched, reading, stopped, no_reply = _launch_until_answered(
            run_dir, root, (name, visit, session), prompt, (role, schema, system), stop)
    if stopped is not None:
        return stopped
    wall = (launched.wall_seconds if launched.timed_out or reading.wall_seconds is None
            else reading.wall_seconds)

    def store(result: dict) -> None:
        engine_ledger.store_result(run_dir, step=name, visit=visit, result=result, at=_now(),
                                   wall_seconds=wall, turns=reading.turns, tokens=reading.tokens,
                                   spend_usd=reading.spend_usd)

    bound = (engine_session.WALL_TIME if launched.timed_out
             else engine_session.CAP_SUBTYPES.get(reading.subtype))
    if bound is not None:
        store({"bound": bound})
        _graded(run_dir, step, visit, procedure_check.OUT_OF_BOUNDS, bound=True)
        return None
    if no_reply:
        store({})
        _graded(run_dir, step, visit, procedure_check.NO_REPLY)
        return None
    reply = reading.reply
    if reply is None:
        reason = engine_session.diagnostic(launched.stderr)
        raise Fault(f"step {name} gave no structured reply, exit {launched.exit_code}"
                    + (f": {reason}" if reason else ""))
    store(reply)
    problem = engine_reply.reply_problem(schema, reply)
    if problem is not None:
        raise Fault(f"step {name} gave a reply that breaks its schema: {problem}")
    outcome = reply.get(step["outcome_from"])
    if not isinstance(outcome, str):
        raise Fault(f"step {name} has no mapping for the outcome {outcome}")
    _graded(run_dir, step, visit, outcome)
    return None


def _launch_until_answered(
        run_dir: Path, root: str, visit_of: tuple[str, int, str], prompt: str,
        launch_of: tuple[engine_session.Role, Mapping, Path], stop: Callable[[], bool],
) -> tuple[engine_session.Launched, engine_session.Reading, tuple[int, dict] | None, bool]:
    """Launch the session, again with `--resume` after each usage limit, after the first other
    API error (once, after `API_RETRY_SECONDS`) and after the first miss (once, with `REASK_PROMPT`),
    until a launch that is none of these, or a second API error or miss, whose result is returned
    with the visit's record stored and the wait ended; a miss's launch and its resume are summed in
    the result's measurements. The third member is the `quota-wait` stop (record stored, wait open)
    when no account can answer, the fourth is true for the second API error or miss, the outcome
    `no-reply`."""
    name, visit, session = visit_of
    role, schema, system = launch_of
    attempt, limited, waiting, released, retried, no_reply = 1, set(), False, False, False, False
    missed, text = False, prompt
    missed_once: tuple[engine_session.Launched, engine_session.Reading] | None = None

    def event(kind: str, **members: object) -> None:
        engine_ledger.append_event(run_dir, {"event": kind, "at": _now(), **members})

    def wait(until: str | None) -> None:
        nonlocal waiting
        if waiting:
            event("wait_ended", wait=engine_session.USAGE_LIMIT)
        event("wait_started", wait=engine_session.USAGE_LIMIT, until=until)
        waiting = True

    def record(launched: engine_session.Launched, reading: engine_session.Reading) -> None:
        _store_record(run_dir, name, visit, session, launched, reading, schema,
                      ".resume" if missed else "")

    def quota_stop(launched: engine_session.Launched, reading: engine_session.Reading,
                   detail: str) -> tuple:
        record(launched, reading)
        return launched, reading, _stop(run_dir, name, procedure_check.QUOTA_WAIT, QUOTA_NEED,
                                        detail, stop), False

    while True:
        started: list[int] = []

        def on_start(pid: int) -> None:
            started.append(pid)
            event("process_started", step=name, visit=visit, pid=pid, started=_now())

        guard = _guard()
        if isinstance(guard, engine_guard.Unavailable):
            raise Fault(f"step {name} was not launched: the host's settings no longer load the "
                        f"lifecycle guard hook: {guard.reason}")
        if attempt > 1:
            event("session_resuming", step=name, visit=visit, session=session, attempt=attempt)
        with tempfile.TemporaryDirectory() as scratch:
            answer_path = Path(scratch) / "answer.json"
            env = {**os.environ, engine_session.ANSWER_ENV: str(answer_path)}
            if released:
                env.pop("CLAUDE_ACCOUNT", None)
            launched = engine_session.launch(
                engine_session.launch_argv(role, schema, session, system, resume=attempt > 1),
                root, text, on_start=on_start, env=env,
                timeout=engine_session.bounds(role.name).wall_seconds, stop=stop)
            answer = engine_session.read_answer(answer_path)
        reading = engine_session.read_result(launched.stdout)
        if answer.all_out and launched.exit_code == engine_session.ALL_OUT_EXIT:
            wait(answer.resumes_at)
            return quota_stop(launched, reading, (
                f"Every account is out of usage; the {ENTRY} procedure waits at step {name} "
                f"until {answer.resumes_at or 'an unknown time'}."))
        account = answer.account or "unknown"
        if started:
            event("session_answered", step=name, visit=visit, session=session, attempt=attempt,
                  account=account)
        if launched.timed_out or reading.subtype in engine_session.CAP_SUBTYPES:
            break  # a bound ended the session: graded by the visit, before any fault below
        denied = next((d for d in reading.denials
                       if isinstance(d, dict) and d.get("tool_name") == "Bash"), None)
        if denied is not None:
            record(launched, reading)
            tool_input = denied.get("tool_input")
            command = tool_input.get("command") if isinstance(tool_input, dict) else None
            raise Fault(f"step {name} was denied the shell command {str(command)[:200]!r}, so "
                        f"its reply is not graded: list it in the role's tools as Bash(<prefix>:*)")
        if reading.api_failure == engine_session.API_ERROR:
            if retried:
                no_reply = True
                break
            retried, attempt = True, attempt + 1
            engine_stop.pause(API_RETRY_SECONDS, stop)
            continue
        if reading.api_failure != engine_session.USAGE_LIMIT:
            if engine_session.is_miss(reading) and _problem(schema, reading) is not None:
                if missed:
                    no_reply = True
                    break
                record(launched, reading)
                engine_ledger.store_session_file(
                    run_dir, f"{name}.{visit}.resume.prompt.md",
                    engine_session.REASK_PROMPT.encode("utf-8"))
                missed_once = (launched, reading)
                missed, text, attempt = True, engine_session.REASK_PROMPT, attempt + 1
                continue
            break
        if account in limited:
            return quota_stop(launched, reading, (
                f"Account {account} hit its usage limit twice at step {name} of the {ENTRY} "
                "procedure; the run waits for it."))
        limited.add(account)
        if not waiting:
            wait(None)
        released, attempt = True, attempt + 1
    if waiting:
        event("wait_ended", wait=engine_session.USAGE_LIMIT)
    record(launched, reading)
    if missed_once is not None:  # the miss and its resume are one result
        ran, read = missed_once
        before = read.wall_seconds if read.wall_seconds is not None else ran.wall_seconds
        launched = replace(launched, wall_seconds=launched.wall_seconds + before)
        reading = replace(
            reading, turns=reading.turns + read.turns, spend_usd=reading.spend_usd + read.spend_usd,
            wall_seconds=(launched.wall_seconds if reading.wall_seconds is None
                          else reading.wall_seconds + before),
            tokens={key: reading.tokens[key] + read.tokens[key] for key in reading.tokens})
    return launched, reading, None, no_reply


def _problem(schema: Mapping, reading: engine_session.Reading) -> str | None:
    return ("no structured_output" if reading.reply is None
            else engine_reply.reply_problem(schema, reading.reply))


def _store_record(run_dir: Path, name: str, visit: int, session: str,
                  launched: engine_session.Launched, reading: engine_session.Reading,
                  schema: Mapping, suffix: str) -> None:
    record = {"denials": reading.denials, "exit_code": launched.exit_code,
              "problem": _problem(schema, reading), "prose": reading.prose, "session": session,
              "subtype": reading.subtype}
    engine_ledger.store_session_file(
        run_dir, f"{name}.{visit}{suffix}.json",
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8"))
