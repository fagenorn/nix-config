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
route of such a project and wrongly answer with the production line (D9). `routes_of(root)` is
`read_only_routes(resolve(root))` and lets every exception, a `ContractError` included, propagate:
`()` means only "resolved, no runnable read-only command" (bootstrap: never guess a value the
resolver declined). `resolve` is a test seam only.

Prompt. `LEAD`, then a routes paragraph (the declared commands, each exactly as written and alone;
or that none is declared so production cannot be read), then `QUESTION_MARK` and the question.
`checked_question` strips and refuses an empty question or one over `MAX_QUESTION_CHARS`;
`parse_request` reads the page's strict JSON body of exactly `project_id` and `question`.

Settings and fail closed (D7). `settings_document(routes)` is the one `--settings` file. Several
layers each refuse on their own: `--setting-sources ""` loads no user, project or local settings,
so the account's `auto` mode and its allows never apply; `dontAsk` denies every call that is not
pre-approved; the allow list is `READ_RULES` plus one `Bash(<argv>)` per route; the deny list is
`DENIED_RULES`, which wins over any allow; `--tools` removes every other built-in tool, and with no
route the Bash tool does not exist at all. On top of those, a PreToolUse command hook
(`project_question_hook`, run through `siblings.sibling_argv`) admits only reads and the bare
declared commands; `"onFailure": "block"` makes the pinned client treat a hook that errors, fails
to start or times out as a block, because without it such a hook is non-blocking and the call would
fall to the permission rules. The file lives in `SETTINGS_DIR` under the console's state (a 0700
directory, the file 0600, written atomically) and is removed when the run ends.

Argv. `launch_command` is None off Linux, else `claude-account run -p --model sonnet
--permission-mode dontAsk --setting-sources "" --strict-mcp-config --tools <tools>
--output-format json --settings <file> <prompt>`. `--tools` is variadic: it is always followed by
another option, so the prompt, which is last, is never swallowed into the tool list. No
`systemd-run` scope is used.

Runner. `run_question` never raises for these cases and removes the settings file once written, in
this order: no launch command (`UNAVAILABLE_TEXT`); a root that is not a directory; a settings
write that fails; the run itself with `TIMEOUT_SECONDS`, the `cancel` event, `stdin` closed and
stderr to a temporary file; `TimeoutExpired` (`TIMED_OUT`); a missing `claude-account`; a set
`cancel` (`STOPPED_TEXT`); a non-zero exit (the last non-empty stderr line); then the JSON on
stdout: not an object with a string `result` (`UNREADABLE_TEXT`), `is_error` true (the result text),
else `ANSWERED` with `answer_text`, which adds `NO_PRODUCTION_LINE` when no route is declared (D5).
`asker_for(platform)` is `run_question` where the manager is supported, else None.
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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.console import manager
from agent_tools.console.project_question_hook import PLAIN_WORD
from agent_tools.project_contract import resolve_project
from agent_tools.system import siblings

MODEL = "sonnet"
PERMISSION_MODE = "dontAsk"
TIMEOUT_SECONDS = 300
MAX_QUESTION_CHARS = 2000
SETTINGS_DIR = "project-question-settings"
SETTINGS_SUFFIX = ".settings.json"
HOOK_MODULE = "console.project_question_hook"
HOOK_TIMEOUT = 10
QUESTION_MARK = "The question: "
ANSWERED = "answered"
FAILED = "failed"
TIMED_OUT = "timed_out"

READ_RULES = ("Read", "Grep", "Glob")
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

LEAD = (
    "You answer one question about this project for its owner, started by the console. You only "
    "read: a step you are refused stays refused. A step that would cost money or needs a "
    "credential you lack is never attempted: put it in your answer as a question for the owner. "
    "Reply in exactly this shape, one heading per line:\n"
    "Answer: <the answer in plain words>\n"
    "Read: <the files you read, or none>\n"
    "Ran: <the commands you ran, or none>\n"
    "Could not find out: <what you could not find out, or none>\n"
    "Question for you: <a step that needs money or a credential, or none>\n\n"
)


class Refused(Exception):
    """A question the console will not start; `str` is the one-line reason."""


@dataclass(frozen=True)
class Route:
    id: str
    argv: tuple[str, ...]
    cwd: str


@dataclass(frozen=True)
class Ask:
    question_id: str
    project_id: str
    root: str
    question: str
    profile: str
    routes: tuple[Route, ...]
    settings: Path


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
    bindings = snapshot["bindings"]["commands"]
    routes = []
    for id in production["read_only"]["commands"]:
        binding = bindings.get(id)
        if binding is None or not _plain_argv(binding.get("argv")):
            continue
        cwd = binding["cwd"]
        if not isinstance(cwd, str) or os.path.normpath(cwd) != root:
            continue
        routes.append(Route(id, tuple(binding["argv"]), cwd))
    return tuple(routes)


def routes_of(root: str, *,
              resolve: Callable[[str], Mapping] = resolve_project.resolve) -> tuple[Route, ...]:
    return read_only_routes(resolve(root))


def new_question_id() -> str:
    return secrets.token_hex(8)


def new_ask(question_id: str, project_id: str, root: str, question: str, profile: str,
            routes: Sequence[Route], settings_dir: Path) -> Ask:
    return Ask(question_id, project_id, root, question, profile, tuple(routes),
               Path(settings_dir) / (question_id + SETTINGS_SUFFIX))


def checked_question(text: str) -> str:
    text = text.strip()
    if not text:
        raise Refused(EMPTY)
    if len(text) > MAX_QUESTION_CHARS:
        raise Refused(TOO_LONG)
    return text


def parse_request(body: bytes) -> tuple[str, str]:
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except RecursionError as error:
        raise ValueError("the body is nested too deeply") from error
    if not isinstance(value, dict) or set(value) != {"project_id", "question"}:
        raise ValueError("the body must be an object of project_id, question")
    project_id, question = value["project_id"], value["question"]
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("project_id must be a non-empty string")
    if not isinstance(question, str):
        raise ValueError("question must be a string")
    return project_id, question


def prompt(question: str, routes: Sequence[Route]) -> str:
    if routes:
        paragraph = ("Commands you may run, each exactly as written and alone: "
                     + ", ".join(shlex.join(route.argv) for route in routes) + ".\n\n")
    else:
        paragraph = ("This project declares no read-only command, so production cannot be read: "
                     "answer from the code and docs only.\n\n")
    return LEAD + paragraph + QUESTION_MARK + question


def tools(routes: Sequence[Route]) -> str:
    return "Read,Grep,Glob,Bash" if routes else "Read,Grep,Glob"


def hook_command(routes: Sequence[Route]) -> str:
    allowed = json.dumps([list(route.argv) for route in routes], separators=(",", ":"))
    return shlex.join([*siblings.sibling_argv(HOOK_MODULE), allowed])


def settings_document(routes: Sequence[Route]) -> dict:
    return {
        "permissions": {
            "defaultMode": PERMISSION_MODE,
            "allow": [*READ_RULES, *(f"Bash({' '.join(route.argv)})" for route in routes)],
            "deny": list(DENIED_RULES),
        },
        "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{
            "type": "command", "command": hook_command(routes),
            "timeout": HOOK_TIMEOUT, "onFailure": "block",
        }]}]},
    }


def launch_command(ask: Ask, platform: str) -> list[str] | None:
    if not manager.supported(platform):
        return None
    return ["claude-account", "run", "-p", "--model", MODEL, "--permission-mode", PERMISSION_MODE,
            "--setting-sources", "", "--strict-mcp-config", "--tools", tools(ask.routes),
            "--output-format", "json", "--settings", str(ask.settings),
            prompt(ask.question, ask.routes)]


def answer_text(result: str, routes: Sequence[Route]) -> str:
    text = result.strip()
    return text if routes else text + "\n" + NO_PRODUCTION_LINE


def _write_settings(ask: Ask) -> None:
    directory = ask.settings.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    descriptor, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(settings_document(ask.routes), handle)
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
                           env=manager.client_environment(ask.profile, environ),
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
