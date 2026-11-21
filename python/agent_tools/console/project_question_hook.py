"""The read-only PreToolUse hook of a project question session (#1176).

Why. The console answers an owner's question about a registered project with a Claude Code client
run in that project's folder. The session only reads: this hook is the one place that decides, for
every tool call, whether the call is a read. It is a packaged sibling run by the console's own
interpreter as `python -m agent_tools.console.project_question_hook '<allowed json>' '<repo>' ['<private dir>'
'<records file>' ['<checkout root>']]`; it has no
command-table row (ADR-console-058) and imports only the standard library.

Input. `argv[1]` is the allowed commands: a JSON list of non-empty lists of non-empty strings, each
one declared read-only command's argv (`parse_allowed`, `ValueError` otherwise). `argv[2]` is the
project's GitHub repository as `owner/name`, or the empty string when its contract names none
(`parse_repo`, `ValueError` otherwise). Stdin is the client's hook document, a JSON object with
`tool_name` and `tool_input`, and `cwd` when the client gives one. `argv[3]` and `argv[4]`, given
together or not at all, are the console's private directory and the question's own records file
(`parse_confinement`, `ValueError` unless both are absolute and the file lies strictly inside the
directory); they are the confinement of #1271 and ADR-console-089. An optional `argv[5]`, the checkout root
of a deeper session (#1274), must be absolute and not inside the private directory and is kept as its real
path (`Confinement.root`); only a deeper session is given one. The confinement also holds the
transcript stores (`transcript_dirs`: `projects` under `$CLAUDE_CONFIG_DIR`, under `~/.claude` and under
every profile of `$CLAUDE_ACCOUNTS_DIR`, default `~/.claude-accounts`), read from the hook's own
environment: the profiles share one transcript store, and a transcript holds every tool result of a
session, so another question's records would stay readable there after their file is removed.
Containment is judged by filesystem identity as well as by spelling, so a case alias on a case-insensitive
volume is the directory it opens, and an identity that cannot be read is a denial. One part of a store is
admitted: the session's own saved tool output, `<store>/<slug>/<session id>/tool-results/`, where the client
puts a command's output that is too large to show inline and tells the model to Read it. The session id is
the hook document's `session_id` when it is a plain name (`[A-Za-z0-9][A-Za-z0-9_.-]*`), so another
session's results stay confined, and a path inside the private directory is never admitted this way.

Decision. `decide(document, allowed, repo)` returns `("allow", ALLOWED)` or `("deny", <sentence>)`, in
this order:

1. A document that is not an object, or whose `tool_name` is not a non-empty string: `MALFORMED`.
2. `Read`, `Grep` and `Glob` (`READ_TOOLS`): allowed; with a confinement, allowed only after the
   confinement below, which reads `cwd` when it is an absolute string and the process's directory
   otherwise. With no confinement every decision is exactly as it was before #1271 and nothing is
   walked.
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
   `-l` or `--list` and options of `TAG_LIST_OPTIONS` or `-n<digits>` alone, with `--sort` and
   `--format` only `=`-attached (git reads their value from the next word, even a dash word, so
   `git tag --format -l v9` creates the tag `v9`). A gh read (`_gh_read`)
   needs a repository: exactly `gh`, then a group of `GH_READ_GROUPS` and a verb of
   `GH_READ_VERBS`, then the repository selection, either `--repo=<repo>` or `--repo <repo>` or
   `-R <repo>`, right after the verb or, for `view` only, right after one positional (the tag,
   number or run id: `gh release view v1.2.0 --repo <repo>`). The position matters because gh
   parses its flags with pflag: a string flag takes the next word as its value and `--` ends flag
   parsing, so a `--repo` word further on could be a value or a positional while the repository
   stays whatever `GH_REPO` or the default says; the word right after the verb or after that one
   positional is neither. A `view` takes at most one positional in all (`_gh_positionals`: a word
   that is not a flag and not the value of a `GH_VIEW_VALUE_FLAGS` flag), before or after the
   selection. Every other word is refused when it is `--`, starts with `--repo`, is or starts with
   `--web`, is a single-dash cluster holding `w` or `R`, or contains `/` (another repository, a URL
   or a path). With no repository (`repo` is None) no gh read is admitted.
9. A command whose first word, by basename, is `git` or `gh` and was not admitted: `reads_denied`.
10. Anything else is `NO_COMMANDS` when `allowed` is empty and `COMMAND_DENIED` otherwise.

The confinement (#1271, ADR-console-089 D2). With a confinement the only file under its private
directory that any tool may reach is its records file. A path reaches (`_reaches`) when its real path
(symlinks resolved, `~` expanded, relative to `cwd`) is not the records file and is the private
directory, the directory holding the records file or a transcript store, lies inside one, or is an ancestor of one, and is not inside the
session's own `tool-results` directory of a store (`_own_results`); a reach is `RECORDS_DENIED`. It applies to:

- `Read`: `file_path`.
- `Grep`: `path` (the client's directory when absent), then the traversal rule below on it; a `glob`
  with a `..` component is `RECORDS_DENIED`.
- `Glob`: `path` (or the client's directory) joined with the literal prefix of `pattern` (the
  components before the first one holding `*`, `?`, `[` or `{`; an absolute pattern replaces the
  directory), then the traversal rule; a `..` component after the literal prefix is `RECORDS_DENIED`.
  Brace groups are expanded first (`_brace_expansions`) and each spelling is checked, so `{..,x}` or
  `{.,x}{.,x}` is the `..` component it can become; past `BRACE_LIMIT` spellings the call is
  `BRACES_UNCHECKED`. A `Grep` `glob` is expanded the same way for its `..` rule.
- An admitted `Bash` command (declared, git read or gh read): every word after the first, read every
  way it could name a file (`_word_targets`: the word, the text after each `=` in it, and for a short
  option word the text after every letter position from the second on, so `-wS<path>` is checked as
  `S<path>` and as `<path>`, because git reads bundled short flags and an attached value; each also
  without a leading `@`), by the
  path rule, and each target that is an existing directory by the traversal rule. A command's file
  operands cannot be told from its grammar, so this over-denies by design: git admits an option value
  such as `git blame --contents=<path>` that prints the named file.

The traversal rule (`_tree_reaches`) covers the client's search meeting the console's state later. The
client's behaviour about symlinks while searching is not established, so the walk assumes it follows
them: it lists with `os.scandir` and descends each real directory once, by filesystem identity
(`st_dev`, `st_ino`) and not by spelling, so a symlinked directory and a second mount of one are one
directory. Every directory it enters is compared by identity with the private directory, the directory holding the records file and each
transcript store, so a bind-mounted alias of one (a mount of the records directory alone included, whose visible ancestry holds neither the private directory nor a store) is `RECORDS_DENIED`, and every symlink it meets is
checked by the path rule on the link's real path. It trusts no subtree: a link into `/nix/store` is
walked like any other, since a store path can hold a link back into the console's state. Each entry
listed counts toward `WALK_LIMIT` and the walk has `WALK_SECONDS` of time; past either, and when a
directory or an identity cannot be read (any `OSError` but a path that vanished), the call is
`SEARCH_UNCHECKED`, because a search that cannot be fully checked is not allowed. A non-symlink
descendant of a directory that does not reach cannot lie inside the private directory unless it is
a mount of it, which the identity check names, so only symlinks and directory identities are checked.

The root (#1274, ADR-console-097 D1). With a root, after the checks above, a path is `OUTSIDE_ROOT` when it is
none of the records file, the session's own `tool-results` and a path inside the root (`_outside`, by real
path). It denies a `Read` whose `file_path` is outside, a `Grep` whose search root (`path`, else `cwd`) is
outside, a `Glob` any of whose literal prefixes joined to the search root is outside, and a `Bash` command
any word target of which is outside (`_word_targets`), a declared command included: a declared read
that names a path outside the checkout (a database of another checkout) is refused like any other; a denied command with such a target (a `git -C <other>` that
`reads_denied` would refuse) is given `OUTSIDE_ROOT` in place of that sentence, except a lifecycle verb,
which keeps `LIFECYCLE_DENIED`. The protected checks run first, so a transcript or another question's
records keep `RECORDS_DENIED`. A search walk inside the checkout keeps the symlink rule above (protected
roots only): a symlink the checkout itself holds is part of its declared content.

Output. Stdout is exactly one line, `json.dumps(output(decision, reason))`, the client's PreToolUse
wire format. Exactly two arguments (`<allowed> <repo>`), four (`<allowed> <repo> <private dir> <records
file>`) or five (those and `<checkout root>`) are required; any other count, a four-argument form `parse_confinement` refuses, an unparseable
argument, or unreadable stdin (JSON nested deeper than the recursion limit included), prints the
`MALFORMED` deny.
The exit status is 0 in every case. A hook process that gives no decision (a timeout, an
interpreter that fails to start) is turned into a deny by `"onFailure": "block"` in the session's
settings, not by this module.
"""

from __future__ import annotations

import errno
import glob
import json
import os
import re
import shlex
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

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
GH_VIEW_VALUE_FLAGS: tuple[str, ...] = (
    "--json", "--jq", "-q", "--template", "-t", "--job", "-j", "--attempt", "-a")
GIT_DENIED_PREFIXES: tuple[str, ...] = ("--ou", "--ext")
TAG_VALUE_OPTIONS: tuple[str, ...] = ("--sort", "--format")
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
    "as pr, release, issue or run list or view with --repo {repo} right after list or view "
    "(a view may name its tag or number just before --repo or just after it, never both), and no "
    "--, no --web and no other repository"
)
GH_WITHOUT_REPO = "never: this project's contract names no GitHub repository"
MALFORMED = "The question session's hook could not read this tool call, so it was refused."
RECORDS_DENIED = (
    "This session reads the console's own records only from its records file, {records}; the "
    "console's other files, other questions' records included, are not read."
)
OUTSIDE_ROOT = (
    "This deeper session reads only its project's checkout {root} and its records file {records}; "
    "that path is outside both, so it was refused."
)
SEARCH_UNCHECKED = (
    "This search is too large to check against the console's own files (over {limit} files and "
    "directories, too slow to list or not fully listable), so it was refused: search a narrower "
    "path."
)
BRACES_UNCHECKED = (
    "This pattern names more than {limit} brace alternatives, too many to check against the "
    "console's own files, so it was refused: use fewer alternatives."
)
WALK_LIMIT = 100_000
WALK_SECONDS = 5.0
BRACE_LIMIT = 64
WILDCARDS = "*?[{"


@dataclass(frozen=True)
class Confinement:
    """The console's private directory and the one file in it a session may read; absolute real paths."""

    private: str
    records: str
    transcripts: tuple[str, ...] = ()
    session: str | None = None
    root: str | None = None

    @property
    def protected(self) -> tuple[str, ...]:
        """The roots no tool may reach beyond the records file: the private directory, the records file's own
        directory (a mount of it has neither the private directory nor a store in its visible ancestry) and the stores."""
        return (self.private, os.path.dirname(self.records), *self.transcripts)


def _identity(path: str) -> tuple[int, int] | None:
    """The `(st_dev, st_ino)` of `path`, or None when it names nothing; any other `OSError` propagates.

    A symlink loop (`ELOOP`) and a name too long to exist (`ENAMETOOLONG`) name nothing a client could
    open, as a missing path does; an unreadable one (`EIO`, `EACCES`) is indeterminate and stays an error.
    """
    try:
        status = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENAMETOOLONG):
            return None
        raise
    return status.st_dev, status.st_ino


def _inside(path: str, directory: str) -> bool:
    """Whether `path` is `directory` or lies below it, by spelling or by filesystem identity."""
    if os.path.commonpath([path, directory]) == directory:
        return True
    held = _identity(directory)
    if held is None:
        return False
    while True:
        if _identity(path) == held:
            return True
        parent = os.path.dirname(path)
        if parent == path:
            return False
        path = parent


def _same_file(path: str, other: str) -> bool:
    """Whether `path` and `other` are one file, by spelling or by identity; a missing one is not."""
    if path == other:
        return True
    first, second = _identity(path), _identity(other)
    return first is not None and first == second


SESSION_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
RESULTS_DIR = "tool-results"


def _own_results(path: str, c: Confinement) -> bool:
    """Whether `path` is inside the session's own saved tool output, `<store>/<slug>/<session>/tool-results`."""
    if c.session is None or _inside(path, c.private):
        return False
    for store in c.transcripts:
        try:
            with os.scandir(store) as scan:
                slugs = [entry.path for entry in scan if entry.is_dir()]
        except (FileNotFoundError, NotADirectoryError):
            continue
        if any(_inside(path, os.path.join(slug, c.session, RESULTS_DIR)) for slug in slugs):
            return True
    return False


def transcript_dirs(environ: Mapping[str, str]) -> tuple[str, ...]:
    """The real paths of every transcript store a client of this host writes, from `environ`."""
    home = environ.get("HOME") or os.path.expanduser("~")
    accounts = environ.get("CLAUDE_ACCOUNTS_DIR") or os.path.join(home, ".claude-accounts")
    found = [os.path.join(home, ".claude", "projects")]
    if environ.get("CLAUDE_CONFIG_DIR"):
        found.append(os.path.join(environ["CLAUDE_CONFIG_DIR"], "projects"))
    found += glob.glob(os.path.join(glob.escape(accounts), "profiles", "*", "projects"))
    return tuple(dict.fromkeys(os.path.realpath(path) for path in found if os.path.isabs(path)))


def parse_confinement(private: str, records: str, environ: Mapping[str, str] | None = None,
                      root: str | None = None) -> Confinement:
    """The confinement of two paths; `ValueError` unless both are absolute and `records` is strictly inside.

    A `root`, the checkout a deeper session is confined to, must be absolute and not inside `private`.
    """
    if not os.path.isabs(private) or not os.path.isabs(records):
        raise ValueError("the confinement paths are not absolute")
    real_private, real_records = os.path.realpath(private), os.path.realpath(records)
    if _same_file(real_records, real_private) or not _inside(real_records, real_private):
        raise ValueError("the records file is not inside the private directory")
    real_root = None
    if root is not None:
        if not os.path.isabs(root):
            raise ValueError("the checkout root is not absolute")
        real_root = os.path.realpath(root)
        if _inside(real_root, real_private):
            raise ValueError("the checkout root is inside the private directory")
    return Confinement(real_private, real_records,
                       transcript_dirs(os.environ if environ is None else environ), root=real_root)


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
        or (word.split("=", 1)[0] in TAG_LIST_OPTIONS and word not in TAG_VALUE_OPTIONS)
        or re.fullmatch(r"-n[0-9]*", word)
        for word in rest
    )


def _gh_later_word_refused(word: str) -> bool:
    if word == "--" or word.startswith("--repo") or word == "--web" or word.startswith("--web="):
        return True
    if word.startswith("-") and not word.startswith("--") and ("w" in word[1:] or "R" in word[1:]):
        return True
    return "/" in word


def _gh_repo_pair(words: Sequence[str], start: int, repo: str) -> int | None:
    """The index after the repository selection at `words[start:]`, or None when it is not one."""
    if start >= len(words):
        return None
    if words[start] == "--repo=" + repo:
        return start + 1
    if words[start] in ("--repo", "-R") and start + 1 < len(words) and words[start + 1] == repo:
        return start + 2
    return None


def _gh_positionals(words: Sequence[str]) -> int:
    """How many words are positionals: not a flag and not the value of a value-taking view flag."""
    count, skip = 0, False
    for word in words:
        if skip:
            skip = False
        elif word.startswith("-"):
            skip = "=" not in word and word in GH_VIEW_VALUE_FLAGS
        else:
            count += 1
    return count


def _gh_read(words: Sequence[str], repo: str | None) -> bool:
    if repo is None or len(words) < 4 or words[0] != "gh":
        return False
    if words[1] not in GH_READ_GROUPS or words[2] not in GH_READ_VERBS:
        return False
    end = _gh_repo_pair(words, 3, repo)
    if end is not None:
        rest = words[end:]
        if words[2] == "view" and _gh_positionals(rest) > 1:
            return False
    elif words[2] == "view" and not words[3].startswith("-"):
        end = _gh_repo_pair(words, 4, repo)
        if end is None or _gh_positionals(words[end:]) > 0:
            return False
        rest = (words[3], *words[end:])
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


def _resolve(text: str, base: str) -> str:
    return os.path.realpath(os.path.join(base, os.path.expanduser(text)))


def _reaches(text: str, base: str, c: Confinement) -> bool:
    """Whether `text`, a path read relative to `base`, reaches the console's state or transcripts beyond its records."""
    if not text:
        return False
    path = _resolve(text, base)
    if _same_file(path, c.records) or _own_results(path, c):
        return False
    return any(_inside(path, held) or _inside(held, path) for held in c.protected)


def _outside(text: str, base: str, c: Confinement) -> bool:
    """Whether `text`, a path read relative to `base`, lies outside a deeper session's checkout and its reads."""
    if c.root is None or not text:
        return False
    path = _resolve(text, base)
    return not (_same_file(path, c.records) or _own_results(path, c) or _inside(path, c.root))


def _word_targets(word: str) -> list[str]:
    """Every reading of `word` that could name a file: itself, the text after each `=`, a short option's value after any bundled flag."""
    targets = [word]
    for index, letter in enumerate(word):
        if letter == "=":
            targets.append(word[index + 1:])
    if word.startswith("-") and not word.startswith("--"):
        targets.extend(word[index:] for index in range(2, len(word)))
    for target in list(targets):
        if target.startswith("@"):
            targets.append(target[1:])
    return list(dict.fromkeys(targets))


def _tree_reaches(root: str, c: Confinement) -> str | None:
    """The deny sentence when a search of `root` could meet the console's state, else None.

    The walk follows symlinks because the client may. It lists with `os.scandir`, enters each
    directory once by `(st_dev, st_ino)`, compares every directory it enters with the identity of the
    private directory and the transcript stores, checks each symlink by the path rule, trusts no
    subtree, and gives up past `WALK_LIMIT` entries or `WALK_SECONDS` seconds or when a directory
    or identity cannot be read, which keeps it inside the hook's own timeout and its answer complete.
    """
    root = os.path.realpath(root)
    if not os.path.isdir(root):
        return None
    denied = RECORDS_DENIED.format(records=c.records)
    unchecked = SEARCH_UNCHECKED.format(limit=WALK_LIMIT)
    held = {identity for identity in map(_identity, c.protected) if identity is not None}
    deadline = time.monotonic() + WALK_SECONDS
    visited: set[tuple[int, int]] = set()
    pending: list[str] = []
    listed = 0

    def enter(real: str) -> str | None:
        try:
            status = os.stat(real)
        except OSError:
            return unchecked
        identity = (status.st_dev, status.st_ino)
        if identity in held:
            return denied
        if identity not in visited:
            visited.add(identity)
            pending.append(real)
        return None

    found = enter(root)
    while found is None and pending:
        if time.monotonic() > deadline:
            return unchecked
        try:
            with os.scandir(pending.pop()) as scan:
                entries = list(scan)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            return unchecked
        listed += len(entries)
        if listed > WALK_LIMIT:
            return unchecked
        for entry in entries:
            if entry.is_symlink():
                real = os.path.realpath(entry.path)
                if _reaches(real, "/", c):
                    return denied
                walk = os.path.isdir(real)
            else:
                real, walk = entry.path, entry.is_dir(follow_symlinks=False)
            found = enter(real) if walk else None
            if found is not None:
                break
    return found


def _brace_expansions(pattern: str) -> list[str] | None:
    """Every spelling of `pattern` with its brace groups expanded, or None past `BRACE_LIMIT`.

    A group with one alternative expands to its text alone; an unclosed `{` stays literal. The pattern
    itself is always among the spellings.
    """
    done, pending = [pattern], [pattern]
    while pending:
        text = pending.pop()
        for start, letter in enumerate(text):
            if letter != "{":
                continue
            depth, cuts = 0, [start]
            for end in range(start, len(text)):
                if text[end] == "{":
                    depth += 1
                elif text[end] == "}":
                    depth -= 1
                    if depth == 0:
                        cuts.append(end)
                        break
                elif text[end] == "," and depth == 1:
                    cuts.append(end)
            else:
                continue
            for first, second in zip(cuts, cuts[1:]):
                spelling = text[:start] + text[first + 1:second] + text[cuts[-1] + 1:]
                if spelling not in done:
                    done.append(spelling)
                    pending.append(spelling)
            break
        if len(done) > BRACE_LIMIT:
            return None
    return done


def _search_reaches(root: str, base: str, c: Confinement) -> str | None:
    if _reaches(root, base, c):
        return RECORDS_DENIED.format(records=c.records)
    return _tree_reaches(_resolve(root, base), c)


def _confined(name: str, tool_input: dict, base: str, c: Confinement) -> str | None:
    """The deny sentence of a Read, Grep or Glob call under the confinement, else None."""
    denied = RECORDS_DENIED.format(records=c.records)
    path = tool_input.get("path")
    root = path if isinstance(path, str) else base
    if name == "Read":
        file_path = tool_input.get("file_path")
        if isinstance(file_path, str) and _reaches(file_path, base, c):
            return denied
        return _outside_root(c) if isinstance(file_path, str) and _outside(file_path, base, c) else None
    if name == "Grep":
        pattern = tool_input.get("glob")
        spellings = _brace_expansions(pattern) if isinstance(pattern, str) else []
        if spellings is None:
            return BRACES_UNCHECKED.format(limit=BRACE_LIMIT)
        if any(".." in spelling.split("/") for spelling in spellings):
            return denied
        return _search_reaches(root, base, c) or (
            _outside_root(c) if _outside(root, base, c) else None)
    pattern = tool_input.get("pattern")
    spellings = _brace_expansions(pattern) if isinstance(pattern, str) else []
    if spellings is None:
        return BRACES_UNCHECKED.format(limit=BRACE_LIMIT)
    prefixes = []
    for spelling in spellings:
        parts = spelling.split("/")
        literal = 0
        while literal < len(parts) and not any(mark in parts[literal] for mark in WILDCARDS):
            literal += 1
        if ".." in parts[literal:]:
            return denied
        prefixes.append("/".join(parts[:literal]) or ("/" if parts[:1] == [""] and literal else ""))
    for prefix in dict.fromkeys(prefixes):
        found = _search_reaches(os.path.join(root, prefix), base, c)
        if found:
            return found
    for prefix in dict.fromkeys(prefixes):
        if _outside(os.path.join(root, prefix), base, c):
            return _outside_root(c)
    return None


def _outside_root(c: Confinement) -> str:
    return OUTSIDE_ROOT.format(root=c.root, records=c.records)


def _command_outside(command: str, base: str, c: Confinement) -> bool:
    """Whether any word of `command` could name a path outside a deeper session's checkout."""
    return any(_outside(target, base, c)
               for word in [word for word in command.split(" ") if word][1:]
               for target in _word_targets(word))


def _confined_command(command: str, base: str, c: Confinement) -> str | None:
    """The deny sentence of an admitted command whose words reach the console's state, else None.

    Under a root, a declared read included, a command is also denied for a word outside it.
    """
    for word in [word for word in command.split(" ") if word][1:]:
        for target in _word_targets(word):
            if _reaches(target, base, c):
                return RECORDS_DENIED.format(records=c.records)
            if target and os.path.isdir(_resolve(target, base)):
                found = _tree_reaches(_resolve(target, base), c)
                if found:
                    return found
    if _command_outside(command, base, c):
        return _outside_root(c)
    return None


def decide(
    document: object,
    allowed: Sequence[Sequence[str]],
    repo: str | None = None,
    confinement: Confinement | None = None,
) -> tuple[str, str]:
    """`("allow", ALLOWED)` or `("deny", <sentence>)` for one tool call."""
    if not isinstance(document, dict):
        return "deny", MALFORMED
    name = document.get("tool_name")
    if not isinstance(name, str) or not name:
        return "deny", MALFORMED
    cwd = document.get("cwd")
    base = cwd if isinstance(cwd, str) and os.path.isabs(cwd) else os.getcwd()
    if name in READ_TOOLS:
        if confinement is None:
            return "allow", ALLOWED
        tool_input = document.get("tool_input")
        if not isinstance(tool_input, dict):
            return "deny", MALFORMED
        session = document.get("session_id")
        if isinstance(session, str) and SESSION_NAME.fullmatch(session):
            confinement = replace(confinement, session=session)
        try:
            found = _confined(name, tool_input, base, confinement)
        except (OSError, ValueError):
            return "deny", MALFORMED
        return ("deny", found) if found else ("allow", ALLOWED)
    if name in WRITE_TOOLS:
        return "deny", WRITE_DENIED.format(tool=name)
    if name != "Bash":
        return "deny", TOOL_DENIED.format(tool=name)
    tool_input = document.get("tool_input")
    if not isinstance(tool_input, dict) or not isinstance(tool_input.get("command"), str):
        return "deny", MALFORMED
    decision = _decide_bash(tool_input["command"], allowed, repo)
    if confinement is None:
        return decision
    session = document.get("session_id")
    if isinstance(session, str) and SESSION_NAME.fullmatch(session):
        confinement = replace(confinement, session=session)
    if decision[0] != "allow":
        if confinement.root is None or decision[1] == LIFECYCLE_DENIED:
            return decision
        try:
            outside = _command_outside(tool_input["command"], base, confinement)
        except (OSError, ValueError):
            return "deny", MALFORMED
        return ("deny", _outside_root(confinement)) if outside else decision
    try:
        found = _confined_command(tool_input["command"], base, confinement)
    except (OSError, ValueError):
        return "deny", MALFORMED
    return ("deny", found) if found else decision


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
        if len(arguments) not in (2, 4, 5):
            raise ValueError("the hook takes the allowed commands, the repository and a confinement")
        allowed = parse_allowed(arguments[0])
        repo = parse_repo(arguments[1])
        confinement = (parse_confinement(*arguments[2:4], root=arguments[4] if len(arguments) == 5 else None)
                       if len(arguments) >= 4 else None)
        document = json.loads(sys.stdin.read())
    except (IndexError, ValueError, RecursionError, OSError):
        decision, reason = "deny", MALFORMED
    else:
        decision, reason = decide(document, allowed, repo, confinement)
    print(json.dumps(output(decision, reason)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
