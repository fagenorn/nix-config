# Task 1: Process seam — table, marker reader, protection, termination

**Files:**
- Create: `python/agent_tools/launch_processes.py`
- Create: `tests/test_launch_scope.py`, which holds the shared helpers and `ProcessSeamTest`
- Modify: `justfile`. In the `agent-workflow-tests` list, add `tests/test_launch_scope.py \` on the line right after `tests/test_launch_commit.py \`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, in `agent_tools.launch_processes`, for Tasks 2 and 3:
  - `MARKER_ENV = "AGENT_LAUNCH_SCOPE"`, `TERM_SECONDS = 5.0`, `KILL_SECONDS = 1.0`, `POLL_SECONDS = 0.05`
  - `class UnsupportedPlatform(Exception)` and `class ProcessTableError(Exception)`. The command maps both to exit 2.
  - `@dataclass(frozen=True) class Proc: pid: int; ppid: int; pgid: int; zombie: bool`
  - `require_supported_platform() -> None`, which raises `UnsupportedPlatform` unless `sys.platform` is `"linux"` or `"darwin"`
  - `process_table() -> dict[int, Proc]`
  - `read_marker(pid: int) -> str | None`
  - `protected_pids(table: Mapping[int, Proc]) -> frozenset[int]`
  - `terminate(pids: Iterable[int], groups: Iterable[int], *, read_table=process_table, send=os.kill, send_group=os.killpg, term_seconds=TERM_SECONDS, kill_seconds=KILL_SECONDS) -> tuple[int, frozenset[int]]`, which returns `(signalled, survivors)`
- Produces, in `tests/test_launch_scope.py`, for Tasks 2 and 3: the module-level helpers `UNMARKED_ENV`, `is_dead(pid)`, `wait_until(predicate, seconds=10.0)` and `kill_quietly(pid)`, exactly as written in Step 1.

**Invariants:**
- `process_table` runs `["ps", "-A", "-o", "pid=,ppid=,pgid=,stat="]` by name on `PATH` (D11). An `OSError`, a non-zero exit, or a non-blank line that is not four fields with three integers raises `ProcessTableError`. `zombie` is `stat.startswith("Z")`.
- `read_marker` returns the marker's value only when the pid's environment is readable and holds `AGENT_LAUNCH_SCOPE=`. An unreadable environment, a vanished pid, a zombie, or an environment that does not decode as ASCII returns `None`. That is "no proof", never an error (D7). On any other platform it raises `UnsupportedPlatform`.
- `protected_pids` is `{1, os.getpid()}` plus every ancestor, found by following `ppid` through the table from `os.getpid()`. The walk stops at a pid that is missing from the table, at a pid of 1 or lower, or at a repeat.
- `terminate` never sends a signal to a protected pid. It never calls `send_group` on a group that has a protected member: such a group's other members are signalled one by one (spec **Signalling**).
- Importing the module loads no libc. The darwin `ctypes` handle is created lazily, under `functools.cache`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_launch_scope.py`:

```python
"""launch-scope: run a launch's long commands in a scope and reap what they leave (#276).

Real processes throughout. Liveness is read from `ps`, and a zombie counts as
dead (spec Test seams). The injectable `terminate` callables cover the
branches a real process cannot reach (D12).
"""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from agent_tools import launch_processes
from agent_tools.launch_processes import (
    MARKER_ENV, Proc, ProcessTableError, UnsupportedPlatform, process_table,
    protected_pids, read_marker, require_supported_platform, terminate)

# The suite itself may run under `launch-scope exec`; no fixture inherits that marker.
UNMARKED_ENV = {key: value for key, value in os.environ.items() if key != MARKER_ENV}
MARKER = "run-x/1:1:1/" + "a" * 32


def is_dead(pid):
    """Dead: `ps` no longer lists the pid, or lists it as a zombie."""
    completed = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                               capture_output=True, text=True, check=False)
    stat = completed.stdout.strip()
    return completed.returncode != 0 or not stat or stat.startswith("Z")


def wait_until(predicate, seconds=10.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def kill_quietly(pid):
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


class ProcessSeamTest(unittest.TestCase):
    def spawn(self, argv, *, marker=None):
        env = dict(UNMARKED_ENV)
        if marker is not None:
            env[MARKER_ENV] = marker
        child = subprocess.Popen(argv, env=env, start_new_session=True)
        self.addCleanup(child.wait)
        self.addCleanup(kill_quietly, child.pid)
        return child

    def test_a_marked_child_is_read_and_an_unmarked_one_is_not(self):
        marked = self.spawn(["sleep", "300"], marker=MARKER)
        unmarked = self.spawn(["sleep", "300"])
        self.assertTrue(wait_until(lambda: read_marker(marked.pid) == MARKER))
        self.assertIsNone(read_marker(unmarked.pid))

    def test_pid_one_and_a_vanished_pid_carry_no_marker(self):
        self.assertIsNone(read_marker(1))
        gone = subprocess.Popen(["true"], env=UNMARKED_ENV)
        gone.wait()
        self.assertIsNone(read_marker(gone.pid))

    def test_the_table_lists_this_process_and_marks_a_zombie(self):
        child = subprocess.Popen(["true"], env=UNMARKED_ENV)
        self.addCleanup(child.wait)
        missing = Proc(0, 0, 0, False)
        self.assertTrue(wait_until(lambda: process_table().get(child.pid, missing).zombie))
        me = process_table()[os.getpid()]
        self.assertEqual((me.ppid, me.pgid, me.zombie), (os.getppid(), os.getpgrp(), False))

    def test_a_ps_that_cannot_run_is_a_table_error(self):
        empty = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with mock.patch.dict(os.environ, {"PATH": str(empty)}):
            with self.assertRaises(ProcessTableError):
                process_table()

    def test_this_process_and_its_ancestors_are_protected(self):
        protected = protected_pids(process_table())
        self.assertTrue({1, os.getpid(), os.getppid()} <= protected)

    def test_terminate_escalates_to_sigkill(self):
        ready = Path(self.enterContext(tempfile.TemporaryDirectory())) / "ready"
        stubborn = self.spawn([
            sys.executable, "-c",
            "import signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "open(sys.argv[1], 'w').close(); time.sleep(300)", str(ready)])
        self.assertTrue(wait_until(ready.exists))
        self.assertEqual(terminate([stubborn.pid], [], term_seconds=0.5), (1, frozenset()))
        self.assertTrue(is_dead(stubborn.pid))

    def test_a_group_is_signalled_as_a_group(self):
        leader = self.spawn(["sh", "-c", "sleep 300 & wait"])

        def members():
            return sorted(pid for pid, proc in process_table().items()
                          if proc.pgid == leader.pid and not proc.zombie)
        self.assertTrue(wait_until(lambda: len(members()) == 2))
        before = members()
        self.assertEqual(terminate([], [leader.pid]), (2, frozenset()))
        for pid in before:
            self.assertTrue(wait_until(lambda: is_dead(pid), 2.0), pid)

    def test_this_process_its_ancestors_and_its_group_are_never_signalled(self):
        calls = []
        terminate([os.getpid(), os.getppid(), 1], [os.getpgrp()],
                  send=lambda pid, sig: calls.append(("pid", pid)),
                  send_group=lambda pgid, sig: calls.append(("group", pgid)),
                  term_seconds=0.1, kill_seconds=0.1)
        protected = protected_pids(process_table())
        self.assertNotIn(("group", os.getpgrp()), calls)
        self.assertEqual([call for call in calls if call[1] in protected], [])

    def test_a_pid_that_outlives_sigkill_is_a_survivor(self):  # D12
        table = {os.getpid(): Proc(os.getpid(), 1, os.getpgrp(), False),
                 4242424: Proc(4242424, 1, 4242424, False)}
        sent = []
        result = terminate([4242424], [], read_table=lambda: table,
                           send=lambda pid, sig: sent.append((pid, sig)),
                           send_group=lambda pgid, sig: sent.append(("group", pgid, sig)),
                           term_seconds=0.1, kill_seconds=0.1)
        self.assertEqual(result, (1, frozenset({4242424})))
        self.assertEqual(sent, [(4242424, signal.SIGTERM), (4242424, signal.SIGKILL)])

    def test_a_reused_pid_is_not_sent_sigkill(self):  # D11
        tables = iter([{4242424: Proc(4242424, 1, 4242424, False)}]
                      + [{4242424: Proc(4242424, 1, 77, False)}] * 1000)
        sent = []
        result = terminate([4242424], [], read_table=lambda: next(tables),
                           send=lambda pid, sig: sent.append((pid, sig)),
                           send_group=lambda pgid, sig: sent.append(("group", pgid, sig)),
                           term_seconds=0.1, kill_seconds=0.1)
        self.assertEqual((result, sent), ((1, frozenset()), [(4242424, signal.SIGTERM)]))

    def test_an_unsupported_platform_fails_loud(self):
        with mock.patch.object(launch_processes.sys, "platform", "win32"):
            with self.assertRaises(UnsupportedPlatform):
                require_supported_platform()
            with self.assertRaises(UnsupportedPlatform):
                read_marker(os.getpid())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest -v tests/test_launch_scope.py 2>&1 | tail -5`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_tools.launch_processes'`.

- [ ] **Step 3: Write the minimal implementation**

Write `python/agent_tools/launch_processes.py` with a module docstring that states the invariants above. Implement the following.

`process_table()`: run `ps` with `capture_output=True, text=True, check=False`. Parse each non-blank line with `line.split()`. Exactly four fields are required, and the first three must be integers. Map each pid to `Proc(pid, ppid, pgid, stat.startswith("Z"))`.

`read_marker(pid)`: call `require_supported_platform()`, then read the raw environment bytes. Find the first item that starts with `b"AGENT_LAUNCH_SCOPE="` and return its value decoded as ASCII. A `UnicodeDecodeError` returns `None`.
- Linux: `Path(f"/proc/{pid}/environ").read_bytes()`, split on `b"\0"`. An `OSError` returns `None`.
- darwin: the reader below, which was probed on this host per D7 (2026-10-07). Its layout is fixed by the spec.

```python
CTL_KERN, KERN_ARGMAX, KERN_PROCARGS2 = 1, 8, 49

@functools.cache
def _libc():
    return ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)

def _darwin_environ(pid: int) -> list[bytes] | None:
    libc = _libc()
    argmax, size = ctypes.c_int(0), ctypes.c_size_t(ctypes.sizeof(ctypes.c_int))
    if libc.sysctl((ctypes.c_int * 2)(CTL_KERN, KERN_ARGMAX), 2,
                   ctypes.byref(argmax), ctypes.byref(size), None, 0) != 0:
        return None
    buffer, size = ctypes.create_string_buffer(argmax.value), ctypes.c_size_t(argmax.value)
    if libc.sysctl((ctypes.c_int * 3)(CTL_KERN, KERN_PROCARGS2, pid), 3,
                   buffer, ctypes.byref(size), None, 0) != 0:
        return None                      # EINVAL for pid 1, ESRCH, EPERM: no proof
    raw = buffer.raw[:size.value]
    if len(raw) < 4:
        return None
    (argc,) = struct.unpack_from("i", raw, 0)
    rest = raw[4:]
    end = rest.find(b"\0")               # end of the exec path
    if end < 0:
        return None
    while end < len(rest) and rest[end] == 0:
        end += 1                         # NUL padding
    strings = rest[end:].split(b"\0")
    if argc < 0 or len(strings) < argc:
        return None
    environment = []
    for item in strings[argc:]:
        if not item:
            break                        # the environment ends at the first empty string
        environment.append(item)
    return environment
```

`protected_pids(table)`: follow the walk described in the invariants.

`terminate(pids, groups, ...)`. Each step below is a decision.
1. Read `table = read_table()` and `protected = protected_pids(table)`. Let `groups = set(groups)`. `safe_groups` is the set of groups with no member in `protected`.
2. The targets form a dict from pid to pgid. It holds every pid in `pids` that is in `table` and is not a zombie, plus every non-zombie pid in `table` whose pgid is in `groups`, minus `protected`. With no targets, return `(0, frozenset())` and send nothing.
3. Deliver SIGTERM. Call `send_group(g, SIGTERM)` once for each `g` in `safe_groups` that holds a target. Call `send(pid, SIGTERM)` for each target whose pgid is not in `safe_groups`. Ignore `ProcessLookupError` and `PermissionError` from either call, because darwin returns `EPERM` for a group whose only member is a zombie (D11).
4. Await. Poll `read_table()` every `POLL_SECONDS` until `term_seconds` have passed. A target is gone when it is absent, a zombie, or its pgid differs from the recorded one, which means the pid was reused (D11). Stop early once every target is gone.
5. When targets remain, deliver SIGKILL in the same way, but only to the remaining targets: a group call for each safe group that still holds one, and a pid call for the rest. Await again for `kill_seconds`.
6. Return `(delivered, frozenset(remaining))`, where `delivered` counts the distinct target pids that SIGTERM actually reached: a pid sent individually counts when `send` did not raise, and a group call that did not raise counts every target in that group. A target that vanished before SIGTERM (the call raised `ProcessLookupError`) is not counted (per D14). A test through the injectable `send`/`send_group` seam makes one send raise `ProcessLookupError` and asserts the count excludes it.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" timeout 600 python3 -m unittest -v tests/test_launch_scope.py 2>&1 | tail -5`
Expected: `OK`, with 11 tests.
Run: `grep -n 'tests/test_launch_scope.py' justfile`
Expected: one match, on the line after `tests/test_launch_commit.py \`. At the base commit there is none.

- [ ] **Step 5: Commit**

Use `launch-commit` when your prompt carries a `Lifecycle worker:` line.

```bash
git add python/agent_tools/launch_processes.py tests/test_launch_scope.py justfile
git commit -m "feat(launch-scope): process table, marker reader and guarded termination (#276)"
```
