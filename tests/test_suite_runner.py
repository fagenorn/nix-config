"""End-to-end tests for `agent_tools.suite_runner`, the scheduler behind
`just agent-workflow-tests` (issue 436).

Most cases run `python -m agent_tools.suite_runner` in a temporary working
directory over fixture members written there. The report-ordering case and the
members' environment cases (issues 496 and 499) call the module's functions
directly, and one control runs a fixture member with `bash` outside the runner.
Members that must overlap meet at a filesystem barrier instead of sleeping, so
no assertion depends on how long anything took (D9). The one exception is
`CpuTimeTest`, which compares each member's CPU with its wall time by design
(issue 497 D4).
"""

from __future__ import annotations

import io
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from collections.abc import Mapping
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

# Runs the runner with SIGINT raised right after it reaps its first member in
# serial mode, before it records the result (issue 497 D2).
SERIAL_REAP_INTERRUPT = textwrap.dedent('''\
    import os
    import signal
    import sys

    from agent_tools import suite_runner

    wait4 = os.wait4
    reaped = []


    def wait4_then_interrupt(*args):
        reaped.append(wait4(*args))
        if len(reaped) == 1:
            signal.raise_signal(signal.SIGINT)
        return reaped[-1]


    os.wait4 = wait4_then_interrupt
    sys.exit(suite_runner.main(sys.argv[1:]))
''')


# Runs the runner with SIGINT raised right after its first non-reaping wait
# returns in serial mode, so the member has exited unreaped, and a second SIGINT
# raised right after the interrupt path's own reap, before its end line
# (issue 497 D6, D7).
SERIAL_INTERRUPTED_REAP_INTERRUPT = textwrap.dedent('''\
    import os
    import signal
    import sys

    from agent_tools import suite_runner

    waitid = os.waitid
    wait4 = os.wait4
    waited = []


    def waitid_then_interrupt(*args):
        result = waitid(*args)
        waited.append(result)
        if len(waited) == 1:
            signal.raise_signal(signal.SIGINT)
        return result


    def wait4_then_interrupt(*args):
        reaped = wait4(*args)
        signal.raise_signal(signal.SIGINT)
        return reaped


    os.waitid = waitid_then_interrupt
    os.wait4 = wait4_then_interrupt
    sys.exit(suite_runner.main(sys.argv[1:]))
''')


PLAIN_MEMBER = textwrap.dedent('''\
    import unittest


    class Member(unittest.TestCase):
        def test_member(self):
            pass
''')

# A shell member that commits once in a fresh repository of its own, with
# global and system git configuration nulled and a fixed identity. Only the
# commit is traced, to the absolute file $SUITE_RUNNER_TEST_TRACE (issue 496).
COMMIT_MEMBER = textwrap.dedent('''\
    set -eu
    export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
    export GIT_AUTHOR_NAME=Suite GIT_AUTHOR_EMAIL=suite@example.invalid
    export GIT_COMMITTER_NAME=Suite GIT_COMMITTER_EMAIL=suite@example.invalid
    repo=$(mktemp -d)
    trap 'rm -rf "$repo"' EXIT
    cd "$repo"
    git init -q -b main
    echo probe > probe.txt
    git add probe.txt
    GIT_TRACE2_EVENT="$SUITE_RUNNER_TEST_TRACE" git commit -q -m probe
''')

# A unittest module that runs a grandchild spinning until it has used 1.0 s of
# its own CPU. Around the grandchild it measures its share of a CPU: the change
# in its own and its children's CPU seconds over the change in wall seconds. It
# writes the share to `seen`, then its `done` marker (issue 497 D4).
BUSY_MEMBER = textwrap.dedent('''\
    import os
    import subprocess
    import sys
    import time
    import unittest
    from pathlib import Path

    BARRIER = Path(os.environ["SUITE_RUNNER_TEST_BARRIER"])
    NAME = Path(__file__).name
    SPIN = "while __import__('time').process_time() < 1.0: pass"


    def cpu_seconds():
        times = os.times()
        return times.user + times.system + times.children_user + times.children_system


    class Member(unittest.TestCase):
        def test_member(self):
            cpu, wall = cpu_seconds(), time.monotonic()
            subprocess.run([sys.executable, "-c", SPIN], check=True)
            share = (cpu_seconds() - cpu) / (time.monotonic() - wall)
            (BARRIER / "seen" / NAME).write_text(repr(share))
            (BARRIER / "done" / NAME).touch()
''')

# A unittest module that waits for a `done` marker, then sleeps 1.0 s. Run
# after the busy member in parallel mode, it is still running when the runner
# reaps the busy member (issue 497 D4).
SLEEP_MEMBER = textwrap.dedent('''\
    import os
    import time
    import unittest
    from pathlib import Path

    BARRIER = Path(os.environ["SUITE_RUNNER_TEST_BARRIER"])


    class Member(unittest.TestCase):
        def test_member(self):
            deadline = time.monotonic() + 60
            while not any((BARRIER / "done").iterdir()):
                if time.monotonic() > deadline:
                    self.fail("the busy member never finished")
                time.sleep(0.01)
            time.sleep(1.0)
''')

# A unittest module that records, from inside its run, the bytecode cache it
# sees: the prefix, whether its own module's bytecode exists at the path CPython
# derives for it there, whether bytecode writing is enabled, and whether a
# `__pycache__` directory exists beside its source (issue 499).
CACHE_MEMBER = textwrap.dedent('''\
    import importlib.util
    import json
    import os
    import sys
    import unittest
    from pathlib import Path

    BARRIER = Path(os.environ["SUITE_RUNNER_TEST_BARRIER"])
    NAME = Path(__file__).name


    class Member(unittest.TestCase):
        def test_member(self):
            (BARRIER / "seen" / NAME).write_text(json.dumps({
                "prefix": sys.pycache_prefix,
                "cached": Path(importlib.util.cache_from_source(__file__)).is_file(),
                "writing": not sys.dont_write_bytecode,
                "beside": (Path(__file__).parent / "__pycache__").exists()}))
''')

RUNNER_LINE = re.compile(r"^suite-runner: ")
START = re.compile(r"^suite-runner: start (\S+)$")
END = re.compile(r"^suite-runner: end (\S+) (passed|failed) exit=(\S+) \d+\.\ds$")
ROW = re.compile(r"^suite-runner: +(?P<wall>\d+\.\d)s wall +(?P<cpu>\d+\.\d)s cpu "
                 r"(?P<state>passed|failed) (?P<member>\S+)$")
SUMMARY = re.compile(r"^suite-runner: summary members=(\d+) passed=(\d+) failed=(\d+) "
                     r"jobs=(\d+) wall=\d+\.\ds cpu=(\d+\.\d)s$")


def without_command_git_config(environ: Mapping[str, str]) -> dict[str, str]:
    """`environ` less every variable that carries command-scope git
    configuration: `GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_COUNT` and its key and
    value variables. This module runs under the suite runner, which gives it the
    suite's git entries (issue 496); a case that kept them would pass against a
    runner that adds nothing."""
    return {key: value for key, value in environ.items()
            if key not in ("GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT")
            and not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}


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


class DefaultJobsTest(unittest.TestCase):
    def test_the_default_is_cpus_minus_two_capped_at_eight_with_a_floor_of_one(self):
        for cpus, expected in ((2, 1), (4, 2), (10, 8), (32, 8), (None, 1), (1, 1)):
            with self.subTest(cpus=cpus):
                self.assertEqual(suite_runner.default_jobs(cpus, {}), expected)

    def test_the_environment_overrides_the_derived_default(self):
        for cpus in (2, 10, 32, None):
            with self.subTest(cpus=cpus):
                self.assertEqual(
                    suite_runner.default_jobs(cpus, {suite_runner.JOBS_ENV: "4"}), 4)

    def test_an_empty_environment_value_is_unset(self):
        self.assertEqual(suite_runner.default_jobs(10, {suite_runner.JOBS_ENV: ""}), 8)

    def test_a_bad_environment_value_is_a_usage_error(self):
        for text in ("0", "-1", "many"):
            with self.subTest(text=text):
                with self.assertRaises(suite_runner.UsageError):
                    suite_runner.default_jobs(10, {suite_runner.JOBS_ENV: text})


class ScheduleOrderTest(RunnerCase):
    members = ["a.py", "b.py", "c.py", "d.py", "e.py"]

    def test_members_start_longest_first_unknown_first_ties_in_list_order(self):
        timings = {"a.py": 5.0, "b.py": 50.0, "d.py": 5.0, "e.py": 20.0}
        order = suite_runner.schedule_order(self.members, timings)
        self.assertEqual([self.members[i] for i in order],
                         ["c.py", "b.py", "e.py", "a.py", "d.py"])

    def test_no_timings_keeps_list_order(self):
        self.assertEqual(suite_runner.schedule_order(self.members, {}), [0, 1, 2, 3, 4])

    def test_a_missing_or_malformed_timing_file_is_empty(self):
        self.assertEqual(suite_runner.load_timings(self.work / "absent.json"), {})
        bad = self.work / "bad.json"
        bad.write_text("[1", encoding="utf-8")
        self.assertEqual(suite_runner.load_timings(bad), {})
        good = self.work / "good.json"
        good.write_text('{"a.py": 1.5, "b.py": "x", "c.py": true, "d.py": NaN, '
                        f'"e.py": {"9" * 400}, "f.py": Infinity}}', encoding="utf-8")
        self.assertEqual(suite_runner.load_timings(good), {"a.py": 1.5})

    def test_a_parallel_run_starts_in_schedule_order_and_reports_failures_in_list_order(self):
        names = [self.member(f"test_m{n}.py", "") for n in range(4)]
        for n, name in enumerate(names):
            self.member(name, "import unittest\nclass T(unittest.TestCase):\n"
                              f"    def test_x(self): self.assertTrue({n % 2 == 1})\n")
        out = io.BytesIO()
        timings = {"test_m0.py": 1.0, "test_m1.py": 9.0, "test_m2.py": 5.0, "test_m3.py": 7.0}
        cwd = os.getcwd()
        os.chdir(self.work)
        try:
            code = suite_runner.run_suite(names, jobs=2, out=out, timings=timings)
        finally:
            os.chdir(cwd)
        lines = out.getvalue().decode().splitlines()
        self.assertEqual(code, 1, "\n".join(lines))
        starts = [line.split()[-1] for line in lines if line.startswith("suite-runner: start ")]
        self.assertEqual(starts, ["test_m1.py", "test_m3.py", "test_m2.py", "test_m0.py"])
        failed = [line.split()[-1] for line in lines if line.startswith("suite-runner: failed ")]
        self.assertEqual(failed, ["test_m0.py", "test_m2.py"])


class CapTest(RunnerCase):
    def test_two_jobs_reach_two_open_members_and_never_exceed_them(self):
        members = self.barrier_members(*(f"test_m{n}.py" for n in range(5)))
        result = self.run_suite("--jobs", "2", *members, cap=2, total=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.most_open(result.stdout), 2)
        self.assertEqual(sorted(self.seen()), sorted(members))
        self.assertEqual(max(self.seen().values()), 2)

    def test_the_default_cap_follows_the_cpu_count(self):
        cap = suite_runner.default_jobs(os.cpu_count(), {})
        members = self.barrier_members(*(f"test_m{n}.py" for n in range(cap + 2)))
        result = self.run_suite(*members, cap=cap, total=cap + 2,
                                env={suite_runner.JOBS_ENV: ""})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.most_open(result.stdout), cap)
        self.assertEqual(SUMMARY.match(result.stdout.splitlines()[-1]).group(4), str(cap))

    def test_help_names_the_command_and_documents_the_default(self):
        result = self.run_suite("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("usage: agent-workflow-tests "),
                        result.stdout[:200])
        self.assertIn("(default: $SUITE_RUNNER_JOBS when set, else min(8, CPUs - 2))",
                      " ".join(result.stdout.split()))

    def test_an_explicit_jobs_wins_over_a_bad_environment_value(self):
        members = self.barrier_members("test_m0.py")
        result = self.run_suite("--jobs", "1", *members, env={suite_runner.JOBS_ENV: "many"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        bad = self.run_suite(*members, env={suite_runner.JOBS_ENV: "many"})
        self.assertEqual(bad.returncode, 2, bad.stdout + bad.stderr)
        self.assertIn(suite_runner.JOBS_ENV, bad.stderr)

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
        self.assertEqual({row["member"]: row["state"] for row in rows}, {
            "test_m0.py": "passed", "test_fail_m1.py": "failed",
            "test_m2.py": "passed", "test_fail_m3.py": "failed"})
        seconds = [float(row["wall"]) for row in rows]
        self.assertEqual(seconds, sorted(seconds, reverse=True))
        self.assertEqual(report[len(members):-1], [
            "suite-runner: failed test_fail_m1.py", "suite-runner: failed test_fail_m3.py"])
        summary = SUMMARY.match(report[-1])
        self.assertIsNotNone(summary, report[-1])
        self.assertEqual(summary.group(1, 2, 3, 4), ("4", "2", "2", "2"))

    def test_rows_run_slowest_first_with_ties_in_list_order(self):
        results = [
            MemberResult(index=0, member="a.py", returncode=0, seconds=2.0, cpu_seconds=1.5),
            MemberResult(index=1, member="b.py", returncode=0, seconds=5.0, cpu_seconds=2.0),
            MemberResult(index=2, member="c.py", returncode=1, seconds=2.0, cpu_seconds=0.04),
            MemberResult(index=3, member="d.py", returncode=-9, seconds=0.04, cpu_seconds=0.04),
            MemberResult(index=4, member="e.py", returncode=0, seconds=5.0, cpu_seconds=4.9),
            MemberResult(index=5, member="f.py", returncode=0, seconds=3.21, cpu_seconds=0.04),
            MemberResult(index=6, member="g.sh", returncode=None, seconds=3.24, cpu_seconds=0.0),
        ]
        lines = suite_runner.report_lines(
            list(reversed(results)), jobs=3, wall_seconds=12.34)
        # c, d and f spend 0.04 s each: their rows print 0.0, and the total
        # counts their 0.12 s, so it is 8.5 where the printed rows add to 8.4.
        self.assertEqual(lines, [
            "suite-runner: timings, slowest first",
            "suite-runner:     5.0s wall     2.0s cpu passed b.py",
            "suite-runner:     5.0s wall     4.9s cpu passed e.py",
            "suite-runner:     3.2s wall     0.0s cpu passed f.py",
            "suite-runner:     3.2s wall     0.0s cpu failed g.sh",
            "suite-runner:     2.0s wall     1.5s cpu passed a.py",
            "suite-runner:     2.0s wall     0.0s cpu failed c.py",
            "suite-runner:     0.0s wall     0.0s cpu failed d.py",
            "suite-runner: failed c.py",
            "suite-runner: failed d.py",
            "suite-runner: failed g.sh",
            "suite-runner: summary members=7 passed=4 failed=3 jobs=3 wall=12.3s cpu=8.5s",
        ])


class CpuTimeTest(RunnerCase):
    """A busy member's CPU is close to its wall time and a sleeping member's far
    below it, in both modes (issue 497 D4). No bound rests on host load: the
    busy member spins to a CPU target and measures the share of a CPU it got,
    and load only lengthens the sleeping member's wall time."""

    def assert_cpu_follows_the_work(self, jobs: str) -> None:
        members = [self.member("test_busy.py", BUSY_MEMBER),
                   self.member("test_sleep.py", SLEEP_MEMBER)]
        result = self.run_suite("--jobs", jobs, *members)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        report = lines[lines.index("suite-runner: timings, slowest first") + 1:]
        rows = [ROW.match(line) for line in report[:2]]
        self.assertTrue(all(rows), report)
        figures = {row["member"]: (float(row["wall"]), float(row["cpu"])) for row in rows}
        self.assertEqual(sorted(figures), sorted(members))
        busy_wall, busy_cpu = figures["test_busy.py"]
        sleep_wall, sleep_cpu = figures["test_sleep.py"]
        share = float((self.barrier / "seen" / "test_busy.py").read_text())
        # The grandchild alone spent 1.0 s.
        self.assertGreaterEqual(busy_cpu, 1.0, report)
        # The member and its grandchild never run at once, so their CPU cannot
        # outrun the wall clock; 0.1 s covers the rounding of both figures.
        self.assertLessEqual(busy_cpu, busy_wall + 0.1, report)
        # Close to wall, scaled by the share of a CPU the host gave the member.
        self.assertGreaterEqual(busy_cpu, share * busy_wall / 2, (share, report))
        self.assertLessEqual(sleep_cpu, sleep_wall / 4, report)
        summary = SUMMARY.match(report[-1])
        self.assertIsNotNone(summary, report[-1])
        total = float(summary.group(5))
        self.assertGreaterEqual(total, 1.0, report[-1])
        self.assertLessEqual(abs(total - busy_cpu - sleep_cpu), 0.15, report)

    def test_parallel_rows_show_busy_cpu_near_wall_and_sleeping_cpu_far_below(self):
        self.assert_cpu_follows_the_work("2")

    def test_serial_rows_show_busy_cpu_near_wall_and_sleeping_cpu_far_below(self):
        self.assert_cpu_follows_the_work("1")


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

    def interrupted_lines(self, runner: subprocess.Popen) -> list[str]:
        """Release the held members only once the runner says it is waiting for
        them, then require exit 130, the interrupted line, an end line for each
        started member and no report, and return the runner's stdout lines.
        The members write nothing to stdout, so every stdout line is the
        runner's."""
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
        return lines

    def finish_interrupted(self, runner: subprocess.Popen) -> list[str]:
        """The members the interrupted run started, in start order."""
        return [match.group(1) for match in map(START.match, self.interrupted_lines(runner))
                if match]

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

    def test_an_interrupt_right_after_a_serial_reap_keeps_the_members_exit_status(self):
        """SIGINT lands right after the runner reaps its first member in serial
        mode, before it records the result. The runner still reports that
        member's own exit status, then stops (issue 497 D2)."""
        members = [self.member("exit3.sh", "exit 3\n"),
                   self.member("test_plain.py", PLAIN_MEMBER)]
        runner = self.launch("-c", SERIAL_REAP_INTERRUPT, "--jobs", "1", *members)
        lines = self.interrupted_lines(runner)
        self.assertEqual([match.group(1, 2, 3) for match in map(END.match, lines) if match],
                         [("exit3.sh", "failed", "3")], lines)

    def test_a_second_interrupt_during_the_interrupted_serial_reap_waits_for_its_end_line(self):
        """SIGINT lands once the first serial member has exited unreaped, and a
        second one right after the interrupt path reaps it. The second is held
        until that member's end line is written, so the runner still reports
        its own exit status, then stops (issue 497 D6, D7). The test fails if
        the interrupt path's hold is removed or released before the end line."""
        members = [self.member("exit3.sh", "exit 3\n"),
                   self.member("test_plain.py", PLAIN_MEMBER)]
        runner = self.launch("-c", SERIAL_INTERRUPTED_REAP_INTERRUPT, "--jobs", "1", *members)
        lines = self.interrupted_lines(runner)
        self.assertEqual([match.group(1, 2, 3) for match in map(END.match, lines) if match],
                         [("exit3.sh", "failed", "3")], lines)


class MemberEnvironmentTest(unittest.TestCase):
    """`member_environment` observed through what git reads under its result
    (issue 496) and through its bytecode variables (issue 499). Each case
    fails for one wrong composition."""

    def setUp(self) -> None:
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        self.scratch = Path(raw.name).resolve()
        self.parent = {**without_command_git_config(os.environ),
                       "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        self.cache = str(self.scratch / "run-cache")

    def read(self, environment: Mapping[str, str], key: str) -> str | None:
        """The value git reads for `key` under `environment`, or None when it
        has none. Any other exit, such as 128 for a `GIT_CONFIG_PARAMETERS` git
        cannot parse, fails the case."""
        result = subprocess.run(
            ["git", "config", "--get", key], cwd=self.scratch, env=environment,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
            check=False)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return result.stdout.strip() if result.returncode == 0 else None

    def compose(self, inherited: str | None) -> dict[str, str]:
        parent = dict(self.parent)
        if inherited is not None:
            parent["GIT_CONFIG_PARAMETERS"] = inherited
        return suite_runner.member_environment(parent, self.cache)

    def assert_suite_entries(self, environment: Mapping[str, str]) -> None:
        self.assertEqual(self.read(environment, "maintenance.auto"), "false")
        self.assertEqual(self.read(environment, "gc.auto"), "0")

    def test_with_nothing_inherited_git_reads_the_suite_entries(self):
        self.assert_suite_entries(self.compose(None))

    def test_an_inherited_entry_still_reads_beside_the_suite_entries(self):
        environment = self.compose("'user.name'='Inherited'")
        self.assertEqual(self.read(environment, "user.name"), "Inherited")
        self.assert_suite_entries(environment)

    def test_an_empty_inherited_value_still_parses(self):
        self.assert_suite_entries(self.compose(""))

    def test_the_suite_entry_wins_over_an_inherited_entry_for_the_same_key(self):
        environment = self.compose("'maintenance.auto'='true'")
        self.assertEqual(self.read(environment, "maintenance.auto"), "false")

    def test_a_tests_own_config_count_keeps_the_suite_entries(self):
        # As the retired review tests did with a hostile git environment.
        environment = {**self.compose(None), "GIT_CONFIG_COUNT": "1",
                       "GIT_CONFIG_KEY_0": "user.name", "GIT_CONFIG_VALUE_0": "Counted"}
        self.assertEqual(self.read(environment, "user.name"), "Counted")
        self.assert_suite_entries(environment)

    def test_the_run_cache_replaces_an_inherited_prefix(self):
        parent = {**self.parent, "PYTHONPYCACHEPREFIX": str(self.scratch / "foreign")}
        environment = suite_runner.member_environment(parent, self.cache)
        self.assertEqual(environment["PYTHONPYCACHEPREFIX"], self.cache)

    def test_an_inherited_dont_write_bytecode_is_dropped(self):
        parent = {**self.parent, "PYTHONDONTWRITEBYTECODE": "1"}
        environment = suite_runner.member_environment(parent, self.cache)
        self.assertNotIn("PYTHONDONTWRITEBYTECODE", environment)

    def test_only_the_git_and_bytecode_variables_change_and_the_parent_is_untouched(self):
        parent = {**self.parent, "GIT_CONFIG_PARAMETERS": "'user.name'='Inherited'",
                  "PYTHONPYCACHEPREFIX": str(self.scratch / "foreign"),
                  "PYTHONDONTWRITEBYTECODE": "1"}
        before = dict(parent)
        environment = suite_runner.member_environment(parent, self.cache)
        self.assertEqual(parent, before)
        changed = ("GIT_CONFIG_PARAMETERS", "PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE")
        self.assertEqual({key: value for key, value in environment.items() if key not in changed},
                         {key: value for key, value in before.items() if key not in changed})


class GitMaintenanceTest(RunnerCase):
    """A commit under the runner starts no `git maintenance` child (issue 496),
    against a control that shows the same commit outside the runner does."""

    def environment(self, cap: int, total: int, extra: dict) -> dict:
        return without_command_git_config(super().environment(cap, total, extra))

    def trace_events(self) -> list[dict]:
        return [json.loads(line)
                for line in self.trace.read_text(encoding="utf-8").splitlines() if line]

    def setUp(self) -> None:
        super().setUp()
        self.trace = self.work.parent / "trace.jsonl"
        self.commit = self.member("commit.sh", COMMIT_MEMBER)

    def commit_under_the_runner(self, jobs: str) -> None:
        result = self.run_suite("--jobs", jobs, self.commit,
                                env={"SUITE_RUNNER_TEST_TRACE": str(self.trace)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.trace_events()
        self.assertTrue(any(event["event"] == "start" and "commit" in event["argv"]
                            for event in events), events)
        self.assertEqual([event["argv"] for event in events
                          if "maintenance" in event.get("argv", [])], [])

    def test_a_commit_in_serial_mode_starts_no_maintenance_child(self):
        self.commit_under_the_runner("1")

    def test_a_commit_in_parallel_mode_starts_no_maintenance_child(self):
        self.commit_under_the_runner("2")

    def test_the_same_commit_outside_the_runner_starts_a_maintenance_child(self):
        # maintenance.autoDetach=false runs the maintenance child in the
        # foreground, so it has finished when the commit returns.
        environment = {**self.environment(1, 1, {"SUITE_RUNNER_TEST_TRACE": str(self.trace)}),
                       "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "maintenance.autoDetach",
                       "GIT_CONFIG_VALUE_0": "false"}
        result = subprocess.run(
            ["bash", self.commit], cwd=self.work, env=environment,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300,
            check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        children = [event["argv"] for event in self.trace_events()
                    if event["event"] == "child_start"]
        self.assertTrue(any(argv[:4] == ["git", "maintenance", "run", "--auto"]
                            for argv in children), children)


class BytecodeCacheTest(RunnerCase):
    """The members of a run share one bytecode cache that the runner creates and
    removes, at both launch sites (issue 499). This module runs under the suite
    runner, so each case hands the inner runner a sentinel `PYTHONPYCACHEPREFIX`
    and `PYTHONDONTWRITEBYTECODE=1` of its own: a case that kept the outer run's
    cache would pass against a runner that sets nothing."""

    def setUp(self) -> None:
        super().setUp()
        self.sentinel = self.work.parent / "sentinel-pycache"
        self.sentinel.mkdir()

    def environment(self, cap: int, total: int, extra: dict) -> dict:
        return {**super().environment(cap, total, extra),
                "PYTHONPYCACHEPREFIX": str(self.sentinel), "PYTHONDONTWRITEBYTECODE": "1"}

    def assert_members_share_one_removed_cache(self, jobs: str) -> None:
        members = [self.member(name, CACHE_MEMBER)
                   for name in ("test_cache_a.py", "test_cache_b.py")]
        result = self.run_suite("--jobs", jobs, *members)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        seen = {path.name: json.loads(path.read_text(encoding="utf-8"))
                for path in (self.barrier / "seen").iterdir()}
        self.assertEqual(sorted(seen), members)
        prefixes = {record["prefix"] for record in seen.values()}
        self.assertEqual(len(prefixes), 1, seen)
        prefix = prefixes.pop()
        self.assertIsNotNone(prefix, seen)
        self.assertNotEqual(Path(prefix).resolve(), self.sentinel, seen)
        self.assertEqual(seen, {member: {"prefix": prefix, "cached": True, "writing": True,
                                         "beside": False} for member in members})
        self.assertFalse(Path(prefix).exists(), prefix)

    def test_serial_members_share_one_cache_the_run_removes(self):
        self.assert_members_share_one_removed_cache("1")

    def test_parallel_members_share_one_cache_the_run_removes(self):
        self.assert_members_share_one_removed_cache("2")


class DocstringContractTest(unittest.TestCase):
    """The module docstring is the contract's home (issue 694); these sentences
    were once in the runner's README section and must not be lost."""

    SENTENCES = (
        "A descendant still running when the member exits, or never waited for, is not counted",
        "so a run compiles the standard-library source modules its processes import "
        "instead of reading the interpreter's own bytecode, and its later processes "
        "read that result",
        "A script run as a main file is compiled on every start.",
    )

    def test_docstring_keeps_the_cpu_and_bytecode_limits(self):
        doc = " ".join((suite_runner.__doc__ or "").split())
        for sentence in self.SENTENCES:
            self.assertIn(sentence, doc)


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
