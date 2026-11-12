"""The console's sprints (#886, #887): a goal the owner states on the page, kept until it is withdrawn, and the brief a manager sends for it.

Six event kinds carry a sprint (`event_log.GOAL_STATED`, `GOAL_WITHDRAWN`, `BRIEF_SENT`,
`BRIEF_APPROVED`, `BRIEF_REPLIED`, `SPRINT_REPORTED`). All put the project id in the event's project
column. A goal row carries `{"sprint_id": <id>, "goal": <text>}` (a withdrawal repeats the stated
text); the brief and report rows carry

    brief.sent      {"sprint_id", "version": <int>, "goal": <str>, "brief": {<the five parts>}}
    brief.approved  {"sprint_id", "version": <int>, "goal": <str>}
    brief.replied   {"sprint_id", "version": <int>, "goal": <str>, "reply": <str>}
    sprint.reported {"sprint_id", "goal": <str>, "report": {<the seven REPORT_MEMBERS>}}

The log keeps all six indefinitely (`event_log.KEPT_KINDS`).

Three more kinds record the sprint's manager (#888), none of them kept (`event_log.MANAGER_STARTED`,
`MANAGER_FAILED`, `MANAGER_WAITING`; each with the project in its project column), and two record
its bring-back (#893; `event_log.MANAGER_WOKEN`, `MANAGER_STALLED`, not kept either):

    manager.started  {"sprint_id", "profile": <str>, "session_name": <str>, "seen_after"?: <int>,
                      "takeover"?: true}
    manager.failed   {"sprint_id", "reason": <str>, "takeover"?: true}
    manager.waiting  {"sprint_id", "until": <str> | null, "takeover"?: true}
    manager.woken    {"sprint_id", "session_id": <str>, "ok": <bool>, "reason"?: <str>,
                      "back"?: <bool>, "listing_failed"?: <str>}
    manager.stalled  {"sprint_id", "reason": <str>}

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
Registration events change nothing here: a goal row outlives the registration rows retention
removes, and the view alone shows sprints only under registered projects. Folding `a + b` equals
folding `b` onto the fold of `a`.

A brief is the five `PARTS`: `done` a text, `slices` a non-empty list of texts, and `excluded`,
`risks` and `asks` lists of texts that may be empty (`MAY_BE_EMPTY`). `checked_brief(brief)` checks
them in `PARTS` order and refuses with `Refused("the brief has no <part>")` the first that is
missing, of the wrong type, empty when it must not be, or holding a text empty after stripping; it
returns a new dict of the five parts with every text stripped. `checked_reply(text)`
keeps the text exactly and refuses `EMPTY_REPLY` when its strip is empty, then `REPLY_TOO_LONG` over
`MAX_REPLY_CHARS` code points. `SecretRefused` (a `Refused`) is the service's refusal of a wrong
secret; it maps to 403.

`parse_brief_request(body)` reads the manager's body and returns `(sprint_id, secret, brief)`:

    {"sprint_id": "<16 lowercase hex>", "secret": "<string>", "brief": {<any subset of PARTS>}}

`parse_approve(body)` returns `(project_id, sprint_id, version)` and `parse_reply(body)` returns
`(project_id, sprint_id, version, reply)` from the page's bodies:

    {"project_id": "<project id>", "sprint_id": "<16 hex>", "version": <int >= 1, not a bool>}
    ... plus "reply": "<string>" for a reply

All three readers are as strict as the goal ones; an unknown brief key is a `ValueError`, a missing
one is not (the service answers it with the part).

The fold also keeps each open sprint's `Brief(version, parts, sent_at, decision, reply)`.
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
until`), `NO_PROGRESS_TEXT` (`the manager has stopped making progress on {goal}`) and `NOT_STUCK`
(the service's refusal of a continue with no item open). `parse_continue(body)` reads the owner's
continue write, exactly `parse_withdraw`'s shape and refusals, and returns `(project_id,
sprint_id)`. `idle` (which this module does not import) reads these fields.

`manager_status(state, listed, now_ms, managers)` turns a sprint's manager into the view's
`(manager_state, manager_text, retry)`; its docstring holds the rules.

The view's `manager_state`, `manager_text` and `retry`, and the service's retry gate, are this
function's three results.

`withdrawn_ids(events, ids)` adds the `sprint_id` of every `goal.withdrawn` row with a string one.

A report is what the approved sprint's manager says about the sprint. `parse_report_request(body)`
reads the manager's body and returns `(sprint_id, secret, report)`:

    {"sprint_id": "<16 lowercase hex>", "secret": "<string>",
     "report": {"status": "<one line>", "phase": "running", "milestone": "<one line>",
                "tracker_url": "https://<host>/<path>",
                "issues": [{"issue": 12, "stage": "building"}, {"issue": 13, "stage": "landed"}],
                "inbox": [12], "next": "<one line>"}}

It accepts only a UTF-8 JSON object of exactly `sprint_id`, `secret` and `report`, a valid sprint
id, a string secret and a `report` object whose keys are a subset of `REPORT_MEMBERS`; anything
else, a repeated key, a NaN literal or nesting too deep is `ValueError`. A missing member is not (the
service answers it with the member). `checked_report(report)` checks the members in `REPORT_MEMBERS`
order and refuses with `Refused("the report has no valid <member>")` the first that is missing or
invalid; right after a valid `status` it refuses `STATUS_NUMBER` when the stripped status matches
`#` and a digit. `status`, `milestone` and `next` are a one-line text (a string, non-empty after stripping,
no line break, at most `MAX_LINE_CHARS` code points after stripping); `phase` is one of
`REPORT_PHASES`; `tracker_url` is a string of at most `MAX_LINE_CHARS` code points starting with
`https://` whose every character is printable and not whitespace; `issues` is a list of at most
`MAX_REPORT_ISSUES` objects of exactly `issue` (an int, not a bool, at least 1) and `stage` (one of
`REPORT_STAGES`), no issue twice, possibly empty; `inbox` is a list of at most `MAX_REPORT_ISSUES`
ints (not bools) of at least 1, possibly empty. It returns a new dict of the seven members: texts
stripped, `issues` sorted by issue, `inbox` sorted without duplicates, `tracker_url` and `phase` as
given.

The fold keeps each open sprint's `Report(at, status, phase, milestone, tracker_url, issues, inbox,
next_step)`. `sprint.reported` changes an open sprint only when its brief is approved (`STARTING`)
and `checked_report` accepts a dict `report`; the report is then replaced (`at` is the event's `at`,
`issues` a tuple of `(issue, stage)`, `inbox` a tuple, `next_step` the `next` member) and the
sprint's observations are cleared. Every other report row changes nothing.

Observations: a `delivery.seen` row carries no sprint id and is read as the delivery fold reads it
(`deliveries.delivery_states` on that one row; a row that parses to nothing changes nothing). For
every open sprint of the row's project that has a report, a run that moved after the report
(`moved_ms` greater than the report's `at` in milliseconds) and carries a reported issue sets the
sprint's `moved_ms` to the larger of the kept one and the run's, and each of the run's stages for a
reported issue becomes that issue's `Observed(issue, moved_ms, session_id, run_id, stage)` when
`(moved_ms, session_id, run_id)` is at least the kept one's. `delivery.gone` changes nothing: the
last stage and movement outlive the run. `SprintState.observed` is ordered by issue. Folding `a + b`
equals folding `b` onto the fold of `a`.

`ago_text(elapsed_ms)` is `just now` under a minute, `<m> min ago` under an hour, `<h> h ago` under
a day, else `1 day ago` or `<d> days ago`; a negative count is 0. `age_text(elapsed_ms)` is `stated `
plus that. `progress_text(landed, total, in_delivery, queued, held)` is `<landed> of <total> landed`
followed by `, <n> in delivery`, `, <n> queued` and `, <n> held` for each non-zero count, in that
order. The view states and texts are the constants `ON_TRACK`, `WAITING`, `QUIET`, `CLOSING`,
`DONE` and their `_TEXT`; `CLOSED_OUT` is the view's stage for a run's `done` (not a report stage).

Messages (#889) are what the owner says to a sprint, each one a `Message` kept in `message_id` order
on `SprintState.messages`. Four rows carry them, the first three kept (`event_log.SPRINT_MESSAGED`,
`SPRINT_READ`, `SPRINT_ANSWERED`, `SPRINT_NUDGED`; each with the project in its project column):

    sprint.messaged {"sprint_id", "goal": <str>, "text": <str>}
    sprint.read     {"sprint_id", "through": <int message id>}
    sprint.answered {"sprint_id", "message": <int message id>, "reply": <str>}
    sprint.nudged   {"sprint_id", "through": <int>, "route": "relay" | "wake" | null, "ok": true,
                     "listing_failed"?: <str>}
                    {"sprint_id", "through": <int>, "route": "relay" | "wake" | null, "ok": false,
                     "reason": <str>, "listing_failed"?: <str>}

A message's id is the `seq` of the row that made it. A `brief.approved` row that approves the open
brief makes a `MESSAGE_APPROVED` message (`version` the brief's, no text); a `brief.replied` row
that asks the open brief for changes makes a `MESSAGE_CHANGES` message (`version`, `text` the reply);
a `sprint.messaged` row with a string `text` makes a `MESSAGE_TEXT` message (no version). A stale or
repeated decision, which `_folded_brief` ignores, makes none. `sprint.read` with an int (not bool)
`through` sets `read_at` (the row's `at`) on every message up to that id still unread and resets
`failed_nudges`. `sprint.nudged` with a bool `ok` and an int `through` sets `last_nudge_at` and
`last_nudge_ok`; `ok` true sets `delivered_at` on every message up to `through` without one and
resets `failed_nudges`, `ok` false adds one to it. `sprint.answered` with an int `message` naming one
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

`message_state(message)` is `READ` when `read_at` is set, else `DELIVERED` when `delivered_at` is,
else `SENT`; `unread(state)` is the messages without `read_at`, in id order; `unreachable(state)` is
true once `failed_nudges` reaches `UNREACHABLE_AFTER`. `checked_message(text)` refuses
`EMPTY_MESSAGE` for a blank text and `MESSAGE_TOO_LONG` above `MAX_MESSAGE_CHARS`, and returns the
text unchanged. `parse_message(body)` reads the owner's write and returns `(project_id, sprint_id,
text)`; `parse_inbox_request(body)` reads the manager's `{"sprint_id", "secret"}` and returns
`(sprint_id, secret)`; `parse_message_reply_request(body)` reads the manager's `{"sprint_id",
"secret", "message": <int of at least 1>, "reply": <str>}` and returns `(sprint_id, secret,
message_id, reply)`. All three are as strict as `parse_reply` (`ValueError` otherwise).
`inbox_entry(message)` is the wire entry `{"id", "kind", "version", "text", "at"}`, and for a
`MESSAGE_ANSWER` message also `"question"`, `"round"` and `"chosen"` (see below).

Rounds of questions (#891) are what an approved sprint's manager asks the owner. Two rows carry
them, both kept (`event_log.QUESTIONS_ASKED`, `QUESTION_ANSWERED`; each with the project in its
project column):

    questions.asked   {"sprint_id", "goal": <str>, "blocker": <bool>,
                       "questions": [{"question", "blocks", "options": [<str>], "recommended"}]}
    question.answered {"sprint_id", "goal": <str>, "round": <int>, "index": <int>,
                       "question": <str>, "answer": <str>, "chosen": <str> | null,
                       "recommended": <str>, "differs": <bool>}

The round the manager sends (inside the ask request) and the owner's answer (the page's write) are

    {"questions": [{"question": "<text>", "blocks": "<one line>", "options": ["<one line>", ...],
                    "recommended": "<exact text of one option>"}, ...],
     "blocker": true | false}                   (blocker optional, default false)
    {"project_id", "sprint_id", "round": <int >= 1>, "question": <int >= 0>, "choice": <int >= 0>}
    {"project_id", "sprint_id", "round": <int >= 1>, "question": <int >= 0>, "text": "<words>"}

A round has one to `MAX_ROUND_QUESTIONS` questions, each with `MIN_OPTIONS` to `MAX_OPTIONS`
options. `checked_round(round)` refuses with `Refused` the first failure, in this order:
`NO_QUESTIONS` (`questions` not a list, or empty), `TOO_MANY_QUESTIONS`, `BAD_BLOCKER` (`blocker`
present and not a bool); then, per question (`n` counts from 1): `QUESTION_SHAPE` (not an object, or
a key outside `question, blocks, options, recommended`), `QUESTION_MEMBER` for `question` (a string,
non-empty after stripping, at most `MAX_QUESTION_CHARS` code points after stripping) and for
`blocks` (one line), `OPTION_COUNT`, `QUESTION_MEMBER` for `options` (an option that is not one
line), `OPTION_TWICE` (two options equal after stripping) and `NO_RECOMMENDATION` (`recommended` not
a string whose strip equals one stripped option). It returns a new `{"blocker": <bool>,
"questions": [{"question", "blocks", "options", "recommended"}]}` with every text stripped.
`parse_ask_request(body)` reads the manager's `{"sprint_id", "secret", "round"}` (exactly those
keys) and returns `(sprint_id, secret, round)`, `round` an object whose keys are a subset of
`questions, blocker`; `parse_round_answer(body)` reads the page's body, exactly one of `choice` and
`text`, and returns `(project_id, sprint_id, round_id, index, choice, text)` with the absent one
None. Both are `ValueError` on anything else, a repeated key, NaN or nesting too deep.

The fold keeps each open sprint's `Question`s on `SprintState.questions`, ordered by `(round_id,
index)`. A `questions.asked` row changes a sprint only when it is open, its brief is approved
(`STARTING`) and `checked_round` accepts the row's `questions` and `blocker` (absent: false); each
checked question is then added with `round_id` the row's `seq`, its `index` and `at`. The fold does
not enforce one open round; the service does. A `question.answered` row applies only when its `round`
and `index` (ints, not bools) name an unanswered question of the sprint, its `answer` is a string and
its `chosen` is null or one of the question's options: the question then keeps `answer`, `chosen`,
`answered_at` (the row's `at`) and `differs`, computed as `chosen != recommended` (the row's own
`differs` is not trusted; the owner's own words, `chosen` null, always differ), and the sprint gains
a `MESSAGE_ANSWER` message (`text` the answer, plus `question`, `round_id`, `chosen`). A second
answer, or any other such row, changes nothing. `open_questions(state)` is the unanswered questions
in `(round_id, index)` order, none once the sprint has `stopped_at` or a `closing`, and `round_open(state)` is true while there is one.
`takes_questions(state)` is false once the sprint has `stopped_at`, a `closing` or has ended (`ended_at`); then
a `questions.asked` or `question.answered` row changes nothing (the service refuses `ENDED`). An answer's inbox
entry is `{"id", "kind": "answer", "version": null, "text": <the answer>, "at", "question":
<question text>, "round": <int>, "chosen": <option text> | null}`; every other entry keeps its five
keys.

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
differently)`, and `stop_at`, `stopped_at`, `stop_reason` and `stop_failed_at`. Each row changes only
an open sprint:

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
  retry due at once.

`ended_at(state)` is every route to done, first match: `stopped_at` when set; `None` when `stop_at`
is set (the sprint is stopping); `closing.at` when `closing` is set; `report.at` when the sprint is `STARTING`, no question is open and the
report's phase is `done` (the route that predates the closing report; a newer brief drops that
done report when it is sent, so a replaced sprint is not ended again by the old report); else `None`. A sprint has ended when `ended_at` is not `None`.

`stop_due(state, now_ms)` is true when `stop_at` is set, `stopped_at` is `None`, the closing is set
or `STOP_WAIT_MS` have passed since `stop_at`, and `stop_failed_at` is `None` or `STOP_RETRY_MS` have
passed since it. `STOP_SETTLE_MS` is the service's settle window for a manager the listing may not
show yet and `FINISHED_AFTER_MS` the age after which an ended sprint is shown as finished.
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

import json
import os
import re
import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.console import deliveries
from agent_tools.console.deliveries import DELIVERY_SEEN
from agent_tools.console.event_log import (BRIEF_APPROVED, BRIEF_REPLIED, BRIEF_SENT, GOAL_STATED,
                                           GOAL_WITHDRAWN, MANAGER_FAILED, MANAGER_NO_PROGRESS,
                                           MANAGER_NUDGED, MANAGER_STALLED, MANAGER_STARTED,
                                           MANAGER_STOP_FAILED, MANAGER_STOPPED, MANAGER_WAITING,
                                           MANAGER_WOKEN, QUESTION_ANSWERED, QUESTIONS_ASKED,
                                           SPRINT_ANSWERED, SPRINT_CLOSED, SPRINT_CONTINUED,
                                           SPRINT_MESSAGED, SPRINT_NUDGED, SPRINT_READ,
                                           SPRINT_REPORTED, SPRINT_STOP_REQUESTED, Event)
from agent_tools.console.manager import FAILED_TEXT, MISSING_TEXT, UNAVAILABLE_TEXT
from agent_tools.console.manager import WAITING_TEXT as MANAGER_WAITING_TEXT
from agent_tools.console.sessions import SEEN

MAX_GOAL_CHARS = 2000
MAX_REPLY_CHARS = 2000
MAX_MESSAGE_CHARS = 2000
PARTS = ("done", "excluded", "slices", "risks", "asks")
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
NO_PROGRESS_TEXT = "the manager has stopped making progress on {goal}"
NOT_STUCK = "this sprint's manager is not waiting for you"
REPORT_MEMBERS = ("status", "phase", "milestone", "tracker_url", "issues", "inbox", "next")
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
FINISHED_AFTER_MS = 86_400_000
CLOSED_OUT = "closed out"
MAX_LINE_CHARS = 500
MIN_OPTIONS = 2
MAX_OPTIONS = 4
MAX_ROUND_QUESTIONS = 10
MAX_QUESTION_CHARS = 1000
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
CLOSING_MEMBER = "the closing report has no valid {member}"
SUMMARY_NUMBER = "the summary's first line names an issue number"
NOT_ENDED = "an issue of this sprint is neither landed nor dropped"
ENDED = "this sprint has ended"
ALREADY_STOPPING = "this sprint is already stopping"
STOP_FAILED_TEXT = "could not stop the manager: {reason}; trying again"
UNSTOPPED_TEXT = "The manager of a withdrawn goal could not be stopped: {reason}; trying again"
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
QUESTION_SHAPE = "question {n} is not an object of question, blocks, options and recommended"
QUESTION_MEMBER = "question {n} has no valid {member}"
OPTION_COUNT = "question {n} needs two to four options"
OPTION_TWICE = "question {n} offers one option twice"
NO_RECOMMENDATION = "question {n} recommends none of its options"
ROUND_OPEN = "a round of questions is already open"
UNKNOWN_QUESTION = "this question is not known"
ANSWERED_ALREADY = "this question is already answered"
NOT_AN_OPTION = "choose one of the question's options"
UNREACHABLE_TEXT = "manager not reachable"
UNREACHABLE_AFTER = 2
RENUDGE_AFTER_MS = 60_000
MESSAGE_APPROVED = "approved"
MESSAGE_CHANGES = "changes"
MESSAGE_TEXT = "text"
MESSAGE_ANSWER = "answer"
MESSAGE_STOP = "stop"
SENT = "sent"
DELIVERED = "delivered"
READ = "read"
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
    manager_seen_seq: int | None = None
    revivals: tuple[Revival, ...] = ()
    stalled: str | None = None
    stalled_at: str | None = None
    idle_nudges: int = 0
    idle_nudged_at: str | None = None
    no_progress_at: str | None = None

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


def parse_brief_request(body: bytes) -> tuple[str, str, dict]:
    value = _object(body, {"sprint_id", "secret", "brief"}, project=False)
    sprint_id = _sprint_id(value["sprint_id"])
    if not isinstance(value["secret"], str):
        raise ValueError("secret must be a string")
    brief = value["brief"]
    if not isinstance(brief, dict) or not set(brief) <= set(PARTS):
        raise ValueError(f"brief must be an object of {', '.join(PARTS)}")
    return sprint_id, value["secret"], brief


def parse_report_request(body: bytes) -> tuple[str, str, dict]:
    value = _object(body, {"sprint_id", "secret", "report"}, project=False)
    sprint_id = _sprint_id(value["sprint_id"])
    if not isinstance(value["secret"], str):
        raise ValueError("secret must be a string")
    report = value["report"]
    if not isinstance(report, dict) or not set(report) <= set(REPORT_MEMBERS):
        raise ValueError(f"report must be an object of {', '.join(REPORT_MEMBERS)}")
    return sprint_id, value["secret"], report


ROUND_KEYS = ("questions", "blocker")


def parse_ask_request(body: bytes) -> tuple[str, str, dict]:
    value = _object(body, {"sprint_id", "secret", "round"}, project=False)
    sprint_id = _sprint_id(value["sprint_id"])
    if not isinstance(value["secret"], str):
        raise ValueError("secret must be a string")
    round_ = value["round"]
    if not isinstance(round_, dict) or not set(round_) <= set(ROUND_KEYS):
        raise ValueError(f"round must be an object of {', '.join(ROUND_KEYS)}")
    return sprint_id, value["secret"], round_


def _count(value: object, least: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < least:
        raise ValueError(f"must be an integer of at least {least}")
    return value


def parse_round_answer(body: bytes) -> tuple[str, str, int, int, int | None, str | None]:
    value = _decoded(body)
    base = {"project_id", "sprint_id", "round", "question"}
    if (not isinstance(value, dict) or set(value) not in (base | {"choice"}, base | {"text"})):
        raise ValueError("the body must be an object of project_id, sprint_id, round, question "
                         "and one of choice and text")
    project_id = value["project_id"]
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("project_id must be a non-empty string")
    text = value.get("text")
    if "text" in value and not isinstance(text, str):
        raise ValueError("text must be a string")
    choice = _count(value["choice"], 0) if "choice" in value else None
    return (project_id, _sprint_id(value["sprint_id"]), _count(value["round"], 1),
            _count(value["question"], 0), choice, text)


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


def checked_brief(brief: dict) -> dict:
    checked: dict = {}
    for part in PARTS:
        value = brief.get(part)
        if part == "done":
            if not _text(value):
                raise Refused(MISSING_PART.format(part=part))
            checked[part] = value.strip()
        else:
            if (not isinstance(value, list) or not all(_text(item) for item in value)
                    or (not value and part not in MAY_BE_EMPTY)):
                raise Refused(MISSING_PART.format(part=part))
            checked[part] = [item.strip() for item in value]
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


def checked_report(report: dict) -> dict:
    for member in REPORT_MEMBERS:
        if not _valid_report_member(member, report.get(member)):
            raise Refused(REPORT_MEMBER.format(member=member))
        if member == "status" and re.search(r"#\d", report["status"].strip()):
            raise Refused(STATUS_NUMBER)
    return {"status": report["status"].strip(), "phase": report["phase"],
            "milestone": report["milestone"].strip(), "tracker_url": report["tracker_url"],
            "issues": sorted(({"issue": row["issue"], "stage": row["stage"]}
                              for row in report["issues"]), key=lambda row: row["issue"]),
            "inbox": sorted(set(report["inbox"])), "next": report["next"].strip()}


def _checked_question(n: int, question: object) -> dict:
    if not isinstance(question, dict) or not set(question) <= {"question", "blocks", "options",
                                                                "recommended"}:
        raise Refused(QUESTION_SHAPE.format(n=n))
    text, blocks = question.get("question"), question.get("blocks")
    if not _text(text) or len(text.strip()) > MAX_QUESTION_CHARS:
        raise Refused(QUESTION_MEMBER.format(n=n, member="question"))
    if not _line(blocks):
        raise Refused(QUESTION_MEMBER.format(n=n, member="blocks"))
    options = question.get("options")
    if not isinstance(options, list) or not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        raise Refused(OPTION_COUNT.format(n=n))
    if not all(_line(option) for option in options):
        raise Refused(QUESTION_MEMBER.format(n=n, member="options"))
    stripped = [option.strip() for option in options]
    if len(set(stripped)) != len(stripped):
        raise Refused(OPTION_TWICE.format(n=n))
    recommended = question.get("recommended")
    if not isinstance(recommended, str) or recommended.strip() not in stripped:
        raise Refused(NO_RECOMMENDATION.format(n=n))
    return {"question": text.strip(), "blocks": blocks.strip(), "options": stripped,
            "recommended": recommended.strip()}


def checked_round(round_: dict) -> dict:
    questions = round_.get("questions")
    if not isinstance(questions, list) or not questions:
        raise Refused(NO_QUESTIONS)
    if len(questions) > MAX_ROUND_QUESTIONS:
        raise Refused(TOO_MANY_QUESTIONS)
    blocker = round_.get("blocker", False)
    if not isinstance(blocker, bool):
        raise Refused(BAD_BLOCKER)
    return {"blocker": blocker,
            "questions": [_checked_question(n, question)
                          for n, question in enumerate(questions, 1)]}


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


def message_state(message: Message) -> str:
    if message.read_at is not None:
        return READ
    return DELIVERED if message.delivered_at is not None else SENT


def unread(state: SprintState) -> tuple[Message, ...]:
    return tuple(message for message in state.messages if message.read_at is None)


def unreachable(state: SprintState) -> bool:
    return state.failed_nudges >= UNREACHABLE_AFTER


def open_questions(state: SprintState) -> tuple[Question, ...]:
    if state.stopped_at is not None or state.closing is not None:
        return ()
    return tuple(sorted((question for question in state.questions if question.answer is None),
                        key=lambda question: (question.round_id, question.index)))


def round_open(state: SprintState) -> bool:
    return bool(open_questions(state))


def takes_questions(state: SprintState) -> bool:
    """False once the sprint has stopped, is closed or has ended: it then asks and is asked no more."""
    return state.stopped_at is None and state.closing is None and ended_at(state) is None


def inbox_entry(message: Message) -> dict:
    entry = {"id": message.message_id, "kind": message.kind, "version": message.version,
             "text": message.text, "at": message.at}
    if message.kind == MESSAGE_ANSWER:
        entry.update(question=message.question, round=message.round_id, chosen=message.chosen)
    return entry


def _with_message(state: SprintState, message: Message) -> SprintState:
    messages = sorted((*state.messages, message), key=lambda item: item.message_id)
    return replace(state, messages=tuple(messages))


def _folded_brief(state: SprintState, event: Event) -> SprintState:
    payload = event.payload
    version = payload.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        return state
    brief = state.brief
    if event.kind == BRIEF_SENT:
        parts = payload.get("brief")
        if isinstance(parts, dict) and version > (brief.version if brief else 0):
            superseded = state.report is not None and state.report.phase == DONE
            return replace(state, brief=Brief(version, parts, event.at, NONE, None, None),
                           report=None if superseded else state.report)
        return state
    if brief is None or version != brief.version or brief.decision != NONE:
        return state
    if event.kind == BRIEF_APPROVED:
        return _with_message(
            replace(state, brief=replace(brief, decision=APPROVED, decided_at=event.at)),
            Message(event.seq, MESSAGE_APPROVED, event.at, version, None))
    reply = payload.get("reply")
    if isinstance(reply, str):
        return _with_message(
            replace(state,
                    brief=replace(brief, decision=CHANGES, reply=reply, decided_at=event.at)),
            Message(event.seq, MESSAGE_CHANGES, event.at, version, reply))
    return state


def _id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _folded_message(state: SprintState, event: Event) -> SprintState:
    payload = event.payload
    if event.kind == SPRINT_MESSAGED:
        text = payload.get("text")
        if isinstance(text, str):
            return _with_message(state, Message(event.seq, MESSAGE_TEXT, event.at, None, text))
    elif event.kind == SPRINT_READ:
        through = payload.get("through")
        if _id(through):
            return replace(state, failed_nudges=0, messages=tuple(
                replace(message, read_at=event.at)
                if message.message_id <= through and message.read_at is None else message
                for message in state.messages))
    elif event.kind == SPRINT_NUDGED:
        through, ok = payload.get("through"), payload.get("ok")
        if _id(through) and isinstance(ok, bool):
            messages = state.messages
            if ok:
                messages = tuple(
                    replace(message, delivered_at=event.at)
                    if message.message_id <= through and message.delivered_at is None
                    else message for message in messages)
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
                                     "blocker": payload.get("blocker", False)})
        except Refused:
            return state
        added = tuple(Question(event.seq, index, event.at, checked["blocker"], row["question"],
                               row["blocks"], tuple(row["options"]), row["recommended"])
                      for index, row in enumerate(checked["questions"]))
        return replace(state, questions=(*state.questions, *added))
    round_id, index = payload.get("round"), payload.get("index")
    answer, chosen = payload.get("answer"), payload.get("chosen")
    if not _id(round_id) or not _id(index) or not isinstance(answer, str):
        return state
    for position, question in enumerate(state.questions):
        if (question.round_id, question.index) != (round_id, index):
            continue
        if question.answer is not None or (chosen is not None and chosen not in question.options):
            return state
        answered = replace(question, answer=answer, chosen=chosen, answered_at=event.at,
                           differs=chosen != question.recommended)
        questions = (*state.questions[:position], answered, *state.questions[position + 1:])
        return _with_message(
            replace(state, questions=questions),
            Message(event.seq, MESSAGE_ANSWER, event.at, None, answer, question=question.question,
                    round_id=round_id, chosen=chosen))
    return state


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
                           revivals=revivals, stalled=None, stalled_at=None)
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
    try:
        checked = checked_report(report)
    except Refused:
        return state
    return replace(state, observed=(), moved_ms=None, idle_nudges=0, no_progress_at=None,
                   report=Report(event.at, checked["status"], checked["phase"],
                                 checked["milestone"], checked["tracker_url"],
                                 tuple((row["issue"], row["stage"]) for row in checked["issues"]),
                                 tuple(checked["inbox"]), checked["next"]))


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
            report = state.report
            if state.project_id != event.project or report is None:
                continue
            if run.moved_ms <= int(datetime.fromisoformat(report.at).timestamp() * 1000):
                continue
            reported = {issue for issue, _ in report.issues}
            stages = [stage for stage in run.issues if stage.issue in reported]
            if not stages:
                continue
            kept = {item.issue: item for item in state.observed}
            for stage in stages:
                old = kept.get(stage.issue)
                if old is None or ((run.moved_ms, run.session_id, run.run_id)
                                   >= (old.moved_ms, old.session_id, old.run_id)):
                    kept[stage.issue] = Observed(stage.issue, run.moved_ms, run.session_id,
                                                 run.run_id, stage)
            folded[sprint_id] = replace(
                state, moved_ms=max(state.moved_ms or 0, run.moved_ms),
                observed=tuple(kept[issue] for issue in sorted(kept)))


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
                                                event.at)
        elif event.kind == GOAL_WITHDRAWN:
            folded.pop(sprint_id, None)
        elif event.kind in (BRIEF_SENT, BRIEF_APPROVED, BRIEF_REPLIED) and sprint_id in folded:
            folded[sprint_id] = _folded_brief(folded[sprint_id], event)
        elif event.kind == SPRINT_STOP_REQUESTED and sprint_id in folded:
            folded[sprint_id] = _folded_stop_request(folded[sprint_id], event)
        elif event.kind == SPRINT_CLOSED and sprint_id in folded:
            folded[sprint_id] = _folded_closing(folded[sprint_id], event)
        elif event.kind in (MANAGER_STOPPED, MANAGER_STOP_FAILED) and sprint_id in folded:
            folded[sprint_id] = _folded_stop(folded[sprint_id], event)
        elif event.kind in (MANAGER_STARTED, MANAGER_FAILED, MANAGER_WAITING, MANAGER_WOKEN,
                            MANAGER_STALLED) and sprint_id in folded:
            folded[sprint_id] = _folded_manager(folded[sprint_id], event)
        elif event.kind in (MANAGER_NUDGED, MANAGER_NO_PROGRESS, SPRINT_CONTINUED) \
                and sprint_id in folded:
            folded[sprint_id] = _folded_idle(folded[sprint_id], event)
        elif event.kind == SPRINT_REPORTED and sprint_id in folded:
            folded[sprint_id] = _folded_report(folded[sprint_id], event)
        elif event.kind in (SPRINT_MESSAGED, SPRINT_READ, SPRINT_ANSWERED, SPRINT_NUDGED) \
                and sprint_id in folded:
            folded[sprint_id] = _folded_message(folded[sprint_id], event)
        elif event.kind in (QUESTIONS_ASKED, QUESTION_ANSWERED) and sprint_id in folded:
            folded[sprint_id] = _folded_question(folded[sprint_id], event)
    return folded


def ended_at(state: SprintState) -> str | None:
    if state.stopped_at is not None:
        return state.stopped_at
    if state.stop_at is not None:
        return None
    if state.closing is not None:
        return state.closing.at
    if (state.state == STARTING and state.report is not None and state.report.phase == DONE
            and not open_questions(state)):
        return state.report.at
    return None


def stop_due(state: SprintState, now_ms: int) -> bool:
    if state.stop_at is None or state.stopped_at is not None:
        return False
    waited = state.closing is not None or now_ms - _ms(state.stop_at) >= STOP_WAIT_MS
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
    return "stated " + ago_text(elapsed_ms)


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
    - `failed`: `failed` and `"<FAILED_TEXT>: <reason>"`.
    - `waiting`: `waiting` and `manager.WAITING_TEXT`.

    A `failed` or `waiting` manager of a first launch offers retry only while the sprint has no
    listed session and no brief: a launch can fail after its detached session was already handed
    off, and a retry would then start a second manager for the sprint. A `failed` or `waiting`
    manager whose `takeover` is true offers retry while the sprint has no listed session, whatever
    the brief (a takeover's sprint has a brief by design).

    A sprint with `stop_at` or `stopped_at` set never offers retry, whatever its manager row says:
    neither the view nor the service relaunches the manager of a stopping or stopped sprint.
    """
    if not managers:
        return UNAVAILABLE, UNAVAILABLE_TEXT, False
    manager = state.manager
    stopping = state.stop_at is not None or state.stopped_at is not None
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
        return FAILED, f"{FAILED_TEXT}: {manager.reason}", free
    return WAITING, MANAGER_WAITING_TEXT, free


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
