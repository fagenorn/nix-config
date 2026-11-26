"""The eleven-m5 memory floor against a fast-growing agent tree outside every declared root.

Drives `enforce_once` with a clock that advances by what each reading costs, while a probe below an
agent session grows a GiB a second, and checks the run bound ends the tree before memory runs under
the floor. Run: just agent-workflow-tests
"""

import contextlib
import io as stdio
import unittest

from agent_tools.hosts.memory_floor import GIB, Limits, Loop, enforce_once
from tests.test_memory_floor import OWNERS, FakeIo, SCRATCH, proc, session_tree

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


if __name__ == "__main__":
    unittest.main()
