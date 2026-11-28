"""What a continued run takes up again from the run a killed engine left (`engine_shell`).

A visit a killed engine left interrupted is continued in the same visit: `resumed` names the session to launch
again, `open_waits` the waits the killed engine left open. A launch whose record carries a pending denial re-ask
(`retry`, `engine_session.store_record`) ended before the re-ask was sent, so the visit resumes with that text as
its prompt, and a launch whose record holds a refusal no re-ask followed, its `tool-denied` stop never recorded,
resumes with that stop (`Resumed.stop`) and launches nothing. A `call` step a killed engine left interrupted is
continued in the same visit too: `named_children` reads the child runs its `call` events name, and `ended`
reads how a child run ended, so the continuing call walks the unfinished children again in place and starts none.

With earlier results stale, the interrupted visit still resumes when each stale step is a `read` command (it
mutates nothing and waits for nothing) that, run again, answers with the outcome and result it stored: the answer is not
recorded and a rewinding walk runs the step as a visit. One that answers otherwise rewinds the visit as before,
so a read that changed (an issue parked meanwhile) is never walked past, and one that cannot have changed (the
repository head) never discards a session.

A visit the walk still has pending, whose result file and staged event a killed engine left with no
`result_stored`, is recorded from the staged event and the continue grades it; a file with no staged event is
left as before. An unchanged read (`unchanged`) re-enters in place: the pending action is kept, whatever it is,
and only its own entered visit is rewound.

A call visit with `call` events naming child runs and no recorded stop after its entry gets no `run_continued`,
no new visit and no new child run. Each named child that is not done or at a stop of its own procedure is
continued as a run of its own (with its own procedure copy) and walked again under the same name; one that
ended keeps its end. A walked-again child owes the first-visit checks of a rewound call as its first walk did.
A call visit whose result file a killed engine published before it appended `result_stored` records that file
as its result and runs no child. A call's result also carries the members its `returns` names, read from its done
child run's final replay state (`returned`), so a rewound child never yields a discarded visit's value.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from agent_tools.claims import forge_markers
from agent_tools.delivery import engine_core, engine_ledger, engine_session, engine_stop, procedure_terms

DONE = "done"
RENEWED = re.compile(r" renewed=[0-9]+")
ENGINE_STOPS = (*procedure_terms.ENGINE_STOPS, engine_stop.STOPPED_BY_REQUEST)


@dataclass(frozen=True)
class Resumed:
    """How a continued run launches the session its predecessor left interrupted in a visit."""
    session: str
    system: Path
    text: str
    attempt: int
    resume: bool
    stop: str | None = None  # the detail of a `tool-denied` stop the visit reached and a killed engine never recorded


def resumed(run_dir: Path, ledger: list[dict], name: str, visit: int) -> Resumed | None:
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
    records = [_recorded(path) for path in (run_dir / "sessions").glob(f"{name}.{visit}.*json")]
    ended = [document for document in records if document.get("attempt") == max(launched, default=1)]
    retry = next((document["retry"] for document in ended if isinstance(document.get("retry"), str)), None)
    if ended and retry is None:
        if (not any(document.get("denials") for document in ended)
                or any(document.get("exit_code") == engine_session.ALL_OUT_EXIT for document in ended)):
            return None  # an all-out launch ends at `quota-wait` whatever it reported, so its visit is entered again
        # the launch ended with a refusal it was not asked about again, and was cut before its stop was recorded
        refused = [document for document in sorted(records, key=lambda d: d.get("attempt") or 0)
                   if isinstance(document.get("denials"), list)]
        calls = tuple(dict.fromkeys(call for document in refused
                                    for call in engine_session.calls_of(document["denials"])))
        return Resumed(session=starting[-1]["session"],
                       system=run_dir / "sessions" / f"{name}.{visit}.system.md", text="",
                       attempt=2 + len(launched), resume=True, stop=engine_session.denial_detail(name, calls))
    # a launch announced and cut before it answered, as soon as its process started (the prompt is written after
    # `process_started`): send the re-ask the latest earlier record saved, if it saved one
    if not ended and launched and here[-1]["event"] in ("session_resuming", "process_started"):
        earlier = [d for d in records if isinstance(d.get("attempt"), int) and d["attempt"] < max(launched)]
        saved = max(earlier, key=lambda document: document["attempt"], default={}).get("retry")
        retry = saved if isinstance(saved, str) else None
    attempt = 2 + len(launched)
    started = any(e["event"] == "process_started" for e in here)
    text = retry or (engine_session.CONTINUE_PROMPT if started else
                     (run_dir / "sessions" / f"{name}.{visit}.prompt.md").read_text(encoding="utf-8"))
    return Resumed(session=starting[-1]["session"],
                   system=run_dir / "sessions" / f"{name}.{visit}.system.md",
                   text=text, attempt=attempt, resume=started)


def _recorded(path: Path) -> dict:
    """A stored session record, `{}` for a file that is no such record."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return document if isinstance(document, dict) else {}


def open_waits(ledger: list[dict]) -> list[str]:
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


def named_children(ledger: list[dict], step: str, visit: int) -> dict[int, str]:
    """The child run each item index of the call visit has, by the visit's `call` events; `{}` when the visit
    was not entered or a stop was recorded after its entry (such a call is rewound to a new visit, as before)."""
    entered = [i for i, e in enumerate(ledger) if e["event"] == "step_entered"
               and (e["step"], e["visit"]) == (step, visit)]
    if not entered or any(e["event"] == "stop_reached" for e in ledger[entered[-1]:]):
        return {}
    return {e["index"]: e["child"] for e in ledger
            if e["event"] == "call" and (e["step"], e["visit"]) == (step, visit)}


def names_child(run_dir: Path, child: str) -> bool:
    """Whether the run's readable events name `child`; true too when they cannot be read."""
    try:
        return any(event["event"] == "call" and event["child"] == child
                   for event in engine_ledger.replay(run_dir / "events.jsonl"))
    except engine_ledger.LedgerError:
        return True


def published_ends(run_dir: Path, ledger: list[dict], step: str, visit: int) -> list[dict] | None:
    """The ends in the call visit's result file a killed engine published before it appended `result_stored`,
    or None when the visit has no such file (or its result is recorded already)."""
    if any(e["event"] == "result_stored" and (e["step"], e["visit"]) == (step, visit) for e in ledger):
        return None
    try:
        document = json.loads((run_dir / "results" / f"{step}.{visit}.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        raise engine_ledger.LedgerError(f"results/{step}.{visit}.json is not readable: {error}") from error
    items = document.get("items") if isinstance(document, dict) else None
    if not isinstance(items, list) or not all(isinstance(item, dict) and isinstance(item.get("end"), str)
                                              for item in items):
        raise engine_ledger.LedgerError(f"results/{step}.{visit}.json is not a call result")
    return items


def pending_visits(action: engine_core.Action) -> tuple[tuple[str, int], ...]:
    """The visits the replayed walk still has pending for `action`: its own, or each waiting member's."""
    if isinstance(action, (engine_core.RunCommand, engine_core.StartSession)):
        return ((action.step, action.visit),)
    if isinstance(action, engine_core.RunGroup):
        return tuple((member.step, member.visit) for member in action.members)
    return ()


def adopt_staged(run_dir: Path, ledger: list[dict], action: engine_core.Action) -> list[dict]:
    """Record, as staged, the `result_stored` of each pending visit whose result file and staged event a killed
    engine left with no such event; the ledger as replayed afterwards, or `ledger` when nothing was recorded.

    A visit the walk does not have pending (a rewound visit's orphan) and a result file with no staged event are
    left alone. The result document is never read: the outcome, head and use are the staged ones."""
    appended = False
    for name, visit in pending_visits(action):
        if any(e["event"] == "result_stored" and (e["step"], e["visit"]) == (name, visit) for e in ledger):
            continue
        if not (run_dir / "results" / f"{name}.{visit}.json").is_file():
            continue
        staged = engine_ledger.staged_event(run_dir, name, visit)
        if staged is not None:
            engine_ledger.append_event(run_dir, staged)
            appended = True
    return engine_ledger.replay(run_dir / "events.jsonl") if appended else ledger


def pending_reentry(action: engine_core.Action, ledger: list[dict]) -> engine_core.Reentry | None:
    """Where a continue that leaves the pending `action` in place re-enters: its own visit when the ledger entered
    it, None when it was never entered (so nothing is rewound)."""
    if not isinstance(action, (engine_core.RunCommand, engine_core.StartSession, engine_core.RunGroup,
                               engine_core.RunCall)):
        return None
    entered = any(e["event"] == "step_entered" and (e["step"], e["visit"]) == (action.step, action.visit)
                  for e in ledger)
    return engine_core.Reentry(action.step, action.visit, ()) if entered else None


def _stored_result(run_dir: Path, name: str, visit: int) -> object:
    """The result document the visit stored, None when it is absent or unreadable."""
    try:
        return json.loads((run_dir / "results" / f"{name}.{visit}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _settled(value: object) -> object:
    """`value` with the renewal count of every claim marker in its text zeroed: the run's own keep-alive rewrites
    that count in the claim comment a read result quotes, which is no change in what the read found."""
    if isinstance(value, str):
        return forge_markers.MARKER.sub(
            lambda found: RENEWED.sub(" renewed=0", found[0]) if found["kind"] == "claim" else found[0], value)
    if isinstance(value, list):
        return [_settled(item) for item in value]
    if isinstance(value, dict):
        return {key: _settled(item) for key, item in value.items()}
    return value


def unchanged(procedure: dict, inputs: dict, ledger: list[dict], stale: tuple[str, ...], *,
              run_dir: Path, events: Callable[[list[dict]], list[dict]],
              rerun: Callable[[engine_core.RunCommand], object]) -> bool:
    """Whether every stale step is a `read` command that, run again through `rerun`, answers with the outcome and
    the result document its latest visit stored (a later step consumes the result's fields, and a read can
    keep its outcome while its fields change). `events` turns a ledger part into the core's events."""
    steps = {item["id"]: item for item in procedure["steps"]}
    for name in stale:
        step = steps[name]
        if step["holds"] != "read":
            return False
        entered = [i for i, e in enumerate(ledger) if e["event"] == "step_entered" and e["step"] == name]
        visit = ledger[entered[-1]]["visit"]
        recorded = next((e.get("outcome") for e in ledger if e["event"] == "result_stored"
                         and (e["step"], e["visit"]) == (name, visit)), None)
        pending = engine_core.replay(procedure, inputs, events(ledger[:entered[-1]])).action
        if not isinstance(pending, engine_core.RunCommand) or pending.step != name:
            return False
        ran = rerun(pending)
        stored = _stored_result(run_dir, name, visit)
        if (ran.timed_out or recorded is None or ran.outcome != recorded or stored is None
                or _settled(ran.result) != _settled(stored)):
            return False
    return True


def returned(step: Mapping, ends: Sequence[Mapping], visits_of: Callable[[str], Mapping[str, int]]) -> dict:
    """The members a call's `returns` names, read from its done child run; `{}` for no `returns` or a stop.

    `visits_of(run)` is the child's final replay state (`engine_core.result_visits`): each `X.m` is member m of
    the visit it holds for X, which a rewind may leave earlier than the last one stored. A missing visit, file
    or member is a ledger fault, never a silent gap."""
    if not step.get("returns") or engine_core.call_outcome([e["end"] for e in ends]) != DONE:
        return {}
    child = engine_ledger.runs_root() / ends[0]["run"]
    visits = visits_of(ends[0]["run"])
    members: dict = {}
    for path in step["returns"]:
        name, member = path.split(".", 1)
        try:
            document = json.loads((child / f"results/{name}.{visits[name]}.json").read_text(encoding="utf-8"))
            members[member] = document[member]
        except (KeyError, OSError, ValueError, TypeError) as error:
            raise engine_ledger.LedgerError(f"the child run {ends[0]['run']} stores no {path}: {error!r}") from error
    return members


def ended(child_dir: Path) -> str | None:
    """How the child run ended: `done`, the name of the procedure's own stop, or None when it is to be walked again.

    A run that stopped at an engine stop (a usage limit, a denied tool call) or at a request, or that has no end,
    is walked again."""
    state = engine_ledger.fold(engine_ledger.read_run(child_dir),
                               engine_ledger.replay(child_dir / "events.jsonl"), lambda pid, started: False)
    if state.done:
        return DONE
    if state.stop is not None and state.stop["name"] not in ENGINE_STOPS:
        return state.stop["name"]
    return None
