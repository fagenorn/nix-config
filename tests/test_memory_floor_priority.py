"""The eleven-m5 memory floor's kernel jetsam priority for oMLX.

launchd ignores the oMLX daemon's `JetsamProperties`, so the floor daemon sets the priority on the
running pid. Calls `agent_tools.hosts.memory_floor` against a fake `memorystatus_control` (no kernel
call, so it runs on Linux) that keeps a pid -> priority map: what is read, when it is set, what the
record keeps (the value read before the set, and the resets of one pid), and the byte layout of
both kernel structs.
Run: just agent-workflow-tests
"""

import contextlib
import dataclasses
import errno
import io
import unittest

from agent_tools.hosts.memory_floor import (
    ENTRY,
    GET_PRIORITY_LIST,
    JETSAM_PRIORITY_DEFAULT,
    JETSAM_PRIORITY_MAX,
    PROPERTIES,
    SET_PRIORITY_PROPERTIES,
    Io,
    Loop,
    build_parser,
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
    def __init__(self, priorities, pid=PID, refuse=False, limits=LIMITS):
        self.limits = limits
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
            enforce_once(self.limits, OWNERS, self.io, self.loop, self.record, self.lines.append)


class PriorityTest(unittest.TestCase):
    def test_a_kernel_priority_above_the_declared_one_is_never_lowered(self):
        daemon = PriorityDaemon({PID: 180}, limits=dataclasses.replace(LIMITS, jetsam_priority=100))
        daemon.sample(2)
        daemon.pid = NEXT_PID
        daemon.control.put_back(NEXT_PID, 200)
        daemon.sample()
        self.assertEqual(daemon.control.sets(), [])
        self.assertEqual(daemon.control.priorities[PID], 180)
        self.assertEqual(
            daemon.lines,
            [
                "2026-11-24T12:33:05+00:00 jetsam_priority_kept pid=55731 kernel=180 declared=100"
                " reason=kernel_above_declared\n",
                "2026-11-24T12:33:05+00:00 jetsam_priority_kept pid=55800 kernel=200 declared=100"
                " reason=kernel_above_declared\n",
            ],
        )
        self.assertEqual(daemon.record["omlx_kernel_priority"], 200)
        self.assertEqual(daemon.record["omlx_priority_resets"], 0)

    def test_a_kernel_priority_under_the_declared_one_is_raised_and_logged_before_and_after(self):
        daemon = PriorityDaemon({PID: 180})
        daemon.sample()
        self.assertEqual(
            daemon.control.sets(), [(SET_PRIORITY_PROPERTIES, PID, PROPERTIES.pack(190, 0))]
        )
        record = daemon.record
        self.assertEqual(record["omlx_pid"], PID)
        self.assertEqual(record["omlx_kernel_priority"], 180)
        self.assertEqual(record["omlx_priority_reads"], 1)
        self.assertEqual(record["omlx_priority_resets"], 0)
        self.assertEqual(record["declared_priority"], 190)
        self.assertIsNone(record["omlx_priority_error"])
        self.assertEqual(
            daemon.lines,
            ["2026-11-24T12:33:05+00:00 jetsam_priority pid=55731 from=180 to=190 after=190 resets=0\n"],
        )
        daemon.sample()
        self.assertEqual(len(daemon.control.sets()), 1)
        self.assertEqual(record["omlx_kernel_priority"], 190)
        self.assertEqual(record["omlx_priority_reads"], 2)
        self.assertEqual(record["omlx_priority_resets"], 0)

    def test_a_priority_put_back_between_samples_counts_each_reset(self):
        daemon = PriorityDaemon({PID: 180})
        for _ in range(2):
            daemon.sample()
            daemon.control.put_back(PID, 180)
        daemon.sample()
        record = daemon.record
        self.assertEqual(len(daemon.control.sets()), 3)
        self.assertEqual(record["omlx_kernel_priority"], 180)
        self.assertEqual(record["omlx_priority_reads"], 3)
        self.assertEqual(record["omlx_priority_resets"], 2)
        self.assertTrue(daemon.lines[-1].endswith("from=180 to=190 after=190 resets=2\n"))
        daemon.pid = NEXT_PID
        daemon.control.put_back(NEXT_PID, 180)
        daemon.sample()
        self.assertEqual(record["omlx_pid"], NEXT_PID)
        self.assertEqual(record["omlx_priority_reads"], 1)
        self.assertEqual(record["omlx_priority_resets"], 0)

    def test_an_equal_kernel_priority_is_left_alone(self):
        daemon = PriorityDaemon({PID: 190})
        daemon.sample()
        self.assertEqual(daemon.control.sets(), [])
        self.assertEqual(daemon.lines, [])
        self.assertEqual(daemon.record["omlx_kernel_priority"], 190)

    def test_a_refused_set_is_logged_once_per_pid(self):
        daemon = PriorityDaemon({PID: 180, NEXT_PID: 180}, refuse=True)
        daemon.sample(3)
        failed = "2026-11-24T12:33:05+00:00 jetsam_priority_failed pid=55731 error=EPERM\n"
        self.assertEqual(daemon.lines, [failed])
        record = daemon.record
        self.assertEqual(record["omlx_priority_error"], "EPERM")
        self.assertEqual(record["omlx_kernel_priority"], 180)
        self.assertEqual(record["omlx_priority_resets"], 0)
        daemon.pid = NEXT_PID
        daemon.sample()
        self.assertEqual(daemon.lines, [failed, failed.replace("55731", "55800")])

    def test_no_omlx_pid_reads_nothing(self):
        daemon = PriorityDaemon({PID: 180}, pid=None)
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

    def test_enforce_refuses_a_declared_priority_outside_the_bands_above_the_default(self):
        base = [
            "enforce", "--floor-gib", "16", "--run-bound-gib", "24", "--agent-user", "x",
            "--agent-root", "/r/*", "--record", "/nonexistent/floor.json", "--omlx-jetsam-priority",
        ]
        self.assertEqual(JETSAM_PRIORITY_DEFAULT, 180)
        self.assertEqual(JETSAM_PRIORITY_MAX, 210)
        for value in ("100", "180", "211"):
            with self.subTest(refused=value), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    build_parser().parse_args(base + [value])
                self.assertEqual(raised.exception.code, 2)
        for value in ("181", "190", "210"):
            with self.subTest(accepted=value):
                self.assertEqual(build_parser().parse_args(base + [value]).omlx_jetsam_priority, int(value))


if __name__ == "__main__":
    unittest.main()
