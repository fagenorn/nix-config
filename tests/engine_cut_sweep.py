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
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from unittest import mock

from agent_tools.claims import forge_markers
from agent_tools.delivery import engine_stop
from tests.engine_procedure_copies import PROCEDURES
from tests.engine_stubbed_world import StubbedRun
from tests.guard_policy_world import REAL_GIT, REPO_ROOT
from tests.process_liveness import process_alive
from tests.test_engine_stubbed_run import Scenario

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


def _mutating() -> frozenset[str]:
    steps = set()
    for path in PROCEDURES.glob("*.json"):
        if path.name.endswith(".reply.json"):
            continue
        for step in json.loads(path.read_text(encoding="utf-8"))["steps"]:
            if step["kind"] == "agent" and step.get("mutates"):
                steps.add(step["id"])
    return frozenset(steps)


MUTATING = _mutating()
NAMED = (CutPoint("direct#1", "session_starting", "implement", 1, 1),
         CutPoint("direct#1", RESULT_FILE, "implement", 1, 1))
SAMPLE = (NAMED[0], BROKEN_CUT, NAMED[1], CutPoint("land-attempt#1", RESULT_FILE, "merge-pr", 1, 1))
MAX_DELIVERIES = 3
EFFECTS = ("comment posted", "issue created", "pull request created", "pull request merged")


@dataclass(frozen=True)
class Outcome:
    end: str
    state: dict
    effects: dict
    fresh: dict
    fresh_steps: dict


def _git(path: str | Path, *args: str) -> list[str]:
    done = subprocess.run([REAL_GIT, "-C", str(path), *args], capture_output=True, text=True, check=True)
    return done.stdout.splitlines()


def _root_events(run: StubbedRun) -> list[dict]:
    roots = run.runs()
    return run.events(roots[0]) if roots and (roots[0] / "events.jsonl").exists() else []


def last_event(run: StubbedRun) -> str | None:
    events = _root_events(run)
    return events[-1]["event"] if events else None


def _end(run: StubbedRun) -> str:
    events = _root_events(run)
    if events and events[-1]["event"] == "run_done":
        return "done"
    if events and events[-1]["event"] == "stop_reached":
        return f"stop {events[-1]['stop']}"
    return "open"


def _fresh(run: StubbedRun) -> tuple[dict, dict]:
    ids: dict[str, int] = {}
    steps: dict[str, int] = {}
    for launch in run.launches():
        argv = launch["argv"]
        if "--session-id" in argv:
            session = argv[argv.index("--session-id") + 1]
            ids[session] = ids.get(session, 0) + 1
            steps[launch["key"]] = steps.get(launch["key"], 0) + 1
    return ids, dict(sorted(steps.items()))


def _effects(run: StubbedRun) -> dict:
    calls = run.forge.calls()
    created = ["api", "-X", "POST", f"repos/{run.fixture.slug}/issues"]
    next_pull = json.loads(run.pulls_state.read_text(encoding="utf-8"))["next"]
    return {
        EFFECTS[0]: sum(1 for c in calls if c["argv"][:3] == ["api", "-X", "POST"]
                        and len(c["argv"]) > 3 and c["argv"][3].endswith("/comments")),
        EFFECTS[1]: sum(1 for c in calls if c["argv"][:4] == created),
        EFFECTS[2]: next_pull - 1,
        EFFECTS[3]: sum(1 for p in run.pulls() if p["state"] == "MERGED"),
    }


def outcome(run: StubbedRun, start: str) -> Outcome:
    issue = run.forge.issue()
    markers = [forge_markers.parse(comment) for comment in run.forge.stored()]
    state = {
        "issue state": issue["state"],
        "issue labels": sorted(issue["labels"]),
        "issues created": len(issue["created"]),
        "comments": sorted("text" if m is None else m.kind for m in markers),
        "live claims": len(run.claims()),
        "released claims": sum(1 for m in markers if m is not None and m.kind == "claim" and "released" in m.fields),
        "lock refs": sorted(run.lock_refs()),
        "pull requests": [[p["number"], p["state"], p["headRefName"]] for p in run.pulls()],
        "main change": _git(run.bare, "diff", "--raw", "--no-renames", "--no-abbrev", start, "main"),
        "main subjects": _git(run.bare, "log", "--format=%s", f"{start}..main"),
        "branch on origin": run.origin_tip(run.branch) is not None,
        "local branches": sorted(_git(run.fixture.root, "for-each-ref", "--format=%(refname)", "refs/heads")),
        "worktree": run.worktree_path.exists(),
    }
    fresh, fresh_steps = _fresh(run)
    return Outcome(_end(run), state, _effects(run), fresh, fresh_steps)


def judge(name: str, reference: Outcome, got: Outcome) -> list[str]:
    prefix = f"cut after {name}: "
    lines = [f"session {session} launched fresh {count} times"
             for session, count in sorted(got.fresh.items()) if count > 1]
    for step in sorted(MUTATING):
        was, now = reference.fresh_steps.get(step, 0), got.fresh_steps.get(step, 0)
        if was != now:
            lines.append(f"mutates step {step} launched fresh {now} times, uninterrupted {was}")
    for effect, was in reference.effects.items():
        now = got.effects.get(effect, 0)
        if was != now:
            lines.append(f"{effect} {now} times, uninterrupted {was}")
    if reference.end != got.end:
        lines.append(f"ended {got.end}, uninterrupted {reference.end}")
    for key, was in reference.state.items():
        if got.state.get(key) != was:
            lines.append(f"{key} {got.state.get(key)!r}, uninterrupted {was!r}")
    return [prefix + line for line in lines]


def again(last_event: str | None, need: str | None, deliveries: int) -> bool:
    if deliveries == 0:
        return last_event != "run_done"
    return need == "retry" and deliveries < MAX_DELIVERIES


def reading(done: subprocess.CompletedProcess) -> tuple[str | None, str | None]:
    lines = (done.stdout or "").splitlines()
    if len(lines) == 1:
        try:
            document = json.loads(lines[0])
        except ValueError:
            document = None
        if isinstance(document, dict):
            return document.get("need"), None
    errors = [line for line in (done.stderr or "").splitlines() if line.strip()]
    return None, f"exited {done.returncode} with no result line: {errors[-1] if errors else ''}"


def continue_to_end(run: StubbedRun, *, broken: bool = False) -> tuple[list[subprocess.CompletedProcess], list[str]]:
    deliveries: list[subprocess.CompletedProcess] = []
    notes: list[str] = []
    need = None
    while again(last_event(run), need, len(deliveries)):
        deliveries.append(deliver(run, broken=broken))
        need, note = reading(deliveries[-1])
        if note:
            notes.append(f"delivery {len(deliveries)} {note}")
            break
    return deliveries, notes


def select(points, slice_spec: str | None, only: str | None) -> tuple[CutPoint, ...]:
    if only:
        names = only.split("|")
        known = {point.name() for point in points}
        for name in names:
            if name not in known:
                raise ValueError(f"no cut point named {name!r}")
        return tuple(point for point in points if point.name() in names)
    if slice_spec:
        match = re.fullmatch(r"([0-9]+)/([1-9][0-9]*)", slice_spec)
        if match is None or int(match[1]) >= int(match[2]):
            raise ValueError(f"malformed slice {slice_spec!r}, want k/n with 0 <= k < n")
        k, n = int(match[1]), int(match[2])
        return tuple(point for i, point in enumerate(sorted(points, key=CutPoint.name)) if i % n == k)
    return tuple(points)


def contained(name: str, action: Callable[[], list[str]]) -> list[str]:
    try:
        return action()
    except Exception as error:
        return [f"cut after {name}: {type(error).__name__}: {error}"]


def _event_label(event: dict) -> str:
    step, visit = event.get("step"), event.get("visit")
    if step is None:
        return event["event"]
    return f"{event['event']} {step}" if visit is None else f"{event['event']} {step}.{visit}"


def diagnose(run: StubbedRun, deliveries) -> str:
    out = []
    for directory in run.run_dirs():
        procedure = json.loads((directory / "run.json").read_text(encoding="utf-8"))["procedure"]
        out.append(f"== {procedure} {directory.name}")
        if (directory / "events.jsonl").exists():
            out.extend(_event_label(event) for event in run.events(directory)[-15:])
    for index, done in enumerate(deliveries, 1):
        out.append(f"== delivery {index}: exit {done.returncode}")
        out.extend((done.stderr or "").splitlines()[-20:])
    return "\n".join(out)


class CutSweep(Scenario):
    cuts_reached = 0

    def world(self) -> tuple[StubbedRun, str]:
        run = self.stubbed()
        return run, run.origin_tip("main")

    def reference(self) -> tuple[Outcome, tuple[CutPoint, ...]]:
        cls = type(self)
        if "_reference" not in cls.__dict__:
            started = time.monotonic()
            run, start = self.world()
            log = run.tmp / CUT_LOG_NAME
            done = deliver(run, log=log)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            result = outcome(run, start)
            self.assertEqual(result.end, "done")
            points = cut_points(log)
            self.assertEqual(len(set(points)), len(points))
            lines = sum(len(run.events(directory)) for directory in run.run_dirs())
            files = sum(1 for directory in run.run_dirs() if (directory / "results").is_dir()
                        for path in (directory / "results").iterdir() if RESULT_NAME.fullmatch(path.name))
            self.assertEqual(sum(1 for p in points if p.event != RESULT_FILE), lines)
            self.assertEqual(sum(1 for p in points if p.event == RESULT_FILE), files)
            seconds = time.monotonic() - started
            print(f"cut reference: {len(points)} cut points, {seconds:.1f} s", file=sys.stderr)
            cls.reference_seconds = seconds
            cls._reference = (result, points)
        return cls._reference

    def cut_and_continue(self, plan, expected: Outcome, *, broken: bool = False) -> tuple[str, list[str]]:
        name = ", ".join(point.name() for point in plan)
        self.cuts_reached = 0
        seen: dict = {}

        def action() -> list[str]:
            run, start = self.world()
            seen["run"] = run
            seen["deliveries"] = []
            try:
                for point in plan:
                    cut_at(run, point)
                    self.cuts_reached += 1
                deliveries, notes = continue_to_end(run, broken=broken)
                seen["deliveries"] = deliveries
                lines = judge(name, expected, outcome(run, start)) + [f"cut after {name}: {note}" for note in notes]
            except Exception:
                print(diagnose(run, seen["deliveries"]), file=sys.stderr)
                raise
            if lines:
                print(diagnose(run, deliveries), file=sys.stderr)
            return lines

        try:
            return name, contained(name, action)
        finally:
            self.doCleanups()
