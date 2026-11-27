"""The digest names a delivery that ended, end to end through the service.

Run: just agent-workflow-tests
"""
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.console import deliveries, digest
from agent_tools.console.event_log import Event
from agent_tools.delivery import engine_ledger

from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "fast"
SINGLE = Path(__file__).parent / "fixtures/console/journals/single.jsonl"
ENGINE_FIXTURES = Path(__file__).parent / "fixtures/console/engine-runs"
RUN_ID = "41-20261121T160000Z-ab12"
SERVICE_NOW = datetime(2026, 11, 21, 16, 30, tzinfo=timezone.utc)


class DeliveryEndedTest(unittest.TestCase):
    def start(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = self.root / "state/console/events.sqlite3"
        self.registry = self.root / "state/fleet/registry.json"
        support.write_registry(self.registry, [{"project_id": "owner/p00", "root": "/srv/p00"}])
        self.now = time.time()  # the log stamps real time; the digest window follows the service clock
        self.svc = support.service(self, self.store, self.registry,
                                   session_dirs=[self.root / "sessions"], session_poll_seconds=3600,
                                   clock=lambda: self.now)
        body = support.hook_body("session start", cwd="/srv/p00")
        self.sid = json.loads(body)["session_id"]
        self.svc.ingest_hook(body)
        self.session = self.root / "projects/-srv-p00" / self.sid
        self.journal = self.session / "subagents/workflows/wf_t1/journal.jsonl"
        self.journal.parent.mkdir(parents=True)

    def write_journal(self, count):
        self.journal.write_text("".join(SINGLE.read_text().splitlines(keepends=True)[:count]))

    def finish(self):
        (self.session / "workflows").mkdir(exist_ok=True)
        (self.session / "workflows/wf_t1.json").write_text("{}")

    def recent(self):
        return json.loads(self.svc.view_bytes)["digest"]["recent"]

    def test_a_run_with_a_final_record_is_named_in_the_digest(self):
        self.start()
        self.write_journal(10)
        self.svc.poll_deliveries()
        self.finish()
        self.svc.poll_deliveries()
        (ended,) = self.recent()
        self.assertEqual(ended["kind"], "delivery_ended")
        self.assertEqual(
            ended["sentence"], "The delivery of owner/p00 #858 ended: stopped at building.")

    def test_a_run_that_starts_and_finishes_between_two_polls_is_named_once(self):
        self.start()
        self.svc.poll_deliveries()
        self.write_journal(10)
        self.finish()
        self.svc.poll_deliveries()
        self.svc.poll_deliveries()
        (ended,) = self.recent()
        self.assertEqual(
            ended["sentence"], "The delivery of owner/p00 #858 ended: stopped at building.")
        rows = [row[2] for row in support.log_rows(self.store) if row[2].startswith("delivery.")]
        self.assertEqual(rows, ["delivery.seen", "delivery.gone"])

    def test_a_run_that_finished_before_the_console_started_says_nothing(self):
        self.start()
        self.write_journal(10)
        self.finish()
        long_ago = time.time() - 3600
        os.utime(self.session / "workflows/wf_t1.json", (long_ago, long_ago))
        self.svc.poll_deliveries()
        self.assertEqual(self.recent(), [])
        self.assertEqual([row for row in support.log_rows(self.store)
                          if row[2].startswith("delivery.")], [])

    def test_a_gone_row_carries_enough_to_replay_its_ending_after_its_seen_row_is_removed(self):
        self.start()
        self.write_journal(10)
        self.svc.poll_deliveries()
        self.finish()
        self.svc.poll_deliveries()
        rows = [Event(seq, at, kind, project, json.loads(payload))
                for seq, at, kind, project, payload in support.log_rows(self.store)]
        (gone,) = [row for row in rows if row.kind == deliveries.DELIVERY_GONE]
        heard = digest.moments([gone], {}, {})
        self.assertEqual([m.sentence for m in heard],
                         ["The delivery of owner/p00 #858 ended: stopped at building."])

    def test_a_gone_row_without_a_known_seen_or_a_snapshot_says_nothing(self):
        gone = Event(1, "2026-11-11T10:30:00.000000+00:00", deliveries.DELIVERY_GONE, "owner/p00",
                     {"session_id": "s1", "run_id": "r1"})
        self.assertEqual(digest.moments([gone], {}, {}), [])
        malformed = Event(2, "2026-11-11T10:30:00.000000+00:00", deliveries.DELIVERY_GONE, "owner/p00",
                          {"session_id": "s1", "run_id": "r1", "project": "owner/p00",
                           "issues": [{"issue": "9", "stage": "done"}]})
        self.assertEqual(digest.moments([malformed], {}, {}), [])


class ReplayCostTest(unittest.TestCase):
    @staticmethod
    def rows(count):
        seen = [Event(n, "2026-11-11T09:00:00.000000+00:00", deliveries.DELIVERY_SEEN, "owner/p00",
                      {"session_id": f"s{n}", "run_id": "r", "moved_ms": 0,
                       "issues": [{"issue": n, "stage": "done", "task": None, "tasks": None}]})
                for n in range(count)]
        gone = [Event(count + n, "2026-11-11T11:00:00.000000+00:00", deliveries.DELIVERY_GONE,
                      "owner/p00", {"session_id": f"s{n}", "run_id": "r"})
                for n in range(count)]
        return seen + gone

    @staticmethod
    def seconds(events):
        best = None
        for _ in range(3):
            started = time.perf_counter()
            found = digest.moments(events, {}, {})
            took = time.perf_counter() - started
            best = took if best is None else min(best, took)
        return best, found

    def test_replaying_distinct_runs_grows_no_faster_than_their_number(self):
        small, found = self.seconds(self.rows(1000))
        self.assertEqual(len(found), 1000)
        large, found = self.seconds(self.rows(4000))
        self.assertEqual(len(found), 4000)
        # four times the rows: linear is about 4x, a copy of every run per row is about 16x
        self.assertLess(large, small * 9)


class EngineDeliveryEndedTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = self.root / "state/console/events.sqlite3"
        self.registry = self.root / "state/fleet/registry.json"
        support.write_registry(self.registry, [{"project_id": "owner/p00", "root": "/srv/p00"}])
        self.runs = self.root / "runs"

    def make_run(self, lines, name=RUN_ID):
        run_dir = self.runs / name
        run_dir.mkdir(parents=True)
        members = {member: "x" for member in engine_ledger.RUN_MEMBERS}
        members.update(inputs={}, issue=41, project="owner/p00", run=name, sequence=1,
                       started="2026-11-21T16:00:00Z")
        (run_dir / "run.json").write_text(json.dumps(members))
        (run_dir / "events.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
        return run_dir

    def start(self):
        return support.service(
            self, self.store, self.registry, engine_runs_root=self.runs, session_poll_seconds=3600,
            clock=lambda: SERVICE_NOW.timestamp(),
            log_clock=lambda: "2026-11-21T16:30:00.000000+00:00")

    def lines(self, fixture):
        return [json.loads(line) for line in (ENGINE_FIXTURES / fixture).read_text().splitlines()]

    def recent(self, svc):
        return json.loads(svc.view_bytes)["digest"]["recent"]

    def test_an_engine_delivery_that_is_done_is_named_once_and_survives_a_restart(self):
        self.make_run(self.lines("done.jsonl"))
        svc = self.start()
        svc.poll_engine_runs()
        svc.poll_engine_runs()
        self.assertEqual([m["sentence"] for m in self.recent(svc)],
                         ["The delivery of owner/p00 #41 ended: merged."])
        svc.close()
        again = self.start()
        again.poll_engine_runs()
        self.assertEqual([m["sentence"] for m in self.recent(again)],
                         ["The delivery of owner/p00 #41 ended: merged."])
        self.assertEqual(len([r for r in support.log_rows(self.store) if r[2] == "engine_run.ended"]), 1)

    def test_an_engine_delivery_stopped_with_nothing_needed_says_where_it_stopped(self):
        lines = self.lines("stopped.jsonl")
        lines[-1] = {**lines[-1], "need": "nothing"}
        self.make_run(lines)
        svc = self.start()
        svc.poll_engine_runs()
        self.assertEqual([m["sentence"] for m in self.recent(svc)],
                         ["The delivery of owner/p00 #41 ended: stopped at setup."])

    def test_an_engine_delivery_that_needs_the_owner_or_is_still_moving_says_nothing(self):
        self.make_run(self.lines("stopped.jsonl"), name="41-20261121T160000Z-ab12")
        self.make_run(self.lines("moving.jsonl"), name="42-20261121T160000Z-ab12")
        svc = self.start()
        svc.poll_engine_runs()
        self.assertEqual(self.recent(svc), [])
        self.assertEqual([r for r in support.log_rows(self.store) if r[2] == "engine_run.ended"], [])

    def test_an_engine_delivery_that_ended_over_a_day_ago_says_nothing(self):
        self.make_run(self.lines("done.jsonl"))
        late = datetime(2026, 11, 23, 16, 30, tzinfo=timezone.utc)
        svc = support.service(
            self, self.store, self.registry, engine_runs_root=self.runs, session_poll_seconds=3600,
            clock=lambda: late.timestamp(), log_clock=lambda: "2026-11-23T16:30:00.000000+00:00")
        svc.poll_engine_runs()
        self.assertEqual(self.recent(svc), [])


if __name__ == "__main__":
    unittest.main()
