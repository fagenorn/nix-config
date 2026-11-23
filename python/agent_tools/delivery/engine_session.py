"""What the engine reads for one agent step: a role, a prompt and a session result (#1514).

A role is the file `~/.claude/agents/<role>.md` (`roles_dir`): its frontmatter
gives `model`, `effort`, the optional `tools` and `disallowedTools` lists (comma
separated) and its body is kept as the role's system prompt. The frontmatter
parser checks no value's fitness for a command line, so `refuse_value` refuses
any value that would put an option the engine never passes, or a permission
bypass, into the launch argv.

`render_prompt` fills each `{{path}}` placeholder of a prompt file with the
argument words of the step's `in` values.

`read_result` reads the one JSON object a print-mode session writes to stdout:
its `structured_output` is the only source of the reply, the prose in `result`
never is, and every measurement that is absent or invalid reads as zero. A result whose
`is_error` is true with an `api_error` string or an integer `api_error_status` is an API failure
(`Reading.api_failure`): `usage-limit` for the `api_error` `usage_limit_reached`, else `api-error`, which the shell retries once and then
reads as the outcome `no-reply`.

`launch_argv` builds the one launch form: the account launcher's print mode
(`claude-account run -p`) with the role handed over by flags (`--model`,
`--effort`, `--tools` with `--allowedTools`, or `--disallowedTools`, and the
role body as `--append-system-prompt-file`), the bounds `--max-turns` and
`--max-budget-usd` from the platform's role table (`ROLE_BOUNDS`, which no
procedure, project or environment variable changes), the reply schema as
`--json-schema`, the session id first fixed by the engine, and the permission
mode `dontAsk`, so a tool the role does not allow is denied rather than asked
about. A session that hit a usage limit is started again with `--resume <session>` in place of
`--session-id <session>`, every other word unchanged; the transcripts are shared between accounts,
so the launcher's next account continues the same session. The engine never passes `--agent`, `--bare`,
`--setting-sources`, `--dangerously-skip-permissions` or `bypassPermissions`: `--bare` would skip the
hooks that guard the session, and the others would hand the session its own
settings or its permissions. The prompt is never in the argv: the tool options
are variadic and would swallow a positional prompt, so `launch` writes it on
stdin.

A session that gave no usable structured answer is asked once more on the same session
(`resume=True`: `--session-id <id>` becomes `--resume <id>`, never `--fork-session`) with the prompt
`REASK_PROMPT`. A miss is a reading with no reply that conforms to the schema
(`engine_reply.reply_problem`) whose stdout is a `result` with a `subtype` in `MISS_SUBTYPES`:
`success` with `is_error` not set, or the client's own `error_max_structured_output_retries`,
flagged or not (`is_miss`). Any other reading without a usable reply is never resumed. A continued
run resumes a session its predecessor left interrupted with `CONTINUE_PROMPT`, which asks it to finish
the task it was given and then give only the structured answer.

The role's `Bash` stays in `--tools` but is preapproved only as the reviewer's
permitted read-only git inspection (`READ_ONLY_BASH`): under `dontAsk` any other
shell command is denied, so a session cannot write to the worktree through it.
`git diff`, `git log` and `git show` write a file given `--output`, which those
prefix patterns would preapprove, so `GIT_WRITING` is passed as
`--disallowedTools` (a deny rule is checked before an allow rule). A role that
needs another shell command lists it in its own `tools` as `Bash(<prefix>:*)`;
one that is denied a shell command anyway is a fault (`engine_shell`), never a
graded reply.

The launcher tells the engine its choice through an answer file: the launch environment carries
`CLAUDE_ACCOUNT_ANSWER`, the path of a file the launcher writes, and `read_answer` reads it. It holds
exactly `{"account": <name>}` (the account the session ran on) or `{"all_out": true,
"resumes_at": <RFC3339 UTC time or null>}` (every account is out; the launcher then exits
`ALL_OUT_EXIT`), and anything else, or no file, is no answer.

`launch` starts the argv as its own process group (`start_new_session`) because
the account launcher waits on its Claude child instead of replacing itself, so
a session is a process tree and ending it means killing the group, which a
SIGTERM to the engine (turned into `SystemExit` while the session runs) and any
other exception, `engine_stop.Stopped` from a polled `stop` included, both do; the
kill reaps the launcher and closes the pipes without waiting for EOF, so a descendant
outside the group that holds a pipe cannot hold the engine. A session started off the main thread (a group
member's, a child walk's) cannot install that handler, so it is registered from its spawn until it is
reaped, and `reaping` (held by the main thread while it waits for such sessions) turns a
SIGTERM or any other stop in the main thread into a kill of every registered group and closes
the registry: after that `launch` starts no session and `ending()` is true. `ending()` is true
as soon as the interpreter has taken a SIGTERM (`reaping` installs a wakeup descriptor), before the
main thread has run the handler. The `timeout` of `launch` is the wall bound, counted from the spawn
(so the time `on_start` takes is inside it, and the deadline is armed, as a `Watchdog` thread, before
`on_start` runs, so a stalled `on_start` cannot keep the group past it): a session past it gets SIGTERM to
its whole group, then `GRACE_SECONDS` for the group (not only the launcher) to
be gone, and SIGKILL to the group if any member is still alive; the call returns
with `timed_out` set within `timeout + GRACE_SECONDS + DRAIN_SECONDS`. A `stop` that is true before
the launcher starts, or turns true while it runs or by the time it ended, raises `Stopped` (after the
group is killed, once it started). A launcher that
cannot start gives exit 127 and the `OSError` text as its stderr. Its stderr is
captured so the launcher's own error is never a second line on the engine's
stderr; `diagnostic` gives the last line of it for the engine's one fault line. A given `env` is
the launcher's whole environment, without one it inherits the engine's; `session_environment` is applied to either.

A session ended by a bound has no reply: its result subtype is `error_max_turns` (the bound
`turns`) or `error_max_budget_usd` (the bound `spend`), named by `CAP_SUBTYPES`; `WALL_TIME`
names the bound the engine's own clock fires.

`session_environment` drops `CLAUDE_CONFIG_DIR` and sets `CLAUDE_ACCOUNT_HOST_SETTINGS=required`, so the
launcher starts the client only on `$HOME/.claude/settings.json`, the file `engine deliver` checked.

This module imports no `engine_core`.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

from agent_tools.canonical import (
    parse_rfc3339_utc, reject_duplicate_keys, reject_nonfinite_literal,
)
from agent_tools.delivery import engine_stop
from agent_tools.delivery.engine_commands import Watchdog, argument
from agent_tools.delivery.engine_ledger import TOKEN_COUNTS
from agent_tools.delivery.procedure_check import PLACEHOLDER_RE, ROLES
from agent_tools.skill_lint import parse_frontmatter

FORBIDDEN_WORDS: tuple[str, ...] = (
    "--agent", "--bare", "--setting-sources", "--dangerously-skip-permissions",
    "bypassPermissions",
)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
LAUNCHER: tuple[str, ...] = ("claude-account", "run")
HOST_SETTINGS_SWITCH = "CLAUDE_ACCOUNT_HOST_SETTINGS"
WALL_TIME = "wall-time"
CAP_SUBTYPES: Mapping[str, str] = MappingProxyType(
    {"error_max_turns": "turns", "error_max_budget_usd": "spend"})
NOT_STARTED = 127
STRUCTURED_OUTPUT_EXHAUSTED = "error_max_structured_output_retries"
MISS_SUBTYPES: tuple[str, ...] = ("success", STRUCTURED_OUTPUT_EXHAUSTED)
REASK_PROMPT = (
    "Your last answer was not a valid structured answer. Reply again with only the structured "
    "answer, a single call of the StructuredOutput tool whose members follow the schema, and no "
    "other text.")
CONTINUE_PROMPT = (
    "Your session was interrupted. Finish the task you were given, then give only the structured "
    "answer, a single call of the StructuredOutput tool whose members follow the schema, and no "
    "other text.")
ANSWER_ENV = "CLAUDE_ACCOUNT_ANSWER"
ALL_OUT_EXIT = 75
USAGE_LIMIT = "usage-limit"
API_ERROR = "api-error"
GRACE_SECONDS = 5
DRAIN_SECONDS = 5
READ_ONLY_BASH: tuple[str, ...] = tuple(
    f"Bash(git {verb}:*)" for verb in ("diff", "log", "show", "status", "rev-parse", "ls-files",
                                      "blame", "merge-base"))
GIT_WRITING: tuple[str, ...] = tuple(
    f"Bash(git {verb}*--output*)" for verb in ("diff", "log", "show"))
DIAGNOSTIC_CHARS = 300
_USAGE_KEYS = {"input": "input_tokens", "cache_write": "cache_creation_input_tokens",
               "cache_read": "cache_read_input_tokens", "output": "output_tokens"}


class RoleError(ValueError):
    """A role file that cannot give a role, or a value the launch must not carry."""


@dataclass(frozen=True)
class Role:
    name: str
    model: str
    effort: str
    tools: tuple[str, ...] | None
    disallowed: tuple[str, ...] | None
    body: str


@dataclass(frozen=True)
class Bounds:
    wall_seconds: float
    turns: int
    spend_usd: float


ROLE_BOUNDS: Mapping[str, Bounds] = MappingProxyType({
    "planner": Bounds(1800, 150, 15.0), "implementer": Bounds(3600, 300, 20.0),
    "reviewer": Bounds(1800, 150, 15.0), "reviewer-lite": Bounds(900, 80, 3.0)})


def bounds(role: str) -> Bounds:
    """The wall-time, turn and spend bounds of `role`; a role the table lacks is refused."""
    found = ROLE_BOUNDS.get(role)
    if found is None:
        raise RoleError(f"role {role}: no bounds")
    return found


def refuse_value(role: str, field: str, value: str) -> None:
    """Raise `RoleError` when `value` would put a forbidden word in the launch argv."""
    problem = None
    if value.startswith("-"):
        problem = "starts with -"
    elif any(word in value for word in FORBIDDEN_WORDS):
        problem = "holds a word the launch never passes"
    elif _CONTROL_RE.search(value):
        problem = "holds a control character"
    elif field in ("model", "effort") and re.search(r"\s", value):
        problem = "holds whitespace"
    if problem is not None:
        raise RoleError(f"role {role}: {field} {value!r} {problem}")


def roles_dir(environ: Mapping[str, str]) -> Path:
    return Path(environ["HOME"]) / ".claude" / "agents"


def _names(role: str, field: str, text: str | None) -> tuple[str, ...] | None:
    if text is None:
        return None
    names = tuple(part.strip() for part in text.split(",") if part.strip())
    if not names:
        raise RoleError(f"role {role}: {field} holds no tool name")
    for name in names:
        refuse_value(role, field, name)
    return names


def read_role(directory: Path, name: str) -> Role:
    if name not in ROLES:
        raise RoleError(f"role {name}: not one of {', '.join(ROLES)}")
    path = Path(directory) / f"{name}.md"
    try:
        fields, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise RoleError(f"role {name}: cannot read {path}: {error}") from error
    if "name" in fields and fields["name"] != name:
        raise RoleError(f"role {name}: its file names the role {fields['name']!r}")
    for field in ("model", "effort"):
        if not fields.get(field):
            raise RoleError(f"role {name}: {field} is missing or empty")
        refuse_value(name, field, fields[field])
    return Role(name, fields["model"], fields["effort"],
                _names(name, "tools", fields.get("tools")),
                _names(name, "disallowedTools", fields.get("disallowedTools")), body)


def render_prompt(text: str, args: Sequence[tuple[str, object]]) -> str:
    """`text` with each `{{path}}` placeholder replaced by its argument word."""
    values = dict(args)

    def fill(match: re.Match) -> str:
        path = match.group(1)
        if path not in values:
            raise ValueError(f"placeholder {path!r} names no input of the step")
        return argument(values[path])

    return PLACEHOLDER_RE.sub(fill, text)


@dataclass(frozen=True)
class Reading:
    reply: dict | None
    prose: str | None
    denials: list
    subtype: str | None
    wall_seconds: float | None
    turns: int
    tokens: dict[str, int]
    spend_usd: float
    is_result: bool = False
    is_error: bool = False
    api_failure: str | None = None


@dataclass(frozen=True)
class Answer:
    account: str | None
    all_out: bool
    resumes_at: str | None


def _number(text: str) -> int | float:
    """A JSON number written with a fraction or exponent: an int when it is integral, so `2.0` reads as 2."""
    value = float(text)
    return int(value) if value.is_integer() else value


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _amount(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return value if math.isfinite(value) and value >= 0 else None
    except OverflowError:
        return None


def _strict_json(text: str) -> object:
    return json.loads(text, object_pairs_hook=reject_duplicate_keys,
                      parse_constant=reject_nonfinite_literal, parse_float=_number)


def read_answer(path: Path) -> Answer:
    """The launcher's answer in `path`; anything but the two exact forms is no answer."""
    nothing = Answer(None, False, None)
    try:
        document = _strict_json(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return nothing
    if not isinstance(document, dict):
        return nothing
    account = document.get("account")
    if set(document) == {"account"} and isinstance(account, str) and account:
        return Answer(account, False, None)
    resumes_at = document.get("resumes_at")
    if set(document) == {"all_out", "resumes_at"} and document["all_out"] is True:
        if resumes_at is not None:
            try:
                parse_rfc3339_utc(resumes_at)
            except ValueError:
                return nothing
        return Answer(None, True, resumes_at)
    return nothing


def _api_failure(document: dict) -> str | None:
    error, status = document.get("api_error"), document.get("api_error_status")
    if document.get("is_error") is not True:
        return None
    if not (isinstance(error, str) and error) and not (
            isinstance(status, int) and not isinstance(status, bool)):
        return None
    return USAGE_LIMIT if error == "usage_limit_reached" else API_ERROR


def read_result(stdout: bytes) -> Reading:
    """The reply, prose, denials and measurements of a session's stdout."""
    try:
        document = _strict_json(stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        document = None
    if not isinstance(document, dict):
        return Reading(None, None, [], None, None, 0, dict.fromkeys(TOKEN_COUNTS, 0), 0)
    usage = document.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    wall = _amount(document.get("duration_ms"))
    denials = document.get("permission_denials")
    reply, prose, subtype = (document.get("structured_output"), document.get("result"),
                             document.get("subtype"))
    return Reading(
        reply=reply if isinstance(reply, dict) else None,
        prose=prose if isinstance(prose, str) else None,
        denials=denials if isinstance(denials, list) else [],
        subtype=subtype if isinstance(subtype, str) else None,
        wall_seconds=None if wall is None else wall / 1000,
        turns=_count(document.get("num_turns")),
        tokens={key: _count(usage.get(_USAGE_KEYS[key])) for key in TOKEN_COUNTS},
        spend_usd=_amount(document.get("total_cost_usd")) or 0,
        is_result=document.get("type") == "result",
        is_error=document.get("is_error") is True,
        api_failure=_api_failure(document))


def is_miss(reading: Reading) -> bool:
    """True when a reading with no usable reply is one the session is asked again about: a result whose
    subtype is in `MISS_SUBTYPES`, a `success` flagging `is_error` being a client error and no miss.
    """
    if not reading.is_result or reading.subtype not in MISS_SUBTYPES:
        return False
    return not reading.is_error or reading.subtype == STRUCTURED_OUTPUT_EXHAUSTED


def launch_argv(role: Role, schema: Mapping, session: str, system_prompt: Path, *,
                resume: bool = False) -> tuple[str, ...]:
    """The launcher argv of one session; no word of it is a prompt.

    With `resume`, `--resume <session>` takes the place of `--session-id <session>`.
    """
    refuse_value(role.name, "model", role.model)
    refuse_value(role.name, "effort", role.effort)
    for field, names in (("tools", role.tools), ("disallowedTools", role.disallowed)):
        for name in names or ():
            refuse_value(role.name, field, name)
    limits = bounds(role.name)
    argv = [*LAUNCHER, "-p", "--output-format", "json",
            "--json-schema", json.dumps(schema, sort_keys=True, separators=(",", ":")),
            "--resume" if resume else "--session-id", session, "--strict-mcp-config",
            "--permission-mode", "dontAsk",
            "--model", role.model, "--effort", role.effort,
            "--max-turns", str(limits.turns), "--max-budget-usd", f"{limits.spend_usd:.2f}"]
    disallowed = list(role.disallowed or ())
    if role.tools is not None:
        allowed = [entry for name in role.tools
                   for entry in (READ_ONLY_BASH if name == "Bash" else (name,))]
        argv += ["--tools", ",".join(role.tools), "--allowedTools", ",".join(allowed)]
        if "Bash" in role.tools:
            disallowed += GIT_WRITING
    if role.disallowed is not None or disallowed:
        argv += ["--disallowedTools", ",".join(disallowed)]
    return (*argv, "--append-system-prompt-file", str(system_prompt))


@dataclass(frozen=True)
class Launched:
    exit_code: int
    stdout: bytes
    stderr: bytes
    wall_seconds: float
    timed_out: bool = False


def diagnostic(stderr: bytes) -> str:
    """The last non-blank line of `stderr`, spaces collapsed, cut to 300 characters."""
    lines = [line for line in stderr.decode("utf-8", errors="replace").splitlines()
             if line.strip()]
    return " ".join(lines[-1].split())[:DIAGNOSTIC_CHARS] if lines else ""


def _terminate(signum: int, frame: object) -> None:
    raise SystemExit(128 + signum)


_registry = threading.Lock()
_live: set[int] = set()
_closed = False
_wakeup_read: int | None = None


def _sigterm_taken() -> bool:
    """True once the interpreter has taken a SIGTERM that `_terminate` has not yet run for.

    The interpreter writes each signal number it takes to the wakeup descriptor `reaping`
    installs, from any thread; the caller holds `_registry`.
    """
    if _wakeup_read is None:
        return False
    try:
        return signal.SIGTERM in os.read(_wakeup_read, 64)
    except BlockingIOError:
        return False


def _is_closed() -> bool:
    """Whether the registry is closed, closing it on a SIGTERM already taken; the caller holds `_registry`."""
    global _closed
    if not _closed and _sigterm_taken():
        _closed = True
    return _closed


def ending() -> bool:
    """True once the registry is closed, by `reaping` or by a SIGTERM taken: no session starts after that."""
    with _registry:
        return _is_closed()


def _reap() -> None:
    """Close the registry and kill every registered session's process group."""
    global _closed
    with _registry:
        _closed = True
        live = list(_live)
    for pid in live:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


@contextlib.contextmanager
def reaping():
    """Turn SIGTERM into `SystemExit` while the main thread waits, and reap every live session.

    A stop that is not an `Exception` leaving the block in the main thread closes the registry and
    kills every session's process group before it propagates; the replaced handler is restored.
    """
    global _wakeup_read
    try:
        previous = signal.signal(signal.SIGTERM, _terminate)
        installed = True
    except ValueError:  # not the main thread: no handler can be installed
        previous, installed = None, False
    if installed:
        read_end, write_end = os.pipe()
        os.set_blocking(read_end, False)
        os.set_blocking(write_end, False)
        previous_wakeup = signal.set_wakeup_fd(write_end, warn_on_full_buffer=False)
        _wakeup_read = read_end
    try:
        yield
    except Exception:
        raise
    except BaseException:
        if threading.current_thread() is threading.main_thread():
            _reap()
        raise
    finally:
        if installed:
            signal.signal(signal.SIGTERM, previous if previous is not None else signal.SIG_DFL)
            signal.set_wakeup_fd(previous_wakeup)
            _wakeup_read = None
            os.close(read_end)
            os.close(write_end)


def session_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """The environment of a session: the caller's, without its config dir, with the host-settings switch."""
    env = {key: value for key, value in environ.items() if key != "CLAUDE_CONFIG_DIR"}
    env[HOST_SETTINGS_SWITCH] = "required"
    return env


def _group_alive(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _kill_group(pid: int, signum: int) -> None:
    try:
        os.killpg(pid, signum)
    except ProcessLookupError:
        pass


def _signal_overrun(process: subprocess.Popen) -> None:
    """Signal a session past its wall bound: TERM to its group, the grace, then KILL to the group."""
    pid = process.pid
    _kill_group(pid, signal.SIGTERM)
    grace_end = time.monotonic() + GRACE_SECONDS
    while process.poll() is None and time.monotonic() < grace_end:
        time.sleep(0.05)
    while _group_alive(pid) and time.monotonic() < grace_end:
        time.sleep(0.05)
    _kill_group(pid, signal.SIGKILL)  # a member that outlived the launcher and the grace


def _collect(process: subprocess.Popen) -> tuple[bytes, bytes]:
    """What an ended session printed, the drain bounded by `DRAIN_SECONDS`."""
    try:
        return process.communicate(timeout=DRAIN_SECONDS)
    except subprocess.TimeoutExpired as late:  # a descendant outside the group holds a pipe
        stdout, stderr = late.output or b"", late.stderr or b""
        process.stdout.close(), process.stderr.close(), process.wait()
        return stdout, stderr


def _end_overrun(process: subprocess.Popen) -> tuple[bytes, bytes]:
    """End a session past its wall bound: TERM to its group, the grace, then KILL to the group."""
    pid = process.pid
    _kill_group(pid, signal.SIGTERM)
    grace_end = time.monotonic() + GRACE_SECONDS
    try:
        stdout, stderr = process.communicate(timeout=max(0.0, grace_end - time.monotonic()))
    except subprocess.TimeoutExpired:  # the launcher ignores TERM, or a member holds a pipe
        _kill_group(pid, signal.SIGKILL)
        return _collect(process)
    while _group_alive(pid) and time.monotonic() < grace_end:
        time.sleep(0.05)
    _kill_group(pid, signal.SIGKILL)  # a member that outlived the launcher and the grace
    return stdout, stderr


def launch(argv: Sequence[str], cwd: str, prompt: str, *,
           on_start: Callable[[int], None], timeout: float | None = None,
           env: Mapping[str, str] | None = None,
           stop: Callable[[], bool] | None = None) -> Launched:
    """Run one session to its end; `on_start(pid)` is called once, before the prompt is written.

    With a `timeout` the session is ended at `started + timeout` (see the module docstring)
    and the result has `timed_out` set.
    A `stop` that is true before the launcher starts, or turns true while it runs or by the time
    it ended, raises `Stopped` (after the group is killed, once it started).
    """
    started = time.monotonic()
    deferred: list[int] = []
    try:  # before the spawn: the session's own group exists from the spawn on
        previous = signal.signal(signal.SIGTERM, lambda signum, frame: deferred.append(signum))
    except ValueError:  # not the main thread: no handler can be installed
        previous = None
    process = None
    timed_out = False
    try:
        # The registry stays locked from the check to the registration, so a close of the registry
        # either comes first (nothing starts) or finds this session registered and kills it.
        with _registry:
            if _is_closed():
                return Launched(NOT_STARTED, b"", b"the engine is ending\n",
                                time.monotonic() - started)
            if stop is not None and stop():
                raise engine_stop.Stopped
            try:
                process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           start_new_session=True,
                                           env=session_environment(os.environ if env is None else env))
            except OSError as error:
                if deferred:  # no group to end, but the engine was told to stop
                    raise SystemExit(128 + deferred[0])
                return Launched(NOT_STARTED, b"", f"{error}\n".encode("utf-8", "replace"),
                                time.monotonic() - started)
            _live.add(process.pid)
        if previous is not None:  # the deferred signals end here: from now on the group is owned
            signal.signal(signal.SIGTERM, _terminate)
            if deferred:
                raise SystemExit(128 + deferred[0])
        guard = None if timeout is None else Watchdog(
            started + timeout - time.monotonic(), lambda: _signal_overrun(process)).start()
        try:
            on_start(process.pid)
        finally:  # the deadline is armed before `on_start` runs and is waited out here
            overran = guard is not None and guard.stop()
        if overran:
            timed_out = True
            stdout, stderr = _collect(process)
        else:
            remaining = None if timeout is None else started + timeout - time.monotonic()
            try:
                if remaining is not None and remaining <= 0:
                    raise subprocess.TimeoutExpired(list(argv), 0)
                stdout, stderr = engine_stop.communicate(
                    process, prompt.encode("utf-8"), stop=stop, timeout=remaining,
                    drain=DRAIN_SECONDS)
            except subprocess.TimeoutExpired:
                timed_out = True
                stdout, stderr = _end_overrun(process)
    except BaseException:
        if process is not None:
            engine_stop.end_group(process)
        raise
    finally:
        if process is not None:
            with _registry:
                _live.discard(process.pid)
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)
    return Launched(process.returncode, stdout, stderr, time.monotonic() - started, timed_out)
