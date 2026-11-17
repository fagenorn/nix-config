"""The launch and runner of a read-only project question session (#1176, ADR-console-058).

Why. The console answers an owner's question about a registered project with one Claude Code
client run in that project's folder, under the account the console chose. The session only reads.
This module builds that session (routes, prompt, settings, argv) and runs it to one `Outcome`; the
service (Task 3 of the plan) owns admission, the event log and the thread. Linux only: the
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
`checked_question` strips and refuses an empty question or one over `MAX_QUESTION_CHARS`;
`parse_request` reads the page's strict JSON body of exactly `project_id` and `question`.

Settings and fail closed (D7). `settings_document(routes)` is the one `--settings` file. Several
layers each refuse on their own: `--setting-sources ""` loads no user, project or local settings,
so the account's `auto` mode and its allows never apply; `dontAsk` denies every call that is not
pre-approved; the allow list is `READ_RULES`, one `Bash(<argv>)` per route, the `GIT_READ_RULES` and,
when the project has a GitHub repository, the `GH_READ_RULES`; the deny list is `DENIED_RULES`,
which wins over any allow; `--tools` removes every other built-in tool, and Bash is always a tool
(the git reads need it even with no route). On top of those, a PreToolUse command hook
(`project_question_hook`, run through `siblings.sibling_argv`, given the allowed argv and the
repository) admits only reads, the bare declared commands and the plain git and gh reads;
`"onFailure": "block"` makes the pinned client treat a hook that errors, fails
to start or times out as a block, because without it such a hook is non-blocking and the call would
fall to the permission rules. The file lives in `SETTINGS_DIR` under the console's state (a 0700
directory, the file 0600, written atomically) and is removed when the run ends.

Argv. `launch_command` is None off Linux, else `claude-account run -p --model sonnet
--session-id <id> --permission-mode dontAsk --setting-sources "" --strict-mcp-config --tools <tools>
--output-format json --settings <file> <prompt>`. `--tools` is variadic: it is always followed by
another option, so the prompt, which is last, is never swallowed into the tool list. The session id
is a fresh UUID per question, which the service records in the asked row so the Spend page can tell
the question's transcript (ADR-console-059). No `systemd-run` scope is used.

Runner. `run_question` never raises for these cases and removes the settings file once written, in
this order: no launch command (`UNAVAILABLE_TEXT`); a root that is not a directory; a settings
write that fails; the run itself with `TIMEOUT_SECONDS`, the `cancel` event, `stdin` closed and
stderr to a temporary file; `TimeoutExpired` (`TIMED_OUT`); a missing `claude-account`; a set
`cancel` (`STOPPED_TEXT`); a non-zero exit (the last non-empty stderr line); then the JSON on
stdout: not an object with a string `result` (`UNREADABLE_TEXT`), `is_error` true (the result text),
else `ANSWERED` with `answer_text`, which adds `NO_PRODUCTION_LINE` when no route is declared (D5).
`asker_for(platform)` is `run_question` where the manager is supported, else None.

Fold and answer shape (#1177). `asked_questions(events, known)` folds the two row kinds into each
project's questions, a tuple of `AskedQuestion` in ascending `seq`. An asked row counts only with
a string project column, a non-empty string `question_id` not already folded for that project and
a string `question`; an answered row applies only to a still-working question of the same id in
the same project (the first answer wins, strays are ignored): outcome `answered` with a string
`answer` is `ANSWERED`, `answered` without one is `FAILED` with `UNREADABLE_TEXT`, `timed_out` is
`TIMED_OUT`, anything else is `FAILED`; `reason` is kept only when a string and `answered_at` is
the answered row's `at`. Folding two batches through `known` equals folding once, and `known` is
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
`parse_request` reads exactly `project_id` and `question`, or those with a non-empty string
`thread_id`, and returns `(project_id, question, thread_id or None)`.
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
import uuid
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.console import manager
from agent_tools.console.event_log import (
    PROJECT_QUESTION_ANSWERED, PROJECT_QUESTION_ASKED, Event)
from agent_tools.console.project_question_hook import (
    GH_READ_GROUPS, GH_READ_VERBS, GIT_READS, PLAIN_WORD, REPO_SLUG)
from agent_tools.project_contract import resolve_project
from agent_tools.system import siblings

MODEL = "sonnet"
PERMISSION_MODE = "dontAsk"
TIMEOUT_SECONDS = 300
MAX_QUESTION_CHARS = 2000
SETTINGS_DIR = "project-question-settings"
SETTINGS_SUFFIX = ".settings.json"
HOOK_MODULE = "console.project_question_hook"
GIT_REPOSITORY_ENV = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_PREFIX")
HOOK_TIMEOUT = 10
QUESTION_MARK = "The question: "
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
    "inside it from the dates you read: raise the list limit (for example --limit) until the "
    "oldest item you read is older than the window, never stop at a first page or an arbitrary "
    "limit, and say in the answer where the count comes from. "
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
THREAD_UNKNOWN = "this thread is not one of the project's questions"
THREAD_UNANSWERED = "a follow-up continues a thread whose last question was answered"
THREAD_TOO_LONG = "this thread is too long to continue: ask a new question"

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
            unset: Sequence[str] = ()) -> Ask:
    return Ask(question_id, project_id, root, question, profile, tuple(routes),
               Path(settings_dir) / (question_id + SETTINGS_SUFFIX), session_id, tuple(thread), repo,
               tuple(unset))


def checked_question(text: str) -> str:
    text = text.strip()
    if not text:
        raise Refused(EMPTY)
    if len(text) > MAX_QUESTION_CHARS:
        raise Refused(TOO_LONG)
    return text


def parse_request(body: bytes) -> tuple[str, str, str | None]:
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except RecursionError as error:
        raise ValueError("the body is nested too deeply") from error
    if not isinstance(value, dict) or set(value) not in (
            {"project_id", "question"}, {"project_id", "question", "thread_id"}):
        raise ValueError(
            "the body must be an object of project_id, question and an optional thread_id")
    project_id, question = value["project_id"], value["question"]
    thread_id = value.get("thread_id")
    if "thread_id" in value and (not isinstance(thread_id, str) or not thread_id):
        raise ValueError("thread_id must be a non-empty string")
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("project_id must be a non-empty string")
    if not isinstance(question, str):
        raise ValueError("question must be a string")
    return project_id, question, thread_id


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
           repo: str | None = None) -> str:
    if routes:
        paragraph = ("Commands you may run, each exactly as written and alone: "
                     + ", ".join(shlex.join(route.argv) for route in routes) + ".\n\n")
    else:
        paragraph = ("This project declares no read-only command, so production cannot be read: "
                     "answer from the code, the docs and the reads below.\n\n")
    return LEAD + paragraph + reads_paragraph(repo) + thread_text(thread) + QUESTION_MARK + question


def tools(routes: Sequence[Route]) -> str:
    return "Read,Grep,Glob,Bash"


def hook_command(routes: Sequence[Route], repo: str | None = None) -> str:
    allowed = json.dumps([list(route.argv) for route in routes], separators=(",", ":"))
    return shlex.join([*siblings.sibling_argv(HOOK_MODULE), allowed, repo or ""])


def settings_document(routes: Sequence[Route], repo: str | None = None) -> dict:
    return {
        "permissions": {
            "defaultMode": PERMISSION_MODE,
            "allow": [*READ_RULES, *(f"Bash({' '.join(route.argv)})" for route in routes),
                      *GIT_READ_RULES, *(GH_READ_RULES if repo else ())],
            "deny": list(DENIED_RULES),
        },
        "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{
            "type": "command", "command": hook_command(routes, repo),
            "timeout": HOOK_TIMEOUT, "onFailure": "block",
        }]}]},
    }


def launch_command(ask: Ask, platform: str) -> list[str] | None:
    if not manager.supported(platform):
        return None
    return ["claude-account", "run", "-p", "--model", MODEL, "--session-id", ask.session_id,
            "--permission-mode", PERMISSION_MODE, "--setting-sources", "", "--strict-mcp-config", "--tools", tools(ask.routes),
            "--output-format", "json", "--settings", str(ask.settings),
            prompt(ask.question, ask.routes, ask.thread, repo=ask.repo)]


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
    directory = ask.settings.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    descriptor, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(settings_document(ask.routes, ask.repo), handle)
        os.chmod(temporary, 0o600)
        os.replace(temporary, ask.settings)
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
    argv = launch_command(ask, platform)
    if argv is None:
        return Outcome(FAILED, reason=UNAVAILABLE_TEXT)
    if not os.path.isdir(ask.root):
        return Outcome(FAILED, reason=f"the project root {ask.root} is not a directory")
    try:
        _write_settings(ask)
    except OSError as error:
        return Outcome(FAILED, reason=f"cannot write the question's settings: {error.strerror or error}")
    try:
        with tempfile.TemporaryFile() as stderr:
            try:
                done = run(argv, timeout=TIMEOUT_SECONDS, cancel=cancel, cwd=ask.root,
                           env=session_environment(ask, environ),
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=stderr,
                           start_new_session=True)
            except subprocess.TimeoutExpired:
                return Outcome(TIMED_OUT, reason=f"the session did not answer within {TIMEOUT_SECONDS} s")
            except FileNotFoundError:
                return Outcome(FAILED, reason="claude-account is not installed")
            if cancel is not None and cancel.is_set():
                return Outcome(FAILED, reason=STOPPED_TEXT)
            if done.returncode != 0:
                return Outcome(FAILED, reason=_last_line(stderr)
                               or f"the session exited {done.returncode}")
        return _outcome_of(done.stdout, ask.routes)
    finally:
        ask.settings.unlink(missing_ok=True)


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
                items.append(AskedQuestion(question_id, question, event.at, event.seq,
                                           thread_id=thread_id))
        elif event.kind == PROJECT_QUESTION_ANSWERED:
            if index is not None and items[index].state == WORKING:
                items[index] = _answered(items[index], event)
    return {project: tuple(items) for project, items in found.items() if items}


def threads(questions: Sequence[AskedQuestion]) -> tuple[tuple[AskedQuestion, ...], ...]:
    groups: dict[str, list[AskedQuestion]] = {}
    for question in sorted(questions, key=lambda q: q.seq):
        groups.setdefault(question.thread_id or question.question_id, []).append(question)
    ordered = sorted(groups.values(), key=lambda group: -group[-1].seq)
    return tuple(tuple(group) for group in ordered)


def follow_up(questions: Sequence[AskedQuestion], thread_id: str, question: str) -> tuple[Turn, ...]:
    thread = next((group for group in threads(questions)
                   if (group[0].thread_id or group[0].question_id) == thread_id), None)
    if thread is None:
        raise Refused(THREAD_UNKNOWN)
    if thread[-1].state != ANSWERED:
        raise Refused(THREAD_UNANSWERED)
    turns = tuple(Turn(q.question, q.answer or "") for q in thread)
    if len(thread_text(turns).encode("utf-8")) + len(question.encode("utf-8")) > MAX_THREAD_BYTES:
        raise Refused(THREAD_TOO_LONG)
    return turns
