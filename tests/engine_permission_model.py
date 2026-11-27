"""A model of the client's Bash permission rules, for the engine's launch tests; CI runs no client.

Not a test module. It models what https://code.claude.com/docs/en/permissions says, sentence by sentence:
a compound command is split at `&&`, `||`, `;`, `|&`, `|`, `&` and a newline and every part must be allowed;
a deny rule applies when any part matches it and outranks an allow rule from any source; the wrappers `time`,
`nohup`, `nice`, `command`, `builtin`, `noglob`, `timeout`, `stdbuf` and a bare `xargs` are stripped before a
rule is matched; an allow rule never matches past an assignment, a deny rule does; `*` matches any run of
characters and `:*` is the legacy prefix form. A command substitution that is active (outside quotes or inside
double quotes) or a process substitution makes the command unparseable, so no allow rule admits it.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOST_SETTINGS = REPO_ROOT / "home/common/claude-code/default.nix"

_SEPARATORS = ("&&", "||", "|&", ";", "|", "&", "\n")
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_PLAIN_WRAPPERS = ("time", "nohup", "nice", "builtin", "noglob")


def rule_matches(pattern: str, command: str) -> bool:
    if pattern.endswith(":*"):  # the legacy prefix form: the prefix alone or followed by a space and anything
        prefix = pattern[:-2]
        return command == prefix or command.startswith(prefix + " ")
    return re.fullmatch(".*".join(re.escape(part) for part in pattern.split("*")), command) is not None


def subcommands(command: str) -> list[str] | None:
    """The parts of `command` the client checks one by one, or None when it cannot be split."""
    parts: list[tuple[str, str]] = []  # (text, the separator that ended it)
    current: list[str] = []
    quote = ""
    i = 0
    while i < len(command):
        char = command[i]
        if quote == "'":
            quote = "" if char == "'" else quote
        elif char == "\\" and i + 1 < len(command):
            current.append(char)
            i += 1
            char = command[i]
        elif char == "`" or command.startswith("$(", i):
            return None
        elif quote == '"':
            quote = "" if char == '"' else quote
        elif char in "'\"":
            quote = char
        elif command[i:i + 2] in ("<(", ">("):
            return None
        else:
            separator = next((s for s in _SEPARATORS if command.startswith(s, i)), "")
            if separator:
                parts.append(("".join(current).strip(), separator))
                current = []
                i += len(separator)
                continue
        current.append(char)
        i += 1
    if quote:
        return None
    parts.append(("".join(current).strip(), ""))
    if not parts[-1][0] and len(parts) > 1 and parts[-2][1] in (";", "&"):
        parts.pop()
    if any(not text for text, _ in parts):
        return None
    return [text for text, _ in parts]


def _after_words(part: str, count: int) -> str:
    pieces = part.split(None, count)
    return pieces[count] if len(pieces) > count else ""


def _strip_wrappers(part: str) -> str:
    """`part` without the leading wrappers the client strips before it matches a rule."""
    while True:
        words = part.split()
        if not words:
            return part
        first = words[0]
        if first in _PLAIN_WRAPPERS or (first == "command" and words[1:2] not in (["-v"], [])):
            part = _after_words(part, 1)
        elif first == "timeout" and len(words) > 2:
            part = _after_words(part, 2)
        elif first == "stdbuf" and len(words) > 1:
            count = 1
            while count < len(words) - 1 and words[count].startswith("-"):
                count += 1
            part = _after_words(part, count)
        elif first == "xargs" and len(words) > 1 and not words[1].startswith("-"):
            part = _after_words(part, 1)
        else:
            return part


def _without_assignments(part: str) -> str:
    while part and _ASSIGNMENT.match(part.split()[0]):
        words = part.split(None, 1)
        part = _strip_wrappers(words[1] if len(words) > 1 else "")
    return part


def client_admits(command: str, allowed: list[str], denied: list[str]) -> bool:
    """Whether the client runs `command` under these `--allowedTools`/`--disallowedTools` words."""
    def bash_rules(rules: list[str]) -> list[str]:
        return [rule[len("Bash("):-1] for rule in rules if rule.startswith("Bash(") and rule.endswith(")")]

    parts = subcommands(command)
    if parts is None:
        return False
    stripped = [_strip_wrappers(part) for part in parts]
    for part in stripped:
        for view in (part, _without_assignments(part)):
            if any(rule_matches(pattern, view) for pattern in bash_rules(denied)):
                return False
    return all("Bash" in allowed
               or (not _ASSIGNMENT.match(part.split()[0] if part.split() else "")
                   and any(rule_matches(pattern, part) for pattern in bash_rules(allowed)))
               for part in stripped)


def host_allowed(nix_text: str) -> list[str]:
    """The strings of the first `allow = [ ... ];` list after `permissions = {`, in order."""
    start = nix_text.index("permissions = {")
    block = nix_text[nix_text.index("allow = [", start) + len("allow = ["):]
    return re.findall(r'"([^"]*)"', block[:block.index("];")])
