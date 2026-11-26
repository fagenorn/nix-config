"""The eleven-m5 watcher's per-sample records and the day line's timed peaks.

Runs `agent_tools.hosts.omlx_memory_watch sample` as a child with fake host tools and a scratch census
record: what each sample line holds, which census it trusts, and which peaks, owners and sample files
the day keeps.
Run: just agent-workflow-tests
"""

import json
import stat
import subprocess
import sys
import unittest
from datetime import datetime, timedelta

from tests.test_omlx_memory_census import FOOTPRINT_ALL, TOP_FIVE
from tests.test_omlx_memory_watch import VM_STAT, WatchCase, state

TIER = "fast"

GIB = 1024**3
PAGE = 16384
DAY = "2026-11-24"


def vm_stat_text(wired=302081, anonymous=12906856, compressions=11842405):
    text = VM_STAT.replace("302081.", f"{wired}.").replace("12906856.", f"{anonymous}.")
    return text + f"Compressions:                             {compressions}.\n"


VM_STAT_FULL = vm_stat_text()


def census(**kw):
    base = {
        "at": "2026-11-24T11:59:30", "seconds": 12.5, "footprint_exit": 0, "error": None, "warnings": 0,
        "sys_footprint_bytes": 214139715584, "process_footprint_bytes": 205000000000,
        "unowned_bytes": 9139715584, "processes": 6, "top_owners": TOP_FIVE,
    }
    base.update(kw)
    return base


def before(now, seconds=30):
    return (datetime.fromisoformat(now) - timedelta(seconds=seconds)).isoformat()


class RecordsCase(WatchCase):
    def setUp(self):
        super().setUp()
        self.settings_on({"enabled": False})

    def put_census(self, record):
        (self.d / "census.json").write_text(json.dumps(record))

    def sample_lines(self, day=DAY):
        return [json.loads(line) for line in (self.state_dir / "samples" / f"{day}.jsonl").read_text().splitlines()]

    def sample_with(self, now, record=None, vm=None):
        if record is not None:
            self.put_census(record)
        if vm is not None:
            self.vm_stat(vm)
        result = self.sample(now=now)
        self.assertEqual(result.returncode, 0, result.stderr)


class RecordsTest(RecordsCase):
    def test_a_census_of_stubbed_footprint_output_lands_in_the_next_sample(self):
        (self.d / "footprint-all.json").write_text(json.dumps(FOOTPRINT_ALL))
        self.fake(
            "footprint-all", 'while [ "$1" != "-j" ]; do shift; done\n' f'cp "{self.d}/footprint-all.json" "$2"\n')
        taken = subprocess.run(
            [sys.executable, "-m", "agent_tools.hosts.omlx_memory_watch", "census",
             "--record", str(self.d / "census.json"), "--footprint", str(self.d / "footprint-all"),
             "--now", "2026-11-24T11:59:30"],
            capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(taken.returncode, 0, taken.stderr)
        self.vm_stat(VM_STAT_FULL)
        result = self.sample()
        self.assertEqual(result.returncode, 0, result.stderr)
        [line] = self.sample_lines()
        self.assertEqual(line["at"], "2026-11-24T12:00:00")
        self.assertEqual(
            (line["sys_footprint_bytes"], line["process_footprint_bytes"], line["unowned_bytes"]),
            (214139715584, 205000000000, 9139715584))
        self.assertEqual(line["top_owners"], TOP_FIVE)
        self.assertEqual(
            (line["wired_bytes"], line["anonymous_bytes"], line["compressions_bytes"]),
            (4949295104, 211465928704, 194025963520))
        self.assertEqual(line["census_at"], "2026-11-24T11:59:30")
        self.assertIsInstance(line["census_seconds"], float)
        samples = self.state_dir / "samples"
        self.assertEqual(stat.S_IMODE((samples / f"{DAY}.jsonl").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(samples.stat().st_mode), 0o700)

    def test_the_day_line_keeps_each_peak_with_its_time(self):
        readings = (
            ("2026-11-24T10:00:00", 190, 3, 302081, 12906856, 11842405),
            ("2026-11-24T11:00:00", 200, 9, 400000, 13500000, 11900000),
            ("2026-11-24T12:00:00", 200, 6, 350000, 13500000, 12000000),
        )
        for now, process, unowned, wired, anonymous, compressions in readings:
            self.sample_with(
                now,
                census(at=before(now), process_footprint_bytes=process * GIB, unowned_bytes=unowned * GIB,
                       sys_footprint_bytes=(process + unowned) * GIB),
                vm_stat_text(wired=wired, anonymous=anonymous, compressions=compressions))
        self.sample_with("2026-11-25T00:01:00")
        [line] = [json.loads(text) for text in self.peaks_file.read_text().splitlines()]
        for name, gib, at in (
            ("unowned", 9.0, "11:00"), ("sys_footprint", 209.0, "11:00"), ("process_footprint", 200.0, "11:00"),
            ("wired", 6.1, "11:00"), ("anonymous", 206.0, "11:00"), ("compressions", 183.1, "12:00"),
        ):
            with self.subTest(figure=name):
                self.assertEqual(line[f"peak_{name}_gib"], gib)
                self.assertEqual(line[f"peak_{name}_at"], f"{DAY}T{at}:00")
        self.assertEqual(line["census_samples"], 3)
        first = f"{DAY}T10:00:00"
        self.assertEqual(line["peak_owners"], [
            {"name": "Python", "pid": 73552, "gib": 174.5, "at": first},
            {"name": "com.apple.Virtualization.VirtualMachine", "pid": 71884, "gib": 8.0, "at": first},
            {"name": "postgres", "pid": 25342, "gib": 4.0, "at": first},
            {"name": "dotnet", "pid": 5001, "gib": 3.0, "at": first},
            {"name": "node", "pid": 5002, "gib": 2.0, "at": first},
        ])
        saved = self.read_state()
        self.assertEqual(saved["census_samples"], 0)
        self.assertNotIn("unowned", saved["census_peaks"])

    def test_a_stale_census_leaves_the_figures_null(self):
        self.sample_with("2026-11-24T12:00:00", census(at="2026-11-24T11:55:00"), VM_STAT_FULL)
        [line] = self.sample_lines()
        for key in ("sys_footprint_bytes", "process_footprint_bytes", "unowned_bytes", "top_owners",
                    "census_at", "census_seconds"):
            with self.subTest(key=key):
                self.assertIsNone(line[key])
        self.assertEqual(line["wired_bytes"], 4949295104)
        self.assertEqual(self.read_state()["census_samples"], 0)

    def test_a_census_that_failed_leaves_the_figures_null(self):
        self.sample_with(
            "2026-11-24T12:00:00",
            census(error="footprint timed out after 50 s", sys_footprint_bytes=None,
                   process_footprint_bytes=None, unowned_bytes=None, top_owners=None),
            VM_STAT_FULL)
        [line] = self.sample_lines()
        self.assertIsNone(line["unowned_bytes"])
        self.assertIsNone(line["top_owners"])
        self.sample_with("2026-11-24T12:01:00", census(at="2026-11-24T12:00:40", error="footprint census incomplete"))
        self.assertIsNone(self.sample_lines()[-1]["unowned_bytes"])

    def test_an_owner_keeps_its_largest_footprint_once(self):
        for now, size in (("2026-11-24T10:00:00", 100), ("2026-11-24T11:00:00", 120)):
            self.sample_with(
                now, census(at=before(now), top_owners=[{"name": "dotnet", "pid": 5001, "bytes": size * GIB}]))
        saved = self.read_state()
        self.assertEqual(saved["census_samples"], 2)
        self.assertEqual(
            saved["peak_owners"], [{"name": "dotnet", "pid": 5001, "bytes": 120 * GIB, "at": "2026-11-24T11:00:00"}])

    def test_sample_files_older_than_fourteen_days_are_deleted_at_the_rollover(self):
        samples = self.state_dir / "samples"
        samples.mkdir(parents=True, mode=0o700)
        for day in ("2026-11-09", "2026-11-10"):
            (samples / f"{day}.jsonl").write_text("{}\n")
        self.put_state(state(day="2026-11-23"))
        self.sample_with("2026-11-24T00:01:00")
        self.assertFalse((samples / "2026-11-09.jsonl").exists())
        self.assertTrue((samples / "2026-11-10.jsonl").exists())
        self.assertTrue((samples / "2026-11-24.jsonl").exists())

    def test_a_legacy_rollover_starts_the_records_on_the_new_day(self):
        self.put_state(state(day="2026-11-23"))
        self.sample_with("2026-11-24T00:01:00")
        [line] = [json.loads(text) for text in self.peaks_file.read_text().splitlines()]
        self.assertEqual(line["day"], "2026-11-23")
        self.assertIsNone(line["records_since"])
        self.assertEqual(line["census_samples"], 0)
        self.assertEqual(self.read_state()["records_since"], "2026-11-24")

    def test_a_mid_day_upgrade_dates_the_records_from_that_day(self):
        self.put_state(state(day="2026-11-24"))
        self.sample_with("2026-11-24T12:00:00")
        self.sample_with("2026-11-25T00:01:00")
        [line] = [json.loads(text) for text in self.peaks_file.read_text().splitlines()]
        self.assertEqual(line["records_since"], "2026-11-24")
        self.assertEqual(self.read_state()["records_since"], "2026-11-24")


class UnownedAlertTest(RecordsCase):
    def samples_ok(self, *nows):
        for now in nows:
            result = self.sample(now=now)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_unowned_over_the_threshold_alerts_once_per_episode(self):
        self.settings_on()
        self.put_census(census())
        self.samples_ok("2026-11-24T12:00:00", "2026-11-24T12:00:00")
        self.assertEqual(
            [request["body"]["text"] for request in self.bot.requests],
            ["eleven-m5: 8.5 GiB of memory is in use but held by no process, over the 5 GiB alert line "
             "(system footprint 199.4 GiB, process footprints 190.9 GiB, wired 4.6 GiB, anonymous 196.9 GiB). "
             "See hosts/darwin/eleven-m5/README.md, Memory budget."])
        self.put_census(census(unowned_bytes=GIB))
        self.samples_ok("2026-11-24T12:00:00")
        self.assertIs(self.read_state()["unowned_open"], False)
        self.put_census(census(unowned_bytes=6 * GIB))
        self.samples_ok("2026-11-24T12:00:00")
        self.assertEqual(len(self.bot.requests), 2)

    def test_a_sampler_stopped_after_its_state_was_written_keeps_the_episode_and_the_sample(self):
        self.settings_on()
        self.put_census(census(unowned_bytes=6 * GIB))
        blocker = self.state_dir / "samples" / f"{DAY}.jsonl"
        blocker.mkdir(parents=True)
        stopped = self.sample(now="2026-11-24T12:00:00")
        self.assertNotEqual(stopped.returncode, 0)
        self.assertEqual(len(self.bot.requests), 1)
        self.assertEqual((self.read_state()["samples"], self.read_state()["unowned_open"]), (1, True))
        blocker.rmdir()
        self.samples_ok("2026-11-24T12:01:00", "2026-11-24T12:02:00")
        self.assertEqual(len(self.bot.requests), 1)
        self.assertEqual(
            [line["at"] for line in self.sample_lines()],
            ["2026-11-24T12:00:00", "2026-11-24T12:01:00", "2026-11-24T12:02:00"])
        self.assertEqual(self.read_state()["samples"], 3)

    def test_a_sample_file_that_stays_unwritable_does_not_stop_the_next_runs_alerts(self):
        self.settings_on()
        self.put_census(census(unowned_bytes=6 * GIB))
        (self.state_dir / "samples" / f"{DAY}.jsonl").mkdir(parents=True)
        self.assertNotEqual(self.sample(now="2026-11-24T12:00:00").returncode, 0)
        self.assertEqual(len(self.bot.requests), 1)
        self.put_census(census(at="2026-11-25T00:00:30", unowned_bytes=GIB))
        resumed = self.sample(now="2026-11-25T00:01:00")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertIn("not recovered", resumed.stderr)
        self.assertIs(self.read_state()["unowned_open"], False)
        self.put_census(census(at="2026-11-25T00:01:30", unowned_bytes=6 * GIB))
        self.samples_ok("2026-11-25T00:02:00")
        self.assertEqual(len(self.bot.requests), 2)
        self.assertEqual(
            [line["at"] for line in self.sample_lines("2026-11-25")],
            ["2026-11-25T00:01:00", "2026-11-25T00:02:00"])

    def test_unowned_at_the_threshold_does_not_alert(self):
        self.settings_on()
        self.put_census(census(unowned_bytes=5 * GIB))
        self.samples_ok("2026-11-24T12:00:00")
        self.assertEqual(self.bot.requests, [])
        self.assertIs(self.read_state()["unowned_open"], False)

    def test_a_stale_census_neither_opens_nor_closes_the_episode(self):
        self.settings_on()
        self.put_state(state(unowned_open=True))
        self.put_census(census(at="2026-11-24T11:50:00", unowned_bytes=GIB))
        self.samples_ok("2026-11-24T12:00:00")
        self.assertIs(self.read_state()["unowned_open"], True)
        self.put_census(census())
        self.samples_ok("2026-11-24T12:00:00")
        self.assertEqual(self.bot.requests, [])

    def test_an_open_episode_carries_over_the_day(self):
        self.settings_on()
        self.put_state(state(day="2026-11-24", unowned_open=True))
        self.put_census(census(at="2026-11-25T00:00:30"))
        self.samples_ok("2026-11-25T00:01:00")
        self.assertEqual(self.bot.requests, [])
        self.assertIs(self.read_state()["unowned_open"], True)

    def test_wired_memory_far_below_the_model_queues_no_alert(self):
        self.settings_on()
        self.health()
        self.put_census(census(unowned_bytes=0))
        self.samples_ok("2026-11-24T12:00:00", "2026-11-24T12:00:00")
        self.assertEqual(self.bot.requests, [])
        self.assertEqual(self.read_state()["pending"], [])


if __name__ == "__main__":
    unittest.main()
