# Task 2: The timing report shows each member's child CPU and the suite total

This task implements spec § Measurement (D1), § Report contract (D3), § Documentation and § Test seams (D4). `_reap` keeps the resource usage that its one `os.wait4` already returns, and `MemberResult` carries the member's user plus system CPU seconds. Each row of the closing table prints that figure beside the wall time, and the summary line ends with the suite's total. Two end-to-end tests prove the criterion: a busy member and a sleeping member, run once in parallel mode and once in serial mode. `python/README.md` documents the new report.

**Files:**
- Modify: `python/agent_tools/suite_runner.py`
- Modify: `python/README.md` (one sentence of the runner paragraph, line 47 at base)
- Test: `tests/test_suite_runner.py`

**Interfaces:**
- Consumes: from Task 1, `_reap(index: int, member: str, process: subprocess.Popen | None, started: float) -> MemberResult`, which holds the module's single `os.wait4(process.pid, 0)` call. Also `report_lines(results, *, jobs: int, wall_seconds: float) -> list[str]`, whose signature does not change. In the tests: `RunnerCase` (`member`, `run_suite`, `barrier`), `ROW` and `SUMMARY`.
- Produces:
  - `MemberResult(index: int, member: str, returncode: int | None, seconds: float, cpu_seconds: float)`. `cpu_seconds` is required and has no default.
  - Row: `suite-runner: <seconds:7.1f>s wall <cpu_seconds:7.1f>s cpu <passed|failed> <member>`.
  - Summary: `suite-runner: summary members=<n> passed=<p> failed=<f> jobs=<N> wall=<wall:.1f>s cpu=<total:.1f>s`.

**Invariants:**
- `cpu_seconds` is `ru_utime + ru_stime` of the rusage that `_reap`'s one `os.wait4` returns, and `0.0` for a member that never launched (D1). `suite_runner.py` reads CPU from no other source: no `resource.getrusage` and no `os.times`.
- Rows still sort on the wall figure as printed, then on list position (436 D11). Both figures use `{:7.1f}`.
- `cpu=` is the sum of the members' unrounded `cpu_seconds`, formatted `.1f`. The runner's own CPU never enters it.
- The summary keeps `members=`, `passed=`, `failed=`, `jobs=` and `wall=` in that order, with `cpu=` appended last. The header and the failed, start, begin, end and interrupted lines are unchanged (D3).
- Outside `CpuTimeTest`, no assertion depends on elapsed time.

- [ ] **Step 1: Write the failing tests**

In `tests/test_suite_runner.py`, make these edits.

1. Replace the module docstring with:

```python
"""End-to-end tests for `agent_tools.suite_runner`, the scheduler behind
`just agent-workflow-tests` (issue 436).

Every case but the report-ordering one runs `python -m agent_tools.suite_runner`
in a temporary working directory over fixture members written there. Members
that must overlap meet at a filesystem barrier instead of sleeping, so no
assertion depends on how long anything took (D9). The one exception is
`CpuTimeTest`, which compares each member's CPU with its wall time by design
(issue 497 D4).
"""
```

2. Directly before `RUNNER_LINE = re.compile(`, add the two fixtures:

```python
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
```

3. Replace the `ROW` and `SUMMARY` patterns with:

```python
ROW = re.compile(r"^suite-runner: +(?P<wall>\d+\.\d)s wall +(?P<cpu>\d+\.\d)s cpu "
                 r"(?P<state>passed|failed) (?P<member>\S+)$")
SUMMARY = re.compile(r"^suite-runner: summary members=(\d+) passed=(\d+) failed=(\d+) "
                     r"jobs=(\d+) wall=\d+\.\ds cpu=(\d+\.\d)s$")
```

4. In `ReportTest.test_every_run_ends_with_a_report_covering_every_member`, change three expressions and nothing else: `{row.group(3): row.group(2) for row in rows}` becomes `{row["member"]: row["state"] for row in rows}`, `float(row.group(1))` becomes `float(row["wall"])`, and `summary.groups()` becomes `summary.group(1, 2, 3, 4)`. `CapTest.test_the_default_cap_is_four` stays as it is, because `group(4)` is still `jobs`.

5. Replace `ReportTest.test_rows_run_slowest_first_with_ties_in_list_order` with:

```python
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
```

6. Directly after `ReportTest`, add:

```python
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
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the focused form with `-k ReportTest -k CpuTimeTest -k test_the_default_cap_is_four`.
Expected: `FAILED (failures=3, errors=2)`, 5 tests. The ordering test fails with `TypeError: … unexpected keyword argument 'cpu_seconds'`. The default-cap test fails with `AttributeError: 'NoneType' object has no attribute 'group'`. The report test and both `CpuTimeTest` tests fail `assertTrue(all(rows))`, because their rows have no `wall` and `cpu` labels.

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/suite_runner.py`:

1. Add the field `cpu_seconds: float` to `MemberResult`, directly after `seconds: float`.

2. Replace `_reap`'s docstring and body with the following. The signature does not change.

```python
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
```

3. In `report_lines`, the row becomes

```python
        lines.append(f"{PREFIX} {result.seconds:7.1f}s wall "
                     f"{result.cpu_seconds:7.1f}s cpu {state} {result.member}")
```

and the summary's last fragment `f"jobs={jobs} wall={wall_seconds:.1f}s")` becomes

```python
                 f"jobs={jobs} wall={wall_seconds:.1f}s "
                 f"cpu={sum(result.cpu_seconds for result in ordered):.1f}s")
```

In `python/README.md`, in the paragraph that starts with `` `just agent-workflow-tests` hands its curated member list``, replace this sentence:

```text
Every completed run ends with a timing table, slowest first with ties in list order, then one `suite-runner: failed <member>` line per failure and a `summary` line.
```

with this text, kept on the paragraph's one line:

```text
Every completed run ends with a timing table, slowest first with ties in list order, of one `suite-runner: <wall>s wall <cpu>s cpu passed|failed <member>` row per member, then one `suite-runner: failed <member>` line per failure and `suite-runner: summary members=<n> passed=<p> failed=<f> jobs=<N> wall=<seconds>s cpu=<seconds>s`. A row's CPU figure is the member's child CPU time: the user plus system seconds in the resource usage that `os.wait4` returns when the runner reaps the member. That covers the member's own process and every descendant that it, or a descendant in between, waited for, such as the `git` and `python -m agent_tools.…` processes a test runs. A descendant still running when the member exits, or never waited for, is not counted, and a member that failed to launch shows `0.0`. The summary's `cpu=` adds up the members' unrounded figures and never the runner's own CPU, so rounding can make it differ from the sum of the printed rows. A member whose CPU is close to its wall time, or above it when its descendants ran at once, was computing. One far below it was waiting, for I/O, a sleep or a CPU it could not get. Set `cpu=` against `wall=` times the CPUs the run could use, the smaller of `--jobs` and the host's CPUs. Near it, every slot was computing and the CPUs were saturated; well below it, the members were waiting on something else. A module whose CPU grows from a `--jobs 1` run to a parallel one ran on slower, shared CPUs.
```

Change nothing else in the paragraph.

- [ ] **Step 4: Verify**

Run the focused form on the whole module.
Expected: `OK`, 20 tests.

Run `bash -c 'set -e; grep -qF "<wall>s wall <cpu>s cpu passed|failed <member>" python/README.md; grep -qF "wall=<seconds>s cpu=<seconds>s" python/README.md; grep -qF "resource usage that \`os.wait4\` returns" python/README.md; if grep -nE "getrusage|os\.times" python/agent_tools/suite_runner.py; then exit 1; fi; echo docs-ok'`.
Expected: `docs-ok` and no other output. At Task 1's head the README greps fail.

Run `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m agent_tools.suite_runner --jobs 2 tests/test_suite_runner.py tests/test_branch_protection.py 2>&1 | tail -4'` (timeout 900 s).
Expected: the header, then two rows that each match `s wall … s cpu passed`, then `suite-runner: summary members=2 passed=2 failed=0 jobs=2 wall=…s cpu=…s`. The CPU of `tests/test_suite_runner.py` is at least `2.0`. That is because its two `CpuTimeTest` spinners, three processes below the member, are counted (D1).

Run `git diff --stat HEAD -- python/agent_tools/suite_runner.py python/README.md tests/test_suite_runner.py`.
Expected: exactly these three files.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/suite_runner.py python/README.md tests/test_suite_runner.py
launch-commit … -- -m "feat(issue-497): show each member's child CPU and the suite total in the timing report" -m "<session trailers>"
```

Verify: `git status --short -- python tests` prints nothing.
