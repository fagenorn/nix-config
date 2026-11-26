"""The events the eleven-m5 watcher records beside each sample, and the verify-slot history's offset read.

Runs `agent_tools.hosts.omlx_memory_watch sample` as a child with fake `hdiutil`, `ps` and pid and history
files, and reads `omlx_memory_events` and `verify_history.read_from` in process: which event each source
yields, what a source that cannot be read leaves alone and how the history is read again.
Run: just agent-workflow-tests
"""

import json
import os
import plistlib
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery import verify_history
from agent_tools.hosts import omlx_memory_events as events
from tests.test_omlx_memory_records import RecordsCase, before, census
from tests.test_omlx_memory_watch import GIB, PS_IDLE, kill

TIER = "fast"

VERIFY_ARGS = (
    "/nix/store/x-python3-env/bin/python3 -I -m agent_tools.delivery.verify_slot run --wait-limit 600 -- just test")
OTHER_VM = (
    "500 /System/Library/Frameworks/Virtualization.framework/Versions/A/XPCServices/"
    "com.apple.Virtualization.VirtualMachine.xpc/Contents/MacOS/com.apple.Virtualization.VirtualMachine")
HOSTAGENT = (
    "71379 /nix/store/x-lima-full/bin/.limactl-wrapped hostagent --pidfile /Users/owner/.colima/_lima/colima/ha.pid colima")


def held_line(started, waited, held, command="just test"):
    record = {
        "command": command, "exit": 0, "held_seconds": held, "repository": "o/r", "started": started,
        "waited_seconds": waited,
    }
    return json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"


def image(blocks, dev, mount):
    entity = {"dev-entry": dev} if mount is None else {"dev-entry": dev, "mount-point": mount}
    return {"image-path": f"ram://{blocks}", "blockcount": blocks, "blocksize": 512, "system-entities": [entity]}


def plist(*images):
    return plistlib.dumps({"images": list(images)}).decode()


class EventSampleTest(RecordsCase):
    def setUp(self):
        super().setUp()
        self.history = self.d / "history.jsonl"
        self.pid_file = self.d / "vz.pid"

    def disks(self, *images):
        (self.d / "hdiutil.plist").write_text(plist(*images))

    def floor(self, kills, recent):
        (self.d / "floor.json").write_text(json.dumps({
            "kills": kills, "recent": recent, "floor_bytes": 16 * GIB, "run_bound_bytes": 24 * GIB,
            "omlx_pid": 73552, "omlx_kernel_priority": 100, "omlx_priority_resets": 0,
            "declared_priority": 100, "omlx_priority_error": None,
        }))

    def take(self, now):
        self.put_census(census(at=before(now)))
        result = self.sample(now=now)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.sample_lines()[-1]

    def test_each_event_kind_lands_in_the_sample_line_beside_the_figures(self):
        self.disks(image(131072, "/dev/disk4", "/private/tmp/secrets.d"))
        self.ps(PS_IDLE + f"9001 (Runner.Worker)\n{OTHER_VM}\n25168 {VERIFY_ARGS}\n")
        self.floor(1, [kill(1)])
        self.history.write_text(held_line("2026-11-24T10:00:00Z", 0.0, 60.0))
        first = self.take("2026-11-24T12:00:00")
        self.disks(image(2097152, "/dev/disk5", "/Volumes/NodoTestTmp"))
        self.ps(PS_IDLE + f"9002 (Runner.Worker)\n{OTHER_VM}\n{HOSTAGENT}\n25432 {VERIFY_ARGS}\n")
        self.pid_file.write_text("71379\n")
        self.floor(2, [kill(1), kill(2)])
        with self.history.open("a") as handle:
            handle.write(held_line("2026-11-24T11:49:00Z", 60.0, 480.0))
        second = self.take("2026-11-24T12:01:00")
        self.ps(PS_IDLE + f"9002 (Runner.Worker)\n{OTHER_VM}\n25432 {VERIFY_ARGS}\n")
        third = self.take("2026-11-24T12:02:00")
        self.assertEqual(first["events"], [])
        self.assertEqual(second["events"], [
            {"kind": "ram_disk_detached", "dev": "/dev/disk4", "mount": "/private/tmp/secrets.d", "gib": 0.1},
            {"kind": "ram_disk_attached", "dev": "/dev/disk5", "mount": "/Volumes/NodoTestTmp", "gib": 1.0},
            {"kind": "vm_started", "pid": 71379},
            {"kind": "ci_job_ended", "pid": 9001},
            {"kind": "ci_job_started", "pid": 9002},
            {"kind": "verify_ended", "pid": 25168, "command": "just test"},
            {"kind": "verify_started", "pid": 25432, "command": "just test"},
            {"kind": "verify_run", "repository": "o/r", "command": "just test", "exit": 0,
             "held_from": "2026-11-24T11:50:00+00:00", "held_until": "2026-11-24T11:58:00+00:00",
             "tree_peak_bytes": None, "tree_peak_at": None},
            {"kind": "floor_kill", "at": "2026-11-24T12:33:05+00:00", "reason": "floor", "owner": "anis",
             "root_pid": 300, "signals": "term+kill", "tree_gib": 146.0},
        ])
        self.assertEqual(third["events"], [{"kind": "vm_stopped", "pid": 71379}])
        for line in (first, second, third):
            self.assertIsNotNone(line["unowned_bytes"])

    def test_a_failed_hdiutil_leaves_the_ram_disks_as_they_were(self):
        self.disks(image(131072, "/dev/disk4", "/private/tmp/secrets.d"))
        self.take("2026-11-24T12:00:00")
        (self.d / "hdiutil.fail").write_text("")
        second = self.take("2026-11-24T12:01:00")
        self.assertEqual(second["events"], [])
        self.assertEqual(list(self.read_state()["ram_disks_seen"]), ["/dev/disk4"])
        (self.d / "hdiutil.fail").unlink()
        self.disks()
        third = self.take("2026-11-24T12:02:00")
        self.assertEqual(
            third["events"],
            [{"kind": "ram_disk_detached", "dev": "/dev/disk4", "mount": "/private/tmp/secrets.d", "gib": 0.1}])

    def test_a_disk_replaced_at_the_same_device_by_one_of_another_size_is_detached_and_attached(self):
        self.disks(image(2097152, "/dev/disk5", "/Volumes/X"))
        self.take("2026-11-24T12:00:00")
        self.disks(image(16777216, "/dev/disk5", "/Volumes/X"))
        line = self.take("2026-11-24T12:01:00")
        self.assertEqual(line["events"], [
            {"kind": "ram_disk_detached", "dev": "/dev/disk5", "mount": "/Volumes/X", "gib": 1.0},
            {"kind": "ram_disk_attached", "dev": "/dev/disk5", "mount": "/Volumes/X", "gib": 8.0}])
        self.disks(image(16777216, "/dev/disk5", None))
        self.assertEqual(self.take("2026-11-24T12:02:00")["events"], [])

    def test_a_replaced_history_of_the_same_length_is_read_again(self):
        first = held_line("2026-11-24T11:00:00Z", 0.0, 60.0)
        second = held_line("2026-11-24T11:30:00Z", 0.0, 60.0)
        self.assertEqual(len(first), len(second))
        self.history.write_text(first)
        self.take("2026-11-24T12:00:00")
        replacement = self.d / "history.tmp"
        replacement.write_text(second)
        os.replace(replacement, self.history)
        line = self.take("2026-11-24T12:01:00")
        [event] = line["events"]
        self.assertEqual(event["kind"], "verify_run")
        self.assertEqual(event["held_from"], "2026-11-24T11:30:00+00:00")
        status = self.history.stat()
        self.assertEqual(
            self.read_state()["history_seen"],
            {"identity": [status.st_dev, status.st_ino], "offset": len(second.encode())})

    def test_a_cleared_history_starts_again_from_its_first_line(self):
        self.history.write_text(
            held_line("2026-11-24T10:00:00Z", 0.0, 60.0) + held_line("2026-11-24T10:30:00Z", 0.0, 60.0))
        self.take("2026-11-24T12:00:00")
        self.history.unlink()
        middle = self.take("2026-11-24T12:01:00")
        self.assertEqual([event for event in middle["events"] if event["kind"] == "verify_run"], [])
        self.assertEqual(self.read_state()["history_seen"], {"identity": None, "offset": 0})
        self.history.write_text(held_line("2026-11-24T12:01:30Z", 0.0, 10.0))
        last = self.take("2026-11-24T12:02:00")
        self.assertEqual([event["kind"] for event in last["events"]], ["verify_run"])

    def test_a_run_that_never_held_a_slot_is_not_an_event(self):
        self.history.write_text("")
        self.take("2026-11-24T12:00:00")
        line = held_line("2026-11-24T12:00:10Z", 5.0, None)
        self.history.write_text(line)
        again = self.take("2026-11-24T12:01:00")
        self.assertEqual(again["events"], [])
        self.assertEqual(self.read_state()["history_seen"]["offset"], len(line.encode()))

    def test_a_hold_too_large_to_be_a_time_is_skipped_and_the_sample_goes_on(self):
        self.history.write_text("")
        self.take("2026-11-24T12:00:00")
        huge_hold = held_line("2026-11-24T12:00:10Z", 0.0, 1e300)
        huge_wait = held_line("9999-12-31T00:00:00Z", 1e9, 60.0)
        good = held_line("2026-11-24T12:00:20Z", 0.0, 10.0)
        with self.history.open("a") as handle:
            handle.write(huge_hold + huge_wait + good)
        line = self.take("2026-11-24T12:01:00")
        [event] = [event for event in line["events"] if event["kind"] == "verify_run"]
        self.assertEqual(event["held_from"], "2026-11-24T12:00:20+00:00")
        self.assertEqual(
            self.read_state()["history_seen"]["offset"], len((huge_hold + huge_wait + good).encode()))

    def test_an_unreadable_pid_file_leaves_the_vm_as_it_was(self):
        self.ps(PS_IDLE + f"{HOSTAGENT}\n")
        self.pid_file.write_text("71379\n")
        self.take("2026-11-24T12:00:00")
        self.assertEqual(self.read_state()["vm_seen"], {"pid": 71379})
        real = self.d / "vz.real"
        real.write_text("71379\n")
        self.pid_file.unlink()
        self.pid_file.symlink_to(real)
        line = self.take("2026-11-24T12:01:00")
        self.assertEqual([event for event in line["events"] if event["kind"].startswith("vm_")], [])
        self.assertEqual(self.read_state()["vm_seen"], {"pid": 71379})


class ParseEventsTest(unittest.TestCase):
    def test_ci_pids_read_paths_and_parenthesised_names(self):
        listing = (
            "12 (Runner.Worker)\n13 /a/b/Runner.Worker spawnclient 1 2\n14 Runner.Workers\n"
            "15 /bin/sh -c Runner.Worker\n")
        self.assertEqual(events.ci_pids(events.parse_listing(listing)), [12, 13])

    def test_a_verify_slot_run_is_found_by_its_arguments(self):
        listing = (
            f"25168 {VERIFY_ARGS}\n30 /nix/store/x/bin/verify-slot run -- nix build .#a extra\n"
            "31 /nix/store/x/bin/verify-slot report\n32 (python3.13)\n")
        self.assertEqual(
            events.verify_runs_live(events.parse_listing(listing)), {25168: "just test", 30: "nix build .#a"})

    def test_a_remote_or_wrapped_verify_slot_run_is_not_a_local_run(self):
        listing = (
            "40 ssh buildhost python3 -m agent_tools.delivery.verify_slot run -- just test\n"
            "41 /bin/sh -c python3 -m agent_tools.delivery.verify_slot run -- just test\n"
            "42 /usr/bin/python3 -c print -m agent_tools.delivery.verify_slot run -- just test\n"
            "43 vi verify-slot run -- just test\n"
            "44 /nix/store/x/bin/.python3.13-wrapped -I -B -m agent_tools.delivery.verify_slot run -- just lint\n")
        self.assertEqual(events.verify_runs_live(events.parse_listing(listing)), {44: "just lint"})

    def test_the_colima_pid_counts_only_while_its_process_lives(self):
        self.assertEqual(events.colima_vm_pid("71379\n", {71379: "x"}), 71379)
        self.assertIsNone(events.colima_vm_pid("71379\n", {500: "x"}))
        self.assertIsNone(events.colima_vm_pid("abc", {71379: "x"}))
        self.assertIsNone(events.colima_vm_pid(None, {71379: "x"}))

    def test_a_ram_disk_is_named_by_its_whole_disk(self):
        text = plistlib.dumps({"images": [
            {"image-path": "ram://2097152", "blockcount": 2097152, "blocksize": 512, "system-entities": [
                {"dev-entry": "/dev/disk5s1", "mount-point": "/Volumes/X"}, {"dev-entry": "/dev/disk5"}]},
            {"image-path": "/Users/o/a.dmg", "blockcount": 8, "blocksize": 512,
             "system-entities": [{"dev-entry": "/dev/disk6", "mount-point": "/Volumes/Y"}]},
        ]}).decode()
        self.assertEqual(events.parse_ram_disks(text), {"/dev/disk5": {"mount": "/Volumes/X", "bytes": 1073741824}})

    def test_text_that_is_not_a_plist_is_refused(self):
        with self.assertRaises(ValueError):
            events.parse_ram_disks("garbage")


class HistoryReadFromTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.path = Path(scratch.name) / "history.jsonl"

    def identity(self):
        status = self.path.stat()
        return [status.st_dev, status.st_ino]

    def test_only_lines_after_the_offset_are_read(self):
        one = held_line("2026-11-24T10:00:00Z", 0.0, 60.0)
        two = held_line("2026-11-24T11:00:00Z", 1.0, 30.0)
        self.path.write_text(one + two)
        records, identity, offset = verify_history.read_from(self.path, self.identity(), len(one))
        self.assertEqual(records, [json.loads(two)])
        self.assertEqual((identity, offset), (self.identity(), len(one) + len(two)))

    def test_a_torn_last_line_waits_for_its_newline(self):
        one = held_line("2026-11-24T10:00:00Z", 0.0, 60.0)
        two = held_line("2026-11-24T11:00:00Z", 1.0, 30.0)
        self.path.write_text(one + two[:-1])
        records, identity, offset = verify_history.read_from(self.path, None, 0)
        self.assertEqual((records, offset), ([json.loads(one)], len(one)))
        with self.path.open("a") as handle:
            handle.write("\n")
        records, _, offset = verify_history.read_from(self.path, identity, offset)
        self.assertEqual((records, offset), ([json.loads(two)], len(one) + len(two)))

    def test_a_record_longer_than_the_read_limit_is_skipped_and_the_offset_advances(self):
        good = held_line("2026-11-24T10:00:00Z", 0.0, 60.0)
        self.assertLess(len(good), 256)
        self.path.write_text("x" * 600 + "\n" + good)
        records, identity, offset = verify_history.read_from(self.path, None, 0, limit=256)
        self.assertEqual((records, offset), ([], 256))
        offsets = [offset]
        while not records:
            records, identity, offset = verify_history.read_from(self.path, identity, offset, limit=256)
            offsets.append(offset)
        self.assertEqual(records, [json.loads(good)])
        self.assertEqual(offset, 601 + len(good))
        self.assertEqual(offsets, [256, 512, 601 + len(good)])

    def test_an_unterminated_record_under_the_limit_is_read_again_without_growing_the_read(self):
        self.path.write_text("y" * 40)
        records, identity, offset = verify_history.read_from(self.path, None, 0, limit=64)
        self.assertEqual((records, offset), ([], 0))
        self.assertEqual(verify_history.read_from(self.path, identity, offset, limit=64)[2], 0)

    def test_a_baseline_skips_to_the_last_newline_of_the_final_bytes_without_reading_records(self):
        one = held_line("2026-11-24T10:00:00Z", 0.0, 60.0)
        torn = held_line("2026-11-24T11:00:00Z", 1.0, 30.0)[:-1]
        self.path.write_text("z" * 5000 + "\n" + one + torn)
        records, identity, offset = verify_history.read_from(self.path, None, 0, baseline=True, limit=1024)
        self.assertEqual((records, identity, offset), ([], self.identity(), 5001 + len(one)))
        self.path.write_text("z" * 5000)
        self.assertEqual(verify_history.read_from(self.path, None, 0, baseline=True, limit=1024)[2], 5000)
        self.path.write_text(torn)
        self.assertEqual(verify_history.read_from(self.path, None, 0, baseline=True, limit=1024)[2], 0)

    def test_a_symlinked_history_is_refused(self):
        real = self.path.parent / "real.jsonl"
        real.write_text(held_line("2026-11-24T10:00:00Z", 0.0, 60.0))
        self.path.symlink_to(real)
        with self.assertRaises(OSError):
            verify_history.read_from(self.path, None, 0)


if __name__ == "__main__":
    unittest.main()
