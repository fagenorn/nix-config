"""Finding, running and grading one command step of an engine procedure (#1512).

A `command` step names an id. The id is looked up in the platform table first
(`PLATFORM_MODULES`), then in the project's commands from the resolved snapshot;
an id in both resolves to the platform form, and an id in neither is an
`UnknownCommand` that starts no process.

Two argv forms exist. A platform id runs as its packaged sibling module
(`siblings.sibling_argv`, agent-helpers rule 3), never by name on `PATH`, in the
snapshot's project root, with its subcommand then its arguments. A project id
runs its snapshot argv followed by its arguments, in the entry's own cwd, and
takes no subcommand.

`PLATFORM_MODULES` mirrors the `lib/agent-tools.nix` rows of the commands that
have a declaration in `command_verdicts.json`; tests/test_engine_commands.py
pins the mirror to those rows, so a drift fails there and not at run time.

Grading: stdout is parsed strictly as one JSON document. The outcome is its
`verdict` when that is a non-empty string, else `ok` for exit 0 and `failed` for
any other exit. A document that is not an object is no result (`{}`).

A command that cannot start (an `OSError` from the spawn) is `failed` with exit
127 and no pid: `on_start` is not called, because there is no process.

The module runs processes, so the pure engine core never imports it.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.delivery.procedure_check import CommandDeclaration, load_commands
from agent_tools.system.siblings import sibling_argv

PLATFORM_MODULES: Mapping[str, str] = MappingProxyType({
    "diff-scope": "delivery.diff_scope",
    "forge-claim": "claims.forge_claim",
})
PROJECT_DECLARATION = CommandDeclaration((), {})
NOT_STARTED = 127


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
        load_commands()  # a DeclarationError propagates
        return cls(PLATFORM_MODULES, snapshot["bindings"]["commands"],
                   snapshot["project"]["root"])

    def declarations(self) -> dict[str, CommandDeclaration | None]:
        """Every runnable id's declaration; the platform's win over a project's."""
        declared: dict[str, CommandDeclaration | None] = {
            name: PROJECT_DECLARATION for name in self.project}
        declared.update(load_commands())
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
    result: dict = {}
    try:
        document = json.loads(stdout.decode("utf-8"),
                              object_pairs_hook=reject_duplicate_keys,
                              parse_constant=reject_nonfinite_literal)
    except (ValueError, RecursionError):
        document = None
    if isinstance(document, dict):
        result = document
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


def run(table: CommandTable, command: str, subcommand: str | None,
        args: Sequence[tuple[str, object]], *, on_start: Callable[[int], None]) -> Ran:
    """Run one command step to its end; `on_start(pid)` is called once, before waiting."""
    invocation = table.invocation(command, subcommand, args)
    started = time.monotonic()
    try:
        process = subprocess.Popen(invocation.argv, cwd=invocation.cwd,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
    except OSError:
        return Ran("failed", {}, NOT_STARTED, time.monotonic() - started)
    on_start(process.pid)
    stdout, _ = process.communicate()
    outcome, result = grade(stdout, process.returncode)
    return Ran(outcome, result, process.returncode, time.monotonic() - started)
