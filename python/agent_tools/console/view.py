"""The console's view of the fleet: pure functions from events to what the page shows.

Nothing here reads a clock, a file or the environment. `project_states` folds
the event log onto per-project state; `registry_changes` turns a difference
between that state and the fleet registry into events to append; `derive_view`
orders and folds the state into the wire view; `encode_view` renders it as one
line of JSON.

Events: `project.registered` (payload `{"root": ...}`) sets a project, keeping
its open work; `project.unregistered` removes it; a project question's asked or answered event
(#1178) changes nothing, so a question or follow-up neither reorders projects nor resets a
project's untouched age; any other event that names a
project updates only that project's last sequence and time; an event naming no
project, or a project not registered, is ignored.

Sessions: only a listed session counts. A session that has ended (a tombstone)
or whose `repo` is `None` (outside any git repository) is not listed under any
project, makes no unmanaged entry and counts in no line. A listed session
belongs to the project whose `root` equals its `repo` (`project_for`), else to
the unmanaged entry for its `repo`. Sessions never touch the statement or
`project_count`: a waiting session is not an inbox item.

Inbox events name a project and carry the tracker's owner-action items. `inbox.seen`
(payload: an item, with its `key`) records the item with `waiting_since` and
`updated_at` both the event's time, and `answered_at` the event's time when the item is
answered, else null; `inbox.changed` (payload: the item) replaces the item and
`updated_at` but keeps `waiting_since` (an unknown key is treated as seen); its `answered_at`
is the event's time when the new item is answered and the old one was not, the old
`answered_at` when both are answered, null when the new item is not answered, so it moves only
when the item turns answered and a later change of any other member keeps it; `inbox.gone`
(payload `{"key"}`) removes the item; `project.unregistered` removes every item of that
project; an inbox event whose payload has no string `key` is ignored. `inbox.health`
(payload `{"ok": true}` or `{"ok": false, "read_at": <time of the last good read> | null}`)
is logged only when a project's tracker read changes between good and failed: `ok` true
folds to a read at the event's time, `ok` false to a failed read at `read_at`, a payload
whose `ok` is not a bool is ignored, `project.unregistered` removes the project's health.
Every inbox event also moves its registered project's last sequence and time.

Ordering and folding: a project is active when `open_work > 0`, it has a
listed session, it has a shown sprint or it has a waiting line of its own (`waits` of its entry), and
quiet otherwise. Each group is sorted by newest `last_seq` first, then `project_id`.
The entries are the active projects, then the quiet projects, except that more
than `FOLD_AFTER` quiet projects are replaced by one `quiet_group` entry.

Wire format, one object:

    {"statement": {"inbox_items": <open items>, "headline": "<headline>",
                   "sentence": "<sentence>", "stale": <bool>},
     "new_replies": [{"project_id", "sprint_id", "title", "message_id", "reply_at"}, ...],
     "new_replies_text": "<text>" | null,
     "capacity": {"tight": <bool>, "all_out": <bool>, "resumes_at": <ISO time> | null,
                  "no_reading": "<n> with no reading yet" | null,
                  "profiles": [<profile capacity>, ...]},
     "inbox": {"open": [<inbox item>, ...], "answered": [<inbox item>, ...]},
     "project_count": <int>,
     "entries": [<project entry> | <group entry>, ...],
     "unmanaged": [<unmanaged entry>, ...],
     "recent_projects": ["<project id>", ...],
     "digest": <digest> | null,
     "managers": <bool>,
     "pin": <pin note> | null,
     "pin_launches": ["<profile>", ...],
     "profile_sessions": {"<profile>": <int>, ...},
     "unstopped": [{"project_id", "sprint_id", "title", "text", "failed_at"}, ...],
     "activation": <activation line> | null,
     "spend": <spend view> | null}

`activation` is the one line the page shows about activating this host (#1114, #1193,
ADR-console-043): `{"text", "state": "pending" | "running" | "activated" | "failed", "commit": <40 hex>,
"root", "activate": <bool>}`. `pending` is a reading (the `activation.py` `Activation`) with a non-empty
`changed`; `activation_run` is the newest run (`activation_run.LastRun`). The first match wins: a
`running` run is `running` (ACTIVATING_TEXT, its commit, no Activate); a settled run is `activated`
(ACTIVATED_TEXT) or `failed` (ACTIVATION_FAILED_TEXT with its reason and next step) when a change is
pending for that very commit, or when nothing is pending and it finished less than OUTCOME_MS before
`now_ms`, and only a `failed` one for the pending commit has `activate` true; a pending change is
`pending` (ACTIVATION_TEXT, the reading's commit, `activate` true); otherwise null. Every text shows
the commit as its first 12 characters. The member is on every view. It is a line beside the statement,
not an inbox item: it is not counted in `inbox_items` and never changes the headline, the sentence
or `stale`.

`spend` is the `spend.spend_view` the caller passes (members defined in `spend.py`), null when none;
it is a reading beside the statement, never counted in `inbox_items` (#1134).

`digest` is what changed since the owner last looked (see `digest.py`):
`{"since": <last look> | null, "first_visit": <bool>, "recent": [<moment>, ...],
"earlier": [<moment>, ...], "omitted": <int>}` with a moment `{"at", "kind", "sentence"}`; it is
null when `derive_view` is given none.

The headline is "1 thing needs you" or "<n> things need you" for open items (a waiting brief is one,
and so is each open question of the registration's plan, and each retry, apply, confirm,
failure or trust card, see below), else
`ALL_OUT_HEADLINE` when every profile is out of usage, else `STALE_HEADLINE` when a registered
project's tracker cannot be read, else "Nothing needs you". The sentence is `ALL_OUT_SENTENCE`
when every profile is out of usage, else `STALE_SENTENCE` naming those projects when any is
stale, else `BRIEF_SENTENCE` when any brief is open, else `MANAGER_SENTENCE` when a sprint is
stalled, else `FAILED_START_SENTENCE` when a manager failed to start, else `PROGRESS_SENTENCE`
when a manager stopped making progress, else `SIGNIN_SENTENCE`
when a profile's sign-in asks, else `ADOPTION_SENTENCE` when an adoption's pull request is ready to
merge, else `QUESTION_SENTENCE` when any manager question is open, else
`REGISTER_SENTENCE` when a plan question, a retry, apply, confirm, failure or trust item offers an option (the page
can answer it), else
`REGISTER_TYPE_SENTENCE` when a plan question takes a typed answer (`text`), else
`CHOOSE_SENTENCE` when an open item is a decision with questions (the page can answer it), else
`ANSWER_SENTENCE` when an open item has answers (a verification prompt the page can answer), else
`REGISTER_STEP_SENTENCE` when only plan questions with no offered answer are open, else
`NEEDS_SENTENCE` when something is open, else, with no project registered, `ADOPTING_SENTENCE` ("An adoption is
under way; nothing is waiting on you.") when the view's `registration` (below) is running or holds
an adoption, else the registered-project count. The
all-out promotion never changes `inbox_items`, and the statement keeps exactly its four keys.
`capacity` is the `capacity_view` the caller passes (`capacity.py` defines its members), else the
empty capacity, the same bytes as `capacity_view` over no profile. `stale` is true
when any registered project's last read failed. An inbox item is every stored member
except `question`, plus `{"type": "inbox_item", "waiting_since", "stale", "read_at",
"headline", "more_questions", "answered_at"}`: `stale` is that project's failed read, `read_at`
the time of its last good read (the item's last update when the read time is unknown),
`headline` and `more_questions` come from `item_headline` (the first question of an item that
has questions and the count of the others; `UNREAD_DECISION` for a decision with none; else
the stored `question`), and `answered_at` is the record's (null while open). The stored
`question` is no wire member (a decision's is a fixed sentence). Only items of
registered projects are shown. Open tracker items are sorted by most held work first, then
`waiting_since`, then `key`; answered items are listed apart, never counted, by
`waiting_since` then `key`.

A waiting check (#1129) is an open inbox item of a shown project whose `wait` member is a mapping
(`is_waiting`, which takes no time): an owner check that is not due, or whose wording states a wait its
verify block does not date. It is a line and nothing else: it is no card, it is not in `inbox.open`,
and it changes no `inbox_items`, headline, sentence, sprint `waiting` or `ball`, and no `checks` line
(a waiting item is taken out before `sprint_checks` reads the records, ADR-console-051). Its wait entry has the
item's `key`, `issue` and `url`; a dated wait (`reason` `not_before` or `window`, with a string `until`)
has that `until` and its `what` as `text`, every other wait has `until` null and the `WAIT_TEXT` of its
reason (`unknown` for any other): `window_opening`, `not_released`, `not_deployed`, `ci_not_passed`,
`unknown`, `no_when` and `due`. The line sits in the `waits` of the first shown sprint of its project,
newest `stated_seq` first, that has not ended (no `ended_at`) and whose report names its issue (its
`issues` or `inbox`, as `waiting` reads them), else in its project entry's `waits`: the page draws an
ended sprint as a finished line that reads no `waits`. A finished sprint's `waits` is `[]`, and every list is
sorted by `key`. No clock ends a wait here: `now_ms` is the host's, and a wait changes only when a
tracker read, which evaluates with the forge's clock (`inbox.read_items`), changes or drops the item's
`wait`, so a dated line whose day has passed stays until that read. A project with a `waits` line is
active, never quiet and never folded into the quiet group.

A waiting brief (a shown sprint whose `brief` is not None and whose decision is `none`) is one
entry of `inbox.open`, before every tracker item, ordered by `waiting_since` then `sprint_id`, and
counts in `inbox_items` and the headline. Its entry is

    {"type": "inbox_item", "reason": "brief", "key": "brief/<sprint id>", "project_id",
     "sprint_id", "title", "version": <int>, "brief": {"title", "done", "excluded", "slices",
     "risks", "asks"}, "pictures": [{"id", "line", "pair"}], "answered": false,
     "waiting_since": "<time the brief was sent>"}

`pictures` is `_picture_entries(brief.pictures)`, `[]` for a brief with none, each line cut to
`MAX_PICTURE_LINE_CHARS` and never refused; `brief` holds the six parts only.

Every item names its sprint by `title` (`sprints.sprint_title`: the brief's title, else the goal's
first sentence, at most 60 characters) and none carries the goal: the sprint entry is the only
place the goal text is on the wire (ADR-console-027).

A stalled sprint (a shown sprint whose `stalled` is not None, `sprints.py`) is one entry of
`inbox.open`, after the briefs and before every tracker item, ordered by `waiting_since` then
`sprint_id`, and counts in `inbox_items` and the headline. Its entry is

    {"type": "inbox_item", "reason": "manager", "key": "manager/<sprint id>", "project_id",
     "sprint_id", "title", "headline": "managers keep failing on <title>", "last_reason": <str>,
     "answered": false, "waiting_since": "<time the sprint stalled>"}

`MANAGER_SENTENCE` says what the page offers. The sentence precedence is all out, stale, briefs, stalls,
then the existing ones. A restart or a takeover adds no item, only a stall does.

A shown, drafted sprint whose manager failed to start (#1182: `sprints.failed_start`, the one rule
the block's Retry and the service's retry gate read too: a `failed` manager row that is not a
takeover's, no brief, no listed session of its own, `managers` true, not stalled and not stopping)
is one entry of `inbox.open`, after the stalls and before the progress entries, ordered by
`(waiting_since, sprint_id)`, and counts in `inbox_items` and the headline. Its entry is

    {"type": "inbox_item", "reason": "failed_start", "key": "failed-start/<sprint id>",
     "project_id", "sprint_id", "title", "headline": "The manager for <title> failed to start.",
     "last_reason": <manager.plain_reason of the failure>, "answered": false,
     "waiting_since": "<time the manager failed>"}

`FAILED_START_SENTENCE` says what the page offers. The sentence precedence is all out, stale,
briefs, stalls, failed starts, then the progress ones below. A later `manager.started`, a
withdrawal, a brief, a listed own session or a takeover removes the card.

A shown sprint whose `no_progress_at` is set (#929, a manager that stopped making progress) is
one entry of `inbox.open`, after the stalls and the failed starts and before the questions, ordered by
`(no_progress_at, sprint_id)`, and counts in `inbox_items` and the headline. Its entry is

    {"type": "inbox_item", "reason": "progress", "key": "progress/<sprint id>", "project_id",
     "sprint_id", "title", "headline": "the manager has stopped making progress on <title>",
     "last_status": <report status> | null, "answered": false,
     "waiting_since": "<time the stop was noticed>"}

`PROGRESS_SENTENCE` says what the page offers. The sentence precedence is all out, stale, briefs,
stalls, progress, sign-in, questions, then the existing ones.

A profile whose sign-in asks (#1010: `capacity["profiles"][i]["signin"]["ask"]` is true, a read of
`entry.get("signin")` so a capacity without that member shows none) is one entry of `inbox.open`,
after the progress entries and before the questions, ordered by profile, and counts in
`inbox_items` and the headline. Its entry is

    {"type": "inbox_item", "reason": "signin", "key": "signin/<profile>", "project_id": null,
     "profile": "<profile>", "headline": "Sign in to <profile>" | "Sign in to <profile> again",
     "action": "signin",
     "run": <signin_runs.get(profile)> | null, "signin": <the entry's signin>,
     "answered": false, "waiting_since": <signin["since"]>}

The headline is `SIGNIN_HEADLINE` ("... again") when the entry's `signin["ever_signed_in"]` is
true and `SIGNIN_FIRST_HEADLINE` ("Sign in to <profile>") otherwise, a profile never signed in
having nothing to sign in to again; the item's `signin` carries `ever_signed_in`.

`SIGNIN_SENTENCE` says what the page offers: its Sign in action, which posts the profile to
`/api/signin`, then a code to `/api/signin-code` or a cancel to `/api/signin-cancel`. The item
carries no terminal command. `run` is the profile's latest sign-in run from the `signin_runs`
argument, `{"state": "running" | "signed_in" | "failed" | "timed_out" | "cancelled", "at":
<ISO string> | null, "attempt": <positive int>}`, and the view's top-level `signin_runs` member
is that mapping, `{profile: run}`, copied (an empty object when none is given). The sign-in
link is never in the view: the page holds it from the start answer, the add answer and the
link answer of `POST /api/signin-link` alone, each a guarded page request.

An adoption whose pull request is ready to merge (#1054, `approve.inbox_entries`) arrives through the
`adoption_items` argument, one mapping each, and is one entry of `inbox.open`, copied, after the
sign-in entries and before the questions, in the order given. It counts in `inbox_items` and the
headline and is not filtered by the registered projects: the adoption's project is not registered
yet. Its entry is

    {"type": "inbox_item", "reason": "adoption", "key": "adoption/<plan id>",
     "project_id": "<the contract's project id>" | null, "name": "<the checkout's name>",
     "headline": "The adoption of <project> is ready to merge", "url": "<pull request url>",
     "number": <pull request number>, "answered": false, "waiting_since": "<time the pull request
     was first read as ready>"}

`ADOPTION_SENTENCE` says what the page offers: opening the pull request, where the owner merges it.
It follows `SIGNIN_SENTENCE` and precedes `QUESTION_SENTENCE` in the precedence.

The top-level `accounts_added` member (#1027) is the sorted, de-duplicated list of the profile names
the owner added from the page and the retained log still holds, from the `accounts_added` argument
(`account_add.added_state`; an empty list when none is given).

The top-level `registration` member (#1052, ADR-console-028, #1053, ADR-console-029) is the entry
`register.view_entry` gives, copied, from the `registration` argument, and null when none is given:
`{"root", "name", "project_id", "status": "running" | "done", "result", "outcome", "headline",
"lines", "note", "at", "plan_id", "state", "questions", "refusal", "line", "refused", "draft",
"draft_more", "adoption", "approve", "cancel"}`, the owner's latest registration of a repository from the page
(twenty-one keys), with the plan's plain open questions and, when the plan refused the last answer, the
refusal's text and the question it answered (`refused`, `{"id", "subject"}`); `draft` is the drafted
contract's lines (`contract_draft.shown`, ADR-console-031) when the latest row holds a draft, else
null; `draft_more` is the counted line for the shown settings outside the main ones
(`contract_draft.more_line`), null when there are none or no draft. `adoption` is the approved adoption's `approve.entry` (#1054) and `approve` the action the
page offers (`approve`, `retry` or null); with an adoption the `lines` are `[]`, `draft` and `draft_more` are
null, and the `line` is the adoption's headline, then its note (ADR-console-037).
The member is the entry given, copied, under three rules (#1085, ADR-console-035). It is null when
the given entry is null, or is `done` and its `root` is the root of a registered project: the
project's entry and the digest say so, and a finished result of a root now registered has nothing
left to say. Else, when any retry, apply, confirm or failure item has a reason in `ASKING_REASONS`
and the entry's `root`, a card already says what is asked, so the entry's `line` is
`NEEDS_LINE` ("Register <name>: needs you"), its `lines` are `[]` and its `note`, `adoption`,
`draft` and `draft_more` null. Otherwise it is a plain copy. A plan question (reason `register`) never reduces the line. `cancel` (#1088) is
true when the page may offer Cancel registration (`register.cancellable`, no run under way); the reduced entry keeps it.

The top-level `pin` member (#1029) is the pin note `pin.note` gives, copied, from the `pin`
argument, and null with no pin. The top-level `pin_launches` member is the sorted list of profiles
under which a new session or manager started while the owner's pin of that profile was in force,
from the `pin_launches` argument (`pin.pin_launches` over the retained log; an empty list when none
is given).

The top-level `profile_sessions` member (#1030) maps each profile of the capacity view to the number of
sessions under it that have not ended (`{}` for an empty capacity; a session with no profile counts for
none): the page states it before a removal, since a running session keeps running.

A sprint's `state` is `quota` ("waiting on quota until") when its manager is `started` and the
capacity view holds an `out` entry for the manager's profile (`manager.quota_wait`), unless the
sprint is waiting on you, closing (fresh), done, drafting, stopping or stopped; `state_until` is
then that entry's `out_until` (null when unknown), else null. Digest and bring-back read the
state without the quota. `view` reads no clock.

`BRIEF_SENTENCE` ("Press Enter to approve the brief, or write a reply to ask for changes.") says
what the page offers. An approved or changes-asked brief is no inbox item; only registered
projects' briefs appear, as for sprints.

Each open question of a shown sprint (`sprints.open_questions`; a registered project, as briefs) is
one entry of `inbox.open` too, after the briefs and before every tracker item, ordered by
`(at, sprint_id, round, index)`, and counts in `inbox_items` and the headline; an answered question
is none. Its entry is

    {"type": "inbox_item", "reason": "question", "key": "question/<sprint id>/<round>/<index>",
     "project_id", "sprint_id", "title", "round": <int>, "index": <int>, "blocker": <bool>,
     "blocks": "<text>", "headline": "<ask>", "context": "<text>" | null, "more_questions": 0,
     "questions": [{"question": "<ask>", "options": [<str>, ...], "chosen": null,
                    "recommended": "<option>", "recommended_index": <int>}],
     "pictures": [{"id": "<picture id>", "line": "<text>", "pair": "before" | "after" | null}],
     "items": [], "answers": [], "answered": false, "waiting_since": "<time it was asked>"}

The texts are shown cut, never refused, though a round logged before the limits can exceed them
(ADR-console-027): the ask and the headline to `MAX_ASK_CHARS` (140), `context` to
`MAX_CONTEXT_CHARS` (400), each option and the recommendation to `MAX_OPTION_CHARS` (80), each
with `sprints.cut`; each picture's line to `MAX_PICTURE_LINE_CHARS` (140), and `pictures`
is `[]` when the question has none. `recommended_index` is the recommendation's index among the
logged options, so it names the right option even when two cut options read the same; the owner's
answer is still an option index into the full logged options.

`QUESTION_SENTENCE` ("Choose an option with its number and press Enter, or answer in your own
words.") says what the page offers.

Each open question of a done registration's plan (#1066, ADR-console-029 D10; `registration.status`
is `done` and `registration.questions` is not empty) is one entry of `inbox.open` too, after the
manager questions and before every tracker item, in the plan's order, and counts in `inbox_items`
and the headline; a running registration, one with no question and none at all add nothing. Its
entry is

    {"type": "inbox_item", "reason": "register", "key": "register/<plan id>/<index>",
     "project_id": null, "root", "name", "title": "Register <name>", "plan_id", "id", "subject",
     "headline": "<ask>", "why": "<text>" | null, "refusal": "<text>" | null,
     "more_questions": 0, "text": <bool>, "placeholder": "<words>" | null,
     "questions": [] | [{"question": "<ask>", "options": ["<label>", ...], "chosen": null,
                         "recommended": null, "recommended_index": null}],
     "values": ["<value>", ...], "items": [], "answers": [], "answered": false,
     "waiting_since": "<the registration's at>"}

`key` is the plan id and the question's index, so an answer that makes a new plan replaces the
items; `options` are the plan's labels and `values` the values they send, in order, and nothing is
preselected. A question the plan offers no answer to has `questions` `[]`, `values` `[]` and its
`why`, and still counts; `text` is true for a drafted-contract question the owner answers by typing
(a text question with no options is still an item, ADR-console-031) and `placeholder` is
`contract_draft.placeholder(subject)`, the words that card's empty box shows, for a `contract-draft`
text question and null on every other. `refusal` is the registration's refusal on the question
`registration.refused` names and null on every other. The items are never cut and carry no `stale`
or `read_at`. `REGISTER_SENTENCE` ("Choose an option with its number and press Enter.") says what
the page offers; `REGISTER_TYPE_SENTENCE` ("Type the answer on its card and press Enter.") stands
when no register item offers options but one takes a typed answer; `REGISTER_STEP_SENTENCE` ("Each one says what to do next.") stands when no plan
question offers an answer and nothing else is open.

Each retry item a caller passes (`retry_items`; #1055, ADR-console-028 D10) is one entry of
`inbox.open` too: a registration the remote refused after its adoption merged, offering the one
option `Retry`. It is copied as given and not filtered by the registered projects (the project is
not registered yet), sits after the manager questions and before the plan questions, in the order
given, and counts in `inbox_items` and the headline. Its entry is

    {"type": "inbox_item", "reason": "register_retry", "key": "register-retry/<plan id>/<at>",
     "project_id": null, "root", "name", "title": "Register <name>", "plan_id", "id": null,
     "subject": null, "headline": "<name> was not registered: <reason>.", "why": "<note>",
     "refusal": null, "more_questions": 0,
     "questions": [{"question": "<headline>", "options": ["Retry"], "chosen": null,
                    "recommended": null, "recommended_index": null}],
     "values": ["retry"], "items": [], "answers": [], "answered": false,
     "waiting_since": "<at>"}

While one is open the sentence is `REGISTER_SENTENCE`, at the slot it already has (after
`QUESTION_SENTENCE`, before `CHOOSE_SENTENCE`). Without `retry_items` the view is unchanged.

Each apply item a caller passes (`apply_items`; #1073, ADR-console-030) is one entry of
`inbox.open` too: the owner's approval to apply a ready adoption, as the question card
`approve.apply_items` builds. It has reason `register_apply` and the shape of a retry item, with
`lines` (what applying will do, from the plan), `text` false and `values` led by the apply (or
retry) value, then `not_now`. It is copied as given and not filtered by the registered projects,
sits right after the plan questions and before the tracker items, in the order given, and counts
once in `inbox_items` and the headline; it is never cut. While one is open the sentence is
`REGISTER_SENTENCE`, in the slot the retry items use. Without `apply_items` the view is unchanged.

Each confirm item a caller passes (`confirm_items`; #1078, ADR-console-034) is one entry of
`inbox.open` too: the Register card of an already-adopted repository, as `register.confirm_items`
builds it. It has reason `register_confirm`, key `register-confirm/<root>/<at>`, `plan_id` null,
the options `Register it` and `Not now` with the values `register` and `not_now`, and the
folder-trust sentence as its `why`. It is copied as given and not filtered by the registered
projects, sits right after the apply items, and counts once in `inbox_items` and the headline.
While one is open the sentence is `REGISTER_SENTENCE`. Without `confirm_items` the view is unchanged.

Each failure item a caller passes (`failure_items`; #1085, ADR-console-035) is one entry of
`inbox.open` too: a registration that failed in plain words, as `register.failure_items` builds it.
It has reason `register_failed`, key `register-failed/<root>/<at>`, the options `Try again` and
`Not now` with the values `try_again` and `not_now`, the failure's headline and its next step as
`why`. It is copied as given, sits right after the confirm items and before the tracker items, and
counts once in `inbox_items` and the headline. While one is open the sentence is
`REGISTER_SENTENCE`. Without `failure_items` the view is unchanged.

Each trust item a caller passes (`trust_items`; #1078, ADR-console-034) is one entry of `inbox.open`
too: a profile whose folder trust could not be read back, as `folder_trust.items` builds it. It has
reason `trust_failed`, key `trust/<profile>/<root>/<at>`, `project_id` null, the `root`, `profile`
and `command`, the terminal command as its `why`, and the one option `Check again` with the value
`check`. It is copied as given, sits right after the retry items and before the plan questions, in
the order given, and counts once in `inbox_items` and the headline. While one is open the sentence
is `REGISTER_SENTENCE`. Without `trust_items` the view is unchanged.

A project entry is `{"type": "project", "project_id", "root", "quiet",
"open_work", "last_activity", "sprints": [<sprint entry>, ...],
"finished_sprints": null | {"label": "Finished sprints", "count": <int>,
"sprints": [<sprint entry>, ...]}, "outside_sprints": <line>,
"notices": [<notice entry>, ...], "notice_post": <bool>, "waits": [<wait entry>, ...],
"questions": null | {"label": "Questions", "count": <int>,
"threads": [{"id", "questions": [<question entry>, ...], "follow_up": <bool>}, ...]},
"tracker_read": {"ok": <bool>, "read_at": "<ISO time>" | null,
"began_at": "<ISO time>" | null} | null}`; a group entry is
`{"type": "quiet_group", "label": "<n> quiet projects", "count": <n>,
"projects": [<project entry>]}`. `project_count` counts registered projects
only. `unmanaged` is always present, possibly empty, sorted by `root`.

    `tracker_read` is the project's last tracker read, copied from its `ReadState` and
    changing no statement, inbox count, headline or sentence. The service sets `read_at` to the
    time each successful read finished and `began_at` to the time it began, before it fetched anything (a
    read that began at or after a moment has seen the tracker as it was then); after a restart `read_at` is the
    time of the last logged change between good and failed reads and `began_at` is null. It is null before any read, never a guessed time.

    <wait entry> = {"key", "issue": <int>, "url", "until": "<ISO time>" | null, "text": "<text>"}
    <notice entry> = {"id": <int>, "sprint_id", "poster": "<sprint title>",
                      "kind": "claim" | "heads-up" | "hand-off", "kind_text": "<text>",
                      "text": "<text>", "what": "<text>" | null, "until_text": "<text>" | null,
                      "to_text": "<text>" | null, "at": "<time>", "owner": <bool>}
    <sprint entry> = {"type": "sprint", "sprint_id", "title", "goal",
                      "state": "drafting" | "starting" | "on_track" | "waiting" | "quota" | "quiet"
                               | "closing" | "done" | "stopping" | "stopped",
                      "state_text": "<text>",
                      "ball": "manager" | "owner" | "nobody" | null,
                      "ball_text": "<text>" | null, "now_text": "<sentence>" | null,
                      "stated_at", "age_text", "manager_text": <text> | null,
                      "manager_state": "none" | "started" | "missing" | "failed" | "waiting"
                                       | "stalled" | "unavailable",
                      "manager_until": "<time>" | null, "retry": <bool>,
                      "permission_text": "<bypass|auto>: <reason>" | null,
                      "progress": {"landed", "in_delivery", "queued", "held", "total"} | null,
                      "progress_text": "<text>" | null,
                      "status": "<status line>" | null, "status_at": "<report time>" | null,
                      "next": "<text>" | null, "milestone": "<text>" | null,
                      "tracker_url": "<url>" | null,
                      "issues": [{"issue": <int>, "stage": "<stage>", "stage_text": "<text>"}, ...],
                      "waiting": <int>,
                      "checks": [{"project_id", "key", "issue", "question", "text"}, ...],
                      "waits": [<wait entry>, ...],
                      "sessions": [<session entry>, ...],
                      "messages": [<message entry>, ...],
                      "reach_text": "manager not reachable" | null,
                      "tell_text": "<text>" | null,
                      "stoppable": <bool>, "ended_at": "<time>" | null,
                      "stop_text": "<text>" | null,
                      "closing": null | {"at", "summary", "first_line", "differently",
                                         "landed": [<int>], "held": [<int>], "dropped": [<int>],
                                         "counts_text": "<text>"},
                      "state_until": "<time>" | null,
                      "pictures": [{"id", "line", "pair"}, ...],
                      "movement": {"sessions": [{"session_id", "manager": <bool>,
                                                 "read_at": "<ISO time>" | null}, ...],
                                   "nudged_at": "<time>" | null, "base_at": "<ISO time>",
                                   "issues": [<int>],
                                   "waits": {"ci_at", "commit_at", "release_at", "lock_at":
                                             "<ISO time>" | null}}}
    <message entry> = {"id": <int>, "kind": "approved" | "changes" | "text" | "stop",
                       "version": <int> | null, "text": <str> | null, "at": "<time>",
                       "state": "sent" | "picked_up" | "replied" | "not_picked_up",
                       "state_text": "<text>", "action_text": "<text>" | null,
                       "read_at": "<time>" | null, "reply": <str> | null,
                       "reply_at": "<time>" | null, "new": <bool>}
    <line> = {"label": "Outside sprints", "working": <int>, "waiting": <int>,
              "summary": "<text>", "sessions": [<session entry>, ...]}
    <session entry> = {"session_id", "name", "state", "state_text", "cwd",
                       "deliveries": [<delivery entry>, ...]}
    <delivery entry> = {"run_id", "quiet": <bool>, "moved_text": "<text>",
                        "summary": "<one sentence>", "moved_at": "<ISO time>",
                        "issues": [{"issue": <int>, "stage", "stage_text"}, ...]}
    <unmanaged entry> = {"type": "unmanaged", "root": "<repo>", "name": "<name>",
                         "label": "Not yet managed", "outside_sprints": <line>}

`working` counts working sessions and `waiting` counts those waiting for an
answer or a permission. `summary` joins, with ", ", the non-zero parts
"<n> working", "<n> waiting", "<n> stopped on a usage limit", "<n> idle", in
that order, and is "No sessions" with none. Sessions are ordered by state rank
(waiting_answer, waiting_permission, working, limit, idle), then newest
`last_seq`, then `session_id`; `name` is the session's name, else the first 8
characters of its id.

`deliveries` (always present, possibly empty) are the in-flight workflow runs of that listed
session, from the delivery states `derive_view` is given: the states whose `session_id` equals the
session's id, newest `moved_ms` first, then `run_id`; each run's issues are ordered by number.
`quiet` and `moved_text` come from `moved_text(now_ms - moved_ms)`; `summary` is the run as one
sentence, `run_summary(issues, moved_text)`: "<n> issue(s) in delivery: <count> <stage>, ...,
<moved_text>" with the stages in a fixed order and no issue number, or "No issue in delivery yet,
<moved_text>" with none; `moved_at` is the journal's last movement as an ISO UTC time, which lets
the page age the sentence's end itself. An unmanaged entry's `name` is the last segment of its `root` (the root
itself when it has none). `now_ms` is injected by the
caller (this module still reads no clock) and `None` counts as no time elapsed. The runs of an
ended or unlisted session appear nowhere, and they change no count, summary, order or the
statement. The word "stalled" is never written: a quiet run is only quiet.
`sprints` (always present, possibly empty) are the open sprints `derive_view` is given whose
`project_id` is that project, newest `stated_seq` first; a sprint of a project that is not
registered appears nowhere and changes no count, order or statement. `age_text` is
`age_text(elapsed)`, where `elapsed` is `now_ms` minus the stated time (`None` counts as no time
elapsed). A project with a shown sprint is never quiet and never folded into the quiet group.

A shown sprint reads its manager's latest report (`SprintState.report`); with none, `progress`,
`progress_text`, `status`, `status_at`, `next`, `milestone` and `tracker_url` are null,
`issues` is `[]` and `waiting` is 0. A sprint ended by a closing report (#980) shows its closing
only: `progress`, `progress_text`, `status`, `status_at` and `next` are null whatever its last report
said, and each of `issues`, ordered by number, is an issue of the closing with its closing stage
(`landed`, `held` or `dropped`) and `stage_text` `landed`, `held for verification` or `dropped`;
`milestone` and `tracker_url` stay the report's. The report's pictures are shown only while its
status is (a report and no closing), as `pictures`, else `[]`. Each reported issue, ordered by number, has an effective
`stage`: the report's own when it is `landed` or `held` (an outcome the manager reported is kept
against any run), else the stage of the sprint's observation of that issue (`SprintState.observed`),
where a run's `done` reads `closed out` and any other run stage is that stage with its
`stage_text`, else the report's stage. `progress` counts the effective stages: `landed`, `held`,
`queued`, `in_delivery` (every other stage, `closed out` included) and `total`;
`progress_text` is `progress_text` of those counts. Observations come only from the sprint's fold,
never from the `deliveries` mapping: a run leaves that mapping once its final record exists, while
the fold keeps its last stage and movement, so they outlive the run. `waiting` is the number of
open inbox items of registered projects whose project is the sprint's and whose issue is one of the
report's issues or its `inbox` numbers, plus the sprint's open questions. An open owner check (a
verification prompt or a held-issue review card, ADR-console-051, ADR-console-054) whose `blocking`
list meets none of the sprint's open issues (report issues not landed, held, dropped or closed
out) is not counted and is listed in `checks`
instead; a missing or malformed `blocking` counts as blocking. `checks` is ordered by
`waiting_since` then `key`, and each check stays an inbox item.
A running sprint's movement (#1109, `sprint_quiet_for`) is one reading. With no clock (`now_ms`
None) or while one of the sprint's listed sessions works, it moves. Else it is the latest of the
approved brief's time (`decided_at`, else the sent time), the report's time, the fold's `moved_ms`
(the latest movement of any run of the sprint, before or after its report) and the goal's stated
time, plus the wait signals of #1110 (`wait_signals`); it is quiet once `now_ms` minus that reaches
`QUIET_AFTER_MS`. A `failed` manager with no listed session drops only the stated time (a run,
report, approval or wait signal still moves the sprint whatever its order against the failure); with
nothing else left it reads quiet at once. The wait signals are the last time CI ran on a pull
request (`ci_ms`), the last time a commit landed on a pull request or a delivery's branch
(`commit_ms`), the last time a release was in progress (`release_ms`) and the last time a delivery
of the sprint held or waited for the land lock (`lock_ms`, #1184), each read from the project's
`ProjectMovement`, which keeps the last time a signal was seen after it disappears. A
pull request belongs to the sprint when its issues meet the issues of the report and its `inbox`
numbers; a branch belongs when its issue is one of them; a release belongs whatever the issues. Each
signal moves the sprint for `QUIET_AFTER_MS` after its time. Two session signals (#1185) join the
reading the same way: the last time one of the sprint's sessions wrote its transcript (`output_ms`),
and the last time a process under one of them used CPU (`check_ms`), each read from the project's
`ProjectMovement.sessions` associations of this sprint (`sprint_sessions_of`: the session carries the
sprint's manager name, is its `manager_session`, or runs a delivery of one of its issues). A time of
a manager session inside `NUDGE_REPLY_MS` (five minutes) after the sprint's `idle_nudged_at` is its
reply to the nudge and moves nothing; a delivery session's time always does. The two signals add no
sentence: they are part of the base reading, so they never name or replace a wait. The state's `quiet`,
the ball's `nobody` and the now-sentence's `last seen` prefix are all this one reading, and none
decides movement itself.
The state is the first that holds: `stopped_at` is set, `stopped` ("stopped by you"); `stop_at` is
set, `stopping` ("stopping"); the sprint has a closing, `done`; the brief is not approved,
`drafting` ("drafting the brief");
the report's phase is `done` and no question is open, `done`; `waiting` is above 0, `waiting` ("waiting on you (<n>)");
the movement reading is quiet, `quiet` ("quiet for <n> min \u2014 may be stuck"); the
phase is `closing`, `closing`; no report, `starting`; else `on_track` ("on track").
`status_at` is the report's own time, which the page words against its own clock.
`ball`, `ball_text` and `now_text` (#1086) are null for an ended sprint (`ended_at` set); a running
sprint has exactly one ball and a non-empty now-sentence, and `state` and `state_text` are
unchanged. `ball` (`sprint_ball`) is the first that holds: `owner` ("waiting on you") when `waiting`
is above 0, the brief waits on the owner (decision none), the sprint is stalled, `no_progress_at` is
set, its manager failed to start with no brief (`sprints.failed_start`), one of the sprint's listed sessions is waiting for an answer or a permission (the manager
waits on the owner at its terminal), or its manager cannot hear the console (below); `manager` ("manager working") while the movement reading moves;
else `nobody` ("nothing running, may be stuck"). `ball_text` is `BALL_TEXT[ball]`. `now_text` (`sprint_now`) is the first
that holds: a stop requested, `NOW_STOPPING_TEXT`; a listed session waiting for an answer, `NOW_ANSWER_TEXT`; a manager that cannot hear the console
(#1229: the sprint's manager session has `SessionMovement.held`, its transcript's last peer message
being one the client held and did not deliver), `NOW_DEAF_TEXT`; a listed session waiting for a
permission, `NOW_PERMISSION_TEXT`; a manager that failed to start, `NOW_FAILED_START_TEXT` (`state` stays
`drafting`); no brief or one the owner asked to change,
`NOW_DRAFTING_TEXT`; a brief waiting on the owner, `NOW_BRIEF_TEXT`; an open question,
`NOW_QUESTION_TEXT` with the first one's text; any other waiting item (`waiting` above 0),
`NOW_DECISION_TEXT`; a stall, `NOW_STALLED_TEXT`; no progress, `NOW_NO_PROGRESS_TEXT`; a quota
wait, `NOW_QUOTA_TEXT`; with no merge refusal shown, a wait signal that alone moves the sprint
(`sprint_wait`), the first of `NOW_CI_TEXT`, `NOW_COMMITTING_TEXT`, `NOW_RELEASE_TEXT` and `NOW_LOCK_TEXT`
whose signal is inside the window; no report, `NOW_STARTING_TEXT`; else a shown merge refusal
(`sprints.merge_refused`), `NOW_REFUSED_TEXT` with its reason; else the stage phrase,
`NOW_STAGE_TEXT`: the leading stage, its issue count, the total and the report's whole milestone
(just the milestone when the report names no issue); either prefixed by `NOW_QUIET_TEXT` when the
ball is `nobody`. The
leading stage is the non-final, non-queued stage the most issues hold (a tie goes to the later in
`REPORT_STAGES`); with none, `queued`; with none, `landed` when any landed, else the most common
remaining stage. The sentence is never the status line but for a merge refusal, and never
shortened (the page holds it to two lines).
`ended_at` is `sprints.ended_at` for every route to done (a stop, a closing, or a latest report of
phase `done`), so the `done` state and `ended_at` never disagree; `stoppable` is true exactly when
the sprint has no stop request, is not stopped and has not ended; `stop_text` is `STOP_FAILED_TEXT`
over `stop_reason` while that is set and the sprint is not stopped, else null; `closing` lists the
closing report's issue numbers by stage, ascending, and `counts_text` is `closing_text` of their
counts.
A sprint is finished when it has ended and `now_ms` (not None) is at least `FINISHED_AFTER_MS` past
`ended_at`. Finished sprints leave `sprints` for the project's `finished_sprints` (same order;
null with none): only a sprint that is not finished makes a project active, blocks `quiet` or puts
its brief in the inbox, and a quiet project's entry still carries its `finished_sprints`. A
finished sprint's manager session renders inside it, not in `outside_sprints`.
`unstopped` (always present) lists each pending stop of a registered project that has a `reason`,
ordered by `(failed_at, sprint_id)`, with `text` `UNSTOPPED_TEXT` over that reason; `derive_view`
reads them from its `pending` argument (default none).
`manager_state`, `manager_text` and `retry` are all `sprints.manager_status` (its docstring holds
the rules, so the view and the service's retry agree) over the sprint, whether it has a listed
session of its own (below) and `now_ms`; `manager_until` is the `until` of a `waiting` manager, else
null. `permission_text` (always present) is the mode the manager's settings file was last written
with and its reason (`SprintState.permission`, ADR-console-060), null when the sprint has none
logged. `derive_view(..., managers=False)` is a host that cannot start managers: every sprint is
`unavailable` with `UNAVAILABLE_TEXT` and no retry, and the view's top-level `managers` is the flag
(default true).
A listed session of the sprint's project whose name is `manager.session_name(project_id,
sprint_id)` is one of that sprint's `sessions` (ordered and shaped as in the line), not of the
project's `outside_sprints`, and is counted in none of its numbers or its summary; inside a sprint
a session waiting for an answer or a permission reads "waiting for an answer" or "waiting for a
permission".
`messages` are the `SHOWN_MESSAGES` (10) newest of the sprint's messages (`SprintState.messages`)
and every older one whose reply is `new`, oldest first (so a reply to an old message is never
cut); an approval the manager picked up without a reply is left out and takes no slot, while one
it replied to stays, its reply `new` until a later look and listed in `new_replies`. `approval` is the sprint's earliest approval message as one `messages` entry (same members), whether or not `messages` shows it, else null: the read receipt the verify check reads, which the presentation filter must not hide. `state` is `sprints.message_state` over `now_ms`: `replied` once the manager answered, else `picked_up` once it read the message, else `not_picked_up` five minutes after the message was
sent, else `sent`; a nudge never changes it. The pick-up is the minute form (`PICKUP_MINUTE_TEXT`)
exactly when `derive_view(..., nudges=True)` (default; the service passes whether it has a nudger)
and the sprint's manager is a `started` row, else the turn form (`PICKUP_TURN_TEXT`). `state_text` is
`"sent, "` and the pick-up for `sent`, else `PICKED_UP_TEXT`, `REPLIED_TEXT` or
`NOT_PICKED_UP_TEXT`; on an ended sprint a `sent` message reads `SENT_ENDED_TEXT` alone, with no
pick-up promise. `action_text` is null unless the message is `not_picked_up` on a sprint that has
not ended (an ended one has no Tell box and no stop or drop control to point at); then
`RETRY_ACTION_TEXT` when the sprint's `retry` is true, else `NUDGE_ACTION_TEXT` with the minute
pick-up, else `TURN_ACTION_TEXT`. `tell_text` is null for an ended sprint, else `TELL_MINUTE_TEXT` or
`TELL_TURN_TEXT` by the same pick-up (the page adds no colour to any of them). `reach_text` is `UNREACHABLE_TEXT` once `sprints.unreachable` holds, else null; it never
changes `retry` and never hides a message.
`new` is true exactly when the message has a `reply_at` and `derive_view(..., looked=<ISO time>)`
(the owner's last look; the service passes its own) is None or earlier than `reply_at`, compared as
aware datetimes. `new_replies` (always present, possibly empty) lists every message entry with `new`
true across the built project entries (their `sprints`, ended ones included, and
`finished_sprints.sprints`; a sprint of an unregistered project is never built, so never listed),
ordered by `(reply_at, message_id)`. `new_replies_text` is null with none, `NEW_REPLY_TEXT` over
the sprint's title with one and `NEW_REPLIES_TEXT` over the count with more. A reply never changes
`statement`: it is not an inbox item, and a later look clears `new` with no other write.
`recent_projects` is every registered project id, newest `last_seq` first, then `project_id`
(always present, possibly empty); it derives from the states alone.
Every project entry, quiet ones and those inside a quiet group too, carries `notices`: the open
notices (`open_notices`, so never a withdrawn or an ended one) of every sprint the view is given for
that project, its drafted and its finished sprints, newest first by descending `id` across all of
them, `[]` when none is open. `poster` is the posting sprint's title, `kind_text` is
`NOTICE_KIND_TEXT` of the kind, `what` is a claim's `what` and else null, `until_text` is
`NOTICE_UNTIL_TEXT` over a claim's `until` and else null, and `to_text` is null unless the notice
is a hand-off: then `NOTICE_OWNER_TEXT` when it is to the owner, `NOTICE_FOR_TEXT` over the title
of the target when it is to a sprint in the given sprints, else `NOTICE_OTHER_TEXT`. `at` is the
notice's own time, unchanged: the page ages it with its own clock. A notice is never an inbox item
and changes no count, headline, sentence or `stale` (#1119).
Every entry carries `owner`, false for a sprint's notice. The project's open owner notices
(`owner_notices`, a map from project id to its folded owner notices, default none; only
`open_owner_notices` of them, so never a withdrawn one) join the same list, ordered by `id` with the
sprints' ones: an owner entry is `{"id", "sprint_id": null, "poster": NOTICE_YOU_TEXT, "kind":
"heads-up", "kind_text": "Heads-up", "text", "what": null, "until_text": null, "to_text": null,
"at", "owner": true}` (#1120). Every project entry also carries `notice_post`: true when one of its
open (not finished) sprints `takes_notices`, so the page offers the owner's post, and false for a
quiet project, one whose only sprints are finished or stopping, and every entry in a quiet group.
Every project entry, quiet ones and those inside a quiet group too, carries `questions`
(`project_questions`, a map from project id to its folded `AskedQuestion`s, default none): null
when the project has no question, else `{"label": QUESTIONS_LABEL, "count", "threads"}` with one
thread per `project_question.threads` group, newest first by the last question's `seq`, `count`
their number. A thread is `{"id", "questions", "follow_up"}`: `id` is its first question's
`thread_id` (its own id when it has none), `questions` its question entries ascending by `seq`, and
`follow_up` true exactly when its last question is answered (#1178, ADR-console-059 D4).
A question entry is `{"id", "question", "asked_at",
"state": "working" | "answered" | "timed_out" | "failed", "state_text", "answered_at": <time> |
null, "answer": <str> | null, "read_text", "ran_text", "unknown_text", "back_text",
"back_choices", "production_text"}`. `state_text` is `ASK_WORKING_TEXT`, `ASK_ANSWERED_TEXT`, or
for a timed-out or failed question `ASK_TIMED_OUT_TEXT` or `ASK_FAILED_TEXT` and `": "` and the
reason when the reason is a non-empty string, else the bare text. The last seven members are null unless the question is
answered: `answer` is the parsed answer part, `read_text`, `ran_text`, `unknown_text` and
`back_text` are `ASK_READ_TEXT`, `ASK_RAN_TEXT`, `ASK_UNKNOWN_TEXT` and `ASK_BACK_TEXT` over their
part and each null when the part is, `back_choices` is the back part's choices as a list (empty
when it has none), and `production_text` is the parsed production line as is.
A question is never an inbox item; it changes no count, headline, sentence, `stale`, `quiet` or
order (#1177, #1178, ADR-console-059 D3, D4).
`encode_view` writes sorted keys, compact separators, non-ASCII kept, NaN
refused, no newline.
"""

import json
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import PurePosixPath

from agent_tools.console import contract_draft, inbox, project_question
from agent_tools.console.activation import Activation
from agent_tools.console.activation_run import LastRun
from agent_tools.console.capacity import EMPTY
from agent_tools.console.deliveries import (
    DONE as RUN_DONE,
    QUEUED,
    QUIET_AFTER_MS,
    DeliveryState,
    moved_text,
    run_summary,
    stage_text,
)
from agent_tools.console.event_log import (
    Event, INBOX_CHANGED, INBOX_GONE, INBOX_SEEN, PROJECT_QUESTION_ANSWERED,
    PROJECT_QUESTION_ASKED, PROJECT_UNREGISTERED as UNREGISTERED)
from agent_tools.console.manager import Wait, plain_reason, quota_wait, session_name
from agent_tools.console.movement import NUDGE_REPLY_MS, ProjectMovement, SessionMovement
from agent_tools.console.sessions import (
    ENDED,
    IDLE,
    LIMIT,
    STATE_TEXT,
    WAITING_ANSWER,
    WAITING_PERMISSION,
    WORKING,
    SessionState,
)
from agent_tools.console.sprints import (
    APPROVED,
    BALL_MANAGER,
    BALL_NOBODY,
    BALL_OWNER,
    BALL_TEXT,
    CHECK_LINE_TEXT,
    CLOSED_OUT,
    CLOSING,
    CLOSING_TEXT,
    DONE,
    DONE_TEXT,
    DRAFTING,
    DRAFTING_TEXT,
    DROPPED,
    FAILED,
    FINISHED_AFTER_MS,
    HELD,
    LANDED,
    MAX_ASK_CHARS,
    MAX_CONTEXT_CHARS,
    MAX_OPTION_CHARS,
    MAX_PICTURE_LINE_CHARS,
    MESSAGE_APPROVED,
    NO_PROGRESS_TEXT,
    NUDGE_ACTION_TEXT,
    NONE,
    NOTICE_OWNER,
    NOT_PICKED_UP,
    NOT_PICKED_UP_TEXT,
    NOW_ANSWER_TEXT,
    NOW_BRIEF_TEXT,
    NOW_CI_TEXT,
    NOW_COMMITTING_TEXT,
    NOW_DEAF_TEXT,
    NOW_DECISION_TEXT,
    NOW_DRAFTING_TEXT,
    NOW_FAILED_START_TEXT,
    NOW_LOCK_TEXT,
    NOW_NO_PROGRESS_TEXT,
    NOW_PERMISSION_TEXT,
    NOW_QUESTION_TEXT,
    NOW_QUIET_TEXT,
    NOW_QUOTA_TEXT,
    NOW_REFUSED_TEXT,
    NOW_RELEASE_TEXT,
    NOW_STAGE_TEXT,
    NOW_STALLED_TEXT,
    NOW_STARTING_TEXT,
    NOW_STOPPING_TEXT,
    ON_TRACK,
    ON_TRACK_TEXT,
    PICKED_UP,
    PICKED_UP_TEXT,
    PICKUP_MINUTE_TEXT,
    PICKUP_TURN_TEXT,
    QUIET,
    QUIET_TEXT,
    QUOTA,
    QUOTA_TEXT,
    REPLIED,
    REPLIED_TEXT,
    REPORT_STAGES,
    RETRY_ACTION_TEXT,
    SENT,
    SENT_ENDED_TEXT,
    STARTED,
    STARTING,
    STARTING_TEXT,
    STOP_FAILED_TEXT,
    STOPPED,
    STOPPED_TEXT,
    STOPPING,
    STOPPING_TEXT,
    TELL_MINUTE_TEXT,
    TELL_TURN_TEXT,
    TURN_ACTION_TEXT,
    UNSTOPPED_TEXT,
    WAITING,
    WAITING_TEXT,
    UNREACHABLE_TEXT,
    Closing,
    Message,
    Notice,
    Question,
    QuestionPicture,
    PendingStop,
    SprintState,
    age_text,
    closing_text,
    cut,
    ended_at,
    failed_start,
    goal_title,
    manager_status,
    merge_refused,
    message_state,
    open_questions,
    open_notices,
    open_owner_notices,
    progress_text,
    sprint_title,
    takes_notices,
    unreachable,
)
from agent_tools.verification import verify_owner

SHOWN_MESSAGES = 10
REGISTERED = "project.registered"
FOLD_AFTER = 3
NEW_REPLY_TEXT = "New reply from the manager of {title}"
NEW_REPLIES_TEXT = "{n} new replies from managers"
HEADLINE = "Nothing needs you"
OUTSIDE_LABEL = "Outside sprints"
CLOSING_OUTCOME_TEXT = {LANDED: "landed", HELD: "held for verification", DROPPED: "dropped"}
FINISHED_LABEL = "Finished sprints"
QUESTIONS_LABEL = "Questions"
UNMANAGED_LABEL = "Not yet managed"
NOTICE_KIND_TEXT = {"claim": "Claim", "heads-up": "Heads-up", "hand-off": "Hand-off"}
NOTICE_UNTIL_TEXT = "until {until}"
NOTICE_OWNER_TEXT = "for you"
NOTICE_FOR_TEXT = "for {title}"
NOTICE_OTHER_TEXT = "for another sprint"
NOTICE_YOU_TEXT = "You"
ASK_WORKING_TEXT = "Working on it"
ASK_ANSWERED_TEXT = "Answered"
ASK_TIMED_OUT_TEXT = "Timed out"
ASK_FAILED_TEXT = "Could not answer"
ASK_READ_TEXT = "Read: {text}"
ASK_RAN_TEXT = "Ran: {text}"
ASK_UNKNOWN_TEXT = "Could not find out: {text}"
ASK_BACK_TEXT = "Question for you: {text}"
_ASK_STATE_TEXT = {project_question.WORKING: ASK_WORKING_TEXT,
                   project_question.ANSWERED: ASK_ANSWERED_TEXT,
                   project_question.TIMED_OUT: ASK_TIMED_OUT_TEXT,
                   project_question.FAILED: ASK_FAILED_TEXT}

_RANK = {state: rank for rank, state in enumerate(
    (WAITING_ANSWER, WAITING_PERMISSION, WORKING, LIMIT, IDLE))}
_WAITING = (WAITING_ANSWER, WAITING_PERMISSION)
_SPRINT_STATE_TEXT = {**STATE_TEXT, WAITING_ANSWER: "waiting for an answer",
                      WAITING_PERMISSION: "waiting for a permission"}
_SUMMARY_PARTS = (
    ("working", (WORKING,)),
    ("waiting", _WAITING),
    ("stopped on a usage limit", (LIMIT,)),
    ("idle", (IDLE,)),
)
STALE_HEADLINE = "The tracker cannot be read"
ALL_OUT_HEADLINE = "Every profile is out of usage"
ALL_OUT_SENTENCE = "Everything resumes at the earliest reset; nothing is asked of you."
NEEDS_SENTENCE = "Each one links to the tracker, where it is answered."
BRIEF_SENTENCE = "Press Enter to approve the brief, or write a reply to ask for changes."
QUESTION_SENTENCE = "Choose an option with its number and press Enter, or answer in your own words."
MANAGER_SENTENCE = "Try again to start a new manager, or drop the sprint."
PROGRESS_SENTENCE = "Tell the manager to continue, or drop the sprint."
FAILED_START_HEADLINE = "The manager for {title} failed to start."
SENTENCE_STOPS = " .!?"
FAILED_START_SENTENCE = "Retry to start the manager, or drop the sprint."
SIGNIN_HEADLINE = "Sign in to {profile} again"
SIGNIN_FIRST_HEADLINE = "Sign in to {profile}"
SIGNIN_SENTENCE = "Press Sign in, then finish signing in in your browser."
ADOPTION_SENTENCE = "Open the pull request to merge the adoption."
REGISTER_TITLE = "Register {name}"
REGISTER_SENTENCE = "Choose an option with its number and press Enter."
REGISTER_STEP_SENTENCE = "Each one says what to do next."
ADOPTING_SENTENCE = "An adoption is under way; nothing is waiting on you."
ASKING_REASONS = ("register_failed", "register_apply", "register_retry", "register_confirm")
NEEDS_LINE = "Register {name}: needs you"
REGISTER_TYPE_SENTENCE = "Type the answer on its card and press Enter."
CHOOSE_SENTENCE = "Choose an option with its number and press Enter, or answer on the tracker."
ANSWER_SENTENCE = "Answer it here, or on the tracker."
WAIT_TEXT = {
    "window_opening": "Waiting for the next verification pass to start its wait: what it waits for has been seen",
    "not_released": "Waiting for the release to be seen: no release yet includes its merge",
    "not_deployed": "Waiting for the deploy to be seen: no deploy is known to include its merge",
    "ci_not_passed": "Waiting for a CI run to pass at its commit",
    "unknown": "Waiting: the tracker could not say whether it is due yet",
    "no_when": "Waiting with no date: its wording states a wait, but its verify block has no when field for that wait",
    "due": "Due now: the next verification pass asks you here",
    "due_command": ("Due now: the next verification pass asks you here, "
                    "unless it refuses the command as not a verification command"),
}
STALE_SENTENCE = ("The tracker could not be read for {projects}; "
                  "each item shows when it was last read.")
UNREAD_DECISION = "A decision waits on the tracker, but its questions could not be read."
INBOX_HEALTH = "inbox.health"
ACTIVATE_COMMAND = "just switch"
ACTIVATION_TEXT = "A console change merged at {commit} is not active on this host."
ACTIVATING_TEXT = "Activating this host at {commit}. The console may restart before it reports."
ACTIVATED_TEXT = "Activated this host at {commit}."
ACTIVATION_FAILED_TEXT = "Activating this host at {commit} failed: {reason}. {next_step}"
ACTIVATE_LABEL = "Activate"
OUTCOME_MS = 24 * 3600 * 1000


@dataclass(frozen=True)
class ProjectState:
    project_id: str
    root: str
    last_seq: int
    last_at: str
    open_work: int = 0


def project_states(
    events: Iterable[Event],
    states: Mapping[str, ProjectState] | None = None,
) -> dict[str, ProjectState]:
    result = dict(states or {})
    for event in events:
        project = event.project
        if event.kind == REGISTERED and project is not None:
            previous = result.get(project)
            result[project] = ProjectState(
                project, event.payload["root"], event.seq, event.at,
                previous.open_work if previous else 0)
        elif event.kind == UNREGISTERED:
            result.pop(project, None)
        elif event.kind in (PROJECT_QUESTION_ASKED, PROJECT_QUESTION_ANSWERED):
            continue
        elif project in result:
            result[project] = replace(
                result[project], last_seq=event.seq, last_at=event.at)
    return result


@dataclass(frozen=True)
class InboxRecord:
    item: dict
    waiting_since: str
    updated_at: str
    answered_at: str | None = None


def is_waiting(item: Mapping) -> bool:
    """Whether `item` is an owner check that waits (a `wait` member) and is not answered. No clock is read."""
    return isinstance(item.get("wait"), Mapping) and not item.get("answered")


def _wait_entry(record: InboxRecord) -> dict:
    item, wait = record.item, record.item["wait"]
    reason, until, what = wait.get("reason"), wait.get("until"), wait.get("what")
    dated = reason in ("not_before", "window") and isinstance(until, str) and isinstance(what, str)
    text = WAIT_TEXT["unknown"] if not isinstance(reason, str) else WAIT_TEXT.get(reason, WAIT_TEXT["unknown"])
    return {"key": item["key"], "issue": item.get("issue"), "url": item.get("url"),
            "until": until if dated else None, "text": what if dated else text}


@dataclass(frozen=True)
class ReadState:
    ok: bool
    read_at: str | None
    began_at: str | None = None


def inbox_records(
    events: Iterable[Event],
    records: Mapping[tuple[str, str], InboxRecord] | None = None,
) -> dict[tuple[str, str], InboxRecord]:
    """Records keyed by (owning project, item key): item keys are global to a repository,
    and two registered projects can resolve to the same one."""
    result = dict(records or {})
    for event in events:
        if event.kind == UNREGISTERED:
            result = {k: record for k, record in result.items()
                      if k[0] != event.project}
            continue
        if event.kind not in (INBOX_SEEN, INBOX_CHANGED, INBOX_GONE):
            continue
        name = event.payload.get("key")
        if not isinstance(name, str) or event.project is None:
            continue
        key = (event.project, name)
        if event.kind == INBOX_GONE:
            result.pop(key, None)
        elif event.kind == INBOX_CHANGED and key in result:
            record = result[key]
            if event.payload.get("answered") is not True:
                answered_at = None
            elif record.item.get("answered") is True:
                answered_at = record.answered_at
            else:
                answered_at = event.at
            result[key] = replace(
                record, item=event.payload, updated_at=event.at, answered_at=answered_at)
        else:
            answered = event.payload.get("answered") is True
            result[key] = InboxRecord(
                event.payload, event.at, event.at, event.at if answered else None)
    return result


def inbox_changes(
    records: Mapping[tuple[str, str], InboxRecord],
    project_id: str,
    items: Sequence[dict],
) -> list[tuple[str, str, dict]]:
    changes: list[tuple[str, str, dict]] = []
    named = set()
    for item in sorted(items, key=lambda i: i["key"]):
        named.add(item["key"])
        record = records.get((project_id, item["key"]))
        if record is None:
            changes.append((INBOX_SEEN, project_id, item))
        elif record.item != item:
            changes.append((INBOX_CHANGED, project_id, item))
    changes.extend(
        (INBOX_GONE, project_id, {"key": key})
        for (owner, key) in sorted(records)
        if owner == project_id and key not in named)
    return changes


def read_states(
    events: Iterable[Event],
    health: Mapping[str, ReadState] | None = None,
) -> dict[str, ReadState]:
    result = dict(health or {})
    for event in events:
        if event.kind == UNREGISTERED:
            result.pop(event.project, None)
        elif event.kind == INBOX_HEALTH and event.project is not None:
            ok = event.payload.get("ok")
            if ok is True:
                result[event.project] = ReadState(True, event.at)
            elif ok is False:
                read_at = event.payload.get("read_at")
                result[event.project] = ReadState(
                    False, read_at if isinstance(read_at, str) else None)
    return result


def health_change(
    health: Mapping[str, ReadState],
    project_id: str,
    ok: bool,
    read_at: str | None = None,
) -> list[tuple[str, str, dict]]:
    known = health.get(project_id)
    if ok and (known is None or not known.ok):
        return [(INBOX_HEALTH, project_id, {"ok": True})]
    if not ok and (known is None or known.ok):
        return [(INBOX_HEALTH, project_id, {"ok": False, "read_at": read_at})]
    return []


def registry_changes(
    states: Mapping[str, ProjectState],
    entries: Sequence[Mapping[str, str]],
) -> list[tuple[str, str, dict]]:
    wanted = {entry["project_id"]: entry["root"] for entry in entries}
    changes: list[tuple[str, str, dict]] = [
        (REGISTERED, project_id, {"root": root})
        for project_id, root in sorted(wanted.items())
        if project_id not in states or states[project_id].root != root
    ]
    changes.extend((UNREGISTERED, project_id, {})
                   for project_id in sorted(states) if project_id not in wanted)
    return changes


def _order(states: Iterable[ProjectState]) -> list[ProjectState]:
    return sorted(states, key=lambda s: (-s.last_seq, s.project_id))


def project_for(repo: str, states: Mapping[str, ProjectState]) -> str | None:
    matches = [project_id for project_id, state in states.items()
               if state.root == repo]
    return min(matches) if matches else None


def repo_name(root: str) -> str:
    """A repository's name: the last segment of its path, or the path itself when it has none."""
    return PurePosixPath(root).name or root


def _delivery_entry(state: DeliveryState, now_ms: int | None) -> dict:
    quiet, text = moved_text(0 if now_ms is None else now_ms - state.moved_ms)
    return {
        "run_id": state.run_id,
        "quiet": quiet,
        "moved_text": text,
        "summary": run_summary(state.issues, text),
        "moved_at": datetime.fromtimestamp(state.moved_ms / 1000, timezone.utc).isoformat(),
        "issues": [
            {"issue": i.issue, "stage": i.stage, "stage_text": stage_text(i)}
            for i in sorted(state.issues, key=lambda i: i.issue)
        ],
    }


def _session_entry(session: SessionState,
                   deliveries: Mapping[str, Sequence[DeliveryState]],
                   now_ms: int | None,
                   texts: Mapping[str, str] = STATE_TEXT) -> dict:
    runs = sorted(deliveries.get(session.session_id, ()),
                  key=lambda d: (-d.moved_ms, d.run_id))
    return {
        "session_id": session.session_id,
        "name": session.name or session.session_id[:8],
        "state": session.state,
        "state_text": texts[session.state],
        "cwd": session.cwd,
        "deliveries": [_delivery_entry(d, now_ms) for d in runs],
    }


def _ordered(sessions: Iterable[SessionState]) -> list[SessionState]:
    return sorted(sessions, key=lambda s: (_RANK[s.state], -s.last_seq, s.session_id))


def _line(sessions: Iterable[SessionState],
          deliveries: Mapping[str, Sequence[DeliveryState]],
          now_ms: int | None) -> dict:
    ordered = _ordered(sessions)
    summary = ", ".join(
        f"{n} {text}" for text, members in _SUMMARY_PARTS
        if (n := sum(s.state in members for s in ordered)))
    return {
        "label": OUTSIDE_LABEL,
        "working": sum(s.state == WORKING for s in ordered),
        "waiting": sum(s.state in _WAITING for s in ordered),
        "summary": summary or "No sessions",
        "sessions": [_session_entry(s, deliveries, now_ms) for s in ordered],
    }


def _millis(text: str) -> int:
    return int(datetime.fromisoformat(text).timestamp() * 1000)


def _effective_stages(state: SprintState) -> list[tuple[int, str, str]]:
    seen = {item.issue: item.stage for item in state.observed}
    rows = []
    for issue, stage in sorted(state.report.issues):
        run = seen.get(issue)
        if stage in (LANDED, HELD) or run is None:
            rows.append((issue, stage, stage))
        elif run.stage == RUN_DONE:
            rows.append((issue, CLOSED_OUT, CLOSED_OUT))
        else:
            rows.append((issue, run.stage, stage_text(run)))
    return rows


def owner_check(item: Mapping) -> bool:
    """Whether a tracker item is a verification owner prompt or a held-issue review card
    (ADR-console-051 D1, ADR-console-054)."""
    return item.get("reason") in verify_owner.REASONS or item.get("reason") == inbox.REVIEW_REASON


def sprint_open_issues(state: SprintState) -> frozenset[int]:
    """The issues of the sprint's report that are not landed, held, dropped or closed out; empty
    with no report."""
    if state.report is None:
        return frozenset()
    return frozenset(issue for issue, stage, _ in _effective_stages(state)
                     if stage not in (LANDED, HELD, DROPPED, CLOSED_OUT))


def _named_issues(state: SprintState) -> set:
    report = state.report
    return set() if report is None else {issue for issue, _ in report.issues} | set(report.inbox)


def _sprint_named(state: SprintState, records: Iterable[InboxRecord]) -> list[InboxRecord]:
    named = _named_issues(state)
    return [r for r in records if r.item.get("issue") in named]


def sprint_checks(state: SprintState, records: Iterable[InboxRecord]) -> list[InboxRecord]:
    """The sprint's open owner checks that block none of its open issues (ADR-console-051), ordered
    by `waiting_since` then `key`. A check on an issue that is itself open (building, verifying or
    queued) blocks it, and a `blocking` that is missing or not a list counts as blocking."""
    open_issues = sprint_open_issues(state)
    checks = [r for r in _sprint_named(state, records)
              if owner_check(r.item) and isinstance(r.item.get("blocking"), list)
              and r.item.get("issue") not in open_issues
              and open_issues.isdisjoint(r.item["blocking"])]
    return sorted(checks, key=lambda r: (r.waiting_since, r.item["key"]))


def sprint_waiting(state: SprintState, records: Iterable[InboxRecord]) -> int:
    """How many open items wait on the sprint: `records` naming an issue its report names, minus
    its check lines (`sprint_checks`), plus its open questions."""
    named = _sprint_named(state, records)
    checks = sprint_checks(state, named)
    return len(named) - len(checks) + len(open_questions(state))


@dataclass(frozen=True)
class WaitSignals:
    """The last time each wait of #1110 and #1184 was seen for one sprint, None when never."""
    ci_ms: int | None = None
    commit_ms: int | None = None
    release_ms: int | None = None
    lock_ms: int | None = None
    output_ms: int | None = None
    check_ms: int | None = None


NO_WAITS = WaitSignals()


def sprint_sessions_of(project_id: str, sprints: Iterable[SprintState],
                       sessions: Iterable[SessionState],
                       deliveries: Mapping[tuple[str, str], DeliveryState],
                       states: Mapping[str, ProjectState]) -> dict[str, frozenset[str]]:
    """The running sprints of `project_id` each live session belongs to (#1185). A session of the
    project's repository belongs to a sprint when it carries the sprint's manager name, is its
    `manager_session`, or runs a delivery of one of its issues (report issues united with `inbox`).
    A session that belongs to no sprint is absent."""
    running = [s for s in sprints if s.project_id == project_id and ended_at(s) is None]
    delivering: dict[str, set[int]] = {}
    for (session_id, _), delivery in deliveries.items():
        delivering.setdefault(session_id, set()).update(stage.issue for stage in delivery.issues)
    found: dict[str, frozenset[str]] = {}
    for session in sessions:
        if (session.state == ENDED or session.repo is None
                or project_for(session.repo, states) != project_id):
            continue
        mine = set()
        for sprint in running:
            report = sprint.report
            issues = (set() if report is None
                      else {issue for issue, _ in report.issues} | set(report.inbox))
            if (session.name == session_name(project_id, sprint.sprint_id)
                    or session.session_id == sprint.manager_session
                    or delivering.get(session.session_id, set()) & issues):
                mine.add(sprint.sprint_id)
        if mine:
            found[session.session_id] = frozenset(mine)
    return found


def sprint_absent_managers(project_id: str, sprints: Iterable[SprintState],
                           belonging: Mapping[str, frozenset[str]]) -> dict[str, frozenset[str]]:
    """The running sprints of `project_id` each known `manager_session` that is not a live session of
    theirs (absent from the registry or ended, so absent from `belonging`) manages (#1229). Its
    transcript is still read for a held peer message, whatever became of the session."""
    found: dict[str, set[str]] = {}
    for sprint in sprints:
        if (sprint.project_id == project_id and ended_at(sprint) is None
                and sprint.manager_session is not None
                and sprint.sprint_id not in belonging.get(sprint.manager_session, ())):
            found.setdefault(sprint.manager_session, set()).add(sprint.sprint_id)
    return {sid: frozenset(ids) for sid, ids in found.items()}


def sprint_nudge_replies(project_id: str, sprints: Iterable[SprintState],
                         sessions: Iterable[SessionState],
                         states: Mapping[str, ProjectState]) -> dict[str, tuple[tuple[str, int], ...]]:
    """For each live session of `project_id` that manages a running sprint which was nudged for being
    idle (`idle_nudged_at`), the `(sprint_id, nudge time in ms)` pairs. A session manages a sprint
    when it carries the sprint's manager name or is its `manager_session`. The movement fold leaves
    the manager's reply to that nudge out (#1185)."""
    running = [s for s in sprints if s.project_id == project_id and ended_at(s) is None
               and s.idle_nudged_at is not None]
    found: dict[str, list[tuple[str, int]]] = {}
    for session in sessions:
        if (session.state == ENDED or session.repo is None
                or project_for(session.repo, states) != project_id):
            continue
        for sprint in running:
            if (session.name == session_name(project_id, sprint.sprint_id)
                    or session.session_id == sprint.manager_session):
                try:
                    found.setdefault(session.session_id, []).append(
                        (sprint.sprint_id, _millis(sprint.idle_nudged_at)))
                except (TypeError, ValueError):
                    continue
    return {sid: tuple(sorted(pairs)) for sid, pairs in found.items()}


def sprint_issue_numbers(state: SprintState) -> set[int]:
    """The sprint's issues as the movement reads them: the report's issue numbers united with its
    `inbox` numbers (none without a report)."""
    report = state.report
    return (set() if report is None
            else {issue for issue, _ in report.issues} | set(report.inbox))


def wait_signals(state: SprintState, movement: ProjectMovement | None,
                 manager_ids: Collection[str] = ()) -> WaitSignals:
    """The sprint's wait signals out of its project's movement. The sprint's issues are the
    report's issue numbers united with its `inbox` numbers (none without a report); a pull request
    belongs when its issues meet them, a branch when its issue is one of them, a land lock time
    when its issue is one of them, and the release whatever the issues. The session signals are the newest transcript write and the newest
    running check among the associations of this sprint; a manager session's time inside the reply
    window of an idle nudge (`NUDGE_REPLY_MS` from `idle_nudged_at`) is left out."""
    if movement is None:
        return NO_WAITS
    issues = sprint_issue_numbers(state)
    pulls = [pull for pull in movement.pulls if issues & pull.issues]
    running = [pull.running_ms for pull in pulls if pull.running_ms is not None]
    commits = [pull.committed_ms for pull in pulls if pull.committed_ms is not None]
    commits += [moved for issue, moved in movement.branches if issue in issues]
    locks = [moved for issue, moved in movement.locks if issue in issues]
    nudged = None if state.idle_nudged_at is None else _millis(state.idle_nudged_at)

    def counted(own: SessionMovement, ms: int | None) -> int | None:
        if (ms is not None and nudged is not None and own.session_id in manager_ids
                and nudged <= ms < nudged + NUDGE_REPLY_MS):
            return None
        return ms

    mine = [own for own in movement.sessions if own.sprint_id == state.sprint_id]
    outputs = [ms for own in mine if (ms := counted(own, own.output_ms)) is not None]
    checks = [ms for own in mine if (ms := counted(own, own.check_ms)) is not None]
    return WaitSignals(max(running, default=None), max(commits, default=None),
                       movement.release_ms, max(locks, default=None), max(outputs, default=None),
                       max(checks, default=None))


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def _base_ms(state: SprintState) -> int:
    """The newest of the sprint's own signals: the approved brief, the report, the fold's
    `moved_ms` and the goal's stated time. A time that does not read as one is left out, so a
    shown entry never fails on it."""
    brief, report = state.brief, state.report
    texts = [state.stated_at]
    if brief is not None and brief.decision == APPROVED:
        texts.append(brief.decided_at or brief.sent_at)
    if report is not None:
        texts.append(report.at)
    times = [] if state.moved_ms is None else [state.moved_ms]
    for text in texts:
        try:
            times.append(_millis(text))
        except (TypeError, ValueError):
            continue
    return max(times, default=0)


def sprint_quiet_for(state: SprintState, now_ms: int | None, listed: Collection[str],
                     waits: WaitSignals = NO_WAITS) -> int | None:
    """The one movement reading of a running sprint (#1109): None while it moves, else the
    milliseconds since it last moved, never negative. The state's quiet, the ball's nobody and the
    now-sentence's `last seen` prefix all follow it, so they cannot disagree. It moves with no
    clock and while one of the sprint's own listed sessions works. Else the signals are the
    approved brief's time (`decided_at`, else the sent time), the report's time, the fold's
    `moved_ms` (the latest movement of any run of the sprint, kept across reports) and the goal's
    stated time, and each wait signal of `waits` (#1110) and session signal (#1185) that is set. A `failed` manager with no
    listed session drops only the stated time (its launch is known to have failed, so a fresh goal
    is no sign of life); a run, a report, an approval or a wait signal inside the window still
    moves the sprint whatever its order against the failure. With no signal left, the sprint reads
    quiet at once, for the time since the goal was stated."""
    if now_ms is None or WORKING in listed:
        return None
    brief, report = state.brief, state.report
    signals = []
    if brief is not None and brief.decision == APPROVED:
        signals.append(_millis(brief.decided_at or brief.sent_at))
    if report is not None:
        signals.append(_millis(report.at))
    if state.moved_ms is not None:
        signals.append(state.moved_ms)
    signals += [ms for ms in (waits.ci_ms, waits.commit_ms, waits.release_ms, waits.lock_ms,
                              waits.output_ms, waits.check_ms) if ms is not None]
    failed = state.manager is not None and state.manager.state == FAILED and not listed
    if not failed:
        signals.append(_millis(state.stated_at))
    elif not signals:
        return max(0, now_ms - _millis(state.stated_at))
    elapsed = max(0, now_ms - max(signals))
    return elapsed if elapsed >= QUIET_AFTER_MS else None


def sprint_wait(state: SprintState, now_ms: int | None, listed: Collection[str],
                waits: WaitSignals) -> str | None:
    """The wait sentence of #1110, or None. It names the wait only when the wait signals alone
    move the sprint (the session signals are part of the base reading and never name a wait): with
    no clock, or when something else moves it, or when it is quiet whatever
    the waits say, it is None. Else the first of CI, a committing delivery, a release step and the
    land lock whose signal is inside `QUIET_AFTER_MS`."""
    base = WaitSignals(output_ms=waits.output_ms, check_ms=waits.check_ms)
    if (now_ms is None or sprint_quiet_for(state, now_ms, listed, base) is None
            or sprint_quiet_for(state, now_ms, listed, waits) is not None):
        return None
    for ms, text in ((waits.ci_ms, NOW_CI_TEXT), (waits.commit_ms, NOW_COMMITTING_TEXT),
                     (waits.release_ms, NOW_RELEASE_TEXT),
                     (waits.lock_ms, NOW_LOCK_TEXT)):
        if ms is not None and now_ms - ms < QUIET_AFTER_MS:
            return text
    return None


def sprint_state(state: SprintState, now_ms: int | None, waiting: int,
                 quota: Wait | None = None, listed: Collection[str] = (),
                 waits: WaitSignals = NO_WAITS) -> tuple[str, str]:
    """The sprint's one shown state and its text; with `now_ms` None the sprint is never quiet.
    A `quota` (its manager's profile is out, #929) replaces every state but waiting on the owner,
    closing and the ones before them. `listed` is the `state` of each of the sprint's own listed
    sessions and `waits` the sprint's wait signals, which `sprint_quiet_for` reads."""
    brief, report = state.brief, state.report
    if state.stopped_at is not None:
        return STOPPED, STOPPED_TEXT
    if state.stop_at is not None:
        return STOPPING, STOPPING_TEXT
    if state.closing is not None:
        return DONE, DONE_TEXT
    if brief is None or brief.decision != APPROVED:
        return DRAFTING, DRAFTING_TEXT
    if report is not None and report.phase == DONE and not open_questions(state):
        return DONE, DONE_TEXT
    if waiting:
        return WAITING, WAITING_TEXT.format(n=waiting)
    if quota is not None and (report is None or report.phase != CLOSING):
        return QUOTA, QUOTA_TEXT
    quiet_for = sprint_quiet_for(state, now_ms, listed, waits)
    if quiet_for is not None:
        return QUIET, QUIET_TEXT.format(minutes=quiet_for // 60_000)
    if report is not None and report.phase == CLOSING:
        return CLOSING, CLOSING_TEXT
    if report is None:
        return STARTING, STARTING_TEXT
    return ON_TRACK, ON_TRACK_TEXT


def sprint_ball(state: SprintState, now_ms: int | None, waiting: int,
                listed: Collection[str], waits: WaitSignals = NO_WAITS,
                failed_start: bool = False, deaf: bool = False) -> str | None:
    """Who holds a running sprint's ball (#1086), or None once it has ended. `listed` is the
    `state` of each of the sprint's own listed sessions. The owner when anything waits on them: an
    open item (`waiting`), a brief awaiting a decision, a stall, no progress, or a manager session
    waiting at its terminal, or a manager that failed to start with no brief (`failed_start`, the
    owner's retry card). Else the manager while `sprint_quiet_for` reads the sprint moving, else
    nobody; a `failed` manager with no listed session drops only the goal's stated time from the
    signals, so the ball reads nobody at once only when no approval, report or run has moved, and a
    run, report, approval or wait signal inside the window keeps it manager whatever its order
    against the failure. `waits` are the sprint's wait signals. A `deaf` manager (its transcript
    shows a held, undelivered peer message, #1229) waits on the owner too."""
    if ended_at(state) is not None:
        return None
    brief = state.brief
    if (waiting or deaf or (brief is not None and brief.decision == NONE) or state.stalled is not None
            or state.no_progress_at is not None or failed_start
            or WAITING_ANSWER in listed or WAITING_PERMISSION in listed):
        return BALL_OWNER
    quiet_for = sprint_quiet_for(state, now_ms, listed, waits)
    return BALL_MANAGER if quiet_for is None else BALL_NOBODY


def _stage_phrase(stages: Sequence[tuple[int, str, str]], milestone: str) -> str:
    """The stage a running sprint leads with, its issue count, the total and the whole milestone;
    just the milestone when the report names no issue. The stage is the non-final, non-queued one
    held by the most issues (a tie goes to the later in `REPORT_STAGES`, a stage outside it ranks
    lowest); with none, `queued`; with none, `landed` when any issue landed, else the most common
    remaining stage (a tie goes to the alphabetically first)."""
    if not stages:
        return milestone
    counts = Counter(stage for _, stage, _ in stages)
    final = (LANDED, HELD, DROPPED, CLOSED_OUT)
    leading = [stage for stage in counts if stage not in final and stage != QUEUED]
    if leading:
        stage = max(leading, key=lambda name: (
            counts[name], REPORT_STAGES.index(name) if name in REPORT_STAGES else -1))
    elif QUEUED in counts:
        stage = QUEUED
    elif LANDED in counts:
        stage = LANDED
    else:
        stage = min(counts, key=lambda name: (-counts[name], name))
    return NOW_STAGE_TEXT.format(stage=stage, count=counts[stage], total=len(stages),
                                 milestone=milestone)


def sprint_now(state: SprintState, quota: Wait | None, listed: Collection[str], waiting: int,
               stages: Sequence[tuple[int, str, str]], ball: str | None,
               wait: str | None = None, failed_start: bool = False,
               deaf: bool = False) -> str | None:
    """What a running sprint is doing right now as one sentence (#1086), or None once it has
    ended; the first rule that holds, in the order the view docstring gives. `waiting`, `stages`,
    `ball`, `wait` (`sprint_wait`), `failed_start` and `deaf` (the manager holds the console's wake
    behind a prompt no one at a terminal answers, #1229) are the entry's own."""
    if ended_at(state) is not None:
        return None
    brief, report = state.brief, state.report
    if state.stop_at is not None:
        return NOW_STOPPING_TEXT
    if WAITING_ANSWER in listed:
        return NOW_ANSWER_TEXT
    if deaf:
        return NOW_DEAF_TEXT
    if WAITING_PERMISSION in listed:
        return NOW_PERMISSION_TEXT
    if failed_start:
        return NOW_FAILED_START_TEXT
    if brief is None or brief.decision not in (APPROVED, NONE):
        return NOW_DRAFTING_TEXT
    if brief.decision == NONE:
        return NOW_BRIEF_TEXT
    if questions := open_questions(state):
        return NOW_QUESTION_TEXT.format(question=questions[0].question)
    if waiting > 0:
        return NOW_DECISION_TEXT
    if state.stalled is not None:
        return NOW_STALLED_TEXT
    if state.no_progress_at is not None:
        return NOW_NO_PROGRESS_TEXT
    if quota is not None:
        return NOW_QUOTA_TEXT
    reason = merge_refused(state)
    if wait is not None and reason is None:
        return wait
    if report is None:
        return NOW_STARTING_TEXT
    phrase = (NOW_REFUSED_TEXT.format(reason=reason) if reason is not None
              else _stage_phrase(stages, report.milestone))
    return NOW_QUIET_TEXT.format(phrase=phrase) if ball == BALL_NOBODY else phrase


def _is_new(message: Message, looked: str | None) -> bool:
    if message.reply_at is None:
        return False
    return looked is None or (datetime.fromisoformat(message.reply_at)
                              > datetime.fromisoformat(looked))


def _shown_messages(messages: Sequence[Message], looked: str | None) -> list[Message]:
    """The `SHOWN_MESSAGES` newest messages, plus any older one whose reply is new (#1086), once
    every approval the manager picked up without a reply is left out: it takes no slot."""
    kept = [m for m in messages
            if not (m.kind == MESSAGE_APPROVED and m.read_at is not None and m.reply is None)]
    first = len(kept) - SHOWN_MESSAGES
    return [m for i, m in enumerate(kept) if i >= first or _is_new(m, looked)]


def _message_entry(message: Message, now_ms: int | None, minute: bool, retry: bool,
                   looked: str | None = None, ended: bool = False) -> dict:
    shown = message_state(message, now_ms)
    pickup = PICKUP_MINUTE_TEXT if minute else PICKUP_TURN_TEXT
    text = {PICKED_UP: PICKED_UP_TEXT, REPLIED: REPLIED_TEXT, NOT_PICKED_UP: NOT_PICKED_UP_TEXT,
            SENT: SENT_ENDED_TEXT if ended else "sent, " + pickup}[shown]
    action = None
    if shown == NOT_PICKED_UP and not ended:
        action = (RETRY_ACTION_TEXT if retry else NUDGE_ACTION_TEXT if minute
                  else TURN_ACTION_TEXT)
    return {"id": message.message_id, "kind": message.kind, "version": message.version,
            "text": message.text, "at": message.at, "state": shown, "state_text": text,
            "action_text": action, "read_at": message.read_at, "reply": message.reply,
            "reply_at": message.reply_at, "new": _is_new(message, looked)}


def _approval_entry(state: SprintState, now_ms: int | None, minute: bool, retry: bool,
                    looked: str | None, ended: bool) -> dict | None:
    """The sprint's earliest approval as a message entry, whether or not `messages` shows it (a
    read approval with no reply is left out of `messages`), else None."""
    first = next((m for m in state.messages if m.kind == MESSAGE_APPROVED), None)
    return None if first is None else _message_entry(first, now_ms, minute, retry, looked, ended)


def _closing_entry(closing: Closing) -> dict:
    by_stage = {stage: sorted(issue for issue, row in closing.issues if row == stage)
                for stage in (LANDED, HELD, DROPPED)}
    return {"at": closing.at, "summary": closing.summary, "first_line": closing.first_line,
            "differently": closing.differently, "landed": by_stage[LANDED],
            "held": by_stage[HELD], "dropped": by_stage[DROPPED],
            "counts_text": closing_text(len(by_stage[LANDED]), len(by_stage[HELD]),
                                        len(by_stage[DROPPED]))}


def _finished(state: SprintState, now_ms: int | None) -> bool:
    ended = ended_at(state)
    return (ended is not None and now_ms is not None
            and now_ms - _millis(ended) >= FINISHED_AFTER_MS)


def _sprint_entry(state: SprintState, now_ms: int | None, managers: bool,
                  sessions: Sequence[SessionState],
                  deliveries: Mapping[str, Sequence[DeliveryState]],
                  records: Sequence[InboxRecord] = (), capacity: Mapping = EMPTY,
                  nudges: bool = True, looked: str | None = None,
                  movement: ProjectMovement | None = None,
                  wait_lines: Sequence[Mapping] = ()) -> dict:
    stated_ms = _millis(state.stated_at)
    elapsed = 0 if now_ms is None else now_ms - stated_ms
    report = state.report
    closing = state.closing
    stages = (sorted((issue, stage, CLOSING_OUTCOME_TEXT[stage])
                     for issue, stage in closing.issues) if closing is not None
              else [] if report is None else _effective_stages(state))
    waiting = sprint_waiting(state, records)
    checks = sprint_checks(state, records)
    counts = {
        "landed": sum(stage == LANDED for _, stage, _ in stages),
        "in_delivery": sum(stage not in (LANDED, HELD, QUEUED) for _, stage, _ in stages),
        "queued": sum(stage == QUEUED for _, stage, _ in stages),
        "held": sum(stage == HELD for _, stage, _ in stages),
        "total": len(stages),
    }
    progressing = report is not None and closing is None
    manager_state, manager_text, retry = manager_status(state, bool(sessions), now_ms, managers)
    quota = (quota_wait(capacity, state.manager.profile)
             if state.manager is not None and state.manager.state == STARTED else None)
    listed = [s.state for s in sessions]
    manager_ids = {s.session_id for s in sessions}
    if state.manager_session is not None:
        manager_ids.add(state.manager_session)
    waits = wait_signals(state, movement, manager_ids)
    name, text = sprint_state(state, now_ms, waiting, quota, listed=listed, waits=waits)
    ended = ended_at(state)
    failed = failed_start(state, bool(sessions), managers)
    own = sorted((m for m in (() if movement is None else movement.sessions)
                  if m.sprint_id == state.sprint_id), key=lambda m: m.session_id)
    deaf = any(m.held and m.session_id in manager_ids for m in own)
    ball = sprint_ball(state, now_ms, waiting, listed, waits, failed_start=failed, deaf=deaf)
    minute = nudges and state.manager is not None and state.manager.state == STARTED
    return {
        "type": "sprint",
        "sprint_id": state.sprint_id,
        "title": sprint_title(state),
        "goal": state.goal,
        "state": name,
        "state_text": text,
        "ball": ball,
        "ball_text": None if ball is None else BALL_TEXT[ball],
        "now_text": sprint_now(state, quota, listed, waiting, stages, ball,
                               sprint_wait(state, now_ms, listed, waits), failed_start=failed,
                               deaf=deaf),
        "stated_at": state.stated_at,
        "age_text": age_text(elapsed),
        "manager_text": manager_text,
        "manager_state": manager_state,
        "permission_text": None if state.permission is None else state.permission.text,
        "manager_until": (state.manager.until
                          if manager_state == WAITING and state.manager is not None else None),
        "retry": retry,
        "progress": counts if progressing else None,
        "progress_text": progress_text(
            counts["landed"], counts["total"], counts["in_delivery"], counts["queued"],
            counts["held"]) if progressing else None,
        "status": report.status if progressing else None,
        "status_at": report.at if progressing else None,
        "next": report.next_step if progressing else None,
        "milestone": None if report is None else report.milestone,
        "tracker_url": None if report is None else report.tracker_url,
        "issues": [{"issue": issue, "stage": stage, "stage_text": text}
                   for issue, stage, text in stages],
        "waiting": waiting,
        "checks": [{"project_id": r.item["project_id"], "key": r.item["key"],
                    "issue": r.item["issue"], "question": r.item["question"],
                    "text": CHECK_LINE_TEXT.format(question=r.item["question"])}
                   for r in checks],
        "waits": [dict(w) for w in wait_lines],
        "sessions": [_session_entry(s, deliveries, now_ms, _SPRINT_STATE_TEXT)
                     for s in _ordered(sessions)],
        "messages": [_message_entry(m, now_ms, minute, retry, looked, ended is not None)
                     for m in _shown_messages(state.messages, looked)],
        "approval": _approval_entry(state, now_ms, minute, retry, looked, ended is not None),
        "tell_text": (None if ended is not None
                      else TELL_MINUTE_TEXT if minute else TELL_TURN_TEXT),
        "reach_text": UNREACHABLE_TEXT if unreachable(state) else None,
        "stoppable": (state.stop_at is None and state.stopped_at is None and ended is None),
        "ended_at": ended,
        "stop_text": (STOP_FAILED_TEXT.format(reason=state.stop_reason)
                      if state.stop_reason is not None and state.stopped_at is None else None),
        "closing": None if state.closing is None else _closing_entry(state.closing),
        "state_until": quota.until if name == QUOTA else None,
        "pictures": _picture_entries(report.pictures) if progressing else [],
        "movement": {
            "sessions": [{"session_id": m.session_id, "manager": m.session_id in manager_ids,
                          "read_at": None if m.read_ms is None else _utc(m.read_ms)}
                         for m in own],
            "nudged_at": state.idle_nudged_at,
            "issues": sorted(sprint_issue_numbers(state)),
            "waits": {"ci_at": None if waits.ci_ms is None else _utc(waits.ci_ms),
                      "commit_at": None if waits.commit_ms is None else _utc(waits.commit_ms),
                      "release_at": None if waits.release_ms is None else _utc(waits.release_ms),
                      "lock_at": None if waits.lock_ms is None else _utc(waits.lock_ms)},
            "base_at": _utc(_base_ms(state)),
        },
    }


def _project_entry(state: ProjectState, sessions: Sequence[SessionState],
                   deliveries: Mapping[str, Sequence[DeliveryState]],
                   now_ms: int | None,
                   sprints: Sequence[SprintState] = (),
                   managers: bool = True,
                   sprint_sessions: Mapping[str, Sequence[SessionState]] | None = None,
                   records: Sequence[InboxRecord] = (),
                   finished: Sequence[SprintState] = (),
                   capacity: Mapping = EMPTY,
                   nudges: bool = True, looked: str | None = None,
                   movement: ProjectMovement | None = None,
                   notices: Sequence[Mapping] = (), notice_post: bool = False,
                   sprint_waits: Mapping[str, Sequence[Mapping]] | None = None,
                   waits: Sequence[Mapping] = (),
                   read: ReadState | None = None,
                   questions: Mapping | None = None) -> dict:
    def entries(group: Sequence[SprintState]) -> list[dict]:
        return [_sprint_entry(s, now_ms, managers, (sprint_sessions or {}).get(s.sprint_id, ()),
                              deliveries, records, capacity, nudges, looked, movement,
                              (sprint_waits or {}).get(s.sprint_id, ()))
                for s in group]

    return {
        "type": "project",
        "project_id": state.project_id,
        "root": state.root,
        "quiet": state.open_work == 0 and not sessions and not sprints and not waits,
        "open_work": state.open_work,
        "last_activity": state.last_at,
        "sprints": entries(sprints),
        "finished_sprints": (None if not finished else
                             {"label": FINISHED_LABEL, "count": len(finished),
                              "sprints": entries(finished)}),
        "outside_sprints": _line(sessions, deliveries, now_ms),
        "notices": [dict(n) for n in notices],
        "notice_post": notice_post,
        "waits": [dict(w) for w in waits],
        "questions": questions,
        "tracker_read": None if read is None else {"ok": read.ok, "read_at": read.read_at, "began_at": read.began_at},
    }


def _question_threads(questions: Sequence[project_question.AskedQuestion]) -> dict | None:
    def one(question: project_question.AskedQuestion) -> dict:
        reason = question.reason
        state_text = _ASK_STATE_TEXT[question.state]
        if question.state in (project_question.TIMED_OUT, project_question.FAILED) and reason:
            state_text = f"{state_text}: {reason}"
        parts = (project_question.answer_parts(question.answer)
                 if question.state == project_question.ANSWERED and question.answer is not None
                 else None)

        def said(template: str, text: str | None) -> str | None:
            return None if text is None else template.format(text=text)

        return {
            "id": question.question_id,
            "question": question.question,
            "asked_at": question.asked_at,
            "state": question.state,
            "state_text": state_text,
            "answered_at": question.answered_at,
            "answer": None if parts is None else parts.answer,
            "read_text": None if parts is None else said(ASK_READ_TEXT, parts.read),
            "ran_text": None if parts is None else said(ASK_RAN_TEXT, parts.ran),
            "unknown_text": None if parts is None else said(ASK_UNKNOWN_TEXT, parts.unknown),
            "back_text": None if parts is None else said(ASK_BACK_TEXT, parts.back),
            "back_choices": None if parts is None else list(parts.choices),
            "production_text": None if parts is None else parts.production,
        }

    threads = project_question.threads(questions)
    if not threads:
        return None
    return {"label": QUESTIONS_LABEL, "count": len(threads),
            "threads": [{"id": group[0].thread_id or group[0].question_id,
                         "questions": [one(q) for q in group],
                         "follow_up": group[-1].state == project_question.ANSWERED}
                        for group in threads]}


def _notice_to_text(to: str | None, titles: Mapping[str, str]) -> str:
    if to == NOTICE_OWNER:
        return NOTICE_OWNER_TEXT
    if to in titles:
        return NOTICE_FOR_TEXT.format(title=titles[to])
    return NOTICE_OTHER_TEXT


def _notice_entries(group: Iterable[SprintState], titles: Mapping[str, str],
                    owner: Iterable[Notice] = ()) -> list[dict]:
    """The open notices of `group`'s sprints and the owner's as page entries, newest first."""
    found = [(n, s) for s in group for n in open_notices(s)]
    entries = [{
        "id": n.notice_id,
        "sprint_id": s.sprint_id,
        "poster": titles[s.sprint_id],
        "kind": n.kind,
        "kind_text": NOTICE_KIND_TEXT[n.kind],
        "text": n.text,
        "what": n.what if n.kind == "claim" else None,
        "until_text": (NOTICE_UNTIL_TEXT.format(until=n.until) if n.kind == "claim" else None),
        "to_text": (_notice_to_text(n.to, titles) if n.kind == "hand-off" else None),
        "at": n.at,
        "owner": False,
    } for n, s in found]
    entries.extend({
        "id": n.notice_id,
        "sprint_id": None,
        "poster": NOTICE_YOU_TEXT,
        "kind": n.kind,
        "kind_text": NOTICE_KIND_TEXT[n.kind],
        "text": n.text,
        "what": None,
        "until_text": None,
        "to_text": None,
        "at": n.at,
        "owner": True,
    } for n in owner)
    return sorted(entries, key=lambda entry: -entry["id"])


def _sentence(count: int, adopting: bool = False) -> str:
    if count == 0:
        return ADOPTING_SENTENCE if adopting else "No project is registered yet."
    noun = "project" if count == 1 else "projects"
    return f"{count} registered {noun}, and nothing is waiting on you."


def item_headline(item: Mapping) -> tuple[str, int]:
    questions = item.get("questions")
    if questions:
        return questions[0]["question"], len(questions) - 1
    if item.get("reason") == "decision":
        return UNREAD_DECISION, 0
    return item.get("question", ""), 0


def _inbox_entry(record: InboxRecord,
                 health: Mapping[str, ReadState]) -> dict:
    known = health.get(record.item["project_id"])
    stale = known is not None and not known.ok
    read_at = known.read_at if known is not None and known.read_at is not None \
        else record.updated_at
    headline, more = item_headline(record.item)
    return {**{k: v for k, v in record.item.items() if k != "question"},
            "type": "inbox_item", "waiting_since": record.waiting_since,
            "stale": stale, "read_at": read_at, "headline": headline,
            "more_questions": more, "answered_at": record.answered_at}


def _picture_entries(pictures: Iterable[QuestionPicture]) -> list[dict]:
    return [{"id": p.picture, "line": cut(p.line, MAX_PICTURE_LINE_CHARS), "pair": p.pair}
            for p in pictures]


def _brief_entry(sprint: SprintState) -> dict:
    brief = sprint.brief
    return {"type": "inbox_item", "reason": "brief", "key": f"brief/{sprint.sprint_id}",
            "project_id": sprint.project_id, "sprint_id": sprint.sprint_id,
            "title": sprint_title(sprint), "version": brief.version, "brief": brief.parts,
            "pictures": _picture_entries(brief.pictures),
            "answered": False, "waiting_since": brief.sent_at}


def _question_entry(sprint: SprintState, question: Question) -> dict:
    ask = cut(question.question, MAX_ASK_CHARS)
    context = question.context
    return {"type": "inbox_item", "reason": "question",
            "key": f"question/{sprint.sprint_id}/{question.round_id}/{question.index}",
            "project_id": sprint.project_id, "sprint_id": sprint.sprint_id,
            "title": sprint_title(sprint),
            "round": question.round_id, "index": question.index, "blocker": question.blocker,
            "blocks": question.blocks, "headline": ask,
            "context": None if context is None else cut(context, MAX_CONTEXT_CHARS),
            "more_questions": 0,
            "questions": [{"question": ask,
                           "options": [cut(o, MAX_OPTION_CHARS) for o in question.options],
                           "chosen": None, "recommended": cut(question.recommended,
                                                              MAX_OPTION_CHARS),
                           "recommended_index": question.options.index(question.recommended)}],
            "pictures": _picture_entries(question.pictures),
            "items": [], "answers": [], "answered": False, "waiting_since": question.at}


def _stall_entry(sprint: SprintState) -> dict:
    title = sprint_title(sprint)
    return {"type": "inbox_item", "reason": "manager", "key": f"manager/{sprint.sprint_id}",
            "project_id": sprint.project_id, "sprint_id": sprint.sprint_id,
            "title": title, "headline": f"managers keep failing on {title}",
            "last_reason": sprint.stalled,
            "answered": False, "waiting_since": sprint.stalled_at}


def _failed_start_entry(sprint: SprintState) -> dict:
    title = sprint_title(sprint)
    return {"type": "inbox_item", "reason": "failed_start", "key": f"failed-start/{sprint.sprint_id}",
            "project_id": sprint.project_id, "sprint_id": sprint.sprint_id,
            "title": title, "headline": FAILED_START_HEADLINE.format(title=title.rstrip(SENTENCE_STOPS)),
            "last_reason": plain_reason(sprint.manager.reason),
            "answered": False, "waiting_since": sprint.manager.at}


def _progress_entry(sprint: SprintState) -> dict:
    report = sprint.report
    title = sprint_title(sprint)
    return {"type": "inbox_item", "reason": "progress", "key": f"progress/{sprint.sprint_id}",
            "project_id": sprint.project_id, "sprint_id": sprint.sprint_id,
            "title": title, "headline": NO_PROGRESS_TEXT.format(title=title),
            "last_status": None if report is None else report.status,
            "answered": False, "waiting_since": sprint.no_progress_at}


def _signin_entry(entry: Mapping, runs: Mapping[str, Mapping]) -> dict:
    profile = entry["profile"]
    signin = entry["signin"]
    headline = SIGNIN_HEADLINE if signin.get("ever_signed_in") is True else SIGNIN_FIRST_HEADLINE
    return {"type": "inbox_item", "reason": "signin", "key": f"signin/{profile}",
            "project_id": None, "profile": profile,
            "headline": headline.format(profile=profile),
            "action": "signin", "run": runs.get(profile) or None, "signin": signin,
            "answered": False, "waiting_since": signin["since"]}


def _register_entries(registration: Mapping | None) -> list[dict]:
    if not isinstance(registration, Mapping) or registration.get("status") != "done":
        return []
    questions = registration.get("questions")
    if not isinstance(questions, list) or not questions:
        return []
    name, plan_id = registration.get("name"), registration.get("plan_id")
    refused = registration.get("refused")
    return [{"type": "inbox_item", "reason": "register", "key": f"register/{plan_id}/{index}",
             "project_id": None, "root": registration.get("root"), "name": name,
             "title": REGISTER_TITLE.format(name=name), "plan_id": plan_id, "id": q["id"],
             "subject": q["subject"], "headline": q["ask"], "why": q["why"],
             "refusal": (registration.get("refusal")
                         if refused == {"id": q["id"], "subject": q["subject"]} else None),
             "more_questions": 0, "text": q.get("text") is True,
             "placeholder": (contract_draft.placeholder(q["subject"])
                             if q["id"] == contract_draft.QUESTION_ID and q.get("text") is True
                             else None),
             "questions": [] if not q["options"] else [{
                 "question": q["ask"], "options": [o["label"] for o in q["options"]],
                 "chosen": None, "recommended": None, "recommended_index": None}],
             "values": [o["value"] for o in q["options"]],
             "items": [], "answers": [], "answered": False,
             "waiting_since": registration.get("at")}
            for index, q in enumerate(questions)]


def _shown_registration(registration: Mapping | None, states: list[ProjectState],
                        cards: Iterable[Mapping]) -> dict | None:
    if registration is None:
        return None
    root = registration.get("root")
    if registration.get("status") == "done" and any(s.root == root for s in states):
        return None
    if any(c.get("reason") in ASKING_REASONS and c.get("root") == root for c in cards):
        return {**registration, "line": NEEDS_LINE.format(name=registration["name"]),
                "lines": [], "note": None, "adoption": None, "draft": None,
                "draft_more": None}
    return dict(registration)


def _headline(open_count: int, stale: bool, all_out: bool) -> str:
    if open_count == 1:
        return "1 thing needs you"
    if open_count > 1:
        return f"{open_count} things need you"
    if all_out:
        return ALL_OUT_HEADLINE
    return STALE_HEADLINE if stale else HEADLINE


def derive_view(
    states: Iterable[ProjectState],
    records: Mapping[tuple[str, str], InboxRecord] | None = None,
    health: Mapping[str, ReadState] | None = None,
    sessions: Iterable[SessionState] = (),
    capacity: Mapping | None = None,
    digest: Mapping | None = None,
    deliveries: Mapping[tuple[str, str], DeliveryState] | None = None,
    now_ms: int | None = None,
    sprints: Mapping[str, SprintState] | None = None,
    managers: bool = True,
    pending: Mapping[str, PendingStop] | None = None,
    signin_runs: Mapping[str, Mapping] | None = None,
    accounts_added: Iterable[str] = (),
    pin: Mapping | None = None,
    pin_launches: Iterable[str] = (),
    registration: Mapping | None = None,
    adoption_items: Iterable[Mapping] = (),
    retry_items: Iterable[Mapping] = (),
    apply_items: Iterable[Mapping] = (),
    confirm_items: Iterable[Mapping] = (),
    trust_items: Iterable[Mapping] = (),
    failure_items: Iterable[Mapping] = (),
    nudges: bool = True,
    looked: str | None = None,
    movement: Mapping[str, ProjectMovement] | None = None,
    activation: Activation | None = None,
    activation_run: LastRun | None = None,
    owner_notices: Mapping[str, tuple[Notice, ...]] | None = None,
    spend: Mapping | None = None,
    project_questions: Mapping[str, Sequence[project_question.AskedQuestion]] | None = None,
) -> dict:
    states = list(states)
    sessions = list(sessions)
    signin_runs = {profile: dict(run) for profile, run in (signin_runs or {}).items()}
    capacity = EMPTY if capacity is None else capacity
    running = Counter(s.profile for s in sessions if s.state != ENDED)
    profile_sessions = {e["profile"]: running[e["profile"]] for e in capacity["profiles"]}
    registered = {s.project_id for s in states}
    health = health or {}
    shown = [r for r in (records or {}).values()
             if r.item.get("project_id") in registered]
    open_items = sorted(
        (r for r in shown if not r.item["answered"] and not is_waiting(r.item)),
        key=lambda r: (-r.item["held_work"], r.waiting_since, r.item["key"],
                       r.item["project_id"]))
    waiting_items = [r for r in shown if is_waiting(r.item)]
    answered = sorted(
        (r for r in shown if r.item["answered"]),
        key=lambda r: (r.waiting_since, r.item["key"], r.item["project_id"]))
    stale_projects = sorted(
        p for p in registered if p in health and not health[p].ok)
    drafted: dict[str, list[SprintState]] = {}
    finished: dict[str, list[SprintState]] = {}
    for sprint in sorted((sprints or {}).values(),
                         key=lambda s: (-s.stated_seq, s.sprint_id)):
        if sprint.project_id in registered:
            kept = finished if _finished(sprint, now_ms) else drafted
            kept.setdefault(sprint.project_id, []).append(sprint)

    briefs = sorted((s for group in drafted.values() for s in group
                     if s.brief is not None and s.brief.decision == NONE),
                    key=lambda s: (s.brief.sent_at, s.sprint_id))
    asked = sorted(((s, q) for group in drafted.values() for s in group
                    for q in open_questions(s)),
                   key=lambda pair: (pair[1].at, pair[0].sprint_id, pair[1].round_id,
                                     pair[1].index))
    stalls = sorted((s for group in drafted.values() for s in group if s.stalled is not None),
                    key=lambda s: (s.stalled_at, s.sprint_id))
    unprogressed = sorted((s for group in drafted.values() for s in group
                           if s.no_progress_at is not None),
                          key=lambda s: (s.no_progress_at, s.sprint_id))
    signins = sorted((e for e in capacity["profiles"]
                      if isinstance(e.get("signin"), Mapping) and e["signin"].get("ask")),
                     key=lambda e: e["profile"])
    adoptions = [dict(item) for item in adoption_items]
    retries = [dict(item) for item in retry_items]
    applies = [dict(item) for item in apply_items]
    confirms = [dict(item) for item in confirm_items]
    trusts = [dict(item) for item in trust_items]
    failures = [dict(item) for item in failure_items]
    registering = _register_entries(registration)
    shown_registration = _shown_registration(registration, states,
                                             (*retries, *applies, *confirms, *failures))
    adopting = (shown_registration is not None
                and (shown_registration.get("status") == "running"
                     or shown_registration.get("adoption") is not None))
    by_id = {state.project_id: state for state in states}
    owned: dict[str, list[SessionState]] = {}
    unmanaged: dict[str, list[SessionState]] = {}
    for session in sessions:
        if session.state == ENDED or session.repo is None:
            continue
        project_id = project_for(session.repo, by_id)
        if project_id is None:
            unmanaged.setdefault(session.repo, []).append(session)
        else:
            owned.setdefault(project_id, []).append(session)

    in_sprint: dict[str, list[SessionState]] = {}
    for project_id in sorted({*drafted, *finished}):
        for sprint in drafted.get(project_id, []) + finished.get(project_id, []):
            name = session_name(project_id, sprint.sprint_id)
            mine = [s for s in owned.get(project_id, ()) if s.name == name]
            if mine:
                in_sprint[sprint.sprint_id] = mine
                owned[project_id] = [s for s in owned[project_id] if s.name != name]

    starts = sorted((s for group in drafted.values() for s in group
                     if failed_start(s, bool(in_sprint.get(s.sprint_id)), managers)),
                    key=lambda s: (s.manager.at, s.sprint_id))
    open_count = (len(briefs) + len(stalls) + len(starts) + len(unprogressed) + len(signins) + len(adoptions)
                  + len(asked) + len(retries) + len(registering) + len(applies) + len(confirms)
                  + len(failures) + len(trusts) + len(open_items))
    all_out = bool(capacity["all_out"])
    if all_out:
        sentence = ALL_OUT_SENTENCE
    elif stale_projects:
        sentence = STALE_SENTENCE.format(projects=", ".join(stale_projects))
    elif briefs:
        sentence = BRIEF_SENTENCE
    elif stalls:
        sentence = MANAGER_SENTENCE
    elif starts:
        sentence = FAILED_START_SENTENCE
    elif unprogressed:
        sentence = PROGRESS_SENTENCE
    elif signins:
        sentence = SIGNIN_SENTENCE
    elif adoptions:
        sentence = ADOPTION_SENTENCE
    elif asked:
        sentence = QUESTION_SENTENCE
    elif retries or applies or confirms or failures or trusts or any(e["questions"] for e in registering):
        sentence = REGISTER_SENTENCE
    elif any(e["text"] for e in registering):
        sentence = REGISTER_TYPE_SENTENCE
    elif any(r.item["reason"] == "decision" and r.item["questions"] for r in open_items):
        sentence = CHOOSE_SENTENCE
    elif any(r.item.get("answers") for r in open_items):
        sentence = ANSWER_SENTENCE
    elif registering and not open_items:
        sentence = REGISTER_STEP_SENTENCE
    elif open_count:
        sentence = NEEDS_SENTENCE
    else:
        sentence = _sentence(len(states), adopting)
    runs: dict[str, list[DeliveryState]] = {}
    for delivery in (deliveries or {}).values():
        runs.setdefault(delivery.session_id, []).append(delivery)
    titles = {s.sprint_id: sprint_title(s) for s in (sprints or {}).values()}
    notices = {pid: _notice_entries(drafted.get(pid, []) + finished.get(pid, []), titles,
                                    open_owner_notices(owner_notices or {}, pid))
               for pid in registered}
    notice_post = {pid: any(takes_notices(s) for s in drafted.get(pid, ())) for pid in registered}
    asks = {pid: _question_threads((project_questions or {}).get(pid, ())) for pid in registered}

    sprint_waits: dict[str, list[dict]] = {}
    project_waits: dict[str, list[dict]] = {}
    for record in sorted(waiting_items, key=lambda r: r.item["key"]):
        owner = next((s for s in drafted.get(record.item["project_id"], ())
                      if ended_at(s) is None and record.item.get("issue") in _named_issues(s)), None)
        into = (project_waits.setdefault(record.item["project_id"], []) if owner is None
                else sprint_waits.setdefault(owner.sprint_id, []))
        into.append(_wait_entry(record))

    def is_active(state: ProjectState) -> bool:
        return (state.open_work > 0 or bool(owned.get(state.project_id))
                or state.project_id in drafted or bool(project_waits.get(state.project_id)))

    active = _order(s for s in states if is_active(s))
    quiet = _order(s for s in states if not is_active(s))
    open_by_project: dict[str, list[InboxRecord]] = {}
    for record in open_items:
        open_by_project.setdefault(record.item["project_id"], []).append(record)
    entries = [_project_entry(s, owned.get(s.project_id, ()), runs, now_ms,
                              drafted.get(s.project_id, ()), managers, in_sprint,
                              open_by_project.get(s.project_id, ()),
                              finished.get(s.project_id, ()), capacity, nudges, looked,
                              (movement or {}).get(s.project_id),
                              notices=notices[s.project_id],
                              notice_post=notice_post[s.project_id],
                              sprint_waits=sprint_waits, waits=project_waits.get(s.project_id, ()),
                              read=health.get(s.project_id), questions=asks[s.project_id])
               for s in active]
    quiet_entries = [_project_entry(s, (), runs, now_ms, (), managers, in_sprint,
                                    finished=finished.get(s.project_id, ()), capacity=capacity,
                                    nudges=nudges, looked=looked,
                                    notices=notices[s.project_id],
                                    notice_post=notice_post[s.project_id],
                                    read=health.get(s.project_id), questions=asks[s.project_id])
                     for s in quiet]
    new_replies = sorted(
        ({"project_id": project["project_id"], "sprint_id": sprint["sprint_id"],
          "title": sprint["title"], "message_id": message["id"], "reply_at": message["reply_at"]}
         for project in (*entries, *quiet_entries)
         for sprint in (*project["sprints"],
                        *(project["finished_sprints"] or {"sprints": ()})["sprints"])
         for message in sprint["messages"] if message["new"]),
        key=lambda r: (datetime.fromisoformat(r["reply_at"]), r["message_id"]))
    if len(quiet_entries) <= FOLD_AFTER:
        entries.extend(quiet_entries)
    else:
        entries.append({
            "type": "quiet_group",
            "label": f"{len(quiet_entries)} quiet projects",
            "count": len(quiet_entries),
            "projects": quiet_entries,
        })
    return {
        "statement": {"inbox_items": open_count,
                      "headline": _headline(open_count, bool(stale_projects), all_out),
                      "sentence": sentence, "stale": bool(stale_projects)},
        "new_replies": new_replies,
        "new_replies_text": (None if not new_replies else
                             NEW_REPLY_TEXT.format(title=new_replies[0]["title"])
                             if len(new_replies) == 1
                             else NEW_REPLIES_TEXT.format(n=len(new_replies))),
        "capacity": capacity,
        "inbox": {"open": [_brief_entry(s) for s in briefs] + [_stall_entry(s) for s in stalls]
                          + [_failed_start_entry(s) for s in starts]
                          + [_progress_entry(s) for s in unprogressed]
                          + [_signin_entry(e, signin_runs) for e in signins]
                          + adoptions
                          + [_question_entry(s, q) for s, q in asked]
                          + retries
                          + trusts
                          + registering
                          + applies
                          + confirms
                          + failures
                          + [_inbox_entry(r, health) for r in open_items],
                  "answered": [_inbox_entry(r, health) for r in answered]},
        "signin_runs": signin_runs,
        "accounts_added": sorted(set(accounts_added)),
        "registration": shown_registration,
        "pin": dict(pin) if pin is not None else None,
        "pin_launches": sorted(set(pin_launches)),
        "profile_sessions": profile_sessions,
        "project_count": len(states),
        "entries": entries,
        "unmanaged": [
            {"type": "unmanaged", "root": root, "name": repo_name(root),
             "label": UNMANAGED_LABEL,
             "outside_sprints": _line(unmanaged[root], runs, now_ms)}
            for root in sorted(unmanaged)],
        "recent_projects": [s.project_id for s in _order(states)],
        "digest": dict(digest) if digest is not None else None,
        "managers": managers,
        "unstopped": [
            {"project_id": stop.project_id, "sprint_id": stop.sprint_id,
             "title": goal_title(stop.goal),
             "text": UNSTOPPED_TEXT.format(reason=stop.reason), "failed_at": stop.failed_at}
            for stop in sorted(
                (p for p in (pending or {}).values()
                 if p.reason is not None and p.project_id in registered),
                key=lambda p: (p.failed_at, p.sprint_id))],
        "activation": _activation_line(activation, activation_run, now_ms),
        "spend": dict(spend) if spend is not None else None,
    }


def _activation_line(activation: Activation | None, run: LastRun | None, now_ms: int | None) -> dict | None:
    """The activation line by the precedence in the module docstring; None when there is nothing to say."""
    pending = activation is not None and bool(activation.changed)

    def line(text: str, state: str, commit: str, root: str, activate: bool) -> dict:
        return {"text": text, "state": state, "commit": commit, "root": root, "activate": activate}

    if run is not None and run.state == "running":
        return line(ACTIVATING_TEXT.format(commit=run.commit[:12]), "running", run.commit, run.root, False)
    if run is not None and run.state in ("activated", "failed"):
        same = pending and activation.commit == run.commit
        recent = (not pending and now_ms is not None and run.finished_ms is not None
                  and now_ms - run.finished_ms < OUTCOME_MS)
        if same or recent:
            if run.state == "activated":
                return line(ACTIVATED_TEXT.format(commit=run.commit[:12]), "activated", run.commit, run.root, False)
            text = ACTIVATION_FAILED_TEXT.format(
                commit=run.commit[:12], reason=run.reason or "", next_step=run.next_step or "")
            return line(text, "failed", run.commit, run.root, same)
    if pending:
        return line(ACTIVATION_TEXT.format(commit=activation.commit[:12]), "pending",
                    activation.commit, activation.root, True)
    return None


def encode_view(view: Mapping) -> bytes:
    return json.dumps(view, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
