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

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_TREE_SCRIPT = "home/common/agent-skills/evals/tests/test-run-eval-tree.sh"

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

# A unittest module that prints a marker, then holds until the test creates
# `release`. The test creates `release` only after it has read the marker, so a
# runner that holds a member's output until exit fails it at the deadline (D15).
LIVE_MEMBER = textwrap.dedent('''\
    import os
    import time
    import unittest
    from pathlib import Path

    BARRIER = Path(os.environ["SUITE_RUNNER_TEST_BARRIER"])


    class Member(unittest.TestCase):
        def test_member(self):
            print("live marker", flush=True)
            deadline = time.monotonic() + 60
            while not (BARRIER / "release").exists():
                if time.monotonic() > deadline:
                    self.fail("never released while running")
                time.sleep(0.01)
''')

# Runs the runner with SIGINT raised right after the first worker thread
# starts, before the others have (D14).
STARTUP_INTERRUPT = textwrap.dedent('''\
    import signal
    import sys
    import threading

    from agent_tools import suite_runner

    start = threading.Thread.start
    started = []


    def start_then_interrupt(thread):
        start(thread)
        started.append(thread)
        if len(started) == 1:
            signal.raise_signal(signal.SIGINT)


    threading.Thread.start = start_then_interrupt
    sys.exit(suite_runner.main(sys.argv[1:]))
''')

# Runs the runner with SIGINT raised right after its first member's process
# launches in serial mode, before the runner waits for it.
SERIAL_LAUNCH_INTERRUPT = textwrap.dedent('''\
    import signal
    import subprocess
    import sys

    from agent_tools import suite_runner

    popen = subprocess.Popen
    launched = []


    def popen_then_interrupt(*args, **kwargs):
        process = popen(*args, **kwargs)
        launched.append(process)
        if len(launched) == 1:
            signal.raise_signal(signal.SIGINT)
        return process


    subprocess.Popen = popen_then_interrupt
    sys.exit(suite_runner.main(sys.argv[1:]))
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

    def test_one_job_passes_a_members_output_through_while_it_runs(self):
        member = self.member("test_live.py", LIVE_MEMBER)
        runner = subprocess.Popen(
            [sys.executable, "-m", "agent_tools.suite_runner", "--jobs", "1", member],
            cwd=self.work, env=self.environment(1, 1, {}), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.addCleanup(runner.stdout.close)
        self.addCleanup(runner.wait, 120)
        self.addCleanup(runner.kill)
        self.addCleanup((self.barrier / "release").touch)
        lines = []
        for line in runner.stdout:
            lines.append(line.rstrip("\n"))
            if line.startswith("live marker"):
                break
        (self.barrier / "release").touch()
        lines += runner.stdout.read().splitlines()
        self.assertEqual(runner.wait(timeout=120), 0, "\n".join(lines))
        inside, end = self.block("\n".join(lines), member)
        self.assertIn("live marker", inside)
        self.assertRegex(end, r" passed exit=0 ")


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
    def launch(self, *argv: str) -> subprocess.Popen:
        """Start `python <argv>` in the work directory over held members. A caught
        handler is reset to the default across exec, so the runner takes SIGINT
        as KeyboardInterrupt even when this process inherited SIGINT ignored."""
        previous = signal.signal(signal.SIGINT, signal.default_int_handler)
        self.addCleanup(signal.signal, signal.SIGINT, previous)
        runner = subprocess.Popen(
            [sys.executable, *argv], cwd=self.work, env=self.environment(1, 1, {}),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True)
        self.addCleanup(runner.stderr.close)
        self.addCleanup(runner.stdout.close)
        self.addCleanup(runner.wait, 120)
        self.addCleanup(runner.kill)
        self.addCleanup((self.barrier / "release").touch)
        return runner

    def finish_interrupted(self, runner: subprocess.Popen) -> list[str]:
        """Release the held members only once the runner says it is waiting for
        them, then require exit 130, the interrupted line, an end line for each
        started member and no report. The held members write nothing to stdout,
        so every stdout line is the runner's."""
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
        starts = [match.group(1) for match in map(START.match, lines) if match]
        self.assertEqual(sorted(match.group(1) for match in map(END.match, lines) if match),
                         sorted(starts))
        self.assertEqual([line for line in lines if line.startswith(
            ("suite-runner: timings", "suite-runner: summary"))], [])
        return starts

    def interrupt_while_running(self, jobs: int) -> None:
        """SIGINT the runner alone once `jobs` held members are live."""
        members = [self.member(f"test_hold{n}.py", HOLD_MEMBER) for n in range(4)]
        runner = self.launch("-m", "agent_tools.suite_runner", "--jobs", str(jobs), *members)
        deadline = time.monotonic() + 60
        while len(list((self.barrier / "live").iterdir())) < jobs:
            self.assertLess(time.monotonic(), deadline, "the held members never started")
            time.sleep(0.01)
        runner.send_signal(signal.SIGINT)
        self.assertEqual(self.finish_interrupted(runner), members[:jobs])

    def test_an_interrupt_in_parallel_mode_starts_nothing_more_and_prints_no_report(self):
        self.interrupt_while_running(2)

    def test_an_interrupt_in_serial_mode_starts_nothing_more_and_prints_no_report(self):
        self.interrupt_while_running(1)

    def test_an_interrupt_while_workers_start_still_stops_and_waits(self):
        """SIGINT lands after the first worker thread starts and before the rest
        do. Workers may or may not have taken a member when the stop flag is
        set, so the started members are only required to be a list-order
        prefix of at most the cap."""
        members = [self.member(f"test_hold{n}.py", HOLD_MEMBER) for n in range(6)]
        runner = self.launch("-c", STARTUP_INTERRUPT, "--jobs", "4", *members)
        starts = self.finish_interrupted(runner)
        self.assertLessEqual(len(starts), 4, starts)
        self.assertEqual(starts, members[:len(starts)])

    def test_an_interrupt_as_a_serial_member_launches_still_waits_for_it(self):
        """SIGINT lands after the first member's process launches and before the
        runner waits for it. The runner exits only once that member has, so its
        done marker is there and its live token is gone."""
        members = [self.member(f"test_hold{n}.py", HOLD_MEMBER) for n in range(3)]
        runner = self.launch("-c", SERIAL_LAUNCH_INTERRUPT, "--jobs", "1", *members)
        self.assertEqual(self.finish_interrupted(runner), members[:1])
        self.assertEqual(sorted(path.name for path in (self.barrier / "done").iterdir()),
                         members[:1])
        self.assertEqual(list((self.barrier / "live").iterdir()), [])


class RecipeWiringTest(unittest.TestCase):
    def test_the_recipe_hands_its_curated_members_to_the_runner(self):
        lines = (REPO_ROOT / "justfile").read_text(encoding="utf-8").splitlines()
        start = lines.index("agent-workflow-tests *args:")
        body = []
        for line in lines[start + 1:]:
            if not line.startswith("  "):
                break
            body.append(line)
        self.assertEqual(
            body[0],
            '  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.suite_runner {{args}} \\')
        self.assertTrue(all(line.endswith(" \\") for line in body[:-1]), body)
        self.assertFalse(body[-1].endswith("\\"), body[-1])
        members = [line.strip().removesuffix(" \\") for line in body[1:]]
        self.assertTrue(all(line.startswith("    ") for line in body[1:]), body)
        self.assertEqual(members[-1], EVAL_TREE_SCRIPT)
        self.assertIn("tests/test_suite_runner.py", members)
        suite_runner.validate_members(members, REPO_ROOT)
