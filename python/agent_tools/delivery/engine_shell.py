"""The engine's shell: `engine deliver` runs a procedure of command, agent and decide steps (#1512, #1514).

`deliver(issue, procedures_dir)` is the imperative half over the pure core: it
refuses what it cannot run before anything exists, creates the run directory,
then loops (replay the run's events through `engine_core.replay`, act on the
next action, record it) until the walk is `Done` or a `Stop`.

Every refusal raises `Refused`, before a run directory exists and before any
process starts: the project contract must resolve from the current directory; a
held run lock answers `EXIT_RUNNING` first; `<procedures_dir>/deliver.json` must
pass `procedure_check.check_directory` against the platform declarations plus
every project command, hold only `command`, `agent` and `decide` steps, a `mutates: true`
step only as a `command` step, and no input but `issue`, and every agent step's role file
must read (`engine_session.read_role`). The same checks run again on the run's staged copy,
which is the copy the loop reads (`<run>/procedure/deliver.json`).

An agent step runs as one headless session (`engine_session`) in the project
root: its role body, rendered prompt and a session record are stored under the
run's `sessions/`, `session_starting` is on disk before the process is spawned,
and only the `outcome_from` member of the session's structured reply grades the
step. A session with no structured reply is a `Fault`, so neither the prose nor
the exit code selects an outcome, and so is a session denied a shell command,
whose reply may rest on a check it never ran.

Before each visit of a `mutates: true` command step, in a procedure naming a `keep_alive`,
the shell runs it (`KEEP_ALIVE_SECONDS`), recording a `keep_alive_ran` per call. It renews
only on the verdict `renewed` with exit 0; an `error` whose `transient` is the boolean
`true` is called once more. Otherwise the run ends at `claim-lost` without entering the
step, its detail carrying the verdict and what the call printed on stdout and stderr.

Before every command it runs, keep-alive included, the shell has the lifecycle guard judge it, and a
refusal is the outcome `refused` (issue 1515).

An outcome the step's `on` does not map is a `Fault`. A run ends with `run_done` or `stop_reached`.

Once the run exists and before its first step, `engine_housekeeping.housekeep` prunes the history and
sweeps expired run directories; a run that ends in done or a stop then appends one history line
(`_record_history`) before its lock is released. Neither changes the call's code or result line.

Single writer: under the issue's creation lock the shell takes `<run>/lock`, an exclusive `flock` held
until `deliver` returns. A run whose lock is held makes the call exit `EXIT_RUNNING`; a run not done and
not locked is refused (continuing a run is a later slice).

Exit codes: `engine.py` lists them; `Fault` and `Refused` print nothing on stdout.
"""

from __future__ import annotations

import fcntl
import json
import os
import socket
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.delivery import (
    engine_commands, engine_core, engine_guard, engine_housekeeping, engine_ledger,
    engine_session, procedure_check,
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
LOCK_NAME = "lock"
ENTRY = "deliver"
SUPPLIED_INPUTS = ("issue",)
RUNNABLE_KINDS = ("command", "agent", "decide")
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


def deliver(issue: int, procedures_dir: Path, *, clock: Callable[[], datetime] | None = None,
            tracker: engine_housekeeping.Tracker | None = None) -> tuple[int, dict]:
    procedures_dir = Path(procedures_dir)
    snapshot, table = _resolve()
    project = snapshot["project"]["id"]
    clock = clock or (lambda: datetime.now(timezone.utc))
    identity = engine_housekeeping.tracker_identity(snapshot["bindings"]["tracker"])
    tracker_factory = ((lambda: tracker) if tracker is not None else
                       (lambda: engine_housekeeping.default_tracker(
                           snapshot["bindings"]["tracker"])))
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
        code, line = _walk(run_dir, table, inputs)
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


def _walk(run_dir: Path, table: CommandTable, inputs: dict) -> tuple[int, dict]:
    procedure = _load(run_dir / "procedure" / f"{ENTRY}.json")
    steps = {item["id"]: item for item in procedure["steps"]}
    ran = 0
    while True:
        ledger = engine_ledger.replay(run_dir / "events.jsonl")
        walk = engine_core.replay(procedure, inputs, core_events(run_dir, ledger))
        _record_core_transitions(run_dir, ledger, walk)
        action = walk.action
        if isinstance(action, engine_core.Done):
            engine_ledger.append_event(run_dir, {"event": "run_done", "at": _now()})
            return EXIT_DONE, {
                "detail": f"The {ENTRY} procedure reached done after {ran} step "
                          f"{'visit' if ran == 1 else 'visits'}.",
                "end": "done", "need": None, "run": run_dir.name}
        if isinstance(action, engine_core.Stop):
            step = walk.transitions[-1].step
            return _stop(run_dir, step, action.name, action.need,
                         f"The {ENTRY} procedure stopped at step {step} with "
                         f"{action.name}, which needs {action.need}.")
        if isinstance(action, engine_core.StartSession):
            _visit_session(run_dir, table.root, steps[action.step], action)
        elif isinstance(action, engine_core.RunCommand):
            if steps[action.step].get("mutates") is True and "keep_alive" in procedure:
                lost = _renew(run_dir, table, procedure, inputs, action)
                if lost is not None:
                    return lost
            _visit(run_dir, table, steps[action.step], action)
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
                                  args, guard=_guard(), on_start=lambda pid: None,
                                  timeout=KEEP_ALIVE_SECONDS)
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
                 f"answered {verdict}: {text}.")


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
                              guard=_guard(), on_start=started)
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


def _visit_session(run_dir: Path, root: str, step: dict,
                   action: engine_core.StartSession) -> None:
    name, visit = action.step, action.visit
    engine_ledger.append_event(run_dir, {"event": "step_entered", "at": _now(), "step": name,
                                         "visit": visit, "stage": step["stage"]})
    role = engine_session.read_role(engine_session.roles_dir(os.environ), step["role"])
    staged = run_dir / "procedure"
    schema = _load(staged / action.reply)
    prompt = engine_session.render_prompt(
        (staged / action.prompt).read_text(encoding="utf-8"), action.args)
    session = str(uuid.uuid4())
    try:
        account = engine_session.choose_account(root)
    except engine_session.AccountChoiceError as error:
        raise Fault(f"step {name} could not choose its account: {error}") from error
    system = engine_ledger.store_session_file(run_dir, f"{name}.{visit}.system.md",
                                              role.body.encode("utf-8"))
    engine_ledger.store_session_file(run_dir, f"{name}.{visit}.prompt.md", prompt.encode("utf-8"))
    engine_ledger.append_event(run_dir, {
        "event": "session_starting", "at": _now(), "step": name, "visit": visit,
        "session": session, "role": role.name,
        "account": account or "custom"})

    def started(pid: int) -> None:
        engine_ledger.append_event(run_dir, {"event": "process_started", "at": _now(),
                                             "step": name, "visit": visit, "pid": pid,
                                             "started": _now()})

    launched = engine_session.launch(
        engine_session.launch_argv(role, schema, session, system), root, prompt, on_start=started,
        env=None if account is None else {**os.environ, "CLAUDE_ACCOUNT": account})
    reading = engine_session.read_result(launched.stdout)
    record = {"denials": reading.denials, "exit_code": launched.exit_code,
              "prose": reading.prose, "session": session, "subtype": reading.subtype}
    engine_ledger.store_session_file(
        run_dir, f"{name}.{visit}.json",
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    reply = reading.reply
    denied = next((d for d in reading.denials
                   if isinstance(d, dict) and d.get("tool_name") == "Bash"), None)
    if denied is not None:
        tool_input = denied.get("tool_input")
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        raise Fault(f"step {name} was denied the shell command {str(command)[:200]!r}, so its "
                    f"reply is not graded: list it in the role's tools as Bash(<prefix>:*)")
    if reply is None:
        reason = engine_session.diagnostic(launched.stderr)
        raise Fault(f"step {name} gave no structured reply, exit {launched.exit_code}"
                    + (f": {reason}" if reason else ""))
    wall = reading.wall_seconds if reading.wall_seconds is not None else launched.wall_seconds
    engine_ledger.store_result(run_dir, step=name, visit=visit, result=reply, at=_now(),
                               wall_seconds=wall, turns=reading.turns, tokens=reading.tokens,
                               spend_usd=reading.spend_usd)
    problem = engine_session.reply_problem(schema, reply)
    if problem is not None:
        raise Fault(f"step {name} gave a reply that breaks its schema: {problem}")
    outcome = reply.get(step["outcome_from"])
    if (not isinstance(outcome, str) or outcome == engine_core.EXHAUSTED
            or outcome not in step["on"]):
        raise Fault(f"step {name} has no mapping for the outcome {outcome}")
    engine_ledger.append_event(run_dir, {"event": "outcome_graded", "at": _now(), "step": name,
                                         "visit": visit, "outcome": outcome})
    engine_ledger.append_event(run_dir, {"event": "transition_taken", "at": _now(),
                                         "step": name, "visit": visit, "outcome": outcome,
                                         "to": step["on"][outcome]})
