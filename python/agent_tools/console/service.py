"""The console's loopback service: the log-derived view and the desk page over HTTP.

The service binds `127.0.0.1` on one port (`DEFAULT_PORT`) and nothing else; no
parameter names a host. `Host` must be `127.0.0.1:<port>` or `localhost:<port>`
for the port actually bound, else the answer is `403` `text/plain`
`loopback only`.

Routes (every response carries `Cache-Control: no-store`, except a picture read's 200, which
carries `Cache-Control: private`, and `X-Content-Type-Options: nosniff`, and every one but the
stream `Content-Length`):

    GET /           200 text/html; charset=utf-8, the page, with `Content-Security-Policy: CSP`
    GET /spend      200 text/html; charset=utf-8, the Spend page, with `Content-Security-Policy: CSP`
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
    POST /api/pin   204, a JSON body, the page pins or unpins a profile (below)
    POST /api/approve 204, a JSON body, the page approves a brief (below)
    POST /api/reply 204, a JSON body, the page asks a brief for changes (below)
    POST /api/retry-manager 204, a JSON body, the page starts a sprint's manager again (below)
    POST /api/message 204, a JSON body, the page sends the owner's message to a sprint (below)
    POST /api/stop  204, a JSON body, the page stops a sprint (below)
    POST /api/register-project 204, a JSON body, the page names a repository to adopt (below)
    POST /api/plan-answer 204, a JSON body, the page answers one question of the adoption plan (below)
    POST /api/plan-approve 204, a JSON body, the page approves a ready adoption plan (below)
    POST /api/plan-defer 204, a JSON body, the page answers Not now to an adoption's apply card (below)
    POST /api/register-confirm 204, a JSON body, the page answers the Register card of an adopted repository (below)
    POST /api/trust-check 204, a JSON body, the page answers a Check again card of a failed folder trust (below)
    POST /api/register-cancel 204, a JSON body, the page cancels a registration that was not applied yet (below)
    POST /api/project-question 204, a JSON body, the page asks a read-only question about a project (below)
    POST /api/brief 200 application/json, a manager sends a sprint's brief (below)
    POST /api/report 200 application/json, a manager sends a sprint's report (below)
    POST /api/close 200 application/json, a manager sends a sprint's closing report (below)
    POST /api/inbox 200 application/json, a manager reads a sprint's unread messages (below)
    POST /api/message-reply 200 application/json, a manager answers one message (below)
    POST /api/ask   200 application/json, a manager sends a round of questions (below)
    POST /api/withdraw-question 200 application/json, a manager takes back one open question (below)
    POST /api/notice 200 application/json, a manager posts one notice for its project (below)
    POST /api/notices 200 application/json, a manager lists its project's open notices (below)
    POST /api/withdraw-notice 200 application/json, a manager takes back one of its notices (below)
    POST /api/picture 200 application/json, a manager sends one PNG picture (below)
    POST /api/round-answer 204, a JSON body, the page answers one question (below)
    POST /api/recap 200 application/json, a manager reads what it needs to pick a sprint up (below)
    GET /api/sprint-status?sprint_id=<id> 200 application/json, what became of a brief (below)
    GET /api/picture/<id> 200 image/png, the page reads a stored picture (below)
    GET /api/profile 200 application/json, the profile a new session should use (below)
    GET /api/excluded 200 application/json, the profiles the owner excluded (below)
    GET /api/whoami 200 application/json, what the guest port received (guest port only; 404 on the owner's port)
    anything else   404
    other methods   405 with `Allow: GET` (`Allow: POST` on `/api/hooks`, `/api/readings`,
                    `/api/looked`, `/api/answer`, `/api/check-answer`, `/api/goal`, `/api/withdraw`,
                    `/api/approve`, `/api/reply`, `/api/retry-manager`, `/api/message`, `/api/stop`, `/api/exclusion`, `/api/pin`, `/api/brief`, `/api/report`,
                    `/api/close`, `/api/inbox`, `/api/message-reply`, `/api/recap`, `/api/ask`, `/api/withdraw-question`, `/api/notice`, `/api/notices`, `/api/withdraw-notice`,
                    `/api/picture` and `/api/round-answer`;
                    `Allow: GET` on `/api/picture/<id>`)

Guest door (#1237, ADR-console-066). With `guest_port` (`console --guest-port`, default
`DEFAULT_GUEST_PORT`, loopback only) the service binds a second server on `127.0.0.1`, served by
`GuestHandler` on its own thread, for Tailscale Serve to proxy to; without it there is no second
server, no `guest-token` file and `guest_address` is None. A guest request is admitted by
`guest.admit` in this order, each refusal `403` `text/plain`, one line, `Connection: close`, with
nothing appended (the one thing a guest-port request may publish is the reading below): sharing
off (no tailnet name), a `Host` that is not exactly the configured tailnet name, then not exactly one `Tailscale-User-Login` header of a listed colleague.
`GET /api/whoami` is answered to any request before admission: it reports the `Host` it saw, how
many `Host` and login headers arrived, whether `X-Forwarded-For` did, and whether the login named
by `X-Console-Probe` arrived as a login header, and never repeats a login. After admission an
owner-only route (`OWNER_ONLY`: every page write, manager write, hook and reading route, `/spend`,
`/api/sprint-status`, `/api/profile`, `/api/excluded`) is `403` `guest.OWNER_ONLY_TEXT` for any method,
its body never read; the guest reads (`GUEST_READS` and `GET /api/picture/<id>`) answer the guest's
scoped view (`guest.scoped`, `guest.scrub`): `GET /` is the page carrying the guest token, `GET
/api/state` the colleague's view (`403` `guest.NOT_SHARED_TEXT` when none), `GET /api/stream` the
stream of it, which re-admits on every publish and ends when the colleague, the tailnet name or the
sharing is gone, and a picture read needs the guest token, an `Origin` (when sent) of `https://<tailnet>`
and an id on the colleague's own view, else `404` `this picture is not known`. Every guest response closes
its connection, so a body or a second request sent on it is never parsed. `ROUTES` registers every
route: a handler compares `route` only with registered names, and a method other than GET on a guest
read is `405` `Allow: GET`. The owner's port refuses, on every route, a request carrying a
`Tailscale-*` header or `X-Forwarded-For` with `403` `guest.OWNER_PORT_TEXT`, after the `Host` check.
With `serve_reader` (`console --tailscale PATH`, `guest.serve_reader`) a daemon thread `SERVE_THREAD`
calls `poll_serve` at once and then every `serve_seconds` (`SERVE_SECONDS`, 60): it reads the Windows
Tailscale client's `serve status --json` outside the ingest lock, keeps the reading in memory only (never
in the log) and publishes, so the owner's `sharing.state` (`guest.serve_state`) says whether Serve proxies
the tailnet name to the bound guest port. A reader that raises is one stderr line `console:
serve_status_failed <Type>: <message>` and the reading is None (`unchecked`); without a reader no
thread starts and the state stays `unchecked`.
The guest token is `guest-token` beside `page-token`, made and checked as the page token is; it is
a different token, refused on every owner route, as the page token is on the guest picture read.
The service keeps the last guest-port request's `guest.reading` (every request the port parses,
whatever its method) in memory only (never logged, null after a restart) as the owner's
`sharing.last_request`, publishing only when it changed; a guest's view and stream never carry it.

The owner's access-list writes (#1237) are three page writes, `POST /api/share-tailnet`, `POST
/api/share-colleague` and `POST /api/share-remove` (`SHARE_TAILNET_PATH`, `SHARE_COLLEAGUE_PATH`,
`SHARE_REMOVE_PATH`), each behind the `_page_write` guard and then `_json_body(MAX_SHARE_BYTES)`
(4096; 411, 415, 411, 413 as every JSON page write). Their bodies are the exactly-keyed objects
`guest.parse_tailnet` (`{"tailnet": "<host>.<tailnet>.ts.net" or null}`), `guest.parse_colleague`
(`{"login", "projects"}`) and `guest.parse_removal` (`{"login"}`) read; a body they refuse is `400`
`bad tailnet`, `bad colleague` or `bad removal`. A write refused on its merits (`guest.Refused`:
a project that is not registered, a login that is not listed) is one stderr line `console:
share_refused <reason>` and `409` with the reason; any other failure is `console: share_failed
<Type>: <message>` and `500` `share failed`; no stderr line carries a login or a tailnet name.
Success appends one row under the console's ingest lock, applies it and answers an empty `204`:
`ConsoleService.set_tailnet` a `sharing.tailnet` row, `set_colleague` a `sharing.colleague` row
that replaces the login's whole project list, `remove_colleague` a `sharing.removed` row. A
refusal appends nothing and publishes nothing. Each write publishes, and the guest stream
re-admits on every publish, so a removed colleague's open stream, a cleared tailnet's and a
moved tailnet's end before any further frame, and the next guest request is `403`.

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
`POST /api/retry-manager`, `POST /api/message`, `POST /api/stop`, `POST /api/round-answer`, `POST /api/continue`, `POST /api/exclusion`, `POST /api/pin`, `POST /api/signin`,
`POST /api/signin-code`, `POST /api/signin-cancel`, `POST /api/signin-link`, `POST /api/account-add`, `POST /api/account-remove` and
`POST /api/register-project`, `POST /api/plan-answer`, `POST /api/plan-approve`,
`POST /api/adoption-register`, `POST /api/plan-defer`, `POST /api/register-confirm`, `POST /api/trust-check`,
`POST /api/owner-notice`, `POST /api/owner-notice-withdraw`, `POST /api/project-question`, `POST /api/activate`,
`POST /api/share-tailnet`, `POST /api/share-colleague` and `POST /api/share-remove`; ADR-console-008, ADR-console-010, ADR-console-011, ADR-console-013) is made by the desk page
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
and 502 with `answer.tracker_words(error)`, plain words that carry no raw tracker text (#1075); any
other exception is `console: answer_failed <Type>: <message>` and 500 `answer.UNEXPECTED_FAILURE`.
Before that final line, every retried transport failure writes `console: answer_tick_retry
<project_id> <key> <attempt> <code>: <detail>` (the detail's whitespace collapsed). `POST /api/check-answer` (#863) runs the same body checks in the same order, with
`answer.parse_check_request` as the parser, and calls `answer_check(project_id, key, answer, version,
note, confirm)`; an `answer.Refused` or a `verify_answer.Refused` is the same stderr line and 409, and a
`ForgeError` and any other exception are mapped and retried as above. Success is an empty `204`. No refusal
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
The cancel route answers `204`. `POST /api/signin-link` (#1035) hands a page opened after the start the
live run's link: the same body rule (`MAX_SIGNIN_BYTES`, `signin_run.parse_profile_request`, 400 `bad
link`) and the same refusals (`no sign-in is running for <profile>` when no run is live), and it
answers `200` `application/json` `{"attempt": <int>, "link": <string> | null}` after waiting for the
link outside the service's lock. It appends no row, starts no client, folds nothing and publishes
nothing; when the run it was asked of is replaced while it waits it is refused 409 `the sign-in for
<profile> changed while waiting for its link`, so an attempt is never answered with another run's link.

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
Type>` and records nothing) before the sign-in starts as the start route starts it. Before that the
new profile is granted every registered project's folder trust (`_grant_trust`, cause `account`, one
`trust.granted` row per project, no lock held), after the adder returned, so the adder's 30 second
deadline bounds creation only; an unreadable registry grants nothing (`console:
trust_account_registry_unreadable <name>`) and no grant fails the add. A sign-in that
cannot start leaves the row and the profile, appends the start route's `failed` row and answers
502 `the account was added; its sign-in could not start: <kind>`, with `console: signin_start_failed
<name> <kind>`. Any other exception is `console: account_add_failed <Type>` (never its message) and
500 `adding the account failed`. Success is `200` `application/json`
`{"attempt": <int>, "link": <string> | null, "profile": <name>}` with the start route's attempt and
link; no row, stderr line, view or stream frame carries the link. The token is created once in
`page-token` beside the event log and reaches a client only inside `GET /`, where it replaces
the slot in the page's `console-token` meta tag.

`POST /api/account-remove` (#1030) runs the same checks with `MAX_REMOVE_BYTES` (4096) and
`account_remove.parse_remove_request`: 400 `bad removal`. The service refuses, in this order, each
as 409 with the text, one stderr line `console: account_remove_refused <reason>`, appending and
running nothing: without a sign-out runner, an account remover or a sign-in reader, `removing an
account is not available on this host`; a typed name that is not the profile's, `the typed name
does not match`; then, under the lock `_adding` and in one block of the ingest lock, a profile not
among the directories as they are now (`default` never is), `no such profile`, and a profile whose
sign-in runs, `a sign-in is running for <profile>; cancel it first`. Still in that block the
profile is marked as being removed: from then until the removal ends the console's own runs leave
it alone (no probe of it starts, `_session_choice` and a manager launch's choice pass over it, the
stored choice is written again at once, a manager launch prepared earlier is chosen again,
`start_signin` refuses `<profile> is being removed`, and no manager launch, nudge, wake, full
listing, stop or sign-in status read of it starts: a nudge or stop fails with the same text, a
status read records nothing), and the removal waits (`account_remove.DRAIN_TIMEOUT`) for the probe
and every such client run of it already in flight to end, refusing `<profile> is still being read; try again in a
moment` (the mark dropped, no row) when they do not. It then runs, with no ingest lock held, the
sign-out under the profile (`account_remove.sign_out`) and only after it the launcher's own rm. A
failed sign-out is read again (`console: signin_remove_read_failed ...` when that read fails): a
profile that now reads signed out is removed anyway (outcome `removed_signed_out_already`, kind
the sign-out's), any other is kept, appends one `account.removal` row of outcome `signout_failed`,
one stderr line `console: account_remove_signout_failed <profile> <kind>` and 502 `the account was
not removed: its sign-out failed: <kind>`. A failed rm, or a profile still listed afterwards
(`still_listed`), appends the row of outcome `remove_failed`, one stderr line `console:
account_remove_failed <profile> <kind>` and 502 `the account was signed out but not removed:
<kind>`. Success is one `append` of, in order, `profile.exclusion` and `profile.pin` rows that lift
the profile's own exclusion or pin and the `account.removal` row (outcome `removed`, or the
sign-out's), then the fold, the publish and the choice written again over the profiles now listed;
the answer is an empty `204`. The mark is dropped on every way out, and the stored choice is
written again then. Any other exception is `console:
account_remove_failed <Type>` (never its message) and 500 `removing the account failed`. A running
session of the profile is not stopped.

`POST /api/register-project` (#1052, ADR-console-028) runs the same checks with
`MAX_REGISTER_BYTES` (4096) and `register.parse_register_request`: 400 `bad registration`. The
service refuses, each as 409 with the text, one stderr line `console: registration_refused
<reason>`, appending and running nothing: without an adopter, `register.UNAVAILABLE`; a path
`register.refusal` rejects (not a full path, not a directory, not the top of a checkout, already
registered); and, under the ingest lock, a second registration while one runs
(`register.running`). Otherwise the answer is an empty `204` at once and the run is dispatched: the
adopter's plan. A fresh run first compares the checkout with its remote (`checkout_reader`, #1233,
ADR-console-070): a checkout behind a remote's default branch is one `behind` row (`register.behind`)
and the `register_behind` card, with no plan, no draft and no child; an unreadable remote runs today's
run and carries `remote` (`register.unread`) on its row, and each plan-answer row after it; no origin or no default branch runs today's
run. A `no_change` plan runs no register check: its row is the waiting row, `register.summary`
with no report (#1078, ADR-console-034), and the Register card waits for the owner (below). One
`registration.ended` row (also for a failed child) is appended, unless the
service is closed, in the same ingest section that clears the running mark, so the view's
`registration` stays `running` until no child of the run is left. The registry is written only by
the register child, never by the console. Any other exception is `console: registration_failed
<Type>` and 500 `registering failed`.

`POST /api/register-confirm` (#1078, ADR-console-034) is the answer to the Register card
(`register.confirm_items`) of a repository that is already adopted, and (#1085, ADR-console-035) to
the failure card (`register.failure_items`) of a registration that failed. It runs the same checks with
`MAX_REGISTER_CONFIRM_BYTES` (4096) and `register.parse_confirm_request`: 400 `bad registration
approval`. The service refuses, each as 409 with the text, one stderr line `console:
register_confirm_refused <reason>`, appending and running nothing, in this order: without an adopter,
`register.UNAVAILABLE`; while a run is under way, `register.running`; when the shown registration is
not the row the choice answers (`register` the waiting row, `try_again` the failing one,
`register.failing`, `not_now` either) or names another root, `register.NOT_WAITING`. `not_now`
appends that row again with the note `register.LATER_NOTE` (`register.dismissed`), which
writes no trust and runs no child, and answers `204`. `try_again` takes the same path as
`POST /api/register-project` (the fleet read, `register.refusal`, the running mark, the plan, and for a
`no_change` plan the Register card as today), with the shown row re-checked by its `at` under the ingest
lock before the mark is set; it grants no folder trust and never runs the register child directly.
`update` answers the behind card the same way (#1233, ADR-console-070): `checkout_updater` runs first,
`register.update_failed` is the row when it returns a reason (nothing else runs), and otherwise the
run is a fresh one that compares again; it grants no trust. `not_now` sets the behind card aside.
Both seams (`checkout_reader`, `checkout_updater`) are called as `(root, cancel=stop)` with the event
`close()` sets, so nothing starts after a shutdown; a failure either returns is logged as
`console: registration_error` with verb `compare` or `update`, its `step` and git's own words as
`detail`, and never reaches the page.
`register` also refuses an unreadable registry
and a root the registry already holds, as the first write does, and otherwise answers `204` at once
and dispatches the run: the folder's trust is granted in every profile (`_grant_trust`, cause
`register`, ADR-console-034), then the plan runs again and, for a `no_change` plan, the register
child. Nothing is granted or registered before this answer. Any other exception is `console:
register_confirm_failed <Type>` and 500 `registering failed`.

`POST /api/register-cancel` (#1088, ADR-console-037) is the owner's Cancel registration of the shown
registration, which was not applied yet or whose apply failed. It takes exactly `{"root"}` with
`MAX_REGISTER_CANCEL_BYTES` (4096) and `register.parse_cancel_request`: 400 `bad registration cancel`.
The service refuses, each as 409 with the text, one stderr line `console: register_cancel_refused
<reason>`, appending nothing, in this order: while a run is under way, `register.running`; when the shown
registration is none or names another root, `register.NOT_WAITING`; when `register.cancellable` is false
for it and its adoption (an applied, pushed or opened one), `register.CANCEL_REFUSED`; while the view
carries a failed commit's evidence card that no `/api/stream` client has been sent, `register.CANCEL_UNSEEN`
(a read of `/api/state` does not count and a new failure is a new card, ADR-console-071), so the kept copy
stays until the owner could read why the commit failed. When the plan's
adoption is `apply_failed`, or the shown failure names no plan id, the service looks at every plan of the
root whose apply failed: `approve.left_behind` finds any copy that attempt kept (its failure record, its
directory or its branch, whichever remains), and the service claims the run, has `Adopter.discard` remove
each outside the lock and releases the claim; an `error` result, a `register.RunFailed` or no adopter refuses
with `register.CANCEL_DISCARD_FAILED` and appends nothing. With no kept copy no child runs. Then it appends
one `registration.cancelled` row (`register.cancelled_row`) for the shown plan id, and one more for each
other failed apply of the root, clears the answer's refusal and answers `204`: the registration, deferral,
adoption and folder-trust folds each drop what the rows name (so registering the same repository again
offers a fresh Apply it, and its Check again cards are gone), after a restart too. A Check again under way
when the cancel lands writes nothing and logs no row (`console: trust_grant_skipped cancelled`), so it cannot
bring the cancelled card back. It writes no file of
its own, grants no trust and reads no registry. Any other exception is `console: register_cancel_failed
<Type>` and 500 `cancelling failed`.

A checkout with no `.agents/project.json` (ADR-console-031) is drafted instead of planned: the run
reads it (`draft_reader`, `contract_draft.read` by default), drafts the contract from the fleet
entries the request already read, and, while any field of the draft is open, appends one
`drafting` row and runs no child. When none is open the registry is read again (a project id the
registry gained since the draft was read reopens the project-id card, with no child), and otherwise
the draft is written as JSON to a file `console/drafts/<name>.json` under the state root (mode 0600,
never inside the checkout) that the adopter's plan takes as `--contract-draft`; the file is removed
after the child returns, on every outcome. A plan the resolver refused for a drafted value reopens
that value's card with the plan's plain reason; any other result is the plan's row, carrying the
draft. A drafted checkout is never registered by the run: only the adopted one is.

`POST /api/plan-answer` (#1053, ADR-console-029) runs the same checks with `MAX_PLAN_ANSWER_BYTES`
(4096) and `plan_questions.parse_answer_request`: 400 `bad plan answer`. The service refuses, each
as 409 with the text, one stderr line `console: plan_answer_refused <reason>`, appending and
running nothing, in this order: without an adopter, `plan_questions.UNAVAILABLE`; while any
registration or answer run is under way (one mark, `register.running`); and when the shown
registration has no plan id or another one than the body's, `plan_questions.STALE`. Otherwise the
answer is an empty `204` at once and the run is dispatched: the adopter's plan again with every
answer the shown row holds, then the new one, and never the register child (no registry write from
an answer run). The original of a planner error, a failed child or any other exception is one
stderr line `console: plan_answer_error <json>` (with the traceback for an unexpected exception)
before it is shortened for the page. A plan appends one `registration.ended` row, as the first
run does; a refusal appends nothing and is kept in memory, naming the answered question (its id and
subject), shown by the view for the plan it answered until the next run starts. One line `console: plan_answer_ended <result>` (or `refused`)
ends the run. Any other exception is `console: plan_answer_failed <Type>` and 500 `answering
failed`. The console never reads or writes the plan store or the registry here.

An answer with the question id `contract-draft` (ADR-console-031) changes one field of the shown
row's draft instead of answering the plan. Beyond the three refusals above the service refuses,
each as 409 with the text, appending and running nothing: a row with no draft
(`contract_draft.NO_DRAFT`), an unreadable registry (`register.registry_unreadable`), and any value
`contract_draft.set_value` refuses (the id rule, a project id registered for another checkout, a
command that cannot be read, JSON that does not parse). Otherwise the answer is a `204` and the run
drafts the plan again from the changed fields as a registration does, appending a `drafting` row
or the plan's row. An answer of any other question to a row that holds a draft plans it with the
draft file the same way, and the plan's row carries the draft.

`POST /api/plan-approve` (#1054, ADR-console-030) runs the same checks with `MAX_PLAN_APPROVE_BYTES`
(4096) and `approve.parse_approve_request`: 400 `bad plan approval`. The service refuses, each as
409 with the text, one stderr line `console: plan_approve_refused <reason>`, appending and running
nothing, in this order: without an adopter or a forge, `approve.UNAVAILABLE`; while any registration,
answer or approval run is under way (`register.running`); when the shown registration has no plan id
or another one than the body's, `approve.STALE`; when it is not ready, `approve.NOT_READY`; and when
the plan's adoption is an opened pull request that is still open or ready (`approve.OPENED`) or was
merged (`approve.MERGED`). A closed pull request, a failed apply or no adoption at all is approved
again as a fresh apply. Otherwise the answer is an empty `204` at once and the run is dispatched on
a tracked thread (`APPROVAL_THREAD`) that `close` joins. A fresh approval (no adoption yet) first
grants the folder's client trust (#1078, ADR-console-034): `folder_trust.grant` for the main
checkout's key in `~/.claude.json` (when the service was given a `trust_home`) and in every profile,
one `trust.granted` owner-action row (cause `apply`; one profile and its result per entry, no file
content) and one stderr line `console: trust_granted <cause> <project> <n granted> <n already> <n
failed>`; a failed grant never stops the run, and a resumed approval (Try again, Apply it again)
grants nothing. `close` waits for a grant under way, so its row is kept, and a grant that starts
after `close` began writes nothing (`console: trust_grant_skipped closing`). A result for a profile that no longer exists when the row is
published (an account removal finished meanwhile) is dropped, and a grant left with no result appends
nothing. The run applies the plan (`Adopter.apply`,
acknowledging deletions only when the shown plan lists them; Apply it again passes
`--discard-retained`, and a plan run first has `adopt-project discard` remove every copy kept by a
failed apply of the same repository, so no copy is left behind unnamed) and appends `adoption.step` `applied`,
pushes only the one adoption branch, at the commit apply recorded (`approve.push`), then looks for the branch's pull request
before opening one and, when the open fails, looks once more (a pull request whose answer was lost
is found, never opened twice) and appends `opened`. A failure appends `apply_failed`,
`push_failed` or `open_failed` with plain words; the original error (code, detail, traceback) is one
stderr line `console: plan_approve_error <json>` and never reaches the page, except that a failed
adoption commit's row carries the page-safe `evidence` (`approve.commit_evidence`), shown as the
failure card's lines, while the raw `commit_output` goes only to the `plan_approve_error` line. A step in
`approve.RESUMABLE` is resumed by the next approval (the card's Try again or Apply it again) at the step that
failed: apply is never run twice for a pushed or kept branch, and an `open_failed` step resumes at
the open without pushing again. The console stops between steps and inside every child
and forge call when it closes, appending nothing for the stopped step, so the next approval resumes;
the one exception is the `applied` row, which is appended even when the close has begun, because
apply has already made its branch and a restarted console must not offer a fresh apply.
The console never merges: it pushes the one branch and opens its pull request, and the forge's
required checks keep merge safety. One line `console: plan_approve_ended <step or stopped>` ends the
run. Any other exception is `console: plan_approve_failed <Type>` and 500 `approving failed`.

A `trust.granted` row that leaves a profile `failed` is folded (`folder_trust.failures`, at start,
on append and after retention) into a Check again card (`folder_trust.items`, `trust_items` of the
view) that a later `granted` or `already` for the same root and profile removes, as does the
removal of that profile (an `account.removal` row of outcome `removed` or `removed_signed_out_already`).

`POST /api/trust-check` (#1078, ADR-console-034) is that card's answer. It runs the same checks with
`MAX_TRUST_CHECK_BYTES` (4096) and `folder_trust.parse_check_request`: 400 `bad trust check`. The
service refuses with 409 `folder_trust.NOT_FAILED` and one stderr line `console:
trust_check_refused <reason>`, writing nothing, unless the `(root, profile)` pair is a folded failure
and the profile still has a target (`trust_home/.claude.json` for `default`, else the profile
directory of that name). Otherwise it runs the grant for that one pair on the handler thread
(`_grant_trust`, cause `check`, so `close` waits for it), appends one
`trust.granted` row for that pair and answers `204`. The key is resolved again from the card's root,
never taken from it: a failed row names the checkout path when its key never resolved, and the row
keeps that root, so a granted retry clears the card it answers. Any other exception is `console:
trust_check_failed <Type>` and 500 `checking failed`.

Folder trust at start (#1183, ADR-console-034 D9): when the service is given `trust_at_start`,
`start()` starts `TRUST_START_THREAD`, which reads the registry once with `read_fleet` and runs
`_grant_trust` with cause `console-start` for every registered project in every target
(`~/.claude.json` when given a `trust_home`, and every profile), one row per project, in registry
order, off the ingest lock. A pair already trusted reads `already` and is not written; a `failed`
result is a Check again card like any other. It stops between projects once `close` began and
`close` joins it. An unreadable registry grants nothing (`console: trust_start_registry_unreadable`);
a failing project is `console: trust_start_failed <project> <Type>` and the sweep goes on.

`POST /api/adoption-register` (#1055, ADR-console-028 D10) is the Retry of a refused registration
of a merged adoption. It runs the same checks with `MAX_ADOPTION_REGISTER_BYTES` (4096) and
`approve.parse_approve_request`: 400 `bad registration retry`. The service refuses, each as 409
with the text, one stderr line `console: adoption_register_refused <reason>`, appending and
running nothing, in this order: without an adopter, `register.UNAVAILABLE`; while the plan's
registration runs, `register.running(<name>)`; when no opened, merged adoption of that plan has a
refused registration, `approve.NOT_REFUSED`. Otherwise the answer is an empty `204` once the run
is dispatched on a tracked thread (`APPROVAL_THREAD`) that `close` joins, and the run appends its
outcome whatever it is (an identical refusal included, so the card is fresh). Any other exception
is `console: adoption_register_failed <Type>` and 500 `registering failed`.

`POST /api/plan-defer` (#1073, ADR-console-030) is the `Not now` of the apply card. It runs the
same checks with `MAX_PLAN_DEFER_BYTES` (4096) and `approve.parse_approve_request`: 400
`bad plan deferral`. The service refuses, each as 409 with the text, one stderr line
`console: plan_defer_refused <reason>`, appending and running nothing, in this order: when the
shown registration has no plan id or another one than the body's, `approve.DEFER_STALE`; when no
apply card is offered for that plan, `approve.NOT_OFFERED`. Otherwise it appends one
`adoption.deferred` row, which is folded into `_deferred` at start and on append, and the answer is
an empty `204`. A plan in `_deferred` gets no apply card until the shown plan id is another one; the
work line is unchanged. It runs nothing else. Any other exception is
`console: plan_defer_failed <Type>: <message>`, then its traceback, and 500 `deferring failed`.

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
appended as one `signin.reading` row only when its `(state, ends_at, account)` differs from the folded
one (a profile with no folded sign-in counts as different), then folded and published. A `signin.StatusFailed`
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
deadline. No row, stderr line, view or stream frame carries a link or a code; the link is in the start, add and
link answers only.

The manager's route, `POST /api/brief`, is not a page write: it carries no token and the sprint's
secret takes the token's place. After the loopback `Host` check it runs the hook route's body checks
(`_checked_length(MAX_BRIEF_BYTES)`, 32768: any `Origin` is 403 `origin refused`, a media type that
is not `application/json` 415 `json only`, a length that is not ASCII digits 411 `length required`,
one over the limit 413 `too large`, the body unread), reads the body and runs
`sprints.parse_brief_request` (a body it does not accept is 400 `bad brief`), then `send_brief`, or
`check_brief` when the body carries `"dry_run": true` (the answer is then 200 `application/json`
`{"checked":true}` and nothing is appended, published or written). A
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
(the six parts, `title` first, then a `pictures` list; the secret is checked before the parts), then
refuses each picture, from 1, that the sprint did not store (`sprints.PART_PICTURE_UNKNOWN`, or
`PART_PICTURE_FOREIGN` when another sprint did) or whose file is gone, with `owner` "brief". A brief
may carry up to eight `pictures` members as a question's round does (`picture`, `line`, `pair`).
The checks and the append all run under the ingest lock every sweep holds, and a refusal leaves
every picture file's age as it was. It appends exactly one `brief.sent` row `{"sprint_id",
"version", "goal", "brief"}` with the version one above the folded brief's (1 for none), plus the
top-level `"pictures"`, the unique ids in first-seen order, only when the brief names any (that
list keeps the files from the sweep); a brief with none logs exactly the six parts. It folds and
publishes, and returns the version. `recap` shows only the six parts. A brief after an approval or a reply replaces
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
`sprints.takes_questions` (a stopped, closed or ended sprint asks no more), `sprints.checked_round`
(each ask, context and option within its limit, else `Refused` names the limit and nothing is
logged), then for each question `n` and picture `m` (from 1) `Refused(PICTURE_FOREIGN)` when the
picture is not among the sprint's own stored pictures but another sprint has stored it, else
`Refused(PICTURE_UNKNOWN)` when no sprint has, then `Refused(PICTURE_UNKNOWN)` when
`pictures.present` finds no regular file for it (the check writes nothing and runs under the lock
every sweep holds; a sprint's own pictures also include those a kept `questions.asked` row names, so
retention does not end the ownership), then
`Refused(ROUND_OPEN)` when a question is open and the round is not a blocker; it appends exactly one
`questions.asked` row `{"sprint_id", "goal", "blocker", "questions"}` (the checked round) plus a
top-level `"pictures"`, the round's unique picture ids, only when the round names any (the sweep
keeps those pictures), folds,
publishes and returns the row's `seq` (the round's id) and the question count; it nudges nobody.
A body that also carries `"dry_run": true` runs every one of those refusals through `check_round`
(the same `_checked_ask` under the same lock) and appends and publishes nothing; the 200 answer is
`{"questions":<n>}` without a round (`sprint ask` sends its round without its `file` members first,
so a refusal comes before any upload). The round's picture rule (#1092), `Refused(LOOK_WITHOUT_PICTURE)`
for the first question whose ask or context names screenshots, a `.png` file or a screenshots folder
and carries no picture, is `sprints.checked_round`'s; a dry run passes `files_withheld` and skips it,
because the round it checks has its `file` members left out and `sprint ask` has already applied the rule
to the whole round.
`answer_question(project_id, sprint_id, round_id, index, choice, text)`, under the lock, raises
`Refused(NOT_OPEN)` unless the sprint is open and of that project, `ENDED` unless
`sprints.takes_questions`, `UNKNOWN_QUESTION` unless
`(round_id, index)` is one of its questions, `ANSWERED_ALREADY` when it is answered, with a choice
`NOT_AN_OPTION` unless it indexes an option, with text whatever `sprints.checked_message` refuses,
and with a choice whose option is in the question's `needs_words` and no text `WORDS_NEEDED`;
the answer is the option or the text exactly (the option when both are given), `chosen` the option
or None, `differs` is `chosen` not being the recommendation. It appends exactly one
`question.answered` row `{"sprint_id", "goal", "round", "index", "question", "answer", "chosen",
"recommended", "differs"}`, plus `"words"` (the checked text) only when a choice and text were
both given, folds,
publishes, nudges the manager as `send_message` does and returns the row's `seq`, the message's id.
Every refusal appends and publishes nothing, and neither the secret nor the owner's text appears
in a stderr line.

Withdraw (#1099): `POST /api/withdraw-question` is a manager write dispatched like `/api/ask`, before
`PAGE_WRITES`: `_checked_length(MAX_WITHDRAW_QUESTION_BYTES)` (4096: any `Origin` 403 `origin refused`,
415, 411, 413), a body `sprints.parse_withdraw_question_request` does not accept (`sprint_id`, `secret`,
`round`, `index`) is 400 `bad withdraw question`, a `sprints.SecretRefused` is `console:
withdraw_question_refused <sprint_id> secret refused` and 403 `secret refused`, any other
`sprints.Refused` is the same prefix with the reason and 409 with the reason, any other exception is
`console: withdraw_question_failed <Type>: <message>` and 500 `withdraw question failed`; success is
200 `application/json` `{"index":<i>,"round":<r>}` (sorted keys, compact). `withdraw_question(sprint_id,
secret, round_id, index)`, under the ingest lock, is `_manager_sprint` (`NOT_OPEN`, then
`SecretRefused`), `Refused(ENDED)` unless `sprints.takes_questions`, then `sprints.withdrawable`
against every other folded sprint (`QUESTION_FOREIGN` or `UNKNOWN_QUESTION`, `ANSWERED_ALREADY`,
`WITHDRAWN_ALREADY`); it appends exactly one `question.withdrawn` row `{"sprint_id", "goal", "round",
"index", "question"}` (the ask), folds, publishes and returns the row's `seq`; it nudges nobody, and a
refusal appends and publishes nothing. A round's question may carry `"replaces": {"round", "index"}`:
`_checked_ask` (so `check_round`, the dry run, too) runs `sprints.withdrawable` for each mark, a refusal
being `Refused(REPLACES_REFUSED)` naming the question's number, the pair and the reason, and raises
`ROUND_OPEN` only when the round is not a blocker and some open question is not among
`sprints.replaced(checked)`; `ask_questions` still appends the one `questions.asked` row, which carries
the marks and withdraws what they name in the fold, and no other row. `answer_question` answers a
question the manager took back (withdrawn or replaced) with `Refused(TAKEN_BACK)`, checked after
`NOT_OPEN` and before `ENDED` (withdrawing a done sprint's last open question ends the sprint, and the
owner is still told why), appending no row and storing no message; a question not taken back in an
ended sprint is still `ENDED`.

Notices (#1117, ADR-console-044): `POST /api/notice`, `POST /api/notices` and `POST
/api/withdraw-notice` are manager writes dispatched like `/api/withdraw-question`, before
`PAGE_WRITES`, each through `_checked_length` with its own limit (`MAX_NOTICE_BYTES` 16384,
`MAX_NOTICES_BYTES` 4096, `MAX_WITHDRAW_NOTICE_BYTES` 4096: any `Origin` 403 `origin refused`, 415,
411, 413 `too large`). A body `sprints.parse_notice_request` (`sprint_id`, `secret`, `notice`),
`sprints.parse_inbox_request` (`sprint_id`, `secret`) or `sprints.parse_withdraw_notice_request`
(`sprint_id`, `secret`, `notice`) does not accept is 400 `bad notice`, `bad notices` or `bad withdraw
notice`; a `sprints.SecretRefused` is `console: <route>_refused <sprint_id> secret refused` and 403
`secret refused`; any other `sprints.Refused` is the same prefix with the reason and 409 with the
reason; any other exception is `console: <route>_failed <Type>: <message>` and 500 `notice failed`,
`notices failed` or `withdraw notice failed`. `<route>` is `notice`, `notices` or `withdraw_notice`.
The reason is always one of `sprints.py`'s fixed refusal texts, which never carry a key or value the
manager sent, so every stderr line is one line and neither the secret nor the notice text is printed.
Success is 200 `application/json` (sorted keys, compact): `{"notice":<id>}` for a post (the new row's
`seq`) and a withdrawal (the withdrawn id), `{"notices":[<sprints.notice_entry>...]}` for the list.
`post_notice(sprint_id, secret, notice)`, under the ingest lock, is `_manager_sprint` (`NOT_OPEN`, then
`SecretRefused`), then `sprints.postable_notice` against every other folded sprint; it appends exactly
one `notice.posted` row (project the sprint's project) `{"sprint_id", "goal", "notice": <checked>}`,
folds, publishes and returns the row's `seq`. `withdraw_notice` is `_manager_sprint` then
`sprints.withdrawable_notice`; it appends exactly one `notice.withdrawn` row `{"sprint_id", "goal",
"notice": <id>}` and returns the id. `list_notices` is `_manager_sprint` then
`sprints.project_notices` over every folded sprint of the project, and appends and publishes
nothing. None of the three nudges anybody, and none calls `tick`, `owner_path` or any other tracker
writer; a refusal appends and publishes nothing.

Owner notice nudges (#1120, ADR-console-053, D6): with a nudger, `post_owner_notice` records, still under the
lock, in `_notice_due[sprint_id]` the new row's seq for each sprint of the project with `sprints.takes_notices`
and `_reachable` (every `_nudgeable` condition but the unread message), and reserves in `_nudging` and
dispatches `_dispatch_notice_nudge` after the lock each of them not already reserved; a reserved sprint keeps
the due notice for later. `_nudge` and `_notice_nudge` pop the due id (`covered`) in their first lock block, so
a nudge started after the post covers it: one relay carries a queued message and a notice together, and a
notice posted after that start is due again. A failed message send puts `covered` back. Wherever either ends a
reservation without scheduling a message re-nudge, `_notice_follow` reserves the sprint again when a notice is
still due (and drops it for a stopping service, no nudger or a sprint no longer reachable), and the notice
nudge is dispatched; `renudge` drains `_notice_due` the same way for a sprint another holder (a wake, an idle
nudge, a takeover) released without looking. `_notice_nudge` sends the same fixed sentence through `_reach`,
the routing `_nudge` shares (listing, wake settings, quota recheck, relay or wake, `UNKNOWN_SESSION`), then
appends one `notice.nudged {sprint_id, notice, route, ok[, reason][, listing_failed]}` row for the sprint's
project (a failure also prints `console: notice_nudge_failed <sprint_id> <reason>`); the row is not kept and
nothing folds it. A notice nudge is never retried after its own attempt, counts no `failed_nudges`, sets no
`last_nudge_at` and delivers no message; one that cannot be dispatched is the same row with route null and the
reason `the nudge could not start: <Type>: <message>`, and the post still answers 204.

Owner notices (#1120, ADR-console-053): `POST /api/owner-notice` (`{"project_id", "text"}`, at most
`MAX_OWNER_NOTICE_BYTES` 4096) and `POST /api/owner-notice-withdraw` (`{"project_id", "notice"}`, at most
`MAX_OWNER_NOTICE_WITHDRAW_BYTES` 4096) are page writes: both pass `_page_write`'s guard before any body is
read (no or a foreign `Origin` is 403 `origin refused`, a missing or wrong token 403 `token refused`,
nothing appended). A body `sprints.parse_owner_notice` or `sprints.parse_owner_notice_withdrawal` does not
accept is 400 `bad owner notice` or `bad owner notice withdrawal`; a `sprints.Refused` is `console:
owner_notice_refused <project_id> <reason>` (`owner_notice_withdraw_refused` for the withdrawal) and 409 with
the reason; any other exception is `console: owner_notice_failed <Type>: <message>` and 500 `owner notice
failed` (`owner_notice_withdraw_failed`, `owner notice withdrawal failed`). No stderr line carries the text
or the token; success is 204. `post_owner_notice(project_id, text)`, under the ingest lock, is
`sprints.postable_owner_notice` (registered, a running sprint, a checked heads-up, at most five open),
then exactly one `notice.posted` row (project the project) `{"poster": "owner", "notice": {"kind":
"heads-up", "text": <checked>}}`, folded and published; it returns the row's `seq` and nudges each running manager of the project once (below).
`withdraw_owner_notice(project_id, notice_id)` is `sprints.withdrawable_owner_notice`, then exactly one
`notice.withdrawn` row `{"poster": "owner", "notice": <id>}` and nudges nobody. The rows are folded per project into
`_owner_notices` (`sprints.owner_notices`, at start and in `_fold`) and touch no sprint. `list_notices`
and a new manager's launch prompt add `sprints.open_owner_notices` to `sprints.project_notices` (`owner`
entries), and a manager's `withdraw_notice` of an owner notice is refused (`owner_ids`).

Pictures (#1089, ADR-console-036): `POST /api/picture` is a manager write dispatched like `/api/brief`,
before `PAGE_WRITES`, whose body is one PNG and whose identity travels in headers. The checks run in
this order and each refusal appends nothing and writes no file: any `Origin` (the console's own
included) is 403 `origin refused`; a media type that is not `image/png` is 415 `png only`; a length
that is not ASCII digits is 411 `length required`; one over `MAX_PICTURE_BYTES` (2097152, 2 MiB) is
413 `too large`, answered before any body byte is read, and exactly 2 MiB is taken; then exactly one
`X-Console-Sprint` header matching `sprints.SPRINT_ID` and exactly one non-empty `X-Console-Secret`
header, else 400 `bad picture`; the body is then read, and fewer bytes than the length are 400
`bad picture` with nothing stored, else `store_picture(sprint_id, secret, data)`,
under the ingest lock, is `_manager_sprint` (`NOT_OPEN` is 409 with the reason, then `SecretRefused`
403 `secret refused`), then `pictures.checked_png` (`pictures.NotPng` is 400 with its reason), then
`pictures.store` into `pictures/` beside the event log (the file `pictures/<sha256>`, 0600 in a 0700
directory, written once; a resend keeps the file and renews its age), then one `picture.stored` row
`{"picture", "sprint_id"}` of the sprint's project, per accepted send, resend included. Success is
200 `application/json` `{"picture":"<id>"}` (sorted keys, compact). A refusal is a stderr line
`console: picture_refused <sprint_id> <reason>`; any other exception is `console: picture_failed
<Type>: <message>` and 500 `picture failed`. Neither the secret nor the bytes appear in a stderr line
or an answer. The page is not changed by this route. A brief or a report row references pictures
too: the ids its `pictures` members name are the row's top-level `pictures`, which keeps the files.

`GET /api/picture/<id>` (ADR-console-036) is the page's read of a stored picture, and the only
route that serves one. After the loopback `Host` check it runs `write_guard.read_refusal`: more
than one `Origin`, or one that is not the console's own, is 403 `origin refused`; a `Sec-Fetch-Site`
other than exactly one `same-origin` is 403 `origin refused`; the `X-Console-Token` header exactly
once with the install's token, else 403 `token refused`. A read with no `Origin` is admitted,
because a browser omits `Origin` on a same-origin GET. The guard runs before the id is looked at.
The id is the route after `PICTURE_PREFIX` (`/api/picture/`): a query string, or an id that does
not fully match `pictures.PICTURE_ID`, is 400 `bad picture id`. The file is read only as
`pictures_dir / <id>` through `pictures.read`: an unknown id, a symlink, a non-regular file or an
unreadable file is 404 `this picture is not known`. Success is 200 `image/png`, the stored bytes,
`X-Content-Type-Options: nosniff` and `Cache-Control: private`; a refusal keeps
`Cache-Control: no-store`. The token appears in no header or body. The page draws a picture from an object URL, so
CSP's img-src is data: blob: (ADR-console-038). A verification item's pictures (#1112) are stored in
the same directory by the tracker poll and read by this same route.

Reports (#890): `POST /api/report` is a manager write like the brief's: no token, the sprint's secret
in its place. After the loopback `Host` check it runs `_checked_length(MAX_REPORT_BYTES)`, 65536
(any `Origin` is 403 `origin refused`, a media type that is not `application/json` 415 `json only`,
a length that is not ASCII digits 411 `length required`, one over the limit 413 `too large`, the
body unread), then `sprints.parse_report_request` (a body it does not accept is 400 `bad report`),
then `send_report(sprint_id, secret, report)`, or `check_report` when the body carries
`"dry_run": true` (the answer is then 200 `application/json` `{"checked":true}` and nothing is
appended, published or written). `send_report` under the ingest lock raises
`Refused(NOT_OPEN)` unless the sprint is open, `SecretRefused` unless `sprints.read_secret` holds a
secret equal (`hmac.compare_digest`) to the presented one, `Refused(NOT_STARTED)` unless the
sprint's brief is approved, then whatever `sprints.checked_report` refuses (the secret is checked
before the members; the members, then a `pictures` list), then each picture, from 1, the sprint did
not store (`PART_PICTURE_UNKNOWN`, or `PART_PICTURE_FOREIGN` when another sprint did) or whose file
is gone, with `owner` "report". It appends exactly one `sprint.reported` row `{"sprint_id", "goal",
"report"}` with the checked report, plus the top-level `"pictures"` (the unique ids, first-seen
order) only when the report names any, folds and publishes, and returns the row's `at`. A report
with none logs exactly today's row. A `sprints.SecretRefused`
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
`GET /spend` serves the Spend page (`spend.html`) from memory with the page's CSP and no token;
it writes nothing and reads its data from `/api/stream` (#1135, ADR-console-052).

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
day, or a waiting line still shown, which only a read can replace by its card) and has a GitHub
checkout (`slug_of`), one project after another and never inside the ingest
lock; a project costs at most `inbox.MAX_CALLS` calls. The stop flag is checked between projects
and, through `cancelled`, before every page, so `close()` waits for at most the one `gh` call
already running and a read cancelled or finished after the stop appends and publishes nothing.
The read also lists held issues (#1129): the due evaluation's forge reads are outside
`inbox.MAX_CALLS`, and `cancelled` is asked before each of them too, so `close()` still waits for at
most the one `gh` call already running.
What a read finds is appended as the four inbox events (`inbox.seen`, `inbox.changed`,
`inbox.gone`, `inbox.health`; see `view.py`) and the view is published. A failed read is one
stderr line `console: tracker_failed <project_id> <Type>: <message>`; the project's items stay,
now marked stale, and only a change of read health is appended (`inbox.health`), so a failed read
stays stale across a restart. A read that ends after its project was unregistered appends
nothing. An exception escaping a poll is one stderr line
`console: tracker_poll_failed <Type>: <message>` and the loop goes on. Without a tracker no
thread starts and nothing is read. After a read succeeds, outside the lock, every item holding a
`check_id` is replaced by `inbox.attach_pictures(item, [project root, *screenshot_dirs], pictures_dir)`
(#1112; the roots are the project's checkout and the `--screenshots` locations the command passes), after
which the stop flag is checked again; an exception from one item is one stderr line
`console: picture_attach_failed <project_id> <Type>: <message>` and that item is kept without its
`pictures` and `missing_pictures`. The attach is deterministic, so unchanged files append no row.

Activation (#1114): when the service is given an `activation_reader`, a thread, `ACTIVATION_THREAD`,
started by `start()`, calls `poll_activation()` at once and then every `activation_seconds`
(`ACTIVATION_SECONDS`, one minute). One poll calls the reader with the sorted roots of the registered
projects, outside the ingest lock; the reading it returns (an `activation.Activation` or None) is kept
in memory only, never logged, and handed to `derive_view` as `activation`; a reading equal to the last
one publishes nothing. A reader that raises (the production reader raises `activation.ReadFailed` for
a failed read) keeps the previous reading, publishes nothing and is one stderr line
`console: activation_failed <Type>: <message>`; only a returned value replaces the reading. Each poll is dated by
the count of polls begun, and a reading older than the one kept is dropped, so a slow poll never
overwrites a newer one. When a run ends `ok`, the reading is withheld from the view and from Activate
(`nothing to activate`) until a poll that began after the run's end has returned a value, so a switch
that succeeded never offers Activate for its own commit again on a reading taken before it; a run that
ended not `ok` withholds nothing. An
exception escaping a poll is one stderr line `console: activation_poll_failed <Type>: <message>` and
the loop goes on. Without a reader no thread starts and no line is shown.

The owner's Activate (#1193): `POST /api/activate`, a page write whose body is exactly one JSON
object `{"commit": <40 lowercase hex>}` of at most `MAX_ACTIVATE_BYTES` (the `_json_body` 411, 415
and 413 rules apply; any other body is 400 `bad activation`). It is answered 409 `text/plain`, one
line, appending nothing, in this order: `nothing to activate` (no `activator`, no reading, or a
reading with nothing pending whose commit is not that of a run that failed less than a day ago,
`view.offers_activate`);
`an activation is already running`;
`that commit is no longer the tip of origin's integration branch` (the body's commit is not the
shown reading's); then a fresh
`activator.tip(root)`, read outside the ingest lock, that cannot be read (`the tip of origin's
integration branch could not be read`) or is not the commit (the same text as before). The claim on
the activation is one flag taken under the ingest lock together with the first three checks, so two
concurrent requests cannot both pass; the last check releases it when it refuses. An admitted request
calls `activator.start(root, commit, record)` on the request thread, `record` being what writes the
`activation.started` row. An `Outcome` (nothing was launched) is
one `activation.finished` row, the claim released and an empty `204`; the page shows the failure. A
`Run` is one `activation.started {root, commit, tree}` row, written by the activator's `record` callback
before the process is launched where the tree is named in advance (a scope) and right after it otherwise (a
failed write then kills the process group), a thread `ACTIVATE_THREAD` that runs
`activator.wait(run, stop)`, and an empty `204`. Any other exception from `start` is a failed
`activation.finished` row ("the activation could not run (<Type>: <message>)"), one stderr line
`console: activation_run_failed <Type>: <message>` and the claim released. The claim lasts until
`wait` returns an `Outcome`, which it does only once the run's whole process tree is gone, not when
its first process exits: then one `activation.finished {root, commit, ok, reason, next_step}` row is
appended, the claim released and the view published; the activation reading is read again just
before the row is appended (`poll_activation`), so the line never pairs a finished run with a reading taken
before it. `Stopped` (the service is closing) appends
nothing and keeps the claim; the run goes on. Any other exception from `wait` is one stderr line
`console: activation_wait_failed <Type>: <message>`, no row, the claim kept. The newest started and
finished rows are folded (`activation_run.fold`) into `_activation_run`, at construction and in
`_fold`. Resume: at `start()`, before the server listens, a run still `running` in the log whose
started row carries a `tree` takes the claim and a new `ACTIVATE_THREAD` waits for that tree (the run
outlived the old console, and its recorded exit decides); a `running` run with no `tree` is settled
by a failed `activation.finished` row, `activation_run.UNRECORDED_REASON`. `close()` sets the stop
flag and joins the thread, which raises `Stopped` within `activation_run.POLL_SECONDS`. Neither kind
is in `KEPT_KINDS`, but retention leaves the newest row of each kind whatever its age (`EventLog.retain`), so the last run folds after a restart, and the page token appears in no row, answer or line.

Adoption pull requests (#1054): when the service is given a `forge`, a thread, `ADOPTION_THREAD`,
started by `start()`, calls `poll_adoptions()` at once and then every `adoption_seconds`
(`ADOPTION_SECONDS`, two minutes). One poll reads, through `forge.pull_request_state(slug, number,
cancel=...)`, the pull request of each adoption whose step is `opened` and whose state is still
`open` or `ready` (`approve.waiting`), in the repository its recorded link names
(`approve.pull_slug`, never the checkout's origin of the day), one after another and never inside the ingest lock; the
stop flag cancels the call in flight and a read finished after the stop appends nothing. Only a
state that differs from the folded one is appended, as one `adoption.pull_request` row, and the
view is published, so a ready pull request is one inbox item (`approve.inbox_entries`, see
`view.py`) until it is merged, closed or reads open again; a merged or closed one is read no
more. A failed read is one stderr line `console: adoption_poll_failed <plan_id> <Type>:
<message>` and the item stays as it was. An exception escaping a round is one stderr line
`console: adoption_poll_loop_failed <Type>: <message>` and the loop goes on. The console never
merges: the owner does, on the forge.

The same round ends with the merged registration (#1055, ADR-console-028 D10, ADR-project-contract-005):
`register_merged()` runs `Adopter.register(root, cancel=..., integration_branch=<the recorded pull
request base>, plan_id=<the adoption's plan id>)`, the bounded child, for each `opened`
adoption whose pull request reads `merged` and whose registration is absent or `waiting`
(`approve.enrolling`), one after another on the poll thread, never inside the ingest lock and
never for a closed, open or ready pull request; `_enrolling` keeps one run per plan id, and
the run does not take the one-registration mark. Its outcome (`approve.registration_outcome`) is
one `adoption.registration` row, appended by the poll only when the result or reason differs from
the folded one; `not_integrated` is `waiting` (the next look tries again), a registered project
is listed at once (`refresh()` runs after the row, outside the lock) and anything else is
`refused` in plain words with a Retry card. A run that ended because the console is closing
appends nothing. Every run that is not a green registration first writes one stderr line
`console: adoption_register_error <json>` holding the original (the failure kind, the exception
with its traceback, or the whole returned report with its failed `checks`); one line
`console: adoption_register_ended <plan_id> <result>` (` unchanged` when nothing was appended)
ends the run. The console never writes the registry: the child does.

Movement (#1110, the reading `movement.py` makes and ADR-console-042 uses):
when the service is given a `pull_reader`, a thread, `MOVEMENT_THREAD`, started by `start()`, calls
`poll_movement()` at once and then every `movement_seconds` (`MOVEMENT_SECONDS`, two minutes). One
poll reads, one project after another and never inside the ingest lock, each registered project
with at least one sprint that has not ended (`sprints.ended_at` is None); first, under the lock, it
drops the reading of every project not in that set, so a project with no such sprint costs no
call. For a project it reads the local half, `local_reader(root, pattern)` (default
`movement.read_local`: the branch reflogs and the release store), where `pattern` is the project's
branch pattern, and the forge half, `pull_reader(slug, pattern, cancelled=...)` (`movement.read_pulls`:
two calls, the GraphQL pulls query and the REST lock listing), through `answer.with_retries`, so a transient `ForgeError`
is retried on ADR-console-032's schedule within its 30-second deadline and a non-transient one is
not. A forge read that cannot be made (no `pull_reader`, no slug) or that failed leaves `pulls`
None, and `movement.merged` keeps the last good reading of the pull requests: the sprint reads
its wait for the quiet window from the last time anything moved, then goes quiet. The fold also
receives the issues whose run is in a session not ended (`live`) and those of them in a lock step (`IssueStage.locking`,
#1184); a holding pull request's issues count only when live (a run that died holding the lock leaves its pull request
holding until a waiter takes it over, ADR-console-061 D1); a lock step counts only in a good read that saw a pull request hold a lock, and a failed
read refreshes no lock time, a journal lock step's included, so a lock wait ages out with the rest
of the kept reading. The merged reading
is kept per project in memory only (a restart reads at once), published, and never appended to the
log. The stop flag cancels the read in flight and a read finished after the stop changes nothing.
Stderr lines: `console: movement_read_failed <project_id> <Type>: <message>` (a forge read that
failed), `console: movement_local_failed <project_id> <Type>: <message>` (the local read raised;
it reads as no movement), `console: movement_release_invalid <project_id> <transaction id>...` (the
release store holds a transaction that is not readable; one line until a good read, and it moves
nothing) and `console: movement_poll_failed <Type>: <message>` (an exception escaped a round; the
loop goes on). The cost is two forge calls per project with a running sprint per `MOVEMENT_SECONDS`.
The sessions half (#1185): under the same lock the poll computes, per running project,
`view.sprint_sessions_of` (the live sessions that carry a running sprint's manager name, are its
`manager_session` or run a delivery of one of its issues); only for a project with at least one
such session, outside the lock, it reads the session registry once per poll for the pids, takes
`at = clock()` in milliseconds and calls `session_reader(projects_dirs, targets)` (default
`movement.read_sessions`: the newest transcript write and the CPU of the session's descendants),
(each target carries `replies`, the idle nudges of the sprints the session manages, so the fold leaves
the manager's reply out and keeps earlier movement) and merges the readings with `sessions_ms=at`, so a write after the read began is never counted as
seen. A running sprint's known `manager_session` that is not such a session (absent or ended; a console
restart finds it so) is added as a `held_only` target (`view.sprint_absent_managers`) that reads only
the transcript's held-peer-message flag (#1229). A project with neither calls neither the registry nor the reader. A reader that
raises prints `console: movement_sessions_failed <project_id> <Type>: <message>` and the project
merges with no session reading (the kept associations are not refreshed and age out; the forge
and local halves are unaffected). The sessions half is memory only. Its cost is one
transcript-tree walk per sprint session and one `/proc` scan per project per `MOVEMENT_SECONDS`.

Answers (#862, ADR-console-010): `answer(project_id, key, choices)` ticks one option under each
question of a decision item on the tracker, through `tick` (default `answer.tick_on_tracker`;
`tick(slug, issue, comment_id, questions, choices)`), and marks the item answered at once. It
raises `answer.Refused` with `NOT_OPEN` when the project is not registered, no record
`(project_id, key)` exists, or the item is answered, is not a decision, or has no questions; with
`CHOOSE` unless `choices` is a list of one `int` (not `bool`) per question within its options; with
`SENDING` while another answer to the same item runs. The tick runs through `answer.with_retries`
(#1075), with the service's `monotonic` clock (default `time.monotonic`, so a step of the system
clock never lengthens or ends the retries) and `write_sleep` (default `self._stop.wait`, so closing the
service ends the retries): a transport failure is tried again within the `answer.RETRY_BUDGET_SECONDS`
deadline, each retry writing one `answer_tick_retry` stderr line, and the slot stays in `_sending`
for the whole retry, so a second answer meanwhile is `SENDING`. A `ForgeError` of the tick propagates
only after the retries, or at once when it is not a transport failure. The tick runs outside the ingest lock, so a hook or a poll never waits for `gh`. On success, under the
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
still exists, is unanswered and names the same comment. `owner_path` runs through the same
`answer.with_retries` as the tick, with the same deadline, `monotonic` clock, `write_sleep` and `SENDING` slot, except
that a note is tried once: posting it again would post the text twice. A failure of `owner_path`
propagates, only after the retries when it is a transport failure, and appends nothing.
A review item (#1113) is answered through `criterion_path` (default `answer.answer_criterion`) with the same
refusals, retries and marking.

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
#1028), which `capacity_view` leaves out of the room, and the pinned profile (#1029), which it
answers first while it has room, and `Wait` appends `manager.waiting`. Otherwise the launcher is called outside the lock, and then,
under it, a sprint that was withdrawn meanwhile has its secret and settings file removed again and
no row appended, and otherwise, unless the service is stopping, `manager.started {sprint_id, profile, session_name}`
or `manager.failed {sprint_id, reason}` is appended (the reason of a `LaunchFailed`, else `<Type>:
<message>`, the secret shown as `<secret>`), a failure is one stderr line `console: manager_failed
<sprint_id> <reason>`, and the view is published. `withdraw_goal` also removes the manager's
settings file. The sprint's secret appears in no row, view or stderr line. `_prepared_launch`
passes `manager.new_launch` `sprints.notice_block` of the project's open notices for the sprint
(every other sprint's, never its own, #1118), so a first launch, an owner retry and a takeover
all carry the block before the goal; a wake does not (the manager reads it with `sprint inbox`).

Profile choice (#1011, ADR-console-023): `GET /api/profile` answers the profile a new session should
use, `manager.session_profile` over `capacity.capacity_view` of the profile directories read at that
moment (never the last poll's), the sign-ins, the excluded profiles (folded from the log's
`profile.exclusion` rows, #1028), the pinned profile (folded from the log's `profile.pin` rows,
#1029) and each profile's last use, folded from the log's
session rows (`manager.profile_use`, kept after a session leaves and rebuilt on restart); a profile
being removed (#1030) is never chosen. The body
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

Pin (#1029): `set_pin(profile, pinned)` (`POST /api/pin`, body `{"profile", "pinned"}` with `pinned`
a bool, at most `MAX_PIN_BYTES`; a bad body is 400 `bad pin`, a refusal 409 with the reason
(`no such profile` unless the profile is among the directories as they are now, `excluded; include
it first`, `already pinned`, `not pinned`: an unpin is checked against the pin alone), any other
failure 500 `pin failed`) appends one `profile.pin {profile, pinned}` row with no project, and
nothing for a refusal. A pin moves an earlier pin to the new profile. As for an exclusion, under the
ingest lock the choice file is written first, over the pin the change gives, so a failed write is a
500 with nothing appended or published, and a failed append puts the file back to the choice over
the old pin. The pin is folded from the log at construction and by `_fold`, and rebuilt by
`retain()`, so a restart and a retention pass give the same pin; the view's `pin_launches` is the
fold `pin.pin_launches` of the log, kept after an unpin and rebuilt at a restart and a retention
pass. Every choice path (the route, the
poll, an exclusion, a manager launch and a launch checked again after an exclusion) is made over
the folded pin. An exclusion of the pinned profile is refused `pinned; unpin it first`.

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
the refresh writes the mode `permission.read` chooses for the sprint's project, read again off the lock
before the write (ADR-console-060), and the row of that attempt (`sprint.nudged`, `notice.nudged` or
`manager.woken`) carries it as `"permission"`; the write runs under the ingest lock so a withdrawal cannot fall inside it; a file that cannot be written, a
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
re-folds the sessions, the inbox records and the project questions and re-derives the last look and the moments from the
log under the ingest lock, with the construction code, and publishes, so the running digest equals
the one a restart would publish, and a later change is judged against what the log still holds. A failing pass
is one stderr line `console: retention_failed <Type>: <message>` and the loop goes on. Each pass, the
construction's included, also sweeps `pictures/` (ADR-console-036): it removes every picture that no
row references (`pictures.referenced` of the log's events) once its age, by `self._clock()`, is more
than one day, whether or not the pass removed rows. A failing sweep is one stderr line
`console: picture_sweep_failed <Type>: <message>`; neither construction nor `retain()` raises for it.

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

Spend (#1134): the thread named `SPEND_THREAD`, started by `start()`, calls `poll_spend()` every
`spend_seconds` (`SPEND_SECONDS`), the first poll `spend_seconds` after `start()`; construction never
reads a transcript, so the view's `spend` is null until that poll. `poll_spend()` reads the session,
session-subagent and workflow agent transcripts under the `projects` directory beside each of
`session_dirs()` (see `spend.py`), and on darwin the keepalive ping log (`ping_log()`), outside the
ingest lock, then builds the spend view and publishes it under that lock; it appends nothing to the
log. The account of a session is folded from the log's `session.seen` and `session.profile` rows
(`spend.session_profiles`) and is kept after `session.gone`, for as long as those rows are retained.
A question session's spend is the `questions` aspect, its sessions folded from the
`project_question.asked` rows' `session_id` and `profile` (`spend.question_sessions`), on
construction and on each append. The asked and answered rows are folded by
`project_question.asked_questions` into each project entry's `questions`, at construction and on
each append; a retention pass that removed rows re-folds them from the retained log, as a restart
would, so a follow-up is admitted and grouped against what the log still holds (#1178).
A failed iteration is one stderr line `console: spend_poll_failed <Type>: <message>` and the loop
goes on.

Construction order: bind the server (an `OSError` propagates and nothing else is
opened); load or create the page token (a `write_guard.TokenError` propagates: the service does
not start); open the event log; run one retention pass; fold the projects, the sessions, the inbox,
the read health, the deliveries, the sprints, the withdrawn ids and the pending stops, then the last look and the digest moments, from it; publish
the view; sample the registry's signature; `refresh()`; `poll_sessions()`; `poll_deliveries()`. The
absent set starts empty, so a restart drops a session only after two polls miss
it. On any failure after the bind, what was opened is closed and the exception
re-raised. `start()` serves on a daemon thread named `console-http` and starts the spend thread; `close()`
sets the stop flag, then `closing`, wakes every waiter, joins the watcher, the session poll, the probe loop, the
tracker, movement, retention, digest and spend threads and the folder-trust start thread and tears the rest down; it is idempotent.

`POST /api/project-question` (#1176, ADR-console-058) carries one JSON body of `project_id` and
`question`, and optionally a non-empty string `thread_id` (#1178, ADR-console-062)
(`MAX_PROJECT_QUESTION_BYTES`, 16384, the checks of the goal route): a body
`project_question.parse_request` does not accept is 400 `bad question`; `project_question.Refused` is
one stderr line `console: project_question_refused <reason>` and 409 with the reason; any other
exception is `console: project_question_failed <Type>: <message>` and 500 `question failed`;
success is an empty `204`, sent once the question is accepted and its job handed to
`project_question_dispatch` (default: a new daemon thread named `PROJECT_QUESTION_THREAD`), never
once it is answered. `ask_project_question(project_id, text, thread_id=None)` admits a question under the ingest
lock, in this order: no `project_asker` is `Refused` "questions are not available on this host
yet", a set stop flag is `Refused` "the console is stopping", an unregistered project, the
question's own checks, with a `thread_id` only the follow-up checks of
`project_question.follow_up` against the project's folded questions (an unknown thread, a thread
whose last question is not answered, a thread too long to carry), and no account the console would
start a session under (`_session_choice`); a refusal appends nothing and counts nothing. An
accepted question appends one `project_question.asked` row (`question_id`, `question`, `profile`,
`session_id`, the last also passed as the session's `--session-id`, and for a follow-up the
`thread_id` it was given) and counts itself open in that same section. A follow-up's session gets
the turns `follow_up` returned at admission in its prompt and nothing else changes: its routes,
model, flags, settings and cap are a first question's (ADR-console-062). Its job reads the project's reach (its read-only routes and its GitHub repository,
`project_question.reach_of`; a contract that cannot be resolved is a
`failed` answer naming why, never "no routes", and starts no session; one stderr line `console:
project_question_contract_failed <question_id> <Type>: <message>`), then runs the asker under the
chosen profile's client-run count (`_client_run`), so an account removal waits for a running
question and a question whose profile is being removed or already removed fails without starting a
session (`claude-account` would otherwise recreate a removed profile directory). A job that finds
the stop flag set answers `failed` without a session. Every accepted question records exactly one
`project_question.answered` row (`question_id`, `outcome`, `answer` or `reason`) and releases its
count on every path; an outcome other than `answered` is also one stderr line `console:
project_question_unanswered <question_id> <reason>`, and a row that cannot be appended is one
`console: project_question_unrecorded <question_id> <Type>: <message>`. `close()` waits, after
the approval workers and before the server and the log close, until no accepted question is
unanswered and then joins the question workers; the stop flag, set first, also cancels a running
session. Nothing in this path reads the tracker or the forge.
"""

import contextlib
import dataclasses
import hmac
import http.server
import json
import socketserver
import sys
import os
import threading
import tempfile
import time
import traceback
import uuid
import collections
from collections import OrderedDict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl

from agent_tools.claims import owner_actions
from agent_tools.console import (
    project_question, account_add, account_remove, activation, checkout_remote, activation_run, answer, approve, capacity, contract_draft, deliveries, digest, exclusion, idle, inbox,
    folder_trust, guest, manager, movement, nudge, permission, pin, plan_questions, probe, register, revive, pictures, sessions, signin, signin_run, spend, sprints, write_guard)
from agent_tools.console.event_log import (
    BRIEF_APPROVED, BRIEF_REPLIED, BRIEF_SENT, GOAL_STATED, GOAL_WITHDRAWN, MANAGER_FAILED,
    MANAGER_NO_PROGRESS, MANAGER_NUDGED, MANAGER_STALLED, MANAGER_STARTED, MANAGER_STOP_FAILED,
    MANAGER_STOPPED, MANAGER_WAITING, MANAGER_WOKEN, NOTICE_NUDGED, NOTICE_POSTED, NOTICE_WITHDRAWN,
    PROJECT_QUESTION_ANSWERED, PROJECT_QUESTION_ASKED,
    QUESTION_ANSWERED, QUESTION_WITHDRAWN, QUESTIONS_ASKED,
    SHARING_COLLEAGUE, SHARING_REMOVED, SHARING_TAILNET,
    SPRINT_ANSWERED, SPRINT_CONTINUED, SPRINT_MESSAGED, SPRINT_NUDGED, SPRINT_CLOSED, SPRINT_READ, SPRINT_REPORTED, SPRINT_STOP_REQUESTED, Event,
    EventLog, utc_now)
from agent_tools.console.view import (
    INBOX_CHANGED, ReadState, derive_view, encode_view, health_change, inbox_changes, inbox_records,
    is_waiting, offers_activate, project_for, project_states, read_states, registry_changes,
    sprint_absent_managers, sprint_nudge_replies, sprint_sessions_of, sprint_waiting)
from agent_tools.project_contract import agent_platform
from agent_tools.system.forge_api import ForgeError
from agent_tools.verification import verify_answer

def _epoch_ms(at: str) -> int:
    return int(datetime.fromisoformat(at).timestamp() * 1000)


def _reduced(questions: list[dict]) -> list[tuple[str, list[str]]]:
    return [(q["question"], list(q["options"])) for q in questions]


HOST = "127.0.0.1"
DEFAULT_PORT = 27184
DEFAULT_GUEST_PORT = 27185
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
       "connect-src 'self'; img-src data: blob:; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'")
PAGE: bytes = Path(__file__).with_name("page.html").read_bytes()
SPEND_PAGE: bytes = Path(__file__).with_name("spend.html").read_bytes()
BACKLOG = 16
POLL_SECONDS = 0.25
KEEPALIVE_SECONDS = 15.0
WATCH_THREAD = "console-registry-watch"
SPEND_PAGE_PATH = "/spend"
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
PIN_PATH = "/api/pin"
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
WITHDRAW_QUESTION_PATH = "/api/withdraw-question"
NOTICE_PATH = "/api/notice"
NOTICES_PATH = "/api/notices"
WITHDRAW_NOTICE_PATH = "/api/withdraw-notice"
OWNER_NOTICE_PATH = "/api/owner-notice"
OWNER_NOTICE_WITHDRAW_PATH = "/api/owner-notice-withdraw"
ACTIVATE_PATH = "/api/activate"
ACTIVATE_NOTHING = "nothing to activate"
ACTIVATE_RUNNING = "an activation is already running"
ACTIVATE_MOVED = "that commit is no longer the tip of origin's integration branch"
ACTIVATE_UNREADABLE = "the tip of origin's integration branch could not be read"
ROUND_ANSWER_PATH = "/api/round-answer"
CHECK_PATH = "/api/check-answer"
SIGNIN_PATH = "/api/signin"
SIGNIN_CODE_PATH = "/api/signin-code"
SIGNIN_CANCEL_PATH = "/api/signin-cancel"
SIGNIN_LINK_PATH = "/api/signin-link"
ACCOUNT_ADD_PATH = "/api/account-add"
ACCOUNT_REMOVE_PATH = "/api/account-remove"
REGISTER_PATH = "/api/register-project"
PLAN_ANSWER_PATH = "/api/plan-answer"
PLAN_APPROVE_PATH = "/api/plan-approve"
ADOPTION_REGISTER_PATH = "/api/adoption-register"
PLAN_DEFER_PATH = "/api/plan-defer"
REGISTER_CONFIRM_PATH = "/api/register-confirm"
TRUST_CHECK_PATH = "/api/trust-check"
REGISTER_CANCEL_PATH = "/api/register-cancel"
PROJECT_QUESTION_PATH = "/api/project-question"
PROJECT_QUESTION_THREAD = "console-project-question"
SHARE_TAILNET_PATH = "/api/share-tailnet"
SHARE_COLLEAGUE_PATH = "/api/share-colleague"
SHARE_REMOVE_PATH = "/api/share-remove"
MAX_SHARE_BYTES = 4096
PAGE_WRITES: frozenset[str] = frozenset({
    LOOKED_PATH, ANSWER_PATH, CHECK_PATH, GOAL_PATH, WITHDRAW_PATH, APPROVE_PATH, REPLY_PATH,
    RETRY_PATH, MESSAGE_PATH, STOP_PATH, ROUND_ANSWER_PATH, CONTINUE_PATH, EXCLUSION_PATH,
    PIN_PATH, SIGNIN_PATH, SIGNIN_CODE_PATH, SIGNIN_CANCEL_PATH, SIGNIN_LINK_PATH, ACCOUNT_ADD_PATH,
    ACCOUNT_REMOVE_PATH, REGISTER_PATH, PLAN_ANSWER_PATH, PLAN_APPROVE_PATH,
    ADOPTION_REGISTER_PATH, PLAN_DEFER_PATH, REGISTER_CONFIRM_PATH, TRUST_CHECK_PATH,
    REGISTER_CANCEL_PATH, OWNER_NOTICE_PATH, OWNER_NOTICE_WITHDRAW_PATH, PROJECT_QUESTION_PATH, ACTIVATE_PATH,
    SHARE_TAILNET_PATH, SHARE_COLLEAGUE_PATH, SHARE_REMOVE_PATH})
MAX_SIGNIN_BYTES = 4096
MAX_ACCOUNT_BYTES = 4096
MAX_REMOVE_BYTES = 4096
MAX_REGISTER_BYTES = 4096
MAX_PLAN_ANSWER_BYTES = 4096
MAX_PLAN_APPROVE_BYTES = 4096
MAX_ADOPTION_REGISTER_BYTES = 4096
MAX_PLAN_DEFER_BYTES = 4096
MAX_REGISTER_CONFIRM_BYTES = 4096
MAX_TRUST_CHECK_BYTES = 4096
MAX_REGISTER_CANCEL_BYTES = 4096
APPROVAL_THREAD = "console-adoption-approval"
SIGNIN_THREAD = "console-signin-deadline"
SIGNIN_TICK_SECONDS = 1.0
MAX_ANSWER_BYTES = 4096
MAX_GOAL_BYTES = 16384
MAX_PROJECT_QUESTION_BYTES = 16384
MAX_WITHDRAW_BYTES = 4096
MAX_BRIEF_BYTES = 32768
MAX_REPORT_BYTES = 65536
MAX_CLOSE_BYTES = 65536
MAX_STOP_BYTES = 4096
RECAP_PATH = "/api/recap"
PICTURE_PATH = "/api/picture"
PICTURE_PREFIX = PICTURE_PATH + "/"
SPRINT_HEADER = "X-Console-Sprint"
SECRET_HEADER = "X-Console-Secret"
MAX_PICTURE_BYTES = pictures.MAX_BYTES
MANAGER_WRITES: frozenset[str] = frozenset({BRIEF_PATH, REPORT_PATH, CLOSE_PATH, INBOX_PATH,
                                            MESSAGE_REPLY_PATH, RECAP_PATH, ASK_PATH, WITHDRAW_QUESTION_PATH,
                                            NOTICE_PATH, NOTICES_PATH, WITHDRAW_NOTICE_PATH,
                                            PICTURE_PATH})
MAX_RECAP_BYTES = 4096
MAX_ASK_BYTES = 65536
MAX_WITHDRAW_QUESTION_BYTES = 4096
MAX_NOTICE_BYTES = 16384
MAX_NOTICES_BYTES = 4096
MAX_WITHDRAW_NOTICE_BYTES = 4096
MAX_OWNER_NOTICE_BYTES = 4096
MAX_OWNER_NOTICE_WITHDRAW_BYTES = 4096
MAX_ACTIVATE_BYTES = 4096
MAX_ROUND_ANSWER_BYTES = 16384
MAX_MESSAGE_BYTES = 16384
MAX_INBOX_BYTES = 4096
MAX_MESSAGE_REPLY_BYTES = 16384
MAX_APPROVE_BYTES = 4096
MAX_REPLY_BYTES = 16384
MAX_RETRY_BYTES = 4096
MAX_CONTINUE_BYTES = 4096
MAX_EXCLUSION_BYTES = 4096
MAX_PIN_BYTES = 4096
_FOLDED = object()
MAX_HOOK_BYTES = 8 * 1024 * 1024
READINGS_PATH = "/api/readings"
MAX_READING_BYTES = 64 * 1024
POST_LIMITS = {HOOK_PATH: MAX_HOOK_BYTES, READINGS_PATH: MAX_READING_BYTES}
PAGE_PATH = "/"
STATE_PATH = "/api/state"
STREAM_PATH = "/api/stream"
WHOAMI_PATH = "/api/whoami"
OWNER_READS: frozenset[str] = frozenset({SPEND_PAGE_PATH, STATUS_PATH, PROFILE_PATH, EXCLUDED_PATH})
GUEST_READS: frozenset[str] = frozenset({PAGE_PATH, STATE_PATH, STREAM_PATH, WHOAMI_PATH})
OWNER_ONLY: frozenset[str] = (PAGE_WRITES | MANAGER_WRITES | frozenset(POST_LIMITS) | OWNER_READS)
ROUTES: frozenset[str] = OWNER_ONLY | GUEST_READS | {PICTURE_PREFIX}
SESSION_POLL_SECONDS = 5.0
SESSION_THREAD = "console-session-poll"
TRACKER_SECONDS = 120.0
TRACKER_THREAD = "console-tracker-poll"
ACTIVATION_SECONDS = 60.0
ACTIVATION_THREAD = "console-activation-poll"
ACTIVATE_THREAD = "console-activate"
ADOPTION_SECONDS = 120.0
ADOPTION_THREAD = "console-adoption-poll"
MOVEMENT_SECONDS = 120.0
MOVEMENT_THREAD = "console-movement-poll"
RETENTION_SECONDS = 86400.0
RETENTION_THREAD = "console-retention"
DIGEST_SECONDS = 60.0
DIGEST_THREAD = "console-digest"
SPEND_SECONDS = 60.0
SPEND_THREAD = "console-spend"
SERVE_SECONDS = 60.0
SERVE_THREAD = "console-serve-poll"
MANAGER_THREAD = "console-manager-launch"
PROBE_TICK_SECONDS = 15.0
PROBE_LOOP_THREAD = "console-probe-poll"
PROBE_THREAD = "console-probe"
TRUST_START_THREAD = "console-trust-start"


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


class ConsoleHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        """Silenced: the service writes no access log."""

    def _send(self, status: int, content_type: str, body: bytes, *headers: tuple[str, str],
              cache: str = "no-store"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _loopback(self) -> bool:
        port = self.server.server_address[1]
        if self.headers.get("Host") not in (f"{HOST}:{port}", f"localhost:{port}"):
            self.close_connection = True
            self._send(403, "text/plain", b"loopback only\n", ("Connection", "close"))
            return False
        text = guest.owner_port_refusal(self.headers.keys())
        if text is not None:
            self._refuse(403, text)
            return False
        return True

    def _refuse(self, status: int, text: str):
        self.close_connection = True
        self._send(status, "text/plain", text.encode() + b"\n", ("Connection", "close"))

    def _checked_length(self, limit: int, media: str = "application/json",
                        wrong_media: str = "json only") -> int | None:
        """The body length of a write that passed the shared checks, else None (already refused)."""
        if self.headers.get("Origin") is not None:
            self._refuse(403, "origin refused")
            return None
        sent = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if sent != media:
            self._refuse(415, wrong_media)
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
        if route == WITHDRAW_QUESTION_PATH:
            return self._withdraw_question_request()
        if route == NOTICE_PATH:
            return self._notice_request()
        if route == NOTICES_PATH:
            return self._notices_request()
        if route == WITHDRAW_NOTICE_PATH:
            return self._withdraw_notice_request()
        if route == PICTURE_PATH:
            return self._picture_request()
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
            self._refuse(502, answer.tracker_words(error))
            return False
        except Exception as error:
            print(f"console: answer_failed {type(error).__name__}: {error}", file=sys.stderr)
            self._refuse(500, answer.UNEXPECTED_FAILURE)
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

    def _project_question_request(self, console: "ConsoleService") -> bool:
        """Read and carry out a project question; False when it was refused."""
        body = self._json_body(MAX_PROJECT_QUESTION_BYTES)
        if body is None:
            return False
        try:
            project_id, question, thread_id = project_question.parse_request(body)
        except ValueError:
            self._refuse(400, "bad question")
            return False
        try:
            console.ask_project_question(project_id, question, thread_id)
        except project_question.Refused as error:
            print(f"console: project_question_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: project_question_failed {type(error).__name__}: {error}", file=sys.stderr)
            self._refuse(500, "question failed")
            return False
        return True

    def _signin_request(self, console: "ConsoleService", route: str) -> bool:
        """Carry out a sign-in write; True when the shared empty 204 is still to be sent."""
        name = {SIGNIN_PATH: "sign-in", SIGNIN_CODE_PATH: "code", SIGNIN_CANCEL_PATH: "cancel",
                SIGNIN_LINK_PATH: "link"}[route]
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
            if route in (SIGNIN_PATH, SIGNIN_LINK_PATH):
                attempt, link = (console.start_signin(profile) if route == SIGNIN_PATH
                                 else console.signin_link(profile))
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

    def _removal_request(self, console: "ConsoleService") -> bool:
        """Carry out the remove-account write; it answers itself, so this is always False."""
        body = self._json_body(MAX_REMOVE_BYTES)
        if body is None:
            return False
        try:
            profile, typed = account_remove.parse_remove_request(body)
        except ValueError:
            self._refuse(400, "bad removal")
            return False
        try:
            console.remove_account(profile, typed)
        except sprints.Refused as error:
            print(f"console: account_remove_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except account_remove.SignOutFailed as error:
            print(f"console: account_remove_signout_failed {profile} {error.kind}",
                  file=sys.stderr)
            self._refuse(502, f"the account was not removed: its sign-out failed: {error.kind}")
            return False
        except account_remove.RemoveFailed as error:
            print(f"console: account_remove_failed {profile} {error.kind}", file=sys.stderr)
            self._refuse(502, f"the account was signed out but not removed: {error.kind}")
            return False
        except Exception as error:
            print(f"console: account_remove_failed {type(error).__name__}", file=sys.stderr)
            self._refuse(500, "removing the account failed")
            return False
        try:
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.flush()
        except OSError:
            pass
        return False

    def _register_request(self, console: "ConsoleService") -> bool:
        """Carry out the register-project write; True when the shared 204 is to be sent."""
        body = self._json_body(MAX_REGISTER_BYTES)
        if body is None:
            return False
        try:
            path = register.parse_register_request(body)
        except ValueError:
            self._refuse(400, "bad registration")
            return False
        try:
            console.register_project(path)
        except sprints.Refused as error:
            print(f"console: registration_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: registration_failed {type(error).__name__}", file=sys.stderr)
            self._refuse(500, "registering failed")
            return False
        return True

    def _plan_answer_request(self, console: "ConsoleService") -> bool:
        """Carry out the plan-answer write; True when the shared 204 is to be sent."""
        body = self._json_body(MAX_PLAN_ANSWER_BYTES)
        if body is None:
            return False
        try:
            plan_id, question, subject, value = plan_questions.parse_answer_request(body)
        except ValueError:
            self._refuse(400, "bad plan answer")
            return False
        try:
            console.answer_plan(plan_id, question, subject, value)
        except sprints.Refused as error:
            print(f"console: plan_answer_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: plan_answer_failed {type(error).__name__}", file=sys.stderr)
            self._refuse(500, "answering failed")
            return False
        return True

    def _plan_approve_request(self, console: "ConsoleService") -> bool:
        """Carry out the plan-approve write; True when the shared 204 is to be sent."""
        body = self._json_body(MAX_PLAN_APPROVE_BYTES)
        if body is None:
            return False
        try:
            plan_id = approve.parse_approve_request(body)
        except ValueError:
            self._refuse(400, "bad plan approval")
            return False
        try:
            console.approve_plan(plan_id)
        except sprints.Refused as error:
            print(f"console: plan_approve_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: plan_approve_failed {type(error).__name__}", file=sys.stderr)
            self._refuse(500, "approving failed")
            return False
        return True

    def _adoption_register_request(self, console: "ConsoleService") -> bool:
        """Carry out the registration retry write; True when the shared 204 is to be sent."""
        body = self._json_body(MAX_ADOPTION_REGISTER_BYTES)
        if body is None:
            return False
        try:
            plan_id = approve.parse_approve_request(body)
        except ValueError:
            self._refuse(400, "bad registration retry")
            return False
        try:
            console.retry_registration(plan_id)
        except sprints.Refused as error:
            print(f"console: adoption_register_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: adoption_register_failed {type(error).__name__}", file=sys.stderr)
            self._refuse(500, "registering failed")
            return False
        return True

    def _plan_defer_request(self, console: "ConsoleService") -> bool:
        """Carry out the Not now write; True when the shared 204 is to be sent."""
        body = self._json_body(MAX_PLAN_DEFER_BYTES)
        if body is None:
            return False
        try:
            plan_id = approve.parse_approve_request(body)
        except ValueError:
            self._refuse(400, "bad plan deferral")
            return False
        try:
            console.defer_plan(plan_id)
        except sprints.Refused as error:
            print(f"console: plan_defer_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: plan_defer_failed {type(error).__name__}: {error}", file=sys.stderr)
            traceback.print_exception(error, file=sys.stderr)
            self._refuse(500, "deferring failed")
            return False
        return True

    def _register_confirm_request(self, console: "ConsoleService") -> bool:
        """Carry out the Register card's answer; True when the shared 204 is to be sent."""
        body = self._json_body(MAX_REGISTER_CONFIRM_BYTES)
        if body is None:
            return False
        try:
            root, choice = register.parse_confirm_request(body)
        except ValueError:
            self._refuse(400, "bad registration approval")
            return False
        try:
            console.confirm_registration(root, choice)
        except sprints.Refused as error:
            print(f"console: register_confirm_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: register_confirm_failed {type(error).__name__}", file=sys.stderr)
            self._refuse(500, "registering failed")
            return False
        return True

    def _register_cancel_request(self, console: "ConsoleService") -> bool:
        """Carry out Cancel registration; True when the shared 204 is to be sent."""
        body = self._json_body(MAX_REGISTER_CANCEL_BYTES)
        if body is None:
            return False
        try:
            root = register.parse_cancel_request(body)
        except ValueError:
            self._refuse(400, "bad registration cancel")
            return False
        try:
            console.cancel_registration(root)
        except sprints.Refused as error:
            print(f"console: register_cancel_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: register_cancel_failed {type(error).__name__}", file=sys.stderr)
            self._refuse(500, "cancelling failed")
            return False
        return True

    def _trust_check_request(self, console: "ConsoleService") -> bool:
        """Carry out the Check again answer; True when the shared 204 is to be sent."""
        body = self._json_body(MAX_TRUST_CHECK_BYTES)
        if body is None:
            return False
        try:
            root, profile = folder_trust.parse_check_request(body)
        except ValueError:
            self._refuse(400, "bad trust check")
            return False
        try:
            console.check_trust(root, profile)
        except sprints.Refused as error:
            print(f"console: trust_check_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: trust_check_failed {type(error).__name__}", file=sys.stderr)
            self._refuse(500, "checking failed")
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
            sprint_id, secret, brief, dry_run = sprints.parse_brief_request(self.rfile.read(length))
        except ValueError:
            return self._refuse(400, "bad brief")
        try:
            if dry_run:
                console.check_brief(sprint_id, secret, brief)
            else:
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
        answer = {"checked": True} if dry_run else {"version": version}
        self._send(200, "application/json", json.dumps(answer, separators=(",", ":")).encode())

    def _report_request(self):
        """The manager's route: a report sent with the sprint's secret; no token, no page."""
        console = self.server.console
        length = self._checked_length(MAX_REPORT_BYTES)
        if length is None:
            return
        self.close_connection = True
        try:
            sprint_id, secret, report, dry_run = sprints.parse_report_request(
                self.rfile.read(length))
        except ValueError:
            return self._refuse(400, "bad report")
        try:
            if dry_run:
                console.check_report(sprint_id, secret, report)
            else:
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
        answer = {"checked": True} if dry_run else {"at": at}
        self._send(200, "application/json", json.dumps(answer, separators=(",", ":")).encode())

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
            sprint_id, secret, round_, dry_run = sprints.parse_ask_request(self.rfile.read(length))
        except ValueError:
            return self._refuse(400, "bad round")
        try:
            if dry_run:
                count = self.server.console.check_round(sprint_id, secret, round_)
            else:
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
        answer = {"questions": count} if dry_run else {"questions": count, "round": round_id}
        self._send(200, "application/json", json.dumps(
            answer, sort_keys=True, separators=(",", ":")).encode())

    def _withdraw_question_request(self):
        """The manager's route: one open question taken back, with the sprint's secret."""
        length = self._checked_length(MAX_WITHDRAW_QUESTION_BYTES)
        if length is None:
            return
        self.close_connection = True
        try:
            sprint_id, secret, round_id, index = sprints.parse_withdraw_question_request(
                self.rfile.read(length))
        except ValueError:
            return self._refuse(400, "bad withdraw question")
        try:
            self.server.console.withdraw_question(sprint_id, secret, round_id, index)
        except sprints.SecretRefused:
            print(f"console: withdraw_question_refused {sprint_id} {sprints.SECRET_REFUSED}",
                  file=sys.stderr)
            return self._refuse(403, sprints.SECRET_REFUSED)
        except sprints.Refused as error:
            print(f"console: withdraw_question_refused {sprint_id} {error}", file=sys.stderr)
            return self._refuse(409, str(error))
        except Exception as error:
            print(f"console: withdraw_question_failed {type(error).__name__}: {error}",
                  file=sys.stderr)
            return self._refuse(500, "withdraw question failed")
        self._send(200, "application/json", json.dumps(
            {"index": index, "round": round_id}, sort_keys=True, separators=(",", ":")).encode())

    def _notice_request(self):
        """The manager's route: one notice posted for its project, with the sprint's secret."""
        length = self._checked_length(MAX_NOTICE_BYTES)
        if length is None:
            return
        self.close_connection = True
        try:
            sprint_id, secret, notice = sprints.parse_notice_request(self.rfile.read(length))
        except ValueError:
            return self._refuse(400, "bad notice")
        try:
            notice_id = self.server.console.post_notice(sprint_id, secret, notice)
        except sprints.SecretRefused:
            print(f"console: notice_refused {sprint_id} {sprints.SECRET_REFUSED}", file=sys.stderr)
            return self._refuse(403, sprints.SECRET_REFUSED)
        except sprints.Refused as error:
            print(f"console: notice_refused {sprint_id} {error}", file=sys.stderr)
            return self._refuse(409, str(error))
        except Exception as error:
            print(f"console: notice_failed {type(error).__name__}: {error}", file=sys.stderr)
            return self._refuse(500, "notice failed")
        self._send(200, "application/json", json.dumps(
            {"notice": notice_id}, sort_keys=True, separators=(",", ":")).encode())

    def _notices_request(self):
        """The manager's route: the project's open notices, read with the sprint's secret."""
        length = self._checked_length(MAX_NOTICES_BYTES)
        if length is None:
            return
        self.close_connection = True
        try:
            sprint_id, secret = sprints.parse_inbox_request(self.rfile.read(length))
        except ValueError:
            return self._refuse(400, "bad notices")
        try:
            entries = self.server.console.list_notices(sprint_id, secret)
        except sprints.SecretRefused:
            print(f"console: notices_refused {sprint_id} {sprints.SECRET_REFUSED}", file=sys.stderr)
            return self._refuse(403, sprints.SECRET_REFUSED)
        except sprints.Refused as error:
            print(f"console: notices_refused {sprint_id} {error}", file=sys.stderr)
            return self._refuse(409, str(error))
        except Exception as error:
            print(f"console: notices_failed {type(error).__name__}: {error}", file=sys.stderr)
            return self._refuse(500, "notices failed")
        self._send(200, "application/json", json.dumps(
            {"notices": entries}, sort_keys=True, separators=(",", ":")).encode())

    def _withdraw_notice_request(self):
        """The manager's route: one open notice of the sprint taken back, with its secret."""
        length = self._checked_length(MAX_WITHDRAW_NOTICE_BYTES)
        if length is None:
            return
        self.close_connection = True
        try:
            sprint_id, secret, notice_id = sprints.parse_withdraw_notice_request(
                self.rfile.read(length))
        except ValueError:
            return self._refuse(400, "bad withdraw notice")
        try:
            self.server.console.withdraw_notice(sprint_id, secret, notice_id)
        except sprints.SecretRefused:
            print(f"console: withdraw_notice_refused {sprint_id} {sprints.SECRET_REFUSED}",
                  file=sys.stderr)
            return self._refuse(403, sprints.SECRET_REFUSED)
        except sprints.Refused as error:
            print(f"console: withdraw_notice_refused {sprint_id} {error}", file=sys.stderr)
            return self._refuse(409, str(error))
        except Exception as error:
            print(f"console: withdraw_notice_failed {type(error).__name__}: {error}",
                  file=sys.stderr)
            return self._refuse(500, "withdraw notice failed")
        self._send(200, "application/json", json.dumps(
            {"notice": notice_id}, sort_keys=True, separators=(",", ":")).encode())

    def _picture_request(self):
        """The manager's route: one PNG picture sent with the sprint's secret in headers."""
        length = self._checked_length(MAX_PICTURE_BYTES, media="image/png", wrong_media="png only")
        if length is None:
            return
        sprint_ids = self.headers.get_all(SPRINT_HEADER) or []
        secrets_sent = self.headers.get_all(SECRET_HEADER) or []
        if not (len(sprint_ids) == 1 and sprints.SPRINT_ID.fullmatch(sprint_ids[0])
                and len(secrets_sent) == 1 and secrets_sent[0]):
            return self._refuse(400, "bad picture")
        sprint_id, secret = sprint_ids[0], secrets_sent[0]
        self.close_connection = True
        data = self.rfile.read(length)
        if len(data) != length:
            return self._refuse(400, "bad picture")
        try:
            picture_id = self.server.console.store_picture(sprint_id, secret, data)
        except sprints.SecretRefused:
            print(f"console: picture_refused {sprint_id} {sprints.SECRET_REFUSED}", file=sys.stderr)
            return self._refuse(403, sprints.SECRET_REFUSED)
        except pictures.NotPng as error:
            print(f"console: picture_refused {sprint_id} {error}", file=sys.stderr)
            return self._refuse(400, str(error))
        except sprints.Refused as error:
            print(f"console: picture_refused {sprint_id} {error}", file=sys.stderr)
            return self._refuse(409, str(error))
        except Exception as error:
            print(f"console: picture_failed {type(error).__name__}: {error}", file=sys.stderr)
            return self._refuse(500, "picture failed")
        self._send(200, "application/json", json.dumps(
            {"picture": picture_id}, sort_keys=True, separators=(",", ":")).encode())

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

    def _share_request(self, console: "ConsoleService", route: str) -> bool:
        """Read and carry out one of the owner's access-list writes; False when it was refused."""
        body = self._json_body(MAX_SHARE_BYTES)
        if body is None:
            return False
        if route == SHARE_TAILNET_PATH:
            bad, parse, write = "bad tailnet", guest.parse_tailnet, console.set_tailnet
        elif route == SHARE_COLLEAGUE_PATH:
            bad, parse = "bad colleague", guest.parse_colleague
            write = lambda parsed: console.set_colleague(*parsed)
        else:
            bad, parse, write = "bad removal", guest.parse_removal, console.remove_colleague
        try:
            action = parse(body)
        except ValueError:
            self._refuse(400, bad)
            return False
        try:
            write(action)
        except guest.Refused as error:
            print(f"console: share_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: share_failed {type(error).__name__}: {error}", file=sys.stderr)
            self._refuse(500, "share failed")
            return False
        return True

    def _owner_notice_request(self, console: "ConsoleService") -> bool:
        """Read and carry out the owner's heads-up for a project; False when it was refused."""
        body = self._json_body(MAX_OWNER_NOTICE_BYTES)
        if body is None:
            return False
        try:
            project_id, text = sprints.parse_owner_notice(body)
        except ValueError:
            self._refuse(400, "bad owner notice")
            return False
        try:
            console.post_owner_notice(project_id, text)
        except sprints.Refused as error:
            print(f"console: owner_notice_refused {project_id} {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: owner_notice_failed {type(error).__name__}: {error}",
                  file=sys.stderr)
            self._refuse(500, "owner notice failed")
            return False
        return True

    def _activate_request(self, console: "ConsoleService") -> bool:
        """Read and carry out the owner's Activate for the shown commit; False when it was refused."""
        body = self._json_body(MAX_ACTIVATE_BYTES)
        if body is None:
            return False
        try:
            commit = activation_run.parse_request(body)
        except ValueError:
            self._refuse(400, "bad activation")
            return False
        try:
            console.activate(commit)
        except sprints.Refused as error:
            print(f"console: activate_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: activate_failed {type(error).__name__}: {error}", file=sys.stderr)
            self._refuse(500, "activation failed")
            return False
        return True

    def _owner_notice_withdraw_request(self, console: "ConsoleService") -> bool:
        """Read and carry out the owner's withdrawal of a heads-up; False when it was refused."""
        body = self._json_body(MAX_OWNER_NOTICE_WITHDRAW_BYTES)
        if body is None:
            return False
        try:
            project_id, notice_id = sprints.parse_owner_notice_withdrawal(body)
        except ValueError:
            self._refuse(400, "bad owner notice withdrawal")
            return False
        try:
            console.withdraw_owner_notice(project_id, notice_id)
        except sprints.Refused as error:
            print(f"console: owner_notice_withdraw_refused {project_id} {error}",
                  file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: owner_notice_withdraw_failed {type(error).__name__}: {error}",
                  file=sys.stderr)
            self._refuse(500, "owner notice withdrawal failed")
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

    def _pin_request(self, console: "ConsoleService") -> bool:
        """Read and carry out the owner's pin or unpin of a profile; False when refused."""
        body = self._json_body(MAX_PIN_BYTES)
        if body is None:
            return False
        try:
            profile, pinned = pin.parse_request(body)
        except ValueError:
            self._refuse(400, "bad pin")
            return False
        try:
            console.set_pin(profile, pinned)
        except pin.Refused as error:
            print(f"console: pin_refused {error}", file=sys.stderr)
            self._refuse(409, str(error))
            return False
        except Exception as error:
            print(f"console: pin_failed {type(error).__name__}: {error}", file=sys.stderr)
            self._refuse(500, "pin failed")
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
        elif route == PROJECT_QUESTION_PATH:
            self.close_connection = True
            if not self._project_question_request(console):
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
        elif route == PIN_PATH:
            self.close_connection = True
            if not self._pin_request(console):
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
        elif route in (SIGNIN_PATH, SIGNIN_CODE_PATH, SIGNIN_CANCEL_PATH, SIGNIN_LINK_PATH):
            self.close_connection = True
            if not self._signin_request(console, route):
                return
        elif route == ACCOUNT_ADD_PATH:
            self.close_connection = True
            if not self._account_request(console):
                return
        elif route == ACCOUNT_REMOVE_PATH:
            self.close_connection = True
            if not self._removal_request(console):
                return
        elif route == REGISTER_PATH:
            self.close_connection = True
            if not self._register_request(console):
                return
        elif route == PLAN_ANSWER_PATH:
            self.close_connection = True
            if not self._plan_answer_request(console):
                return
        elif route == PLAN_APPROVE_PATH:
            self.close_connection = True
            if not self._plan_approve_request(console):
                return
        elif route == ADOPTION_REGISTER_PATH:
            self.close_connection = True
            if not self._adoption_register_request(console):
                return
        elif route == PLAN_DEFER_PATH:
            self.close_connection = True
            if not self._plan_defer_request(console):
                return
        elif route == REGISTER_CONFIRM_PATH:
            self.close_connection = True
            if not self._register_confirm_request(console):
                return
        elif route == TRUST_CHECK_PATH:
            self.close_connection = True
            if not self._trust_check_request(console):
                return
        elif route == REGISTER_CANCEL_PATH:
            self.close_connection = True
            if not self._register_cancel_request(console):
                return
        elif route == OWNER_NOTICE_PATH:
            self.close_connection = True
            if not self._owner_notice_request(console):
                return
        elif route == OWNER_NOTICE_WITHDRAW_PATH:
            self.close_connection = True
            if not self._owner_notice_withdraw_request(console):
                return
        elif route == ACTIVATE_PATH:
            self.close_connection = True
            if not self._activate_request(console):
                return
        elif route in (SHARE_TAILNET_PATH, SHARE_COLLEAGUE_PATH, SHARE_REMOVE_PATH):
            self.close_connection = True
            if not self._share_request(console, route):
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
        if route == PAGE_PATH:
            self._send(200, "text/html; charset=utf-8", self.server.console.page_bytes,
                       ("Content-Security-Policy", CSP))
        elif route == SPEND_PAGE_PATH:
            self._send(200, "text/html; charset=utf-8", SPEND_PAGE,
                       ("Content-Security-Policy", CSP))
        elif route == STATE_PATH:
            self._send(200, "application/json", self.server.console.view_bytes)
        elif route == STREAM_PATH:
            console = self.server.console
            self._stream(lambda seen: console.wait_for_change(seen, KEEPALIVE_SECONDS),
                         console.delivered)
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
        elif route.startswith(PICTURE_PREFIX):
            self._picture_read(route)
        elif route in POST_LIMITS or route in PAGE_WRITES or route in MANAGER_WRITES:
            self._refuse_method()
        else:
            self._send(404, "text/plain", b"not found\n")

    def _picture_read(self, route: str):
        console = self.server.console
        refusal = write_guard.read_refusal(
            self.headers["Host"], self.headers.get_all("Origin") or [],
            self.headers.get_all(write_guard.FETCH_SITE_HEADER) or [],
            self.headers.get_all(write_guard.TOKEN_HEADER) or [], console.page_token)
        if refusal is not None:
            return self._refuse(*refusal)
        picture_id = route[len(PICTURE_PREFIX):]
        if "?" in self.path or not pictures.PICTURE_ID.fullmatch(picture_id):
            return self._refuse(400, "bad picture id")
        self._send_picture(picture_id)

    def _send_picture(self, picture_id: str):
        try:
            data = pictures.read(self.server.console.pictures_dir, picture_id)
        except OSError:
            data = None
        if data is None:
            return self._refuse(404, "this picture is not known")
        self._send(200, "image/png", data, cache="private")

    def _stream(self, wait: Callable[[int], tuple[int, bytes | None] | None],
                delivered: Callable[[int], None] | None = None):
        """Write views as they publish; `delivered` hears each version once written.

        Only the owner's stream passes it: a guest view never carries the evidence card, so a frame
        written to a colleague shows the owner nothing (ADR-console-071 D4).
        """
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
                change = wait(seen)
                if change is None:
                    if console.closing:
                        return
                    self.wfile.write(b": keepalive\n\n")
                    continue
                seen, view = change
                if view is None:
                    return
                self.wfile.write(b"event: view\ndata: " + view + b"\n\n")
                if delivered is not None:
                    delivered(seen)
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

    def __getattr__(self, name: str):
        """Any other method (TRACE, CONNECT, an unknown one) is refused like the listed ones, never 501."""
        if name.startswith("do_"):
            return self._refuse_method
        raise AttributeError(name)


class GuestHandler(ConsoleHandler):
    """The guest port's one handler (#1237); it never calls the owner's route methods."""

    def _send(self, status: int, content_type: str, body: bytes, *headers: tuple[str, str],
              cache: str = "no-store"):
        self.close_connection = True
        if not any(name.lower() == "connection" for name, _ in headers):
            headers = (*headers, ("Connection", "close"))
        super()._send(status, content_type, body, *headers, cache=cache)

    def _guest_request(self):
        console = self.server.console
        route = self.path.split("?", 1)[0]
        hosts = self.headers.get_all("Host") or []
        logins = self.headers.get_all(guest.LOGIN_HEADER) or []
        if self.command == "GET" and route == WHOAMI_PATH:
            body = json.dumps(
                guest.whoami(hosts, logins, self.headers.get_all("X-Forwarded-For") or [],
                             self.headers.get_all(guest.PROBE_HEADER) or []),
                sort_keys=True, separators=(",", ":"))
            return self._send(200, "application/json", body.encode())
        access = console.access
        login, text = guest.admit(access, hosts, logins)
        if text is not None:
            return self._refuse(403, text)
        if route in OWNER_ONLY:
            return self._refuse(403, guest.OWNER_ONLY_TEXT)
        if self.command != "GET":
            if route in GUEST_READS or route.startswith(PICTURE_PREFIX):
                return self._send(405, "text/plain", b"method not allowed\n", ("Allow", "GET"))
            return self._refuse(404, "not found")
        if route == PAGE_PATH:
            self._send(200, "text/html; charset=utf-8", console.guest_page_bytes,
                       ("Content-Security-Policy", CSP))
        elif route == STATE_PATH:
            view = console.guest_view_bytes(login)
            if view is None:
                return self._refuse(403, guest.NOT_SHARED_TEXT)
            self._send(200, "application/json", view)
        elif route == STREAM_PATH:
            self._stream(self._readmitting(login, hosts, logins))
        elif route.startswith(PICTURE_PREFIX):
            self._guest_picture(route, access, login)
        else:
            self._refuse(404, "not found")

    def _readmitting(self, login: str, hosts: list[str], logins: list[str]):
        console = self.server.console
        last: list[bytes | None] = [None]

        def wait(seen: int):
            deadline = time.monotonic() + KEEPALIVE_SECONDS
            while True:
                remaining = deadline - time.monotonic()
                change = None if remaining <= 0 else console.wait_for_guest_change(
                    login, seen, remaining)
                if change is None:
                    return None
                version, access, view = change
                if guest.admit(access, hosts, logins) != (login, None) or view is None:
                    return version, None
                if view == last[0]:
                    seen = version
                    continue
                last[0] = view
                return version, view

        return wait

    def _guest_picture(self, route: str, access: "guest.Access", login: str):
        console = self.server.console
        refusal = write_guard.read_refusal(
            access.tailnet, self.headers.get_all("Origin") or [],
            self.headers.get_all(write_guard.FETCH_SITE_HEADER) or [],
            self.headers.get_all(write_guard.TOKEN_HEADER) or [], console.guest_token,
            scheme="https")
        if refusal is not None:
            return self._refuse(*refusal)
        picture_id = route[len(PICTURE_PREFIX):]
        if "?" in self.path or not pictures.PICTURE_ID.fullmatch(picture_id):
            return self._refuse(400, "bad picture id")
        if picture_id not in console.guest_pictures(login):
            return self._refuse(404, "this picture is not known")
        self._send_picture(picture_id)

    def parse_request(self) -> bool:
        """Read every request the guest port parses, whatever its method, for the owner's state."""
        ok = super().parse_request()
        if ok:
            headers = self.headers
            console = self.server.console
            console.record_guest_request(guest.reading(
                console.access, headers.get_all("Host") or [],
                headers.get_all(guest.LOGIN_HEADER) or [],
                headers.get_all("X-Forwarded-For") or [],
                headers.get_all(guest.PROBE_HEADER) or []))
        return ok

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _guest_request

    def __getattr__(self, name: str):
        """Any other method takes the same admission and owner-only refusals, never the 501."""
        if name.startswith("do_"):
            return self._guest_request
        raise AttributeError(name)


class GuestPortError(OSError):
    """The guest port could not be bound; `port` is the one that failed."""

    def __init__(self, port: int, error: OSError):
        super().__init__(error.errno, error.strerror)
        self.port = port


class ConsoleServer(socketserver.ThreadingTCPServer):
    # Not http.server.HTTPServer, whose server_bind does a reverse lookup.
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = BACKLOG

    def __init__(self, port: int, console: "ConsoleService", handler=ConsoleHandler):
        self.console = console
        super().__init__((HOST, port), handler)


class _ProfileRemoving(Exception):
    """A client run under a profile was refused because the profile is being removed (#1030)."""


class _RetryReservation:
    """A launch reservation made by a retry: it runs only while the sprint still offers retry."""


class _TakeoverReservation:
    """A launch reservation made by the bring-back: it runs only while the takeover is still decided."""


def _retry_line(project_id: str, key: str) -> Callable[[int, ForgeError], None]:
    def on_retry(attempt: int, error: ForgeError) -> None:
        print(f"console: answer_tick_retry {project_id} {key} {attempt} {error.code}: "
              f"{' '.join(error.detail.split())}", file=sys.stderr)
    return on_retry


class ConsoleService:
    def __init__(self, store: Path, registry: Path, *, port: int = DEFAULT_PORT,
                 poll_seconds: float = POLL_SECONDS,
                 session_dirs: Callable[[], Iterable[Path]] = default_session_dirs,
                 profile_dirs: Callable[[], Iterable[Path]] = default_profile_dirs,
                 session_poll_seconds: float = SESSION_POLL_SECONDS,
                 repo_of: Callable[[str], str | None] = sessions.main_checkout,
                 tracker: Callable[..., list[dict]] | None = None,
                 tracker_seconds: float = TRACKER_SECONDS,
                 adoption_seconds: float = ADOPTION_SECONDS,
                 pull_reader: Callable[..., tuple[movement.PullRequest, ...]] | None = None,
                 local_reader: Callable[[str, str | None], movement.LocalReading] = movement.read_local,
                 session_reader: Callable[[Sequence[Path], Sequence[movement.SessionTarget]],
                                          tuple[movement.SessionReading, ...]] = movement.read_sessions,
                 movement_seconds: float = MOVEMENT_SECONDS,
                 activation_reader: Callable[[Iterable[str]], activation.Activation | None] | None = None,
                 activation_seconds: float = ACTIVATION_SECONDS,
                 activator: activation_run.Activator | None = None,
                 slug_of: Callable[[str], str | None] = owner_actions.checkout_slug,
                 branch_pattern_of: Callable[[str], str | None] = deliveries.configured_branch_pattern,
                 activity: Callable[[str], float | None] = inbox.local_activity,
                 clock: Callable[[], float] = time.time,
                 retention_seconds: float = RETENTION_SECONDS,
                 digest_seconds: float = DIGEST_SECONDS,
                 spend_seconds: float = SPEND_SECONDS,
                 ping_log: Callable[[], Path | None] = spend.default_ping_log,
                 log_clock: Callable[[], str] = utc_now,
                 token_path: Path | None = None,
                 sprint_secrets: Path | None = None,
                 tick: Callable[[str, int, int, list[dict], list[int]], None] = answer.tick_on_tracker,
                 owner_path: Callable[..., None] = verify_answer.answer_prompt,
                 criterion_path: Callable[..., None] = answer.answer_criterion,
                 write_sleep: Callable[[float], object] | None = None,
                 monotonic: Callable[[], float] = time.monotonic,
                 launcher: Callable[[manager.Launch], None] | None = None,
                 dispatch: Callable[[Callable[[], None]], None] | None = None,
                 nudger: Callable[[nudge.Nudge], None] | None = None,
                 listing: Callable[[], Mapping[str, sessions.Observation]] | None = None,
                 stopper: Callable[[str, str], None] | None = None,
                 full_listing: Callable[[str, str], Collection[str]] | None = None,
                 permission_reader: Callable[[str, str], permission.Permission] = permission.read,
                 prober: Callable[[probe.Probe], None] | None = None,
                 signin_reader: Callable[[probe.Probe], signin.Status] | None = None,
                 signin_runs: Callable[..., signin_run.SignIns] | None = None,
                 account_adder: Callable[[str], None] | None = None,
                 signer_out: Callable[[probe.Probe], None] | None = None,
                 account_remover: Callable[[str], None] | None = None,
                 adopter=None,
                 draft_reader: Callable[[str], dict] = contract_draft.read,
                 checkout_reader: Callable[..., checkout_remote.Comparison] = checkout_remote.compare,
                 checkout_updater: Callable[..., checkout_remote.Updated] = checkout_remote.update,
                 forge=None,
                 pusher: Callable[..., None] = approve.push,
                 trust_home: Path | None = None,
                 trust_granter: Callable[[Path, str], str] = folder_trust.grant,
                 trust_at_start: bool = False,
                 approval_dispatch: Callable[[Callable[[], None]], None] | None = None,
                 probe_dispatch: Callable[[Callable[[], None]], None] | None = None,
                 project_asker: Callable[[project_question.Ask, threading.Event | None],
                                         project_question.Outcome] | None = None,
                 project_reach: Callable[[str], project_question.Reach] = project_question.reach_of,
                 project_question_dispatch: Callable[[Callable[[], None]], None] | None = None,
                 probe_tick_seconds: float = PROBE_TICK_SECONDS,
                 choice_file: Path | None = None,
                 screenshot_dirs: Iterable[Path] = (),
                 guest_port: int | None = None,
                 guest_token_path: Path | None = None,
                 serve_reader: Callable[[], object | None] | None = None,
                 serve_seconds: float = SERVE_SECONDS):
        self.registry = Path(registry)
        self._screenshot_dirs = tuple(Path(d) for d in screenshot_dirs)
        self._choice_file = choice_file
        self._choice = manager.read_choice(choice_file) if choice_file is not None else None
        self._prober = prober
        self._signin_reader = signin_reader
        self._account_adder = account_adder
        self._signer_out = signer_out
        self._account_remover = account_remover
        self._adopter = adopter
        self._draft_reader = draft_reader
        self._checkout_reader = checkout_reader
        self._checkout_updater = checkout_updater
        self._forge = forge
        self._pusher = pusher
        self._trust_home = None if trust_home is None else Path(trust_home)
        self._trust_granter = trust_granter
        self._trust_at_start = trust_at_start
        self._trust_start_thread: threading.Thread | None = None
        self._grants_running = 0
        self._cancelled: dict[str, int] = {}
        self._approving = False
        self._enrolling: set[str] = set()
        self._approval_workers: list[threading.Thread] = []
        self._approval_dispatch = (
            self._on_approval_thread if approval_dispatch is None else approval_dispatch)
        self._adoptions: dict[str, dict] = {}
        self._deferred: frozenset[str] = frozenset()
        self._registering: str | None = None
        self._answering = False
        self._answer_refusal: dict | None = None
        self._adding = threading.Lock()
        self._removing: set[str] = set()
        self._client_live: collections.Counter[str] = collections.Counter()  # client runs under a profile in flight
        self._probe_dispatch = self._on_probe_thread if probe_dispatch is None else probe_dispatch
        self._probe_tick_seconds = probe_tick_seconds
        self._probe_since = clock()
        self._probing: set[str] = set()
        self._probe_started: dict[str, float] = {}
        self._probe_sessions: OrderedDict[str, str] = OrderedDict()
        self._probe_live: dict[str, str] = {}
        self._probe_workers: list[threading.Thread] = []
        self._project_asker = project_asker
        self._project_reach = project_reach
        self._project_question_dispatch = (
            self._on_project_question_thread if project_question_dispatch is None
            else project_question_dispatch)
        self._project_questions_open = 0  # accepted questions whose answered row is not yet written
        self._project_question_workers: list[threading.Thread] = []
        self._probe_thread: threading.Thread | None = None
        self._nudger = nudger
        self._full_listing = full_listing
        self._permission_reader = permission_reader
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
        self._notice_due: dict[str, int] = {}
        self._launcher = launcher
        self._dispatch = self._on_new_thread if dispatch is None else dispatch
        self._launching: dict[str, object] = {}
        self._last_listed: dict[str, int] = {}
        self._tick = tick
        self._store = store
        self._owner_path = owner_path
        self._criterion_path = criterion_path
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
        self._pinned: str | None = None
        self._signin_ends: dict[str, signin_run.Ended] = {}
        self._accounts_added: frozenset[str] = frozenset()
        self._trust_failures: dict[tuple[str, str], dict] = {}
        self._pin_launches: pin.PinLaunches = pin.pin_launches([])
        self._signin_live: dict[str, int] = {}
        self._signin_by_run: dict[int, tuple[str, int]] = {}
        self._signin_tickets: dict[str, int] = {}
        self._signin_recorded: dict[str, int] = {}
        self._signin_thread: threading.Thread | None = None
        self._session_poll_seconds = session_poll_seconds
        self._repo_of = repo_of
        self._sessions: dict[str, sessions.SessionState] = {}
        self._use = manager.ProfileUse({}, {})
        self._spend = spend.SpendReader(repo_of=repo_of)
        self._spend_view: dict | None = None
        self._spend_profiles: dict[str, str] = {}
        self._spend_questions: dict[str, str] = {}
        self._absent: frozenset[str] = frozenset()
        self._deliveries: dict[tuple[str, str], deliveries.DeliveryState] = {}
        self._reader = deliveries.JournalReader()
        self._runs: dict[Path, deliveries.RunFold] = {}
        self._run_moves: dict[tuple[str, str], int] = {}
        self._unreadable: set[str] = set()
        self._session_poller: threading.Thread | None = None
        self._tracker = tracker
        self._tracker_seconds = tracker_seconds
        self._adoption_seconds = adoption_seconds
        self._adoption_thread: threading.Thread | None = None
        self._pull_reader = pull_reader
        self._local_reader = local_reader
        self._session_reader = session_reader
        self._movement_seconds = movement_seconds
        self._movement: dict[str, movement.ProjectMovement] = {}
        self._movement_thread: threading.Thread | None = None
        self._activation_reader = activation_reader
        self._activation_seconds = activation_seconds
        self._activation: activation.Activation | None = None
        self._activation_polls = 0  # readings begun; a reading is dated by the count when it began
        self._activation_applied = 0  # the date of the reading kept
        self._activation_after: int | None = None  # a successful run's end: only a later reading shows
        self._activation_thread: threading.Thread | None = None
        self._activator = activator
        self._activation_run: activation_run.LastRun | None = None
        self._activating = False
        self._activate_thread: threading.Thread | None = None
        self._slug_of = slug_of
        self._branch_pattern_of = branch_pattern_of
        self._patterns: dict[str, str] = {}
        self._activity = activity
        self._clock = clock
        self._revive_since_ms = int(clock() * 1000)
        self._retention_seconds = retention_seconds
        self._digest_seconds = digest_seconds
        self._spend_seconds = spend_seconds
        self._serve_reader = serve_reader
        self._serve_seconds = serve_seconds
        self._serve_status: object | None = None
        self._guest_reading: dict | None = None
        self._serve_thread: threading.Thread | None = None
        self._ping_log = ping_log
        self._retention_thread: threading.Thread | None = None
        self._digest_thread: threading.Thread | None = None
        self._spend_thread: threading.Thread | None = None
        self._looked: str | None = None
        self._moments: list[digest.Moment] = []
        self._tracker_thread: threading.Thread | None = None
        self._closing = False
        self._stop = threading.Event()
        self._write_sleep = self._stop.wait if write_sleep is None else write_sleep
        self._monotonic = monotonic
        self._watcher: threading.Thread | None = None
        self._signature = None
        self.log: EventLog | None = None
        self._ingest = threading.Lock()
        # Keeps a sweep from deleting a picture an attach is storing; taken after `_ingest`, never before it.
        self._storing = threading.Lock()
        self._idle = threading.Condition(self._ingest)
        self._grants_done = threading.Condition(self._ingest)
        self._project_questions_done = threading.Condition(self._ingest)
        self._signin_runs = None if signin_runs is None else signin_runs(on_end=self._signin_ended)
        self._published = threading.Condition()
        self._view = b""
        self._version = 0
        self._delivered = -1
        # The key of the failed commit's evidence card in the view and the first version that carried it.
        self._evidence_card: tuple[str, int] | None = None
        self._thread: threading.Thread | None = None
        self._closed = False
        self._access = guest.NO_ACCESS
        self._published_access = guest.NO_ACCESS
        self._guest_views: dict[str, bytes] = {}
        self._guest_pictures: dict[str, frozenset[str]] = {}
        self._guest_token: str | None = None
        self._guest_page: bytes | None = None
        self._guest_server: ConsoleServer | None = None
        self._guest_thread: threading.Thread | None = None
        self._guest_port_number: int | None = None
        self._server = ConsoleServer(port, self)
        try:
            if guest_port is not None:
                try:
                    self._guest_server = ConsoleServer(guest_port, self, GuestHandler)
                except OSError as error:
                    raise GuestPortError(guest_port, error) from error
                self._guest_port_number = self._guest_server.server_address[1]
            self._token = write_guard.load_token(
                Path(store).with_name(write_guard.TOKEN_FILE) if token_path is None
                else token_path)
            self._page = PAGE.replace(write_guard.TOKEN_SLOT, self._token.encode("ascii"))
            if self._guest_server is not None:
                self._guest_token = write_guard.load_token(
                    Path(store).with_name(write_guard.GUEST_TOKEN_FILE)
                    if guest_token_path is None else guest_token_path)
                self._guest_page = PAGE.replace(
                    write_guard.TOKEN_SLOT, self._guest_token.encode("ascii"))
            self.log = EventLog(store, clock=log_clock)
            self.log.retain()
            events = self.log.events()
            self._sweep_pictures(events)
            self._states = project_states(events)
            self._sessions = sessions.session_states(events)
            self._use = manager.profile_use(events)
            self._spend_profiles = spend.session_profiles(events)
            self._spend_questions = spend.question_sessions(events)
            self._inbox = inbox_records(events)
            self._health = read_states(events)
            self._capacity = capacity.capacity_state(events)
            self._signins = signin.signin_state(events)
            self._excluded = exclusion.excluded_profiles(events)
            self._pinned = pin.pinned_profile(events)
            self._signin_ends = signin_run.ended_state(events)
            self._accounts_added = account_add.added_state(events)
            self._trust_failures = folder_trust.failures(events)
            self._registration = register.latest(events)
            self._adoptions = approve.adoptions(events)
            self._deferred = approve.deferrals(events)
            self._pin_launches = pin.pin_launches(events)
            self._derive_digest(events)
            self._deliveries = deliveries.delivery_states(events)
            self._moved = idle.last_moved(events)
            self._sprints = sprints.sprint_states(events)
            self._withdrawn = sprints.withdrawn_ids(events)
            self._owner_notices = sprints.owner_notices(events)
            self._project_questions = project_question.asked_questions(events)
            self._activation_run = activation_run.fold(events)
            self._pending = sprints.pending_stops(events)
            self._access = guest.access_list(events)
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
            if self._guest_server is not None:
                self._guest_server.server_close()
            raise

    @property
    def pictures_dir(self) -> Path:
        """The directory of the pictures managers sent, beside the event log."""
        return Path(self._store).with_name(pictures.DIRECTORY)

    @property
    def address(self) -> tuple[str, int]:
        return self._server.server_address[:2]

    @property
    def guest_address(self) -> tuple[str, int] | None:
        return None if self._guest_server is None else self._guest_server.server_address[:2]

    @property
    def guest_token(self) -> str | None:
        return self._guest_token

    @property
    def access(self) -> "guest.Access":
        return self._access

    @property
    def guest_page_bytes(self) -> bytes | None:
        return self._guest_page

    def guest_view_bytes(self, login: str) -> bytes | None:
        """The login's guest view; None when the login is not listed or sharing is off."""
        with self._published:
            return self._guest_views.get(login)

    def guest_pictures(self, login: str) -> frozenset[str]:
        """The pictures on the login's guest view."""
        with self._published:
            return self._guest_pictures.get(login, frozenset())

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

    def wait_for_guest_change(self, login: str, seen: int, timeout: float
                              ) -> tuple[int, "guest.Access", bytes | None] | None:
        """Like `wait_for_change`, with the access list and the login's view of that publish."""
        with self._published:
            self._published.wait_for(lambda: self._version > seen or self._closing, timeout)
            if self._closing or self._version <= seen:
                return None
            return self._version, self._published_access, self._guest_views.get(login)

    def delivered(self, version: int) -> None:
        """Record that the view of `version` was written to a page stream (ADR-console-071)."""
        with self._published:
            self._delivered = max(self._delivered, version)

    def _now(self) -> datetime:
        return datetime.fromtimestamp(self._clock(), timezone.utc)

    def _derive_digest(self, events: list[Event]) -> None:
        """Derive the last look and the moments from the whole log (construction and retention)."""
        self._looked = digest.last_looked(events)
        self._moments = digest.keep(digest.moments(events, {}, {}),
                                    digest.window_start(self._looked, self._now()))

    def _signin_view(self) -> dict[str, dict]:
        runs = {profile: {"state": end.outcome, "at": end.at, "attempt": end.attempt}
                for profile, end in self._signin_ends.items() if profile in self._profiles}
        for profile, attempt in self._signin_live.items():
            if profile in self._profiles:
                runs[profile] = {"state": "running", "at": None, "attempt": attempt}
        return runs

    def _approval_view(self) -> tuple[dict | None, str | None, list[dict]]:
        latest = self._registration
        if latest is None:
            return None, None, []
        plan_id = latest["plan_id"]
        found = self._adoptions.get(plan_id) if plan_id else None
        entry = approve.entry(found, running=self._approving, name=register.name_of(latest["root"]),
                              registering=bool(plan_id) and plan_id in self._enrolling)
        action = approve.action(
            latest, found, available=self._adopter is not None and self._forge is not None,
            running=self._registering is not None)
        return entry, action, approve.apply_items(
            latest, found, entry, action, deferred=self._deferred)

    def record_guest_request(self, reading: Mapping) -> None:
        """Keep the latest guest-port request's reading for the owner; see the module docstring."""
        with self._ingest:
            if reading == self._guest_reading:
                return
            self._guest_reading = dict(reading)
            self._publish(guests=False)

    def _publish(self, *, guests: bool = True) -> None:
        """Derive and publish the views; `guests=False` publishes the owner's view alone.

        A guest view is derived from the clock (a sprint's age text), so recomputing it for a
        guest-port reading would change a guest's bytes: the cached guest views are kept.
        """
        adoption, action, apply_items = self._approval_view()
        latest = self._registration
        cancel = (self._registering is None and latest is not None
                  and register.cancellable(latest, self._adoptions.get(latest["plan_id"])))
        cap = capacity.capacity_view(
            self._profiles, self._capacity, self._clock(), self._signins,
            excluded=self._excluded, pinned=self._pinned)
        inputs = dict(
            states=list(self._states.values()), records=self._inbox, health=self._health,
            sessions=list(self._sessions.values()), deliveries=self._deliveries,
            now_ms=int(self._clock() * 1000), sprints=self._sprints,
            owner_notices=self._owner_notices,
            project_questions=self._project_questions,
            digest=digest.digest(self._moments, self._looked, self._now()),
            spend=self._spend_view,
            capacity=cap, activation=self._shown_activation(),
            activation_run=self._activation_run,
            signin_runs=self._signin_view(), accounts_added=self._accounts_added,
            registration=register.view_entry(
                None if self._approving else self._registering, self._registration,
                again=self._answering, refusal=self._answer_refusal, adoption=adoption,
                approve=action, cancel=cancel),
            adoption_items=approve.inbox_entries(self._adoptions),
            retry_items=approve.retry_entries(self._adoptions, self._enrolling),
            apply_items=apply_items,
            trust_items=folder_trust.items(self._trust_failures),
            confirm_items=register.confirm_items(
                self._registration, running=self._registering is not None),
            failure_items=register.failure_items(
                self._registration, running=self._registering is not None),
            pin=pin.note(self._pinned, cap, manager.session_profile(cap, self._use.last)),
            pin_launches=self._pin_launches.launched,
            managers=self._launcher is not None, pending=self._pending,
            nudges=self._nudger is not None, looked=self._looked, movement=self._movement)
        access = self._access
        view = encode_view(derive_view(**inputs, sharing=guest.sharing_entry(
            access, guest.serve_state(self._serve_status, access.tailnet, self._guest_port_number),
            self._guest_reading)))
        found = self._adoptions.get(latest["plan_id"]) if latest is not None else None
        evidence_key = None
        if found is not None and found["step"] == "apply_failed" and found.get("evidence") is not None:
            evidence_key = next((item["key"] for item in apply_items), None)
        if not guests:
            with self._published:
                if view != self._view:
                    self._version += 1
                self._view = view
                self._track_evidence_card(evidence_key)
                self._published.notify_all()
            return
        views: dict[str, bytes] = {}
        seen_pictures: dict[str, frozenset[str]] = {}
        if self._guest_server is not None and access.tailnet is not None:
            for login, projects in access.colleagues.items():
                derived = guest.scrub(derive_view(**guest.scoped(inputs, projects)))
                views[login] = encode_view(derived)
                seen_pictures[login] = guest.picture_ids(derived)
        with self._published:
            if view != self._view or views != self._guest_views:
                self._version += 1
            self._view = view
            self._published_access = access
            self._guest_views = views
            self._guest_pictures = seen_pictures
            self._track_evidence_card(evidence_key)
            self._published.notify_all()

    def _track_evidence_card(self, evidence_key: str | None) -> None:
        """Remember the version at which the evidence card appeared (call under `_published`)."""
        if evidence_key is None:
            self._evidence_card = None
        elif self._evidence_card is None or self._evidence_card[0] != evidence_key:
            self._evidence_card = (evidence_key, self._version)

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

    def defer_plan(self, plan_id: str) -> None:
        """Record `Not now` for the shown plan's apply card; see the module docstring."""
        with self._ingest:
            latest = self._registration
            if latest is None or latest["plan_id"] != plan_id:
                raise sprints.Refused(approve.DEFER_STALE)
            if not self._approval_view()[2]:
                raise sprints.Refused(approve.NOT_OFFERED)
            self._apply(self.log.append([approve.deferral_row(plan_id)]))

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
            answer.with_retries(
                lambda: self._tick(item["repo"], item["issue"], item["comment_id"], questions, choices),
                clock=self._monotonic, sleep=self._write_sleep, on_retry=_retry_line(project_id, key))
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
            def write():
                if item.get("kind") == inbox.REVIEW_KIND:
                    self._criterion_path(item["repo"], item["issue"], item["criterion"], answer_word,
                                         version=version, note=note)
                    return
                self._owner_path(item["repo"], item["issue"], item["comment_id"], answer_word,
                                 version=version, note=note, paid=bool(item.get("paid")))

            if answer_word == "note":
                write()
            else:
                answer.with_retries(write, clock=self._monotonic, sleep=self._write_sleep,
                                    on_retry=_retry_line(project_id, key))
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

    def _on_approval_thread(self, job: Callable[[], None]) -> None:
        worker = threading.Thread(target=job, name=APPROVAL_THREAD, daemon=True)
        with self._ingest:
            self._approval_workers = [w for w in self._approval_workers if w.is_alive()]
            self._approval_workers.append(worker)
        worker.start()

    def _on_project_question_thread(self, job: Callable[[], None]) -> None:
        """Run a question's job on a tracked daemon thread; `close` joins every one it started."""
        worker = threading.Thread(target=job, name=PROJECT_QUESTION_THREAD, daemon=True)
        with self._ingest:
            # Started inside the lock and listed only once started: the list never holds an
            # unstarted thread, which `close` could not join (and a failed start lists nothing).
            self._project_question_workers = [
                w for w in self._project_question_workers if w.is_alive()]
            worker.start()
            self._project_question_workers.append(worker)

    def ask_project_question(self, project_id: str, text: str,
                             thread_id: str | None = None) -> str:
        """Accept one question about a registered project and return its id (#1176, ADR-console-058).

        Admission, the asked row and the open count are one section under the ingest lock; the
        session runs on a job handed to `project_question_dispatch` outside it. A `thread_id`
        makes it a follow-up (#1178, ADR-console-062): it is checked against the project's folded
        questions after the question's own checks and before the profile choice, and its thread's
        turns go to the job. Refusals are `project_question.Refused` and append and count nothing.
        """
        with self._ingest:
            if self._project_asker is None:
                raise project_question.Refused(project_question.UNAVAILABLE_TEXT)
            if self._stop.is_set():
                raise project_question.Refused(project_question.STOPPING)
            if project_id not in self._states:
                raise project_question.Refused(project_question.UNREGISTERED)
            text = project_question.checked_question(text)
            thread = () if thread_id is None else project_question.follow_up(
                self._project_questions.get(project_id, ()), thread_id, text)
            profile = self._session_choice(self._read_profiles())
            if profile is None:
                raise project_question.Refused(project_question.NO_PROFILE)
            root = self._states[project_id].root
            question_id = project_question.new_question_id()
            session_id = project_question.new_session_id()
            payload = {"question_id": question_id, "question": text, "profile": profile,
                       "session_id": session_id}
            if thread_id is not None:
                payload["thread_id"] = thread_id
            appended = self.log.append([(PROJECT_QUESTION_ASKED, project_id, payload)])
            self._apply(appended)
            self._project_questions_open += 1
        try:
            self._project_question_dispatch(
                lambda: self._run_project_question(
                    question_id, project_id, root, text, profile, session_id, thread))
        except BaseException as error:
            self._record_project_answer(question_id, project_id, project_question.Outcome(
                project_question.FAILED, reason=f"{type(error).__name__}: {error}"))
            raise
        return question_id

    def _run_project_question(self, question_id: str, project_id: str, root: str, text: str,
                              profile: str, session_id: str,
                              thread: "tuple[project_question.Turn, ...]" = ()) -> None:
        """The job of one accepted question: stop check, routes, the session, then the one answer."""
        outcome = None
        try:
            if self._stop.is_set():
                outcome = project_question.Outcome(
                    project_question.FAILED, reason=project_question.STOPPED_TEXT)
            else:
                try:
                    reach = self._project_reach(root)
                except Exception as error:
                    print(f"console: project_question_contract_failed {question_id} "
                          f"{type(error).__name__}: {error}", file=sys.stderr)
                    outcome = project_question.Outcome(
                        project_question.FAILED,
                        reason=project_question.CONTRACT_UNREADABLE.format(
                            detail=f"{type(error).__name__}: {error}"))
                else:
                    try:
                        with self._client_run(profile):
                            if profile not in self._read_profiles():
                                outcome = project_question.Outcome(
                                    project_question.FAILED,
                                    reason=project_question.PROFILE_GONE.format(profile=profile))
                            else:
                                ask = project_question.new_ask(
                                    question_id, project_id, root, text, profile, reach.routes,
                                    Path(self._store).with_name(project_question.SETTINGS_DIR),
                                    session_id=session_id, thread=thread, repo=reach.repo,
                                    unset=reach.unset)
                                try:
                                    outcome = self._project_asker(ask, self._stop)
                                except Exception as error:
                                    outcome = project_question.Outcome(
                                        project_question.FAILED,
                                        reason=f"{type(error).__name__}: {error}")
                    except _ProfileRemoving as error:
                        outcome = project_question.Outcome(project_question.FAILED, reason=str(error))
        except Exception as error:
            # Never raised on: a dispatch that runs the job inline would answer the question twice.
            traceback.print_exc()
            outcome = project_question.Outcome(
                project_question.FAILED, reason=f"{type(error).__name__}: {error}")
        finally:
            if outcome is None:  # interrupted: the question is still answered once
                outcome = project_question.Outcome(
                    project_question.FAILED, reason=project_question.STOPPED_TEXT)
            self._record_project_answer(question_id, project_id, outcome)

    def _record_project_answer(self, question_id: str, project_id: str,
                               outcome: "project_question.Outcome") -> None:
        """Append the one answered row of an accepted question and release its open count."""
        try:
            if outcome.outcome != project_question.ANSWERED:
                print(f"console: project_question_unanswered {question_id} {outcome.reason}",
                      file=sys.stderr)
            payload = {"question_id": question_id, "outcome": outcome.outcome}
            if outcome.outcome == project_question.ANSWERED:
                payload["answer"] = outcome.answer
            else:
                payload["reason"] = outcome.reason
            try:
                with self._ingest:
                    self._apply(self.log.append(
                        [(PROJECT_QUESTION_ANSWERED, project_id, payload)]))
            except Exception as error:
                print(f"console: project_question_unrecorded {question_id} "
                      f"{type(error).__name__}: {error}", file=sys.stderr)
        finally:
            with self._ingest:
                self._project_questions_open -= 1
                self._project_questions_done.notify_all()

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
                    self._profiles - self._removing, self._probing, self._probe_started, self._probe_since, now):
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
            newest = self._capacity.readings.get(profile)
            left = capacity.left_candidate(self._capacity, profile, folded)
            row = signin.entry(profile, status, folded, newest.seq if newest is not None else None,
                               left.account if left is not None else None,
                               left.seq if left is not None else 0)
            if folded is not None and (folded.state, folded.ends_at, folded.account) == (
                    row[2]["state"], row[2]["ends_at"], row[2]["account"]):
                return
            self._fold(self.log.append([row]))
            self._publish()

    @contextlib.contextmanager
    def _client_run(self, profile: str):
        """Hold the profile's client-run count around one launcher call under it (#1030).

        Raises `_ProfileRemoving` without running anything while the profile is marked as being
        removed; the removal waits for the count to reach zero before it signs the profile out.
        """
        with self._ingest:
            if profile in self._removing:
                raise _ProfileRemoving(account_remove.removing(profile))
            self._client_live[profile] += 1
        try:
            yield
        finally:
            with self._ingest:
                self._client_live[profile] -= 1
                if self._client_live[profile] <= 0:
                    del self._client_live[profile]
                self._idle.notify_all()

    def _send_nudge(self, sent: nudge.Nudge) -> None:
        """The nudger's call under the nudge's profile; `NudgeFailed` while that profile is being removed."""
        try:
            with self._client_run(sent.profile):
                self._nudger(sent)
        except _ProfileRemoving as error:
            raise nudge.NudgeFailed(str(error)) from None

    def _stop_one(self, session_id: str, profile: str) -> None:
        """The stopper's call under the session's profile; `StopFailed` while that profile is being removed."""
        try:
            with self._client_run(profile):
                self._stopper(session_id, profile)
        except _ProfileRemoving as error:
            raise manager.StopFailed(str(error)) from None

    def _read_signin_now(self, profile: str, when: str) -> signin.Status | None:
        """The status read at once (`when` is "end", "add" or "remove"); a failed read records nothing.

        The removal's own read ("remove") is the only one that runs while the profile is marked as
        being removed; any other is held in the profile's client-run count and is not run (None)
        once the mark is set.
        """
        ticket = self._signin_ticket(profile)
        try:
            with (contextlib.nullcontext() if when == "remove" else self._client_run(profile)):
                status = self._signin_reader(probe.Probe(profile, str(uuid.uuid4()), self._stop))
        except _ProfileRemoving:
            return None
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
            if profile in self._removing:
                raise sprints.Refused(account_remove.removing(profile))
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

    def signin_link(self, profile: str) -> tuple[int, str | None]:
        """The live run's attempt and link, for a page opened after the start; no row, no client."""
        runs = self._signin_refuse_unless_listed(profile)
        with self._ingest:
            attempt = self._signin_live.get(profile)
            if attempt is None or profile not in runs.running():
                raise sprints.Refused(f"no sign-in is running for {profile}")
        link = runs.wait_link(profile)
        with self._ingest:
            if self._signin_live.get(profile) != attempt:
                raise sprints.Refused(f"the sign-in for {profile} changed while waiting for its link")
        return attempt, link

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
        self._grant_registered_projects(name)
        self._read_signin_now(name, "add")
        return self.start_signin(name)

    def _grant_registered_projects(self, name: str) -> None:
        """Grant a page-added profile every registered project's folder trust (#1078).

        Runs after the adder returned, so the add deadline bounds creation only, and before the
        sign-in starts. Nothing here fails the add: an unreadable registry grants nothing.
        """
        entries = read_fleet(self.registry)
        if entries is None:
            if os.path.lexists(self.registry):
                print(f"console: trust_account_registry_unreadable {name}", file=sys.stderr)
            return
        found = [d for d in self._profile_dirs() if sessions.account_name(d) == name]
        if not found:
            return
        for entry in entries:
            try:
                self._grant_trust("account", entry["root"], entry["project_id"],
                                  profiles=[(name, found[0] / ".claude.json")])
            except Exception as error:
                print(f"console: trust_account_failed {name} {type(error).__name__}",
                      file=sys.stderr)

    def _grant_at_start(self) -> None:
        """Grant every registered project's folder trust in every target, once (#1183).

        Runs on `TRUST_START_THREAD` and holds no lock of its own: `_grant_trust` takes `_ingest`
        only around its bookkeeping, and every write goes through the folder-trust writer lock.
        Stops between projects once `close` began; one failing project does not stop the rest.
        """
        entries = read_fleet(self.registry)
        if entries is None:
            if os.path.lexists(self.registry):
                print("console: trust_start_registry_unreadable", file=sys.stderr)
            return
        for entry in entries:
            if self._stop.is_set():
                return
            try:
                self._grant_trust(folder_trust.START_CAUSE, entry["root"], entry["project_id"])
            except Exception as error:
                print(f"console: trust_start_failed {entry['project_id']} {type(error).__name__}",
                      file=sys.stderr)

    def register_project(self, path: str) -> None:
        """Dispatch the adoption plan of a repository; refusals are `sprints.Refused`."""
        if self._adopter is None:
            raise sprints.Refused(register.UNAVAILABLE)
        entries = read_fleet(self.registry)
        if entries is None:
            if os.path.lexists(self.registry):
                raise sprints.Refused(register.registry_unreadable())
            entries = []
        reason, root = register.refusal(path, entries, home=os.environ.get("HOME", ""))
        if reason is not None:
            raise sprints.Refused(reason)
        with self._ingest:
            if self._registering is not None:
                raise sprints.Refused(register.running(register.name_of(self._registering)))
            self._registering = str(root)
            self._publish()
        try:
            self._dispatch(lambda: self._run_registration(str(root), entries))
        except BaseException:
            with self._ingest:
                self._registering = None
                self._publish()
            raise

    def confirm_registration(self, root: str, choice: str) -> None:
        """Answer the Register card or the failure card of a repository; refusals are `sprints.Refused`."""
        if self._adopter is None:
            raise sprints.Refused(register.UNAVAILABLE)
        with self._ingest:
            latest = self._check_answerable(root, choice)
            if choice == register.LATER_VALUE:
                self._fold(self.log.append([register.ended(register.dismissed(latest))]))
                self._publish()
                return
        entries = read_fleet(self.registry)
        if entries is None:
            if os.path.lexists(self.registry):
                raise sprints.Refused(register.registry_unreadable())
            entries = []
        reason, _ = register.refusal(root, entries, home=os.environ.get("HOME", ""))
        if reason is not None:
            raise sprints.Refused(reason)
        project = latest["project_id"] or register.name_of(root)
        with self._ingest:
            if self._check_answerable(root, choice)["at"] != latest["at"]:
                raise sprints.Refused(register.NOT_WAITING)
            self._registering = root
            self._publish()

        remote = latest["remote"] if isinstance(latest.get("remote"), str) else None

        def run() -> None:
            if choice in (register.TRY_VALUE, register.UPDATE_VALUE):
                self._run_registration(root, entries, update=choice == register.UPDATE_VALUE)
                return
            try:
                self._grant_trust("register", root, project)
            except Exception as error:
                print(f"console: trust_grant_failed {type(error).__name__}", file=sys.stderr)
            self._run_registration(root, entries, confirmed=True,
                                   answers=latest["answered"], draft=latest["draft"], remote=remote)

        try:
            self._dispatch(run)
        except BaseException:
            with self._ingest:
                self._registering = None
                self._publish()
            raise

    def cancel_registration(self, root: str) -> None:
        """Cancel the shown registration of `root` before apply; refusals are `sprints.Refused`.

        Every failed apply of the root is cleaned and forgotten, not only the shown plan's: a shown
        failure can carry no plan id while an earlier attempt still keeps its copy (#1088).
        """
        with self._ingest:
            latest = self._cancellable(root)
            failed = self._failed_applies(root)
        pending = [plan_id for plan_id in failed if approve.left_behind(plan_id, root)]
        if pending:
            with self._ingest:
                if self._cancellable(root) is not latest:
                    raise sprints.Refused(register.NOT_WAITING)
                self._registering = root
                self._publish()
            try:
                if self._adopter is None:
                    refused = True
                else:
                    refused = any("error" in self._adopter.discard(plan_id, cancel=self._stop)
                                  for plan_id in pending)
            except register.RunFailed:
                refused = True
            except BaseException:
                with self._ingest:
                    self._registering = None
                    self._publish()
                raise
            with self._ingest:
                self._registering = None
                if refused:
                    self._publish()
            if refused:
                raise sprints.Refused(register.CANCEL_DISCARD_FAILED)
        with self._ingest:
            if self._cancellable(root) is not latest:
                raise sprints.Refused(register.NOT_WAITING)
            plan_ids = [latest["plan_id"], *(one for one in self._failed_applies(root)
                                             if one != latest["plan_id"])]
            self._cancelled[root] = self._cancelled.get(root, 0) + 1
            self._fold(self.log.append([register.cancelled_row(root, one) for one in plan_ids]))
            self._answer_refusal = None
            self._publish()

    def _failed_applies(self, root: str) -> list[str]:
        """The plan ids of `root` whose apply failed, held under the ingest lock."""
        return sorted(plan_id for plan_id, found in self._adoptions.items()
                      if found["root"] == root and found["step"] == "apply_failed")

    def _cancellable(self, root: str) -> dict:
        """The shown registration of `root` when it may be cancelled, held under the ingest lock."""
        if self._registering is not None:
            raise sprints.Refused(register.running(register.name_of(self._registering)))
        latest = self._registration
        if latest is None or latest["root"] != root:
            raise sprints.Refused(register.NOT_WAITING)
        if not register.cancellable(latest, self._adoptions.get(latest["plan_id"])):
            raise sprints.Refused(register.CANCEL_REFUSED)
        with self._published:
            unseen = self._evidence_card is not None and self._delivered < self._evidence_card[1]
        if unseen:
            raise sprints.Refused(register.CANCEL_UNSEEN)
        return latest

    def _check_answerable(self, root: str, choice: str) -> dict:
        """The registration row `choice` answers for `root`, held under the ingest lock.

        `register` answers the waiting row, `try_again` the failing one, `update` the behind row and
        `not_now` the waiting, the failing or the behind one.
        """
        if self._registering is not None:
            raise sprints.Refused(register.running(register.name_of(self._registering)))
        latest = self._registration
        if latest is None or latest["root"] != root:
            raise sprints.Refused(register.NOT_WAITING)
        asks = ((choice in (register.CONFIRM_VALUE, register.LATER_VALUE) and register.waiting(latest))
                or (choice in (register.TRY_VALUE, register.LATER_VALUE) and register.failing(latest))
                or (choice in (register.UPDATE_VALUE, register.LATER_VALUE)
                    and register.behind_waiting(latest)))
        if not asks:
            raise sprints.Refused(register.NOT_WAITING)
        return latest

    def _run_registration(self, root: str, entries: list[dict], *, confirmed: bool = False,
                          answers: list[dict] | None = None, draft: list[dict] | None = None,
                          update: bool = False, remote: str | None = None) -> None:
        """Plan and, when confirmed, register; a confirmed run plans with the waiting row's answers.

        A fresh run compares the checkout with its remote first (#1233, ADR-console-070): a checkout
        behind a remote that has a contract is one `behind` row and nothing else runs; `update` moves
        the checkout forward first. A confirmed run and an answer run never compare; a confirmed run
        keeps the waiting row's `remote` sentence, as an answer run does, because it still uses the
        checkout that was never compared.

        The Register card can follow an answer run, and a plan without those answers goes back to
        `reconcile` (a `retain` answer adds no operation), so `register` would never run.
        """
        verb = "plan"
        unread = False
        try:
            left = self._discard_left(root)
            if left is not None:
                self._log_registration_error({"root": root, "verb": "discard",
                                              "error": left["error"]})
                payload = register.summary(root, left)
            else:
                done = None
                if update:
                    done = self._checkout_updater(root, cancel=self._stop)
                    self._log_checkout(root, "update", done.failure)
                    if self._stop.is_set():
                        raise register.RunFailed("cancelled")
                if done is not None and done.reason is not None:
                    payload = register.update_failed(root, done.reason)
                else:
                    seen = None if confirmed else self._checkout_reader(root, cancel=self._stop)
                    if seen is not None:
                        self._log_checkout(root, "compare", seen.failure)
                    if self._stop.is_set():
                        raise register.RunFailed("cancelled")
                    unread = seen is not None and seen.state == checkout_remote.UNREADABLE
                    if seen is not None and seen.state == checkout_remote.BEHIND:
                        payload = register.behind(root, seen.behind, seen.contract)
                    elif not os.path.lexists(os.path.join(root, ".agents/project.json")):
                        reading = self._draft_reader(root)
                        fields = contract_draft.draft(root, reading, entries=entries)
                        payload = self._plan_draft(root, fields, [])
                    else:
                        plan = (self._plan_with(root, draft, answers) if answers or draft
                                else self._adopter.plan(root, cancel=self._stop))
                        report = None
                        if confirmed and plan.get("plan", {}).get("outcome") == "no_change":
                            verb = "register"
                            report = self._adopter.register(root, cancel=self._stop)
                        self._log_registration_failure(root, plan, report)
                        payload = register.summary(root, plan, report)
        except register.RunFailed as error:
            self._log_registration_error({"root": root, "verb": verb, "failure": error.kind,
                                          "cause": repr(error.__cause__)})
            payload = register.failed(root, error.kind, verb)
        except Exception as error:
            self._log_registration_error({"root": root, "verb": verb,
                                          "exception": type(error).__name__,
                                          "detail": str(error)})
            traceback.print_exception(error, file=sys.stderr)
            payload = register.failed(root, type(error).__name__, verb)
        if unread:
            payload = register.unread(payload)
        elif remote is not None:
            payload = {**payload, "remote": remote}
        with self._ingest:
            if not self._closed:
                self._fold(self.log.append([register.ended(payload)]))
            self._registering = None
            if not self._closed:
                self._publish()
        if not self._closed:
            self.refresh()
        print(f"console: registration_ended {payload['result']}", file=sys.stderr)

    @staticmethod
    def _log_registration_error(record: dict) -> None:
        print(f"console: registration_error {json.dumps(record, sort_keys=True)}", file=sys.stderr)

    def _log_checkout(self, root: str, verb: str, failure: checkout_remote.Failure | None) -> None:
        """Git's own words of a failed comparison or update, before the page shows plain ones."""
        if failure is not None:
            self._log_registration_error({"root": root, "verb": verb, "step": failure.step,
                                          "detail": failure.detail})

    def _log_registration_failure(self, root: str, plan: Mapping, report: Mapping | None) -> None:
        """The child's own words of a failed plan or registration, before the page shows plain ones."""
        if "error" in plan:
            self._log_registration_error({"root": root, "verb": "plan", "error": plan["error"]})
        elif report is not None and report.get("registered") is not True:
            self._log_registration_error({"root": root, "verb": "register", "report": report})

    def answer_plan(self, plan_id: str, question: str, subject: str, value: str) -> None:
        """Plan the shown registration again with one more answer; refusals are `sprints.Refused`."""
        if self._adopter is None:
            raise sprints.Refused(plan_questions.UNAVAILABLE)
        with self._ingest:
            if self._registering is not None:
                raise sprints.Refused(register.running(register.name_of(self._registering)))
            latest = self._registration
            if latest is None or latest["plan_id"] != plan_id:
                raise sprints.Refused(plan_questions.STALE)
            root = latest["root"]
            changed = None
            if question == contract_draft.QUESTION_ID:
                if latest["draft"] is None:
                    raise sprints.Refused(contract_draft.NO_DRAFT)
                entries = read_fleet(self.registry)
                if entries is None:
                    if os.path.lexists(self.registry):
                        raise sprints.Refused(register.registry_unreadable())
                    entries = []
                changed, refusal = contract_draft.set_value(
                    latest["draft"], subject, value, entries=entries, root=root)
                if refusal is not None:
                    raise sprints.Refused(refusal)
                answers = list(latest["answered"])
            else:
                answers = [*latest["answered"], {"id": question, "subject": subject, "value": value}]
            asked = {"id": question, "subject": subject}
            draft = latest["draft"]
            remote = latest["remote"] if isinstance(latest.get("remote"), str) else None
            self._registering = root
            self._answering = True
            self._answer_refusal = None
            self._publish()
        try:
            self._dispatch(lambda: self._run_answer(root, plan_id, answers, asked, draft, changed, remote))
        except BaseException:
            with self._ingest:
                self._registering = None
                self._answering = False
                self._publish()
            raise

    def _discard_left(self, root: str) -> dict | None:
        """Remove every copy a failed apply of `root` kept; the first failure's error document.

        A plan run of the root leaves those copies behind, so each is discarded first (#1088).
        With none kept, no child runs.
        """
        with self._ingest:
            plan_ids = sorted(plan_id for plan_id, found in self._adoptions.items()
                              if found["root"] == root and found["step"] == "apply_failed")
        for plan_id in plan_ids:
            if not approve.left_behind(plan_id, root):
                continue
            try:
                result = self._adopter.discard(plan_id, cancel=self._stop)
            except register.RunFailed:
                result = {"error": {
                    "code": "adopt_failure", "repair_id": approve.DISCARD_REPAIR,
                    "violations": [{"pointer": "", "message": approve.DISCARD_REASON}]}}
            if "error" in result:
                return result
        return None

    def _write_draft(self, fields: list[dict]) -> Path:
        directory = agent_platform.ensure_directory(agent_platform.state_root() / "console" / "drafts")
        handle, name = tempfile.mkstemp(dir=directory, suffix=".json")
        try:
            with os.fdopen(handle, "w") as stream:
                stream.write(json.dumps(contract_draft.contract(fields), sort_keys=True))
        except BaseException:
            Path(name).unlink(missing_ok=True)
            raise
        return Path(name)

    def _plan_with(self, root: str, fields: list[dict] | None, answers: list[dict]) -> dict:
        """The adopter's plan, with the drafted contract as a file that is gone when it returns."""
        if fields is None:
            return self._adopter.plan(root, cancel=self._stop, answers=answers)
        path = self._write_draft(fields)
        try:
            return self._adopter.plan(root, cancel=self._stop, answers=answers, contract=str(path))
        finally:
            path.unlink(missing_ok=True)

    def _plan_draft(self, root: str, fields: list[dict], answers: list[dict],
                    *, refusals: bool = False) -> dict:
        """The row of a drafted checkout: its open cards, else its plan (ADR-console-031).

        With `refusals`, a plan error that names no drafted value is returned as the plan document,
        not as a failed row.
        """
        if contract_draft.open_fields(fields):
            return register.drafting(root, fields, answers)
        entries = read_fleet(self.registry)
        if entries is None:
            if os.path.lexists(self.registry):
                raise register.RunFailed("unreadable")
            entries = []
        held = contract_draft.taken_id(fields, entries, root)
        if held is not None:
            return register.drafting(
                root, contract_draft.mark_refused(fields, "project-id", held), answers)
        plan = self._plan_with(root, fields, answers)
        if "error" in plan:
            refused = contract_draft.refused_field(plan["error"])
            if refused is not None:
                return register.drafting(
                    root, contract_draft.mark_refused(fields, *refused), answers)
            if refusals:
                return plan
            self._log_registration_error({"root": root, "verb": "plan", "error": plan["error"]})
        return register.summary(root, plan, None, draft=fields)

    def _run_answer(self, root: str, plan_id: str, answers: list[dict], asked: dict,
                    draft: list[dict] | None = None, changed: list[dict] | None = None,
                    remote: str | None = None) -> None:
        """Plan again with one more answer; the row keeps the shown row's `remote` sentence (#1233).

        The sentence says the registration used a checkout whose remote was never read, which stays
        true of every later plan of that run.
        """
        payload = None
        text = None
        try:
            left = self._discard_left(root)
            if left is not None:
                self._log_answer_error({"root": root, "discard": left["error"]})
                payload = register.summary(root, left)
            else:
                if changed is not None:
                    result = self._plan_draft(root, changed, answers, refusals=True)
                else:
                    result = self._plan_with(root, draft, answers)
                    refused = (contract_draft.refused_field(result["error"])
                               if draft is not None and "error" in result else None)
                    if refused is not None:
                        result = register.drafting(
                            root, contract_draft.mark_refused(draft, *refused), answers)
                    elif "error" not in result:
                        result = register.summary(root, result, draft=draft)
                if "error" in result:
                    self._log_answer_error({"root": root, "error": result["error"]})
                    text = plan_questions.refusal_text(result["error"])
                else:
                    payload = result if remote is None else {**result, "remote": remote}
        except register.RunFailed as error:
            self._log_answer_error(
                {"root": root, "failure": error.kind, "cause": repr(error.__cause__)})
            text = plan_questions.rerun_failed(
                register.RUN_WORDS.get(error.kind, register.UNEXPECTED))
        except Exception as error:
            self._log_answer_error(
                {"root": root, "exception": type(error).__name__, "detail": str(error)})
            traceback.print_exception(error, file=sys.stderr)
            text = plan_questions.rerun_failed(register.UNEXPECTED)
        with self._ingest:
            if payload is not None and not self._closed:
                self._fold(self.log.append([register.ended(payload)]))
            elif payload is None:
                self._answer_refusal = {
                    "plan_id": plan_id, "text": text,
                    "id": asked["id"], "subject": asked["subject"]}
            self._registering = None
            self._answering = False
            if not self._closed:
                self._publish()
        if not self._closed:
            self.refresh()
        print(f"console: plan_answer_ended {payload['result'] if payload else 'refused'}",
              file=sys.stderr)

    @staticmethod
    def _log_answer_error(record: dict) -> None:
        print(f"console: plan_answer_error {json.dumps(record, sort_keys=True)}", file=sys.stderr)

    def approve_plan(self, plan_id: str) -> None:
        """Apply, push and open the pull request of the shown ready plan; refusals are `sprints.Refused`."""
        if self._adopter is None or self._forge is None:
            raise sprints.Refused(approve.UNAVAILABLE)
        with self._ingest:
            if self._registering is not None:
                raise sprints.Refused(register.running(register.name_of(self._registering)))
            latest = self._registration
            if latest is None or latest["plan_id"] != plan_id:
                raise sprints.Refused(approve.STALE)
            if latest["state"] != "ready":
                raise sprints.Refused(approve.NOT_READY)
            found = self._adoptions.get(plan_id)
            if found is not None and found["step"] == "opened":
                if found["pull_state"] in ("open", "ready"):
                    raise sprints.Refused(approve.OPENED)
                if found["pull_state"] == "merged":
                    raise sprints.Refused(approve.MERGED)
            root = latest["root"]
            shown = dict(latest)
            adoption = None if found is None else dict(found)
            self._registering = root
            self._approving = True
            self._publish()
        try:
            self._approval_dispatch(lambda: self._run_approval(root, shown, adoption))
        except BaseException:
            with self._ingest:
                self._registering = None
                self._approving = False
                self._publish()
            raise

    @staticmethod
    def _log_approval_error(record: dict) -> None:
        print(f"console: plan_approve_error {json.dumps(record, sort_keys=True)}", file=sys.stderr)

    def _log_forge_error(self, stage: str, error: BaseException, where: dict) -> None:
        record = {"stage": stage, **where}
        if isinstance(error, ForgeError):
            record.update({"code": error.code, "detail": error.detail,
                           "transient": error.transient})
            self._log_approval_error(record)
            return
        record.update({"exception": type(error).__name__, "detail": str(error)})
        self._log_approval_error(record)
        traceback.print_exception(error, file=sys.stderr)

    def _step(self, shown: Mapping, plan_id: str, root: str, step: str, **members) -> dict:
        payload = {"by": "owner", "plan_id": plan_id, "root": root,
                   "project_id": shown["project_id"], "step": step, "branch": None,
                   "commit": None, "base": None, "pull_request": None, "reason": None,
                   "note": None, "kept": None, "evidence": None, **members}
        approve.step_row(payload)
        return payload

    def _grant_trust(self, cause: str, root: str, project: str,
                     profiles: Sequence[tuple[str, Path]] | None = None,
                     slot: str | None = None, epoch: int | None = None) -> list[tuple[str, str]]:
        """Grant the folder's client trust in every target and log one `trust.granted` row.

        The key is read from `root` every time. The row names the key, or `slot` when the caller
        answers a failed row (a failure whose key never resolved names the checkout path, and the
        retry must clear that very pair). A result for a profile that no longer exists when the row
        is published is dropped, so an account removal that finished first leaves no card behind.

        The row is kept even when `close` has begun, the files being written already; a grant that
        starts after `close` began writes nothing. `close` waits for every grant under way.

        A retry passes the `epoch` it read of the root's cancellations (#1088): once the owner has
        cancelled the root's registration, nothing is written and no row is logged, so a Check again
        that was under way cannot bring the cancelled card back.
        """
        with self._ingest:
            if self._closed:
                print("console: trust_grant_skipped closing", file=sys.stderr)
                return []
            if epoch is not None and self._cancelled.get(root, 0) != epoch:
                print("console: trust_grant_skipped cancelled", file=sys.stderr)
                return []
            self._grants_running += 1
        try:
            found = (folder_trust.targets(self._trust_home, self._profile_dirs())
                     if profiles is None else list(profiles))
            if not found:
                return []
            key = folder_trust.trust_key(root)
            results = []
            for name, path in found:
                if key is None:
                    results.append((name, folder_trust.FAILED))
                    continue
                try:
                    results.append((name, self._trust_granter(path, key)))
                except Exception as error:
                    print(f"console: trust_grant_error {name} {type(error).__name__}",
                          file=sys.stderr)
                    results.append((name, folder_trust.FAILED))
            named = slot if slot is not None else (
                key if key is not None else os.path.realpath(root))
            with self._ingest:
                if epoch is not None and self._cancelled.get(root, 0) != epoch:
                    print("console: trust_grant_skipped cancelled", file=sys.stderr)
                    return []
                present = self._read_profiles()
                results = [(name, result) for name, result in results
                           if name == "default" or name in present]
                if not results:
                    return []
                row = folder_trust.granted_row(cause, project, named, results)
                self._fold(self.log.append([row]))
                if not self._closed:
                    self._publish()
            counts = [sum(1 for _, result in results if result == one)
                      for one in folder_trust.RESULTS]
            print(f"console: trust_granted {cause} {project} {counts[0]} {counts[1]} {counts[2]}",
                  file=sys.stderr)
            return results
        finally:
            with self._ingest:
                self._grants_running -= 1
                self._grants_done.notify_all()

    def check_trust(self, root: str, profile: str) -> None:
        """Grant the trust again for one failed pair, as the Check again card asks (#1078).

        Refused with `folder_trust.NOT_FAILED` unless a logged `trust.granted` row left
        `(root, profile)` failed and the profile's file is still a target; nothing else is granted.
        """
        with self._ingest:
            failed = self._trust_failures.get((root, profile))
            epoch = self._cancelled.get(root, 0)
        found = [pair for pair in folder_trust.targets(self._trust_home, self._profile_dirs())
                 if pair[0] == profile]
        if failed is None or not found:
            raise sprints.Refused(folder_trust.NOT_FAILED)
        self._grant_trust("check", root, failed["project"], found, slot=root, epoch=epoch)

    def _run_approval(self, root: str, shown: dict, adoption: dict | None) -> None:
        final = None
        try:
            if adoption is None:
                self._grant_trust("apply", root, shown["project_id"] or register.name_of(root))
            final = self._approval_steps(root, shown, adoption)
        except Exception as error:
            self._log_approval_error({"stage": "run", "root": root,
                                      "exception": type(error).__name__, "detail": str(error)})
            traceback.print_exception(error, file=sys.stderr)
        appended = False
        with self._ingest:
            if final is not None and not self._closed:
                self._fold(self.log.append([approve.step_row(final)]))
                appended = True
            self._registering = None
            self._approving = False
            if not self._closed:
                self._publish()
        if not self._closed:
            self.refresh()
        print(f"console: plan_approve_ended {final['step'] if appended else 'stopped'}",
              file=sys.stderr)

    def _append_applied(self, payload: dict) -> None:
        # Apply has already made its branch, so its row is kept even when `close` has begun: the
        # log is closed only after every approval worker is joined.
        with self._ingest:
            self._fold(self.log.append([approve.step_row(payload)]))
            if not self._closed:
                self._publish()

    def _approval_steps(self, root: str, shown: dict, adoption: dict | None) -> dict | None:
        """The run's stages; the payload of the last row to append, or None when stopped."""
        stop = self._stop
        plan_id = shown["plan_id"]
        name = register.name_of(root)
        acknowledge = approve.acknowledges(shown)
        resume = adoption is not None and adoption["step"] in approve.RESUMABLE
        again = adoption is not None and adoption["step"] == "apply_failed"
        if resume:
            branch, commit, base = adoption["branch"], adoption["commit"], adoption["base"]
        else:
            try:
                result = self._adopter.apply(plan_id, cancel=stop, acknowledge_deletions=acknowledge,
                                             discard_retained=again)
            except register.RunFailed as error:
                self._log_approval_error({"stage": "apply", "root": root, "plan_id": plan_id,
                                          "failure": error.kind, "cause": repr(error.__cause__)})
                reason, note = approve.run_failure(name, error.kind)
                return self._step(shown, plan_id, root, "apply_failed",
                                         reason=approve.reason_of(reason), note=note)
            except Exception as error:
                self._log_approval_error({"stage": "apply", "root": root, "plan_id": plan_id,
                                          "exception": type(error).__name__,
                                          "detail": str(error)})
                traceback.print_exception(error, file=sys.stderr)
                reason, note = approve.run_failure(name, type(error).__name__)
                return self._step(shown, plan_id, root, "apply_failed",
                                         reason=approve.reason_of(reason), note=note)
            if "error" in result:
                self._log_approval_error({"stage": "apply", "root": root, "plan_id": plan_id,
                                          "error": result["error"]})
                kept = approve.retained(plan_id)
                reason, note = approve.apply_failure(name, result["error"], kept)
                evidence = approve.commit_evidence(result["error"], kept)
                return self._step(shown, plan_id, root, "apply_failed",
                                         reason=approve.reason_of(reason), note=note, kept=kept,
                                         evidence=evidence)
            branch, commit = result["branch"], result["commit"]
            base = result.get("integration_branch")
            self._append_applied(self._step(
                shown, plan_id, root, "applied", branch=branch, commit=commit, base=base))
        if stop.is_set():
            return None
        where = {"root": root, "plan_id": plan_id, "branch": branch, "base": base}
        if not (resume and adoption["step"] == "open_failed"):
            try:
                self._pusher(root, branch, commit, cancel=stop)
            except approve.PushFailed as error:
                self._log_approval_error({"stage": "push", "root": root, "plan_id": plan_id,
                                          "branch": branch, "reason": error.reason,
                                          "detail": error.detail})
                return self._step(
                    shown, plan_id, root, "push_failed", branch=branch, commit=commit, base=base,
                    reason=error.reason, note=approve.PUSH_NOTE)
        if stop.is_set():
            return None
        slug = self._slug_of(root)
        pushed = {"branch": branch, "commit": commit, "base": base}
        if slug is None:
            return self._step(
                shown, plan_id, root, "open_failed", **pushed, reason=approve.NO_SLUG,
                note=approve.NO_SLUG_NOTE)
        if base is None:
            return self._step(
                shown, plan_id, root, "open_failed", **pushed, reason=approve.NO_BASE,
                note=approve.NO_BASE_NOTE)
        try:
            pull, error = self._pull_request(slug, branch, base, name, shown, stop, where)
        except approve.Cancelled:
            return None
        if pull is None:
            reason, note = approve.forge_failure(error, base)
            return self._step(shown, plan_id, root, "open_failed", **pushed,
                                     reason=approve.reason_of(reason), note=note)
        return self._step(shown, plan_id, root, "opened", **pushed, pull_request=pull)

    def _pull_request(self, slug: str, branch: str, base: str, name: str, shown: Mapping,
                      stop: threading.Event, where: dict) -> tuple[dict | None, Exception | None]:
        """The branch's pull request, found or opened; (None, the failure) when neither worked."""
        try:
            found = self._forge.find_pull_request(slug, branch, base, cancel=stop)
        except approve.Cancelled:
            raise
        except Exception as error:
            self._log_forge_error("find", error, where)
            return None, error
        if found is not None:
            return found, None
        try:
            return self._forge.open_pull_request(
                slug, branch, base, approve.title(name), approve.body(shown), cancel=stop), None
        except approve.Cancelled:
            raise
        except Exception as error:
            self._log_forge_error("open", error, where)
            failure = error
        try:
            found = self._forge.find_pull_request(slug, branch, base, cancel=stop)
        except approve.Cancelled:
            raise
        except Exception as error:
            self._log_forge_error("find", error, where)
            found = None
        return (found, None) if found is not None else (None, failure)

    def remove_account(self, profile: str, typed: str) -> None:
        """Sign the profile out, then remove it through the launcher; refusals are `sprints.Refused`.

        The profile is marked as being removed from the checks until the removal ends, the
        console's own probes and client runs under it (manager launches, nudges, wakes, stops and
        sign-in status reads) already in flight are waited for, and no
        ingest lock is held while the sign-out or the launcher runs.
        """
        if (self._signer_out is None or self._account_remover is None
                or self._signin_reader is None):
            raise sprints.Refused(account_remove.UNAVAILABLE)
        if typed != profile:
            raise sprints.Refused(account_remove.MISMATCH)
        with self._adding:
            marked = False
            try:
                with self._ingest:
                    if profile not in self._read_profiles():
                        raise sprints.Refused(account_remove.UNKNOWN)
                    if self._signin_runs is not None and profile in self._signin_runs.running():
                        raise sprints.Refused(account_remove.running(profile))
                    self._removing.add(profile)
                    marked = True
                    self._note_choice(self._session_choice(self._read_profiles()))
                    if not self._idle.wait_for(
                            lambda: profile not in self._probing
                            and self._client_live[profile] == 0,
                            timeout=account_remove.DRAIN_TIMEOUT):
                        raise sprints.Refused(account_remove.busy(profile))
                outcome, kind = self._sign_out_first(profile)
                try:
                    self._account_remover(profile)
                except account_remove.RemoveFailed as error:
                    self._record_removal(profile, "remove_failed", error.kind)
                    raise
                listed = self._read_profiles()
                if profile in listed:
                    self._record_removal(profile, "remove_failed", "still_listed")
                    raise account_remove.RemoveFailed("still_listed")
                with self._ingest:
                    self._profiles = listed
                    rows = []
                    if profile in self._excluded:
                        rows.append(exclusion.entry(profile, False))
                    if profile == self._pinned:
                        rows.append(pin.entry(profile, False))
                    rows.append(account_remove.removed(profile, outcome, kind))
                    self._fold(self.log.append(rows))
                    self._removing.discard(profile)
                    self._publish()
                    self._note_choice(self._session_choice(listed))
            finally:
                if marked:
                    with self._ingest:
                        self._removing.discard(profile)
                        self._note_choice(self._session_choice(self._read_profiles()))
                        self._idle.notify_all()

    def _sign_out_first(self, profile: str) -> tuple[str, str | None]:
        """Run the sign-out; the outcome and kind to record when the removal goes on, else raise."""
        try:
            self._signer_out(probe.Probe(profile, str(uuid.uuid4()), self._stop))
        except account_remove.SignOutFailed as error:
            status = self._read_signin_now(profile, "remove")
            if status is not None and status.state == "signed_out":
                return "removed_signed_out_already", error.kind
            self._record_removal(profile, "signout_failed", error.kind)
            raise
        return "removed", None

    def _record_removal(self, profile: str, outcome: str, kind: str) -> None:
        with self._ingest:
            self._fold(self.log.append([account_remove.removed(profile, outcome, kind)]))
            self._publish()

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
                self._idle.notify_all()

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
        """Under the ingest lock: how many open records of the sprint's project wait on the owner. A record
        that is a not-due wait is a line, never the owner's item (`view.is_waiting`)."""
        records = [r for r in self._inbox.values()
                   if r.item.get("project_id") == sprint.project_id and not r.item["answered"]
                   and not is_waiting(r.item)]
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
                prepared_pin = self._pinned
            if launch is None:
                return
            launch = dataclasses.replace(
                launch, permission=self._read_permission(launch.project_id, launch.cwd))
            with self._ingest:
                launch = self._unexcluded_launch(launch, token, prepared_pin)
                if launch is not None:
                    self._client_live[launch.profile] += 1
            if launch is None:
                return
            try:
                reason = None
                try:
                    self._launcher(launch)
                except Exception as error:
                    reason = (str(error) if isinstance(error, manager.LaunchFailed)
                              else f"{type(error).__name__}: {error}")
                self._record_launch(launch, reason, token)
            finally:
                with self._ingest:
                    self._client_live[launch.profile] -= 1
                    if self._client_live[launch.profile] <= 0:
                        del self._client_live[launch.profile]
                    self._idle.notify_all()
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
            capacity.capacity_view(self._read_profiles() - self._removing, self._capacity,
                                   self._clock(), self._signins, excluded=self._excluded,
                                   pinned=self._pinned),
            self._use.last)
        if isinstance(choice, manager.Wait):
            self._append_manager(MANAGER_WAITING, project_id, {
                "sprint_id": sprint_id, "until": choice.until, **marks}, token)
            return None
        notices = sprints.notice_block(
            sprints.project_notices(self._sprints.values(), project_id,
                                    owner=sprints.open_owner_notices(self._owner_notices,
                                                                     project_id)), sprint_id,
            int(self._clock() * 1000))
        return manager.new_launch(sprint_id, project_id, sprint.goal, project.root, choice,
                                  secret, self._sprint_secrets, takeover=takeover,
                                  seen_after=sprint.manager_seen_seq or 0, notices=notices)

    def _unexcluded_launch(self, launch: manager.Launch, token: object,
                           prepared_pin: str | None) -> manager.Launch | None:
        """Under the ingest lock: `launch`, or its replacement when its profile was excluded, is being removed or gone, or the pin moved after it was prepared.

        `prepared_pin` is the pin in force when it was prepared. The choice is made again over the
        set and the pin now in force; with nothing to choose a wait row is appended (as
        `_prepared_launch` does) and None returned.
        """
        if (launch.profile not in self._excluded and self._pinned == prepared_pin
                and launch.profile not in self._removing
                and launch.profile in self._read_profiles()):
            return launch
        sprint = self._sprints.get(launch.sprint_id)
        if sprint is None:
            self._release(launch.sprint_id, token)
            return None
        choice = manager.choose_profile(
            capacity.capacity_view(self._read_profiles() - self._removing, self._capacity,
                                   self._clock(), self._signins, excluded=self._excluded,
                                   pinned=self._pinned),
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
                    "permission": launch.permission.payload(), **marks}, token)
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
            sprint, checked = self._checked_brief(sprint_id, secret, brief)
            version = (sprint.brief.version if sprint.brief else 0) + 1
            payload = {"sprint_id": sprint_id, "version": version, "goal": sprint.goal,
                       "brief": checked}
            if "pictures" in checked:
                payload["pictures"] = sprints.picture_ids(checked["pictures"])
            appended = self.log.append([(BRIEF_SENT, sprint.project_id, payload)])
            self._apply(appended)
            return version

    def _checked_brief(self, sprint_id: str, secret: str,
                       brief: dict) -> tuple[sprints.SprintState, dict]:
        """Every refusal of a brief, in order, with nothing written (the caller holds the lock)."""
        sprint = self._manager_sprint(sprint_id, secret)
        checked = sprints.checked_brief(brief)
        for m, member in enumerate(checked.get("pictures", ()), 1):
            self._own_picture(sprint, member["picture"],
                              sprints.PART_PICTURE_UNKNOWN.format(owner="brief", m=m),
                              sprints.PART_PICTURE_FOREIGN.format(owner="brief", m=m))
        return sprint, checked

    def check_brief(self, sprint_id: str, secret: str, brief: dict) -> None:
        """Refuse a brief `send_brief` would refuse now; nothing is written."""
        with self._ingest:
            self._checked_brief(sprint_id, secret, brief)

    def store_picture(self, sprint_id: str, secret: str, data: bytes) -> str:
        """Keep one PNG of an open sprint whose secret is presented and log it; the picture's id."""
        with self._ingest:
            sprint = self._manager_sprint(sprint_id, secret)
            pictures.checked_png(data)
            picture_id, _ = pictures.store(self.pictures_dir, data)
            self._apply(self.log.append(
                [pictures.entry(sprint.project_id, sprint_id, picture_id)]))
            return picture_id

    def _sweep_pictures(self, events: Iterable[Event]) -> None:
        try:
            with self._storing:
                pictures.sweep(self.pictures_dir, pictures.referenced(events), self._clock())
        except Exception as error:
            print(f"console: picture_sweep_failed {type(error).__name__}: {error}",
                  file=sys.stderr)

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
            sprint, checked = self._checked_report(sprint_id, secret, report)
            payload = {"sprint_id": sprint_id, "goal": sprint.goal, "report": checked}
            if "pictures" in checked:
                payload["pictures"] = sprints.picture_ids(checked["pictures"])
            appended = self.log.append([(SPRINT_REPORTED, sprint.project_id, payload)])
            self._apply(appended)
            return appended[-1].at

    def _checked_report(self, sprint_id: str, secret: str,
                        report: dict) -> tuple[sprints.SprintState, dict]:
        """Every refusal of a report, in order, with nothing written (the caller holds the lock)."""
        sprint = self._manager_sprint(sprint_id, secret)
        if sprint.state != sprints.STARTING:
            raise sprints.Refused(sprints.NOT_STARTED)
        checked = sprints.checked_report(report)
        for m, member in enumerate(checked.get("pictures", ()), 1):
            self._own_picture(sprint, member["picture"],
                              sprints.PART_PICTURE_UNKNOWN.format(owner="report", m=m),
                              sprints.PART_PICTURE_FOREIGN.format(owner="report", m=m))
        return sprint, checked

    def check_report(self, sprint_id: str, secret: str, report: dict) -> None:
        """Refuse a report `send_report` would refuse now; nothing is written."""
        with self._ingest:
            self._checked_report(sprint_id, secret, report)

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

    def _reachable(self, sprint_id: str) -> sprints.SprintState | None:
        """Under the ingest lock: the open sprint when its manager can be nudged, unread or not.

        A sprint with a launch reserved is not reachable: a wake would resume the manager the launch replaces.
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
        return sprint

    def _nudgeable(self, sprint_id: str) -> tuple[sprints.SprintState, tuple[sprints.Message, ...]] | None:
        """Under the ingest lock: the reachable sprint and its unread messages when there are any."""
        sprint = self._reachable(sprint_id)
        if sprint is None:
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
            with self._client_run(profile):
                shown = self._full_listing(profile, cwd)
        except _ProfileRemoving as error:
            return None, str(error)
        except nudge.ListingUnreadable as error:
            return None, str(error)
        except Exception as error:
            return None, f"{type(error).__name__}: {error}"
        if session_id in shown:
            return None, None
        return str(manager.settings_path(self._sprint_secrets, sprint_id)), None

    def _read_permission(self, project_id: str, root: str) -> permission.Permission:
        """Off the ingest lock: the mode the project's manager runs in; a reader that raises is `FALLBACK`."""
        try:
            return self._permission_reader(project_id, root)
        except Exception as error:
            print(f"console: permission_unreadable {project_id} {type(error).__name__}: {error}",
                  file=sys.stderr)
            return permission.FALLBACK

    def _refresh_settings(self, sprint_id: str, root: str) -> permission.Permission:
        """Write the sprint's manager settings file again before a wake (ADR-console-021); the mode it wrote.

        The content is what a launch writes, from the sprint's stored secret and the mode the project's
        production rules choose now (ADR-console-060), read off the lock. The write runs under the ingest lock,
        as `withdraw_goal` removes the secret and the file, so a withdrawal can never fall between the read
        and the write and leave a file holding the secret. `NudgeFailed` when the sprint is no longer open,
        when its secret is missing (the wake is not sent without the isolation and permission members) or when
        the file cannot be written (the write's reason).
        """
        with self._ingest:
            sprint = self._sprints.get(sprint_id)
            if sprint is None:
                raise nudge.NudgeFailed("the sprint is no longer open")
            project_id = sprint.project_id
        chosen = self._read_permission(project_id, root)
        with self._ingest:
            if sprint_id not in self._sprints:
                raise nudge.NudgeFailed("the sprint is no longer open")
            secret = sprints.read_secret(self._sprint_secrets, sprint_id)
            if secret is None:
                raise nudge.NudgeFailed("the sprint's secret is missing")
            try:
                manager.write_settings(manager.settings_path(self._sprint_secrets, sprint_id),
                                       {manager.ID_ENV: sprint_id, manager.SECRET_ENV: secret},
                                       chosen)
            except manager.LaunchFailed as error:
                raise nudge.NudgeFailed(str(error)) from error
        return chosen

    def _relays_in_bypass(self, sprint_id: str) -> bool:
        """Under the ingest lock: whether the sprint's newest logged mode (ADR-console-060 D4) is bypass, so its relay must come from a bypassing sender (ADR-console-068)."""
        sprint = self._sprints.get(sprint_id)
        return (sprint is not None and sprint.permission is not None
                and sprint.permission.mode == permission.BYPASS)

    def _record_nudge(self, sprint_id: str, through: int | None, route: str | None,
                      reason: str | None, listing_failed: str | None = None,
                      written: permission.Permission | None = None) -> None:
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
        if written is not None:
            payload["permission"] = written.payload()
        self._apply(self.log.append([(SPRINT_NUDGED, sprint.project_id, payload)]))
        if reason is not None:
            print(f"console: nudge_failed {sprint_id} {reason}", file=sys.stderr)
        if listing_failed is not None:
            print(f"console: listing_failed {sprint_id} {listing_failed}", file=sys.stderr)

    def _listed_ids(self, name: str) -> list[str]:
        """Off the ingest lock: the session ids the running listing shows under `name`, lowest first."""
        return sorted(o.session_id for o in self._listing().values() if o.name == name)

    def _reach(self, sprint_id: str, name: str, profile: str, known: str | None,
               cwd: str) -> tuple[str | None, str | None, str | None, permission.Permission | None] | None:
        """Off the ingest lock: send the one nudge; `(route, reason, listing_failed, written)`, None when held for quota.

        `written` is the mode the attempt's settings refresh wrote, None when it wrote no file.
        """
        route, reason, listing_failed, written = None, None, None, None
        try:
            listed, settings = self._listed_ids(name), None
            if not listed and known is not None:
                settings, listing_failed = self._wake_settings(sprint_id, known, profile, cwd)
                listed = self._listed_ids(name)  # the full listing is slow: the manager may be running now
            with self._ingest:
                if self._held_for_quota(sprint_id):
                    return None
                bypass = self._relays_in_bypass(sprint_id)
            if listed:
                route, listing_failed = nudge.RELAY, None
                self._send_nudge(nudge.Nudge(sprint_id, route, name, listed[0], profile, cwd,
                                             sender_bypass=bypass))
            elif known is not None:
                route = nudge.WAKE
                written = self._refresh_settings(sprint_id, cwd)
                self._send_nudge(nudge.Nudge(sprint_id, route, name, known, profile, cwd, settings))
            else:
                reason = nudge.UNKNOWN_SESSION
        except Exception as error:
            reason = (str(error) if isinstance(error, nudge.NudgeFailed)
                      else f"{type(error).__name__}: {error}")
        return route, reason, listing_failed, written

    def _nudge(self, sprint_id: str) -> None:
        """Tell the sprint's manager to read its inbox, then record the attempt; the reservation ends here."""
        with self._ingest:
            found = self._nudgeable(sprint_id)
            project = None if found is None else self._states.get(found[0].project_id)
            if found is None or project is None:
                self._nudging.discard(sprint_id)
                self._nudge_again.discard(sprint_id)
                follow = self._notice_follow(sprint_id)
            else:
                follow = False
                sprint, unread = found
                covered = self._notice_due.pop(sprint_id, None)
                through = unread[-1].message_id
                name = manager.session_name(sprint.project_id, sprint_id)
                profile, known, cwd = sprint.manager.profile, sprint.manager_session, project.root
        if found is None or project is None:
            if follow:
                self._dispatch_notice_nudge(sprint_id)
            return
        reached = self._reach(sprint_id, name, profile, known, cwd)
        if reached is None:
            with self._ingest:
                self._nudging.discard(sprint_id)
                self._nudge_again.discard(sprint_id)
                follow = self._notice_follow(sprint_id)
            if follow:
                self._dispatch_notice_nudge(sprint_id)
            return
        route, reason, listing_failed, written = reached
        again = False
        with self._ingest:
            self._nudging.discard(sprint_id)
            self._settled[sprint_id] = int(self._clock() * 1000)
            wanted = sprint_id in self._nudge_again
            self._nudge_again.discard(sprint_id)
            self._record_nudge(sprint_id, through, route, reason, listing_failed, written)
            if covered is not None and reason is not None:
                self._notice_due[sprint_id] = max(covered, self._notice_due.get(sprint_id, 0))
            found = self._nudgeable(sprint_id)
            if wanted and found is not None and found[1][-1].message_id > through \
                    and not self._stop.is_set():
                self._nudging.add(sprint_id)
                again = True
            else:
                follow = self._notice_follow(sprint_id)
        if again:
            self._dispatch_nudge(sprint_id)
        elif follow:
            self._dispatch_notice_nudge(sprint_id)

    def _notice_follow(self, sprint_id: str) -> bool:
        """Under the ingest lock: reserve the sprint for the nudge of a notice still due; whether it did.

        A stopping service, no nudger, an unreachable sprint or one whose project left the registry drops the
        due notice: no nudge can carry it.
        """
        sprint = None if self._stop.is_set() or self._nudger is None else self._reachable(sprint_id)
        if sprint is None or sprint.project_id not in self._states:
            self._notice_due.pop(sprint_id, None)
            return False
        if sprint_id in self._notice_due and sprint_id not in self._nudging:
            self._nudging.add(sprint_id)
            return True
        return False

    def _dispatch_notice_nudge(self, sprint_id: str) -> None:
        """Hand a reserved sprint's notice nudge to the dispatcher; one that cannot start is a failed nudge."""
        try:
            self._dispatch(lambda: self._notice_nudge(sprint_id))
        except Exception as error:
            reason = f"the nudge could not start: {type(error).__name__}: {error}"
            with self._ingest:
                self._nudging.discard(sprint_id)
                self._nudge_again.discard(sprint_id)
                self._settled[sprint_id] = int(self._clock() * 1000)
                self._record_notice_nudge(
                    sprint_id, self._notice_due.pop(sprint_id, None), None, reason)

    def _record_notice_nudge(self, sprint_id: str, covered: int | None, route: str | None,
                             reason: str | None, listing_failed: str | None = None,
                             written: permission.Permission | None = None) -> None:
        """Under the ingest lock: append one `notice.nudged` row for the open sprint and fold it."""
        sprint = self._sprints.get(sprint_id)
        if sprint is None or covered is None or self._stop.is_set():
            return
        payload = {"sprint_id": sprint_id, "notice": covered, "route": route, "ok": reason is None}
        if reason is not None:
            payload["reason"] = reason
        if listing_failed is not None:
            payload["listing_failed"] = listing_failed
        if written is not None:
            payload["permission"] = written.payload()
        self._apply(self.log.append([(NOTICE_NUDGED, sprint.project_id, payload)]))
        if reason is not None:
            print(f"console: notice_nudge_failed {sprint_id} {reason}", file=sys.stderr)
        if listing_failed is not None:
            print(f"console: listing_failed {sprint_id} {listing_failed}", file=sys.stderr)

    def _notice_nudge(self, sprint_id: str) -> None:
        """Tell the sprint's manager to read its inbox for the owner's notice; the reservation ends here."""
        with self._ingest:
            sprint = self._reachable(sprint_id)
            project = None if sprint is None else self._states.get(sprint.project_id)
            if sprint is None or project is None:
                self._nudging.discard(sprint_id)
                self._nudge_again.discard(sprint_id)
                covered = None
            else:
                covered = self._notice_due.pop(sprint_id, None)
                if covered is None:
                    self._nudging.discard(sprint_id)
            if covered is None:
                follow = self._notice_follow(sprint_id)
            else:
                name = manager.session_name(sprint.project_id, sprint_id)
                profile, known, cwd = sprint.manager.profile, sprint.manager_session, project.root
        if covered is None:
            if follow:
                self._dispatch_notice_nudge(sprint_id)
            return
        reached = self._reach(sprint_id, name, profile, known, cwd)
        if reached is None:
            with self._ingest:
                self._nudging.discard(sprint_id)
                self._nudge_again.discard(sprint_id)
                follow = self._notice_follow(sprint_id)
            if follow:
                self._dispatch_notice_nudge(sprint_id)
            return
        route, reason, listing_failed, written = reached
        again = False
        with self._ingest:
            self._nudging.discard(sprint_id)
            self._settled[sprint_id] = int(self._clock() * 1000)
            wanted = sprint_id in self._nudge_again
            self._nudge_again.discard(sprint_id)
            self._record_notice_nudge(sprint_id, covered, route, reason, listing_failed, written)
            if wanted and self._nudgeable(sprint_id) is not None and not self._stop.is_set():
                self._nudging.add(sprint_id)
                again = True
            else:
                follow = self._notice_follow(sprint_id)
        if again:
            self._dispatch_nudge(sprint_id)
        elif follow:
            self._dispatch_notice_nudge(sprint_id)

    def renudge(self) -> None:
        """Nudge again the managers whose message went unread and undelivered for a minute."""
        if self._nudger is None:
            return
        due, noticed = [], []
        with self._ingest:
            now = int(self._clock() * 1000)
            for sprint_id in list(self._notice_due):
                if sprint_id not in self._nudging and self._notice_follow(sprint_id):
                    noticed.append(sprint_id)
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
        for sprint_id in noticed:
            self._dispatch_notice_nudge(sprint_id)
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
                    manager.stop_listed([name], lambda: listed, self._stop_one)
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
                     listing_failed: str | None = None,
                     written: permission.Permission | None = None) -> None:
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
        if written is not None:
            payload["permission"] = written.payload()
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
        reason, listing_failed, written = None, None, None
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
            written = self._refresh_settings(sprint_id, root)
            self._send_nudge(nudge.Nudge(
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
            self._record_wake(sprint_id, reason is None, reason, back, listing_failed, written)

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
                bypass = self._relays_in_bypass(sprint_id)
            self._send_nudge(nudge.Nudge(sprint_id, nudge.CONTINUE, name, session_id, profile, cwd,
                                         sender_bypass=bypass))
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

    def _own_picture(self, sprint: sprints.SprintState, picture_id: str, unknown: str,
                     foreign: str) -> None:
        """Refuse a picture the sprint did not store or that is no longer a regular file."""
        if picture_id not in sprint.pictures:
            if any(picture_id in other.pictures for other in self._sprints.values()):
                raise sprints.Refused(foreign)
            raise sprints.Refused(unknown)
        if not pictures.present(self.pictures_dir, picture_id):
            raise sprints.Refused(unknown)

    def _checked_ask(self, sprint_id: str, secret: str, round_: dict,
                     files_withheld: bool = False) -> tuple[sprints.SprintState, dict]:
        """Every refusal of a round, in order, with nothing written (the caller holds the lock)."""
        sprint = self._manager_sprint(sprint_id, secret)
        if sprint.state != sprints.STARTING:
            raise sprints.Refused(sprints.NOT_STARTED)
        if not sprints.takes_questions(sprint):
            raise sprints.Refused(sprints.ENDED)
        checked = sprints.checked_round(round_, files_withheld=files_withheld)
        for n, question in enumerate(checked["questions"], 1):
            for m, member in enumerate(question.get("pictures", ()), 1):
                self._own_picture(sprint, member["picture"],
                                  sprints.PICTURE_UNKNOWN.format(n=n, m=m),
                                  sprints.PICTURE_FOREIGN.format(n=n, m=m))
        others = [other for key, other in self._sprints.items() if key != sprint_id]
        for n, question in enumerate(checked["questions"], 1):
            mark = question.get("replaces")
            if mark is None:
                continue
            try:
                sprints.withdrawable(sprint, mark["round"], mark["index"], others)
            except sprints.Refused as error:
                raise sprints.Refused(sprints.REPLACES_REFUSED.format(
                    n=n, round=mark["round"], index=mark["index"], reason=str(error))) from None
        if not checked["blocker"]:
            replaced = set(sprints.replaced(checked))
            if any((question.round_id, question.index) not in replaced
                   for question in sprints.open_questions(sprint)):
                raise sprints.Refused(sprints.ROUND_OPEN)
        return sprint, checked

    def check_round(self, sprint_id: str, secret: str, round_: dict) -> int:
        """The question count of a round `ask_questions` would take now; nothing is written."""
        with self._ingest:
            return len(self._checked_ask(sprint_id, secret, round_, True)[1]["questions"])

    def ask_questions(self, sprint_id: str, secret: str, round_: dict) -> tuple[int, int]:
        """Append one `questions.asked` event for an approved sprint; the round's id and size."""
        with self._ingest:
            sprint, checked = self._checked_ask(sprint_id, secret, round_)
            payload = {"sprint_id": sprint_id, "goal": sprint.goal, "blocker": checked["blocker"],
                       "questions": checked["questions"]}
            if listed := sprints.round_pictures(checked):
                payload["pictures"] = listed
            appended = self.log.append([(QUESTIONS_ASKED, sprint.project_id, payload)])
            self._apply(appended)
            return appended[-1].seq, len(checked["questions"])

    def withdraw_question(self, sprint_id: str, secret: str, round_id: int, index: int) -> int:
        """Append one `question.withdrawn` event for an open question of the sprint; its seq."""
        with self._ingest:
            sprint = self._manager_sprint(sprint_id, secret)
            if not sprints.takes_questions(sprint):
                raise sprints.Refused(sprints.ENDED)
            others = [other for key, other in self._sprints.items() if key != sprint_id]
            asked = sprints.withdrawable(sprint, round_id, index, others)
            appended = self.log.append([(QUESTION_WITHDRAWN, sprint.project_id, {
                "sprint_id": sprint_id, "goal": sprint.goal, "round": round_id, "index": index,
                "question": asked.question})])
            self._apply(appended)
            return appended[-1].seq

    def post_notice(self, sprint_id: str, secret: str, notice: dict) -> int:
        """Append one `notice.posted` event for the sprint's project; its seq, the notice's id."""
        with self._ingest:
            sprint = self._manager_sprint(sprint_id, secret)
            others = [other for key, other in self._sprints.items() if key != sprint_id]
            checked = sprints.postable_notice(sprint, notice, others)
            appended = self.log.append([(NOTICE_POSTED, sprint.project_id, {
                "sprint_id": sprint_id, "goal": sprint.goal, "notice": checked})])
            self._apply(appended)
            return appended[-1].seq

    def post_owner_notice(self, project_id: str, text: str) -> int:
        """Append one owner `notice.posted` event for the project; its seq, the notice's id."""
        with self._ingest:
            checked = sprints.postable_owner_notice(
                project_id, text, project_id in self._states, self._sprints.values(),
                self._owner_notices)
            appended = self.log.append([(NOTICE_POSTED, project_id, {
                "poster": sprints.NOTICE_OWNER, "notice": checked})])
            self._apply(appended)
            seq = appended[-1].seq
            reserved = []
            if self._nudger is not None:
                for sprint_id, sprint in self._sprints.items():
                    if (sprint.project_id == project_id and sprints.takes_notices(sprint)
                            and self._reachable(sprint_id) is not None):
                        self._notice_due[sprint_id] = seq
                        if sprint_id not in self._nudging:
                            self._nudging.add(sprint_id)
                            reserved.append(sprint_id)
        for sprint_id in reserved:
            self._dispatch_notice_nudge(sprint_id)
        return seq

    def set_tailnet(self, tailnet: str | None) -> None:
        """Append one `sharing.tailnet` row: the guest door's tailnet name, or None for off."""
        with self._ingest:
            self._apply(self.log.append([(SHARING_TAILNET, None, {"tailnet": tailnet})]))

    def set_colleague(self, login: str, projects: tuple[str, ...]) -> None:
        """Append one `sharing.colleague` row: the login's whole project list (it replaces)."""
        with self._ingest:
            if any(project not in self._states for project in projects):
                raise guest.Refused("that project is not registered")
            self._apply(self.log.append([(SHARING_COLLEAGUE, None, {
                "login": login, "projects": list(projects)})]))

    def remove_colleague(self, login: str) -> None:
        """Append one `sharing.removed` row for a listed colleague."""
        with self._ingest:
            if login not in self._access.colleagues:
                raise guest.Refused("that colleague is not listed")
            self._apply(self.log.append([(SHARING_REMOVED, None, {"login": login})]))

    def withdraw_owner_notice(self, project_id: str, notice_id: int) -> int:
        """Append one owner `notice.withdrawn` event for an open owner notice; the notice's id."""
        with self._ingest:
            sprints.withdrawable_owner_notice(
                project_id, notice_id, self._owner_notices, self._sprints.values())
            appended = self.log.append([(NOTICE_WITHDRAWN, project_id, {
                "poster": sprints.NOTICE_OWNER, "notice": notice_id})])
            self._apply(appended)
            return notice_id

    def list_notices(self, sprint_id: str, secret: str) -> list[dict]:
        """The open notices of the sprint's project in id order; appends and publishes nothing."""
        with self._ingest:
            sprint = self._manager_sprint(sprint_id, secret)
            return sprints.project_notices(
                self._sprints.values(), sprint.project_id,
                owner=sprints.open_owner_notices(self._owner_notices, sprint.project_id))

    def withdraw_notice(self, sprint_id: str, secret: str, notice_id: int) -> int:
        """Append one `notice.withdrawn` event for an open notice of the sprint; the notice's id."""
        with self._ingest:
            sprint = self._manager_sprint(sprint_id, secret)
            others = [other for key, other in self._sprints.items() if key != sprint_id]
            sprints.withdrawable_notice(
                sprint, notice_id, others,
                owner_ids={n.notice_id for ns in self._owner_notices.values() for n in ns})
            appended = self.log.append([(NOTICE_WITHDRAWN, sprint.project_id, {
                "sprint_id": sprint_id, "goal": sprint.goal, "notice": notice_id})])
            self._apply(appended)
            return notice_id

    def answer_question(self, project_id: str, sprint_id: str, round_id: int, index: int,
                        choice: int | None, text: str | None) -> int:
        """Append one `question.answered` event, a message to the manager; its id."""
        with self._ingest:
            sprint = self._sprints.get(sprint_id)
            if sprint is None or sprint.project_id != project_id:
                raise sprints.Refused(sprints.NOT_OPEN)
            asked = next((question for question in sprint.questions
                          if (question.round_id, question.index) == (round_id, index)), None)
            if asked is not None and asked.withdrawn_at is not None:
                raise sprints.Refused(sprints.TAKEN_BACK)
            if not sprints.takes_questions(sprint):
                raise sprints.Refused(sprints.ENDED)
            if asked is None:
                raise sprints.Refused(sprints.UNKNOWN_QUESTION)
            if asked.answer is not None:
                raise sprints.Refused(sprints.ANSWERED_ALREADY)
            words = None
            if choice is not None:
                if not 0 <= choice < len(asked.options):
                    raise sprints.Refused(sprints.NOT_AN_OPTION)
                chosen = answer = asked.options[choice]
                if text is not None:
                    words = sprints.checked_message(text)
                elif chosen in asked.needs_words:
                    raise sprints.Refused(sprints.WORDS_NEEDED)
            else:
                chosen, answer = None, sprints.checked_message(text)
            appended = self.log.append([(QUESTION_ANSWERED, project_id, {
                "sprint_id": sprint_id, "goal": sprint.goal, "round": round_id, "index": index,
                "question": asked.question, "answer": answer, "chosen": chosen,
                "recommended": asked.recommended, "differs": chosen != asked.recommended,
                **({} if words is None else {"words": words})})])
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

    def _session_choice(self, profiles: frozenset[str], excluded: frozenset[str] | None = None,
                        pinned: object = _FOLDED) -> str | None:
        """Under the ingest lock: the profile a new session should use, over `profiles`.

        `excluded` is the set the choice is made over, the folded one when None; `pinned` is the
        pin it is made over, the folded one when left out and no pin when None.
        """
        return manager.session_profile(
            capacity.capacity_view(profiles - self._removing, self._capacity, self._clock(),
                                   self._signins,
                                   excluded=self._excluded if excluded is None else excluded,
                                   pinned=self._pinned if pinned is _FOLDED else pinned),
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
            if excluded and profile == self._pinned:
                raise exclusion.Refused(exclusion.PINNED)
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

    def set_pin(self, profile: str, pinned: bool) -> list[Event]:
        """Pin `profile` as the console's choice, or lift its pin; `pin.Refused` when it cannot.

        Under the ingest lock: a pin needs a profile among the directories as they are now, not
        excluded and not already pinned; an unpin needs the profile to be the pinned one. The
        choice file is written first, over the pin the change gives, so a failed write appends and
        publishes nothing; a failed append puts the file back to the choice over the old pin.
        """
        with self._ingest:
            profiles = self._read_profiles()
            if pinned:
                if profile not in profiles:
                    raise pin.Refused(pin.UNKNOWN)
                if profile in self._excluded:
                    raise pin.Refused(pin.EXCLUDED)
                if profile == self._pinned:
                    raise pin.Refused(pin.ALREADY_PINNED)
            elif profile != self._pinned:
                raise pin.Refused(pin.NOT_PINNED)
            choice = self._session_choice(profiles, pinned=profile if pinned else None)
            if self._choice_file is not None and choice != self._choice:
                manager.write_choice(self._choice_file, choice)
                self._choice = choice
                self._unreadable.discard("choice")
            try:
                appended = self.log.append([pin.entry(profile, pinned)])
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

    def _projects_dirs(self) -> list[Path]:
        """The transcript trees beside the registry directories, in order and without repeats."""
        found: list[Path] = []
        for directory in self._session_dirs():
            projects = Path(directory).parent / "projects"
            if projects not in found:
                found.append(projects)
        return found

    def poll_deliveries(self) -> list[Event]:
        """Append what the run journals of the live sessions show that the log does not, and publish."""
        folded = self._deliveries
        scanned = {sid: s for sid, s in self._sessions.items()
                   if s.state != sessions.ENDED and s.repo is not None}
        projects_dirs = self._projects_dirs()
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
        self._spend_profiles = spend.session_profiles(appended, self._spend_profiles)
        self._spend_questions = spend.question_sessions(appended, self._spend_questions)
        self._inbox = inbox_records(appended, self._inbox)
        self._health = read_states(appended, self._health)
        self._capacity = capacity.capacity_state(appended, self._capacity)
        self._signins = signin.signin_state(appended, self._signins)
        self._excluded = exclusion.excluded_profiles(appended, self._excluded)
        self._pinned = pin.pinned_profile(appended, self._pinned)
        self._signin_ends = signin_run.ended_state(appended, self._signin_ends)
        self._accounts_added = account_add.added_state(appended, self._accounts_added)
        self._trust_failures = folder_trust.failures(appended, self._trust_failures)
        self._registration = register.latest(appended, self._registration)
        self._adoptions = approve.adoptions(appended, self._adoptions)
        self._deferred = approve.deferrals(appended, self._deferred)
        self._pin_launches = pin.pin_launches(appended, self._pin_launches)
        self._deliveries = deliveries.delivery_states(appended, self._deliveries)
        self._moved = idle.last_moved(appended, self._moved)
        self._sprints = sprints.sprint_states(appended, self._sprints)
        self._withdrawn = sprints.withdrawn_ids(appended, self._withdrawn)
        self._owner_notices = sprints.owner_notices(appended, self._owner_notices)
        self._project_questions = project_question.asked_questions(appended, self._project_questions)
        self._activation_run = activation_run.fold(appended, self._activation_run)
        self._pending = sprints.pending_stops(appended, self._pending)
        self._access = guest.access_list(appended, self._access)
        self._moments = digest.keep([*self._moments, *new],
                                    digest.window_start(self._looked, self._now()))

    def retain(self) -> int:
        """One retention pass; when it removed rows, re-fold the digest's baselines and publish.

        The folded sessions, inbox records and project questions are rebuilt from the retained
        log, as a restart would, so a later change is judged against what the log still holds.
        """
        with self._ingest:
            removed = self.log.retain()
            events = self.log.events()
            if removed:
                self._sessions = sessions.session_states(events)
                self._use = manager.profile_use(events)
                self._spend_profiles = spend.session_profiles(events)
                self._inbox = inbox_records(events)
                self._capacity = capacity.capacity_state(events)
                self._signins = signin.signin_state(events)
                self._excluded = exclusion.excluded_profiles(events)
                self._pinned = pin.pinned_profile(events)
                self._signin_ends = signin_run.ended_state(events)
                self._accounts_added = account_add.added_state(events)
                self._trust_failures = folder_trust.failures(events)
                self._registration = register.latest(events)
                self._adoptions = approve.adoptions(events)
                self._deferred = approve.deferrals(events)
                self._pin_launches = pin.pin_launches(events)
                self._project_questions = project_question.asked_questions(events)
                self._derive_digest(events)
                self._publish()
            self._sweep_pictures(events)
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

    def poll_spend(self) -> None:
        """Read the transcripts, rebuild the spend view and publish it; see the module docstring."""
        projects_dirs: list[Path] = []
        for directory in self._session_dirs():
            projects = Path(directory).parent / "projects"
            if projects not in projects_dirs:
                projects_dirs.append(projects)
        today = datetime.fromtimestamp(self._clock(), timezone.utc).date()
        since = (today - timedelta(days=spend.WINDOW_DAYS - 1)).isoformat()
        self._spend.read(projects_dirs, since, self._ping_log())
        snapshot = self._spend.snapshot()
        with self._ingest:
            self._spend_view = spend.spend_view(
                snapshot, today=today.isoformat(),
                project_of=lambda repo: project_for(repo, self._states),
                profiles=self._spend_profiles, questions=self._spend_questions)
            self._publish()

    def _spend_step(self) -> None:
        try:
            self.poll_spend()
        except Exception as error:
            print(f"console: spend_poll_failed {type(error).__name__}: {error}",
                  file=sys.stderr)

    def _spend_loop(self) -> None:
        while not self._stop.wait(self._spend_seconds):
            self._spend_step()

    def poll_tracker(self) -> None:
        """One refresh of the inbox of every active project; see the module docstring."""
        if self._tracker is None:
            return
        now = self._clock()
        with self._ingest:
            waiting = {project_id for (project_id, _), record in self._inbox.items() if is_waiting(record.item)}
        for project_id, state in sorted(dict(self._states).items()):
            if self._stop.is_set():
                return
            if project_id not in waiting and not inbox.is_active(state.last_at, self._activity(state.root), now):
                continue
            slug = self._slug_of(state.root)
            if slug is None:
                continue
            generation = self._answer_generation
            began = utc_now()
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
                items = self._with_pictures(project_id, state.root, items)
                if self._stop.is_set():
                    return
                self._read_succeeded(project_id, items, generation, began)

    def _with_pictures(self, project_id: str, root: str, items: list[dict]) -> list[dict]:
        """Each verification item with its pictures attached; one that fails is kept without them."""
        roots = [Path(root), *self._screenshot_dirs]
        attached = []
        for entry in items:
            if "check_id" in entry:
                try:
                    with self._storing:
                        entry = inbox.attach_pictures(entry, roots, self.pictures_dir)
                except Exception as error:
                    print(f"console: picture_attach_failed {project_id} {type(error).__name__}: {error}",
                          file=sys.stderr)
            attached.append(entry)
        return attached

    def poll_activation(self) -> None:
        """One activation reading over the registered roots; see the module docstring."""
        if self._activation_reader is None:
            return
        with self._ingest:
            roots = sorted(state.root for state in self._states.values())
            self._activation_polls += 1
            began = self._activation_polls
        try:
            found = self._activation_reader(roots)
        except Exception as error:
            print(f"console: activation_failed {type(error).__name__}: {error}", file=sys.stderr)
            return
        with self._ingest:
            if began < self._activation_applied:
                return
            self._activation_applied = began
            before = self._shown_activation()
            if self._activation_after is not None and began > self._activation_after:
                self._activation_after = None
            if found != self._activation or self._shown_activation() != before:
                self._activation = found
                self._publish()

    def _shown_activation(self) -> activation.Activation | None:
        """The reading the page and Activate go by: none while a successful run awaits a reading begun after it."""
        return None if self._activation_after is not None else self._activation

    def poll_serve(self) -> None:
        """One reading of Tailscale Serve's status; see the module docstring (guest door)."""
        if self._serve_reader is None:
            return
        try:
            found = self._serve_reader()
        except Exception as error:
            print(f"console: serve_status_failed {type(error).__name__}: {error}", file=sys.stderr)
            found = None
        with self._ingest:
            self._serve_status = found
            self._publish()

    def activate(self, commit: str) -> None:
        """Start one activation of `commit`, the shown tip; see the module docstring."""
        with self._ingest:
            reading = self._shown_activation()
            if self._activator is None or not offers_activate(
                    reading, self._activation_run, self.received_ms()):
                raise sprints.Refused(ACTIVATE_NOTHING)
            if self._activating:
                raise sprints.Refused(ACTIVATE_RUNNING)
            if reading.commit != commit:
                raise sprints.Refused(ACTIVATE_MOVED)
            self._activating = True
            root = reading.root
        try:
            try:
                tip = self._activator.tip(root)
            except activation.ReadFailed:
                tip = None
            if tip is None:
                raise sprints.Refused(ACTIVATE_UNREADABLE)
            if tip != commit:
                raise sprints.Refused(ACTIVATE_MOVED)
        except BaseException:
            self._release_activation()
            raise
        try:
            started = self._activator.start(root, commit, self._record_started)
        except Exception as error:
            print(f"console: activation_run_failed {type(error).__name__}: {error}", file=sys.stderr)
            started = activation_run.Outcome(
                commit, False, f"the activation could not run ({type(error).__name__}: {error})",
                activation_run.NEXT_STEP.format(log=self._activation_log()))
        if isinstance(started, activation_run.Outcome):
            try:
                self._finish_activation(root, started)
            finally:
                self._release_activation()
            return
        self._wait_for_activation(started)

    def _record_started(self, run: activation_run.Run) -> None:
        """Persist the run's ownership; the activator calls it before a scope's launch, so no run lacks a record."""
        with self._ingest:
            self._apply(self.log.append([activation_run.started_row(run)]))

    def _release_activation(self) -> None:
        with self._ingest:
            self._activating = False

    def _activation_log(self) -> Path:
        if self._activator is not None:
            return self._activator.log_path
        return Path(self._store).parent / activation_run.LOG_FILE

    def _finish_activation(self, root: str, outcome: activation_run.Outcome) -> None:
        with self._ingest:
            self._apply(self.log.append([activation_run.finished_row(root, outcome)]))

    def _wait_for_activation(self, run: activation_run.Run) -> None:
        self._activate_thread = threading.Thread(
            target=self._await_activation, args=(run,), name=ACTIVATE_THREAD, daemon=True)
        self._activate_thread.start()

    def _await_activation(self, run: activation_run.Run) -> None:
        try:
            outcome = self._activator.wait(run, self._stop)
        except activation_run.Stopped:
            return
        except Exception as error:
            print(f"console: activation_wait_failed {type(error).__name__}: {error}", file=sys.stderr)
            return
        if outcome.ok:
            with self._ingest:
                self._activation_after = self._activation_polls
        self.poll_activation()
        try:
            self._finish_activation(run.root, outcome)
        except Exception as error:
            print(f"console: activation_finish_failed {type(error).__name__}: {error}",
                  file=sys.stderr)
            return
        self._release_activation()

    def _resume_activation(self) -> None:
        """Settle or keep waiting for a run the log still holds as running; see the module docstring."""
        last = self._activation_run
        if last is None or last.state != "running":
            return
        if last.tree is None:
            outcome = activation_run.Outcome(
                last.commit, False, activation_run.UNRECORDED_REASON,
                activation_run.NEXT_STEP.format(log=self._activation_log()))
            self._finish_activation(last.root, outcome)
        elif self._activator is not None:
            with self._ingest:
                self._activating = True
            self._wait_for_activation(activation_run.Run(last.root, last.commit, last.tree))

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

    def _read_succeeded(self, project_id: str, items: list[dict], generation: int,
                        began: str | None = None) -> None:
        with self._ingest:
            if project_id not in self._states:
                return
            items = [self._kept_answered(project_id, i, generation) for i in items]
            self._answered = {k: g for k, g in self._answered.items()
                              if k[0] != project_id or g > generation}
            appended = self.log.append([*inbox_changes(self._inbox, project_id, items),
                                        *health_change(self._health, project_id, True)])
            self._fold(appended)
            self._health[project_id] = ReadState(True, utc_now(), began)
            self._publish()

    def _kept_answered(self, project_id: str, item: dict, generation: int) -> dict:
        """A read that began before the item's answer finished does not undo the answer."""
        if item["answered"] or self._answered.get((project_id, item["key"]), 0) <= generation:
            return item
        record = self._inbox.get((project_id, item["key"]))
        return record.item if record is not None and record.item["answered"] else item

    def poll_adoptions(self) -> None:
        """One read of every adopted pull request still waiting; see the module docstring."""
        if self._forge is None:
            return
        with self._ingest:
            waiting = approve.waiting(self._adoptions)
        for entry in waiting:
            if self._stop.is_set():
                return
            slug = approve.pull_slug(entry["pull_request"])
            if slug is None:
                continue
            number = entry["pull_request"]["number"]
            try:
                state = self._forge.pull_request_state(slug, number, cancel=self._stop)
            except approve.Cancelled:
                return
            except Exception as error:
                print(f"console: adoption_poll_failed {entry['plan_id']} "
                      f"{type(error).__name__}: {error}", file=sys.stderr)
                continue
            if self._stop.is_set():
                return
            with self._ingest:
                found = self._adoptions.get(entry["plan_id"])
                if (found is None or found["step"] != "opened"
                        or found["pull_request"]["number"] != number
                        or found["pull_state"] == state):
                    continue
                appended = self.log.append(
                    [approve.pull_row(entry["plan_id"], number, found["pull_request"]["url"],
                                      state)])
                self._fold(appended)
                self._publish()
        self.register_merged()

    def register_merged(self) -> None:
        """One round of merged registrations; see the module docstring."""
        if self._adopter is None:
            return
        with self._ingest:
            plans = [found["plan_id"] for found in approve.enrolling(self._adoptions)
                     if found["plan_id"] not in self._enrolling]
        for plan_id in plans:
            if self._stop.is_set():
                return
            with self._ingest:
                found = self._adoptions.get(plan_id)
                if (self._closed or plan_id in self._enrolling or found is None
                        or not any(one["plan_id"] == plan_id
                                   for one in approve.enrolling(self._adoptions))):
                    continue
                entry = dict(found)
                self._enrolling.add(plan_id)
                self._publish()
            try:
                self._register_adoption(entry, retry=False)
            finally:
                with self._ingest:
                    self._enrolling.discard(plan_id)
                    if not self._closed:
                        self._publish()

    @staticmethod
    def _log_register_error(record: dict) -> None:
        print(f"console: adoption_register_error {json.dumps(record, sort_keys=True)}",
              file=sys.stderr)

    def _register_adoption(self, entry: dict, *, retry: bool) -> None:
        """Run the registration of one merged adoption, append its outcome, list the project."""
        root, plan_id = entry["root"], entry["plan_id"]
        where = {"stage": "register", "root": root, "plan_id": plan_id}
        try:
            report = self._adopter.register(
                root, cancel=self._stop, integration_branch=entry["base"], plan_id=plan_id)
        except register.RunFailed as failure:
            if self._stop.is_set():
                return
            self._log_register_error({**where, "failure": failure.kind,
                                      "cause": repr(failure.__cause__)})
            outcome = approve.run_outcome(root, failure.kind)
        except Exception as error:
            self._log_register_error({**where, "exception": type(error).__name__,
                                      "detail": str(error)})
            traceback.print_exception(error, file=sys.stderr)
            outcome = approve.run_outcome(root, type(error).__name__)
        else:
            project_id = report.get("project_id") if isinstance(report, Mapping) else None
            if not (isinstance(report, Mapping) and report.get("registered") is True
                    and isinstance(project_id, str) and project_id != ""):
                try:
                    json.dumps(report)
                    whole = report
                except (TypeError, ValueError):
                    whole = repr(report)
                self._log_register_error({**where, "report": whole})
            outcome = approve.registration_outcome(root, report)
        appended = False
        with self._ingest:
            if not self._closed:
                folded = self._adoptions.get(plan_id)
                current = folded.get("registration") if folded is not None else None
                same = (current is not None
                        and (current["result"], current["reason"])
                        == (outcome["result"], outcome["reason"]))
                if retry or not same:
                    row = approve.registration_row({
                        "plan_id": plan_id, "number": entry["pull_request"]["number"], **outcome})
                    self._fold(self.log.append([row]))
                    appended = True
                self._publish()
            listed = outcome["result"] == "registered" and not self._closed
        if listed:
            self.refresh()
        print(f"console: adoption_register_ended {plan_id} {outcome['result']}"
              f"{'' if appended else ' unchanged'}", file=sys.stderr)

    def retry_registration(self, plan_id: str) -> None:
        """Run a refused registration again on a tracked worker; refusals are `sprints.Refused`."""
        if self._adopter is None:
            raise sprints.Refused(register.UNAVAILABLE)
        with self._ingest:
            found = self._adoptions.get(plan_id)
            if plan_id in self._enrolling:
                name = register.name_of(found["root"]) if found is not None else plan_id
                raise sprints.Refused(register.running(name))
            if (found is None or found["step"] != "opened" or found["pull_state"] != "merged"
                    or found.get("registration") is None
                    or found["registration"]["result"] != "refused"):
                raise sprints.Refused(approve.NOT_REFUSED)
            entry = dict(found)
            self._enrolling.add(plan_id)
            self._publish()
        try:
            self._approval_dispatch(lambda: self._retry_job(entry))
        except BaseException:
            with self._ingest:
                self._enrolling.discard(plan_id)
                self._publish()
            raise

    def _retry_job(self, entry: dict) -> None:
        try:
            self._register_adoption(entry, retry=True)
        except Exception as error:
            print(f"console: adoption_register_failed {type(error).__name__}", file=sys.stderr)
        finally:
            with self._ingest:
                self._enrolling.discard(entry["plan_id"])
                if not self._closed:
                    self._publish()

    def _adopt(self) -> None:
        while True:
            try:
                self.poll_adoptions()
            except Exception as error:
                print(f"console: adoption_poll_loop_failed {type(error).__name__}: {error}",
                      file=sys.stderr)
            if self._stop.wait(self._adoption_seconds):
                return

    def poll_movement(self) -> None:
        """One read of the movement of every project with a running sprint; see the module docstring."""
        with self._ingest:
            running = {sprint.project_id for sprint in self._sprints.values()
                       if sprints.ended_at(sprint) is None}
            roots = {project_id: state.root for project_id, state in self._states.items()
                     if project_id in running}
            belonging = {project_id: sprint_sessions_of(
                project_id, self._sprints.values(), self._sessions.values(), self._deliveries,
                self._states) for project_id in roots}
            nudged = {project_id: sprint_nudge_replies(
                project_id, self._sprints.values(), self._sessions.values(), self._states)
                for project_id in roots}
            absent = {project_id: sprint_absent_managers(
                project_id, self._sprints.values(), belonging[project_id]) for project_id in roots}
            dropped = [project_id for project_id in self._movement if project_id not in roots]
            for project_id in dropped:
                del self._movement[project_id]
            if dropped and not self._closed:
                self._publish()
        registry = None
        for project_id, root in sorted(roots.items()):
            if self._stop.is_set():
                return
            pattern = self._branch_pattern(root)
            try:
                local = self._local_reader(root, pattern)
            except Exception as error:
                print(f"console: movement_local_failed {project_id} {type(error).__name__}: {error}",
                      file=sys.stderr)
                local = movement.LocalReading((), False)
            belong = belonging[project_id]
            if belong or absent[project_id]:
                try:
                    targets = ()
                    if belong:
                        if registry is None:
                            registry = sessions.read_session_registry(self._session_dirs())
                        targets = tuple(
                            movement.SessionTarget(
                                sid, registry[sid].pid if sid in registry else None, belong[sid],
                                nudged[project_id].get(sid, ()))
                            for sid in sorted(belong))
                    targets += tuple(
                        movement.SessionTarget(sid, None, absent[project_id][sid], (), True)
                        for sid in sorted(absent[project_id]))
                    at = int(self._clock() * 1000)
                    readings = self._session_reader(self._projects_dirs(), targets)
                    local = dataclasses.replace(local, sessions=tuple(readings), sessions_ms=at)
                except Exception as error:
                    print(f"console: movement_sessions_failed {project_id} "
                          f"{type(error).__name__}: {error}", file=sys.stderr)
            pulls = None
            slug = self._slug_of(root) if self._pull_reader is not None else None
            if slug is not None:
                try:
                    pulls = answer.with_retries(
                        lambda: self._pull_reader(slug, pattern, cancelled=self._stop.is_set),
                        clock=self._monotonic, sleep=self._write_sleep)
                except Exception as error:
                    if (isinstance(error, ForgeError) and error.code == "cancelled") or self._stop.is_set():
                        return
                    print(f"console: movement_read_failed {project_id} "
                          f"{type(error).__name__}: {error}", file=sys.stderr)
            if self._stop.is_set():
                return
            key = f"release {project_id}"
            if local.invalid:
                self._warn_once(key, f"console: movement_release_invalid {project_id} "
                                     f"{' '.join(local.invalid)}")
            else:
                self._unreadable.discard(key)
            with self._ingest:
                if project_id not in self._states or self._closed:
                    continue
                live, locking = self._live_issues(project_id)
                self._movement[project_id] = movement.merged(
                    self._movement.get(project_id), pulls, int(self._clock() * 1000), local,
                    locking=locking, live=live)
                self._publish()

    def _live_issues(self, project_id: str) -> tuple[frozenset[int], frozenset[int]]:
        """Under the ingest lock: the issues of the runs in sessions not ended, and those of them sitting in a lock step."""
        sids = {sid for sid, session in self._sessions.items()
                if session.state != sessions.ENDED and session.repo is not None
                and project_for(session.repo, self._states) == project_id}
        stages = [stage for (sid, _), state in self._deliveries.items() if sid in sids
                  for stage in state.issues]
        return (frozenset(stage.issue for stage in stages),
                frozenset(stage.issue for stage in stages if stage.locking))

    def _move(self) -> None:
        while True:
            try:
                self.poll_movement()
            except Exception as error:
                print(f"console: movement_poll_failed {type(error).__name__}: {error}",
                      file=sys.stderr)
            if self._stop.wait(self._movement_seconds):
                return

    def _track(self) -> None:
        while True:
            try:
                self.poll_tracker()
            except Exception as error:
                print(f"console: tracker_poll_failed {type(error).__name__}: {error}", file=sys.stderr)
            if self._stop.wait(self._tracker_seconds):
                return

    def _serve_loop(self) -> None:
        while True:
            self.poll_serve()
            if self._stop.wait(self._serve_seconds):
                return

    def _activate(self) -> None:
        while True:
            try:
                self.poll_activation()
            except Exception as error:
                print(f"console: activation_poll_failed {type(error).__name__}: {error}",
                      file=sys.stderr)
            if self._stop.wait(self._activation_seconds):
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
        self._resume_activation()
        self._watcher = threading.Thread(target=self._watch, name=WATCH_THREAD, daemon=True)
        self._watcher.start()
        self._session_poller = threading.Thread(
            target=self._poll_loop, name=SESSION_THREAD, daemon=True)
        self._session_poller.start()
        if self._tracker is not None:
            self._tracker_thread = threading.Thread(
                target=self._track, name=TRACKER_THREAD, daemon=True)
            self._tracker_thread.start()
        if self._activation_reader is not None:
            self._activation_thread = threading.Thread(
                target=self._activate, name=ACTIVATION_THREAD, daemon=True)
            self._activation_thread.start()
        if self._forge is not None:
            self._adoption_thread = threading.Thread(
                target=self._adopt, name=ADOPTION_THREAD, daemon=True)
            self._adoption_thread.start()
        if self._pull_reader is not None:
            self._movement_thread = threading.Thread(
                target=self._move, name=MOVEMENT_THREAD, daemon=True)
            self._movement_thread.start()
        self._retention_thread = threading.Thread(
            target=self._retain_loop, name=RETENTION_THREAD, daemon=True)
        self._retention_thread.start()
        self._digest_thread = threading.Thread(
            target=self._expire_loop, name=DIGEST_THREAD, daemon=True)
        self._digest_thread.start()
        self._spend_thread = threading.Thread(
            target=self._spend_loop, name=SPEND_THREAD, daemon=True)
        self._spend_thread.start()
        if self._prober is not None or self._signin_reader is not None:
            self._probe_thread = threading.Thread(
                target=self._probe_loop, name=PROBE_LOOP_THREAD, daemon=True)
            self._probe_thread.start()
        if self._signin_runs is not None:
            self._signin_thread = threading.Thread(
                target=self._signin_loop, name=SIGNIN_THREAD, daemon=True)
            self._signin_thread.start()
        if self._trust_at_start:
            self._trust_start_thread = threading.Thread(
                target=self._grant_at_start, name=TRUST_START_THREAD, daemon=True)
            self._trust_start_thread.start()
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="console-http", daemon=True)
        self._thread.start()
        if self._guest_server is not None:
            self._guest_thread = threading.Thread(
                target=self._guest_server.serve_forever, name="console-guest-http", daemon=True)
            self._guest_thread.start()
        if self._serve_reader is not None:
            self._serve_thread = threading.Thread(
                target=self._serve_loop, name=SERVE_THREAD, daemon=True)
            self._serve_thread.start()

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
        if self._activation_thread is not None:
            self._activation_thread.join()
        if self._activate_thread is not None:
            self._activate_thread.join()
        if self._adoption_thread is not None:
            self._adoption_thread.join()
        if self._movement_thread is not None:
            self._movement_thread.join()
        if self._retention_thread is not None:
            self._retention_thread.join()
        if self._digest_thread is not None:
            self._digest_thread.join()
        if self._spend_thread is not None:
            self._spend_thread.join()
        if self._serve_thread is not None:
            self._serve_thread.join()
        if self._probe_thread is not None:
            self._probe_thread.join()
        if self._signin_thread is not None:
            self._signin_thread.join()
        if self._trust_start_thread is not None:
            self._trust_start_thread.join()
        if self._signin_runs is not None:
            self._signin_runs.close()
        with self._ingest:
            workers = list(self._probe_workers)
        for worker in workers:
            worker.join()
        with self._ingest:
            workers = list(self._approval_workers)
        for worker in workers:
            worker.join()
        with self._ingest:
            while self._project_questions_open:
                self._project_questions_done.wait()
            workers = list(self._project_question_workers)
        for worker in workers:
            worker.join()
        if self._thread is not None:
            self._server.shutdown()
        self._server.server_close()
        if self._guest_server is not None:
            if self._guest_thread is not None:
                self._guest_server.shutdown()
            self._guest_server.server_close()
        with self._ingest:
            while self._grants_running:
                self._grants_done.wait()
            self.log.close()
