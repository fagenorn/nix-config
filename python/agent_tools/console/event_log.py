"""The console's append-only event log (ADR-console-001).

The store is one SQLite file. Its table is `events(seq INTEGER PRIMARY KEY
AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL, project TEXT, payload TEXT
NOT NULL)`, and two triggers, `events_no_update` and `events_no_delete`, abort
every `UPDATE` and `DELETE` with "the console event log is append-only", so a
raw connection cannot rewrite history either. This module never issues
`UPDATE`, `DELETE`, `REPLACE` or `INSERT OR ...`.

`EventLog.append` writes all its entries in one transaction under one `at`
taken from the clock: a failure writes no row, rolls back the earlier entries of
the same call and leaves the connection usable. An empty sequence returns `[]`
and writes nothing. A payload is stored as canonical JSON (sorted keys, compact
separators, non-ASCII kept, NaN refused), serialised before the transaction
begins.

`PRAGMA user_version` is `SCHEMA_VERSION` for a store this module created; a
file whose version is neither 0 nor `SCHEMA_VERSION` raises `EventLogError` and
is not modified. The parent directory is created with mode 0700. The connection
is shared across threads and every use of it holds one lock.
"""

import json
import sqlite3
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

_APPEND_ONLY = "the console event log is append-only"

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        kind TEXT NOT NULL,
        project TEXT,
        payload TEXT NOT NULL)""",
    f"""CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
        BEGIN SELECT RAISE(ABORT, '{_APPEND_ONLY}'); END""",
    f"""CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
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
        if version != 0:
            raise EventLogError(
                f"the console event log has schema version {version}; "
                f"this build reads {SCHEMA_VERSION}")
        self._transaction(self._create_schema)

    def _create_schema(self) -> None:
        for statement in _SCHEMA:
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
