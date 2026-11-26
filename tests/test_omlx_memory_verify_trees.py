"""The eleven-m5 watcher's record of each verify run's tree peak and the day's highest.

Runs `agent_tools.hosts.omlx_memory_watch sample` as a child over a scratch verify-slot history whose lines
carry the tree peak `verify-slot run` measured: the `verify_run` event each line becomes, the day's highest
peak with its time, the run count, and the day a peak belongs to.
Run: just agent-workflow-tests
"""

import json
import subprocess
import sys
import unittest

from tests.test_omlx_memory_events import held_line
from tests.test_omlx_memory_records import RecordsCase
from tests.test_omlx_memory_watch import SEE, state

TIER = "fast"

GIB = 1024**3


class VerifyTreeCase(RecordsCase):
    def setUp(self):
        super().setUp()
        self.env["TZ"] = "UTC"
        self.history = self.d / "history.jsonl"
        self.history.write_text("")

    def run_line(self, started, held, peak_gib, peak_at, command="just test", repository="fagenorn/nix-config"):
        record = {
            "command": command, "exit": 0, "held_seconds": held, "lane": "long", "owner": None, "place": 1,
            "repository": repository, "started": started, "tree_peak_at": peak_at,
            "tree_peak_bytes": None if peak_gib is None else int(peak_gib * GIB), "waited_seconds": 0.0,
        }
        self.append(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")

    def append(self, text):
        with self.history.open("a") as handle:
            handle.write(text)

    def day_lines(self):
        return [json.loads(text) for text in self.peaks_file.read_text().splitlines()]


class VerifyTreeRecordTest(VerifyTreeCase):
    def test_a_verify_run_records_its_tree_peak_with_its_command_and_repository(self):
        self.sample_with("2026-11-24T12:00:00")
        self.run_line("2026-11-24T12:00:10Z", 30.0, 3.0, "2026-11-24T12:00:20Z")
        self.sample_with("2026-11-24T12:01:00")
        self.assertEqual(self.sample_lines()[-1]["events"], [{
            "kind": "verify_run", "repository": "fagenorn/nix-config", "command": "just test", "exit": 0,
            "held_from": "2026-11-24T12:00:10+00:00", "held_until": "2026-11-24T12:00:40+00:00",
            "tree_peak_bytes": 3 * GIB, "tree_peak_at": "2026-11-24T12:00:20+00:00",
        }])

    def test_the_day_line_keeps_the_highest_verify_peak_with_its_time(self):
        self.sample_with("2026-11-24T10:00:00")
        self.run_line("2026-11-24T10:20:00Z", 600.0, 2.0, "2026-11-24T10:25:00Z")
        self.sample_with("2026-11-24T11:00:00")
        self.run_line("2026-11-24T11:20:00Z", 600.0, 3.2, "2026-11-24T11:30:00Z")
        self.run_line("2026-11-24T11:35:00Z", 600.0, 3.2, "2026-11-24T11:40:00Z")
        self.sample_with("2026-11-24T12:00:00")
        self.sample_with("2026-11-25T00:01:00")
        [line] = self.day_lines()
        self.assertEqual(line["peak_verify_gib"], 3.2)
        self.assertEqual(line["peak_verify_at"], "2026-11-24T11:30:00+00:00")
        self.assertEqual(line["verify_runs"], 3)
        saved = self.read_state()
        self.assertNotIn("verify", saved["census_peaks"])
        self.assertEqual(saved["verify_runs"], 0)

    def test_a_run_without_a_tree_reading_counts_but_leaves_the_peak_null(self):
        self.sample_with("2026-11-24T12:00:00")
        self.append(held_line("2026-11-24T12:00:05Z", 0.0, 30.0))
        self.run_line("2026-11-24T12:00:10Z", 30.0, None, None)
        self.sample_with("2026-11-24T12:01:00")
        self.sample_with("2026-11-25T00:01:00")
        events = self.sample_lines()[-1]["events"]
        self.assertEqual([event["kind"] for event in events], ["verify_run", "verify_run"])
        for event in events:
            self.assertIsNone(event["tree_peak_bytes"])
            self.assertIsNone(event["tree_peak_at"])
        [line] = self.day_lines()
        self.assertIsNone(line["peak_verify_gib"])
        self.assertIsNone(line["peak_verify_at"])
        self.assertEqual(line["verify_runs"], 2)

    def test_a_run_without_a_peak_counts_in_the_day_that_reads_it(self):
        self.sample_with("2026-11-24T23:58:00")
        self.run_line("2026-11-24T23:50:00Z", 600.0, None, None)
        self.sample_with("2026-11-25T00:00:10")
        [line] = self.day_lines()
        self.assertEqual((line["day"], line["verify_runs"], line["peak_verify_gib"]), ("2026-11-24", 0, None))
        self.assertEqual(self.read_state()["verify_runs"], 1)
        self.run_line("2026-11-25T00:01:00Z", 60.0, None, None)
        self.sample_with("2026-11-25T00:04:00")
        self.assertEqual(self.read_state()["verify_runs"], 2)

    def test_a_peak_before_midnight_read_after_it_lands_in_the_finished_day_not_the_new_one(self):
        self.sample_with("2026-11-24T23:58:00")
        self.run_line("2026-11-24T23:50:00Z", 600.0, 4.0, "2026-11-24T23:59:50Z")
        self.sample_with("2026-11-25T00:00:10")
        [event] = self.sample_lines("2026-11-25")[-1]["events"]
        self.assertEqual(event["tree_peak_bytes"], 4 * GIB)
        [line] = self.day_lines()
        self.assertEqual(line["day"], "2026-11-24")
        self.assertEqual(line["peak_verify_gib"], 4.0)
        self.assertEqual(line["peak_verify_at"], "2026-11-24T23:59:50+00:00")
        self.assertEqual(line["verify_runs"], 1)
        saved = self.read_state()
        self.assertEqual(saved["day"], "2026-11-25")
        self.assertEqual(saved["verify_runs"], 0)
        self.assertNotIn("verify", saved["census_peaks"])

    def test_a_lower_peak_read_after_midnight_does_not_replace_the_finished_days_highest(self):
        self.sample_with("2026-11-24T23:58:00")
        self.run_line("2026-11-24T23:50:00Z", 100.0, 4.0, "2026-11-24T23:51:00Z")
        self.sample_with("2026-11-24T23:59:00")
        self.run_line("2026-11-24T23:55:00Z", 300.0, 3.0, "2026-11-24T23:59:30Z")
        self.sample_with("2026-11-25T00:00:10")
        [line] = self.day_lines()
        self.assertEqual((line["peak_verify_gib"], line["peak_verify_at"]), (4.0, "2026-11-24T23:51:00+00:00"))
        self.assertEqual(line["verify_runs"], 2)

    def test_a_run_peaking_before_midnight_read_after_the_first_new_day_sample_is_not_counted_in_the_new_day(self):
        self.sample_with("2026-11-24T23:58:00")
        self.sample_with("2026-11-25T00:00:10")
        self.run_line("2026-11-24T23:50:00Z", 800.0, 4.0, "2026-11-24T23:58:30Z")
        self.sample_with("2026-11-25T00:04:00")
        [event] = self.sample_lines("2026-11-25")[-1]["events"]
        self.assertEqual(event["tree_peak_bytes"], 4 * GIB)
        saved = self.read_state()
        self.assertEqual(saved["verify_runs"], 0)
        self.assertNotIn("verify", saved["census_peaks"])
        self.sample_with("2026-11-26T00:01:00")
        self.assertEqual([(line["day"], line["verify_runs"], line["peak_verify_gib"]) for line in self.day_lines()],
                         [("2026-11-24", 0, None), ("2026-11-25", 0, None)])

    def test_the_day_of_a_peak_follows_the_hosts_clock_across_a_fall_back_change(self):
        self.env["TZ"] = "America/Los_Angeles"
        self.sample_with("2026-11-01T00:10:00")
        self.run_line("2026-11-01T07:20:00Z", 600.0, 3.0, "2026-11-01T07:30:00Z")
        self.sample_with("2026-11-01T02:10:00")
        self.sample_with("2026-11-02T00:01:00")
        [line] = self.day_lines()
        self.assertEqual(line["day"], "2026-11-01")
        self.assertEqual((line["peak_verify_gib"], line["peak_verify_at"]), (3.0, "2026-11-01T07:30:00+00:00"))
        self.assertEqual(line["verify_runs"], 1)

    def test_a_tree_peak_too_large_to_be_a_byte_count_is_skipped_and_the_next_sample_goes_on(self):
        self.sample_with("2026-11-24T12:00:00")
        self.append(json.dumps({
            "command": "just test", "exit": 0, "held_seconds": 30.0, "lane": "long", "owner": None, "place": 1,
            "repository": "o/r", "started": "2026-11-24T12:00:10Z", "tree_peak_at": "2026-11-24T12:00:20Z",
            "tree_peak_bytes": 10**400, "waited_seconds": 0.0}) + "\n")
        self.run_line("2026-11-24T12:00:30Z", 30.0, 3.0, "2026-11-24T12:00:40Z")
        self.sample_with("2026-11-24T12:01:00")
        [event] = self.sample_lines()[-1]["events"]
        self.assertEqual(event["tree_peak_bytes"], 3 * GIB)

    def test_an_upgrade_over_an_older_saved_day_dates_the_verify_records_from_the_new_day(self):
        self.put_state(state(day="2026-11-24"))
        self.sample_with("2026-11-25T12:00:00")
        self.assertEqual(self.read_state()["verify_records_since"], "2026-11-25")
        self.sample_with("2026-11-26T00:01:00")
        line = self.day_lines()[0]
        self.assertEqual(line["day"], "2026-11-24")
        self.assertIsNone(line["peak_verify_gib"])
        self.assertEqual(line["verify_runs"], 0)
        self.assertEqual(self.read_state()["verify_records_since"], "2026-11-25")


class VerifyTreeAlertTest(VerifyTreeCase):
    def setUp(self):
        super().setUp()
        self.sample_with("2026-11-24T12:00:00")

    def sample_ok(self, now, *extra):
        result = self.sample(*extra, now=now)
        self.assertEqual(result.returncode, 0, result.stderr)

    def texts(self):
        return [request["body"]["text"] for request in self.bot.requests]

    def test_a_verify_tree_over_the_alert_line_sends_exactly_one_alert_naming_it(self):
        self.settings_on()
        self.run_line("2026-11-24T12:00:10Z", 30.0, 3.0, "2026-11-24T12:00:20Z")
        self.sample_with("2026-11-24T12:01:00")
        self.sample_with("2026-11-24T12:02:00")
        self.assertEqual(self.texts(), [
            "eleven-m5: a verify run's process tree reached 3.0 GiB, over the 2.5 GiB alert line: just test in "
            "fagenorn/nix-config. " + SEE])
        self.assertEqual(self.read_state()["pending"], [])

    def test_a_stub_verify_run_whose_tree_reaches_3_gib_is_recorded_and_alerted_once(self):
        self.settings_on()
        report = self.d / "tree-report.json"
        report.write_text(json.dumps({
            "unit": "byte", "bytes per unit": 1, "errors": [], "total footprint": 3 * GIB,
            "processes": [{"pid": 1, "name": "python3", "footprint": GIB},
                          {"pid": 2, "name": "node", "footprint": 5 * GIB // 2}],
        }))
        fake = self.d / "tree-footprint"
        fake.write_text(
            '#!/bin/sh\nwhile [ $# -gt 0 ]; do if [ "$1" = "-j" ]; then dest="$2"; fi; shift; done\n'
            f'cp "{report}" "$dest"\n')
        fake.chmod(0o755)
        history = self.d / "slots" / "history.jsonl"
        (self.d / "work").mkdir()
        (self.d / "home").mkdir()
        self.sample_ok("2026-11-24T12:00:30", "--slot-history", str(history))
        run = subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.verify_slot", "run", "--", sys.executable, "-c",
             "import time; time.sleep(0.5)"],
            cwd=self.d / "work", capture_output=True, text=True, timeout=60,
            env={**self.env, "HOME": str(self.d / "home"), "VERIFY_SLOT_DIR": str(self.d / "slots"),
                 "VERIFY_SLOT_FOOTPRINT": str(fake)})
        self.assertEqual(run.returncode, 0, run.stderr)
        self.sample_ok("2026-11-24T12:01:00", "--slot-history", str(history))
        self.sample_ok("2026-11-24T12:02:00", "--slot-history", str(history))
        [event] = self.sample_lines()[-2]["events"]
        self.assertEqual((event["kind"], event["tree_peak_bytes"], event["repository"]), ("verify_run", 3 * GIB, None))
        [text] = self.texts()
        self.assertIn("reached 3.0 GiB, over the 2.5 GiB alert line", text)
        self.assertIn("in (no repository).", text)

    def test_the_queued_alert_reaches_host_alerts_as_verify_tree(self):
        self.run_line("2026-11-24T12:00:10Z", 30.0, 3.0, "2026-11-24T12:00:20Z")
        self.sample_with("2026-11-24T12:01:00")
        [line] = self.alert_log.read_text().splitlines()
        self.assertIn(
            " verify_tree recorded only, alerts disabled: eleven-m5: a verify run's process tree reached 3.0 GiB",
            line)

    def test_the_alert_line_comes_from_the_flag(self):
        self.settings_on()
        self.run_line("2026-11-24T12:00:10Z", 30.0, 3.0, "2026-11-24T12:00:20Z")
        self.sample_ok("2026-11-24T12:01:00", "--verify-alert-gib", "3.5")
        self.run_line("2026-11-24T12:01:10Z", 30.0, 3.6, "2026-11-24T12:01:20Z")
        self.sample_ok("2026-11-24T12:02:00", "--verify-alert-gib", "3.5")
        [text] = self.texts()
        self.assertIn("reached 3.6 GiB, over the 3.5 GiB alert line", text)

    def test_a_tree_at_the_line_or_unmeasured_sends_nothing(self):
        self.settings_on()
        self.run_line("2026-11-24T12:00:10Z", 30.0, 2.5, "2026-11-24T12:00:20Z")
        self.run_line("2026-11-24T12:00:30Z", 30.0, None, None)
        self.sample_with("2026-11-24T12:01:00")
        self.assertEqual(self.texts(), [])
        events = self.sample_lines()[-1]["events"]
        self.assertEqual([event["kind"] for event in events], ["verify_run", "verify_run"])
        self.assertEqual(events[0]["tree_peak_bytes"], int(2.5 * GIB))

    def test_the_alert_redacts_assignments_and_bounds_what_it_names(self):
        self.settings_on()
        self.run_line("2026-11-24T12:00:10Z", 30.0, 2.6, "2026-11-24T12:00:20Z",
                      command="env API_TOKEN=example just", repository=None)
        self.run_line("2026-11-24T12:00:30Z", 30.0, 2.7, "2026-11-24T12:00:40Z", command="x" * 5000)
        self.run_line("2026-11-24T12:00:50Z", 30.0, 2.8, "2026-11-24T12:01:00Z", repository="r" * 150)
        self.sample_with("2026-11-24T12:01:30")
        redacted, long_word, long_repository = self.texts()
        self.assertIn(": env API_TOKEN=<redacted> just in (no repository).", redacted)
        self.assertNotIn("example", redacted)
        self.assertIn(": " + "x" * 60 + "… in fagenorn/nix-config.", long_word)
        self.assertLess(len(long_word), 4096)
        self.assertIn("just test in " + "r" * 100 + "….", long_repository)

    def test_a_non_positive_or_non_finite_alert_line_is_a_usage_error(self):
        for value in ("0", "-1", "nan"):
            with self.subTest(value=value):
                result = self.sample("--verify-alert-gib", value, now="2026-11-24T12:01:00")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("argument --verify-alert-gib:", result.stderr)

    def test_a_failed_send_is_retried_without_a_second_alert(self):
        self.settings.unlink()
        self.run_line("2026-11-24T12:00:10Z", 30.0, 3.0, "2026-11-24T12:00:20Z")
        failed = self.sample(now="2026-11-24T12:01:00")
        self.assertEqual(failed.returncode, 3, failed.stderr)
        [line] = self.alert_log.read_text().splitlines()
        self.assertIn(" verify_tree not sent (", line)
        self.settings_on()
        self.sample_with("2026-11-24T12:02:00")
        self.sample_with("2026-11-24T12:03:00")
        self.assertEqual(len(self.texts()), 1)
        self.assertEqual(self.read_state()["pending"], [])


if __name__ == "__main__":
    unittest.main()
