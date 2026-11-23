"""The engine's shell: `engine deliver` runs or continues a procedure of command, agent and decide steps (#1512, #1514).

`deliver(issue, procedures_dir)` is the imperative half over the pure core: it
refuses what it cannot run before anything is changed, creates the run directory
(or finds the issue's open run), then loops (replay the run's events through `engine_core.replay`, act on the
next action, record it) until the walk is `Done` or a `Stop`.

Every refusal raises `Refused`, before a run directory exists and before any
process starts: the project contract must resolve from the current directory; a
held run lock answers `EXIT_RUNNING` first; the host's settings must name the lifecycle guard as the one
unconditional Bash hook with no hook switch on (`engine_guard.locate`), checked after that answer;
the procedure must pass `procedure_check.check_directory` against the platform
declarations plus every project command, hold only `command`, `agent` and `decide` steps, a
`mutates: true` step only as a `command` step, and no input but `issue`, and every agent step's role
file must read (`engine_session.read_role`), and the host declaration must admit the engine route (else the
refusal starts with its reason code), checked after the guard. The same checks run again on the run's staged copy, which
is the copy the loop reads (`<run>/procedure/deliver.json`); a mutating command step needs its `check`,
which the checker requires. A new run checks `<procedures_dir>/deliver.json`; a continued run checks
its own staged copy only.

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
both launches (in a continued visit a miss is `no-reply` at once, see "Continuing"). Any other reading with no usable reply is a `Fault`, and so is a session denied a
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

A visit a killed engine left interrupted is continued in the same visit (issue 1523), after the stale-result
rule and `engine_core.reentry` have run first: its `step_entered` and `session_starting` stand, no `run_continued`
is appended and no new visit starts. The session recorded for the visit is launched again under the next attempt
(2 plus its `session_resuming` events), with `session_resuming` before every launch: `--resume <session>` with
`engine_session.CONTINUE_PROMPT` when a process of the visit had started, else `--session-id <session>` with the
stored `prompt.md`. The launch's prompt is stored as `sessions/<step>.<visit>.continue-<attempt>.prompt.md` when
absent, and each record as `.continue-<attempt>.json`. The continued launches are not re-asked, so a miss is
`no-reply`; every later launch of the visit resumes. A visit with a stored result (with or without its outcome) or
a recorded stop after its entry (`quota-wait`, `stopped-by-request`) or a launch that ended with its record stored (a
`Fault` such as no structured reply or a denied shell command; each record names its `attempt`) is not resumed but
rewound to a new visit as before, its `run_continued` clearing the stop and closing an open usage-limit wait. A resumed visit
appends no `run_continued`, so the continuing call closes every wait the killed engine left open with a
`wait_ended` of its kind (a usage-limit or `host-slot` wait) before the visit launches.

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
until `deliver` returns. The probe for a held run lock and every lock taking (a new run's and a continued
run's renewal) happen under the creation lock, so no probe reads a lock file between a lock and its write.
A run whose lock is held makes the call exit `EXIT_RUNNING`.

Continuing: the issue's runs that are not done are found under the creation lock. Two or more are
refused, naming them. One is continued on its own procedure copy (`procedures_dir` is not read) with the
inputs of its `run.json`: a visit whose result is stored with its outcome but lacks its grading or its
transition (either may be the one a kill left) is first completed from the stored outcome; unless the
walk is already `Done`, `engine_core.reentry` (given the current repository head) names the step to
re-enter and a `run_continued` event records it; the loop then runs as for a new run. A mutating command
step's `check` runs first on every visit that replays one a continue discarded (`RunCommand.recheck`),
under the same guard, wall bound and stop polling as the command: the outcome `absent` runs the command,
any other outcome stands for it, its document stored as the visit's result, and the keep-alive runs before
that check as before any visit of the step. A `run_continued` carries no `head`; a `result_stored` carries
the visit's graded `outcome` and, for a command step that holds `head`, the repository head only when it
is the same before and after the step's process. None are open: a new run is created.

The leftover rule comes after the procedure rule and before every other rule, for a continued and a
superseded run: the process group of the run's last `process_started` whose visit stored no result is
ended (`engine_stop.end_leftover`) when its pid is alive with the recorded start time (`same_process`),
before any visit is graded and before anything is appended, so no session of the interrupted engine runs
beside the new one. A process that does not match is left alone.

A continued run whose procedure copy declares a `format` the engine does not read is superseded: it gets
one `stop_reached` named `superseded` (need `nothing`) at its last entered step (`deliver` when it entered
none) and one history line, and the same call then creates a new run from `--procedures` and runs it; the
line printed is the new run's. A superseded run is never open, so it is never continued. A copy that differs
only in content (its `SHA256SUMS` no longer matching) is continued, and a copy that does not parse as a JSON
object is refused as before, with nothing written.

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
import subprocess
import sys
import tempfile
import uuid
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
RUNNABLE_KINDS = ("command", "agent", "decide")
QUOTA_NEED = "retry"
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


def _open_runs(runs: list[Path]) -> list[Path]:
    open_runs = []
    for existing in runs:
        state = engine_ledger.fold(engine_ledger.read_run(existing),
                                   engine_ledger.replay(existing / "events.jsonl"),
                                   engine_ledger.process_alive)
        if not state.done and (state.stop or {}).get("name") != procedure_check.SUPERSEDED:
            open_runs.append(existing)
    return open_runs


def _superseded(run_dir: Path) -> bool:
    """Whether the run's procedure copy is in a format the engine does not read; a copy that does
    not parse is not (it is refused later, by `_validate`)."""
    try:
        document = _load(run_dir / "procedure" / "deliver.json")
    except (ValueError, OSError):
        return False
    return not procedure_check.readable_format(document.get("format"))


def _supersede(run_dir: Path, clock: Callable[[], datetime]) -> None:
    """End a run whose copy is unreadable: one stop at its last entered step, one history line."""
    ledger = engine_ledger.replay(run_dir / "events.jsonl")
    step = next((e["step"] for e in reversed(ledger) if e["event"] == "step_entered"), ENTRY)
    with engine_stop.publication(run_dir):
        _record_stop(run_dir, step, procedure_check.SUPERSEDED, "nothing", "", False)
    _record_history(run_dir, clock)


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
    guard = _guard()
    if isinstance(guard, engine_guard.Unavailable):
        # Refused before the runs root or any run is created; a held run lock answers first.
        try:
            running = _running(engine_ledger.find_runs(engine_ledger.runs_root(), issue, project),
                               issue)
        except (engine_ledger.LedgerError, OSError, KeyError) as error:
            raise Refused(str(error)) from error
        if running is not None:
            return running
        raise Refused(f"the host's settings load no lifecycle guard hook, so no run starts: "
                      f"{guard.reason}")
    slots = _admitted()
    holder = {"pid": os.getpid(), "started": _now()}
    held: list[int] = []
    continued = False

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
            open_runs = _open_runs(runs)
            if len(open_runs) > 1:
                raise Refused(f"runs {', '.join(run.name for run in open_runs)} of issue "
                              f"{issue} are all open; the engine continues one run only")
            if open_runs and _superseded(open_runs[0]):
                held.append(_take_run_lock(open_runs[0], holder["started"]))
                _end_leftover(open_runs[0])
                _supersede(open_runs[0], clock)
                _release(held)
                open_runs = []
            if open_runs:
                run_dir = open_runs[0]
                procedure = _validate(run_dir / "procedure", table)
                inputs = engine_ledger.read_run(run_dir)["inputs"]
                held.append(_take_run_lock(run_dir, holder["started"]))
                continued = True
            else:
                procedure = _validate(procedures_dir, table)
                inputs = {name: issue for name in procedure["inputs"]}
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
        if continued:
            _continue(run_dir, table, inputs)
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


def _end_leftover(run_dir: Path) -> None:
    """End the process group a killed engine left running for the run's interrupted visit."""
    state = engine_ledger.fold(engine_ledger.read_run(run_dir),
                               engine_ledger.replay(run_dir / "events.jsonl"),
                               engine_stop.same_process)
    if state.process is not None and state.alive:
        engine_stop.end_leftover(state.process["pid"])


def _continue(run_dir: Path, table: CommandTable, inputs: dict) -> None:
    """Record where the run's next walk re-enters; a stored but ungraded visit is graded first."""
    _end_leftover(run_dir)
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
            _graded(run_dir, steps[name], visit, outcome, graded=graded, moved=moved,
                    bound=outcome == procedure_check.OUT_OF_BOUNDS)
            ledger = engine_ledger.replay(run_dir / "events.jsonl")
    events = core_events(run_dir, ledger)
    action = engine_core.replay(procedure, inputs, events).action
    if isinstance(action, engine_core.Done):
        return
    if isinstance(action, engine_core.Stop) and (not ledger or ledger[-1]["event"] != "stop_reached"):
        return  # the owner never saw this stop: the walk reports it before anything is re-entered
    point = engine_core.reentry(procedure, inputs, events, read_head(table.root))
    if (isinstance(action, engine_core.StartSession)
            and (action.step, action.visit) == (point.step, point.visit)
            and _resumed(run_dir, ledger, action.step, action.visit) is not None):
        for wait in _open_waits(ledger):  # no run_continued closes what the killed engine left open
            engine_ledger.append_event(run_dir, {"event": "wait_ended", "at": _now(), "wait": wait})
        return  # the interrupted visit resumes its own session: no rewind, no new visit
    event = {"event": "run_continued", "at": _now(), "step": point.step}
    if point.visit is not None:
        event["visit"] = point.visit
    engine_ledger.append_event(run_dir, event)


def _open_waits(ledger: list[dict]) -> list[str]:
    """The kinds of the waits the ledger leaves open, oldest first (a `run_continued` closes all)."""
    open_kinds: list[str] = []
    for e in ledger:
        if e["event"] == "wait_started":
            open_kinds.append(e["wait"])
        elif e["event"] == "wait_ended" and e["wait"] in open_kinds:
            open_kinds.remove(e["wait"])
        elif e["event"] == "run_continued":
            open_kinds.clear()
    return open_kinds


@dataclass(frozen=True)
class _Resumed:
    """How a continued run launches the session its predecessor left interrupted in a visit."""
    session: str
    system: Path
    text: str
    attempt: int
    resume: bool


def _resumed(run_dir: Path, ledger: list[dict], name: str, visit: int) -> _Resumed | None:
    """The interrupted visit's session to launch again, or None when the visit is to be entered
    (again): it was never entered or never recorded a session, stored a result (graded or not), or
    ended at a recorded stop after its entry, or whose last launch ended with its record stored (a
    `Fault` writes nothing to the ledger, so the record's `attempt` is what tells a launch that ended
    from one a killed engine cut short)."""
    here = [e for e in ledger if e.get("step") == name and e.get("visit") == visit]
    entered = [i for i, e in enumerate(ledger) if e["event"] == "step_entered"
               and (e["step"], e["visit"]) == (name, visit)]
    starting = [e for e in here if e["event"] == "session_starting"]
    if not entered or not starting or any(e["event"] == "result_stored" for e in here):
        return None
    if any(e["event"] == "stop_reached" for e in ledger[entered[-1]:]):
        return None
    launched = [e["attempt"] for e in here if e["event"] == "session_resuming"]
    if any(_recorded_attempt(path) == max(launched, default=1)
           for path in (run_dir / "sessions").glob(f"{name}.{visit}.*json")):
        return None
    attempt = 2 + len(launched)
    started = any(e["event"] == "process_started" for e in here)
    text = (engine_session.CONTINUE_PROMPT if started else
            (run_dir / "sessions" / f"{name}.{visit}.prompt.md").read_text(encoding="utf-8"))
    return _Resumed(session=starting[-1]["session"],
                    system=run_dir / "sessions" / f"{name}.{visit}.system.md",
                    text=text, attempt=attempt, resume=started)


def _recorded_attempt(path: Path) -> object:
    """The launch attempt a stored session record names, None for a file that is no such record."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document.get("attempt") if isinstance(document, dict) else None


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
                stopped = _visit_session(
                    run_dir, table.root, steps[action.step], action, stop, slots,
                    resumed=_resumed(run_dir, ledger, action.step, action.visit))
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

    Keyed by step and the core's visit number, which a rewind never reuses; a command visit
    writes its own in `_visit`, so this holds the `decide` and exhausted-entry transitions."""
    taken = {(event["step"], event["visit"]) for event in ledger
             if event["event"] == "transition_taken"}
    for transition in walk.transitions:
        if (transition.step, transition.visit) not in taken:
            engine_ledger.append_event(run_dir, {
                "event": "transition_taken", "at": _now(), "step": transition.step,
                "visit": transition.visit, "outcome": transition.outcome,
                "to": transition.target})


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


def _graded(run_dir: Path, step: dict, visit: int, outcome: str, *, bound: bool = False,
            graded: bool = False, moved: bool = False) -> None:
    """Record the grade of a visit and the transition it takes.

    A reply or a printed verdict (`bound=False`) must be mapped by the step's `on`, else it is a
    `Fault` before any event. The engine's own grade of a fired bound (`bound=True`) is always
    recorded, because `core_events` reads it from `outcome_graded`, and then faults when `on`
    does not map it, with no `transition_taken`. `graded` and `moved` name the event a kill
    left, which a continue does not write again.
    """
    name = step["id"]
    unmapped = outcome == engine_core.EXHAUSTED or outcome not in step["on"]
    if unmapped and not bound:
        raise Fault(f"step {name} has no mapping for the outcome {outcome}")
    if not graded:
        engine_ledger.append_event(run_dir, {"event": "outcome_graded", "at": _now(),
                                             "step": name, "visit": visit, "outcome": outcome})
    if unmapped:
        raise Fault(f"step {name} has no mapping for the outcome {outcome}")
    if not moved:
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

    before = read_head(table.root) if step["holds"] == "head" else None
    ran = None
    if action.recheck:
        check = step["check"]
        ran = engine_commands.run(table, check["command"], check.get("subcommand"), action.args,
                                  guard=_guard(), on_start=started,
                                  timeout=table.wall_seconds(check["command"]), stop=stop)
        if ran.outcome == ABSENT and not ran.timed_out:
            ran = None
    if ran is None:
        ran = engine_commands.run(table, action.command, action.subcommand, action.args,
                                  guard=_guard(), on_start=started,
                                  timeout=table.wall_seconds(action.command), stop=stop)
    after = read_head(table.root) if step["holds"] == "head" else None
    try:
        _grade_command(run_dir, step, name, visit, ran, before if before == after else None)
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
                   ran: engine_commands.Ran, head: str | None) -> None:
    if ran.timed_out:
        engine_ledger.store_result(run_dir, step=name, visit=visit, result={"bound": "wall-time"},
                                   at=_now(), wall_seconds=ran.wall_seconds, turns=0,
                                   tokens=dict(NO_TOKENS), spend_usd=0, head=head,
                                   outcome=procedure_check.OUT_OF_BOUNDS)
        _graded(run_dir, step, visit, procedure_check.OUT_OF_BOUNDS, bound=True)
        return
    engine_ledger.store_result(run_dir, step=name, visit=visit, result=ran.result, at=_now(),
                               wall_seconds=ran.wall_seconds, turns=0, tokens=dict(NO_TOKENS),
                               spend_usd=0, head=head, outcome=ran.outcome)
    if ran.outcome == procedure_check.OUT_OF_BOUNDS:  # only the engine grades a fired bound
        raise Fault(f"step {name} has no mapping for the outcome {ran.outcome}")
    _graded(run_dir, step, visit, ran.outcome)


def _visit_session(run_dir: Path, root: str, step: dict, action: engine_core.StartSession,
                   stop: Callable[[], bool], slots: int,
                   resumed: _Resumed | None = None) -> tuple[int, dict] | None:
    """Run the step's session to its result; the `quota-wait` stop when no account can answer.

    With `resumed` the visit is already entered and its session recorded: neither is recorded
    again, and the session is launched under `resumed.attempt`."""
    name, visit = action.step, action.visit
    role = engine_session.read_role(engine_session.roles_dir(os.environ), step["role"])
    staged = run_dir / "procedure"
    schema = _load(staged / action.reply)
    if resumed is None:
        engine_ledger.append_event(run_dir, {"event": "step_entered", "at": _now(), "step": name,
                                             "visit": visit, "stage": step["stage"]})
        prompt = engine_session.render_prompt(
            (staged / action.prompt).read_text(encoding="utf-8"), action.args)
        session = str(uuid.uuid4())
        system = engine_ledger.store_session_file(run_dir, f"{name}.{visit}.system.md",
                                                  role.body.encode("utf-8"))
        engine_ledger.store_session_file(run_dir, f"{name}.{visit}.prompt.md",
                                         prompt.encode("utf-8"))
    else:
        session, system, prompt = resumed.session, resumed.system, resumed.text
        if not (run_dir / "sessions" / f"{name}.{visit}.continue-{resumed.attempt}.prompt.md"
                ).exists():
            engine_ledger.store_session_file(
                run_dir, f"{name}.{visit}.continue-{resumed.attempt}.prompt.md",
                resumed.text.encode("utf-8"))

    def waiting() -> None:
        engine_ledger.append_event(run_dir, {"event": "wait_started", "at": _now(),
                                             "wait": engine_slots.WAIT, "until": None})

    def waited() -> None:
        engine_ledger.append_event(run_dir, {"event": "wait_ended", "at": _now(),
                                             "wait": engine_slots.WAIT})

    with engine_slots.hold(run_dir, slots, on_wait=waiting, on_waited=waited):
        if resumed is None:
            engine_ledger.append_event(run_dir, {
                "event": "session_starting", "at": _now(), "step": name, "visit": visit,
                "session": session, "role": role.name,
                "account": os.environ.get("CLAUDE_ACCOUNT") or "console"})
        launched, reading, stopped, no_reply = _launch_until_answered(
            run_dir, root, (name, visit, session), prompt, (role, schema, system), stop,
            resumed=resumed)
    if stopped is not None:
        return stopped
    wall = (launched.wall_seconds if launched.timed_out or reading.wall_seconds is None
            else reading.wall_seconds)

    def store(result: dict, outcome: str | None) -> None:
        engine_ledger.store_result(run_dir, step=name, visit=visit, result=result, at=_now(),
                                   wall_seconds=wall, turns=reading.turns, tokens=reading.tokens,
                                   spend_usd=reading.spend_usd, outcome=outcome)

    bound = (engine_session.WALL_TIME if launched.timed_out
             else engine_session.CAP_SUBTYPES.get(reading.subtype))
    if bound is not None:
        store({"bound": bound}, procedure_check.OUT_OF_BOUNDS)
        _graded(run_dir, step, visit, procedure_check.OUT_OF_BOUNDS, bound=True)
        return None
    if no_reply:
        store({}, procedure_check.NO_REPLY)
        _graded(run_dir, step, visit, procedure_check.NO_REPLY)
        return None
    reply = reading.reply
    if reply is None:
        reason = engine_session.diagnostic(launched.stderr)
        raise Fault(f"step {name} gave no structured reply, exit {launched.exit_code}"
                    + (f": {reason}" if reason else ""))
    problem = engine_reply.reply_problem(schema, reply)
    outcome = reply.get(step["outcome_from"])
    store(reply, outcome if problem is None and isinstance(outcome, str) else None)
    if problem is not None:
        raise Fault(f"step {name} gave a reply that breaks its schema: {problem}")
    if not isinstance(outcome, str):
        raise Fault(f"step {name} has no mapping for the outcome {outcome}")
    _graded(run_dir, step, visit, outcome)
    return None


def _launch_until_answered(
        run_dir: Path, root: str, visit_of: tuple[str, int, str], prompt: str,
        launch_of: tuple[engine_session.Role, Mapping, Path], stop: Callable[[], bool],
        resumed: _Resumed | None = None,
) -> tuple[engine_session.Launched, engine_session.Reading, tuple[int, dict] | None, bool]:
    """Launch the session, again with `--resume` after each usage limit, after the first other
    API error (once, after `API_RETRY_SECONDS`) and after the first miss (once, with `REASK_PROMPT`),
    until a launch that is none of these, or a second API error or miss, whose result is returned
    with the visit's record stored and the wait ended; a miss's launch and its resume are summed in
    the result's measurements. The third member is the `quota-wait` stop (record stored, wait open)
    when no account can answer, the fourth is true for the second API error or miss, the outcome
    `no-reply`. With `resumed` the first launch is its attempt (`--resume` only when a process of the
    visit had started, else `--session-id`), every later one resumes, and a miss is `no-reply` with no
    re-ask; each record is `<step>.<visit>.continue-<attempt>.json`."""
    name, visit, session = visit_of
    role, schema, system = launch_of
    attempt, limited, waiting, released, retried, no_reply = (
        1 if resumed is None else resumed.attempt), set(), False, False, False, False
    missed, text = resumed is not None, prompt
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
        _store_record(run_dir, (name, visit, session, attempt), launched, reading, schema,
                      f".continue-{attempt}" if resumed is not None else
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
                engine_session.launch_argv(role, schema, session, system,
                                      resume=attempt > 1 and (resumed is None or resumed.resume
                                                              or attempt > resumed.attempt)),
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


def _store_record(run_dir: Path, visit_of: tuple[str, int, str, int],
                  launched: engine_session.Launched, reading: engine_session.Reading,
                  schema: Mapping, suffix: str) -> None:
    name, visit, session, attempt = visit_of
    record = {"attempt": attempt, "denials": reading.denials, "exit_code": launched.exit_code,
              "problem": _problem(schema, reading), "prose": reading.prose, "session": session,
              "subtype": reading.subtype}
    engine_ledger.store_session_file(
        run_dir, f"{name}.{visit}{suffix}.json",
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8"))
