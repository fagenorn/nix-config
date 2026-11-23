"""Finding, running and grading one command step of an engine procedure (#1512).

A `command` step names an id, looked up in the platform table (`PLATFORM_MODULES`) first, then in the
snapshot's project commands; an id in neither is an `UnknownCommand` that starts no process. A
platform id runs as its packaged sibling module (`siblings.sibling_argv`, agent-helpers rule 3) in
the snapshot's project root, with its subcommand then its arguments, each as the flag its member
names (`run.repo_root` is `--repo-root`) except an id in `POSITIONAL`, whose arguments are bare
words; a project id runs its snapshot argv then its arguments, in the entry's own cwd, with no
subcommand. `PLATFORM_MODULES` mirrors the `lib/agent-tools.nix` rows of the commands that have a declaration in `command_verdicts.json`;
tests/test_engine_commands.py pins the mirror.

Grading: stdout is parsed strictly as one JSON document; the outcome is its `verdict` when that is a
non-empty string, else `ok` for exit 0 and `failed` otherwise. A document that is not an object is no
result (`{}`).

A command that cannot start (an `OSError` from the spawn) is `failed` with exit 127 and no pid, and
`on_start` is not called. When `on_start` raises, the process is killed and reaped before the error
propagates. Every run is the leader of its own process group, and any exception while it waits (a
SIGTERM to the engine, raised as `SystemExit`, and a failing `on_start` included) kills that group
and closes its pipes without waiting for EOF. A timed run (`timeout` given) also has captured
stderr, kills the group at the timeout and bounds the drain by `DRAIN_SECONDS`; the timeout counts
from the spawn, `on_start` included. The deadline is armed (a `Watchdog` thread) before `on_start`
runs, so a stalled `on_start` cannot keep the group past its bound; the SIGTERM handler is
installed before the spawn, timed or not, and defers a signal until the group is owned, so a
SIGTERM in the spawn interval still ends the group, and the previous handler returns with the run.
`Ran.timed_out` says the timeout fired. A run given `stop` raises `Stopped` when it is true before
the process starts, polls it while the process runs (`engine_stop.communicate`) and raises
`Stopped` once it is true, also when the process has already ended. `Ran.stdout`/`stderr` are what
it printed (stderr is empty untimed).

Four lifecycle ids (`LIFECYCLE_ARGV`) are rows of fixed words with numbered slots: a procedure supplies only
slot values, each one argv word, so the spelling is always the one the guard accepts; the guard judges them
like any command.

The platform command table holds each platform id's wall bound (`PLATFORM_WALL_SECONDS`) and the one
bound of every project command (`PROJECT_WALL_SECONDS`); the engine times every step run by it and
captures its stderr. The module runs processes, so the pure engine core never imports it.

Every command passes the lifecycle guard first, in the guard's accepted spelling (`command_text`),
and runs marked as an agent session so the pre-push hook judges a push it makes (issue 1515). A
refusal, a timeout or an unusable guard is the outcome `refused`, with the guard's reason as the
result and no process. A run given `stop` polls it while the guard runs and checks it before a
refusal is returned: a stop raises `Stopped` there, the guard reaped, and no refusal is graded.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
import threading
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
    "independent-review": "delivery.independent_review",
    "issue-setup": "delivery.issue_setup",
    "look-approval": "delivery.look_approval",
    "resolve-project": "project_contract.resolve_project",
    "verified-tree": "verification.verified_tree",
})
LIFECYCLE_ARGV: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "git-push": ("git", "-C", "{0}", "push", "origin", "{1}"),
    "pr-create": ("gh", "pr", "create", "--repo", "{0}", "--base", "{1}", "--head", "{2}",
                  "--title", "{3}", "--body", "{4}"),
    "pr-merge": ("gh", "pr", "merge", "{0}", "--repo", "{1}", "--merge", "--match-head-commit",
                 "{2}", "--delete-branch"),
    "branch-delete": ("git", "-C", "{0}", "branch", "-d", "{1}"),
})
LIFECYCLE_WALL_SECONDS = 600
SLOT_RE = re.compile(r"^\{(\d+)\}$")
POSITIONAL: frozenset[str] = frozenset({"diff-scope"})
PLATFORM_WALL_SECONDS: Mapping[str, float] = MappingProxyType({
    "diff-scope": 300,
    "forge-claim": 1200,
    "independent-review": 3600,
    "issue-setup": 1200,
    "look-approval": 300,
    "resolve-project": 300,
    "verified-tree": 14400,
})
PROJECT_WALL_SECONDS = 3600
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
            if command not in POSITIONAL:
                words = tuple(word for path, value in args for word in (
                    "--" + path.split(".", 1)[1].replace("_", "-"), argument(value)))
            return Invocation(
                (*sibling_argv(self.platform[command]),
                 *([subcommand] if subcommand else []), *words),
                self.root)
        if command in LIFECYCLE_ARGV:
            if subcommand is not None:
                raise UnknownCommand(f"{command}: a lifecycle command takes no subcommand")
            return Invocation(tuple(self._slot(command, word, args)
                                    for word in LIFECYCLE_ARGV[command]), self.root)
        if command in self.project and subcommand is None:
            entry = self.project[command]
            return Invocation((*entry["argv"], *words), entry["cwd"])
        if command in self.project:
            raise UnknownCommand(f"{command}: a project command takes no subcommand")
        raise UnknownCommand(f"{command}: not a platform or project command")

    @staticmethod
    def _slot(command: str, word: str, args: Sequence[tuple[str, object]]) -> str:
        slot = SLOT_RE.match(word)
        if slot is None:
            return word
        if int(slot[1]) >= len(args):
            raise UnknownCommand(f"{command}: slot {slot[1]} has no argument")
        return argument(args[int(slot[1])][1])

    def wall_seconds(self, command: str) -> float:
        """The wall bound of a command step: its platform row, the lifecycle bound, else the project's."""
        if command in self.platform:
            return PLATFORM_WALL_SECONDS[command]
        if command in LIFECYCLE_ARGV:
            return LIFECYCLE_WALL_SECONDS
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
    exit_code: int | None
    wall_seconds: float
    stdout: bytes = b""
    stderr: bytes = b""
    timed_out: bool = False


def _terminate(signum: int, frame: object) -> None:
    raise SystemExit(128 + signum)


class Watchdog:
    """Runs `end` once at a deadline from its own thread, so a stall in the caller cannot outlast it."""

    def __init__(self, seconds: float, end: Callable[[], None]) -> None:
        self.fired = False
        self._end = end
        self._timer = threading.Timer(max(0.0, seconds), self._fire)
        self._timer.daemon = True

    def _fire(self) -> None:
        self.fired = True
        self._end()

    def start(self) -> Watchdog:
        self._timer.start()
        return self

    def stop(self) -> bool:
        """Disarm the deadline, waiting for an ending already begun; whether the deadline passed."""
        self._timer.cancel()
        if self._timer.is_alive():
            self._timer.join()
        return self.fired


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
        if stop is not None and stop():
            raise engine_stop.Stopped
        return _refused(f"The command text {text} does not split back to its words.", started)
    verdict = engine_guard.judge(guard, text, invocation.cwd, stop)
    if stop is not None and stop():  # a stop is honored before a refusal is returned
        raise engine_stop.Stopped
    if not verdict.allowed:
        return _refused(verdict.reason or "The lifecycle guard refused.", started)
    started = time.monotonic()  # the wall bound counts from the spawn, not from the guard
    deferred: list[int] = []
    previous = None
    try:  # before the spawn: the group exists from the spawn on
        previous = signal.signal(signal.SIGTERM, lambda signum, frame: deferred.append(signum))
    except ValueError:  # not the main thread: no handler can be installed
        pass
    try:
        try:
            process = subprocess.Popen(
                shlex.split(text), cwd=invocation.cwd, stdin=subprocess.DEVNULL,
                env={**os.environ, SESSION_MARKER: os.environ.get(SESSION_MARKER) or "1"},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE if timeout is not None else None,
                start_new_session=True)
        except OSError:
            if deferred:  # no group to end, but the engine was told to stop
                raise SystemExit(128 + deferred[0])
            return Ran("failed", {}, NOT_STARTED, time.monotonic() - started)
        return _wait(process, on_start, started, timeout, deferred, stop)
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


def _kill(process: subprocess.Popen) -> None:
    """End the command's own process group."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):  # gone, or a leader left unreaped as a zombie (macOS)
        pass


def _wait(process: subprocess.Popen, on_start: Callable[[int], None], started: float,
          timeout: float | None, deferred: list[int], stop: Callable[[], bool] | None) -> Ran:
    guard = None
    try:
        try:  # the deferred signals end here: from now on the group is owned
            signal.signal(signal.SIGTERM, _terminate)
        except ValueError:
            pass
        if deferred:
            raise SystemExit(128 + deferred[0])
        if timeout is not None:
            guard = Watchdog(started + timeout - time.monotonic(),
                             lambda: _kill(process)).start()
        on_start(process.pid)
    except BaseException:
        if guard is not None:
            guard.stop()
        engine_stop.end_group(process)
        raise
    overran = guard is not None and guard.stop()
    try:
        remaining = None if timeout is None else started + timeout - time.monotonic()
        if overran or (remaining is not None and remaining <= 0):
            raise subprocess.TimeoutExpired(process.args, timeout)
        stdout, stderr = engine_stop.communicate(process, None, stop=stop, timeout=remaining)
    except subprocess.TimeoutExpired:
        _kill(process)
        try:
            stdout, stderr = process.communicate(timeout=DRAIN_SECONDS)
        except subprocess.TimeoutExpired as late:  # a descendant outside the group holds a pipe
            stdout, stderr = late.output or b"", late.stderr or b""
            process.stdout.close(), process.stderr.close(), process.wait()
        return Ran(TIMED_OUT, {}, process.returncode, time.monotonic() - started, stdout, stderr,
                   timed_out=True)
    except BaseException:  # an interrupt, a SIGTERM or a stop must not leave the group alive
        engine_stop.end_group(process)
        raise
    outcome, result = grade(stdout, process.returncode)
    return Ran(outcome, result, process.returncode, time.monotonic() - started,
               stdout, stderr or b"")
