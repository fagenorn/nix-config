"""The read-only PreToolUse hook of a project question session (#1176).

Why. The console answers an owner's question about a registered project with a Claude Code client
run in that project's folder. The session only reads: this hook is the one place that decides, for
every tool call, whether the call is a read. It is a packaged sibling run by the console's own
interpreter as `python -m agent_tools.console.project_question_hook '<allowed json>'`; it has no
command-table row (ADR-console-057) and imports only the standard library.

Input. `argv[1]` is the allowed commands: a JSON list of non-empty lists of non-empty strings, each
one declared read-only command's argv (`parse_allowed`, `ValueError` otherwise). Stdin is the
client's hook document, a JSON object with `tool_name` and `tool_input`.

Decision. `decide(document, allowed)` returns `("allow", ALLOWED)` or `("deny", <sentence>)`, in
this order:

1. A document that is not an object, or whose `tool_name` is not a non-empty string: `MALFORMED`.
2. `Read`, `Grep` and `Glob` (`READ_TOOLS`): allowed.
3. `Edit`, `Write` and `NotebookEdit` (`WRITE_TOOLS`): `WRITE_DENIED`.
4. Any other tool but `Bash` (MCP tools, `Task`, `Agent` and `WebFetch` included): `TOOL_DENIED`.
5. A `Bash` call whose `tool_input` is not an object or whose `command` is not a string: `MALFORMED`.
6. A `Bash` command in which a lifecycle verb (`LIFECYCLE_VERBS`: `git push`, `gh pr create`,
   `gh pr merge`, `git branch -d`, `gh release create`) is a contiguous run of the words of
   `command.split()` (any whitespace): `LIFECYCLE_DENIED`, whatever `allowed` holds.
7. Otherwise the separators are checked before any split: the command is allowed only when
   `PLAIN_COMMAND` matches all of it (plain words separated by U+0020 only) and its words equal one
   member of `allowed`. Anything else is `NO_COMMANDS` when `allowed` is empty and
   `COMMAND_DENIED` otherwise. `PLAIN_COMMAND` excludes every shell metacharacter and every
   whitespace but U+0020, so no composed command is admitted: `just\\nbuild` is two commands to a
   shell, and a bare `just` runs the project's default recipe.

Output. Stdout is exactly one line, `json.dumps(output(decision, reason))`, the client's PreToolUse
wire format. A missing or unparseable argument, or unreadable stdin, prints the `MALFORMED` deny.
The exit status is 0 in every case. A hook process that gives no decision (a timeout, an
interpreter that fails to start) is turned into a deny by `"onFailure": "block"` in the session's
settings, not by this module.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from collections.abc import Sequence

READ_TOOLS: tuple[str, ...] = ("Read", "Grep", "Glob")
WRITE_TOOLS: tuple[str, ...] = ("Edit", "Write", "NotebookEdit")
LIFECYCLE_VERBS: tuple[tuple[str, ...], ...] = (
    ("git", "push"),
    ("gh", "pr", "create"),
    ("gh", "pr", "merge"),
    ("git", "branch", "-d"),
    ("gh", "release", "create"),
)
PLAIN_WORD = re.compile(r"[A-Za-z0-9_./:@%+=,-]+")
PLAIN_COMMAND = re.compile(r" *[A-Za-z0-9_./:@%+=,-]+(?: +[A-Za-z0-9_./:@%+=,-]+)* *")

ALLOWED = "a read-only step of a question session"
WRITE_DENIED = (
    "This session only reads, so {tool} is not allowed: answer from what you can read and name "
    "any change as a suggestion."
)
LIFECYCLE_DENIED = (
    "This session never pushes, opens or merges a pull request, deletes a branch or creates a "
    "release."
)
COMMAND_DENIED = (
    "This session runs only the project's declared read-only commands, each exactly as declared "
    "and alone, with no pipe, redirect, ;, &&, subshell or substitution: {commands}."
)
NO_COMMANDS = (
    "This project declares no read-only command, so no shell command can run in this session: "
    "answer from the code and docs."
)
TOOL_DENIED = (
    "This session can use only Read, Grep and Glob, and Bash for a declared read-only command, "
    "so {tool} is not allowed."
)
MALFORMED = "The question session's hook could not read this tool call, so it was refused."


def parse_allowed(text: str) -> tuple[tuple[str, ...], ...]:
    """The allowed argv list from its JSON text; `ValueError` unless a list of non-empty word lists."""
    value = json.loads(text)
    if not isinstance(value, list):
        raise ValueError("the allowed commands are not a list")
    parsed = []
    for argv in value:
        if not isinstance(argv, list) or not argv:
            raise ValueError("a command is not a non-empty list")
        if not all(isinstance(word, str) and word for word in argv):
            raise ValueError("a command word is not a non-empty string")
        parsed.append(tuple(argv))
    return tuple(parsed)


def _has_lifecycle_verb(words: list[str]) -> bool:
    for verb in LIFECYCLE_VERBS:
        size = len(verb)
        for start in range(len(words) - size + 1):
            if tuple(words[start : start + size]) == verb:
                return True
    return False


def _decide_bash(command: str, allowed: Sequence[Sequence[str]]) -> tuple[str, str]:
    if _has_lifecycle_verb(command.split()):
        return "deny", LIFECYCLE_DENIED
    if PLAIN_COMMAND.fullmatch(command):
        words = tuple(word for word in command.split(" ") if word)
        if any(words == tuple(argv) for argv in allowed):
            return "allow", ALLOWED
    if not allowed:
        return "deny", NO_COMMANDS
    return "deny", COMMAND_DENIED.format(commands=", ".join(shlex.join(argv) for argv in allowed))


def decide(document: object, allowed: Sequence[Sequence[str]]) -> tuple[str, str]:
    """`("allow", ALLOWED)` or `("deny", <sentence>)` for one tool call."""
    if not isinstance(document, dict):
        return "deny", MALFORMED
    name = document.get("tool_name")
    if not isinstance(name, str) or not name:
        return "deny", MALFORMED
    if name in READ_TOOLS:
        return "allow", ALLOWED
    if name in WRITE_TOOLS:
        return "deny", WRITE_DENIED.format(tool=name)
    if name != "Bash":
        return "deny", TOOL_DENIED.format(tool=name)
    tool_input = document.get("tool_input")
    if not isinstance(tool_input, dict) or not isinstance(tool_input.get("command"), str):
        return "deny", MALFORMED
    return _decide_bash(tool_input["command"], allowed)


def output(decision: str, reason: str) -> dict:
    """The client's PreToolUse wire format."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    try:
        allowed = parse_allowed(arguments[0])
        document = json.loads(sys.stdin.read())
    except (IndexError, ValueError):
        decision, reason = "deny", MALFORMED
    else:
        decision, reason = decide(document, allowed)
    print(json.dumps(output(decision, reason)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
