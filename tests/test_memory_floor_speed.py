"""The eleven-m5 memory floor against a fast-growing agent tree outside every declared root.

Drives `enforce_once` with a clock that advances by what each reading costs, while a probe below an
agent session grows a GiB a second, and checks the run bound ends the tree before memory runs under
the floor. Run: just agent-workflow-tests
"""

import contextlib
import io as stdio
import os
import tempfile
import unittest
from pathlib import Path

from agent_tools.hosts.memory_floor import GIB, Limits, Loop, enforce_once, memory_reader, read_available
from agent_tools.hosts.omlx_memory_watch import ReadingError
from tests.test_memory_floor import (
    LIMITS, OWNERS, W1, W2, Daemon, FakeIo, SCRATCH, proc, session_tree, table_of, w1_and_w2,
)
from tests.test_omlx_memory_watch import VM_STAT, VM_STAT_LOW

TIER = "fast"

DECLARED = Limits(10 * GIB, 3, 5, 16 * GIB, 2 * GIB, 2, 10, 24 * GIB, 190, GIB)
COST = {"available": 0.2, "services": 0.1, "omlx_pid": 0.1, "table": 0.5}


class GrowingIo(FakeIo):
    """One probe grows a GiB a second from `start`; each reading takes its cost and answers at the new time."""

    def __init__(self, start):
        super().__init__([20], session_tree(0))
        self.start = start
        self.last_tree = 0
        self.available_at_term = None
        self.tree_at_term = None

    def _grown(self, name):
        self.time += COST[name]
        return self.time - 1000.0

    def available(self):
        grown = self._grown("available")
        if 301 in self.dead:
            return int((20 + self.start) * GIB)
        return int((20 - grown) * GIB)

    def services(self):
        self._grown("services")
        return set()

    def omlx_pid(self):
        self._grown("omlx_pid")
        return None

    def table(self):
        grown = self._grown("table")
        table = session_tree(0)
        table[301] = proc(301, 300, 501, SCRATCH, self.start + grown, "python3 probe.py")
        table = {pid: p for pid, p in table.items() if pid not in self.dead}
        self.last_tree = sum(table[pid].footprint for pid in (300, 301) if pid in table)
        return table

    def signal(self, pid, sig):
        if pid == 301 and self.available_at_term is None:
            grown = self.time - 1000.0
            self.available_at_term = 20 - grown
            self.tree_at_term = self.last_tree
        super().signal(pid, sig)


class GrowthTest(unittest.TestCase):
    def test_a_scratch_tree_growing_a_gib_a_second_ends_at_the_run_bound_before_the_floor(self):
        for start in (15, 16, 17, 18):
            with self.subTest(start=start):
                fake = GrowingIo(start)
                io, loop, record, lines = fake.io(), Loop(), {}, []
                with contextlib.redirect_stderr(stdio.StringIO()):
                    for _ in range(20):
                        if 301 in fake.dead:
                            break
                        interval = enforce_once(DECLARED, OWNERS, io, loop, record, lines.append)
                        fake.sleep(interval)
                self.assertIn(301, fake.dead)
                self.assertGreater(fake.tree_at_term, DECLARED.run_bound_bytes)
                self.assertGreaterEqual(fake.available_at_term, 10)
                entry = record["recent"][0]
                self.assertEqual(entry["reason"], "run_bound")
                self.assertGreater(entry["tree_bytes"], DECLARED.run_bound_bytes)
                self.assertEqual(entry["workload"], "agent:session:300")
                self.assertFalse([line for line in lines if "floor_unmet" in line])


AT = "2026-11-24T12:33:05+00:00"
READINGS = ("available", "services", "omlx_pid", "table")


class ClockedIo(FakeIo):
    """A reading takes its cost on the clock before it answers, or fails."""

    def __init__(self, cost, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cost = cost

    def _read(self, name):
        self.time += self.cost.get(name, 0)
        super()._read(name)


def clocked_samples(fake, samples, record=None):
    io, loop, lines, stderr = fake.io(), Loop(), [], stdio.StringIO()
    record = {} if record is None else record
    intervals = []
    with contextlib.redirect_stderr(stderr):
        for _ in range(samples):
            intervals.append(enforce_once(LIMITS, OWNERS, io, loop, record, lines.append))
    return intervals, lines, record, stderr.getvalue()


class SlowReadingTest(unittest.TestCase):
    def test_a_reading_slower_than_the_fast_interval_is_named(self):
        for name in READINGS:
            with self.subTest(name):
                fake = ClockedIo({name: 2.5}, [100], {})
                _, lines, record, _ = clocked_samples(fake, 1)
                self.assertEqual(lines, [f"{AT} slow_reading reading={name} seconds=2.5\n"])
                self.assertEqual(record["slow_readings"], 1)
                self.assertEqual(
                    record["slow_reading_recent"], [{"seq": 1, "at": AT, "reading": name, "seconds": 2.5}]
                )

    def test_a_reading_at_the_fast_interval_is_not_slow(self):
        fake = ClockedIo({name: LIMITS.fast_seconds for name in READINGS}, [100], {})
        _, lines, record, _ = clocked_samples(fake, 3)
        self.assertEqual(lines, [])
        self.assertEqual(record["slow_readings"], 0)
        self.assertEqual(record["slow_reading_recent"], [])

    def test_a_slow_reading_that_fails_is_still_named(self):
        fake = ClockedIo({"table": 2.5}, [10], w1_and_w2(), broken={"table"})
        _, lines, record, stderr = clocked_samples(fake, 3)
        self.assertEqual(lines, [f"{AT} slow_reading reading=table seconds=2.5\n"] * 3)
        self.assertEqual(record["slow_readings"], 3)
        self.assertEqual(fake.signals, [])
        self.assertIn("table could not run", stderr)
        upgraded = {
            "since": "2026-11-20T00:00:00+00:00", "kills": 2, "recent": [], "floor_unmets": 0,
            "floor_unmet_recent": [],
        }
        rows = {"first_available_fresh_record": ({}, 0), "first_available_upgraded_record": (upgraded, 2)}
        for name, (record, kills) in rows.items():
            with self.subTest(name):
                fake = ClockedIo({"available": 2.5}, [10], {}, broken={"available"})
                intervals, lines, record, stderr = clocked_samples(fake, 1, record)
                self.assertEqual(intervals, [LIMITS.fast_seconds])
                self.assertEqual(lines, [f"{AT} slow_reading reading=available seconds=2.5\n"])
                self.assertEqual(record["slow_readings"], 1)
                self.assertEqual(len(record["slow_reading_recent"]), 1)
                self.assertIn("available could not run", stderr)
                self.assertEqual(record.get("kills"), kills)


def counting(daemon, after_first=None):
    """Replace the daemon's process table reading with one that counts its calls."""
    original, calls = daemon.io.table, []

    def table():
        result = original()
        calls.append(1)
        if len(calls) == 1 and after_first:
            after_first()
        return result

    daemon.io.table = table
    return calls


class ReuseTest(unittest.TestCase):
    def test_a_floor_kill_reads_the_process_table_once_before_its_first_kill(self):
        daemon = Daemon([10, 10, 10, 40], w1_and_w2())
        calls = counting(daemon)
        daemon.sample(3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(daemon.record["recent"]), 1)

    def test_a_run_bound_kill_reads_the_table_again_before_the_floor_pass(self):
        daemon = Daemon(
            [10, 13, 40],
            table_of(proc(300, 1, 501, W1, 30, "node vitest run"), proc(310, 1, 501, W2, 4)),
        )
        daemon.loop.streak = 2

        def later():
            daemon.fake.base = table_of(proc(320, 1, 501, "/private/tmp/verify-pending-ab12cd34/src", 5, "node later"))

        calls = counting(daemon, later)
        daemon.sample()
        self.assertEqual(len(calls), 2)
        self.assertEqual([e["reason"] for e in daemon.record["recent"]], ["run_bound", "floor"])
        self.assertEqual([e["root_pid"] for e in daemon.record["recent"]], [300, 320])


class MemoryReaderTest(unittest.TestCase):
    TOTAL = "274877906944"

    def tools(self, scratch):
        scratch = Path(scratch)
        vm_stat, sysctl = scratch / "vm_stat", scratch / "sysctl"
        vm_stat.write_text(f"#!/bin/sh\ncat {scratch}/vm.txt\n")
        sysctl.write_text(
            f"#!/bin/sh\necho x >> {scratch}/count\n[ -e {scratch}/fail ] && exit 1\necho {self.TOTAL}\n"
        )
        for tool in (vm_stat, sysctl):
            tool.chmod(0o755)
        return scratch, memory_reader(str(vm_stat), str(sysctl))

    def test_the_host_memory_size_is_read_once(self):
        with tempfile.TemporaryDirectory() as directory:
            scratch, read = self.tools(directory)
            results = []
            for text in (VM_STAT, VM_STAT_LOW, VM_STAT):
                (scratch / "vm.txt").write_text(text)
                results.append(read())
            self.assertEqual(
                results, [read_available(text, self.TOTAL) for text in (VM_STAT, VM_STAT_LOW, VM_STAT)]
            )
            self.assertNotEqual(results[0], results[1])
            self.assertEqual(len((scratch / "count").read_text().splitlines()), 1)

    def test_a_failed_host_memory_size_is_read_again(self):
        with tempfile.TemporaryDirectory() as directory:
            scratch, read = self.tools(directory)
            (scratch / "vm.txt").write_text(VM_STAT)
            (scratch / "fail").write_text("")
            with self.assertRaises(ReadingError):
                read()
            os.remove(scratch / "fail")
            self.assertEqual([read(), read()], [read_available(VM_STAT, self.TOTAL)] * 2)
            self.assertEqual(len((scratch / "count").read_text().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
