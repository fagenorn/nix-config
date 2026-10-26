"""Run the agent workflow suite's members, each in its own process, at most --jobs at a time (issue 436)."""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Sequence

PREFIX = "suite-runner:"
DEFAULT_JOBS = 4
INTERRUPTED = f"{PREFIX} interrupted, waiting for running members"
INTERRUPT_EXIT = 130


class UsageError(ValueError):
    """A member list refused before anything starts."""


@dataclass(frozen=True)
class MemberResult:
    index: int
    member: str
    returncode: int | None
    seconds: float

    @property
    def passed(self) -> bool:
        return self.returncode == 0


def member_command(member: str) -> list[str]:
    suffix = Path(member).suffix
    if suffix == ".py":
        return [sys.executable, "-m", "unittest", "-v", member]
    if suffix == ".sh":
        return ["bash", member]
    raise UsageError(f"{member}: a member must be a .py or a .sh file")


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
        lines.append(f"{PREFIX} {result.seconds:7.1f}s {state} {result.member}")
    failed = [result for result in ordered if not result.passed]
    lines.extend(f"{PREFIX} failed {result.member}" for result in failed)
    lines.append(f"{PREFIX} summary members={len(ordered)} "
                 f"passed={len(ordered) - len(failed)} failed={len(failed)} "
                 f"jobs={jobs} wall={wall_seconds:.1f}s")
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
    SIGINT under it (D14). Construct it before the `try` that handles the
    interrupt and release it inside that `try`, so a SIGINT on either side of
    the held span reaches that handler or nothing has started yet."""

    def __init__(self) -> None:
        self.held = threading.Event()
        self.previous = signal.signal(signal.SIGINT, lambda signum, frame: self.held.set())

    def release(self) -> None:
        signal.signal(signal.SIGINT, self.previous)
        if self.held.is_set():
            signal.raise_signal(signal.SIGINT)


def _run_serial(members: Sequence[str], out: _Output) -> list[MemberResult]:
    results = []
    for index, member in enumerate(members):
        out.write(_line(f"{PREFIX} start {member}") + _line(f"{PREFIX} begin {member}"))
        started = time.monotonic()
        process = None
        # A SIGINT while the member launches is held, so a launched member is
        # always waited for.
        hold = _HeldSigint()
        try:
            try:
                process = subprocess.Popen(member_command(member))
            except OSError as error:
                out.write(_line(str(error)))
            finally:
                hold.release()
            returncode = None if process is None else process.wait()
        except KeyboardInterrupt:
            # The member shares the terminal's process group, so a Ctrl-C
            # reaches it too: wait for it, close its block, then stop.
            out.write(_line(INTERRUPTED))
            returncode = None if process is None else process.wait()
            out.write(_line(end_line(MemberResult(
                index, member, returncode, time.monotonic() - started))))
            raise
        result = MemberResult(index, member, returncode, time.monotonic() - started)
        out.write(_line(end_line(result)))
        results.append(result)
    return results


def _run_parallel(members: Sequence[str], jobs: int,
                  out: _Output) -> list[MemberResult | None]:
    results: list[MemberResult | None] = [None] * len(members)
    stop = threading.Event()
    next_index = 0
    running = min(jobs, len(members))
    finished = threading.Condition()

    def run_members() -> None:
        nonlocal next_index
        while True:
            # Taking a member, writing its start line and launching it share
            # the output lock: members start in list order, and no start line
            # lands inside another member's block.
            with out.lock:
                if stop.is_set() or next_index == len(members):
                    return
                index, member = next_index, members[next_index]
                next_index += 1
                out.write(_line(f"{PREFIX} start {member}"))
                started = time.monotonic()
                try:
                    process = subprocess.Popen(
                        member_command(member), stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                except OSError as error:
                    process, output = None, _line(str(error))
            if process is not None:
                output, _ = process.communicate()
            result = MemberResult(
                index, member, None if process is None else process.returncode,
                time.monotonic() - started)
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


def run_suite(members: Sequence[str], *, jobs: int, out: BinaryIO) -> int:
    """Run every member and write the report; 0 when all passed, else 1.

    A KeyboardInterrupt propagates after the running members have finished and
    written their blocks. Must be called from the main thread: the runner holds
    SIGINT while it launches a serial member or starts its parallel workers.
    """
    output = _Output(out)
    started = time.monotonic()
    if jobs == 1:
        results = _run_serial(members, output)
    else:
        results = _run_parallel(members, jobs, output)
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
        "--jobs", metavar="N", type=_jobs, default=DEFAULT_JOBS,
        help="run at most N members at a time; 1 runs them one at a time "
             "with live output (default: %(default)s)")
    parser.add_argument(
        "members", nargs="+", metavar="member",
        help="a test file (.py, run by unittest) or a shell script (.sh, run by bash)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        validate_members(args.members, Path.cwd())
    except UsageError as error:
        parser.error(str(error))
    try:
        return run_suite(args.members, jobs=args.jobs, out=sys.stdout.buffer)
    except KeyboardInterrupt:
        return INTERRUPT_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
