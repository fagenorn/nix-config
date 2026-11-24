"""The eleven-m5 memory floor's kernel jetsam priority for oMLX.

launchd ignores the oMLX daemon's `JetsamProperties`, so the floor daemon sets the priority on the
running pid. Calls `agent_tools.hosts.memory_floor` against a fake `memorystatus_control` (no kernel
call, so it runs on Linux) that keeps a pid -> priority map: what is read, when it is set, what the
record keeps (the value read before the set, and the resets of one pid), and the byte layout of
both kernel structs.
Run: just agent-workflow-tests
"""

import errno
import unittest

from agent_tools.hosts.memory_floor import (
    ENTRY,
    GET_PRIORITY_LIST,
    PROPERTIES,
    SET_PRIORITY_PROPERTIES,
    Io,
    Loop,
    enforce_once,
    kernel_priority,
    set_kernel_priority,
)
from tests.test_memory_floor import LIMITS, OWNERS, FakeIo

TIER = "fast"

PID = 55731
NEXT_PID = 55800


class FakeControl:
    """memorystatus_control over a {pid: priority} map; a successful SET stores the value."""

    def __init__(self, priorities, refuse=False):
        self.priorities = dict(priorities)
        self.refuse = refuse
        self.calls = []

    def __call__(self, command, pid, flags, buffer):
        self.calls.append((command, pid, bytes(buffer)))
        if command == GET_PRIORITY_LIST:
            if pid not in self.priorities:
                return 0
            buffer[:] = ENTRY.pack(pid, self.priorities[pid], 0, -1, 0)
            return ENTRY.size
        if self.refuse:
            raise OSError(errno.EPERM, "Operation not permitted")
        self.priorities[pid] = PROPERTIES.unpack(bytes(buffer))[0]
        return 0

    def put_back(self, pid, value):
        self.priorities[pid] = value

    def sets(self):
        return [call for call in self.calls if call[0] == SET_PRIORITY_PROPERTIES]


class PriorityDaemon:
    def __init__(self, priorities, pid=PID, refuse=False):
        self.control = FakeControl(priorities, refuse)
        self.pid = pid
        self.fake = FakeIo([100], {})
        self.fake.omlx_pid = lambda: self.pid
        self.fake.priority_get = lambda pid: kernel_priority(pid, self.control)
        self.fake.priority_set = lambda pid, priority: set_kernel_priority(pid, priority, self.control)
        self.io: Io = self.fake.io()
        self.loop = Loop()
        self.record = {}
        self.lines = []

    def sample(self, times=1):
        for _ in range(times):
            enforce_once(LIMITS, OWNERS, self.io, self.loop, self.record, self.lines.append)


class PriorityTest(unittest.TestCase):
    def test_a_differing_kernel_priority_is_set_to_the_declared_one(self):
        daemon = PriorityDaemon({PID: 40})
        daemon.sample()
        self.assertEqual(
            daemon.control.sets(), [(SET_PRIORITY_PROPERTIES, PID, PROPERTIES.pack(100, 0))]
        )
        record = daemon.record
        self.assertEqual(record["omlx_pid"], PID)
        self.assertEqual(record["omlx_kernel_priority"], 40)
        self.assertEqual(record["omlx_priority_reads"], 1)
        self.assertEqual(record["omlx_priority_resets"], 0)
        self.assertEqual(record["declared_priority"], 100)
        self.assertIsNone(record["omlx_priority_error"])
        self.assertEqual(
            daemon.lines,
            ["2026-11-24T12:33:05+00:00 jetsam_priority pid=55731 from=40 to=100 resets=0\n"],
        )
        daemon.sample()
        self.assertEqual(len(daemon.control.sets()), 1)
        self.assertEqual(record["omlx_kernel_priority"], 100)
        self.assertEqual(record["omlx_priority_reads"], 2)
        self.assertEqual(record["omlx_priority_resets"], 0)

    def test_a_priority_put_back_between_samples_counts_each_reset(self):
        daemon = PriorityDaemon({PID: 40})
        for _ in range(2):
            daemon.sample()
            daemon.control.put_back(PID, 40)
        daemon.sample()
        record = daemon.record
        self.assertEqual(len(daemon.control.sets()), 3)
        self.assertEqual(record["omlx_kernel_priority"], 40)
        self.assertEqual(record["omlx_priority_reads"], 3)
        self.assertEqual(record["omlx_priority_resets"], 2)
        self.assertTrue(daemon.lines[-1].endswith("from=40 to=100 resets=2\n"))
        daemon.pid = NEXT_PID
        daemon.control.put_back(NEXT_PID, 40)
        daemon.sample()
        self.assertEqual(record["omlx_pid"], NEXT_PID)
        self.assertEqual(record["omlx_priority_reads"], 1)
        self.assertEqual(record["omlx_priority_resets"], 0)

    def test_an_equal_kernel_priority_is_left_alone(self):
        daemon = PriorityDaemon({PID: 100})
        daemon.sample()
        self.assertEqual(daemon.control.sets(), [])
        self.assertEqual(daemon.lines, [])
        self.assertEqual(daemon.record["omlx_kernel_priority"], 100)

    def test_a_refused_set_is_logged_once_per_pid(self):
        daemon = PriorityDaemon({PID: 40, NEXT_PID: 40}, refuse=True)
        daemon.sample(3)
        failed = "2026-11-24T12:33:05+00:00 jetsam_priority_failed pid=55731 error=EPERM\n"
        self.assertEqual(daemon.lines, [failed])
        record = daemon.record
        self.assertEqual(record["omlx_priority_error"], "EPERM")
        self.assertEqual(record["omlx_kernel_priority"], 40)
        self.assertEqual(record["omlx_priority_resets"], 0)
        daemon.pid = NEXT_PID
        daemon.sample()
        self.assertEqual(daemon.lines, [failed, failed.replace("55731", "55800")])

    def test_no_omlx_pid_reads_nothing(self):
        daemon = PriorityDaemon({PID: 40}, pid=None)
        daemon.sample()
        self.assertEqual(daemon.control.calls, [])
        self.assertIsNone(daemon.record["omlx_pid"])
        self.assertIsNone(daemon.record["omlx_kernel_priority"])
        self.assertEqual(daemon.record["omlx_priority_reads"], 0)

    def test_the_memorystatus_buffers_match_the_kernel_structs(self):
        self.assertEqual(ENTRY.size, 24)
        self.assertEqual(PROPERTIES.size, 16)
        self.assertEqual(kernel_priority(PID, FakeControl({PID: 40})), 40)
        self.assertIsNone(kernel_priority(PID, FakeControl({})))
        control = FakeControl({})
        set_kernel_priority(PID, 100, control)
        self.assertEqual(control.calls, [(SET_PRIORITY_PROPERTIES, PID, PROPERTIES.pack(100, 0))])


if __name__ == "__main__":
    unittest.main()
