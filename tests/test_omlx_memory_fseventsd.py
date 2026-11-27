"""The eleven-m5 watcher's fseventsd restart and its sampling of the restart record.

Runs `agent_tools.hosts.omlx_memory_watch` as a child with fake `launchctl`, `footprint`, `kill`,
`vm_stat`, `sysctl` and `ps` scripts: when the `fseventsd` subcommand restarts the daemon, what it
records, and how `sample` folds that record into its state, day line and alerts.
Run: just agent-workflow-tests
"""

import json
import os
import plistlib
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_host_alerts import PROXY_VARIABLES, SETTINGS, Bot

TIER = "fast"

ROOT = Path(__file__).resolve().parent.parent
GIB = 1024**3
TOTAL = 274877906944
NOW = "2026-11-24T12:00:00"

LAUNCHCTL = "system/com.apple.fseventsd = {\n\tpid = 29194\n\truns = 2\n\tproperties = {\n\t\tpid = 1\n\t}\n}\n"
LAUNCHCTL_RUNS_ONLY = "system/org.nixos.omlx = {\n\truns = 7\n\tstate = running\n}\n"
VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages wired down:                          302081.
Pages purgeable:                             4054.
Anonymous pages:                         12906856.
Pages occupied by compressor:              105539.
"""


def record(**kw):
    base = {
        "at": "2026-11-24T11:59:00", "pid": 29194, "footprint_bytes": 2 * GIB, "limit_bytes": 4 * GIB,
        "restarts": 0, "last_restart_at": None, "held": False, "restart_failed": False,
    }
    base.update(kw)
    return base


def state(**kw):
    base = {
        "since": "2026-11-24", "day": "2026-11-24", "peak_used_bytes": 0, "peak_others_bytes": None,
        "peak_omlx_bytes": None, "min_available_bytes": TOTAL, "samples": 0, "loaded_samples": 0,
        "min_loaded_available_bytes": None, "peak_ci_jobs": 0, "jetsam_exits": 0, "omlx_runs": 7,
        "omlx_jetsam_priority": None, "low_memory_open": False, "pending": [],
        "fseventsd_bytes": None, "peak_fseventsd_bytes": None, "fseventsd_restarts_seen": None,
        "fseventsd_restarts_today": 0, "fseventsd_held_open": False,
    }
    base.update(kw)
    return base


class FakeHost(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.d = Path(scratch.name)
        self.env = {k: v for k, v in os.environ.items() if k not in PROXY_VARIABLES}
        self.env["PYTHONPATH"] = str(ROOT / "python")
        self.record_file = self.d / "db" / "fseventsd.json"

    def fake(self, name, body):
        path = self.d / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    def logging_script(self, log):
        return (
            'out="["; sep=""\nfor a in "$@"; do out="$out$sep\\"$a\\""; sep=", "; done\n'
            f'echo "$out]" >> "{self.d}/{log}"\n'
        )

    def log_json(self, name):
        return [json.loads(line) for line in (self.d / name).read_text().splitlines()]

    def run_module(self, argv, env=None):
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.hosts.omlx_memory_watch", *argv],
            capture_output=True, text=True, env=env or self.env, timeout=60)


class TrimTest(FakeHost):
    def setUp(self):
        super().setUp()
        self.launchctl(LAUNCHCTL)
        self.footprint(5 * GIB)
        self.fake("kill", self.logging_script("kill.log") + f'if [ -e "{self.d}/kill.fail" ]; then exit 1; fi\n')

    def launchctl(self, text):
        (self.d / "launchctl.txt").write_text(text)
        self.fake("launchctl", f'cat "{self.d}/launchctl.txt"\n')

    def footprint(self, size):
        self.fake(
            "footprint",
            f'if [ -e "{self.d}/footprint.fail" ]; then exit 66; fi\n'
            f'echo "    phys_footprint: {size} B"\n')

    def put_record(self, content):
        self.record_file.parent.mkdir(exist_ok=True)
        self.record_file.write_text(json.dumps(content))

    def trim(self, *extra):
        return self.run_module([
            "fseventsd", "--record", str(self.record_file), "--limit-gib", "4",
            "--launchctl", str(self.d / "launchctl"), "--footprint", str(self.d / "footprint"),
            "--kill", str(self.d / "kill"), "--now", NOW, *extra])

    def written(self):
        return json.loads(self.record_file.read_text())

    def test_fseventsd_over_the_limit_is_restarted(self):
        result = self.trim()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log_json("kill.log"), [["-TERM", "29194"]])
        saved = self.written()
        self.assertEqual((saved["pid"], saved["footprint_bytes"]), (29194, 5 * GIB))
        self.assertEqual((saved["restarts"], saved["last_restart_at"]), (1, "2026-11-24T12:00:00"))
        self.assertIs(saved["held"], False)
        self.assertEqual(stat.S_IMODE(self.record_file.stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(self.record_file.parent.stat().st_mode), 0o755)

    def test_fseventsd_under_the_limit_is_left_alone(self):
        self.footprint(3 * GIB)
        self.assertEqual(self.trim().returncode, 0)
        self.assertFalse((self.d / "kill.log").exists())
        saved = self.written()
        self.assertEqual((saved["restarts"], saved["footprint_bytes"]), (0, 3 * GIB))
        self.assertIs(saved["held"], False)

    def test_fseventsd_at_the_limit_is_left_alone(self):
        self.footprint(4 * GIB)
        self.assertEqual(self.trim().returncode, 0)
        self.assertFalse((self.d / "kill.log").exists())

    def test_a_second_growth_within_the_hour_is_held(self):
        self.put_record(record(restarts=1, last_restart_at="2026-11-24T11:30:00"))
        self.assertEqual(self.trim().returncode, 0)
        self.assertFalse((self.d / "kill.log").exists())
        saved = self.written()
        self.assertIs(saved["held"], True)
        self.assertEqual((saved["restarts"], saved["last_restart_at"]), (1, "2026-11-24T11:30:00"))

    def test_a_growth_after_the_hour_is_restarted(self):
        self.put_record(record(restarts=1, last_restart_at="2026-11-24T10:59:00"))
        self.assertEqual(self.trim().returncode, 0)
        self.assertEqual(self.log_json("kill.log"), [["-TERM", "29194"]])
        self.assertEqual(self.written()["restarts"], 2)

    def test_an_unread_footprint_restarts_nothing(self):
        (self.d / "footprint.fail").write_text("")
        self.assertEqual(self.trim().returncode, 0)
        self.assertFalse((self.d / "kill.log").exists())
        saved = self.written()
        self.assertIsNone(saved["footprint_bytes"])
        self.assertEqual(saved["restarts"], 0)

    def test_a_failed_kill_is_reported(self):
        (self.d / "kill.fail").write_text("")
        result = self.trim()
        self.assertEqual(result.returncode, 1)
        self.assertIn("kill", result.stderr)
        saved = self.written()
        self.assertEqual((saved["restarts"], saved["last_restart_at"]), (0, None))
        self.assertIs(saved["restart_failed"], True)

    def test_a_service_with_no_pid_writes_no_record(self):
        self.launchctl(LAUNCHCTL_RUNS_ONLY)
        result = self.trim()
        self.assertEqual(result.returncode, 1)
        self.assertIn("pid", result.stderr)
        self.assertFalse(self.record_file.exists())
        self.assertFalse((self.d / "kill.log").exists())

    def test_the_interval_is_an_option(self):
        self.put_record(record(restarts=1, last_restart_at="2026-11-24T11:30:00"))
        self.assertEqual(self.trim("--min-restart-minutes", "30").returncode, 0)
        self.assertEqual(self.log_json("kill.log"), [["-TERM", "29194"]])


class SampleTest(FakeHost):
    def setUp(self):
        super().setUp()
        self.bot = Bot()
        self.addCleanup(self.bot.close)
        self.fake("vm_stat", f'cat "{self.d}/vm_stat.txt"\n')
        (self.d / "vm_stat.txt").write_text(VM_STAT)
        self.fake("sysctl", f"echo {TOTAL}\n")
        (self.d / "launchctl.txt").write_text("system/org.nixos.omlx = {\n\truns = 7\n\tpid = 73552\n}\n")
        self.fake("launchctl", f'cat "{self.d}/launchctl.txt"\n')
        self.fake("ps", "echo 1 /sbin/launchd\n")
        (self.d / "hdiutil.plist").write_text(plistlib.dumps({"images": []}).decode())
        self.fake("hdiutil", f'cat "{self.d}/hdiutil.plist"\n')
        self.fake("footprint", "exit 66\n")
        self.state_dir = self.d / "state"
        self.state_file = self.state_dir / "memory-watch.json"
        self.peaks_file = self.state_dir / "memory-peaks.jsonl"
        self.settings = self.d / "telegram.json"
        self.settings.write_text(json.dumps(SETTINGS))
        self.settings.chmod(0o600)

    def put_record(self, content):
        self.record_file.parent.mkdir(exist_ok=True)
        self.record_file.write_text(json.dumps(content))

    def put_state(self, content):
        self.state_dir.mkdir(mode=0o700, exist_ok=True)
        self.state_file.write_text(json.dumps(content))

    def sample(self, now=NOW):
        return self.run_module([
            "sample", "--state-dir", str(self.state_dir), "--floor-gib", "16", "--others-budget-gib", "46", "--unowned-alert-gib", "5",
            "--verify-alert-gib", "2.5", "--omlx-jetsam-priority", "100", "--host", "eleven-m5",
            "--vm-stat", str(self.d / "vm_stat"), "--sysctl", str(self.d / "sysctl"),
            "--launchctl", str(self.d / "launchctl"), "--ps", str(self.d / "ps"),
            "--footprint", str(self.d / "footprint"),
            "--health-url", (self.d / "health.json").as_uri(),
            "--alert-settings", str(self.settings), "--alert-log", str(self.d / "alerts.log"),
            "--telegram-api", self.bot.api, "--fseventsd-record", str(self.record_file),
            "--census-record", str(self.d / "census.json"), "--floor-record", str(self.d / "floor.json"),
            "--hdiutil", str(self.d / "hdiutil"), "--slot-history", str(self.d / "history.jsonl"),
            "--colima-pid-file", str(self.d / "vz.pid"),
            "--now", now])

    def read_state(self):
        return json.loads(self.state_file.read_text())

    def texts(self):
        return [request["body"]["text"] for request in self.bot.requests]

    def test_each_sample_records_the_fseventsd_size(self):
        self.put_state(state())
        self.put_record(record(footprint_bytes=2 * GIB))
        self.assertEqual(self.sample().returncode, 0)
        saved = self.read_state()
        self.assertEqual((saved["fseventsd_bytes"], saved["peak_fseventsd_bytes"]), (2 * GIB, 2 * GIB))
        self.put_record(record(footprint_bytes=GIB))
        self.assertEqual(self.sample().returncode, 0)
        saved = self.read_state()
        self.assertEqual((saved["fseventsd_bytes"], saved["peak_fseventsd_bytes"]), (GIB, 2 * GIB))
        self.assertEqual(self.sample(now="2026-11-25T00:01:00").returncode, 0)
        line = json.loads(self.peaks_file.read_text().splitlines()[0])
        self.assertEqual((line["peak_fseventsd_gib"], line["fseventsd_restarts"]), (2.0, 0))

    def test_the_day_line_counts_the_days_restarts(self):
        self.put_state(state(day="2026-11-23", fseventsd_restarts_today=2, fseventsd_restarts_seen=2))
        self.put_record(record(restarts=2))
        self.assertEqual(self.sample().returncode, 0)
        line = json.loads(self.peaks_file.read_text().splitlines()[0])
        self.assertEqual(line["fseventsd_restarts"], 2)
        self.assertEqual(self.read_state()["fseventsd_restarts_today"], 0)

    def test_a_restart_sends_one_alert(self):
        self.put_state(state(fseventsd_restarts_seen=0))
        self.put_record(record(restarts=1, footprint_bytes=10485760))
        self.assertEqual(self.sample().returncode, 0)
        self.assertEqual(self.sample().returncode, 0)
        self.assertEqual(len(self.bot.requests), 1)
        self.assertEqual(
            self.texts()[0],
            "eleven-m5: fseventsd was restarted at 0.0 GiB (limit 4 GiB). "
            "See hosts/darwin/eleven-m5/README.md, Memory budget.")
        saved = self.read_state()
        self.assertEqual((saved["fseventsd_restarts_today"], saved["fseventsd_restarts_seen"]), (1, 1))

    def test_the_first_sample_only_records_the_restart_count(self):
        self.put_record(record(restarts=3))
        self.assertEqual(self.sample().returncode, 0)
        self.assertEqual(self.bot.requests, [])
        saved = self.read_state()
        self.assertEqual((saved["fseventsd_restarts_seen"], saved["fseventsd_restarts_today"]), (3, 0))

    def test_a_held_growth_alerts_once_per_episode(self):
        self.put_state(state())
        self.put_record(record(held=True, at=NOW, footprint_bytes=5 * GIB, last_restart_at="2026-11-24T11:30:00"))
        self.assertEqual(self.sample().returncode, 0)
        self.assertEqual(self.sample().returncode, 0)
        self.assertEqual(len(self.bot.requests), 1)
        self.assertIn("was not restarted", self.texts()[0])
        self.assertIn("fseventsd is at 5.0 GiB, over 4 GiB within 30 minutes of its last restart", self.texts()[0])
        self.put_record(record(held=False))
        self.sample()
        self.put_record(record(held=True, at=NOW, footprint_bytes=5 * GIB, last_restart_at="2026-11-24T11:30:00"))
        self.sample()
        self.assertEqual(len(self.bot.requests), 2)

    def test_a_restart_that_keeps_failing_alerts_once_per_episode(self):
        self.put_state(state())
        failed = record(restart_failed=True, at=NOW, footprint_bytes=6 * GIB)
        self.put_record(failed)
        self.assertEqual(self.sample().returncode, 0)
        self.assertEqual(self.sample().returncode, 0)
        self.assertEqual(len(self.bot.requests), 1)
        self.assertIn("fseventsd is at 6.0 GiB, over 4 GiB, and its restart failed", self.texts()[0])
        self.put_record(record())
        self.sample()
        self.put_record(failed)
        self.sample()
        self.assertEqual(len(self.bot.requests), 2)

    def test_a_missing_record_is_not_a_failed_reading(self):
        self.assertEqual(self.sample().returncode, 0)
        saved = self.read_state()
        self.assertIsNone(saved["fseventsd_bytes"])
        self.assertEqual(saved["samples"], 1)
        self.assertEqual(self.bot.requests, [])

    def test_a_record_that_is_not_json_is_not_a_failed_reading(self):
        self.record_file.parent.mkdir()
        self.record_file.write_text("{")
        self.assertEqual(self.sample().returncode, 0)
        saved = self.read_state()
        self.assertIsNone(saved["fseventsd_bytes"])
        self.assertEqual(saved["samples"], 1)


if __name__ == "__main__":
    unittest.main()
