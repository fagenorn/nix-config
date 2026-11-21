"""The console's sprints (#886, #887): a goal the owner states on the page, kept until it is withdrawn, and the brief a manager sends for it.

Six event kinds carry a sprint (`event_log.GOAL_STATED`, `GOAL_WITHDRAWN`, `BRIEF_SENT`,
`BRIEF_APPROVED`, `BRIEF_REPLIED`, `SPRINT_REPORTED`). All put the project id in the event's project
column. A goal row carries `{"sprint_id": <id>, "goal": <text>}` (a withdrawal repeats the stated
text); the brief and report rows carry

    brief.sent      {"sprint_id", "version": <int>, "goal": <str>,
                     "brief": {<the six parts>, "pictures"?: [{"picture": <id>, "line": <str>,
                                                               "pair"?: "before" | "after"}]},
                     "pictures"?: [<id>]}
    brief.approved  {"sprint_id", "version": <int>, "goal": <str>}
    brief.replied   {"sprint_id", "version": <int>, "goal": <str>, "reply": <str>}
    sprint.reported {"sprint_id", "goal": <str>,
                     "report": {<the seven REPORT_MEMBERS>, "pictures"?: [<same members>]},
                     "pictures"?: [<id>]}

The log keeps all six indefinitely (`event_log.KEPT_KINDS`).

Three more kinds record the sprint's manager (#888), none of them kept (`event_log.MANAGER_STARTED`,
`MANAGER_FAILED`, `MANAGER_WAITING`; each with the project in its project column), and two record
its bring-back (#893; `event_log.MANAGER_WOKEN`, `MANAGER_STALLED`, not kept either):

    manager.started  {"sprint_id", "profile": <str>, "session_name": <str>, "seen_after"?: <int>,
                      "takeover"?: true, "moved"?: true, "permission"?: {"mode", "reason"}}
    manager.failed   {"sprint_id", "reason": <str>, "takeover"?: true}
    manager.waiting  {"sprint_id", "until": <str> | null, "takeover"?: true}
    manager.woken    {"sprint_id", "session_id": <str>, "ok": <bool>, "reason"?: <str>,
                      "back"?: <bool>, "listing_failed"?: <str>, "permission"?: {"mode", "reason"}}
    manager.stalled  {"sprint_id", "reason": <str>}

The fold does not read `moved` (a listed manager moved to another account, #1378); the digest does.

A sprint id is `secrets.token_hex(8)`: 16 lowercase hex characters (`SPRINT_ID`), the only form a
request may name and the file name of the sprint's secret.

The sprint's secret is `secrets.token_urlsafe(32)` plus one newline in
`<directory>/sprint-secrets/<sprint id>` (`SECRETS_DIR` beside the event log), the directory created
0700 and the file created once, 0600, with `O_EXCL`. Only `read_secret(directory, sprint_id)` reads it back, for the service's
check of a manager's secret: it validates the id (`ValueError` otherwise), returns the file text
with one trailing newline removed and `None` when the file does not exist; any other `OSError`
propagates. The secret appears in no row, view, stream frame, answer or stderr line.

The goal is the sent text with `str.strip()` applied (`checked_goal`). The refusals, in the order the
service applies them: `UNREGISTERED` (the service's check, not made here), `EMPTY` after stripping,
`TOO_LONG` over `MAX_GOAL_CHARS` code points after stripping. The stored goal is the stripped text.
`Refused` carries the one-line reason as `str(error)`.

`parse_goal(body)` reads the body of the goal write and returns `(project_id, goal)`; the goal may
be empty so the service can give the plain reason:

    {"project_id": "<project id>", "goal": "<text>"}

`parse_withdraw(body)` reads the body of the withdraw write and returns `(project_id, sprint_id)`:

    {"project_id": "<project id>", "sprint_id": "<16 lowercase hex>"}

`parse_retry(body)` reads the body of the manager retry write, the same shape as the withdraw's, and
returns `(project_id, sprint_id)`. `HAS_MANAGER`, `LAUNCHING` and `TOO_SOON` are the service's
retry refusals.

Both accept only a UTF-8 JSON object with exactly those keys; anything else, a repeated key, a
NaN or Infinity literal or nesting too deep to parse raises `ValueError`.

`sprint_states(events, states=None)` folds events into the open sprints keyed by sprint id: a
`goal.stated` event with a project, a string `sprint_id` and a string `goal` adds a `SprintState`
(`stated_seq` and `stated_at` are the event's `seq` and `at`); a `goal.withdrawn` with a string
`sprint_id` removes it; the brief rows and the manager rows below change an open sprint; every other
event and any malformed goal event changes nothing.

A guest's `goal.stated`, `brief.approved`, `brief.replied`, `sprint.messaged` and
`question.answered` rows carry `"by": <login>` (#1263), and an owner's row carries none. `actor_of`
reads it: the login when it is already a normal login (`event_log.normal_login`, the definition
admission uses), else None, which means the owner. `SprintState.started_by` is the actor of the
`goal.stated` row, `Message.by` the actor of the row that made the message, and
`Question.answered_by` the actor of its `question.answered` row. A malformed `by` reads as the
owner, so no guest can steer that sprint.
Registration events change nothing here: a goal row outlives the registration rows retention
removes, and the view alone shows sprints only under registered projects. Folding `a + b` equals
folding `b` onto the fold of `a`.

A brief is the six `PARTS`: `title` one line of at most `MAX_TITLE_CHARS` characters naming the
sprint, `done` a text, `slices` a non-empty list of texts, and `excluded`, `risks` and `asks` lists
of texts that may be empty (`MAY_BE_EMPTY`). `checked_brief(brief)` checks them in `PARTS` order
(so `title` first) and refuses with `Refused("the brief has no <part>")` the first that is
missing, of the wrong type, empty when it must not be, or holding a text empty after stripping
(a `title` holding a line break is also "no title"), and a title over the limit with
`TITLE_TOO_LONG`; it returns a new dict of the six parts with every text stripped, plus `"pictures"` (the checked
members) only when `brief` has a non-empty `pictures` list. After the six parts it checks that list
as `checked_pictures("brief", brief["pictures"])`: the picture checks of a question's round (see
below), under the `PART_*` reasons, which read "the brief's picture 1 has no valid line" for the
question's "question 1 picture 1 has no valid line". `sprint_title(state)` is the latest brief's title (whitespace collapsed, cut by `cut` to
`MAX_TITLE_CHARS`) when it is a non-empty string, else `goal_title(goal)`: the goal's first line up
to the first `.`, `!` or `?` followed by whitespace or the end (else the whole line), cut the same
way, so a logged brief without a title still has a name. `cut(text, limit)` is the text when it fits,
else its first `limit - 1` characters, stripped, and an ellipsis. `checked_reply(text)`
keeps the text exactly and refuses `EMPTY_REPLY` when its strip is empty, then `REPLY_TOO_LONG` over
`MAX_REPLY_CHARS` code points. `SecretRefused` (a `Refused`) is the service's refusal of a wrong
secret; it maps to 403.

`parse_brief_request(body)` reads the manager's body and returns `(sprint_id, secret, brief,
dry_run)`:

    {"sprint_id": "<16 lowercase hex>", "secret": "<string>",
     "brief": {<any subset of PARTS, and "pictures">}}

plus an optional `"dry_run": true` (the same flag as `parse_ask_request`'s: `false` or any other
value is `ValueError`); `dry_run` is `True` only when it was given.

`parse_approve(body)` returns `(project_id, sprint_id, version)` and `parse_reply(body)` returns
`(project_id, sprint_id, version, reply)` from the page's bodies:

    {"project_id": "<project id>", "sprint_id": "<16 hex>", "version": <int >= 1, not a bool>}
    ... plus "reply": "<string>" for a reply

All three readers are as strict as the goal ones; an unknown brief key is a `ValueError`, a missing
one is not (the service answers it with the part).

The fold also keeps each open sprint's `Brief(version, parts, sent_at, decision, reply, decided_at,
pictures)`; `parts` is the logged `brief` dict without its `pictures` key.
`brief.sent` changes an open sprint only when `version` is an int (not a bool) greater than the
folded brief's version (0 with none) and `brief` is a dict: the brief is then that version with
decision `NONE` and no reply, and a folded report of phase `done` is dropped (the replaced run's
end). `brief.approved` and `brief.replied` apply only when the sprint is
open, has a brief, the version equals its version and its decision is `NONE`; approval sets
`APPROVED`, a reply (a string) sets `CHANGES` and the reply. A sprint whose brief is `APPROVED` is
`STARTING`, else `DRAFTING` (`SprintState.state`). `brief.approved` and `brief.replied`, when they
apply, also set the brief's `decided_at` to the event's `at`; a `brief.sent` brief has `decided_at`
`None`.

The fold also keeps each open sprint's `Manager(state, at, profile, session_name, reason, until)`,
`None` until a valid manager row arrives. A manager row changes only an open sprint (a row for a
sprint that is not folded changes nothing) and the latest valid row wins, whatever the earlier one
was; `Manager.at` is that row's `at`. `manager.started` is valid only with a string `profile` and a
string `session_name` (state `started`); `manager.failed` only with a string `reason` (`failed`);
`manager.waiting` only with an `until` key whose value is a string or null (`waiting`). A row that
is not valid changes nothing.

The bring-back rows (#893) add to the same state. `Manager.takeover` is true when a valid started,
failed or waiting row says `"takeover": true` (exactly true; any other value or none is false).
`SprintState.revivals` is a tuple of `Revival(at, how, ok, reason, back)` in row order. A valid
`manager.woken` (a string `session_id`, a bool `ok`, a `back` member that is absent or a bool; a
`back` that is not a bool makes the row malformed) appends `Revival(at, WAKE, ok, reason, back)`,
`reason` the row's string `reason` when `ok` is false and else `None`, `back` true only when the row
says so. A valid `manager.started` that is a takeover appends `Revival(at, TAKEOVER, True)` and a
valid `manager.failed` that is a takeover appends `Revival(at, TAKEOVER, False, reason)`; a
`manager.waiting` appends none (a wait started nothing). Every valid `manager.started` also clears
`stalled` and `stalled_at`. A `manager.stalled` with a string `reason` sets `stalled` to it and
`stalled_at` to the row's `at`; while the sprint is stalled a valid `manager.failed` replaces
`stalled` with its reason and keeps `stalled_at`. `revive` (which this module does not import)
reads these fields to decide the next step.

The idle rows (#929) record the nudges of a manager that sat idle with work left
(`event_log.MANAGER_NUDGED`, `MANAGER_NO_PROGRESS`, `SPRINT_CONTINUED`, none kept, each with the
project in its project column):

    manager.nudged      {"sprint_id", "goal": <str>, "session_id": <str>, "ok": <bool>,
                         "reason"?: <str>, "resumed"?: true}
    manager.no_progress {"sprint_id", "goal": <str>, "status": <str> | null}
    sprint.continued    {"sprint_id", "goal": <str>}

`SprintState` keeps `idle_nudges` (0), `idle_nudged_at` and `no_progress_at` (both `None`). Each row
changes only an open sprint. A `manager.nudged` with a bool `ok` and a string `session_id` adds one
to `idle_nudges` and sets `idle_nudged_at` to the row's `at`; any other such row changes nothing. A
`manager.no_progress` sets `no_progress_at` to the row's `at` when it is `None` (a repeat keeps the
first). A `sprint.continued` with `no_progress_at` set clears it and sets `idle_nudges` to 0, and
changes nothing otherwise. A `sprint.reported` row that is accepted also sets `idle_nudges` to 0 and
`no_progress_at` to `None` and keeps `idle_nudged_at`: the spacing is about nudges. The new
constants are `QUOTA` (a view state), `QUOTA_TEXT` (the manager's waiting text, `waiting on quota
until`), `NO_PROGRESS_TEXT` (`the manager has stopped making progress on {title}`) and `NOT_STUCK`
(the service's refusal of a continue with no item open). `parse_continue(body)` reads the owner's
continue write, exactly `parse_withdraw`'s shape and refusals, and returns `(project_id,
sprint_id)`. `idle` (which this module does not import) reads these fields. `stated_hold(state, now_ms)` (#1380) is
the hold the report's own `paused` or `wait_until` puts on them: `(PAUSED, reason)` or `(WAIT_UNTIL,
time)` while it stands, else `None`; a `wait_until` holds while `now_ms * 1000` is under its
microseconds (`_wait_us`, exact, never the truncating `_ms`), so a fractional-millisecond deadline holds
through its own millisecond.

`manager_status(state, listed, now_ms, managers)` turns a sprint's manager into the view's
`(manager_state, manager_text, retry)`; its docstring holds the rules. `failed_start(state, listed,
managers)` is true when that status is a `failed` one with retry on a first launch that has no brief
(#1182): the owner's card, the line's `NOW_FAILED_START_TEXT` and the owner's ball read it.

The view's `manager_state`, `manager_text` and `retry`, and the service's retry gate, are this
function's three results.

`withdrawn_ids(events, ids)` adds the `sprint_id` of every `goal.withdrawn` row with a string one.

A report is what the approved sprint's manager says about the sprint. `parse_report_request(body)`
reads the manager's body and returns `(sprint_id, secret, report, dry_run)`:

    {"sprint_id": "<16 lowercase hex>", "secret": "<string>",
     "report": {"status": "<one line>", "phase": "running", "milestone": "<one line>",
                "tracker_url": "https://<host>/<path>",
                "issues": [{"issue": 12, "stage": "building"}, {"issue": 13, "stage": "landed"}],
                "inbox": [12], "next": "<one line>", "pictures": [...],
                "wait_until": "<ISO 8601 UTC time>", "paused": "<one line>"}}

It accepts only a UTF-8 JSON object of exactly `sprint_id`, `secret` and `report` (plus an optional
`"dry_run": true`, as a brief's), a valid sprint id, a string secret and a `report` object whose
keys are a subset of `REPORT_MEMBERS`, `REPORT_OPTIONAL` and `pictures`; anything
else, a repeated key, a NaN literal or nesting too deep is `ValueError`. A missing member is not (the
service answers it with the member). `checked_report(report)` checks the members in `REPORT_MEMBERS`
order and refuses with `Refused("the report has no valid <member>")` the first that is missing or
invalid; right after a valid `status` it refuses `STATUS_NUMBER` when the stripped status matches
`#` and a digit. `checked_report(report, now_ms=None)` takes the clock in milliseconds of the service
that judges the report; the fold calls it without one. `status`, `milestone` and `next` are a one-line text (a string, non-empty after stripping,
no line break, at most `MAX_LINE_CHARS` code points after stripping); `phase` is one of
`REPORT_PHASES`; `tracker_url` is a string of at most `MAX_LINE_CHARS` code points starting with
`https://` whose every character is printable and not whitespace; `issues` is a list of at most
`MAX_REPORT_ISSUES` objects of exactly `issue` (an int, not a bool, at least 1) and `stage` (one of
`REPORT_STAGES`), no issue twice, possibly empty; `inbox` is a list of at most `MAX_REPORT_ISSUES`
ints (not bools) of at least 1, possibly empty. It returns a new dict of the seven members: texts
stripped, `issues` sorted by issue, `inbox` sorted without duplicates, `tracker_url` and `phase` as
given, plus `"pictures"` on the same rule as a brief's: after the seven members and `STATUS_NUMBER`,
`checked_pictures("report", report["pictures"])` checks a `pictures` list, and the checked members
are returned only when it is non-empty. `pictures` is not one of `REPORT_MEMBERS`.

A report may state a wait or a pause (#1380), the two `REPORT_OPTIONAL` members, checked after the
seven members and `STATUS_NUMBER` and before `pictures`, in this order. `wait_until` is a string
`WAIT_TIME` matches: `YYYY-MM-DDTHH:MM`, optional `:SS` with any number of fractional digits, and a
UTC zone (`Z`, `+00:00`, `+0000` or `+00`); naive, any other offset (a fractional one included), a
number, `null` or a word is `REPORT_MEMBER`. Only when `now_ms` is given (an int or a `Fraction`, so
the service passes its clock without truncating it): a time at or before the clock is `WAIT_PAST` and
one more than `MAX_WAIT_HOURS` hours (24) ahead is `WAIT_TOO_FAR`, both compared exactly (`_wait_us`,
a `Fraction` of microseconds: no float, never `_ms`, which truncates to the millisecond). `paused` is a one-line text as `status` is (else `REPORT_MEMBER`),
stripped, and `PAUSED_NUMBER` when it matches `#` and a digit. A report that states both is
`WAIT_AND_PAUSE`. The returned dict carries `"wait_until"` (as `isoformat()` of the UTC time rounded up to the
microsecond, so `Z` reads `+00:00` and a fractional part is kept to the microsecond) and `"paused"` (stripped) only when given, so a report
without either is exactly the dict above.

The fold keeps each open sprint's `Report(at, status, phase, milestone, tracker_url, issues, inbox,
next_step, pictures, wait_until, paused)`. `sprint.reported` changes an open sprint only when its brief is approved
(`STARTING`) and `checked_report` accepts the dict `report` without its `pictures` key; the report
is then replaced (`at` is the event's `at`, `issues` a tuple of `(issue, stage)`, `inbox` a tuple,
`next_step` the `next` member, `pictures` the read-back below, `wait_until` and `paused` the checked
members or None; the fold checks without a clock, so a stored wait whose time has passed folds) and the sprint's observations are
cleared; its movement (`moved_ms`) is kept (#1109). Every other report row changes nothing.

Movement and observations (#1109): a `delivery.seen` row carries no sprint id and is read as the
delivery fold reads it (`deliveries.delivery_states` on that one row; a row that parses to nothing
changes nothing). A run belongs to a sprint of the row's project, open or ended, when its
`session_id` is the sprint's manager session, or when the sprint has a report and the run carries an
issue of the report's `issues` or `inbox`; any other run changes nothing. A belonging run sets the
sprint's `moved_ms` to the larger of the kept one and the run's, whether it moved before or after the
report, and a report never clears it. Observations are narrower: only when the sprint has a report
and the run moved after it (`moved_ms` greater than the report's `at` in milliseconds), each of the
run's stages for an issue in the report's `issues` becomes that issue's `Observed(issue, moved_ms,
session_id, run_id, stage)` when `(moved_ms, session_id, run_id)` is at least the kept one's.
`delivery.gone` changes nothing: the last stage and movement outlive the run. A run of the sprint's
manager session also adds each of its issues to `SprintState.delivered` (#1377), which only grows, so
the record that the manager delivered an issue outlives the run and its cleanup.
`SprintState.observed` is ordered by issue. Folding `a + b` equals folding `b` onto the fold of `a`.

`ago_text(elapsed_ms)` is `just now` under a minute, `<m> min ago` under an hour, `<h> h ago` under
a day, else `1 day ago` or `<d> days ago`; a negative count is 0. `age_text(elapsed_ms)` is `goal set `
plus that. `progress_text(landed, total, in_delivery, queued, held)` is `<landed> of <total> landed`
followed by `, <n> in delivery`, `, <n> queued` and `, <n> held` for each non-zero count, in that
order. The view states and texts are the constants `ON_TRACK`, `WAITING`, `QUIET`, `CLOSING`,
`DONE` and their `_TEXT`; `CLOSED_OUT` is the view's stage for a run's `done` (not a report stage).
A running sprint's ball (#1086) is `BALL_MANAGER`, `BALL_OWNER` or `BALL_NOBODY`, worded by
`BALL_TEXT`, and its now-sentence is one of the `NOW_*_TEXT` constants (among them the wait sentences
`NOW_CI_TEXT`, `NOW_COMMITTING_TEXT`, `NOW_RELEASE_TEXT` (#1110) and `NOW_LOCK_TEXT` (#1184)) or
the stage phrase (`NOW_STAGE_TEXT`, prefixed by `NOW_QUIET_TEXT` when nobody has the ball), never the report's status
line and never shortened. A sprint's check line (#1111) reads `CHECK_LINE_TEXT`. The now-sentence of a report whose status marks a refused merge
(`refused_reason`) is `NOW_REFUSED_TEXT` in place of the stage phrase, shown by `merge_refused`
until a later report without the marker or a closing clears it (no run observation clears it: the
status names no issue); it is the one now-sentence that may equal the status line.

Messages (#889) are what the owner says to a sprint, each one a `Message` kept in `message_id` order
on `SprintState.messages`. Four rows carry them, the first three kept (`event_log.SPRINT_MESSAGED`,
`SPRINT_READ`, `SPRINT_ANSWERED`, `SPRINT_NUDGED`; each with the project in its project column):

    sprint.messaged {"sprint_id", "goal": <str>, "text": <str>}
    sprint.read     {"sprint_id", "through": <int message id>}
    sprint.answered {"sprint_id", "message": <int message id>, "reply": <str>}
    sprint.nudged   {"sprint_id", "through": <int>, "covers"?: [<int message id>], "route": "relay" |
                     "wake" | null, "ok": true, "listing_failed"?: <str>, "permission"?: {"mode", "reason"}}
                    {"sprint_id", "through": <int>, "covers"?: [<int message id>], "route": "relay" |
                     "wake" | null, "ok": false, "reason": <str>, "listing_failed"?: <str>,
                     "permission"?: {"mode", "reason"}}

A message's id is the `seq` of the row that made it. A `brief.approved` row that approves the open
brief makes a `MESSAGE_APPROVED` message (`version` the brief's, no text); a `brief.replied` row
that asks the open brief for changes makes a `MESSAGE_CHANGES` message (`version`, `text` the reply);
a `sprint.messaged` row with a string `text` makes a `MESSAGE_TEXT` message (no version). A stale or
repeated decision, which `_folded_brief` ignores, makes none. `sprint.read` with an int (not bool)
`through` sets `read_at` (the row's `at`) on every message up to that id still unread and resets
`failed_nudges`. `sprint.nudged` with a bool `ok` and an int `through` sets `last_nudge_at` and
`last_nudge_ok`; `ok` true sets `delivered_at` on every message up to `through` without one and
resets `failed_nudges` (when the row carries `covers`, a list of ids, on exactly the listed messages
instead: a message released after the nudge began, a look approval the console had held, was not told
of), `ok` false adds one to it. An `ok` row whose `route` is `"relay"` also adds one to `relays`
and sets `relayed_at` (the row's `at`) on the same messages (a message already relayed twice keeps
both, so later traffic never moves its wake), and one whose `route` is `"wake"` sets
`woken_at` on them (the latest row wins); a failed row, a null route or any other route changes
none of the three. `sprint.answered` with an int `message` naming one
of the sprint's messages and a string `reply` sets that message's `reply` and `reply_at` (the latest
row wins). Every other such row changes nothing, and a withdrawn sprint keeps nothing.

A `session.seen` row carries no sprint id: when its string `name` fully matches
`<project> sprint <16 lowercase hex>` (`manager.session_name`), the sprint is open, the name's
project and the row's project column both equal the sprint's, the row's string `session_id` becomes
the sprint's `manager_session` (the latest row wins) and the row's `seq` becomes its
`manager_seen_seq`; the same row sets `back` on the last revival when that is a `WAKE` not yet back
and clears `stalled` and `stalled_at`, since a manager listed again is no longer stalled.
A valid `manager.started` row clears `manager_session`, since the session it named belonged to the
manager that row replaces, unless the row's int `seen_after` (the `manager_seen_seq` the sprint had
when the launch began) is below the seq of the latest seen row: that row was written while the
launcher was still returning, so it names the new manager and is kept.

`message_state(message, now_ms)` is the first that holds of: `REPLIED` when `reply` is set,
`PICKED_UP` when `read_at` is set, `NOT_PICKED_UP` when `now_ms` is not None and at least
`NOT_PICKED_UP_AFTER_MS` have passed since the message's `at`, else `SENT`; `delivered_at` never
changes the shown state, it only feeds the service's re-nudge, and `relays`, `relayed_at` and
`woken_at` feed its escalation likewise. `unread(state)` is the messages without `read_at` and not
held, in id order; `unreachable(state)` is true once `failed_nudges` reaches `UNREACHABLE_AFTER`.
`unread_step(state, now_ms)` is pure and decides what a message that was relayed and is still unread
needs, the first of these that holds: None when `unreachable(state)`; None when `last_nudge_at` is
less than `UNREAD_AGAIN_MS` before `now_ms` and failed (`last_nudge_ok` false); of the unread messages with no `woken_at` and a
`relayed_at` at least `UNREAD_AGAIN_MS` old, `WAKE_UNREAD` when one has `relays` of 2 or more and
`manager_session` is set, else `RELAY_AGAIN` when one has exactly 1 relay, else None.
`STILL_RUNNING_TEXT` is the reason a wake gives up when the manager's session did not stop. `checked_message(text)` refuses
`EMPTY_MESSAGE` for a blank text and `MESSAGE_TOO_LONG` above `MAX_MESSAGE_CHARS`, and returns the
text unchanged. `parse_message(body)` reads the owner's write and returns `(project_id, sprint_id,
text)`; `parse_inbox_request(body)` reads the manager's `{"sprint_id", "secret"}` and returns
`(sprint_id, secret)`; `parse_message_reply_request(body)` reads the manager's `{"sprint_id",
"secret", "message": <int of at least 1>, "reply": <str>}` and returns `(sprint_id, secret,
message_id, reply)`. All three are as strict as `parse_reply` (`ValueError` otherwise).
`parse_permit_request(body)` reads the manager's `{"sprint_id", "secret", "phase": "judge" | "landed",
"session_id": <1 to 128 characters>, "tool_use_id": <1 to 128 characters>, "command": <at most 8192
characters>}` and returns the frozen `PermitRequest` of those six members, `ValueError` for any other body (#1377).
`inbox_entry(message)` is the wire entry `{"id", "kind", "version", "text", "at"}`, and for a
`MESSAGE_ANSWER` message also `"question"`, `"round"`, `"chosen"` and `"words"` (see below).

Rounds of questions (#891) are what an approved sprint's manager asks the owner. Three rows carry
them, all kept (`event_log.QUESTIONS_ASKED`, `QUESTION_ANSWERED`, `QUESTION_WITHDRAWN`; each with
the project in its project column), and a fourth, `look.recorded` (#1260, kept), records what the
console did about a look card's approval:

    questions.asked   {"sprint_id", "goal": <str>, "blocker": <bool>, "pictures"?: [<id>],
                       "look_repo"?: <str> (the project's repository when a question has a look),
                       "questions": [{"question", "context"?, "blocks", "options": [<str>],
                                      "recommended", "needs_words"?: [<option text>],
                                      "owner_only"?: true, "consequential"?: true,
                                      "pictures"?: [{"picture": <id>,
                                      "line": <str>, "pair"?: "before" | "after"}],
                                      "look"?: {"issue": <int>, "pr": <int>, "head": <40 hex>,
                                                "approve": <str>},
                                      "replaces"?: {"round": <int>, "index": <int>}}]}
    question.withdrawn {"sprint_id", "goal": <str>, "round": <int>, "index": <int>,
                        "question": <str>}
    question.answered {"sprint_id", "goal": <str>, "round": <int>, "index": <int>,
                       "question": <str>, "answer": <str>, "chosen": <str> | null,
                       "recommended": <str>, "differs": <bool>, "words"?: <str>,
                       "look"?: {"issue": <int>, "pr": <int>, "head": <40 hex>, "repo": <str>}}
    look.recorded     {"sprint_id", "round": <int>, "index": <int>, "outcome": "moved" | "posted" |
                       "failed", ...}  moved: "found": <40 hex> | null, "state": "open" | "closed"
                       | "merged", "message"?: <int> (the answer taken back); posted: "message":
                       <int>, "comment_id": <int>; failed: "message": <int>, "reason": <str>

The round the manager sends (inside the ask request) and the owner's answer (the page's write) are

    {"questions": [{"question": "<the ask>", "context": "<why, optional>",
                    "blocks": "<one line>", "options": ["<one line>", ...],
                    "recommended": "<exact text of one option>",
                    "look": {"issue": <int >= 1>, "pr": <int >= 1>, "head": "<40 lowercase hex>",
                             "approve": "<exact text of one option>"},
                    "needs_words": ["<exact text of an option>", ...],
                    "pictures": [{"picture": "<id>", "line": "<one line>",
                                  "pair": "before" | "after"}, ...],
                    "replaces": {"round": <int >= 1>, "index": <int >= 0>}}, ...],
     "blocker": true | false}                   (blocker optional, default false)
    {"project_id", "sprint_id", "round": <int >= 1>, "question": <int >= 0>, "choice": <int >= 0>}
    {"project_id", "sprint_id", "round": <int >= 1>, "question": <int >= 0>, "text": "<words>"}
    {"project_id", "sprint_id", "round": <int >= 1>, "question": <int >= 0>, "choice": <int >= 0>,
     "text": "<words>"}

A round has one to `MAX_ROUND_QUESTIONS` questions, each with `MIN_OPTIONS` to `MAX_OPTIONS`
options. A question's `question` is its ask, at most `MAX_ASK_CHARS`; its optional `context`, at most
`MAX_CONTEXT_CHARS` and free to span lines, is the why; each option is at most `MAX_OPTION_CHARS`.
`checked_round(round, limits=True)` refuses with `Refused` the first failure, in this order:
`NO_QUESTIONS` (`questions` not a list, or empty), `TOO_MANY_QUESTIONS`, `BAD_BLOCKER` (`blocker`
present and not a bool); then, per question (`n` counts from 1): `QUESTION_SHAPE` (not an object, or
a key outside `question, context, blocks, options, recommended, needs_words, owner_only,
consequential, pictures, look, replaces`),
`QUESTION_MEMBER` for
`question`
(not a string non-empty after stripping), `ASK_TOO_LONG`, `QUESTION_MEMBER` for `context` (present
and not a string non-empty after stripping), `CONTEXT_TOO_LONG`, `QUESTION_MEMBER` for `blocks`
(one line), `OPTION_COUNT`, `QUESTION_MEMBER` for `options` (an option not a string non-empty after
stripping), `OPTION_TOO_LONG`, `QUESTION_MEMBER` for `options` again (an option with a line break or
over `MAX_LINE_CHARS`), `OPTION_TWICE` (two options equal after stripping) and `NO_RECOMMENDATION`
(`recommended` not a string whose strip equals one stripped option), then (#1260) `LOOK_SHAPE`
(`look` present and not an object of exactly `issue` and `pr`, each an int that is not a bool and
at least 1, `head`, 40 lowercase hex, and `approve`, a string) and `LOOK_APPROVE` (`approve`
whose strip equals no stripped option), then `NEEDS_WORDS_SHAPE`
(`needs_words` present and not a non-empty list of strings whose strips are each one stripped
option, each named once) and (#1260) `LOOK_APPROVE_WORDS` (the look's `approve` is also in `needs_words`: choosing it
records the approval and takes no words, so the owner could never approve), then `OWNER_ONLY_SHAPE` (`owner_only` present and not `true`),
then `CONSEQUENTIAL_SHAPE` (`consequential` present and not `true`), then `REPLACES_SHAPE`
(`replaces` present and not an object of exactly `round`, an int that is not a bool and at least 1,
and `index`, an int that is not a bool and at least 0). The picture checks follow (#1090): `PICTURES_SHAPE` (`pictures` present and not a list), `TOO_MANY_PICTURES` (over
`MAX_PICTURES`), then per picture `m` (from 1) `PICTURE_SHAPE` (not an object, a key outside
`picture, line, pair`, or `picture` or `line` missing), `PICTURE_MEMBER` for `picture` (not a string
fully matching `pictures.PICTURE_ID`), `PICTURE_MEMBER` for `line` (not a string non-empty after
stripping), `LINE_TOO_LONG` (over `MAX_PICTURE_LINE_CHARS`), `PICTURE_MEMBER` for `line` again (a
line break, or over `MAX_LINE_CHARS`) and `PICTURE_MEMBER` for `pair` (present and not in `PAIRS`);
after the loop `PAIR_TWICE` for the first `pair` given twice, then (#1260) `LOOK_PAIR` for a question
with a `look` whose pictures lack a member marked `before` or one marked `after` (a card
that approves a head shows the owner the pair, whatever its words say; a round read back from the log
or a check with `files_withheld=True` skips it), then (#1092) `LOOK_WITHOUT_PICTURE`
for a question that has no picture while its ask or context matches `LOOK_WORDS` (the word
screenshot or screenshots in any case, also written "screen shot", a `.png` file or a folder with a
`screenshots` segment), naming the question's number and ask; a round read back from the log
(`limits=False`) and a check with `files_withheld=True` (the service's dry run, whose round has its
`file` members left out) skip it. After the questions `REPLACES_TWICE` names the first question
whose `replaces` equals an earlier question's (also with `limits=False`). `REPLACES_REFUSED` is the
service's refusal of a mark that names no open question of the sprint. `PICTURE_UNKNOWN` and `PICTURE_FOREIGN`
name the service's refusals of a picture it does not hold or another sprint sent. A brief and a
report check their picture list with the same loop (#1091): `checked_pictures(owner, pictures, *,
limits=True)` with `owner` `"brief"` or `"report"` takes the same steps in the same order and
refuses under `PART_PICTURES_SHAPE`, `PART_TOO_MANY_PICTURES`, `PART_PICTURE_SHAPE`,
`PART_PICTURE_MEMBER`, `PART_LINE_TOO_LONG` and `PART_PAIR_TWICE` (each formatted with `owner`, and
`m` or `pair` as above), and `PART_PICTURE_UNKNOWN` and `PART_PICTURE_FOREIGN` name the service's
refusals. `picture_ids(members)` is the unique `picture` values of checked members in first-seen
order. With
`limits=False` the three limit steps are replaced by today's caps: a `QUESTION_MEMBER` for a
`question` or `context` over `MAX_QUESTION_CHARS` (an option's cap is `MAX_LINE_CHARS`), and a
picture's line over `MAX_LINE_CHARS`; the picture count cap stays. It returns a new
`{"blocker": <bool>, "questions": [{"question", "blocks", "options", "recommended"}]}` with every
text stripped, a question carrying `"context"` only when the round gave one, `"needs_words"` (the
stripped option texts, in the given order) only when it gave one, `"owner_only"` (`true`) only when it
gave it, `"consequential"` (`true`) only when it gave it, `"look"` (`{"issue",
"pr", "head", "approve"}`, `approve` stripped) only when it gave one, and `"pictures"`
(`{"picture", "line"}` plus `"pair"` when given) only when it gave a non-empty list, and `"replaces"`
(`{"round", "index"}`) only when it gave one. `replaced(checked)` is the `(round, index)` each
question's `replaces` names in a checked round, in question order.
`round_pictures(checked)` is the unique picture ids of a checked round, in question then picture
order.
`parse_ask_request(body)` reads the manager's `{"sprint_id", "secret", "round"}` (exactly those
keys, plus an optional `"dry_run"` that must be `true`) and returns `(sprint_id, secret, round,
dry_run)`, `round` an object whose keys are a subset of
`questions, blocker`; `parse_round_answer(body)` reads the page's body, one or both of `choice` and
`text`, and returns `(project_id, sprint_id, round_id, index, choice, text)` with an absent one
None; `parse_look_retry(body)` reads the page's retry of a look card's approval, exactly
`{"project_id", "sprint_id", "round": <int >= 1>, "question": <int >= 0>}`, and returns
`(project_id, sprint_id, round_id, index)`. All three are `ValueError` on anything else, a
repeated key, NaN or nesting too deep.

The fold keeps each open sprint's `Question`s on `SprintState.questions`, ordered by `(round_id,
index)`. A `questions.asked` row changes a sprint only when it is open, its brief is approved
(`STARTING`) and `checked_round(..., limits=False)` accepts the row's `questions` and `blocker`
(absent: false), so a logged round over a limit folds whole and renders cut; each
checked question is then added with `round_id` the row's `seq`, its `index` and `at`, and its
`look` kept as a `QuestionLook`, its `needs_words` (`Question.needs_words`, `()` when the round
gave none) and `owner_only`
(`Question.owner_only`, false unless the round marked it: a question only the console's owner
answers, #1263) and `consequential` (`Question.consequential`, false unless the round marked it: the
page opens its card with nothing picked, #1265). Each checked
question's pictures become `Question.pictures`, `QuestionPicture`s in order. A `picture.stored`
row adds its `picture` to `SprintState.pictures` when its `sprint_id` is folded and `picture` fully
matches `PICTURE_ID`; any other such row changes nothing. A `questions.asked`, `brief.sent` or
`sprint.reported` row of a folded sprint adds the members of its top-level `pictures` list that
fully match `PICTURE_ID`, whether or not the row itself applied, so a sprint still owns a picture
its kept row names after retention has removed the `picture.stored` row. A `brief.sent` or
`sprint.reported` row that applies also reads its pictures back: `Brief.pictures` and
`Report.pictures` are the `QuestionPicture`s of `checked_pictures(owner, <the logged pictures>,
limits=False)`, so a logged line over `MAX_PICTURE_LINE_CHARS` folds whole and renders cut, and are
`()` when the key is absent or that check refuses; a refusal there never drops the brief or the
report. The fold does not enforce one open round;
the service does. A `question.answered` row applies only when its `round`
and `index` (ints, not bools) name an unanswered question of the sprint, its `answer` is a string and
its `chosen` is null or one of the question's options: the question then keeps `answer`, `chosen`,
`answered_at` (the row's `at`) and `differs`, computed as `chosen != recommended` (the row's own
`differs` is not trusted; the owner's own words, `chosen` null, always differ), and the sprint gains
a `MESSAGE_ANSWER` message (`text` the answer, plus `question`, `round_id`, `chosen`). A row that
also carries `words` applies only when `words` is a string and `chosen` is not null (an option and
the owner's words together; `answer` and `chosen` are then the option's text), else it changes
nothing; the question and message then keep `words` (`Question.words`, `Message.words`), and
`differs` is `chosen != recommended` either way. An answer
on a question with a `look` whose `chosen` equals `look.approve` and whose row's `look` equals the
question's `(issue, pr, head)` and names a `repo` (`owner/name`, the repository the console read it
for) sets `look_state` to `"posting"` (and `look_message` to the row's `seq`, `look_repo` to the
`repo`, which a retry posts to) and its message is `held`: `unread` leaves a held message out and no `sprint.read` or
`sprint.nudged` watermark marks it read or delivered, so the approval reaches the manager only after
the console has posted it; the `repo` must equal the `look_repo` the `questions.asked` row bound to the
card when it was issued (`QuestionLook.repo`; a card without one accepts the logged repo), else the answer is an
ordinary one; any other answer to a look question is an ordinary answer (`look_state` None, not held). A `look.recorded` row names a question by its `round` and `index`: `posted`
applies when `look_state` is `"posting"` or `"failed"` and `message` is the held answer's id
(`look_state` `"posted"`, `look_comment` the `comment_id`, the message no longer held, so the next
read marks it once), `failed` under the same conditions (`look_state` `"failed"`, `look_reason`,
the message stays held; a later `posted` still applies), `moved` on an unanswered, unwithdrawn look
question (`look_state` `"moved"`, `look_found`, `look_found_state`; the question stays open and an approving
answer replaces it with `"posting"`) and, with a `message` that is the held answer's id, on that answered
question while its `look_state` is `"posting"` or `"failed"`: the console found the pull request moved or ended
after it kept the answer and before it posted it, so the answer is taken back (`answer`, `chosen`,
`answered_at`, `look_message` and `look_repo` cleared, its held message removed and never offered to the manager)
and the question is open again, replaceable or withdrawable by the manager, in the `"moved"` state. Either `moved` row also
adds one `MESSAGE_LOOK_MOVED` message (id the row's `seq`, `text` `LOOK_MOVED_OPEN` naming the head now found, or
`LOOK_MOVED_ENDED` when the pull request is closed or merged, `round_id` the card's) so an idle manager is told the card
is stale: a repeat of the first kind while an identical notice is unread adds none. The owner's panel never shows it
(`view._shown_messages`); any other `look.recorded` row,
an unknown `outcome` or a malformed member changes nothing. `pending_looks(state)` is the
answered questions whose `look_state` is `"posting"` or `"failed"` in `(round_id, index)` order,
none once the sprint has `stopped_at` or a `closing`. A second
answer, or any other such row, changes nothing, and so does an answer naming a withdrawn question:
no answer and no message. A `question.withdrawn` row (#1099) changes a sprint only when
`takes_questions(state)` holds and its `round` and `index` (ints, not bools) name an unanswered,
unwithdrawn question of the sprint: that question's `withdrawn_at` becomes the row's `at`. A
`questions.asked` row the fold accepts first withdraws each own open question its `replaces` marks
name (`withdrawn_at` the row's `at`, `replaced_by` the row's `seq`), then adds its questions; a mark
naming anything else is ignored and the round still folds. `withdrawable(state, round_id, index,
others=())` returns the open question of `state` or raises `Refused`, in this order:
`QUESTION_FOREIGN` when the pair is no question of `state` but one of a sprint in `others`, else
`UNKNOWN_QUESTION`; `ANSWERED_ALREADY`; `WITHDRAWN_ALREADY`. (`TAKEN_BACK` is the answer's refusal
for a withdrawn question.) `parse_withdraw_question_request(body)` reads the manager's
`{"sprint_id", "secret", "round": <int >= 1>, "index": <int >= 0>}` and returns `(sprint_id,
secret, round_id, index)`, as strict as `parse_ask_request`. `open_questions(state)` is the
unanswered, unwithdrawn questions in `(round_id, index)` order, none once the sprint has `stopped_at` or a `closing`, and `round_open(state)` is true while there is one.
`takes_questions(state)` is false once the sprint has `stopped_at`, a `closing` or has ended (`ended_at`); then
a `questions.asked` or `question.answered` row changes nothing (the service refuses `ENDED`). An answer's inbox
entry is `{"id", "kind": "answer", "version": null, "text": <the answer>, "at", "question":
<question text>, "round": <int>, "chosen": <option text> | null, "words": <str> | null}`, where
`words` is the message's `words` when set, else its `text` when `chosen` is null (the owner's own
words), else null (an option alone); every other entry keeps its five keys.

Notices (#1117, ADR-console-044) are what a sprint's manager tells the other managers of its
project: a `claim` ("I am working in this area until ..."), a `heads-up` or a `hand-off` (to the
owner or to another open sprint of the project). They are information, never approval. Two rows
carry them, both kept (`event_log.NOTICE_POSTED`, `NOTICE_WITHDRAWN`; each with the project in its
project column):

    notice.posted     {"sprint_id", "goal": <str>, "notice": {"kind", "text", "what"?, "until"?,
                       "issue"?, "live_fault"?, "to"?}}
    notice.withdrawn  {"sprint_id", "goal": <str>, "notice": <int>}

A third row, `notice.nudged {"sprint_id", "notice", "route", "ok", "reason"?, "listing_failed"?,
"permission"?: {"mode", "reason"}}` (`event_log.NOTICE_NUDGED`, not kept), is the nudge an owner's notice
cost a manager; the fold reads only its `permission`.

`checked_notice(notice)` returns a new dict of exactly the kind's members (`NOTICE_MEMBERS`: a claim
has kind, text, what, until, issue and live_fault; a heads-up kind and text; a hand-off kind, text and to), texts
stripped, or raises `Refused` at the first failure, in this order: not an object
(`NOTICE_NOT_OBJECT`); `kind` missing or not in `NOTICE_KINDS` (`NOTICE_KIND`); a key outside the
kind's members (`NOTICE_EXTRA`, one fixed text per kind that never carries the key); then `text`,
then a claim's `what`, then its `until`: not a string, empty after stripping, or holding a line
break (`NOTICE_MEMBER`), or longer than `MAX_NOTICE_TEXT_CHARS` / `MAX_CLAIM_WHAT_CHARS` /
`MAX_CLAIM_UNTIL_CHARS` after stripping (`NOTICE_TOO_LONG`); then, for a claim, `issue`
(optional; an int of at least 1, not a bool) and `live_fault` (optional; a bool), each refused as
`NOTICE_MEMBER`; then a hand-off's `to`, which is `"owner"` or a sprint id (`NOTICE_MEMBER`).
Every notice refusal is one line built only from fixed
kinds, member names and limits, never from a key or value the manager sent, because the command
prints it and the service answers it as it is. `takes_notices(state)` is `takes_questions(state)`
and no stop requested. `postable_notice(state, notice, others)` refuses, in order: a sprint that
takes no notice (`ALREADY_STOPPING` while a stop waits, else `ENDED`); `checked_notice`; for a claim,
no `issue` (`NOTICE_MEMBER`), then no part in its `what` (`claim_parts`: split on commas, stripped,
empty parts and repeats dropped; `NOTICE_MEMBER`), then a part outside the project (absolute or with
a `..` segment, `outside_claim_part`; `CLAIM_OUTSIDE`), and only then a part naming a whole folder
tree (`wide_claim_part`: a trailing slash, the root, a `**`, a last segment `*`, or a directory
`is_folder` reports; `CLAIM_FOLDER`), so no path leaving the project reaches `is_folder`; the
checked claim keeps `what` as written and `claim_path` / `claim_paths` give the normalized
comparison keys; for a hand-off to a sprint, its own id (`NOTICE_TO_SELF`) or an id that is no sprint of `others` of the
same project that takes notices (`NOTICE_TO_REFUSED`); and a sixth open notice (`NOTICE_LIMIT`);
it never looks at another sprint's claims. `withdrawable_notice(state, notice_id, others)` refuses
a sprint that takes no notice as `postable_notice` does, then returns the open notice of `state`,
or raises `NOTICE_ENDED` (withdrawn or ended), `NOTICE_FOREIGN` (a notice of a sprint in `others`)
or `NOTICE_UNKNOWN`. `open_notices(state)` is the notices neither withdrawn nor ended, in id order
(the row's `seq`); `notice_entry` and `project_notices(states, project_id)` are the wire entries
`{"id", "sprint_id", "title", "kind", "text", "at"}` plus `"what"`, `"until"`, `"issue"`,
`"live_fault"` and `"started"` for a claim (the lowest notice id of the sprint's claims, withdrawn and
ended ones included, naming the same issue, so a withdrawn and reposted claim keeps its slice's start;
the claim's own id when it names no issue) and
`"to"` for a hand-off, of the project's open notices in id order.
`claim_overlaps(entries)` is the console's reading of those entries (#1337, D5-D8): one dict per pair
of claims of two different sprints whose paths overlap, `{"claims": [a, b], "sprints": [...],
"files": [...], "first", "rule"}`, `a` being the claim with the lower `started`. Paths are
compared segment by segment (`claim_paths`, `*` never crosses a `/`, a shorter path reads as a folder);
the rule is `OVERLAP_EARLIER` (the earlier-started slice is `first`), `OVERLAP_FAULT` (the one live-fault
fix is `first`, even when the feature started earlier) or `OVERLAP_UNSETTLED` (both fix a live fault:
`first` None; the owner's page shows it as one line (#1347) and no sprint asks). The console refuses
nothing because of an overlap.
`notice_block` ends with one `- overlap with "<title>" on <files>: ...` line per reading naming the
reader's sprint, saying who lands first (or, unsettled, that the rule cannot order them and the
owner sees it on the page). `notice_block(entries, sprint_id,
now_ms)` renders those entries for the manager of `sprint_id` under `NOTICE_BLOCK_HEAD`, one line
per entry of another sprint (the sprint's own notices are left out), in the order given, and is
`""` when no other sprint's notice is open. The four line forms are
`- claim from "<title>", <age>: <text> (what: <what>; until: <until>)`,
`- heads-up from "<title>", <age>: <text>`, `- hand-off for you from "<title>", <age>: <text>`
(a hand-off whose `to` is `sprint_id`) and `- hand-off from "<title>", <age>: <text>`; the age is
`ago_text` over the entry's `at`. Every field's whitespace runs collapse to one space, so each
notice is one line beginning with `- `. `parse_notice_request(body)`
reads `{"sprint_id", "secret", "notice": <object>}` and returns `(sprint_id, secret, notice)`;
`parse_withdraw_notice_request(body)` reads `{"sprint_id", "secret", "notice": <int >= 1>}` and
returns `(sprint_id, secret, notice_id)`; both are as strict as `parse_ask_request`.

The owner posts a notice too (#1120, ADR-console-053): a heads-up to every sprint of one project,
information only. It reuses the two kept rows with the project in the project column and no
`sprint_id` member, so the sprint fold never sees it:

    notice.posted     {"poster": "owner", "notice": {"kind": "heads-up", "text"}}
    notice.withdrawn  {"poster": "owner", "notice": <int>}

`owner_notices(events, states=None)` folds them into every owner notice per project id (withdrawn
ones included, `states` a dict of tuples carried between calls). A row is an owner row when its
payload has no `sprint_id` and `"poster": "owner"` and its project column is a non-empty string;
any other row, and any owner row of another shape, changes nothing. A posted row adds `Notice(seq,
at, "heads-up", text)` only when `checked_notice` accepts its `notice` and its kind is `heads-up`; a
withdrawn row whose `notice` is an int (not a bool) naming an open owner notice of the same project
sets `withdrawn_at` to the row's `at`. Folding in one call, one row per call or in any split gives
equal results. `open_owner_notices(folded, project_id)` is the project's notices not withdrawn, in
id order. `postable_owner_notice(project_id, text, registered, project_sprints, folded)` refuses,
in order: an unregistered project (`UNREGISTERED`); no sprint of the project that `takes_notices`
(`OWNER_NOTICE_NO_SPRINT`); `checked_notice` of a heads-up of the text (`NOTICE_MEMBER`,
`NOTICE_TOO_LONG`); a sixth open owner notice (`OWNER_NOTICE_LIMIT`, `MAX_OPEN_OWNER_NOTICES`); it
returns `{"kind": "heads-up", "text": <stripped>}`. `withdrawable_owner_notice(project_id,
notice_id, folded, states)` returns the open owner notice of the project, or raises `NOTICE_ENDED`
(withdrawn), `OWNER_NOTICE_MANAGERS` (the id of a notice of any sprint in `states`) or
`NOTICE_UNKNOWN` (anything else, another project's owner notice included).
`withdrawable_notice` takes `owner_ids` and, after the sprint's own notices and before
`NOTICE_FOREIGN`, refuses one of them as `NOTICE_OWNERS`. `owner_notice_entry(notice)` is the wire
entry `{"id", "sprint_id": null, "title": null, "owner": true, "kind", "text", "at"}` and
`project_notices(states, project_id, owner=())` merges the sprints' entries and the owner's by id.
`notice_block` renders an entry with `"owner": true` as `- heads-up from the owner, <age>: <text>`
for every reader. `parse_owner_notice(body)` reads `{"project_id", "text": <str>}` and returns
`(project_id, text)`; `parse_owner_notice_withdrawal(body)` reads `{"project_id", "notice": <int >=
1>}` and returns `(project_id, notice_id)`; both are as strict as `parse_ask_request`.

The fold: a `notice.posted` row for a folded sprint that takes notices and whose `notice`
`checked_notice` accepts adds a `Notice` (id the row's `seq`); any other such row changes nothing.
A `notice.withdrawn` row whose `notice` is an int (not a bool) naming an open notice of a sprint that
takes notices sets that notice's `withdrawn_at` to the row's `at`; anything else changes nothing.
The fold enforces neither the limit nor the addressee: the service does, under its lock. After
every row that names a folded sprint, the landing sweep (`_landed_claims`) sets `ended_at` to the row's
`at` on each open claim whose `issue` the sprint's report lists as landed or held (a claim without an
`issue`, a heads-up and a hand-off are never ended by it), and the end sweep (`_ended_notices`) sets `ended_at` to the
row's `at` on each notice still open when the sprint takes no notice (a stop was requested, it
closed, stopped or is done); `ended_at` is never cleared, so a notice stays ended when its sprint
reopens (a newer brief or report clears a done report), and folding the rows in one call, one row
per call or in any split gives equal states. A dropped sprint leaves the fold with its notices.

A sprint ends with a closing report, and the owner can stop one (#892). Four rows carry that
(`event_log.SPRINT_CLOSED`, `SPRINT_STOP_REQUESTED`, `MANAGER_STOPPED`, `MANAGER_STOP_FAILED`; each
with the project in its project column), the first three kept, `manager.stop_failed` not:

    sprint.closed          {"sprint_id", "goal": <str>, "closing": {"summary": <str>,
                            "issues": [{"issue": <int>, "stage": "landed" | "held" | "dropped"}],
                            "differently": <str>}}
    sprint.stop_requested  {"sprint_id", "goal": <str>}
    manager.stopped        {"sprint_id"}
    manager.stop_failed    {"sprint_id", "reason": <str>}

`parse_close_request(body)` reads the manager's body and returns `(sprint_id, secret, closing)`: a
UTF-8 JSON object of exactly `sprint_id`, `secret` and `closing`, a valid sprint id, a string secret
and a `closing` object whose keys are a subset of `CLOSING_MEMBERS`; anything else is `ValueError`.
`parse_stop(body)` reads the owner's body, exactly `parse_withdraw`'s shape.

`checked_closing(closing, reported)` refuses with `Refused(...)` at the first failure, in
this order. `summary` is a string whose strip is non-empty and at most `MAX_CLOSING_CHARS` code
points and whose `first_line` is at most `MAX_LINE_CHARS`, else `CLOSING_MEMBER` for `summary`; the
first line matching `#` and a digit is `SUMMARY_NUMBER`. `issues` is a list of at most
`MAX_REPORT_ISSUES` objects of exactly `issue` (an int, not a bool, at least 1) and `stage` (one of
`CLOSING_STAGES`), no issue twice, possibly empty, else `CLOSING_MEMBER` for `issues`.
`differently` is like `summary` without the first-line rules. Every number of
`reported` must be an `issue` of the closing (landed, held or dropped), else `NOT_ENDED`. It returns
`{"summary", "issues" (sorted by issue, new dicts), "differently"}` with the texts stripped.
`first_line(summary)` is the first line of `summary.strip()`, itself stripped.

The fold keeps, on each open sprint, `closing` as `Closing(at, summary, first_line, issues,
differently)`, and `stop_at`, `stopped_at`, `stop_reason`, `stop_failed_at` and `done_stopped_at`.
Each row changes only an open sprint:

- `sprint.stop_requested` applies when `stop_at`, `closing` and `stopped_at` are all `None` and the
  sprint has not ended (`ended_at` is `None`, so it is not done by its report either): `stop_at` is
  the row's `at` and one `Message(seq, MESSAGE_STOP, at, None, STOP_TEXT)` is added. Otherwise it
  changes nothing.
- `sprint.closed` applies when `closing` and `stopped_at` are `None`, the `closing` payload is a dict,
  the sprint is `STARTING` or has `stop_at`, and `checked_closing` accepts it with `reported` the
  issue numbers of the sprint's report (none without one); a stopping sprint is held to the same coverage rule.
- `manager.stopped` and `manager.stop_failed` (neither is a manager row) apply only when `stop_at`
  is set and `stopped_at` is `None`: `manager.stopped` sets `stopped_at` and clears `stop_reason` and
  `stop_failed_at`; `manager.stop_failed` with a string `reason` sets `stop_reason` and
  `stop_failed_at`. Anything else changes nothing. `manager.stopped` is kept, so a stop survives
  retention and a restart; a lost `manager.stop_failed` only drops a shown reason and makes the next
  retry due at once. Both also apply to a sprint with a `closing`, no `stop_at` and no
  `done_stopped_at` (#980, a closing report stops the manager's session): `manager.stopped` sets
  `done_stopped_at` and clears `stop_failed_at`, `manager.stop_failed` sets `stop_failed_at` only,
  and neither sets `stopped_at`, `stop_reason` or the "stopped by you" state.

`ended_at(state)` is every route to done, first match: `stopped_at` when set; `None` when `stop_at`
is set (the sprint is stopping); `closing.at` when `closing` is set; `report.at` when the sprint is `STARTING`, no question is open and the
report's phase is `done` and no answered look question still waits for its approval to be posted (`pending_looks`, #1260: a failed post keeps its Retry) (the route that predates the closing report; a newer brief drops that
done report when it is sent, so a replaced sprint is not ended again by the old report); else `None`. A sprint has ended when `ended_at` is not `None`.

`stop_due(state, now_ms)` is true when `stop_at` is set, `stopped_at` is `None`, the closing is set
or `STOP_WAIT_MS` have passed since `stop_at`, and `stop_failed_at` is `None` or `STOP_RETRY_MS` have
passed since it. `STOP_SETTLE_MS` is the service's settle window for a manager the listing may not
show yet and `FINISHED_AFTER_MS` the age after which an ended sprint is shown as finished.
`done_stop_due(state, now_ms, turn_ended)` (#980) is true when `closing` is set, `stop_at` and
`done_stopped_at` are `None`, `turn_ended` (the caller saw the manager's session end a turn after the
closing) is true or `DONE_STOP_WAIT_MS` have passed since `closing.at`, and `stop_failed_at` is `None`
or `STOP_RETRY_MS` have passed since it.
`pending_stops(events, pending=None)` folds the stops a withdrawal leaves to make, keyed by sprint
id: a `goal.withdrawn` row with a string project, `sprint_id` and `goal` adds `PendingStop(sprint_id,
project, goal, at)` (replacing an earlier one); `manager.stopped` for a pending id removes it;
`manager.stop_failed` for a pending id with a string `reason` sets `reason` and `failed_at`; every
other row changes nothing, and folding `a + b` equals folding `b` onto the fold of `a`.
`pending_due(stop, now_ms)` is true when `failed_at` is `None` or `STOP_RETRY_MS` have passed since
it. `closing_text(landed, held, dropped)` is `<landed> landed` then `, <held> held for
verification` and `, <dropped> dropped` for each non-zero count. The new texts are `STOP_TEXT`,
`STOPPING_TEXT`, `STOPPED_TEXT`, `CLOSING_MEMBER`, `SUMMARY_NUMBER`, `NOT_ENDED`, `ENDED`,
`ALREADY_STOPPING`, `STOP_FAILED_TEXT` and `UNSTOPPED_TEXT`.

The module reads no clock and no environment; only the secret helpers touch the filesystem.
"""

import fnmatch
import json
import math
import os
import posixpath
import re
import secrets
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.console import deliveries
from agent_tools.console.deliveries import DELIVERY_SEEN
from agent_tools.console.event_log import (BRIEF_APPROVED, BRIEF_REPLIED, BRIEF_SENT, GOAL_STATED,
                                           GOAL_WITHDRAWN, LOOK_RECORDED, MANAGER_FAILED, MANAGER_NO_PROGRESS,
                                           MANAGER_NUDGED, MANAGER_STALLED, MANAGER_STARTED,
                                           MANAGER_STOP_FAILED, MANAGER_STOPPED, MANAGER_WAITING,
                                           MANAGER_WOKEN, NOTICE_NUDGED, NOTICE_POSTED,
                                           normal_login,
                                           NOTICE_WITHDRAWN,
                                           PICTURE_STORED, QUESTION_ANSWERED,
                                           QUESTION_WITHDRAWN, QUESTIONS_ASKED,
                                           SPRINT_ANSWERED, SPRINT_CLOSED, SPRINT_CONTINUED,
                                           SPRINT_MESSAGED, SPRINT_NUDGED, SPRINT_READ,
                                           SPRINT_REPORTED, SPRINT_STOP_REQUESTED, Event)
from agent_tools.console.manager import FAILED_TEXT, MISSING_TEXT, UNAVAILABLE_TEXT, plain_reason
from agent_tools.console.manager import WAITING_TEXT as MANAGER_WAITING_TEXT
from agent_tools.console.permission import Permission, from_payload
from agent_tools.console.pictures import PICTURE_ID
from agent_tools.console.sessions import SEEN

MAX_GOAL_CHARS = 2000
MAX_REPLY_CHARS = 2000
MAX_MESSAGE_CHARS = 2000
PARTS = ("title", "done", "excluded", "slices", "risks", "asks")
MAY_BE_EMPTY = ("excluded", "risks", "asks")
NONE = "none"
APPROVED = "approved"
CHANGES = "changes"
WITHDRAWN = "withdrawn"
STARTING = "starting"
STARTING_TEXT = "starting"
NO_MANAGER_AFTER_MS = 120_000
DRAFTING = "drafting"
DRAFTING_TEXT = "drafting the brief"
NO_MANAGER_TEXT = "no manager has picked this up"
STARTED = "started"
FAILED = "failed"
MISSING = "missing"
UNAVAILABLE = "unavailable"
WAKE = "wake"
TAKEOVER = "takeover"
STALLED = "stalled"
STALLED_TEXT = "managers keep failing"
QUOTA = "quota"
QUOTA_TEXT = MANAGER_WAITING_TEXT
NO_PROGRESS_TEXT = "the manager has stopped making progress on {title}"
NOT_STUCK = "this sprint's manager is not waiting for you"
REPORT_MEMBERS = ("status", "phase", "milestone", "tracker_url", "issues", "inbox", "next")
REPORT_OPTIONAL = ("wait_until", "paused")
MAX_WAIT_HOURS = 24
REPORT_PHASES = ("running", "closing", "done")
LANDED = "landed"
HELD = "held"
DROPPED = "dropped"
REPORT_STAGES = ("queued", "planning", "plan review", "building", "final review", "verifying",
                 "landing", "working", LANDED, HELD)
CLOSING_STAGES = (LANDED, HELD, DROPPED)
CLOSING_MEMBERS = ("summary", "issues", "differently")
MAX_CLOSING_CHARS = 4000
STOP_WAIT_MS = 600_000
STOP_RETRY_MS = 60_000
STOP_SETTLE_MS = 30_000
DONE_STOP_WAIT_MS = 120_000
FINISHED_AFTER_MS = 86_400_000
CLOSED_OUT = "closed out"
MAX_LINE_CHARS = 500
MIN_OPTIONS = 2
MAX_OPTIONS = 4
MAX_ROUND_QUESTIONS = 10
MAX_QUESTION_CHARS = 1000
MAX_TITLE_CHARS = 60
MAX_ASK_CHARS = 140
MAX_CONTEXT_CHARS = 400
MAX_OPTION_CHARS = 80
MAX_PICTURES = 8
MAX_PICTURE_LINE_CHARS = 140
PAIRS = ("before", "after")


def is_look(pairs: Iterable[str | None]) -> bool:
    """A look is a question carrying both a before and an after picture; one alone is a plain picture."""
    return set(PAIRS) <= set(pairs)


MAX_REPORT_ISSUES = 200
ON_TRACK = "on_track"
ON_TRACK_TEXT = "on track"
WAITING = "waiting"
WAITING_TEXT = "waiting on you ({n})"
QUIET = "quiet"
QUIET_TEXT = "quiet for {minutes} min \u2014 may be stuck"
CLOSING = "closing"
CLOSING_TEXT = "closing"
DONE = "done"
DONE_TEXT = "done"
STOPPING = "stopping"
STOPPING_TEXT = "stopping"
STOPPED = "stopped"
STOPPED_TEXT = "stopped by you"
BALL_MANAGER = "manager"
BALL_OWNER = "owner"
BALL_NOBODY = "nobody"
BALL_TEXT = {BALL_MANAGER: "manager working", BALL_OWNER: "waiting on you",
             BALL_NOBODY: "nothing running, may be stuck"}
NOW_STOPPING_TEXT = "finishing what is mid-merge, then stopping"
NOW_ANSWER_TEXT = "waiting for your answer in the manager's terminal"
NOW_PERMISSION_TEXT = "waiting for your permission in the manager's terminal"
NOW_DEAF_TEXT = "the manager cannot hear the console: bring it back or drop the sprint"
NOW_DRAFTING_TEXT = "drafting the brief"
NOW_BRIEF_TEXT = "waiting for your approval of the brief"
NOW_QUESTION_TEXT = "waiting for your answer: {question}"
NOW_DECISION_TEXT = "waiting for your decision on the tracker"
NOW_LOOK_RETRY_TEXT = "waiting for you to press Retry on your approval"
NOW_LOOK_RECORDING_TEXT = "recording your approval"
NOW_STALLED_TEXT = "waiting for you: its managers keep failing"
NOW_FAILED_START_TEXT = "waiting for you: the manager failed to start"
NOW_NO_PROGRESS_TEXT = "waiting for you: the manager has stopped making progress"
NOW_QUOTA_TEXT = "waiting for its account's usage to reset"
NOW_WAIT_TEXT = "waiting until"
NOW_PAUSED_TEXT = "paused: {reason}"
NOW_UNREAD_TEXT = "waiting for the manager to read your message"
NOW_STARTING_TEXT = "starting the work"
NOW_STAGE_TEXT = "{stage} {count} of {total}: {milestone}"
NOW_QUIET_TEXT = "last seen {phrase}"
CHECK_LINE_TEXT = "Your check: {question}"
NOW_CI_TEXT = "waiting for CI on its pull request"
NOW_COMMITTING_TEXT = "a delivery is committing"
NOW_RELEASE_TEXT = "waiting for a release step"
NOW_LOCK_TEXT = "waiting its turn to merge"
NOW_REFUSED_TEXT = "merge refused: {reason}"
REFUSED_STATUS = re.compile(r"merge refused:\s*(\S.*)", re.IGNORECASE | re.DOTALL)
SECRETS_DIR = "sprint-secrets"
SPRINT_ID = re.compile(r"[0-9a-f]{16}")

UNREGISTERED = "this project is not registered"
EMPTY = "write the goal first"
TOO_LONG = "a goal is at most 2000 characters"
NOT_OPEN = "this sprint is not open"
SECRET_REFUSED = "secret refused"
MISSING_PART = "the brief has no {part}"
REPORT_MEMBER = "the report has no valid {member}"
STATUS_NUMBER = "the status line names an issue number"
WAIT_PAST = "the report's wait_until is not in the future"
WAIT_TOO_FAR = f"the report's wait_until is more than {MAX_WAIT_HOURS} hours ahead"
PAUSED = "paused"
WAIT_UNTIL = "wait_until"
PAUSED_NUMBER = "the pause reason names an issue number"
WAIT_AND_PAUSE = "a report states a wait_until or a paused reason, not both"
CLOSING_MEMBER = "the closing report has no valid {member}"
SUMMARY_NUMBER = "the summary's first line names an issue number"
NOT_ENDED = "an issue of this sprint is neither landed nor dropped"
ENDED = "this sprint has ended"
ALREADY_STOPPING = "this sprint is already stopping"
STOP_FAILED_TEXT = "could not stop the manager: {reason}; trying again"
UNSTOPPED_TEXT = "The manager of a dropped sprint could not be stopped: {reason}; trying again"
STOP_TEXT = ("The owner stopped this sprint: finish what is mid-merge, start nothing new, and send "
             "your closing report with sprint close.")
NOT_STARTED = "this sprint's brief is not approved"
NOT_WAITING = "this brief is not waiting for you"
REPLACED = "a newer brief replaced this one"
EMPTY_REPLY = "write the reply first"
REPLY_TOO_LONG = "a reply is at most 2000 characters"
UNKNOWN = "this sprint is not known"
HAS_MANAGER = "this sprint has a manager"
LAUNCHING = "a manager is starting for this sprint"
TOO_SOON = "retry is offered two minutes after the goal"
EMPTY_MESSAGE = "write the message first"
MESSAGE_TOO_LONG = "a message is at most 2000 characters"
UNKNOWN_MESSAGE = "this message is not known"
NO_QUESTIONS = "the round has no questions"
TOO_MANY_QUESTIONS = "a round has at most 10 questions"
BAD_BLOCKER = "the round's blocker is not true or false"
QUESTION_SHAPE = ("question {n} is not an object of question, context, blocks, options, "
                  "recommended, pictures, look and replaces")
LOOK_SHAPE = "question {n}'s look is not an object of issue, pr, head and approve"
LOOK_APPROVE = "question {n}'s look approve is not one of its options"
LOOK_APPROVE_WORDS = ("question {n}'s look approve is also in its needs_words: choosing it records the "
                      "approval and takes no words, so no answer could approve")
LOOK_PAIR = ('question {n} is a look card and needs a picture marked "pair": "before" and one '
             'marked "pair": "after": attach the pictures with pictures')
REPLACES_SHAPE = "question {n}'s replaces is not an object of round and index"
REPLACES_TWICE = "question {n} replaces a question another question of the round replaces"
REPLACES_REFUSED = "question {n} cannot replace round {round} question {index}: {reason}"
PICTURES_SHAPE = "question {n}'s pictures are not a list"
TOO_MANY_PICTURES = f"question {{n}} has more than {MAX_PICTURES} pictures"
PICTURE_SHAPE = "question {n} picture {m} is not an object of picture, line and pair"
PICTURE_MEMBER = "question {n} picture {m} has no valid {member}"
LINE_TOO_LONG = f"question {{n}} picture {{m}}'s line is over {MAX_PICTURE_LINE_CHARS} characters"
PAIR_TWICE = "question {n} marks two pictures {pair}"
LOOK_WITHOUT_PICTURE = ('question {n} "{ask}" names screenshots, a PNG file or a screenshots '
                        "folder but attaches no picture: attach the pictures with pictures, or "
                        "reword it")
PICTURE_UNKNOWN = "question {n} picture {m} is not known"
PICTURE_FOREIGN = "question {n} picture {m} was sent by another sprint"
PART_PICTURES_SHAPE = "the {owner}'s pictures are not a list"
PART_TOO_MANY_PICTURES = f"the {{owner}} has more than {MAX_PICTURES} pictures"
PART_PICTURE_SHAPE = "the {owner}'s picture {m} is not an object of picture, line and pair"
PART_PICTURE_MEMBER = "the {owner}'s picture {m} has no valid {member}"
PART_LINE_TOO_LONG = f"the {{owner}}'s picture {{m}}'s line is over {MAX_PICTURE_LINE_CHARS} characters"
PART_PAIR_TWICE = "the {owner} marks two pictures {pair}"
PART_PICTURE_UNKNOWN = "the {owner}'s picture {m} is not known"
PART_PICTURE_FOREIGN = "the {owner}'s picture {m} was sent by another sprint"
TITLE_TOO_LONG = f"the brief's title is at most {MAX_TITLE_CHARS} characters"
ASK_TOO_LONG = (f"question {{n}}'s ask is over {MAX_ASK_CHARS} characters: keep it to the question "
                "the owner answers and move the rest into context")
CONTEXT_TOO_LONG = f"question {{n}}'s context is over {MAX_CONTEXT_CHARS} characters"
OPTION_TOO_LONG = f"question {{n}} has an option over {MAX_OPTION_CHARS} characters"
QUESTION_MEMBER = "question {n} has no valid {member}"
OPTION_COUNT = "question {n} needs two to four options"
OPTION_TWICE = "question {n} offers one option twice"
NO_RECOMMENDATION = "question {n} recommends none of its options"
NEEDS_WORDS_SHAPE = "question {n}'s needs_words must list some of its options, each once"
OWNER_ONLY_SHAPE = "question {n}'s owner_only must be true when given"
CONSEQUENTIAL_SHAPE = "question {n}'s consequential must be true when given"
WORDS_NEEDED = "say what to change"
ROUND_OPEN = "a round of questions is already open"
UNKNOWN_QUESTION = "this question is not known"
ANSWERED_ALREADY = "this question is already answered"
QUESTION_FOREIGN = "this question belongs to another sprint"
WITHDRAWN_ALREADY = "this question is already withdrawn"
TAKEN_BACK = "the manager took this question back"
MAX_NOTICE_TEXT_CHARS = 280
MAX_CLAIM_WHAT_CHARS = 200
MAX_CLAIM_UNTIL_CHARS = 140
MAX_OPEN_NOTICES = 5
NOTICE_OWNER = "owner"
NOTICE_KINDS = ("claim", "heads-up", "hand-off")
NOTICE_MEMBERS = {"claim": ("kind", "text", "what", "until", "issue", "live_fault"),
                  "heads-up": ("kind", "text"),
                  "hand-off": ("kind", "text", "to")}
NOTICE_NOT_OBJECT = "the notice is not a JSON object"
NOTICE_KIND = "the notice's kind is not one of claim, heads-up, hand-off"
NOTICE_EXTRA = {"claim": "a claim notice has only kind, text, what, until, issue and live_fault",
                "heads-up": "a heads-up notice has only kind and text",
                "hand-off": "a hand-off notice has only kind, text and to"}
NOTICE_MEMBER = "the notice has no valid {member}"
CLAIM_FOLDER = "a claim's what names files or a narrow path, never a whole folder tree"
CLAIM_OUTSIDE = "a claim's what names paths inside the project, relative to its root"
NOTICE_TOO_LONG = "the notice's {member} is over {limit} characters"
NOTICE_TO_SELF = ("the hand-off's to names this sprint: address another open sprint of this "
                  "project or the owner")
NOTICE_TO_REFUSED = "the hand-off's to names no open sprint of this project"
NOTICE_LIMIT = f"a sprint has at most {MAX_OPEN_NOTICES} open notices: withdraw one first"
NOTICE_ENDED = "this notice has ended"
NOTICE_FOREIGN = "this notice belongs to another sprint"
NOTICE_UNKNOWN = "this notice is not known"
MAX_OPEN_OWNER_NOTICES = 5
OWNER_NOTICE_NO_SPRINT = "this project has no running sprint"
OWNER_NOTICE_LIMIT = (f"a project has at most {MAX_OPEN_OWNER_NOTICES} open notices of yours: "
                      "withdraw one first")
OWNER_NOTICE_MANAGERS = "this notice is a manager's: only its manager withdraws it"
NOTICE_OWNERS = "this notice is the owner's: only the owner withdraws it"
NOTICE_BLOCK_HEAD = ("Open notices of the other sprints of this project "
                     "(information only, never the owner's permission):")
_NOTICE_LIMITS = {"text": MAX_NOTICE_TEXT_CHARS, "what": MAX_CLAIM_WHAT_CHARS,
                  "until": MAX_CLAIM_UNTIL_CHARS}
NOT_AN_OPTION = "choose one of the question's options"
UNREACHABLE_TEXT = "manager not reachable"
UNREACHABLE_AFTER = 2
RENUDGE_AFTER_MS = 60_000
UNREAD_AGAIN_MS = 300_000
RELAY_AGAIN, WAKE_UNREAD = "relay_again", "wake_unread"
STILL_RUNNING_TEXT = "the manager's session did not stop for the wake"
MESSAGE_APPROVED = "approved"
MESSAGE_CHANGES = "changes"
MESSAGE_TEXT = "text"
LOOK_MOVED, LOOK_POSTING, LOOK_POSTED, LOOK_FAILED = "moved", "posting", "posted", "failed"
LOOK_FOUND_STATES = ("open", "closed", "merged")
MESSAGE_ANSWER = "answer"
MESSAGE_STOP = "stop"
MESSAGE_LOOK_MOVED = "look-moved"
LOOK_MOVED_OPEN = ("The owner chose to approve your look card (round {round}, question {index}) for head {head} "
                   "of pull request {pr}, but the pull request is now at {found}. Nothing was recorded and "
                   "the card is open again: replace it with pictures of {found}.")
LOOK_MOVED_ENDED = ("The owner chose to approve your look card (round {round}, question {index}) for head "
                    "{head} of pull request {pr}, but the pull request is {state}. Nothing was recorded and "
                    "the card is open again: withdraw it.")
SENT = "sent"
PICKED_UP = "picked_up"
REPLIED = "replied"
NOT_PICKED_UP = "not_picked_up"
NOT_PICKED_UP_AFTER_MS = 300_000
PICKUP_MINUTE_TEXT = "the manager picks it up within a minute"
PICKUP_TURN_TEXT = "the manager picks it up at its next turn"
TELL_MINUTE_TEXT = "The manager picks it up within a minute."
TELL_TURN_TEXT = "The manager picks it up at its next turn."
PICKED_UP_TEXT = "picked up"
SENT_ENDED_TEXT = "sent"
REPLIED_TEXT = "replied"
NOT_PICKED_UP_TEXT = "not picked up after 5 min"
RETRY_ACTION_TEXT = "Press Retry to start a new manager."
NUDGE_ACTION_TEXT = "Tell the manager again, or drop the sprint."
TURN_ACTION_TEXT = ("It waits for the manager's next turn; "
                    "drop the sprint if none comes.")
MANAGER_SESSION_NAME = re.compile(r"(?P<project>.+) sprint (?P<sprint>[0-9a-f]{16})")

_MINUTE_MS = 60_000
_HOUR_MS = 3_600_000
_DAY_MS = 86_400_000


class Refused(Exception):
    """The write was not made; `str(error)` is the one-line reason."""


class SecretRefused(Refused):
    """The sprint's secret was wrong; the service answers 403."""


@dataclass(frozen=True)
class Brief:
    version: int
    parts: dict
    sent_at: str
    decision: str
    reply: str | None
    decided_at: str | None = None
    pictures: tuple["QuestionPicture", ...] = ()


@dataclass(frozen=True)
class Report:
    at: str
    status: str
    phase: str
    milestone: str
    tracker_url: str
    issues: tuple[tuple[int, str], ...]
    inbox: tuple[int, ...]
    next_step: str
    pictures: tuple["QuestionPicture", ...] = ()
    wait_until: str | None = None
    paused: str | None = None


@dataclass(frozen=True)
class Closing:
    at: str
    summary: str
    first_line: str
    issues: tuple[tuple[int, str], ...]
    differently: str


@dataclass(frozen=True)
class PendingStop:
    sprint_id: str
    project_id: str
    goal: str
    at: str
    reason: str | None = None
    failed_at: str | None = None


@dataclass(frozen=True)
class Observed:
    issue: int
    moved_ms: int
    session_id: str
    run_id: str
    stage: deliveries.IssueStage


@dataclass(frozen=True)
class Revival:
    at: str
    how: str
    ok: bool
    reason: str | None = None
    back: bool = False


@dataclass(frozen=True)
class Manager:
    state: str
    at: str
    profile: str | None = None
    session_name: str | None = None
    reason: str | None = None
    until: str | None = None
    takeover: bool = False


@dataclass(frozen=True)
class Message:
    message_id: int
    kind: str
    at: str
    version: int | None
    text: str | None
    delivered_at: str | None = None
    read_at: str | None = None
    reply: str | None = None
    reply_at: str | None = None
    question: str | None = None
    round_id: int | None = None
    chosen: str | None = None
    held: bool = False
    words: str | None = None
    by: str | None = None
    relays: int = 0
    relayed_at: str | None = None
    woken_at: str | None = None


@dataclass(frozen=True)
class QuestionPicture:
    picture: str
    line: str
    pair: str | None = None


@dataclass(frozen=True)
class QuestionLook:
    issue: int
    pr: int
    head: str
    approve: str
    repo: str | None = None


@dataclass(frozen=True)
class Question:
    round_id: int
    index: int
    at: str
    blocker: bool
    question: str
    blocks: str
    options: tuple[str, ...]
    recommended: str
    answer: str | None = None
    chosen: str | None = None
    differs: bool | None = None
    answered_at: str | None = None
    context: str | None = None
    pictures: tuple[QuestionPicture, ...] = ()
    withdrawn_at: str | None = None
    replaced_by: int | None = None
    look: QuestionLook | None = None
    look_state: str | None = None
    look_reason: str | None = None
    look_found: str | None = None
    look_found_state: str | None = None
    look_comment: int | None = None
    look_message: int | None = None
    look_repo: str | None = None
    needs_words: tuple[str, ...] = ()
    words: str | None = None
    answered_by: str | None = None
    owner_only: bool = False
    consequential: bool = False


@dataclass(frozen=True)
class Notice:
    notice_id: int
    at: str
    kind: str
    text: str
    what: str | None = None
    until: str | None = None
    to: str | None = None
    withdrawn_at: str | None = None
    ended_at: str | None = None
    issue: int | None = None
    live_fault: bool = False


@dataclass(frozen=True)
class SprintState:
    sprint_id: str
    project_id: str
    goal: str
    stated_seq: int
    stated_at: str
    brief: Brief | None = None
    manager: Manager | None = None
    report: Report | None = None
    observed: tuple[Observed, ...] = ()
    moved_ms: int | None = None
    messages: tuple[Message, ...] = ()
    failed_nudges: int = 0
    last_nudge_at: str | None = None
    last_nudge_ok: bool | None = None
    manager_session: str | None = None
    questions: tuple[Question, ...] = ()
    closing: Closing | None = None
    stop_at: str | None = None
    stopped_at: str | None = None
    stop_reason: str | None = None
    stop_failed_at: str | None = None
    done_stopped_at: str | None = None
    manager_seen_seq: int | None = None
    revivals: tuple[Revival, ...] = ()
    stalled: str | None = None
    stalled_at: str | None = None
    idle_nudges: int = 0
    idle_nudged_at: str | None = None
    no_progress_at: str | None = None
    pictures: frozenset[str] = frozenset()
    notices: tuple[Notice, ...] = ()
    permission: Permission | None = None
    started_by: str | None = None
    delivered: frozenset[int] = frozenset()

    @property
    def state(self) -> str:
        if self.brief is not None and self.brief.decision == APPROVED:
            return STARTING
        return DRAFTING


def _decoded(body: bytes) -> object:
    try:
        return json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                          parse_constant=reject_nonfinite_literal)
    except RecursionError as error:
        raise ValueError("the body is nested too deeply") from error


def _object(body: bytes, keys: set[str], project: bool = True) -> dict:
    value = _decoded(body)
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"the body must be an object of {', '.join(sorted(keys))}")
    if project:
        project_id = value["project_id"]
        if not isinstance(project_id, str) or not project_id:
            raise ValueError("project_id must be a non-empty string")
    return value


def _sprint_id(value: object) -> str:
    if not isinstance(value, str) or SPRINT_ID.fullmatch(value) is None:
        raise ValueError("sprint_id must be 16 lowercase hex characters")
    return value


def _version(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("version must be an integer of at least 1")
    return value


def parse_goal(body: bytes) -> tuple[str, str]:
    value = _object(body, {"project_id", "goal"})
    if not isinstance(value["goal"], str):
        raise ValueError("goal must be a string")
    return value["project_id"], value["goal"]


def parse_withdraw(body: bytes) -> tuple[str, str]:
    value = _object(body, {"project_id", "sprint_id"})
    return value["project_id"], _sprint_id(value["sprint_id"])


def parse_retry(body: bytes) -> tuple[str, str]:
    value = _object(body, {"project_id", "sprint_id"})
    return value["project_id"], _sprint_id(value["sprint_id"])


def parse_continue(body: bytes) -> tuple[str, str]:
    value = _object(body, {"project_id", "sprint_id"})
    return value["project_id"], _sprint_id(value["sprint_id"])


def _manager_request(body: bytes, key: str, members: tuple[str, ...]) -> tuple[str, str, dict, bool]:
    """A manager's sprint, secret and `key` object with an optional `"dry_run": true`."""
    value = _decoded(body)
    dry_run = isinstance(value, dict) and "dry_run" in value
    if dry_run and value["dry_run"] is not True:
        raise ValueError("dry_run must be true when given")
    value = _object(body, {"sprint_id", "secret", key} | ({"dry_run"} if dry_run else set()),
                    project=False)
    sprint_id = _sprint_id(value["sprint_id"])
    if not isinstance(value["secret"], str):
        raise ValueError("secret must be a string")
    given = value[key]
    if not isinstance(given, dict) or not set(given) <= {*members, "pictures"}:
        raise ValueError(f"{key} must be an object of {', '.join((*members, 'pictures'))}")
    return sprint_id, value["secret"], given, dry_run


def parse_brief_request(body: bytes) -> tuple[str, str, dict, bool]:
    return _manager_request(body, "brief", PARTS)


def parse_report_request(body: bytes) -> tuple[str, str, dict, bool]:
    return _manager_request(body, "report", (*REPORT_MEMBERS, *REPORT_OPTIONAL))


ROUND_KEYS = ("questions", "blocker")


def parse_ask_request(body: bytes) -> tuple[str, str, dict, bool]:
    value = _decoded(body)
    dry_run = isinstance(value, dict) and "dry_run" in value
    if dry_run and value["dry_run"] is not True:
        raise ValueError("dry_run must be true when given")
    value = _object(body, {"sprint_id", "secret", "round"} | ({"dry_run"} if dry_run else set()),
                    project=False)
    sprint_id = _sprint_id(value["sprint_id"])
    if not isinstance(value["secret"], str):
        raise ValueError("secret must be a string")
    round_ = value["round"]
    if not isinstance(round_, dict) or not set(round_) <= set(ROUND_KEYS):
        raise ValueError(f"round must be an object of {', '.join(ROUND_KEYS)}")
    return sprint_id, value["secret"], round_, dry_run


def _count(value: object, least: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < least:
        raise ValueError(f"must be an integer of at least {least}")
    return value


def parse_round_answer(body: bytes) -> tuple[str, str, int, int, int | None, str | None]:
    value = _decoded(body)
    base = {"project_id", "sprint_id", "round", "question"}
    if (not isinstance(value, dict)
            or set(value) not in (base | {"choice"}, base | {"text"}, base | {"choice", "text"})):
        raise ValueError("the body must be an object of project_id, sprint_id, round, question "
                         "and one or both of choice and text")
    project_id = value["project_id"]
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("project_id must be a non-empty string")
    text = value.get("text")
    if "text" in value and not isinstance(text, str):
        raise ValueError("text must be a string")
    choice = _count(value["choice"], 0) if "choice" in value else None
    return (project_id, _sprint_id(value["sprint_id"]), _count(value["round"], 1),
            _count(value["question"], 0), choice, text)


def parse_look_retry(body: bytes) -> tuple[str, str, int, int]:
    value = _object(body, {"project_id", "sprint_id", "round", "question"})
    return (value["project_id"], _sprint_id(value["sprint_id"]), _count(value["round"], 1),
            _count(value["question"], 0))


def parse_withdraw_question_request(body: bytes) -> tuple[str, str, int, int]:
    value = _object(body, {"sprint_id", "secret", "round", "index"}, project=False)
    sprint_id = _sprint_id(value["sprint_id"])
    if not isinstance(value["secret"], str):
        raise ValueError("secret must be a string")
    return sprint_id, value["secret"], _count(value["round"], 1), _count(value["index"], 0)


def parse_notice_request(body: bytes) -> tuple[str, str, dict]:
    value = _object(body, {"sprint_id", "secret", "notice"}, project=False)
    sprint_id = _sprint_id(value["sprint_id"])
    if not isinstance(value["secret"], str):
        raise ValueError("secret must be a string")
    if not isinstance(value["notice"], dict):
        raise ValueError("notice must be an object")
    return sprint_id, value["secret"], value["notice"]


def parse_withdraw_notice_request(body: bytes) -> tuple[str, str, int]:
    value = _object(body, {"sprint_id", "secret", "notice"}, project=False)
    sprint_id = _sprint_id(value["sprint_id"])
    if not isinstance(value["secret"], str):
        raise ValueError("secret must be a string")
    return sprint_id, value["secret"], _count(value["notice"], 1)


def parse_owner_notice(body: bytes) -> tuple[str, str]:
    value = _object(body, {"project_id", "text"})
    if not isinstance(value["text"], str):
        raise ValueError("text must be a string")
    return value["project_id"], value["text"]


def parse_owner_notice_withdrawal(body: bytes) -> tuple[str, int]:
    value = _object(body, {"project_id", "notice"})
    return value["project_id"], _count(value["notice"], 1)


def parse_close_request(body: bytes) -> tuple[str, str, dict]:
    value = _object(body, {"sprint_id", "secret", "closing"}, project=False)
    sprint_id = _sprint_id(value["sprint_id"])
    if not isinstance(value["secret"], str):
        raise ValueError("secret must be a string")
    closing = value["closing"]
    if not isinstance(closing, dict) or not set(closing) <= set(CLOSING_MEMBERS):
        raise ValueError(f"closing must be an object of {', '.join(CLOSING_MEMBERS)}")
    return sprint_id, value["secret"], closing


def parse_stop(body: bytes) -> tuple[str, str]:
    value = _object(body, {"project_id", "sprint_id"})
    return value["project_id"], _sprint_id(value["sprint_id"])


def parse_message(body: bytes) -> tuple[str, str, str]:
    value = _object(body, {"project_id", "sprint_id", "text"})
    if not isinstance(value["text"], str):
        raise ValueError("text must be a string")
    return value["project_id"], _sprint_id(value["sprint_id"]), value["text"]


def parse_inbox_request(body: bytes) -> tuple[str, str]:
    value = _object(body, {"sprint_id", "secret"}, project=False)
    sprint_id = _sprint_id(value["sprint_id"])
    if not isinstance(value["secret"], str):
        raise ValueError("secret must be a string")
    return sprint_id, value["secret"]


PERMIT_PHASES = ("judge", "landed")
MAX_PERMIT_SESSION_CHARS = 128
MAX_PERMIT_COMMAND_CHARS = 8192


@dataclass(frozen=True)
class PermitRequest:
    sprint_id: str
    secret: str
    phase: str
    session_id: str
    tool_use_id: str
    command: str


def parse_permit_request(body: bytes) -> PermitRequest:
    """The manager's permit request: an object of exactly the five members, none repeated (#1377)."""
    value = _object(body, {"sprint_id", "secret", "phase", "session_id", "tool_use_id", "command"},
                    project=False)
    sprint_id = _sprint_id(value["sprint_id"])
    if not isinstance(value["secret"], str):
        raise ValueError("secret must be a string")
    if value["phase"] not in PERMIT_PHASES:
        raise ValueError("phase must be judge or landed")
    session_id = value["session_id"]
    if not isinstance(session_id, str) or not 1 <= len(session_id) <= MAX_PERMIT_SESSION_CHARS:
        raise ValueError("session_id must be a string of 1 to 128 characters")
    tool_use_id = value["tool_use_id"]
    if not isinstance(tool_use_id, str) or not 1 <= len(tool_use_id) <= MAX_PERMIT_SESSION_CHARS:
        raise ValueError("tool_use_id must be a string of 1 to 128 characters")
    command = value["command"]
    if not isinstance(command, str) or len(command) > MAX_PERMIT_COMMAND_CHARS:
        raise ValueError("command must be a string of at most 8192 characters")
    return PermitRequest(sprint_id, value["secret"], value["phase"], session_id, tool_use_id, command)


def parse_message_reply_request(body: bytes) -> tuple[str, str, int, str]:
    value = _object(body, {"sprint_id", "secret", "message", "reply"}, project=False)
    sprint_id = _sprint_id(value["sprint_id"])
    if not isinstance(value["secret"], str):
        raise ValueError("secret must be a string")
    if not _number(value["message"]):
        raise ValueError("message must be an integer of at least 1")
    if not isinstance(value["reply"], str):
        raise ValueError("reply must be a string")
    return sprint_id, value["secret"], value["message"], value["reply"]


def parse_approve(body: bytes) -> tuple[str, str, int]:
    value = _object(body, {"project_id", "sprint_id", "version"})
    return value["project_id"], _sprint_id(value["sprint_id"]), _version(value["version"])


def parse_reply(body: bytes) -> tuple[str, str, int, str]:
    value = _object(body, {"project_id", "sprint_id", "version", "reply"})
    if not isinstance(value["reply"], str):
        raise ValueError("reply must be a string")
    return (value["project_id"], _sprint_id(value["sprint_id"]), _version(value["version"]),
            value["reply"])


def checked_goal(text: str) -> str:
    goal = text.strip()
    if not goal:
        raise Refused(EMPTY)
    if len(goal) > MAX_GOAL_CHARS:
        raise Refused(TOO_LONG)
    return goal


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def cut(text: str, limit: int) -> str:
    """`text` when it fits `limit`, else its first `limit - 1` characters, stripped, and "…"."""
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def goal_title(goal: str) -> str:
    """The first sentence of a goal's first line, cut to `MAX_TITLE_CHARS`."""
    lines = goal.strip().splitlines()
    line = lines[0] if lines else ""
    found = re.match(r"(.+?[.!?])(?=\s|$)", line)
    return cut(found.group(1) if found else line, MAX_TITLE_CHARS)


def sprint_title(state: "SprintState") -> str:
    """The brief's title, else the goal's first sentence; at most `MAX_TITLE_CHARS` long."""
    parts = state.brief.parts if state.brief is not None else None
    title = parts.get("title") if isinstance(parts, dict) else None
    if isinstance(title, str) and title.strip():
        return cut(" ".join(title.split()), MAX_TITLE_CHARS)
    return goal_title(state.goal)


def checked_brief(brief: dict) -> dict:
    checked: dict = {}
    for part in PARTS:
        value = brief.get(part)
        if part == "title":
            if not _text(value) or "\n" in value or "\r" in value:
                raise Refused(MISSING_PART.format(part=part))
            if len(value.strip()) > MAX_TITLE_CHARS:
                raise Refused(TITLE_TOO_LONG)
            checked[part] = value.strip()
        elif part == "done":
            if not _text(value):
                raise Refused(MISSING_PART.format(part=part))
            checked[part] = value.strip()
        else:
            if (not isinstance(value, list) or not all(_text(item) for item in value)
                    or (not value and part not in MAY_BE_EMPTY)):
                raise Refused(MISSING_PART.format(part=part))
            checked[part] = [item.strip() for item in value]
    pictures = checked_pictures("brief", brief["pictures"]) if "pictures" in brief else []
    if pictures:
        checked["pictures"] = pictures
    return checked


def _line(value: object) -> bool:
    return (isinstance(value, str) and bool(value.strip()) and "\n" not in value
            and "\r" not in value and len(value.strip()) <= MAX_LINE_CHARS)


def _number(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _issue_row(row: object) -> bool:
    return (isinstance(row, dict) and set(row) == {"issue", "stage"} and _number(row["issue"])
            and row["stage"] in REPORT_STAGES)


def _valid_report_member(member: str, value: object) -> bool:
    if member in ("status", "milestone", "next"):
        return _line(value)
    if member == "phase":
        return value in REPORT_PHASES
    if member == "tracker_url":
        return (isinstance(value, str) and value.startswith("https://")
                and len(value) <= MAX_LINE_CHARS
                and all(char.isprintable() and not char.isspace() for char in value))
    if member == "issues":
        return (isinstance(value, list) and len(value) <= MAX_REPORT_ISSUES
                and all(_issue_row(row) for row in value)
                and len({row["issue"] for row in value}) == len(value))
    return isinstance(value, list) and len(value) <= MAX_REPORT_ISSUES and all(
        _number(item) for item in value)


EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
EPOCH_NAIVE = datetime(1970, 1, 1)


WAIT_TIME = re.compile(
    r"([0-9]{4}-[0-9]{2}-[0-9]{2})[T ]([0-9]{2}:[0-9]{2})(?::([0-9]{2})(?:[.,]([0-9]+))?)?"
    r"(?:Z|z|[+-]00(?::?00)?)")


def _wait_us(value: object) -> Fraction | None:
    """The exact microseconds since the epoch a `wait_until` states, or None when it is not one.

    A date, a time to the minute, optional seconds with any number of fractional digits, and a UTC
    zone (`Z`, `+00:00`, `+0000` or `+00`): nothing else, so an offset that is not zero, a
    fractional offset and a time with no zone are not times. Integer and `Fraction` arithmetic
    only: no float and no truncation to the millisecond or the microsecond.
    """
    if not isinstance(value, str) or len(value) > MAX_LINE_CHARS:
        return None
    found = WAIT_TIME.fullmatch(value)
    if found is None:
        return None
    day, minute, seconds, fraction = found.groups()
    try:
        whole = datetime.fromisoformat(f"{day}T{minute}:{seconds or '00'}")
    except ValueError:
        return None
    return ((whole - EPOCH_NAIVE) // timedelta(microseconds=1)
            + Fraction(int(fraction or 0), 10 ** len(fraction or "")) * 1_000_000)


def _wait_text(us: Fraction) -> str:
    """The `isoformat()` of a wait's UTC time rounded up to the microsecond.

    The hold compares whole milliseconds with the time, and a whole number is under the time
    exactly when it is under the time rounded up, so the rounding changes no release.
    """
    return (EPOCH + timedelta(microseconds=math.ceil(us))).isoformat()


def checked_report(report: dict, now_ms: int | Fraction | None = None) -> dict:
    for member in REPORT_MEMBERS:
        if not _valid_report_member(member, report.get(member)):
            raise Refused(REPORT_MEMBER.format(member=member))
        if member == "status" and re.search(r"#\d", report["status"].strip()):
            raise Refused(STATUS_NUMBER)
    wait = None
    if "wait_until" in report:
        wait = _wait_us(report["wait_until"])
        if wait is None:
            raise Refused(REPORT_MEMBER.format(member="wait_until"))
        if now_ms is not None:
            if wait <= now_ms * 1000:
                raise Refused(WAIT_PAST)
            if wait > (now_ms + MAX_WAIT_HOURS * 3_600_000) * 1000:
                raise Refused(WAIT_TOO_FAR)
    paused = None
    if "paused" in report:
        if not _line(report["paused"]):
            raise Refused(REPORT_MEMBER.format(member="paused"))
        paused = report["paused"].strip()
        if re.search(r"#\d", paused):
            raise Refused(PAUSED_NUMBER)
    if wait is not None and paused is not None:
        raise Refused(WAIT_AND_PAUSE)
    pictures = checked_pictures("report", report["pictures"]) if "pictures" in report else []
    checked = {"status": report["status"].strip(), "phase": report["phase"],
               "milestone": report["milestone"].strip(), "tracker_url": report["tracker_url"],
               "issues": sorted(({"issue": row["issue"], "stage": row["stage"]}
                                 for row in report["issues"]), key=lambda row: row["issue"]),
               "inbox": sorted(set(report["inbox"])), "next": report["next"].strip()}
    if wait is not None:
        checked["wait_until"] = _wait_text(wait)
    if paused is not None:
        checked["paused"] = paused
    if pictures:
        checked["pictures"] = pictures
    return checked


# A question about look or layout (#1092): the word screenshot or screenshots (also "screen shot"),
# a `.png` file, or a folder with a `screenshots` segment, which the word's boundary also matches.
LOOK_WORDS = re.compile(r"\bscreen ?shots?\b|\.png\b|(?:^|[/\\])screenshots(?:[/\\]|$)",
                        re.IGNORECASE)


def _checked_question(n: int, question: object, limits: bool, files_withheld: bool) -> dict:
    if not isinstance(question, dict) or not set(question) <= {"question", "context", "blocks",
                                                                "options", "recommended",
                                                                "needs_words", "owner_only",
                                                                "consequential", "pictures",
                                                                "look", "replaces"}:
        raise Refused(QUESTION_SHAPE.format(n=n))
    text, blocks = question.get("question"), question.get("blocks")
    if not _text(text):
        raise Refused(QUESTION_MEMBER.format(n=n, member="question"))
    if limits and len(text.strip()) > MAX_ASK_CHARS:
        raise Refused(ASK_TOO_LONG.format(n=n))
    if not limits and len(text.strip()) > MAX_QUESTION_CHARS:
        raise Refused(QUESTION_MEMBER.format(n=n, member="question"))
    context = question.get("context")
    if "context" in question:
        if not _text(context):
            raise Refused(QUESTION_MEMBER.format(n=n, member="context"))
        if limits and len(context.strip()) > MAX_CONTEXT_CHARS:
            raise Refused(CONTEXT_TOO_LONG.format(n=n))
        if not limits and len(context.strip()) > MAX_QUESTION_CHARS:
            raise Refused(QUESTION_MEMBER.format(n=n, member="context"))
    if not _line(blocks):
        raise Refused(QUESTION_MEMBER.format(n=n, member="blocks"))
    options = question.get("options")
    if not isinstance(options, list) or not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        raise Refused(OPTION_COUNT.format(n=n))
    if not all(_text(option) for option in options):
        raise Refused(QUESTION_MEMBER.format(n=n, member="options"))
    if limits and any(len(option.strip()) > MAX_OPTION_CHARS for option in options):
        raise Refused(OPTION_TOO_LONG.format(n=n))
    if not all(_line(option) for option in options):
        raise Refused(QUESTION_MEMBER.format(n=n, member="options"))
    stripped = [option.strip() for option in options]
    if len(set(stripped)) != len(stripped):
        raise Refused(OPTION_TWICE.format(n=n))
    recommended = question.get("recommended")
    if not isinstance(recommended, str) or recommended.strip() not in stripped:
        raise Refused(NO_RECOMMENDATION.format(n=n))
    look = question.get("look")
    if "look" in question:
        if not _look_mark(look):
            raise Refused(LOOK_SHAPE.format(n=n))
        if look["approve"].strip() not in stripped:
            raise Refused(LOOK_APPROVE.format(n=n))
    needs_words = question.get("needs_words")
    if "needs_words" in question:
        kept = ([word.strip() for word in needs_words if isinstance(word, str)]
                if isinstance(needs_words, list) else [])
        if (not isinstance(needs_words, list) or not needs_words
                or len(kept) != len(needs_words) or len(set(kept)) != len(kept)
                or not set(kept) <= set(stripped)):
            raise Refused(NEEDS_WORDS_SHAPE.format(n=n))
        if "look" in question and look["approve"].strip() in kept:
            raise Refused(LOOK_APPROVE_WORDS.format(n=n))
    if "owner_only" in question and question["owner_only"] is not True:
        raise Refused(OWNER_ONLY_SHAPE.format(n=n))
    if "consequential" in question and question["consequential"] is not True:
        raise Refused(CONSEQUENTIAL_SHAPE.format(n=n))
    replaces = question.get("replaces")
    if "replaces" in question and not _replaces_mark(replaces):
        raise Refused(REPLACES_SHAPE.format(n=n))
    pictures = _checked_pictures(n, question["pictures"], limits) if "pictures" in question else []
    if (limits and not files_withheld and "look" in question
            and not is_look(member.get("pair") for member in pictures)):
        raise Refused(LOOK_PAIR.format(n=n))
    if (limits and not files_withheld and not pictures
            and any(LOOK_WORDS.search(part) for part in (text, context) if part)):
        raise Refused(LOOK_WITHOUT_PICTURE.format(n=n, ask=text.strip()))
    checked = {"question": text.strip(), "blocks": blocks.strip(), "options": stripped,
               "recommended": recommended.strip()}
    if "context" in question:
        checked["context"] = context.strip()
    if "needs_words" in question:
        checked["needs_words"] = kept
    if "owner_only" in question:
        checked["owner_only"] = True
    if "consequential" in question:
        checked["consequential"] = True
    if pictures:
        checked["pictures"] = pictures
    if "look" in question:
        checked["look"] = {"issue": look["issue"], "pr": look["pr"], "head": look["head"],
                           "approve": look["approve"].strip()}
    if "replaces" in question:
        checked["replaces"] = {"round": replaces["round"], "index": replaces["index"]}
    return checked


HEAD = re.compile(r"[0-9a-f]{40}")


def _look_mark(look: object) -> bool:
    return (isinstance(look, dict) and set(look) == {"issue", "pr", "head", "approve"}
            and _id(look["issue"]) and look["issue"] >= 1 and _id(look["pr"]) and look["pr"] >= 1
            and isinstance(look["head"], str) and HEAD.fullmatch(look["head"]) is not None
            and isinstance(look["approve"], str))


def _replaces_mark(mark: object) -> bool:
    return (isinstance(mark, dict) and set(mark) == {"round", "index"}
            and _id(mark["round"]) and mark["round"] >= 1
            and _id(mark["index"]) and mark["index"] >= 0)


def _checked_pictures(n: int, pictures: object, limits: bool) -> list[dict]:
    return _checked_picture_list(
        pictures, limits, PICTURES_SHAPE.format(n=n), TOO_MANY_PICTURES.format(n=n),
        lambda m: PICTURE_SHAPE.format(n=n, m=m),
        lambda m, member: PICTURE_MEMBER.format(n=n, m=m, member=member),
        lambda m: LINE_TOO_LONG.format(n=n, m=m), lambda pair: PAIR_TWICE.format(n=n, pair=pair))


def checked_pictures(owner: str, pictures: object, *, limits: bool = True) -> list[dict]:
    """A brief's or report's picture list, checked as a question's is, under the `PART_*` reasons."""
    return _checked_picture_list(
        pictures, limits, PART_PICTURES_SHAPE.format(owner=owner),
        PART_TOO_MANY_PICTURES.format(owner=owner),
        lambda m: PART_PICTURE_SHAPE.format(owner=owner, m=m),
        lambda m, member: PART_PICTURE_MEMBER.format(owner=owner, m=m, member=member),
        lambda m: PART_LINE_TOO_LONG.format(owner=owner, m=m),
        lambda pair: PART_PAIR_TWICE.format(owner=owner, pair=pair))


def _checked_picture_list(pictures: object, limits: bool, not_a_list: str, too_many: str,
                          shape: Callable[[int], str], member_reason: Callable[[int, str], str],
                          too_long: Callable[[int], str],
                          twice: Callable[[str], str]) -> list[dict]:
    if not isinstance(pictures, list):
        raise Refused(not_a_list)
    if len(pictures) > MAX_PICTURES:
        raise Refused(too_many)
    checked = []
    for m, row in enumerate(pictures, 1):
        if (not isinstance(row, dict) or not set(row) <= {"picture", "line", "pair"}
                or "picture" not in row or "line" not in row):
            raise Refused(shape(m))
        picture, line = row["picture"], row["line"]
        if not isinstance(picture, str) or not PICTURE_ID.fullmatch(picture):
            raise Refused(member_reason(m, "picture"))
        if not _text(line):
            raise Refused(member_reason(m, "line"))
        if limits and len(line.strip()) > MAX_PICTURE_LINE_CHARS:
            raise Refused(too_long(m))
        if not _line(line):
            raise Refused(member_reason(m, "line"))
        if "pair" in row and row["pair"] not in PAIRS:
            raise Refused(member_reason(m, "pair"))
        member = {"picture": picture, "line": line.strip()}
        if "pair" in row:
            member["pair"] = row["pair"]
        checked.append(member)
    pairs = [member["pair"] for member in checked if "pair" in member]
    for pair in pairs:
        if pairs.count(pair) > 1:
            raise Refused(twice(pair))
    return checked


def picture_ids(members: Iterable[dict]) -> list[str]:
    """The unique `picture` values of checked members, in first-seen order."""
    ids: list[str] = []
    for member in members:
        if member["picture"] not in ids:
            ids.append(member["picture"])
    return ids


def round_pictures(checked: dict) -> list[str]:
    """The unique picture ids of a checked round, in question then picture order."""
    return picture_ids(member for question in checked["questions"]
                       for member in question.get("pictures", ()))


def checked_round(round_: dict, *, limits: bool = True, files_withheld: bool = False) -> dict:
    questions = round_.get("questions")
    if not isinstance(questions, list) or not questions:
        raise Refused(NO_QUESTIONS)
    if len(questions) > MAX_ROUND_QUESTIONS:
        raise Refused(TOO_MANY_QUESTIONS)
    blocker = round_.get("blocker", False)
    if not isinstance(blocker, bool):
        raise Refused(BAD_BLOCKER)
    checked = [_checked_question(n, question, limits, files_withheld)
               for n, question in enumerate(questions, 1)]
    marks = [(row["replaces"]["round"], row["replaces"]["index"]) if "replaces" in row else None
             for row in checked]
    for n, mark in enumerate(marks, 1):
        if mark is not None and mark in marks[:n - 1]:
            raise Refused(REPLACES_TWICE.format(n=n))
    return {"blocker": blocker, "questions": checked}


def replaced(checked: dict) -> list[tuple[int, int]]:
    """The `(round, index)` each question's `replaces` names in a checked round, in question order."""
    return [(row["replaces"]["round"], row["replaces"]["index"])
            for row in checked["questions"] if "replaces" in row]


def first_line(summary: str) -> str:
    return summary.strip().split("\n", 1)[0].strip()


def _closing_text_ok(value: object) -> bool:
    return (isinstance(value, str) and bool(value.strip())
            and len(value.strip()) <= MAX_CLOSING_CHARS)


def checked_closing(closing: dict, reported: Iterable[int]) -> dict:
    summary, issues = closing.get("summary"), closing.get("issues")
    if not _closing_text_ok(summary) or len(first_line(summary)) > MAX_LINE_CHARS:
        raise Refused(CLOSING_MEMBER.format(member="summary"))
    if re.search(r"#\d", first_line(summary)):
        raise Refused(SUMMARY_NUMBER)
    if not (isinstance(issues, list) and len(issues) <= MAX_REPORT_ISSUES
            and all(isinstance(row, dict) and set(row) == {"issue", "stage"}
                    and _number(row["issue"]) and row["stage"] in CLOSING_STAGES
                    for row in issues)
            and len({row["issue"] for row in issues}) == len(issues)):
        raise Refused(CLOSING_MEMBER.format(member="issues"))
    differently = closing.get("differently")
    if not _closing_text_ok(differently):
        raise Refused(CLOSING_MEMBER.format(member="differently"))
    if not set(reported) <= {row["issue"] for row in issues}:
        raise Refused(NOT_ENDED)
    return {"summary": summary.strip(),
            "issues": sorted(({"issue": row["issue"], "stage": row["stage"]} for row in issues),
                             key=lambda row: row["issue"]),
            "differently": differently.strip()}


def checked_reply(text: str) -> str:
    if not text.strip():
        raise Refused(EMPTY_REPLY)
    if len(text) > MAX_REPLY_CHARS:
        raise Refused(REPLY_TOO_LONG)
    return text


def checked_message(text: str) -> str:
    if not text.strip():
        raise Refused(EMPTY_MESSAGE)
    if len(text) > MAX_MESSAGE_CHARS:
        raise Refused(MESSAGE_TOO_LONG)
    return text


def message_state(message: Message, now_ms: int | None) -> str:
    if message.reply is not None:
        return REPLIED
    if message.read_at is not None:
        return PICKED_UP
    if now_ms is not None and now_ms - _ms(message.at) >= NOT_PICKED_UP_AFTER_MS:
        return NOT_PICKED_UP
    return SENT


def unread(state: SprintState) -> tuple[Message, ...]:
    return tuple(message for message in state.messages
                 if message.read_at is None and not message.held)


def pending_looks(state: SprintState) -> tuple[Question, ...]:
    """The answered look questions whose approval is not yet on the tracker, in `(round_id, index)` order."""
    if state.stopped_at is not None or state.closing is not None:
        return ()
    return tuple(sorted((question for question in state.questions
                         if question.look_state in (LOOK_POSTING, LOOK_FAILED)),
                        key=lambda question: (question.round_id, question.index)))


def unreachable(state: SprintState) -> bool:
    return state.failed_nudges >= UNREACHABLE_AFTER


def unread_step(state: SprintState, now_ms: int) -> str | None:
    """Return `RELAY_AGAIN`, `WAKE_UNREAD` or None: what an unread, once relayed message needs now."""
    if unreachable(state):
        return None
    if (state.last_nudge_at is not None and not state.last_nudge_ok
            and now_ms - _ms(state.last_nudge_at) < UNREAD_AGAIN_MS):
        return None
    due = [message for message in unread(state)
           if message.woken_at is None and message.relayed_at is not None
           and now_ms - _ms(message.relayed_at) >= UNREAD_AGAIN_MS]
    if state.manager_session is not None and any(message.relays >= 2 for message in due):
        return WAKE_UNREAD
    if any(message.relays == 1 for message in due):
        return RELAY_AGAIN
    return None


def open_questions(state: SprintState) -> tuple[Question, ...]:
    if state.stopped_at is not None or state.closing is not None:
        return ()
    return tuple(sorted((question for question in state.questions
                         if question.answer is None and question.withdrawn_at is None),
                        key=lambda question: (question.round_id, question.index)))


def withdrawable(state: SprintState, round_id: int, index: int,
                 others: Iterable[SprintState] = ()) -> Question:
    """The open question `(round_id, index)` of `state`, else `Refused` with why it cannot be taken back."""
    for question in state.questions:
        if (question.round_id, question.index) == (round_id, index):
            if question.answer is not None:
                raise Refused(ANSWERED_ALREADY)
            if question.withdrawn_at is not None:
                raise Refused(WITHDRAWN_ALREADY)
            return question
    if any((question.round_id, question.index) == (round_id, index)
           for other in others for question in other.questions):
        raise Refused(QUESTION_FOREIGN)
    raise Refused(UNKNOWN_QUESTION)


def round_open(state: SprintState) -> bool:
    return bool(open_questions(state))


def takes_questions(state: SprintState) -> bool:
    """False once the sprint has stopped, is closed or has ended: it then asks and is asked no more."""
    return state.stopped_at is None and state.closing is None and ended_at(state) is None


def takes_notices(state: SprintState) -> bool:
    """False once the sprint has a stop requested or takes no question: it then posts no notice."""
    return takes_questions(state) and state.stop_at is None


def open_notices(state: SprintState) -> tuple[Notice, ...]:
    """The notices neither withdrawn nor ended, in id order."""
    return tuple(sorted((notice for notice in state.notices
                         if notice.withdrawn_at is None and notice.ended_at is None),
                        key=lambda notice: notice.notice_id))


def _notice_line(value: object) -> bool:
    return (isinstance(value, str) and bool(value.strip()) and "\n" not in value
            and "\r" not in value)


def claim_parts(what: str) -> tuple[str, ...]:
    """A claim's `what` split on commas: each part stripped, empty parts and repeats dropped."""
    parts: dict[str, None] = {}
    for part in what.split(","):
        if part.strip():
            parts.setdefault(part.strip())
    return tuple(parts)


def claim_path(part: str) -> str:
    """The one normalized, project-relative key a claim part is compared by."""
    return posixpath.normpath(part)


def claim_paths(what: str) -> tuple[str, ...]:
    """`claim_path` of each part of `what`, repeats dropped, in first-seen order."""
    return tuple(dict.fromkeys(claim_path(part) for part in claim_parts(what)))


def outside_claim_part(part: str) -> bool:
    """True when the part is absolute or climbs out of the project with a `..` segment."""
    return part.startswith("/") or ".." in part.split("/")


def wide_claim_part(part: str, is_folder: Callable[[str], bool]) -> bool:
    """True when the part names a whole folder tree: a trailing slash, the root, a `**`, a last
    segment of `*` and `?` that holds a `*` (it matches every name), or a path, wildcards read as
    patterns, that `is_folder` finds to be a directory."""
    path = claim_path(part)
    last = path.split("/")[-1]
    return (part.endswith("/") or path == "." or "**" in path
            or ("*" in last and not last.strip("*?")) or is_folder(path))


def _no_folder(path: str) -> bool:
    return False


def checked_notice(notice: object) -> dict:
    """The notice reduced to its kind's members, texts stripped, else `Refused` at the first failure."""
    if not isinstance(notice, dict):
        raise Refused(NOTICE_NOT_OBJECT)
    kind = notice.get("kind")
    if not isinstance(kind, str) or kind not in NOTICE_KINDS:
        raise Refused(NOTICE_KIND)
    members = NOTICE_MEMBERS[kind]
    if any(key not in members for key in notice):
        raise Refused(NOTICE_EXTRA[kind])
    checked: dict = {"kind": kind}
    for member in ("text", "what", "until"):
        if member not in members:
            continue
        value = notice.get(member)
        if not _notice_line(value):
            raise Refused(NOTICE_MEMBER.format(member=member))
        if len(value.strip()) > _NOTICE_LIMITS[member]:
            raise Refused(NOTICE_TOO_LONG.format(member=member, limit=_NOTICE_LIMITS[member]))
        checked[member] = value.strip()
    if kind == "claim":
        if "issue" in notice:
            issue = notice["issue"]
            if not isinstance(issue, int) or isinstance(issue, bool) or issue < 1:
                raise Refused(NOTICE_MEMBER.format(member="issue"))
            checked["issue"] = issue
        if "live_fault" in notice:
            if not isinstance(notice["live_fault"], bool):
                raise Refused(NOTICE_MEMBER.format(member="live_fault"))
            checked["live_fault"] = notice["live_fault"]
    if kind == "hand-off":
        to = notice.get("to")
        if not isinstance(to, str) or (to != NOTICE_OWNER and SPRINT_ID.fullmatch(to) is None):
            raise Refused(NOTICE_MEMBER.format(member="to"))
        checked["to"] = to
    return checked


def _refused_notices(state: SprintState) -> None:
    if not takes_notices(state):
        raise Refused(ALREADY_STOPPING if state.stop_at is not None and ended_at(state) is None
                      else ENDED)


def postable_notice(state: SprintState, notice: object, others: Iterable[SprintState],
                    is_folder: Callable[[str], bool] = _no_folder) -> dict:
    """The checked notice `state` may post now, else `Refused` with why not."""
    _refused_notices(state)
    checked = checked_notice(notice)
    if checked["kind"] == "claim":
        if "issue" not in checked:
            raise Refused(NOTICE_MEMBER.format(member="issue"))
        parts = claim_parts(checked["what"])
        if not parts:
            raise Refused(NOTICE_MEMBER.format(member="what"))
        if any(outside_claim_part(part) for part in parts):
            raise Refused(CLAIM_OUTSIDE)
        if any(wide_claim_part(part, is_folder) for part in parts):
            raise Refused(CLAIM_FOLDER)
    to = checked.get("to")
    if checked["kind"] == "hand-off" and to != NOTICE_OWNER:
        if to == state.sprint_id:
            raise Refused(NOTICE_TO_SELF)
        if not any(other.sprint_id == to and other.project_id == state.project_id
                   and takes_notices(other) for other in others):
            raise Refused(NOTICE_TO_REFUSED)
    if len(open_notices(state)) >= MAX_OPEN_NOTICES:
        raise Refused(NOTICE_LIMIT)
    return checked


def withdrawable_notice(state: SprintState, notice_id: int, others: Iterable[SprintState],
                        owner_ids: Collection[int] = frozenset()) -> Notice:
    """The open notice `notice_id` of `state`, else `Refused` with why it cannot be taken back."""
    _refused_notices(state)
    for notice in state.notices:
        if notice.notice_id == notice_id:
            if notice.withdrawn_at is not None or notice.ended_at is not None:
                raise Refused(NOTICE_ENDED)
            return notice
    if notice_id in owner_ids:
        raise Refused(NOTICE_OWNERS)
    if any(notice.notice_id == notice_id for other in others for notice in other.notices):
        raise Refused(NOTICE_FOREIGN)
    raise Refused(NOTICE_UNKNOWN)


def open_owner_notices(folded: Mapping[str, tuple[Notice, ...]],
                       project_id: str) -> tuple[Notice, ...]:
    """The project's owner notices not withdrawn, in id order."""
    return tuple(sorted((notice for notice in folded.get(project_id, ())
                         if notice.withdrawn_at is None), key=lambda notice: notice.notice_id))


def postable_owner_notice(project_id: str, text: object, registered: bool,
                          project_sprints: Iterable[SprintState],
                          folded: Mapping[str, tuple[Notice, ...]]) -> dict:
    """The heads-up the owner may post to the project now, else `Refused` with why not."""
    if not registered:
        raise Refused(UNREGISTERED)
    if not any(state.project_id == project_id and takes_notices(state)
               for state in project_sprints):
        raise Refused(OWNER_NOTICE_NO_SPRINT)
    checked = checked_notice({"kind": "heads-up", "text": text})
    if len(open_owner_notices(folded, project_id)) >= MAX_OPEN_OWNER_NOTICES:
        raise Refused(OWNER_NOTICE_LIMIT)
    return checked


def withdrawable_owner_notice(project_id: str, notice_id: int,
                              folded: Mapping[str, tuple[Notice, ...]],
                              states: Iterable[SprintState]) -> Notice:
    """The open owner notice `notice_id` of the project, else `Refused` with why it cannot end."""
    for notice in folded.get(project_id, ()):
        if notice.notice_id == notice_id:
            if notice.withdrawn_at is not None:
                raise Refused(NOTICE_ENDED)
            return notice
    if any(notice.notice_id == notice_id for state in states for notice in state.notices):
        raise Refused(OWNER_NOTICE_MANAGERS)
    raise Refused(NOTICE_UNKNOWN)


def notice_entry(state: SprintState, notice: Notice) -> dict:
    entry = {"id": notice.notice_id, "sprint_id": state.sprint_id, "title": sprint_title(state),
             "kind": notice.kind, "text": notice.text}
    if notice.kind == "claim":
        entry["what"], entry["until"] = notice.what, notice.until
        entry["issue"], entry["live_fault"] = notice.issue, notice.live_fault
        entry["started"] = (notice.notice_id if notice.issue is None else min(
            other.notice_id for other in state.notices
            if other.kind == "claim" and other.issue == notice.issue))
    if notice.kind == "hand-off":
        entry["to"] = notice.to
    entry["at"] = notice.at
    return entry


def owner_notice_entry(notice: Notice) -> dict:
    return {"id": notice.notice_id, "sprint_id": None, "title": None, "owner": True,
            "kind": notice.kind, "text": notice.text, "at": notice.at}


def project_notices(states: Iterable[SprintState], project_id: str,
                    owner: Iterable[Notice] = ()) -> list[dict]:
    """The open notices of the project's sprints and the owner's, in id order."""
    return sorted([*(notice_entry(state, notice) for state in states
                     if state.project_id == project_id for notice in open_notices(state)),
                   *(owner_notice_entry(notice) for notice in owner)],
                  key=lambda entry: entry["id"])


OVERLAP_EARLIER = "earlier-started"
OVERLAP_FAULT = "live-fault"
OVERLAP_UNSETTLED = "unsettled"
_WILDCARDS = "*?["


def _segment_tokens(segment: str) -> list[str]:
    """`*`, `?`, a bracket class as `fnmatch` reads it, or one literal character, each a token."""
    tokens, i = [], 0
    while i < len(segment):
        if segment[i] == "[":
            j = i + 1
            if j < len(segment) and segment[j] == "!":
                j += 1
            if j < len(segment) and segment[j] == "]":
                j += 1
            while j < len(segment) and segment[j] != "]":
                j += 1
            if j < len(segment):
                tokens.append(segment[i:j + 1])
                i = j + 1
                continue
        tokens.append(segment[i])
        i += 1
    return tokens


def _is_class(token: str) -> bool:
    return len(token) > 1


def _classes_meet(x: str, y: str) -> bool:
    """True when some character is in both bracket classes: an endpoint, a neighbour of one, or a
    character neither names (two negated classes) is tried."""
    named = set(x[1:-1] + y[1:-1])
    tried = {chr(n) for c in named for n in (ord(c) - 1, ord(c), ord(c) + 1) if 0 <= n <= 0x10FFFF}
    outside = next(chr(n) for n in range(0x10FFFF, 0, -1) if chr(n) not in named | tried)
    return any(fnmatch.fnmatchcase(c, x) and fnmatch.fnmatchcase(c, y) for c in tried | {outside})


def _stand_together(x: str, y: str) -> bool:
    """True when two single-character tokens may stand for one character (class and class: yes)."""
    if x == "?" or y == "?":
        return True
    if _is_class(x) and _is_class(y):
        return _classes_meet(x, y)
    if _is_class(x):
        return fnmatch.fnmatchcase(y, x)
    if _is_class(y):
        return fnmatch.fnmatchcase(x, y)
    return x == y


def _segments_meet(first: str, second: str) -> bool:
    """True when some name without a `/` matches both segments read as `fnmatch` patterns."""
    xs, ys = _segment_tokens(first), _segment_tokens(second)
    reached = {(0, 0)}
    todo = [(0, 0)]
    while todo:
        i, j = todo.pop()
        steps = []
        if i < len(xs) and xs[i] == "*":
            steps.append((i + 1, j))
            if j < len(ys) and ys[j] != "*":
                steps.append((i, j + 1))
        if j < len(ys) and ys[j] == "*":
            steps.append((i, j + 1))
            if i < len(xs) and xs[i] != "*":
                steps.append((i + 1, j))
        if i < len(xs) and j < len(ys) and "*" not in (xs[i], ys[j]) \
                and _stand_together(xs[i], ys[j]):
            steps.append((i + 1, j + 1))
        for step in steps:
            if step not in reached:
                reached.add(step)
                todo.append(step)
    return (len(xs), len(ys)) in reached


def _overlapping_files(first: str, second: str) -> list[str]:
    """The files two claim paths both name, `[]` when they share none (a shorter path is a folder)."""
    xs = [] if first == "." else first.split("/")
    ys = [] if second == "." else second.split("/")
    depth = min(len(xs), len(ys))
    if not all(_segments_meet(xs[k], ys[k]) for k in range(depth)):
        return []
    if len(xs) < len(ys):
        return [second]
    if len(ys) < len(xs):
        return [first]
    first_glob = any(c in first for c in _WILDCARDS)
    second_glob = any(c in second for c in _WILDCARDS)
    if first_glob and second_glob:
        return [first, second]
    return [second] if first_glob else [first]


def _claim_start(entry: Mapping) -> int:
    return entry.get("started", entry["id"])


def claim_overlaps(entries: Iterable[Mapping]) -> list[dict]:
    """One reading per pair of slices with overlapping open claims, in `(start, start)` order.

    A slice is a sprint's claims for one issue. A slice is a live-fault fix when any of its
    overlapping claims is; its claim in the reading is its earliest such claim, else its earliest."""
    claims = [entry for entry in entries
              if entry.get("kind") == "claim" and entry.get("owner") is not True]
    pairs: dict[frozenset, dict] = {}
    for index, one in enumerate(claims):
        for two in claims[index + 1:]:
            if one["sprint_id"] == two["sprint_id"]:
                continue
            files = {file for p in claim_paths(one["what"]) for q in claim_paths(two["what"])
                     for file in _overlapping_files(p, q)}
            if not files:
                continue
            slices = [(c["sprint_id"], c.get("issue", c["id"])) for c in (one, two)]
            group = pairs.setdefault(frozenset(slices), {"files": set(), "claims": {}})
            group["files"] |= files
            for slice_key, claim in zip(slices, (one, two)):
                group["claims"].setdefault(slice_key, []).append(claim)
    readings = []
    for group in pairs.values():
        speaking = []
        for slice_claims in group["claims"].values():
            faulted = [c for c in slice_claims if c.get("live_fault") is True]
            speaking.append(min(faulted or slice_claims, key=lambda c: (_claim_start(c), c["id"])))
        a, b = sorted(speaking, key=lambda c: (_claim_start(c), c["id"]))
        fault_a, fault_b = a.get("live_fault") is True, b.get("live_fault") is True
        if fault_a and fault_b:
            first, rule = None, OVERLAP_UNSETTLED
        elif fault_a != fault_b:
            first, rule = (a if fault_a else b)["id"], OVERLAP_FAULT
        else:
            first, rule = a["id"], OVERLAP_EARLIER
        reading = {"claims": [a["id"], b["id"]], "sprints": [a["sprint_id"], b["sprint_id"]],
                   "files": sorted(group["files"]), "first": first, "rule": rule}
        readings.append(((_claim_start(a), _claim_start(b), a["id"], b["id"]), reading))
    return [reading for _, reading in sorted(readings, key=lambda keyed: keyed[0])]


def _one_line(value: object) -> str:
    return " ".join(str(value).split())


def notice_block(entries: Iterable[Mapping], sprint_id: str, now_ms: int) -> str:
    """The open notices of the other sprints as a head and one `- ` line each, or `""`."""
    entries = list(entries)
    lines = []
    for entry in entries:
        if entry.get("owner") is True:
            lines.append(f"- heads-up from the owner, "
                         f"{ago_text(now_ms - _ms(entry['at']))}: {_one_line(entry['text'])}")
            continue
        if entry["sprint_id"] == sprint_id:
            continue
        title, text = _one_line(entry["title"]), _one_line(entry["text"])
        age = ago_text(now_ms - _ms(entry["at"]))
        if entry["kind"] == "claim":
            what, until = _one_line(entry["what"]), _one_line(entry["until"])
            lines.append(f'- claim from "{title}", {age}: {text} (what: {what}; until: {until})')
        elif entry["kind"] == "hand-off":
            form = "hand-off for you" if entry["to"] == sprint_id else "hand-off"
            lines.append(f'- {form} from "{title}", {age}: {text}')
        else:
            lines.append(f'- heads-up from "{title}", {age}: {text}')
    if lines:
        titles = {entry["sprint_id"]: entry["title"] for entry in entries
                  if entry.get("kind") == "claim" and entry.get("owner") is not True}
        for reading in claim_overlaps(entries):
            if sprint_id not in reading["sprints"]:
                continue
            other = next(s for s in reading["sprints"] if s != sprint_id)
            who, files = _one_line(titles[other]), _one_line(", ".join(reading["files"]))
            head = f'- overlap with "{who}" on {files}: '
            if reading["rule"] == OVERLAP_UNSETTLED:
                lines.append(head + "both fix a live fault and the rule cannot order them; "
                                    "keep working, the owner sees this overlap on the page")
            elif reading["claims"].index(reading["first"]) == reading["sprints"].index(sprint_id):
                lines.append(head + "your slice lands first; theirs rebases")
            else:
                lines.append(head + "their slice lands first; rebase yours after it lands")
    return "\n".join([NOTICE_BLOCK_HEAD, *lines]) if lines else ""


def inbox_entry(message: Message) -> dict:
    entry = {"id": message.message_id, "kind": message.kind, "version": message.version,
             "text": message.text, "at": message.at}
    if message.by is not None:
        entry["by"] = message.by
    if message.kind == MESSAGE_ANSWER:
        words = (message.words if message.words is not None
                 else message.text if message.chosen is None else None)
        entry.update(question=message.question, round=message.round_id, chosen=message.chosen,
                     words=words)
    return entry


def _with_message(state: SprintState, message: Message) -> SprintState:
    messages = sorted((*state.messages, message), key=lambda item: item.message_id)
    return replace(state, messages=tuple(messages))


def _read_back_pictures(owner: str, logged: dict) -> tuple["QuestionPicture", ...]:
    """The pictures a logged brief or report carries; none when absent or when they fail the check."""
    if "pictures" not in logged:
        return ()
    try:
        checked = checked_pictures(owner, logged["pictures"], limits=False)
    except Refused:
        return ()
    return tuple(QuestionPicture(p["picture"], p["line"], p.get("pair")) for p in checked)


def _folded_brief(state: SprintState, event: Event) -> SprintState:
    payload = event.payload
    version = payload.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        return state
    brief = state.brief
    if event.kind == BRIEF_SENT:
        logged = payload.get("brief")
        if isinstance(logged, dict) and version > (brief.version if brief else 0):
            parts = {key: value for key, value in logged.items() if key != "pictures"}
            superseded = state.report is not None and state.report.phase == DONE
            return replace(state,
                           brief=Brief(version, parts, event.at, NONE, None, None,
                                       _read_back_pictures("brief", logged)),
                           report=None if superseded else state.report)
        return state
    if brief is None or version != brief.version or brief.decision != NONE:
        return state
    if event.kind == BRIEF_APPROVED:
        return _with_message(
            replace(state, brief=replace(brief, decision=APPROVED, decided_at=event.at)),
            Message(event.seq, MESSAGE_APPROVED, event.at, version, None, by=actor_of(payload)))
    reply = payload.get("reply")
    if isinstance(reply, str):
        return _with_message(
            replace(state,
                    brief=replace(brief, decision=CHANGES, reply=reply, decided_at=event.at)),
            Message(event.seq, MESSAGE_CHANGES, event.at, version, reply, by=actor_of(payload)))
    return state


def _id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def actor_of(payload: Mapping) -> str | None:
    """The guest login a row's `by` names, or None for the owner (#1263).

    `by` counts only when it is already a normal login (`event_log.normal_login`, the one definition
    admission shares); an absent, malformed or non-canonical member reads as the owner, so no guest
    can steer a sprint whose start row is malformed."""
    value = payload.get("by")
    return value if isinstance(value, str) and normal_login(value) == value else None


def _folded_notice(state: SprintState, event: Event) -> SprintState:
    payload = event.payload
    if not takes_notices(state):
        return state
    if event.kind == NOTICE_POSTED:
        try:
            checked = checked_notice(payload.get("notice"))
        except Refused:
            return state
        notice = Notice(event.seq, event.at, checked["kind"], checked["text"],
                        checked.get("what"), checked.get("until"), checked.get("to"),
                        issue=checked.get("issue"), live_fault=checked.get("live_fault", False))
        return replace(state, notices=(*state.notices, notice))
    notice_id = payload.get("notice")
    if not _id(notice_id):
        return state
    return replace(state, notices=tuple(
        replace(notice, withdrawn_at=event.at)
        if notice.notice_id == notice_id and notice.withdrawn_at is None
        and notice.ended_at is None else notice for notice in state.notices))


def _is_owner_row(event: Event) -> bool:
    payload = event.payload
    return ("sprint_id" not in payload and payload.get("poster") == NOTICE_OWNER
            and isinstance(event.project, str) and bool(event.project))


def owner_notices(events: Iterable[Event],
                  states: Mapping[str, tuple[Notice, ...]] | None = None
                  ) -> dict[str, tuple[Notice, ...]]:
    """Every owner notice per project id, withdrawn ones included: no row touches a sprint."""
    folded = dict(states or {})
    for event in events:
        if event.kind not in (NOTICE_POSTED, NOTICE_WITHDRAWN) or not _is_owner_row(event):
            continue
        project_id = event.project
        notices = folded.get(project_id, ())
        if event.kind == NOTICE_POSTED:
            try:
                checked = checked_notice(event.payload.get("notice"))
            except Refused:
                continue
            if checked["kind"] == "heads-up":
                folded[project_id] = (*notices,
                                      Notice(event.seq, event.at, "heads-up", checked["text"]))
            continue
        notice_id = event.payload.get("notice")
        if _id(notice_id) and any(notice.notice_id == notice_id for notice in notices):
            folded[project_id] = tuple(
                replace(notice, withdrawn_at=event.at)
                if notice.notice_id == notice_id and notice.withdrawn_at is None else notice
                for notice in notices)
    return folded


def _ended_notices(state: SprintState, at: str) -> SprintState:
    """Marks every open notice ended when the sprint takes none: a notice never reopens."""
    if not open_notices(state) or takes_notices(state):
        return state
    return replace(state, notices=tuple(
        replace(notice, ended_at=at)
        if notice.withdrawn_at is None and notice.ended_at is None else notice
        for notice in state.notices))


def _landed_claims(state: SprintState, at: str) -> SprintState:
    """Marks every open claim ended whose slice the sprint's report lists as landed or held."""
    if state.report is None:
        return state
    done = {issue for issue, stage in state.report.issues if stage in (LANDED, HELD)}
    if not any(notice.kind == "claim" and notice.issue in done and notice.withdrawn_at is None
               and notice.ended_at is None for notice in state.notices):
        return state
    return replace(state, notices=tuple(
        replace(notice, ended_at=at)
        if notice.kind == "claim" and notice.issue in done and notice.withdrawn_at is None
        and notice.ended_at is None else notice for notice in state.notices))


def _nudged_message(message: Message, at: str, route: object) -> Message:
    if message.delivered_at is None:
        message = replace(message, delivered_at=at)
    if route == "relay":
        if message.relays >= 2:
            return message
        return replace(message, relays=message.relays + 1, relayed_at=at)
    if route == "wake":
        return replace(message, woken_at=at)
    return message


def _folded_message(state: SprintState, event: Event) -> SprintState:
    payload = event.payload
    if event.kind == SPRINT_MESSAGED:
        text = payload.get("text")
        if isinstance(text, str):
            return _with_message(state, Message(event.seq, MESSAGE_TEXT, event.at, None, text,
                                                by=actor_of(payload)))
    elif event.kind == SPRINT_READ:
        through = payload.get("through")
        if _id(through):
            return replace(state, failed_nudges=0, messages=tuple(
                replace(message, read_at=event.at)
                if (message.message_id <= through and message.read_at is None
                    and not message.held) else message
                for message in state.messages))
    elif event.kind == SPRINT_NUDGED:
        through, ok = payload.get("through"), payload.get("ok")
        if _id(through) and isinstance(ok, bool):
            messages = state.messages
            covers = payload.get("covers")
            covered = (set(covers) if isinstance(covers, list) and all(_id(item) for item in covers)
                       else None)
            if ok:
                route = payload.get("route")
                messages = tuple(
                    _nudged_message(message, event.at, route)
                    if (message.message_id <= through and not message.held
                        and (covered is None or message.message_id in covered)) else message
                    for message in messages)
            return replace(state, messages=messages, last_nudge_at=event.at, last_nudge_ok=ok,
                           failed_nudges=0 if ok else state.failed_nudges + 1)
    elif event.kind == SPRINT_ANSWERED:
        target, reply = payload.get("message"), payload.get("reply")
        if _id(target) and isinstance(reply, str):
            return replace(state, messages=tuple(
                replace(message, reply=reply, reply_at=event.at)
                if message.message_id == target else message for message in state.messages))
    return state


def _folded_question(state: SprintState, event: Event) -> SprintState:
    payload = event.payload
    if not takes_questions(state):
        return state
    if event.kind == QUESTIONS_ASKED:
        if state.state != STARTING:
            return state
        try:
            checked = checked_round({"questions": payload.get("questions"),
                                     "blocker": payload.get("blocker", False)}, limits=False)
        except Refused:
            return state
        marks = set(replaced(checked))
        withdrawn = tuple(
            replace(question, withdrawn_at=event.at, replaced_by=event.seq)
            if (question.round_id, question.index) in marks and question.answer is None
            and question.withdrawn_at is None else question for question in state.questions)
        bound = payload.get("look_repo")
        bound = bound if _text(bound) else None
        added = tuple(Question(event.seq, index, event.at, checked["blocker"], row["question"],
                               row["blocks"], tuple(row["options"]), row["recommended"],
                               context=row.get("context"),
                               look=QuestionLook(**row["look"], repo=bound) if "look" in row else None,
                               needs_words=tuple(row.get("needs_words", ())),
                               owner_only=row.get("owner_only", False) is True,
                               consequential=row.get("consequential", False) is True,
                               pictures=tuple(QuestionPicture(p["picture"], p["line"],
                                                              p.get("pair"))
                                              for p in row.get("pictures", ())))
                      for index, row in enumerate(checked["questions"]))
        return replace(state, questions=(*withdrawn, *added))
    round_id, index = payload.get("round"), payload.get("index")
    if event.kind == QUESTION_WITHDRAWN:
        if not _id(round_id) or not _id(index):
            return state
        return replace(state, questions=tuple(
            replace(question, withdrawn_at=event.at)
            if (question.round_id, question.index) == (round_id, index)
            and question.answer is None and question.withdrawn_at is None else question
            for question in state.questions))
    answer, chosen = payload.get("answer"), payload.get("chosen")
    if not _id(round_id) or not _id(index) or not isinstance(answer, str):
        return state
    if "words" in payload and not (isinstance(payload["words"], str) and chosen is not None):
        return state
    for position, question in enumerate(state.questions):
        if (question.round_id, question.index) != (round_id, index):
            continue
        if (question.answer is not None or question.withdrawn_at is not None
                or (chosen is not None and chosen not in question.options)):
            return state
        held = "words" not in payload and _approves_look(question, chosen, payload.get("look"))
        words = payload.get("words")
        answered = replace(question, answer=answer, chosen=chosen, answered_at=event.at,
                           differs=chosen != question.recommended, words=words,
                           answered_by=actor_of(payload),
                           look_state=LOOK_POSTING if held else None,
                           look_found=None, look_found_state=None,
                           look_message=event.seq if held else None,
                           look_repo=payload["look"]["repo"] if held else None)
        questions = (*state.questions[:position], answered, *state.questions[position + 1:])
        return _with_message(
            replace(state, questions=questions),
            Message(event.seq, MESSAGE_ANSWER, event.at, None, answer, question=question.question,
                    round_id=round_id, chosen=chosen, held=held, words=words, by=actor_of(payload)))
    return state


def _approves_look(question: Question, chosen: object, logged: object) -> bool:
    """Whether an answer approves the head its look card names: the approve option and that head."""
    look = question.look
    return (look is not None and chosen == look.approve and isinstance(logged, dict)
            and set(logged) == {"issue", "pr", "head", "repo"}
            and _id(logged["issue"]) and _id(logged["pr"]) and _text(logged["repo"])
            and (logged["issue"], logged["pr"], logged["head"]) == (look.issue, look.pr, look.head)
            and (look.repo is None or logged["repo"] == look.repo))


def _folded_look(state: SprintState, event: Event) -> SprintState:
    """A `look.recorded` row: what the console found or did about a look card's approval."""
    payload = event.payload
    round_id, index, outcome = payload.get("round"), payload.get("index"), payload.get("outcome")
    for position, question in enumerate(state.questions):
        if (question.round_id, question.index) == (round_id, index) and question.look is not None:
            break
    else:
        return state
    if outcome == LOOK_MOVED:
        found, found_state = payload.get("found"), payload.get("state")
        message = payload.get("message")
        if (question.withdrawn_at is not None
                or not (found is None or isinstance(found, str) and HEAD.fullmatch(found))
                or found_state not in LOOK_FOUND_STATES):
            return state
        notice = Message(event.seq, MESSAGE_LOOK_MOVED, event.at, None, _look_moved_text(
            question, found, found_state), round_id=round_id)
        if message is None:
            if question.answer is not None:
                return state
            changed = replace(question, look_state=LOOK_MOVED, look_found=found,
                              look_found_state=found_state)
            moved = replace(state, questions=_swapped(state.questions, position, changed))
            # An owner who approves a stale card again before the manager read the first notice adds none.
            return moved if any(item.kind == MESSAGE_LOOK_MOVED and item.read_at is None
                                and item.text == notice.text for item in state.messages) \
                else _with_message(moved, notice)
        # The head moved after the answer was kept and before it was posted: the answer is taken
        # back, the held message with it, and the question is open again for the manager to replace.
        if (not _id(message) or question.answer is None
                or question.look_state not in (LOOK_POSTING, LOOK_FAILED)
                or question.look_message != message):
            return state
        reopened = replace(question, answer=None, chosen=None, differs=None, answered_at=None,
                           look_state=LOOK_MOVED, look_found=found, look_found_state=found_state,
                           look_reason=None, look_message=None, look_repo=None)
        return _with_message(
            replace(state, questions=_swapped(state.questions, position, reopened),
                    messages=tuple(item for item in state.messages if item.message_id != message)),
            notice)
    message = payload.get("message")
    if (outcome not in (LOOK_POSTED, LOOK_FAILED) or not _id(message)
            or question.look_state not in (LOOK_POSTING, LOOK_FAILED)
            or question.look_message != message):
        return state
    if outcome == LOOK_POSTED:
        comment = payload.get("comment_id")
        if not _id(comment):
            return state
        changed = replace(question, look_state=LOOK_POSTED, look_comment=comment)
        released = tuple(replace(item, held=False) if item.message_id == message else item
                         for item in state.messages)
        return replace(state, questions=_swapped(state.questions, position, changed),
                       messages=released)
    reason = payload.get("reason")
    if not isinstance(reason, str):
        return state
    changed = replace(question, look_state=LOOK_FAILED, look_reason=reason)
    return replace(state, questions=_swapped(state.questions, position, changed))


def _look_moved_text(question: Question, found: str | None, found_state: str | None) -> str:
    """What the manager is told when the owner's approval of a look card found its head gone."""
    look = question.look
    if found_state == "open" and found is not None:
        return LOOK_MOVED_OPEN.format(round=question.round_id, index=question.index, head=look.head,
                                      pr=look.pr, found=found)
    return LOOK_MOVED_ENDED.format(round=question.round_id, index=question.index, head=look.head,
                                   pr=look.pr, state=found_state)


def _swapped(questions: tuple[Question, ...], position: int, question: Question
             ) -> tuple[Question, ...]:
    return (*questions[:position], question, *questions[position + 1:])


def _folded_session(folded: dict[str, SprintState], event: Event) -> None:
    name, session_id = event.payload.get("name"), event.payload.get("session_id")
    if not isinstance(name, str) or not isinstance(session_id, str):
        return
    match = MANAGER_SESSION_NAME.fullmatch(name)
    state = folded.get(match["sprint"]) if match else None
    if state is not None and match["project"] == state.project_id == event.project:
        revivals = state.revivals
        if revivals and revivals[-1].how == WAKE and not revivals[-1].back:
            revivals = (*revivals[:-1], replace(revivals[-1], back=True))
        folded[state.sprint_id] = replace(state, manager_session=session_id,
                                          manager_seen_seq=event.seq, revivals=revivals,
                                          stalled=None, stalled_at=None)


def _folded_manager(state: SprintState, event: Event) -> SprintState:
    payload = event.payload
    takeover = payload.get("takeover") is True
    if event.kind == MANAGER_STARTED:
        profile, name = payload.get("profile"), payload.get("session_name")
        if isinstance(profile, str) and isinstance(name, str):
            revivals = state.revivals + ((Revival(event.at, TAKEOVER, True),) if takeover else ())
            seen_after = payload.get("seen_after")
            current = (_id(seen_after) and state.manager_seen_seq is not None
                       and state.manager_seen_seq > seen_after)
            return replace(state, manager=Manager(STARTED, event.at, profile, name,
                                                  takeover=takeover),
                           manager_session=state.manager_session if current else None,
                           revivals=revivals, stalled=None, stalled_at=None,
                           permission=from_payload(payload.get("permission")))
    elif event.kind == MANAGER_FAILED:
        reason = payload.get("reason")
        if isinstance(reason, str):
            revivals = state.revivals + (
                (Revival(event.at, TAKEOVER, False, reason),) if takeover else ())
            return replace(state, manager=Manager(FAILED, event.at, reason=reason,
                                                  takeover=takeover),
                           revivals=revivals,
                           stalled=reason if state.stalled is not None else None)
    elif event.kind == MANAGER_WAITING and "until" in payload:
        until = payload["until"]
        if until is None or isinstance(until, str):
            return replace(state, manager=Manager(WAITING, event.at, until=until,
                                                  takeover=takeover))
    elif event.kind == MANAGER_WOKEN:
        ok, back = payload.get("ok"), payload.get("back", False)
        if isinstance(payload.get("session_id"), str) and isinstance(ok, bool) \
                and isinstance(back, bool):
            reason = payload.get("reason")
            return replace(state, revivals=state.revivals + (Revival(
                event.at, WAKE, ok, reason if not ok and isinstance(reason, str) else None,
                back=back),))
    elif event.kind == MANAGER_STALLED:
        reason = payload.get("reason")
        if isinstance(reason, str):
            return replace(state, stalled=reason, stalled_at=event.at)
    return state


def _folded_permission(state: SprintState, event: Event) -> SprintState:
    """The mode a wake, nudge or notice nudge wrote replaces the sprint's; a row without a valid one leaves it."""
    chosen = from_payload(event.payload.get("permission"))
    return state if chosen is None else replace(state, permission=chosen)


def _folded_idle(state: SprintState, event: Event) -> SprintState:
    if event.kind == MANAGER_NUDGED:
        if isinstance(event.payload.get("ok"), bool) \
                and isinstance(event.payload.get("session_id"), str):
            return replace(state, idle_nudges=state.idle_nudges + 1, idle_nudged_at=event.at)
    elif event.kind == MANAGER_NO_PROGRESS:
        if state.no_progress_at is None:
            return replace(state, no_progress_at=event.at)
    elif state.no_progress_at is not None:
        return replace(state, no_progress_at=None, idle_nudges=0)
    return state


def _folded_report(state: SprintState, event: Event) -> SprintState:
    report = event.payload.get("report")
    if state.state != STARTING or not isinstance(report, dict):
        return state
    members = {key: value for key, value in report.items() if key != "pictures"}
    try:
        checked = checked_report(members)
    except Refused:
        return state
    return replace(state, observed=(), idle_nudges=0, no_progress_at=None,
                   report=Report(event.at, checked["status"], checked["phase"],
                                 checked["milestone"], checked["tracker_url"],
                                 tuple((row["issue"], row["stage"]) for row in checked["issues"]),
                                 tuple(checked["inbox"]), checked["next"],
                                 _read_back_pictures("report", report),
                                 checked.get("wait_until"), checked.get("paused")))


def _folded_stop_request(state: SprintState, event: Event) -> SprintState:
    if (state.stop_at is not None or state.closing is not None or state.stopped_at is not None
            or ended_at(state) is not None):
        return state
    return _with_message(replace(state, stop_at=event.at),
                         Message(event.seq, MESSAGE_STOP, event.at, None, STOP_TEXT))


def _folded_closing(state: SprintState, event: Event) -> SprintState:
    closing = event.payload.get("closing")
    if (state.closing is not None or state.stopped_at is not None or not isinstance(closing, dict)
            or not (state.state == STARTING or state.stop_at is not None)):
        return state
    reported = [issue for issue, _ in state.report.issues] if state.report else []
    try:
        checked = checked_closing(closing, reported)
    except Refused:
        return state
    return replace(state, closing=Closing(
        event.at, checked["summary"], first_line(checked["summary"]),
        tuple((row["issue"], row["stage"]) for row in checked["issues"]), checked["differently"]))


def _folded_stop(state: SprintState, event: Event) -> SprintState:
    if state.stop_at is None and state.closing is not None and state.done_stopped_at is None:
        if event.kind == MANAGER_STOPPED:
            return replace(state, done_stopped_at=event.at, stop_failed_at=None)
        if isinstance(event.payload.get("reason"), str):
            return replace(state, stop_failed_at=event.at)
        return state
    if state.stop_at is None or state.stopped_at is not None:
        return state
    if event.kind == MANAGER_STOPPED:
        return replace(state, stopped_at=event.at, stop_reason=None, stop_failed_at=None)
    reason = event.payload.get("reason")
    if isinstance(reason, str):
        return replace(state, stop_reason=reason, stop_failed_at=event.at)
    return state


def _observed(folded: dict[str, SprintState], event: Event) -> None:
    runs = deliveries.delivery_states([event])
    for run in runs.values():
        for sprint_id, state in folded.items():
            if state.project_id != event.project:
                continue
            report = state.report
            named = ({issue for issue, _ in report.issues} | set(report.inbox)
                     if report is not None else set())
            own = state.manager_session is not None and run.session_id == state.manager_session
            if not own and not any(stage.issue in named for stage in run.issues):
                continue
            moved = max(state.moved_ms or 0, run.moved_ms)
            delivered = state.delivered | {stage.issue for stage in run.issues} if own else state.delivered
            observed = state.observed
            if report is not None and run.moved_ms > int(
                    datetime.fromisoformat(report.at).timestamp() * 1000):
                reported = {issue for issue, _ in report.issues}
                kept = {item.issue: item for item in state.observed}
                for stage in run.issues:
                    if stage.issue not in reported:
                        continue
                    old = kept.get(stage.issue)
                    if old is None or ((run.moved_ms, run.session_id, run.run_id)
                                       >= (old.moved_ms, old.session_id, old.run_id)):
                        kept[stage.issue] = Observed(stage.issue, run.moved_ms, run.session_id,
                                                     run.run_id, stage)
                observed = tuple(kept[issue] for issue in sorted(kept))
            folded[sprint_id] = replace(state, moved_ms=moved, observed=observed, delivered=delivered)


def sprint_states(events: Iterable[Event],
                  states: Mapping[str, SprintState] | None = None) -> dict[str, SprintState]:
    folded = dict(states or {})
    for event in events:
        if event.kind == DELIVERY_SEEN:
            _observed(folded, event)
            continue
        if event.kind == SEEN:
            _folded_session(folded, event)
            continue
        sprint_id = event.payload.get("sprint_id")
        if not isinstance(sprint_id, str):
            continue
        if event.kind == GOAL_STATED:
            goal = event.payload.get("goal")
            if event.project is not None and isinstance(goal, str):
                folded[sprint_id] = SprintState(sprint_id, event.project, goal, event.seq,
                                                event.at, started_by=actor_of(event.payload))
        elif event.kind == GOAL_WITHDRAWN:
            folded.pop(sprint_id, None)
        elif event.kind in (BRIEF_SENT, BRIEF_APPROVED, BRIEF_REPLIED) and sprint_id in folded:
            folded[sprint_id] = _folded_brief(folded[sprint_id], event)
            if event.kind == BRIEF_SENT:
                folded[sprint_id] = _folded_row_pictures(folded[sprint_id], event)
        elif event.kind == SPRINT_STOP_REQUESTED and sprint_id in folded:
            folded[sprint_id] = _folded_stop_request(folded[sprint_id], event)
        elif event.kind == SPRINT_CLOSED and sprint_id in folded:
            folded[sprint_id] = _folded_closing(folded[sprint_id], event)
        elif event.kind in (MANAGER_STOPPED, MANAGER_STOP_FAILED) and sprint_id in folded:
            folded[sprint_id] = _folded_stop(folded[sprint_id], event)
        elif event.kind in (MANAGER_STARTED, MANAGER_FAILED, MANAGER_WAITING, MANAGER_WOKEN,
                            MANAGER_STALLED) and sprint_id in folded:
            folded[sprint_id] = _folded_manager(folded[sprint_id], event)
            if event.kind == MANAGER_WOKEN:
                folded[sprint_id] = _folded_permission(folded[sprint_id], event)
        elif event.kind in (MANAGER_NUDGED, MANAGER_NO_PROGRESS, SPRINT_CONTINUED) \
                and sprint_id in folded:
            folded[sprint_id] = _folded_idle(folded[sprint_id], event)
        elif event.kind == SPRINT_REPORTED and sprint_id in folded:
            folded[sprint_id] = _folded_report(folded[sprint_id], event)
            folded[sprint_id] = _folded_row_pictures(folded[sprint_id], event)
        elif event.kind in (SPRINT_MESSAGED, SPRINT_READ, SPRINT_ANSWERED, SPRINT_NUDGED) \
                and sprint_id in folded:
            folded[sprint_id] = _folded_message(folded[sprint_id], event)
            if event.kind == SPRINT_NUDGED:
                folded[sprint_id] = _folded_permission(folded[sprint_id], event)
        elif event.kind == NOTICE_NUDGED and sprint_id in folded:
            folded[sprint_id] = _folded_permission(folded[sprint_id], event)
        elif event.kind in (QUESTIONS_ASKED, QUESTION_ANSWERED, QUESTION_WITHDRAWN) \
                and sprint_id in folded:
            folded[sprint_id] = _folded_question(folded[sprint_id], event)
            if event.kind == QUESTIONS_ASKED:
                folded[sprint_id] = _folded_row_pictures(folded[sprint_id], event)
        elif event.kind == LOOK_RECORDED and sprint_id in folded:
            folded[sprint_id] = _folded_look(folded[sprint_id], event)
        elif event.kind in (NOTICE_POSTED, NOTICE_WITHDRAWN) and sprint_id in folded:
            folded[sprint_id] = _folded_notice(folded[sprint_id], event)
        elif event.kind == PICTURE_STORED and sprint_id in folded:
            picture = event.payload.get("picture")
            if isinstance(picture, str) and PICTURE_ID.fullmatch(picture):
                folded[sprint_id] = replace(folded[sprint_id],
                                            pictures=folded[sprint_id].pictures | {picture})
        if sprint_id in folded:
            folded[sprint_id] = _ended_notices(folded[sprint_id], event.at)
            folded[sprint_id] = _landed_claims(folded[sprint_id], event.at)
    return folded


def _folded_row_pictures(state: SprintState, event: Event) -> SprintState:
    """A kept row's top-level pictures stay the sprint's own after retention drops their rows."""
    listed = event.payload.get("pictures")
    named = {p for p in listed if isinstance(p, str) and PICTURE_ID.fullmatch(p)} \
        if isinstance(listed, list) else set()
    return replace(state, pictures=state.pictures | named) if named else state


def refused_reason(status: str) -> str | None:
    """The reason of a status that marks a refused merge (#1115): the stripped text after a leading
    `merge refused:` (any case, any whitespace after the colon) when that text is not empty, else
    None. The words anywhere but the start are not a refusal."""
    found = REFUSED_STATUS.fullmatch(status.strip())
    return found.group(1).strip() if found else None


def merge_refused(state: SprintState) -> str | None:
    """The merge refusal the sprint shows now, else None: the reason in its report's status, unless
    the sprint is closing. It reads no run observation: the status names no issue, so no run can be
    tied to the refused merge, and only a later report or a closing clears it."""
    if state.report is None or state.closing is not None:
        return None
    return refused_reason(state.report.status)


def stated_hold(state: SprintState, now_ms: int | None) -> tuple[str, str] | None:
    """The wait or pause the sprint's report states and that still holds, else None (#1380).

    `(PAUSED, report.paused)` while the report carries a `paused` reason, `(WAIT_UNTIL,
    report.wait_until)` while it carries a `wait_until` that `now_ms` has not reached (`now_ms`
    None counts as not reached). The deadline is compared in microseconds (`_wait_us`), never
    through `_ms`, which truncates: a deadline with a fractional millisecond holds through the
    millisecond it falls in and releases on the next, and a whole-millisecond deadline releases at
    `now_ms` equal to it. A sprint without a report holds nothing.
    """
    report = state.report
    if report is None:
        return None
    if report.paused is not None:
        return PAUSED, report.paused
    if report.wait_until is not None and (
            now_ms is None or now_ms * 1000 < _wait_us(report.wait_until)):
        return WAIT_UNTIL, report.wait_until
    return None


def ended_at(state: SprintState) -> str | None:
    if state.stopped_at is not None:
        return state.stopped_at
    if state.stop_at is not None:
        return None
    if state.closing is not None:
        return state.closing.at
    if (state.state == STARTING and state.report is not None and state.report.phase == DONE
            and not open_questions(state) and not pending_looks(state)):
        return state.report.at
    return None


def stop_due(state: SprintState, now_ms: int) -> bool:
    if state.stop_at is None or state.stopped_at is not None:
        return False
    waited = state.closing is not None or now_ms - _ms(state.stop_at) >= STOP_WAIT_MS
    return waited and (state.stop_failed_at is None
                       or now_ms - _ms(state.stop_failed_at) >= STOP_RETRY_MS)


def done_stop_due(state: SprintState, now_ms: int, turn_ended: bool) -> bool:
    if state.closing is None or state.stop_at is not None or state.done_stopped_at is not None:
        return False
    waited = turn_ended or now_ms - _ms(state.closing.at) >= DONE_STOP_WAIT_MS
    return waited and (state.stop_failed_at is None
                       or now_ms - _ms(state.stop_failed_at) >= STOP_RETRY_MS)


def pending_stops(events: Iterable[Event],
                  pending: Mapping[str, PendingStop] | None = None) -> dict[str, PendingStop]:
    folded = dict(pending or {})
    for event in events:
        sprint_id = event.payload.get("sprint_id")
        if not isinstance(sprint_id, str):
            continue
        if event.kind == GOAL_WITHDRAWN:
            goal = event.payload.get("goal")
            if isinstance(event.project, str) and isinstance(goal, str):
                folded[sprint_id] = PendingStop(sprint_id, event.project, goal, event.at)
        elif event.kind == MANAGER_STOPPED:
            folded.pop(sprint_id, None)
        elif event.kind == MANAGER_STOP_FAILED and sprint_id in folded:
            reason = event.payload.get("reason")
            if isinstance(reason, str):
                folded[sprint_id] = replace(folded[sprint_id], reason=reason,
                                            failed_at=event.at)
    return folded


def pending_due(stop: PendingStop, now_ms: int) -> bool:
    return stop.failed_at is None or now_ms - _ms(stop.failed_at) >= STOP_RETRY_MS


def closing_text(landed: int, held: int, dropped: int) -> str:
    text = f"{landed} landed"
    for count, label in ((held, "held for verification"), (dropped, "dropped")):
        if count:
            text += f", {count} {label}"
    return text


def withdrawn_ids(events: Iterable[Event], ids: frozenset[str] = frozenset()) -> frozenset[str]:
    withdrawn = set(ids)
    for event in events:
        sprint_id = event.payload.get("sprint_id")
        if event.kind == GOAL_WITHDRAWN and isinstance(sprint_id, str):
            withdrawn.add(sprint_id)
    return frozenset(withdrawn)


def ago_text(elapsed_ms: int) -> str:
    elapsed = max(elapsed_ms, 0)
    if elapsed < _MINUTE_MS:
        return "just now"
    if elapsed < _HOUR_MS:
        return f"{elapsed // _MINUTE_MS} min ago"
    if elapsed < _DAY_MS:
        return f"{elapsed // _HOUR_MS} h ago"
    days = elapsed // _DAY_MS
    return "1 day ago" if days == 1 else f"{days} days ago"


def age_text(elapsed_ms: int) -> str:
    return "goal set " + ago_text(elapsed_ms)


def progress_text(landed: int, total: int, in_delivery: int, queued: int, held: int) -> str:
    text = f"{landed} of {total} landed"
    for count, label in ((in_delivery, "in delivery"), (queued, "queued"), (held, "held")):
        if count:
            text += f", {count} {label}"
    return text


def _ms(time: str) -> int:
    return int(datetime.fromisoformat(time).timestamp() * 1000)


def manager_status(state: SprintState, listed: bool, now_ms: int | None,
                   managers: bool) -> tuple[str, str | None, bool]:
    """Return `(manager_state, manager_text, retry)` for one open sprint.

    `listed` is whether the sprint has a listed session of its own and `now_ms` is the clock in
    milliseconds (`None` counts as no time elapsed). The rules, first match wins:

    - `managers` false (a host that cannot start managers): `unavailable`, `UNAVAILABLE_TEXT`, no
      retry.
    - A stalled sprint (`SprintState.stalled`): `stalled`, `"<STALLED_TEXT>: <reason>"` and retry
      while it has no listed session and is not stopping.
    - The sprint is overdue when `now_ms` is more than `NO_MANAGER_AFTER_MS` past its start time, it
      has no brief and it has no listed session. The start time is `Manager.at` of a `started`
      manager and the stated time (`stated_at`) otherwise.
    - No manager row: `none`, with `NO_MANAGER_TEXT` and retry when overdue, else no text, no retry.
    - `started`: `missing`, `MISSING_TEXT` and retry when overdue, else `started`, no text, no retry.
    - `failed`: `failed` and `"<FAILED_TEXT>: <plain_reason(reason)>"`.
    - `waiting`: `waiting` and `manager.WAITING_TEXT`.

    A `failed` or `waiting` manager of a first launch offers retry only while the sprint has no
    listed session and no brief: a launch can fail after its detached session was already handed
    off, and a retry would then start a second manager for the sprint. A `failed` or `waiting`
    manager whose `takeover` is true offers retry while the sprint has no listed session, whatever
    the brief (a takeover's sprint has a brief by design).

    A sprint with `stop_at`, `stopped_at` or `closing` set never offers retry, whatever its manager
    row says: neither the view nor the service relaunches the manager of a stopping, stopped or
    closed sprint (#980).
    """
    if not managers:
        return UNAVAILABLE, UNAVAILABLE_TEXT, False
    manager = state.manager
    stopping = (state.stop_at is not None or state.stopped_at is not None
                or state.closing is not None)
    since = state.stated_at if manager is None or manager.state != STARTED else manager.at
    overdue = (now_ms is not None and now_ms - _ms(since) > NO_MANAGER_AFTER_MS
               and state.brief is None and not listed)
    if state.stalled is not None:
        return STALLED, f"{STALLED_TEXT}: {state.stalled}", not listed and not stopping
    if manager is None:
        return (NONE, NO_MANAGER_TEXT, not stopping) if overdue else (NONE, None, False)
    if manager.state == STARTED:
        return (MISSING, MISSING_TEXT, not stopping) if overdue else (STARTED, None, False)
    free = not listed and (state.brief is None or manager.takeover) and not stopping
    if manager.state == FAILED:
        return FAILED, f"{FAILED_TEXT}: {plain_reason(manager.reason)}", free
    return WAITING, MANAGER_WAITING_TEXT, free


def failed_start(state: SprintState, listed: bool, managers: bool) -> bool:
    """Whether a sprint's manager failed to start and the owner's retry is the way on (#1182).

    True exactly when `manager_status(state, listed, None, managers)` is `failed` with retry, the
    manager row is not a takeover's and the sprint has no brief: a first launch that never reached
    a brief. A stalled sprint is not one (its stall card speaks) and neither is a stopping one.
    The inbox card, the block's Retry and the service's retry gate read the same `manager_status`,
    so the three never disagree."""
    manager_state, _, retry = manager_status(state, listed, None, managers)
    return (manager_state == FAILED and retry and state.manager is not None
            and not state.manager.takeover and state.brief is None)


def new_sprint_id() -> str:
    return secrets.token_hex(8)


def _checked_id(sprint_id: str) -> None:
    if SPRINT_ID.fullmatch(sprint_id) is None:
        raise ValueError("sprint_id must be 16 lowercase hex characters")


def create_secret(directory: Path, sprint_id: str) -> Path:
    _checked_id(sprint_id)
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / sprint_id
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(secrets.token_urlsafe(32) + "\n")
    return path


def remove_secret(directory: Path, sprint_id: str) -> None:
    _checked_id(sprint_id)
    (Path(directory) / sprint_id).unlink(missing_ok=True)


def read_secret(directory: Path, sprint_id: str) -> str | None:
    _checked_id(sprint_id)
    try:
        text = (Path(directory) / sprint_id).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return text.removesuffix("\n")
