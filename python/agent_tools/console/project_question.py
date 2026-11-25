"""The launch and runner of a read-only project question session (#1176, ADR-console-058).

Why. The console answers an owner's question about a registered project with one Claude Code
client run in that project's folder, under the account the console chose. The session only reads.
This module builds that session (routes, prompt, settings, argv) and runs it to one `Outcome`; the
service (Task 3 of the plan) owns admission, the event log and the thread. Linux and macOS: the
session is a child of the console, started by `manager.run_in_own_group` under
`manager.client_environment`, both reused and never copied. The manager's own model is not
compared or changed (D1): the session names `--model sonnet` and nothing else changes.

Routes. `read_only_routes(snapshot)` takes the resolved project contract (`resolve_project.resolve`)
and returns one `Route(id, argv, cwd)` per id of `production.read_only.commands`, in order, only
when `production.status` is `declared`. An id is skipped when it has no binding, its argv is not a
non-empty list of strings, a word is not a `project_question_hook.PLAIN_WORD`, or its `cwd` is not
the project's root. The root it compares with is the snapshot's own `project.root`, never the path
the caller passed: the resolver canonicalises the root and builds every cwd from that canonical
root, while a registry root may hold a symlink, so comparing with the caller's path would drop every
route of such a project and wrongly answer with the production line (D9). When the root holds a
`devenv.nix` that is a regular file (an inference from the root, not a contract field), each kept
route's argv is `devenv shell -- <declared argv>` unless it already starts with `devenv`, so the
read runs in the project's environment; its `id` and `cwd` do not change, and the skip rules above
run on the declared argv first (D7). `repo_slug(snapshot)` is `bindings.tracker.repo_slug` only for a
`github` tracker whose slug fullmatches `project_question_hook.REPO_SLUG`, else None, and never raises.
`credential_unset(snapshot)` is `bindings.tracker.credential_env.unset_before_invocation` (the
non-empty strings of it, else ()). `session_environment(ask, environ)` is `manager.client_environment`
minus the `GIT_REPOSITORY_ENV` variables (an inherited `GIT_DIR` would point the admitted git reads at
another repository) and minus the names in `ask.unset` (a stale `GH_TOKEN` would override the working
`gh` credential); the run uses it, and the hook rejects `env` and `unset` so the session cannot repair it.
`reach_of(root)` is `Reach(read_only_routes(s), repo_slug(s), credential_unset(s))` with `s = resolve(root)` and lets every
exception, a `ContractError` included, propagate: an empty `routes` means only "resolved, no
runnable read-only command" (bootstrap: never guess a value the resolver declined). `resolve` is a
test seam only.

Prompt. `LEAD` (the owner's framing, the `ANSWER_RULES` and the heading shape: a direct answer in two
or three sentences in plain business terms, what is live first, no decision-record jargon, history
and tracker before decision records, every item in a question's time window counted from the dates
read with list limits raised until the window is covered and the count's source named, a failed
command named in the answer), then a routes paragraph
(the declared commands, each exactly as written and alone; or that none is declared so production
cannot be read), then the reads paragraph (the git reads with their examples, and either the gh
reads pinned to `--repo <repo>` with their examples or the sentence that gh cannot be used), then the
thread text, then `QUESTION_MARK` and the question (ADR-console-065).

Records (ADR-console-089). An `Ask` may carry `records`, the encoded document of the console's own
records for the project (None: none). The session's file is `records_path(ask)`: `SETTINGS_DIR`'s
directory (0700), the question's id plus `RECORDS_SUFFIX`, mode 0600, written atomically after the
settings file with exactly `ask.records`. The settings file is removed on every path once the run ends;
the records file is removed then too unless the outcome is `ANSWERED`, when it is kept so the verify check
can read its spend section (`question_check`, ADR-console-089), and a write of any records file first removes
the kept files older than `RECORDS_KEPT_SECONDS` (90 days, the question's own retention). `prompt` puts `RECORDS_TEXT` with that path after the reads paragraph and before the
thread text, only with records. With records it also gives each part of `question_records.SECTIONS`
that the document holds as `<name> offset <n> limit <m>` (`SECTIONS_TEXT`, from `section_lines`), so
the session reads one part alone, and it asks the session to cite the file with the parts it read in
parentheses right after the file name, as `<path> (spend)`; a cost question is answered with figures
from the spend part, and spend is null only when the console could not read its spend (ADR-console-089).
No permission rule is added: Read is already admitted. A write that
fails is a failed outcome (`RECORDS_UNWRITABLE`) and no session starts.

Deeper mode (#1274, ADR-console-101). An `Ask` with `deep` true (`new_ask(..., deep=True)`; the page's
Dig deeper, `parse_ask`'s optional boolean `deep`) is a deeper look at an answered question. It runs
`DEEP_MODEL` (`opus`, `model_of`) with `DEEP_TIMEOUT_SECONDS` (1200, `timeout_of`; a timed-out run's
reason names that figure) instead of `MODEL` and `TIMEOUT_SECONDS`. With records, its prompt lists the
`transcripts` part of `question_records.DEEP_SECTIONS` beside the others and adds `DEEP_TEXT` after the
records text and before the thread: analyse before answering, answer where time or tokens go from the
`transcripts` part (counts, times and token sums by script, phase and issue; no transcript itself is
readable), quote each figure exactly and cite it as `<path> (transcripts)`. A light ask's argv, prompt and
settings are byte-identical to before. A deeper ask without records is refused: `new_ask(..., deep=True)`
raises `ValueError(DEEP_NEEDS_RECORDS)` and `run_question` of such an `Ask` is a failed outcome with that
reason before any file is written or session started, because only records give the hook its confinement.
A deeper session's settings differ from a light one's only by the
hook's fifth argument, the ask's checkout root: the permission rules are the same, and the hook confines
Read, Grep, Glob and the admitted commands to the root and the records file (`OUTSIDE_ROOT`,
`project_question_hook`); a symlink the checkout itself holds is part of its declared content, a stated
limit (ADR-console-101 D1).
`checked_question` strips and refuses an empty question or one over `MAX_QUESTION_CHARS`;
`parse_request` reads the page's strict JSON body of exactly `project_id` and `question`
(`parse_keyed_request` also reads an optional `request_key`, ADR-console-089).
A credential-shaped text (#1272) is refused first, with `CREDENTIAL`, before it is stored or sent:
`credential_shaped(text)` is true when any pattern of `CREDENTIAL_SHAPES` (known token prefixes,
key blocks, a `Bearer` value, a JWT, a `token`/`secret`/`password`-style assignment in any case,
quoted or not, with a real value, the console's own page token, and a long base64 run that is not
an SRI hash or a path, a path being slash-separated parts that are each a word holding three lowercase letters in a row,
a label of up to four characters, or a short CamelCase or acronym name such as `README`, `HTTP2` or `Vec3D`)
searches it, in time linear in its length (the three shapes a regex would backtrack on, `jwt`, `assignment` and
`base64_run`, are code that reads each run of characters once). The refusal text never holds any of the question's text.
Limits (#1272): the shapes judge text as a paste gives it. A credential split by spaces or invisible
characters, encoded (URL encoding, hex, or base64 of a token), a password shorter than eight characters
or written with no `token`, `secret`, `password`-style name before it, or a console token with fewer
than two capital or two small letters (about one generated token in 10^8) is not caught.

Settings and fail closed (D7). `settings_document(routes)` is the one `--settings` file. Several
layers each refuse on their own: `--setting-sources ""` loads no user, project or local settings,
so the account's `auto` mode and its allows never apply; `dontAsk` denies every call that is not
pre-approved; the allow list is `READ_RULES`, one `Bash(<argv>)` per route, the `GIT_READ_RULES` and,
when the project has a GitHub repository, the `GH_READ_RULES`; the deny list is `DENIED_RULES`,
which wins over any allow; `--tools` removes every other built-in tool, and Bash is always a tool
(the git reads need it even with no route). On top of those, a PreToolUse command hook
(`project_question_hook`, run through `siblings.sibling_argv`, given the allowed argv and the
repository, and with records also `private_dir(ask)`, the console's state directory, and
`records_path(ask)`, which confine its reads to that one file: ADR-console-089) admits only reads, the bare declared commands and the plain git and gh reads;
`"onFailure": "block"` makes the pinned client treat a hook that errors, fails
to start or times out as a block, because without it such a hook is non-blocking and the call would
fall to the permission rules. The file lives in `SETTINGS_DIR` under the console's state (a 0700
directory, the file 0600, written atomically) and is removed when the run ends.

Argv. `launch_command` is None on a host `manager.supported` refuses, else `claude-account run -p --model sonnet
--session-id <id> --permission-mode dontAsk --setting-sources "" --strict-mcp-config --tools <tools>
--output-format json --settings <file> <prompt>`. `--tools` is variadic: it is always followed by
another option, so the prompt, which is last, is never swallowed into the tool list. The session id
is a fresh UUID per question, which the service records in the asked row so the Spend page can tell
the question's transcript (ADR-console-059). No `systemd-run` scope is used. A deeper ask names
`--model opus`.

Runner. `run_question` never raises for these cases and removes the settings file once written, in
this order: no launch command (`UNAVAILABLE_TEXT`); a root that is not a directory; a settings
write that fails; a records write that fails (`RECORDS_UNWRITABLE`, only with records, after the
settings write); the run itself with `timeout_of(ask)` (`TIMEOUT_SECONDS`, or `DEEP_TIMEOUT_SECONDS` for a deeper ask), the `cancel` event, `stdin` closed and
stderr to a temporary file; `TimeoutExpired` (`TIMED_OUT`); a missing `claude-account`; a set
`cancel` (`STOPPED_TEXT`); a non-zero exit (the last non-empty stderr line); then the JSON on
stdout: not an object with a string `result` (`UNREADABLE_TEXT`), `is_error` true (the result text),
else `ANSWERED` with `answer_text`, which adds `NO_PRODUCTION_LINE` when no route is declared (D5).
`asker_for(platform)` is `run_question` on Linux and macOS (what `manager.supported` admits), else None
(ADR-console-058: a project question runs wherever a manager does).

Fold and answer shape (#1177). `asked_questions(events, known)` folds the two row kinds into each
project's questions, a tuple of `AskedQuestion` in ascending `seq`. An asked row counts only with
a string project column, a non-empty string `question_id` not already folded for that project and
a string `question`; an answered row applies only to a still-working question of the same id in
the same project (the first answer wins, strays are ignored): outcome `answered` with a string
`answer` is `ANSWERED`, `answered` without one is `FAILED` with `UNREADABLE_TEXT`, `timed_out` is
`TIMED_OUT`, anything else is `FAILED`; `reason` is kept only when a string and `answered_at` is
the answered row's `at`. An asked row's `deep` is kept only when it is `True` and its `session_id` only
when a non-empty string (#1274). Folding two batches through `known` equals folding once, and `known` is
never mutated. `answer_parts(text)` splits a stored answer by the `HEADINGS` of the shape `LEAD`
asks for: a heading matches at line start after optional spaces, case-insensitively, followed by
`:`, and is not recognised inside fenced code (a line whose left-trimmed text starts with three
backticks toggles the fence and stays in the current part, and so does a heading's text after its colon; an unclosed fence runs to the end, so
every later line stays in the part the fence opened in); the lines after a heading up to the next one belong to it (joined with a newline, stripped);
text before the first heading starts the answer part, and a text with no heading is wholly the
answer; an empty part is None, and so is a part other than the answer that is `none` (any case, a
trailing `.` ignored): an answer of `None.` is an answer and keeps its text; a text
ending with `NO_PRODUCTION_LINE` carries that line as `production` and in no other part.
A back part with question text and two to `MAX_CHOICES` (5) list lines (`-`, `*`, `+`, or one or
two digits then `.` or `)`, then a space) is split: `back` is the question text alone and `choices`
the list lines' texts in order. One list line, more than `MAX_CHOICES`, or no question text leaves
`back` the whole part and `choices` empty (`()`). The prompt (`ANSWER_RULES`, `LEAD`) names the
formatting subset (bold, `- ` list lines, inline code, fenced code; no headings, tables, links or
HTML) and asks for a choice as two to five answers on their own `- ` lines.

Threads (#1178, ADR-console-062). A `Turn` is one earlier question with the answer the session
gave. An `Ask` carries a `thread` of turns, oldest first, and a thread changes only the prompt:
`thread_text(thread)` is `""` for none, else `THREAD_LEAD` and each turn as `EARLIER_QUESTION`,
`EARLIER_ANSWER`; `prompt` puts it between the routes paragraph and `QUESTION_MARK`, so with no
thread the prompt and the argv are byte-identical to before, and the settings never see it. The
fold gives each `AskedQuestion` a `thread_id`: an asked row whose `thread_id` is a non-empty string
naming a question already folded for the same project takes that question's `thread_id`, else the
question's own id starts a thread (folding in two batches equals folding once). `threads(questions)`
groups by `thread_id`, each thread ascending by `seq`, threads ordered by their last question,
newest first. `follow_up(questions, thread_id, question)` returns the thread's `Turn`s in order
after refusing, in this order, a `thread_id` that is not a thread's id (`THREAD_UNKNOWN`; a
follow-up's own id is not one), a thread whose last question is not answered (`THREAD_UNANSWERED`)
and a thread whose `thread_text` plus the question exceeds `MAX_THREAD_BYTES` UTF-8 bytes
(`THREAD_TOO_LONG`): the prompt is one argv string and Linux refuses one past 131072 bytes.
Between the last two, a thread any of whose questions or answers is credential-shaped is refused
(`THREAD_CREDENTIAL`, #1272): the turns are the text the next session's prompt would carry.
A `PROJECT_QUESTION_DELETED` row removes from its project's folded questions each question whose
id is a string member of its `question_ids` list (a row with a non-string project or a
`question_ids` that is not a list removes nothing, the rule the delete trigger enforces,
#1272). `thread_question_ids(questions, thread_id)` returns the ids of the thread whose id is
`thread_id`, ascending by `seq`, or refuses with `THREAD_UNKNOWN`; the service refuses a delete
of a thread with a working question with `THREAD_WORKING`. `parse_delete_request` reads exactly
`project_id` and `thread_id`, both non-empty strings, and returns them as a pair.
`parse_keyed_request` reads exactly `project_id` and `question`, plus optionally a non-empty
string `thread_id` and optionally a `request_key` (a string that fullmatches `REQUEST_KEY`, 32
lowercase hex digits; any other is a `ValueError`), and returns
`(project_id, question, thread_id or None, request_key or None)`; `parse_request` returns its
first three; `parse_ask` also reads an optional `deep`, a JSON boolean (`ValueError("deep must be true or false")`
otherwise), and returns `parse_keyed_request`'s four with it, and `parse_keyed_request` is its first four.
`deep_follow_up(questions, thread_id, question)` is `follow_up` (its refusals first), then `DEEP_STALE`
unless the thread's last question is not deep and has this very text: a Dig deeper is honoured only
against the thread's current last light answer. The key names one request: an asked row carries `request_key` only when one was
given, the fold keeps it only when it is a string fullmatching `REQUEST_KEY`, and the service asks
a key once per project (ADR-console-089).
"""

from __future__ import annotations

import json
import os
import secrets
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.console import manager, question_records
from agent_tools.console.event_log import (
    PROJECT_QUESTION_ANSWERED, PROJECT_QUESTION_ASKED, PROJECT_QUESTION_DELETED,
    PROJECT_QUESTION_KEYED, Event)
from agent_tools.console.project_question_hook import (
    GH_READ_GROUPS, GH_READ_VERBS, GIT_READS, PLAIN_WORD, REPO_SLUG)
from agent_tools.project_contract import resolve_project
from agent_tools.system import siblings

MODEL = "sonnet"
DEEP_MODEL = "opus"
PERMISSION_MODE = "dontAsk"
TIMEOUT_SECONDS = 300
DEEP_TIMEOUT_SECONDS = 1200
MAX_QUESTION_CHARS = 2000
SETTINGS_DIR = "project-question-settings"
SETTINGS_SUFFIX = ".settings.json"
RECORDS_SUFFIX = ".records.json"
RECORDS_KEPT_SECONDS = 90 * 24 * 3600
HOOK_MODULE = "console.project_question_hook"
GIT_REPOSITORY_ENV = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_PREFIX")
HOOK_TIMEOUT = 10
QUESTION_MARK = "The question: "
REQUEST_KEY = re.compile(r"[0-9a-f]{32}")
EARLIER_QUESTION = "Earlier question: "
EARLIER_ANSWER = "Earlier answer: "
MAX_THREAD_BYTES = 98304
ANSWERED = "answered"
FAILED = "failed"
TIMED_OUT = "timed_out"
WORKING = "working"

READ_RULES = ("Read", "Grep", "Glob")
GIT_READ_RULES = tuple(f"Bash(git {verb}:*)" for verb in GIT_READS)
GH_READ_RULES = tuple(
    f"Bash(gh {group} {verb}:*)" for group in GH_READ_GROUPS for verb in GH_READ_VERBS)
DENIED_RULES = (
    "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Agent",
    "Bash(git push:*)", "Bash(gh pr create:*)", "Bash(gh pr merge:*)",
    "Bash(git branch -d:*)", "Bash(gh release create:*)",
)

NO_PRODUCTION_LINE = (
    "Production cannot be read for this project: its contract declares no read-only command that "
    "runs from its root."
)
RECORDS_UNWRITABLE = "cannot write the question's records: {detail}"
SECTIONS_TEXT = (
    "To read one part alone, give Read this file with that part's offset and limit: {parts}. "
    "Read a part longer than one read in steps from its offset. ")
RECORDS_TEXT = (
    "The console's own records for this project are in the file {path}: its spend over the last "
    "30 days by day, delivery run, issue, phase and sprint, in tokens and estimated dollars; its "
    "sprints; its delivery runs with each issue's stage; this host's activation runs of it with "
    "how each ended and why; and its held checks. Read it with Read, or Grep it for an issue "
    "number, a run id or a commit, whenever the question is about cost, time, effort, what was "
    "delivered or is live, sprints, checks, or why a delivery or production run failed, and name "
    "it under Read with the parts you read, in parentheses right after the file name, for "
    "example {path} (spend). Answer a cost question with figures from the spend part, in tokens "
    "or dollars, and quote each figure exactly as the records print it: a token count as its "
    "whole number (commas between thousands are fine) and a dollar amount as $ with two "
    "decimals, never rounded, converted or reworded. {sections}The console wrote it for this project when this question started; "
    "its spend is null only when the console could not read its spend. The console's other "
    "files are not readable from this session.\n\n")
DEEP_TEXT = (
    "This question asks for a deeper look, so analyse before you answer. The records file also "
    "holds a transcripts part: counts, times and token sums of this project's delivery runs over "
    "the last 30 days, by script, phase and issue, aggregated by the console from the runs' "
    "transcripts; no transcript itself is readable. Answer where time or tokens go from that "
    "part, quote each figure exactly as it is printed, and name it under Read as {path} "
    "(transcripts).\n\n")
RECORDS_FAILED = "the console's records could not be gathered: {detail}"
CHECKOUT_MOVED = "the project no longer holds the checkout the question was asked in"
DEEP_NEEDS_RECORDS = "a deeper question needs the console's records: it carries the checkout confinement"
CONTRACT_UNREADABLE = "the project's contract could not be resolved, so no session was started: {detail}"
UNAVAILABLE_TEXT = "questions are not available on this host yet"
UNREGISTERED = "this project is not registered"
EMPTY = "write the question first"
TOO_LONG = "a question is at most 2000 characters"
NO_PROFILE = "no account can take a question now"
STOPPED_TEXT = "the console stopped before the session answered"
UNREADABLE_TEXT = "the session's answer could not be read"
STOPPING = "the console is stopping"
PROFILE_GONE = "the account {profile} was removed before the session started"

ANSWER_RULES = (
    "Lead with the direct answer in two or three sentences, in the owner's plain business terms, "
    "then at most a short list of five lines. "
    "When the question asks what is live or in production, say what is live first. "
    "Use no decision-record jargon: no ADR numbers, decision ids or internal terms unless the "
    "owner asks for them. "
    "Answer from the project's history, its pull requests and releases and its declared "
    "production read, not from its decision records alone. "
    "If a command you run fails, say plainly in the answer which command failed and what it "
    "printed. "
    "When the question covers a time window, count every release, pull request or deploy dated "
    "inside it from the dates you read: raise the list limit (for example --limit) until a list "
    "returns fewer items than the limit, so you have read every item, never stop at a first page "
    "or an arbitrary limit and never stop at the first item older than the window, because gh "
    "lists by creation date and a release published or a pull request merged inside the window "
    "can have been created before it; when a list is too long to read whole, filter it by the "
    "date that counts (for example --search merged:2026-01-01..2026-01-31), and say in the answer where "
    "the count comes from. "
    "Format only with **bold**, list lines starting with \"- \", `inline code` and fenced code "
    "blocks; use no headings, tables, links or HTML. "
)

LEAD = (
    "You answer one question about this project for its owner, started by the console. You only "
    "read: a step you are refused stays refused. A step that would cost money or needs a "
    "credential you lack is never attempted: put it in your answer as a question for the owner. "
    + ANSWER_RULES +
    "Reply in exactly this shape, one heading per line:\n"
    "Answer: <the answer in plain words>\n"
    "Read: <the files you read, or none>\n"
    "Ran: <the commands you ran, or none>\n"
    "Could not find out: <what you could not find out, or none>\n"
    "Question for you: <a step that needs money or a credential, or a choice only the owner can "
    "make, then its two to five answers, each on its own line starting with \"- \", or none>\n\n"
)

THREAD_LEAD = (
    "This question follows up earlier questions of the same thread, oldest first, each with the "
    "answer you gave. Use them as context: the rules above still apply.\n\n"
)
DEEP_STALE = "This answer was already dug deeper, or its thread moved on: reload to see it."
THREAD_UNKNOWN = "this thread is not one of the project's questions"
THREAD_WORKING = "this thread is still being answered: delete it once the answer is in"
THREAD_UNANSWERED = "a follow-up continues a thread whose last question was answered"
THREAD_TOO_LONG = "this thread is too long to continue: ask a new question"
CREDENTIAL = "this looks like a password, token or key, so it was not kept or sent: take it out and ask again"
THREAD_CREDENTIAL = (
    "this thread holds a password, token or key, so it was not continued: delete the thread and ask again")

class _Searchable(Protocol):
    def search(self, text: str, /) -> object: ...


class _LinearShape:
    """A shape judged by code in time linear in the text, where one regex would backtrack.

    `search` answers like `re.Pattern.search`: something truthy when the text holds the shape."""

    def __init__(self, search: Callable[[str], bool]) -> None:
        self.search = search


_JWT_HEAD = re.compile(r"\beyJ[A-Za-z0-9_-]*", re.ASCII)
_JWT_TAIL = re.compile(r"\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", re.ASCII)


def _jwt_search(text: str) -> bool:
    # Every `eyJ` head in one run of token characters ends at the same place, so the first one,
    # which has the most characters, decides for the run: each run is read once as a head.
    return any(
        head.end() - head.start() >= 11 and _JWT_TAIL.match(text, head.end())
        for head in _JWT_HEAD.finditer(text))


_ASSIGNMENT_NAME = re.compile(
    r"(?i:TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|ACCESS[_-]?KEY)(?=[\"']?\s*=|[\"']\s*:|\s*:)", re.ASCII)
_ASSIGNMENT_VALUES = (
    ("quoted", re.compile(r"[\"']?\s*=\s*[\"']", re.ASCII)),
    ("bare", re.compile(r"[\"']?\s*=\s*", re.ASCII)),
    ("json", re.compile(r"[\"']\s*:\s*[\"']?", re.ASCII)),
    ("colon", re.compile(r"\s*:\s*[\"']?", re.ASCII)),
)
_VALUE_RUN = re.compile(r"[^\s\"']*", re.ASCII)
_LAST_OF = {
    kind: re.compile(r"(?s:.*)(" + shape + ")", re.ASCII)
    for kind, shape in (
        ("letter", "[A-Za-z]"), ("digit", "[0-9]"), ("digit_or_hyphen", "[0-9-]"),
        ("bracket", r"[(\[]"), ("dot_word", r"\.[A-Za-z_]"))}


class _ValueRun:
    """The run of non-space, non-quote characters from `start`, with where each class last occurs.

    A value that begins later in the same run sees the same characters from its own start on, so
    the run is read once for all the names that sit in it."""

    def __init__(self, text: str, start: int) -> None:
        self.start = start
        self.end = _VALUE_RUN.match(text, start).end()
        run = text[start:self.end]
        self.last = {}
        for kind, pattern in _LAST_OF.items():
            found = pattern.match(run)
            self.last[kind] = start + found.start(1) if found else -1


def _assignment_search(text: str) -> bool:
    run = None
    for name in _ASSIGNMENT_NAME.finditer(text):
        for kind, opening in _ASSIGNMENT_VALUES:
            opened = opening.match(text, name.end())
            if opened is None:
                continue
            value = opened.end()
            if value >= len(text) or text[value] in "$<{":
                continue
            if run is None or not run.start <= value < run.end:
                run = _ValueRun(text, value)
            if run.end - value < 8:
                continue
            last = run.last
            if last["letter"] < value:
                continue
            if kind in ("quoted", "json"):
                return True
            if kind == "colon":
                if last["digit"] >= value:
                    return True
            elif (last["digit_or_hyphen"] >= value and last["bracket"] < value
                  and not (last["dot_word"] >= value and last["digit"] < value)):
                return True
    return False


_BASE64_RUN = re.compile(
    r"(?<![A-Za-z0-9+/=])(?<!sha1-)(?<!sha256-)(?<!sha384-)(?<!sha512-)"
    r"([A-Za-z0-9+/]{32,})(={0,2})(?![A-Za-z0-9+/=])", re.ASCII)
_TWO_UPPER = re.compile(r"[^A-Z]*[A-Z][^A-Z]*[A-Z]", re.ASCII)
_TWO_LOWER = re.compile(r"[^a-z]*[a-z][^a-z]*[a-z]", re.ASCII)
_TWO_DIGITS = re.compile(r"[^0-9]*[0-9][^0-9]*[0-9]", re.ASCII)
_THREE_LOWER = re.compile(r"[a-z]{3}", re.ASCII)
_SHORT_CAMEL = re.compile(r"(?:[A-Z][a-z]{0,2}|[0-9][a-z]?)+", re.ASCII)


def _path_part(part: str) -> bool:
    return (len(part) <= 4 or _THREE_LOWER.search(part) is not None
            or (len(part) <= 10 and _SHORT_CAMEL.fullmatch(part) is not None))


def _base64_run_search(text: str) -> bool:
    for found in _BASE64_RUN.finditer(text):
        run = found.group(1)
        if not (_TWO_UPPER.match(run) and _TWO_LOWER.match(run) and _TWO_DIGITS.match(run)):
            continue
        parts = run.split("/")
        # A path is parts separated by slashes that are each a word, a short label or a short CamelCase
        # name, with no padding after it; the last part is not one when padding follows the run.
        if found.group(2) or len(parts) < 2 or not all(_path_part(part) for part in parts):
            return True
    return False


CREDENTIAL_SHAPES: tuple[tuple[str, _Searchable], ...] = (
    ("github", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}", re.ASCII)),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}", re.ASCII)),
    ("hugging_face", re.compile(r"\bhf_[A-Za-z0-9]{30,}", re.ASCII)),
    ("sk_key", re.compile(r"\bsk-[A-Za-z0-9_-]{32,}", re.ASCII)),
    ("age_secret_key", re.compile(r"AGE-SECRET-KEY-1[0-9A-Z]{50,}", re.ASCII)),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.ASCII)),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}", re.ASCII)),
    ("aws_key_id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", re.ASCII)),
    ("slack", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}", re.ASCII)),
    ("gitlab", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}", re.ASCII)),
    ("jwt", _LinearShape(_jwt_search)),
    ("assignment", _LinearShape(_assignment_search)),
    ("console_token", re.compile(
        r"(?<![A-Za-z0-9_-])(?=(?:[A-Za-z0-9_-]*?[A-Z]){2})(?=(?:[A-Za-z0-9_-]*?[a-z]){2})"
        r"[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])", re.ASCII)),
    ("base64_run", _LinearShape(_base64_run_search)),
)


def credential_shaped(text: str) -> bool:
    """True when `text` looks like a password, token or key (#1272); the text is never repeated."""
    return any(pattern.search(text) for _, pattern in CREDENTIAL_SHAPES)

HEADINGS: tuple[tuple[str, str], ...] = (
    ("answer", "Answer"), ("read", "Read"), ("ran", "Ran"),
    ("unknown", "Could not find out"), ("back", "Question for you"),
)
_HEADING = re.compile(
    r"^\s*(" + "|".join(re.escape(label) for _, label in HEADINGS) + r")\s*:\s?(.*)$",
    re.IGNORECASE | re.ASCII)
_KEY_OF = {label.lower(): key for key, label in HEADINGS}
MAX_CHOICES = 5
_LIST_LINE = re.compile(r"^\s*(?:[-*+]|\d{1,2}[.)])\s+(\S.*)$", re.ASCII)


class Refused(Exception):
    """A question the console will not start; `str` is the one-line reason."""


@dataclass(frozen=True)
class Route:
    id: str
    argv: tuple[str, ...]
    cwd: str


@dataclass(frozen=True)
class Reach:
    routes: tuple[Route, ...]
    repo: str | None
    unset: tuple[str, ...] = ()


@dataclass(frozen=True)
class Turn:
    question: str
    answer: str


@dataclass(frozen=True)
class Ask:
    question_id: str
    project_id: str
    root: str
    question: str
    profile: str
    routes: tuple[Route, ...]
    settings: Path
    session_id: str
    thread: tuple[Turn, ...] = ()
    repo: str | None = None
    unset: tuple[str, ...] = ()
    records: str | None = None
    deep: bool = False


@dataclass(frozen=True)
class Outcome:
    outcome: str
    answer: str | None = None
    reason: str | None = None


def _plain_argv(argv: object) -> bool:
    return (
        isinstance(argv, list) and bool(argv)
        and all(isinstance(word, str) and PLAIN_WORD.fullmatch(word) for word in argv)
    )


def read_only_routes(snapshot: Mapping) -> tuple[Route, ...]:
    production = snapshot["production"]
    if production["status"] != "declared":
        return ()
    root = os.path.normpath(snapshot["project"]["root"])
    in_devenv = os.path.isfile(os.path.join(root, "devenv.nix"))
    bindings = snapshot["bindings"]["commands"]
    routes = []
    for id in production["read_only"]["commands"]:
        binding = bindings.get(id)
        if binding is None or not _plain_argv(binding.get("argv")):
            continue
        cwd = binding["cwd"]
        if not isinstance(cwd, str) or os.path.normpath(cwd) != root:
            continue
        argv = tuple(binding["argv"])
        if in_devenv and argv[0] != "devenv":
            argv = ("devenv", "shell", "--", *argv)
        routes.append(Route(id, argv, cwd))
    return tuple(routes)


def repo_slug(snapshot: Mapping) -> str | None:
    bindings = snapshot.get("bindings")
    tracker = bindings.get("tracker") if isinstance(bindings, Mapping) else None
    if not isinstance(tracker, Mapping) or tracker.get("kind") != "github":
        return None
    slug = tracker.get("repo_slug")
    return slug if isinstance(slug, str) and REPO_SLUG.fullmatch(slug) else None


def credential_unset(snapshot: Mapping) -> tuple[str, ...]:
    """`bindings.tracker.credential_env.unset_before_invocation`; () when absent or not strings."""
    bindings = snapshot.get("bindings")
    tracker = bindings.get("tracker") if isinstance(bindings, Mapping) else None
    policy = tracker.get("credential_env") if isinstance(tracker, Mapping) else None
    names = policy.get("unset_before_invocation") if isinstance(policy, Mapping) else None
    if not isinstance(names, list):
        return ()
    return tuple(name for name in names if isinstance(name, str) and name)


def reach_of(root: str, *,
             resolve: Callable[[str], Mapping] = resolve_project.resolve) -> Reach:
    snapshot = resolve(root)
    return Reach(read_only_routes(snapshot), repo_slug(snapshot), credential_unset(snapshot))


def new_question_id() -> str:
    return secrets.token_hex(8)


def new_session_id() -> str:
    return str(uuid.uuid4())


def new_ask(question_id: str, project_id: str, root: str, question: str, profile: str,
            routes: Sequence[Route], settings_dir: Path, *, session_id: str,
            thread: Sequence[Turn] = (), repo: str | None = None,
            unset: Sequence[str] = (), records: str | None = None, deep: bool = False) -> Ask:
    if deep and records is None:
        raise ValueError(DEEP_NEEDS_RECORDS)
    return Ask(question_id, project_id, root, question, profile, tuple(routes),
               Path(settings_dir) / (question_id + SETTINGS_SUFFIX), session_id, tuple(thread), repo,
               tuple(unset), records, deep)


def model_of(ask: Ask) -> str:
    return DEEP_MODEL if ask.deep else MODEL


def timeout_of(ask: Ask) -> int:
    return DEEP_TIMEOUT_SECONDS if ask.deep else TIMEOUT_SECONDS


def records_path(ask: Ask) -> Path:
    return ask.settings.with_name(ask.question_id + RECORDS_SUFFIX)


def private_dir(ask: Ask) -> Path:
    """The console's state directory: it holds the settings directory, the event log and the page token."""
    return ask.settings.parent.parent


def checked_question(text: str) -> str:
    text = text.strip()
    if not text:
        raise Refused(EMPTY)
    if len(text) > MAX_QUESTION_CHARS:
        raise Refused(TOO_LONG)
    return text


def _decode_body(body: bytes) -> object:
    try:
        return json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                          parse_constant=reject_nonfinite_literal)
    except RecursionError as error:
        raise ValueError("the body is nested too deeply") from error


def parse_ask(body: bytes) -> tuple[str, str, str | None, str | None, bool]:
    value = _decode_body(body)
    required = {"project_id", "question"}
    if not isinstance(value, dict) or not required <= set(value) <= required | {
            "thread_id", "request_key", "deep"}:
        raise ValueError(
            "the body must be an object of project_id, question, an optional thread_id, an "
            "optional request_key and an optional deep")
    project_id, question = value["project_id"], value["question"]
    thread_id = value.get("thread_id")
    if "thread_id" in value and (not isinstance(thread_id, str) or not thread_id):
        raise ValueError("thread_id must be a non-empty string")
    request_key = value.get("request_key")
    if "request_key" in value and not (
            isinstance(request_key, str) and REQUEST_KEY.fullmatch(request_key)):
        raise ValueError("request_key must be 32 lowercase hex digits")
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("project_id must be a non-empty string")
    if not isinstance(question, str):
        raise ValueError("question must be a string")
    deep = value.get("deep", False)
    if not isinstance(deep, bool):
        raise ValueError("deep must be true or false")
    return project_id, question, thread_id, request_key, deep


def parse_keyed_request(body: bytes) -> tuple[str, str, str | None, str | None]:
    return parse_ask(body)[:4]


def parse_request(body: bytes) -> tuple[str, str, str | None]:
    return parse_keyed_request(body)[:3]


def parse_delete_request(body: bytes) -> tuple[str, str]:
    value = _decode_body(body)
    if not isinstance(value, dict) or set(value) != {"project_id", "thread_id"}:
        raise ValueError("the body must be an object of project_id and thread_id")
    project_id, thread_id = value["project_id"], value["thread_id"]
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("project_id must be a non-empty string")
    if not isinstance(thread_id, str) or not thread_id:
        raise ValueError("thread_id must be a non-empty string")
    return project_id, thread_id


def thread_text(thread: Sequence[Turn]) -> str:
    if not thread:
        return ""
    return THREAD_LEAD + "".join(
        EARLIER_QUESTION + turn.question + "\n" + EARLIER_ANSWER + turn.answer + "\n\n"
        for turn in thread)


def reads_paragraph(repo: str | None) -> str:
    text = ("You may also run these reads, each alone, in plain words with no quotes: git log, "
            "git show, git diff, git status, git blame, git ls-files and git tag -l. For recent "
            "work: git log --since=7.days.ago --oneline. Name revisions by sha, tag or --since, "
            "since ~ and ^ are refused. ")
    if repo:
        return text + (
            "For this project's GitHub repository: gh pr list, gh pr view, gh release list, "
            "gh release view, gh issue list, gh issue view, gh run list and gh run view, each "
            f"with --repo {repo} right after list or view, before any other word, and no --; a "
            "view may instead name its one tag or number just before --repo, never both. "
            f"For merged work: gh pr list --repo {repo} --state merged --limit 30. "
            f"For what was released: gh release list --repo {repo} --limit 100. "
            f"To read one release: gh release view v1.2.0 --repo {repo}.\n\n")
    return text + "gh cannot be used: this project's contract names no GitHub repository.\n\n"


def prompt(question: str, routes: Sequence[Route], thread: Sequence[Turn] = (), *,
           repo: str | None = None, records: str | None = None,
           sections: Mapping[str, tuple[int, int]] | None = None, deep: bool = False) -> str:
    if routes:
        paragraph = ("Commands you may run, each exactly as written and alone: "
                     + ", ".join(shlex.join(route.argv) for route in routes) + ".\n\n")
    else:
        paragraph = ("This project declares no read-only command, so production cannot be read: "
                     "answer from the code, the docs and the reads below.\n\n")
    parts = "; ".join(f"{name} offset {sections[name][0]} limit {sections[name][1]}"
                      for name in (question_records.DEEP_SECTIONS if deep and records is not None
                                   else question_records.SECTIONS) if name in (sections or {}))
    held = (RECORDS_TEXT.format(path=records, sections=SECTIONS_TEXT.format(parts=parts) if parts else "")
            if records is not None else "")
    if deep and records is not None:
        held += DEEP_TEXT.format(path=records)
    return (LEAD + paragraph + reads_paragraph(repo) + held + thread_text(thread) + QUESTION_MARK
            + question)


def tools(routes: Sequence[Route]) -> str:
    return "Read,Grep,Glob,Bash"


def hook_command(routes: Sequence[Route], repo: str | None = None,
                 confinement: tuple[str, ...] | None = None) -> str:
    allowed = json.dumps([list(route.argv) for route in routes], separators=(",", ":"))
    return shlex.join([*siblings.sibling_argv(HOOK_MODULE), allowed, repo or "",
                       *(confinement or ())])


def settings_document(routes: Sequence[Route], repo: str | None = None,
                      confinement: tuple[str, ...] | None = None) -> dict:
    return {
        "permissions": {
            "defaultMode": PERMISSION_MODE,
            "allow": [*READ_RULES, *(f"Bash({' '.join(route.argv)})" for route in routes),
                      *GIT_READ_RULES, *(GH_READ_RULES if repo else ())],
            "deny": list(DENIED_RULES),
        },
        "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{
            "type": "command", "command": hook_command(routes, repo, confinement),
            "timeout": HOOK_TIMEOUT, "onFailure": "block",
        }]}]},
    }


def launch_command(ask: Ask, platform: str) -> list[str] | None:
    if not manager.supported(platform):
        return None
    return ["claude-account", "run", "-p", "--model", model_of(ask), "--session-id", ask.session_id,
            "--permission-mode", PERMISSION_MODE, "--setting-sources", "", "--strict-mcp-config", "--tools", tools(ask.routes),
            "--output-format", "json", "--settings", str(ask.settings),
            prompt(ask.question, ask.routes, ask.thread, repo=ask.repo,
                   records=str(records_path(ask)) if ask.records is not None else None,
                   sections=(question_records.section_lines(
                       ask.records, question_records.DEEP_SECTIONS if ask.deep else question_records.SECTIONS)
                             if ask.records is not None else None),
                   deep=ask.deep)]


def answer_text(result: str, routes: Sequence[Route]) -> str:
    text = result.strip()
    return text if routes else text + "\n" + NO_PRODUCTION_LINE


def session_environment(ask: Ask, environ: Mapping[str, str]) -> dict[str, str]:
    """The client's environment without the repository selection or the contract's credentials."""
    env = manager.client_environment(ask.profile, environ)
    for name in (*GIT_REPOSITORY_ENV, *ask.unset):
        env.pop(name, None)
    return env


def _write_settings(ask: Ask) -> None:
    confinement = ((str(private_dir(ask)), str(records_path(ask)), *((ask.root,) if ask.deep else ()))
                   if ask.records is not None else None)
    directory = ask.settings.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    descriptor, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(settings_document(ask.routes, ask.repo, confinement), handle)
        os.chmod(temporary, 0o600)
        os.replace(temporary, ask.settings)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _prune_records(directory: Path, *, clock=time.time) -> None:
    """Remove the retained records files older than `RECORDS_KEPT_SECONDS` (the question's own 90 days)."""
    cutoff = clock() - RECORDS_KEPT_SECONDS
    for path in directory.glob("*" + RECORDS_SUFFIX):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            pass


def _write_records(ask: Ask) -> None:
    directory = ask.settings.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    _prune_records(directory)
    descriptor, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(ask.records)
        os.chmod(temporary, 0o600)
        os.replace(temporary, records_path(ask))
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _last_line(stderr) -> str | None:
    stderr.seek(0)
    lines = [line.strip() for line in stderr.read().decode("utf-8", "replace").splitlines()]
    lines = [line for line in lines if line]
    return lines[-1] if lines else None


def run_question(ask: Ask, cancel: threading.Event | None = None, *, platform: str = sys.platform,
                 run=manager.run_in_own_group,
                 environ: Mapping[str, str] = os.environ) -> Outcome:
    if ask.deep and ask.records is None:
        return Outcome(FAILED, reason=DEEP_NEEDS_RECORDS)
    argv = launch_command(ask, platform)
    if argv is None:
        return Outcome(FAILED, reason=UNAVAILABLE_TEXT)
    if not os.path.isdir(ask.root):
        return Outcome(FAILED, reason=f"the project root {ask.root} is not a directory")
    try:
        _write_settings(ask)
    except OSError as error:
        return Outcome(FAILED, reason=f"cannot write the question's settings: {error.strerror or error}")
    kept = False
    try:
        if ask.records is not None:
            try:
                _write_records(ask)
            except OSError as error:
                return Outcome(
                    FAILED, reason=RECORDS_UNWRITABLE.format(detail=error.strerror or error))
        with tempfile.TemporaryFile() as stderr:
            try:
                done = run(argv, timeout=timeout_of(ask), cancel=cancel, cwd=ask.root,
                           env=session_environment(ask, environ),
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=stderr,
                           start_new_session=True)
            except subprocess.TimeoutExpired:
                return Outcome(TIMED_OUT, reason=f"the session did not answer within {timeout_of(ask)} s")
            except FileNotFoundError:
                return Outcome(FAILED, reason="claude-account is not installed")
            if cancel is not None and cancel.is_set():
                return Outcome(FAILED, reason=STOPPED_TEXT)
            if done.returncode != 0:
                return Outcome(FAILED, reason=_last_line(stderr)
                               or f"the session exited {done.returncode}")
        outcome = _outcome_of(done.stdout, ask.routes)
        kept = outcome.outcome == ANSWERED and ask.records is not None
        return outcome
    finally:
        ask.settings.unlink(missing_ok=True)
        if not kept:
            records_path(ask).unlink(missing_ok=True)


def _outcome_of(stdout: bytes | None, routes: Sequence[Route]) -> Outcome:
    try:
        value = json.loads((stdout or b"").decode("utf-8"))
    except (ValueError, RecursionError):
        return Outcome(FAILED, reason=UNREADABLE_TEXT)
    if not isinstance(value, dict) or not isinstance(value.get("result"), str):
        return Outcome(FAILED, reason=UNREADABLE_TEXT)
    result = value["result"]
    if value.get("is_error") is True:
        return Outcome(FAILED, reason=result.strip() or "the session ended with an error")
    return Outcome(ANSWERED, answer=answer_text(result, routes))


def asker_for(platform: str) -> Callable[[Ask, threading.Event | None], Outcome] | None:
    return run_question if manager.supported(platform) else None


@dataclass(frozen=True)
class AnswerParts:
    answer: str | None
    read: str | None
    ran: str | None
    unknown: str | None
    back: str | None
    production: str | None
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class AskedQuestion:
    question_id: str
    question: str
    asked_at: str
    seq: int
    state: str = WORKING
    answer: str | None = None
    reason: str | None = None
    answered_at: str | None = None
    thread_id: str | None = None
    request_key: str | None = None
    deep: bool = False
    session_id: str | None = None


def _part(lines: list[str], key: str) -> str | None:
    text = "\n".join(lines).strip()
    if not text or (key != "answer" and text.rstrip(".").strip().lower() == "none"):
        return None
    return text


def answer_parts(text: str) -> AnswerParts:
    body, production = text.rstrip(), None
    if body.endswith(NO_PRODUCTION_LINE):
        body, production = body[:-len(NO_PRODUCTION_LINE)], NO_PRODUCTION_LINE
    buckets: dict[str, list[str]] = {key: [] for key, _ in HEADINGS}
    current, in_fence = "answer", False
    for line in body.splitlines():
        if not in_fence:
            match = _HEADING.match(line)
            if match:
                current = _KEY_OF[match.group(1).lower()]
                line = match.group(2)
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        buckets[current].append(line)
    answer, read, ran, unknown, back = (_part(buckets[key], key) for key, _ in HEADINGS)
    choices: tuple[str, ...] = ()
    if back is not None:
        lines = back.splitlines()
        listed = [m.group(1).strip() for m in map(_LIST_LINE.match, lines) if m]
        asked = "\n".join(l for l in lines if not _LIST_LINE.match(l)).strip()
        if asked and 2 <= len(listed) <= MAX_CHOICES:
            back, choices = asked, tuple(listed)
    return AnswerParts(answer, read, ran, unknown, back, production, choices)


def _answered(question: AskedQuestion, event: Event) -> AskedQuestion:
    payload = event.payload
    outcome, answer, reason = payload.get("outcome"), payload.get("answer"), payload.get("reason")
    reason = reason if isinstance(reason, str) else None
    if outcome == ANSWERED and isinstance(answer, str):
        state = ANSWERED
    elif outcome == ANSWERED:
        state, answer, reason = FAILED, None, UNREADABLE_TEXT
    else:
        state, answer = (TIMED_OUT if outcome == TIMED_OUT else FAILED), None
    return replace(question, state=state, answer=answer, reason=reason, answered_at=event.at)


def asked_questions(events: Iterable[Event],
                    known: Mapping[str, tuple[AskedQuestion, ...]] | None = None
                    ) -> dict[str, tuple[AskedQuestion, ...]]:
    """Each project's questions in ascending `seq`; see "Fold and answer shape" above."""
    found = {project: list(items) for project, items in known.items()} if known else {}
    for event in events:
        project, payload = event.project, event.payload
        if event.kind == PROJECT_QUESTION_DELETED:
            named = payload.get("question_ids")
            if isinstance(project, str) and isinstance(named, list):
                dropped = {name for name in named if isinstance(name, str)}
                found[project] = [item for item in found.get(project, [])
                                  if item.question_id not in dropped]
            continue
        question_id = payload.get("question_id")
        if not isinstance(project, str) or not isinstance(question_id, str) or not question_id:
            continue
        items = found.setdefault(project, [])
        index = next((i for i, item in enumerate(items) if item.question_id == question_id), None)
        if event.kind == PROJECT_QUESTION_ASKED:
            question = payload.get("question")
            if index is None and isinstance(question, str):
                named = payload.get("thread_id")
                head = next((item for item in items if isinstance(named, str) and named
                             and item.question_id == named), None)
                thread_id = (head.thread_id or head.question_id) if head else question_id
                key, session = payload.get("request_key"), payload.get("session_id")
                items.append(AskedQuestion(
                    question_id, question, event.at, event.seq, thread_id=thread_id,
                    request_key=key if isinstance(key, str) and REQUEST_KEY.fullmatch(key) else None,
                    deep=payload.get("deep") is True,
                    session_id=session if isinstance(session, str) and session else None))
        elif event.kind == PROJECT_QUESTION_ANSWERED:
            if index is not None and items[index].state == WORKING:
                items[index] = _answered(items[index], event)
    return {project: tuple(items) for project, items in found.items() if items}


def question_keys(events: Iterable[Event],
                  known: Mapping[tuple[str, str], str] | None = None) -> dict[tuple[str, str], str]:
    """`(project, request key)` to the id of the question asked under it, from the receipt rows (ADR-console-089).

    A receipt is kept whatever its age, so this outlives the asked row `asked_questions` folds; the first receipt of a key wins.
    """
    found = dict(known or {})
    for event in events:
        if event.kind != PROJECT_QUESTION_KEYED or not isinstance(event.project, str):
            continue
        key, question_id = event.payload.get("request_key"), event.payload.get("question_id")
        if (isinstance(key, str) and REQUEST_KEY.fullmatch(key)
                and isinstance(question_id, str) and question_id):
            found.setdefault((event.project, key), question_id)
    return found


def threads(questions: Sequence[AskedQuestion]) -> tuple[tuple[AskedQuestion, ...], ...]:
    groups: dict[str, list[AskedQuestion]] = {}
    for question in sorted(questions, key=lambda q: q.seq):
        groups.setdefault(question.thread_id or question.question_id, []).append(question)
    ordered = sorted(groups.values(), key=lambda group: -group[-1].seq)
    return tuple(tuple(group) for group in ordered)


def _thread_of(questions: Sequence[AskedQuestion], thread_id: str) -> tuple[AskedQuestion, ...]:
    thread = next((group for group in threads(questions)
                   if (group[0].thread_id or group[0].question_id) == thread_id), None)
    if thread is None:
        raise Refused(THREAD_UNKNOWN)
    return thread


def thread_question_ids(questions: Sequence[AskedQuestion], thread_id: str) -> tuple[str, ...]:
    return tuple(q.question_id for q in _thread_of(questions, thread_id))


def follow_up(questions: Sequence[AskedQuestion], thread_id: str, question: str) -> tuple[Turn, ...]:
    thread = _thread_of(questions, thread_id)
    if thread[-1].state != ANSWERED:
        raise Refused(THREAD_UNANSWERED)
    turns = tuple(Turn(q.question, q.answer or "") for q in thread)
    if any(credential_shaped(turn.question) or credential_shaped(turn.answer) for turn in turns):
        raise Refused(THREAD_CREDENTIAL)
    if len(thread_text(turns).encode("utf-8")) + len(question.encode("utf-8")) > MAX_THREAD_BYTES:
        raise Refused(THREAD_TOO_LONG)
    return turns


def deep_follow_up(questions: Sequence[AskedQuestion], thread_id: str,
                   question: str) -> tuple[Turn, ...]:
    """`follow_up`, honoured only for a Dig deeper of the thread's last light answer with this text."""
    turns = follow_up(questions, thread_id, question)
    last = _thread_of(questions, thread_id)[-1]
    if last.deep or last.question != question:
        raise Refused(DEEP_STALE)
    return turns
