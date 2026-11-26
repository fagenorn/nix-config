"""The verify-slot short lane: a declared short command runs in its own slots, beside the long lane.

It starts `verify-slot` processes in scratch git repositories and reads the queue store and history.

Run: just agent-workflow-tests
"""

import fcntl
import json
import os
import pty
import signal
import subprocess
import sys
import termios
import time
import unittest
from datetime import datetime, timedelta, timezone

from agent_tools.delivery import verify_queue, verify_slot
from agent_tools.delivery.verify_slot import (
    DEFERRING_LINE, QUEUED_LINE, REPORT_SKIPPED_LINE, SAME_REPOSITORY_LINE, WAITING_LINE)
from .test_verify_slot import (
    CHILD, PLACE_PATTERN, WAITED_PATTERN, SlotHarness, is_place, places, read_place, read_until,
    wait_for)
from .process_liveness import process_alive

TIER = "integration"

PAIR = """
import os, subprocess, sys, time
directory = sys.argv[1]
GRANDCHILD = '''
import os, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
path = os.path.join(sys.argv[1], "grandchild.pid")
with open(path + ".tmp", "w") as handle:
    handle.write(str(os.getpid()))
os.replace(path + ".tmp", path)
time.sleep(60)
'''
subprocess.Popen([sys.executable, "-c", GRANDCHILD, directory])
while not os.path.exists(os.path.join(directory, "grandchild.pid")):
    time.sleep(0.02)
with open(os.path.join(directory, "pair.pid"), "w") as handle:
    handle.write(str(os.getpid()))
time.sleep(60)
"""

TTY_CHILD = """
import os, sys
with open(os.path.join(sys.argv[1], "tty.foreground"), "w") as handle:
    handle.write(f"{os.tcgetpgrp(0) == os.getpgrp()} {os.getpgrp() != os.getpgid(os.getppid())}")
"""


def is_dead(pid, timeout=5):
    deadline = time.monotonic() + timeout
    while process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not process_alive(pid)


class ShortLaneTest(SlotHarness, unittest.TestCase):
    def short(self, name):
        return [sys.executable, "-c", CHILD, str(self.marks), name]

    def declare_short(self, *names, slots=1, bound=30, repository="example/alpha", **extra):
        commands = {repository: [self.short(name) for name in names]}
        self.declare(verify_short_lane={
            "slots": slots, "bound_seconds": bound, "commands": commands}, **extra)

    def worktree(self, name, repository="alpha"):
        return self.repository(name, f"git@github.com:example/{repository}.git")

    def test_a_short_command_of_a_repository_that_holds_its_slot_starts_at_once(self):
        self.declare_short("lint", verify_slots=1)
        one = self.repository("alpha-one", "git@github.com:example/alpha.git")
        two = self.repository("alpha-two", "https://github.com/Example/alpha")
        suite = self.start("suite", cwd=one)
        self.assertTrue(wait_for(self.mark("suite", "start")))
        self.release("lint")
        lint = self.start("lint", argv=self.short("lint"), cwd=two)
        code, err = self.finish(lint, timeout=15)
        self.assertEqual(code, 0, err)
        for line in (WAITING_LINE.format(count=1), SAME_REPOSITORY_LINE, QUEUED_LINE):
            self.assertNotIn(line, err.splitlines())
        self.assertTrue(self.mark("lint", "start").exists())
        self.assertTrue(self.mark("lint", "end").exists())
        self.assertFalse(self.mark("suite", "end").exists())
        holders = verify_queue.read_holders(self.slots)
        self.assertEqual([holder.repository for holder in holders], ["example/alpha"])
        self.release("suite")
        self.assertEqual(self.finish(suite)[0], 0)
        history = self.history()
        self.assertEqual(len(history), 2)
        self.assertEqual({entry["lane"] for entry in history}, {"long", "short"})
        short = next(entry for entry in history if entry["lane"] == "short")
        self.assertIsInstance(short["held_seconds"], float)
        self.assertLess(short["waited_seconds"], 1.0)

    def test_a_long_command_of_that_repository_still_waits_its_turn(self):
        self.declare_short("lint", verify_slots=2)
        one = self.worktree("alpha-one")
        two = self.worktree("alpha-two")
        suite = self.start("suite", cwd=one)
        self.assertTrue(wait_for(self.mark("suite", "start")))
        other = self.start("other", cwd=two)
        read_until(other, lambda line: line == SAME_REPOSITORY_LINE)
        time.sleep(1.5)
        self.assertFalse(self.mark("other", "start").exists())
        self.release("suite")
        self.assertEqual(self.finish(suite)[0], 0)
        self.assertTrue(wait_for(self.mark("other", "start")))
        self.release("other")
        self.assertEqual(self.finish(other)[0], 0)
        lanes = {entry["command"]: entry["lane"] for entry in self.history()}
        self.assertEqual(set(lanes.values()), {"long"})

    def test_a_second_short_waiter_of_one_repository_is_admitted_beside_the_first(self):
        self.slots.mkdir()
        tickets = []
        self.addCleanup(lambda: [os.close(ticket.descriptor) for ticket in tickets])
        now = time.time()
        first = verify_queue.join(self.slots, "k1", False, "example/alpha", now,
                                  lane=verify_queue.SHORT_LANE)
        second = verify_queue.join(self.slots, "k2", False, "example/alpha", now,
                                   lane=verify_queue.SHORT_LANE)
        tickets.extend([first, second])
        result = verify_slot._decide(self.slots, 2, False, "example/alpha", "k2", "just lint",
                                     second, lane=verify_queue.SHORT_LANE)
        self.assertIsNone(result[2])
        self.assertIsNone(result[1])

    def test_the_declared_argv_in_an_undeclared_repository_takes_the_long_lane(self):
        self.declare_short("lint", verify_slots=1)
        holder = self.start("l1", cwd=self.worktree("beta-one", "beta"))
        self.assertTrue(wait_for(self.mark("l1", "start")))
        self.release("lint")
        lint = self.start("lint", argv=self.short("lint"), cwd=self.worktree("beta-two", "beta"))
        read_until(lint, lambda line: line == SAME_REPOSITORY_LINE)
        time.sleep(1.5)
        self.assertFalse(self.mark("lint", "start").exists())
        self.release("l1")
        self.assertEqual((self.finish(holder)[0], self.finish(lint)[0]), (0, 0))

    def test_short_waiters_are_served_in_arrival_order_with_live_ones_first(self):
        self.declare_short("s1", "s2", "s3", "s4", slots=1)
        first = self.start("s1", argv=self.short("s1"), cwd=self.worktree("alpha-1"))
        self.assertTrue(wait_for(self.mark("s1", "start")))
        second = self.start("s2", argv=self.short("s2"), cwd=self.worktree("alpha-2"))
        self.assertEqual(read_place(second)[0], 1)
        third = self.start("s3", argv=self.short("s3"), cwd=self.worktree("alpha-3"))
        self.assertEqual(read_place(third)[0], 2)
        fourth = self.start("s4", "--live", argv=self.short("s4"), cwd=self.worktree("alpha-4"))
        read_until(fourth, is_place(1))
        for name in ("s2", "s3", "s4", "s1"):
            self.release(name)
        for proc in (first, second, third, fourth):
            self.assertEqual(self.finish(proc)[0], 0)
        started = {name: float(self.mark(name, "start").read_text()) for name in ("s2", "s3", "s4")}
        self.assertLess(started["s4"], started["s2"])
        self.assertLess(started["s2"], started["s3"])

    def test_a_short_waiter_takes_no_place_in_the_long_lanes_line(self):
        self.declare_short("s1", "s2", slots=1, verify_slots=1)
        long_holder = self.start("l1", cwd=self.worktree("beta", "beta"))
        self.assertTrue(wait_for(self.mark("l1", "start")))
        long_waiter = self.start("l2", cwd=self.worktree("gamma", "gamma"))
        place, holders, _ = read_place(long_waiter)
        self.assertEqual(place, 1)
        self.assertIn("example/beta", holders)
        self.assertNotIn("example/alpha", holders)
        short_holder = self.start("s1", argv=self.short("s1"), cwd=self.worktree("alpha-1"))
        self.assertTrue(wait_for(self.mark("s1", "start")))
        short_waiter = self.start("s2", argv=self.short("s2"), cwd=self.worktree("alpha-2"))
        place, holders, _ = read_place(short_waiter)
        self.assertEqual(place, 1)
        self.assertIn("example/alpha", holders)
        self.assertNotIn("example/beta", holders)
        self.release("l1")
        self.release("l2")
        lines = read_until(long_waiter, WAITED_PATTERN.match)
        self.assertLessEqual(set(places("\n".join(lines))), {1})
        for name in ("s1", "s2"):
            self.release(name)
        for proc in (long_holder, long_waiter, short_holder, short_waiter):
            self.assertEqual(self.finish(proc)[0], 0)

    def test_a_live_short_waiter_holds_back_no_ordinary_long_run(self):
        self.declare_short("s1", "s2", verify_slots=2)
        holder = self.start("s1", argv=self.short("s1"), cwd=self.worktree("alpha-1"))
        self.assertTrue(wait_for(self.mark("s1", "start")))
        waiter = self.start("s2", "--live", argv=self.short("s2"), cwd=self.worktree("alpha-2"))
        read_place(waiter)
        self.release("g")
        ordinary = self.start("g", cwd=self.worktree("gamma", "gamma"))
        self.assertTrue(wait_for(self.mark("g", "start"), 5))
        code, err = self.finish(ordinary, timeout=15)
        self.assertEqual(code, 0, err)
        self.assertNotIn(DEFERRING_LINE, err.splitlines())
        self.release("s1")
        self.release("s2")
        self.assertEqual((self.finish(holder)[0], self.finish(waiter)[0]), (0, 0))

    def test_a_short_run_does_not_defer_to_a_live_long_waiter(self):
        self.declare_short("lint", verify_slots=1)
        holder = self.start("l1", cwd=self.worktree("beta", "beta"))
        self.assertTrue(wait_for(self.mark("l1", "start")))
        waiter = self.start("l2", "--live", cwd=self.worktree("gamma", "gamma"))
        read_place(waiter)
        self.release("lint")
        lint = self.start("lint", argv=self.short("lint"), cwd=self.worktree("alpha"))
        code, err = self.finish(lint, timeout=15)
        self.assertEqual(code, 0, err)
        self.assertNotIn(DEFERRING_LINE, err.splitlines())
        self.release("l1")
        self.release("l2")
        self.assertEqual((self.finish(holder)[0], self.finish(waiter)[0]), (0, 0))

    def test_a_short_command_past_its_bound_is_ended_and_reported(self):
        self.declare_short("lint", bound=1)
        alpha = self.worktree("alpha")
        begin = time.monotonic()
        code, err = self.finish(self.start("lint", argv=self.short("lint"), cwd=alpha), timeout=20)
        elapsed = time.monotonic() - begin
        self.assertEqual(code, verify_slot.BOUND_EXIT, err)
        self.assertEqual(err.splitlines().count(verify_slot.SHORT_BOUND_LINE.format(bound=1)), 1)
        self.assertLess(elapsed, 1 + verify_slot.SHORT_GRACE_SECONDS + 3)
        self.assertTrue(is_dead(int(self.mark("lint", "pid").read_text())))
        self.assertFalse(self.mark("lint", "end").exists())
        (line,) = self.history()
        self.assertEqual((line["lane"], line["exit"]), ("short", 124))
        self.assertGreaterEqual(line["held_seconds"], 1.0)
        self.assertEqual(verify_queue.read_holders(self.slots, verify_queue.SHORT_LANE), [])

    def test_a_descendant_that_ignores_sigterm_is_killed_before_the_next_short_command_takes_the_slot(self):
        pair_argv = [sys.executable, "-c", PAIR, str(self.marks)]
        self.declare(verify_short_lane={
            "slots": 1, "bound_seconds": 1,
            "commands": {"example/alpha": [pair_argv, self.short("lint")]}})
        alpha = self.worktree("alpha")
        self.release("lint")
        grace = verify_slot.SHORT_GRACE_SECONDS
        begin = time.monotonic()
        pair = self.start("pair", argv=pair_argv, cwd=alpha)
        self.assertTrue(wait_for(self.mark("grandchild", "pid")))
        lint = self.start("lint", argv=self.short("lint"), cwd=alpha)
        self.assertTrue(wait_for(self.mark("lint", "start"), 1 + grace + 5))
        grandchild_alive = process_alive(int(self.mark("grandchild", "pid").read_text()))
        self.assertFalse(grandchild_alive)
        code, err = self.finish(pair)
        self.assertEqual(code, verify_slot.BOUND_EXIT, err)
        self.assertGreaterEqual(time.monotonic() - begin, 1 + grace - 0.5)
        self.assertEqual(self.finish(lint)[0], 0)
        self.assertFalse(process_alive(int(self.mark("pair", "pid").read_text())))

    def test_a_short_command_past_its_bound_is_ended_though_the_caller_closed_its_stderr(self):
        self.declare_short("lint", bound=1)
        proc = self.start("lint", argv=self.short("lint"), cwd=self.worktree("alpha"))
        self.assertTrue(wait_for(self.mark("lint", "start")))
        pid = int(self.mark("lint", "pid").read_text())
        proc.stderr.close()
        self.assertEqual(proc.wait(timeout=20), verify_slot.BOUND_EXIT)
        self.assertTrue(is_dead(pid, timeout=0.5))
        self.assertEqual(verify_queue.read_holders(self.slots, verify_queue.SHORT_LANE), [])

    def test_a_signalled_short_run_holds_its_slot_until_a_descendant_that_ignores_sigterm_is_gone(self):
        pair_argv = [sys.executable, "-c", PAIR, str(self.marks)]
        self.declare(verify_short_lane={
            "slots": 1, "bound_seconds": 30, "commands": {"example/alpha": [pair_argv]}})
        proc = self.start("pair", argv=pair_argv, cwd=self.worktree("alpha"))
        self.assertTrue(wait_for(self.mark("pair", "pid")))
        grandchild = int(self.mark("grandchild", "pid").read_text())
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(self.finish(proc)[0], 143)
        self.assertFalse(process_alive(grandchild))
        self.assertFalse(process_alive(int(self.mark("pair", "pid").read_text())))
        self.assertEqual(verify_queue.read_holders(self.slots, verify_queue.SHORT_LANE), [])

    def test_a_short_command_keeps_the_terminal_foreground_of_an_interactive_run(self):
        tty_argv = [sys.executable, "-c", TTY_CHILD, str(self.marks)]
        self.declare(verify_short_lane={
            "slots": 1, "bound_seconds": 30, "commands": {"example/alpha": [tty_argv]}})
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)

        def take_terminal():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        proc = subprocess.Popen(
            [sys.executable, "-m", "agent_tools.delivery.verify_slot", "run", "--", *tty_argv],
            env=self.env(), cwd=self.worktree("alpha"), stdin=slave, stderr=subprocess.PIPE,
            text=True, preexec_fn=take_terminal)
        self.procs.append(proc)
        os.close(slave)
        code, err = self.finish(proc, timeout=15)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.mark("tty", "foreground").read_text(), "True True")

    def test_a_short_bound_too_large_for_a_timer_is_a_setup_error_and_nothing_runs(self):
        self.declare_short("lint", bound=10 ** 310)
        code, err = self.finish(
            self.start("lint", argv=self.short("lint"), cwd=self.worktree("alpha")), timeout=15)
        self.assertEqual(code, verify_slot.USAGE_EXIT, err)
        self.assertFalse(self.mark("lint", "start").exists())

    def test_a_long_command_is_never_ended_at_the_short_bound(self):
        self.declare_short("lint", bound=1)
        proc = self.start("suite", cwd=self.worktree("alpha"))
        self.assertTrue(wait_for(self.mark("suite", "start")))
        time.sleep(2.5)
        self.release("suite")
        code, err = self.finish(proc)
        self.assertEqual(code, 0, err)
        self.assertNotIn(verify_slot.SHORT_BOUND_LINE.format(bound=1), err.splitlines())

    def test_a_terminated_short_run_ends_its_command_group_and_frees_the_short_slot(self):
        self.declare_short("lint", bound=30)
        alpha = self.worktree("alpha")
        proc = self.start("lint", argv=self.short("lint"), cwd=alpha)
        self.assertTrue(wait_for(self.mark("lint", "start")))
        pid = int(self.mark("lint", "pid").read_text())
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(self.finish(proc)[0], 143)
        self.assertTrue(is_dead(pid))
        self.release("lint")
        again = self.start("lint", argv=self.short("lint"), cwd=alpha)
        self.assertEqual(self.finish(again, timeout=10)[0], 0)

    def test_a_line_with_an_unknown_lane_is_skipped_and_one_without_a_lane_is_read(self):
        started = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        record = {"command": "just lint", "exit": 0, "held_seconds": 2, "repository": "example/alpha",
                  "started": started, "waited_seconds": 1}
        readable = [record, {**record, "lane": "short"}]
        template = json.dumps({**record, "lane": "@"}, separators=(",", ":"))
        raw = [template.replace('"@"', bad) for bad in ('"medium"', "1", "null")]
        self.slots.mkdir()
        lines = [json.dumps(item, separators=(",", ":")) for item in readable] + raw
        (self.slots / "history.jsonl").write_text("".join(line + "\n" for line in lines))
        result = subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.verify_slot", "report", "--hours", "100000"],
            env=self.env(), cwd=self.home, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("example/alpha runs=2 "), result.stdout)
        self.assertIn(REPORT_SKIPPED_LINE.format(count=3, path=self.slots / "history.jsonl"),
                      result.stderr.splitlines())


if __name__ == "__main__":
    unittest.main()
