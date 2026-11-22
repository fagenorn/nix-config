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

This module starts no process and imports no `engine_core`.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

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


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _amount(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def read_result(stdout: bytes) -> Reading:
    """The reply, prose, denials and measurements of a session's stdout."""
    try:
        document = json.loads(stdout.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                              parse_constant=reject_nonfinite_literal)
    except (UnicodeDecodeError, ValueError):
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
        spend_usd=_amount(document.get("total_cost_usd")) or 0)
