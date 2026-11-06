"""Run the agent workflow suite's members, each in its own process, at most --jobs at a time (issue 436)."""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Mapping, Sequence

PREFIX = "suite-runner:"
JOBS_ENV = "SUITE_RUNNER_JOBS"
MAX_DEFAULT_JOBS = 8
# CPUs left to the host and to other agents' work when the default is derived.
RESERVED_CPUS = 2
TIMINGS_FILE = Path(__file__).with_name("suite_timings.json")
INTERRUPTED = f"{PREFIX} interrupted, waiting for running members"
INTERRUPT_EXIT = 130
# Appended to every member's GIT_CONFIG_PARAMETERS, in the form `git -c` exports
# (issue 496).
SUITE_GIT_CONFIG = "'maintenance.auto'='false' 'gc.auto'='0'"


class UsageError(ValueError):
    """A member list refused before anything starts."""


@dataclass(frozen=True)
class MemberResult:
    index: int
    member: str
    returncode: int | None
    seconds: float
    cpu_seconds: float

    @property
    def passed(self) -> bool:
        return self.returncode == 0


def default_jobs(cpu_count: int | None, environ: Mapping[str, str]) -> int:
    """The job count used when `--jobs` is not given: `SUITE_RUNNER_JOBS` when
    it is set and non-empty, else `min(8, cpu_count - 2)` with a floor of 1
    (also the value when the CPU count is unknown). A bad `SUITE_RUNNER_JOBS`
    raises `UsageError`."""
    text = environ.get(JOBS_ENV, "")
    if text:
        try:
            return _jobs(text)
        except argparse.ArgumentTypeError as error:
            raise UsageError(f"{JOBS_ENV}: {error}") from None
    return max(1, min(MAX_DEFAULT_JOBS, (cpu_count or 1) - RESERVED_CPUS))


def load_timings(path: Path = TIMINGS_FILE) -> dict[str, float]:
    """Member path to seconds from the committed timing file; empty when the
    file is missing or malformed, so scheduling falls back to list order."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    timings = {}
    for key, value in data.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        try:
            seconds = float(value)
        except OverflowError:
            continue
        if math.isfinite(seconds):
            timings[key] = seconds
    return timings


def schedule_order(members: Sequence[str], timings: Mapping[str, float]) -> list[int]:
    """Indexes of `members` in the order they start: longest-first (LPT) by
    `timings`, members the file does not name first, in list order, because
    their length is unknown, and ties in list order."""
    unknown = [i for i, member in enumerate(members) if member not in timings]
    known = [i for i, member in enumerate(members) if member in timings]
    known.sort(key=lambda i: (-timings[members[i]], i))
    return unknown + known


def member_command(member: str) -> list[str]:
    suffix = Path(member).suffix
    if suffix == ".py":
        return [sys.executable, "-m", "unittest", "-v", member]
    if suffix == ".sh":
        return ["bash", member]
    raise UsageError(f"{member}: a member must be a .py or a .sh file")


def member_environment(parent: Mapping[str, str], cache: str) -> dict[str, str]:
    """A copy of `parent` whose `GIT_CONFIG_PARAMETERS` ends with
    `SUITE_GIT_CONFIG`, so every git command run with it reads
    `maintenance.auto=false` and `gc.auto=0` (issue 496), and whose Python
    processes share the bytecode cache `cache` (issue 499).

    The entries are appended as `git -c` appends its own: after one space when
    the inherited value is non-empty, standing alone otherwise. Coming last,
    they win over an inherited entry for the same key, and a test's own
    `GIT_CONFIG_COUNT` entries still apply beside them. The inherited value is
    passed on unparsed: one git cannot parse already fails every git call with
    exit 128.

    `PYTHONPYCACHEPREFIX` is set to `cache`, replacing an inherited value, and
    an inherited `PYTHONDONTWRITEBYTECODE` is dropped, so a Python process run
    with the copy writes its bytecode under `cache` and reads what an earlier
    one wrote there. `parent` is not modified, and every other variable is
    copied unchanged.
    """
    environment = dict(parent)
    inherited = environment.get("GIT_CONFIG_PARAMETERS", "")
    environment["GIT_CONFIG_PARAMETERS"] = (
        f"{inherited} {SUITE_GIT_CONFIG}" if inherited else SUITE_GIT_CONFIG)
    environment["PYTHONPYCACHEPREFIX"] = cache
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    return environment


def validate_members(members: Sequence[str], cwd: Path) -> None:
    if not members:
        raise UsageError("no members given")
    root = cwd.resolve()
    seen: dict[Path, str] = {}
    for member in members:
        member_command(member)
        resolved = (cwd / member).resolve()
        if not resolved.is_relative_to(root):
            raise UsageError(f"{member}: lies outside the working directory")
        if not resolved.is_file():
            raise UsageError(f"{member}: is not an existing file")
        if resolved in seen:
            raise UsageError(f"{member}: duplicates {seen[resolved]}")
        seen[resolved] = member


def exit_field(returncode: int | None) -> str:
    if returncode is None:
        return "launch-error"
    if returncode < 0:
        return f"signal-{-returncode}"
    return str(returncode)


def end_line(result: MemberResult) -> str:
    state = "passed" if result.passed else "failed"
    return (f"{PREFIX} end {result.member} {state} "
            f"exit={exit_field(result.returncode)} {result.seconds:.1f}s")


def report_lines(results: Sequence[MemberResult], *, jobs: int,
                 wall_seconds: float) -> list[str]:
    ordered = sorted(results, key=lambda result: result.index)
    lines = [f"{PREFIX} timings, slowest first"]
    for result in sorted(ordered, key=lambda r: (-round(r.seconds, 1), r.index)):
        state = "passed" if result.passed else "failed"
        lines.append(f"{PREFIX} {result.seconds:7.1f}s wall "
                     f"{result.cpu_seconds:7.1f}s cpu {state} {result.member}")
    failed = [result for result in ordered if not result.passed]
    lines.extend(f"{PREFIX} failed {result.member}" for result in failed)
    lines.append(f"{PREFIX} summary members={len(ordered)} "
                 f"passed={len(ordered) - len(failed)} failed={len(failed)} "
                 f"jobs={jobs} wall={wall_seconds:.1f}s "
                 f"cpu={sum(result.cpu_seconds for result in ordered):.1f}s")
    return lines


def _line(text: str) -> bytes:
    return (text + "\n").encode()


class _Output:
    """The runner's stdout: every write is flushed at once, and `lock` orders
    the parallel workers' writes."""

    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream
        self.lock = threading.Lock()

    def write(self, data: bytes) -> None:
        self.stream.write(data)
        self.stream.flush()


class _HeldSigint:
    """Records a SIGINT instead of raising it, from construction until
    `release`, which restores the caller's handler and re-delivers a recorded
    SIGINT under it (D14). Release it inside the `try` that handles the
    interrupt. A hold over a launch or the parallel workers' start is
    constructed before that `try`, so a SIGINT just before it finds nothing
    started. A hold over a serial reap is constructed once the member has
    exited, so a SIGINT just before it finds the member exited and unreaped
    (issue 497 D2)."""

    def __init__(self) -> None:
        self.held = threading.Event()
        self.previous = signal.signal(signal.SIGINT, lambda signum, frame: self.held.set())

    def release(self) -> None:
        signal.signal(signal.SIGINT, self.previous)
        if self.held.is_set():
            signal.raise_signal(signal.SIGINT)


def _wait_exited(process: subprocess.Popen) -> None:
    """Block until the member has exited, reaping nothing: `waitid` with
    WNOWAIT leaves its status for `_reap`, so a SIGINT that interrupts this
    wait loses nothing (issue 497 D2)."""
    os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT)


def _reap(index: int, member: str, process: subprocess.Popen | None,
          started: float) -> MemberResult:
    """The member's result, reaping its process if it launched; one that never
    launched has no exit code and 0.0 CPU. One `os.wait4` on its pid is the
    only wait that reaps a member, in either mode (issue 497 D1), and its
    status is stored as the Popen's `returncode`, so nothing waits on it again.
    Its CPU seconds are the user plus system time that `wait4` reports for the
    process and every descendant reaped beneath it. The wall time runs from
    `started` to just after the reap."""
    returncode, cpu_seconds = None, 0.0
    if process is not None:
        _, status, usage = os.wait4(process.pid, 0)
        returncode = process.returncode = os.waitstatus_to_exitcode(status)
        cpu_seconds = usage.ru_utime + usage.ru_stime
    return MemberResult(index, member, returncode, time.monotonic() - started,
                        cpu_seconds)


def _run_serial(members: Sequence[str], environment: Mapping[str, str],
                out: _Output) -> list[MemberResult]:
    results = []
    for index, member in enumerate(members):
        out.write(_line(f"{PREFIX} start {member}") + _line(f"{PREFIX} begin {member}"))
        started = time.monotonic()
        process = result = None
        # A SIGINT while the member launches is held, so a launched member is
        # always waited for.
        hold = _HeldSigint()
        try:
            try:
                process = subprocess.Popen(member_command(member), env=environment)
            except OSError as error:
                out.write(_line(str(error)))
            finally:
                hold.release()
            if process is not None:
                _wait_exited(process)
            # The member has exited. A SIGINT while it is reaped is held until
            # its result is bound (issue 497 D2).
            hold = _HeldSigint()
            try:
                result = _reap(index, member, process, started)
            finally:
                hold.release()
        except KeyboardInterrupt:
            # The member shares the terminal's process group, so a Ctrl-C
            # reaches it too: wait for it, close its block, then stop. A result
            # bound before the interrupt is reported without waiting again, and
            # a further SIGINT is held until the end line is written.
            out.write(_line(INTERRUPTED))
            if result is None and process is not None:
                _wait_exited(process)
            hold = _HeldSigint()
            try:
                if result is None:
                    result = _reap(index, member, process, started)
                out.write(_line(end_line(result)))
            finally:
                hold.release()
            raise
        out.write(_line(end_line(result)))
        results.append(result)
    return results


def _run_parallel(members: Sequence[str], order: Sequence[int], jobs: int,
                  environment: Mapping[str, str], out: _Output) -> list[MemberResult | None]:
    results: list[MemberResult | None] = [None] * len(members)
    stop = threading.Event()
    next_index = 0
    running = min(jobs, len(members))
    finished = threading.Condition()

    def run_members() -> None:
        nonlocal next_index
        while True:
            # Taking a member, writing its start line and launching it share
            # the output lock: members start in `order`, and no start line
            # lands inside another member's block.
            with out.lock:
                if stop.is_set() or next_index == len(members):
                    return
                index = order[next_index]
                member = members[index]
                next_index += 1
                out.write(_line(f"{PREFIX} start {member}"))
                started = time.monotonic()
                try:
                    process = subprocess.Popen(
                        member_command(member), env=environment, stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                except OSError as error:
                    process, output = None, _line(str(error))
            if process is not None:
                # Read the merged output to its end, then reap: what
                # communicate() does for one pipe and no input. Signal handlers
                # run on the main thread only, so this reap is never
                # interrupted (issue 497 D2).
                with process.stdout:
                    output = process.stdout.read()
            result = _reap(index, member, process, started)
            if output and not output.endswith(b"\n"):
                output += b"\n"
            # One write per block, before this worker takes its next member.
            with out.lock:
                out.write(_line(f"{PREFIX} begin {member}") + output
                          + _line(end_line(result)))
            results[index] = result

    def worker() -> None:
        nonlocal running
        try:
            run_members()
        finally:
            with finished:
                running -= 1
                finished.notify_all()

    def wait_for_workers() -> None:
        # Never Thread.join(): on Python 3.12 an interrupt during join() marks
        # the running thread stopped, and the process can exit before that
        # worker writes its block.
        with finished:
            while running:
                finished.wait()

    # A SIGINT while the workers start is held, so `running` always equals
    # the workers that will count themselves out (D14).
    hold = _HeldSigint()
    try:
        try:
            for _ in range(running):
                threading.Thread(target=worker).start()
        finally:
            hold.release()
        wait_for_workers()
    except KeyboardInterrupt:
        stop.set()
        with out.lock:
            out.write(_line(INTERRUPTED))
        wait_for_workers()
        raise
    return results


def run_suite(members: Sequence[str], *, jobs: int, out: BinaryIO,
              timings: Mapping[str, float] | None = None) -> int:
    """Run every member and write the report; 0 when all passed, else 1.
    Parallel runs start members in `schedule_order(members, timings)`, serial
    runs in list order.

    A KeyboardInterrupt propagates after the running members have finished and
    written their blocks. Must be called from the main thread: the runner holds
    SIGINT while it launches or reaps a serial member or starts its parallel workers.
    Every member runs with `member_environment(os.environ, cache)`, computed
    once, where `cache` is the run's bytecode cache: a temporary directory
    created before the first launch and removed however this call ends, a
    removal error propagating (issue 499).
    """
    output = _Output(out)
    with tempfile.TemporaryDirectory(prefix="suite-runner-pycache-") as cache:
        environment = member_environment(os.environ, cache)
        started = time.monotonic()
        if jobs == 1:
            results = _run_serial(members, environment, output)
        else:
            order = schedule_order(members, timings or {})
            results = _run_parallel(members, order, jobs, environment, output)
        missing = [member for member, result in zip(members, results) if result is None]
        if missing:
            raise RuntimeError(f"members left without a result: {', '.join(missing)}")
        report = report_lines(results, jobs=jobs, wall_seconds=time.monotonic() - started)
        output.write(b"".join(_line(line) for line in report))
        return 0 if all(result.passed for result in results) else 1


def _jobs(text: str) -> int:
    try:
        jobs = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not an integer") from None
    if jobs < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is below 1")
    return jobs


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-workflow-tests",
        description="Run the agent workflow suite's members, each in its own process.")
    parser.add_argument(
        "--jobs", metavar="N", type=_jobs, default=None,
        help="run at most N members at a time; 1 runs them one at a time "
             f"with live output (default: ${JOBS_ENV} when set, else "
             f"min({MAX_DEFAULT_JOBS}, CPUs - {RESERVED_CPUS}))")
    parser.add_argument(
        "members", nargs="+", metavar="member",
        help="a test file (.py, run by unittest) or a shell script (.sh, run by bash)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.jobs is None:
        try:
            args.jobs = default_jobs(os.cpu_count(), os.environ)
        except UsageError as error:
            parser.error(str(error))
    try:
        validate_members(args.members, Path.cwd())
    except UsageError as error:
        parser.error(str(error))
    try:
        return run_suite(args.members, jobs=args.jobs, out=sys.stdout.buffer,
                         timings=load_timings())
    except KeyboardInterrupt:
        return INTERRUPT_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
