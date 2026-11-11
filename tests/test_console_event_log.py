"""The console's append-only event log (#855): sequence, immutability, canonical payloads, atomic appends."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_tools.console import event_log
from agent_tools.console.event_log import EventLog, EventLogError

STAMP = "2026-11-11T00:00:00.000000+00:00"


def clock():
    return STAMP


def rows(store):
    connection = sqlite3.connect(store)
    try:
        return connection.execute(
            "SELECT seq, at, kind, project, payload FROM events ORDER BY seq"
        ).fetchall()
    finally:
        connection.close()


class EventLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "console" / "events.sqlite3"

    def open(self):
        log = EventLog(self.store, clock=clock)
        self.addCleanup(log.close)
        return log

    def test_append_assigns_increasing_sequence_numbers(self):
        log = self.open()
        log.append([
            ("project.registered", "o/a", {"root": "/a"}),
            ("project.registered", "o/b", {"root": "/b"}),
        ])
        log.append([("project.registered", "o/c", {"root": "/c"})])
        events = log.events()
        self.assertEqual([e.seq for e in events], [1, 2, 3])
        self.assertEqual([e.kind for e in events], ["project.registered"] * 3)
        self.assertEqual([e.project for e in events], ["o/a", "o/b", "o/c"])
        self.assertEqual([e.payload for e in events],
                         [{"root": "/a"}, {"root": "/b"}, {"root": "/c"}])
        self.assertEqual({e.at for e in events}, {STAMP})

    def test_an_update_is_refused(self):
        self.open().append([("k", "o/a", {})])
        before = rows(self.store)
        connection = sqlite3.connect(self.store)
        self.addCleanup(connection.close)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("UPDATE events SET kind = 'x'")
        self.assertEqual(rows(self.store), before)

    def test_a_delete_is_refused(self):
        self.open().append([("k", "o/a", {})])
        connection = sqlite3.connect(self.store)
        self.addCleanup(connection.close)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM events")
        self.assertEqual(len(rows(self.store)), 1)

    def test_a_replacing_insert_is_refused(self):
        self.open().append([("k", "o/a", {})])
        before = rows(self.store)
        connection = sqlite3.connect(self.store)
        self.addCleanup(connection.close)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT OR REPLACE INTO events (seq, at, kind, project, payload) "
                "VALUES (1, 'x', 'x', 'x', '{}')")
        self.assertEqual(rows(self.store), before)

    def test_reopening_keeps_every_row(self):
        log = EventLog(self.store, clock=clock)
        log.append([("k", "o/a", {"n": 1}), ("k", None, {"n": 2})])
        before = log.events()
        log.close()
        again = self.open()
        self.assertEqual(again.events(), before)
        self.assertEqual(len(before), 2)

    def test_payload_is_stored_canonically(self):
        self.open().append([("k", "o/a", {"b": 1, "a": "é"})])
        connection = sqlite3.connect(self.store)
        self.addCleanup(connection.close)
        stored = connection.execute("SELECT payload FROM events").fetchone()[0]
        self.assertEqual(stored, '{"a":"é","b":1}')

    def test_a_failed_append_writes_no_row(self):
        log = self.open()
        with self.assertRaises(ValueError):
            log.append([("k", "o/a", {}), ("k", "o/b", {"x": float("nan")})])
        self.assertEqual(rows(self.store), [])

    def test_a_database_failure_rolls_back_the_whole_append(self):
        log = self.open()
        log.append([("k", "o/first", {})])
        before = rows(self.store)
        connection = sqlite3.connect(self.store)
        connection.execute(
            "CREATE TRIGGER boom BEFORE INSERT ON events WHEN NEW.project = 'o/boom' "
            "BEGIN SELECT RAISE(ABORT, 'boom'); END")
        connection.commit()
        connection.close()
        with self.assertRaises(sqlite3.IntegrityError):
            log.append([("k", "o/ok", {}), ("k", "o/boom", {})])
        self.assertEqual(rows(self.store), before)
        after = log.append([("k", "o/after", {})])
        self.assertEqual([e.seq for e in after], [2])

    def test_an_empty_append_writes_nothing(self):
        log = self.open()
        self.assertEqual(log.append([]), [])
        self.assertEqual(rows(self.store), [])

    def test_an_unknown_schema_version_is_refused(self):
        self.store.parent.mkdir(parents=True)
        connection = sqlite3.connect(self.store)
        connection.execute("PRAGMA user_version = 7")
        connection.close()
        with self.assertRaises(EventLogError):
            EventLog(self.store, clock=clock)
        connection = sqlite3.connect(self.store)
        self.addCleanup(connection.close)
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 7)
        self.assertEqual(connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'events'").fetchall(), [])


if __name__ == "__main__":
    unittest.main()
