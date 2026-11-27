"""Cut a stubbed delivery straight after one ledger write, and wait for what it started to end.

`deliver(run, cut=point)` runs the stubbed engine through `tests/fixtures/engine-stubbed-run/cut_engine.py`, which
SIGKILLs its process group right after the write that makes `point`. `cut_at` refuses a point the run never reached
and `settle` returns only once every process the cut run started has ended, so a continue sees a quiet fixture.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_stop
from tests.engine_stubbed_world import StubbedRun
from tests.guard_policy_world import REPO_ROOT
from tests.process_liveness import process_alive

CUT_ENGINE = REPO_ROOT / "tests/fixtures/engine-stubbed-run/cut_engine.py"
RESULT_FILE = "result-file"
CUT_LOG_NAME = "cuts.log"  # in `run.tmp`: where `cut_at` logs, and so where `live_started` finds the spawn record
SPAWNED_SUFFIX = ".spawned"
RESULT_NAME = re.compile(r"[a-z][a-z0-9-]*\.[1-9][0-9]*\.json")


@dataclass(frozen=True)
class CutPoint:
    run: str
    event: str
    step: str | None
    visit: int | None
    occurrence: int

    def name(self) -> str:
        if self.event == RESULT_FILE:
            return f"{self.run} result-file {self.step}.{self.visit}"
        if self.step is None:
            return f"{self.run} {self.event} #{self.occurrence}"
        label = self.step if self.visit is None else f"{self.step}.{self.visit}"
        return f"{self.run} {self.event} {label} #{self.occurrence}"

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, document: dict) -> CutPoint:
        return cls(document["run"], document["event"], document["step"], document["visit"],
                   document["occurrence"])


BROKEN_CUT = CutPoint("direct#1", "session_answered", "implement", 1, 1)


def deliver(run: StubbedRun, *, cut: CutPoint | None = None, log: Path | None = None,
            broken: bool = False) -> subprocess.CompletedProcess:
    env = dict(run.env)
    if cut:
        env["ENGINE_CUT_AT"] = json.dumps(cut.to_json())
    if log:
        env["ENGINE_CUT_LOG"] = str(log)
    if broken:
        env["ENGINE_BREAK_CONTINUE"] = "1"
    run.test.addCleanup(run.end_started)
    run.test.addCleanup(end_spawned, run)
    return subprocess.run([sys.executable, str(CUT_ENGINE), "deliver", str(run.issue)], cwd=run.fixture.root,
                          env=env, start_new_session=True, capture_output=True, text=True, timeout=600)


def _logged(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


def cut_points(log: Path) -> tuple[CutPoint, ...]:
    return tuple(CutPoint.from_json(document) for document in _logged(log))


def _spawned(run: StubbedRun) -> list[dict]:
    """Every `{pid, started}` the cut engine spawned, as it recorded them beside the cut log (see `cut_engine.py`):
    the ledger lacks a process spawned just before the cut, whose `process_started` is never written."""
    return _logged(run.tmp / (CUT_LOG_NAME + SPAWNED_SUFFIX))


def _live(event: dict) -> bool:
    try:
        os.kill(event["pid"], 0)  # cheap: most spawned processes are long gone
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return engine_stop.same_process(event["pid"], event["started"]) and process_alive(event["pid"])


def live_started(run: StubbedRun) -> list[int]:
    """The pids of every process a run started that is still that process and not a zombie: those its ledger
    recorded as started and those the cut engine recorded at spawn."""
    pids = []
    with mock.patch.dict(os.environ, {"PATH": run.env["PATH"]}):  # the fake forge leaves `ps` off this process's
        for directory in run.run_dirs():
            for event in run.events(directory):
                if event["event"] == "process_started" and _live(event):
                    pids.append(event["pid"])
        pids.extend(event["pid"] for event in _spawned(run) if event["pid"] not in pids and _live(event))
    return pids


def end_spawned(run: StubbedRun) -> None:
    """End every process the cut engine recorded at spawn that is still that process."""
    with mock.patch.dict(os.environ, {"PATH": run.env["PATH"]}):
        for event in _spawned(run):
            if engine_stop.same_process(event["pid"], event["started"]):
                try:
                    os.killpg(event["pid"], signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass


def settle(run: StubbedRun, wait: float = 60.0) -> None:
    deadline = time.monotonic() + wait
    pids = live_started(run)
    while pids and time.monotonic() < deadline:
        time.sleep(0.05)
        pids = live_started(run)
    if pids:
        run.end_started()
        end_spawned(run)
        raise AssertionError(f"cut run processes still alive after {wait} s: {pids}")


def cut_at(run: StubbedRun, point: CutPoint) -> subprocess.CompletedProcess:
    log = run.tmp / CUT_LOG_NAME
    done = deliver(run, cut=point, log=log)
    logged = _logged(log)
    if done.returncode != -signal.SIGKILL or not logged or logged[-1] != {**point.to_json(), "cut": True}:
        raise AssertionError(f"cut point {point.name()} never reached: exit {done.returncode}")
    settle(run)
    return done
