"""The terms of the procedure format that the engine and the check share.

The format's contract stays `procedure_check`'s docstring; this module holds only the names,
patterns and declaration loader both sides read, so the engine takes them without importing the
validator.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal

FORMAT = 1
STAGES = ("setup", "planning", "plan review", "building", "final review",
          "verifying", "awaiting look", "landing", "closing out", "done")
NEEDS = ("owner-decision", "owner-look", "retry", "nothing")
ROLES = ("planner", "implementer", "reviewer", "reviewer-lite")
WHOLE_SHELL_ROLES = ("implementer",)
WAITS = ("usage-limit", "host-slot", "lock", "checks")
EXHAUSTED = "exhausted"
OUT_OF_BOUNDS = "out-of-bounds"
REFUSAL_MEMBERS = ("reason", "verdict")  # all a refused command step stores (`engine_commands._refused`)
NO_REPLY = "no-reply"
CLAIM_LOST = "claim-lost"
QUOTA_WAIT = "quota-wait"
TOOL_DENIED = "tool-denied"
TOOL_DENIED_NEED = "owner-decision"
ENGINE_STOPS = (QUOTA_WAIT, TOOL_DENIED)
SUPERSEDED = "superseded"

NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
INPUT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")
DEFAULT_VERDICTS = ("ok", "failed")


class DeclarationError(Exception):
    """`command_verdicts.json` is not a valid declaration file."""


@dataclass(frozen=True)
class CommandDeclaration:
    """The two declared forms: `verdicts` (no subcommands) or `subcommands`."""

    verdicts: tuple[str, ...] | None
    subcommands: Mapping[str, tuple[str, ...]]

    def outcomes(self, subcommand: str | None) -> tuple[str, ...] | None:
        if self.verdicts is not None:
            return (self.verdicts or DEFAULT_VERDICTS) if subcommand is None else None
        if subcommand in self.subcommands:
            return self.subcommands[subcommand] or DEFAULT_VERDICTS
        return None


def _strict_load(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"),
                          object_pairs_hook=reject_duplicate_keys,
                          parse_constant=reject_nonfinite_literal)
    except RecursionError as error:
        raise ValueError("the document is nested too deeply") from error


def _verdict_list(value: object, where: str) -> tuple[str, ...]:
    if (not isinstance(value, list) or not all(isinstance(item, str) and item for item in value)
            or len(set(value)) != len(value)):
        raise DeclarationError(f"{where}: verdicts are distinct non-empty strings")
    for reserved in (EXHAUSTED, OUT_OF_BOUNDS):
        if reserved in value:
            raise DeclarationError(f"{where}: {reserved!r} is reserved, not a verdict")
    return tuple(value)


def _declaration(key: str, value: object) -> CommandDeclaration | None:
    if value is None:
        return None
    if isinstance(value, dict) and list(value) == ["verdicts"]:
        return CommandDeclaration(_verdict_list(value["verdicts"], key), {})
    if isinstance(value, dict) and list(value) == ["subcommands"]:
        listed = value["subcommands"]
        if not isinstance(listed, dict) or not listed:
            raise DeclarationError(f"{key}: subcommands is a non-empty object")
        for subcommand in listed:
            if not NAME_RE.fullmatch(subcommand):
                raise DeclarationError(f"{key}: subcommand {subcommand!r} is not a name")
        return CommandDeclaration(None, {
            subcommand: _verdict_list(verdicts, f"{key} {subcommand}")
            for subcommand, verdicts in listed.items()})
    raise DeclarationError(f"{key}: null, {{\"verdicts\": [...]}} or {{\"subcommands\": {{...}}}} only")


def load_commands(path: Path | None = None) -> dict[str, CommandDeclaration | None]:
    path = path or Path(__file__).with_name("command_verdicts.json")
    try:
        document = _strict_load(path)
    except (OSError, ValueError) as error:
        raise DeclarationError(f"{path.name} is unreadable: {error}") from error
    if not isinstance(document, dict):
        raise DeclarationError(f"{path.name} is not an object")
    commands: dict[str, CommandDeclaration | None] = {}
    for key, value in document.items():
        if not NAME_RE.fullmatch(key):
            raise DeclarationError(f"{key!r} is not a command id")
        commands[key] = _declaration(key, value)
    return commands


def readable_format(value: object) -> bool:
    """Whether `value` is the one procedure format this engine reads."""
    return isinstance(value, int) and not isinstance(value, bool) and value == FORMAT


def _inside(directory: Path, name: str) -> Path | None:
    """The named file when it is a file that resolves inside `directory`."""
    path = directory / name
    if not path.is_file():
        return None
    try:
        path.resolve().relative_to(directory.resolve())
    except ValueError:
        return None
    return path
