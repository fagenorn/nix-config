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
    POST /api/exclusion 204, a JSON body, the page excludes or includes a profile (below)
    POST /api/approve 204, a JSON body, the page approves a brief (below)
    POST /api/reply 204, a JSON body, the page asks a brief for changes (below)
    POST /api/retry-manager 204, a JSON body, the page starts a sprint's manager again (below)
    POST /api/message 204, a JSON body, the page sends the owner's message to a sprint (below)
    POST /api/stop  204, a JSON body, the page stops a sprint (below)
    POST /api/brief 200 application/json, a manager sends a sprint's brief (below)
    POST /api/report 200 application/json, a manager sends a sprint's report (below)
    POST /api/close 200 application/json, a manager sends a sprint's closing report (below)
    POST /api/inbox 200 application/json, a manager reads a sprint's unread messages (below)
    POST /api/message-reply 200 application/json, a manager answers one message (below)
    POST /api/ask   200 application/json, a manager sends a round of questions (below)
    POST /api/round-answer 204, a JSON body, the page answers one question (below)
    POST /api/recap 200 application/json, a manager reads what it needs to pick a sprint up (below)
    GET /api/sprint-status?sprint_id=<id> 200 application/json, what became of a brief (below)
    GET /api/profile 200 application/json, the profile a new session should use (below)
    GET /api/excluded 200 application/json, the profiles the owner excluded (below)
    anything else   404
    other methods   405 with `Allow: GET` (`Allow: POST` on `/api/hooks`, `/api/readings`,
                    `/api/looked`, `/api/answer`, `/api/check-answer`, `/api/goal`, `/api/withdraw`,
                    `/api/approve`, `/api/reply`, `/api/retry-manager`, `/api/message`, `/api/stop`, `/api/exclusion`, `/api/brief`, `/api/report`,
                    `/api/close`, `/api/inbox`, `/api/message-reply`, `/api/recap`, `/api/ask` and `/api/round-answer`)

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
`POST /api/goal`, `POST /api/withdraw`, `POST /api/approve`, `POST /api/reply`,
`POST /api/retry-manager`, `POST /api/message`, `POST /api/stop`, `POST /api/round-answer`, `POST /api/continue`, `POST /api/exclusion`, `POST /api/signin`,
`POST /api/signin-code`, `POST /api/signin-cancel` and `POST /api/account-add`; ADR-console-008, ADR-console-010, ADR-console-011, ADR-console-013) is made by the desk page
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
<Type>: <message>` and 500 `retry failed`; success is an empty `204`. `POST /api/message` (#889)
runs the same checks with `MAX_MESSAGE_BYTES` (16384) and `sprints.parse_message`: 400 `bad
message`, `sprints.Refused` is one stderr line `console: message_refused <reason>` and 409 with
the reason, any other exception is `console: message_failed <Type>: <message>` and 500 `message
failed`; success is an empty `204`. `POST /api/stop` (#892) runs the same checks with
`MAX_STOP_BYTES` (4096) and `sprints.parse_stop`: 400 `bad stop`, `sprints.Refused` is one stderr
line `console: stop_refused <reason>` and 409 with the reason, any other exception is `console:
stop_failed <Type>: <message>` and 500 `stop failed`; success is an empty `204`. `POST /api/round-answer` (#891) runs the same checks with
`MAX_ROUND_ANSWER_BYTES` (16384) and `sprints.parse_round_answer`: 400 `bad round answer`,
`sprints.Refused` is one stderr line `console: round_answer_refused <reason>` and 409 with the
reason, any other exception is `console: round_answer_failed <Type>: <message>` and 500 `round
answer failed`; success is an empty `204`. `POST /api/signin`, `POST /api/signin-code` and
`POST /api/signin-cancel` (#1026) run the same checks with `MAX_SIGNIN_BYTES` (4096) and
`signin_run.parse_profile_request` (start and cancel) or `signin_run.parse_code_request`: 400 `bad
sign-in`, `bad code` or `bad cancel`; a refusal is one stderr line `console: signin_refused <profile>
<reason>` and 409 with the reason (`sign-in is not available on this host` when the service has no
runs, `unknown profile` for a profile that is not listed, `no sign-in is running for <profile>` for a
code or a cancel with no live run); any other exception is `console: signin_failed <Type>` (never its
message) and 500 `sign-in failed`. Each accepted write appends exactly one `signin.acted` row and no
refusal appends one. The start route alone answers with a body: `200` `application/json`
`{"attempt": <int>, "link": <string> | null}` (the attempt is the `seq` of the started row, and a
start while a run is live answers that run's attempt and link and starts no second client), after
waiting for the link outside the service's lock; a failed start is a `signin.acted` row with outcome
`failed`, one stderr line `console: signin_start_failed <profile> <kind>` and 502 `the sign-in could
not start: <kind>`. The code route answers `204`; a write the client's input refuses is `console:
signin_code_failed <profile> <Type>` and 502 `the code could not be passed on`, appending nothing.
The cancel route answers `204`.

`POST /api/account-add` (#1027) runs the same checks with `MAX_ACCOUNT_BYTES` (4096) and
`account_add.parse_add_request`: 400 `bad account`. Under the lock `_adding` (never `_ingest`) the
service refuses a name `account_add.refusal` refuses, a name already listed
(`account <name> already exists`) and, without an account adder, sign-in runs or a sign-in reader,
every name (`adding an account is not available on this host`): one stderr line `console:
account_add_refused <reason>` and 409 with the reason, appending nothing. It then calls the adder
(the launcher's own add), reads the listing again, and a profile not listed is `not_listed`. A
failed add is one stderr line `console: account_add_failed <name> <kind>` and 502 `the account could
not be created: <kind>`, appending nothing. An added profile appends one `account.added` row
`{"by": "owner", "profile": <name>}`, joins the service's profiles at once, and its sign-in status is
read once (a failed read is one stderr line `console: signin_add_read_failed <profile> <kind or
Type>` and records nothing) before the sign-in starts as the start route starts it. A sign-in that
cannot start leaves the row and the profile, appends the start route's `failed` row and answers
502 `the account was added; its sign-in could not start: <kind>`, with `console: signin_start_failed
<name> <kind>`. Any other exception is `console: account_add_failed <Type>` (never its message) and
500 `adding the account failed`. Success is `200` `application/json`
`{"attempt": <int>, "link": <string> | null, "profile": <name>}` with the start route's attempt and
link; no row, stderr line, view or stream frame carries the link. The token is created once in
`page-token` beside the event log and reaches a client only inside `GET /`, where it replaces
the slot in the page's `console-token` meta tag.

`POST /api/readings` runs the same checks in the same order (loopback `Host`, no `Origin`,
`application/json`, a length, at most `MAX_READING_BYTES`), answers `204` and flushes, and only
then ingests (`ingest_reading`): `capacity.parse_report` keeps the whitelisted members of the body
(a body that is not UTF-8 JSON or not a report is one stderr line `console: reading_unreadable
<message>`; any other failure `console: reading_failed <Type>: <message>`; the handler never
raises). The reading's profile is the profile the console probed under the report's session (below),
else the `profile` of the session the report names when the registry
placed that session under a profile, else the profile its account was last attributed to (the folded
`(account, profile)` pairs of earlier readings), else the reading is dropped with one stderr line
`console: reading_unattributed` and no identifier. No credential file is opened and no subprocess
started to learn a profile. The attributed reading is appended with its `capacity.stop` when it was
a refusal, and published. Every poll of the session registry also lists the profile directories
(`profile_dirs()`, `default_profile_dirs()`: each directory of `profiles/` under
`$CLAUDE_ACCOUNTS_DIR`, else `$HOME/.claude-accounts`; only `is_dir` touches one; only the accounts
among them count, `sessions.account_name`, so the unprofiled `$HOME/.claude` is never listed, probed,
read for sign-in or chosen, #1016) so a profile never
used reads `unknown` and a removed one is no longer listed, and ends by publishing, so a reset that has passed shows within one poll.

Probes (#1009, ADR-console-006): with a `prober` (`probe.prober_for(sys.platform)` from `console.py`;
none elsewhere than Linux), `PROBE_LOOP_THREAD`, started by `start()`, calls `probe_round()` every
`probe_tick_seconds` (`PROBE_TICK_SECONDS`, 15 s). A round takes, under the ingest lock, the profiles
`probe.due_profiles` names (a first probe 30 s after the service started, then one every 600 s, never a
second while one is in flight), gives each a `probe.Probe` with a fresh UUID4 session id, remembers the
id (kept for as long as the probe is pending or running, then for the last `probe.PROBE_MEMORY` (256)
completed probes), and hands each probe, after releasing the lock, to
`probe_dispatch` (default: a new daemon thread named `PROBE_THREAD`) as a job that runs the prober. The
reading a probe's request makes arrives like any other and is credited to the profile probed under that
session id, before the session rule and the account rule. A probe is never a session: a hook whose
`session_id` is a remembered probe id appends nothing, and a registry entry with such an id is dropped
before `sessions.poll_changes`. A prober that raises `probe.ProbeFailed` is one stderr line `console:
probe_failed <profile> <kind>`, any other exception `console: probe_failed <profile> <Type>` (never its
message); nothing is appended, so the last reading stays, and the profile's mark is released only once
the prober has returned or raised. A round that escapes is one stderr line `console: probe_round_failed
<Type>: <message>`. `close()` sets the stop event every `probe.Probe` carries and joins the probe loop and
the default dispatch's workers, so a probe still running is killed and reaped (`probe.py`'s Stop) before
it returns, and a probe not yet started runs nothing. The service starts no client itself and opens no
credential file: the prober,
the sign-in reader, the sign-in runs and the account adder are the only seams that run a subprocess.

Sign-in (#1010, ADR-console-022): with a `signin_reader` (`signin.reader_for(sys.platform)` from
`console.py`; none elsewhere than Linux) the same probe job, under the same in-flight mark, schedule and
stop event, first reads the profile's sign-in with the same `probe.Probe`, then runs the prober when
there is one; a service with a reader and no prober still runs the loop and its rounds. The answer is
appended as one `signin.reading` row only when its `(state, ends_at)` differs from the folded one (a
profile with no folded sign-in counts as different), then folded and published. A `signin.StatusFailed`
is one stderr line `console: signin_unknown <profile> <kind>`, any other exception `console:
signin_unknown <profile> <Type>` (never its message); both record `unknown`, so the last answer wins
and an unknown sign-in asks nothing. A stop set during the read records nothing, and a reader that
fails never stops the prober of the same job. The published view and the manager's launch choice are
given the sign-ins, so a signed-out profile is never launched; the quota wait reads the capacity without them.

Sign-in runs (#1026): with `signin_runs` (`signin_run.runs_for(sys.platform)` from `console.py`, called
once as `signin_runs(on_end=...)`; none elsewhere than Linux) the owner starts a profile's own client
login from the page. Every status read of a profile takes a ticket first, and a reading is recorded
only when no reading from a later-ticketed read was recorded before it, so a scheduled read that
finishes after the exit read never overwrites it. When a run's client ends (on its watcher thread,
nothing when `close()` ended it) the service reads the profile's status once at once, with the same
reader and a stop-bound `probe.Probe`, and records the reading by the same rule; a failed end read is
one stderr line `console: signin_end_read_failed <profile> <kind or Type>` and records nothing, so the
profile's earlier reading, its open item and its Sign in action stay. The outcome is `timed_out` or
`cancelled` as the run ended, and for an exit `signed_in` only when the exit status was 0 and that
read says signed in, else `failed`. One `signin.ended` row, carrying the attempt of its start, is then
appended and the view's `signin_runs` is `running` for a live run's attempt, else the folded end. A
thread `SIGNIN_THREAD` calls `expire_signins()` every `SIGNIN_TICK_SECONDS` to enforce the run
deadline. No row, stderr line, view or stream frame carries a link or a code.

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

Messages (#889): `send_message(project_id, sprint_id, text)`, under the ingest lock, raises
`Refused(NOT_OPEN)` unless the sprint is open and belongs to that project, then applies
`sprints.checked_message`; it appends exactly one `sprint.messaged` row `{"sprint_id", "goal",
"text"}` with the text exactly as sent, folds and publishes, and returns the row's `seq`, the
message's id. An approval and a change request need no new code to become messages: the fold makes
them of the `brief.approved` and `brief.replied` rows. `POST /api/inbox` and `POST
/api/message-reply` are manager writes dispatched like `/api/brief`, before `PAGE_WRITES`:
`_checked_length(MAX_INBOX_BYTES)` (4096) or `_checked_length(MAX_MESSAGE_REPLY_BYTES)` (16384),
a body the parser does not accept is 400 `bad inbox` or `bad message reply`, a
`sprints.SecretRefused` is `console: inbox_refused <sprint_id> secret refused` or `console:
message_reply_refused <sprint_id> secret refused` and 403 `secret refused`, any other
`sprints.Refused` the same prefix with the reason and 409, any other exception `console:
inbox_failed <Type>: <message>` or `console: message_reply_failed <Type>: <message>` and 500
`inbox failed` or `message reply failed`. `read_inbox(sprint_id, secret)`, under the lock, is
`_manager_sprint` (`NOT_OPEN`, then `SecretRefused`), then `sprints.unread`; when that is not
empty it appends exactly one `sprint.read` row `{"sprint_id", "through": <last id>}` in the same
locked section and answers 200 `application/json` `{"messages": [...]}` of `sprints.inbox_entry`
dicts in id order, as `json.dumps(answer, sort_keys=True, separators=(",", ":"))`; a second call
with nothing new appends nothing and answers `{"messages":[]}`. `answer_message(sprint_id, secret,
message_id, reply)`, under the lock, is `_manager_sprint`, `Refused(UNKNOWN_MESSAGE)` unless
`message_id` is one of the sprint's messages, `sprints.checked_reply`, then exactly one
`sprint.answered` row `{"sprint_id", "message", "reply"}` with the reply exactly as sent; it
answers 200 `{"at": <row at>}`. Every refusal appends and publishes nothing, and neither the
secret nor the owner's text appears in a stderr line.

Recap (#893): `POST /api/recap` is a manager write dispatched like `/api/inbox`, before `PAGE_WRITES`:
`_checked_length(MAX_RECAP_BYTES)` (4096; any `Origin` is 403 `origin refused`, a media type that
is not `application/json` 415 `json only`, a bad length 411 and one over the limit 413), a body
`sprints.parse_inbox_request` does not accept is 400 `bad recap`, a `sprints.SecretRefused` is
`console: recap_refused <sprint_id> secret refused` and 403 `secret refused`, any other
`sprints.Refused` the same prefix with the reason and 409, any other exception `console:
recap_failed <Type>: <message>` and 500 `recap failed`. `recap(sprint_id, secret)` runs under the
ingest lock and is `_manager_sprint` (`NOT_OPEN`, then `SecretRefused`) and a read: it appends
nothing, publishes nothing and marks nothing read. It answers 200 `application/json`,
`json.dumps(recap, sort_keys=True, separators=(",", ":"))` of `{"sprint_id", "goal", "brief",
"report", "unread"}`: `brief` is null until a brief is sent, else `{"version", "decision" ("none",
"approved" or "changes"), "reply" (the owner's words, or null), "parts"}` of the latest version;
`report` is null until a report is sent, else the last report `{"at", "status", "phase",
"milestone", "tracker_url", "issues": [{"issue", "stage"}, ...], "inbox", "next"}`, which a newer
brief does not remove; `unread` is the number of the owner's messages not yet read.

Questions (#891): `POST /api/ask` is a manager write dispatched like `/api/brief`, before
`PAGE_WRITES`: `_checked_length(MAX_ASK_BYTES)` (65536: any `Origin` 403 `origin refused`, 415, 411,
413), a body `sprints.parse_ask_request` does not accept is 400 `bad round`, a `sprints.SecretRefused`
is `console: ask_refused <sprint_id> secret refused` and 403 `secret refused`, any other
`sprints.Refused` is `console: ask_refused <sprint_id> <reason>` and 409 with the reason, any other
exception is `console: ask_failed <Type>: <message>` and 500 `ask failed`; success is 200
`application/json` `{"questions":<n>,"round":<id>}` (sorted keys, compact). `ask_questions(sprint_id,
secret, round_)`, under the ingest lock, is `_manager_sprint` (`NOT_OPEN`, then `SecretRefused`),
`Refused(NOT_STARTED)` unless the sprint's brief is approved, `Refused(ENDED)` unless
`sprints.takes_questions` (a stopped, closed or ended sprint asks no more), `sprints.checked_round`, then
`Refused(ROUND_OPEN)` when a question is open and the round is not a blocker; it appends exactly one
`questions.asked` row `{"sprint_id", "goal", "blocker", "questions"}` (the checked round), folds,
publishes and returns the row's `seq` (the round's id) and the question count; it nudges nobody.
`answer_question(project_id, sprint_id, round_id, index, choice, text)`, under the lock, raises
`Refused(NOT_OPEN)` unless the sprint is open and of that project, `ENDED` unless
`sprints.takes_questions`, `UNKNOWN_QUESTION` unless
`(round_id, index)` is one of its questions, `ANSWERED_ALREADY` when it is answered, with a choice
`NOT_AN_OPTION` unless it indexes an option, with text whatever `sprints.checked_message` refuses;
the answer is the option or the text exactly, `chosen` the option or None, `differs` is `chosen`
not being the recommendation. It appends exactly one `question.answered` row `{"sprint_id",
"goal", "round", "index", "question", "answer", "chosen", "recommended", "differs"}`, folds,
publishes, nudges the manager as `send_message` does and returns the row's `seq`, the message's id.
Every refusal appends and publishes nothing, and neither the secret nor the owner's text appears
in a stderr line.

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

Closing (#892): `POST /api/close` is a manager write like the report's: no token, the sprint's
secret in its place, `_checked_length(MAX_CLOSE_BYTES)` (65536, the same refusals as the report's:
any `Origin` is 403 `origin refused`, 415 `json only`, 411, 413), then `sprints.parse_close_request`
(a body it does not accept is 400 `bad closing`), then `send_closing(sprint_id, secret, closing)`,
which under the ingest lock refuses in this order, appending and publishing nothing:
`Refused(NOT_OPEN)` or `SecretRefused` (`_manager_sprint`), `Refused(ENDED)` when the sprint has a
closing or `stopped_at`, `Refused(NOT_STARTED)` unless the sprint is `STARTING` or has `stop_at`,
then whatever `sprints.checked_closing` refuses, given the issue numbers of the sprint's latest
report (a stopping sprint is held to the same coverage rule). It appends exactly one `sprint.closed` row
`{"sprint_id", "goal", "closing"}` with the checked closing, folds and publishes, and returns the
row's `at`. A `sprints.SecretRefused` is one stderr line `console: close_refused <sprint_id> secret
refused` and 403 `secret refused`; any other `sprints.Refused` is `console: close_refused
<sprint_id> <reason>` and 409 with the reason; any other exception is `console: close_failed
<Type>: <message>` and 500 `close failed`. Success is 200 `application/json`
`{"at":"<the row's at>"}`. Every refusal is `text/plain`, one line, closes the connection, appends
nothing and publishes nothing. The secret appears in no stderr line or answer.

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
<message>` and the withdrawal still succeeds; then, with a stopper, it stops the manager's session at
once, or once its launch or nudge in flight has ended (below), sending the manager no message and no
nudge. The sprints are folded at construction and in `_fold`
(`sprints.sprint_states`) and handed to `derive_view`; `retain()` re-folds nothing, because goal, brief,
report, closing, stop-request and `manager.stopped` rows are never removed. The secret's value appears in no answer, view, stream frame, row or stderr line.

Managers (#888): the service takes `launcher` (`manager.launcher_for(sys.platform)` from `console.py`;
None means managers are not available on this host, no launch is ever made, no manager row is
written and every sprint reads `unavailable`) and `dispatch` (default None: each launch runs on a new daemon thread named `MANAGER_THREAD`,
`console-manager-launch`; a test passes a stand-in). With a launcher, `state_goal` reserves the new
sprint (`_launching`, changed only under the ingest lock) in the critical section that appends
`goal.stated` and dispatches `_launch_reserved(sprint_id)` after releasing it. `retry_manager(
project_id, sprint_id)`, under the lock, raises `Refused` with `manager.UNAVAILABLE_TEXT` without a
launcher, `NOT_OPEN` unless the sprint is open and of that project, `LAUNCHING` while the sprint is
reserved for a launch or a nudge (`_nudging`; the two never overlap, so a wake never resumes the manager a
retry replaces), and, from `sprints.manager_status`, `HAS_MANAGER` when the manager is started or stalled and `TOO_SOON`
otherwise when no retry is offered (a stalled sprint, and a takeover's failed or waiting manager, offer retry: "try again"); else it reserves the sprint before the lock is released and
dispatches, so a second retry that arrives while the first is queued or running is refused
`LAUNCHING`. `start_manager(sprint_id)` reserves (returning when it cannot, a nudge reservation included) and launches in the
calling thread. `_launch_reserved`, under the lock, drops its own attempt's reservation (each reservation is one token, so a finished attempt never frees a later retry's) and returns when the sprint
is no longer open, has `stop_at` or `stopped_at` (a launch that has not started never starts after
a stop, #892) or its manager reads `started` (a stale or duplicate job never starts a second
manager), and a launch a retry reserved also returns when the sprint no longer offers retry (the
failed manager registered or briefed meanwhile); a missing secret appends `manager.failed` ("the sprint's secret is missing"); the profile
is chosen by `manager.choose_profile` over `capacity.capacity_view` of the profile directories read
at that moment (`_read_profiles`, never the last poll's) with the sign-ins and each profile's last use,
folded from the log's session rows (`manager.profile_use`, kept after a session leaves; ADR-console-023,
#1011) and the excluded profiles folded from the log's `profile.exclusion` rows (`exclusion.excluded_profiles`,
#1028), which `capacity_view` leaves out of the room, and `Wait` appends `manager.waiting`. Otherwise the launcher is called outside the lock, and then,
under it, a sprint that was withdrawn meanwhile has its secret and settings file removed again and
no row appended, and otherwise, unless the service is stopping, `manager.started {sprint_id, profile, session_name}`
or `manager.failed {sprint_id, reason}` is appended (the reason of a `LaunchFailed`, else `<Type>:
<message>`, the secret shown as `<secret>`), a failure is one stderr line `console: manager_failed
<sprint_id> <reason>`, and the view is published. `withdraw_goal` also removes the manager's
settings file. The sprint's secret appears in no row, view or stderr line.

Profile choice (#1011, ADR-console-023): `GET /api/profile` answers the profile a new session should
use, `manager.session_profile` over `capacity.capacity_view` of the profile directories read at that
moment (never the last poll's), the sign-ins, the excluded profiles (folded from the log's
`profile.exclusion` rows, #1028) and each profile's last use, folded from the log's
session rows (`manager.profile_use`, kept after a session leaves and rebuilt on restart). The body
is exactly `{"profile":"<name>"}` (`json.dumps` with sorted keys and compact separators), and
`{"profile":null}` when nothing can be chosen; the route needs no token and, like every GET route,
answers only a loopback `Host`. The service also keeps that choice in `choice_file`
(`default_choice_file()`: `$CLAUDE_ACCOUNTS_DIR/chosen-profile`, else
`~/.claude-accounts/chosen-profile`), one line holding the profile name: it is written, atomically
(`manager.write_choice`), at the end of every `poll_sessions` and on every route answer, only when
the choice differs from the last one written (at construction, what the file holds), and removed when
nothing can be chosen. A failed write is one stderr line `console: choice_unwritten <Type>:
<message>` until a write succeeds, and is tried again at the next choice. With `choice_file` None
no file is read or written.

Exclusion (#1028): `set_exclusion(profile, excluded)` (`POST /api/exclusion`, body `{"profile",
"excluded"}` with `excluded` a bool, at most `MAX_EXCLUSION_BYTES`; a bad body is 400 `bad
exclusion`, a refusal 409 with the reason (`no such profile` unless the profile is among the
directories as they are now, `already excluded`, `already included`), any other failure 500
`exclusion failed`) appends one `profile.exclusion {profile, excluded}` row with no project, and
nothing for a refusal. Under the ingest lock it writes the choice file first, over the set the
toggle gives (`manager.write_choice` directly, not `_note_choice`, which swallows a failed write):
a failed write is a 500 with nothing appended or published and the file as it was, so a 204 never
leaves the file naming an excluded profile; a failed append puts the file back to the choice over the
old set and is a 500. Only then is the row appended, folded and published. The excluded profiles
are folded from the log at construction and by `_fold`, and rebuilt by `retain()`.
`GET /api/excluded` answers them, exactly `{"excluded":["<name>",...]}` in name order (`json.dumps`
with sorted keys and compact separators), behind the same loopback check with no token: the account
launcher asks it before its own fallback, so a profile the owner excluded is never started by the
launcher's guess either (ADR-hosts-008). A manager launch that was prepared before an exclusion is
checked again under the ingest lock immediately before the launcher runs: when its profile has been
excluded since, the choice is made again over the set now in force (a wait row when nothing can be
chosen), so an exclusion that succeeded is never followed by a launch under that profile that was
prepared before it.

Nudges (#889): the service takes `nudger` (`nudge.nudger_for(sys.platform)` from `console.py`; None
means no nudge is ever made, no reservation, row or listing read) and `listing` (default: read
`sessions.read_session_registry(self._session_dirs())` when called). After `send_message`,
`approve_brief` and `reply_brief` append, still under the ingest lock, the sprint is reserved for a
nudge (`_nudging`) when there is a nudger, the sprint is open, its manager row is `started`, no
launch is reserved for it (`_launching`) and `sprints.unread(sprint)` is non-empty; a sprint already reserved is marked in `_nudge_again`
instead. The job is dispatched through `self._dispatch` after the lock is released. A dispatch that
raises is a failed nudge, never the caller's failure (the message is already stored): the
reservation is freed and, while the sprint is open, one `sprint.nudged {sprint_id, through, route:
null, ok: false, reason: "the nudge could not start: <Type>: <message>"}` is appended and
`console: nudge_failed <sprint_id> <reason>` printed, so the route still answers normally.
`_nudge(sprint_id)`, under the lock, drops the reservation and returns unless the sprint is open, its
manager started and something unread (the project's root is the working directory); off the lock
it lists the sessions named `manager.session_name(project, sprint)`: a listed one gets a `RELAY`
`nudge.Nudge` to the lowest session id, else the sprint's `manager_session` gets a `WAKE`, else
there is no nudger call and the reason is `nudge.UNKNOWN_SESSION` with a null route; a `NudgeFailed`
gives its text and any other exception (the listing's included) `<Type>: <message>`. Under the lock
again it releases the reservation and, while the sprint is open and the service is not stopping,
appends one `sprint.nudged {sprint_id, through: the last unread id, route, ok[, reason]}` (a failure
also prints `console: nudge_failed <sprint_id> <reason>`); when the sprint was marked in
`_nudge_again` and now holds an unread message above `through`, it is reserved and dispatched once
more (never after a success alone). `renudge()`, called by `_poll_loop` after `poll_deliveries` (a
failure is `console: renudge_failed <Type>: <message>`), reserves under the lock each open
unreserved sprint with a started manager, `failed_nudges < sprints.UNREACHABLE_AFTER`, an unread
message with no `delivered_at` whose `at` is at least `sprints.RENUDGE_AFTER_MS` before
`self._clock()` and a `last_nudge_at` that is None or as old, and dispatches each after the lock
(row times are compared as epoch milliseconds). The WAKE route (#949) first asks the `full_listing`
seam (`nudge.full_lister_for(sys.platform)`, called `full_listing(profile, cwd)` with the manager row's
profile and the project's root; None means every wake is bare and no read is made) which sessions the
profile's full listing shows, stopped ones included: `_wake_settings` gives `Nudge.settings` None
(bare: no `--name`, no `--settings`) for a session the listing shows, and the sprint's settings file
(`manager.settings_path` in the sprint secrets directory) for one it does not show, because its
record was removed and the client would otherwise resume it under another name without its settings.
A listing that raises is a bare wake whose row carries `"listing_failed": <reason>` (a
`nudge.ListingUnreadable`'s text, else `<Type>: <message>`) and one stderr line `console:
listing_failed <sprint_id> <reason>`; the wake is still sent and `ok` is its own outcome. Before every wake or revive, bare or not,
`_refresh_settings` writes the sprint's settings file again with `manager.write_settings` from the stored
secret (ADR-console-021), so a sprint started before that decision gets the isolation and permission members;
the refresh runs under the ingest lock so a withdrawal cannot fall inside it; a file that cannot be written, a
missing secret and a sprint no longer open are each a failed wake (no wake is sent) with that reason. The full
listing is read only on the wake routes, never for a relay or when the running listing shows the
manager. The nudger, the listing and the full listing are never called with the
ingest lock held, and no `Nudge`, row or stderr line carries the owner's text. No nudge is made while the
sprint's session stop is reserved (`_stopping`) or once the sprint has `stopped_at` (a wake would resume
the stopped manager), and `send_message` refuses `Refused(ENDED)` (409 `this sprint has ended`) a
sprint with `stopped_at` or one that has ended (`sprints.ended_at`), after `NOT_OPEN` and before the
text check, appending nothing. No message nudge is made while the manager's profile is out of quota
(#929, see Idle managers): `_nudgeable` gives None, so `send_message`, `stop_sprint` and `renudge`
reserve nothing and `renudge` sends the held message once the profile is no longer out; `_nudge`
takes the lock again after its listings and, when the sprint is gone or its profile reads out by
then, drops the reservation and returns with no nudger call and no row.

Stops (#892): the service takes `stopper` (`manager.stopper_for(sys.platform)` from `console.py`;
None means a due stop is recorded without a call). `stop_sprint(project_id, sprint_id)`, under the
ingest lock, raises `Refused` with `NOT_OPEN` unless the sprint is open and of that project,
`ALREADY_STOPPING` when it has `stop_at`, `ENDED` when it has `stopped_at` or has ended, each with
nothing appended; else it appends one `sprint.stop_requested {sprint_id, goal}` row (the sprint's one
stop message), folds and publishes, and reserves and dispatches the nudge as `send_message` does.
A withdrawal leaves a pending stop (`_pending`, `sprints.pending_stops`, folded with the sprints at
construction, after the retention pass, and in `_fold`, and handed to `derive_view` as `pending`):
`withdraw_goal` calls `_reserve_stop` under the lock, with a stopper, and dispatches `_stop_session`
after releasing it when that reserved; while a launch or a nudge of the sprint is in flight nothing is
dispatched, the stop stays pending and the first `finish_stops` after they end takes it. A pending
stop is ended for good only by a `manager.stopped` row, which is kept, so it stays ended past
retention and a restart; a withdrawal recorded before this change, with no such row, is stopped on
the first `finish_stops`. A failure (`manager.stop_failed`) leaves it pending, shown in the view's
`unstopped`, and due again `sprints.STOP_RETRY_MS` after it. `finish_stops` also reserves each pending
stop for which `sprints.pending_due` holds, only with a stopper (without one a withdrawal appends
exactly its one `goal.withdrawn` row). `_stop_session` serves a pending stop as well (the open sprint
gone): the session name and the rows' project come from the pending stop, the settle window below
applies, and no row is appended for a sprint that is neither stopping nor pending.
One sprint's launch, nudge and session stop never overlap: `_reserve_stop(sprint_id)`, under the lock,
adds the sprint to `_stopping` only when it is in none of `_stopping`, `_launching` and `_nudging`
(a stop that cannot be reserved stays due and the next `finish_stops` takes it). `finish_stops()`,
called by `_poll_loop` after `renudge` (a failure is `console: stop_poll_failed <Type>: <message>`),
reserves under the lock every sprint for which `sprints.stop_due` or `sprints.done_stop_due` holds
and dispatches each after it; `send_closing` on a sprint with `stop_at` does the same for that
sprint at once. A closing on a sprint without `stop_at` (#980) leaves its session to `finish_stops`:
`done_stop_due` is true once the manager's folded session is idle (`idle.IDLE_STATES`) with a `state_ms`
(`sessions`: the time its state was asserted, not `last_at`) after the closing's, or `sprints.DONE_STOP_WAIT_MS` (two minutes) after the closing, whichever
comes first; `_stop_session` then stops it as below and the `manager.stopped` row folds into
`done_stopped_at`, so it is stopped exactly once, also across a restart. `_nudgeable` is None for a sprint with a closing and no
`stop_at`, so nothing wakes the stopped manager. `_stop_session(sprint_id)`, under the lock, drops the
reservation and returns unless the sprint has `stop_at` and not `stopped_at` (or is a done sprint
whose session is still to stop); off the lock, without
a stopper it makes no listing and no call (a success); with one it reads `listing()` once and, when
no listed session carries the manager's name and the sprint's last launch, nudge or wake (`_settled`, epoch
ms, set under the lock when a reservation ends and, at construction, for every sprint still to be stopped, so a restart keeps the window) ended less than `sprints.STOP_SETTLE_MS` ago, defers
(a session just made may not be listed yet); else `manager.stop_listed([name], ..., stopper)`. Under
the lock again, unless the service is stopping, a deferral appends nothing, a success appends one
`manager.stopped {sprint_id}` and a failure one `manager.stop_failed {sprint_id, reason}` (a
`StopFailed`'s text, else `<Type>: <message>`; one stderr line `console: manager_stop_failed
<sprint_id> <reason>`); a dispatch that raises is a failure with reason `the stop could not start:
<Type>: <message>`. Each row carries the project column and is published. The stopper and the listing
are never called with the ingest lock held.

Bring-back (#893, ADR-console-017): a sprint's manager that is gone while the sprint has work is woken
or replaced. `revive()`, called by `_poll_loop` after `renudge()` (a failure is `console:
revive_failed <Type>: <message>`) and returning at once without a launcher, runs under the ingest lock
over each open sprint: a manager listed (`_manager_listed`) sets `_last_listed[sprint_id]` to now and
the sprint is skipped, as is a sprint reserved for a launch or a nudge. `_revive_step(sprint, now)` is
the one decision, `revive.next_step` over the sprint, `view.sprint_waiting` of its project's open
inbox records (`_waiting`), the time the manager was last listed (in memory, starting at the service's
construction, so a restarted console waits two minutes first), `now`, whether there is a nudger and
whether the manager's profile is out of quota (`out`: no wake then, #929; a takeover is unchanged);
`revive()`, `_revive_wake` and a takeover's `_prepared_launch` all call it, so a queued job is
decided again when it runs. A sprint whose `no_progress_at` is set (#929) is never brought back: the
owner's Continue or Withdraw is the handoff. `STALL` appends one `manager.stalled {sprint_id, goal, reason}` row and
no job; `WAKE` reserves the sprint in `_nudging` and queues `_revive_wake`; `TAKEOVER` reserves it in
`_launching` with a `_TakeoverReservation` and queues the launch. A wake dispatch that raises frees
the reservation and appends one failed `manager.woken` row ("the wake could not start: ..."). The
wake job, off the lock, reads a fresh `listing()` and sends no wake when it shows the manager's name
(it sets `_last_listed` instead and appends nothing); it then reads the full listing as the nudges'
WAKE route does (`_wake_settings`, off the lock, so `Nudge.settings` and the row's `listing_failed`
follow the same rule, #949) and decides again under the lock
(`_wake_due`: open, manager not listed, `_revive_step` still `WAKE`) and sends no wake, appending
nothing, when the sprint was withdrawn or stopped having work during the listing; otherwise it calls
the nudger with the `revive` route and appends `manager.woken {sprint_id, goal, session_id, ok[, reason][, back]}` while the
sprint is open and the service not stopping; a failure also prints `console: wake_failed <sprint_id>
<reason>`, and `back` is true when the wake succeeded and the manager was listed or seen (a newer
`manager_seen_seq`) while the command ran; the reservation's end after a wake was sent, or one that could not start, also sets `_settled`, so a stop that waited out the wake defers for the resumed session. A takeover job reads the listing off the lock (one that
raises ends the reservation and appends nothing), then launches only while the sprint is open,
neither the fresh listing nor the folded sessions show the manager and `_revive_step` is still a
takeover; otherwise it appends nothing. A launch is a takeover when it was reserved by the bring-back
or is a retry of a stalled sprint or of a manager row that is a takeover; every manager row it writes
(`manager.started`, `manager.failed` including the missing-secret one, `manager.waiting`) carries
`"takeover": true` and `"goal"`, every `manager.started` carries `"seen_after"` (the sprint's
`manager_seen_seq` when the launch was prepared, 0 if none) so the fold keeps a session seen while the
launcher returned, and the launch uses `manager.new_launch(..., takeover=True)`. The
nudger, launcher and listing are never called with the ingest lock held; the owner's text and the
secret appear in no new row or stderr line.

Idle managers (#929, ADR-console-020): a manager listed in state `idle` or `limit` while its sprint has
work is told to go on. `_quota_wait(sprint)`, under the ingest lock, is `manager.quota_wait` over
`capacity.capacity_view` of the last poll's profiles (what the view shows) and the manager row's
profile: a `Wait` while that profile reads out. It also keeps the quota mark `_quota_held` (in
memory, lost on a restart): a started manager with work and an account that is out joins it, a
sprint without work leaves it. `_moved` is `idle.last_moved` of the log, rebuilt at construction and
extended by `_fold`, so a run that moved and then ended (`delivery.gone`) still holds the nudge.
`nudge_idle()`, called by `_poll_loop` after `revive()` in its own try (a failure is `console:
idle_nudge_failed <Type>: <message>`) and returning at once without a nudger, runs under the lock
over each open sprint that is in none of `_nudging`, `_launching` and `_stopping`: the manager's
folded session (`_manager_session`, lowest session id), `active` (the larger of that session's last
movement and the sprint's `_settled`, the last launch, nudge or wake), `run_ms` (`_run_moved`: the
latest movement of a run of that session that has not ended: the larger `moved_ms` of its
`_deliveries` rows and of `_run_moves`, which `poll_deliveries` rebuilds each poll with the journal
mtime of every unended run it read, whether or not the run names an issue; a manager with such a
run is not nudged until it has been still for `idle.RUN_STILL_MS`, 30 minutes, #974), the sprint's
waiting count and its quota; a sprint not out whose manager row is not `started` or whose manager is seen
`working` leaves `_quota_held` (resumed without a send, no sentence). Then `idle.next_step` decides:
`GIVE_UP` appends one `manager.no_progress {sprint_id, goal, status}` (the report's status line or
null), `NUDGE` reserves the sprint in `_nudging` and dispatches `_idle_nudge` after the lock.
`_idle_nudge(sprint_id, forced)` decides again under the lock (`_idle_due`), reads the listing off
the lock (a manager not listed sends nothing and appends nothing: the bring-back owns a gone
manager), decides once more under the lock (the quota recheck) and sends nothing when the fresh listing's reading of the manager shows it `working` (`_working_now`: a reading not newer than the session's newest hook does not count), calls the nudger off the lock with a
`continue` route `nudge.Nudge` to the lowest listed session, and appends one `manager.nudged
{sprint_id, goal, session_id, ok[, reason][, resumed]}` while the sprint is open and the service not
stopping (a failure also prints `console: idle_nudge_failed <sprint_id> <reason>`). A dispatch
that raises is a failed nudge with reason `the nudge could not start: <Type>: <message>`. After a
quota wait one send resumes the sprint: the first successful send recorded for a sprint in
`_quota_held` that still has work, whether a held message (`sprint.nudged`), an idle nudge or a wake
(`manager.woken`), carries `"resumed": true` and clears the mark (`_resume`); the idle nudge waits
`idle.IDLE_AFTER_MS` after any send because every send sets `_settled`. `continue_sprint(project_id,
sprint_id)` (`POST /api/continue`, body `{"project_id", "sprint_id"}`, at most `MAX_CONTINUE_BYTES`;
a bad body is 400 `bad continue`, a refusal 409, any other failure 500 `continue failed`) raises
`Refused(NOT_OPEN)` unless the sprint is open and of that project and `Refused(NOT_STUCK)` unless
its `no_progress_at` is set, appending nothing; else it appends one `sprint.continued {sprint_id,
goal}` and, with a nudger and the sprint in none of `_nudging`, `_launching` and `_stopping`,
reserves it and dispatches one forced idle nudge (the idle-time and spacing rules are skipped, every
other rule holds). The nudger, the listing and the full listing are never called with the ingest
lock held, and no row or stderr line carries the owner's text or the sprint's secret.

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
the read health, the deliveries, the sprints, the withdrawn ids and the pending stops, then the last look and the digest moments, from it; publish
the view; sample the registry's signature; `refresh()`; `poll_sessions()`; `poll_deliveries()`. The
absent set starts empty, so a restart drops a session only after two polls miss
it. On any failure after the bind, what was opened is closed and the exception
re-raised. `start()` serves on a daemon thread named `console-http`; `close()`
sets the stop flag, then `closing`, wakes every waiter, joins the watcher, the session poll, the probe loop, the
tracker, retention and digest threads and tears the rest down; it is idempotent.
"""

import dataclasses
import hmac
import http.server
import json
import socketserver
import sys
import os
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Collection, Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl

from agent_tools.claims import owner_actions
from agent_tools.console import (
    account_add, answer, capacity, deliveries, digest, exclusion, idle, inbox, manager, nudge, probe,
    revive, sessions, signin, signin_run, sprints, write_guard)
from agent_tools.console.event_log import (
    BRIEF_APPROVED, BRIEF_REPLIED, BRIEF_SENT, GOAL_STATED, GOAL_WITHDRAWN, MANAGER_FAILED,
    MANAGER_NO_PROGRESS, MANAGER_NUDGED, MANAGER_STALLED, MANAGER_STARTED, MANAGER_STOP_FAILED,
    MANAGER_STOPPED, MANAGER_WAITING, MANAGER_WOKEN, QUESTION_ANSWERED, QUESTIONS_ASKED,
    SPRINT_ANSWERED, SPRINT_CONTINUED, SPRINT_MESSAGED, SPRINT_NUDGED, SPRINT_CLOSED, SPRINT_READ, SPRINT_REPORTED, SPRINT_STOP_REQUESTED, Event,
    EventLog, utc_now)
from agent_tools.console.view import (
    INBOX_CHANGED, ReadState, derive_view, encode_view, health_change, inbox_changes, inbox_records,
    project_for, project_states, read_states, registry_changes, sprint_waiting)
from agent_tools.project_contract import agent_platform
from agent_tools.system.forge_api import ForgeError
from agent_tools.verification import verify_answer

def _epoch_ms(at: str) -> int:
    return int(datetime.fromisoformat(at).timestamp() * 1000)


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
CONTINUE_PATH = "/api/continue"
EXCLUSION_PATH = "/api/exclusion"
BRIEF_PATH = "/api/brief"
REPORT_PATH = "/api/report"
CLOSE_PATH = "/api/close"
STOP_PATH = "/api/stop"
STATUS_PATH = "/api/sprint-status"
PROFILE_PATH = "/api/profile"
EXCLUDED_PATH = "/api/excluded"
MESSAGE_PATH = "/api/message"
INBOX_PATH = "/api/inbox"
MESSAGE_REPLY_PATH = "/api/message-reply"
ASK_PATH = "/api/ask"
ROUND_ANSWER_PATH = "/api/round-answer"
CHECK_PATH = "/api/check-answer"
SIGNIN_PATH = "/api/signin"
SIGNIN_CODE_PATH = "/api/signin-code"
SIGNIN_CANCEL_PATH = "/api/signin-cancel"
ACCOUNT_ADD_PATH = "/api/account-add"
PAGE_WRITES: frozenset[str] = frozenset({
    LOOKED_PATH, ANSWER_PATH, CHECK_PATH, GOAL_PATH, WITHDRAW_PATH, APPROVE_PATH, REPLY_PATH,
    RETRY_PATH, MESSAGE_PATH, STOP_PATH, ROUND_ANSWER_PATH, CONTINUE_PATH, EXCLUSION_PATH,
    SIGNIN_PATH, SIGNIN_CODE_PATH, SIGNIN_CANCEL_PATH, ACCOUNT_ADD_PATH})
MAX_SIGNIN_BYTES = 4096
MAX_ACCOUNT_BYTES = 4096
SIGNIN_THREAD = "console-signin-deadline"
SIGNIN_TICK_SECONDS = 1.0
MAX_ANSWER_BYTES = 4096
MAX_GOAL_BYTES = 16384
MAX_WITHDRAW_BYTES = 4096
MAX_BRIEF_BYTES = 32768
MAX_REPORT_BYTES = 65536
MAX_CLOSE_BYTES = 65536
MAX_STOP_BYTES = 4096
RECAP_PATH = "/api/recap"
MANAGER_WRITES: frozenset[str] = frozenset({BRIEF_PATH, REPORT_PATH, CLOSE_PATH, INBOX_PATH,
                                            MESSAGE_REPLY_PATH, RECAP_PATH, ASK_PATH})
MAX_RECAP_BYTES = 4096
MAX_ASK_BYTES = 65536
MAX_ROUND_ANSWER_BYTES = 16384
MAX_MESSAGE_BYTES = 16384
MAX_INBOX_BYTES = 4096
MAX_MESSAGE_REPLY_BYTES = 16384
MAX_APPROVE_BYTES = 4096
MAX_REPLY_BYTES = 16384
MAX_RETRY_BYTES = 4096
MAX_CONTINUE_BYTES = 4096
MAX_EXCLUSION_BYTES = 4096
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
PROBE_TICK_SECONDS = 15.0
PROBE_LOOP_THREAD = "console-probe-poll"
PROBE_THREAD = "console-probe"


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
    """Every account's config directory: each directory of `profiles/`.

    The unprofiled `~/.claude` is not an account (#1016).
    """
    home = Path.home()
    accounts = os.environ.get("CLAUDE_ACCOUNTS_DIR") or str(home / ".claude-accounts")
    return sorted(p for p in Path(accounts).glob("profiles/*") if p.is_dir())


def default_choice_file() -> Path:
    """The file the console keeps its profile choice in: `chosen-profile` in the accounts directory."""
    accounts = os.environ.get("CLAUDE_ACCOUNTS_DIR") or str(Path.home() / ".claude-accounts")
    return Path(accounts) / manager.CHOICE_FILE


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
        if route == CLOSE_PATH:
            return self._close_request()
        if route == INBOX_PATH:
            return self._inbox_request()
        if route == MESSAGE_REPLY_PATH:
            return self._message_reply_request()
        if route == ASK_PATH:
            return self._ask_request()
        if route == RECAP_PATH:
            return self._recap_request()
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

    def _signin_request(self, console: "ConsoleService", route: str) -> bool:
        """Carry out a sign-in write; True when the shared empty 204 is still to be sent."""
        name = {SIGNIN_PATH: "sign-in", SIGNIN_CODE_PATH: "code", SIGNIN_CANCEL_PATH: "cancel"}[route]
        body = self._json_body(MAX_SIGNIN_BYTES)
        if body is None:
            return False
        try:
            if route == SIGNIN_CODE_PATH:
                profile, code = signin_run.parse_code_request(body)
            else:
                profile = signin_run.parse_profile_request(body)
        except ValueError:
            self._refuse(400, f"bad {name}")
            return False
        answer = None
        try:
            if route == SIGNIN_PATH:
                attempt, link = console.start_signin(profile)
                answer = json.dumps({"attempt": attempt, "link": link}, sort_keys=True,
                                    separators=(",", ":")).encode()
            elif route == SIGNIN_CODE_PATH:
                console.send_signin_code(profile, code)
            else:
                console.cancel_signin(profile)
        except sprints.Refused as error:
            print(f"console: signin_refused {profile} {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except signin_run.StartFailed as error:
            print(f"console: signin_start_failed {profile} {error.kind}", file=sys.stderr)
            self._refuse(502, f"the sign-in could not start: {error.kind}")
            return False
        except OSError as error:
            if route != SIGNIN_CODE_PATH:
                print(f"console: signin_failed {type(error).__name__}", file=sys.stderr)
                self._refuse(500, "sign-in failed")
                return False
            print(f"console: signin_code_failed {profile} {type(error).__name__}", file=sys.stderr)
            self._refuse(502, "the code could not be passed on")
            return False
        except Exception as error:
            print(f"console: signin_failed {type(error).__name__}", file=sys.stderr)
            self._refuse(500, "sign-in failed")
            return False
        if answer is None:
            return True
        try:
            self._send(200, "application/json", answer, ("Connection", "close"))
            self.wfile.flush()
        except OSError:
            pass
        return False

    def _account_request(self, console: "ConsoleService") -> bool:
        """Carry out the add-account write; it answers itself, so this is always False."""
        body = self._json_body(MAX_ACCOUNT_BYTES)
        if body is None:
            return False
        try:
            name = account_add.parse_add_request(body)
        except ValueError:
            self._refuse(400, "bad account")
            return False
        try:
            attempt, link = console.add_account(name)
        except sprints.Refused as error:
            print(f"console: account_add_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except account_add.AddFailed as error:
            print(f"console: account_add_failed {name} {error.kind}", file=sys.stderr)
            self._refuse(502, f"the account could not be created: {error.kind}")
            return False
        except signin_run.StartFailed as error:
            print(f"console: signin_start_failed {name} {error.kind}", file=sys.stderr)
            self._refuse(502, f"the account was added; its sign-in could not start: {error.kind}")
            return False
        except Exception as error:
            print(f"console: account_add_failed {type(error).__name__}", file=sys.stderr)
            self._refuse(500, "adding the account failed")
            return False
        answer = json.dumps({"attempt": attempt, "link": link, "profile": name}, sort_keys=True,
                            separators=(",", ":")).encode()
        try:
            self._send(200, "application/json", answer, ("Connection", "close"))
            self.wfile.flush()
        except OSError:
            pass
        return False

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

    def _close_request(self):
        """The manager's route: a closing report sent with the sprint's secret; no token, no page."""
        console = self.server.console
        length = self._checked_length(MAX_CLOSE_BYTES)
        if length is None:
            return
        self.close_connection = True
        try:
            sprint_id, secret, closing = sprints.parse_close_request(self.rfile.read(length))
        except ValueError:
            return self._refuse(400, "bad closing")
        try:
            at = console.send_closing(sprint_id, secret, closing)
        except sprints.SecretRefused:
            print(f"console: close_refused {sprint_id} {sprints.SECRET_REFUSED}", file=sys.stderr)
            return self._refuse(403, sprints.SECRET_REFUSED)
        except sprints.Refused as error:
            print(f"console: close_refused {sprint_id} {error}", file=sys.stderr)
            return self._refuse(409, str(error))
        except Exception as error:
            print(f"console: close_failed {type(error).__name__}: {error}", file=sys.stderr)
            return self._refuse(500, "close failed")
        self._send(200, "application/json", json.dumps({"at": at}, separators=(",", ":")).encode())

    def _inbox_request(self):
        """The manager's route: the unread messages, read with the sprint's secret."""
        length = self._checked_length(MAX_INBOX_BYTES)
        if length is None:
            return
        self.close_connection = True
        try:
            sprint_id, secret = sprints.parse_inbox_request(self.rfile.read(length))
        except ValueError:
            return self._refuse(400, "bad inbox")
        try:
            entries = self.server.console.read_inbox(sprint_id, secret)
        except sprints.SecretRefused:
            print(f"console: inbox_refused {sprint_id} {sprints.SECRET_REFUSED}", file=sys.stderr)
            return self._refuse(403, sprints.SECRET_REFUSED)
        except sprints.Refused as error:
            print(f"console: inbox_refused {sprint_id} {error}", file=sys.stderr)
            return self._refuse(409, str(error))
        except Exception as error:
            print(f"console: inbox_failed {type(error).__name__}: {error}", file=sys.stderr)
            return self._refuse(500, "inbox failed")
        self._send(200, "application/json", json.dumps(
            {"messages": entries}, sort_keys=True, separators=(",", ":")).encode())

    def _recap_request(self):
        """The manager's route: the sprint's record, read with the sprint's secret."""
        length = self._checked_length(MAX_RECAP_BYTES)
        if length is None:
            return
        self.close_connection = True
        try:
            sprint_id, secret = sprints.parse_inbox_request(self.rfile.read(length))
        except ValueError:
            return self._refuse(400, "bad recap")
        try:
            recap = self.server.console.recap(sprint_id, secret)
        except sprints.SecretRefused:
            print(f"console: recap_refused {sprint_id} {sprints.SECRET_REFUSED}", file=sys.stderr)
            return self._refuse(403, sprints.SECRET_REFUSED)
        except sprints.Refused as error:
            print(f"console: recap_refused {sprint_id} {error}", file=sys.stderr)
            return self._refuse(409, str(error))
        except Exception as error:
            print(f"console: recap_failed {type(error).__name__}: {error}", file=sys.stderr)
            return self._refuse(500, "recap failed")
        self._send(200, "application/json", json.dumps(
            recap, sort_keys=True, separators=(",", ":")).encode())

    def _message_reply_request(self):
        """The manager's route: an answer to one message, sent with the sprint's secret."""
        length = self._checked_length(MAX_MESSAGE_REPLY_BYTES)
        if length is None:
            return
        self.close_connection = True
        try:
            sprint_id, secret, message, reply = sprints.parse_message_reply_request(
                self.rfile.read(length))
        except ValueError:
            return self._refuse(400, "bad message reply")
        try:
            at = self.server.console.answer_message(sprint_id, secret, message, reply)
        except sprints.SecretRefused:
            print(f"console: message_reply_refused {sprint_id} {sprints.SECRET_REFUSED}",
                  file=sys.stderr)
            return self._refuse(403, sprints.SECRET_REFUSED)
        except sprints.Refused as error:
            print(f"console: message_reply_refused {sprint_id} {error}", file=sys.stderr)
            return self._refuse(409, str(error))
        except Exception as error:
            print(f"console: message_reply_failed {type(error).__name__}: {error}",
                  file=sys.stderr)
            return self._refuse(500, "message reply failed")
        self._send(200, "application/json", json.dumps({"at": at}, separators=(",", ":")).encode())

    def _ask_request(self):
        """The manager's route: a round of questions sent with the sprint's secret."""
        length = self._checked_length(MAX_ASK_BYTES)
        if length is None:
            return
        self.close_connection = True
        try:
            sprint_id, secret, round_ = sprints.parse_ask_request(self.rfile.read(length))
        except ValueError:
            return self._refuse(400, "bad round")
        try:
            round_id, count = self.server.console.ask_questions(sprint_id, secret, round_)
        except sprints.SecretRefused:
            print(f"console: ask_refused {sprint_id} {sprints.SECRET_REFUSED}", file=sys.stderr)
            return self._refuse(403, sprints.SECRET_REFUSED)
        except sprints.Refused as error:
            print(f"console: ask_refused {sprint_id} {error}", file=sys.stderr)
            return self._refuse(409, str(error))
        except Exception as error:
            print(f"console: ask_failed {type(error).__name__}: {error}", file=sys.stderr)
            return self._refuse(500, "ask failed")
        self._send(200, "application/json", json.dumps(
            {"questions": count, "round": round_id}, sort_keys=True,
            separators=(",", ":")).encode())

    def _round_answer_request(self, console: "ConsoleService") -> bool:
        """Read and carry out the owner's answer to one question; False when it was refused."""
        body = self._json_body(MAX_ROUND_ANSWER_BYTES)
        if body is None:
            return False
        try:
            parsed = sprints.parse_round_answer(body)
        except ValueError:
            self._refuse(400, "bad round answer")
            return False
        try:
            console.answer_question(*parsed)
        except sprints.Refused as error:
            print(f"console: round_answer_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: round_answer_failed {type(error).__name__}: {error}",
                  file=sys.stderr)
            self._refuse(500, "round answer failed")
            return False
        return True

    def _message_request(self, console: "ConsoleService") -> bool:
        """Read and carry out an owner's message; False when it was refused."""
        body = self._json_body(MAX_MESSAGE_BYTES)
        if body is None:
            return False
        try:
            parsed = sprints.parse_message(body)
        except ValueError:
            self._refuse(400, "bad message")
            return False
        try:
            console.send_message(*parsed)
        except sprints.Refused as error:
            print(f"console: message_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: message_failed {type(error).__name__}: {error}", file=sys.stderr)
            self._refuse(500, "message failed")
            return False
        return True

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

    def _continue_request(self, console: "ConsoleService") -> bool:
        """Read and carry out the owner's tell-it-to-continue; False when it was refused."""
        body = self._json_body(MAX_CONTINUE_BYTES)
        if body is None:
            return False
        try:
            project_id, sprint_id = sprints.parse_continue(body)
        except ValueError:
            self._refuse(400, "bad continue")
            return False
        try:
            console.continue_sprint(project_id, sprint_id)
        except sprints.Refused as error:
            print(f"console: continue_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: continue_failed {type(error).__name__}: {error}", file=sys.stderr)
            self._refuse(500, "continue failed")
            return False
        return True

    def _exclusion_request(self, console: "ConsoleService") -> bool:
        """Read and carry out the owner's exclusion or inclusion of a profile; False when refused."""
        body = self._json_body(MAX_EXCLUSION_BYTES)
        if body is None:
            return False
        try:
            profile, excluded = exclusion.parse_request(body)
        except ValueError:
            self._refuse(400, "bad exclusion")
            return False
        try:
            console.set_exclusion(profile, excluded)
        except exclusion.Refused as error:
            print(f"console: exclusion_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: exclusion_failed {type(error).__name__}: {error}", file=sys.stderr)
            self._refuse(500, "exclusion failed")
            return False
        return True

    def _stop_request(self, console: "ConsoleService") -> bool:
        """Read and carry out an owner's stop of a sprint; False when it was refused."""
        body = self._json_body(MAX_STOP_BYTES)
        if body is None:
            return False
        try:
            project_id, sprint_id = sprints.parse_stop(body)
        except ValueError:
            self._refuse(400, "bad stop")
            return False
        try:
            console.stop_sprint(project_id, sprint_id)
        except sprints.Refused as error:
            print(f"console: stop_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: stop_failed {type(error).__name__}: {error}", file=sys.stderr)
            self._refuse(500, "stop failed")
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
        elif route == CONTINUE_PATH:
            self.close_connection = True
            if not self._continue_request(console):
                return
        elif route == EXCLUSION_PATH:
            self.close_connection = True
            if not self._exclusion_request(console):
                return
        elif route == MESSAGE_PATH:
            self.close_connection = True
            if not self._message_request(console):
                return
        elif route == ROUND_ANSWER_PATH:
            self.close_connection = True
            if not self._round_answer_request(console):
                return
        elif route == STOP_PATH:
            self.close_connection = True
            if not self._stop_request(console):
                return
        elif route in (SIGNIN_PATH, SIGNIN_CODE_PATH, SIGNIN_CANCEL_PATH):
            self.close_connection = True
            if not self._signin_request(console, route):
                return
        elif route == ACCOUNT_ADD_PATH:
            self.close_connection = True
            if not self._account_request(console):
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
        elif route == PROFILE_PATH:
            body = json.dumps({"profile": self.server.console.session_profile()},
                              sort_keys=True, separators=(",", ":")).encode()
            self._send(200, "application/json", body)
        elif route == EXCLUDED_PATH:
            body = json.dumps({"excluded": self.server.console.excluded_profiles()},
                              sort_keys=True, separators=(",", ":")).encode()
            self._send(200, "application/json", body)
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


class _TakeoverReservation:
    """A launch reservation made by the bring-back: it runs only while the takeover is still decided."""


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
                 dispatch: Callable[[Callable[[], None]], None] | None = None,
                 nudger: Callable[[nudge.Nudge], None] | None = None,
                 listing: Callable[[], Mapping[str, sessions.Observation]] | None = None,
                 stopper: Callable[[str, str], None] | None = None,
                 full_listing: Callable[[str, str], Collection[str]] | None = None,
                 prober: Callable[[probe.Probe], None] | None = None,
                 signin_reader: Callable[[probe.Probe], signin.Status] | None = None,
                 signin_runs: Callable[..., signin_run.SignIns] | None = None,
                 account_adder: Callable[[str], None] | None = None,
                 probe_dispatch: Callable[[Callable[[], None]], None] | None = None,
                 probe_tick_seconds: float = PROBE_TICK_SECONDS,
                 choice_file: Path | None = None):
        self.registry = Path(registry)
        self._choice_file = choice_file
        self._choice = manager.read_choice(choice_file) if choice_file is not None else None
        self._prober = prober
        self._signin_reader = signin_reader
        self._account_adder = account_adder
        self._adding = threading.Lock()
        self._probe_dispatch = self._on_probe_thread if probe_dispatch is None else probe_dispatch
        self._probe_tick_seconds = probe_tick_seconds
        self._probe_since = clock()
        self._probing: set[str] = set()
        self._probe_started: dict[str, float] = {}
        self._probe_sessions: OrderedDict[str, str] = OrderedDict()
        self._probe_live: dict[str, str] = {}
        self._probe_workers: list[threading.Thread] = []
        self._probe_thread: threading.Thread | None = None
        self._nudger = nudger
        self._full_listing = full_listing
        self._stopper = stopper
        self._stopping: set[str] = set()
        self._pending: dict[str, sprints.PendingStop] = {}
        self._settled: dict[str, int] = {}
        self._quota_held: set[str] = set()
        self._moved: dict[str, int] = {}
        self._listing = (
            (lambda: sessions.read_session_registry(self._session_dirs()))
            if listing is None else listing)
        self._nudging: set[str] = set()
        self._nudge_again: set[str] = set()
        self._launcher = launcher
        self._dispatch = self._on_new_thread if dispatch is None else dispatch
        self._launching: dict[str, object] = {}
        self._last_listed: dict[str, int] = {}
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
        self._signins: dict[str, signin.SignIn] = {}
        self._excluded: frozenset[str] = frozenset()
        self._signin_ends: dict[str, signin_run.Ended] = {}
        self._accounts_added: frozenset[str] = frozenset()
        self._signin_live: dict[str, int] = {}
        self._signin_by_run: dict[int, tuple[str, int]] = {}
        self._signin_tickets: dict[str, int] = {}
        self._signin_recorded: dict[str, int] = {}
        self._signin_thread: threading.Thread | None = None
        self._session_poll_seconds = session_poll_seconds
        self._repo_of = repo_of
        self._sessions: dict[str, sessions.SessionState] = {}
        self._use = manager.ProfileUse({}, {})
        self._absent: frozenset[str] = frozenset()
        self._deliveries: dict[tuple[str, str], deliveries.DeliveryState] = {}
        self._reader = deliveries.JournalReader()
        self._runs: dict[Path, deliveries.RunFold] = {}
        self._run_moves: dict[tuple[str, str], int] = {}
        self._unreadable: set[str] = set()
        self._session_poller: threading.Thread | None = None
        self._tracker = tracker
        self._tracker_seconds = tracker_seconds
        self._slug_of = slug_of
        self._branch_pattern_of = branch_pattern_of
        self._patterns: dict[str, str] = {}
        self._activity = activity
        self._clock = clock
        self._revive_since_ms = int(clock() * 1000)
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
        self._signin_runs = None if signin_runs is None else signin_runs(on_end=self._signin_ended)
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
            self._use = manager.profile_use(events)
            self._inbox = inbox_records(events)
            self._health = read_states(events)
            self._capacity = capacity.capacity_state(events)
            self._signins = signin.signin_state(events)
            self._excluded = exclusion.excluded_profiles(events)
            self._signin_ends = signin_run.ended_state(events)
            self._accounts_added = account_add.added_state(events)
            self._derive_digest(events)
            self._deliveries = deliveries.delivery_states(events)
            self._moved = idle.last_moved(events)
            self._sprints = sprints.sprint_states(events)
            self._withdrawn = sprints.withdrawn_ids(events)
            self._pending = sprints.pending_stops(events)
            self._settle_stops()
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

    def _signin_view(self) -> dict[str, dict]:
        runs = {profile: {"state": end.outcome, "at": end.at, "attempt": end.attempt}
                for profile, end in self._signin_ends.items()}
        for profile, attempt in self._signin_live.items():
            runs[profile] = {"state": "running", "at": None, "attempt": attempt}
        return runs

    def _publish(self) -> None:
        view = encode_view(derive_view(
            self._states.values(), self._inbox, self._health,
            sessions=self._sessions.values(), deliveries=self._deliveries,
            now_ms=int(self._clock() * 1000), sprints=self._sprints,
            digest=digest.digest(self._moments, self._looked, self._now()),
            capacity=capacity.capacity_view(
                self._profiles, self._capacity, self._clock(), self._signins,
                excluded=self._excluded),
            signin_runs=self._signin_view(), accounts_added=self._accounts_added,
            managers=self._launcher is not None, pending=self._pending))
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
            if isinstance(document, dict):
                probed = document.get("session_id")
                if isinstance(probed, str) and self._probe_profile(probed) is not None:
                    return []
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
            profile = self._probe_profile(report["session_id"])
            known = self._sessions.get(report["session_id"])
            if profile is None and known is not None:
                profile = known.profile
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

    def _on_probe_thread(self, job: Callable[[], None]) -> None:
        worker = threading.Thread(target=job, name=PROBE_THREAD, daemon=True)
        with self._ingest:
            self._probe_workers = [w for w in self._probe_workers if w.is_alive()]
            self._probe_workers.append(worker)
        worker.start()

    def _probe_profile(self, session_id: str) -> str | None:
        """Under the ingest lock: the profile a pending, running or remembered probe session probed."""
        profile = self._probe_live.get(session_id)
        return profile if profile is not None else self._probe_sessions.get(session_id)

    def _retire_probe(self, one: probe.Probe) -> None:
        """Under the ingest lock: a probe that is over moves to the bounded history of probes."""
        if self._probe_live.pop(one.session_id, None) is not None:
            self._probe_sessions[one.session_id] = one.profile
        while len(self._probe_sessions) > probe.PROBE_MEMORY:
            self._probe_sessions.popitem(last=False)

    def probe_round(self) -> list[probe.Probe]:
        """Start a probe of every profile that is due and return them in profile order.

        A dispatch that fails frees the in-flight mark of its probe and of every probe not yet
        dispatched, so those profiles are probed again at the next due time.
        """
        if self._prober is None and self._signin_reader is None:
            return []
        with self._ingest:
            now = self._clock()
            probes = []
            for profile in probe.due_profiles(
                    self._profiles, self._probing, self._probe_started, self._probe_since, now):
                one = probe.Probe(profile, str(uuid.uuid4()), self._stop)
                self._probing.add(profile)
                self._probe_started[profile] = now
                self._probe_live[one.session_id] = profile
                probes.append(one)
        for at, one in enumerate(probes):
            try:
                self._probe_dispatch(lambda one=one: self._run_probe(one))
            except BaseException:
                with self._ingest:
                    for unrun in probes[at:]:
                        self._probing.discard(unrun.profile)
                        self._retire_probe(unrun)
                raise
        return probes

    def _signin_ticket(self, profile: str) -> int:
        with self._ingest:
            ticket = self._signin_tickets.get(profile, 0) + 1
            self._signin_tickets[profile] = ticket
            return ticket

    def _read_signin(self, one: probe.Probe) -> None:
        """Read the profile's sign-in and record it; a failed read records `unknown`."""
        ticket = self._signin_ticket(one.profile)
        try:
            status = self._signin_reader(one)
        except signin.StatusFailed as error:
            status = signin.UNKNOWN
            if not self._stop.is_set():
                print(f"console: signin_unknown {one.profile} {error.kind}", file=sys.stderr)
        except Exception as error:
            status = signin.UNKNOWN
            if not self._stop.is_set():
                print(f"console: signin_unknown {one.profile} {type(error).__name__}",
                      file=sys.stderr)
        if not self._stop.is_set():
            self._record_signin(one.profile, status, ticket)

    def _record_signin(self, profile: str, status: signin.Status, ticket: int) -> None:
        with self._ingest:
            if ticket < self._signin_recorded.get(profile, 0):
                return
            self._signin_recorded[profile] = ticket
            folded = self._signins.get(profile)
            if folded is not None and (folded.state, folded.ends_at) == (
                    status.state, status.ends_at):
                return
            self._fold(self.log.append([signin.entry(profile, status)]))
            self._publish()

    def _read_signin_now(self, profile: str, when: str) -> signin.Status | None:
        """The status read at once (`when` is "end" or "add"); a failed read records nothing."""
        ticket = self._signin_ticket(profile)
        try:
            status = self._signin_reader(probe.Probe(profile, str(uuid.uuid4()), self._stop))
        except signin.StatusFailed as error:
            print(f"console: signin_{when}_read_failed {profile} {error.kind}", file=sys.stderr)
            return None
        except Exception as error:
            print(f"console: signin_{when}_read_failed {profile} {type(error).__name__}",
                  file=sys.stderr)
            return None
        self._record_signin(profile, status, ticket)
        return status

    def _signin_ended(self, profile: str, run: int, end: str, returncode: int | None) -> None:
        """A client ended (called on the run's watcher thread): read once, then one `ended` row."""
        if self._stop.is_set():
            return
        with self._ingest:
            found = self._signin_by_run.pop(run, None)
        if found is None:
            return
        attempt = found[1]
        status = None
        if self._signin_reader is not None:
            status = self._read_signin_now(profile, "end")
        if end != "exited":
            outcome = end
        elif returncode == 0 and status is not None and status.state == "signed_in":
            outcome = "signed_in"
        else:
            outcome = "failed"
        if self._stop.is_set():
            return
        with self._ingest:
            self._fold(self.log.append([signin_run.ended(profile, outcome, attempt)]))
            if self._signin_live.get(profile) == attempt:
                del self._signin_live[profile]
            self._publish()

    def _signin_refuse_unless_listed(self, profile: str) -> signin_run.SignIns:
        if self._signin_runs is None:
            raise sprints.Refused("sign-in is not available on this host")
        if profile not in self._profiles:
            raise sprints.Refused("unknown profile")
        return self._signin_runs

    def _record_signin_action(self, profile: str, action: str, outcome: str) -> Event:
        appended = self.log.append([signin_run.acted(profile, action, outcome)])
        self._fold(appended)
        return appended[0]

    def start_signin(self, profile: str) -> tuple[int, str | None]:
        """Start the profile's client login, or join the live one; the attempt and the link."""
        runs = self._signin_refuse_unless_listed(profile)
        with self._ingest:
            try:
                started = runs.start(profile)
            except signin_run.StartFailed:
                self._record_signin_action(profile, "start", "failed")
                self._publish()
                raise
            if started.fresh:
                attempt = self._record_signin_action(profile, "start", "started").seq
                self._signin_live[profile] = attempt
                self._signin_by_run[started.run] = (profile, attempt)
            else:
                self._record_signin_action(profile, "start", "running")
                attempt = self._signin_live[profile]
            self._publish()
        return attempt, runs.wait_link(profile)

    def add_account(self, name: str) -> tuple[int, str | None]:
        """Create the account through the launcher, then start its sign-in; the attempt and link."""
        if self._account_adder is None or self._signin_runs is None or self._signin_reader is None:
            raise sprints.Refused(account_add.UNAVAILABLE)
        reason = account_add.refusal(name)
        if reason is not None:
            raise sprints.Refused(reason)
        with self._adding:
            if name in self._read_profiles():
                raise sprints.Refused(account_add.already_exists(name))
            self._account_adder(name)
            listed = self._read_profiles()
            if name not in listed:
                raise account_add.AddFailed("not_listed")
            with self._ingest:
                self._profiles = listed
                self._fold(self.log.append([account_add.added(name)]))
                self._publish()
        self._read_signin_now(name, "add")
        return self.start_signin(name)

    def send_signin_code(self, profile: str, code: str) -> None:
        runs = self._signin_refuse_unless_listed(profile)
        with self._ingest:
            if profile not in runs.running():
                raise sprints.Refused(f"no sign-in is running for {profile}")
            try:
                runs.send_code(profile, code)
            except signin_run.NotRunning:
                raise sprints.Refused(f"no sign-in is running for {profile}") from None
            self._record_signin_action(profile, "code", "sent")
            self._publish()

    def cancel_signin(self, profile: str) -> None:
        runs = self._signin_refuse_unless_listed(profile)
        with self._ingest:
            if profile not in runs.running():
                raise sprints.Refused(f"no sign-in is running for {profile}")
            try:
                runs.cancel(profile)
            except signin_run.NotRunning:
                raise sprints.Refused(f"no sign-in is running for {profile}") from None
            self._record_signin_action(profile, "cancel", "cancelled")
            self._publish()

    def expire_signins(self) -> list[str]:
        """End every sign-in run past its deadline; the profiles ended."""
        return [] if self._signin_runs is None else self._signin_runs.expire()

    def _signin_loop(self) -> None:
        while not self._stop.wait(SIGNIN_TICK_SECONDS):
            try:
                self.expire_signins()
            except Exception as error:
                print(f"console: signin_expire_failed {type(error).__name__}", file=sys.stderr)

    def _run_probe(self, one: probe.Probe) -> None:
        try:
            if self._signin_reader is not None and not self._stop.is_set():
                self._read_signin(one)
            if self._prober is not None and not self._stop.is_set():
                self._prober(one)
        except probe.ProbeFailed as error:
            if not self._stop.is_set():
                print(f"console: probe_failed {one.profile} {error.kind}", file=sys.stderr)
        except Exception as error:
            if not self._stop.is_set():
                print(f"console: probe_failed {one.profile} {type(error).__name__}",
                      file=sys.stderr)
        finally:
            with self._ingest:
                self._probing.discard(one.profile)
                self._retire_probe(one)

    def _probe_loop(self) -> None:
        while not self._stop.wait(self._probe_tick_seconds):
            try:
                self.probe_round()
            except Exception as error:
                print(f"console: probe_round_failed {type(error).__name__}: {error}",
                      file=sys.stderr)

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

    def _manager_session(self, sprint: sprints.SprintState) -> sessions.SessionState | None:
        """The folded session a listed manager is: the lowest session id carrying its name, or None."""
        name = manager.session_name(sprint.project_id, sprint.sprint_id)
        return min((s for s in self._sessions.values()
                    if s.name == name and s.state != sessions.ENDED and s.repo is not None
                    and project_for(s.repo, self._states) == sprint.project_id),
                   key=lambda s: s.session_id, default=None)

    def _manager_listed(self, sprint: sprints.SprintState) -> bool:
        """Whether a listed session of the sprint's project carries the sprint's manager name."""
        return self._manager_session(sprint) is not None

    def _waiting(self, sprint: sprints.SprintState) -> int:
        """Under the ingest lock: how many open records of the sprint's project wait on the owner."""
        records = [r for r in self._inbox.values()
                   if r.item.get("project_id") == sprint.project_id and not r.item["answered"]]
        return sprint_waiting(sprint, records)

    def _quota_wait(self, sprint: sprints.SprintState) -> manager.Wait | None:
        """Under the ingest lock: where the sprint's manager waits for quota, None when its account has room.

        Also keeps the quota mark (`_quota_held`): a started manager with work and an account that is
        out joins it, a sprint without work leaves it.
        """
        wait = manager.quota_wait(
            capacity.capacity_view(self._profiles, self._capacity, self._clock()),
            sprint.manager.profile if sprint.manager else None)
        if wait is not None or sprint.sprint_id in self._quota_held:
            if not idle.has_work(sprint, self._waiting(sprint)):
                self._quota_held.discard(sprint.sprint_id)
            elif wait is not None and sprint.manager.state == sprints.STARTED:
                self._quota_held.add(sprint.sprint_id)
        return wait

    def _resume(self, sprint_id: str) -> bool:
        """Under the ingest lock, for a send that succeeded: whether it resumes a sprint held for quota."""
        held = sprint_id in self._quota_held
        self._quota_held.discard(sprint_id)
        sprint = self._sprints.get(sprint_id)
        return held and sprint is not None and idle.has_work(sprint, self._waiting(sprint))

    def _held_for_quota(self, sprint_id: str) -> bool:
        """Under the ingest lock: whether a send to the sprint must not go: it is gone or its account is out."""
        sprint = self._sprints.get(sprint_id)
        return sprint is None or self._quota_wait(sprint) is not None

    def _manager_state(self, sprint: sprints.SprintState) -> tuple[str, str | None, bool]:
        return sprints.manager_status(
            sprint, self._manager_listed(sprint), int(self._clock() * 1000), True)

    def start_manager(self, sprint_id: str) -> None:
        """Reserve the sprint's launch and run it in this thread; nothing when it cannot be reserved."""
        with self._ingest:
            if (self._launcher is None or sprint_id not in self._sprints
                    or sprint_id in self._launching or sprint_id in self._nudging):
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
            if sprint_id in self._launching or sprint_id in self._nudging:
                raise sprints.Refused(sprints.LAUNCHING)
            state, _, retry = self._manager_state(sprint)
            if not retry:
                raise sprints.Refused(
                    sprints.HAS_MANAGER if state in (sprints.STARTED, sprints.STALLED)
                    else sprints.TOO_SOON)
            self._launching[sprint_id] = _RetryReservation()
        self._dispatch_launch(sprint_id)

    def _launch_reserved(self, sprint_id: str) -> None:
        """Start the reserved sprint's manager and record the outcome; the reservation ends here."""
        with self._ingest:
            token = self._launching.get(sprint_id)
        if token is None:
            return
        try:
            listed = None
            if isinstance(token, _TakeoverReservation):
                try:
                    listed = self._listing()
                except Exception as error:
                    print(f"console: revive_failed {type(error).__name__}: {error}",
                          file=sys.stderr)
                    return
            with self._ingest:
                launch = self._prepared_launch(sprint_id, token, listed)
            if launch is None:
                return
            with self._ingest:
                launch = self._unexcluded_launch(launch, token)
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
                self._settled[sprint_id] = int(self._clock() * 1000)

    def _prepared_launch(self, sprint_id: str, token: object,
                         listed: Mapping[str, sessions.Observation] | None = None
                         ) -> manager.Launch | None:
        """Under the ingest lock: the launch to run, or None after dropping the reservation."""
        sprint = self._sprints.get(sprint_id)
        if (sprint is None or sprint.stop_at is not None or sprint.stopped_at is not None
                or sprint.closing is not None):
            self._release(sprint_id, token)
            return None
        if isinstance(token, _TakeoverReservation):
            now = int(self._clock() * 1000)
            name = manager.session_name(sprint.project_id, sprint_id)
            shown = any(o.name == name for o in (listed or {}).values())
            if shown:
                self._last_listed[sprint_id] = now
            if (shown or self._manager_listed(sprint)
                    or self._revive_step(sprint, now) != sprints.TAKEOVER):
                self._release(sprint_id, token)
                return None
        elif (self._manager_state(sprint)[0] == sprints.STARTED
                or (isinstance(token, _RetryReservation) and not self._manager_state(sprint)[2])):
            self._release(sprint_id, token)
            return None
        takeover = isinstance(token, _TakeoverReservation) or (
            isinstance(token, _RetryReservation)
            and (sprint.stalled is not None
                 or (sprint.manager is not None and sprint.manager.takeover)))
        marks = {"takeover": True, "goal": sprint.goal} if takeover else {}
        project_id = sprint.project_id
        secret = sprints.read_secret(self._sprint_secrets, sprint_id)
        if secret is None:
            self._append_manager(MANAGER_FAILED, project_id, {
                "sprint_id": sprint_id, "reason": "the sprint's secret is missing", **marks}, token)
            return None
        project = self._states.get(project_id)
        if project is None:
            self._release(sprint_id, token)
            return None
        choice = manager.choose_profile(
            capacity.capacity_view(self._read_profiles(), self._capacity, self._clock(),
                                   self._signins, excluded=self._excluded),
            self._use.last)
        if isinstance(choice, manager.Wait):
            self._append_manager(MANAGER_WAITING, project_id, {
                "sprint_id": sprint_id, "until": choice.until, **marks}, token)
            return None
        return manager.new_launch(sprint_id, project_id, sprint.goal, project.root, choice,
                                  secret, self._sprint_secrets, takeover=takeover,
                                  seen_after=sprint.manager_seen_seq or 0)

    def _unexcluded_launch(self, launch: manager.Launch, token: object) -> manager.Launch | None:
        """Under the ingest lock: `launch`, or its replacement when its profile was excluded after it was prepared.

        The choice is made again over the set now in force; with nothing to choose a wait row is
        appended (as `_prepared_launch` does) and None returned.
        """
        if launch.profile not in self._excluded:
            return launch
        sprint = self._sprints.get(launch.sprint_id)
        if sprint is None:
            self._release(launch.sprint_id, token)
            return None
        choice = manager.choose_profile(
            capacity.capacity_view(self._read_profiles(), self._capacity, self._clock(),
                                   self._signins, excluded=self._excluded),
            self._use.last)
        if isinstance(choice, manager.Wait):
            marks = {"takeover": True, "goal": sprint.goal} if launch.takeover else {}
            self._append_manager(MANAGER_WAITING, launch.project_id, {
                "sprint_id": launch.sprint_id, "until": choice.until, **marks}, token)
            return None
        return dataclasses.replace(launch, profile=choice)

    def _append_manager(self, kind: str, project_id: str, payload: dict, token: object) -> None:
        """Under the ingest lock: append one manager row, release the attempt's hold, publish."""
        self._release(payload["sprint_id"], token)
        self._apply(self.log.append([(kind, project_id, payload)]))

    def _record_launch(self, launch: manager.Launch, reason: str | None, token: object) -> None:
        secret = launch.env[manager.SECRET_ENV]
        with self._ingest:
            self._settled[launch.sprint_id] = int(self._clock() * 1000)
            self._release(launch.sprint_id, token)
            if launch.sprint_id not in self._sprints:
                self._drop_sprint_files(launch.sprint_id)
                return
            if self._stop.is_set():
                return
            marks = ({"takeover": True, "goal": self._sprints[launch.sprint_id].goal}
                     if launch.takeover else {})
            if reason is None:
                self._append_manager(MANAGER_STARTED, launch.project_id, {
                    "sprint_id": launch.sprint_id, "profile": launch.profile,
                    "session_name": launch.session_name, "seen_after": launch.seen_after,
                    **marks}, token)
                return
            if secret:
                reason = reason.replace(secret, "<secret>")
            self._append_manager(MANAGER_FAILED, launch.project_id, {
                "sprint_id": launch.sprint_id, "reason": reason, **marks}, token)
            print(f"console: manager_failed {launch.sprint_id} {reason}", file=sys.stderr)

    def withdraw_goal(self, project_id: str, sprint_id: str) -> None:
        """Append one `goal.withdrawn` event for an open sprint of that project, drop its secret, stop its manager."""
        with self._ingest:
            sprint = self._sprints.get(sprint_id)
            if sprint is None or sprint.project_id != project_id:
                raise sprints.Refused(sprints.NOT_OPEN)
            appended = self.log.append(
                [(GOAL_WITHDRAWN, project_id, {"sprint_id": sprint_id, "goal": sprint.goal})])
            self._apply(appended)
            self._drop_sprint_files(sprint_id)
            reserved = self._stopper is not None and self._reserve_stop(sprint_id)
        if reserved:
            self._dispatch_stop(sprint_id)

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

    def send_closing(self, sprint_id: str, secret: str, closing: dict) -> str:
        """Append one `sprint.closed` event for a sprint that may close; its at."""
        with self._ingest:
            sprint = self._manager_sprint(sprint_id, secret)
            if sprint.closing is not None or sprint.stopped_at is not None:
                raise sprints.Refused(sprints.ENDED)
            if sprint.state != sprints.STARTING and sprint.stop_at is None:
                raise sprints.Refused(sprints.NOT_STARTED)
            reported = [issue for issue, _ in sprint.report.issues] if sprint.report else []
            checked = sprints.checked_closing(closing, reported)
            appended = self.log.append([(SPRINT_CLOSED, sprint.project_id, {
                "sprint_id": sprint_id, "goal": sprint.goal, "closing": checked})])
            self._apply(appended)
            reserved = sprint.stop_at is not None and self._reserve_stop(sprint_id)
        if reserved:
            self._dispatch_stop(sprint_id)
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
            reserved = self._reserve_nudge(sprint_id)
        if reserved:
            self._dispatch_nudge(sprint_id)

    def reply_brief(self, project_id: str, sprint_id: str, version: int, reply: str) -> None:
        """Append one `brief.replied` event carrying the owner's words exactly as sent."""
        with self._ingest:
            sprint = self._waiting_brief(project_id, sprint_id, version)
            sprints.checked_reply(reply)
            appended = self.log.append([(BRIEF_REPLIED, project_id, {
                "sprint_id": sprint_id, "version": version, "goal": sprint.goal,
                "reply": reply})])
            self._apply(appended)
            reserved = self._reserve_nudge(sprint_id)
        if reserved:
            self._dispatch_nudge(sprint_id)

    def send_message(self, project_id: str, sprint_id: str, text: str) -> int:
        """Append one `sprint.messaged` event with the owner's text exactly as sent; its id."""
        with self._ingest:
            sprint = self._sprints.get(sprint_id)
            if sprint is None or sprint.project_id != project_id:
                raise sprints.Refused(sprints.NOT_OPEN)
            if sprint.stopped_at is not None or sprints.ended_at(sprint) is not None:
                raise sprints.Refused(sprints.ENDED)
            sprints.checked_message(text)
            appended = self.log.append([(SPRINT_MESSAGED, project_id, {
                "sprint_id": sprint_id, "goal": sprint.goal, "text": text})])
            self._apply(appended)
            reserved = self._reserve_nudge(sprint_id)
        if reserved:
            self._dispatch_nudge(sprint_id)
        return appended[-1].seq

    def _nudgeable(self, sprint_id: str) -> tuple[sprints.SprintState, tuple[sprints.Message, ...]] | None:
        """Under the ingest lock: the open sprint and its unread messages when its manager can be nudged.

        A sprint with a launch reserved is not nudgeable: a wake would resume the manager the launch replaces.
        Nor is one whose session stop is reserved or whose manager is stopped (#892): a wake would resume it.
        Nor is one ended by a closing report (#980): its manager is stopped, and stays stopped.
        Nor is one whose manager's account is out of quota (#929): the message waits for the reset.
        """
        sprint = self._sprints.get(sprint_id)
        if (sprint is None or sprint_id in self._launching or sprint_id in self._stopping
                or sprint.stopped_at is not None or sprint.manager is None
                or sprint.manager.state != sprints.STARTED
                or (sprint.closing is not None and sprint.stop_at is None)
                or self._quota_wait(sprint) is not None):
            return None
        unread = sprints.unread(sprint)
        return (sprint, unread) if unread else None

    def _reserve_nudge(self, sprint_id: str) -> bool:
        """Under the ingest lock: reserve the sprint for a nudge; a reserved sprint is marked to nudge again."""
        if self._nudger is None or self._nudgeable(sprint_id) is None:
            return False
        if sprint_id in self._nudging:
            self._nudge_again.add(sprint_id)
            return False
        self._nudging.add(sprint_id)
        return True

    def _dispatch_nudge(self, sprint_id: str) -> None:
        """Hand a reserved sprint's nudge to the dispatcher; one that cannot start is a failed nudge."""
        try:
            self._dispatch(lambda: self._nudge(sprint_id))
        except Exception as error:
            reason = f"the nudge could not start: {type(error).__name__}: {error}"
            with self._ingest:
                self._nudging.discard(sprint_id)
                self._nudge_again.discard(sprint_id)
                self._settled[sprint_id] = int(self._clock() * 1000)
                self._record_nudge(sprint_id, None, None, reason)

    def _wake_settings(self, sprint_id: str, session_id: str, profile: str,
                       cwd: str) -> tuple[str | None, str | None]:
        """Off the ingest lock: the settings path a wake of `session_id` must carry, and why it is unknown.

        The profile's full listing (stopped sessions included) shows the session: the wake is bare
        `(None, None)`. It does not: the record was removed, so the wake passes the sprint's name and
        settings file again, `(path, None)`. No seam, or a listing that cannot be read, is a bare wake
        (a copy is the worse failure); an unreadable one also returns its reason.
        """
        if self._full_listing is None:
            return None, None
        try:
            shown = self._full_listing(profile, cwd)
        except nudge.ListingUnreadable as error:
            return None, str(error)
        except Exception as error:
            return None, f"{type(error).__name__}: {error}"
        if session_id in shown:
            return None, None
        return str(manager.settings_path(self._sprint_secrets, sprint_id)), None

    def _refresh_settings(self, sprint_id: str) -> None:
        """Write the sprint's manager settings file again before a wake (ADR-console-021).

        The content is what a launch writes, from the sprint's stored secret. It runs under the ingest lock,
        as `withdraw_goal` removes the secret and the file, so a withdrawal can never fall between the read
        and the write and leave a file holding the secret. `NudgeFailed` when the sprint is no longer open,
        when its secret is missing (the wake is not sent without the isolation and permission members) or when
        the file cannot be written (the write's reason).
        """
        with self._ingest:
            if sprint_id not in self._sprints:
                raise nudge.NudgeFailed("the sprint is no longer open")
            secret = sprints.read_secret(self._sprint_secrets, sprint_id)
            if secret is None:
                raise nudge.NudgeFailed("the sprint's secret is missing")
            try:
                manager.write_settings(manager.settings_path(self._sprint_secrets, sprint_id),
                                       {manager.ID_ENV: sprint_id, manager.SECRET_ENV: secret})
            except manager.LaunchFailed as error:
                raise nudge.NudgeFailed(str(error)) from error

    def _record_nudge(self, sprint_id: str, through: int | None, route: str | None,
                      reason: str | None, listing_failed: str | None = None) -> None:
        """Under the ingest lock: append one `sprint.nudged` row for the open sprint and fold it."""
        sprint = self._sprints.get(sprint_id)
        if sprint is None or self._stop.is_set():
            return
        if through is None:
            unread = sprints.unread(sprint)
            if not unread:
                return
            through = unread[-1].message_id
        payload = {"sprint_id": sprint_id, "through": through, "route": route,
                   "ok": reason is None}
        if reason is not None:
            payload["reason"] = reason
        elif self._resume(sprint_id):
            payload["resumed"] = True
        if listing_failed is not None:
            payload["listing_failed"] = listing_failed
        self._apply(self.log.append([(SPRINT_NUDGED, sprint.project_id, payload)]))
        if reason is not None:
            print(f"console: nudge_failed {sprint_id} {reason}", file=sys.stderr)
        if listing_failed is not None:
            print(f"console: listing_failed {sprint_id} {listing_failed}", file=sys.stderr)

    def _listed_ids(self, name: str) -> list[str]:
        """Off the ingest lock: the session ids the running listing shows under `name`, lowest first."""
        return sorted(o.session_id for o in self._listing().values() if o.name == name)

    def _nudge(self, sprint_id: str) -> None:
        """Tell the sprint's manager to read its inbox, then record the attempt; the reservation ends here."""
        with self._ingest:
            found = self._nudgeable(sprint_id)
            project = None if found is None else self._states.get(found[0].project_id)
            if found is None or project is None:
                self._nudging.discard(sprint_id)
                self._nudge_again.discard(sprint_id)
                return
            sprint, unread = found
            through = unread[-1].message_id
            name = manager.session_name(sprint.project_id, sprint_id)
            profile, known, cwd = sprint.manager.profile, sprint.manager_session, project.root
        route, reason, listing_failed = None, None, None
        try:
            listed, settings = self._listed_ids(name), None
            if not listed and known is not None:
                settings, listing_failed = self._wake_settings(sprint_id, known, profile, cwd)
                listed = self._listed_ids(name)  # the full listing is slow: the manager may be running now
            with self._ingest:
                if self._held_for_quota(sprint_id):
                    self._nudging.discard(sprint_id)
                    self._nudge_again.discard(sprint_id)
                    return
            if listed:
                route, listing_failed = nudge.RELAY, None
                self._nudger(nudge.Nudge(sprint_id, route, name, listed[0], profile, cwd))
            elif known is not None:
                route = nudge.WAKE
                self._refresh_settings(sprint_id)
                self._nudger(nudge.Nudge(sprint_id, route, name, known, profile, cwd, settings))
            else:
                reason = nudge.UNKNOWN_SESSION
        except Exception as error:
            reason = (str(error) if isinstance(error, nudge.NudgeFailed)
                      else f"{type(error).__name__}: {error}")
        again = False
        with self._ingest:
            self._nudging.discard(sprint_id)
            self._settled[sprint_id] = int(self._clock() * 1000)
            wanted = sprint_id in self._nudge_again
            self._nudge_again.discard(sprint_id)
            self._record_nudge(sprint_id, through, route, reason, listing_failed)
            found = self._nudgeable(sprint_id)
            if wanted and found is not None and found[1][-1].message_id > through \
                    and not self._stop.is_set():
                self._nudging.add(sprint_id)
                again = True
        if again:
            self._dispatch_nudge(sprint_id)

    def renudge(self) -> None:
        """Nudge again the managers whose message went unread and undelivered for a minute."""
        if self._nudger is None:
            return
        due = []
        with self._ingest:
            now = int(self._clock() * 1000)
            for sprint_id, sprint in self._sprints.items():
                found = self._nudgeable(sprint_id)
                if (found is None or sprint_id in self._nudging
                        or sprints.unreachable(sprint)):
                    continue
                if not any(message.delivered_at is None
                           and now - _epoch_ms(message.at) >= sprints.RENUDGE_AFTER_MS
                           for message in found[1]):
                    continue
                if sprint.last_nudge_at is not None and \
                        now - _epoch_ms(sprint.last_nudge_at) < sprints.RENUDGE_AFTER_MS:
                    continue
                self._nudging.add(sprint_id)
                due.append(sprint_id)
        for sprint_id in due:
            self._dispatch_nudge(sprint_id)

    def stop_sprint(self, project_id: str, sprint_id: str) -> None:
        """Append the owner's stop request for an open sprint and nudge its manager with the stop message."""
        with self._ingest:
            sprint = self._sprints.get(sprint_id)
            if sprint is None or sprint.project_id != project_id:
                raise sprints.Refused(sprints.NOT_OPEN)
            if sprint.stop_at is not None:
                raise sprints.Refused(sprints.ALREADY_STOPPING)
            if sprint.stopped_at is not None or sprints.ended_at(sprint) is not None:
                raise sprints.Refused(sprints.ENDED)
            appended = self.log.append([(SPRINT_STOP_REQUESTED, project_id, {
                "sprint_id": sprint_id, "goal": sprint.goal})])
            self._apply(appended)
            reserved = self._reserve_nudge(sprint_id)
        if reserved:
            self._dispatch_nudge(sprint_id)

    def _settle_stops(self) -> None:
        """Start the settle window of every session still to be stopped: a restart loses `_settled`."""
        now = int(self._clock() * 1000)
        for sprint_id, sprint in self._sprints.items():
            if (sprint.stop_at is not None and sprint.stopped_at is None) \
                    or self._done_stop_pending(sprint):
                self._settled[sprint_id] = now
        for sprint_id in self._pending:
            self._settled[sprint_id] = now

    @staticmethod
    def _done_stop_pending(sprint: sprints.SprintState) -> bool:
        """Whether a sprint ended by a closing report still has its manager's session to stop (#980)."""
        return (sprint.closing is not None and sprint.stop_at is None
                and sprint.done_stopped_at is None)

    def _turn_ended(self, sprint: sprints.SprintState) -> bool:
        """Under the ingest lock: whether the manager's session went idle after the sprint's closing report: its state's own time is later."""
        session = self._manager_session(sprint)
        return (session is not None and sprint.closing is not None
                and session.state in idle.IDLE_STATES and session.state_ms is not None
                and session.state_ms > sprints._ms(sprint.closing.at))

    def _reserve_stop(self, sprint_id: str) -> bool:
        """Under the ingest lock: reserve the sprint's session stop unless a launch, nudge or stop holds it."""
        if (sprint_id in self._stopping or sprint_id in self._launching
                or sprint_id in self._nudging):
            return False
        self._stopping.add(sprint_id)
        return True

    def finish_stops(self) -> None:
        """Stop the session of every sprint whose stop is due and not held by a launch, nudge or stop."""
        due = []
        with self._ingest:
            now = int(self._clock() * 1000)
            for sprint_id, sprint in self._sprints.items():
                if (sprints.stop_due(sprint, now)
                        or sprints.done_stop_due(sprint, now, self._turn_ended(sprint))) \
                        and self._reserve_stop(sprint_id):
                    due.append(sprint_id)
            if self._stopper is not None:
                for sprint_id, pending in self._pending.items():
                    if sprints.pending_due(pending, now) and self._reserve_stop(sprint_id):
                        due.append(sprint_id)
        for sprint_id in due:
            self._dispatch_stop(sprint_id)

    def _dispatch_stop(self, sprint_id: str) -> None:
        """Hand a reserved sprint's session stop to the dispatcher; one that cannot start is a failed stop."""
        try:
            self._dispatch(lambda: self._stop_session(sprint_id))
        except Exception as error:
            reason = f"the stop could not start: {type(error).__name__}: {error}"
            with self._ingest:
                self._stopping.discard(sprint_id)
                self._record_stop_failure(sprint_id, reason)

    def _stoppable(self, sprint_id: str) -> str | None:
        """Under the ingest lock: the project of a sprint whose session is to be stopped, else None.

        That is a stopping sprint not yet stopped, or a withdrawn sprint whose stop is pending.
        """
        sprint = self._sprints.get(sprint_id)
        if sprint is not None:
            stopping = sprint.stop_at is not None and sprint.stopped_at is None
            return sprint.project_id if stopping or self._done_stop_pending(sprint) else None
        pending = self._pending.get(sprint_id)
        return pending.project_id if pending is not None else None

    def _record_stop_failure(self, sprint_id: str, reason: str) -> None:
        """Under the ingest lock: append one `manager.stop_failed` row for a stopping sprint, say it, publish."""
        project_id = self._stoppable(sprint_id)
        if project_id is None or self._stop.is_set():
            return
        self._apply(self.log.append([(MANAGER_STOP_FAILED, project_id, {
            "sprint_id": sprint_id, "reason": reason})]))
        print(f"console: manager_stop_failed {sprint_id} {reason}", file=sys.stderr)

    def _stop_session(self, sprint_id: str) -> None:
        """End the stopping sprint's manager session and record the outcome; the reservation ends here."""
        with self._ingest:
            project_id = self._stoppable(sprint_id)
            if project_id is None:
                self._stopping.discard(sprint_id)
                return
            name = manager.session_name(project_id, sprint_id)
            settled = self._settled.get(sprint_id)
        deferred, reason = False, None
        if self._stopper is not None:
            try:
                listed = self._listing()
                if (not any(o.name == name for o in listed.values()) and settled is not None
                        and int(self._clock() * 1000) - settled < sprints.STOP_SETTLE_MS):
                    deferred = True
                else:
                    manager.stop_listed([name], lambda: listed, self._stopper)
            except manager.StopFailed as error:
                reason = str(error)
            except Exception as error:
                reason = f"{type(error).__name__}: {error}"
        with self._ingest:
            self._stopping.discard(sprint_id)
            if deferred or self._stop.is_set():
                return
            if reason is not None:
                self._record_stop_failure(sprint_id, reason)
            elif self._stoppable(sprint_id) is not None:
                self._apply(self.log.append([(MANAGER_STOPPED, project_id, {
                    "sprint_id": sprint_id})]))

    def _revive_step(self, sprint: sprints.SprintState, now: int) -> str | None:
        """Under the ingest lock: the one bring-back decision for the sprint at `now` (milliseconds)."""
        return revive.next_step(
            sprint, self._waiting(sprint),
            self._last_listed.get(sprint.sprint_id, self._revive_since_ms), now,
            self._nudger is not None, self._quota_wait(sprint) is not None)

    def revive(self) -> None:
        """Bring back each manager that is gone while its sprint has work (#893)."""
        if self._launcher is None:
            return
        jobs: list[tuple[str, str]] = []
        with self._ingest:
            if self._stop.is_set():
                return
            now = int(self._clock() * 1000)
            for sprint_id in [key for key in self._last_listed if key not in self._sprints]:
                del self._last_listed[sprint_id]
            for sprint_id, sprint in list(self._sprints.items()):
                if self._manager_listed(sprint):
                    self._last_listed[sprint_id] = now
                    continue
                if sprint_id in self._launching or sprint_id in self._nudging:
                    continue
                step = self._revive_step(sprint, now)
                if step == revive.STALL:
                    self._apply(self.log.append([(MANAGER_STALLED, sprint.project_id, {
                        "sprint_id": sprint_id, "goal": sprint.goal,
                        "reason": revive.stall_reason(sprint)})]))
                elif step == sprints.WAKE:
                    self._nudging.add(sprint_id)
                    jobs.append((step, sprint_id))
                elif step == sprints.TAKEOVER:
                    self._launching[sprint_id] = _TakeoverReservation()
                    jobs.append((step, sprint_id))
        for step, sprint_id in jobs:
            try:
                if step == sprints.WAKE:
                    self._dispatch_wake(sprint_id)
                else:
                    self._dispatch_launch(sprint_id)
            except Exception as error:
                print(f"console: revive_failed {type(error).__name__}: {error}", file=sys.stderr)

    def _dispatch_wake(self, sprint_id: str) -> None:
        """Hand a reserved sprint's wake to the dispatcher; one that cannot start is a failed wake."""
        try:
            self._dispatch(lambda: self._revive_wake(sprint_id))
        except Exception as error:
            reason = f"the wake could not start: {type(error).__name__}: {error}"
            with self._ingest:
                self._nudging.discard(sprint_id)
                self._settled[sprint_id] = int(self._clock() * 1000)
                self._record_wake(sprint_id, False, reason, False)

    def _record_wake(self, sprint_id: str, ok: bool, reason: str | None, back: bool,
                     listing_failed: str | None = None) -> None:
        """Under the ingest lock: append one `manager.woken` row for the open sprint and fold it."""
        sprint = self._sprints.get(sprint_id)
        if sprint is None or self._stop.is_set():
            return
        payload = {"sprint_id": sprint_id, "goal": sprint.goal,
                   "session_id": sprint.manager_session or "", "ok": ok}
        if reason is not None:
            payload["reason"] = reason
        if back:
            payload["back"] = True
        if ok and self._resume(sprint_id):
            payload["resumed"] = True
        if listing_failed is not None:
            payload["listing_failed"] = listing_failed
        self._apply(self.log.append([(MANAGER_WOKEN, sprint.project_id, payload)]))
        if not ok:
            print(f"console: wake_failed {sprint_id} {reason}", file=sys.stderr)
        if listing_failed is not None:
            print(f"console: listing_failed {sprint_id} {listing_failed}", file=sys.stderr)

    def _wake_due(self, sprint_id: str) -> sprints.SprintState | None:
        """Under the ingest lock: the open sprint when a wake of its manager is still the step."""
        sprint = self._sprints.get(sprint_id)
        if (sprint is None or sprint.manager is None or self._manager_listed(sprint)
                or self._revive_step(sprint, int(self._clock() * 1000)) != sprints.WAKE):
            return None
        return sprint

    def _revive_wake(self, sprint_id: str) -> None:
        """Resume the sprint's stopped manager in place, then record the attempt; the reservation ends here."""
        with self._ingest:
            sprint = self._wake_due(sprint_id)
            project = None if sprint is None else self._states.get(sprint.project_id)
            if sprint is None or project is None:
                self._nudging.discard(sprint_id)
                return
            name = manager.session_name(sprint.project_id, sprint_id)
            session_id, profile, root = sprint.manager_session, sprint.manager.profile, project.root
            seen_before = sprint.manager_seen_seq
        reason, listing_failed = None, None
        try:
            if any(o.name == name for o in self._listing().values()):
                with self._ingest:
                    self._last_listed[sprint_id] = int(self._clock() * 1000)
                    self._nudging.discard(sprint_id)
                return
            settings, listing_failed = self._wake_settings(sprint_id, session_id, profile, root)
            with self._ingest:
                if self._wake_due(sprint_id) is None:
                    self._nudging.discard(sprint_id)
                    return
            self._refresh_settings(sprint_id)
            self._nudger(nudge.Nudge(
                sprint_id, nudge.REVIVE, name, session_id, profile, root, settings))
        except Exception as error:
            reason = (str(error) if isinstance(error, nudge.NudgeFailed)
                      else f"{type(error).__name__}: {error}")
        with self._ingest:
            self._nudging.discard(sprint_id)
            self._settled[sprint_id] = int(self._clock() * 1000)
            sprint = self._sprints.get(sprint_id)
            back = (reason is None and sprint is not None
                    and (self._manager_listed(sprint) or sprint.manager_seen_seq != seen_before))
            self._record_wake(sprint_id, reason is None, reason, back, listing_failed)

    def _active_ms(self, sprint: sprints.SprintState,
                   session: sessions.SessionState | None) -> int | None:
        """Under the ingest lock: the latest movement of the manager's runs or send to it, else None."""
        times = [self._settled.get(sprint.sprint_id)]
        if session is not None:
            times.append(self._moved.get(session.session_id))
        known = [t for t in times if t is not None]
        return max(known) if known else None

    def _run_moved(self, session: sessions.SessionState | None) -> int | None:
        """Under the ingest lock: the latest movement of a run of the session still in progress, else None."""
        if session is None:
            return None
        moved = [state.moved_ms for (sid, _), state in self._deliveries.items()
                 if sid == session.session_id]
        moved += [ms for (sid, _), ms in self._run_moves.items() if sid == session.session_id]
        return max(moved) if moved else None

    def nudge_idle(self) -> None:
        """Tell each idle manager whose sprint has work to go on, and give up after too many tries (#929)."""
        if self._nudger is None:
            return
        jobs: list[str] = []
        with self._ingest:
            if self._stop.is_set():
                return
            now = int(self._clock() * 1000)
            self._quota_held.intersection_update(self._sprints)
            for sprint_id, sprint in list(self._sprints.items()):
                if (sprint_id in self._nudging or sprint_id in self._launching
                        or sprint_id in self._stopping):
                    continue
                session = self._manager_session(sprint)
                waiting = self._waiting(sprint)
                quota = self._quota_wait(sprint)
                if quota is None and (
                        sprint.manager is None or sprint.manager.state != sprints.STARTED
                        or (session is not None and session.state == sessions.WORKING)):
                    self._quota_held.discard(sprint_id)
                step = idle.next_step(sprint, waiting, session, self._active_ms(sprint, session),
                                      quota is not None, now, run_ms=self._run_moved(session))
                if step == idle.GIVE_UP:
                    status = sprint.report.status if sprint.report is not None else None
                    self._apply(self.log.append([(MANAGER_NO_PROGRESS, sprint.project_id, {
                        "sprint_id": sprint_id, "goal": sprint.goal, "status": status})]))
                elif step == idle.NUDGE:
                    self._nudging.add(sprint_id)
                    jobs.append(sprint_id)
        for sprint_id in jobs:
            self._dispatch_idle(sprint_id)

    def continue_sprint(self, project_id: str, sprint_id: str) -> None:
        """Clear a sprint's no-progress item and send its manager one idle nudge at once (#929)."""
        with self._ingest:
            sprint = self._sprints.get(sprint_id)
            if sprint is None or sprint.project_id != project_id:
                raise sprints.Refused(sprints.NOT_OPEN)
            if sprint.no_progress_at is None:
                raise sprints.Refused(sprints.NOT_STUCK)
            self._apply(self.log.append([(SPRINT_CONTINUED, project_id, {
                "sprint_id": sprint_id, "goal": sprint.goal})]))
            reserved = (self._nudger is not None and sprint_id not in self._nudging
                        and sprint_id not in self._launching and sprint_id not in self._stopping)
            if reserved:
                self._nudging.add(sprint_id)
        if reserved:
            self._dispatch_idle(sprint_id, forced=True)

    def _dispatch_idle(self, sprint_id: str, forced: bool = False) -> None:
        """Hand a reserved sprint's idle nudge to the dispatcher; one that cannot start is a failed nudge."""
        try:
            self._dispatch(lambda: self._idle_nudge(sprint_id, forced))
        except Exception as error:
            reason = f"the nudge could not start: {type(error).__name__}: {error}"
            with self._ingest:
                self._nudging.discard(sprint_id)
                self._settled[sprint_id] = int(self._clock() * 1000)
                sprint = self._sprints.get(sprint_id)
                self._record_idle(
                    sprint_id, "" if sprint is None else sprint.manager_session or "", reason)

    def _idle_due(self, sprint_id: str, forced: bool) -> tuple[sprints.SprintState, str] | None:
        """Under the ingest lock: the open sprint and its project's root while an idle nudge is still the step."""
        sprint = self._sprints.get(sprint_id)
        project = None if sprint is None else self._states.get(sprint.project_id)
        if sprint is None or project is None:
            return None
        session = self._manager_session(sprint)
        step = idle.next_step(
            sprint, self._waiting(sprint), session, self._active_ms(sprint, session),
            self._quota_wait(sprint) is not None, int(self._clock() * 1000), forced,
            self._run_moved(session))
        return (sprint, project.root) if step == idle.NUDGE else None

    def _working_now(self, observed: sessions.Observation) -> bool:
        """Under the ingest lock: whether a fresh registry reading shows the session working.

        A reading older than, or as old as, the session's newest hook does not count: hooks win.
        """
        if sessions.registry_state(observed) != sessions.WORKING:
            return False
        known = self._sessions.get(observed.session_id)
        return (known is None or known.hook_ms is None
                or (observed.updated_ms is not None and observed.updated_ms > known.hook_ms))

    def _idle_nudge(self, sprint_id: str, forced: bool) -> None:
        """Tell the idle manager to go on, then record the attempt; the reservation ends here."""
        with self._ingest:
            due = self._idle_due(sprint_id, forced)
            if due is None:
                self._nudging.discard(sprint_id)
                return
            sprint, cwd = due
            name = manager.session_name(sprint.project_id, sprint_id)
            profile, session_id = sprint.manager.profile, sprint.manager_session or ""
        reason = None
        try:
            listed = sorted((o for o in self._listing().values() if o.name == name),
                            key=lambda o: o.session_id)
            if not listed:
                with self._ingest:
                    self._nudging.discard(sprint_id)
                return
            session_id = listed[0].session_id
            with self._ingest:
                if (self._idle_due(sprint_id, forced) is None
                        or self._working_now(listed[0])):
                    self._nudging.discard(sprint_id)
                    return
            self._nudger(nudge.Nudge(sprint_id, nudge.CONTINUE, name, session_id, profile, cwd))
        except Exception as error:
            reason = (str(error) if isinstance(error, nudge.NudgeFailed)
                      else f"{type(error).__name__}: {error}")
        with self._ingest:
            self._nudging.discard(sprint_id)
            self._settled[sprint_id] = int(self._clock() * 1000)
            self._record_idle(sprint_id, session_id, reason)

    def _record_idle(self, sprint_id: str, session_id: str, reason: str | None) -> None:
        """Under the ingest lock: append one `manager.nudged` row for the open sprint and fold it."""
        sprint = self._sprints.get(sprint_id)
        if sprint is None or self._stop.is_set():
            return
        payload = {"sprint_id": sprint_id, "goal": sprint.goal, "session_id": session_id,
                   "ok": reason is None}
        if reason is not None:
            payload["reason"] = reason
        elif self._resume(sprint_id):
            payload["resumed"] = True
        self._apply(self.log.append([(MANAGER_NUDGED, sprint.project_id, payload)]))
        if reason is not None:
            print(f"console: idle_nudge_failed {sprint_id} {reason}", file=sys.stderr)

    def read_inbox(self, sprint_id: str, secret: str) -> list[dict]:
        """The unread messages in id order; the same locked section records them as read."""
        with self._ingest:
            sprint = self._manager_sprint(sprint_id, secret)
            unread = sprints.unread(sprint)
            if not unread:
                return []
            appended = self.log.append([(SPRINT_READ, sprint.project_id, {
                "sprint_id": sprint_id, "through": unread[-1].message_id})])
            self._apply(appended)
            return [sprints.inbox_entry(message) for message in unread]

    def recap(self, sprint_id: str, secret: str) -> dict:
        """What a manager needs to pick the sprint up; a read that appends and marks nothing."""
        with self._ingest:
            sprint = self._manager_sprint(sprint_id, secret)
            brief, report = sprint.brief, sprint.report
            return {
                "sprint_id": sprint_id,
                "goal": sprint.goal,
                "brief": None if brief is None else {
                    "version": brief.version, "decision": brief.decision,
                    "reply": brief.reply, "parts": brief.parts},
                "report": None if report is None else {
                    "at": report.at, "status": report.status, "phase": report.phase,
                    "milestone": report.milestone, "tracker_url": report.tracker_url,
                    "issues": [{"issue": issue, "stage": stage} for issue, stage in report.issues],
                    "inbox": list(report.inbox), "next": report.next_step},
                "unread": len(sprints.unread(sprint))}

    def answer_message(self, sprint_id: str, secret: str, message_id: int, reply: str) -> str:
        """Append one `sprint.answered` event under a message of the sprint; its at."""
        with self._ingest:
            sprint = self._manager_sprint(sprint_id, secret)
            if all(message.message_id != message_id for message in sprint.messages):
                raise sprints.Refused(sprints.UNKNOWN_MESSAGE)
            sprints.checked_reply(reply)
            appended = self.log.append([(SPRINT_ANSWERED, sprint.project_id, {
                "sprint_id": sprint_id, "message": message_id, "reply": reply})])
            self._apply(appended)
            return appended[-1].at

    def ask_questions(self, sprint_id: str, secret: str, round_: dict) -> tuple[int, int]:
        """Append one `questions.asked` event for an approved sprint; the round's id and size."""
        with self._ingest:
            sprint = self._manager_sprint(sprint_id, secret)
            if sprint.state != sprints.STARTING:
                raise sprints.Refused(sprints.NOT_STARTED)
            if not sprints.takes_questions(sprint):
                raise sprints.Refused(sprints.ENDED)
            checked = sprints.checked_round(round_)
            if sprints.round_open(sprint) and not checked["blocker"]:
                raise sprints.Refused(sprints.ROUND_OPEN)
            appended = self.log.append([(QUESTIONS_ASKED, sprint.project_id, {
                "sprint_id": sprint_id, "goal": sprint.goal, "blocker": checked["blocker"],
                "questions": checked["questions"]})])
            self._apply(appended)
            return appended[-1].seq, len(checked["questions"])

    def answer_question(self, project_id: str, sprint_id: str, round_id: int, index: int,
                        choice: int | None, text: str | None) -> int:
        """Append one `question.answered` event, a message to the manager; its id."""
        with self._ingest:
            sprint = self._sprints.get(sprint_id)
            if sprint is None or sprint.project_id != project_id:
                raise sprints.Refused(sprints.NOT_OPEN)
            if not sprints.takes_questions(sprint):
                raise sprints.Refused(sprints.ENDED)
            asked = next((question for question in sprint.questions
                          if (question.round_id, question.index) == (round_id, index)), None)
            if asked is None:
                raise sprints.Refused(sprints.UNKNOWN_QUESTION)
            if asked.answer is not None:
                raise sprints.Refused(sprints.ANSWERED_ALREADY)
            if choice is not None:
                if not 0 <= choice < len(asked.options):
                    raise sprints.Refused(sprints.NOT_AN_OPTION)
                chosen = answer = asked.options[choice]
            else:
                chosen, answer = None, sprints.checked_message(text)
            appended = self.log.append([(QUESTION_ANSWERED, project_id, {
                "sprint_id": sprint_id, "goal": sprint.goal, "round": round_id, "index": index,
                "question": asked.question, "answer": answer, "chosen": chosen,
                "recommended": asked.recommended, "differs": chosen != asked.recommended})])
            self._apply(appended)
            reserved = self._reserve_nudge(sprint_id)
        if reserved:
            self._dispatch_nudge(sprint_id)
        return appended[-1].seq

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
            observations = {
                session_id: seen
                for session_id, seen in sessions.read_session_registry(self._session_dirs()).items()
                if self._probe_profile(session_id) is None}

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
            self._note_choice(self._session_choice(self._profiles))
            return appended

    def _session_choice(self, profiles: frozenset[str],
                        excluded: frozenset[str] | None = None) -> str | None:
        """Under the ingest lock: the profile a new session should use, over `profiles`.

        `excluded` is the set the choice is made over, the folded one when None.
        """
        return manager.session_profile(
            capacity.capacity_view(profiles, self._capacity, self._clock(), self._signins,
                                   excluded=self._excluded if excluded is None else excluded),
            self._use.last)

    def set_exclusion(self, profile: str, excluded: bool) -> list[Event]:
        """Exclude `profile` from the console's choice, or put it back; `exclusion.Refused` when it cannot.

        Under the ingest lock: the profile must be among the directories as they are now and the
        toggle must change something. The choice file is written first, over the set the toggle
        gives, so a failed write appends and publishes nothing; a failed append puts the file back
        to the choice over the old set.
        """
        with self._ingest:
            profiles = self._read_profiles()
            if profile not in profiles:
                raise exclusion.Refused(exclusion.UNKNOWN)
            if excluded and profile in self._excluded:
                raise exclusion.Refused(exclusion.ALREADY_EXCLUDED)
            if not excluded and profile not in self._excluded:
                raise exclusion.Refused(exclusion.ALREADY_INCLUDED)
            after = self._excluded | {profile} if excluded else self._excluded - {profile}
            choice = self._session_choice(profiles, after)
            if self._choice_file is not None and choice != self._choice:
                manager.write_choice(self._choice_file, choice)
                self._choice = choice
                self._unreadable.discard("choice")
            try:
                appended = self.log.append([exclusion.entry(profile, excluded)])
            except Exception:
                self._note_choice(self._session_choice(profiles))
                raise
            self._apply(appended)
            return appended

    def excluded_profiles(self) -> list[str]:
        """The profiles the owner excluded, in name order."""
        with self._ingest:
            return sorted(self._excluded)

    def session_profile(self) -> str | None:
        """The profile a new session should use now, over the profile directories as they are; kept in the choice file."""
        with self._ingest:
            profile = self._session_choice(self._read_profiles())
            self._note_choice(profile)
            return profile

    def _note_choice(self, profile: str | None) -> None:
        """Under the ingest lock: write the choice file when `profile` differs from the last value written."""
        if self._choice_file is None or profile == self._choice:
            return
        try:
            manager.write_choice(self._choice_file, profile)
        except OSError as error:
            self._warn_once("choice", f"console: choice_unwritten {type(error).__name__}: {error}")
            return
        self._choice = profile
        self._unreadable.discard("choice")

    def _read_profiles(self) -> frozenset[str]:
        """The accounts among the profile directories as they are now."""
        names = (sessions.account_name(d) for d in self._profile_dirs() if d.is_dir())
        return frozenset(name for name in names if name is not None)

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
        run_moves: dict[tuple[str, str], int] = {}
        terminal: list[tuple[str, str]] = []
        for sid in sorted(scanned):
            listing = deliveries.run_journals(projects_dirs, sid)
            if isinstance(listing, deliveries.Unreadable):
                readings.update({k: v for k, v in folded.items() if k[0] == sid})
                runs.update({j: f for j, f in self._runs.items() if j.parents[3].name == sid})
                run_moves.update({k: v for k, v in self._run_moves.items() if k[0] == sid})
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
                    if key in self._run_moves:
                        run_moves[key] = self._run_moves[key]
                    self._warn_once(path, f"console: journal_unreadable {path} {chunk.reason}")
                    continue
                self._unreadable.discard(path)
                if chunk is None:
                    continue
                if not ended:
                    run_moves[key] = chunk.moved_ms
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
            self._run_moves = run_moves

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
            try:
                self.renudge()
            except Exception as error:
                print(f"console: renudge_failed {type(error).__name__}: {error}",
                      file=sys.stderr)
            try:
                self.finish_stops()
            except Exception as error:
                print(f"console: stop_poll_failed {type(error).__name__}: {error}",
                      file=sys.stderr)
            try:
                self.revive()
            except Exception as error:
                print(f"console: revive_failed {type(error).__name__}: {error}",
                      file=sys.stderr)
            try:
                self.nudge_idle()
            except Exception as error:
                print(f"console: idle_nudge_failed {type(error).__name__}: {error}",
                      file=sys.stderr)

    def _fold(self, appended: list[Event]) -> None:
        new = digest.moments(appended, self._sessions, self._inbox, self._sprints)
        self._looked = digest.last_looked(appended, self._looked)
        self._states = project_states(appended, self._states)
        self._sessions = sessions.session_states(appended, self._sessions)
        self._use = manager.profile_use(appended, self._use)
        self._inbox = inbox_records(appended, self._inbox)
        self._health = read_states(appended, self._health)
        self._capacity = capacity.capacity_state(appended, self._capacity)
        self._signins = signin.signin_state(appended, self._signins)
        self._excluded = exclusion.excluded_profiles(appended, self._excluded)
        self._signin_ends = signin_run.ended_state(appended, self._signin_ends)
        self._accounts_added = account_add.added_state(appended, self._accounts_added)
        self._deliveries = deliveries.delivery_states(appended, self._deliveries)
        self._moved = idle.last_moved(appended, self._moved)
        self._sprints = sprints.sprint_states(appended, self._sprints)
        self._withdrawn = sprints.withdrawn_ids(appended, self._withdrawn)
        self._pending = sprints.pending_stops(appended, self._pending)
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
                self._use = manager.profile_use(events)
                self._inbox = inbox_records(events)
                self._capacity = capacity.capacity_state(events)
                self._signins = signin.signin_state(events)
                self._excluded = exclusion.excluded_profiles(events)
                self._signin_ends = signin_run.ended_state(events)
                self._accounts_added = account_add.added_state(events)
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
        if self._prober is not None or self._signin_reader is not None:
            self._probe_thread = threading.Thread(
                target=self._probe_loop, name=PROBE_LOOP_THREAD, daemon=True)
            self._probe_thread.start()
        if self._signin_runs is not None:
            self._signin_thread = threading.Thread(
                target=self._signin_loop, name=SIGNIN_THREAD, daemon=True)
            self._signin_thread.start()
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
        if self._probe_thread is not None:
            self._probe_thread.join()
        if self._signin_thread is not None:
            self._signin_thread.join()
        if self._signin_runs is not None:
            self._signin_runs.close()
        with self._ingest:
            workers = list(self._probe_workers)
        for worker in workers:
            worker.join()
        if self._thread is not None:
            self._server.shutdown()
        self._server.server_close()
        with self._ingest:
            self.log.close()
