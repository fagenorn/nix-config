"""The console's append-only event log (#855): sequence, immutability, canonical payloads, atomic appends."""

import inspect
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_tools.console import event_log, exclusion, signin
from agent_tools.console.event_log import EventLog, EventLogError
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

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
        for version in (10, 9):
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

# The schema-2 store as the base build created it: schema 1 without its delete
# trigger, then the retention cutoff and its triggers.
SCHEMA_2 = (
    SCHEMA_1[0],
    SCHEMA_1[1],
    SCHEMA_1[3],
    """CREATE TABLE IF NOT EXISTS retention (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        cutoff TEXT NOT NULL)""",
    "INSERT INTO retention (id, cutoff) VALUES (1, '')",
    """CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
        WHEN NOT (OLD.at < coalesce((SELECT cutoff FROM retention WHERE id = 1), ''))
        BEGIN SELECT RAISE(ABORT, 'the console event log is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS retention_no_delete BEFORE DELETE ON retention
        BEGIN SELECT RAISE(ABORT, 'the console retention cutoff only moves forward'); END""",
    """CREATE TRIGGER IF NOT EXISTS retention_no_rewind BEFORE UPDATE ON retention
        WHEN NEW.id IS NOT OLD.id OR NEW.cutoff < OLD.cutoff
        BEGIN SELECT RAISE(ABORT, 'the console retention cutoff only moves forward'); END""",
    """CREATE TRIGGER IF NOT EXISTS retention_one_row BEFORE INSERT ON retention
        WHEN EXISTS (SELECT 1 FROM retention)
        BEGIN SELECT RAISE(ABORT, 'the console retention cutoff only moves forward'); END""",
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
        self.assertEqual(raw.execute("PRAGMA user_version").fetchone()[0], 8)
        self.assertEqual(rows(self.store), [
            (1, "2026-01-01T00:00:00.000000+00:00", "a", "o/a", "{}"),
            (2, NOW, "b", "o/a", "{}"),
        ])
        with self.assertRaises(sqlite3.IntegrityError):
            raw.execute("DELETE FROM events")
        self.assertEqual(self.retain_at(log, NOW), 1)

    def goal_rows(self):
        log = self.open()
        self.at(log, OLD, event_log.GOAL_STATED)
        self.at(log, OLD, event_log.GOAL_WITHDRAWN)
        self.at(log, OLD, "old")
        return log

    def test_a_pass_keeps_goal_rows_of_any_age(self):
        log = self.goal_rows()
        removed = self.retain_at(log, NOW)
        self.assertEqual(removed, 1)
        self.assertEqual([row[2] for row in rows(self.store)],
                         ["goal.stated", "goal.withdrawn"])
        self.assertEqual([e.kind for e in log.events()],
                         ["goal.stated", "goal.withdrawn"])
        self.assertEqual(event_log.KEPT_KINDS, frozenset({
            "goal.stated", "goal.withdrawn",
            "brief.sent", "brief.approved", "brief.replied",
            "sprint.reported",
            "sprint.messaged", "sprint.read", "sprint.answered",
            "questions.asked", "question.answered",
            "sprint.closed", "sprint.stop_requested", "manager.stopped"}))
        self.assertNotIn("sprint.nudged", event_log.KEPT_KINDS)
        self.assertEqual(event_log.MANAGER_WOKEN, "manager.woken")
        self.assertNotIn("manager.woken", event_log.KEPT_KINDS)
        self.assertNotIn("manager.stalled", event_log.KEPT_KINDS)

    def test_a_raw_delete_of_a_goal_row_is_refused_after_a_pass(self):
        log = self.goal_rows()
        self.retain_at(log, NOW)
        before = rows(self.store)
        connection = self.raw()
        for statement in ("DELETE FROM events WHERE kind = 'goal.stated'",
                          "DELETE FROM events WHERE kind = 'goal.withdrawn'",
                          "DELETE FROM events"):
            with self.subTest(statement=statement):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(statement)
        self.assertEqual(rows(self.store), before)
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 8)

    def test_a_version_2_store_is_migrated_and_protects_goal_rows(self):
        self.store.parent.mkdir(parents=True)
        connection = sqlite3.connect(self.store)
        for statement in SCHEMA_2:
            connection.execute(statement)
        connection.execute("PRAGMA user_version = 2")
        connection.execute(
            "INSERT INTO events (at, kind, project, payload) VALUES (?, ?, ?, ?)",
            (OLD, "goal.stated", "o/a", '{"goal":"g","sprint_id":"aaaaaaaaaaaaaaaa"}'))
        connection.execute(
            "INSERT INTO events (at, kind, project, payload) VALUES (?, ?, ?, ?)",
            (NOW, "b", "o/a", "{}"))
        connection.commit()
        connection.close()
        log = self.open()
        self.assertEqual(self.raw().execute("PRAGMA user_version").fetchone()[0], 8)
        expected = [
            (1, OLD, "goal.stated", "o/a", '{"goal":"g","sprint_id":"aaaaaaaaaaaaaaaa"}'),
            (2, NOW, "b", "o/a", "{}"),
        ]
        self.assertEqual(rows(self.store), expected)
        self.assertEqual(self.retain_at(log, NOW), 0)
        with self.assertRaises(sqlite3.IntegrityError):
            self.raw().execute("DELETE FROM events WHERE kind = 'goal.stated'")
        self.assertEqual(rows(self.store), expected)

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

    def test_a_pass_keeps_brief_rows_of_any_age(self):
        log = self.open()
        self.at(log, OLD, event_log.BRIEF_SENT)
        self.at(log, OLD, event_log.BRIEF_APPROVED)
        self.at(log, OLD, event_log.BRIEF_REPLIED)
        self.at(log, OLD, "old")
        self.assertEqual(self.retain_at(log, NOW), 1)
        self.assertEqual([row[2] for row in rows(self.store)],
                         ["brief.sent", "brief.approved", "brief.replied"])

    def test_a_version_3_store_is_migrated_and_protects_brief_rows(self):
        self.store.parent.mkdir(parents=True)
        connection = sqlite3.connect(self.store)
        for statement in SCHEMA_2:
            connection.execute(statement)
        connection.execute("DROP TRIGGER events_no_delete")
        connection.execute(
            """CREATE TRIGGER events_no_delete BEFORE DELETE ON events
            WHEN OLD.kind IN ('goal.stated', 'goal.withdrawn')
                OR NOT (OLD.at < coalesce((SELECT cutoff FROM retention WHERE id = 1), ''))
            BEGIN SELECT RAISE(ABORT, 'the console event log is append-only'); END""")
        connection.execute("PRAGMA user_version = 3")
        for kind in ("brief.sent", "old"):
            connection.execute(
                "INSERT INTO events (at, kind, project, payload) VALUES (?, ?, ?, ?)",
                (OLD, kind, "o/a", "{}"))
        connection.commit()
        connection.close()
        log = self.open()
        self.assertEqual(self.raw().execute("PRAGMA user_version").fetchone()[0], 8)
        self.assertEqual(self.retain_at(log, NOW), 1)
        expected = [(1, OLD, "brief.sent", "o/a", "{}")]
        self.assertEqual(rows(self.store), expected)
        with self.assertRaises(sqlite3.IntegrityError):
            self.raw().execute("DELETE FROM events WHERE kind = 'brief.sent'")
        self.assertEqual(rows(self.store), expected)

    def test_a_pass_keeps_report_rows_of_any_age(self):
        log = self.open()
        self.at(log, OLD, event_log.SPRINT_REPORTED)
        self.at(log, OLD, "old")
        removed = self.retain_at(log, NOW)
        self.assertEqual(removed, 1)
        self.assertEqual([row[2] for row in rows(self.store)], ["sprint.reported"])

    def test_a_version_4_store_is_migrated_and_protects_report_rows(self):
        self.store.parent.mkdir(parents=True)
        connection = sqlite3.connect(self.store)
        for statement in SCHEMA_2:
            connection.execute(statement)
        connection.execute("DROP TRIGGER events_no_delete")
        connection.execute(
            """CREATE TRIGGER events_no_delete BEFORE DELETE ON events
            WHEN OLD.kind IN ('brief.approved', 'brief.replied', 'brief.sent', 'goal.stated', 'goal.withdrawn')
                OR NOT (OLD.at < coalesce((SELECT cutoff FROM retention WHERE id = 1), ''))
            BEGIN SELECT RAISE(ABORT, 'the console event log is append-only'); END""")
        connection.execute("PRAGMA user_version = 4")
        for kind in ("sprint.reported", "old"):
            connection.execute(
                "INSERT INTO events (at, kind, project, payload) VALUES (?, ?, ?, ?)",
                (OLD, kind, "o/a", "{}"))
        connection.commit()
        connection.close()
        log = self.open()
        self.assertEqual(self.raw().execute("PRAGMA user_version").fetchone()[0], 8)
        self.assertEqual(self.retain_at(log, NOW), 1)
        expected = [(1, OLD, "sprint.reported", "o/a", "{}")]
        self.assertEqual(rows(self.store), expected)
        with self.assertRaises(sqlite3.IntegrityError):
            self.raw().execute("DELETE FROM events WHERE kind = 'sprint.reported'")
        self.assertEqual(rows(self.store), expected)

    def test_a_version_5_store_is_migrated_and_protects_message_rows(self):
        self.store.parent.mkdir(parents=True)
        connection = sqlite3.connect(self.store)
        for statement in SCHEMA_2:
            connection.execute(statement)
        connection.execute("DROP TRIGGER events_no_delete")
        connection.execute(
            """CREATE TRIGGER events_no_delete BEFORE DELETE ON events
            WHEN OLD.kind IN ('brief.approved', 'brief.replied', 'brief.sent', 'goal.stated', 'goal.withdrawn', 'sprint.reported')
                OR NOT (OLD.at < coalesce((SELECT cutoff FROM retention WHERE id = 1), ''))
            BEGIN SELECT RAISE(ABORT, 'the console event log is append-only'); END""")
        connection.execute("PRAGMA user_version = 5")
        for kind in ("sprint.messaged", "sprint.read", "sprint.answered", "sprint.nudged", "old"):
            connection.execute(
                "INSERT INTO events (at, kind, project, payload) VALUES (?, ?, ?, ?)",
                (OLD, kind, "o/a", "{}"))
        connection.commit()
        connection.close()
        log = self.open()
        self.assertEqual(self.raw().execute("PRAGMA user_version").fetchone()[0], 8)
        self.assertEqual(self.retain_at(log, NOW), 2)
        self.assertEqual([row[2] for row in rows(self.store)],
                         ["sprint.messaged", "sprint.read", "sprint.answered"])
        with self.assertRaises(sqlite3.IntegrityError):
            self.raw().execute("DELETE FROM events WHERE kind = 'sprint.messaged'")

    def test_a_version_6_store_is_migrated_and_protects_closing_rows(self):
        self.store.parent.mkdir(parents=True)
        connection = sqlite3.connect(self.store)
        for statement in SCHEMA_2:
            connection.execute(statement)
        connection.execute("DROP TRIGGER events_no_delete")
        connection.execute(
            """CREATE TRIGGER events_no_delete BEFORE DELETE ON events
            WHEN OLD.kind IN ('brief.approved', 'brief.replied', 'brief.sent', 'goal.stated', 'goal.withdrawn', 'sprint.answered', 'sprint.messaged', 'sprint.read', 'sprint.reported')
                OR NOT (OLD.at < coalesce((SELECT cutoff FROM retention WHERE id = 1), ''))
            BEGIN SELECT RAISE(ABORT, 'the console event log is append-only'); END""")
        connection.execute("PRAGMA user_version = 6")
        for kind in ("sprint.closed", "sprint.stop_requested", "manager.stopped",
                     "manager.stop_failed", "old"):
            connection.execute(
                "INSERT INTO events (at, kind, project, payload) VALUES (?, ?, ?, ?)",
                (OLD, kind, "o/a", "{}"))
        connection.commit()
        connection.close()
        log = self.open()
        self.assertEqual(self.raw().execute("PRAGMA user_version").fetchone()[0], 8)
        self.assertEqual(self.retain_at(log, NOW), 2)
        self.assertEqual([row[2] for row in rows(self.store)],
                         ["sprint.closed", "sprint.stop_requested", "manager.stopped"])
        for kind in ("sprint.closed", "sprint.stop_requested", "manager.stopped"):
            with self.subTest(kind=kind):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.raw().execute("DELETE FROM events WHERE kind = ?", (kind,))

    def test_the_closing_kinds_are_kept_and_a_failed_stop_is_not(self):
        self.assertEqual(event_log.SPRINT_CLOSED, "sprint.closed")
        self.assertEqual(event_log.SPRINT_STOP_REQUESTED, "sprint.stop_requested")
        self.assertEqual(event_log.MANAGER_STOPPED, "manager.stopped")
        self.assertEqual(event_log.MANAGER_STOP_FAILED, "manager.stop_failed")
        self.assertIn(event_log.SPRINT_CLOSED, event_log.KEPT_KINDS)
        self.assertIn(event_log.SPRINT_STOP_REQUESTED, event_log.KEPT_KINDS)
        self.assertIn(event_log.MANAGER_STOPPED, event_log.KEPT_KINDS)
        self.assertNotIn(event_log.MANAGER_STOP_FAILED, event_log.KEPT_KINDS)

    def test_a_version_7_store_is_migrated_and_protects_question_rows(self):
        self.store.parent.mkdir(parents=True)
        connection = sqlite3.connect(self.store)
        for statement in SCHEMA_2:
            connection.execute(statement)
        connection.execute("DROP TRIGGER events_no_delete")
        connection.execute(
            """CREATE TRIGGER events_no_delete BEFORE DELETE ON events
            WHEN OLD.kind IN ('brief.approved', 'brief.replied', 'brief.sent', 'goal.stated', 'goal.withdrawn', 'manager.stopped', 'sprint.answered', 'sprint.closed', 'sprint.messaged', 'sprint.read', 'sprint.reported', 'sprint.stop_requested')
                OR NOT (OLD.at < coalesce((SELECT cutoff FROM retention WHERE id = 1), ''))
            BEGIN SELECT RAISE(ABORT, 'the console event log is append-only'); END""")
        connection.execute("PRAGMA user_version = 7")
        for kind in ("questions.asked", "question.answered", "old"):
            connection.execute(
                "INSERT INTO events (at, kind, project, payload) VALUES (?, ?, ?, ?)",
                (OLD, kind, "o/a", "{}"))
        connection.commit()
        connection.close()
        log = self.open()
        self.assertEqual(self.raw().execute("PRAGMA user_version").fetchone()[0], 8)
        self.assertEqual(self.retain_at(log, NOW), 1)
        self.assertEqual([row[2] for row in rows(self.store)],
                         ["questions.asked", "question.answered"])
        with self.assertRaises(sqlite3.IntegrityError):
            self.raw().execute("DELETE FROM events WHERE kind = 'questions.asked'")


    def test_a_pass_keeps_the_newest_sign_in_reading_of_each_profile(self):
        log = self.open()
        self.now = OLD
        log.append([(event_log.SIGNIN_READING, None, {"profile": "a", "state": "signed_out",
                                                       "ends_at": None})])
        log.append([(event_log.SIGNIN_READING, None, {"profile": "a", "state": "signed_out",
                                                       "ends_at": None}),
                    (event_log.SIGNIN_READING, None, {"profile": "b", "state": "signed_out",
                                                       "ends_at": None})])
        log.append([("old", None, {})])
        self.assertEqual(self.retain_at(log, NOW), 2)
        self.assertEqual([(r[0], r[2]) for r in rows(self.store)],
                         [(2, event_log.SIGNIN_READING), (3, event_log.SIGNIN_READING)])
        self.assertEqual(self.retain_at(log, NOW), 0)

    def test_a_pass_keeps_the_newest_signed_in_reading_of_each_profile(self):
        log = self.open()
        self.now = OLD
        reading = lambda profile, state: (event_log.SIGNIN_READING, None, {
            "profile": profile, "state": state, "ends_at": None})
        log.append([reading("a", "signed_in")])
        log.append([reading("a", "signed_in")])
        log.append([reading("a", "signed_out")])
        log.append([reading("b", "signed_out")])
        log.append([("old", None, {})])
        removed = self.retain_at(log, NOW)
        self.assertEqual(removed, 2)
        self.assertEqual([(r[0], r[2]) for r in rows(self.store)],
                         [(2, event_log.SIGNIN_READING), (3, event_log.SIGNIN_READING),
                          (4, event_log.SIGNIN_READING)])
        self.assertIs(signin.signin_state(log.events())["a"].ever, True)
        self.assertEqual(self.retain_at(log, NOW), 0)

    def test_a_pass_keeps_the_newest_exclusion_of_each_profile_while_it_is_in_force(self):
        log = self.open()
        self.now = OLD
        row = lambda payload: (event_log.PROFILE_EXCLUSION, None, payload)
        log.append([row({"profile": "a", "excluded": True})])
        log.append([row({"profile": "a", "excluded": True})])
        log.append([row({"profile": "b", "excluded": True})])
        log.append([row({"profile": "b", "excluded": False})])
        log.append([row({"profile": "c", "excluded": True})])
        log.append([row({"profile": "c", "excluded": 0})])
        log.append([row({"profile": "c"})])
        log.append([("old", None, {})])
        before = exclusion.excluded_profiles(log.events())
        self.assertEqual(before, frozenset({"a", "c"}))
        self.assertEqual(self.retain_at(log, NOW), 6)
        self.assertEqual([(r[0], r[2]) for r in rows(self.store)],
                         [(2, "profile.exclusion"), (5, "profile.exclusion")])
        self.assertEqual(exclusion.excluded_profiles(log.events()), before)
        self.assertEqual(self.retain_at(log, NOW), 0)

    def test_a_pass_keeps_the_assignment_in_force_of_a_session_with_a_hook_in_the_window(self):
        log = self.open()
        seen = lambda sid, profile: (event_log.SESSION_SEEN, None, {
            "session_id": sid, "profile": profile})
        hook = lambda sid: (event_log.SESSION_HOOK, None, {"session_id": sid})
        self.now = OLD
        log.append([seen("s-1", "a"), seen("s-2", "a"), seen("s-3", "a"), hook("s-1"),
                    hook("s-3")])
        log.append([(event_log.SESSION_PROFILE, None, {"session_id": "s-1", "profile": "b"})])
        self.now = EDGE
        log.append([hook("s-2")])
        self.now = NEW
        log.append([hook("s-1")])
        self.assertEqual(self.retain_at(log, NOW), 4)
        self.assertEqual(
            [(r[0], r[2]) for r in rows(self.store)],
            [(2, event_log.SESSION_SEEN), (6, event_log.SESSION_PROFILE),
             (7, event_log.SESSION_HOOK), (8, event_log.SESSION_HOOK)])
        self.assertEqual(self.retain_at(log, NOW), 0)


if __name__ == "__main__":
    unittest.main()
