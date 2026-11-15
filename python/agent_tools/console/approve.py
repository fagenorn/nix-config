"""The console's adoption approval: the words, rows, fold and view entries (#1054).

Decided in ADR-console-030. The owner approves a ready adoption plan on the page; the console then
applies it, pushes its branch and opens its pull request, and tells the owner in plain words how far
it got. The console never merges: merge safety stays with the forge's required checks. This module
is the pure part (it does no I/O except `retained`); the runners that apply, push and open belong to
the same module and the service owns every append.

Rows. Three kinds record an adoption approved on the page, `STEP` (`event_log.ADOPTION_STEP`),
`PULL` (`event_log.ADOPTION_PULL`) and `REGISTRATION` (`event_log.ADOPTION_REGISTRATION`, #1055,
ADR-console-028 D10); none is in `KEPT_KINDS`. `step_row(payload)` returns `(STEP,
None, dict(payload))` and raises `ValueError` unless the members are exactly `STEP_MEMBERS` (`by`,
`plan_id`, `root`, `project_id`, `step`, `branch`, `commit`, `base`, `pull_request`, `reason`, `note`,
`kept`), `by` is `owner`, `plan_id` and `root` are non-empty strings, `step` is one of `STEPS`
(`applied`, `apply_failed`, `push_failed`, `open_failed`, `opened`), `project_id`, `branch`,
`commit`, `base`, `reason` and `note` are each a string or None, `pull_request` is None or exactly
`{number, url}` (a positive int, not a bool, and a string) and `kept` is None or exactly `{branch,
worktree}` strings. A step in `RESUMABLE` (`applied`, `push_failed`, `open_failed`) or `opened` needs
a string `branch` and `commit`; `opened` also needs a `pull_request` and a string `base`.
`pull_row(plan_id, number, url, state)` returns `(PULL, None, {plan_id, number, url, state})` and
raises `ValueError` unless `state` is one of `PULL_STATES` (`open`, `ready`, `merged`, `closed`) and
`number` is a positive int. `registration_row(payload)` returns `(REGISTRATION, None, dict(payload))`
and raises `ValueError` unless the members are exactly `REGISTRATION_MEMBERS` (`plan_id`, `number`,
`result`, `project_id`, `reason`, `note`), `plan_id` is a non-empty string, `number` a positive int,
`result` one of `REGISTRATION_RESULTS` (`waiting`, `registered`, `refused`), `project_id`, `reason`
and `note` each a string or None, a `registered` row has a non-empty `project_id` and a `refused`
row string `reason` and `note`. `parse_approve_request(body)` takes a UTF-8 JSON object with exactly the
member `plan_id`, a non-empty string with no character below 0x20 and no 0x7F, and returns it; it
raises `ValueError` otherwise.

Fold. `adoptions(events, state=None)` folds over a copy of `state` (never mutated): a valid step row
sets `result[plan_id]` to the payload with `at` (the event's), `pull_state` (`open` for an `opened`
step, else None) and `pull_at` (the event's `at` for an `opened` step, else None); a valid pull row
changes `pull_state` and `pull_at` only when the folded entry's step is `opened` and its
`pull_request` number equals the row's. Invalid rows are skipped. `waiting(adoptions)` lists the
entries with step `opened` and `pull_state` `open` or `ready`, ordered by `plan_id`. Every folded
entry also has `registration`: None, or `{result, project_id, reason, note, at}` of the latest
registration row, which folds only onto an `opened` entry whose pull request number equals the
row's and whose `pull_state` is `merged` (any other row is ignored); a new step row resets it to
None and a pull row keeps it. `enrolling(adoptions)` lists the `opened`, `merged` entries whose
registration is None or `waiting`, ordered by `plan_id`; `retry_entries(adoptions, running)` lists
one `inbox_item` of reason `register_retry` (a question card with the single option `Retry`, keyed
`register-retry/<plan_id>/<registration at>`) per `opened`, `merged` entry whose registration is
`refused` and whose plan id is not in `running`, ordered by `(registration at, plan_id)`.
`inbox_entries(adoptions)` lists one `inbox_item` of reason `adoption` per `opened` entry whose
`pull_state` is `ready`, ordered by `(pull_at, plan_id)`, keyed `adoption/<plan_id>`, headed `The
adoption of <project_id or name> is ready to merge`, with the pull request's `url` and `number`,
`answered` False and `waiting_since` the `pull_at`.

`pull_slug(pull_request)` is the `owner/repo` of an opened step's recorded link (None when the
link is not a GitHub pull request link of that number): the poll reads the repository the pull
request was opened in, never the checkout's origin of the day.

Words. Every reason and note is plain: none holds an error code, a repair id, an HTTP status, a run
kind or an exception name. `branch_of(plan_id)` is the branch apply creates for the plan.
`forge_failure(error, branch, base)` is `(reason, note)` for a failed pull request lookup or open, by
the first rule that matches: not a `ForgeError` (`UNEXPECTED`), `gh_missing`, `gh_timeout`, a
transient `gh_failed`, an HTTP 401 or 403, 422 or 404 read from gh's message, else the forge answered
in a way the console does not understand. `apply_failure(root, plan_id, error, kept, acknowledge)` is
`(reason, note)` for an apply error object: `plan_stale`; the dirty, retained and unavailable
worktree repairs; a failed `adopt.gate.*` gate; an uninstalled platform manifest; else the error's
first violation message and the terminal command (`terminal_note`). `run_failure(plan_id, kind,
acknowledge)` words a failed run by `register.RUN_WORDS`, with a retry note for `RETRY_KINDS`.
`registration_outcome(root, report)` reads the answer of `verify --register` as exactly `{result,
project_id, reason, note}`: `not_integrated` is `waiting` (never refused), a green report is
`registered`, any other is `refused` in plain words ending in `Retry` (`retry_note`; the retry
words replace the register words, never a code, a repair id or `Register again`); `run_outcome(root,
kind)` words a failed run the same way. `reason_of(text)` whitespace-collapses and cuts to
`REASON_CHARS` characters, a cut text ending in the ellipsis. `closed_note` tells the owner what to
do after a pull request was closed. The line words are `applied_line`, `pushed_line`,
`opened_line`, `kept_line`, `running_headline`, `waiting_line`, `registering_line`,
`registered_line` and `refused_line`.

View. `entry(adoption, *, running, name, registering=False)` is the registration's `adoption` member: None for no
adoption, else exactly the keys `status`, `step`, `state`, `headline`, `lines`, `note`, `branch`,
`commit` and `url` (`running` gives status `running`, the running headline and None elsewhere; a
merged pull request's headline reads its registration: waiting, `registering`, registered or
refused, and its `note` is None).
`action(latest, adoption, *, available, running)` is `approve` for a ready plan with no adoption, a
failed apply or a closed pull request, `retry` for a step in `RESUMABLE`, else None (and None unless
`available`, not `running` and `latest` is a ready plan with an id). `acknowledges(latest)` is true
when a plan line starts with `deletes `, the only case a deletion is acknowledged for the owner.
`title(name)` and `body(latest)` word the pull request from the plan. `retained(plan_id)` reads the
kept worktree of a failed apply from its failure record (a file of at most 65536 bytes holding a JSON
object whose `branch` and `worktree` are strings and whose worktree is a directory), else None; it
never raises.

Runners. The console never merges: the forge's required checks keep merge safety, and `GitHubForge`
has no method that merges. `push(root, branch, commit, cancel=None, *, timeout=PUSH_TIMEOUT, environ=None)`
pushes only the one adoption branch, at the one commit apply recorded, by the one refspec
`<commit>:refs/heads/<branch>`: the local branch is never read, so a branch that moved after
apply (a failed push, then more commits) publishes nothing the apply gates did not run on. It is
never forced and has `--no-follow-tags`, so no tag rides along whatever the repository's config
says; it refuses a branch that is not `adopt-<12 hex>` and a commit that is not 40 lowercase hex
digits before any process, runs git in its own
group with prompts off (`GIT_TERMINAL_PROMPT=0`), and raises `PushFailed` (`reason` the page's
words, `detail` git's stderr for the log only, `str(error) == reason`) on a refusal, a timeout, a
cancel or a git that could not be started. `gh_json(argv, cancel=None, *, timeout, environ=None)`
is the console's cancellable `gh` runner: it runs `gh` in its own group with no `GITHUB_TOKEN` or
`GH_TOKEN`, so a set `cancel` (the console is closing) ends the call and its process and raises
`Cancelled`, and its failures are the `ForgeError`s of `forge_api` (`gh_timeout`, `gh_missing`,
`gh_failed`, `payload_invalid`). `GitHubForge(gh_json=gh_json)` offers `find_pull_request(slug,
head, base, cancel=None)` (the open pull request of that head and base as `{number, url}`, else
None), `open_pull_request(slug, head, base, title, body, cancel=None)` and `pull_request_state(slug,
number, cancel=None)` (`merged`, `closed`, `ready` for an open pull request whose `mergeable_state`
is in `READY_MERGEABLE`, else `open`); the link of a pull request is built here from the slug and
number, never read from the forge's answer. `forge_for(platform)` is `GitHubForge()` where
`manager.supported(platform)`, else None.
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

from agent_tools.console import event_log, manager, register
from agent_tools.console.event_log import Event
from agent_tools.project_contract import adopt_apply
from agent_tools.system import forge_api
from agent_tools.system.forge_api import ForgeError

STEP = event_log.ADOPTION_STEP
PULL = event_log.ADOPTION_PULL
REGISTRATION = event_log.ADOPTION_REGISTRATION
STEPS = ("applied", "apply_failed", "push_failed", "open_failed", "opened")
RESUMABLE = ("applied", "push_failed", "open_failed")
PULL_STATES = ("open", "ready", "merged", "closed")
REGISTRATION_RESULTS = ("waiting", "registered", "refused")
REGISTRATION_MEMBERS = {"plan_id", "number", "result", "project_id", "reason", "note"}
STEP_MEMBERS = {"by", "plan_id", "root", "project_id", "step", "branch", "commit", "base",
                "pull_request", "reason", "note", "kept"}
BRANCH = re.compile(r"adopt-[0-9a-f]{12}")
COMMIT = re.compile(r"[0-9a-f]{40}")
PULL_URL = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/pull/([0-9]+)")
REASON_CHARS = 200
RECORD_BYTES = 65536
UNAVAILABLE = "approving an adoption is not available on this host"
STALE = "that plan is no longer the one shown; approve the plan shown now"
NOT_READY = "only a ready plan can be approved"
OPENED = "the pull request of this plan is already open"
PUSH_NOTE = ("Check that the repository's origin can be reached from this host and accepts the "
             "push, then press Try again.")
OPEN_NOTE = ("Check that gh is signed in on this host and can open pull requests on the "
             "repository, then press Try again.")
NO_SLUG = "the repository's origin is not on GitHub"
NO_BASE = "the project contract names no integration branch"
APPLIED_NOTE = "Press Try again to push the branch and open its pull request."
MERGED = "the pull request of this plan was already merged"
NOT_REFUSED = "that registration is not waiting for a retry"
RETRY_AGAIN = "choose Retry."
RETRY_OPTION = "Retry"
RETRY_VALUE = "retry"
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


def parse_approve_request(body: bytes) -> str:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("not a JSON object") from error
    if not isinstance(value, dict) or set(value) != {"plan_id"}:
        raise ValueError("wrong members")
    plan_id = value["plan_id"]
    if not _text(plan_id):
        raise ValueError("not a non-empty string")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in plan_id):
        raise ValueError("control character")
    return plan_id


def _valid_pull_request(value: object) -> bool:
    return (isinstance(value, dict) and set(value) == {"number", "url"}
            and _positive(value["number"]) and isinstance(value["url"], str))


def _valid_kept(value: object) -> bool:
    return (isinstance(value, dict) and set(value) == {"branch", "worktree"}
            and all(isinstance(text, str) for text in value.values()))


def step_row(payload: Mapping) -> tuple[str, None, dict]:
    if (not isinstance(payload, Mapping) or set(payload) != STEP_MEMBERS
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


def pull_row(plan_id: str, number: int, url: str, state: str) -> tuple[str, None, dict]:
    if state not in PULL_STATES or not _positive(number):
        raise ValueError("not an adoption pull request row")
    return (PULL, None, {"plan_id": plan_id, "number": number, "url": url, "state": state})


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


def adoptions(events: Iterable[Event], state: dict | None = None) -> dict[str, dict]:
    result = dict(state or {})
    for event in events:
        try:
            if event.kind == STEP:
                _, _, payload = step_row(event.payload)
                opened = payload["step"] == "opened"
                result[payload["plan_id"]] = {
                    **payload, "at": event.at, "pull_state": "open" if opened else None,
                    "pull_at": event.at if opened else None, "registration": None}
            elif event.kind == PULL:
                payload = event.payload
                _, _, row = pull_row(payload["plan_id"], payload["number"], payload["url"],
                                     payload["state"])
                found = result.get(row["plan_id"])
                if (found is not None and found["step"] == "opened"
                        and found["pull_request"]["number"] == row["number"]):
                    result[row["plan_id"]] = {**found, "pull_state": row["state"],
                                              "pull_at": event.at}
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
            "subject": None, "headline": headline, "why": registration["note"],
            "refusal": None, "more_questions": 0,
            "questions": [{"question": headline, "options": [RETRY_OPTION], "chosen": None,
                           "recommended": None, "recommended_index": None}],
            "values": [RETRY_VALUE], "items": [], "answers": [], "answered": False,
            "waiting_since": registration["at"]})
    return items


def waiting(adoptions: Mapping[str, Mapping]) -> list[dict]:
    return [dict(adoptions[plan_id]) for plan_id in sorted(adoptions)
            if adoptions[plan_id]["step"] == "opened"
            and adoptions[plan_id]["pull_state"] in ("open", "ready")]


def inbox_entries(adoptions: Mapping[str, Mapping]) -> list[dict]:
    ready = [found for found in adoptions.values()
             if found["step"] == "opened" and found["pull_state"] == "ready"]
    ready.sort(key=lambda found: (found["pull_at"], found["plan_id"]))
    return [{"type": "inbox_item", "reason": "adoption", "key": f"adoption/{found['plan_id']}",
             "project_id": found["project_id"], "name": register.name_of(found["root"]),
             "headline": ("The adoption of "
                          f"{found['project_id'] or register.name_of(found['root'])} "
                          "is ready to merge"),
             "url": found["pull_request"]["url"], "number": found["pull_request"]["number"],
             "answered": False, "waiting_since": found["pull_at"]} for found in ready]


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


def closed_note(root: str, branch: str) -> str:
    return (f"Delete the branch {branch} with git -C {root} branch -D {branch} and git -C {root} "
            f"push origin --delete {branch}, then press Approve to apply the plan again.")


def _retry_words(step: str) -> str:
    leading = "P" + register.AGAIN[1:]
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
            first = _collapse(violations[0].get("message") or "")
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


def forge_failure(error: BaseException, branch: str, base: str) -> tuple[str, str]:
    if not isinstance(error, forge_api.ForgeError):
        return (register.UNEXPECTED, OPEN_NOTE)
    if error.code == "gh_missing":
        return ("gh is not installed on this host",
                "Install gh and sign it in with gh auth login, then press Try again.")
    if error.code == "gh_timeout":
        return ("the forge took too long to answer",
                "Press Try again; the console first looks for a pull request the forge may have "
                "opened already.")
    if error.code == "gh_failed":
        if error.transient:
            return ("the forge could not be reached",
                    "Check this host's network connection, then press Try again.")
        found = forge_api.HTTP_STATUS.search(error.detail)
        status = int(found.group(1)) if found else None
        if status in (401, 403):
            return ("gh is not signed in, or may not open pull requests on this repository",
                    "Sign gh in with gh auth login on this host with access to the repository, "
                    "then press Try again.")
        if status == 422:
            return ("the forge refused the pull request",
                    f"Check on the forge that {branch} differs from {base} and has no pull "
                    "request open already, then press Try again.")
        if status == 404:
            return ("the forge does not know the repository or the branch",
                    f"Check that origin is the GitHub repository and that {branch} reached it, "
                    "then press Try again.")
    return ("the forge answered in a way the console does not understand", OPEN_NOTE)


def terminal_note(plan_id: str, acknowledge: bool) -> str:
    flag = " --acknowledge-deletions" if acknowledge else ""
    return (f"Run adopt-project apply --plan-id {plan_id}{flag} in a terminal to see the full "
            "reason.")


def apply_failure(root: str, plan_id: str, error: Mapping, kept: Mapping | None,
                  acknowledge: bool) -> tuple[str, str]:
    repair = error.get("repair_id") or ""
    if error.get("code") == "plan_stale":
        return ("the repository changed since this plan was made",
                "Register the repository again to make a new plan, then approve that one.")
    if repair == "adopt.worktree.dirty":
        return ("an uncommitted change in the repository overlaps what the plan changes",
                f"Commit or set aside the uncommitted change in {root}, then press Approve "
                "again.")
    if repair == "adopt.worktree.retained":
        note = (f"Remove the kept worktree with git worktree remove {kept['worktree']} and "
                f"delete the branch {kept['branch']}, then press Approve again." if kept
                else terminal_note(plan_id, acknowledge))
        return ("an earlier attempt of this plan is still kept", note)
    if repair == "adopt.worktree.unavailable":
        branch = branch_of(plan_id)
        return ("the adoption's branch or worktree could not be created",
                f"If the branch {branch} is left from an earlier attempt, delete it with git -C "
                f"{root} branch -D {branch}, then press Approve again.")
    if repair.startswith(GATE_PREFIX):
        note = (f"Fix what failed in the repository (the kept worktree at {kept['worktree']} "
                f"shows it), remove that worktree and the branch {kept['branch']}, then "
                "register the repository again." if kept
                else terminal_note(plan_id, acknowledge))
        return (f"the {repair[len(GATE_PREFIX):]} check did not pass", note)
    if repair.startswith(register.MANIFEST_PREFIX):
        return ("the agent platform's files are not installed on this host yet",
                "Run just switch in a terminal to install them, then press Approve again.")
    violations = error.get("violations") or []
    message = ""
    if violations and isinstance(violations[0], Mapping):
        message = _collapse(violations[0].get("message") or "")
    return (message or "it could not be applied", terminal_note(plan_id, acknowledge))


def run_failure(plan_id: str, kind: str, acknowledge: bool) -> tuple[str, str]:
    reason = register.RUN_WORDS.get(kind, register.UNEXPECTED)
    if kind in register.RETRY_KINDS:
        return (reason, "Press Approve again. If it keeps failing, r"
                + terminal_note(plan_id, acknowledge)[1:])
    return (reason, terminal_note(plan_id, acknowledge))


def reason_of(text: object) -> str:
    words = _collapse(text)
    return words if len(words) <= REASON_CHARS else words[:REASON_CHARS - 1] + "…"


def applied_line(branch: str, commit: str) -> str:
    return f"Applied on the branch {branch} as one commit, {commit[:12]}."


def pushed_line(branch: str) -> str:
    return f"Pushed {branch} to origin."


def opened_line(number: int, base: str) -> str:
    return f"Opened pull request #{number} against {base}."


def kept_line(kept: Mapping) -> str:
    return f"Apply kept its worktree at {kept['worktree']} and its branch {kept['branch']}."


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
    applied = applied_line(branch, commit) if branch and commit else None
    kept = adoption["kept"]
    note = adoption["note"]
    lines: list[str]
    if step == "applied":
        headline = f"The adoption of {name} was applied, but its branch is not pushed yet."
        lines, note = [applied], APPLIED_NOTE
    elif step == "apply_failed":
        headline = _sentence(f"The adoption of {name} was not applied: {reason}")
        lines = [kept_line(kept)] if kept else []
    elif step == "push_failed":
        headline = _sentence(f"The branch {branch} was not pushed: {reason}")
        lines = [applied]
    elif step == "open_failed":
        headline = _sentence(f"The pull request for {branch} was not opened: {reason}")
        lines = [applied, pushed_line(branch)]
    else:
        lines = [applied, pushed_line(branch), opened_line(pull["number"], adoption["base"])]
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
                headline = refused_line(name, registration["reason"], registration["note"])
            else:
                headline = waiting_line(name, adoption["base"])
        elif state == "closed":
            headline = f"The pull request of {name} was closed without merging."
            note = closed_note(adoption["root"], branch)
        else:
            headline = f"Waiting for the pull request of {name} to be ready to merge."
    return {"status": "done", "step": step, "state": state, "headline": headline,
            "lines": lines, "note": note, "branch": branch, "commit": commit,
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


def body(latest: Mapping) -> str:
    bullets = "\n".join(f"- {line}" for line in latest["lines"])
    return (f"{latest['headline']}\n\n{bullets}\n\nPlan {latest['plan_id']}, approved by the "
            "owner on the console. Merge it once its required checks pass.")


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
    lines = [line for line in stderr.splitlines() if line.strip()]
    raise PushFailed(reason_of(lines[-1]) if lines else "git refused the push",
                     stderr[:DETAIL_CHARS])


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
                    return pull
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

    def pull_request_state(self, slug: str, number: int, cancel=None) -> str:
        answer = self._gh_json(["api", f"repos/{slug}/pulls/{number}"], cancel)
        if isinstance(answer, dict):
            if answer.get("merged") is True:
                return "merged"
            if answer.get("state") == "closed":
                return "closed"
            if answer.get("state") == "open":
                return "ready" if answer.get("mergeable_state") in READY_MERGEABLE else "open"
        raise ForgeError("payload_invalid", "the pull request answer has no state")


def forge_for(platform: str) -> GitHubForge | None:
    return GitHubForge() if manager.supported(platform) else None
