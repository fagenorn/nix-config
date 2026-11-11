"""The console's append-only event log (#855): sequence, immutability, canonical payloads, atomic appends."""

import inspect
import re
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
        for version in (7, 3):
            with self.subTest(version=version):
                store = Path(self.tmp.name) / f"v{version}" / "events.sqlite3"
                store.parent.mkdir(parents=True)
                connection = sqlite3.connect(store)
                connection.execute(f"PRAGMA user_version = {version}")
                connection.close()
                with self.assertRaises(EventLogError):
                    EventLog(store, clock=clock)
                connection = sqlite3.connect(store)
                self.addCleanup(connection.close)
                self.assertEqual(
                    connection.execute("PRAGMA user_version").fetchone()[0], version)
                self.assertEqual(connection.execute(
                    "SELECT name FROM sqlite_master WHERE name = 'events'").fetchall(), [])


NOW = "2026-11-11T00:00:00.000000+00:00"
CUTOFF = "2026-08-13T00:00:00.000000+00:00"
OLD = "2026-08-12T23:59:59.999999+00:00"
EDGE = "2026-08-13T00:00:00.000000+00:00"
NEW = "2026-11-10T00:00:00.000000+00:00"

SCHEMA_1 = (
    """CREATE TABLE IF NOT EXISTS events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        kind TEXT NOT NULL,
        project TEXT,
        payload TEXT NOT NULL)""",
    """CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
        BEGIN SELECT RAISE(ABORT, 'the console event log is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
        BEGIN SELECT RAISE(ABORT, 'the console event log is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS events_no_replace BEFORE INSERT ON events
        WHEN EXISTS (SELECT 1 FROM events WHERE seq = NEW.seq)
        BEGIN SELECT RAISE(ABORT, 'the console event log is append-only'); END""",
)


class FailingDelete:
    """A connection whose DELETE statements fail; everything else passes through."""

    def __init__(self, connection):
        self._connection = connection

    def execute(self, statement, *args):
        if statement.lstrip().upper().startswith("DELETE"):
            raise sqlite3.OperationalError("boom")
        return self._connection.execute(statement, *args)

    def __getattr__(self, name):
        return getattr(self._connection, name)


class RetentionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "console" / "events.sqlite3"
        self.now = NOW

    def open(self):
        log = EventLog(self.store, clock=lambda: self.now)
        self.addCleanup(log.close)
        return log

    def at(self, log, stamp, kind):
        self.now = stamp
        return log.append([(kind, "o/a", {})])

    def three_rows(self):
        log = self.open()
        self.at(log, OLD, "old")
        self.at(log, EDGE, "edge")
        self.at(log, NEW, "new")
        return log

    def retain_at(self, log, stamp):
        self.now = stamp
        return log.retain()

    def raw(self):
        # autocommit: a refused statement must not leave a read lock behind
        connection = sqlite3.connect(self.store, isolation_level=None)
        self.addCleanup(connection.close)
        return connection

    def cutoff(self):
        return self.raw().execute("SELECT cutoff FROM retention").fetchall()

    def test_a_pass_removes_only_rows_older_than_90_days(self):
        log = self.three_rows()
        self.assertEqual(self.retain_at(log, NOW), 1)
        self.assertEqual([row[2] for row in rows(self.store)], ["edge", "new"])
        self.assertEqual([e.kind for e in log.events()], ["edge", "new"])

    def test_a_raw_delete_of_a_kept_row_is_refused_after_a_pass(self):
        log = self.three_rows()
        self.retain_at(log, NOW)
        before = rows(self.store)
        connection = self.raw()
        for statement in ("DELETE FROM events",
                          "DELETE FROM events WHERE kind = 'new'"):
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(statement)
        self.assertEqual(rows(self.store), before)

    def test_the_cutoff_only_moves_forward(self):
        log = self.three_rows()
        self.retain_at(log, NOW)
        connection = self.raw()
        for statement in ("UPDATE retention SET cutoff = ''",
                          "DELETE FROM retention",
                          "INSERT INTO retention (id, cutoff) VALUES (2, 'z')",
                          "INSERT OR REPLACE INTO retention (id, cutoff) VALUES (1, '')"):
            with self.assertRaises(sqlite3.IntegrityError, msg=statement):
                connection.execute(statement)
        self.assertEqual(self.cutoff(), [(CUTOFF,)])
        self.assertEqual(self.retain_at(log, "2026-11-01T00:00:00.000000+00:00"), 0)
        self.assertEqual(self.cutoff(), [(CUTOFF,)])

    def test_sequence_numbers_are_not_reused_after_a_pass(self):
        log = self.open()
        self.at(log, "2026-01-01T00:00:00.000000+00:00", "a")
        self.at(log, "2026-01-01T00:00:00.000000+00:00", "b")
        self.assertEqual(self.retain_at(log, NOW), 2)
        self.assertEqual(rows(self.store), [])
        self.assertEqual(self.at(log, NOW, "c")[0].seq, 3)

    def test_a_version_1_store_is_migrated_and_keeps_its_rows(self):
        self.store.parent.mkdir(parents=True)
        connection = sqlite3.connect(self.store)
        for statement in SCHEMA_1:
            connection.execute(statement)
        connection.execute("PRAGMA user_version = 1")
        connection.execute(
            "INSERT INTO events (at, kind, project, payload) "
            "VALUES ('2026-01-01T00:00:00.000000+00:00', 'a', 'o/a', '{}')")
        connection.execute(
            f"INSERT INTO events (at, kind, project, payload) VALUES ('{NOW}', 'b', 'o/a', '{{}}')")
        connection.commit()
        connection.close()
        log = self.open()
        raw = self.raw()
        self.assertEqual(raw.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(rows(self.store), [
            (1, "2026-01-01T00:00:00.000000+00:00", "a", "o/a", "{}"),
            (2, NOW, "b", "o/a", "{}"),
        ])
        with self.assertRaises(sqlite3.IntegrityError):
            raw.execute("DELETE FROM events")
        self.assertEqual(self.retain_at(log, NOW), 1)

    def test_a_failed_pass_deletes_nothing(self):
        log = self.three_rows()
        before = rows(self.store)
        log._connection = FailingDelete(log._connection)
        self.now = NOW
        with self.assertRaises(sqlite3.OperationalError):
            log.retain()
        self.assertEqual(rows(self.store), before)
        self.assertEqual(self.cutoff(), [("",)])

    def test_only_retain_issues_a_delete(self):
        source = inspect.getsource(event_log)
        self.assertEqual(len(re.findall(r"\bDELETE\s+FROM\b", source)), 1)
        self.assertIn("DELETE FROM events", inspect.getsource(EventLog.retain))


if __name__ == "__main__":
    unittest.main()
