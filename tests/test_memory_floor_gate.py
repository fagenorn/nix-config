"""The oMLX relaunch gate of the eleven-m5 memory floor.

The gate runs before `omlx serve` starts: it waits while available memory is under the floor and
starts at once when memory is over it or cannot be read. Calls `agent_tools.hosts.memory_floor`
with a scripted reading, sleep and log, and runs the `gate` command against fake host tools.
Run: just agent-workflow-tests
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.hosts.memory_floor import GIB, wait_for_floor
from agent_tools.hosts.omlx_memory_watch import ReadingError
from tests.test_omlx_memory_watch import VM_STAT

TIER = "fast"

ROOT = Path(__file__).resolve().parent.parent
TOTAL = 274877906944


def scripted(*readings):
    values = iter(readings)

    def read():
        value = next(values)
        if isinstance(value, Exception):
            raise value
        return value

    return read


class GateTest(unittest.TestCase):
    def setUp(self):
        self.sleeps, self.lines = [], []

    def gate(self, *readings, floor_gib=16, interval=2):
        return wait_for_floor(
            scripted(*readings), floor_gib * GIB, interval, self.sleeps.append, self.lines.append
        )

    def test_the_gate_waits_under_the_floor_and_starts_once_at_or_over_it(self):
        waits = self.gate(10 * GIB, 12 * GIB, 16 * GIB)
        self.assertEqual(waits, 2)
        self.assertEqual(self.sleeps, [2, 2])
        self.assertEqual(
            self.lines,
            [
                "oMLX start waits: available 10.0 GiB is under the 16 GiB floor",
                "oMLX start: available 16.0 GiB, starting after 2 waits",
            ],
        )

    def test_memory_at_or_over_the_floor_starts_at_once(self):
        self.assertEqual(self.gate(40 * GIB), 0)
        self.assertEqual(self.sleeps, [])
        self.assertEqual(self.lines, [])

    def test_an_unreadable_reading_starts_at_once(self):
        self.assertEqual(self.gate(ReadingError("vm_stat exited 1")), 0)
        self.assertEqual(self.sleeps, [])
        self.assertEqual(len(self.lines), 1)
        self.assertTrue(self.lines[0].startswith("oMLX start: memory unreadable (vm_stat exited 1)"))


class GateCliTest(unittest.TestCase):
    def test_the_gate_command_reads_the_host_tools_and_exits_0(self):
        with tempfile.TemporaryDirectory() as scratch:
            vm_stat, sysctl = Path(scratch, "vm_stat"), Path(scratch, "sysctl")
            vm_stat.write_text(f"#!/bin/sh\ncat <<'EOF'\n{VM_STAT}EOF\n")
            sysctl.write_text(f"#!/bin/sh\necho {TOTAL}\n")
            for tool in (vm_stat, sysctl):
                tool.chmod(0o755)
            env = {**os.environ, "PYTHONPATH": str(ROOT / "python")}
            result = subprocess.run(
                [
                    sys.executable, "-m", "agent_tools.hosts.memory_floor", "gate",
                    "--floor-gib", "16", "--interval-seconds", "2",
                    "--vm-stat", str(vm_stat), "--sysctl", str(sysctl),
                ],
                capture_output=True, text=True, env=env, timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
