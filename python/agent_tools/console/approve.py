"""The console's adoption approval: the words, rows, fold and view entries (#1054).

Decided in ADR-console-030. The owner approves a ready adoption plan on the page; the console then
applies it, pushes its branch and opens its pull request, and tells the owner in plain words how far
it got. The console merges only on the owner's Merge (ADR-console-088): the forge's branch
protection keeps merge safety. This module is the pure part (it does no I/O except `retained`);
the runners that apply, push, open and merge belong to the same module and the service owns every
append.

Rows. Three kinds record an adoption approved on the page, `STEP` (`event_log.ADOPTION_STEP`),
`PULL` (`event_log.ADOPTION_PULL`) and `REGISTRATION` (`event_log.ADOPTION_REGISTRATION`, #1055,
ADR-console-028 D10); none is in `KEPT_KINDS`. `step_row(payload)` returns `(STEP,
None, dict(payload))` and raises `ValueError` unless the members are exactly `STEP_MEMBERS` (`by`,
`plan_id`, `root`, `project_id`, `step`, `branch`, `commit`, `base`, `pull_request`, `reason`, `note`,
`kept`, `evidence`), `by` is `owner`, `plan_id` and `root` are non-empty strings, `step` is one of `STEPS`
(`applied`, `apply_failed`, `push_failed`, `open_failed`, `opened`), `project_id`, `branch`,
`commit`, `base`, `reason` and `note` are each a string or None, `pull_request` is None or exactly
`{number, url}` or `{number, url, created}` (a positive int, not a bool, a string and a bool: whether
the console made the pull request, absent in a row of an earlier release) and `kept` is None or exactly `{branch,
worktree}` strings and `evidence` is None or exactly `{hook, why, lines}` (`hook` None or
matching `HOOK`, `why` None or a string, `lines` a list of at most `EVIDENCE_LINES` strings of at
most `LINE_CHARS` characters; a stored step without `evidence` reads as None, so rows of an earlier
release still fold). A step in `RESUMABLE` (`applied`, `push_failed`, `open_failed`) or `opened` needs
a string `branch` and `commit`; `opened` also needs a `pull_request` and a string `base`.
`pull_row(plan_id, number, url, state, head=None, base=None)` returns `(PULL, None, {plan_id, number,
url, state, head, base})` and raises `ValueError` unless `state` is one of `PULL_STATES` (`open`, `ready`,
`failing`, `merged`, `closed`), `number` is a positive int, `head` is None or 40 lowercase hex and
`base` is None or a non-empty string (the branch the pull request targets as read). `registration_row(payload)` returns `(REGISTRATION, None, dict(payload))`
and raises `ValueError` unless the members are exactly `REGISTRATION_MEMBERS` (`plan_id`, `number`,
`result`, `project_id`, `reason`, `note`), `plan_id` is a non-empty string, `number` a positive int,
`result` one of `REGISTRATION_RESULTS` (`waiting`, `registered`, `refused`), `project_id`, `reason`
and `note` each a string or None, a `registered` row has a non-empty `project_id` and a `refused`
row string `reason` and `note`. `parse_approve_request(body)` takes a UTF-8 JSON object with exactly the
member `plan_id`, a non-empty string with no character below 0x20 and no 0x7F, and returns it; it
raises `ValueError` otherwise.

Fold. `adoptions(events, state=None)` folds over a copy of `state` (never mutated): a valid step row
sets `result[plan_id]` to the payload with `at` (the event's), `pull_state` (`open` for an `opened`
step, else None), `pull_at` (the event's `at` for an `opened` step, else None) and `pull_head`
and `pull_base` (None: the head and the target branch are unknown until a reading names them); a
valid pull row changes `pull_state`, `pull_at`, `pull_head` and `pull_base` (the row's `head` and
`base`, None when the stored row has none) only when the
folded entry's step is `opened` and its `pull_request` number equals the row's. Invalid rows are
skipped. `waiting(adoptions)` lists the entries with step `opened` and `pull_state` `open`, `ready`
or `failing`, ordered by `plan_id`. `merge_refusal(adoption)` is None when Merge is offered, only
for an `opened` entry whose `pull_request.created` is True, whose `pull_state` is `ready` and
whose `pull_head` equals its `commit` and whose `pull_base` equals its `base`; else the first of
`NO_PULL` (none, or not `opened`), `MERGED`, `CLOSED_PULL`, `FOUND` (`created` not True), `UNREAD`
(no head or no target branch read), `MOVED` (the head is not the recorded commit), `RETARGETED`
(the pull request no longer targets the recorded base), `FAILING`, `NOT_READY_PULL`. Every folded
entry also has `registration`: None, or `{result, project_id, reason, note, at}` of the latest
registration row, which folds only onto an `opened` entry whose pull request number equals the
row's and whose `pull_state` is `merged` (any other row is ignored); a new step row resets it to
None and a pull row keeps it. `enrolling(adoptions)` lists the `opened`, `merged` entries whose
registration is None or `waiting`, ordered by `plan_id`; `retry_entries(adoptions, running)` lists
one `inbox_item` of reason `register_retry` (a question card with the single option `Retry`, keyed
`register-retry/<plan_id>/<registration at>`) per `opened`, `merged` entry whose registration is
`refused` and whose plan id is not in `running`, ordered by `(registration at, plan_id)`.
`inbox_entries(adoptions, shown_root=None)` lists one `inbox_item` of reason `adoption` per
`opened` entry whose `pull_state` is `ready` or `failing`, or `open` with a read head that is not
its `commit` or a read target that is not its `base`, or `closed` while its `root` is not
`shown_root` (None when no registration is shown) and no later `opened` entry of that root exists
(a plan opened again is the adoption now, so the earlier closed one is superseded), never `merged`,
ordered by `(pull_at, plan_id)`, keyed `adoption/<plan_id>`, headed `The adoption of <project_id or
name> is ready to merge` when Merge is offered and `Merge is not offered for the adoption of
<project_id or name>` when not, with the pull request's `url` and `number`, `answered` False,
`waiting_since` the `pull_at`, `plan_id`, `commit`, `merge` (whether `merge_refusal` is None) and
`why` (None, else the `*_WHY` words of the refusal: `MOVED_WHY`, `FAILING_WHY`, `FOUND_WHY`,
`UNREAD_WHY`, `RETARGETED_WHY`, `CLOSED_WHY`). `signature(plan_id)` is the sentence the pull request's body ends
its plan with, `attempt_marker(attempt)` is the invisible line (an HTML comment) that `body(latest, attempt)` ends with when the console opens a pull request, `attempt` being a token the service makes fresh for each create attempt and keeps only in memory, and `console_made(found, name, plan_id, attempt)` is true only when a found pull request's
`title` is `title(name)` and its `body` carries that signature and that attempt's marker (the service asks only of one found after its own open failed: a pull request found before it tried to open one is never the console's), and `parse_merge_request(body)`
takes a UTF-8 JSON object of exactly `{plan_id, number, commit}` (a non-empty plan id as
`parse_approve_request` reads it, a positive int and 40 lowercase hex) and fails as it does. The
words `MERGE_UNAVAILABLE`, `STALE_CARD`, `MERGING` and `MERGED_ELSEWHERE` are the service's
refusals of a merge.

`pull_slug(pull_request)` is the `owner/repo` of an opened step's recorded link (None when the
link is not a GitHub pull request link of that number): the poll reads the repository the pull
request was opened in, never the checkout's origin of the day.

Words. The notes name the option of the card they sit on: `Try again` on a resumable step, `Apply it
again` on a failed apply and on a closed pull request; none says `press` or `Approve`.
`current_note(note)` is a stored note in the words of today: it applies each pair of `LEGACY_WORDS`
(the words an earlier release stored for its buttons) with `str.replace`, None stays None, and the
stored row is never rewritten. Every reason and note is plain: none holds an error code, a repair
id, an HTTP status, a run kind or an exception name.
`branch_of(plan_id)` is the branch apply creates for the plan.
`forge_failure(error, base)` is `(reason, note)` for a failed pull request lookup or open, by
the first rule that matches: not a `ForgeError` (`UNEXPECTED`), `gh_missing`, `gh_timeout`, a
transient `gh_failed`, an HTTP 401 or 403, 422 or 404 read from gh's message, else the forge answered
in a way the console does not understand. `merge_failure(error)` is the plain words of a failed
merge, by the same kind of rules (HTTP 409 reads `MOVED`, 405 that the repository's rules do not
allow the merge yet, 404 that the forge does not know the pull request). `apply_failure(name, error, kept)` is `(reason, note)`
for an apply error object, by the first rule that matches: `plan_stale`; the dirty, retained and
unavailable worktree repairs; `DISCARD_REPAIR` (`adopt.discard.failed`, a copy that could not be
removed, noted `RETAINED_NOTE`); `SIGNING_REPAIR` (`adopt.commit.signing_unavailable`, reason
`SIGNING_REASON`, note `SIGNING_NOTE`); `COMMIT_REPAIR` (`adopt.commit.failed`); a failed
`adopt.gate.*` gate; an uninstalled platform manifest (`MANIFEST_NOTE`, which names `just switch`);
a repair id with a prefix of `APPLY_REASONS`; else `it could not be applied`. It reads no violation
message, so a formatter's output, a worktree path or a plan id never reaches a card (the service
logs them), except the failing hook that `commit_evidence(error, None)` names for `COMMIT_REPAIR`
(reason `the project's <hook> hook stopped the adoption commit: <hook_why(exit)>`, note
`HOOK_NOTE`) and for `SIGNING_REPAIR` (the reason stays `SIGNING_REASON`, so `Turn signed commits
off` is still offered, and the note is `hook_signing_note(hook, why)`, two sentences).
`kept` is not read: no note mentions a leftover copy except `RETAINED_NOTE`, none asks an
agent to remove anything, and every note is at most two sentences. A signing failure whose plan
holds a drafted `commit-signed` of `yes` offers a third option, `SIGNING_OFF_OPTION` (value
`SIGNING_OFF_VALUE`), which the page sends as a draft change to `no`; no note carries a path, a
branch, a hash or a command other than `just switch`.
`commit_evidence(error, kept)` is `{hook, why, lines}` for the `commit_output` member of an apply
error (None unless that member is exactly `{hook, exit, lines}` with `lines` a list of strings,
`hook` None or matching `HOOK`, `exit` None or an int that is not a bool, and `hook` and `exit`
None together): `lines` are the last `EVIDENCE_LINES` results of `evidence_line` that are not None
and `why` is `hook_why(exit)` when a hook is named. `hook_why(code)` words a hook's exit status
(127 a command it runs was not found, 126 could not be executed, -1 could not be started, else
`it ended with exit status <code>`). `evidence_line(text, worktree)` makes one line of git's own
words fit for the page: it removes ANSI CSI and OSC sequences and control characters, shows a path
under the worktree relative to it and any other absolute path (`HOST_PATH`, which leaves a
relative path and a URL whole) as its last segment, cuts a hex run of 12 or more to seven
characters and an ellipsis, collapses whitespace, cuts to `LINE_CHARS` characters, and returns
None for an empty line or one that still matches `PAGE_PATTERN`. These lines are git's own words,
held to `PAGE_PATTERN` and not to the plain-words rule of the reasons and notes.
`run_failure(name, kind)` words a failed run by `register.RUN_WORDS` with the note `Choose
Apply it again. If it keeps failing, ask an agent to apply the adoption of <name> in a terminal,
which shows the full reason.`
`registration_outcome(root, report)` reads the answer of `verify --register` as exactly `{result,
project_id, reason, note}`: `not_integrated` is `waiting` (never refused), a green report is
`registered`, any other is `refused` in plain words ending in `Retry` (`retry_note`; the retry
words replace the register words, never a code, a repair id or `Register again`; a violation
message that holds a path, a hash or a plan id is dropped through `register.plain`, so the reason
is `it could not be registered`); `run_outcome(root, kind)` words a failed run the same way.
`reason_of(text)` whitespace-collapses and cuts to `REASON_CHARS` characters, a cut text ending in
the ellipsis. `CLOSED_NOTE` asks an agent to delete the adoption's branch after a pull request was
closed; `NO_SLUG_NOTE` and `NO_BASE_NOTE` ask the owner to open the pull request by hand and
choose `Not now` (the console cannot open it, so Try again would fail the same way). The line words
are `running_headline`, `waiting_line`, `registering_line`, `registered_line` and `refused_line`;
no entry has a line of its own.

View. `entry(adoption, *, running, name, registering=False)` is the registration's `adoption` member: None for no
adoption, else exactly the keys `status`, `step`, `state`, `headline`, `lines`, `note`, `branch`,
`commit` and `url` (`lines` is `[]` for every step, though `apply_items` shows the `lines` of a failed apply's
`evidence` on its card; a failed push reads `The adoption of <name> was
applied, but its branch was not pushed: <reason>.` and a failed open `The adoption of <name> was
pushed, but its pull request was not opened: <reason>.`; an open pull request reads `The
pull request of <name> is not ready to merge yet.`, and a failing one `The pull request of <name> has a
failed check.`; `running` gives status `running`, the running
headline and None elsewhere; a
merged pull request's headline reads its registration: waiting, `registering`, registered or
refused, and its `note` is None).
`action(latest, adoption, *, available, running)` is the action the card offers: `approve` for a
ready plan with no adoption, a failed apply or a closed pull request, `retry` for a step in
`RESUMABLE`, else None (and None unless `available`, not `running` and `latest` is a ready plan
with an id). `apply_items(latest, adoption, entry, action, *, deferred)` lists the one question
card (an `inbox_item` of reason `register_apply`, `text` False, the options `[<first>, Not now]`
and the values `[apply | retry, not_now]`) that action asks, else `[]`: none when `latest` or the
action is None or when `latest["plan_id"]` is in `deferred`. A ready plan with no adoption asks
`Apply this adoption?` with `Apply it` (key `register-apply/<plan_id>/<latest at>`, the proposed
commit environment's line of a drafted or a reconcile plan (`contract_draft.proposed_lines`,
ADR-console-082, ADR-console-083), then the plan's lines,
as `lines`, and `folder_trust.TRUST_SENTENCE` as `why`: approving also grants the folder's client
trust, #1078, ADR-console-034); with an adoption the ask is the entry's headline and its note is `why` (key
`.../<adoption at>`), the option `Apply it again` for `approve` (waiting since the pull request's
`pull_at`, else the step's `at`) and `Try again` for `retry`. `deferral_row(plan_id)` is the
`(DEFERRED, None, {"plan_id"})` row of a `Not now` (`adoption.deferred`, ValueError for a plan id
that is not a non-empty string), and `deferrals(events, state)` folds `state` plus the plan id of
every such row whose payload is exactly that, skipping any other. `acknowledges(latest)` is true
when a plan line starts with `deletes `, the only case a deletion is acknowledged for the owner.
`title(name)` and `body(latest)` word the pull request from the plan. `retained(plan_id)` reads the
kept worktree of a failed apply from its failure record (a file of at most 65536 bytes holding a JSON
object whose `branch` and `worktree` are strings and whose worktree is a directory), else None; it
never raises. `left_behind(plan_id, root)` is wider: true when the failure record, the worktree directory
or the local `branch_of` branch of a failed apply remains, so a copy whose record was never written (a
timed-out apply) or whose cleanup stopped half way is still found.

Runners. The console merges only on the owner's Merge, through `GitHubForge.merge_pull_request`
pinned to the recorded commit, and the forge's branch protection keeps merge safety (ADR-console-088).
`push(root, branch, commit, cancel=None, *, timeout=PUSH_TIMEOUT, environ=None)`
pushes only the one adoption branch, at the one commit apply recorded, by the one refspec
`<commit>:refs/heads/<branch>`: the local branch is never read, so a branch that moved after
apply (a failed push, then more commits) publishes nothing the apply gates did not run on. It is
never forced and has `--no-follow-tags`, so no tag rides along whatever the repository's config
says; it refuses a branch that is not `adopt-<12 hex>` and a commit that is not 40 lowercase hex
digits before any process, runs git in its own
group with prompts off (`GIT_TERMINAL_PROMPT=0`), and raises `PushFailed` (`reason` the page's
words, `detail` git's stderr for the log only, `str(error) == reason`) on a refusal, a timeout, a
cancel or a git that could not be started; `reason` is `PUSH_REFUSED` for every non-zero git exit,
whatever git printed. `gh_json(argv, cancel=None, *, timeout, environ=None)`
is the console's cancellable `gh` runner: it runs `gh` in its own group with no `GITHUB_TOKEN` or
`GH_TOKEN`, so a set `cancel` (the console is closing) ends the call and its process and raises
`Cancelled`, and its failures are the `ForgeError`s of `forge_api` (`gh_timeout`, `gh_missing`,
`gh_failed`, `payload_invalid`). `GitHubForge(gh_json=gh_json)` offers `find_pull_request(slug,
head, base, cancel=None)` (the open pull request of that head and base as `{number, url, title,
body}`, the title and body as the listing gives them and None when not text, else None),
`open_pull_request(slug, head, base, title, body, cancel=None)`,
`pull_request_reading(slug, number, cancel=None)` (`{state, head, base, checks_error}`: `merged`,
`closed`, `ready` for an open pull request whose `mergeable_state` is in `READY_MERGEABLE`, `failing`
for a `blocked`, `behind` or `dirty` one whose head has a check run of any page concluded in
`FAILED_CONCLUSIONS` or a combined status in `FAILED_STATUSES`, else `open`; `head` is the forge's
head when it is 40 hex and `base` its target branch when a non-empty string, else None; when the
check read of such a pull request fails, the reading is still returned, `open`, with the exception
as `checks_error` (None otherwise) so the head and target it saw are not lost),
`merge_pull_request(slug, number, head, cancel=None)` (a merge of that head only, with the merge
method, refusing a head that is not 40 lowercase hex before any call); the link of a pull request is
built here from the slug and number, never read from the forge's answer. `forge_for(platform)` is
`GitHubForge()` on Linux and macOS (what `manager.supported` admits), else None (ADR-console-081:
the adoption it serves runs wherever a manager does).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from collections.abc import Callable, Collection, Iterable, Mapping
from pathlib import Path
from typing import Any

from agent_tools.console import contract_draft, event_log, folder_trust, manager, register
from agent_tools.console.event_log import Event
from agent_tools.project_contract import adopt_apply
from agent_tools.system import forge_api
from agent_tools.system.forge_api import ForgeError

STEP = event_log.ADOPTION_STEP
PULL = event_log.ADOPTION_PULL
REGISTRATION = event_log.ADOPTION_REGISTRATION
DEFERRED = event_log.ADOPTION_DEFERRED
STEPS = ("applied", "apply_failed", "push_failed", "open_failed", "opened")
RESUMABLE = ("applied", "push_failed", "open_failed")
PULL_STATES = ("open", "ready", "failing", "merged", "closed")
FAILED_CONCLUSIONS = ("failure", "timed_out", "cancelled", "action_required")
FAILED_STATUSES = ("failure", "error")
REGISTRATION_RESULTS = ("waiting", "registered", "refused")
REGISTRATION_MEMBERS = {"plan_id", "number", "result", "project_id", "reason", "note"}
STEP_MEMBERS = {"by", "plan_id", "root", "project_id", "step", "branch", "commit", "base",
                "pull_request", "reason", "note", "kept", "evidence"}
EVIDENCE_LINES = 8
LINE_CHARS = 160
HOOK = re.compile(r"[a-z][a-z-]{0,39}")
# What a line shown on the page may not hold (the page's own pattern, written out here).
PAGE_PATTERN = re.compile(r"--plan-id|sha256:|[0-9a-f]{12,}|(?:^|[\s(\"'])/\S")
# An absolute path of the host: a "/" that no word character, ".", "~" or "/" precedes, and that
# is not the "//" of a URL's authority.
HOST_PATH = re.compile(r"(?<![\w.~/])(?!(?<=[A-Za-z0-9]:)//[^/\s])/[^\s\"'`)\]}>,;]*")
ANSI_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ANSI_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
HEX_RUN = re.compile(r"[0-9a-f]{12,}")
HOOK_NOTE = ("The hook ran in a fresh copy of the repository, in the development environment the "
             "project contract names for its commit, or in none when it names none. Make it pass "
             "there, then choose Apply it again.")
BRANCH = re.compile(r"adopt-[0-9a-f]{12}")
COMMIT = re.compile(r"[0-9a-f]{40}")
PULL_URL = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/pull/([0-9]+)")
REASON_CHARS = 200
RECORD_BYTES = 65536
UNAVAILABLE = "approving an adoption is not available on this host"
STALE = "that plan is no longer the one shown; approve the plan shown now"
NOT_READY = "only a ready plan can be approved"
OPENED = "the pull request of this plan is already open"
MERGE_UNAVAILABLE = "merging an adoption is not available on this host"
NO_PULL = "this plan has no pull request the console opened"
STALE_CARD = "this card is out of date; the page now shows the current one"
CLOSED_PULL = "the pull request of this plan was closed without merging"
FOUND = "the console did not open this pull request"
UNREAD = "the console has not read the pull request's head yet"
MOVED = "the pull request's branch holds commits the console did not push"
RETARGETED = "the pull request no longer targets the branch the console opened it against"
FAILING = "a check of the pull request failed"
NOT_READY_PULL = "the pull request is not ready to merge yet"
MERGING = "the pull request of this plan is being merged"
MERGED_ELSEWHERE = ("the pull request was merged on the forge with commits the console did not "
                    "push")
MOVED_WHY = ("Its branch holds commits the console did not push. Review them on the forge and "
             "merge it there, or close it and choose Apply it again.")
RETARGETED_WHY = ("Its target branch is no longer the one the console opened it against. Review it on "
                  "the forge, or close it and choose Apply it again.")
FAILING_WHY = "A check of its pull request failed. Open the pull request to see which one."
FOUND_WHY = "The console did not open this pull request. Review it on the forge and merge it there."
UNREAD_WHY = "The console has not read its pull request's head yet; Merge is offered once it has."
CLOSED_WHY = "Its pull request was closed without merging. Register the project again to adopt it."
PUSH_NOTE = ("Check that the repository's origin can be reached from this host and accepts the "
             "push, then choose Try again.")
OPEN_NOTE = ("Check that gh is signed in on this host and can open pull requests on the "
             "repository, then choose Try again.")
NO_SLUG = "the repository's origin is not on GitHub"
NO_BASE = "the project contract names no integration branch"
NO_SLUG_NOTE = ("Open a pull request for the adoption's branch yourself on the forge that hosts "
                "origin, then choose Not now.")
NO_BASE_NOTE = ("Open a pull request for the adoption's branch yourself against the branch the "
                "project merges into, then choose Not now.")
PUSH_REFUSED = "origin refused the push or could not be reached"
CLOSED_NOTE = ("Ask an agent to delete the adoption's branch on this computer and on origin, then "
               "choose Apply it again.")
DISCARD_REPAIR = "adopt.discard.failed"
DISCARD_REASON = "the copy that the last attempt left on this computer could not be removed"
RETAINED_NOTE = ("Choose Apply it again to remove the copy that attempt left on this computer and "
                 "apply the plan again.")
SIGNING_REPAIR = "adopt.commit.signing_unavailable"
SIGNING_REASON = ("the project asks for signed commits and this computer could not sign the "
                  "adoption commit")
SIGNING_NOTE = "Set up a signing key on this computer, then choose Apply it again."
SIGNING_FIELD = "commit-signed"
MANIFEST_NOTE = "Run just switch on this computer to install them, then choose Apply it again."
COMMIT_REPAIR = "adopt.commit.failed"
APPLY_REASONS = (
    ("adopt.format.", "a formatter the project declares did not run cleanly"),
    ("adopt.operation.", "one of the plan's changes could not be written"),
    ("adopt.plan.", "the stored plan could not be used"),
    ("adopt.resolver.", "the project contract could not be read"),
    ("adopt.commit.", "the adoption commit did not pass its own checks"),
)
APPLIED_NOTE = "Choose Try again to push the branch and open its pull request."
MERGED = "the pull request of this plan was already merged"
NOT_REFUSED = "that registration is not waiting for a retry"
RETRY_AGAIN = "choose Retry."
RETRY_OPTION = "Retry"
RETRY_VALUE = "retry"
APPLY_ASK = "Apply this adoption?"
APPLY_OPTION = "Apply it"
APPLY_AGAIN_OPTION = "Apply it again"
TRY_AGAIN_OPTION = "Try again"
SIGNING_OFF_OPTION = "Turn signed commits off"
NOT_NOW_OPTION = "Not now"
APPLY_VALUE = "apply"
NOT_NOW_VALUE = "not_now"
SIGNING_OFF_VALUE = "signing_off"
DEFER_STALE = "that plan is no longer the one shown"
NOT_OFFERED = "that plan is not waiting for an answer"
# Notes a console of an earlier release stored, by the words they used for the buttons then.
LEGACY_WORDS = (
    ("then press Try again.", "then choose Try again."),
    ("Press Try again; ", "Choose Try again; "),
    ("then press Approve again.", "then choose Apply it again."),
    ("Press Approve again. If it keeps failing,", "Choose Apply it again. If it keeps failing,"),
    ("then approve that one.", "then apply that one."),
    ("Set up a signing key on this computer, then choose Apply it again. To turn signed commits "
     "off in the project's settings instead, commit that change, then register the repository "
     "again to make a new plan.", SIGNING_NOTE),
    (" A leftover copy of the adoption is kept on this computer; ask an agent to remove it "
     "before you choose Apply it again.", ""),
    ("A leftover copy of the adoption is kept on this computer; ask an agent to remove it, then "
     "choose Apply it again.", RETAINED_NOTE),
    ("Switch this computer to its current configuration to install them, then choose Apply it "
     "again.", MANIFEST_NOTE),
    ("Switch this computer to its current configuration to install them, then choose Retry.",
     register.MANIFEST_STEP.removesuffix(register.AGAIN) + RETRY_AGAIN),
)
NOT_INTEGRATED = "adopt.registration.not_integrated"
UNCHECKED = "the adoption on the remote did not pass the registration's checks"
GATE_PREFIX = "adopt.gate."
PUSH_TIMEOUT = 120
DETAIL_CHARS = 2000
READY_MERGEABLE = ("clean", "unstable", "has_hooks")


def _collapse(text: object) -> str:
    return " ".join(str(text).split())


def _sentence(text: str) -> str:
    return text if text.endswith((".", "!", "?")) else text + "."


def _plain(value: object, kinds: type | tuple) -> bool:
    return isinstance(value, kinds) and not isinstance(value, bool)


def _text_or_none(value: object) -> bool:
    return value is None or isinstance(value, str)


def _text(value: object) -> bool:
    return isinstance(value, str) and value != ""


def _positive(value: object) -> bool:
    return _plain(value, int) and value > 0


def _request(body: bytes, members: set[str]) -> dict:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("not a JSON object") from error
    if not isinstance(value, dict) or set(value) != members:
        raise ValueError("wrong members")
    plan_id = value["plan_id"]
    if not _text(plan_id):
        raise ValueError("not a non-empty string")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in plan_id):
        raise ValueError("control character")
    return value


def parse_approve_request(body: bytes) -> str:
    return _request(body, {"plan_id"})["plan_id"]


def parse_merge_request(body: bytes) -> tuple[str, int, str]:
    value = _request(body, {"plan_id", "number", "commit"})
    if (not _positive(value["number"]) or not isinstance(value["commit"], str)
            or COMMIT.fullmatch(value["commit"]) is None):
        raise ValueError("not a pull request number and commit")
    return (value["plan_id"], value["number"], value["commit"])


def _valid_pull_request(value: object) -> bool:
    return (isinstance(value, dict) and set(value) in ({"number", "url"},
                                                       {"number", "url", "created"})
            and _positive(value["number"]) and isinstance(value["url"], str)
            and isinstance(value.get("created", False), bool))


def _valid_kept(value: object) -> bool:
    return (isinstance(value, dict) and set(value) == {"branch", "worktree"}
            and all(isinstance(text, str) for text in value.values()))


def _valid_evidence(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict) or set(value) != {"hook", "why", "lines"}:
        return False
    hook, why, lines = value["hook"], value["why"], value["lines"]
    return ((hook is None or (isinstance(hook, str) and HOOK.fullmatch(hook) is not None))
            and (why is None or isinstance(why, str))
            and isinstance(lines, list) and len(lines) <= EVIDENCE_LINES
            and all(isinstance(line, str) and len(line) <= LINE_CHARS for line in lines))


def step_row(payload: Mapping) -> tuple[str, None, dict]:
    if isinstance(payload, Mapping) and "evidence" not in payload:
        payload = {"evidence": None, **payload}
    if (not isinstance(payload, Mapping) or set(payload) != STEP_MEMBERS
            or not _valid_evidence(payload["evidence"])
            or payload["by"] != "owner" or not _text(payload["plan_id"])
            or not _text(payload["root"]) or payload["step"] not in STEPS
            or not all(_text_or_none(payload[key]) for key in
                       ("project_id", "branch", "commit", "base", "reason", "note"))
            or (payload["pull_request"] is not None
                and not _valid_pull_request(payload["pull_request"]))
            or (payload["kept"] is not None and not _valid_kept(payload["kept"]))):
        raise ValueError("not an adoption step row")
    step = payload["step"]
    if (step in RESUMABLE or step == "opened") and (
            not isinstance(payload["branch"], str) or not isinstance(payload["commit"], str)):
        raise ValueError("a pushed step names its branch and commit")
    if step == "opened" and (payload["pull_request"] is None
                             or not isinstance(payload["base"], str)):
        raise ValueError("an opened step names its pull request and base")
    return (STEP, None, dict(payload))


def pull_row(plan_id: str, number: int, url: str, state: str, head: str | None = None,
             base: str | None = None) -> tuple[str, None, dict]:
    if (state not in PULL_STATES or not _positive(number)
            or (head is not None and (not isinstance(head, str)
                                      or COMMIT.fullmatch(head) is None))
            or (base is not None and not _text(base))):
        raise ValueError("not an adoption pull request row")
    return (PULL, None, {"plan_id": plan_id, "number": number, "url": url, "state": state,
                         "head": head, "base": base})


def registration_row(payload: Mapping) -> tuple[str, None, dict]:
    if (not isinstance(payload, Mapping) or set(payload) != REGISTRATION_MEMBERS
            or not _text(payload["plan_id"]) or not _positive(payload["number"])
            or payload["result"] not in REGISTRATION_RESULTS
            or not all(_text_or_none(payload[key]) for key in ("project_id", "reason", "note"))):
        raise ValueError("not an adoption registration row")
    result = payload["result"]
    if result == "registered" and not _text(payload["project_id"]):
        raise ValueError("a registered row names its project")
    if result == "refused" and not (isinstance(payload["reason"], str)
                                    and isinstance(payload["note"], str)):
        raise ValueError("a refused row gives its reason and note")
    return (REGISTRATION, None, dict(payload))


def deferral_row(plan_id: str) -> tuple[str, None, dict]:
    if not isinstance(plan_id, str) or plan_id == "":
        raise ValueError("not an adoption deferral row")
    return (DEFERRED, None, {"plan_id": plan_id})


def deferrals(events: Iterable[Event], state: Collection[str] = frozenset()) -> frozenset[str]:
    result = set(state)
    for event in events:
        cancelled = event_log.cancelled_registration(event)
        if cancelled is not None:
            result.discard(cancelled[1])
            continue
        if event.kind != DEFERRED:
            continue
        try:
            _, _, payload = deferral_row(event.payload["plan_id"])
        except (ValueError, KeyError, TypeError):
            continue
        if event.payload == payload:
            result.add(payload["plan_id"])
    return frozenset(result)


def current_note(note: str | None) -> str | None:
    if note is None:
        return None
    for old, new in LEGACY_WORDS:
        note = note.replace(old, new)
    return note


def adoptions(events: Iterable[Event], state: dict | None = None) -> dict[str, dict]:
    result = dict(state or {})
    for event in events:
        cancelled = event_log.cancelled_registration(event)
        if cancelled is not None:
            result.pop(cancelled[1], None)
            continue
        try:
            if event.kind == STEP:
                _, _, payload = step_row(event.payload)
                opened = payload["step"] == "opened"
                result[payload["plan_id"]] = {
                    **payload, "at": event.at, "pull_state": "open" if opened else None,
                    "pull_at": event.at if opened else None, "pull_head": None,
                    "pull_base": None, "registration": None}
            elif event.kind == PULL:
                payload = event.payload
                _, _, row = pull_row(payload["plan_id"], payload["number"], payload["url"],
                                     payload["state"], payload.get("head"),
                                     payload.get("base"))
                found = result.get(row["plan_id"])
                if (found is not None and found["step"] == "opened"
                        and found["pull_request"]["number"] == row["number"]):
                    result[row["plan_id"]] = {**found, "pull_state": row["state"],
                                              "pull_at": event.at, "pull_head": row["head"],
                                              "pull_base": row["base"]}
            elif event.kind == REGISTRATION:
                _, _, row = registration_row(event.payload)
                found = result.get(row["plan_id"])
                if (found is not None and found["step"] == "opened"
                        and found["pull_request"]["number"] == row["number"]
                        and found["pull_state"] == "merged"):
                    result[row["plan_id"]] = {**found, "registration": {
                        "result": row["result"], "project_id": row["project_id"],
                        "reason": row["reason"], "note": row["note"], "at": event.at}}
        except (ValueError, KeyError, TypeError):
            continue
    return result


def _merged(adoptions: Mapping[str, Mapping]) -> list[dict]:
    return [dict(adoptions[plan_id]) for plan_id in sorted(adoptions)
            if adoptions[plan_id]["step"] == "opened"
            and adoptions[plan_id]["pull_state"] == "merged"]


def enrolling(adoptions: Mapping[str, Mapping]) -> list[dict]:
    return [found for found in _merged(adoptions)
            if found.get("registration") is None or found["registration"]["result"] == "waiting"]


def retry_entries(adoptions: Mapping[str, Mapping],
                  running: Collection[str] = frozenset()) -> list[dict]:
    refused = [found for found in _merged(adoptions)
               if found.get("registration") is not None
               and found["registration"]["result"] == "refused"
               and found["plan_id"] not in running]
    refused.sort(key=lambda found: (found["registration"]["at"], found["plan_id"]))
    items = []
    for found in refused:
        name = register.name_of(found["root"])
        registration = found["registration"]
        headline = refused_headline(name, registration["reason"])
        items.append({
            "type": "inbox_item", "reason": "register_retry",
            "key": f"register-retry/{found['plan_id']}/{registration['at']}",
            "project_id": None, "root": found["root"], "name": name,
            "title": f"Register {name}", "plan_id": found["plan_id"], "id": None,
            "subject": None, "headline": headline, "why": current_note(registration["note"]),
            "refusal": None, "more_questions": 0,
            "questions": [{"question": headline, "options": [RETRY_OPTION], "chosen": None,
                           "recommended": None, "recommended_index": None}],
            "values": [RETRY_VALUE], "items": [], "answers": [], "answered": False,
            "waiting_since": registration["at"]})
    return items


def _signing_draft(latest: Mapping) -> bool:
    draft = latest.get("draft")
    return isinstance(draft, list) and any(
        isinstance(row, Mapping) and row.get("field") == SIGNING_FIELD and row.get("value") == "yes"
        for row in draft)


def apply_items(latest: Mapping | None, adoption: Mapping | None, entry: Mapping | None,
                action: str | None, *, deferred: Collection[str] = frozenset()) -> list[dict]:
    if latest is None or action is None or latest["plan_id"] in deferred:
        return []
    plan_id = latest["plan_id"]
    name = register.name_of(latest["root"])
    signing_off = False
    if action == "approve" and adoption is None:
        key, ask, why = (f"register-apply/{plan_id}/{latest['at']}", APPLY_ASK,
                         folder_trust.TRUST_SENTENCE)
        lines = [*contract_draft.proposed_lines(latest.get("draft")), *latest["lines"]]
        first, value, since = APPLY_OPTION, APPLY_VALUE, latest["at"]
    elif action in ("approve", "retry") and adoption is not None and entry is not None:
        key = f"register-apply/{plan_id}/{latest['at']}/{adoption['at']}"
        ask, why, lines = entry["headline"], entry["note"], []
        evidence = adoption.get("evidence")
        if action == "approve" and adoption["step"] == "apply_failed" and evidence is not None:
            lines = list(evidence["lines"])
        if action == "approve":
            first, value = APPLY_AGAIN_OPTION, APPLY_VALUE
            since = adoption["pull_at"] or adoption["at"]
            signing_off = (adoption["step"] == "apply_failed"
                           and adoption["reason"] == SIGNING_REASON and _signing_draft(latest))
        else:
            first, value, since = TRY_AGAIN_OPTION, RETRY_VALUE, adoption["at"]
    else:
        return []
    options, values = [first, NOT_NOW_OPTION], [value, NOT_NOW_VALUE]
    if signing_off:
        options, values = ([first, SIGNING_OFF_OPTION, NOT_NOW_OPTION],
                           [value, SIGNING_OFF_VALUE, NOT_NOW_VALUE])
    return [{
        "type": "inbox_item", "reason": "register_apply", "key": key,
        "project_id": None, "root": latest["root"], "name": name,
        "title": f"Register {name}", "plan_id": plan_id, "id": None, "subject": None,
        "headline": ask, "why": why, "lines": lines, "refusal": None,
        "more_questions": 0, "text": False,
        "questions": [{"question": ask, "options": options, "chosen": None,
                       "recommended": None, "recommended_index": None}],
        "values": values, "items": [], "answers": [], "answered": False,
        "waiting_since": since}]


def waiting(adoptions: Mapping[str, Mapping]) -> list[dict]:
    return [dict(adoptions[plan_id]) for plan_id in sorted(adoptions)
            if adoptions[plan_id]["step"] == "opened"
            and adoptions[plan_id]["pull_state"] in ("open", "ready", "failing")]


def merge_refusal(adoption: Mapping | None) -> str | None:
    if adoption is None or adoption["step"] != "opened":
        return NO_PULL
    state = adoption["pull_state"]
    if state == "merged":
        return MERGED
    if state == "closed":
        return CLOSED_PULL
    if adoption["pull_request"].get("created") is not True:
        return FOUND
    head = adoption["pull_head"]
    if head is None or adoption["pull_base"] is None:
        return UNREAD
    if head != adoption["commit"]:
        return MOVED
    if adoption["pull_base"] != adoption["base"]:
        return RETARGETED
    if state == "failing":
        return FAILING
    if state != "ready":
        return NOT_READY_PULL
    return None


REFUSAL_WHY = {MOVED: MOVED_WHY, RETARGETED: RETARGETED_WHY, FAILING: FAILING_WHY,
               FOUND: FOUND_WHY, UNREAD: UNREAD_WHY, CLOSED_PULL: CLOSED_WHY}


def _on_card(found: Mapping, shown_root: str | None, adoptions: Mapping[str, Mapping]) -> bool:
    if found["step"] != "opened":
        return False
    state = found["pull_state"]
    if state in ("ready", "failing"):
        return True
    if state == "open":
        return ((found["pull_head"] is not None and found["pull_head"] != found["commit"])
                or (found["pull_base"] is not None and found["pull_base"] != found["base"]))
    if state == "closed":
        return found["root"] != shown_root and not any(
            other["root"] == found["root"] and other["step"] == "opened"
            and other["at"] > found["at"] for other in adoptions.values())
    return False


def inbox_entries(adoptions: Mapping[str, Mapping], shown_root: str | None = None) -> list[dict]:
    cards = [found for found in adoptions.values() if _on_card(found, shown_root, adoptions)]
    cards.sort(key=lambda found: (found["pull_at"], found["plan_id"]))
    items = []
    for found in cards:
        refusal = merge_refusal(found)
        name = found["project_id"] or register.name_of(found["root"])
        items.append({
            "type": "inbox_item", "reason": "adoption", "key": f"adoption/{found['plan_id']}",
            "project_id": found["project_id"], "name": register.name_of(found["root"]),
            "headline": (f"The adoption of {name} is ready to merge" if refusal is None
                         else f"Merge is not offered for the adoption of {name}"),
            "url": found["pull_request"]["url"], "number": found["pull_request"]["number"],
            "answered": False, "waiting_since": found["pull_at"],
            "plan_id": found["plan_id"], "commit": found["commit"], "merge": refusal is None,
            "why": REFUSAL_WHY.get(refusal)})
    return items


def pull_slug(pull_request: Mapping) -> str | None:
    """The repository an opened pull request lives in, read from its recorded link.

    The link was built from the slug the pull request was found or opened under (`_pull_request`),
    so it, not the checkout's origin today, names the repository to poll.
    """
    found = PULL_URL.fullmatch(pull_request["url"])
    if found is None or int(found.group(2)) != pull_request["number"]:
        return None
    return found.group(1)


def branch_of(plan_id: str) -> str:
    return f"adopt-{adopt_apply.plan_digest(plan_id)[:12]}"


def _retry_words(step: str) -> str:
    leading = register.AGAIN[0].upper() + register.AGAIN[1:]
    if step.startswith(leading):
        return "Choose Retry." + step.removeprefix(leading)
    if step.endswith(register.AGAIN):
        return step.removesuffix(register.AGAIN) + RETRY_AGAIN
    return f"{step} Then choose Retry."


def retry_note(root: str, error: Mapping) -> str:
    return _retry_words(register.next_step(root, error, "register"))


def run_outcome(root: str, kind: str) -> dict:
    return {"result": "refused", "project_id": None,
            "reason": reason_of(register.RUN_WORDS.get(kind, register.UNEXPECTED)),
            "note": _retry_words(register.run_next_step(root, kind, "register"))}


def registration_outcome(root: str, report: object) -> dict:
    if not isinstance(report, Mapping):
        return run_outcome(root, "unreadable")
    error = report.get("error")
    if isinstance(error, Mapping):
        if error.get("repair_id") == NOT_INTEGRATED:
            return {"result": "waiting", "project_id": None, "reason": None, "note": None}
        violations = error.get("violations")
        first = ""
        if isinstance(violations, list) and violations and isinstance(violations[0], Mapping):
            first = register.plain(_collapse(violations[0].get("message") or ""))
        if (str(error.get("repair_id") or "").startswith(register.MANIFEST_PREFIX)
                and first == register.MANIFEST_ABSENT):
            reason = "the agent platform's files are not installed on this host"
        else:
            reason = reason_of(first or "it could not be registered")
        return {"result": "refused", "project_id": None, "reason": reason,
                "note": retry_note(root, error)}
    project_id = report.get("project_id")
    if report.get("registered") is True and isinstance(project_id, str) and project_id != "":
        return {"result": "registered", "project_id": project_id, "reason": None, "note": None}
    return {"result": "refused", "project_id": None, "reason": UNCHECKED,
            "note": retry_note(root, {})}


def forge_failure(error: BaseException, base: str) -> tuple[str, str]:
    if not isinstance(error, forge_api.ForgeError):
        return (register.UNEXPECTED, OPEN_NOTE)
    if error.code == "gh_missing":
        return ("gh is not installed on this host",
                "Install gh on this computer and sign it in, then choose Try again.")
    if error.code == "gh_timeout":
        return ("the forge took too long to answer",
                "Choose Try again; the console first looks for a pull request the forge may have "
                "opened already.")
    if error.code == "gh_failed":
        if error.transient:
            return ("the forge could not be reached",
                    "Check this host's network connection, then choose Try again.")
        found = forge_api.HTTP_STATUS.search(error.detail)
        status = int(found.group(1)) if found else None
        if status in (401, 403):
            return ("gh is not signed in, or may not open pull requests on this repository",
                    "Sign gh in on this computer with an account that may open pull requests on "
                    "the repository, then choose Try again.")
        if status == 422:
            return ("the forge refused the pull request",
                    f"Check on the forge that the adoption's branch differs from {base} and has "
                    "no pull request open already, then choose Try again.")
        if status == 404:
            return ("the forge does not know the repository or the branch",
                    "Check that origin is the GitHub repository and that the adoption's branch "
                    "reached it, then choose Try again.")
    return ("the forge answered in a way the console does not understand", OPEN_NOTE)


def merge_failure(error: BaseException) -> str:
    if not isinstance(error, forge_api.ForgeError):
        return register.UNEXPECTED
    if error.code == "gh_missing":
        return "gh is not installed on this host"
    if error.code == "gh_timeout":
        return "the forge took too long to answer"
    if error.code == "gh_failed":
        if error.transient:
            return "the forge could not be reached"
        found = forge_api.HTTP_STATUS.search(error.detail)
        status = int(found.group(1)) if found else None
        if status in (401, 403):
            return "gh is not signed in, or may not merge pull requests on this repository"
        if status == 409:
            return MOVED
        if status == 405:
            return "the forge refused the merge; the repository's rules do not allow it yet"
        if status == 404:
            return "the forge does not know the repository or the pull request"
    return "the forge answered in a way the console does not understand"


def hook_why(code: int) -> str:
    if code == 127:
        return "a command it runs was not found"
    if code == 126:
        return "a command it runs could not be executed"
    if code == -1:
        return "it could not be started"
    return f"it ended with exit status {code}"


def hook_signing_note(hook: str, why: str) -> str:
    return (f"The project's {hook} hook also stopped the commit: {why}. Make it pass in a fresh "
            "copy of the repository, in the development environment the project contract names for "
            "its commit or in none when it names none, and set up a signing key on this computer, "
            "then choose Apply it again.")


def evidence_line(text: str, worktree: str | None) -> str | None:
    text = ANSI_OSC.sub("", ANSI_CSI.sub("", text)).replace("\t", " ")
    text = CONTROL.sub("", text)
    if worktree is not None:
        roots = sorted({worktree, os.path.realpath(worktree)}, key=len, reverse=True)
        for root in roots:
            text = text.replace(root + "/", "")
        for root in roots:
            text = text.replace(root, ".")
    text = HOST_PATH.sub(lambda found: (found.group(0).rstrip("/").rsplit("/", 1)[-1]
                                        or "\u2026"), text)
    text = HEX_RUN.sub(lambda found: found.group(0)[:7] + "\u2026", text)
    text = " ".join(text.split())
    if not text:
        return None
    if len(text) > LINE_CHARS:
        text = text[:LINE_CHARS - 1] + "\u2026"
    return None if PAGE_PATTERN.search(text) else text


def commit_evidence(error: Mapping, kept: Mapping | None) -> dict | None:
    output = error.get("commit_output")
    if not isinstance(output, dict) or set(output) != {"hook", "exit", "lines"}:
        return None
    hook, code, lines = output["hook"], output["exit"], output["lines"]
    if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
        return None
    if hook is not None and not (isinstance(hook, str) and HOOK.fullmatch(hook)):
        return None
    if code is not None and (not isinstance(code, int) or isinstance(code, bool)):
        return None
    if (hook is None) != (code is None):
        return None
    worktree = kept["worktree"] if kept else None
    shown = [line for line in (evidence_line(line, worktree) for line in lines)
             if line is not None]
    return {"hook": hook, "why": None if hook is None else hook_why(code),
            "lines": shown[-EVIDENCE_LINES:]}


def apply_failure(name: str, error: Mapping, kept: Mapping | None) -> tuple[str, str]:
    repair = error.get("repair_id") or ""
    commit_note = register.unknown_step(name, "apply").replace("Try again", "Apply it again", 1)
    if error.get("code") == "plan_stale":
        return ("the repository changed since this plan was made",
                "Register the repository again to make a new plan, then apply that one.")
    if repair == "adopt.worktree.dirty":
        return ("an uncommitted change in the repository overlaps what the plan changes",
                f"Set aside the uncommitted change in {name}, then choose Apply it again. To "
                "keep the change instead, commit it, then register the repository again to make "
                "a new plan.")
    if repair == "adopt.worktree.retained":
        return ("an earlier attempt of this plan is still kept", RETAINED_NOTE)
    if repair == DISCARD_REPAIR:
        return (DISCARD_REASON, RETAINED_NOTE)
    if repair == "adopt.worktree.unavailable":
        return ("the adoption's branch or worktree could not be created", commit_note)
    found = commit_evidence(error, None) if repair in (SIGNING_REPAIR, COMMIT_REPAIR) else None
    hook = found["hook"] if found else None
    if repair == SIGNING_REPAIR:
        if hook is None:
            return (SIGNING_REASON, SIGNING_NOTE)
        return (SIGNING_REASON, hook_signing_note(hook, found["why"]))
    if repair == COMMIT_REPAIR:
        if hook is None:
            return ("the adoption commit could not be made", commit_note)
        return (f"the project's {hook} hook stopped the adoption commit: {found['why']}",
                HOOK_NOTE)
    if repair.startswith(GATE_PREFIX):
        return (f"the {repair[len(GATE_PREFIX):]} check did not pass",
                "Fix what failed in the repository, then register the repository again.")
    if repair.startswith(register.MANIFEST_PREFIX):
        return ("the agent platform's files are not installed on this host yet",
                MANIFEST_NOTE)
    for prefix, words in APPLY_REASONS:
        if repair.startswith(prefix):
            return (words, commit_note)
    return ("it could not be applied", commit_note)


def run_failure(name: str, kind: str) -> tuple[str, str]:
    return (register.RUN_WORDS.get(kind, register.UNEXPECTED),
            register.unknown_step(name, "apply").replace("Try again", "Apply it again", 1))


def reason_of(text: object) -> str:
    words = _collapse(text)
    return words if len(words) <= REASON_CHARS else words[:REASON_CHARS - 1] + "…"


def waiting_line(name: str, base: str) -> str:
    return (f"The pull request of {name} was merged; waiting for {base} on origin to carry it "
            "before registering.")


def registering_line(name: str) -> str:
    return f"Registering {name}…"


def registered_line(name: str, project_id: str) -> str:
    return f"{name} is registered as {project_id}."


def refused_headline(name: str, reason: str) -> str:
    return _sentence(f"{name} was not registered: {reason}")


def refused_line(name: str, reason: str, note: str) -> str:
    return refused_headline(name, reason) + " " + note


def running_headline(name: str) -> str:
    return f"Applying the adoption of {name} and opening its pull request…"


def entry(adoption: Mapping | None, *, running: bool, name: str,
          registering: bool = False) -> dict | None:
    if running:
        return {"status": "running", "step": None, "state": None,
                "headline": running_headline(name), "lines": [], "note": None, "branch": None,
                "commit": None, "url": None}
    if adoption is None:
        return None
    step, branch, commit = adoption["step"], adoption["branch"], adoption["commit"]
    reason = adoption["reason"] or ""
    pull = adoption["pull_request"]
    state = adoption["pull_state"]
    note = current_note(adoption["note"])
    if step == "applied":
        headline = f"The adoption of {name} was applied, but its branch is not pushed yet."
        note = APPLIED_NOTE
    elif step == "apply_failed":
        headline = _sentence(f"The adoption of {name} was not applied: {reason}")
    elif step == "push_failed":
        headline = _sentence(
            f"The adoption of {name} was applied, but its branch was not pushed: {reason}")
    elif step == "open_failed":
        headline = _sentence(
            f"The adoption of {name} was pushed, but its pull request was not opened: {reason}")
    else:
        note = None
        if state == "ready":
            headline = f"The pull request of {name} is ready to merge."
        elif state == "merged":
            registration = adoption.get("registration")
            result = registration["result"] if registration else "waiting"
            if registering:
                headline = registering_line(name)
            elif result == "registered":
                headline = registered_line(name, registration["project_id"])
            elif result == "refused":
                headline = refused_line(name, registration["reason"],
                                         current_note(registration["note"]))
            else:
                headline = waiting_line(name, adoption["base"])
        elif state == "closed":
            headline = f"The pull request of {name} was closed without merging."
            note = CLOSED_NOTE
        elif state == "failing":
            headline = f"The pull request of {name} has a failed check."
        else:
            headline = f"The pull request of {name} is not ready to merge yet."
    return {"status": "done", "step": step, "state": state, "headline": headline,
            "lines": [], "note": note, "branch": branch, "commit": commit,
            "url": pull["url"] if pull else None}


def action(latest: Mapping | None, adoption: Mapping | None, *, available: bool,
           running: bool) -> str | None:
    if (not available or running or latest is None or latest["state"] != "ready"
            or not isinstance(latest["plan_id"], str)):
        return None
    if adoption is None or adoption["step"] == "apply_failed":
        return "approve"
    if adoption["step"] in RESUMABLE:
        return "retry"
    if adoption["step"] == "opened" and adoption["pull_state"] == "closed":
        return "approve"
    return None


def acknowledges(latest: Mapping) -> bool:
    return any(line.startswith("deletes ") for line in latest["lines"])


def title(name: str) -> str:
    return f"Adopt {name} onto the agent platform"


def signature(plan_id: str) -> str:
    return f"Plan {plan_id}, approved by the owner on the console."


def attempt_marker(attempt: str) -> str:
    return f"<!-- console-attempt {attempt} -->"


def console_made(found: Mapping, name: str, plan_id: str, attempt: str) -> bool:
    text = found.get("body")
    return (found.get("title") == title(name) and isinstance(text, str)
            and signature(plan_id) in text and attempt_marker(attempt) in text)


def body(latest: Mapping, attempt: str | None = None) -> str:
    bullets = "\n".join(f"- {line}" for line in latest["lines"])
    text = (f"{latest['headline']}\n\n{bullets}\n\n{signature(latest['plan_id'])} Merge it "
            "once its required checks pass.")
    return text if attempt is None else f"{text}\n\n{attempt_marker(attempt)}"


def retained(plan_id: str) -> dict | None:
    try:
        path = adopt_apply.failure_record_path(adopt_apply.plan_digest(plan_id))
        if path.stat().st_size > RECORD_BYTES:
            return None
        record = json.loads(path.read_bytes().decode("utf-8"))
        if (not isinstance(record, dict) or not isinstance(record.get("branch"), str)
                or not isinstance(record.get("worktree"), str)
                or not Path(record["worktree"]).is_dir()):
            return None
        return {"branch": record["branch"], "worktree": record["worktree"]}
    except (adopt_apply.AdoptError, OSError, ValueError):
        return None


def left_behind(plan_id: str, root: str, *, timeout: float = 10.0) -> bool:
    """True when a failed apply of `plan_id` left any copy `Adopter.discard` removes (#1088).

    Every deterministic target counts, not only the pair `retained` shows: the failure record, the
    worktree directory and the local branch of `branch_of`. An apply that timed out leaves the
    directory before it writes a record, and a cleanup that stopped half way leaves the branch.
    An unreadable plan id or a branch that cannot be asked about is False for that target.
    """
    try:
        digest = adopt_apply.plan_digest(plan_id)
        record = adopt_apply.failure_record_path(digest)
        branch = branch_of(plan_id)
    except adopt_apply.AdoptError:
        return False
    if os.path.lexists(record) or os.path.lexists(record.parent / digest):
        return True
    try:
        done = subprocess.run(
            ["git", "-C", root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


class PushFailed(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def push(root: str, branch: str, commit: str, cancel: threading.Event | None = None, *,
         timeout: float = PUSH_TIMEOUT, environ: Mapping[str, str] | None = None) -> None:
    if BRANCH.fullmatch(branch) is None:
        raise PushFailed("that branch is not an adoption branch")
    if COMMIT.fullmatch(commit) is None:
        raise PushFailed("that is not the commit apply recorded")
    env = {**(environ if environ is not None else os.environ), "GIT_TERMINAL_PROMPT": "0"}
    try:
        done = manager.run_in_own_group(
            ["git", "-C", root, "push", "--quiet", "--no-follow-tags", "origin",
             f"{commit}:refs/heads/{branch}"],
            timeout=timeout, cancel=cancel, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, env=env, start_new_session=True)
    except subprocess.TimeoutExpired as error:
        raise PushFailed(register.RUN_WORDS["timed_out"]) from error
    except OSError as error:
        raise PushFailed("git could not be started") from error
    if cancel is not None and cancel.is_set():
        raise PushFailed(register.RUN_WORDS["cancelled"])
    if done.returncode == 0:
        return
    stderr = (done.stderr or b"").decode("utf-8", errors="replace")
    raise PushFailed(PUSH_REFUSED, stderr[:DETAIL_CHARS])


class Cancelled(Exception):
    """A forge call ended because its `cancel` event was set (the console is closing)."""


def gh_json(argv: list[str], cancel: threading.Event | None = None, *,
            timeout: float = forge_api.TIMEOUT, environ: Mapping[str, str] | None = None) -> Any:
    source = environ if environ is not None else os.environ
    env = {key: value for key, value in source.items() if key not in ("GITHUB_TOKEN", "GH_TOKEN")}
    try:
        done = manager.run_in_own_group(
            ["gh", *argv], timeout=timeout, cancel=cancel, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
            env=env)
    except subprocess.TimeoutExpired:
        raise ForgeError("gh_timeout", " ".join(argv)) from None
    except OSError as error:
        raise ForgeError("gh_missing", str(error)) from None
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    if done.returncode != 0:
        raise ForgeError("gh_failed", done.stderr.strip(),
                         transient=forge_api.is_transport(done.stderr))
    try:
        return json.loads(done.stdout)
    except ValueError:
        raise ForgeError("payload_invalid", "stdout is not JSON") from None


def _pull_request(slug: str, number: object) -> dict | None:
    if not _positive(number):
        return None
    return {"number": number, "url": f"https://github.com/{slug}/pull/{number}"}


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


class GitHubForge:
    def __init__(self, gh_json: Callable[..., Any] = gh_json):
        self._gh_json = gh_json

    def find_pull_request(self, slug: str, head: str, base: str, cancel=None) -> dict | None:
        listing = self._gh_json(
            ["api", "-X", "GET", f"repos/{slug}/pulls", "-f", f"head={slug.split('/')[0]}:{head}",
             "-f", f"base={base}", "-f", "state=open"], cancel)
        if not isinstance(listing, list):
            raise ForgeError("payload_invalid", "the pull request listing is not a list")
        for found in listing:
            if (isinstance(found, dict) and isinstance(found.get("head"), dict)
                    and isinstance(found.get("base"), dict)
                    and found["head"].get("ref") == head and found["base"].get("ref") == base):
                pull = _pull_request(slug, found.get("number"))
                if pull is not None:
                    return {**pull, "title": _str_or_none(found.get("title")),
                            "body": _str_or_none(found.get("body"))}
        return None

    def open_pull_request(self, slug: str, head: str, base: str, title: str, body: str,
                          cancel=None) -> dict:
        answer = self._gh_json(
            ["api", "-X", "POST", f"repos/{slug}/pulls", "-f", f"title={title}",
             "-f", f"head={head}", "-f", f"base={base}", "-f", f"body={body}"], cancel)
        pull = _pull_request(slug, answer.get("number")) if isinstance(answer, dict) else None
        if pull is None:
            raise ForgeError("payload_invalid", "the pull request answer has no number")
        return pull

    def pull_request_reading(self, slug: str, number: int, cancel=None) -> dict:
        answer = self._gh_json(["api", f"repos/{slug}/pulls/{number}"], cancel)
        if not isinstance(answer, dict):
            raise ForgeError("payload_invalid", "the pull request answer has no state")
        head = answer.get("head")
        sha = head.get("sha") if isinstance(head, dict) else None
        sha = sha if isinstance(sha, str) and COMMIT.fullmatch(sha) else None
        target = answer.get("base")
        target = target.get("ref") if isinstance(target, dict) else None
        seen = {"head": sha, "base": target if _text(target) else None, "checks_error": None}
        if answer.get("merged") is True:
            return {"state": "merged", **seen}
        if answer.get("state") == "closed":
            return {"state": "closed", **seen}
        if answer.get("state") != "open":
            raise ForgeError("payload_invalid", "the pull request answer has no state")
        mergeable = answer.get("mergeable_state")
        if mergeable in READY_MERGEABLE:
            return {"state": "ready", **seen}
        if mergeable in ("blocked", "behind", "dirty") and sha is not None:
            try:
                if self._failed(slug, sha, cancel):
                    return {"state": "failing", **seen}
            except Cancelled:
                raise
            except Exception as error:
                return {"state": "open", **{**seen, "checks_error": error}}
        return {"state": "open", **seen}

    def _failed(self, slug: str, head: str, cancel) -> bool:
        pages = self._gh_json(["api", "--paginate", "--slurp",
                               f"repos/{slug}/commits/{head}/check-runs?per_page=100"], cancel)
        if not isinstance(pages, list) or not all(
                isinstance(page, dict) and isinstance(page.get("check_runs"), list)
                for page in pages):
            raise ForgeError("payload_invalid", "the check runs are not a list of pages")
        if any(isinstance(run, dict) and run.get("conclusion") in FAILED_CONCLUSIONS
               for page in pages for run in page["check_runs"]):
            return True
        status = self._gh_json(["api", f"repos/{slug}/commits/{head}/status"], cancel)
        if not isinstance(status, dict) or not isinstance(status.get("state"), str):
            raise ForgeError("payload_invalid", "the commit status has no state")
        return status["state"] in FAILED_STATUSES

    def merge_pull_request(self, slug: str, number: int, head: str, cancel=None) -> None:
        if not isinstance(head, str) or COMMIT.fullmatch(head) is None:
            raise ValueError("a merge names the recorded head in full")
        answer = self._gh_json(
            ["api", "-X", "PUT", f"repos/{slug}/pulls/{number}/merge", "-f", f"sha={head}",
             "-f", "merge_method=merge"], cancel)
        if not isinstance(answer, dict) or answer.get("merged") is not True:
            raise ForgeError("payload_invalid", "the merge answer does not say it merged")


def forge_for(platform: str) -> GitHubForge | None:
    return GitHubForge() if manager.supported(platform) else None
