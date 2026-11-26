"""The verify-slot tree peak: each run's whole-tree footprint, read while its command runs, lands in its history line.

Runs `verify-slot run` as a child process against a scratch slot directory and a fake `footprint`
script, and `agent_tools.delivery.verify_tree` and `verify_history.read` in-process.
Run: just agent-workflow-tests
"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_tools.canonical import parse_rfc3339_utc
from agent_tools.delivery import verify_history, verify_tree

TIER = "fast"

ROOT = Path(__file__).resolve().parent.parent
GIB = 1 << 30
TREE = {
    "unit": "byte", "bytes per unit": 1, "errors": [], "total footprint": 3 * GIB,
    "processes": [{"pid": 1, "name": "python3", "footprint": GIB // 2},
                  {"pid": 2, "name": "node", "footprint": 11 * GIB // 4}],
}
BASE = {"command": "just test", "exit": 0, "held_seconds": 30.0, "repository": "o/r",
        "started": "2026-11-24T12:00:00Z", "waited_seconds": 0.0}


def total(amount):
    return {**copy.deepcopy(TREE), "total footprint": amount}


def fake_footprint(directory, reports):
    """An executable `footprint` that logs its arguments and answers the reports in turn, the last one for good."""
    for index, document in enumerate(reports):
        (directory / f"report-{index}.json").write_text(json.dumps(document))
    path = directory / "footprint"
    path.write_text(
        "#!/bin/sh\n"
        'out="["; sep=""\nfor a in "$@"; do out="$out$sep\\"$a\\""; sep=", "; done\n'
        f'echo "$out]" >> "{directory}/footprint.log"\n'
        f'if [ -e "{directory}/footprint.fail" ]; then exit 66; fi\n'
        f'n=0; if [ -e "{directory}/count" ]; then n=$(cat "{directory}/count"); fi\n'
        f'i=$n; if [ "$i" -gt {len(reports) - 1} ]; then i={len(reports) - 1}; fi\n'
        'while [ $# -gt 0 ]; do if [ "$1" = "-j" ]; then dest="$2"; fi; shift; done\n'
        f'cp "{directory}/report-$i.json" "$dest"\n'
        f'echo $((n + 1)) > "{directory}/count"\n')
    path.chmod(0o755)
    return path


class VerifyRunTreeTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.d = Path(scratch.name)
        (self.d / "work").mkdir()
        self.log = self.d / "footprint.log"

    def run_verify(self, argv, footprint):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "python"), "HOME": str(self.d / "home"),
               "VERIFY_SLOT_DIR": str(self.d / "slots"), "VERIFY_SLOT_FOOTPRINT": str(footprint)}
        (self.d / "home").mkdir(exist_ok=True)
        result = subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.verify_slot", "run", "--", *argv],
            cwd=self.d / "work", env=env, capture_output=True, text=True, timeout=60)
        history = (self.d / "slots" / "history.jsonl").read_text().splitlines()
        return result, [json.loads(line) for line in history]

    def log_lines(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_a_verify_run_records_its_trees_total_footprint_in_its_history_line(self):
        fake = fake_footprint(self.d, [TREE])
        pid_file = self.d / "child.pid"
        code = ("import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(0.5)")
        result, lines = self.run_verify([sys.executable, "-c", code, str(pid_file)], fake)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertEqual(line["tree_peak_bytes"], 3 * GIB)
        started = parse_rfc3339_utc(line["started"])
        at = parse_rfc3339_utc(line["tree_peak_at"])
        window = timedelta(seconds=line["waited_seconds"] + line["held_seconds"] + 1)
        self.assertTrue(started <= at <= started + window, (started, at, window))
        arguments = json.loads(self.log_lines()[0])
        self.assertEqual(arguments[0], "-p")
        self.assertEqual(arguments[1], pid_file.read_text())
        self.assertEqual(arguments[2:7], ["-t", "-f", "bytes", "--noCategories", "-j"])
        self.assertEqual(len(arguments), 8)

    def test_the_peak_is_the_largest_reading_and_a_tie_keeps_the_earlier_time(self):
        fake = fake_footprint(self.d, [total(GIB), TREE, TREE, total(2 * GIB)])
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        ticks = iter(range(1000))
        clock = lambda: datetime(2026, 11, 24, 12, 0, next(ticks), tzinfo=timezone.utc)
        peak = verify_tree.TreePeak(child.pid, str(fake), interval=0.05, clock=clock)
        peak.start()
        deadline = time.monotonic() + 10
        while len(self.log_lines()) < 5 and time.monotonic() < deadline:
            time.sleep(0.05)
        result = peak.stop()
        reads = len(self.log_lines())
        time.sleep(0.3)
        self.assertEqual(result, (3 * GIB, "2026-11-24T12:00:01Z"))
        self.assertEqual(len(self.log_lines()), reads)

    def test_a_report_counts_only_as_a_complete_byte_report(self):
        self.assertEqual(verify_tree.parse_tree(TREE), 3 * GIB)
        for change in ({"errors": [{"pid": 1}]}, {"unit": "page"}, {"bytes per unit": True},
                       {"bytes per unit": 2}, {"total footprint": "1"}, {"total footprint": True}):
            with self.subTest(change=change):
                self.assertIsNone(verify_tree.parse_tree({**TREE, **change}))
        missing = {key: value for key, value in TREE.items() if key != "total footprint"}
        self.assertIsNone(verify_tree.parse_tree(missing))
        self.assertIsNone(verify_tree.parse_tree([TREE]))

    def test_a_missing_or_failing_footprint_records_no_tree_and_keeps_the_exit(self):
        result, lines = self.run_verify(["sh", "-c", "exit 3"], self.d / "absent")
        self.assertEqual(result.returncode, 3)
        fake = fake_footprint(self.d, [TREE])
        (self.d / "footprint.fail").write_text("")
        result, lines = self.run_verify(["sh", "-c", "sleep 0.3; exit 4"], fake)
        self.assertEqual(result.returncode, 4)
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertIsNone(line["tree_peak_bytes"])
            self.assertIsNone(line["tree_peak_at"])

    def test_history_lines_with_bad_tree_fields_are_skipped_and_old_lines_still_read(self):
        good = [BASE, {**BASE, "tree_peak_bytes": None, "tree_peak_at": None},
                {**BASE, "tree_peak_bytes": 3 * GIB, "tree_peak_at": "2026-11-24T12:00:10Z"}]
        at = "2026-11-24T12:00:10Z"
        bad = [{**BASE, "tree_peak_bytes": True, "tree_peak_at": at},
               {**BASE, "tree_peak_bytes": -1, "tree_peak_at": at},
               {**BASE, "tree_peak_bytes": "1", "tree_peak_at": at},
               {**BASE, "tree_peak_bytes": 1, "tree_peak_at": "yesterday"},
               {**BASE, "tree_peak_bytes": 1, "tree_peak_at": None},
               {**BASE, "tree_peak_bytes": None, "tree_peak_at": at}]
        path = self.d / "history.jsonl"
        path.write_text("".join(json.dumps(record) + "\n" for record in [*good, *bad]))
        records, skipped = verify_history.read(path)
        self.assertEqual(records, good)
        self.assertEqual(skipped, 6)


if __name__ == "__main__":
    unittest.main()
