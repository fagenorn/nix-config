"""The console's loopback service: the log-derived view and the desk page over HTTP.

The service binds `127.0.0.1` on one port (`DEFAULT_PORT`) and nothing else; no
parameter names a host. `Host` must be `127.0.0.1:<port>` or `localhost:<port>`
for the port actually bound, else the answer is `403` `text/plain`
`loopback only`.

Routes (every response carries `Cache-Control: no-store` and
`X-Content-Type-Options: nosniff`, and every one but the stream `Content-Length`):

    GET /           200 text/html; charset=utf-8, the page, with `Content-Security-Policy: CSP`
    GET /api/state  200 application/json, the encoded view (see `view.py`)
    GET /api/stream 200 text/event-stream; charset=utf-8, the update stream (below)
    POST /api/hooks 204, no body, a Claude Code hook's input (below)
    POST /api/readings 204, no body, the cache proxy's limit reading (below)
    POST /api/looked 204, no body, the page records that the owner looked (below)
    POST /api/answer 204, a JSON body, the page sends the owner's choice (below)
    POST /api/check-answer 204, a JSON body, the page answers one verification prompt (below)
    POST /api/goal  204, a JSON body, the page states a goal (below)
    POST /api/withdraw 204, a JSON body, the page withdraws a goal (below)
    POST /api/approve 204, a JSON body, the page approves a brief (below)
    POST /api/reply 204, a JSON body, the page asks a brief for changes (below)
    POST /api/retry-manager 204, a JSON body, the page starts a sprint's manager again (below)
    POST /api/brief 200 application/json, a manager sends a sprint's brief (below)
    POST /api/report 200 application/json, a manager sends a sprint's report (below)
    GET /api/sprint-status?sprint_id=<id> 200 application/json, what became of a brief (below)
    anything else   404
    other methods   405 with `Allow: GET` (`Allow: POST` on `/api/hooks`, `/api/readings`,
                    `/api/looked`, `/api/answer`, `/api/check-answer`, `/api/goal`, `/api/withdraw`,
                    `/api/approve`, `/api/reply`, `/api/retry-manager`, `/api/brief` and `/api/report`)

Two kinds of write exist. The hook and reading routes append what the proxies and hooks observe:
`POST /api/hooks` appends session observations, `POST /api/readings` the capacity kinds
`capacity.reading` and `capacity.stop` (see `capacity.py`). The hook route's checks run in this
order, each refusal closing the connection: a loopback
`Host` (else 403 as above); no `Origin` header (a browser page sends one: 403
`text/plain` `origin refused`); a `Content-Type` whose media type is
`application/json` (else 415 `json only`); a `Content-Length` that is a
non-negative integer (else 411 `length required`) of at most `MAX_HOOK_BYTES`
(else 413 `too large`, the body unread). Then the body is read, the `204` is
written and flushed, and only then is the hook ingested (`ingest_hook`): the
session that sent it never waits for the log. The hook's time is taken from the
service clock before the `204`, not when the log row is written, so a session
that updates its registry record after the answer is newer than the hook. A body that is not UTF-8 JSON
is one stderr line `console: hook_unreadable <message>`; any other failure is
`console: hook_failed <Type>: <message>`; the handler never raises. An
ignored payload (an unknown event, a missing member) appends nothing. The
route carries no token: it records observations and answers nothing (ADR-console-004).

A page write (`PAGE_WRITES`, today `POST /api/looked`, `POST /api/answer`, `POST /api/check-answer`,
`POST /api/goal`, `POST /api/withdraw`, `POST /api/approve`, `POST /api/reply` and
`POST /api/retry-manager`; ADR-console-008, ADR-console-010, ADR-console-011, ADR-console-013) is made by the desk page
alone and goes through one guard, `_page_write`, whatever its route. After the loopback `Host`
check and before any body is read, exactly one `Origin` header must equal `http://<Host>` (else
403 `text/plain` `origin refused`) and exactly one `X-Console-Token` header must equal the
install's token (else 403 `token refused`; see `write_guard.py`), each refusal closing the
connection and appending nothing. The body rule is per route. `POST /api/looked` carries no body: a
`Content-Length` other than absent or `0`, or any `Transfer-Encoding`, is 400 `no body`; it then
appends one `page.looked` event (`record_look`) and answers an empty `204`. `POST /api/answer`
carries one JSON body, and after the guard these checks run in order, each refusal `text/plain`, one
line, closing the connection, appending nothing and ticking nothing: any `Transfer-Encoding` is 411
`length required`; a `Content-Type` whose media type is not `application/json` is 415 `json only`;
a `Content-Length` that is not ASCII digits is 411 `length required`, one above `MAX_ANSWER_BYTES`
(4096) is 413 `too large` (the body unread); a body `answer.parse_request` does not accept is 400
`bad answer`. Then `answer(project_id, key, choices)` runs, and each failure writes one stderr
line before it is translated: `answer.Refused` is `console: answer_refused <project_id> <key>
<reason>` and 409 with the reason; a `ForgeError` is `console: answer_tick_failed <project_id> <key>
<code>: <detail>` (whitespace runs collapsed to one space; the detail is what `gh` wrote to stderr)
and 502 `the tracker refused the tick: <error>`; any other exception is `console: answer_failed
<Type>: <message>` and 500 `answer failed`. `POST /api/check-answer` (#863) runs the same body checks in the same order, with
`answer.parse_check_request` as the parser, and calls `answer_check(project_id, key, answer, version,
note, confirm)`; an `answer.Refused` or a `verify_answer.Refused` is the same stderr line and 409, and a
`ForgeError` and any other exception are mapped as above. Success is an empty `204`. No refusal
appends to the event log. `POST /api/goal` and `POST /api/withdraw` carry one JSON body each and run the same
checks, in the same order and with the same statuses and texts as the answer route (one helper
serves the three), with the limits `MAX_GOAL_BYTES` (16384) and `MAX_WITHDRAW_BYTES` (4096). A body
`sprints.parse_goal` does not accept is 400 `bad goal`; `sprints.Refused` is one stderr line
`console: goal_refused <reason>` and 409 with the reason; any other exception is `console:
goal_failed <Type>: <message>` and 500 `goal failed`; success is an empty `204`. The withdraw route
is the same with `bad withdraw`, `console: withdraw_refused <reason>`, `console: withdraw_failed
<Type>: <message>` and 500 `withdraw failed`. No refusal appends a row, publishes or creates a
secret file. `POST /api/approve` and `POST /api/reply` run the same checks again (one helper), with
the limits `MAX_APPROVE_BYTES` (4096) and `MAX_REPLY_BYTES` (16384): a body `sprints.parse_approve`
or `sprints.parse_reply` does not accept is 400 `bad approve` or `bad reply`; `sprints.Refused` is
one stderr line `console: approve_refused <reason>` or `console: reply_refused <reason>` and 409
with the reason; any other exception is `console: approve_failed <Type>: <message>` or
`console: reply_failed <Type>: <message>` and 500 `approve failed` or `reply failed`; success is an
empty `204`. `POST /api/retry-manager` (#888) runs the same checks once more with `MAX_RETRY_BYTES`
(4096) and `sprints.parse_retry`: 400 `bad retry`, `sprints.Refused` is one stderr line `console:
retry_refused <reason>` and 409 with the reason, any other exception is `console: retry_failed
<Type>: <message>` and 500 `retry failed`; success is an empty `204`. The token is created once in
`page-token` beside the event log and reaches a client only inside `GET /`, where it replaces
the slot in the page's `console-token` meta tag.

`POST /api/readings` runs the same checks in the same order (loopback `Host`, no `Origin`,
`application/json`, a length, at most `MAX_READING_BYTES`), answers `204` and flushes, and only
then ingests (`ingest_reading`): `capacity.parse_report` keeps the whitelisted members of the body
(a body that is not UTF-8 JSON or not a report is one stderr line `console: reading_unreadable
<message>`; any other failure `console: reading_failed <Type>: <message>`; the handler never
raises). The reading's profile is the `profile` of the session the report names when the registry
placed that session under a profile, else the profile its account was last attributed to (the folded
`(account, profile)` pairs of earlier readings), else the reading is dropped with one stderr line
`console: reading_unattributed` and no identifier. No credential file is opened and no subprocess
started to learn a profile. The attributed reading is appended with its `capacity.stop` when it was
a refusal, and published. Every poll of the session registry also lists the profile directories
(`profile_dirs()`, `default_profile_dirs()`: `$HOME/.claude` and each directory of `profiles/` under
`$CLAUDE_ACCOUNTS_DIR`, else `$HOME/.claude-accounts`; only `is_dir` touches one) so a profile never
used reads `unknown` and a removed one is no longer listed, and ends by publishing, so a reset that has passed shows within one poll.

The manager's route, `POST /api/brief`, is not a page write: it carries no token and the sprint's
secret takes the token's place. After the loopback `Host` check it runs the hook route's body checks
(`_checked_length(MAX_BRIEF_BYTES)`, 32768: any `Origin` is 403 `origin refused`, a media type that
is not `application/json` 415 `json only`, a length that is not ASCII digits 411 `length required`,
one over the limit 413 `too large`, the body unread), reads the body and runs
`sprints.parse_brief_request` (a body it does not accept is 400 `bad brief`), then `send_brief`. A
`sprints.SecretRefused` is one stderr line `console: brief_refused <sprint_id> secret refused` and
403 `secret refused`; any other `sprints.Refused` is `console: brief_refused <sprint_id> <reason>` and
409 with the reason; any other exception is `console: brief_failed <Type>: <message>` and 500 `brief
failed`. Success is 200 `application/json` `{"version":<n>}`. Every refusal is `text/plain`, one line,
closes the connection and appends nothing.
`GET /api/sprint-status?sprint_id=<id>` carries no write guard: its query must hold exactly one
parameter, `sprint_id`, matching `sprints.SPRINT_ID` (else 400 `bad sprint`); an id that is neither
open nor withdrawn is 404 `this sprint is not known`; else 200 `application/json`,
`sprint_status(sprint_id)` as compact JSON with sorted keys.

Briefs (#887): `send_brief(sprint_id, secret, brief)`, under the ingest lock, raises
`Refused(NOT_OPEN)` unless the sprint is open, `SecretRefused` unless `sprints.read_secret` holds a
secret equal (`hmac.compare_digest`) to the presented one, then applies `sprints.checked_brief`
(the secret is checked before the parts); it appends exactly one `brief.sent` row
`{"sprint_id", "version", "goal", "brief"}` with the version one above the folded brief's (1 for
none), folds and publishes, and returns the version. A brief after an approval or a reply replaces
the decision: the sprint waits again. `approve_brief(project_id, sprint_id, version)` and
`reply_brief(project_id, sprint_id, version, reply)`, under the lock, raise `Refused(NOT_OPEN)`
unless the sprint is open and belongs to that project, `NOT_WAITING` when it has no brief, `REPLACED`
when `version` is not the folded brief's, `NOT_WAITING` when its decision is not `none`, and for a
reply `sprints.checked_reply`; each appends exactly one `brief.approved` row `{"sprint_id",
"version", "goal"}` or `brief.replied` row with the reply exactly as sent. `sprint_status(sprint_id)`,
under the lock, is `{"sprint_id", "decision", "version", "reply"}`: `none`, `approved` or `changes`
for an open sprint (`reply` only with `changes`), `withdrawn` for an id in `_withdrawn` (the
`sprints.withdrawn_ids` fold of the log, kept beside the sprints), else `Refused(UNKNOWN)`. The
secret, presented or stored, appears in no stderr line, answer, view or row.

Reports (#890): `POST /api/report` is a manager write like the brief's: no token, the sprint's secret
in its place. After the loopback `Host` check it runs `_checked_length(MAX_REPORT_BYTES)`, 65536
(any `Origin` is 403 `origin refused`, a media type that is not `application/json` 415 `json only`,
a length that is not ASCII digits 411 `length required`, one over the limit 413 `too large`, the
body unread), then `sprints.parse_report_request` (a body it does not accept is 400 `bad report`),
then `send_report(sprint_id, secret, report)`, which under the ingest lock raises
`Refused(NOT_OPEN)` unless the sprint is open, `SecretRefused` unless `sprints.read_secret` holds a
secret equal (`hmac.compare_digest`) to the presented one, `Refused(NOT_STARTED)` unless the
sprint's brief is approved, then whatever `sprints.checked_report` refuses (the secret is checked
before the members). It appends exactly one `sprint.reported` row `{"sprint_id", "goal", "report"}`
with the checked report, folds and publishes, and returns the row's `at`. A `sprints.SecretRefused`
is one stderr line `console: report_refused <sprint_id> secret refused` and 403 `secret refused`;
any other `sprints.Refused` is `console: report_refused <sprint_id> <reason>` and 409 with the
reason; any other exception is `console: report_failed <Type>: <message>` and 500 `report failed`.
Success is 200 `application/json` `{"at":"<the row's at>"}`. Every refusal is `text/plain`, one
line, closes the connection, appends nothing and publishes nothing. The secret appears in no stderr
line or answer.

A state request reads only `view_bytes`, which is memory: no log access, no
registry read, no derivation, no file, no filesystem metadata call, no
subprocess. The view is rebuilt only by `refresh()`, which reads the fleet
registry, appends the difference to the event log and publishes the new view;
the page itself is read once, at import and given its token at construction.

The stream carries `Connection: close` and no `Content-Length`. Its first frame is
the current view (the page takes its view from the stream alone, never from a
separate `/api/state` request that could answer after a newer frame); one frame
follows each later change of the view; a `: keepalive` comment follows
`KEEPALIVE_SECONDS` without one. A frame is

    event: view\\n
    data: <the bytes of /api/state>\\n
    \\n

A write error, or the service closing, ends the stream.

The registry is read, never written. An absent registry, or one that is not a
valid registry (unreadable, not UTF-8 or JSON, or a violation of
`agent_platform.validate_registry`), is not a reading: `refresh()` appends
nothing, so a registry that vanishes or is damaged never unregisters a project.
An unreadable one, as opposed to an absent one, writes one stderr line
`console: registry_unreadable <reason>`.

Registry changes are found by a watcher thread, `WATCH_THREAD`, started by
`start()`: every `poll_seconds` it takes the registry's `(st_mtime_ns, st_size,
st_ino)` (`None` when it cannot be read) and, when that differs from the last
one, calls `refresh()` and records it once that returns. A failing `refresh()` is
one stderr line `console: refresh_failed <Type>: <message>`; the loop goes on and
the signature is not recorded, so each later poll tries again (one line per
failed poll) until a refresh succeeds. A signature is sampled before the read it vouches for, so a
registry replaced between the two differs from the recorded signature and is
read again on the next poll.
The watcher only calls `os.stat`, so an idle service does no other I/O.

Sessions arrive by hooks and by a poll of the session registry (see
`sessions.py`). A hook is appended with its `repo` mapped by `repo_of` (the main
checkout of its `cwd` by default) and its `project` column set to the registered
project whose root is that repository, so the event is the project's activity.
`SESSION_THREAD`, started by `start()`, calls `poll_sessions()` every
`session_poll_seconds` (`SESSION_POLL_SECONDS`) over the directories
`session_dirs()` names, called on every poll: `default_session_dirs()` is
`$HOME/.claude/sessions` and the `sessions` directory of every profile under
`$CLAUDE_ACCOUNTS_DIR` (else `$HOME/.claude-accounts`). `poll_sessions` holds the
ingest lock from before it reads the registry until after it publishes, so no
hook is ingested between a reading and its application and an older reading
never overwrites a newer hook. An unchanged registry appends nothing. A failing
poll is one stderr line `console: session_poll_failed <Type>: <message>` and the
loop goes on.

Tracker (#859): when the service is given a `tracker`, a thread, `TRACKER_THREAD`, started by
`start()`, calls `poll_tracker()` at once and then every `tracker_seconds` (`TRACKER_SECONDS`,
two minutes). One poll reads the tracker, through `tracker(project_id, slug, cancelled=...)`, for
each registered project that is active (`inbox.is_active`: a log event or a git write within a
day) and has a GitHub checkout (`slug_of`), one project after another and never inside the ingest
lock; a project costs at most `inbox.MAX_CALLS` calls. The stop flag is checked between projects
and, through `cancelled`, before every page, so `close()` waits for at most the one `gh` call
already running and a read cancelled or finished after the stop appends and publishes nothing.
What a read finds is appended as the four inbox events (`inbox.seen`, `inbox.changed`,
`inbox.gone`, `inbox.health`; see `view.py`) and the view is published. A failed read is one
stderr line `console: tracker_failed <project_id> <Type>: <message>`; the project's items stay,
now marked stale, and only a change of read health is appended (`inbox.health`), so a failed read
stays stale across a restart. A read that ends after its project was unregistered appends
nothing. An exception escaping a poll is one stderr line
`console: tracker_poll_failed <Type>: <message>` and the loop goes on. Without a tracker no
thread starts and nothing is read.

Answers (#862, ADR-console-010): `answer(project_id, key, choices)` ticks one option under each
question of a decision item on the tracker, through `tick` (default `answer.tick_on_tracker`;
`tick(slug, issue, comment_id, questions, choices)`), and marks the item answered at once. It
raises `answer.Refused` with `NOT_OPEN` when the project is not registered, no record
`(project_id, key)` exists, or the item is answered, is not a decision, or has no questions; with
`CHOOSE` unless `choices` is a list of one `int` (not `bool`) per question within its options; with
`SENDING` while another answer to the same item runs. A `ForgeError` of the tick propagates. The
tick runs outside the ingest lock, so a hook or a poll never waits for `gh`. On success, under the
lock, when the record still exists, is unanswered and holds the same `(question, options)`, one
`inbox.changed` event with the item answered (its `chosen` set) is appended and published, so the
count leaves the headline at once; otherwise, and once the service is stopping, nothing is appended.
On failure nothing is appended. The appended item is what the reader makes of the ticked comment, so
the next read appends nothing. A tracker read that began before an answer finished never turns that
item back to unanswered (each answer takes a generation; a read keeps the answered item when its
own generation is older), and a read that began after it is authoritative.

Verification answers (#863): `answer_check(project_id, key, answer, version, note, confirm)` answers one runner
prompt of the inbox (a manual check, a verdict, an approval or a stale check) through `owner_path`
(default `verify_answer.answer_prompt`; `owner_path(slug, issue, comment_id, answer, version=version,
note=note, paid=paid)`, where `version` is the one the page sent, so the owner path refuses a prompt that
changed since the owner read it), which runs outside the ingest lock. Under the lock, in order, it raises `answer.Refused`
with `NOT_OPEN` when the project is not registered, no record exists, the item is answered or the
item takes no answer; with `NOT_AN_ANSWER` when the word is not among the item's answers; with
`CONFIRM` when the word is `approve` and `confirm` is not exactly the item's own `confirm` text (an
item without one is never approved): every live or paid approval needs its typed confirmation; with
`SENDING` while another answer to the same item runs. No request answers more than one item, and no
multi-item route exists. A note posts the owner's text and leaves the item open; any other word marks
the item answered at once, as `answer` does and with the same generation bookkeeping, when the record
still exists, is unanswered and names the same comment. A failure of `owner_path` propagates and
appends nothing.

Goals (#886, ADR-console-011): `state_goal(project_id, goal)`, under the ingest lock, raises
`sprints.Refused` with `UNREGISTERED` when the project is not in the folded states, then applies
`sprints.checked_goal` (`EMPTY`, `TOO_LONG`); it then makes a new sprint id, creates the sprint's
secret (`sprints.create_secret`) in `sprint-secrets/` beside the event log (`sprint_secrets`, like
`page-token`), appends exactly one `goal.stated` row `{"sprint_id", "goal"}` (the stripped goal),
removing the secret and re-raising when the append fails, then folds and publishes; it returns the
id. `withdraw_goal(project_id, sprint_id)`, under the lock, raises `Refused(NOT_OPEN)` unless the
folded sprint exists and belongs to that project (registration is not checked: a sprint of a project
that left the registry is hidden, and withdrawing it is harmless), appends exactly one
`goal.withdrawn` row carrying the stated goal, folds and publishes, then removes the secret; a
failure to remove is one stderr line `console: sprint_secret_unremoved <sprint_id> <Type>:
<message>` and the withdrawal still succeeds. The sprints are folded at construction and in `_fold`
(`sprints.sprint_states`) and handed to `derive_view`; `retain()` re-folds nothing, because goal rows
are never removed. The secret's value appears in no answer, view, stream frame, row or stderr line.

Managers (#888): the service takes `launcher` (`manager.launcher_for(sys.platform)` from `console.py`;
None means managers are not available on this host, no launch is ever made, no manager row is
written and every sprint reads `unavailable`), `bound_profile_of` (default `manager.bound_profile`)
and `dispatch` (default None: each launch runs on a new daemon thread named `MANAGER_THREAD`,
`console-manager-launch`; a test passes a stand-in). With a launcher, `state_goal` reserves the new
sprint (`_launching`, changed only under the ingest lock) in the critical section that appends
`goal.stated` and dispatches `_launch_reserved(sprint_id)` after releasing it. `retry_manager(
project_id, sprint_id)`, under the lock, raises `Refused` with `manager.UNAVAILABLE_TEXT` without a
launcher, `NOT_OPEN` unless the sprint is open and of that project, `LAUNCHING` while the sprint is
reserved, and, from `sprints.manager_status`, `HAS_MANAGER` when the manager is started and `TOO_SOON`
otherwise when no retry is offered; else it reserves the sprint before the lock is released and
dispatches, so a second retry that arrives while the first is queued or running is refused
`LAUNCHING`. `start_manager(sprint_id)` reserves (returning when it cannot) and launches in the
calling thread. `_launch_reserved`, under the lock, drops its own attempt's reservation (each reservation is one token, so a finished attempt never frees a later retry's) and returns when the sprint
is no longer open or its manager reads `started` (a stale or duplicate job never starts a second
manager), and a launch a retry reserved also returns when the sprint no longer offers retry (the
failed manager registered or briefed meanwhile); a missing secret appends `manager.failed` ("the sprint's secret is missing"); the profile
is chosen by `manager.choose_profile` over `capacity.capacity_view` of the profile directories read
at that moment (`_read_profiles`, never the last poll's) and the project's bound profile, and
`Wait` appends `manager.waiting`. Otherwise the launcher is called outside the lock, and then,
under it, a sprint that was withdrawn meanwhile has its secret and settings file removed again and
no row appended, and otherwise, unless the service is stopping, `manager.started {sprint_id, profile, session_name}`
or `manager.failed {sprint_id, reason}` is appended (the reason of a `LaunchFailed`, else `<Type>:
<message>`, the secret shown as `<secret>`), a failure is one stderr line `console: manager_failed
<sprint_id> <reason>`, and the view is published. `withdraw_goal` also removes the manager's
settings file. The sprint's secret appears in no row, view or stderr line.

Retention (ADR-console-009): construction runs one retention pass (`EventLog.retain`) after
opening the log and before reading its events, and `RETENTION_THREAD`, started by `start()`, calls
`retain()` every `retention_seconds` (`RETENTION_SECONDS`, one day). A pass that removed rows
re-folds the sessions and the inbox records and re-derives the last look and the moments from the
log under the ingest lock, with the construction code, and publishes, so the running digest equals
the one a restart would publish, and a later change is judged against what the log still holds. A failing pass
is one stderr line `console: retention_failed <Type>: <message>` and the loop goes on.

Digest: the view carries `digest.digest(moments, last look, now)` (see `digest.py`). The last look
is the newest `page.looked` event of the log, the same for every client and across restarts; the
moments are folded from each appended batch against the sessions, inbox and sprints before it, and only those
after the current window start are kept. The window of a first visit moves with the clock, so
`DIGEST_THREAD`, started by `start()`, calls `expire_digest()` every `digest_seconds`
(`DIGEST_SECONDS`): it trims the moments to the window and publishes, which changes the view only
when a moment left. A failure is one stderr line `console: digest_expiry_failed <Type>: <message>`
and the loop goes on.

Deliveries (#858): after each `poll_sessions()` the same thread calls `poll_deliveries()`, which
reads the run journals (see `deliveries.py`) of every folded session that is not ended and has a
repository, under the `projects` directory beside each of `session_dirs()`, outside the ingest
lock, and then appends `delivery.seen` and `delivery.gone` rows and publishes under it (every
poll publishes, so the minutes since a run moved advance; an unchanged view bumps no version). A
journal is read incrementally; one that was truncated or replaced is folded again from its start.
A run leaves only when its final record exists or its journal is confirmed absent (its listing
succeeded without it); a journal or a listing that cannot be read keeps the run's last
observation. A run that names no issue is not listed. A branch names its issue through the
project's configured branch pattern, `branch_pattern_of(repo)` (default
`deliveries.configured_branch_pattern`, kept once resolved); while it is None no run of that
repository names an issue, and a run read under another pattern is folded again from its start.
A state request reads memory only. Stderr lines: `console: delivery_poll_failed <Type>: <message>`
(a poll that raised, once per failed poll), `console: branch_pattern_unresolved <repo>` (a
repository's pattern did not resolve, again only after it resolved in between), `console: journal_unreadable <path> <reason>` (a journal or its final record turned
unreadable, again only after it read successfully in between) and `console: journals_unreadable
<session_id> <reason>` (a session's journal listing turned unreadable, likewise).

Construction order: bind the server (an `OSError` propagates and nothing else is
opened); load or create the page token (a `write_guard.TokenError` propagates: the service does
not start); open the event log; run one retention pass; fold the projects, the sessions, the inbox,
the read health, the deliveries, the sprints and the withdrawn ids, then the last look and the digest moments, from it; publish
the view; sample the registry's signature; `refresh()`; `poll_sessions()`; `poll_deliveries()`. The
absent set starts empty, so a restart drops a session only after two polls miss
it. On any failure after the bind, what was opened is closed and the exception
re-raised. `start()` serves on a daemon thread named `console-http`; `close()`
sets the stop flag, then `closing`, wakes every waiter, joins the watcher, the session poll, the
tracker, retention and digest threads and tears the rest down; it is idempotent.
"""

import hmac
import http.server
import json
import socketserver
import sys
import os
import threading
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl

from agent_tools.claims import owner_actions
from agent_tools.console import (
    answer, capacity, deliveries, digest, inbox, manager, sessions, sprints, write_guard)
from agent_tools.console.event_log import (
    BRIEF_APPROVED, BRIEF_REPLIED, BRIEF_SENT, GOAL_STATED, GOAL_WITHDRAWN, MANAGER_FAILED,
    MANAGER_STARTED, MANAGER_WAITING, SPRINT_REPORTED, Event, EventLog, utc_now)
from agent_tools.console.view import (
    INBOX_CHANGED, ReadState, derive_view, encode_view, health_change, inbox_changes, inbox_records,
    project_for, project_states, read_states, registry_changes)
from agent_tools.project_contract import agent_platform
from agent_tools.system.forge_api import ForgeError
from agent_tools.verification import verify_answer

def _reduced(questions: list[dict]) -> list[tuple[str, list[str]]]:
    return [(q["question"], list(q["options"])) for q in questions]


HOST = "127.0.0.1"
DEFAULT_PORT = 27184
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
       "connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'")
PAGE: bytes = Path(__file__).with_name("page.html").read_bytes()
BACKLOG = 16
POLL_SECONDS = 0.25
KEEPALIVE_SECONDS = 15.0
WATCH_THREAD = "console-registry-watch"
HOOK_PATH = "/api/hooks"
LOOKED_PATH = "/api/looked"
ANSWER_PATH = "/api/answer"
GOAL_PATH = "/api/goal"
WITHDRAW_PATH = "/api/withdraw"
APPROVE_PATH = "/api/approve"
REPLY_PATH = "/api/reply"
RETRY_PATH = "/api/retry-manager"
BRIEF_PATH = "/api/brief"
REPORT_PATH = "/api/report"
STATUS_PATH = "/api/sprint-status"
CHECK_PATH = "/api/check-answer"
PAGE_WRITES: frozenset[str] = frozenset({
    LOOKED_PATH, ANSWER_PATH, CHECK_PATH, GOAL_PATH, WITHDRAW_PATH, APPROVE_PATH, REPLY_PATH,
    RETRY_PATH})
MAX_ANSWER_BYTES = 4096
MAX_GOAL_BYTES = 16384
MAX_WITHDRAW_BYTES = 4096
MAX_BRIEF_BYTES = 32768
MAX_REPORT_BYTES = 65536
MANAGER_WRITES: frozenset[str] = frozenset({BRIEF_PATH, REPORT_PATH})
MAX_APPROVE_BYTES = 4096
MAX_REPLY_BYTES = 16384
MAX_RETRY_BYTES = 4096
MAX_HOOK_BYTES = 8 * 1024 * 1024
READINGS_PATH = "/api/readings"
MAX_READING_BYTES = 64 * 1024
POST_LIMITS = {HOOK_PATH: MAX_HOOK_BYTES, READINGS_PATH: MAX_READING_BYTES}
SESSION_POLL_SECONDS = 5.0
SESSION_THREAD = "console-session-poll"
TRACKER_SECONDS = 120.0
TRACKER_THREAD = "console-tracker-poll"
RETENTION_SECONDS = 86400.0
RETENTION_THREAD = "console-retention"
DIGEST_SECONDS = 60.0
DIGEST_THREAD = "console-digest"
MANAGER_THREAD = "console-manager-launch"


def default_store() -> Path:
    return agent_platform.state_root() / "console" / "events.sqlite3"


def default_registry() -> Path:
    return agent_platform.registry_path()


def default_session_dirs() -> list[Path]:
    """Every directory a Claude Code session registers in: the default config and each profile."""
    home = Path.home()
    accounts = os.environ.get("CLAUDE_ACCOUNTS_DIR") or str(home / ".claude-accounts")
    return [home / ".claude" / "sessions",
            *sorted(Path(accounts).glob("profiles/*/sessions"))]


def default_profile_dirs() -> list[Path]:
    """Every account's config directory, as `claude-account list` names them: the base and each profile."""
    home = Path.home()
    accounts = os.environ.get("CLAUDE_ACCOUNTS_DIR") or str(home / ".claude-accounts")
    return [home / ".claude",
            *sorted(p for p in Path(accounts).glob("profiles/*") if p.is_dir())]


def signature(path: Path) -> tuple[int, int, int] | None:
    """What the registry file looks like now; None when it cannot be statted."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size, stat.st_ino


def read_fleet(path: Path) -> list[dict] | None:
    """The registered entries, or None when the registry is not a reading."""
    try:
        document = json.loads(Path(path).read_bytes().decode("utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        return _unreadable(f"{type(error).__name__}: {error}")
    violations = agent_platform.validate_registry(document)
    if violations:
        first = violations[0]
        return _unreadable(f"{first['pointer']}: {first['message']}")
    return list(document["projects"])


def _unreadable(reason: str) -> None:
    print(f"console: registry_unreadable {reason}", file=sys.stderr)
    return None


class ConsoleServer(socketserver.ThreadingTCPServer):
    # Not http.server.HTTPServer, whose server_bind does a reverse lookup.
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = BACKLOG

    def __init__(self, port: int, console: "ConsoleService"):
        self.console = console
        super().__init__((HOST, port), ConsoleHandler)


class ConsoleHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        """Silenced: the service writes no access log."""

    def _send(self, status: int, content_type: str, body: bytes, *headers: tuple[str, str]):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _loopback(self) -> bool:
        port = self.server.server_address[1]
        if self.headers.get("Host") in (f"{HOST}:{port}", f"localhost:{port}"):
            return True
        self.close_connection = True
        self._send(403, "text/plain", b"loopback only\n", ("Connection", "close"))
        return False

    def _refuse(self, status: int, text: str):
        self.close_connection = True
        self._send(status, "text/plain", text.encode() + b"\n", ("Connection", "close"))

    def _checked_length(self, limit: int) -> int | None:
        """The body length of a write that passed the shared checks, else None (already refused)."""
        if self.headers.get("Origin") is not None:
            self._refuse(403, "origin refused")
            return None
        media = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if media != "application/json":
            self._refuse(415, "json only")
            return None
        length = self.headers.get("Content-Length", "")
        if not (length.isascii() and length.isdigit()):
            self._refuse(411, "length required")
            return None
        if int(length) > limit:
            self._refuse(413, "too large")
            return None
        return int(length)

    def do_POST(self):
        if not self._loopback():
            return
        route = self.path.split("?", 1)[0]
        if route == BRIEF_PATH:
            return self._brief_request()
        if route == REPORT_PATH:
            return self._report_request()
        if route in PAGE_WRITES:
            return self._page_write(route)
        if route not in POST_LIMITS:
            return self._refuse_method()
        length = self._checked_length(POST_LIMITS[route])
        if length is None:
            return
        console = self.server.console
        self.close_connection = True
        try:
            body = self.rfile.read(length)
            received = console.received_ms()
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.flush()
        except OSError:
            return
        name = "hook" if route == HOOK_PATH else "reading"
        try:
            if route == HOOK_PATH:
                console.ingest_hook(body, received)
            else:
                console.ingest_reading(body)
        except ValueError as error:
            print(f"console: {name}_unreadable {error}", file=sys.stderr)
        except Exception as error:
            print(f"console: {name}_failed {type(error).__name__}: {error}", file=sys.stderr)

    def _json_body(self, limit: int) -> bytes | None:
        """Read the body of a JSON page write; None when it was refused (already answered)."""
        if self.headers.get("Transfer-Encoding") is not None:
            self._refuse(411, "length required")
            return None
        media = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if media != "application/json":
            self._refuse(415, "json only")
            return None
        length = self.headers.get("Content-Length", "")
        if not (length.isascii() and length.isdigit()):
            self._refuse(411, "length required")
            return None
        if int(length) > limit:
            self._refuse(413, "too large")
            return None
        return self.rfile.read(int(length))

    def _answer_request(self, console: "ConsoleService", route: str = ANSWER_PATH) -> bool:
        """Read and carry out an answer; False when it was refused (already answered to the page)."""
        body = self._json_body(MAX_ANSWER_BYTES)
        if body is None:
            return False
        try:
            if route == CHECK_PATH:
                project_id, key, *rest = answer.parse_check_request(body)
            else:
                project_id, key, choices = answer.parse_request(body)
        except ValueError:
            self._refuse(400, "bad answer")
            return False
        try:
            if route == CHECK_PATH:
                console.answer_check(project_id, key, *rest)
            else:
                console.answer(project_id, key, choices)
        except (answer.Refused, verify_answer.Refused) as error:
            print(f"console: answer_refused {project_id} {key} {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except ForgeError as error:
            detail = " ".join(error.detail.split())
            print(f"console: answer_tick_failed {project_id} {key} {error.code}: {detail}",
                  file=sys.stderr)
            self._refuse(502, f"the tracker refused the tick: {' '.join(str(error).split())}")
            return False
        except Exception as error:
            print(f"console: answer_failed {type(error).__name__}: {error}", file=sys.stderr)
            self._refuse(500, "answer failed")
            return False
        return True

    def _goal_request(self, console: "ConsoleService", route: str) -> bool:
        """Read and carry out a goal or a withdrawal; False when it was refused."""
        name = "goal" if route == GOAL_PATH else "withdraw"
        body = self._json_body(MAX_GOAL_BYTES if route == GOAL_PATH else MAX_WITHDRAW_BYTES)
        if body is None:
            return False
        try:
            if route == GOAL_PATH:
                project_id, goal = sprints.parse_goal(body)
            else:
                project_id, sprint_id = sprints.parse_withdraw(body)
        except ValueError:
            self._refuse(400, f"bad {name}")
            return False
        try:
            if route == GOAL_PATH:
                console.state_goal(project_id, goal)
            else:
                console.withdraw_goal(project_id, sprint_id)
        except sprints.Refused as error:
            print(f"console: {name}_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: {name}_failed {type(error).__name__}: {error}", file=sys.stderr)
            self._refuse(500, f"{name} failed")
            return False
        return True

    def _brief_request(self):
        """The manager's route: a brief sent with the sprint's secret; no token, no page."""
        console = self.server.console
        length = self._checked_length(MAX_BRIEF_BYTES)
        if length is None:
            return
        self.close_connection = True
        try:
            sprint_id, secret, brief = sprints.parse_brief_request(self.rfile.read(length))
        except ValueError:
            return self._refuse(400, "bad brief")
        try:
            version = console.send_brief(sprint_id, secret, brief)
        except sprints.SecretRefused:
            print(f"console: brief_refused {sprint_id} {sprints.SECRET_REFUSED}", file=sys.stderr)
            return self._refuse(403, sprints.SECRET_REFUSED)
        except sprints.Refused as error:
            print(f"console: brief_refused {sprint_id} {error}", file=sys.stderr)
            return self._refuse(409, str(error))
        except Exception as error:
            print(f"console: brief_failed {type(error).__name__}: {error}", file=sys.stderr)
            return self._refuse(500, "brief failed")
        self._send(200, "application/json",
                   json.dumps({"version": version}, separators=(",", ":")).encode())

    def _report_request(self):
        """The manager's route: a report sent with the sprint's secret; no token, no page."""
        console = self.server.console
        length = self._checked_length(MAX_REPORT_BYTES)
        if length is None:
            return
        self.close_connection = True
        try:
            sprint_id, secret, report = sprints.parse_report_request(self.rfile.read(length))
        except ValueError:
            return self._refuse(400, "bad report")
        try:
            at = console.send_report(sprint_id, secret, report)
        except sprints.SecretRefused:
            print(f"console: report_refused {sprint_id} {sprints.SECRET_REFUSED}", file=sys.stderr)
            return self._refuse(403, sprints.SECRET_REFUSED)
        except sprints.Refused as error:
            print(f"console: report_refused {sprint_id} {error}", file=sys.stderr)
            return self._refuse(409, str(error))
        except Exception as error:
            print(f"console: report_failed {type(error).__name__}: {error}", file=sys.stderr)
            return self._refuse(500, "report failed")
        self._send(200, "application/json", json.dumps({"at": at}, separators=(",", ":")).encode())

    def _decision_request(self, console: "ConsoleService", route: str) -> bool:
        """Read and carry out an approval or a reply; False when it was refused."""
        name = "approve" if route == APPROVE_PATH else "reply"
        body = self._json_body(MAX_APPROVE_BYTES if route == APPROVE_PATH else MAX_REPLY_BYTES)
        if body is None:
            return False
        try:
            if route == APPROVE_PATH:
                parsed = sprints.parse_approve(body)
            else:
                parsed = sprints.parse_reply(body)
        except ValueError:
            self._refuse(400, f"bad {name}")
            return False
        try:
            if route == APPROVE_PATH:
                console.approve_brief(*parsed)
            else:
                console.reply_brief(*parsed)
        except sprints.Refused as error:
            print(f"console: {name}_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: {name}_failed {type(error).__name__}: {error}", file=sys.stderr)
            self._refuse(500, f"{name} failed")
            return False
        return True

    def _retry_request(self, console: "ConsoleService") -> bool:
        """Read and carry out a manager retry; False when it was refused."""
        body = self._json_body(MAX_RETRY_BYTES)
        if body is None:
            return False
        try:
            project_id, sprint_id = sprints.parse_retry(body)
        except ValueError:
            self._refuse(400, "bad retry")
            return False
        try:
            console.retry_manager(project_id, sprint_id)
        except sprints.Refused as error:
            print(f"console: retry_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: retry_failed {type(error).__name__}: {error}", file=sys.stderr)
            self._refuse(500, "retry failed")
            return False
        return True

    def _status_request(self):
        query = self.path.partition("?")[2]
        try:
            pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=bool(query))
        except ValueError:
            pairs = []
        if (len(pairs) != 1 or pairs[0][0] != "sprint_id"
                or sprints.SPRINT_ID.fullmatch(pairs[0][1]) is None):
            return self._send(400, "text/plain", b"bad sprint\n")
        try:
            status = self.server.console.sprint_status(pairs[0][1])
        except sprints.Refused as error:
            return self._send(404, "text/plain", str(error).encode() + b"\n")
        self._send(200, "application/json",
                   json.dumps(status, sort_keys=True, separators=(",", ":")).encode())

    def _page_write(self, route: str):
        console = self.server.console
        refusal = write_guard.refusal(
            self.headers["Host"], self.headers.get_all("Origin") or [],
            self.headers.get_all(write_guard.TOKEN_HEADER) or [], console.page_token)
        if refusal is not None:
            return self._refuse(*refusal)
        if route in (ANSWER_PATH, CHECK_PATH):
            self.close_connection = True
            if not self._answer_request(console, route):
                return
        elif route in (GOAL_PATH, WITHDRAW_PATH):
            self.close_connection = True
            if not self._goal_request(console, route):
                return
        elif route in (APPROVE_PATH, REPLY_PATH):
            self.close_connection = True
            if not self._decision_request(console, route):
                return
        elif route == RETRY_PATH:
            self.close_connection = True
            if not self._retry_request(console):
                return
        else:
            if (self.headers.get("Content-Length", "0") != "0"
                    or self.headers.get("Transfer-Encoding") is not None):
                return self._refuse(400, "no body")
            self.close_connection = True
            try:
                console.record_look()
            except Exception as error:
                print(f"console: look_failed {type(error).__name__}: {error}", file=sys.stderr)
                return self._refuse(500, "look failed")
        try:
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.flush()
        except OSError:
            return

    def do_GET(self):
        if not self._loopback():
            return
        route = self.path.split("?", 1)[0]
        if route == "/":
            self._send(200, "text/html; charset=utf-8", self.server.console.page_bytes,
                       ("Content-Security-Policy", CSP))
        elif route == "/api/state":
            self._send(200, "application/json", self.server.console.view_bytes)
        elif route == "/api/stream":
            self._stream()
        elif route == STATUS_PATH:
            self._status_request()
        elif route in POST_LIMITS or route in PAGE_WRITES or route in MANAGER_WRITES:
            self._refuse_method()
        else:
            self._send(404, "text/plain", b"not found\n")

    def _stream(self):
        console = self.server.console
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        seen = -1
        try:
            while not console.closing:
                change = console.wait_for_change(seen, KEEPALIVE_SECONDS)
                if change is None:
                    if console.closing:
                        return
                    self.wfile.write(b": keepalive\n\n")
                    continue
                seen, view = change
                self.wfile.write(b"event: view\ndata: " + view + b"\n\n")
        except OSError:
            return

    def _refuse_method(self):
        if not self._loopback():
            return
        self.close_connection = True
        route = self.path.split("?", 1)[0]
        allow = "POST" if (route in POST_LIMITS or route in PAGE_WRITES
                           or route in MANAGER_WRITES) else "GET"
        self._send(405, "text/plain", b"method not allowed\n",
                   ("Allow", allow), ("Connection", "close"))

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _refuse_method


class _RetryReservation:
    """A launch reservation made by a retry: it runs only while the sprint still offers retry."""


class ConsoleService:
    def __init__(self, store: Path, registry: Path, *, port: int = DEFAULT_PORT,
                 poll_seconds: float = POLL_SECONDS,
                 session_dirs: Callable[[], Iterable[Path]] = default_session_dirs,
                 profile_dirs: Callable[[], Iterable[Path]] = default_profile_dirs,
                 session_poll_seconds: float = SESSION_POLL_SECONDS,
                 repo_of: Callable[[str], str | None] = sessions.main_checkout,
                 tracker: Callable[..., list[dict]] | None = None,
                 tracker_seconds: float = TRACKER_SECONDS,
                 slug_of: Callable[[str], str | None] = owner_actions.checkout_slug,
                 branch_pattern_of: Callable[[str], str | None] = deliveries.configured_branch_pattern,
                 activity: Callable[[str], float | None] = inbox.local_activity,
                 clock: Callable[[], float] = time.time,
                 retention_seconds: float = RETENTION_SECONDS,
                 digest_seconds: float = DIGEST_SECONDS,
                 log_clock: Callable[[], str] = utc_now,
                 token_path: Path | None = None,
                 sprint_secrets: Path | None = None,
                 tick: Callable[[str, int, int, list[dict], list[int]], None] = answer.tick_on_tracker,
                 owner_path: Callable[..., None] = verify_answer.answer_prompt,
                 launcher: Callable[[manager.Launch], None] | None = None,
                 bound_profile_of: Callable[[str], str] = manager.bound_profile,
                 dispatch: Callable[[Callable[[], None]], None] | None = None):
        self.registry = Path(registry)
        self._launcher = launcher
        self._bound_profile_of = bound_profile_of
        self._dispatch = self._on_new_thread if dispatch is None else dispatch
        self._launching: dict[str, object] = {}
        self._tick = tick
        self._owner_path = owner_path
        self._sprint_secrets = (Path(store).with_name(sprints.SECRETS_DIR)
                                if sprint_secrets is None else Path(sprint_secrets))
        self._sending: set[tuple[str, str]] = set()
        self._answered: dict[tuple[str, str], int] = {}
        self._answer_generation = 0
        self._poll_seconds = poll_seconds
        self._session_dirs = session_dirs
        self._profile_dirs = profile_dirs
        self._profiles: frozenset[str] = frozenset()
        self._capacity = capacity.CapacityState({}, {})
        self._session_poll_seconds = session_poll_seconds
        self._repo_of = repo_of
        self._sessions: dict[str, sessions.SessionState] = {}
        self._absent: frozenset[str] = frozenset()
        self._deliveries: dict[tuple[str, str], deliveries.DeliveryState] = {}
        self._reader = deliveries.JournalReader()
        self._runs: dict[Path, deliveries.RunFold] = {}
        self._unreadable: set[str] = set()
        self._session_poller: threading.Thread | None = None
        self._tracker = tracker
        self._tracker_seconds = tracker_seconds
        self._slug_of = slug_of
        self._branch_pattern_of = branch_pattern_of
        self._patterns: dict[str, str] = {}
        self._activity = activity
        self._clock = clock
        self._retention_seconds = retention_seconds
        self._digest_seconds = digest_seconds
        self._retention_thread: threading.Thread | None = None
        self._digest_thread: threading.Thread | None = None
        self._looked: str | None = None
        self._moments: list[digest.Moment] = []
        self._tracker_thread: threading.Thread | None = None
        self._closing = False
        self._stop = threading.Event()
        self._watcher: threading.Thread | None = None
        self._signature = None
        self.log: EventLog | None = None
        self._ingest = threading.Lock()
        self._published = threading.Condition()
        self._view = b""
        self._version = 0
        self._thread: threading.Thread | None = None
        self._closed = False
        self._server = ConsoleServer(port, self)
        try:
            self._token = write_guard.load_token(
                Path(store).with_name(write_guard.TOKEN_FILE) if token_path is None
                else token_path)
            self._page = PAGE.replace(write_guard.TOKEN_SLOT, self._token.encode("ascii"))
            self.log = EventLog(store, clock=log_clock)
            self.log.retain()
            events = self.log.events()
            self._states = project_states(events)
            self._sessions = sessions.session_states(events)
            self._inbox = inbox_records(events)
            self._health = read_states(events)
            self._capacity = capacity.capacity_state(events)
            self._derive_digest(events)
            self._deliveries = deliveries.delivery_states(events)
            self._sprints = sprints.sprint_states(events)
            self._withdrawn = sprints.withdrawn_ids(events)
            self._publish()
            self._signature = signature(self.registry)
            self.refresh()
            self.poll_sessions()
            self.poll_deliveries()
        except BaseException:
            if self.log is not None:
                self.log.close()
            self._server.server_close()
            raise

    @property
    def address(self) -> tuple[str, int]:
        return self._server.server_address[:2]

    @property
    def view_bytes(self) -> bytes:
        return self._view

    @property
    def profiles(self) -> frozenset[str]:
        """The profile directories that existed at the last poll."""
        return self._profiles

    @property
    def page_bytes(self) -> bytes:
        """The page, with this install's token in its slot."""
        return self._page

    @property
    def page_token(self) -> str:
        return self._token

    @property
    def version(self) -> int:
        return self._version

    @property
    def closing(self) -> bool:
        return self._closing

    def wait_for_change(self, seen: int, timeout: float) -> tuple[int, bytes] | None:
        """The newest (version, view) once its version exceeds `seen`; None on timeout or close."""
        with self._published:
            self._published.wait_for(lambda: self._version > seen or self._closing, timeout)
            if self._closing or self._version <= seen:
                return None
            return self._version, self._view

    def _now(self) -> datetime:
        return datetime.fromtimestamp(self._clock(), timezone.utc)

    def _derive_digest(self, events: list[Event]) -> None:
        """Derive the last look and the moments from the whole log (construction and retention)."""
        self._looked = digest.last_looked(events)
        self._moments = digest.keep(digest.moments(events, {}, {}),
                                    digest.window_start(self._looked, self._now()))

    def _publish(self) -> None:
        view = encode_view(derive_view(
            self._states.values(), self._inbox, self._health,
            sessions=self._sessions.values(), deliveries=self._deliveries,
            now_ms=int(self._clock() * 1000), sprints=self._sprints,
            digest=digest.digest(self._moments, self._looked, self._now()),
            capacity=capacity.capacity_view(self._profiles, self._capacity, self._clock()),
            managers=self._launcher is not None))
        with self._published:
            if view != self._view:
                self._view = view
                self._version += 1
            self._published.notify_all()

    def refresh(self) -> list[Event]:
        """Append the difference between the registry and the log, and publish."""
        with self._ingest:
            entries = read_fleet(self.registry)
            if entries is None:
                return []
            appended = self.log.append(registry_changes(self._states, entries))
            if appended:
                self._fold(appended)
                self._publish()
            return appended

    def _apply(self, appended: list[Event]) -> None:
        self._fold(appended)
        self._publish()

    def received_ms(self) -> int:
        """The time, in epoch milliseconds, a hook is received; taken before it is answered."""
        return int(self._clock() * 1000)

    def ingest_hook(self, body: bytes, received_ms: int | None = None) -> list[Event]:
        """Append the session event a hook's input document describes; ValueError if unreadable."""
        if received_ms is None:
            received_ms = self.received_ms()
        document = json.loads(body.decode("utf-8"))
        with self._ingest:
            entry = sessions.hook_entry(document, self._repo_of, received_ms)
            if entry is None:
                return []
            kind, payload = entry
            repo = payload["repo"]
            project = None if repo is None else project_for(repo, self._states)
            appended = self.log.append([(kind, project, payload)])
            self._apply(appended)
            return appended

    def ingest_reading(self, body: bytes) -> list[Event]:
        """Append the capacity rows a limit report describes; ValueError if it is not one."""
        report = capacity.parse_report(json.loads(body.decode("utf-8")))
        with self._ingest:
            known = self._sessions.get(report["session_id"])
            profile = known.profile if known is not None else None
            if profile is None:
                profile = self._capacity.accounts.get(report["account"])
            if profile is None:
                print("console: reading_unattributed", file=sys.stderr)
                return []
            appended = self.log.append(capacity.report_entries(report, profile))
            self._apply(appended)
            return appended

    def record_look(self) -> list[Event]:
        """Append one `page.looked` event: the owner looked at the page."""
        with self._ingest:
            appended = self.log.append([(digest.LOOKED, None, {})])
            self._apply(appended)
            return appended

    def answer(self, project_id: str, key: str, choices: list[int]) -> None:
        """Tick `choices` on the tracker and mark the item answered; see the module docstring."""
        slot = (project_id, key)
        with self._ingest:
            record = self._inbox.get(slot) if project_id in self._states else None
            item = record.item if record is not None else None
            if (item is None or item["answered"] or item["reason"] != "decision"
                    or not item["questions"]):
                raise answer.Refused(answer.NOT_OPEN)
            questions = item["questions"]
            if (not isinstance(choices, list) or len(choices) != len(questions)
                    or any(isinstance(c, bool) or not isinstance(c, int) or not 0 <= c < len(q["options"])
                           for c, q in zip(choices, questions))):
                raise answer.Refused(answer.CHOOSE)
            if slot in self._sending:
                raise answer.Refused(answer.SENDING)
            self._sending.add(slot)
        sent = False
        try:
            self._tick(item["repo"], item["issue"], item["comment_id"], questions, choices)
            sent = True
        finally:
            with self._ingest:
                self._sending.discard(slot)
                if sent and not self._stop.is_set():
                    self._answer_generation += 1
                    self._mark_answered(slot, questions, choices)

    def answer_check(self, project_id: str, key: str, answer_word: str, version: str,
                     note: str | None = None, confirm: str | None = None) -> None:
        """Answer one verification prompt through the owner path; see the module docstring."""
        slot = (project_id, key)
        with self._ingest:
            record = self._inbox.get(slot) if project_id in self._states else None
            item = record.item if record is not None else None
            if item is None or item["answered"] or not item.get("answers", []):
                raise answer.Refused(answer.NOT_OPEN)
            if answer_word not in item["answers"]:
                raise answer.Refused(answer.NOT_AN_ANSWER)
            if answer_word == "approve" and (not item.get("confirm", "") or confirm != item["confirm"]):
                raise answer.Refused(answer.CONFIRM)
            if slot in self._sending:
                raise answer.Refused(answer.SENDING)
            self._sending.add(slot)
        sent = False
        try:
            self._owner_path(item["repo"], item["issue"], item["comment_id"], answer_word,
                             version=version, note=note, paid=bool(item.get("paid")))
            sent = True
        finally:
            with self._ingest:
                self._sending.discard(slot)
                if sent and answer_word != "note" and not self._stop.is_set():
                    self._answer_generation += 1
                    self._mark_check_answered(slot, item["comment_id"])

    def _mark_check_answered(self, slot: tuple[str, str], comment_id: int) -> None:
        record = self._inbox.get(slot)
        if record is None or record.item["answered"] or record.item["comment_id"] != comment_id:
            return
        appended = self.log.append([(INBOX_CHANGED, slot[0], {**record.item, "answered": True})])
        self._fold(appended)
        self._answered[slot] = self._answer_generation
        self._publish()

    def state_goal(self, project_id: str, goal: str) -> str:
        """Append one `goal.stated` event for a registered project and return the new sprint id."""
        with self._ingest:
            if project_id not in self._states:
                raise sprints.Refused(sprints.UNREGISTERED)
            goal = sprints.checked_goal(goal)
            sprint_id = sprints.new_sprint_id()
            sprints.create_secret(self._sprint_secrets, sprint_id)
            try:
                appended = self.log.append(
                    [(GOAL_STATED, project_id, {"sprint_id": sprint_id, "goal": goal})])
            except BaseException:
                sprints.remove_secret(self._sprint_secrets, sprint_id)
                raise
            self._apply(appended)
            if self._launcher is not None:
                self._launching[sprint_id] = object()
        if self._launcher is not None:
            self._dispatch_launch(sprint_id)
        return sprint_id

    def _on_new_thread(self, job: Callable[[], None]) -> None:
        threading.Thread(target=job, name=MANAGER_THREAD, daemon=True).start()

    def _dispatch_launch(self, sprint_id: str) -> None:
        """Hand a reserved sprint's launch to the dispatcher; a dispatch that fails frees the reservation."""
        with self._ingest:
            token = self._launching.get(sprint_id)
        try:
            self._dispatch(lambda: self._launch_reserved(sprint_id))
        except BaseException:
            with self._ingest:
                self._release(sprint_id, token)
            raise

    def _release(self, sprint_id: str, token: object) -> None:
        """Under the ingest lock: end the reservation `token` names; a later attempt's stays."""
        if token is not None and self._launching.get(sprint_id) is token:
            del self._launching[sprint_id]

    def _manager_listed(self, sprint: sprints.SprintState) -> bool:
        """Whether a listed session of the sprint's project carries the sprint's manager name."""
        name = manager.session_name(sprint.project_id, sprint.sprint_id)
        return any(
            s.name == name and s.state != sessions.ENDED and s.repo is not None
            and project_for(s.repo, self._states) == sprint.project_id
            for s in self._sessions.values())

    def _manager_state(self, sprint: sprints.SprintState) -> tuple[str, str | None, bool]:
        return sprints.manager_status(
            sprint, self._manager_listed(sprint), int(self._clock() * 1000), True)

    def start_manager(self, sprint_id: str) -> None:
        """Reserve the sprint's launch and run it in this thread; nothing when it cannot be reserved."""
        with self._ingest:
            if (self._launcher is None or sprint_id not in self._sprints
                    or sprint_id in self._launching):
                return
            self._launching[sprint_id] = object()
        self._launch_reserved(sprint_id)

    def retry_manager(self, project_id: str, sprint_id: str) -> None:
        """Reserve a new launch for an open sprint whose manager failed, waits or is missing."""
        with self._ingest:
            if self._launcher is None:
                raise sprints.Refused(manager.UNAVAILABLE_TEXT)
            sprint = self._sprints.get(sprint_id)
            if sprint is None or sprint.project_id != project_id:
                raise sprints.Refused(sprints.NOT_OPEN)
            if sprint_id in self._launching:
                raise sprints.Refused(sprints.LAUNCHING)
            state, _, retry = self._manager_state(sprint)
            if not retry:
                raise sprints.Refused(
                    sprints.HAS_MANAGER if state == sprints.STARTED else sprints.TOO_SOON)
            self._launching[sprint_id] = _RetryReservation()
        self._dispatch_launch(sprint_id)

    def _launch_reserved(self, sprint_id: str) -> None:
        """Start the reserved sprint's manager and record the outcome; the reservation ends here."""
        with self._ingest:
            token = self._launching.get(sprint_id)
        if token is None:
            return
        try:
            with self._ingest:
                launch = self._prepared_launch(sprint_id, token)
            if launch is None:
                return
            reason = None
            try:
                self._launcher(launch)
            except Exception as error:
                reason = (str(error) if isinstance(error, manager.LaunchFailed)
                          else f"{type(error).__name__}: {error}")
            self._record_launch(launch, reason, token)
        finally:
            with self._ingest:
                self._release(sprint_id, token)

    def _prepared_launch(self, sprint_id: str, token: object) -> manager.Launch | None:
        """Under the ingest lock: the launch to run, or None after dropping the reservation."""
        sprint = self._sprints.get(sprint_id)
        if (sprint is None or self._manager_state(sprint)[0] == sprints.STARTED
                or (isinstance(token, _RetryReservation) and not self._manager_state(sprint)[2])):
            self._release(sprint_id, token)
            return None
        project_id = sprint.project_id
        secret = sprints.read_secret(self._sprint_secrets, sprint_id)
        if secret is None:
            self._append_manager(MANAGER_FAILED, project_id, {
                "sprint_id": sprint_id, "reason": "the sprint's secret is missing"}, token)
            return None
        project = self._states.get(project_id)
        if project is None:
            self._release(sprint_id, token)
            return None
        choice = manager.choose_profile(
            capacity.capacity_view(self._read_profiles(), self._capacity, self._clock()),
            self._bound_profile_of(project.root))
        if isinstance(choice, manager.Wait):
            self._append_manager(MANAGER_WAITING, project_id, {
                "sprint_id": sprint_id, "until": choice.until}, token)
            return None
        return manager.new_launch(sprint_id, project_id, sprint.goal, project.root, choice,
                                  secret, self._sprint_secrets)

    def _append_manager(self, kind: str, project_id: str, payload: dict, token: object) -> None:
        """Under the ingest lock: append one manager row, release the attempt's hold, publish."""
        self._release(payload["sprint_id"], token)
        self._apply(self.log.append([(kind, project_id, payload)]))

    def _record_launch(self, launch: manager.Launch, reason: str | None, token: object) -> None:
        secret = launch.env[manager.SECRET_ENV]
        with self._ingest:
            self._release(launch.sprint_id, token)
            if launch.sprint_id not in self._sprints:
                self._drop_sprint_files(launch.sprint_id)
                return
            if self._stop.is_set():
                return
            if reason is None:
                self._append_manager(MANAGER_STARTED, launch.project_id, {
                    "sprint_id": launch.sprint_id, "profile": launch.profile,
                    "session_name": launch.session_name}, token)
                return
            if secret:
                reason = reason.replace(secret, "<secret>")
            self._append_manager(MANAGER_FAILED, launch.project_id, {
                "sprint_id": launch.sprint_id, "reason": reason}, token)
            print(f"console: manager_failed {launch.sprint_id} {reason}", file=sys.stderr)

    def withdraw_goal(self, project_id: str, sprint_id: str) -> None:
        """Append one `goal.withdrawn` event for an open sprint of that project, then drop its secret."""
        with self._ingest:
            sprint = self._sprints.get(sprint_id)
            if sprint is None or sprint.project_id != project_id:
                raise sprints.Refused(sprints.NOT_OPEN)
            appended = self.log.append(
                [(GOAL_WITHDRAWN, project_id, {"sprint_id": sprint_id, "goal": sprint.goal})])
            self._apply(appended)
            self._drop_sprint_files(sprint_id)

    def _drop_sprint_files(self, sprint_id: str) -> None:
        """Remove a sprint's secret and its manager's settings file; a failure is logged, not raised."""
        for remove in (sprints.remove_secret, manager.remove_settings):
            try:
                remove(self._sprint_secrets, sprint_id)
            except Exception as error:
                print(f"console: sprint_secret_unremoved {sprint_id} "
                      f"{type(error).__name__}: {error}", file=sys.stderr)

    def send_brief(self, sprint_id: str, secret: str, brief: dict) -> int:
        """Append one `brief.sent` event for an open sprint whose secret is presented; its version."""
        with self._ingest:
            sprint = self._manager_sprint(sprint_id, secret)
            parts = sprints.checked_brief(brief)
            version = (sprint.brief.version if sprint.brief else 0) + 1
            appended = self.log.append([(BRIEF_SENT, sprint.project_id, {
                "sprint_id": sprint_id, "version": version, "goal": sprint.goal,
                "brief": parts})])
            self._apply(appended)
            return version

    def _manager_sprint(self, sprint_id: str, secret: str) -> sprints.SprintState:
        """The open sprint whose secret is presented (the caller holds the ingest lock)."""
        sprint = self._sprints.get(sprint_id)
        if sprint is None:
            raise sprints.Refused(sprints.NOT_OPEN)
        expected = sprints.read_secret(self._sprint_secrets, sprint_id)
        if expected is None or not hmac.compare_digest(expected.encode(), secret.encode()):
            raise sprints.SecretRefused(sprints.SECRET_REFUSED)
        return sprint

    def send_report(self, sprint_id: str, secret: str, report: dict) -> str:
        """Append one `sprint.reported` event for an approved sprint whose secret is presented; its at."""
        with self._ingest:
            sprint = self._manager_sprint(sprint_id, secret)
            if sprint.state != sprints.STARTING:
                raise sprints.Refused(sprints.NOT_STARTED)
            checked = sprints.checked_report(report)
            appended = self.log.append([(SPRINT_REPORTED, sprint.project_id, {
                "sprint_id": sprint_id, "goal": sprint.goal, "report": checked})])
            self._apply(appended)
            return appended[-1].at

    def _waiting_brief(self, project_id: str, sprint_id: str, version: int) -> sprints.SprintState:
        sprint = self._sprints.get(sprint_id)
        if sprint is None or sprint.project_id != project_id:
            raise sprints.Refused(sprints.NOT_OPEN)
        if sprint.brief is None:
            raise sprints.Refused(sprints.NOT_WAITING)
        if version != sprint.brief.version:
            raise sprints.Refused(sprints.REPLACED)
        if sprint.brief.decision != sprints.NONE:
            raise sprints.Refused(sprints.NOT_WAITING)
        return sprint

    def approve_brief(self, project_id: str, sprint_id: str, version: int) -> None:
        """Append one `brief.approved` event for the waiting brief of that version."""
        with self._ingest:
            sprint = self._waiting_brief(project_id, sprint_id, version)
            appended = self.log.append([(BRIEF_APPROVED, project_id, {
                "sprint_id": sprint_id, "version": version, "goal": sprint.goal})])
            self._apply(appended)

    def reply_brief(self, project_id: str, sprint_id: str, version: int, reply: str) -> None:
        """Append one `brief.replied` event carrying the owner's words exactly as sent."""
        with self._ingest:
            sprint = self._waiting_brief(project_id, sprint_id, version)
            sprints.checked_reply(reply)
            appended = self.log.append([(BRIEF_REPLIED, project_id, {
                "sprint_id": sprint_id, "version": version, "goal": sprint.goal,
                "reply": reply})])
            self._apply(appended)

    def sprint_status(self, sprint_id: str) -> dict:
        """What became of a sprint's brief: its decision, version and the reply asking for changes."""
        with self._ingest:
            sprint = self._sprints.get(sprint_id)
            if sprint is not None:
                brief = sprint.brief
                decision = brief.decision if brief else sprints.NONE
                return {"sprint_id": sprint_id, "decision": decision,
                        "version": brief.version if brief else None,
                        "reply": brief.reply if decision == sprints.CHANGES else None}
            if sprint_id in self._withdrawn:
                return {"sprint_id": sprint_id, "decision": sprints.WITHDRAWN,
                        "version": None, "reply": None}
            raise sprints.Refused(sprints.UNKNOWN)

    def _mark_answered(self, slot: tuple[str, str], questions: list[dict], choices: list[int]) -> None:
        record = self._inbox.get(slot)
        if record is None or record.item["answered"] or _reduced(record.item["questions"]) != _reduced(questions):
            return
        item = {**record.item, "answered": True,
                "questions": [{**q, "chosen": q["options"][c]} for q, c in zip(record.item["questions"], choices)]}
        appended = self.log.append([(INBOX_CHANGED, slot[0], item)])
        self._fold(appended)
        self._answered[slot] = self._answer_generation
        self._publish()

    def poll_sessions(self) -> list[Event]:
        """Append what the session registry shows that the folded sessions do not, and publish."""
        with self._ingest:
            observations = sessions.read_session_registry(self._session_dirs())

            def project_of(repo: str | None) -> str | None:
                return None if repo is None else project_for(repo, self._states)

            changes, absent = sessions.poll_changes(
                self._sessions, observations, self._absent, self._repo_of, project_of)
            appended = self.log.append(changes)
            self._absent = absent
            self._profiles = self._read_profiles()
            if appended:
                self._fold(appended)
            self._publish()
            return appended

    def _read_profiles(self) -> frozenset[str]:
        """The profile directories as they are now."""
        return frozenset(sessions.profile_name(d) for d in self._profile_dirs() if d.is_dir())

    def _warn_once(self, key: str, line: str) -> None:
        """Print `line` unless `key` is already unreadable; `_unreadable` is cleared by a good read."""
        if key not in self._unreadable:
            self._unreadable.add(key)
            print(line, file=sys.stderr)

    def _branch_pattern(self, repo: str) -> str | None:
        """The repository's branch pattern, kept once resolved; None (one stderr line) while it does not resolve."""
        pattern = self._patterns.get(repo)
        if pattern is None:
            pattern = self._branch_pattern_of(repo)
            if pattern is None:
                self._warn_once(f"pattern {repo}", f"console: branch_pattern_unresolved {repo}")
                return None
            self._patterns[repo] = pattern
        self._unreadable.discard(f"pattern {repo}")
        return pattern

    def poll_deliveries(self) -> list[Event]:
        """Append what the run journals of the live sessions show that the log does not, and publish."""
        folded = self._deliveries
        scanned = {sid: s for sid, s in self._sessions.items()
                   if s.state != sessions.ENDED and s.repo is not None}
        projects_dirs: list[Path] = []
        for directory in self._session_dirs():
            projects = Path(directory).parent / "projects"
            if projects not in projects_dirs:
                projects_dirs.append(projects)
        readings: dict[tuple[str, str], deliveries.DeliveryState] = {}
        runs: dict[Path, deliveries.RunFold] = {}
        terminal: list[tuple[str, str]] = []
        for sid in sorted(scanned):
            listing = deliveries.run_journals(projects_dirs, sid)
            if isinstance(listing, deliveries.Unreadable):
                readings.update({k: v for k, v in folded.items() if k[0] == sid})
                runs.update({j: f for j, f in self._runs.items() if j.parents[3].name == sid})
                self._warn_once(f"listing {sid}",
                                f"console: journals_unreadable {sid} {listing.reason}")
                continue
            self._unreadable.discard(f"listing {sid}")
            pattern = self._branch_pattern(scanned[sid].repo)
            for journal in listing:
                key = (sid, journal.parent.name)
                path = str(journal)
                final = deliveries.has_final_record(journal)
                # A run that ended between two polls, or while the console was down (the log still
                # holds it), is read once more, so its close-out reaches the log as the run's last
                # observation before the run leaves.
                ended = final is True and (journal in self._runs or key in folded)
                if final is True and not ended:
                    self._reader.forget(journal)
                    self._unreadable.discard(path)
                    continue
                known = self._runs.get(journal)
                if known is not None and known.branch_pattern != pattern:
                    self._reader.forget(journal)
                chunk = final if isinstance(final, deliveries.Unreadable) else self._reader.read(journal)
                if ended:
                    self._reader.forget(journal)
                if isinstance(chunk, deliveries.Unreadable):
                    if key in folded:
                        readings[key] = folded[key]
                    if journal in self._runs:
                        runs[journal] = self._runs[journal]
                    self._warn_once(path, f"console: journal_unreadable {path} {chunk.reason}")
                    continue
                self._unreadable.discard(path)
                if chunk is None:
                    continue
                fold = self._runs.get(journal)
                if fold is None or chunk.from_start or fold.branch_pattern != pattern:
                    fold = deliveries.RunFold(pattern)
                fold.apply(chunk.records)
                issues = fold.issues()
                if issues:
                    readings[key] = deliveries.DeliveryState(sid, key[1], chunk.moved_ms, issues)
                if ended:
                    self._unreadable.discard(path)
                    if issues:
                        terminal.append(key)
                else:
                    runs[journal] = fold
        for journal in self._runs.keys() - runs.keys():
            self._reader.forget(journal)
        self._runs = runs
        with self._ingest:
            def project_of(sid: str) -> str | None:
                repo = scanned[sid].repo
                return project_for(repo, self._states)

            changes = deliveries.delivery_changes(self._deliveries, readings, scanned, project_of)
            changes += [(deliveries.DELIVERY_GONE, project_of(sid), {"session_id": sid, "run_id": run})
                        for sid, run in terminal]
            appended = self.log.append(changes)
            if appended:
                self._fold(appended)
            self._publish()
            return appended

    def _poll_loop(self) -> None:
        while not self._stop.wait(self._session_poll_seconds):
            try:
                self.poll_sessions()
            except Exception as error:
                print(f"console: session_poll_failed {type(error).__name__}: {error}",
                      file=sys.stderr)
            try:
                self.poll_deliveries()
            except Exception as error:
                print(f"console: delivery_poll_failed {type(error).__name__}: {error}",
                      file=sys.stderr)

    def _fold(self, appended: list[Event]) -> None:
        new = digest.moments(appended, self._sessions, self._inbox, self._sprints)
        self._looked = digest.last_looked(appended, self._looked)
        self._states = project_states(appended, self._states)
        self._sessions = sessions.session_states(appended, self._sessions)
        self._inbox = inbox_records(appended, self._inbox)
        self._health = read_states(appended, self._health)
        self._capacity = capacity.capacity_state(appended, self._capacity)
        self._deliveries = deliveries.delivery_states(appended, self._deliveries)
        self._sprints = sprints.sprint_states(appended, self._sprints)
        self._withdrawn = sprints.withdrawn_ids(appended, self._withdrawn)
        self._moments = digest.keep([*self._moments, *new],
                                    digest.window_start(self._looked, self._now()))

    def retain(self) -> int:
        """One retention pass; when it removed rows, re-fold the digest's baselines and publish.

        The folded sessions and inbox records are rebuilt from the retained log, as a
        restart would, so a later change is judged against what the log still holds.
        """
        with self._ingest:
            removed = self.log.retain()
            if removed:
                events = self.log.events()
                self._sessions = sessions.session_states(events)
                self._inbox = inbox_records(events)
                self._capacity = capacity.capacity_state(events)
                self._derive_digest(events)
                self._publish()
            return removed

    def expire_digest(self) -> None:
        """Trim the moments to the current window and publish."""
        with self._ingest:
            self._moments = digest.keep(
                self._moments, digest.window_start(self._looked, self._now()))
            self._publish()

    def _retain_loop(self) -> None:
        while not self._stop.wait(self._retention_seconds):
            try:
                self.retain()
            except Exception as error:
                print(f"console: retention_failed {type(error).__name__}: {error}",
                      file=sys.stderr)

    def _expire_loop(self) -> None:
        while not self._stop.wait(self._digest_seconds):
            try:
                self.expire_digest()
            except Exception as error:
                print(f"console: digest_expiry_failed {type(error).__name__}: {error}",
                      file=sys.stderr)

    def poll_tracker(self) -> None:
        """One refresh of the inbox of every active project; see the module docstring."""
        if self._tracker is None:
            return
        now = self._clock()
        for project_id, state in sorted(dict(self._states).items()):
            if self._stop.is_set():
                return
            if not inbox.is_active(state.last_at, self._activity(state.root), now):
                continue
            slug = self._slug_of(state.root)
            if slug is None:
                continue
            generation = self._answer_generation
            try:
                items = self._tracker(project_id, slug, cancelled=self._stop.is_set)
            except ForgeError as error:
                if error.code == "cancelled" or self._stop.is_set():
                    return
                self._read_failed(project_id, error)
            except Exception as error:
                if self._stop.is_set():
                    return
                self._read_failed(project_id, error)
            else:
                if self._stop.is_set():
                    return
                self._read_succeeded(project_id, items, generation)

    def _read_failed(self, project_id: str, error: Exception) -> None:
        print(f"console: tracker_failed {project_id} {type(error).__name__}: {error}", file=sys.stderr)
        with self._ingest:
            if project_id not in self._states:
                return
            previous = self._health.get(project_id)
            appended = self.log.append(health_change(
                self._health, project_id, False, previous.read_at if previous else None))
            self._fold(appended)
            self._publish()

    def _read_succeeded(self, project_id: str, items: list[dict], generation: int) -> None:
        with self._ingest:
            if project_id not in self._states:
                return
            items = [self._kept_answered(project_id, i, generation) for i in items]
            self._answered = {k: g for k, g in self._answered.items()
                              if k[0] != project_id or g > generation}
            appended = self.log.append([*inbox_changes(self._inbox, project_id, items),
                                        *health_change(self._health, project_id, True)])
            self._fold(appended)
            self._health[project_id] = ReadState(True, utc_now())
            self._publish()

    def _kept_answered(self, project_id: str, item: dict, generation: int) -> dict:
        """A read that began before the item's answer finished does not undo the answer."""
        if item["answered"] or self._answered.get((project_id, item["key"]), 0) <= generation:
            return item
        record = self._inbox.get((project_id, item["key"]))
        return record.item if record is not None and record.item["answered"] else item

    def _track(self) -> None:
        while True:
            try:
                self.poll_tracker()
            except Exception as error:
                print(f"console: tracker_poll_failed {type(error).__name__}: {error}", file=sys.stderr)
            if self._stop.wait(self._tracker_seconds):
                return

    def _watch(self) -> None:
        while not self._stop.wait(self._poll_seconds):
            current = signature(self.registry)
            if current == self._signature:
                continue
            try:
                self.refresh()
            except Exception as error:
                print(f"console: refresh_failed {type(error).__name__}: {error}", file=sys.stderr)
            else:
                self._signature = current

    def start(self) -> None:
        self._watcher = threading.Thread(target=self._watch, name=WATCH_THREAD, daemon=True)
        self._watcher.start()
        self._session_poller = threading.Thread(
            target=self._poll_loop, name=SESSION_THREAD, daemon=True)
        self._session_poller.start()
        if self._tracker is not None:
            self._tracker_thread = threading.Thread(
                target=self._track, name=TRACKER_THREAD, daemon=True)
            self._tracker_thread.start()
        self._retention_thread = threading.Thread(
            target=self._retain_loop, name=RETENTION_THREAD, daemon=True)
        self._retention_thread.start()
        self._digest_thread = threading.Thread(
            target=self._expire_loop, name=DIGEST_THREAD, daemon=True)
        self._digest_thread.start()
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="console-http", daemon=True)
        self._thread.start()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        with self._published:
            self._closing = True
            self._published.notify_all()
        if self._watcher is not None:
            self._watcher.join()
        if self._session_poller is not None:
            self._session_poller.join()
        if self._tracker_thread is not None:
            self._tracker_thread.join()
        if self._retention_thread is not None:
            self._retention_thread.join()
        if self._digest_thread is not None:
            self._digest_thread.join()
        if self._thread is not None:
            self._server.shutdown()
        self._server.server_close()
        with self._ingest:
            self.log.close()
