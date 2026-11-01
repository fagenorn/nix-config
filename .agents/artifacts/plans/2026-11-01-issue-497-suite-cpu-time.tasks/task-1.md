# Task 1: One `os.wait4` reaps every member, and an interrupt never loses a serial member's status

This task implements spec § Measurement (D1) and § Reaping and interrupts (D2), refined by D6 and pinned by D5. Both modes stop waiting through `Popen` and reap each member with one `os.wait4` inside a new `_reap`, which builds the member's `MemberResult`. Serial mode waits for the member with a non-reaping `os.waitid` and then reaps it with SIGINT held. A SIGINT can then no longer land between the reap and the recorded result. The report does not change in this task. Task 2 reads the CPU from the same `wait4`.

**Files:**
- Modify: `python/agent_tools/suite_runner.py`
- Test: `tests/test_suite_runner.py`

**Interfaces:**
- Consumes (base): `MemberResult(index: int, member: str, returncode: int | None, seconds: float)` and `_HeldSigint`, whose constructor installs a recording SIGINT handler and whose `release()` restores the previous handler and re-raises a recorded SIGINT. Also `end_line`, `INTERRUPTED` and `_line`. In the tests: `RunnerCase.member`, `InterruptTest.launch`, `START`, `END` and `PLAIN_MEMBER`.
- Produces (Task 2 relies on these names):
  - `_wait_exited(process: subprocess.Popen) -> None`
  - `_reap(index: int, member: str, process: subprocess.Popen | None, started: float) -> MemberResult`, the only place in either mode where a member is reaped.
  - `InterruptTest.interrupted_lines(runner: subprocess.Popen) -> list[str]`. `InterruptTest.finish_interrupted(runner: subprocess.Popen) -> list[str]` keeps its signature and return value.

**Invariants:**
- `suite_runner.py` calls `os.wait4` once, inside `_reap`. It never calls `Popen.wait`, `Popen.communicate`, `Popen.poll` or `os.waitpid`.
- `os.wait4` and `os.waitid` are called as attributes of the `os` module and never imported by name, so a wrapper that replaces `os.wait4` reaches every reap (D5).
- `_reap` stores the converted status as `process.returncode`, so nothing waits on the member again.
- A death by signal still reads `exit=signal-<n>`, through a negative returncode from `os.waitstatus_to_exitcode`. A launch failure still reads `exit=launch-error`.
- Serial mode handles a SIGINT before the reap as it does today: the member is unreaped, and the runner writes the `interrupted` line, waits, writes the end line and exits 130. A SIGINT during the reap is re-delivered only after the result is bound. The interrupt path then writes the end line from that result without waiting again (D2, D6).
- Parallel capture is unchanged: the worker reads the merged output to its end and closes the pipe before it reaps.

- [ ] **Step 1: Write the failing test**

In `tests/test_suite_runner.py`, make three edits.

1. Directly after the `SERIAL_LAUNCH_INTERRUPT` constant, before `PLAIN_MEMBER`, add:

```python
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
```

2. In `InterruptTest`, rename `finish_interrupted` to `interrupted_lines`. Keep its body, except that its last line returns `lines` instead of `starts`. Replace its docstring with:

```python
        """Release the held members only once the runner says it is waiting for
        them, then require exit 130, the interrupted line, an end line for each
        started member and no report, and return the runner's stdout lines.
        The members write nothing to stdout, so every stdout line is the
        runner's."""
```

Directly after it, add:

```python
    def finish_interrupted(self, runner: subprocess.Popen) -> list[str]:
        """The members the interrupted run started, in start order."""
        return [match.group(1) for match in map(START.match, self.interrupted_lines(runner))
                if match]
```

3. Append this method to `InterruptTest`, after `test_an_interrupt_as_a_serial_member_launches_still_waits_for_it`:

```python
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
```

Leave the four existing `InterruptTest` test methods as they are.

- [ ] **Step 2: Run the test and watch it fail**

Run the focused form with `-k test_an_interrupt_right_after_a_serial_reap`.
Expected: `FAILED (failures=1)`, 1 test, `AssertionError: 1 != 130`. At base nothing calls `os.wait4`, so the wrapper never interrupts, and the run completes with exit 1 because `exit3.sh` failed.

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/suite_runner.py`, add `import os` between `import argparse` and `import signal`. Then make the edits below. The serial loop's code is given in full because its order is the decision (D2, D6). It was prototyped at plan time: the new test passed with it and failed with `ChildProcessError` once the reap hold was removed.

1. Replace the `_HeldSigint` docstring with:

```python
    """Records a SIGINT instead of raising it, from construction until
    `release`, which restores the caller's handler and re-delivers a recorded
    SIGINT under it (D14). Release it inside the `try` that handles the
    interrupt. A hold over a launch or the parallel workers' start is
    constructed before that `try`, so a SIGINT just before it finds nothing
    started. A hold over a serial reap is constructed once the member has
    exited, so a SIGINT just before it finds the member exited and unreaped
    (issue 497 D2)."""
```

2. Add these two functions directly after `_HeldSigint`:

```python
def _wait_exited(process: subprocess.Popen) -> None:
    """Block until the member has exited, reaping nothing: `waitid` with
    WNOWAIT leaves its status for `_reap`, so a SIGINT that interrupts this
    wait loses nothing (issue 497 D2)."""
    os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT)


def _reap(index: int, member: str, process: subprocess.Popen | None,
          started: float) -> MemberResult:
    """The member's result, reaping its process if it launched; one that never
    launched has no exit code. One `os.wait4` on its pid is the only wait that
    reaps a member, in either mode (issue 497 D1), and its status is stored as
    the Popen's `returncode`, so nothing waits on it again. The wall time runs
    from `started` to just after the reap."""
    returncode = None
    if process is not None:
        _, status, _ = os.wait4(process.pid, 0)
        returncode = process.returncode = os.waitstatus_to_exitcode(status)
    return MemberResult(index, member, returncode, time.monotonic() - started)
```

3. Replace the body of `_run_serial` with:

```python
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
                process = subprocess.Popen(member_command(member))
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
```

4. In `_run_parallel`'s `run_members`, replace

```python
            if process is not None:
                output, _ = process.communicate()
            result = MemberResult(
                index, member, None if process is None else process.returncode,
                time.monotonic() - started)
```

with

```python
            if process is not None:
                # Read the merged output to its end, then reap: what
                # communicate() does for one pipe and no input. Signal handlers
                # run on the main thread only, so this reap is never
                # interrupted (issue 497 D2).
                with process.stdout:
                    output = process.stdout.read()
            result = _reap(index, member, process, started)
```

5. In the `run_suite` docstring, change `the runner holds SIGINT while it launches a serial member or starts its parallel workers.` to `the runner holds SIGINT while it launches or reaps a serial member or starts its parallel workers.`

Change nothing else. Leave `MemberResult`, `report_lines`, `end_line` and both launch holds as they are.

- [ ] **Step 4: Verify**

Run the focused form on the whole module.
Expected: `OK`, 17 tests.

Run `bash -c 'set -e; test "$(grep -c "os\.wait4(" python/agent_tools/suite_runner.py)" = 1; if grep -nE "process\.(wait|communicate|poll)\(|os\.waitpid|from os import" python/agent_tools/suite_runner.py; then exit 1; fi; echo reap-ok'`.
Expected: `reap-ok` and no other output. At base, `grep -c` counts 0 and `process.wait()` matches, so this gate fails there.

Run `git diff --stat HEAD -- python/agent_tools/suite_runner.py tests/test_suite_runner.py`.
Expected: exactly these two files.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/suite_runner.py tests/test_suite_runner.py
launch-commit … -- -m "fix(issue-497): reap each suite member with one wait4 and hold SIGINT across serial reaps" -m "<session trailers>"
```

Verify: `git status --short -- python tests` prints nothing.
