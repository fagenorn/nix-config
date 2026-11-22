"""The engine's shell: `engine deliver` runs a procedure of command, decide, group and call steps (#1512, #1517).

`deliver(issue, procedures_dir)` is the imperative half over the pure core: it
refuses what it cannot run before anything exists, creates the run directory,
then loops (replay the run's events through `engine_core.replay`, act on the
next action, record it) until the walk is `Done` or a `Stop`. `_walk` is that
loop for any run directory: it reads the run's procedure name and inputs from
its `run.json`, so the root run and every child run share it.

Every refusal raises `Refused`, before a run directory exists and before any
process starts: the project contract must resolve from the current directory; a
held run lock answers `EXIT_RUNNING` first; `<procedures_dir>/deliver.json` must
pass `procedure_check.check_directory` against the platform declarations plus
every project command, hold only `command`, `decide`, `group` and `call` steps,
a `mutates: true` step only as a `command` step, no input the run does not supply, no `call` member
of a group and no procedure that calls itself; every child procedure a `call`
names is refused on the same terms, with the parent's inputs (plus `item` under
`each`) as the inputs it may declare. The same checks run again on the run's
staged copy, which is the copy the loop reads (`<run>/procedure/`).

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
child.

Before each visit of a `mutates: true` command step, in a procedure naming a `keep_alive`,
the shell runs it (`KEEP_ALIVE_SECONDS`), recording a `keep_alive_ran` per call. It renews
only on the verdict `renewed` with exit 0; an `error` whose `transient` is the boolean
`true` is called once more. Otherwise the run ends at `claim-lost` without entering the
step, its detail carrying the verdict and what the call printed on stdout and stderr.

An outcome the step's `on` does not map is a `Fault`. A run ends with `run_done` or `stop_reached`.

Single writer: under the issue's creation lock the shell takes `<run>/lock`, an
exclusive `flock` held until its walk ends, for the root run and for each child
run (released on every path). A run whose lock is held makes the call exit
`EXIT_RUNNING`; a run not done and not locked is refused (continuing a run is a
later slice).

Exit codes: `engine.py` lists them; `Fault` and `Refused` print nothing on stdout.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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
KEEP_ALIVE_SECONDS = 1200
LOCK_NAME = "lock"
ENTRY = "deliver"
SUPPLIED_INPUTS = ("issue",)
RUNNABLE_KINDS = ("command", "decide", "group", "call")
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
        if item.get("mutates") is True and item["kind"] != "command":
            raise Refused(f"step {item['id']} is a {item['kind']} step marked mutates, and the "
                          "engine renews the claim only before a command step")
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


def deliver(issue: int, procedures_dir: Path) -> tuple[int, dict]:
    procedures_dir = Path(procedures_dir)
    snapshot, table = _resolve()
    project = snapshot["project"]["id"]
    try:
        running = _running(engine_ledger.find_runs(engine_ledger.runs_root(), issue, project),
                           issue)
    except (engine_ledger.LedgerError, OSError, KeyError) as error:
        raise Refused(str(error)) from error
    if running is not None:
        return running
    procedure = _validate(procedures_dir, table)
    inputs = {name: issue for name in procedure["inputs"]}
    held: list[int] = []

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
        return _walk(run_dir, table)
    except (engine_ledger.LedgerError, engine_core.CoreError, UnknownCommand,
            OSError, ValueError, KeyError) as error:
        raise Fault(str(error)) from error
    finally:
        _release(held)


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
    """Hands out the indexes of a call's items in list order, none once a fault is noted."""

    def __init__(self, count: int) -> None:
        self._count = count
        self._next = 0
        self._stopped = False
        self._lock = threading.Lock()

    def take(self) -> int | None:
        with self._lock:
            if self._stopped or self._next >= self._count:
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


def _walk(run_dir: Path, table: CommandTable) -> tuple[int, dict]:
    run = engine_ledger.read_run(run_dir)
    name, inputs = run["procedure"], run["inputs"]
    procedure = _load(run_dir / "procedure" / f"{name}.json")
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
        action = walk.action
        if isinstance(action, engine_core.Done):
            engine_ledger.append_event(run_dir, {"event": "run_done", "at": _now()})
            return EXIT_DONE, {
                "detail": f"The {name} procedure reached done after {ran} command "
                          f"{'visit' if ran == 1 else 'visits'}.",
                "end": "done", "need": None, "run": run_dir.name}
        if isinstance(action, engine_core.Stop):
            step = walk.transitions[-1].step
            return _stop(run_dir, step, action.name, action.need,
                         f"The {name} procedure stopped at step {step} with "
                         f"{action.name}, which needs {action.need}.")
        if isinstance(action, engine_core.RunCommand):
            if steps[action.step].get("mutates") is True and "keep_alive" in procedure:
                lost = _renew(run_dir, table, procedure, inputs, action)
                if lost is not None:
                    return lost
            _visit(run_dir, table, steps[action.step], action)
            ran += 1
        elif isinstance(action, engine_core.RunGroup):
            _group(run_dir, table, steps, action)
            ran += len(action.members)
        elif isinstance(action, engine_core.RunCall):
            _call(run_dir, table, run, steps[action.step], action)
        else:
            raise Fault(f"step {action.step} needs a session, which the engine does not run yet")



def _stop(run_dir: Path, step: str, name: str, need: str, detail: str) -> tuple[int, dict]:
    engine_ledger.append_event(run_dir, {"event": "stop_reached", "at": _now(), "step": step,
                                         "stop": name, "need": need})
    return EXIT_STOP, {"detail": detail, "end": name, "need": need, "run": run_dir.name}


def _renew(run_dir: Path, table: CommandTable, procedure: dict, inputs: dict,
           action: engine_core.RunCommand) -> tuple[int, dict] | None:
    """None when the claim is renewed before `action`'s step, else the `claim-lost` stop."""
    keep_alive = procedure["keep_alive"]
    args = tuple((path, inputs[path.split(".", 1)[1]]) for path in keep_alive["in"])
    for attempt in (1, 2):
        ran = engine_commands.run(table, keep_alive["command"], keep_alive.get("subcommand"),
                                  args, on_start=lambda pid: None, timeout=KEEP_ALIVE_SECONDS)
        verdict = "failed" if ran.outcome == "renewed" and ran.exit_code != 0 else ran.outcome
        engine_ledger.append_event(run_dir, {
            "event": "keep_alive_ran", "at": _now(), "step": action.step,
            "visit": action.visit, "attempt": attempt, "verdict": verdict})
        if verdict == "renewed":
            return None
        if verdict != "error" or ran.result.get("transient") is not True:
            break
    text = " ".join(ran.stdout.decode("utf-8", "replace").split()
                    + ran.stderr.decode("utf-8", "replace").split()) or "no output"
    need = procedure["stops"][procedure_check.CLAIM_LOST]["need"]
    return _stop(run_dir, action.step, procedure_check.CLAIM_LOST, need,
                 f"The claim was not renewed before step {action.step}, the keep-alive "
                 f"answered {verdict}: {text}.")


def _run_command(run_dir: Path, table: CommandTable, step: dict,
                 action: engine_core.RunCommand) -> engine_commands.Ran:
    """Enter, run and store one command step visit; the caller records its outcome."""
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
    return ran


def _graded(run_dir: Path, name: str, visit: int, outcome: str) -> None:
    engine_ledger.append_event(run_dir, {"event": "outcome_graded", "at": _now(), "step": name,
                                         "visit": visit, "outcome": outcome})


def _visit(run_dir: Path, table: CommandTable, step: dict,
           action: engine_core.RunCommand) -> None:
    name, visit = action.step, action.visit
    ran = _run_command(run_dir, table, step, action)
    if ran.outcome == engine_core.EXHAUSTED or ran.outcome not in step["on"]:
        raise Fault(f"step {name} has no mapping for the outcome {ran.outcome}")
    _graded(run_dir, name, visit, ran.outcome)
    engine_ledger.append_event(run_dir, {"event": "transition_taken", "at": _now(),
                                         "step": name, "visit": visit, "outcome": ran.outcome,
                                         "to": step["on"][ran.outcome]})


def _member(run_dir: Path, table: CommandTable, step: dict,
            action: engine_core.RunCommand | engine_core.StartSession) -> None:
    if not isinstance(action, engine_core.RunCommand):
        raise Fault(f"step {action.step} needs a session, which the engine does not run yet")
    ran = _run_command(run_dir, table, step, action)
    if ran.outcome == engine_core.EXHAUSTED:
        raise Fault(f"step {action.step} reported the reserved outcome {ran.outcome}")
    _graded(run_dir, action.step, action.visit, ran.outcome)


def _group(run_dir: Path, table: CommandTable, steps: dict[str, dict],
           action: engine_core.RunGroup) -> None:
    """Run the members beside each other; the group's grade is recorded by `_record_grades`."""
    engine_ledger.append_event(run_dir, {"event": "step_entered", "at": _now(),
                                         "step": action.step, "visit": action.visit,
                                         "stage": steps[action.step]["stage"]})
    with ThreadPoolExecutor(max_workers=len(action.members)) as pool:
        futures = [pool.submit(_member, run_dir, table, steps[member.step], member)
                   for member in action.members]
    for future in futures:
        future.result()


def _child(run_dir: Path, table: CommandTable, run: dict, step: dict,
           action: engine_core.RunCall, item: object, index: int, count: int) -> dict:
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
                now=datetime.now(timezone.utc), parent=run_dir.name,
                before_publish=lambda staged: held.append(_take_run_lock(staged, _now())))
        finally:
            os.close(creation)
        try:
            engine_ledger.append_event(run_dir, {
                "event": "call", "at": _now(), "step": action.step, "visit": action.visit,
                "child": child_dir.name, "index": index, "items": count})
        except BaseException:
            # Published but never named by the parent and never walked: leave no unnamed child.
            shutil.rmtree(child_dir, ignore_errors=True)
            raise
        _, line = _walk(child_dir, table)
        return {"end": line["end"], "item": item, "run": child_dir.name}
    finally:
        _release(held)


def _call(run_dir: Path, table: CommandTable, run: dict, step: dict,
          action: engine_core.RunCall) -> None:
    """Run the child procedure once per item, `parallel` at a time, and record the call's outcome."""
    started = time.monotonic()
    engine_ledger.append_event(run_dir, {"event": "step_entered", "at": _now(),
                                         "step": action.step, "visit": action.visit,
                                         "stage": step["stage"]})
    items = [None] if action.items is None else list(action.items)
    admission = _Admission(len(items))
    entries: dict[int, dict] = {}
    errors: dict[int, Exception] = {}

    def worker() -> None:
        while (index := admission.take()) is not None:
            try:
                entries[index] = _child(run_dir, table, run, step, action, items[index],
                                        index, len(items))
            except Exception as error:
                errors[index] = error
                admission.fail()

    threads = [threading.Thread(target=worker) for _ in range(min(action.parallel, len(items)))]
    running: list[threading.Thread] = []
    try:
        for thread in threads:
            thread.start()
            running.append(thread)
    except RuntimeError as error:
        admission.fail()
        raise Fault(f"step {action.step} could not start a child worker: {error}") from error
    finally:
        for thread in running:
            thread.join()
    if errors:
        raise errors[min(errors)]
    ends = [entries[index] for index in range(len(items))]
    engine_ledger.store_result(run_dir, step=action.step, visit=action.visit,
                               result={"items": ends}, at=_now(),
                               wall_seconds=time.monotonic() - started, turns=0,
                               tokens=dict(NO_TOKENS), spend_usd=0)
    outcome = engine_core.call_outcome([entry["end"] for entry in ends])
    if outcome not in step["on"]:
        raise Fault(f"step {action.step} has no mapping for the outcome {outcome}")
    _graded(run_dir, action.step, action.visit, outcome)
    engine_ledger.append_event(run_dir, {"event": "transition_taken", "at": _now(),
                                         "step": action.step, "visit": action.visit,
                                         "outcome": outcome, "to": step["on"][outcome]})
