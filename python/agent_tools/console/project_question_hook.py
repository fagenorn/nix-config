"""The read-only PreToolUse hook of a project question session (#1176).

Why. The console answers an owner's question about a registered project with a Claude Code client
run in that project's folder. The session only reads: this hook is the one place that decides, for
every tool call, whether the call is a read. It is a packaged sibling run by the console's own
interpreter as `python -m agent_tools.console.project_question_hook '<allowed json>' '<repo>'`; it has no
command-table row (ADR-console-058) and imports only the standard library.

Input. `argv[1]` is the allowed commands: a JSON list of non-empty lists of non-empty strings, each
one declared read-only command's argv (`parse_allowed`, `ValueError` otherwise). `argv[2]` is the
project's GitHub repository as `owner/name`, or the empty string when its contract names none
(`parse_repo`, `ValueError` otherwise). Stdin is the client's hook document, a JSON object with
`tool_name` and `tool_input`.

Decision. `decide(document, allowed, repo)` returns `("allow", ALLOWED)` or `("deny", <sentence>)`, in
this order:

1. A document that is not an object, or whose `tool_name` is not a non-empty string: `MALFORMED`.
2. `Read`, `Grep` and `Glob` (`READ_TOOLS`): allowed.
3. `Edit`, `Write` and `NotebookEdit` (`WRITE_TOOLS`): `WRITE_DENIED`.
4. Any other tool but `Bash` (MCP tools, `Task`, `Agent` and `WebFetch` included): `TOOL_DENIED`.
5. A `Bash` call whose `tool_input` is not an object or whose `command` is not a string: `MALFORMED`.
6. A `Bash` command in which a lifecycle verb (`LIFECYCLE_VERBS`: `git push`, `gh pr create`,
   `gh pr merge`, `git branch -d`, `gh release create`) occurs in the words of `command.split()`
   (any whitespace): `LIFECYCLE_DENIED`, whatever `allowed` holds. The executable matches by its
   basename (`/usr/bin/git push`), and option words, each with one optional value, may sit between
   the verb's words (`git -C . push`, `gh pr -R owner/repo create`); the words of `-d` itself stay
   contiguous with `branch`.
7. Otherwise the separators are checked before any split: the command is allowed only when
   `PLAIN_COMMAND` matches all of it (plain words separated by U+0020 only) and its words equal one
   member of `allowed`. `PLAIN_COMMAND` excludes every shell metacharacter and every
   whitespace but U+0020, so no composed command is admitted: `just\\nbuild` is two commands to a
   shell, and a bare `just` runs the project's default recipe.
8. A plain command that is a git read or a gh read is allowed. A git read (`_git_read`) is exactly
   `git`, then one of `GIT_READS` as the very next word (no option before the subcommand, so no
   `-C`, `-c`, `--git-dir` or `--no-pager`), and no later word starting with a prefix of
   `GIT_DENIED_PREFIXES` (`--output` and `--ext-diff` write a file or run a program; git abbreviates
   long options, so the prefixes cover every spelling). `git tag` is only a listing: bare, or with
   `-l` or `--list` and options of `TAG_LIST_OPTIONS` or `-n<digits>` alone. A gh read (`_gh_read`)
   needs a repository: exactly `gh`, then a group of `GH_READ_GROUPS` and a verb of
   `GH_READ_VERBS`, then the word right after the verb pins the project's repository, either
   `--repo=<repo>` or `--repo <repo>` or `-R <repo>`. The position matters because gh parses its
   flags with pflag: a string flag takes the next word as its value and `--` ends flag parsing, so
   a `--repo` word further on could be a value or a positional while the repository stays whatever
   `GH_REPO` or the default says; the word right after the verb is neither. Every later word is
   refused when it is `--`, starts with `--repo`, is or starts with `--web`, is a single-dash
   cluster holding `w` or `R`, or contains `/` (another repository, a URL or a path). With no
   repository (`repo` is None) no gh read is admitted.
9. A command whose first word, by basename, is `git` or `gh` and was not admitted: `reads_denied`.
10. Anything else is `NO_COMMANDS` when `allowed` is empty and `COMMAND_DENIED` otherwise.

Output. Stdout is exactly one line, `json.dumps(output(decision, reason))`, the client's PreToolUse
wire format. Exactly two arguments are required; a missing, extra or unparseable argument, or unreadable stdin (JSON nested deeper than the recursion limit included), prints the `MALFORMED`
deny.
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
GIT_READS: tuple[str, ...] = ("log", "show", "diff", "status", "blame", "ls-files", "tag")
GH_READ_GROUPS: tuple[str, ...] = ("pr", "release", "issue", "run")
GH_READ_VERBS: tuple[str, ...] = ("list", "view")
GIT_DENIED_PREFIXES: tuple[str, ...] = ("--ou", "--ext")
TAG_LIST_OPTIONS: tuple[str, ...] = (
    "-l", "--list", "-n", "--sort", "--format", "--contains", "--no-contains", "--merged",
    "--no-merged", "--points-at", "-i", "--ignore-case", "--column", "--no-column", "--color",
    "--no-color",
)
REPO_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+")

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
    "This project declares no read-only command, so only the git and gh reads can run in this "
    "session: answer from the code, the docs and those reads."
)
TOOL_DENIED = (
    "This session can use only Read, Grep and Glob, and Bash for a declared read-only command or "
    "a git or gh read, so {tool} is not allowed."
)
READS_DENIED = (
    "This session runs git only as a plain read (git log, show, diff, status, blame, ls-files or "
    "tag -l, with no option before the subcommand and no --output or --ext-diff) and gh only "
    "{gh}, each alone with no pipe, redirect, ;, &&, subshell or substitution."
)
GH_WITH_REPO = (
    "as pr, release, issue or run list or view with --repo {repo} right after list or view, "
    "before any other word, and no --, no --web and no other repository"
)
GH_WITHOUT_REPO = "never: this project's contract names no GitHub repository"
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


def _follows(words: list[str], position: int, verb: tuple[str, ...]) -> bool:
    """Whether `verb[1:]` follows `words[position:]`, option words (and one value each) skipped.

    An option word is any word starting with `-` that is not itself the next verb word, and it may
    take the following word as its value, so both readings are tried: `git -C . push` and
    `gh pr -R owner/repo create` match, and an unknown option is over-denied, never missed.
    """
    if not verb:
        return True
    if position >= len(words):
        return False
    if words[position] == verb[0]:
        return _follows(words, position + 1, verb[1:])
    if verb[0].startswith("-") or not words[position].startswith("-"):
        return False
    if _follows(words, position + 1, verb):
        return True
    return "=" not in words[position] and _follows(words, position + 2, verb)


def _has_lifecycle_verb(words: list[str]) -> bool:
    for verb in LIFECYCLE_VERBS:
        for start, word in enumerate(words):
            if word.rsplit("/", 1)[-1] == verb[0] and _follows(words, start + 1, verb[1:]):
                return True
    return False


def parse_repo(text: str) -> str | None:
    """The repository slug from its argument; None for `""`, `ValueError` for anything else."""
    if text == "":
        return None
    if not REPO_SLUG.fullmatch(text):
        raise ValueError("the repository is not an owner/name slug")
    return text


def reads_denied(repo: str | None) -> str:
    """The sentence for a git or gh command that is not an admitted read."""
    return READS_DENIED.format(gh=GH_WITH_REPO.format(repo=repo) if repo else GH_WITHOUT_REPO)


def _git_read(words: Sequence[str]) -> bool:
    if len(words) < 2 or words[0] != "git" or words[1] not in GIT_READS:
        return False
    rest = words[2:]
    if any(word.startswith(prefix) for word in rest for prefix in GIT_DENIED_PREFIXES):
        return False
    if words[1] != "tag" or not rest:
        return True
    if "-l" not in rest and "--list" not in rest:
        return False
    return all(
        not word.startswith("-")
        or word.split("=", 1)[0] in TAG_LIST_OPTIONS
        or re.fullmatch(r"-n[0-9]*", word)
        for word in rest
    )


def _gh_later_word_refused(word: str) -> bool:
    if word == "--" or word.startswith("--repo") or word == "--web" or word.startswith("--web="):
        return True
    if word.startswith("-") and not word.startswith("--") and ("w" in word[1:] or "R" in word[1:]):
        return True
    return "/" in word


def _gh_read(words: Sequence[str], repo: str | None) -> bool:
    if repo is None or len(words) < 4 or words[0] != "gh":
        return False
    if words[1] not in GH_READ_GROUPS or words[2] not in GH_READ_VERBS:
        return False
    if words[3] == "--repo=" + repo:
        rest = words[4:]
    elif words[3] in ("--repo", "-R") and len(words) >= 5 and words[4] == repo:
        rest = words[5:]
    else:
        return False
    return not any(_gh_later_word_refused(word) for word in rest)


def _decide_bash(
    command: str, allowed: Sequence[Sequence[str]], repo: str | None
) -> tuple[str, str]:
    if _has_lifecycle_verb(command.split()):
        return "deny", LIFECYCLE_DENIED
    if PLAIN_COMMAND.fullmatch(command):
        words = tuple(word for word in command.split(" ") if word)
        if any(words == tuple(argv) for argv in allowed):
            return "allow", ALLOWED
        if _git_read(words) or _gh_read(words, repo):
            return "allow", ALLOWED
    if (command.split() or [""])[0].rsplit("/", 1)[-1] in ("git", "gh"):
        return "deny", reads_denied(repo)
    if not allowed:
        return "deny", NO_COMMANDS
    return "deny", COMMAND_DENIED.format(commands=", ".join(shlex.join(argv) for argv in allowed))


def decide(
    document: object, allowed: Sequence[Sequence[str]], repo: str | None = None
) -> tuple[str, str]:
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
    return _decide_bash(tool_input["command"], allowed, repo)


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
        if len(arguments) != 2:
            raise ValueError("the hook takes the allowed commands and the repository")
        allowed = parse_allowed(arguments[0])
        repo = parse_repo(arguments[1])
        document = json.loads(sys.stdin.read())
    except (IndexError, ValueError, RecursionError):
        decision, reason = "deny", MALFORMED
    else:
        decision, reason = decide(document, allowed, repo)
    print(json.dumps(output(decision, reason)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
