# Task 1: `agent_tools.suite_runner` and its end-to-end tests

Spec § Solution, § Decisions (D1, D2, D4–D6) and § Test seams (D9), with the output details of D11 and the interrupt handling of D12. A new module runs a list of suite members (test files and shell scripts) as child processes, at most `--jobs` at a time. It prints each member's output as one block and ends with a timing report. This task does not touch the `justfile`: Task 2 wires the recipe.

**Files:**
- Create: `python/agent_tools/suite_runner.py`
- Create: `tests/test_suite_runner.py`
- Modify: `python/README.md` (one new section after `## lane-triage`)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces, in `agent_tools.suite_runner` (Task 2 imports `validate_members` and `UsageError`):
  - `PREFIX = "suite-runner:"` and `DEFAULT_JOBS = 4`.
  - `class UsageError(ValueError)`: a member list refused before anything starts.
  - `@dataclass(frozen=True) class MemberResult` with the fields `index: int` (position in the member list), `member: str` (the path exactly as given), `returncode: int | None` (`None` when the member never launched; negative `-n` for death by signal `n`) and `seconds: float`, plus the property `passed -> bool`, which is `returncode == 0`.
  - `member_command(member: str) -> list[str]`: `[sys.executable, "-m", "unittest", "-v", member]` for a `.py` suffix and `["bash", member]` for `.sh`. Any other suffix raises `UsageError` (D2: a closed set that fails loud).
  - `validate_members(members: Sequence[str], cwd: Path) -> None`, which raises `UsageError` for each D4 member error.
  - `exit_field(returncode: int | None) -> str`, `end_line(result: MemberResult) -> str` and `report_lines(results: Sequence[MemberResult], *, jobs: int, wall_seconds: float) -> list[str]`.
  - `run_suite(members: Sequence[str], *, jobs: int, out: BinaryIO) -> int` returns 0 or 1. A `KeyboardInterrupt` propagates out of it.
  - `main(argv: Sequence[str] | None = None) -> int`, behind `if __name__ == "__main__": raise SystemExit(main())`.

**Invariants:**
- Output wire format (D6, D11). Every runner line goes to stdout as bytes, flushed at once, and starts `suite-runner: `:
  - `start <member>` is written when a member is launched, before `Popen`.
  - `begin <member>` comes next, then the member's output, then `end <member> <passed|failed> exit=<field> <seconds:.1f>s`. `<field>` is `exit_field`: the exit code; `signal-<n>` for death by signal `n`; or `launch-error` when `Popen` raised `OSError`. In that last case the error's `str()` plus a newline is the block's output.
  - The report: `timings, slowest first`; then one row per member, `f"{PREFIX} {seconds:7.1f}s {passed|failed} {member}"`, sorted by `(-round(seconds, 1), index)`; then `failed <member>` for each failed member in list order; then `summary members=<n> passed=<p> failed=<f> jobs=<jobs> wall=<wall:.1f>s`. `report_lines` sorts by `index` itself, so it accepts results in any order.
- Parallel mode (`jobs` ≥ 2). Worker threads take members in list order. Under one output lock a worker writes the `start` line and calls `Popen`, with stdin `DEVNULL` and stderr merged into one stdout pipe. It collects the output with `communicate()`. It then writes `begin` + output + `end` as **one** write under the same lock, adding a newline before `end` only when the output does not end with one, and only then takes its next member. So no runner line lands inside a block, and the start/end sequence never shows more than `jobs` members open.
- Serial mode (`jobs` == 1). For each member the runner writes `start` and `begin`, then runs `Popen(member_command(member))` with stdin, stdout and stderr inherited, then writes `end`. Its own writes are flushed before each launch, so its lines and the member's stdout keep their order.
- Every member runs after a failure. Exit 0 means every member passed and 1 means one failed. If a member is left without a result (a worker raised), `run_suite` raises `RuntimeError` naming those members rather than report a run that skipped them.
- Exit 2 comes from `parser.error`, so stderr reads `agent-workflow-tests: error: …`, before any member starts: a malformed or `< 1` `--jobs` (an `argparse` type function), no members (`nargs="+"`), or a `validate_members` refusal.
- `validate_members` refuses an empty list, an unknown suffix (through `member_command`), a member whose `(cwd / member).resolve()` is not inside `cwd.resolve()`, one that is not an existing regular file, and a duplicate compared on the resolved path.
- Interrupt (D12). A `KeyboardInterrupt` in the main thread sets a stop flag that workers check under the lock before taking a member. The runner then writes `suite-runner: interrupted, waiting for running members` and waits for the running members, whose blocks and `end` lines are still written. `main` returns 130 with no report. The main thread waits on a `threading.Condition` that counts running workers, **never** on `Thread.join()`. On Python 3.12 a `KeyboardInterrupt` during `join()` of a running thread marks that thread stopped, and the process can then exit before the worker writes its block.
- `--help` starts `usage: agent-workflow-tests ` and documents the default as `(default: 4)`, through `%(default)s` from `DEFAULT_JOBS`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_suite_runner.py` with exactly this content:

```python
"""End-to-end tests for `agent_tools.suite_runner`, the scheduler behind
`just agent-workflow-tests` (issue 436).

Every case but the report-ordering one runs `python -m agent_tools.suite_runner`
in a temporary working directory over fixture members written there. Members
that must overlap meet at a filesystem barrier instead of sleeping, so no
assertion depends on how long anything took (D9).
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from agent_tools import suite_runner
from agent_tools.suite_runner import MemberResult

# A unittest module that meets its peers at the barrier. It holds a live token
# until `min(cap, members not yet done)` tokens are live, writes three stdout
# and three stderr markers while that token is still live, and records the most
# live tokens it ever counted. A member whose name starts `test_fail` then fails.
BARRIER_MEMBER = textwrap.dedent('''\
    import os
    import sys
    import time
    import unittest
    from pathlib import Path

    BARRIER = Path(os.environ["SUITE_RUNNER_TEST_BARRIER"])
    CAP = int(os.environ["SUITE_RUNNER_TEST_CAP"])
    TOTAL = int(os.environ["SUITE_RUNNER_TEST_TOTAL"])
    NAME = Path(__file__).name


    def count(state):
        return len(list((BARRIER / state).iterdir()))


    class Member(unittest.TestCase):
        def test_member(self):
            token = BARRIER / "live" / NAME
            token.touch()
            seen = 0
            deadline = time.monotonic() + 60
            while True:
                live = count("live")
                seen = max(seen, live)
                if live >= min(CAP, TOTAL - count("done")):
                    break
                if time.monotonic() > deadline:
                    self.fail(f"{NAME}: the barrier was not met within 60 s")
                time.sleep(0.01)
            for n in range(3):
                print(f"marker {NAME} stdout {n}", flush=True)
                print(f"marker {NAME} stderr {n}", file=sys.stderr, flush=True)
                seen = max(seen, count("live"))
            (BARRIER / "seen" / NAME).write_text(str(seen))
            token.unlink()
            (BARRIER / "done" / NAME).touch()
            if NAME.startswith("test_fail"):
                self.fail(f"{NAME}: deliberate failure")
''')

# A unittest module that holds a live token until the test creates `release`.
HOLD_MEMBER = textwrap.dedent('''\
    import os
    import time
    import unittest
    from pathlib import Path

    BARRIER = Path(os.environ["SUITE_RUNNER_TEST_BARRIER"])
    NAME = Path(__file__).name


    class Member(unittest.TestCase):
        def test_member(self):
            token = BARRIER / "live" / NAME
            token.touch()
            deadline = time.monotonic() + 60
            while not (BARRIER / "release").exists():
                if time.monotonic() > deadline:
                    self.fail(f"{NAME}: never released")
                time.sleep(0.01)
            token.unlink()
            (BARRIER / "done" / NAME).touch()
''')

PLAIN_MEMBER = textwrap.dedent('''\
    import unittest


    class Member(unittest.TestCase):
        def test_member(self):
            pass
''')

RUNNER_LINE = re.compile(r"^suite-runner: ")
START = re.compile(r"^suite-runner: start (\S+)$")
END = re.compile(r"^suite-runner: end (\S+) (passed|failed) exit=(\S+) \d+\.\ds$")
ROW = re.compile(r"^suite-runner: +(\d+\.\d)s (passed|failed) (\S+)$")
SUMMARY = re.compile(r"^suite-runner: summary members=(\d+) passed=(\d+) failed=(\d+) "
                     r"jobs=(\d+) wall=\d+\.\ds$")


class RunnerCase(unittest.TestCase):
    def setUp(self) -> None:
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        root = Path(raw.name).resolve()
        self.work = root / "work"
        self.barrier = root / "barrier"
        self.work.mkdir()
        for state in ("live", "done", "seen"):
            (self.barrier / state).mkdir(parents=True)

    def member(self, name: str, source: str) -> str:
        (self.work / name).write_text(source, encoding="utf-8")
        return name

    def barrier_members(self, *names: str) -> list[str]:
        return [self.member(name, BARRIER_MEMBER) for name in names]

    def environment(self, cap: int, total: int, extra: dict) -> dict:
        return {**os.environ, "SUITE_RUNNER_TEST_BARRIER": str(self.barrier),
                "SUITE_RUNNER_TEST_CAP": str(cap), "SUITE_RUNNER_TEST_TOTAL": str(total),
                **extra}

    def run_suite(self, *args: str, cap: int = 1, total: int = 1,
                  env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.suite_runner", *args],
            cwd=self.work, env=self.environment(cap, total, env or {}),
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300,
            check=False)

    def seen(self) -> dict[str, int]:
        return {path.name: int(path.read_text())
                for path in (self.barrier / "seen").iterdir()}

    def nothing_started(self) -> bool:
        return not any(any((self.barrier / state).iterdir())
                       for state in ("live", "done", "seen"))

    @staticmethod
    def most_open(stdout: str) -> int:
        open_now = most = 0
        for line in stdout.splitlines():
            if START.match(line):
                open_now += 1
                most = max(most, open_now)
            elif END.match(line):
                open_now -= 1
        return most

    @staticmethod
    def block(stdout: str, member: str) -> tuple[list[str], str]:
        """The lines strictly between `member`'s begin and end lines, and that end line."""
        lines = stdout.splitlines()
        begin = lines.index(f"suite-runner: begin {member}")
        end = next(index for index in range(begin + 1, len(lines))
                   if lines[index].startswith(f"suite-runner: end {member} "))
        return lines[begin + 1:end], lines[end]


class FailureIsolationTest(RunnerCase):
    def test_a_failing_member_fails_the_run_and_keeps_its_output_in_one_block(self):
        members = self.barrier_members("test_fail_bad.py", "test_good.py")
        result = self.run_suite("--jobs", "2", *members, cap=2, total=2)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        inside, end = self.block(result.stdout, "test_fail_bad.py")
        self.assertRegex(end, r" failed exit=1 ")
        # unittest's progress text and a marker can share a line, so markers
        # are matched within lines.
        lines = result.stdout.splitlines()
        for n in range(3):
            for stream in ("stdout", "stderr"):
                marker = f"marker test_fail_bad.py {stream} {n}"
                self.assertEqual(sum(marker in line for line in lines), 1, marker)
                self.assertTrue(any(marker in line for line in inside), marker)
        self.assertTrue(any("test_fail_bad.py: deliberate failure" in line for line in inside))
        intruders = [line for line in inside
                     if RUNNER_LINE.match(line) or "marker test_good.py" in line]
        self.assertEqual(intruders, [])
        self.assertRegex(self.block(result.stdout, "test_good.py")[1], r" passed exit=0 ")


class CapTest(RunnerCase):
    def test_two_jobs_reach_two_open_members_and_never_exceed_them(self):
        members = self.barrier_members(*(f"test_m{n}.py" for n in range(5)))
        result = self.run_suite("--jobs", "2", *members, cap=2, total=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.most_open(result.stdout), 2)
        self.assertEqual(sorted(self.seen()), sorted(members))
        self.assertEqual(max(self.seen().values()), 2)

    def test_the_default_cap_is_four(self):
        self.assertEqual(suite_runner.DEFAULT_JOBS, 4)
        members = self.barrier_members(*(f"test_m{n}.py" for n in range(6)))
        result = self.run_suite(*members, cap=4, total=6)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.most_open(result.stdout), 4)
        self.assertEqual(max(self.seen().values()), 4)
        self.assertEqual(SUMMARY.match(result.stdout.splitlines()[-1]).group(4), "4")

    def test_help_names_the_command_and_documents_the_default(self):
        result = self.run_suite("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("usage: agent-workflow-tests "),
                        result.stdout[:200])
        self.assertIn("(default: 4)", " ".join(result.stdout.split()))

    def test_one_job_runs_members_one_at_a_time_with_their_output_live(self):
        members = self.barrier_members("test_m0.py", "test_m1.py", "test_m2.py")
        result = self.run_suite("--jobs", "1", *members, cap=1, total=3)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.most_open(result.stdout), 1)
        self.assertEqual(self.seen(), {member: 1 for member in members})
        for member in members:
            inside, end = self.block(result.stdout, member)
            self.assertRegex(end, r" passed exit=0 ")
            self.assertEqual(inside, [f"marker {member} stdout {n}" for n in range(3)])
            for n in range(3):
                self.assertIn(f"marker {member} stderr {n}", result.stderr)
                self.assertNotIn(f"marker {member} stderr {n}", result.stdout)


class ReportTest(RunnerCase):
    def test_every_run_ends_with_a_report_covering_every_member(self):
        members = self.barrier_members(
            "test_m0.py", "test_fail_m1.py", "test_m2.py", "test_fail_m3.py")
        result = self.run_suite("--jobs", "2", *members, cap=2, total=4)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        report = lines[lines.index("suite-runner: timings, slowest first") + 1:]
        rows = [ROW.match(line) for line in report[:len(members)]]
        self.assertTrue(all(rows), report)
        self.assertEqual({row.group(3): row.group(2) for row in rows}, {
            "test_m0.py": "passed", "test_fail_m1.py": "failed",
            "test_m2.py": "passed", "test_fail_m3.py": "failed"})
        seconds = [float(row.group(1)) for row in rows]
        self.assertEqual(seconds, sorted(seconds, reverse=True))
        self.assertEqual(report[len(members):-1], [
            "suite-runner: failed test_fail_m1.py", "suite-runner: failed test_fail_m3.py"])
        summary = SUMMARY.match(report[-1])
        self.assertIsNotNone(summary, report[-1])
        self.assertEqual(summary.groups(), ("4", "2", "2", "2"))

    def test_rows_run_slowest_first_with_ties_in_list_order(self):
        results = [
            MemberResult(index=0, member="a.py", returncode=0, seconds=2.0),
            MemberResult(index=1, member="b.py", returncode=0, seconds=5.0),
            MemberResult(index=2, member="c.py", returncode=1, seconds=2.0),
            MemberResult(index=3, member="d.py", returncode=-9, seconds=0.04),
            MemberResult(index=4, member="e.py", returncode=0, seconds=5.0),
            MemberResult(index=5, member="f.py", returncode=0, seconds=3.21),
            MemberResult(index=6, member="g.sh", returncode=None, seconds=3.24),
        ]
        lines = suite_runner.report_lines(
            list(reversed(results)), jobs=3, wall_seconds=12.34)
        self.assertEqual(lines, [
            "suite-runner: timings, slowest first",
            "suite-runner:     5.0s passed b.py",
            "suite-runner:     5.0s passed e.py",
            "suite-runner:     3.2s passed f.py",
            "suite-runner:     3.2s failed g.sh",
            "suite-runner:     2.0s passed a.py",
            "suite-runner:     2.0s failed c.py",
            "suite-runner:     0.0s failed d.py",
            "suite-runner: failed c.py",
            "suite-runner: failed d.py",
            "suite-runner: failed g.sh",
            "suite-runner: summary members=7 passed=4 failed=3 jobs=3 wall=12.3s",
        ])


class ExitStatusTest(RunnerCase):
    def test_each_kind_of_member_failure_fails_the_run_and_every_member_runs(self):
        members = [self.member("test_plain.py", PLAIN_MEMBER),
                   self.member("test_empty.py", "import unittest\n"),
                   self.member("killed.sh", "kill -9 $$\n")]
        result = self.run_suite("--jobs", "2", *members)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        ends = {match.group(1): match.group(2, 3)
                for match in map(END.match, result.stdout.splitlines()) if match}
        self.assertEqual(ends, {"test_plain.py": ("passed", "0"),
                                "test_empty.py": ("failed", "5"),
                                "killed.sh": ("failed", "signal-9")})
        self.assertEqual(
            [line for line in result.stdout.splitlines()
             if line.startswith("suite-runner: failed ")],
            ["suite-runner: failed test_empty.py", "suite-runner: failed killed.sh"])

    def test_a_member_that_cannot_launch_fails_with_its_launch_error_as_output(self):
        empty = self.work.parent / "empty-path"
        empty.mkdir()
        members = [self.member("test_plain.py", PLAIN_MEMBER),
                   self.member("hello.sh", "echo hello\n")]
        result = self.run_suite("--jobs", "2", *members, env={"PATH": str(empty)})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        inside, end = self.block(result.stdout, "hello.sh")
        self.assertRegex(end, r" failed exit=launch-error ")
        self.assertTrue(any("'bash'" in line for line in inside), inside)
        self.assertNotIn("hello", inside)
        self.assertRegex(self.block(result.stdout, "test_plain.py")[1], r" passed exit=0 ")


class UsageTest(RunnerCase):
    def test_usage_errors_exit_2_before_any_member_starts(self):
        good = self.barrier_members("test_good.py")[0]
        self.member("notes.txt", "notes\n")
        (self.work / "folder.py").mkdir()
        outside = self.work.parent / "outside"
        outside.mkdir()
        (outside / "test_outside.py").write_text(PLAIN_MEMBER, encoding="utf-8")
        cases = {
            "zero jobs": ("--jobs", "0", good),
            "negative jobs": ("--jobs", "-1", good),
            "non-integer jobs": ("--jobs", "two", good),
            "fractional jobs": ("--jobs", "1.5", good),
            "no members": ("--jobs", "2"),
            "duplicate member": (good, f"./{good}"),
            "missing member": (good, "test_missing.py"),
            "directory member": (good, "folder.py"),
            "member outside the working directory": (good, "../outside/test_outside.py"),
            "unknown suffix": (good, "notes.txt"),
        }
        for name, args in cases.items():
            with self.subTest(name):
                result = self.run_suite(*args)
                self.assertEqual((result.returncode, result.stdout), (2, ""), result.stderr)
                self.assertIn("agent-workflow-tests: error:", result.stderr)
                self.assertTrue(self.nothing_started())


class InterruptTest(RunnerCase):
    def interrupt_while_running(self, jobs: int) -> None:
        """SIGINT the runner alone once `jobs` held members are live, and release
        them only after the runner says it is waiting for them. The held members
        write nothing to stdout, so every stdout line is the runner's."""
        # A caught handler is reset to the default across exec, so the runner
        # takes SIGINT as KeyboardInterrupt even when this process inherited
        # SIGINT ignored.
        previous = signal.signal(signal.SIGINT, signal.default_int_handler)
        self.addCleanup(signal.signal, signal.SIGINT, previous)
        members = [self.member(f"test_hold{n}.py", HOLD_MEMBER) for n in range(4)]
        runner = subprocess.Popen(
            [sys.executable, "-m", "agent_tools.suite_runner", "--jobs", str(jobs), *members],
            cwd=self.work, env=self.environment(1, 1, {}), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(runner.stderr.close)
        self.addCleanup(runner.stdout.close)
        self.addCleanup(runner.wait, 120)
        self.addCleanup(runner.kill)
        self.addCleanup((self.barrier / "release").touch)
        deadline = time.monotonic() + 60
        while len(list((self.barrier / "live").iterdir())) < jobs:
            self.assertLess(time.monotonic(), deadline, "the held members never started")
            time.sleep(0.01)
        runner.send_signal(signal.SIGINT)
        lines = []
        for line in runner.stdout:
            lines.append(line.rstrip("\n"))
            if line.startswith("suite-runner: interrupted"):
                break
        (self.barrier / "release").touch()
        # Members write only a few lines to stderr, so reading stdout to its end
        # first cannot fill the stderr pipe.
        lines += runner.stdout.read().splitlines()
        errors = runner.stderr.read()
        self.assertEqual(runner.wait(timeout=120), 130, "\n".join(lines) + errors)
        self.assertIn("suite-runner: interrupted, waiting for running members", lines)
        self.assertEqual([match.group(1) for match in map(START.match, lines) if match],
                         members[:jobs])
        self.assertEqual(sorted(match.group(1) for match in map(END.match, lines) if match),
                         members[:jobs])
        self.assertEqual([line for line in lines if line.startswith(
            ("suite-runner: timings", "suite-runner: summary"))], [])

    def test_an_interrupt_in_parallel_mode_starts_nothing_more_and_prints_no_report(self):
        self.interrupt_while_running(2)

    def test_an_interrupt_in_serial_mode_starts_nothing_more_and_prints_no_report(self):
        self.interrupt_while_running(1)
```

- [ ] **Step 2: Run the test and watch it fail**

Run the focused form (Global Constraints) on `tests/test_suite_runner.py`.
Expected: FAIL, with one `ERROR` for the module import: `ModuleNotFoundError: No module named 'agent_tools.suite_runner'`.

- [ ] **Step 3: Write the minimal implementation**

Create `python/agent_tools/suite_runner.py`, with the module docstring `"""Run the agent workflow suite's members, each in its own process, at most --jobs at a time (issue 436)."""`, `from __future__ import annotations` and standard-library imports only. Define the Interfaces above with the Invariants above, and add these private helpers:
- `_line(text: str) -> bytes`, which returns `(text + "\n").encode()`.
- `_Output`, which holds the binary stream and a `threading.Lock` named `lock`. Its `write(data: bytes)` writes and then flushes.
- `INTERRUPTED = f"{PREFIX} interrupted, waiting for running members"`.

The scheduling core embodies D6, D11 and D12, so implement it as follows (names may change; the order of operations may not):

```python
def _run_serial(members: Sequence[str], out: _Output) -> list[MemberResult]:
    results = []
    for index, member in enumerate(members):
        out.write(_line(f"{PREFIX} start {member}") + _line(f"{PREFIX} begin {member}"))
        started = time.monotonic()
        try:
            process = subprocess.Popen(member_command(member))
        except OSError as error:
            out.write(_line(str(error)))
            returncode = None
        else:
            try:
                returncode = process.wait()
            except KeyboardInterrupt:
                # The member shares the terminal's process group, so a Ctrl-C
                # reaches it too: wait for it, close its block, then stop.
                out.write(_line(INTERRUPTED))
                returncode = process.wait()
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

    for _ in range(running):
        threading.Thread(target=worker).start()
    try:
        wait_for_workers()
    except KeyboardInterrupt:
        stop.set()
        with out.lock:
            out.write(_line(INTERRUPTED))
        wait_for_workers()
        raise
    return results
```

`run_suite` notes `time.monotonic()` and picks `_run_serial` for `jobs == 1`, else `_run_parallel`. It raises `RuntimeError` for any `None` result, then writes `report_lines(...)` (wall time since its start) as one flushed write, and returns 0 or 1.

`main` builds the parser and parses. It calls `validate_members(args.members, Path.cwd())`, turning a `UsageError` into `parser.error(str(error))`. It returns `run_suite(args.members, jobs=args.jobs, out=sys.stdout.buffer)`, or 130 on `KeyboardInterrupt`. The parser is `argparse.ArgumentParser(prog="agent-workflow-tests", description="Run the agent workflow suite's members, each in its own process.")` with these arguments:
- `--jobs`: `metavar="N"`, `default=DEFAULT_JOBS`, and a type function that raises `argparse.ArgumentTypeError` for a non-integer or a value below 1. Its help is `"run at most N members at a time; 1 runs them one at a time with live output (default: %(default)s)"`.
- `members`: `nargs="+"`, `metavar="member"`, with the help `"a test file (.py, run by unittest) or a shell script (.sh, run by bash)"`.

Then add this section to `python/README.md`, directly after the `## lane-triage` section. Check every clause against the code you wrote, and correct the README where they differ:

```markdown
## `agent-workflow-tests` runner

`just agent-workflow-tests` hands its curated member list to `agent_tools.suite_runner` (issue 436; source entry `python -m agent_tools.suite_runner`, no command-table row). The runner runs each member in its own process from its working directory, with the recipe's environment: a `.py` member as `python -m unittest -v <path>`, and a `.sh` member as `bash <path>`. At most `--jobs N` members run at once. The default, 4, is a fixed value, not one derived from the CPU count: the suite is CPU-bound, the hosted CI runner has 4 vCPUs, and several agents may verify on one host. In parallel mode each member's stdout and stderr are captured together and printed as one block when it exits, from `suite-runner: begin <member>` to `suite-runner: end <member> passed|failed exit=<code> <seconds>s`. A `suite-runner: start <member>` line marks each launch, so a run cut off by a time limit names the members still running. `--jobs 1` is serial mode: members run one at a time with stdin, stdout and stderr passed straight through, for a hang or a `breakpoint()`. A member passes only on exit 0. Unittest's exit 5 for a module that ran no tests, a death by signal (`exit=signal-<n>`) and a failure to launch (`exit=launch-error`) all fail it, and every member still runs after a failure. Every completed run ends with a timing table, slowest first with ties in list order, then one `suite-runner: failed <member>` line per failure and a `summary` line. Exit 0 means every member passed and 1 that one failed. Exit 2 is a usage error, raised before anything starts: a bad `--jobs`, no members, a duplicate, a member that is missing, is not a file or lies outside the working directory, or a suffix other than `.py` or `.sh`. Exit 130 is an interrupt: the runner starts nothing more, prints `suite-runner: interrupted, waiting for running members`, waits for those members and prints no report. A test that shares state with another test process is fixed by giving it its own temporary location, never by a serial-exemption list, a retry or a lock.
```

- [ ] **Step 4: Verify**

Run the focused form on `tests/test_suite_runner.py`.
Expected: `Ran 12 tests`, `OK`.

Run the module three times under Python 3.12, the hosted runner's version, where the `Thread.join()` trap applies (timeout 1800 s):
`nix shell nixpkgs#python312 --command bash -c 'for i in 1 2 3; do PYTHONPATH="$PWD/python" python3.12 -m unittest tests/test_suite_runner.py 2>&1 | tail -1; done'`
Expected: `OK` three times.

Run `bash -c 'PYTHONPATH="$PWD/python" python3 -c "import agent_tools.suite_runner"; echo "exit=$?"'`.
Expected: `exit=0` and nothing else: the import starts nothing.

Run `just build` (timeout 3600 s). The package build import-checks every module, including this one.
Expected: exit 0.

Run `git diff --stat 9d2abb3f..HEAD -- lib/agent-tools.nix justfile CLAUDE.md`.
Expected: nothing (D1: no command-table row; the recipe changes in Task 2).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/suite_runner.py tests/test_suite_runner.py python/README.md
launch-commit … -- -m "feat(issue-436): suite runner for the agent workflow tests" -m "<session trailers>"
```

Verify: `git status --short` prints nothing.
