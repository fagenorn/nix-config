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
propagates. A timed run (`timeout` given) has its own session and captured stderr, kills the group at
the timeout and bounds the drain by `DRAIN_SECONDS`; the timeout counts from the spawn, `on_start`
included, and a SIGTERM to the engine ends the group too. `Ran.timed_out` says the timeout fired.
`Ran.stdout`/`stderr` are what it printed (stderr is empty untimed).

The platform command table holds each platform id's wall bound (`PLATFORM_WALL_SECONDS`) and the one
bound of every project command (`PROJECT_WALL_SECONDS`); the engine times every step run by it and
captures its stderr. The module runs processes, so the pure engine core never imports it.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.delivery import procedure_check
from agent_tools.delivery.procedure_check import CommandDeclaration
from agent_tools.system.siblings import sibling_argv

PLATFORM_MODULES: Mapping[str, str] = MappingProxyType({
    "diff-scope": "delivery.diff_scope",
    "forge-claim": "claims.forge_claim",
})
PLATFORM_WALL_SECONDS: Mapping[str, float] = MappingProxyType({
    "diff-scope": 300,
    "forge-claim": 1200,
})
PROJECT_WALL_SECONDS = 3600
PROJECT_DECLARATION = CommandDeclaration((), {})
NOT_STARTED = 127
TIMED_OUT = "timeout"
DRAIN_SECONDS = 5


class UnknownCommand(LookupError):
    """A command id (or a subcommand of a project id) that neither table holds."""


def argument(value: object) -> str:
    """A step argument as one argv word: text as is, an integer as digits, else compact JSON."""
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


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

    def wall_seconds(self, command: str) -> float:
        """The wall bound of a command step: its platform row, else the project bound."""
        if command in self.platform:
            return PLATFORM_WALL_SECONDS[command]
        if command in self.project:
            return PROJECT_WALL_SECONDS
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
    exit_code: int
    wall_seconds: float
    stdout: bytes = b""
    stderr: bytes = b""
    timed_out: bool = False


def _terminate(signum: int, frame: object) -> None:
    raise SystemExit(128 + signum)


def run(table: CommandTable, command: str, subcommand: str | None,
        args: Sequence[tuple[str, object]], *, on_start: Callable[[int], None],
        timeout: float | None = None) -> Ran:
    """Run one command step to its end; `on_start(pid)` is called once, before waiting."""
    invocation = table.invocation(command, subcommand, args)
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            invocation.argv, cwd=invocation.cwd, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE if timeout is not None else None,
            start_new_session=timeout is not None)
    except OSError:
        return Ran("failed", {}, NOT_STARTED, time.monotonic() - started)
    previous = None
    if timeout is not None:
        try:
            previous = signal.signal(signal.SIGTERM, _terminate)
        except ValueError:  # not the main thread: no handler can be installed
            pass
    try:
        return _wait(process, on_start, started, timeout)
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


def _kill(process: subprocess.Popen, timeout: float | None) -> None:
    """End the command: its own group when it has one, else the leader alone."""
    try:
        if timeout is not None:
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass


def _wait(process: subprocess.Popen, on_start: Callable[[int], None], started: float,
          timeout: float | None) -> Ran:
    try:
        on_start(process.pid)
    except BaseException:
        _kill(process, timeout)
        process.communicate()
        raise
    try:
        if timeout is None:
            stdout, stderr = process.communicate()
        else:
            remaining = started + timeout - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, timeout)
            stdout, stderr = process.communicate(timeout=remaining)
    except subprocess.TimeoutExpired:
        _kill(process, timeout)
        try:
            stdout, stderr = process.communicate(timeout=DRAIN_SECONDS)
        except subprocess.TimeoutExpired as late:  # a descendant outside the group holds a pipe
            stdout, stderr = late.output or b"", late.stderr or b""
            process.stdout.close(), process.stderr.close(), process.wait()
        return Ran(TIMED_OUT, {}, process.returncode, time.monotonic() - started, stdout, stderr,
                   timed_out=True)
    except BaseException:  # an interrupt must not leave a timed run's group alive
        if timeout is not None:
            _kill(process, timeout)
            process.wait()
        raise
    outcome, result = grade(stdout, process.returncode)
    return Ran(outcome, result, process.returncode, time.monotonic() - started,
               stdout, stderr or b"")
