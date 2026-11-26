"""What a continued run takes up again from the run a killed engine left (`engine_shell`, #1886).

A visit a killed engine left interrupted is continued in the same visit: `resumed` names the session to launch
again, `open_waits` the waits the killed engine left open. A `call` step a killed engine left interrupted is
continued in the same visit too: `named_children` reads the child runs its `call` events name, and `ended`
reads how a child run ended, so the continuing call walks the unfinished children again in place and starts none.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agent_tools.delivery import engine_ledger, engine_session, engine_stop, procedure_terms

DONE = "done"
ENGINE_STOPS = (procedure_terms.QUOTA_WAIT, engine_stop.STOPPED_BY_REQUEST)


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
    if any(_recorded_attempt(path) == max(launched, default=1)
           for path in (run_dir / "sessions").glob(f"{name}.{visit}.*json")):
        return None
    attempt = 2 + len(launched)
    started = any(e["event"] == "process_started" for e in here)
    text = (engine_session.CONTINUE_PROMPT if started else
            (run_dir / "sessions" / f"{name}.{visit}.prompt.md").read_text(encoding="utf-8"))
    return Resumed(session=starting[-1]["session"],
                   system=run_dir / "sessions" / f"{name}.{visit}.system.md",
                   text=text, attempt=attempt, resume=started)


def _recorded_attempt(path: Path) -> object:
    """The launch attempt a stored session record names, None for a file that is no such record."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document.get("attempt") if isinstance(document, dict) else None


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


def ended(child_dir: Path) -> str | None:
    """How the child run ended: `done`, the name of the procedure's own stop, or None when it is to be walked again.

    A run that stopped for a usage limit or at a request, or that has no end, is walked again."""
    state = engine_ledger.fold(engine_ledger.read_run(child_dir),
                               engine_ledger.replay(child_dir / "events.jsonl"), lambda pid, started: False)
    if state.done:
        return DONE
    if state.stop is not None and state.stop["name"] not in ENGINE_STOPS:
        return state.stop["name"]
    return None
