"""What a continued run takes up again from the run a killed engine left (`engine_shell`).

A visit a killed engine left interrupted is continued in the same visit: `resumed` names the session to launch
again, `open_waits` the waits the killed engine left open. A launch whose record carries a pending denial re-ask
(`retry`, `engine_session.store_record`) ended before the re-ask was sent, so the visit resumes with that text as
its prompt. A `call` step a killed engine left interrupted is
continued in the same visit too: `named_children` reads the child runs its `call` events name, and `ended`
reads how a child run ended, so the continuing call walks the unfinished children again in place and starts none.

With earlier results stale, the interrupted visit still resumes when each stale step is a `read` command (it
mutates nothing and waits for nothing) that, run again, answers with the outcome it stored: the answer is not
recorded and a rewinding walk runs the step as a visit. One that answers otherwise rewinds the visit as before,
so a read that changed (an issue parked meanwhile) is never walked past, and one that cannot have changed (the
repository head) never discards a session.

A call visit with `call` events naming child runs and no recorded stop after its entry gets no `run_continued`,
no new visit and no new child run. Each named child that is not done or at a stop of its own procedure is
continued as a run of its own (with its own procedure copy) and walked again under the same name; one that
ended keeps its end. A walked-again child owes the first-visit checks of a rewound call as its first walk did.
A call visit whose result file a killed engine published before it appended `result_stored` records that file
as its result and runs no child.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agent_tools.delivery import engine_ledger, engine_session, engine_stop, procedure_terms

DONE = "done"
ENGINE_STOPS = (*procedure_terms.ENGINE_STOPS, engine_stop.STOPPED_BY_REQUEST)


@dataclass(frozen=True)
class Resumed:
    """How a continued run launches the session its predecessor left interrupted in a visit."""
    session: str
    system: Path
    text: str
    attempt: int
    resume: bool


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
        return None
    # a launch announced and never started: send the re-ask the latest earlier record saved, if it saved one
    if not ended and launched and here[-1]["event"] == "session_resuming":
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
