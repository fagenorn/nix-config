"""The console's event log (ADR-console-001, ADR-console-009).

The store is one SQLite file. Its table is `events(seq INTEGER PRIMARY KEY
AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL, project TEXT, payload TEXT
NOT NULL)`. Triggers refuse every `UPDATE` of `events`, every `INSERT` that
names an existing `seq` (which `INSERT OR REPLACE` would otherwise carry out
without firing a delete trigger) and every deletion of a goal row or a brief row
(`KEPT_KINDS`, kept indefinitely per #838 and #887), whatever its age, or of a row that is not older
than the retention cutoff, with "the console event log is append-only", so a
raw connection cannot rewrite history either. The cutoff is the one row of
`retention(id, cutoff)`: it starts empty, triggers let it only move forward and
refuse to delete, replace or duplicate that row, and `at` is compared as text,
which is valid for the `utc_now` format. This module issues no `UPDATE` except
the cutoff's, no `REPLACE`, no `INSERT OR ...`, and deletes only in
`EventLog.retain`.

`EventLog.retain` is the 90-day retention pass: in one transaction it moves the
cutoff to the clock minus `RETENTION` and removes the rows older than it except
those of `KEPT_KINDS`, and returns how many. Sequence numbers are never reused.

Three kinds record a sprint's manager (#888): `MANAGER_STARTED` (`manager.started`), `MANAGER_FAILED`
(`manager.failed`) and `MANAGER_WAITING` (`manager.waiting`), each with the project in its project
column. They are not in `KEPT_KINDS`: retention removes them like any other row, and a sprint whose
manager rows are gone reads as having none.

`EventLog.append` writes all its entries in one transaction under one `at`
taken from the clock: a failure writes no row, rolls back the earlier entries of
the same call and leaves the connection usable. An empty sequence returns `[]`
and writes nothing. A payload is stored as canonical JSON (sorted keys, compact
separators, non-ASCII kept, NaN refused), serialised before the transaction
begins.

`PRAGMA user_version` is `SCHEMA_VERSION` (4) once opened: version 0 is created
as schema 4, versions 1, 2 and 3 are migrated to 4 in one transaction each and
keep every row, and a file at any other version raises `EventLogError` and is not
modified. The parent directory is created with mode 0700. The connection
is shared across threads and every use of it holds one lock.
"""

import json
import sqlite3
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = 4
RETENTION = timedelta(days=90)

GOAL_STATED = "goal.stated"
GOAL_WITHDRAWN = "goal.withdrawn"
BRIEF_SENT = "brief.sent"
BRIEF_APPROVED = "brief.approved"
BRIEF_REPLIED = "brief.replied"
MANAGER_STARTED = "manager.started"
MANAGER_FAILED = "manager.failed"
MANAGER_WAITING = "manager.waiting"
# Rows of these kinds (the two goal kinds and the three brief kinds) are never
# removed: not by the retention pass, not by a raw connection (the delete
# trigger of schema 3 and 4).
KEPT_KINDS = frozenset({GOAL_STATED, GOAL_WITHDRAWN,
                        BRIEF_SENT, BRIEF_APPROVED, BRIEF_REPLIED})

_APPEND_ONLY = "the console event log is append-only"

_RETENTION_ONLY_FORWARD = "the console retention cutoff only moves forward"

_EVENTS = (
    """CREATE TABLE IF NOT EXISTS events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        kind TEXT NOT NULL,
        project TEXT,
        payload TEXT NOT NULL)""",
    f"""CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
        BEGIN SELECT RAISE(ABORT, '{_APPEND_ONLY}'); END""",
    f"""CREATE TRIGGER IF NOT EXISTS events_no_replace BEFORE INSERT ON events
        WHEN EXISTS (SELECT 1 FROM events WHERE seq = NEW.seq)
        BEGIN SELECT RAISE(ABORT, '{_APPEND_ONLY}'); END""",
)

# What schema 2 adds to schema 1: the cutoff and the triggers that guard it.
# A missing cutoff row fails closed (coalesce), so no row is then deletable.
_RETENTION = (
    """CREATE TABLE IF NOT EXISTS retention (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        cutoff TEXT NOT NULL)""",
    "INSERT INTO retention (id, cutoff) VALUES (1, '')",
    f"""CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
        WHEN NOT (OLD.at < coalesce((SELECT cutoff FROM retention WHERE id = 1), ''))
        BEGIN SELECT RAISE(ABORT, '{_APPEND_ONLY}'); END""",
    f"""CREATE TRIGGER IF NOT EXISTS retention_no_delete BEFORE DELETE ON retention
        BEGIN SELECT RAISE(ABORT, '{_RETENTION_ONLY_FORWARD}'); END""",
    f"""CREATE TRIGGER IF NOT EXISTS retention_no_rewind BEFORE UPDATE ON retention
        WHEN NEW.id IS NOT OLD.id OR NEW.cutoff < OLD.cutoff
        BEGIN SELECT RAISE(ABORT, '{_RETENTION_ONLY_FORWARD}'); END""",
    f"""CREATE TRIGGER IF NOT EXISTS retention_one_row BEFORE INSERT ON retention
        WHEN EXISTS (SELECT 1 FROM retention)
        BEGIN SELECT RAISE(ABORT, '{_RETENTION_ONLY_FORWARD}'); END""",
)

# What schemas 3 and 4 add to schema 2: the delete trigger also refuses every row
# of a kept kind, whatever its age. Built from KEPT_KINDS so a later kept kind
# needs no hand-edited SQL, only a re-run on an existing store (schema 4 added the
# brief kinds).
_KEPT_LITERALS = ", ".join("'" + kind.replace("'", "''") + "'"
                           for kind in sorted(KEPT_KINDS))
_KEPT = (
    "DROP TRIGGER events_no_delete",
    f"""CREATE TRIGGER events_no_delete BEFORE DELETE ON events
        WHEN OLD.kind IN ({_KEPT_LITERALS})
            OR NOT (OLD.at < coalesce((SELECT cutoff FROM retention WHERE id = 1), ''))
        BEGIN SELECT RAISE(ABORT, '{_APPEND_ONLY}'); END""",
)


class EventLogError(Exception):
    """The store cannot be used as an event log."""


@dataclass(frozen=True)
class Event:
    seq: int
    at: str
    kind: str
    project: str | None
    payload: dict


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _encode(payload: Mapping) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


class EventLog:
    def __init__(self, path: Path, *, clock: Callable[[], str] = utc_now):
        self._clock = clock
        self._lock = threading.Lock()
        path = Path(path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, isolation_level=None,
                                           check_same_thread=False)
        try:
            self._prepare()
        except BaseException:
            self._connection.close()
            raise

    def _prepare(self) -> None:
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:
            return
        if version == 1:
            self._transaction(self._migrate_from_1)
        elif version in (2, 3):
            self._transaction(self._migrate_from_2)
        elif version == 0:
            self._transaction(self._create_schema)
        else:
            raise EventLogError(
                f"the console event log has schema version {version}; "
                f"this build reads {SCHEMA_VERSION}")

    def _create_schema(self) -> None:
        for statement in _EVENTS + _RETENTION + _KEPT:
            self._connection.execute(statement)
        self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _migrate_from_1(self) -> None:
        self._connection.execute("DROP TRIGGER events_no_delete")
        for statement in _RETENTION:
            self._connection.execute(statement)
        self._migrate_from_2()

    def _migrate_from_2(self) -> None:
        for statement in _KEPT:
            self._connection.execute(statement)
        self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _transaction(self, body: Callable[[], object]):
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            result = body()
            self._connection.execute("COMMIT")
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise
        return result

    def append(self, entries: Sequence[tuple[str, str | None, Mapping]]) -> list[Event]:
        encoded = [(kind, project, _encode(payload)) for kind, project, payload in entries]
        if not encoded:
            return []
        with self._lock:
            at = self._clock()

            def insert() -> list[Event]:
                events = []
                for kind, project, text in encoded:
                    cursor = self._connection.execute(
                        "INSERT INTO events (at, kind, project, payload) VALUES (?, ?, ?, ?)",
                        (at, kind, project, text))
                    events.append(Event(cursor.lastrowid, at, kind, project,
                                        json.loads(text)))
                return events

            return self._transaction(insert)

    def retain(self) -> int:
        """Remove the rows older than the retention window; return how many."""
        with self._lock:
            now = datetime.fromisoformat(self._clock())
            cutoff = (now - RETENTION).astimezone(timezone.utc).isoformat(
                timespec="microseconds")

            def remove() -> int:
                self._connection.execute(
                    "UPDATE retention SET cutoff = ? WHERE id = 1 AND cutoff < ?",
                    (cutoff, cutoff))
                marks = ", ".join("?" * len(KEPT_KINDS))
                return self._connection.execute(
                    f"DELETE FROM events WHERE at < ? AND kind NOT IN ({marks})",
                    (cutoff, *sorted(KEPT_KINDS))).rowcount

            return self._transaction(remove)

    def events(self) -> list[Event]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT seq, at, kind, project, payload FROM events ORDER BY seq"
            ).fetchall()
        return [Event(seq, at, kind, project, json.loads(payload))
                for seq, at, kind, project, payload in rows]

    def close(self) -> None:
        with self._lock:
            self._connection.close()
