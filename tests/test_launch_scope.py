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
# darwin hides an Apple platform binary's environment (D15): a marker proof needs this.
SLEEPER = [sys.executable, "-c", "import time; time.sleep(300)"]


def is_dead(pid):
    """Dead: `ps` no longer lists the pid, or lists it as a zombie.

    A live pid may print an empty `stat` (darwin procps, D15), so being listed
    is what counts.
    """
    completed = subprocess.run(["ps", "-o", "pid=,stat=", "-p", str(pid)],
                               capture_output=True, text=True, check=False)
    fields = completed.stdout.split()
    if completed.returncode != 0 or fields[:1] != [str(pid)]:
        return True
    return len(fields) > 1 and fields[1].startswith("Z")


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
        marked = self.spawn(SLEEPER, marker=MARKER)
        unmarked = self.spawn(SLEEPER)
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

    def test_a_blank_stat_is_a_live_process_and_a_bad_line_is_an_error(self):  # D15
        bin_dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        fake_ps = bin_dir / "ps"

        def table_from(output):
            fake_ps.write_text(f"#!/bin/sh\nprintf '{output}'\n")
            fake_ps.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": str(bin_dir)}):
                return process_table()
        self.assertEqual(table_from("  380     1   380     \\n   42   380    42 Z\\n\\n    7     1     7 Ss\\n"),
                         {380: Proc(380, 1, 380, False), 42: Proc(42, 380, 42, True),
                          7: Proc(7, 1, 7, False)})
        for bad in ("  380     1\\n", "  380     1   abc Ss\\n", "1 1 1 S extra\\n"):
            with self.subTest(bad=bad), self.assertRaises(ProcessTableError):
                table_from(bad)

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

    def test_a_target_gone_before_sigterm_is_not_counted(self):  # D14
        tables = iter([{4242424: Proc(4242424, 1, 4242424, False),
                        4242425: Proc(4242425, 1, 4242425, False)}] + [{}] * 1000)
        sent = []

        def send(pid, sig):
            sent.append((pid, sig))
            if pid == 4242425:
                raise ProcessLookupError(pid)
        result = terminate([4242424, 4242425], [], read_table=lambda: next(tables),
                           send=send,
                           send_group=lambda pgid, sig: sent.append(("group", pgid, sig)),
                           term_seconds=0.1, kill_seconds=0.1)
        self.assertEqual(result, (1, frozenset()))
        self.assertEqual(sorted(sent), [(4242424, signal.SIGTERM), (4242425, signal.SIGTERM)])

    def test_an_unsupported_platform_fails_loud(self):
        with mock.patch.object(launch_processes.sys, "platform", "win32"):
            with self.assertRaises(UnsupportedPlatform):
                require_supported_platform()
            with self.assertRaises(UnsupportedPlatform):
                read_marker(os.getpid())


if __name__ == "__main__":
    unittest.main()
