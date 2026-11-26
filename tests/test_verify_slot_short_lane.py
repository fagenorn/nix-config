"""The verify-slot short lane: a declared short command runs in its own slots, beside the long lane.

It starts `verify-slot` processes in scratch git repositories and reads the queue store and history.

Run: just agent-workflow-tests
"""

import json
import os
import subprocess
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone

from agent_tools.delivery import verify_queue, verify_slot
from agent_tools.delivery.verify_slot import (
    DEFERRING_LINE, QUEUED_LINE, REPORT_SKIPPED_LINE, SAME_REPOSITORY_LINE, WAITING_LINE)
from .test_verify_slot import (
    CHILD, PLACE_PATTERN, WAITED_PATTERN, SlotHarness, is_place, places, read_place, read_until,
    wait_for)

TIER = "integration"


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
