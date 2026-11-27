"""`engine deliver` that kills its own process group straight after one named ledger write.

Run as `cut_engine.py deliver <issue>` with the environment of a stubbed run. Without the three variables below it
behaves as `python -m agent_tools.delivery.engine`.

- `ENGINE_CUT_AT`: a JSON object `{run, event, step, visit, occurrence}`. The write that makes exactly that point
  is followed by SIGKILL to the process group, while the lock that serialises every writer is still held.
- `ENGINE_CUT_LOG`: a file that receives one JSON line per point written, `{run, event, step, visit, occurrence, cut}`.
- `ENGINE_BREAK_CONTINUE=1`: a continue never resumes an interrupted session, so it launches the step afresh.

A point is `run` (`<procedure>#<n>`, the n-th run of that procedure among the run directories beside the run, by
`sequence`), the event type (`result-file` for a file published by the ledger), the event's step and visit, and the
number of lines of the run's `events.jsonl` with the same event, step and visit once the line is written.
"""

from __future__ import annotations

import dataclasses
import json
import os
import signal
import sys
import threading
from pathlib import Path

from agent_tools.delivery import engine, engine_ledger, engine_resume

RESULT_FILE = "result-file"
LOCK = threading.RLock()
LABELS: dict[str, str] = {}
TARGET = json.loads(os.environ["ENGINE_CUT_AT"]) if os.environ.get("ENGINE_CUT_AT") else None
LOG = os.environ.get("ENGINE_CUT_LOG")


def label(run_dir: Path) -> str:
    """`<procedure>#<n>` of a run directory, cached by its name."""
    if run_dir.name not in LABELS:
        own = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["procedure"]
        same = []
        for entry in run_dir.parent.iterdir():
            try:
                document = json.loads((entry / "run.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if document.get("procedure") == own:
                same.append((document.get("sequence"), entry.name))
        same.sort()
        LABELS[run_dir.name] = f"{own}#{[name for _, name in same].index(run_dir.name) + 1}"
    return LABELS[run_dir.name]


def reached(point: dict) -> None:
    """Log `point` and, when it is the target, kill the process group."""
    cut = point == TARGET
    if LOG:
        with open(LOG, "a", encoding="utf-8") as log:
            log.write(json.dumps({**point, "cut": cut}) + "\n")
            log.flush()
            os.fsync(log.fileno())
    if cut:
        os.killpg(os.getpgrp(), signal.SIGKILL)


def wrap_append(original):
    def append_line(*args, **kwargs):
        with LOCK:
            result = original(*args, **kwargs)
            events_path = Path(args[0])
            written = json.loads(args[1] if isinstance(args[1], str) else bytes(args[1]).decode("utf-8"))
            key = (written["event"], written.get("step"), written.get("visit"))
            seen = 0
            for line in events_path.read_text(encoding="utf-8").splitlines():
                if line:
                    other = json.loads(line)
                    seen += (other["event"], other.get("step"), other.get("visit")) == key
            reached({"run": label(events_path.parent), "event": key[0], "step": key[1], "visit": key[2],
                     "occurrence": seen})
            return result
    return append_line


def wrap_result(original):
    def write_result(*args, **kwargs):
        with LOCK:
            result = original(*args, **kwargs)
            path = Path(args[0])
            step, visit, _ = path.name.rsplit(".", 2)
            reached({"run": label(path.parent.parent), "event": RESULT_FILE, "step": step, "visit": int(visit),
                     "occurrence": 1})
            return result
    return write_result


def wrap_resumed(original):
    def resumed(*args, **kwargs):
        found = original(*args, **kwargs)
        if found is not None and found.stop is None:
            return dataclasses.replace(found, resume=False)
        return found
    return resumed


engine_ledger._append_line = wrap_append(engine_ledger._append_line)
engine_ledger._write_result = wrap_result(engine_ledger._write_result)
if os.environ.get("ENGINE_BREAK_CONTINUE") == "1":
    engine_resume.resumed = wrap_resumed(engine_resume.resumed)

sys.exit(engine.main(sys.argv[1:]))
