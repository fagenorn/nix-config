"""The eleven-m5 root census: `omlx-memory-watch census` and `parse_census`.

Runs `agent_tools.hosts.omlx_memory_watch` as a child with a fake `footprint` script: what the
census records from `footprint -a`'s JSON (footprint's own total, not a sum of processes), and
which reports it refuses as incomplete or not parseable.
Run: just agent-workflow-tests
"""

import copy
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.hosts import omlx_memory_watch

TIER = "fast"

ROOT = Path(__file__).resolve().parent.parent

FOOTPRINT_ALL = {
    "unit": "byte",
    "bytes per unit": 1,
    "processes": [
        {"name": "Python", "pid": 73552, "footprint": 187360249992},
        {"name": "postgres", "pid": 25342, "footprint": 4294967296},
        {"name": "com.apple.Virtualization.VirtualMachine", "pid": 71884, "footprint": 8589934592},
        {"name": "dotnet", "pid": 5001, "footprint": 3221225472},
        {"name": "node", "pid": 5002, "footprint": 2147483648},
        {"name": "zsh", "pid": 54043, "footprint": 2916760},
    ],
    "total footprint": 205000000000,
    "auxiliary": {"sys_wired": 5070684160, "sys_unwired": 207825338368,
                  "boot_carveout": 1243693056, "sys_footprint": 214139715584},
    "errors": [],
    "warnings": [],
}
TOP_FIVE = [
    {"name": "Python", "pid": 73552, "bytes": 187360249992},
    {"name": "com.apple.Virtualization.VirtualMachine", "pid": 71884, "bytes": 8589934592},
    {"name": "postgres", "pid": 25342, "bytes": 4294967296},
    {"name": "dotnet", "pid": 5001, "bytes": 3221225472},
    {"name": "node", "pid": 5002, "bytes": 2147483648},
]
FIGURES = ("warnings", "sys_footprint_bytes", "process_footprint_bytes", "unowned_bytes", "processes", "top_owners")


def document(**changes):
    found = copy.deepcopy(FOOTPRINT_ALL)
    found.update(changes)
    return found


class CensusTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.d = Path(scratch.name)
        self.record = self.d / "db" / "census.json"
        self.env = {**os.environ, "PYTHONPATH": str(ROOT / "python")}
        self.report(FOOTPRINT_ALL)
        script = self.d / "footprint"
        script.write_text(
            "#!/bin/sh\n"
            'out="["; sep=""\nfor a in "$@"; do out="$out$sep\\"$a\\""; sep=", "; done\n'
            f'echo "$out]" >> "{self.d}/footprint.log"\n'
            f'if [ -e "{self.d}/footprint.fail" ]; then exit 66; fi\n'
            f'if [ -e "{self.d}/footprint.slow" ]; then sleep 5; fi\n'
            'while [ "$1" != "-j" ]; do shift; done\n'
            f'cp "{self.d}/footprint-all.json" "$2"\n'
            f'if [ -e "{self.d}/footprint.exit3" ]; then exit 3; fi\n'
        )
        script.chmod(0o755)

    def report(self, found):
        (self.d / "footprint-all.json").write_text(json.dumps(found))

    def flag(self, name):
        (self.d / name).write_text("")

    def census(self, *extra):
        argv = [
            sys.executable, "-m", "agent_tools.hosts.omlx_memory_watch", "census",
            "--record", str(self.record), "--footprint", str(self.d / "footprint"),
            "--now", "2026-11-25T13:00:00+00:00", *extra,
        ]
        return subprocess.run(argv, capture_output=True, text=True, env=self.env, timeout=60)

    def written(self):
        return json.loads(self.record.read_text())

    def test_the_census_records_footprints_own_total_not_a_sum_of_processes(self):
        done = self.census()
        self.assertEqual(done.returncode, 0, done.stderr)
        found = self.written()
        self.assertEqual(found["sys_footprint_bytes"], 214139715584)
        self.assertEqual(found["process_footprint_bytes"], 205000000000)
        self.assertEqual(found["unowned_bytes"], 9139715584)
        self.assertEqual(found["processes"], 6)
        self.assertEqual(found["top_owners"], TOP_FIVE)
        self.assertEqual(found["at"], "2026-11-25T13:00:00+00:00")
        self.assertIsNone(found["error"])
        self.assertEqual(found["warnings"], 0)
        self.assertEqual(found["footprint_exit"], 0)
        self.assertIsInstance(found["seconds"], float)
        self.assertGreaterEqual(found["seconds"], 0)
        self.assertEqual(
            list(found), ["at", "seconds", "footprint_exit", "error", *FIGURES])
        calls = [json.loads(line) for line in (self.d / "footprint.log").read_text().splitlines()]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:4], ["-a", "--sysFootprint", "--noCategories", "-j"])
        self.assertEqual(len(calls[0]), 5)
        self.assertTrue(calls[0][4].endswith("/footprint.json"), calls[0])
        self.assertEqual(stat.S_IMODE(self.record.stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(self.record.parent.stat().st_mode), 0o755)

    def test_a_negative_difference_is_recorded_with_its_sign(self):
        found = document()
        found["total footprint"] = 222264557568
        found["auxiliary"]["sys_footprint"] = 222049809203
        self.report(found)
        self.assertEqual(self.census().returncode, 0)
        self.assertEqual(self.written()["unowned_bytes"], -214748365)

    def test_a_failed_footprint_writes_an_error_record_and_exits_1(self):
        self.flag("footprint.fail")
        done = self.census()
        text = "footprint output not parseable (exit 66)"
        self.assertEqual(done.returncode, 1)
        self.assertIn(text, done.stderr)
        found = self.written()
        self.assertEqual(found["error"], text)
        self.assertEqual(found["footprint_exit"], 66)
        for key in FIGURES:
            with self.subTest(key=key):
                self.assertIsNone(found[key])

    def test_a_footprint_over_the_timeout_is_an_error(self):
        self.flag("footprint.slow")
        done = self.census("--timeout-seconds", "1")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.written()["error"], "footprint timed out after 1 s")

    def test_json_without_the_system_footprint_is_not_parseable(self):
        found = document()
        del found["auxiliary"]
        self.report(found)
        self.assertEqual(self.census().returncode, 1)
        self.assertIsNone(self.written()["unowned_bytes"])

    def test_a_complete_report_with_a_nonzero_exit_is_a_census(self):
        self.flag("footprint.exit3")
        done = self.census()
        self.assertEqual(done.returncode, 0, done.stderr)
        found = self.written()
        self.assertEqual(found["footprint_exit"], 3)
        self.assertIsNone(found["error"])
        self.assertEqual(found["unowned_bytes"], 9139715584)

    def test_a_report_with_totals_and_process_errors_is_incomplete(self):
        self.report(document(errors=["pid 4321: could not read its memory"]))
        done = self.census()
        text = "footprint census incomplete (errors: 1)"
        self.assertEqual(done.returncode, 1)
        self.assertIn(text, done.stderr)
        found = self.written()
        self.assertEqual(found["error"], text)
        for key in ("unowned_bytes", "processes", "top_owners"):
            with self.subTest(key=key):
                self.assertIsNone(found[key])


class ParseCensusTest(unittest.TestCase):
    def test_entries_without_a_numeric_footprint_are_left_out(self):
        found = document()
        found["processes"] += [
            {"name": "x", "pid": 9, "footprint": None},
            {"name": "y", "pid": True, "footprint": 10**13},
        ]
        got = omlx_memory_watch.parse_census(found)
        self.assertEqual(got["processes"], 6)
        self.assertEqual(got["top_owners"], TOP_FIVE)

    def test_a_report_not_counted_in_bytes_is_refused(self):
        without_errors = document()
        del without_errors["errors"]
        for name, found in (
            ("unit", document(unit="page")),
            ("bytes per unit", document(**{"bytes per unit": 16384})),
            ("errors", without_errors),
            ("processes", document(processes=[])),
        ):
            with self.subTest(name=name):
                with self.assertRaises(ValueError) as caught:
                    omlx_memory_watch.parse_census(found)
                self.assertNotIsInstance(caught.exception, omlx_memory_watch.CensusIncomplete)


if __name__ == "__main__":
    unittest.main()
