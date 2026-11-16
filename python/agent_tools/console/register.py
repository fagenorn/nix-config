"""The console's project registration: plan a repository's adoption and say what was found (#1052).

Decided in ADR-console-028. The owner names a repository on the page; the console runs the adoption
tools as children, off the request path, and tells the owner in plain words what adopting it would
change. The adoption tools stay the one implementation: nothing here edits a repository or writes the
fleet registry.

Request. `parse_register_request(body)` takes a UTF-8 JSON object with exactly the member `path`,
whose value is a string with no character below 0x20 and no 0x7F (the empty string included:
`refusal` judges the rule, so that an empty path is answered as a refusal, not as a malformed
request), and returns it. It raises `ValueError` otherwise. `expand(path, home)` strips the path and
turns a leading `~` (alone, or before a `/`) into `home`. `name_of(root)` is the last path segment.

Refusals. `refusal(path, entries, *, home, toplevel=checkout_root)` returns `(reason, None)` for the
first failing rule, else `(None, root)`, with no adopter in sight: a refusal never runs a plan. The
rules, in order: `EMPTY` (empty after trimming); `RELATIVE` (the expanded path is not absolute);
`not_directory(path)`; `not_toplevel(path)` (`toplevel(path)` is None); `already_registered(path,
project_id)` (a fleet registry entry whose resolved root equals the resolved path). `checkout_root`
runs `git -C <path> rev-parse --show-toplevel` with no shell, `stdin` and `stderr` to `DEVNULL` and
`GIT_TIMEOUT` (10 seconds), and returns the resolved path only when the exit is 0 and the printed
top, resolved, equals it; otherwise (an `OSError` or a timeout included) it returns None and never
raises. `running(name)` is the text of a second registration for the same repository, decided by the
service. `registry_unreadable()` is the text of a registration refused because the fleet registry
exists but cannot be read (an absent registry is an empty fleet), also decided by the service.
`UNAVAILABLE` is `registering a project is not available on this host`.

Runner. `Adopter(command=None, environ=None, timeout=RUN_TIMEOUT, apply_timeout=APPLY_TIMEOUT)` runs
`[*command, "plan", "--repo-root", root, "--format", "json"]` (`plan`, followed by `--answer <id>
<subject> <value>` for each of its `answers`, in the given order: ADR-console-029 D4, then
`--contract-draft <contract>` when `contract` is given: ADR-console-031) or
`[*command, "verify", "--repo-root", root, "--register"]` (`register`) or `[*command, "apply",
"--plan-id", plan_id]` with `--acknowledge-deletions` and then `--discard-retained` added when asked
(`apply`, #1054, #1088) or `[*command, "discard", "--plan-id", plan_id]` (`discard`, #1088), the command
defaulting to the `adopt_project` sibling module. Each runs with no shell, in its own process group
(`manager.run_in_own_group`), `stdin` and `stderr` to `DEVNULL`, `stdout` piped, `env=dict(environ)`
when `environ` is given (else the console's own) and `timeout` (`RUN_TIMEOUT`, 300 seconds; an apply
runs its gates, so it has its own `apply_timeout`, `APPLY_TIMEOUT`, 1800 seconds). Exit 0
or 2 returns the parsed stdout object. A failed run raises `RunFailed(kind)`, `str(error) == kind`,
`kind` one of `RUN_KINDS`: `cancelled` (the `cancel` event is set), `failed` (any other exit),
`unreadable` (stdout is not a JSON object), `timed_out` (`subprocess.TimeoutExpired`), `not_installed`
(`FileNotFoundError`, or `PermissionError` on the executable) and `unavailable` (any other
`OSError`). `adopter_for(platform)` is `Adopter()` where `manager.supported(platform)`, else None.

Plain lines. `plan_lines(document)` is the D4 list of ADR-console-028, each line only when its count
is above zero, in this order: `moves N agent file(s)` (followed by ` under .agents/` when every move
target starts with `.agents/`), `writes the project contract`, `generates N file(s) from the
contract`, `writes <paths>` (the non-contract files other than the adoption's own records), `records
the adoption` (when the plan writes any record), `deletes <paths>`, `rewrites N link(s)` and `rewrites
N path reference(s)` (the references answered `rewrite` or `extend`). `<paths>` names up to three
paths, as `a`, `a and b`, `a, b and c`, and from four on `a, b, c and N more` (#1057). The adoption's
own records, the two files the plan's `handoff` names as `migration_map` and `evidence_record` (any
other file, even beside them, stays named), are never named: a plan that writes any ends its `writes`
line with `, and records the adoption`, or is the line `records the adoption` when it writes nothing
else, and `NAMED` counts only the named files (#1060). It is a
pure function of the document. `summary(root, plan, report=None, draft=None)` is the row payload
(`by`, `root`, `project_id`, `result`, `outcome`, `headline`, `lines`, `note`, the `EXTRA` members
`plan_id`, `state`, `questions`, `answered`, and `draft`) with the D4 to D6 texts; message text is whitespace-collapsed. A
`bootstrap` or `reconcile` plan carries its header's `plan_id` and `state`, its
`plan_questions.questions`, and its answered decisions as `{id, subject, value}` (ADR-console-029
D1) and the `draft` it was given (the drafted contract's fields, ADR-console-031); every other row
carries `DEFAULTS` (None, None, `[]`, `[]`, None). A ready plan's note is `The plan
is ready.` with no command and no plan id (#1065; ADR-console-030 keeps it, the page offers Approve beside it). A `no_change` plan with no report is
`not_registered` and says `waiting_headline(name)`, `<name> is already adopted and is not registered
yet.`, with the note `CONFIRM_NOTE`, `Choose Register it to register it.` (#1078, ADR-console-034):
the row the Register card waits on. A failed plan's headline is `The adoption plan for <name> failed:
<message>`, or `... could not be made.` when the error has no message, or, when the error's
`repair_id` is `adopt.manifest.*` and its message says the manifest was not found, `The adoption plan for <name> could not start: the agent
platform's files are not installed on this host.` (#1065); a refused registration's is
`<name> was not registered: <message>`, or `... was not registered.`, and for that `repair_id` it is
`<name> was not registered: ` and the same words; any other `adopt.manifest.*` failure keeps its own message; neither shows the error code (#1057). `failed(root, kind, verb="plan")` is the same shape for a run that raised, its headline ending in the
words of `RUN_WORDS[kind]` (an unknown kind reads `it stopped unexpectedly`), never the kind word.

Next step (#1062). Every failed headline ends with a full stop, and every failed row (a plan that
failed, a refused or unconfirmed registration, a run that raised) carries one plain line in `note`
saying what the owner can do next, never an error code, a hash or a path, and no command but `just switch` (#1085). `plain(text)` is
the text, or the empty string when `FORBIDDEN` (`--plan-id`, `sha256:`, a run of twelve hex digits, an
absolute path) finds any in it: a child's raw message is shown only through it, so a message that holds one falls back to
`could not be made.` or `was not registered.`. `next_step(root, error, verb)` reads the
error's `repair_id`: `adopt.manifest.*` with the not-found message says to run `just switch` on this computer to
install the agent platform's files and to choose Try again (`MANIFEST_STEP`, which does not repeat the
cause the headline gave; `LEGACY_NOTES` shows a stored note in the earlier words as it is today and `latest`
applies it, never rewriting the log); `adopt.registration.no_remote`
says to add the origin remote; `remote_default_unknown` (an origin that exists but advertises no
default branch) says the origin needs a published default branch, not another origin;
`adopt.git.remote_unreachable` and
`fetch_failed` say to check the remote can be reached; `adopt.registration.not_integrated` says to
merge the adoption into the remote's main branch; each ends with `AGAIN`, choosing Try again. Any other
failure is `unknown_step(name, verb)`: `Choose Try again. If it keeps failing, ask an agent to <VERB_WORDS[verb]> <name> in a
terminal, which shows the full reason.` `run_next_step(root, kind, verb="plan")` is the line for
a run that raised, `verb` being the operation that raised (`plan`, `register` or `apply`): `unknown_step` for every
kind. A `needs_migration` row says `<name> needs a migration before it can be adopted.` and a `needs_repair` row
`<name> needs a repair before it can be adopted.`, each with a note asking an agent to do it in a terminal, then to choose
Try again. `failed(root, kind, verb="plan")` for the
`register` verb reads `<name> was not registered: <words>.`, so a registration that raised never
sends the owner to rerun the plan that had succeeded.

Register card (#1078, ADR-console-034). `waiting(latest)` is true for that row only (`not_registered`,
`no_change`, the note `CONFIRM_NOTE`); `confirm_items(latest, *, running)` is `[]` unless the latest row
is waiting and no run is under way, else the one inbox item of reason `register_confirm` (key
`register-confirm/<root>/<at>`, headline `CONFIRM_ASK`, `why` the folder-trust sentence, options
`CONFIRM_OPTION` then `LATER_OPTION`, values `CONFIRM_VALUE` then `LATER_VALUE`). The page answers it
with `parse_confirm_request(body)`, exactly `{"root", "choice"}`, `root` a string with no character
below 0x20 and no 0x7F, `choice` one of `CONFIRM_VALUE`, `LATER_VALUE` and `TRY_VALUE` (`ValueError` otherwise).
`dismissed(latest)` is the waiting row with the note `LATER_NOTE`: `Not now` appends it, `waiting` is
false for it, and the card is gone until the owner presses Register again. The failure card (#1085):
`failing(latest)` is true when the latest row's `result` is in `FAILED_RESULTS` and its note is neither
`CONFIRM_NOTE` nor `LATER_NOTE`; `failure_items(latest, *, running)` is `[]` unless the latest row is failing and no
run is under way, else the one inbox item of reason `register_failed` (key `register-failed/<root>/<at>`, headline
the row's headline, `why` its note, options `TRY_OPTION` then `LATER_OPTION`, values `TRY_VALUE` then `LATER_VALUE`).
`parse_confirm_request` takes `TRY_VALUE` as a third choice. `NOT_WAITING` is the text of
a confirmation for a root that is not the waiting one.

Cancel (#1088, ADR-console-037). `CANCELLED` is `event_log.REGISTRATION_CANCELLED`; `cancelled_row(root,
plan_id)` is `(CANCELLED, None, {"by": "owner", "root", "plan_id"})`. `latest` folds the registration to
None when a valid cancel row names the folded row's root and plan id (a cancel naming another, or
malformed, changes nothing; a later `registration.ended` row starts a new registration).
`parse_cancel_request(body)` is exactly `{"root"}`, a non-empty string with no character below 0x20 and
no 0x7F (`ValueError` otherwise). `cancellable(latest, adoption)` is true when `latest` is not None,
its `result` is not `registered` and the plan's folded adoption is None or `apply_failed`.
`CANCEL_REFUSED` and `CANCEL_DISCARD_FAILED` are the service's refusals. `view_entry` carries `cancel`
(false for a running entry, the `cancel` argument for a done one).

Drafting row (ADR-console-031). `drafting(root, fields, answered=())` is the row of a repository with no
project contract: `result` and `state` `drafting`, `project_id` the draft's project-id value (None
when it has none), `headline` `What the console read from <name>: it has no project contract yet`,
`note` `The draft has <N> open question(s).` (singular for one), `plan_id`
`contract_draft.draft_id(root, fields)` (so it changes with any value), `questions`
`contract_draft.questions(fields)`, `answered` as given and `draft` the fields. It names no repair id
or code.

Row. `ended(payload)` is `("registration.ended", None, payload)` and raises `ValueError` unless the
members are exactly `MEMBERS` (a legacy row), `MEMBERS | EXTRA` or `MEMBERS | EXTRA | {"draft"}`
(thirteen members), `by` is `owner`,
`result` is one of `RESULTS` and `lines` is a list of strings; for twelve members also unless
`plan_id` and `state` are strings or None, `questions` is a list of dicts and `answered` is a list
of dicts with exactly the string keys `id`, `subject` and `value` (ADR-console-029 D1); for thirteen
also unless `draft` is None or a list of dicts whose keys are exactly `FIELD_KEYS`. `ENDED` is
`event_log.REGISTRATION_ENDED`, not in `KEPT_KINDS`. `latest(events, state=None)` is the last valid
`ENDED` payload over `DEFAULTS` with `at` added (a saved draft is read back through
`contract_draft.refresh`, and a `drafting` row's questions from it, so an earlier console's wording
never shows, ADR-console-033 D2), else `state`: the view's `registration` member, folded by the service. `view_entry(running, latest, *, again=False, refusal=None, adoption=None,
approve=None)` is that member, always the same twenty keys: the `running` entry (headline `Planning the adoption of <name>…`, or
`again_headline(name)`, `Planning the adoption of <name> again with your answer…`, when `again`)
while a run is under way, with `plan_id`, `state` and `refusal` None and `questions` `[]`; else the
latest with status `done`, its `plan_id`, `state` and `questions`, and `refusal` the text of the
given `{"plan_id", "text", "id", "subject"}` only when its `plan_id` is the latest's, and `refused`
its `{"id", "subject"}` under the same match (the question the refused answer was for), and `draft`
`contract_draft.shown(draft)` when the latest row holds a draft list (None for the running entry and
for any other row), and `draft_more` `contract_draft.more_line(draft)` under the same condition (the
counted line for the shown settings outside the main ones; None otherwise, including when no such
setting is shown); else None (D4). The keys `adoption` and `approve` are None in the `running` entry
and carry the given values (the `approve.entry` object and the action the page offers, #1054) in the
`done` entry. `line` is the entry's state in one line (D6, D7): the running headline while a run is
under way; the given adoption's headline when there is one (the adoption is then the plan's latest
state, so a ready plan never says `ready to apply` beside an applied branch); else `line_of(latest)`:
for a plan or a drafting row with open questions `Register <name>: 1 question open` or `<N> questions
open`, counting every question, answerable or not; for a ready plan `Register <name>: ready to
apply`, whatever the note says; for any other plan the note, else the headline; for any other result
the headline, then a space and the note when it is a non-empty string.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from agent_tools.console import contract_draft, event_log, folder_trust, manager, plan_questions
from agent_tools.system import siblings

ENDED = event_log.REGISTRATION_ENDED
CANCELLED = event_log.REGISTRATION_CANCELLED
RUN_TIMEOUT = 300
APPLY_TIMEOUT = 1800
GIT_TIMEOUT = 10
RESULTS = ("planned", "registered", "not_registered", "needs_migration", "needs_repair", "failed",
           "drafting")
RUN_KINDS = ("not_installed", "timed_out", "unavailable", "failed", "unreadable", "cancelled")
UNAVAILABLE = "registering a project is not available on this host"
EMPTY = "type the path of a repository"
RELATIVE = "type the full path of the repository, starting with / or ~"
OUTCOME_TEXT = {
    "bootstrap": "it has no agent files or project contract yet",
    "reconcile": "it has agent files or a contract to bring up to date",
}
MEMBERS = {"by", "root", "project_id", "result", "outcome", "headline", "lines", "note"}
EXTRA = {"plan_id", "state", "questions", "answered"}
DEFAULTS = {"plan_id": None, "state": None, "questions": [], "answered": [], "draft": None}
FIELD_KEYS = contract_draft.FIELD_KEYS
CONTRACT = ".agents/project.json"
NAMED = 3
RUN_WORDS = {
    "timed_out": "it took too long and was stopped",
    "not_installed": "the adoption tool could not be started",
    "unavailable": "the adoption tool could not be started",
    "cancelled": "it was cancelled",
    "failed": "the adoption tool stopped with an error",
    "unreadable": "the adoption tool gave an answer that could not be read",
}
UNEXPECTED = "it stopped unexpectedly"
AGAIN = "choose Try again."
MANIFEST_STEP = "Run just switch on this computer to install them, then " + AGAIN
# A note an earlier release stored for its manifest step, shown in today's words and never rewritten.
LEGACY_NOTES = {
    "Switch this computer to its current configuration to install them, then choose Try again.":
        MANIFEST_STEP,
}
DISCARD_STEP = ("Choose Try again to remove the copy the last attempt left on this computer and "
                "plan again.")
VERB_WORDS = {"plan": "plan the adoption of", "register": "register",
              "apply": "apply the adoption of"}
FORBIDDEN = re.compile(r"--plan-id|sha256:|[0-9a-f]{12,}|(?:^|[\s(\"'])/\S")
FAILED_RESULTS = ("failed", "not_registered", "needs_migration", "needs_repair")
REMOTE_STEP = "Add the repository's origin remote, then " + AGAIN
DEFAULT_BRANCH_STEP = ("The repository's origin remote needs a published default branch. Push one to "
                       "it, then " + AGAIN)
UNREACHABLE_STEP = ("Check that the repository's remote can be reached from this host, then "
                    + AGAIN)
INTEGRATED_STEP = "The adoption is not on the remote's main branch yet. Merge it, then " + AGAIN
RETRY_KINDS = ("timed_out", "not_installed", "unavailable", "cancelled")
NEXT_STEPS = {
    "adopt.registration.no_remote": REMOTE_STEP,
    "adopt.registration.remote_default_unknown": DEFAULT_BRANCH_STEP,
    "adopt.git.remote_unreachable": UNREACHABLE_STEP,
    "adopt.git.fetch_failed": UNREACHABLE_STEP,
    "adopt.registration.not_integrated": INTEGRATED_STEP,
}
MANIFEST_PREFIX = "adopt.manifest."
MANIFEST_ABSENT = "the installed platform manifest was not found"
PLATFORM_MISSING = "the agent platform's files are not installed on this host."
CONFIRM_NOTE = "Choose Register it to register it."
CONFIRM_ASK = "Register this project?"
CONFIRM_OPTION = "Register it"
CONFIRM_VALUE = "register"
LATER_OPTION = "Not now"
LATER_VALUE = "not_now"
LATER_NOTE = "Not registered. Press Register again to register it."
TRY_OPTION = "Try again"
TRY_VALUE = "try_again"
NOT_WAITING = "that project is not waiting to be registered"
CANCEL_REFUSED = "only a registration that was not applied yet can be cancelled"
CANCEL_DISCARD_FAILED = ("The copy that the failed attempt left on this computer could not be removed, "
                         "so the registration was not cancelled. Choose Cancel registration to try again.")


def not_directory(path: str) -> str:
    return f"{path} is not a directory on this host"


def not_toplevel(path: str) -> str:
    return f"{path} is not the top of a git checkout"


def already_registered(path: str, project_id: str) -> str:
    return f"{path} is already registered as {project_id}"


def registry_unreadable() -> str:
    return "the project registry exists but cannot be read, so no registration was started"


def running(name: str) -> str:
    return f"a registration is already running for {name}"


def waiting_headline(name: str) -> str:
    return f"{name} is already adopted and is not registered yet."


def parse_register_request(body: bytes) -> str:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("not a JSON object") from error
    if not isinstance(value, dict) or set(value) != {"path"} or not isinstance(value["path"], str):
        raise ValueError("wrong members")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value["path"]):
        raise ValueError("control character")
    return value["path"]


def expand(path: str, home: str) -> str:
    path = path.strip()
    if path == "~":
        return home
    if path.startswith("~/"):
        return home + path[1:]
    return path


def name_of(root: str) -> str:
    return Path(root).name


def checkout_root(path: str) -> Path | None:
    try:
        done = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
        if done.returncode != 0:
            return None
        top = Path(done.stdout.decode("utf-8").rstrip("\n")).resolve()
        root = Path(path).resolve()
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return root if top == root else None


def refusal(path: str, entries: Iterable[Mapping], *, home: str,
            toplevel=checkout_root) -> tuple[str | None, Path | None]:
    if not path.strip():
        return (EMPTY, None)
    expanded = expand(path, home)
    if not expanded.startswith("/"):
        return (RELATIVE, None)
    if not os.path.isdir(expanded):
        return (not_directory(expanded), None)
    root = toplevel(expanded)
    if root is None:
        return (not_toplevel(expanded), None)
    for entry in entries:
        if Path(entry["root"]).resolve() == root:
            return (already_registered(expanded, entry["project_id"]), None)
    return (None, root)


def _count(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _named(paths: Sequence[str]) -> str:
    if len(paths) > NAMED:
        return f"{', '.join(paths[:NAMED])} and {len(paths) - NAMED} more"
    if len(paths) > 1:
        return f"{', '.join(paths[:-1])} and {paths[-1]}"
    return paths[0]


def plan_lines(document: Mapping) -> list[str]:
    changes = document["changes"]
    moves = [op for op in changes if op["op"] == "git-mv"]
    writes = [op for op in changes if op["op"] == "write-file"]
    contract = any(CONTRACT in op["targets"] for op in writes)
    moved = sum(len(op["sources"]) for op in moves)
    generated = sum(len(op["targets"]) for op in changes if op["op"] == "regenerate-projection")
    written = [path for op in writes if CONTRACT not in op["targets"] for path in op["targets"]]
    handoff = document.get("handoff") or {}
    records = {handoff.get("migration_map"), handoff.get("evidence_record")} - {None}
    other = [path for path in written if path not in records]
    recorded = len(other) != len(written)
    deleted = [path for op in changes if op["op"] == "delete-file" for path in op["sources"]]
    rewrites = document["link_rewrites"]
    links = rewrites["inbound"]["links"] + rewrites["outbound"]["links"]
    references = sum(1 for row in document["path_references"]
                     if row.get("answer") in ("rewrite", "extend"))
    lines = []
    if moved:
        under = all(target.startswith(".agents/") for op in moves for target in op["targets"])
        lines.append(f"moves {_count(moved, 'agent file')}" + (" under .agents/" if under else ""))
    if contract:
        lines.append("writes the project contract")
    if generated:
        lines.append(f"generates {_count(generated, 'file')} from the contract")
    if other:
        lines.append(f"writes {_named(other)}" + (", and records the adoption" if recorded else ""))
    elif recorded:
        lines.append("records the adoption")
    if deleted:
        lines.append(f"deletes {_named(deleted)}")
    if links:
        lines.append(f"rewrites {_count(links, 'link')}")
    if references:
        lines.append(f"rewrites {_count(references, 'path reference')}")
    return lines


def _collapse(text: object) -> str:
    return " ".join(str(text).split())


def plain(text: str) -> str:
    """The text, or "" when it holds a plan id, a hash or an absolute path (a child's raw words)."""
    return text if FORBIDDEN.search(text) is None else ""


def _error_message(error: Mapping) -> str:
    violations = error.get("violations") or []
    if violations and isinstance(violations[0], Mapping):
        return plain(_collapse(violations[0].get("message") or ""))
    return ""


def _sentence(text: str) -> str:
    return text if text.endswith((".", "!", "?")) else text + "."


def unknown_step(name: str, verb: str) -> str:
    return (f"Choose Try again. If it keeps failing, ask an agent to {VERB_WORDS[verb]} {name} in a "
            "terminal, which shows the full reason.")


def run_next_step(root: str, kind: str, verb: str = "plan") -> str:
    return unknown_step(name_of(root), verb)


def _is_manifest(error: Mapping) -> bool:
    """True only for a manifest refusal whose reason is that the file is absent.

    `adopt.manifest.*` also covers an unreadable or invalid manifest and a missing or
    ambiguous migration step, which `just switch` may not cure: those keep their own words.
    """
    return (str(error.get("repair_id") or "").startswith(MANIFEST_PREFIX)
            and _error_message(error) == MANIFEST_ABSENT)


def next_step(root: str, error: Mapping, verb: str) -> str:
    repair_id = str(error.get("repair_id") or "")
    if _is_manifest(error):
        return MANIFEST_STEP
    if repair_id == "adopt.discard.failed":
        return DISCARD_STEP
    return NEXT_STEPS.get(repair_id) or unknown_step(name_of(root), verb)


def _row(root: str, project_id: str | None, result: str, outcome: str | None, headline: str,
         lines: list[str], note: str | None, *, plan_id: str | None = None,
         state: str | None = None, questions: Iterable[dict] = (),
         answered: Iterable[dict] = (), draft: list[dict] | None = None) -> dict:
    return {"by": "owner", "root": root, "project_id": project_id, "result": result,
            "outcome": outcome, "headline": headline, "lines": lines, "note": note,
            "plan_id": plan_id, "state": state, "questions": list(questions),
            "answered": list(answered), "draft": draft}


def drafting(root: str, fields: list[dict], answered: Sequence[Mapping] = ()) -> dict:
    """The row of a repository with no contract: the draft the console made and its open fields."""
    project_id = next((f["value"] for f in fields if f["field"] == "project-id"), None)
    questions = contract_draft.questions(fields)
    return _row(root, project_id, "drafting", None,
                f"What the console read from {name_of(root)}: it has no project contract yet", [],
                f"The draft has {_count(len(questions), 'open question')}.",
                plan_id=contract_draft.draft_id(root, fields), state="drafting",
                questions=questions, answered=answered, draft=fields)


def _answered(document: Mapping) -> list[dict]:
    return [{"id": a["id"], "subject": a["subject"], "value": a["value"]}
            for a in document.get("decisions", {}).get("answered", [])]


def _note(plan: Mapping, document: Mapping) -> str:
    if plan.get("state") == "ready":
        return "The plan is ready."
    questions = len(document.get("decisions", {}).get("open", []))
    if questions:
        return f"The plan has {_count(questions, 'open question')}."
    blockers = plan.get("blockers") or []
    if blockers:
        return f"The plan is a draft: {_collapse(blockers[0]['message'])}"
    return "The plan is a draft."


def summary(root: str, plan: Mapping, report: Mapping | None = None,
            draft: list[dict] | None = None) -> dict:
    name = name_of(root)
    if "error" in plan:
        message = _error_message(plan["error"])
        if _is_manifest(plan["error"]):
            text = f"The adoption plan for {name} could not start: {PLATFORM_MISSING}"
        else:
            text = (_sentence(f"The adoption plan for {name} failed: {message}") if message
                    else f"The adoption plan for {name} could not be made.")
        return _row(root, None, "failed", None, text, [], next_step(root, plan["error"], "plan"))
    header = plan["plan"]
    outcome = header["outcome"]
    project_id = report.get("project_id") if report is not None else header.get("project_id")
    if outcome in OUTCOME_TEXT:
        return _row(root, project_id, "planned", outcome,
                    f"What adopting {name} would change: {OUTCOME_TEXT[outcome]}",
                    plan_lines(plan), _note(header, plan), plan_id=header.get("plan_id"),
                    state=header.get("state"), questions=plan_questions.questions(plan),
                    answered=_answered(plan), draft=draft)
    if outcome == "no_change":
        if report is not None and "error" in report:
            message = _error_message(report["error"])
            if _is_manifest(report["error"]):
                text = f"{name} was not registered: {PLATFORM_MISSING}"
            else:
                text = (_sentence(f"{name} was not registered: {message}") if message
                        else f"{name} was not registered.")
            return _row(root, project_id, "not_registered", outcome, text, [],
                        next_step(root, report["error"], "register"))
        if report is not None and report.get("registered") is True:
            return _row(root, project_id, "registered", outcome,
                        f"{name} is registered as {report.get('project_id')}.", [], None)
        if report is None:
            return _row(root, project_id, "not_registered", outcome, waiting_headline(name), [],
                        CONFIRM_NOTE, answered=_answered(plan))
        result = plain(_collapse(report.get("result")))
        return _row(root, project_id, "not_registered", outcome,
                    _sentence(f"{name} was not registered: {result}") if result
                    else f"{name} was not registered.", [], unknown_step(name, "register"))
    if outcome == "migration_required":
        return _row(root, project_id, "needs_migration", outcome,
                    f"{name} needs a migration before it can be adopted.", [],
                    "Ask an agent to migrate it in a terminal, then " + AGAIN)
    if outcome == "repair_required":
        return _row(root, project_id, "needs_repair", outcome,
                    f"{name} needs a repair before it can be adopted.", [],
                    "Ask an agent to repair its project contract in a terminal, then " + AGAIN)
    return failed(root, "unreadable")


def failed(root: str, kind: str, verb: str = "plan") -> dict:
    words = RUN_WORDS.get(kind, UNEXPECTED)
    headline = (f"{name_of(root)} was not registered: {words}." if verb == "register"
                else f"The adoption plan for {name_of(root)} failed: {words}.")
    return _row(root, None, "failed", None, headline, [], run_next_step(root, kind, verb))


def _draft_valid(draft: object) -> bool:
    return draft is None or (isinstance(draft, list) and all(
        isinstance(f, dict) and set(f) == FIELD_KEYS for f in draft))


def _extras_valid(payload: Mapping) -> bool:
    answered = payload["answered"]
    return (_draft_valid(payload.get("draft")) and all(payload[key] is None or isinstance(payload[key], str)
                for key in ("plan_id", "state"))
            and isinstance(payload["questions"], list)
            and all(isinstance(q, dict) for q in payload["questions"])
            and isinstance(answered, list)
            and all(isinstance(a, dict) and set(a) == {"id", "subject", "value"}
                    and all(isinstance(v, str) for v in a.values()) for a in answered))


def ended(payload: Mapping) -> tuple[str, None, dict]:
    if (not isinstance(payload, Mapping) or set(payload) not in (MEMBERS, MEMBERS | EXTRA, MEMBERS | EXTRA | {"draft"})
            or payload["by"] != "owner"
            or payload["result"] not in RESULTS or not isinstance(payload["lines"], list)
            or not all(isinstance(line, str) for line in payload["lines"])
            or (set(payload) != MEMBERS and not _extras_valid(payload))):
        raise ValueError("not a registration row")
    return (ENDED, None, dict(payload))


def latest(events: Iterable[event_log.Event], state: dict | None = None) -> dict | None:
    found = state
    for event in events:
        cancelled = event_log.cancelled_registration(event)
        if cancelled is not None:
            if found is not None and cancelled == (found["root"], found["plan_id"]):
                found = None
            continue
        if event.kind != ENDED:
            continue
        try:
            _, _, payload = ended(event.payload)
        except ValueError:
            continue
        found = {**DEFAULTS, **payload, "at": event.at}
        if isinstance(found["note"], str) and found["note"] in LEGACY_NOTES:
            found["note"] = LEGACY_NOTES[found["note"]]
        if isinstance(found["draft"], list) and isinstance(found["root"], str):
            found["draft"] = contract_draft.refresh(found["root"], found["draft"])
            if found["result"] == "drafting":
                found["questions"] = contract_draft.questions(found["draft"])
    return found


def waiting(latest: Mapping | None) -> bool:
    return (latest is not None and latest.get("result") == "not_registered"
            and latest.get("outcome") == "no_change" and latest.get("note") == CONFIRM_NOTE)


def dismissed(latest: Mapping) -> dict:
    return {**{key: latest[key] for key in MEMBERS | EXTRA | {"draft"} if key in latest},
            "note": LATER_NOTE}


def confirm_items(latest: Mapping | None, *, running: bool) -> list[dict]:
    if running or not waiting(latest):
        return []
    root, at = latest["root"], latest["at"]
    name = name_of(root)
    return [{
        "type": "inbox_item", "reason": "register_confirm", "key": f"register-confirm/{root}/{at}",
        "project_id": None, "root": root, "name": name, "title": f"Register {name}",
        "plan_id": None, "id": None, "subject": None, "headline": CONFIRM_ASK,
        "why": folder_trust.TRUST_SENTENCE, "lines": [], "refusal": None, "more_questions": 0,
        "text": False,
        "questions": [{"question": CONFIRM_ASK, "options": [CONFIRM_OPTION, LATER_OPTION],
                       "chosen": None, "recommended": None, "recommended_index": None}],
        "values": [CONFIRM_VALUE, LATER_VALUE], "items": [], "answers": [], "answered": False,
        "waiting_since": at}]


def failing(latest: Mapping | None) -> bool:
    return (latest is not None and latest.get("result") in FAILED_RESULTS
            and latest.get("note") not in (CONFIRM_NOTE, LATER_NOTE))


def failure_items(latest: Mapping | None, *, running: bool) -> list[dict]:
    if running or not failing(latest):
        return []
    root, at = latest["root"], latest["at"]
    name = name_of(root)
    return [{
        "type": "inbox_item", "reason": "register_failed", "key": f"register-failed/{root}/{at}",
        "project_id": None, "root": root, "name": name, "title": f"Register {name}",
        "plan_id": latest["plan_id"], "id": None, "subject": None,
        "headline": latest["headline"], "why": latest["note"], "lines": [], "refusal": None,
        "more_questions": 0, "text": False,
        "questions": [{"question": latest["headline"], "options": [TRY_OPTION, LATER_OPTION],
                       "chosen": None, "recommended": None, "recommended_index": None}],
        "values": [TRY_VALUE, LATER_VALUE], "items": [], "answers": [], "answered": False,
        "waiting_since": at}]


def parse_confirm_request(body: bytes) -> tuple[str, str]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("not a JSON object") from error
    if not isinstance(value, dict) or set(value) != {"root", "choice"}:
        raise ValueError("wrong members")
    root, choice = value["root"], value["choice"]
    if not isinstance(root, str) or not root or not isinstance(choice, str):
        raise ValueError("wrong types")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in root):
        raise ValueError("control character")
    if choice not in (CONFIRM_VALUE, LATER_VALUE, TRY_VALUE):
        raise ValueError("unknown choice")
    return root, choice


def cancelled_row(root: str, plan_id: str | None) -> tuple[str, None, dict]:
    return (CANCELLED, None, {"by": "owner", "root": root, "plan_id": plan_id})


def parse_cancel_request(body: bytes) -> str:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("not a JSON object") from error
    if not isinstance(value, dict) or set(value) != {"root"}:
        raise ValueError("wrong members")
    root = value["root"]
    if not isinstance(root, str) or not root:
        raise ValueError("wrong types")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in root):
        raise ValueError("control character")
    return root


def cancellable(latest: Mapping | None, adoption: Mapping | None) -> bool:
    """True for a registration the owner may cancel: not registered and not applied yet."""
    return (latest is not None and latest["result"] != "registered"
            and (adoption is None or adoption["step"] == "apply_failed"))


def again_headline(name: str) -> str:
    return f"Planning the adoption of {name} again with your answer…"


def line_of(latest: Mapping) -> str:
    """The one line a finished entry says: open questions, ready, the note or the headline."""
    if latest["result"] in ("planned", "drafting"):
        name = name_of(latest["root"])
        if latest["questions"]:
            return f"Register {name}: {_count(len(latest['questions']), 'question')} open"
        if latest["state"] == "ready":
            return f"Register {name}: ready to apply"
        return latest["note"] or latest["headline"]
    note = latest["note"]
    return f"{latest['headline']} {note}" if isinstance(note, str) and note else latest["headline"]


def view_entry(running: str | None, latest: Mapping | None, *, again: bool = False,
               refusal: Mapping | None = None, adoption: Mapping | None = None,
               approve: str | None = None, cancel: bool = False) -> dict | None:
    if running is not None:
        name = name_of(running)
        headline = again_headline(name) if again else f"Planning the adoption of {name}\u2026"
        return {"root": running, "name": name, "project_id": None, "status": "running",
                "result": None, "outcome": None, "headline": headline,
                "lines": [], "note": None, "at": None, "plan_id": None, "state": None,
                "questions": [], "refusal": None, "line": headline, "refused": None,
                "draft": None, "draft_more": None, "adoption": None, "approve": None,
                "cancel": False}
    if latest is None:
        return None
    mine = refusal is not None and refusal["plan_id"] == latest["plan_id"]
    draft = latest.get("draft")
    if adoption is not None:
        lines, draft = [], None
        line = adoption["headline"] + (" " + adoption["note"] if adoption["note"] else "")
    else:
        lines, line = latest["lines"], line_of(latest)
    return {"root": latest["root"], "name": name_of(latest["root"]),
            "project_id": latest["project_id"], "status": "done", "result": latest["result"],
            "outcome": latest["outcome"], "headline": latest["headline"],
            "lines": lines, "note": latest["note"], "at": latest["at"],
            "plan_id": latest["plan_id"], "state": latest["state"],
            "questions": latest["questions"], "refusal": refusal["text"] if mine else None,
            "line": line,
            "refused": {"id": refusal["id"], "subject": refusal["subject"]} if mine else None,
            "draft": contract_draft.shown(draft) if isinstance(draft, list) else None,
            "draft_more": contract_draft.more_line(draft) if isinstance(draft, list) else None,
            "adoption": adoption, "approve": approve, "cancel": cancel}


class RunFailed(Exception):
    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


class Adopter:
    def __init__(self, *, command: Sequence[str] | None = None,
                 environ: Mapping[str, str] | None = None, timeout: float = RUN_TIMEOUT,
                 apply_timeout: float = APPLY_TIMEOUT):
        self._command = (tuple(command) if command is not None
                         else tuple(siblings.sibling_argv("project_contract.adopt_project")))
        self._environ = environ
        self._timeout = timeout
        self._apply_timeout = apply_timeout

    def plan(self, root: str, cancel=None, answers: Sequence[Mapping[str, str]] = (),
             contract: str | None = None) -> dict:
        arguments = ["plan", "--repo-root", root, "--format", "json"]
        for answer in answers:
            arguments += ["--answer", answer["id"], answer["subject"], answer["value"]]
        if contract is not None:
            arguments += ["--contract-draft", contract]
        return self._run(arguments, cancel, self._timeout)

    def register(self, root: str, cancel=None, *, integration_branch: str | None = None,
                 plan_id: str | None = None) -> dict:
        arguments = ["verify", "--repo-root", root, "--register"]
        if integration_branch is not None:
            arguments += ["--integration-branch", integration_branch]
        if plan_id is not None:
            arguments += ["--plan-id", plan_id]
        return self._run(arguments, cancel, self._timeout)

    def apply(self, plan_id: str, cancel=None, acknowledge_deletions: bool = False,
              discard_retained: bool = False) -> dict:
        arguments = ["apply", "--plan-id", plan_id]
        if acknowledge_deletions:
            arguments.append("--acknowledge-deletions")
        if discard_retained:
            arguments.append("--discard-retained")
        return self._run(arguments, cancel, self._apply_timeout)

    def discard(self, plan_id: str, cancel=None) -> dict:
        return self._run(["discard", "--plan-id", plan_id], cancel, self._timeout)

    def _run(self, arguments: list[str], cancel, timeout: float) -> dict:
        env = dict(self._environ) if self._environ is not None else None
        try:
            done = manager.run_in_own_group(
                [*self._command, *arguments], timeout=timeout, cancel=cancel,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=env, start_new_session=True)
        except subprocess.TimeoutExpired as error:
            raise RunFailed("timed_out") from error
        except (FileNotFoundError, PermissionError) as error:
            raise RunFailed("not_installed") from error
        except OSError as error:
            raise RunFailed("unavailable") from error
        if cancel is not None and cancel.is_set():
            raise RunFailed("cancelled")
        if done.returncode not in (0, 2):
            raise RunFailed("failed")
        try:
            value = json.loads(done.stdout)
        except ValueError as error:
            raise RunFailed("unreadable") from error
        if not isinstance(value, dict):
            raise RunFailed("unreadable")
        return value


def adopter_for(platform: str) -> Adopter | None:
    return Adopter() if manager.supported(platform) else None
