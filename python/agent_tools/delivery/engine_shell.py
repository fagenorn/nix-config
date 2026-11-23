"""The engine's shell: `engine deliver` runs a procedure of command, agent, decide, group and call steps (#1512, #1514, #1517).

`deliver(issue, procedures_dir)` is the imperative half over the pure core: it
refuses what it cannot run before anything exists, creates the run directory,
then loops (replay the run's events through `engine_core.replay`, act on the
next action, record it) until the walk is `Done` or a `Stop`. `_walk` is that
loop for any run directory: it reads the run's procedure name and inputs from
its `run.json`, so the root run and every child run share it.

Every refusal raises `Refused`, before a run directory exists and before any
process starts: the project contract must resolve from the current directory; a
held run lock answers `EXIT_RUNNING` first; the host's settings must name the lifecycle guard as the one
unconditional Bash hook with no hook switch on (`engine_guard.locate`), checked after that answer;
`<procedures_dir>/deliver.json` must pass `procedure_check.check_directory` against the platform
declarations plus every project command, hold only `command`, `agent`, `decide`, `group` and `call` steps,
a `mutates: true` step only as a `command` step, no input the run does not supply, no `call` member
of a group, no procedure that calls itself and no agent step whose role file does not read
(`engine_session.read_role`), and the host declaration must admit the engine route (else the
refusal starts with its reason code), checked after the guard; every child procedure a `call`
names is refused on the same terms, with the parent's inputs (plus `item` under
`each`) as the inputs it may declare. The same checks run again on the run's
staged copy, which is the copy the loop reads (`<run>/procedure/`).

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

A `group` step runs its members beside each other, one thread each: each member
records `step_entered`, `process_started`, its stored result and
`outcome_graded`, and no `transition_taken`; the group's own grade is recorded
once per visit from `Replay.graded`, before the shell acts on the next action,
so a group of decide members, or one graded then exhausted in one replay, is
recorded too. A `call` step runs its child procedure once per item of `each`
(once with item `null` without `each`), each as a child run of its own: a run
directory whose `run.json` names the parent, with the procedures copied from the
parent's staged copy. At most `parallel` child walks run at once; children are
admitted in list order, and admission stops at the first fault, while the
children already admitted finish, and a worker that cannot start stops admission
the same way. The parent records a `call` event for each child before that child
walks (a child whose event cannot be recorded is removed unwalked), stores `{"items": [{"end", "item", "run"}, ...]}`
and takes `engine_core.call_outcome` of the ends. A fault in any child faults
the parent with no call outcome. `engine status` reads the root run, never a
child. A group's and a call's wait runs under `engine_session.reaping`, so a SIGTERM ends
every live session, admits no further child, starts no further step in any walk and exits
143 once the running steps end.

Before each visit of a `mutates: true` command step, and before each visit of a group with a
`mutates: true` member (once for the group, recorded at the group's step), in a procedure naming a `keep_alive`,
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

Single writer: under the issue's creation lock the shell takes `<run>/lock`, an
exclusive `flock` held until its walk ends, for the root run and for each child
run (released on every path). A run whose lock is held makes the call exit
`EXIT_RUNNING`; a run not done and not locked is refused (continuing a run is a
later slice).

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
import shutil
import socket
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
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
RUNNABLE_KINDS = ("command", "agent", "decide", "group", "call")
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


def _refuse_unrunnable(procedure: dict, directory: Path, supplied: tuple[str, ...] | frozenset[str],
                       name: str, calling: tuple[str, ...] = (),
                       validated: set[tuple[str, frozenset[str]]] | None = None) -> None:
    """Refuse what the engine cannot run in `procedure` and in every child it calls.

    A child already validated with the same supplied inputs is not validated again, so a procedure
    reached by many call paths is read once; the cycle check runs before that skip.
    """
    validated = set() if validated is None else validated
    for item in procedure["steps"]:
        if item["kind"] not in RUNNABLE_KINDS:
            raise Refused(f"step {item['id']} is a {item['kind']} step, "
                          "which the engine does not run yet")
    for item in procedure["steps"]:
        if item.get("mutates") is True and item["kind"] != "command":
            raise Refused(f"step {item['id']} is a {item['kind']} step marked mutates, and the "
                          "engine renews the claim only before a command step")
    for item in procedure["steps"]:
        if item["kind"] == "agent":
            try:
                engine_session.read_role(engine_session.roles_dir(os.environ), item["role"])
            except engine_session.RoleError as error:
                raise Refused(str(error)) from error
    for input_name in procedure["inputs"]:
        if input_name not in supplied:
            raise Refused(f"input {input_name} is not supplied by the engine")
    kinds = {item["id"]: item["kind"] for item in procedure["steps"]}
    for item in procedure["steps"]:
        if item["kind"] == "group":
            for member in item["members"]:
                if kinds.get(member["step"]) == "call":
                    raise Refused(f"group {item['id']} has the call step {member['step']} as a "
                                  "member, which the engine does not run")
    for item in procedure["steps"]:
        if item["kind"] != "call":
            continue
        child = item["procedure"]
        if child in (*calling, name):
            raise Refused(f"procedure {child} calls itself through step {item['id']}, "
                          "which the engine does not run")
        given = frozenset(procedure["inputs"]) | ({"item"} if "each" in item else frozenset())
        if (child, given) in validated:
            continue
        try:
            document = _load(directory / f"{child}.json")
        except (ValueError, OSError) as error:
            raise Refused(str(error)) from error
        _refuse_unrunnable(document, directory, given, child, (*calling, name), validated)
        validated.add((child, given))


def core_events(run_dir: Path, ledger: list[dict],
                computed: frozenset[str] = frozenset()) -> list[dict]:
    """The core's events for a run's ledger events; every other ledger event is skipped.

    An `outcome_graded` of a step in `computed` (a group, graded by the core) is skipped.
    """
    stored = {(e["step"], e["visit"]): e["result"]
              for e in ledger if e["event"] == "result_stored"}
    events: list[dict] = []
    for event in ledger:
        if event["event"] == "step_entered":
            events.append({"type": "entered", "step": event["step"]})
        elif event["event"] == "outcome_graded" and event["step"] not in computed:
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
    _refuse_unrunnable(procedure, directory, SUPPLIED_INPUTS, ENTRY)
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
        code, line = _walk(run_dir, table, _Scope(run_dir, holder, slots))
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


class _Admission:
    """Hands out the indexes of a call's items in list order, none once a fault is noted or the engine ends."""

    def __init__(self, count: int) -> None:
        self._count = count
        self._next = 0
        self._stopped = False
        self._lock = threading.Lock()

    def take(self) -> int | None:
        with self._lock:
            if self._stopped or self._next >= self._count or engine_session.ending():
                return None
            index = self._next
            self._next += 1
            return index

    def fail(self) -> None:
        with self._lock:
            self._stopped = True


def _record_grades(run_dir: Path, ledger: list[dict],
                   graded: tuple[engine_core.Graded, ...]) -> None:
    """Record each group grade the ledger lacks: its `outcome_graded`, then its `transition_taken`."""
    recorded = {(e["step"], e["visit"]) for e in ledger if e["event"] == "outcome_graded"}
    for grade in graded:
        if (grade.step, grade.visit) in recorded:
            continue
        engine_ledger.append_event(run_dir, {"event": "outcome_graded", "at": _now(),
                                             "step": grade.step, "visit": grade.visit,
                                             "outcome": grade.outcome})
        engine_ledger.append_event(run_dir, {"event": "transition_taken", "at": _now(),
                                             "step": grade.step, "visit": grade.visit,
                                             "outcome": grade.outcome, "to": grade.target})


@dataclass(frozen=True)
class _Scope:
    """What every walk of a run shares: the root run's directory, which holds the stop request
    and the agent slots, the lock holder the request names, and the slots the host admits."""

    root: Path
    holder: Mapping[str, object]
    slots: int

    def stop(self) -> bool:
        return engine_stop.requested(self.root, self.holder)


class _Quota(Exception):
    """A group member's session or a child run ended at the `quota-wait` stop, which the group
    or the call records once its members have ended; `step` is the member that hit it, else None."""

    def __init__(self, detail: str, step: str | None = None) -> None:
        super().__init__(detail)
        self.detail, self.step = detail, step


def _walk(run_dir: Path, table: CommandTable, scope: _Scope) -> tuple[int, dict]:
    run = engine_ledger.read_run(run_dir)
    name, inputs = run["procedure"], run["inputs"]
    procedure = _load(run_dir / "procedure" / f"{name}.json")
    stop = scope.stop
    steps = {item["id"]: item for item in procedure["steps"]}
    computed = frozenset(item["id"] for item in procedure["steps"] if item["kind"] == "group")
    ran = 0
    while True:
        ledger = engine_ledger.replay(run_dir / "events.jsonl")
        try:
            walk = engine_core.replay(procedure, inputs, core_events(run_dir, ledger, computed))
        except engine_core.CoreError as error:
            _record_grades(run_dir, ledger, error.graded)
            raise
        _record_grades(run_dir, ledger, walk.graded)
        _record_core_transitions(run_dir, ledger, walk)
        action = walk.action
        if isinstance(action, engine_core.Done):
            with engine_stop.publication(run_dir):  # a request is honored or published after
                if stop():
                    return _record_stop(run_dir, walk.transitions[-1].step, "", "", "", True)
                engine_ledger.append_event(run_dir, {"event": "run_done", "at": _now()})
            return EXIT_DONE, {
                "detail": f"The {name} procedure reached done after {ran} step "
                          f"{'visit' if ran == 1 else 'visits'}.",
                "end": "done", "need": None, "run": run_dir.name}
        if isinstance(action, engine_core.Stop):
            step = walk.transitions[-1].step
            return _stop(run_dir, step, action.name, action.need,
                         f"The {name} procedure stopped at step {step} with "
                         f"{action.name}, which needs {action.need}.", stop)
        _refuse_when_ending(run_dir, action.step)
        if isinstance(action, engine_core.StartSession):
            try:
                stopped = _visit_session(run_dir, table.root, steps[action.step], action, scope)
            except engine_stop.Stopped:
                return _stopped(run_dir, action.step)
            if stopped is not None:
                return stopped
            ran += 1
        elif isinstance(action, engine_core.RunCommand):
            try:
                if steps[action.step].get("mutates") is True and "keep_alive" in procedure:
                    lost = _renew(run_dir, table, procedure, inputs, action.step, action.visit,
                                  stop)
                    if lost is not None:
                        return lost
                _visit(run_dir, table, steps[action.step], action, stop)
            except engine_stop.Stopped:
                return _stopped(run_dir, action.step)
            ran += 1
        elif isinstance(action, engine_core.RunGroup):
            try:
                if "keep_alive" in procedure and any(
                        steps[member["step"]].get("mutates") is True
                        for member in steps[action.step]["members"]):
                    lost = _renew(run_dir, table, procedure, inputs, action.step, action.visit,
                                  stop)
                    if lost is not None:
                        return lost
                _group(run_dir, table, steps, action, scope)
            except engine_stop.Stopped:
                return _stopped(run_dir, action.step)
            except _Quota as quota:
                return _quota_ended(run_dir, action.step, quota, stop)
            ran += len(action.members)
        elif isinstance(action, engine_core.RunCall):
            try:
                _call(run_dir, table, run, steps[action.step], action, scope)
            except engine_stop.Stopped:
                return _stopped(run_dir, action.step)
            except _Quota as quota:
                return _quota_ended(run_dir, action.step, quota, stop)
        else:
            raise Fault(f"step {action.step} needs {type(action).__name__}, "
                        "which the engine does not run yet")


def _refuse_when_ending(run_dir: Path, step: str) -> None:
    """A fault when the engine is ending: nothing is entered or dispatched after that."""
    if engine_session.ending():
        raise Fault(f"run {run_dir.name} stops before step {step}: the engine is ending")


def _record_core_transitions(run_dir: Path, ledger: list[dict], walk: engine_core.Replay) -> None:
    """Append the `transition_taken` of each walk transition the ledger lacks, in order.

    A command visit writes its own in `_visit`; the core resolves a `decide` step and an
    exhausted entry with no command, so the ledger holds the rest of the walk's transitions here.
    A group's grade is `_record_grades`'s, with its transition, and is left out of the count.
    """
    grades = {(grade.step, grade.visit) for grade in walk.graded}
    taken = sum(1 for event in ledger if event["event"] == "transition_taken"
                and (event["step"], event["visit"]) not in grades)
    visits: dict[str, int] = {}
    pending = []
    for transition in walk.transitions:
        visits[transition.step] = visits.get(transition.step, 0) + 1
        if (transition.step, visits[transition.step]) not in grades:
            pending.append((transition, visits[transition.step]))
    for transition, visit in pending[taken:]:
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
           step: str, visit: int, stop: Callable[[], bool]) -> tuple[int, dict] | None:
    """None when the claim is renewed before visit `visit` of `step`, else the `claim-lost` stop."""
    keep_alive = procedure["keep_alive"]
    args = tuple((path, inputs[path.split(".", 1)[1]]) for path in keep_alive["in"])
    for attempt in (1, 2):
        ran = engine_commands.run(table, keep_alive["command"], keep_alive.get("subcommand"),
                                  args, guard=_guard(), on_start=lambda pid: None,
                                  timeout=KEEP_ALIVE_SECONDS, stop=stop)
        verdict = "failed" if ran.outcome == "renewed" and ran.exit_code != 0 else ran.outcome
        engine_ledger.append_event(run_dir, {
            "event": "keep_alive_ran", "at": _now(), "step": step,
            "visit": visit, "attempt": attempt, "verdict": verdict})
        if verdict == "renewed":
            _refuse_when_ending(run_dir, step)  # the engine may have begun ending during the renewal
            return None
        if verdict != "error" or ran.result.get("transient") is not True:
            break
    if ran.exit_code is None:
        text = " ".join(ran.result["reason"].split())
    else:
        text = " ".join(ran.stdout.decode("utf-8", "replace").split()
                        + ran.stderr.decode("utf-8", "replace").split()) or "no output"
    need = procedure["stops"][procedure_check.CLAIM_LOST]["need"]
    return _stop(run_dir, step, procedure_check.CLAIM_LOST, need,
                 f"The claim was not renewed before step {step}, the keep-alive "
                 f"answered {verdict}: {text}.", stop)


def _graded(run_dir: Path, step: dict, visit: int, outcome: str, *, bound: bool = False,
            member: bool = False) -> None:
    """Record the grade of a visit and the transition it takes.

    A reply or a printed verdict (`bound=False`) must be mapped by the step's `on`, else it is a
    `Fault` before any event. The engine's own grade of a fired bound (`bound=True`) is always
    recorded, because `core_events` reads it from `outcome_graded`, and then faults when `on`
    does not map it, with no `transition_taken`. A group member's grade (`member=True`) is its outcome
    alone, which the group's `pass` entries judge; the group takes the transition.
    """
    name = step["id"]
    if member:
        if outcome == engine_core.EXHAUSTED:
            raise Fault(f"step {name} reported the reserved outcome {outcome}")
        engine_ledger.append_event(run_dir, {"event": "outcome_graded", "at": _now(), "step": name,
                                             "visit": visit, "outcome": outcome})
        return
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
           stop: Callable[[], bool], member: bool = False) -> None:
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
        _grade_command(run_dir, step, name, visit, ran, member)
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
                   ran: engine_commands.Ran, member: bool) -> None:
    if ran.timed_out:
        engine_ledger.store_result(run_dir, step=name, visit=visit, result={"bound": "wall-time"},
                                   at=_now(), wall_seconds=ran.wall_seconds, turns=0,
                                   tokens=dict(NO_TOKENS), spend_usd=0)
        _graded(run_dir, step, visit, procedure_check.OUT_OF_BOUNDS, bound=True, member=member)
        return
    engine_ledger.store_result(run_dir, step=name, visit=visit, result=ran.result, at=_now(),
                               wall_seconds=ran.wall_seconds, turns=0, tokens=dict(NO_TOKENS),
                               spend_usd=0)
    if ran.outcome == procedure_check.OUT_OF_BOUNDS:  # only the engine grades a fired bound
        raise Fault(f"step {name} has no mapping for the outcome {ran.outcome}")
    _graded(run_dir, step, visit, ran.outcome, member=member)


def _member(run_dir: Path, table: CommandTable, step: dict,
            action: engine_core.RunCommand | engine_core.StartSession, scope: _Scope) -> None:
    if isinstance(action, engine_core.StartSession):
        stopped = _visit_session(run_dir, table.root, step, action, scope, member=True)
        if stopped is not None:
            raise _Quota(stopped[1]["detail"], step["id"])
    else:
        _visit(run_dir, table, step, action, scope.stop, member=True)


def _group(run_dir: Path, table: CommandTable, steps: dict[str, dict],
           action: engine_core.RunGroup, scope: _Scope) -> None:
    """Run the members beside each other; the group's grade is recorded by `_record_grades`."""
    engine_ledger.append_event(run_dir, {"event": "step_entered", "at": _now(),
                                         "step": action.step, "visit": action.visit,
                                         "stage": steps[action.step]["stage"]})
    pool = ThreadPoolExecutor(max_workers=len(action.members))
    futures = []
    try:
        with engine_session.reaping():
            try:
                try:
                    for member in action.members:
                        futures.append(pool.submit(_member, run_dir, table,
                                                   steps[member.step], member, scope))
                except RuntimeError as error:
                    raise Fault(f"step {action.step} could not start a member: {error}") from error
                pool.shutdown(wait=True)
            except Exception:
                pool.shutdown(wait=True)  # drain the started members, still under `reaping`
                raise
    finally:
        pool.shutdown(wait=True)  # after a stop `reaping` has killed the sessions: this returns
    for future in futures:
        future.result()


def _names_child(run_dir: Path, child: str) -> bool:
    """Whether the run's readable events name `child`; true too when they cannot be read."""
    try:
        return any(event["event"] == "call" and event["child"] == child
                   for event in engine_ledger.replay(run_dir / "events.jsonl"))
    except engine_ledger.LedgerError:
        return True


def _child(run_dir: Path, table: CommandTable, run: dict, step: dict,
           action: engine_core.RunCall, item: object, index: int, count: int,
           scope: _Scope) -> dict:
    """Create the child run for one item, record its `call` event, walk it, and keep its end."""
    held: list[int] = []
    try:
        child = _load(run_dir / "procedure" / f"{action.procedure}.json")
        inputs = {name: item if name == "item" and action.items is not None
                  else run["inputs"][name] for name in child["inputs"]}
        creation = _lock_creation(run["issue"])
        try:
            child_dir = engine_ledger.create_run(
                project=run["project"], issue=run["issue"], procedure=action.procedure,
                procedures_dir=run_dir / "procedure",
                platform_revision=run["platform_revision"], host=run["host"], inputs=inputs,
                now=datetime.now(timezone.utc), parent=run_dir.name, tracker=run.get("tracker"),
                before_publish=lambda staged: held.append(_take_run_lock(staged, _now())))
        finally:
            os.close(creation)
        try:
            engine_ledger.append_event(run_dir, {
                "event": "call", "at": _now(), "step": action.step, "visit": action.visit,
                "child": child_dir.name, "index": index, "items": count})
        except BaseException:
            # Published but never named by the parent and never walked: leave no unnamed child.
            # A write that failed only at its fsync did name it: that child stays.
            if not _names_child(run_dir, child_dir.name):
                shutil.rmtree(child_dir, ignore_errors=True)
            raise
        _, line = _walk(child_dir, table, scope)
        if line["end"] == procedure_check.QUOTA_WAIT:
            raise _Quota(line["detail"])
        if line["end"] == engine_stop.STOPPED_BY_REQUEST:
            raise engine_stop.Stopped
        return {"end": line["end"], "item": item, "run": child_dir.name}
    finally:
        _release(held)


def _call(run_dir: Path, table: CommandTable, run: dict, step: dict,
          action: engine_core.RunCall, scope: _Scope) -> None:
    """Run the child procedure once per item, `parallel` at a time, and record the call's outcome."""
    started = time.monotonic()
    engine_ledger.append_event(run_dir, {"event": "step_entered", "at": _now(),
                                         "step": action.step, "visit": action.visit,
                                         "stage": step["stage"]})
    items = [None] if action.items is None else list(action.items)
    admission = _Admission(len(items))
    entries: dict[int, dict] = {}
    errors: dict[int, Exception] = {}

    def worker(ended: threading.Event) -> None:
        try:
            while (index := admission.take()) is not None:
                try:
                    entries[index] = _child(run_dir, table, run, step, action, items[index],
                                            index, len(items), scope)
                except Exception as error:
                    errors[index] = error
                    admission.fail()
        finally:
            ended.set()

    finished = [threading.Event() for _ in range(min(action.parallel, len(items)))]
    threads = [threading.Thread(target=worker, args=(ended,)) for ended in finished]
    running: list[threading.Event] = []

    def drain() -> None:
        # An event, not `Thread.join`: before Python 3.13 a join a stop interrupted marks its thread
        # ended though it still runs, so the join in `finally` would return at once.
        for ended in running:
            ended.wait()

    try:
        with engine_session.reaping():
            try:
                try:
                    for thread, ended in zip(threads, finished):
                        thread.start()
                        running.append(ended)
                except RuntimeError as error:
                    raise Fault(f"step {action.step} could not start a child worker: "
                                f"{error}") from error
                drain()
            except Exception:
                admission.fail()
                drain()  # the started workers finish, still under `reaping`
                raise
    except BaseException:
        admission.fail()
        raise
    finally:
        drain()  # after a stop `reaping` has killed the sessions: this returns
    if errors:
        raise errors[min(errors)]
    if len(entries) != len(items):
        raise Fault(f"step {action.step} stops before its items are all run: "
                    "the engine is ending")
    ends = [entries[index] for index in range(len(items))]
    engine_ledger.store_result(run_dir, step=action.step, visit=action.visit,
                               result={"items": ends}, at=_now(),
                               wall_seconds=time.monotonic() - started, turns=0,
                               tokens=dict(NO_TOKENS), spend_usd=0)
    _graded(run_dir, step, action.visit, engine_core.call_outcome([entry["end"] for entry in ends]))


def _quota_ended(run_dir: Path, step: str, quota: _Quota,
                 stop: Callable[[], bool]) -> tuple[int, dict]:
    """The `quota-wait` stop of a group or a call, recorded once its members or children have
    ended, so it is the run's last event; a member's step names it, else the group's or call's."""
    return _stop(run_dir, quota.step or step, procedure_check.QUOTA_WAIT, QUOTA_NEED,
                 quota.detail, stop)


def _visit_session(run_dir: Path, root: str, step: dict, action: engine_core.StartSession,
                   scope: _Scope, member: bool = False) -> tuple[int, dict] | None:
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

    with engine_slots.hold(scope.root, scope.slots, on_wait=waiting, on_waited=waited):
        engine_ledger.append_event(run_dir, {
            "event": "session_starting", "at": _now(), "step": name, "visit": visit,
            "session": session, "role": role.name,
            "account": os.environ.get("CLAUDE_ACCOUNT") or "console"})
        launched, reading, stopped, no_reply = _launch_until_answered(
            run_dir, root, (name, visit, session), prompt, (role, schema, system), scope.stop,
            defer=member)
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
        _graded(run_dir, step, visit, procedure_check.OUT_OF_BOUNDS, bound=True, member=member)
        return None
    if no_reply:
        store({})
        _graded(run_dir, step, visit, procedure_check.NO_REPLY, member=member)
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
    _graded(run_dir, step, visit, outcome, member=member)
    return None


def _launch_until_answered(
        run_dir: Path, root: str, visit_of: tuple[str, int, str], prompt: str,
        launch_of: tuple[engine_session.Role, Mapping, Path], stop: Callable[[], bool],
        defer: bool = False,
) -> tuple[engine_session.Launched, engine_session.Reading, tuple[int, dict] | None, bool]:
    """Launch the session, again with `--resume` after a usage limit, a first API error (once, after
    `API_RETRY_SECONDS`) or a first miss (once, with `REASK_PROMPT`); return the first launch that is
    none of these, or follows a second error or miss, with its record stored and the wait ended (a
    miss and its resume summed in the measurements), the `quota-wait` stop (wait open; unrecorded
    with `defer`, for a group to record) and whether the outcome is `no-reply`."""
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
        if defer:
            line = {"detail": detail, "end": procedure_check.QUOTA_WAIT, "need": QUOTA_NEED,
                    "run": run_dir.name}
            return launched, reading, (EXIT_STOP, line), False
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
