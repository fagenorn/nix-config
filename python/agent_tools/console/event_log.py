"""The console's event log (ADR-console-001, ADR-console-009).

The store is one SQLite file. Its table is `events(seq INTEGER PRIMARY KEY
AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL, project TEXT, payload TEXT
NOT NULL)`. Triggers refuse every `UPDATE` of `events`, every `INSERT` that
names an existing `seq` (which `INSERT OR REPLACE` would otherwise carry out
without firing a delete trigger) and every deletion of a goal row, a brief row, a
report row, a message row, a question row or a closing row (`KEPT_KINDS`, kept indefinitely per #838, #887, #890, #889, #891 and #892), whatever
its age, or of a row that is not older than the retention cutoff, with "the
console event log is append-only", so a raw connection cannot rewrite history
either. The cutoff is the one row of
`retention(id, cutoff)`: it starts empty, triggers let it only move forward and
refuse to delete, replace or duplicate that row, and `at` is compared as text,
which is valid for the `utc_now` format. This module issues no `UPDATE` except
the cutoff's, no `REPLACE`, no `INSERT OR ...`, and deletes only in
`EventLog.retain` and `EventLog.delete_question_thread`.

`EventLog.retain` is the 90-day retention pass: in one transaction it moves the
cutoff to the clock minus `RETENTION` and removes the rows older than it except
those of `KEPT_KINDS`, and returns how many. Sequence numbers are never reused.

Three kinds record what the owner says to a sprint and what comes of it (#889): `SPRINT_MESSAGED`
(`sprint.messaged`), `SPRINT_READ` (`sprint.read`) and `SPRINT_ANSWERED` (`sprint.answered`) are in
`KEPT_KINDS`; `SPRINT_NUDGED` (`sprint.nudged`, the record of an attempt to reach the manager) is
not, and retention removes it like any other row.

A guest's goal, approval, reply, message and answer rows carry `by`, the guest's normal login
(#1263); an owner's row carries none.

Two kinds record a manager's questions and the owner's answers (#891): `QUESTIONS_ASKED`
(`questions.asked`) and `QUESTION_ANSWERED` (`question.answered`), both in `KEPT_KINDS`.
`QUESTION_WITHDRAWN` (`question.withdrawn`, #1099, kept) records a manager taking back an
open question.

One kind records what the console did about a look card's approval (#1260): `LOOK_RECORDED`
(`look.recorded`, kept, payload `sprint_id`, `round`, `index` and `outcome`, `moved`, `posted` or
`failed`, with the head it found, the comment it posted or the reason it could not), so a restart
never loses a posted approval or reopens a held answer.

Two kinds record a manager's notices (#1117): `NOTICE_POSTED` (`notice.posted`) and
`NOTICE_WITHDRAWN` (`notice.withdrawn`), both in `KEPT_KINDS`, so the retention pass never drops
an open notice and a withdrawal is never lost (ADR-console-044). `NOTICE_NUDGED` (`notice.nudged`,
#1120) records the one nudge an owner's notice cost a manager; it is not kept; the sprint fold reads only its `permission` member (ADR-console-060).

Two kinds record a manager's live faults (#1432): `FAULT_DECLARED` (`fault.declared`) and
`FAULT_WITHDRAWN` (`fault.withdrawn`), both in `KEPT_KINDS` like the notice rows, so the retention
pass never drops an open declaration and a withdrawal is never lost (ADR-console-099).

Three more kinds are kept (#892): `SPRINT_CLOSED` (`sprint.closed`), `SPRINT_STOP_REQUESTED`
(`sprint.stop_requested`) and `MANAGER_STOPPED` (`manager.stopped`). `manager.stopped` is kept
because it alone ends a stop and a withdrawal's pending stop, and retention runs before the fold at
construction, so a restart must never reopen a finished stop. `MANAGER_STOP_FAILED`
(`manager.stop_failed`, one failed attempt) is not kept: it is an observation like the other manager
rows and retention removes it.

Three kinds record a sprint's manager (#888): `MANAGER_STARTED` (`manager.started`), `MANAGER_FAILED`
(`manager.failed`) and `MANAGER_WAITING` (`manager.waiting`), each with the project in its project
column. They are not in `KEPT_KINDS`: retention removes them like any other row, and a sprint whose
manager rows are gone reads as having none.

Two kinds record a question about a project and its answer (#1176): `PROJECT_QUESTION_ASKED`
(`project_question.asked`, payload `question_id`, `question`, `profile`, `session_id`, and for a
follow-up the `thread_id` it was given (#1178), the project in its project column) and `PROJECT_QUESTION_ANSWERED` (`project_question.answered`, payload `question_id`,
`outcome` and either `answer` or `reason`). Neither is in `KEPT_KINDS`, retention removes them like
any other row; the spend fold reads the asked row's `session_id` and `profile`
(`spend.question_sessions`), and `project_question.asked_questions` folds both into the desk
view's questions (#1177).

`PROJECT_QUESTION_DELETED` (`project_question.deleted`, #1272, project in its project column, payload
`question_ids`, the ids of the deleted thread's questions in the order given, and `thread_id`) is the
text-free record that the owner deleted a question thread, and is in `KEPT_KINDS`.
`EventLog.delete_question_thread` writes it and removes, in one transaction, the asked and answered
rows of that project whose `question_id` it names. Schema 12 gives the delete trigger exactly one
exception to its two refusals: a row of the asked or answered kind whose `question_id` is a string may
be deleted when a deletion record with a larger sequence number, whose project is a string equal to the
row's project and whose `question_ids` is a JSON array, holds that id as a string member; a record
the fold ignores authorizes no delete, so a raw connection still cannot delete any other question
row. A keyed question's receipt (`PROJECT_QUESTION_KEYED`) names only ids and is not removed by a
deletion. The connection runs `PRAGMA secure_delete = ON`, so the
freed pages of a deleted question or answer are zeroed instead of keeping its text.

One kind is kept whole (#1271): `PROJECT_QUESTION_KEYED` (`project_question.keyed`, payload `request_key`
and `question_id`, the project in its project column) is the receipt of a question asked under a request
key, appended in the same transaction as its asked row (ADR-console-089 D9). It is not in `KEPT_KINDS`, but the
retention pass never removes it, whatever its age, so a key the console has asked still finds its question
after the asked row is gone and a retry of that key starts no second session. The question's own rows go
at 90 days as before; the receipt is two short strings.

Two kinds are kept in part for the ownership of a path (#1271): `PROJECT_REGISTERED` (`project.registered`,
payload `root`) and `PROJECT_UNREGISTERED` (`project.unregistered`) are not in `KEPT_KINDS`, but the retention pass
never removes a registered row, and removes an unregistered row only when no earlier registered row of its
project remains. The activation rows above are kept past the window and name a root, not a project, so the
registrations that say who held the root when one was written must outlive it too (ADR-console-089 D3);
one pair of short rows per registration is all that is kept.

Three more rows record an idle manager's nudges (#929): `MANAGER_NUDGED` (`manager.nudged`, one
nudge to a manager session that sat idle), `MANAGER_NO_PROGRESS` (`manager.no_progress`, the
console's give-up that opens an item for the owner) and `SPRINT_CONTINUED` (`sprint.continued`, the
owner's answer to it). Like the other manager rows they are not in `KEPT_KINDS`.

Two kinds are kept in part (#1193): `ACTIVATION_STARTED` (`activation.started`) and
`ACTIVATION_FINISHED` (`activation.finished`) are not in `KEPT_KINDS`, but the retention pass leaves
the newest row of each kind in place whatever its age, because the console folds them into the last
activation's state at construction and a failed activation must still show its reason and next step
while its commit stays pending (ADR-system-004 D9).

Two rows record a manager's permit (#1377, ADR-console-094): `PERMIT_JUDGED` (`permit.judged`, one per
decided verdict on a merge or rerun command: payload `sprint_id`, `session_id`, `repo` (the
project's slug, null when unknown), `verb`, `decision`, `reason` and `target`) and `PERMIT_LANDED`
(`permit.landed`, one per merge the manager's session ran after the console allowed it: `sprint_id`,
`session_id`, `repo`, `verb` `merge` and `target` `{"pr", "head"}`). Neither is in `KEPT_KINDS`, so
retention removes them like any other row, and no fold reads them.

Two rows record a release card outside any sprint (#1401): `RELEASE_CARD_POSTED` (`release_card.posted`)
carries payload `commit`, `version`, with a null project column, and `RELEASE_CARD_ANSWERED`
(`release_card.answered`) carries payload `card` (the posted row's `seq`) and `answer` (`approve` or
`decline`); an owner's row carries no `by`. Neither is in `KEPT_KINDS`: retention removes them like any
other row, and the reader ignores rows outside the window.

Three rows record a manager's held Bash permission prompt and its end (#1424): `PROMPT_ASKED`
(`prompt.asked`, payload `sprint_id`, `session_id`, `command` and optionally `description`, under the
sprint's project), `PROMPT_ANSWERED` (`prompt.answered`, payload `prompt`, the asked row's `seq`, and
`answer`, `allow` or `refuse`) and `PROMPT_CLOSED` (`prompt.closed`, payload `prompt` and `reason`,
`expired` or `ended`). None is in `KEPT_KINDS`: retention removes them like any other row.

One kind is kept in part (#1010): `SIGNIN_READING` (`signin.reading`) is not in `KEPT_KINDS`, but the
retention pass leaves the newest row of each profile (by sequence number, the profile being the
payload's `profile`) in place whatever its age, and also the newest row of each profile whose
`state` is `signed_in`, because the console records a sign-in only when it changes: a profile
signed out for longer than the window would otherwise read as never read, and one signed out after
signing in as never signed in.

One kind is kept while in force (#1028): `PROFILE_EXCLUSION` (`profile.exclusion`) is not in
`KEPT_KINDS`, but the retention pass leaves, whatever its age, the newest valid row of each profile
when that row's `excluded` is JSON `true`, and removes every other old row of the kind. A row is
valid when its `profile` is a non-empty JSON string and its `excluded` a JSON boolean (an integer
is not one), the rule `exclusion.excluded_profiles` folds by, so a newer invalid row never displaces
the row in force and the folded set is the same before and after a pass.

One kind is kept while in force (#1029): `PROFILE_PIN` (`profile.pin`) is not in `KEPT_KINDS`, but
the retention pass leaves, whatever its age, the one row whose `pinned` is JSON `true`, whose
`profile` is a non-empty JSON string and whose sequence number is the largest among such rows, when
no row of the kind with a larger sequence number has `pinned` JSON `false` and the same `profile`,
and removes every other old row of the kind. That is the rule `pin.pinned_profile` folds by, so the
folded pin is the same before and after a pass.

Two more rows record the owner's sign-in from the page (#1026): `SIGNIN_ACTED` (`signin.acted`, one per
accepted owner action) and `SIGNIN_ENDED` (`signin.ended`, one per finished client). Neither is in
`KEPT_KINDS`, and neither carries a link or a code.

Two kinds record an adoption the owner approved on the page (#1054): `ADOPTION_STEP`
(`adoption.step`) and `ADOPTION_PULL` (`adoption.pull_request`); neither is in `KEPT_KINDS`.
`ADOPTION_DEFERRED` (`adoption.deferred`, #1073, `{"plan_id"}`, one per `Not now` the owner chooses
on an apply card) is not in `KEPT_KINDS` either.

`REGISTRATION_CANCELLED` (`registration.cancelled`, #1088, `{"by": "owner", "root", "plan_id"}`, one per
Cancel registration the owner chooses, plus one per other failed apply of the same root) is not in `KEPT_KINDS`; the registration, deferral, adoption and
folder-trust folds each drop what it names. `cancelled_registration(event)` reads it: `(root, plan_id)`
for exactly that payload, or exactly it plus `"restore": true` (#1334; `plan_id` null for a registration
with none, a failed plan), else None.

`ACCOUNT_ADDED` (`account.added`, one per account the owner or a listed colleague adds from the page,
#1027, #1343) is not in `KEPT_KINDS` but is kept in part: the retention pass leaves, whatever its age,
the `account.added` row whose `by` is a login (a JSON string other than `owner` with `normal_login(by) == by`), whose
seq is the largest of the `account.added` rows of the same `profile` whose `by` the owner fold reads
(`owner` or a login with `normal_login(by) == by`; a row with any other `by` is ignored by the fold and
by this rule alike), and after which no
`account.removal` row of that profile has an outcome in `ACCOUNT_GONE_OUTCOMES` (`removed`,
`removed_signed_out_already`: the same two as `folder_trust.GONE_OUTCOMES`, which this module cannot
import). A colleague's account must stay his after the window and end only with a completed removal,
so the owner fold after a retention pass equals the fold before it; an owner-added row, an
older row of a re-added profile and a row a completed removal ended all age out as before, and a
failed removal leaves the row kept. `ACCOUNT_REMOVAL` (`account.removal`, one per removal the owner or the colleague who added the profile confirms,
#1030, #1345) is not in `KEPT_KINDS`.
`TRUST_GRANTED` (`trust.granted`, one per folder-trust grant the owner approved or per registered project at the console's start, #1078, `folder_trust.granted_row`)
is not in `KEPT_KINDS`.
`PICTURE_STORED` (`picture.stored`, one per picture a manager sent that the console accepted, #1089)
is not in `KEPT_KINDS`.

Three kinds are kept in part (#1129): `INBOX_SEEN` (`inbox.seen`), `INBOX_CHANGED` (`inbox.changed`)
and `INBOX_GONE` (`inbox.gone`) are not in `KEPT_KINDS`, but the retention pass leaves, whatever its
age, the newest row of each inbox item (the project and the payload's `key`) when that row is a
`seen` or `changed` row whose payload carries a `wait` object (an owner check that is not due) and no
`project.unregistered` row of its project is newer. An idle project is polled only while it holds
such a wait, and an unchanged wait appends no row, so removing the row would end the polling and the
waiting line with it, and the check would never become a card once its time came. A gone row, a
superseded row and every other inbox row go like any other.

Another is kept in part (#1011): a session's profile is assigned by its `SESSION_SEEN` and
`SESSION_PROFILE` rows, and a profile's last use is read from the session's later `SESSION_HOOK` rows
(`manager.profile_use`). The pass therefore leaves, for a session with a `SESSION_HOOK` row inside the
window, the newest of its assignment rows older than the cutoff (the assignment in force when the
window opens), so retained hooks keep their profile; once no hook of the session is inside the window
that row is removed like any other.

Three kinds record the access list the owner keeps for the guest door (#1237): `SHARING_TAILNET`
(`sharing.tailnet`, `{"shared"}`; a legacy `{"tailnet"}` row still folds to on), `SHARING_COLLEAGUE` (`sharing.colleague`, `{"login", "projects"}`)
and `SHARING_REMOVED` (`sharing.removed`, `{"login"}`). None is in `KEPT_KINDS`, but the retention
pass leaves, whatever its age, the newest tailnet row and, for each login, the newest colleague or
removed row when it is a colleague row, the rows `guest.access_list` folds by, so the folded list is
the same before and after a pass.

`EventLog.append` writes all its entries in one transaction under one `at`
taken from the clock: a failure writes no row, rolls back the earlier entries of
the same call and leaves the connection usable. An empty sequence returns `[]`
and writes nothing. A payload is stored as canonical JSON (sorted keys, compact
separators, non-ASCII kept, NaN refused), serialised before the transaction
begins.

`PRAGMA user_version` is `SCHEMA_VERSION` (13) once opened: version 0 is created
as schema 13, versions 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11 and 12 are migrated to 13 in one transaction each and
keep every row, and a file at any other version raises `EventLogError` and is not
modified. The parent directory is created with mode 0700. The connection
is shared across threads and every use of it holds one lock.
"""

import json
import re
import sqlite3
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = 13
LOGIN_MAX = 254
_LOGIN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+")
RETENTION = timedelta(days=90)

GOAL_STATED = "goal.stated"
GOAL_WITHDRAWN = "goal.withdrawn"
BRIEF_SENT = "brief.sent"
BRIEF_APPROVED = "brief.approved"
BRIEF_REPLIED = "brief.replied"
MANAGER_STARTED = "manager.started"
MANAGER_FAILED = "manager.failed"
MANAGER_WAITING = "manager.waiting"
MANAGER_WOKEN = "manager.woken"
MANAGER_STALLED = "manager.stalled"
MANAGER_NUDGED = "manager.nudged"
MANAGER_NO_PROGRESS = "manager.no_progress"
SPRINT_CONTINUED = "sprint.continued"
SPRINT_REPORTED = "sprint.reported"
SPRINT_MESSAGED = "sprint.messaged"
SPRINT_READ = "sprint.read"
SPRINT_ANSWERED = "sprint.answered"
SPRINT_NUDGED = "sprint.nudged"
QUESTIONS_ASKED = "questions.asked"
QUESTION_ANSWERED = "question.answered"
QUESTION_WITHDRAWN = "question.withdrawn"
LOOK_RECORDED = "look.recorded"
NOTICE_POSTED = "notice.posted"
NOTICE_WITHDRAWN = "notice.withdrawn"
NOTICE_NUDGED = "notice.nudged"
FAULT_DECLARED = "fault.declared"
FAULT_WITHDRAWN = "fault.withdrawn"
PROJECT_QUESTION_ASKED = "project_question.asked"
PROJECT_QUESTION_KEYED = "project_question.keyed"
PROJECT_QUESTION_ANSWERED = "project_question.answered"
PROJECT_QUESTION_DELETED = "project_question.deleted"
SPRINT_CLOSED = "sprint.closed"
SPRINT_STOP_REQUESTED = "sprint.stop_requested"
MANAGER_STOPPED = "manager.stopped"
MANAGER_STOP_FAILED = "manager.stop_failed"
SIGNIN_READING = "signin.reading"
PROFILE_EXCLUSION = "profile.exclusion"
PROFILE_PIN = "profile.pin"
SIGNIN_ACTED = "signin.acted"
SIGNIN_ENDED = "signin.ended"
ACCOUNT_ADDED = "account.added"
ACCOUNT_REMOVAL = "account.removal"
ACCOUNT_GONE_OUTCOMES = ("removed", "removed_signed_out_already")
TRUST_GRANTED = "trust.granted"
REGISTRATION_ENDED = "registration.ended"
ADOPTION_STEP = "adoption.step"
ADOPTION_PULL = "adoption.pull_request"
ADOPTION_REGISTRATION = "adoption.registration"
ADOPTION_DEFERRED = "adoption.deferred"
REGISTRATION_CANCELLED = "registration.cancelled"
INBOX_SEEN = "inbox.seen"
INBOX_CHANGED = "inbox.changed"
INBOX_GONE = "inbox.gone"
PROJECT_REGISTERED = "project.registered"
PROJECT_UNREGISTERED = "project.unregistered"
SESSION_HOOK = "session.hook"
SESSION_SEEN = "session.seen"
SESSION_PROFILE = "session.profile"
PICTURE_STORED = "picture.stored"
ACTIVATION_STARTED = "activation.started"
ACTIVATION_FINISHED = "activation.finished"
PERMIT_JUDGED = "permit.judged"
PERMIT_LANDED = "permit.landed"
RELEASE_CARD_POSTED = "release_card.posted"
RELEASE_CARD_ANSWERED = "release_card.answered"
PROMPT_ASKED = "prompt.asked"
PROMPT_ANSWERED = "prompt.answered"
PROMPT_CLOSED = "prompt.closed"
SHARING_TAILNET = "sharing.tailnet"
SHARING_COLLEAGUE = "sharing.colleague"
SHARING_REMOVED = "sharing.removed"
# Rows of these kinds (the two goal kinds, the three brief kinds, the report
# Rows of these kinds (the two goal kinds, the three brief kinds, the report
# kind, the three message kinds, the three question kinds, the look record, the two notice kinds,
# the closing kind, the stop request and the stop's completion, and the record of a deleted
# question thread, and the two live-fault kinds) are never removed: not by the retention pass, not
# by a raw connection (the delete trigger of schema 3, 4, 5, 6, 7, 8, 9, 10, 11, 12 and 13).
# `SPRINT_NUDGED` and `MANAGER_STOP_FAILED` are not among them, nor is any manager kind other
# than `MANAGER_STOPPED` (`MANAGER_STARTED`, `MANAGER_FAILED`, `MANAGER_WAITING`,
# `MANAGER_WOKEN`, `MANAGER_STALLED`, `MANAGER_NUDGED`, `MANAGER_NO_PROGRESS`), nor is
# `SPRINT_CONTINUED`.
KEPT_KINDS = frozenset({GOAL_STATED, GOAL_WITHDRAWN,
                        BRIEF_SENT, BRIEF_APPROVED, BRIEF_REPLIED,
                        SPRINT_REPORTED,
                        SPRINT_MESSAGED, SPRINT_READ, SPRINT_ANSWERED,
                        QUESTIONS_ASKED, QUESTION_ANSWERED, QUESTION_WITHDRAWN, LOOK_RECORDED,
                        NOTICE_POSTED, NOTICE_WITHDRAWN,
                        SPRINT_CLOSED, SPRINT_STOP_REQUESTED, MANAGER_STOPPED,
                        PROJECT_QUESTION_DELETED,
                        FAULT_DECLARED, FAULT_WITHDRAWN})

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

# What schemas 3, 4, 5, 6, 7, 8, 9, 10, 11, 12 and 13 add to schema 2: the delete trigger also refuses
# every row of a kept kind, whatever its age. Built from KEPT_KINDS so a later kept kind
# needs no hand-edited SQL, only a re-run on an existing store (schema 4 added the
# brief kinds, schema 5 the report kind, schema 6 the message kinds, schema 7 the closing kinds
# and the stop's completion, schema 8 the question kinds, schema 9 the question withdrawal,
# schema 10 the notice kinds, schema 11 the look record, schema 12 the deletion record and one exception:
# an asked or answered question row is deletable when a later deletion record of its project names it,
# schema 13 the two live-fault kinds).
_KEPT_LITERALS = ", ".join("'" + kind.replace("'", "''") + "'"
                           for kind in sorted(KEPT_KINDS))
_QUESTION_NAMED = f"""OLD.kind IN ('{PROJECT_QUESTION_ASKED}', '{PROJECT_QUESTION_ANSWERED}')
            AND EXISTS (SELECT 1 FROM events AS deleted,
                    json_each(deleted.payload, '$.question_ids') AS named
                WHERE deleted.kind = '{PROJECT_QUESTION_DELETED}'
                    AND json_type(OLD.payload, '$.question_id') = 'text'
                    AND typeof(deleted.project) = 'text'
                    AND deleted.project = OLD.project
                    AND json_type(deleted.payload, '$.question_ids') = 'array'
                    AND named.type = 'text'
                    AND deleted.seq > OLD.seq
                    AND named.value = json_extract(OLD.payload, '$.question_id'))"""
_KEPT = (
    "DROP TRIGGER events_no_delete",
    f"""CREATE TRIGGER events_no_delete BEFORE DELETE ON events
        WHEN NOT ({_QUESTION_NAMED})
            AND (OLD.kind IN ({_KEPT_LITERALS})
                OR NOT (OLD.at < coalesce((SELECT cutoff FROM retention WHERE id = 1), '')))
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


def cancelled_registration(event: Event) -> tuple[str, str] | None:
    """`(root, plan_id)` of a `REGISTRATION_CANCELLED` row with exactly the owner's payload, else None.

    The payload may also carry `"restore": true` (a restoring Cancel, #1334) and no other member.

    The plan id is a non-empty string, or JSON null for a registration that has none (a failed plan).
    """
    payload = event.payload
    if event.kind != REGISTRATION_CANCELLED or not isinstance(payload, Mapping):
        return None
    root, plan_id = payload.get("root"), payload.get("plan_id")
    owner = {"by": "owner", "root": root, "plan_id": plan_id}
    if (payload not in (owner, {**owner, "restore": True})
            or payload.get("restore", True) is not True
            or not isinstance(root, str) or not root
            or not (plan_id is None or (isinstance(plan_id, str) and plan_id))):
        return None
    return (root, plan_id)


def normal_login(text: object) -> str | None:
    if (not isinstance(text, str) or len(text) > LOGIN_MAX or not text.isascii()
            or _LOGIN.fullmatch(text) is None):
        return None
    return text.lower()


def _valid_added_by(by: object) -> int:
    """1 for the `by` of an `account.added` row the owner fold reads: `owner` or a normalised login."""
    return int(isinstance(by, str) and (by == "owner" or normal_login(by) == by))


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
        self._connection.create_function("valid_added_by", 1, _valid_added_by, deterministic=True)
        try:
            self._connection.execute("PRAGMA secure_delete = ON")
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
        elif version in (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12):
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

    def delete_question_thread(self, project: str, thread_id: str,
                               question_ids: Sequence[str]) -> Event:
        """Record that a question thread was deleted and remove its question rows, in one transaction; return the record.

        The record is a row of `PROJECT_QUESTION_DELETED` holding only the ids; the asked and
        answered rows of `project` that name one of `question_ids` are then removed, and a
        failure of either rolls both back. Anything but non-empty strings and a non-empty
        sequence of distinct non-empty ids raises `ValueError` and writes nothing.
        """
        ids = list(question_ids)
        if (not isinstance(project, str) or not project
                or not isinstance(thread_id, str) or not thread_id
                or not ids or len(set(ids)) != len(ids)
                or any(not isinstance(one, str) or not one for one in ids)):
            raise ValueError("a deleted thread needs a project, a thread id and distinct question ids")
        payload = {"question_ids": ids, "thread_id": thread_id}
        text = _encode(payload)
        with self._lock:
            at = self._clock()

            def remove() -> Event:
                cursor = self._connection.execute(
                    "INSERT INTO events (at, kind, project, payload) VALUES (?, ?, ?, ?)",
                    (at, PROJECT_QUESTION_DELETED, project, text))
                self._connection.execute(
                    "DELETE FROM events WHERE project = ? AND kind IN (?, ?) "
                    "AND json_extract(payload, '$.question_id') IN (%s)"
                    % ", ".join("?" * len(ids)),
                    (project, PROJECT_QUESTION_ASKED, PROJECT_QUESTION_ANSWERED, *ids))
                return Event(cursor.lastrowid, at, PROJECT_QUESTION_DELETED, project,
                             json.loads(text))

            return self._transaction(remove)

    def retain(self) -> int:
        """Remove the rows older than the retention window, keeping each profile's newest sign-in reading, exclusion in force and the pin in force, and the newest activation started and finished rows, and the access list in force, and every question key receipt, and the registry rows that say who owned a root; return how many."""
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
                    f"DELETE FROM events WHERE at < ? AND kind NOT IN ({marks}) "
                    "AND NOT (kind = ? AND seq = (SELECT MAX(newer.seq) FROM events AS newer "
                    "WHERE newer.kind = events.kind AND json_extract(newer.payload, '$.profile') "
                    "IS json_extract(events.payload, '$.profile'))) "
                    "AND NOT (kind = ? AND json_extract(events.payload, '$.state') = 'signed_in' "
                    "AND seq = (SELECT MAX(newer.seq) FROM events AS newer "
                    "WHERE newer.kind = events.kind "
                    "AND json_extract(newer.payload, '$.state') = 'signed_in' "
                    "AND json_extract(newer.payload, '$.profile') "
                    "IS json_extract(events.payload, '$.profile'))) "
                    "AND NOT (kind = ? AND json_type(events.payload, '$.excluded') = 'true' "
                    "AND json_type(events.payload, '$.profile') = 'text' "
                    "AND json_extract(events.payload, '$.profile') <> '' "
                    "AND seq = (SELECT MAX(newer.seq) FROM events AS newer "
                    "WHERE newer.kind = events.kind "
                    "AND json_type(newer.payload, '$.profile') = 'text' "
                    "AND json_type(newer.payload, '$.excluded') IN ('true', 'false') "
                    "AND json_extract(newer.payload, '$.profile') = "
                    "json_extract(events.payload, '$.profile'))) "
                    "AND NOT (kind = ? AND json_type(events.payload, '$.pinned') = 'true' "
                    "AND json_type(events.payload, '$.profile') = 'text' "
                    "AND json_extract(events.payload, '$.profile') <> '' "
                    "AND seq = (SELECT MAX(newer.seq) FROM events AS newer "
                    "WHERE newer.kind = events.kind "
                    "AND json_type(newer.payload, '$.pinned') = 'true' "
                    "AND json_type(newer.payload, '$.profile') = 'text' "
                    "AND json_extract(newer.payload, '$.profile') <> '') "
                    "AND NOT EXISTS (SELECT 1 FROM events AS later "
                    "WHERE later.kind = events.kind AND later.seq > events.seq "
                    "AND json_type(later.payload, '$.pinned') = 'false' "
                    "AND json_extract(later.payload, '$.profile') = "
                    "json_extract(events.payload, '$.profile'))) "
                    "AND NOT (kind IN (?, ?) AND json_type(events.payload, '$.wait') IS 'object' "
                    "AND seq = (SELECT MAX(newer.seq) FROM events AS newer "
                    "WHERE newer.kind IN (?, ?, ?) AND newer.project IS events.project "
                    "AND json_extract(newer.payload, '$.key') IS json_extract(events.payload, '$.key')) "
                    "AND NOT EXISTS (SELECT 1 FROM events AS ended WHERE ended.kind = ? "
                    "AND ended.project IS events.project AND ended.seq > events.seq)) "
                    "AND NOT (kind IN (?, ?) AND seq = (SELECT MAX(owner.seq) FROM events AS owner "
                    "WHERE owner.kind IN (?, ?) AND owner.at < ? AND "
                    "json_extract(owner.payload, '$.session_id') "
                    "IS json_extract(events.payload, '$.session_id')) "
                    "AND EXISTS (SELECT 1 FROM events AS hook WHERE hook.kind = ? "
                    "AND hook.at >= ? AND hook.seq > events.seq AND "
                    "json_extract(hook.payload, '$.session_id') "
                    "IS json_extract(events.payload, '$.session_id'))) "
                    "AND NOT (kind IN (?, ?, ?) AND seq = (SELECT MAX(newer.seq) FROM events AS newer "
                    "WHERE newer.kind = events.kind)) "
                    "AND NOT (kind = ? AND seq = (SELECT MAX(newer.seq) FROM events AS newer "
                    "WHERE newer.kind IN (?, ?) AND "
                    "json_extract(newer.payload, '$.login') IS json_extract(events.payload, '$.login'))) "
                    "AND NOT (kind = ? AND valid_added_by(json_extract(payload, '$.by')) "
                    "AND json_extract(payload, '$.by') != 'owner' "
                    "AND seq = (SELECT MAX(newer.seq) FROM events AS newer WHERE newer.kind = ? "
                    "AND valid_added_by(json_extract(newer.payload, '$.by')) "
                    "AND json_extract(newer.payload, '$.profile') "
                    "IS json_extract(events.payload, '$.profile')) "
                    "AND NOT EXISTS (SELECT 1 FROM events AS gone WHERE gone.kind = ? "
                    "AND gone.seq > events.seq AND json_extract(gone.payload, '$.outcome') IN (?, ?) "
                    "AND json_extract(gone.payload, '$.profile') "
                    "IS json_extract(events.payload, '$.profile'))) "
                    "AND kind NOT IN (?, ?) "
                    "AND NOT (kind = ? AND EXISTS (SELECT 1 FROM events AS began "
                    "WHERE began.kind = ? AND began.project IS events.project "
                    "AND began.seq < events.seq))",
                    (cutoff, *sorted(KEPT_KINDS), SIGNIN_READING, SIGNIN_READING, PROFILE_EXCLUSION,
                     PROFILE_PIN,
                     INBOX_SEEN, INBOX_CHANGED, INBOX_SEEN, INBOX_CHANGED, INBOX_GONE, PROJECT_UNREGISTERED,
                     SESSION_SEEN, SESSION_PROFILE, SESSION_SEEN, SESSION_PROFILE, cutoff,
                     SESSION_HOOK, cutoff, ACTIVATION_STARTED, ACTIVATION_FINISHED, SHARING_TAILNET,
                     SHARING_COLLEAGUE, SHARING_COLLEAGUE, SHARING_REMOVED,
                     ACCOUNT_ADDED, ACCOUNT_ADDED, ACCOUNT_REMOVAL, *ACCOUNT_GONE_OUTCOMES,
                     PROJECT_QUESTION_KEYED, PROJECT_REGISTERED, PROJECT_UNREGISTERED,
                     PROJECT_REGISTERED)).rowcount

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
