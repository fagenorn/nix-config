"""The eleven-m5 memory watcher's `sample` command, against fake host tools and a stand-in bot API.

Runs `agent_tools.hosts.omlx_memory_watch` as a child with fake `vm_stat`, `sysctl`, `launchctl`,
`ps` and `footprint` scripts, a health file and a loopback server that records each alert: what
a sample records, when it queues an alert, what delivery keeps and that the token never leaks.
Run: just agent-workflow-tests
"""

import http.server
import json
import os
import socketserver
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from agent_tools.hosts import omlx_memory_watch
from agent_tools.hosts.omlx_memory_watch import kill_line
from tests.test_host_alerts import PROXY_VARIABLES, SETTINGS, Bot

TIER = "fast"

ROOT = Path(__file__).resolve().parent.parent
GIB = 1024**3
TOTAL = 274877906944

VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               3181988.
Pages active:                             6541412.
Pages inactive:                           6595687.
Pages speculative:                          16413.
Pages wired down:                          302081.
Pages purgeable:                             4054.
Anonymous pages:                         12906856.
Pages occupied by compressor:              105539.
"""
VM_STAT_LOW = VM_STAT.replace("12906856.", "15400000.")
HEALTH_LOADED = {"status": "healthy", "engine_pool": {"loaded_count": 1, "current_model_memory": 195219083423}}
PS_IDLE = "/sbin/launchd\n(Runner.Listener)\n(bash)\n"
PS_BUSY = PS_IDLE + "(Runner.Worker)\n/Users/runner/actions-runner/bin/Runner.Worker\n"
FOOTPRINT = """======================================================================
Python [73552]: 64-bit    Footprint: 187360249992 B (16384 bytes per page)
======================================================================

Auxiliary data:
    phys_footprint: 187360249992 B
    phys_footprint_peak: 190905486696 B
"""


def launchctl(runs, reason):
    return (
        "system/org.nixos.omlx = {\n"
        "\tstate = running\n"
        f"\truns = {runs}\n"
        "\tpid = 73552\n"
        f"\tlast exit reason = {reason}\n"
        "\tjetsam priority = 40\n"
        "\tproperties = {\n\t\truns = 99\n\t}\n"
        "}\n"
    )


def state(**kw):
    base = {
        "since": "2026-11-24", "day": "2026-11-24", "peak_used_bytes": 0, "peak_others_bytes": None,
        "peak_omlx_bytes": None, "min_available_bytes": TOTAL, "samples": 0, "loaded_samples": 0,
        "min_loaded_available_bytes": None, "peak_ci_jobs": 0, "jetsam_exits": 0, "omlx_runs": 7,
        "omlx_jetsam_priority": None, "low_memory_open": False, "pending": [],
    }
    base.update(kw)
    return base


QUEUED = state(pending=[{"kind": "jetsam", "text": "eleven-m5: queued.", "logged": False}])
OLD_DAY = dict(
    since="2026-11-22", day="2026-11-23", peak_used_bytes=230 * GIB, peak_others_bytes=50 * GIB,
    peak_omlx_bytes=180 * GIB, min_available_bytes=26 * GIB, min_loaded_available_bytes=28 * GIB,
    samples=1440, loaded_samples=1400, jetsam_exits=1, peak_ci_jobs=2, omlx_jetsam_priority=100)
DAY_LINE = {
    "day": "2026-11-23", "peak_used_gib": 230.0, "peak_others_gib": 50.0, "peak_omlx_gib": 180.0,
    "min_available_gib": 26.0, "others_budget_gib": 46, "over_budget": True, "jetsam_exits": 1,
    "peak_ci_jobs": 2, "samples": 1440, "loaded_samples": 1400, "min_loaded_available_gib": 28.0,
    "floor_gib": 16, "omlx_jetsam_priority": 100, "declared_jetsam_priority": 100,
    "peak_fseventsd_gib": None, "fseventsd_restarts": 0,
}


class WatchCase(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.d = Path(scratch.name)
        self.bot = Bot()
        self.addCleanup(self.bot.close)
        self.env = {k: v for k, v in os.environ.items() if k not in PROXY_VARIABLES}
        self.env["PYTHONPATH"] = str(ROOT / "python")
        self.vm_stat(VM_STAT)
        self.launchctl(launchctl(7, "(none)"))
        self.ps(PS_IDLE)
        self.fake("sysctl", f"echo {TOTAL}\n")
        self.footprint_text = self.d / "footprint.out"
        self.footprint_text.write_text(FOOTPRINT)
        self.fake("footprint", self.logging_script("footprint.log") +
                  f'if [ -e "{self.d}/footprint.fail" ]; then exit 66; fi\ncat "{self.footprint_text}"\n')
        self.state_dir = self.d / "state"
        self.state_file = self.state_dir / "memory-watch.json"
        self.peaks_file = self.state_dir / "memory-peaks.jsonl"
        self.alert_log = self.d / "alerts.log"
        self.settings = self.d / "telegram.json"

    def fake(self, name, body):
        path = self.d / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    def logging_script(self, log):
        return (
            'out="["; sep=""\nfor a in "$@"; do out="$out$sep\\"$a\\""; sep=", "; done\n'
            f'echo "$out]" >> "{self.d}/{log}"\n'
        )

    def vm_stat(self, text):
        (self.d / "vm_stat.txt").write_text(text)
        self.fake("vm_stat", f'cat "{self.d}/vm_stat.txt"\n')

    def launchctl(self, text):
        (self.d / "launchctl.txt").write_text(text)
        self.fake("launchctl", f'cat "{self.d}/launchctl.txt"\n')

    def ps(self, text):
        (self.d / "ps.out").write_text(text)
        self.fake("ps", self.logging_script("ps.log") + f'cat "{self.d}/ps.out"\n')

    def health(self, body=HEALTH_LOADED):
        (self.d / "health.json").write_text(json.dumps(body))

    def settings_on(self, content=SETTINGS):
        self.settings.write_text(json.dumps(content))
        self.settings.chmod(0o600)

    def put_state(self, content):
        self.state_dir.mkdir(mode=0o700, exist_ok=True)
        self.state_file.write_text(json.dumps(content))

    def sample(self, *extra, now="2026-11-24T12:00:00", env=None):
        argv = [
            sys.executable, "-m", "agent_tools.hosts.omlx_memory_watch", "sample",
            "--state-dir", str(self.state_dir), "--floor-gib", "16", "--others-budget-gib", "46",
            "--omlx-jetsam-priority", "100", "--host", "eleven-m5",
            "--vm-stat", str(self.d / "vm_stat"), "--sysctl", str(self.d / "sysctl"),
            "--launchctl", str(self.d / "launchctl"), "--ps", str(self.d / "ps"),
            "--footprint", str(self.d / "footprint"),
            "--health-url", (self.d / "health.json").as_uri(),
            "--alert-settings", str(self.settings), "--alert-log", str(self.alert_log),
            "--telegram-api", self.bot.api, "--floor-record", str(self.d / "floor.json"),
            "--now", now, *extra,
        ]
        return subprocess.run(argv, capture_output=True, text=True, env=env or self.env, timeout=60)

    def read_state(self):
        return json.loads(self.state_file.read_text())

    def log_json(self, name):
        return [json.loads(line) for line in (self.d / name).read_text().splitlines()]


SEE = "See hosts/darwin/eleven-m5/README.md, Memory budget."


def kill(seq, **kw):
    entry = {
        "seq": seq, "at": "2026-11-24T12:33:05+00:00", "reason": "floor", "owner": "anis",
        "root_pid": 300, "root_command": "node vitest run", "processes": 46, "tree_bytes": 146 * GIB,
        "available_before_bytes": int(0.2 * GIB), "available_after_bytes": int(140.3 * GIB),
        "signals": "term+kill",
    }
    entry.update(kw)
    return entry


class SampleTest(WatchCase):
    def test_a_jetsam_exit_sends_one_alert(self):
        self.put_state(state(omlx_runs=6))
        self.launchctl(launchctl(7, "OS_REASON_JETSAM"))
        self.health()
        self.settings_on()
        for _ in range(2):
            self.assertEqual(self.sample().returncode, 0)
        self.assertEqual(len(self.bot.requests), 1)
        text = self.bot.requests[0]["body"]["text"]
        self.assertTrue(text.startswith("eleven-m5: the memory killer ended oMLX (runs 7)."), text)
        self.assertIn("oMLX footprint 174.5 GiB", text)
        self.assertIn("Memory budget", text)
        saved = self.read_state()
        self.assertEqual((saved["pending"], saved["omlx_runs"], saved["jetsam_exits"]), ([], 7, 1))

    def test_the_first_sample_records_a_baseline_without_alerting(self):
        self.launchctl(launchctl(7, "OS_REASON_JETSAM"))
        self.assertEqual(self.sample().returncode, 0)
        saved = self.read_state()
        self.assertEqual(saved["pending"], [])
        self.assertEqual((saved["omlx_runs"], saved["since"], saved["jetsam_exits"]), (7, "2026-11-24", 0))

    def test_an_ordinary_restart_queues_nothing(self):
        self.put_state(state(omlx_runs=6))
        self.assertEqual(self.sample().returncode, 0)
        saved = self.read_state()
        self.assertEqual((saved["pending"], saved["omlx_runs"]), ([], 7))

    def test_low_memory_while_a_model_is_loaded_alerts_once_per_episode(self):
        self.put_state(state())
        self.vm_stat(VM_STAT_LOW)
        self.health()
        self.settings_on()
        for _ in range(3):
            self.sample()
        self.assertEqual(len(self.bot.requests), 1)
        text = self.bot.requests[0]["body"]["text"]
        self.assertTrue(
            text.startswith("eleven-m5: available memory fell under 16 GiB while a model was loaded."), text)
        self.vm_stat(VM_STAT)
        self.sample()
        self.vm_stat(VM_STAT_LOW)
        self.sample()
        self.assertEqual(len(self.bot.requests), 2)

    def test_low_memory_with_no_model_loaded_alerts_nothing(self):
        self.put_state(state())
        self.vm_stat(VM_STAT_LOW)
        self.assertEqual(self.sample().returncode, 0)
        saved = self.read_state()
        self.assertEqual(saved["pending"], [])
        self.assertIs(saved["low_memory_open"], False)
        self.assertEqual((saved["samples"], saved["loaded_samples"]), (1, 0))
        self.assertIsNone(saved["min_loaded_available_bytes"])

    def test_the_peak_of_others_excludes_the_measured_omlx_footprint(self):
        self.health()
        self.assertEqual(self.sample().returncode, 0)
        self.assertEqual(self.log_json("footprint.log"), [["-p", "73552", "-f", "bytes", "--noCategories"]])
        saved = self.read_state()
        self.assertEqual(saved["peak_used_bytes"], 218077954048)
        self.assertEqual(saved["peak_omlx_bytes"], 187360249992)
        self.assertEqual(saved["peak_others_bytes"], 30717704056)
        self.assertEqual(saved["min_available_bytes"], 56799952896)
        self.assertEqual((saved["loaded_samples"], saved["min_loaded_available_bytes"]), (1, 56799952896))
        self.assertEqual(stat.S_IMODE(self.state_dir.stat().st_mode), 0o700)

    def test_the_day_rollover_appends_the_finished_day(self):
        self.put_state(state(**OLD_DAY))
        self.assertEqual(self.sample(now="2026-11-24T00:01:00").returncode, 0)
        self.assertEqual(self.log_json_at(self.peaks_file), [DAY_LINE])
        saved = self.read_state()
        self.assertEqual((saved["day"], saved["since"], saved["jetsam_exits"]), ("2026-11-24", "2026-11-22", 0))
        self.assertEqual((saved["samples"], saved["omlx_jetsam_priority"]), (1, 40))
        self.assertIsNone(saved["peak_others_bytes"])

    def log_json_at(self, path):
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_a_failed_reading_leaves_the_state_untouched(self):
        self.put_state(state())
        before = self.state_file.read_bytes()
        self.fake("vm_stat", "exit 1\n")
        result = self.sample()
        self.assertEqual(result.returncode, 1)
        self.assertIn("vm_stat", result.stderr)
        self.assertEqual(self.state_file.read_bytes(), before)
        self.assertFalse(self.peaks_file.exists())

    def test_the_day_keeps_the_most_ci_jobs_seen(self):
        self.assertEqual(omlx_memory_watch.count_ci_jobs(PS_BUSY), 2)
        self.assertEqual(omlx_memory_watch.count_ci_jobs(PS_IDLE), 0)
        self.ps(PS_BUSY)
        self.sample()
        self.ps(PS_IDLE)
        self.sample()
        self.assertEqual(self.read_state()["peak_ci_jobs"], 2)
        self.assertEqual(self.log_json("ps.log"), [["-axo", "comm="], ["-axo", "comm="]])

    def test_the_health_read_ignores_proxy_variables(self):
        body = json.dumps(HEALTH_LOADED).encode()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        env = {k: v for k, v in self.env.items() if k not in ("no_proxy", "NO_PROXY")}
        env["http_proxy"] = env["HTTP_PROXY"] = "http://127.0.0.1:9"
        url = f"http://127.0.0.1:{server.server_address[1]}/health"
        self.assertEqual(self.sample("--health-url", url, env=env).returncode, 0)
        self.assertEqual(self.read_state()["loaded_samples"], 1)

    def serve_raw(self, reply):
        """A loopback server that answers every connection with `reply` bytes, then closes it."""
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.recv(4096)
                self.request.sendall(reply)

        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}/health"

    def test_a_health_answer_cut_short_counts_as_not_loaded(self):
        url = self.serve_raw(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n{")
        done = self.sample("--health-url", url)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.read_state()["loaded_samples"], 0)

    def test_a_garbled_health_status_line_counts_as_not_loaded(self):
        url = self.serve_raw(b"garbage\r\n\r\n")
        done = self.sample("--health-url", url)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.read_state()["loaded_samples"], 0)

    def stale_others_state(self):
        self.put_state(state(
            peak_used_bytes=100 * GIB, peak_others_bytes=21474836480, peak_omlx_bytes=170 * GIB,
            samples=10, loaded_samples=10))

    def test_a_sample_with_no_model_loaded_leaves_the_others_peak_unchanged(self):
        self.stale_others_state()
        self.assertEqual(self.sample().returncode, 0)
        saved = self.read_state()
        self.assertEqual((saved["peak_others_bytes"], saved["peak_omlx_bytes"]), (21474836480, 170 * GIB))
        self.assertEqual(saved["peak_used_bytes"], 218077954048)
        self.assertEqual((saved["samples"], saved["loaded_samples"]), (11, 10))

    def test_a_loaded_sample_without_an_omlx_footprint_leaves_the_others_peak_unchanged(self):
        self.stale_others_state()
        self.health()
        (self.d / "footprint.fail").write_text("")
        self.assertEqual(self.sample().returncode, 0)
        saved = self.read_state()
        self.assertEqual(saved["peak_others_bytes"], 21474836480)
        self.assertEqual(saved["loaded_samples"], 11)

    def test_a_day_with_no_counted_sample_is_not_over_budget(self):
        self.put_state(state(**{
            **OLD_DAY, "peak_others_bytes": None, "peak_omlx_bytes": None,
            "min_loaded_available_bytes": None, "loaded_samples": 0}))
        self.assertEqual(self.sample(now="2026-11-24T00:01:00").returncode, 0)
        line = self.log_json_at(self.peaks_file)[0]
        self.assertIsNone(line["peak_others_gib"])
        self.assertIsNone(line["peak_omlx_gib"])
        self.assertIsNone(line["min_loaded_available_gib"])
        self.assertIs(line["over_budget"], False)


class ParseTest(unittest.TestCase):
    def test_used_counts_app_wired_and_compressed_memory(self):
        self.assertEqual(omlx_memory_watch.used_bytes(omlx_memory_watch.parse_vm_stat(VM_STAT)), 218077954048)

    def test_launchctl_reads_only_top_level_fields(self):
        self.assertEqual(
            omlx_memory_watch.parse_launchctl(launchctl(7, "OS_REASON_JETSAM")),
            {"runs": 7, "pid": 73552, "jetsam_priority": 40, "last_exit_reason": "OS_REASON_JETSAM"})


class AlertTest(WatchCase):
    def test_unusable_settings_keep_the_alert_log_it_once_and_exit_3(self):
        self.put_state(QUEUED)
        for _ in range(2):
            result = self.sample()
            self.assertEqual(result.returncode, 3)
            self.assertIn("host alert not sent: settings file", result.stderr)
            self.assertIn("is missing", result.stderr)
        lines = self.alert_log.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("jetsam not sent", lines[0])
        self.assertIn("eleven-m5: queued.", lines[0])
        entry = self.read_state()["pending"][0]
        self.assertIs(entry["logged"], True)
        self.assertEqual(self.bot.requests, [])

    def test_a_kept_alert_is_sent_once_the_settings_work(self):
        self.put_state(QUEUED)
        self.sample()
        self.sample()
        self.settings_on()
        self.assertEqual(self.sample().returncode, 0)
        self.assertEqual([r["body"]["text"] for r in self.bot.requests], ["eleven-m5: queued."])
        self.assertEqual(self.read_state()["pending"], [])
        self.assertEqual(len(self.alert_log.read_text().splitlines()), 1)

    def test_disabled_alerts_are_logged_and_dropped(self):
        self.put_state(QUEUED)
        self.settings_on({"enabled": False})
        self.assertEqual(self.sample().returncode, 0)
        self.assertEqual(self.bot.requests, [])
        lines = self.alert_log.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("recorded only", lines[0])
        self.assertEqual(self.read_state()["pending"], [])

    def test_the_token_never_reaches_output_state_or_logs(self):
        self.put_state(QUEUED)
        self.settings_on()
        self.bot.status = 401
        result = self.sample()
        self.assertEqual(result.returncode, 3)
        self.assertNotIn("SECRET-TOKEN", result.stdout)
        self.assertNotIn("SECRET-TOKEN", result.stderr)
        self.assertNotIn(b"SECRET-TOKEN", self.state_file.read_bytes())
        self.assertNotIn(b"SECRET-TOKEN", self.alert_log.read_bytes())
        if self.peaks_file.exists():
            self.assertNotIn(b"SECRET-TOKEN", self.peaks_file.read_bytes())


class FloorRecordTest(WatchCase):
    def floor(self, **kw):
        record = {
            "kills": 0, "recent": [], "floor_bytes": 16 * GIB, "run_bound_bytes": 24 * GIB,
            "omlx_pid": 73552, "omlx_kernel_priority": 100, "omlx_priority_resets": 0,
            "declared_priority": 100, "omlx_priority_error": None,
        }
        record.update(kw)
        (self.d / "floor.json").write_text(json.dumps(record))

    def texts(self):
        return [request["body"]["text"] for request in self.bot.requests]

    def test_each_new_kill_in_the_floor_record_sends_one_alert(self):
        self.put_state(state(floor_kills_seen=1))
        self.floor(kills=2, recent=[kill(1, root_pid=299), kill(2)])
        self.health()
        self.settings_on()
        first = self.sample()
        second = self.sample()
        self.assertEqual((first.returncode, second.returncode), (0, 0), first.stderr + second.stderr)
        self.assertEqual(self.texts(), [
            "eleven-m5: the memory floor ended anis's workload node vitest run (46 processes, 146.0 GiB, "
            "under the 16 GiB floor). Available 0.2 GiB before, 140.3 GiB after. " + SEE])
        self.assertEqual(first.stdout, (
            "2026-11-24T12:33:05+00:00 memory_kill reason=floor owner=anis root_pid=300"
            ' root="node vitest run" processes=46 tree_gib=146.0 available_before_gib=0.2'
            " available_after_gib=140.3 signals=term+kill\n"))
        self.assertEqual(first.stdout, kill_line(kill(2)))
        self.assertEqual(second.stdout, "")
        saved = self.read_state()
        self.assertEqual((saved["floor_kills_seen"], saved["floor_log"]), (2, []))

    def test_a_long_workload_command_is_cut_in_the_alert_as_in_the_log(self):
        self.put_state(state(floor_kills_seen=1))
        self.floor(kills=2, recent=[kill(2, root_command="x" * 5000)])
        self.health()
        self.settings_on()
        done = self.sample()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.texts()), 1)
        self.assertLess(len(self.texts()[0]), 4096)
        self.assertIn("workload " + "x" * 200 + " (46 processes", self.texts()[0])

    def test_the_first_sample_only_records_the_kill_count(self):
        self.floor(kills=5, recent=[kill(4, owner="jarbird"), kill(5, owner="jarbird")])
        self.health()
        self.settings_on()
        done = self.sample()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((self.bot.requests, done.stdout), ([], ""))
        self.assertEqual(self.read_state()["floor_kills_seen"], 5)

    def unmet(self, seq, available=13, largest=2):
        return {"seq": seq, "at": "2026-11-24T12:33:05+00:00", "available_bytes": available * GIB,
                "largest_bytes": largest * GIB}

    def unmet_text(self, available=13, largest=2):
        return ("eleven-m5: the memory floor has no workload it may end that would bring available memory over "
                f"the 16 GiB floor. Available {available:.1f} GiB, largest candidate {largest:.1f} GiB. " + SEE)

    def test_one_alert_per_floor_unmet_episode_in_the_floor_record(self):
        self.put_state(state(floor_unmet_seen=1))
        self.floor(floor_unmets=2, floor_unmet_recent=[self.unmet(1), self.unmet(2)])
        self.health()
        self.settings_on()
        first = self.sample()
        second = self.sample()
        self.assertEqual((first.returncode, second.returncode), (0, 0), first.stderr + second.stderr)
        self.assertEqual(self.texts(), [self.unmet_text()])
        self.assertEqual(self.read_state()["floor_unmet_seen"], 2)

    def test_every_episode_between_two_samples_alerts_in_order(self):
        self.put_state(state(floor_unmet_seen=1))
        self.floor(floor_unmets=3, floor_unmet_recent=[self.unmet(3, largest=3), self.unmet(2, largest=1)])
        self.health()
        self.settings_on()
        done = self.sample()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.texts(), [self.unmet_text(largest=1), self.unmet_text(largest=3)])
        self.assertEqual(self.read_state()["floor_unmet_seen"], 3)

    def test_the_first_episode_after_a_healthy_sample_alerts(self):
        self.floor(floor_unmets=0, floor_unmet_recent=[])
        self.health()
        self.settings_on()
        healthy = self.sample()
        self.assertEqual((healthy.returncode, self.bot.requests, self.read_state()["floor_unmet_seen"]), (0, [], 0))
        self.floor(floor_unmets=1, floor_unmet_recent=[self.unmet(1)])
        breach = self.sample()
        self.assertEqual(breach.returncode, 0, breach.stderr)
        self.assertEqual(self.texts(), [self.unmet_text()])

    def test_a_record_without_the_episode_count_is_zero_episodes(self):
        self.floor()
        self.health()
        self.settings_on()
        self.sample()
        self.assertEqual(self.read_state()["floor_unmet_seen"], 0)

    def test_the_first_sample_only_records_the_floor_unmet_count(self):
        self.floor(floor_unmets=3, floor_unmet_recent=[self.unmet(3, largest=0)])
        self.health()
        self.settings_on()
        done = self.sample()
        self.assertEqual((done.returncode, self.bot.requests), (0, []), done.stderr)
        self.assertEqual(self.read_state()["floor_unmet_seen"], 3)

    def test_a_run_bound_kill_names_the_bound(self):
        self.put_state(state(floor_kills_seen=0))
        self.floor(kills=1, recent=[kill(1, reason="run_bound", owner="_github-runner", processes=9,
                                          tree_bytes=31 * GIB, root_command="cargo test")])
        self.settings_on()
        self.assertEqual(self.sample().returncode, 0)
        self.assertEqual(self.texts(), [
            "eleven-m5: the memory floor ended _github-runner's workload cargo test (9 processes, "
            "31.0 GiB, over the 24 GiB run bound). Available 0.2 GiB before, 140.3 GiB after. " + SEE])

    def test_the_kernel_priority_replaces_launchctls_only_for_the_same_pid_and_no_reset(self):
        self.settings_on()
        for pid, resets, expected in ((73552, 0, 100), (999, 0, 40), (73552, 3, 40)):
            with self.subTest(pid=pid, resets=resets):
                self.put_state(state(floor_kills_seen=0))
                self.floor(omlx_pid=pid, omlx_priority_resets=resets, omlx_kernel_priority=100)
                self.assertEqual(self.sample().returncode, 0)
                self.assertEqual(self.read_state()["omlx_jetsam_priority"], expected)

    def test_an_unset_priority_alerts_once_per_episode(self):
        self.settings_on()
        self.floor(omlx_priority_error="EPERM", omlx_kernel_priority=40)
        for _ in range(2):
            self.assertEqual(self.sample().returncode, 0)
        self.assertEqual(self.texts(), [
            "eleven-m5: oMLX's jetsam priority could not be set to 100 (EPERM); it is 40. " + SEE])
        self.floor()
        self.assertEqual(self.sample().returncode, 0)
        self.assertFalse(self.read_state()["priority_unset_open"])
        self.floor(omlx_priority_resets=2, omlx_kernel_priority=40)
        self.assertEqual(self.sample().returncode, 0)
        self.assertEqual(self.texts()[1:], [
            "eleven-m5: oMLX's jetsam priority could not be set to 100 (put back 2 times); it is 40. " + SEE])


class CommandTest(unittest.TestCase):
    def test_the_watcher_is_a_row_of_the_command_table(self):
        lines = (ROOT / "lib" / "agent-tools.nix").read_text().splitlines()
        self.assertEqual(lines.count('    "omlx-memory-watch" = "hosts.omlx_memory_watch";'), 1)
        verdicts = json.loads((ROOT / "python/agent_tools/delivery/command_verdicts.json").read_text())
        self.assertIsNone(verdicts["omlx-memory-watch"])
        env = {**os.environ, "PYTHONPATH": str(ROOT / "python")}
        result = subprocess.run(
            [sys.executable, "-m", "agent_tools.hosts.omlx_memory_watch", "--help"],
            capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(result.returncode, 0)
        self.assertIn("sample", result.stdout)


if __name__ == "__main__":
    unittest.main()
