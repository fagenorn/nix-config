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
never is, and every measurement that is absent or invalid reads as zero.

`launch_argv` builds the one launch form: the account launcher's print mode
(`claude-account run -p`) with the role handed over by flags (`--model`,
`--effort`, `--tools` with `--allowedTools`, or `--disallowedTools`, and the
role body as `--append-system-prompt-file`), the reply schema as
`--json-schema`, the session id first fixed by the engine, and the permission
mode `dontAsk`, so a tool the role does not allow is denied rather than asked
about. The engine never passes `--agent`, `--bare`, `--setting-sources`,
`--dangerously-skip-permissions` or `bypassPermissions`: `--bare` would skip the
hooks that guard the session, and the others would hand the session its own
settings or its permissions. The prompt is never in the argv: the tool options
are variadic and would swallow a positional prompt, so `launch` writes it on
stdin.

A session that gave no usable structured answer is asked once more on the same
session: with `resume=True` the argv is the same except `--session-id <id>`
becomes `--resume <id>`, and `--fork-session` is never passed, so the id is kept.
The prompt of that second launch is `REASK_PROMPT`. A miss is a reading with no
reply that conforms to the schema (`engine_reply.reply_problem`) whose stdout is
a JSON object of `type` `result` with a `subtype` in `MISS_SUBTYPES`: `success`
(the model answered in prose or its answer broke the schema) with `is_error` not set, or the
client's own `error_max_structured_output_retries`, flagged or not (`is_miss`). Any other
reading without a usable reply, a `success` flagging `is_error` included, is not a miss and is
never resumed.

The role's `Bash` stays in `--tools` but is preapproved only as the reviewer's
permitted read-only git inspection (`READ_ONLY_BASH`): under `dontAsk` any other
shell command is denied, so a session cannot write to the worktree through it.
`git diff`, `git log` and `git show` write a file given `--output`, which those
prefix patterns would preapprove, so `GIT_WRITING` is passed as
`--disallowedTools` (a deny rule is checked before an allow rule). A role that
needs another shell command lists it in its own `tools` as `Bash(<prefix>:*)`;
one that is denied a shell command anyway is a fault (`engine_shell`), never a
graded reply.

`launch` starts the argv as its own process group (`start_new_session`) because
the account launcher waits on its Claude child instead of replacing itself, so
a session is a process tree and ending it means killing the group, which a
SIGTERM to the engine (turned into `SystemExit` while the session runs) and any
other exception both do. A launcher that cannot start gives exit 127 and the
`OSError` text as its stderr. Its stderr is
captured so the launcher's own error is never a second line on the engine's
stderr; `diagnostic` gives the last line of it for the engine's one fault line.

A session is launched without `CLAUDE_CONFIG_DIR` and with
`CLAUDE_ACCOUNT_HOST_SETTINGS=required`, so the account launcher starts the client
only on `$HOME/.claude/settings.json`, the file `engine deliver` checked before the run.

This module imports no `engine_core`.
"""

from __future__ import annotations

import json
import math
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.delivery.engine_commands import argument
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
NOT_STARTED = 127
STRUCTURED_OUTPUT_EXHAUSTED = "error_max_structured_output_retries"
MISS_SUBTYPES: tuple[str, ...] = ("success", STRUCTURED_OUTPUT_EXHAUSTED)
REASK_PROMPT = (
    "Your last answer was not a valid structured answer. Reply again with only the structured "
    "answer, a single call of the StructuredOutput tool whose members follow the schema, and no "
    "other text.")
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


def read_result(stdout: bytes) -> Reading:
    """The reply, prose, denials and measurements of a session's stdout."""
    try:
        document = json.loads(stdout.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                              parse_constant=reject_nonfinite_literal, parse_float=_number)
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
        is_error=document.get("is_error") is True)


def is_miss(reading: Reading) -> bool:
    """True when a reading with no usable reply is one the session is asked again about.

    A result whose subtype is in `MISS_SUBTYPES`; but a `success` that flags `is_error` is a client
    error, not an answer that missed, and is no miss. Only the client's own structured-output
    exhaustion is a miss whatever it flags.
    """
    if not reading.is_result or reading.subtype not in MISS_SUBTYPES:
        return False
    return not reading.is_error or reading.subtype == STRUCTURED_OUTPUT_EXHAUSTED



def launch_argv(role: Role, schema: Mapping, session: str, system_prompt: Path, *,
                resume: bool = False) -> tuple[str, ...]:
    """The launcher argv of one session; no word of it is a prompt.

    With `resume` the session is the one already started: `--resume` replaces `--session-id`.
    """
    refuse_value(role.name, "model", role.model)
    refuse_value(role.name, "effort", role.effort)
    for field, names in (("tools", role.tools), ("disallowedTools", role.disallowed)):
        for name in names or ():
            refuse_value(role.name, field, name)
    argv = [*LAUNCHER, "-p", "--output-format", "json",
            "--json-schema", json.dumps(schema, sort_keys=True, separators=(",", ":")),
            "--resume" if resume else "--session-id", session, "--strict-mcp-config",
            "--permission-mode", "dontAsk",
            "--model", role.model, "--effort", role.effort]
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


def diagnostic(stderr: bytes) -> str:
    """The last non-blank line of `stderr`, spaces collapsed, cut to 300 characters."""
    lines = [line for line in stderr.decode("utf-8", errors="replace").splitlines()
             if line.strip()]
    return " ".join(lines[-1].split())[:DIAGNOSTIC_CHARS] if lines else ""


def _terminate(signum: int, frame: object) -> None:
    raise SystemExit(128 + signum)


def session_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """The environment of a session: the caller's, without its config dir, with the host-settings switch."""
    env = {key: value for key, value in environ.items() if key != "CLAUDE_CONFIG_DIR"}
    env[HOST_SETTINGS_SWITCH] = "required"
    return env


def launch(argv: Sequence[str], cwd: str, prompt: str, *,
           on_start: Callable[[int], None]) -> Launched:
    """Run one session to its end; `on_start(pid)` is called once, before the prompt is written."""
    started = time.monotonic()
    try:
        previous = signal.signal(signal.SIGTERM, _terminate)
    except ValueError:  # not the main thread: no handler can be installed
        previous = None
    process = None
    try:
        try:
            process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       start_new_session=True,
                                       env=session_environment(os.environ))
        except OSError as error:
            return Launched(NOT_STARTED, b"", f"{error}\n".encode("utf-8", "replace"),
                            time.monotonic() - started)
        on_start(process.pid)
        stdout, stderr = process.communicate(prompt.encode("utf-8"))
    except BaseException:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
        raise
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)
    return Launched(process.returncode, stdout, stderr, time.monotonic() - started)
