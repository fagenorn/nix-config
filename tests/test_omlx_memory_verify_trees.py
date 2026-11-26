"""The eleven-m5 watcher's record of each verify run's tree peak and the day's highest.

Runs `agent_tools.hosts.omlx_memory_watch sample` as a child over a scratch verify-slot history whose lines
carry the tree peak `verify-slot run` measured: the `verify_run` event each line becomes, the day's highest
peak with its time, the run count, and the day a peak belongs to.
Run: just agent-workflow-tests
"""

import json
import unittest

from tests.test_omlx_memory_events import held_line
from tests.test_omlx_memory_records import RecordsCase
from tests.test_omlx_memory_watch import state

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
    def test_a_verify_run_carries_its_tree_peak_with_its_command_and_repository(self):
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

    def test_a_peak_before_midnight_read_after_it_stays_out_of_the_new_day(self):
        self.sample_with("2026-11-24T23:58:00")
        self.run_line("2026-11-24T23:50:00Z", 600.0, 3.0, "2026-11-24T23:59:00Z")
        self.sample_with("2026-11-25T00:01:00")
        [event] = self.sample_lines("2026-11-25")[-1]["events"]
        self.assertEqual(event["tree_peak_bytes"], 3 * GIB)
        [line] = self.day_lines()
        self.assertEqual(line["day"], "2026-11-24")
        self.assertIsNone(line["peak_verify_gib"])
        self.assertEqual(line["verify_runs"], 0)
        saved = self.read_state()
        self.assertEqual(saved["day"], "2026-11-25")
        self.assertEqual(saved["verify_runs"], 1)
        self.assertNotIn("verify", saved["census_peaks"])

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


if __name__ == "__main__":
    unittest.main()
