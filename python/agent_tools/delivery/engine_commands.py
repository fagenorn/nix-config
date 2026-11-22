"""Finding, running and grading one command step of an engine procedure (#1512).

A `command` step names an id, looked up in the platform table (`PLATFORM_MODULES`) first, then in the
snapshot's project commands; an id in neither is an `UnknownCommand` that starts no process. A
platform id runs as its packaged sibling module (`siblings.sibling_argv`, agent-helpers rule 3) in
the snapshot's project root, with its subcommand then its arguments; a project id runs its snapshot
argv then its arguments, in the entry's own cwd, with no subcommand. `PLATFORM_MODULES` mirrors the
`lib/agent-tools.nix` rows of the commands that have a declaration in `command_verdicts.json`;
tests/test_engine_commands.py pins the mirror.

Grading: stdout is parsed strictly as one JSON document; the outcome is its `verdict` when that is a
non-empty string, else `ok` for exit 0 and `failed` otherwise. A document that is not an object is no
result (`{}`).

A command that cannot start (an `OSError` from the spawn) is `failed` with exit 127 and no pid, and
`on_start` is not called. When `on_start` raises, the process is killed and reaped before the error
propagates. Every run is the leader of its own process group, and any exception while it waits (a
SIGTERM to the engine, raised as `SystemExit`, and a failing `on_start` included) kills that group
and closes its pipes without waiting for EOF. A timed run (`timeout` given) also has captured
stderr, kills the group at the timeout and bounds the drain by `DRAIN_SECONDS`. A run given `stop`
raises `Stopped` when it is true before the process starts, polls it while the process runs
(`engine_stop.communicate`) and raises `Stopped` once it is true, also when the process has
already ended. `Ran.stdout`/`stderr` are what it printed
(stderr is empty untimed). The module runs processes, so the pure engine core never imports it.

Every command passes the lifecycle guard first, in the guard's accepted spelling (`command_text`),
and runs marked as an agent session so the pre-push hook judges a push it makes (issue 1515). A
refusal, a timeout or an unusable guard is the outcome `refused`, with the guard's reason as the
result and no process.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.delivery import engine_guard, engine_stop, procedure_check
from agent_tools.delivery.procedure_check import CommandDeclaration
from agent_tools.system.siblings import sibling_argv

PLATFORM_MODULES: Mapping[str, str] = MappingProxyType({
    "diff-scope": "delivery.diff_scope",
    "forge-claim": "claims.forge_claim",
})
PROJECT_DECLARATION = CommandDeclaration((), {})
NOT_STARTED = 127
TIMED_OUT = "timeout"
DRAIN_SECONDS = 5
TEXT_VALUE_FLAGS = ("--body", "--subject", "--title")
SHELL_ACTIVE = frozenset('"\\$`!')
SESSION_MARKER = "CLAUDECODE"


class UnknownCommand(LookupError):
    """A command id (or a subcommand of a project id) that neither table holds."""


def argument(value: object) -> str:
    """A step argument as one argv word: text as is, an integer as digits, else compact JSON."""
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def command_text(argv: Sequence[str]) -> str:
    """The argv in the guard's accepted spelling, words joined by one space (issue 1515, D6)."""
    def bare_or_double(word: str) -> str:
        if shlex.quote(word) == word:
            return word
        if not SHELL_ACTIVE.intersection(word):
            return f'"{word}"'
        return shlex.quote(word)

    words: list[str] = []
    index = 0
    while index < len(argv):
        word = argv[index]
        words.append(bare_or_double(word))
        if word in TEXT_VALUE_FLAGS and index + 1 < len(argv):
            value = argv[index + 1]
            words.append(shlex.quote(value) if SHELL_ACTIVE.intersection(value)
                         else f'"{value}"')
            index += 1
        index += 1
    return " ".join(words)


@dataclass(frozen=True)
class Invocation:
    argv: tuple[str, ...]
    cwd: str


@dataclass(frozen=True)
class CommandTable:
    platform: Mapping[str, str]
    project: Mapping[str, Mapping]
    root: str

    @classmethod
    def from_snapshot(cls, snapshot: Mapping) -> CommandTable:
        procedure_check.load_commands()  # a DeclarationError propagates
        return cls(PLATFORM_MODULES, snapshot["bindings"]["commands"],
                   snapshot["project"]["root"])

    def declarations(self) -> dict[str, CommandDeclaration | None]:
        """Every runnable id's declaration; `invocation`'s lookup order: the platform table first."""
        declared: dict[str, CommandDeclaration | None] = dict(procedure_check.load_commands())
        for name in self.project:
            if name not in self.platform:
                declared[name] = PROJECT_DECLARATION
        return declared

    def invocation(self, command: str, subcommand: str | None,
                   args: Sequence[tuple[str, object]]) -> Invocation:
        words = tuple(argument(value) for _, value in args)
        if command in self.platform:
            return Invocation(
                (*sibling_argv(self.platform[command]),
                 *([subcommand] if subcommand else []), *words),
                self.root)
        if command in self.project and subcommand is None:
            entry = self.project[command]
            return Invocation((*entry["argv"], *words), entry["cwd"])
        if command in self.project:
            raise UnknownCommand(f"{command}: a project command takes no subcommand")
        raise UnknownCommand(f"{command}: not a platform or project command")


def grade(stdout: bytes, exit_code: int) -> tuple[str, dict]:
    """The outcome and the result object of a finished command."""
    try:
        document = json.loads(stdout.decode("utf-8"),
                              object_pairs_hook=reject_duplicate_keys,
                              parse_constant=reject_nonfinite_literal)
    except (ValueError, RecursionError):
        document = None
    result = document if isinstance(document, dict) else {}
    verdict = result.get("verdict")
    if isinstance(verdict, str) and verdict:
        return verdict, result
    return ("ok" if exit_code == 0 else "failed"), result


@dataclass(frozen=True)
class Ran:
    outcome: str
    result: dict
    exit_code: int | None
    wall_seconds: float
    stdout: bytes = b""
    stderr: bytes = b""


def _refused(reason: str, started: float) -> Ran:
    return Ran("refused", {"reason": reason, "verdict": "refused"}, None,
               time.monotonic() - started)


def run(table: CommandTable, command: str, subcommand: str | None,
        args: Sequence[tuple[str, object]], *, guard: engine_guard.Hook | engine_guard.Unavailable,
        on_start: Callable[[int], None], timeout: float | None = None,
        stop: Callable[[], bool] | None = None) -> Ran:
    """Run one command step to its end once the guard allows it; `on_start(pid)` is called once,
    before waiting."""
    invocation = table.invocation(command, subcommand, args)
    started = time.monotonic()
    text = command_text(invocation.argv)
    if shlex.split(text) != list(invocation.argv):
        return _refused(f"The command text {text} does not split back to its words.", started)
    verdict = engine_guard.judge(guard, text, invocation.cwd)
    if not verdict.allowed:
        return _refused(verdict.reason or "The lifecycle guard refused.", started)
    if stop is not None and stop():
        raise engine_stop.Stopped
    with engine_stop.sigterm_exits():
        try:
            process = subprocess.Popen(
                shlex.split(text), cwd=invocation.cwd, stdin=subprocess.DEVNULL,
                env={**os.environ, SESSION_MARKER: os.environ.get(SESSION_MARKER) or "1"},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE if timeout is not None else None,
                start_new_session=True)
        except OSError:
            return Ran("failed", {}, NOT_STARTED, time.monotonic() - started)
        try:
            on_start(process.pid)
        except BaseException:
            engine_stop.end_group(process)
            raise
        try:
            stdout, stderr = engine_stop.communicate(process, None, stop=stop, timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                stdout, stderr = process.communicate(timeout=DRAIN_SECONDS)
            except subprocess.TimeoutExpired as late:  # a descendant outside the group holds a pipe
                stdout, stderr = late.output or b"", late.stderr or b""
                process.stdout.close(), process.stderr.close(), process.wait()
            return Ran(TIMED_OUT, {}, process.returncode, time.monotonic() - started, stdout,
                       stderr)
        except BaseException:  # an interrupt, a SIGTERM or a stop must not leave the group alive
            engine_stop.end_group(process)
            raise
    outcome, result = grade(stdout, process.returncode)
    return Ran(outcome, result, process.returncode, time.monotonic() - started,
               stdout, stderr or b"")
