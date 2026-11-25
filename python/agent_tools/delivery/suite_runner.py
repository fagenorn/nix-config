"""Run the agent workflow suite's members, each in its own process, at most --jobs at a time (issue 436).

`just agent-workflow-tests` hands its curated member list to this module
(`python -m agent_tools.delivery.suite_runner`; it has no command-table row). Each member runs from
the working directory with the recipe's environment plus two git configuration entries and
the run's bytecode cache: a `.py` member as `python -m unittest -v <path>`, a `.sh` member
as `bash <path>`.

Git entries (issue 496). `maintenance.auto=false` and `gc.auto=0` are appended to
`GIT_CONFIG_PARAMETERS` in the form `git -c` exports (`member_environment`), so a commit or
a fetch in a test's repository starts no detached `git maintenance run --auto`, which would
create `.git/objects/maintenance.lock` while the test reads that repository. Every git
command that inherits a member's environment, at any depth, reads them as if given
`git -c maintenance.auto=false -c gc.auto=0`: they win over an inherited entry, a test's own
`GIT_CONFIG_COUNT` entry and any config file for the same key, a test's other count entries
still apply, and a `git -c` option a command adds comes after them and wins. The entries do
not reach a process started with an environment built from scratch or with its own
`GIT_CONFIG_PARAMETERS`, nor the receive-pack of a push to a local repository, so that
receiving repository still runs automatic maintenance.

Scratch directory (issue 1283). Members write their temporary files where `TMPDIR` points.
Unless `SUITE_RUNNER_SCRATCH` says otherwise the runner creates one `suite-runner-tmp-*`
directory per run under `/dev/shm` when that is a directory with 2 GiB free where a script
runs (`usable_memory_root`: a `noexec` mount would make tests skip their fake commands), sets every member's
`TMPDIR` to it and removes it when the run ends, so a test's files, forced flushes included,
stay in memory. `SUITE_RUNNER_SCRATCH=disk` keeps the inherited `TMPDIR`; any other value is the
directory the run's scratch directory is created in. A host without `/dev/shm` runs as before.
A run killed before its cleanup leaves its directory; the next run removes this user's
`suite-runner-tmp-*` directories there that are a day old (`sweep_stale_scratch`).

Bytecode cache (issue 499). It is one directory per run. Before the first member starts the
runner creates a `suite-runner-pycache-*` directory in the default temporary directory, sets
`PYTHONPYCACHEPREFIX` to it, replacing an inherited value, and drops an inherited
`PYTHONDONTWRITEBYTECODE` (`member_environment`). Every Python process that inherits a
member's environment, at any depth, writes the bytecode of the source modules it imports
there, under each source's absolute path, and reads what an earlier process of the same run
wrote instead of compiling again. Parallel writers need no coordination: CPython writes each
file under a temporary name and renames it into place, and skips a write it cannot make. The
prefix redirects every bytecode lookup, the standard library's included, so a run compiles
the standard-library source modules its processes import instead of reading the
interpreter's own bytecode, and its later processes read that result. The cache does not reach
a process started with an environment built from scratch, nor one run with `-I` or `-E`.
CPython takes a cached file as current while its source's modification time, in whole
seconds, and its size match, so a test that rewrites an importable source in place to the
same size within one second, then imports it in a new process, gives that process its own
`PYTHONPYCACHEPREFIX` directory. Outside the runner, as in a direct `python -m unittest`
run, a test's Python children write bytecode beside their sources where those are writable.
A script run as a main file is compiled on every start. The runner removes
the directory when the run ends, after the report, after an interrupted run has waited for
its members, or on an error, and a failure to remove it is raised, never ignored. A
descendant still running after the run ends may recreate part of the removed directory.

Jobs and order (issue 604). At most `--jobs N` members run at once. The default is
`SUITE_RUNNER_JOBS` when that variable is set and non-empty, else `min(8, CPUs - 2)` with a
floor of 1 (also when the CPU count is unknown); an explicit `--jobs` wins over both, and a
bad `SUITE_RUNNER_JOBS` is a usage error (exit 2); the hosted CI job sets it to 4, the vCPUs
of its runner (`.github/workflows/ci.yaml:101`). In parallel mode members start
longest-first (LPT): the order comes from `python/agent_tools/delivery/suite_timings.json`, a
committed map of member path to wall seconds taken from a full run's timing table, with
members it does not name starting first in list order, ties in list order, and a missing or
malformed file meaning list order. Serial mode keeps list order, and the report stays in
list order for ties. Refresh the file from a run's `suite-runner: <wall>s wall ... <member>`
rows when the suite's shape changes. Every completed run checks the file against what it
measured, and a stale file fails the run (exit 1) with a `suite-runner: stale timing` line per
member. A checked member passed, took more than `STALE_FLOOR_SECONDS` (30 s) and, when the
justfile's suite recipe is readable (`registered_members`), is registered there, so a paired
test the recipe does not list runs and is reported but is never checked. It is stale when the file
does not name it, or names it at under a third of its time: more than `STALE_FACTOR` (3) times
its recorded seconds times the run's speed. The speed is suite_timing's `median_speed` of the
other passed members' measured seconds over their recorded seconds, so a member never sets its
own speed, a failed member never sets it, and a uniformly slower host is not stale.

Output. In parallel mode each member's stdout and stderr are captured together and printed
as one block when it exits, from `suite-runner: begin <member>` to
`suite-runner: end <member> passed|failed exit=<code> <seconds>s`. A
`suite-runner: start <member>` line marks each launch, so a run cut off by a time limit names
the members still running. `--jobs 1` is serial mode: members run one at a time with stdin,
stdout and stderr passed straight through, for a hang or a `breakpoint()`.

Verdict. A member passes only on exit 0. Unittest's exit 5 for a module that ran no tests, a
death by signal (`exit=signal-<n>`) and a failure to launch (`exit=launch-error`) all fail
it, and every member still runs after a failure.

Timing table. Every completed run ends with one
`suite-runner: <wall>s wall <cpu>s cpu passed|failed <member>` row per member, slowest first
with ties in list order, then one `suite-runner: failed <member>` line per failure, one `suite-runner: stale timing
<member>: <seconds>s measured, not in suite_timings.json` or `... <seconds>s measured,
<recorded>s recorded at runner speed <factor>` line per stale member, in list order, and
`suite-runner: summary members=<n> passed=<p> failed=<f> jobs=<N> wall=<seconds>s cpu=<seconds>s`.
A row's CPU figure is the member's child CPU time: the user plus system seconds in the
resource usage that `os.wait4` returns when the runner reaps the member. That covers the
member's own process and every descendant that it, or a descendant in between, waited for,
such as the `git` and `python -m agent_tools.…` processes a test runs. A descendant still
running when the member exits, or never waited for, is not counted, and a member that failed
to launch shows `0.0`. The summary's `cpu=` adds up the members' unrounded figures and never
the runner's own CPU, so rounding can make it differ from the sum of the printed rows. A
member whose CPU is close to its wall time, or above it when its descendants ran at once, was
computing. One far below it was waiting, for I/O, a sleep or a CPU it could not get. Set
`cpu=` against `wall=` times the CPUs the run could use, the smaller of `--jobs` and the
host's CPUs. Near it, every slot was computing and the CPUs were saturated; well below it,
the members were waiting on something else. A module whose CPU grows from a `--jobs 1` run to
a parallel one ran on slower, shared CPUs.

Timing report (issue 1385, ADR-delivery-015). When `SUITE_RUNNER_REPORT` names a path,
relative to the working directory, every completed run also writes the report there as JSON
after the timing table, whether it passed or failed. The keys are `version` (1), `members`,
`passed`, `failed`, `jobs`, `wall_seconds`, `member_seconds`, `cpu_seconds`,
`idle_tail_seconds` and `timings`, one `{member, seconds, cpu_seconds, passed}` per member,
slowest first by unrounded `seconds`, which a tie leaves in list order. The `idle_tail_seconds`
figure is the time from the first worker that ran its last member to the last member's end:
the latest of each worker's last end minus the earliest of them, 0.0 with one worker, rounded
to 0.1 s. The `wall_seconds` and `cpu_seconds` figures are the summary's, rounded to 0.1 s; `member_seconds` and each member's `seconds` keep full precision,
so a comparison of two reports sees growth the table's rounding hides. The file is written whole through a temporary
file in its directory, and the parent directories are created. Members do not inherit the
variable. An unwritable path raises, and an empty or unset value writes nothing.

Exits. 0 means every member passed and no timing is stale, and 1 that one failed or one is
stale. 2 is a usage error, raised before
anything starts: a bad `--jobs`, no members, a duplicate, a member that is missing, is not a
file or lies outside the working directory, or a suffix other than `.py` or `.sh`. 130 is an
interrupt: the runner starts nothing more, prints `suite-runner: interrupted, waiting for
running members`, waits for those members and prints no report.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Collection, Mapping, Sequence

from agent_tools.delivery.suite_timing import median_speed

PREFIX = "suite-runner:"
JOBS_ENV = "SUITE_RUNNER_JOBS"
MAX_DEFAULT_JOBS = 8
# CPUs left to the host and to other agents' work when the default is derived.
RESERVED_CPUS = 2
# The path of the JSON timing report, relative to the working directory (issue 1385).
REPORT_ENV = "SUITE_RUNNER_REPORT"
REPORT_VERSION = 1
TIMINGS_FILE = Path(__file__).with_name("suite_timings.json")
# A passed member over this many seconds is checked against the timings file, and is stale
# when its time is over this factor times its recorded seconds at the run's speed.
STALE_FLOOR_SECONDS = 30.0
STALE_FACTOR = 3.0
INTERRUPTED = f"{PREFIX} interrupted, waiting for running members"
INTERRUPT_EXIT = 130
# Where the members' temporary files go (issue 1283): unset picks MEMORY_ROOT when it is a
# writable directory, `disk` keeps the inherited TMPDIR, any other value names the directory.
SCRATCH_ENV = "SUITE_RUNNER_SCRATCH"
SCRATCH_DISK = "disk"
MEMORY_ROOT = "/dev/shm"
SCRATCH_PREFIX = "suite-runner-tmp-"
# The default is taken only with this much free there: a full memory directory fails writes
# the disk would have taken.
SCRATCH_FREE_BYTES = 2 * 1024 ** 3
SCRATCH_STALE_SECONDS = 24 * 3600
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
    ended: float = 0.0
    slot: int = 0

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


SUITE_RECIPE = "agent-workflow-tests *args:"


def suite_members(justfile_text: str) -> list[str]:
    """The suite's members: the recipe `SUITE_RECIPE` is their registration, one per line after the runner line."""
    lines = justfile_text.splitlines()
    if SUITE_RECIPE not in lines:
        raise ValueError(f"justfile has no {SUITE_RECIPE!r} recipe")
    body: list[str] = []
    for line in lines[lines.index(SUITE_RECIPE) + 1:]:
        if not line.startswith("  "):
            break
        body.append(line.strip().removesuffix(" \\"))
    return body[1:]


def registered_members(root: Path) -> list[str] | None:
    """The suite registration of `root`'s justfile; None when it cannot be read or has no
    suite recipe."""
    try:
        return suite_members((root / "justfile").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


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
    one wrote there. An inherited `AGENT_PLATFORM_ROOT` is dropped: the suite
    runs from source, so a member never inherits a platform package's root
    (ADR-system-005). An inherited `REPORT_ENV` is dropped too, so a runner nested in a
    member never writes to the outer run's report path (issue 1385). `parent` is not modified, and every other variable is
    copied unchanged.
    """
    environment = dict(parent)
    environment.pop("AGENT_PLATFORM_ROOT", None)
    environment.pop(REPORT_ENV, None)
    inherited = environment.get("GIT_CONFIG_PARAMETERS", "")
    environment["GIT_CONFIG_PARAMETERS"] = (
        f"{inherited} {SUITE_GIT_CONFIG}" if inherited else SUITE_GIT_CONFIG)
    environment["PYTHONPYCACHEPREFIX"] = cache
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    return environment


def scratch_root(environ: Mapping[str, str], memory_root: str = MEMORY_ROOT) -> str | None:
    """The directory a run's scratch directory is created in, None to keep the inherited TMPDIR.

    `SUITE_RUNNER_SCRATCH` decides: `disk` is None; any other non-empty value is that directory
    as an absolute path, so a nested runner started from another directory finds it; unset or
    empty is `memory_root` when `usable_memory_root` accepts it, else None (issue 1283: the
    suite's forced flushes kept the host's disk busy, and a file in memory costs no flush).
    """
    choice = environ.get(SCRATCH_ENV, "")
    if choice == SCRATCH_DISK:
        return None
    if choice:
        return os.path.abspath(choice)
    return memory_root if usable_memory_root(memory_root) else None


def usable_memory_root(root: str, free_bytes: int = SCRATCH_FREE_BYTES) -> bool:
    """Whether the suite can use `root` for its files without changing what a test sees.

    It must be a directory with at least `free_bytes` free, and a script written there must
    run: members put fake commands in their temporary directories ahead of `PATH`, and on a
    `noexec` mount the shell would skip them and run the host's real commands. Any error is
    False.
    """
    try:
        usage = os.statvfs(root)
        if usage.f_bavail * usage.f_frsize < free_bytes:
            return False
        with tempfile.TemporaryDirectory(prefix="suite-runner-probe-", dir=root) as probe:
            script = os.path.join(probe, "probe")
            with open(script, "w", encoding="utf-8") as handle:
                handle.write("#!/bin/sh\nexit 0\n")
            os.chmod(script, 0o700)
            return _runs(script)
    except OSError:
        return False


def _runs(script: str) -> bool:
    """Whether the kernel executes `script`. It is spawned directly, not through `subprocess`,
    whose launches the runner counts and guards against SIGINT for its members."""
    pid = os.posix_spawn(script, [script], {})
    return os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]) == 0


def sweep_stale_scratch(root: str, now: float, older_than: float = SCRATCH_STALE_SECONDS) -> None:
    """Remove this user's `suite-runner-tmp-*` directories in `root` not modified for
    `older_than` seconds: what a run killed before its cleanup left behind. Errors are ignored."""
    try:
        entries = list(os.scandir(root))
    except OSError:
        return
    for entry in entries:
        try:
            status = entry.stat(follow_symlinks=False)
            if (entry.name.startswith(SCRATCH_PREFIX) and entry.is_dir(follow_symlinks=False)
                    and status.st_uid == os.getuid() and now - status.st_mtime >= older_than):
                shutil.rmtree(entry.path, ignore_errors=True)
        except OSError:
            continue


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


def idle_tail(results: Sequence[MemberResult]) -> float:
    """The latest of each slot's last end minus the earliest of them, over the slots that
    ran a member; 0.0 with one slot."""
    last_end: dict[int, float] = {}
    for result in results:
        last_end[result.slot] = max(result.ended, last_end.get(result.slot, result.ended))
    return max(last_end.values()) - min(last_end.values()) if last_end else 0.0


def stale_timings(results: Sequence[MemberResult], timings: Mapping[str, float],
                  registered: Collection[str] | None = None) -> list[str]:
    """One line per checked member, in list order, whose time `timings` does not name or
    understates by more than `STALE_FACTOR` at the run's speed. A checked member passed,
    took over `STALE_FLOOR_SECONDS` and, when `registered` is given, is in it. A member's
    speed is `median_speed` of the other passed members, so it never sets its own."""
    ordered = sorted(results, key=lambda result: result.index)
    passed = [result for result in ordered if result.passed]
    lines = []
    for result in passed:
        if result.seconds <= STALE_FLOOR_SECONDS:
            continue
        if registered is not None and result.member not in registered:
            continue
        if result.member not in timings:
            lines.append(f"{PREFIX} stale timing {result.member}: {result.seconds:.1f}s "
                         "measured, not in suite_timings.json")
            continue
        factor = median_speed(timings, [(other.member, other.seconds) for other in passed
                                        if other.index != result.index])
        recorded = timings[result.member]
        if result.seconds > STALE_FACTOR * factor * recorded:
            lines.append(f"{PREFIX} stale timing {result.member}: {result.seconds:.1f}s "
                         f"measured, {recorded:.1f}s recorded at runner speed {factor:.2f}")
    return lines


def report_lines(results: Sequence[MemberResult], *, jobs: int,
                 wall_seconds: float, stale: Sequence[str] = ()) -> list[str]:
    ordered = sorted(results, key=lambda result: result.index)
    lines = [f"{PREFIX} timings, slowest first"]
    for result in sorted(ordered, key=lambda r: (-round(r.seconds, 1), r.index)):
        state = "passed" if result.passed else "failed"
        lines.append(f"{PREFIX} {result.seconds:7.1f}s wall "
                     f"{result.cpu_seconds:7.1f}s cpu {state} {result.member}")
    failed = [result for result in ordered if not result.passed]
    lines.extend(f"{PREFIX} failed {result.member}" for result in failed)
    lines.extend(stale)
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
          started: float, slot: int = 0) -> MemberResult:
    """The member's result, reaping its process if it launched; one that never
    launched has no exit code and 0.0 CPU. One `os.wait4` on its pid is the
    only wait that reaps a member, in either mode (issue 497 D1), and its
    status is stored as the Popen's `returncode`, so nothing waits on it again.
    Its CPU seconds are the user plus system time that `wait4` reports for the
    process and every descendant reaped beneath it. The wall time runs from
    `started` to just after the reap, and `ended` is the clock's value there."""
    returncode, cpu_seconds = None, 0.0
    if process is not None:
        _, status, usage = os.wait4(process.pid, 0)
        returncode = process.returncode = os.waitstatus_to_exitcode(status)
        cpu_seconds = usage.ru_utime + usage.ru_stime
    now = time.monotonic()
    return MemberResult(index, member, returncode, now - started, cpu_seconds, now, slot)


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

    def run_members(slot: int) -> None:
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
            result = _reap(index, member, process, started, slot)
            if output and not output.endswith(b"\n"):
                output += b"\n"
            # One write per block, before this worker takes its next member.
            with out.lock:
                out.write(_line(f"{PREFIX} begin {member}") + output
                          + _line(end_line(result)))
            results[index] = result

    def worker(slot: int) -> None:
        nonlocal running
        try:
            run_members(slot)
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
            for slot in range(running):
                threading.Thread(target=worker, args=(slot,)).start()
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


def timing_report(results: Sequence[MemberResult], *, jobs: int,
                  wall_seconds: float) -> dict:
    """The JSON-ready report of a completed run: the summary's figures of `report_lines`, but
    member times unrounded and rows slowest first by those times."""
    ordered = sorted(results, key=lambda result: result.index)
    failed = sum(1 for result in ordered if not result.passed)
    rows = sorted(ordered, key=lambda r: (-r.seconds, r.index))
    return {
        "version": REPORT_VERSION,
        "members": len(ordered),
        "passed": len(ordered) - failed,
        "failed": failed,
        "jobs": jobs,
        "wall_seconds": round(wall_seconds, 1),
        "member_seconds": sum(result.seconds for result in ordered),
        "cpu_seconds": round(sum(result.cpu_seconds for result in ordered), 1),
        "idle_tail_seconds": round(idle_tail(ordered), 1),
        "timings": [{"member": result.member, "seconds": result.seconds,
                     "cpu_seconds": round(result.cpu_seconds, 1), "passed": result.passed}
                    for result in rows],
    }


def write_report(path: Path, report: dict) -> None:
    """Write `report` to `path` whole: the parent directories are created and the JSON goes
    to a temporary file beside `path`, which replaces it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(report, indent=2) + "\n")
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def run_suite(members: Sequence[str], *, jobs: int, out: BinaryIO,
              timings: Mapping[str, float] | None = None,
              registered: Collection[str] | None = None) -> int:
    """Run every member and write the report; 0 when all passed and no timing is stale
    (`stale_timings` against `timings` and `registered`), else 1.
    Parallel runs start members in `schedule_order(members, timings)`, serial
    runs in list order.

    A KeyboardInterrupt propagates after the running members have finished and
    written their blocks. Must be called from the main thread: the runner holds
    SIGINT while it launches or reaps a serial member or starts its parallel workers.
    Every member runs with `member_environment(os.environ, cache)`, computed
    once, where `cache` is the run's bytecode cache: a temporary directory
    created before the first launch and removed however this call ends, a
    removal error propagating (issue 499). When `scratch_root(os.environ)` names a
    directory, every member's `TMPDIR` is a `suite-runner-tmp-*` directory created there
    for the run and removed the same way (issue 1283); otherwise `TMPDIR` is inherited.
    When `REPORT_ENV` is non-empty, its value is resolved against the working directory
    before the first member starts, and after the report lines `write_report` writes the
    timing report there; an `OSError` propagates (issue 1385).
    """
    output = _Output(out)
    report_value = os.environ.get(REPORT_ENV, "")
    report_path = Path.cwd() / report_value if report_value else None
    root = scratch_root(os.environ)
    with tempfile.TemporaryDirectory(prefix="suite-runner-pycache-") as cache, \
            contextlib.ExitStack() as stack:
        environment = member_environment(os.environ, cache)
        if root is not None:
            sweep_stale_scratch(root, time.time())
            environment["TMPDIR"] = stack.enter_context(
                tempfile.TemporaryDirectory(prefix=SCRATCH_PREFIX, dir=root))
        started = time.monotonic()
        if jobs == 1:
            results = _run_serial(members, environment, output)
        else:
            order = schedule_order(members, timings or {})
            results = _run_parallel(members, order, jobs, environment, output)
        missing = [member for member, result in zip(members, results) if result is None]
        if missing:
            raise RuntimeError(f"members left without a result: {', '.join(missing)}")
        wall = time.monotonic() - started
        stale = stale_timings(results, timings or {}, registered)
        report = report_lines(results, jobs=jobs, wall_seconds=wall, stale=stale)
        output.write(b"".join(_line(line) for line in report))
        if report_path is not None:
            write_report(report_path, timing_report(results, jobs=jobs, wall_seconds=wall))
        return 0 if all(result.passed for result in results) and not stale else 1


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
                         timings=load_timings(), registered=registered_members(Path.cwd()))
    except KeyboardInterrupt:
        return INTERRUPT_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
