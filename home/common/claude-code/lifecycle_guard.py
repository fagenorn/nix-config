"""Claude Code's PreToolUse Bash lifecycle guard.

The claude-code module's store wrapper clears NIX_PYTHON* and runs this file
under `python3 -I` with `--base-policy` naming the store base policy, the only
source of the trusted members, and `--policy` naming the compiled policy at
`~/.agents/state/guard/policy.json`, which supplies derived rows alone. The
wrapper also passes `--derive-bin`, the row check the guard runs for a
repository with a compiled row before it relies on that row. Any of the three
flags given after the wrapper's own replaces it, which is how a test loads
fixtures.
Standard library only: it imports nothing from the repository's helper package.
"""

import argparse
from collections import namedtuple
import json
import os
import re
import shlex
import signal
import stat
import subprocess
import sys
import time


BASE_POLICY_KEYS = frozenset(
    {"authorized_owners", "integration_bases", "git_bin", "gh_bin", "jq_bin"}
)
COMPILED_POLICY_KEYS = frozenset({"derived_repositories", "derivation"})
DERIVED_ROW_KEYS = frozenset({"default_branch", "integration_branch", "evidence"})
# A policy file larger than this is refused unread. Either file is a few kilobytes,
# so the cap only bounds the read of a file that is not what it claims to be.
POLICY_MAX_BYTES = 1 << 20
# Variables a shell reads its startup file from (`BASH_ENV`, `ENV`) or imports
# functions from (`BASH_FUNC_<name>%%`), which never reach the row check.
ROW_CHECK_ENV_DROPPED = frozenset({"BASH_ENV", "ENV"})
ROW_CHECK_ENV_DROPPED_PREFIX = "BASH_FUNC_"
CHILD_DIAGNOSTIC_LIMIT = 240
# One invocation, the row check included, answers inside this many seconds, which
# keeps the verdict ahead of the hook's 30-second timeout.
INVOCATION_DEADLINE_SECONDS = 27
DEADLINE_REFUSAL = (
    f"the {INVOCATION_DEADLINE_SECONDS}-second invocation deadline leaves too "
    "little time for the next check, so it was not started"
)
ROW_CHECK_EXIT_STATUSES = {"derived": 0, "refused": 1, "unavailable": 2}
# The gh keyring credential is the authority for these lookups. gh prefers an
# ambient GITHUB_TOKEN/GH_TOKEN over it, and such a token, when one is present
# (CI, a one-off export, another tool), may be narrower: it may not see every
# authorized owner's org. The guard's forge lookups drop the env tokens, so
# validation observes GitHub with the keyring credential: the auth the guarded
# command uses when it sees neither env token (none is set, or an accepted
# scrub prefix in SCRUB_PREFIXES below removed every one that was set). A
# machine with no keyring auth still fails closed at the lookup.
GH_ENV_TOKEN_NAMES = ("GITHUB_TOKEN", "GH_TOKEN")
# The scrub-prefix spelling a resolved exhaustive credential-name list yields
# (`unset GITHUB_TOKEN && gh ...`), and the one the ship-issue skill check reads
# from this single assignment. SCRUB_PREFIXES below includes it.
UNSET_GITHUB_TOKEN_PREFIX = "unset GITHUB_TOKEN && "
# Every accepted credential-scrub prefix (issue 400 D1): `unset N && `,
# `unset N M && `, `env -u N ` and `env -u N -u M `, single spaces, with N and M
# distinct members of GH_ENV_TOKEN_NAMES. Unsetting any other name could change
# the repository or config the command sees. Longest first, so a two-name
# spelling is tried before the one-name spelling it begins with.
SCRUB_PREFIXES = tuple(sorted(
    {
        spelling
        for names in [(name,) for name in GH_ENV_TOKEN_NAMES] + [
            (first, second)
            for first in GH_ENV_TOKEN_NAMES for second in GH_ENV_TOKEN_NAMES
            if first != second
        ]
        for spelling in (
            "unset " + " ".join(names) + " && ",
            "env " + " ".join(f"-u {name}" for name in names) + " ",
        )
    },
    key=lambda spelling: (-len(spelling), spelling),
))
# The guarded verbs as word sequences: the program, then its subcommand path.
# Order matters: the first match at a token wins, and no sequence is a prefix
# of another.
GUARDED_VERBS = (
    (("gh", "pr", "merge"), "merge"),
    (("gh", "pr", "create"), "pr-create"),
    (("git", "branch", "-d"), "branch"),
    (("git", "push"), "push"),
    (("gh", "release", "create"), "release"),
    # `new` is gh's alias of `create`; it routes to the same grammar, which
    # refuses it because the grammar spells `create`.
    (("gh", "release", "new"), "release"),
)
# The raise label is the user's Instruction Budget raise decision. The refusal
# is a mistake-catcher for agents, not enforcement (#294).
RAISE_LABEL = "instruction-budget-raise"
RAISE_LABEL_REFUSAL = (
    "only the user applies this label (Instruction Budget raise control)"
)
OPERATION_LABELS = {
    "merge": "merge",
    "pr-create": "PR creation",
    "branch": "branch deletion",
    "push": "push",
    "release": "release creation",
    "label": "instruction-budget-raise label edit",
}
# Words that keep the command position open: shell keywords that introduce a
# command, and wrappers that hand the rest of the words to another command.
COMMAND_KEYWORDS = frozenset({
    "!", "time", "if", "then", "elif", "else", "while", "until", "do", "done",
    "in", "coproc",
})
COMMAND_WRAPPERS = frozenset({"command", "builtin", "exec", "env", "sudo"})
# Programs whose argument is shell source, matched by basename (`/bin/sh -c`).
# Arbitrary shell cannot be parsed here, so a guarded verb anywhere in such a
# segment is refused outright, and so is a detaching word (matched there as
# raw text).
SHELL_EVALUATORS = frozenset({"eval", "sh", "bash", "zsh", "dash", "ksh"})
EVALUATOR_REASON = "shell source passed to an evaluator cannot be validated"
SPLIT_STRING_REASON = "command text handed to env -S cannot be validated"
NOT_COMMAND_POSITION = (
    "the verb is not in a command position the guard can validate; quote it "
    "if you only mean to mention it"
)
# What a branch-name check that timed out reports; a refusal of the state, not
# of the command's text, so it prints no accepted forms (issue 402 D3).
BRANCH_VALIDATION_TIMEOUT = "branch validation timed out"
# Ends every refusal of an invocation form at recognition (issue 400 D6).
INVOCATION_FORM_HINT = "run git and gh by name, and carry a directory only as git -C <dir>"
# Words that detach a process from the task that started it (#278). Refused
# in every repository, before the policy loads.
DETACHING_WORDS = ("nohup", "setsid", "disown")
DETACHING_ROUTES = (
    "a detached process outlives the task stop; run it with the Bash tool's "
    "background mode (run_in_background: true), or wrap a lifecycle launch in "
    "launch-scope exec"
)
# Characters that end a word and re-open the command position: subshells,
# groups, `case` arms and command substitution all start a command after one.
OPERATOR_CHARS = "(){}`"
ASSIGNMENT_PREFIX = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
SLUG_PATTERN = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")
REF_NAME_PATTERN = re.compile(r"[A-Za-z0-9._/-]+")
# Path components that make a token a namespaced ref rather than a branch
# name: `git push origin refs/heads/main` and `heads/main` both update the
# branch `main`, so they must never be compared as plain names.
REF_NAMESPACE_COMPONENTS = frozenset({"refs", "heads", "tags", "remotes"})
# The release tag the forge adapter pushes and publishes: vMAJOR.MINOR.PATCH,
# no leading zeros, nothing else (D9).
SEMVER_TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
TAG_REF_PREFIX = "refs/tags/"
SEGMENT_SEPARATORS = frozenset(";&|\n")
UNSAFE_BRANCH_CHARS = set(";&|<>$`\\\n\r*?[]{}()#~")
UNSAFE_TEXT_CHARS = frozenset('"$`\\\0\r')
# Where the guard reads raw text (issue 400 D5, D12, D16) it reads it twice: a
# word ends at whitespace, a quote or any shell-active character; and, because
# the shell glues quoted or escaped pieces into one word (`g''it`, `g\it`), with
# the quotes and backslashes deleted, a word ends at whitespace or any other
# shell-active character.
RAW_WORD_BREAKS = frozenset("'\"") | frozenset(UNSAFE_BRANCH_CHARS)
RAW_GLUE_CHARS = frozenset("'\"\\")


# Every accepted spelling, one table per operation (issue 402 D1). A form is
# (id, template, note): words separated by single spaces; `<name>` is a slot
# taking one word, `"<name>"` a free-text slot whose value may begin with `-`;
# a slot may close a literal word (`refs/tags/<vX.Y.Z>`); `[...]` is an
# optional group whose first word is its flag, never nested; the note is
# printed after the form and never matched. Forms are tried in order. `main`
# compiles this literal first on every invocation (D14).
FORM_SLOTS = ("n", "slug", "base", "branch", "sha", "subject", "title", "body", "vX.Y.Z", "path")
FORM_TABLE = {
    "push": {
        "forms": (
            ("tag", "git push origin refs/tags/<vX.Y.Z>", None),
            ("branch", "git push [-u] origin <branch>", None),
        ),
        "whole_text_characters": True,
        "exact_spelling": False,
        "scrub_prefix": True,
    },
    "pr-create": {
        "forms": (
            ("pr-create", 'gh pr create --repo <slug> --base <base> --head <branch> '
                          '--title "<title>" --body "<body>"', None),
        ),
        "whole_text_characters": False,
        "exact_spelling": False,
        "scrub_prefix": True,
    },
    "merge": {
        "forms": (
            ("feature", 'gh pr merge <n> --repo <slug> --merge [--subject "<subject>"] '
                        "[--match-head-commit <sha>] --delete-branch", None),
            ("release", 'gh pr merge <n> --repo <slug> --merge [--subject "<subject>"] '
                        "[--match-head-commit <sha>]", "only <integration> into <default>"),
        ),
        "whole_text_characters": False,
        "exact_spelling": True,
        "scrub_prefix": True,
    },
    "release": {
        "forms": (
            ("release", 'gh release create <vX.Y.Z> --repo <slug> --verify-tag '
                        '--title "<title>" --notes-file <path>', None),
        ),
        "whole_text_characters": False,
        "exact_spelling": True,
        "scrub_prefix": True,
    },
    "branch": {
        "forms": (("branch", "git branch -d <branch>", None),),
        "whole_text_characters": True,
        "exact_spelling": False,
        "scrub_prefix": False,
    },
}
# The value `--match-head-commit` takes: a full commit SHA (issue 402 D10).
HEAD_COMMIT = re.compile(r"[0-9a-f]{40}")

Literal = namedtuple("Literal", "word")
Slot = namedtuple("Slot", "name quoted prefix")
Group = namedtuple("Group", "elements")
CompiledForm = namedtuple("CompiledForm", "id template note elements")
CompiledOperation = namedtuple(
    "CompiledOperation",
    "operation forms whole_text_characters exact_spelling scrub_prefix program flags "
    "quoted_value_flags",
)
FormWalk = namedtuple("FormWalk", "position expected values quoted")
FormMatch = namedtuple("FormMatch", "form values")

FORM_TABLE_OPERATIONS = frozenset({"push", "pr-create", "merge", "release", "branch"})
FORM_TABLE_PROPERTIES = ("whole_text_characters", "exact_spelling", "scrub_prefix")
NOTE_PLACEHOLDERS = frozenset({"<integration>", "<default>"})
SLOT_WORD = re.compile(r'([^<>"]*)<([^<>"]+)>')
QUOTED_SLOT_WORD = re.compile(r'([^<>"]*)"<([^<>"]+)>"')
LITERAL_WORD = re.compile(r'[^<>"]+')


class FormTableError(ValueError):
    """A form-table entry that does not compile; `main` lets it reach the
    unexpected-failure handler, which refuses with exit 2 (issue 402 D14)."""


class DeadlineExhausted(Exception):
    """The invocation deadline leaves too little time to start the next child.

    A plain `Exception`, so the validators' `except (subprocess.TimeoutExpired,
    OSError)` clauses and the module's unexpected-failure handler never see it;
    `main` alone turns it into a refusal.
    """


def block(reason):
    print(f"lifecycle guard: {reason}", file=sys.stderr)
    return 2


def bounded_child_diagnostic(child):
    parts = []
    for name, output in (("stderr", child.stderr), ("stdout", child.stdout)):
        if not output:
            continue
        normalized = "".join(
            character if character.isprintable() else " "
            for character in output
        )
        normalized = " ".join(normalized.split())
        if normalized:
            parts.append(f"{name}={normalized}")
    if not parts:
        return "no child output"
    diagnostic = "; ".join(parts)
    if len(diagnostic) > CHILD_DIAGNOSTIC_LIMIT:
        return diagnostic[:CHILD_DIAGNOSTIC_LIMIT - 3] + "..."
    return diagnostic


def block_child_failure(reason, child):
    return block(f"{reason}: {bounded_child_diagnostic(child)}")


def gh_lookup_env():
    """os.environ with the gh-recognised token variables removed."""
    environment = dict(os.environ)
    for name in GH_ENV_TOKEN_NAMES:
        environment.pop(name, None)
    return environment


def read_heredoc_delimiter(command, index):
    """Consume the `<<`/`<<-` redirection starting at `index`.

    Returns (next_index, delimiter, strip_tabs); delimiter is None when the
    redirection is malformed.
    """
    length = len(command)
    cursor = index + 2
    strip_tabs = False
    if cursor < length and command[cursor] == "-":
        strip_tabs = True
        cursor += 1
    while cursor < length and command[cursor] in " \t":
        cursor += 1
    delimiter = []
    quote = None
    while cursor < length:
        character = command[cursor]
        if quote is not None:
            if character == quote:
                quote = None
            else:
                delimiter.append(character)
            cursor += 1
            continue
        if character in "'\"":
            quote = character
            cursor += 1
            continue
        if character == "\\" and cursor + 1 < length:
            delimiter.append(command[cursor + 1])
            cursor += 2
            continue
        if character in " \t\n;&|<>()":
            break
        delimiter.append(character)
        cursor += 1
    if quote is not None or not delimiter:
        return cursor, None, False
    return cursor, "".join(delimiter), strip_tabs


def skip_heredoc_bodies(command, index, pending):
    """Skip `pending` heredoc bodies. Returns None when one is unterminated."""
    length = len(command)
    for delimiter, strip_tabs in pending:
        closed = False
        while index < length:
            end = command.find("\n", index)
            if end == -1:
                line = command[index:]
                index = length
            else:
                line = command[index:end]
                index = end + 1
            candidate = line.lstrip("\t") if strip_tabs else line
            if candidate == delimiter:
                closed = True
                break
        if not closed:
            return None
    return index


def split_segments(command):
    """Split a shell command into its top-level segments.

    Quoted interiors stay inside their segment; comments and heredoc bodies are
    dropped. Neither can therefore open a command position. Returns None when
    the string cannot be parsed (unterminated quote or heredoc), which the
    caller treats as a fail-closed signal.
    """
    segments = []
    current = []
    pending = []
    quote = None
    index = 0
    length = len(command)
    while index < length:
        character = command[index]
        if quote == "'":
            current.append(character)
            if character == "'":
                quote = None
            index += 1
            continue
        if character == "\\" and index + 1 < length:
            current.append(character)
            current.append(command[index + 1])
            index += 2
            continue
        if quote == '"':
            current.append(character)
            if character == '"':
                quote = None
            index += 1
            continue
        if character in "'\"":
            quote = character
            current.append(character)
            index += 1
            continue
        if character == "#" and (not current or current[-1] in " \t"):
            while index < length and command[index] != "\n":
                index += 1
            continue
        if character == "<" and command.startswith("<<", index):
            if command.startswith("<<<", index):
                current.append("<<<")
                index += 3
                continue
            cursor, delimiter, strip_tabs = read_heredoc_delimiter(command, index)
            if delimiter is None:
                return None
            current.append(command[index:cursor])
            pending.append((delimiter, strip_tabs))
            index = cursor
            continue
        if character == "\n":
            # Heredoc bodies begin after the newline that ends the line which
            # declared them — never at an earlier `;`/`&`/`|` on that line.
            segments.append("".join(current))
            current = []
            index += 1
            if pending:
                index = skip_heredoc_bodies(command, index, pending)
                if index is None:
                    return None
                pending = []
            continue
        if character in SEGMENT_SEPARATORS:
            segments.append("".join(current))
            current = []
            while (
                index < length
                and command[index] in SEGMENT_SEPARATORS
                and command[index] != "\n"
            ):
                index += 1
            continue
        current.append(character)
        index += 1
    if quote is not None or pending:
        return None
    segments.append("".join(current))
    return segments


def tokenize_segment(segment):
    """Split one segment into (value, is_operator) tokens.

    Values are unquoted, so `"git" push` and `git  push` both tokenise to
    ["git", "push"] while a quoted `'git push origin main'` stays one token and
    can never match a multi-token verb. Returns None when the segment cannot be
    tokenised, which the caller treats as fail-closed.
    """
    tokens = []
    value = []
    started = False
    quote = None
    index = 0
    length = len(segment)
    while index < length:
        character = segment[index]
        if quote == "'":
            if character == "'":
                quote = None
            else:
                value.append(character)
            index += 1
            continue
        if character == "\\" and index + 1 < length:
            value.append(segment[index + 1])
            started = True
            index += 2
            continue
        if quote == '"':
            if character == '"':
                quote = None
            else:
                value.append(character)
            index += 1
            continue
        if character in "'\"":
            quote = character
            started = True
            index += 1
            continue
        if character in " \t":
            if started:
                tokens.append(("".join(value), False))
                value = []
                started = False
            index += 1
            continue
        if character in OPERATOR_CHARS:
            if started:
                tokens.append(("".join(value), False))
                value = []
                started = False
            tokens.append((character, True))
            index += 1
            continue
        value.append(character)
        started = True
        index += 1
    if quote is not None:
        return None
    if started:
        tokens.append(("".join(value), False))
    return tokens


def command_position_flags(tokens):
    """(flags, split_string): per token, does a simple command start here; and
    does an `env` at a command position take `-S`/`--split-string`?

    Keywords, assignments and wrappers keep the position open. A wrapper option
    that takes an argument (`env -u NAME`, `sudo -u user`, per the wrapper option
    tables) also consumes the next word, unless the argument is attached
    (`-uNAME`, `--user=anis`), so the wrapped program is the command word. An
    operator token ends any pending option argument.
    """
    flags = [False] * len(tokens)
    split_string = False
    open_position = True
    wrapper = None
    pending = 0
    for index, (value, operator) in enumerate(tokens):
        if operator:
            open_position, wrapper, pending = True, None, 0
            continue
        if not open_position:
            continue
        if pending:
            pending -= 1
            continue
        if ASSIGNMENT_PREFIX.match(value) is not None:
            continue
        if value in COMMAND_KEYWORDS or value in COMMAND_WRAPPERS:
            wrapper = value
            continue
        if wrapper is not None and value.startswith("-"):
            kind, attached = wrapper_option(wrapper, value)
            if kind == "payload":
                split_string = True
            if kind is not None and attached is None:
                pending += 1
            continue
        flags[index] = True
        open_position = False
    return flags, split_string


def program_name(word):
    """The basename of `word`: `/usr/bin/git` -> `git`."""
    return word.rsplit("/", 1)[-1]


def raw_words(text, glued=False):
    """The words of raw `text`, split at whitespace and RAW_WORD_BREAKS.

    With `glued`, quotes and backslashes are deleted first, as the shell joins
    the pieces around them into one word (issue 400 D16).

    A word that env's option table reads as a split-string option with attached
    command text (`-Sgit`, `--split-string=git`) is followed by that text as a
    word of its own, since env runs it (issue 400 D12).
    """
    words = []
    current = []
    for character in text + " ":
        if glued and character in RAW_GLUE_CHARS:
            continue
        if character.isspace() or character in RAW_WORD_BREAKS:
            if current:
                words.append("".join(current))
                current = []
        else:
            current.append(character)
    expanded = []
    for word in words:
        expanded.append(word)
        if word.startswith("-"):
            kind, attached = wrapper_option("env", word)
            if kind == "payload" and attached:
                expanded.append(attached)
    return expanded


def verb_occurs_in_order(words, verb_words):
    """True when `verb_words` occur in `words` in order, not necessarily
    adjacent, the program word matched by basename."""
    position = 0
    for word in words:
        candidate = program_name(word) if position == 0 else word
        if candidate == verb_words[position]:
            position += 1
            if position == len(verb_words):
                return True
    return False


def mentions_raise_label(texts):
    """True when any of `texts` contains the raise label, ignoring case."""
    return any(RAISE_LABEL in text.lower() for text in texts)


def adds_raise_label(tokens):
    """True when a `gh` invocation in `tokens` adds the raise label.

    Looks at every `gh` word, in any position: its words run to the end of
    `tokens` (the whole command's tokenised segments), skipping operator
    tokens, so a substitution, group or pipeline before the label
    (`gh pr edit $(… | …) --add-label …`) cannot hide it. A label value is
    the word after `--add-label` or the rest of a `--add-label=` word. No
    subcommand parsing and no comma splitting: a value that contains the label
    anywhere counts.
    """
    for index, (value, is_operator) in enumerate(tokens):
        if is_operator or os.path.basename(value) != "gh":
            continue
        words = [
            word for word, word_is_operator in tokens[index + 1:]
            if not word_is_operator
        ]
        labels = [
            words[position + 1]
            for position, word in enumerate(words[:-1])
            if word == "--add-label"
        ]
        labels.extend(
            word[len("--add-label="):]
            for word in words
            if word.startswith("--add-label=")
        )
        if any(RAISE_LABEL in label.lower() for label in labels):
            return True
    return False


def git_directory_problem(directory):
    """True when a `git -C` directory is not one plain word: empty, or holding
    whitespace, a quote or a shell-active character (issue 400 D7)."""
    return not directory or any(
        character.isspace() or character in "'\"" or character in UNSAFE_BRANCH_CHARS
        for character in directory
    )


def git_invocation(program, words):
    """(operation, problem, directory) for a guarded git invocation, else None
    (issue 400 D3).

    `words` follow the `git` word up to the end of its simple command. Leading
    words that begin with `-` are global options, each `-C` taking the next word
    as its directory. With no other option and at most one `-C`, the next word is
    the subcommand; otherwise `push`, or `branch` then `-d`, anywhere among
    `words` counts, since the walk cannot know which options take a value.
    `problem` is None for a plain `git` with no global option or one plain
    `-C <dir>`, else the recognition refusal (D6). `directory` is that `-C` value
    when `problem` is None, else None.
    """
    options = []
    directories = []
    index = 0
    while index < len(words) and words[index].startswith("-"):
        if words[index] == "-C" and index + 1 < len(words):
            directories.append(words[index + 1])
            index += 2
        else:
            options.append(words[index])
            index += 1
    if not options and len(directories) <= 1:
        candidates = [words[index:index + 2]]
    else:
        candidates = [words[position:position + 2] for position in range(len(words))]
    operation = None
    for candidate in candidates:
        if candidate[:1] == ["push"]:
            operation = "push"
        elif candidate == ["branch", "-d"]:
            operation = "branch"
        if operation is not None:
            break
    if operation is None:
        return None
    if program != "git":
        problem = "git named by a path"
    elif options:
        problem = f"git global option {options[0]} is not accepted"
    elif len(directories) > 1:
        problem = "git -C given more than once"
    elif directories and git_directory_problem(directories[0]):
        problem = (
            "the git -C directory must be one word without whitespace, quotes "
            "or shell-active characters"
        )
    else:
        return operation, None, (directories[0] if directories else None)
    return operation, f"{problem}; {INVOCATION_FORM_HINT}", None


def gh_invocation(program, words):
    """(operation, problem, None) for a guarded gh invocation, else None (issue 400 D4).

    Guarded when `words` begin with a guarded path (`pr merge`, `pr create`,
    `release create`, `release new`), or when a flag word comes before an
    occurrence of the path's second word that follows its first. Flags after
    the path never matter. A gh named by a path is refused (D6); a flag between
    the path words is left to the verb's grammar.
    """
    paths = [
        (list(verb_words[1:]), operation)
        for verb_words, operation in GUARDED_VERBS
        if verb_words[0] == "gh"
    ]
    found = next((operation for path, operation in paths if words[:2] == path), None)
    for (first, second), operation in paths:
        if found is not None:
            break
        if first not in words:
            continue
        start = words.index(first) + 1
        if any(
            words[position] == second
            and any(word.startswith("-") for word in words[:position])
            for position in range(start, len(words))
        ):
            found = operation
    if found is None:
        return None
    if program != "gh":
        return found, f"gh named by a path; {INVOCATION_FORM_HINT}", None
    return found, None, None


def guarded_invocation(tokens, index, later=""):
    """(operation, problem, directory) when the word at `index` starts a guarded
    git or gh invocation, matched by basename, else None.

    Its words run to the next operator token. `problem` is a recognition refusal
    or None; the caller still judges the command position. `later` is the raw
    text of the command's segments after this one. A run that ends at an
    operator (a substitution, expansion or grouping) before its verb is
    certain reads on through the rest of this segment and then `later`, in
    both raw readings, because a separator inside a substitution
    (`git -C $(pwd | cat) push …`) splits the invocation across segments
    (issue 400 D15, D17). A git verb is uncertain when the run ends inside the
    global options or carries an option other than `-C`, whose value the walk
    cannot bound (`git -c k=$(…) push …`); a gh verb is uncertain when the run
    carries a flag or ends before a third word (`gh pr --repo $(…) merge …`,
    issue 400 D18).
    """
    value, operator = tokens[index]
    if operator:
        return None
    words = []
    truncated = False
    for word, word_is_operator in tokens[index + 1:]:
        if word_is_operator:
            truncated = True
            break
        words.append(word)
    name = program_name(value)
    if name == "git":
        reader, uncertain = git_invocation, git_verb_uncertain(words)
    elif name == "gh":
        reader = gh_invocation
        uncertain = len(words) < 3 or any(word.startswith("-") for word in words)
    else:
        return None
    found = reader(value, words)
    if found is None and truncated and uncertain:
        rest = [word for word, is_operator in tokens[index + 1:] if not is_operator]
        loose = next(
            (
                reading for reading in (
                    reader(value, ["--"] + rest + raw_words(later, glued))
                    for glued in (False, True)
                )
                if reading is not None
            ),
            None,
        )
        if loose is not None:
            found = loose[0], (
                f"the {name} invocation continues past a shell substitution or "
                f"grouping; {INVOCATION_FORM_HINT}"
            ), None
    return found


def git_verb_uncertain(words):
    """True when the leading git global options in `words` leave the subcommand
    unknown: they run to the end of `words`, or one of them is not `-C`, so
    the walk cannot know how many words it takes (issue 400 D15, D18)."""
    index = 0
    while index < len(words) and words[index].startswith("-"):
        if words[index] != "-C" or index + 1 == len(words):
            return True
        index += 2
    return index >= len(words)


def git_option_operands(tokens, index):
    """Indices of the `-C` values in the leading global-option run of the word
    at `index` (issue 400 D15): arguments of git, never programs."""
    operands = []
    position = index + 1
    while (position < len(tokens) and not tokens[position][1]
           and tokens[position][0].startswith("-")):
        if (tokens[position][0] == "-C" and position + 1 < len(tokens)
                and not tokens[position + 1][1]):
            operands.append(position + 1)
            position += 2
        else:
            position += 1
    return operands


def unvalidatable(segment, reason, mentions_label=False):
    """Every guarded verb found in `segment`'s raw text, all refused for `reason`.

    A verb is found when its words occur in order in either reading of the
    text's quotes and backslashes (issue 400 D16), or when its words joined by
    one space are a substring of the text or of the text with its quotes and
    backslashes deleted (issue 400 D17, the base `336d9e05` check): a word such
    as `${CMD:-git` or `-df` has no word equal to the verb's, yet the shell runs
    the verb. When `mentions_label` is set, the raise-label edit is refused too.
    """
    readings = [raw_words(segment), raw_words(segment, glued=True)]
    texts = [segment, "".join(c for c in segment if c not in RAW_GLUE_CHARS)]
    found = [
        (operation, segment, reason, None)
        for verb_words, operation in GUARDED_VERBS
        if any(verb_occurs_in_order(words, verb_words) for words in readings)
        or any(" ".join(verb_words) in text for text in texts)
    ]
    if mentions_label:
        found.append(("label", segment, reason, None))
    return found


def guarded_operations(command):
    """(operation, segment, problem, directory) for every guarded verb the shell
    would run. `directory` is the accepted `git -C` value, else None.

    `problem` is None when the segment can be handed to that verb's grammar,
    and a reason when the verb sits where the guard cannot validate it: an
    unparseable command or untokenisable segment, shell source passed to an
    evaluator (`eval`, `sh -c`, matched by basename), or a position that is not
    a command position (an argument to some other program). Those are refused
    rather than waved through — the parser and the shell have to agree, and
    where they cannot the guard fails closed. A segment in which env takes
    `-S`/`--split-string` is judged like an evaluator segment, on its whole
    text, because env appends the remaining words to the split payload.

    Recognition refuses an invocation form before any lookup (issue 400 D6,
    D15, D18): git or gh named by a path, a git global option other than one
    `-C`, a repeated `-C` or a `-C` directory that is not one plain word, and a
    git or gh run that ends at an operator before its verb is certain and so
    continues past a substitution or grouping, read on through the rest of the
    command.

    The `label` operation is mention-gated: it is considered only when the
    command's tokens mention the raise label, always carries a problem, and is
    refused for any `gh` invocation, in any position, whose `--add-label` value
    contains it. That check runs over every tokenised segment at once, because
    a separator inside a substitution splits a `gh` word from its label. A
    word that mentions the label inside a `$(…)` or backtick substitution is
    refused too, because a quoted substitution still runs.
    """
    segments = split_segments(command)
    if segments is None:
        return unvalidatable(
            command, "the command could not be parsed",
            mentions_raise_label([command]),
        )
    found = []
    stream = []
    for position, segment in enumerate(segments):
        tokens = tokenize_segment(segment)
        if tokens is None:
            found.extend(unvalidatable(
                segment, "the segment could not be tokenised",
                mentions_raise_label([segment]),
            ))
            continue
        # Every tokenised segment joins the label stream, evaluator segments
        # included: `gh pr edit $(sh -c '…'; true) --add-label …` puts the
        # `gh` word in an evaluator segment and its label in the next one.
        stream.extend(tokens)
        stream.append((";", True))
        flags, split_string = command_position_flags(tokens)
        values = [value for value, _ in tokens]
        mentions = mentions_raise_label(values)
        # An env -S or evaluator segment is judged on its whole text, and its
        # words are still recognised below with that reason as their problem:
        # a git or gh run in it may continue into a later segment
        # (`git -C $(sh -c pwd | cat) push …`, issue 400 D15, D19), which the
        # segment's own raw text never shows.
        raw_reason = None
        if split_string:
            raw_reason = SPLIT_STRING_REASON
        elif any(
            flag and program_name(value) in SHELL_EVALUATORS
            for flag, value in zip(flags, values)
        ):
            raw_reason = EVALUATOR_REASON
        if raw_reason is not None:
            found.extend(unvalidatable(segment, raw_reason, mentions))
        operands = set()
        for index in range(len(tokens)):
            if index in operands:
                continue
            if not tokens[index][1] and program_name(tokens[index][0]) == "git":
                operands.update(git_option_operands(tokens, index))
            invocation = guarded_invocation(
                tokens, index, "\n".join(segments[position + 1:]))
            if invocation is None:
                continue
            operation, problem, directory = invocation
            if not flags[index]:
                problem, directory = NOT_COMMAND_POSITION, None
            if problem is None and raw_reason is not None:
                problem, directory = raw_reason, None
            found.append((operation, segment, problem, directory))
    # Judged over every tokenised segment at once: a separator inside a
    # substitution (`gh pr edit $(gh pr view | jq …) --add-label …`) splits
    # the `gh` word from its label, so a per-segment check would miss it.
    if mentions_raise_label([value for value, _ in stream]) and adds_raise_label(stream):
        found.append(("label", command, RAISE_LABEL_REFUSAL, None))
    # A substitution inside a double-quoted word (`x="$(gh pr edit … )"`) runs,
    # but the tokeniser keeps it as one word, so the guard cannot see its `gh`.
    # A word that mentions the label and carries a substitution fails closed.
    if any(
        not is_operator and mentions_raise_label([value])
        and ("$(" in value or "`" in value)
        for value, is_operator in stream
    ):
        found.append((
            "label", command,
            "a command substitution inside a quoted word cannot be validated",
            None,
        ))
    return found


# Wrapper options that consume an argument, so the word holding it is not the
# wrapped command. Used by the verb pass and the detaching pass. Short options
# may be clustered (`env -iu FOO`), and an argument may be attached (`-uanis`,
# `--user=anis`). An option not listed here is treated as a flag, so the word
# after it is taken as the command word.
WRAPPER_SHORT_OPTIONS_WITH_ARGUMENT = {
    "sudo": frozenset("ugCDhprtTU"),
    "exec": frozenset("a"),
    "env": frozenset("uCS"),
}
WRAPPER_OPTIONS_WITH_ARGUMENT = {
    "sudo": frozenset({
        "--user", "--group", "--close-from", "--chdir", "--host", "--prompt",
        "--role", "--type", "--command-timeout", "--other-user",
    }),
    "exec": frozenset(),
    "env": frozenset({"--unset", "--chdir", "--split-string"}),
}
# `env -S`/`--split-string` hands its argument to env, which splits it into a
# command line and runs it. That argument is command text, not a name.
ENV_SPLIT_STRING = "--split-string"
# A redirection operator standing alone takes the next word as its target.
BARE_REDIRECTION = re.compile(r"^(\d*|&)(>>?|<<?<?|<>|>&|<&)$")
ATTACHED_REDIRECTION = re.compile(r"^(\d+|&)?(>>?|<<?<?|<>|>&|<&)")
# A segment cut at the `&` of `2>&1` ends in an unescaped `>` or `<`. Only then
# does the next segment continue the same simple command.
DANGLING_REDIRECTION = re.compile(r"(?:^|[^\\])(?:\\\\)*[<>]$")


def split_redirection(value):
    """(word, redirection): `nohup>/dev/null` -> ("nohup", ">/dev/null").

    The shell ends a word at an unquoted `<` or `>`. Token values are already
    unquoted, so a quoted `"a>b"` splits too; that only ever over-refuses.
    """
    for index, character in enumerate(value):
        if character in "<>":
            return value[:index], value[index:]
    return value, ""


def wrapper_option(wrapper, option):
    """(kind, attached) for a wrapper option word.

    `kind` is None for a flag, "argument" for an option that consumes an
    argument and "payload" for env's split-string, whose argument is command
    text. `attached` is the argument carried in the same word, or None when the
    option takes the next word.
    """
    payload_letters = "S" if wrapper == "env" else ""
    if option.startswith("--"):
        name, equals, attached = option.partition("=")
        if wrapper == "env" and len(name) >= 3 and ENV_SPLIT_STRING.startswith(name):
            # getopt_long accepts any unambiguous prefix (`--split`); reading
            # more as command text only ever refuses more.
            return "payload", attached if equals else None
        if name in WRAPPER_OPTIONS_WITH_ARGUMENT.get(wrapper, ()):
            return "argument", attached if equals else None
        return None, None
    letters = WRAPPER_SHORT_OPTIONS_WITH_ARGUMENT.get(wrapper, frozenset())
    for index in range(1, len(option)):
        letter = option[index]
        if letter in letters:
            kind = "payload" if letter in payload_letters else "argument"
            return kind, option[index + 1:] or None
    return None, None


def detaching_command_flags(tokens, state=(True, None, (), False),
                            embedded_targets=True):
    """Per token: is it a word at which the shell may start a simple command?

    Returns (flags, payloads, state). `payloads` is the command text handed to
    `env -S`. `state` is (open_position, wrapper, pending_arguments,
    redirection_target) and carries a dangling redirection: `split_segments`
    cuts at the `&` of `2>&1`, so the next segment opens with its target.

    A word ending in a bare operator inside it (`X=>`, `worker>`) is ambiguous,
    because token values are unquoted: an unquoted `>` takes the next word as
    its target, a quoted one (`X='>'`) does not. `embedded_targets` picks one
    reading; `detaching_word` scans both and refuses on either.

    Like `command_position_flags`, which also steps over the arguments of
    wrapper options (`sudo -u anis nohup x`), but it also steps over
    redirections, attached (`nohup>log`) or not, so `>log nohup x` is seen. An
    operator token ends any pending option argument. The verb pass keeps
    `command_position_flags`; this pass has no such fail-closed backstop, hence
    the extra stepping.
    """
    flags = [False] * len(tokens)
    payloads = []
    open_position, wrapper, pending, target = state
    pending = list(pending)
    for index, (value, operator) in enumerate(tokens):
        if operator:
            open_position, wrapper, pending, target = True, None, [], False
            continue
        if target:
            target = False
            continue
        if not open_position:
            continue
        if BARE_REDIRECTION.match(value) is not None:
            target = True
            continue
        if ATTACHED_REDIRECTION.match(value) is not None:
            continue
        word, redirection = split_redirection(value)
        target = (embedded_targets
                  and BARE_REDIRECTION.match(redirection) is not None)
        if pending:
            if pending.pop(0) == "payload":
                payloads.append(value)
            continue
        if ASSIGNMENT_PREFIX.match(word) is not None:
            continue
        if word in COMMAND_KEYWORDS or word in COMMAND_WRAPPERS:
            wrapper = word
            continue
        if wrapper is not None and word.startswith("-"):
            kind, attached = wrapper_option(wrapper, word)
            if kind == "payload" and attached is not None:
                payloads.append(value)
            elif kind == "payload" or (kind == "argument" and attached is None
                                       and not redirection):
                # An option word that also carries a redirection may be a quoted
                # attached argument; taking the next word as the command then
                # only ever refuses more.
                pending.append(kind)
            continue
        flags[index] = True
        open_position = False
    return flags, payloads, (open_position, wrapper, tuple(pending), target)


def detaching_word(command):
    """The detaching word (`nohup`, `setsid`, `disown`) the shell would run, or None.

    Policy-free and global. A word at a command position matches by value or by
    basename, after any attached redirection is cut off (`nohup>log`). Where the
    guard cannot see command positions it matches raw text instead and fails
    closed: an unparseable command, an untokenisable segment, a segment whose
    command-position word (or its basename) is an evaluator, a token carrying
    `$(` or a backtick, and the command text handed to `env -S`. A raw-text match
    names the word that occurs earliest in that text. A word in argument
    position otherwise passes.
    """

    def earliest(text):
        hits = [(text.find(word), word) for word in DETACHING_WORDS if word in text]
        return min(hits)[1] if hits else None

    def name(value):
        return split_redirection(value)[0].rsplit("/", 1)[-1]

    fresh = (True, None, (), False)
    segments = split_segments(command)
    if segments is None:
        return earliest(command)
    # One scan per reading of a bare operator inside a word: as a redirection
    # whose target is the next word, and as a quoted character.
    readings = (True, False)
    states = dict.fromkeys(readings, fresh)
    for segment in segments:
        tokens = tokenize_segment(segment)
        if tokens is None:
            states = dict.fromkeys(readings, fresh)
            found = earliest(segment)
            if found is not None:
                return found
            continue
        flags = [False] * len(tokens)
        payloads = []
        for reading in readings:
            read_flags, read_payloads, after = detaching_command_flags(
                tokens, states[reading], embedded_targets=reading)
            # Only a redirection cut at its `&` (`2>&1`) continues into the next
            # segment; any real separator ends the simple command and its options.
            dangling = after[3] and DANGLING_REDIRECTION.search(segment) is not None
            states[reading] = after if dangling else fresh
            flags = [a or b for a, b in zip(flags, read_flags)]
            payloads.extend(read_payloads)
        for payload in payloads:
            found = earliest(payload)
            if found is not None:
                return found
        if any(
            flag and not operator and name(value) in SHELL_EVALUATORS
            for flag, (value, operator) in zip(flags, tokens)
        ):
            found = earliest(segment)
            if found is not None:
                return found
            continue
        for flag, (value, operator) in zip(flags, tokens):
            if operator:
                continue
            if flag and name(value) in DETACHING_WORDS:
                return name(value)
            if "$(" in value or "`" in value:
                found = earliest(value)
                if found is not None:
                    return found
    return None


def strip_spelling(text, spelling):
    """The rest of `text` after a leading `spelling`, or None.

    None also when the rest is empty or begins with whitespace: a doubled space
    is not the spelling (issue 400 D13).
    """
    if not text.startswith(spelling):
        return None
    rest = text[len(spelling):]
    if not rest or rest[0].isspace():
        return None
    return rest


def strip_scrub_prefix(text):
    """`text` without its leading credential-scrub prefix, else `text` unchanged."""
    for prefix in SCRUB_PREFIXES:
        rest = strip_spelling(text, prefix)
        if rest is not None:
            return rest
    return text


def canonical_text(operation, text, directory):
    """The text `operation`'s grammar judges (issue 400 D13).

    Push and PR creation are judged per segment, with leading whitespace dropped;
    every operation whose form-table entry carries the scrub-prefix property (all
    but branch deletion, issue 400 D2) then loses an exact scrub prefix; and,
    with a `git -C` `directory`, a leading `git -C <directory> ` becomes `git `.
    Text in any other spelling is returned whole, for the grammar to refuse.
    """
    if operation in ("push", "pr-create"):
        text = text.lstrip()
    if FORM_TABLE[operation]["scrub_prefix"]:
        text = strip_scrub_prefix(text)
    if directory is not None:
        rest = strip_spelling(text, f"git -C {directory} ")
        if rest is not None:
            text = "git " + rest
    return text


def target_directory(directory, cwd):
    """The directory a push's repository context is built from (issue 400 D7).

    The `git -C` `directory` joined to the payload `cwd` (an absolute one stands
    alone; no normalisation, so git resolves it as the shell's `git -C` would),
    or `cwd` with no `-C`. None when there is none to use: a relative
    `directory` with no string `cwd`, or no `-C` and no string `cwd`.
    """
    base = cwd if isinstance(cwd, str) and cwd else None
    if directory is None:
        return base
    if os.path.isabs(directory):
        return directory
    if base is None:
        return None
    return os.path.join(base, directory)


def detect_repository(git_bin, cwd, timeout):
    """Return the owner/name slug of cwd's origin remote, or None."""
    if not isinstance(cwd, str) or not cwd:
        return None
    try:
        child = subprocess.run(
            [git_bin, "-C", cwd, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if child.returncode != 0:
        return None
    url = child.stdout.strip()
    if url.endswith(".git"):
        url = url[: -len(".git")]
    for prefix in (
        "git@github.com:",
        "ssh://git@github.com/",
        "https://github.com/",
        "http://github.com/",
    ):
        if url.startswith(prefix):
            slug = url[len(prefix):]
            break
    else:
        return None
    slug = slug.strip("/")
    if SLUG_PATTERN.fullmatch(slug) is None:
        return None
    return slug


def default_branch(git_bin, cwd, timeout):
    """The branch origin/HEAD points at, or None when it cannot be resolved."""
    if not isinstance(cwd, str) or not cwd:
        return None
    try:
        child = subprocess.run(
            [git_bin, "-C", cwd, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if child.returncode != 0:
        return None
    prefix = "origin/"
    value = child.stdout.strip()
    if not value.startswith(prefix):
        return None
    name = value[len(prefix):]
    if REF_NAME_PATTERN.fullmatch(name) is None:
        return None
    return name


class BasePolicy:
    """The values of the base policy file named by `--base-policy`.

    The store file holds the five trusted members: the authorized owners, the
    literal integration bases and the absolute paths of `git`, `gh` and `jq`.
    Nothing outside this file supplies any of them; a test passes any file of the
    same schema.
    """

    def __init__(self, document):
        self.authorized_owners = frozenset(document["authorized_owners"])
        self.integration_bases = dict(document["integration_bases"])
        self.git_bin = document["git_bin"]
        self.gh_bin = document["gh_bin"]
        self.jq_bin = document["jq_bin"]


def _read_policy_bytes(path):
    """(bytes, None) for a regular file at `path` of at most POLICY_MAX_BYTES, else (None, why).

    The open never blocks (`O_NONBLOCK`, so a FIFO with no writer opens at once), and
    the descriptor's own `fstat` decides: anything but a regular file, a FIFO or a
    device such as `/dev/zero` behind a symlink included, is refused before a byte
    is read, and so is a file over the cap or one that grows past it while read.
    """
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOCTTY)
    except OSError as error:
        return None, str(error)
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            return None, "not a regular file"
        if status.st_size > POLICY_MAX_BYTES:
            return None, f"larger than {POLICY_MAX_BYTES} bytes"
        chunks = []
        size = 0
        while size <= POLICY_MAX_BYTES:
            chunk = os.read(descriptor, POLICY_MAX_BYTES + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > POLICY_MAX_BYTES:
            return None, f"larger than {POLICY_MAX_BYTES} bytes"
        return b"".join(chunks), None
    except OSError as error:
        return None, str(error)
    finally:
        os.close(descriptor)


def _load_json_object(path, keys):
    """(document, None) for a JSON object at `path` with exactly `keys`, else (None, reason)."""
    data, why = _read_policy_bytes(path)
    if data is None:
        return None, f"cannot load {path}: {why}"
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, f"cannot load {path}: {error}"
    if not isinstance(document, dict) or set(document) != keys:
        return None, f"{path}: expected an object with exactly the keys {', '.join(sorted(keys))}"
    return document, None


def load_base_policy(path):
    """(BasePolicy, None) for a well-formed base policy at `path`, else (None, reason)."""
    document, reason = _load_json_object(path, BASE_POLICY_KEYS)
    if document is None:
        return None, reason
    owners = document["authorized_owners"]
    if not isinstance(owners, list) or not all(
        isinstance(owner, str) and owner for owner in owners
    ):
        return None, f"{path}: authorized_owners must be a list of non-empty strings"
    bases = document["integration_bases"]
    if not isinstance(bases, dict) or not all(
        isinstance(repository, str) and repository and isinstance(base, str) and base
        for repository, base in bases.items()
    ):
        return None, f"{path}: integration_bases must be an object of non-empty strings"
    for key in ("git_bin", "gh_bin", "jq_bin"):
        if not isinstance(document[key], str) or not os.path.isabs(document[key]):
            return None, f"{path}: {key} must be an absolute path"
    return BasePolicy(document), None


def load_compiled_policy(path):
    """(rows, None) for a well-formed compiled policy at `path`, else ({}, reason).

    The file supplies derived rows alone: `derived_repositories` maps a repository
    slug to its row, and the guard reads a row's two branches and leaves
    `evidence` and `derivation` to the compiler that wrote them. The path is read
    without blocking and only when it is a regular file of at most
    POLICY_MAX_BYTES (`_read_policy_bytes`). A file that is anything else, cannot
    be read or carries any malformed row contributes no row at all, so it is never
    partially read, and it never blocks a call by itself.
    """
    document, reason = _load_json_object(path, COMPILED_POLICY_KEYS)
    if document is None:
        return {}, reason
    derived = document["derived_repositories"]
    if not isinstance(derived, dict):
        return {}, f"{path}: derived_repositories must be an object"
    for repository, row in derived.items():
        if not isinstance(repository, str) or SLUG_PATTERN.fullmatch(repository) is None:
            return {}, f"{path}: derived_repositories key {repository!r} is not an owner/name slug"
        if not isinstance(row, dict) or set(row) != DERIVED_ROW_KEYS:
            keys = ", ".join(sorted(DERIVED_ROW_KEYS))
            return {}, (
                f"{path}: derived_repositories {repository} must be an object "
                f"with exactly the keys {keys}"
            )
        for key in ("default_branch", "integration_branch"):
            branch = row[key]
            if not isinstance(branch, str) or REF_NAME_PATTERN.fullmatch(branch) is None:
                return {}, f"{path}: derived_repositories {repository} {key} must be a branch name"
        if not isinstance(row["evidence"], dict):
            return {}, f"{path}: derived_repositories {repository} evidence must be an object"
    if document["derivation"] is not None and not isinstance(document["derivation"], dict):
        return {}, f"{path}: derivation must be null or an object"
    return dict(derived), None


class Context:
    """Injected dependencies plus one target directory's repository facts,
    resolved once per directory (issue 400 D8).

    `cwd` is that directory: the payload `cwd`, or a push's `git -C` directory
    (`target_directory`). Building a context is the one place the compiled
    policy is opened and the one place the row check runs, so a command with no
    push, PR creation, merge or release creation never reads the first or
    starts the second.
    """

    def __init__(self, args, base, cwd, deadline):
        self.git_bin = args.git_bin
        self.gh_bin = args.gh_bin
        self.jq_bin = args.jq_bin
        self.deadline = deadline
        self.child_timeout = args.child_timeout_seconds
        self.authorized_owners = base.authorized_owners
        self.repository = detect_repository(self.git_bin, cwd, self.timeout)
        self.base_branch = default_branch(self.git_bin, cwd, self.timeout)
        self.cwd = cwd
        rows, self.compiled_problem = load_compiled_policy(args.policy)
        self.derived_row = rows.get(self.repository)
        self.row_problem = self._row_problem(base, args)
        # A derived row with two distinct branches declares an integration
        # branch exactly as an `integration_bases` entry does, so every reader
        # of `integration_bases` sees both without knowing where a row came from.
        # A row with a problem declares nothing.
        self.integration_bases = dict(base.integration_bases)
        if self.derived_row is not None and self.row_problem is None and (
            self.derived_row["integration_branch"] != self.derived_row["default_branch"]
        ):
            self.integration_bases[self.repository] = self.derived_row["integration_branch"]

    @property
    def timeout(self):
        """The bound for the next child, read immediately before it starts.

        A child starts only when its whole bound ends before the deadline: the
        bound is never clipped to the time left, so a child that starts has the
        full `--child-timeout-seconds` and one that cannot is refused before it
        starts.
        """
        if self.deadline - time.monotonic() < self.child_timeout:
            raise DeadlineExhausted()
        return self.child_timeout

    def _row_problem(self, base, args):
        """Why the repository's derived row cannot be used, or None (also None with no row).

        Three checks, in this order, and the first to fail is the answer: the
        literal conflict, `origin/HEAD` against the row's default branch, and the
        row check.
        """
        row = self.derived_row
        if row is None:
            return None
        if self.repository in base.integration_bases:
            return (
                f"repository {self.repository} has both a literal integration base "
                "and a derived policy row; repair: run claude-guard-policy"
            )
        if self.base_branch != row["default_branch"]:
            live = self.base_branch if self.base_branch is not None else "no branch"
            return (
                f"repository {self.repository}: origin/HEAD names {live}, "
                f"its derived policy row names {row['default_branch']}"
            )
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise DeadlineExhausted()
        return row_check_problem(
            args.derive_bin, self.repository, row,
            min(args.derive_timeout_seconds, remaining),
        )


def _report_mismatch(report, status, repository, row):
    """Why `report` (the row check's parsed stdout) does not confirm `row`, or None.

    A shape failure is an unreadable report; `evidence` is never compared.
    """
    unreadable = f"unreadable report (exit {status})"
    if not isinstance(report, dict) or report.get("repository") != repository:
        return unreadable
    outcome = report.get("outcome")
    if not isinstance(outcome, str) or ROW_CHECK_EXIT_STATUSES.get(outcome) != status:
        return unreadable
    if outcome == "derived":
        derived = report.get("row")
        branches = ("default_branch", "integration_branch")
        if not isinstance(derived, dict) or not all(
            isinstance(derived.get(key), str) for key in branches
        ):
            return unreadable
        if any(derived[key] != row[key] for key in branches):
            return (
                f"it derives {derived['default_branch']} and {derived['integration_branch']}, "
                f"the row names {row['default_branch']} and {row['integration_branch']}"
            )
        return None
    if outcome == "refused":
        refused = report.get("refused")
        if not isinstance(refused, list):
            return unreadable
        if not refused:
            return "refused (no registered project derives it)"
        if not all(
            isinstance(item, dict) and isinstance(item.get("reason_code"), str)
            for item in refused
        ):
            return unreadable
        return "refused (" + ", ".join(item["reason_code"] for item in refused) + ")"
    cause = report.get("cause")
    if not isinstance(cause, dict) or not isinstance(cause.get("reason_code"), str):
        return unreadable
    return f"unavailable ({cause['reason_code']})"


def row_check_env():
    """os.environ without the shell startup variables and exported bash functions.

    A `BASH_ENV` or `ENV` file, or a `BASH_FUNC_<name>%%` function, could make a
    shell script in the row check print a report the check never derived.
    """
    return {
        name: value
        for name, value in os.environ.items()
        if name not in ROW_CHECK_ENV_DROPPED
        and not name.startswith(ROW_CHECK_ENV_DROPPED_PREFIX)
    }


def row_check_problem(derive_bin, repository, row, timeout):
    """Why the row check does not confirm `row` for `repository`, or None when it does.

    The check is `derive_bin --repository <repository>`, run once with no stdin,
    the environment of `row_check_env`, its output captured and its own session,
    so one SIGKILL to its process group on the bound takes its descendants with
    it. The pipes are not read again after the kill; only the direct child is
    reaped.
    """
    why = None
    try:
        child = subprocess.Popen(
            [derive_bin, "--repository", repository],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=row_check_env(),
            start_new_session=True,
        )
    except OSError as error:
        why = f"could not start ({error})"
    else:
        try:
            stdout, _stderr = child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                # Gone, or (macOS) a group of zombies only, which signals as EPERM.
                pass
            child.wait()
            why = "timed out"
        else:
            try:
                report = json.loads(stdout)
            except ValueError:
                report = None
            why = _report_mismatch(report, child.returncode, repository, row)
    if why is None:
        return None
    return (
        f"repository {repository}: the row check did not confirm its derived "
        f"policy row: {why}; repair: run claude-guard-policy"
    )


def ownership_problem(context):
    """Why the context's repository is outside standing authorization, or None.

    A derived row authorizes exactly its repository, whoever the owner is, and
    only while it has no problem: it must not sit beside a literal integration
    base, and origin/HEAD must name the branch the row recorded as the default.
    Without a row the owner must be a literal authorized owner, and a compiled
    policy that contributed no row says why.
    """
    repository = context.repository
    if repository is None:
        return "repository unknown is outside standing authorization"
    if context.derived_row is not None:
        return context.row_problem
    if repository.split("/", 1)[0] not in context.authorized_owners:
        message = f"repository {repository} is outside standing authorization"
        if context.compiled_problem is not None:
            message += (
                f"; the compiled policy contributed no row: {context.compiled_problem}"
                "; repair: run claude-guard-policy"
            )
        return message
    return None


def authorized_bases(repository, base_branch, integration_bases):
    """The branches a guarded PR may target in `repository`.

    Always the default branch, plus the repository's declared integration
    branch when it has one. Membership decides only what may be TARGETED;
    the merge's protection requirement is applied to whichever base the PR
    actually carries.
    """
    bases = {base_branch}
    integration_base = integration_bases.get(repository)
    if integration_base is not None:
        bases.add(integration_base)
    return bases


def branch_name_problem(git_bin, branch, timeout):
    """Why `branch` is not a plain, safe branch name, or None; the problem names
    the value, escaped (issue 402 D4, D18)."""
    shown = shown_value(branch)
    if not branch:
        return "branch name must not be empty"
    if branch.startswith("-"):
        return f"branch {shown} must not begin with a dash"
    if ":" in branch:
        return f"refspec {shown} is not accepted; name the branch alone"
    if "+" in branch:
        return f"force-push refspec {shown} is not accepted"
    forbidden = next((c for c in branch if c in UNSAFE_BRANCH_CHARS), None)
    if forbidden is not None:
        return f"branch {shown} contains the forbidden character `{shown_character(forbidden)}`"
    if any(component in REF_NAMESPACE_COMPONENTS for component in branch.split("/")):
        # `refs/heads/main` and `heads/main` both name the branch `main`, so a
        # plain string comparison against the default branch would miss them.
        return f"namespaced ref {shown} is not accepted; name the branch directly"
    try:
        child = subprocess.run(
            [git_bin, "check-ref-format", "--branch", branch],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return BRANCH_VALIDATION_TIMEOUT
    if child.returncode != 0:
        return f"invalid branch name {shown}"
    return None


def free_text_problem(value, allow_newlines):
    """Why `value` is not safe to hand to the shell verbatim, or None."""
    if not value:
        return "must not be empty"
    forbidden = set(UNSAFE_TEXT_CHARS)
    if not allow_newlines:
        forbidden.add("\n")
    found = next((character for character in value if character in forbidden), None)
    if found is not None:
        return f"contains the forbidden character `{shown_character(found)}`"
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        return "contains an unpaired surrogate"
    return None


def compile_word(word, fail):
    """One bracket-stripped template word as a `Literal` or a `Slot`."""
    if LITERAL_WORD.fullmatch(word):
        return Literal(word)
    quoted = QUOTED_SLOT_WORD.fullmatch(word)
    if quoted:
        if quoted.group(1):
            fail(f"quoted slot {word!r} must not carry a prefix")
        name, is_quoted, prefix = quoted.group(2), True, ""
    else:
        slot = SLOT_WORD.fullmatch(word)
        if not slot:
            fail(f"word {word!r} is neither a literal nor a slot")
        prefix, name, is_quoted = slot.group(1), slot.group(2), False
    if name not in FORM_SLOTS:
        fail(f"slot <{name}> is not one of {', '.join(FORM_SLOTS)}")
    return Slot(name, is_quoted, prefix)


def compile_template(operation, template):
    """A template's elements: `Literal`, `Slot` and `Group` in order."""
    def fail(why):
        raise FormTableError(f"form table {operation}: {template!r}: {why}")

    elements = []
    group = None
    for word in template.split(" "):
        opens = word.startswith("[")
        closes = word.endswith("]")
        inner = word[1 if opens else 0:len(word) - 1 if closes else len(word)]
        if not inner:
            fail("empty word")
        if "[" in inner or "]" in inner:
            fail(f"misplaced bracket in {word!r}")
        if opens and group is not None:
            fail("a group does not nest")
        if closes and not opens and group is None:
            fail(f"{word!r} closes no group")
        element = compile_word(inner, fail)
        if opens:
            if not (isinstance(element, Literal) and element.word.startswith("-")):
                fail(f"a group must begin with a flag literal, not {inner!r}")
            group = []
        (elements if group is None else group).append(element)
        if closes:
            elements.append(Group(tuple(group)))
            group = None
    if group is not None:
        fail("a group is never closed")
    return tuple(elements)


def flag_words(elements):
    """The literal flag words in `elements`, groups included, and the flags each
    followed immediately by a quoted slot."""
    flags, quoted_value_flags = set(), set()
    for index, element in enumerate(elements):
        if isinstance(element, Group):
            inner_flags, inner_quoted = flag_words(element.elements)
            flags |= inner_flags
            quoted_value_flags |= inner_quoted
        elif isinstance(element, Literal) and element.word.startswith("-"):
            flags.add(element.word)
            following = elements[index + 1:index + 2]
            if following and isinstance(following[0], Slot) and following[0].quoted:
                quoted_value_flags.add(element.word)
    return flags, quoted_value_flags


def compile_form_table(table):
    """`table` as one `CompiledOperation` per operation, or `FormTableError`.

    Run first on every invocation, so a template that does not compile refuses
    every call instead of leaving a verb unjudged (issue 402 D14).
    """
    if not isinstance(table, dict) or set(table) != FORM_TABLE_OPERATIONS:
        raise FormTableError(
            "form table: the operations must be exactly "
            + ", ".join(sorted(FORM_TABLE_OPERATIONS))
        )
    compiled = {}
    for operation, entry in table.items():
        if not isinstance(entry, dict) or set(entry) != {"forms", *FORM_TABLE_PROPERTIES}:
            raise FormTableError(
                f"form table {operation}: the keys must be exactly forms, "
                + ", ".join(FORM_TABLE_PROPERTIES)
            )
        for name in FORM_TABLE_PROPERTIES:
            if not isinstance(entry[name], bool):
                raise FormTableError(f"form table {operation}: {name} must be a bool")
        forms = entry["forms"]
        if not isinstance(forms, tuple) or not forms:
            raise FormTableError(f"form table {operation}: forms must be a non-empty tuple")
        compiled_forms = []
        for form in forms:
            if (
                not isinstance(form, tuple)
                or len(form) != 3
                or not isinstance(form[0], str)
                or not isinstance(form[1], str)
                or not (form[2] is None or isinstance(form[2], str))
            ):
                raise FormTableError(
                    f"form table {operation}: a form must be (id, template, note), got {form!r}"
                )
            form_id, template, note = form
            if any(form_id == earlier.id for earlier in compiled_forms):
                raise FormTableError(f"form table {operation}: {template!r}: duplicate id {form_id}")
            elements = compile_template(operation, template)
            if not isinstance(elements[0], Literal):
                raise FormTableError(
                    f"form table {operation}: {template!r}: a form must begin with a literal"
                )
            if note is not None and any(
                placeholder not in NOTE_PLACEHOLDERS
                for placeholder in re.findall(r"<[^>]*>", note)
            ):
                raise FormTableError(
                    f"form table {operation}: {template!r}: the note names a placeholder "
                    "other than <integration> and <default>"
                )
            compiled_forms.append(CompiledForm(form_id, template, note, elements))
        programs = {form.elements[0].word for form in compiled_forms}
        if len(programs) != 1:
            raise FormTableError(
                f"form table {operation}: the forms begin with different literals: "
                + ", ".join(sorted(programs))
            )
        flags, quoted_value_flags = set(), set()
        for form in compiled_forms:
            form_flags, form_quoted = flag_words(form.elements)
            flags |= form_flags
            quoted_value_flags |= form_quoted
        compiled[operation] = CompiledOperation(
            operation, tuple(compiled_forms), entry["whole_text_characters"],
            entry["exact_spelling"], entry["scrub_prefix"], programs.pop(),
            frozenset(flags), frozenset(quoted_value_flags),
        )
    return compiled


def walk_form(elements, words, flags):
    """How far `words` follow a compiled form's `elements` from the first word.

    An optional group is entered only when the next word equals its flag; once
    entered, every element in it must match. A literal matches its own word; an
    unquoted slot takes one word not in `flags`; a glued slot takes a word that
    starts with its literal, its value the rest; a quoted slot takes any one
    word. `expected` is the element that could not be matched at `position`,
    None when every element matched; `quoted` holds the indices of the words
    quoted slots took.
    """
    position = 0
    values = {}
    quoted = set()

    def take(element):
        nonlocal position
        if position >= len(words):
            return False
        word = words[position]
        if isinstance(element, Literal):
            if word != element.word:
                return False
        elif element.quoted:
            values[element.name] = word
            quoted.add(position)
        elif element.prefix:
            if not word.startswith(element.prefix):
                return False
            values[element.name] = word[len(element.prefix):]
        elif word in flags:
            return False
        else:
            values[element.name] = word
        position += 1
        return True

    for element in elements:
        if isinstance(element, Group):
            if position < len(words) and words[position] == element.elements[0].word:
                for inner in element.elements:
                    if not take(inner):
                        return FormWalk(position, inner, values, frozenset(quoted))
            continue
        if not take(element):
            return FormWalk(position, element, values, frozenset(quoted))
    return FormWalk(position, None, values, frozenset(quoted))


def match_form(compiled, text):
    """The first of `compiled`'s forms that `text` spells, with its slot values, else None
    (issue 402 D2): the whole-text character rule, the `shlex` words, the forms in
    table order, and for an exact-spelling operation the rendered form against `text`."""
    if compiled.whole_text_characters and any(c in UNSAFE_BRANCH_CHARS for c in text):
        return None
    try:
        words = shlex.split(text)
    except ValueError:
        return None
    for form in compiled.forms:
        walk = walk_form(form.elements, words, compiled.flags)
        if walk.expected is not None or walk.position != len(words):
            continue
        if compiled.exact_spelling:
            rendered = " ".join(
                f'"{word}"' if index in walk.quoted else word
                for index, word in enumerate(words)
            )
            if rendered != text:
                return None
        return FormMatch(form, walk.values)
    return None


# Characters that join or redirect a command: their refusal adds the run-alone advice (D5).
ADVISED_CHARACTERS = frozenset(";&|<>\n")


def shown_character(character):
    """`character` as a message shows it: itself, or its escape when it does not print."""
    return character if character.isprintable() else repr(character)[1:-1]


def shown_value(value):
    """`value` as a message shows it: each character through `shown_character`,
    so a value holding a newline keeps the refusal on one line (D18)."""
    return "".join(shown_character(character) for character in value)


def forbidden_character(text, anywhere):
    """The first character of `text` in UNSAFE_BRANCH_CHARS, anywhere or only
    outside single and double quotes (a backslash escapes inside double quotes),
    else None."""
    quote = None
    index = 0
    while index < len(text):
        character = text[index]
        if quote == "'":
            if character == "'":
                quote = None
        elif quote == '"':
            if character == "\\":
                index += 1
            elif character == '"':
                quote = None
        elif not anywhere and character in "'\"":
            quote = character
        elif character in UNSAFE_BRANCH_CHARS:
            return character
        index += 1
    return None


def doubled_space_before(text, program):
    """Whether the raw text before the first whitespace-delimited `program` word
    holds two whitespace characters in a row."""
    match = re.search(rf"(?<!\S){re.escape(program)}(?!\S)", text)
    head = text[:match.start()] if match else text
    return re.search(r"\s\s", head) is not None


def element_spelling(element):
    """How a refusal names a form element: its word, or the slot as the form spells it."""
    if isinstance(element, Literal):
        return element.word
    if element.quoted:
        return f'"<{element.name}>"'
    return f"{element.prefix}<{element.name}>"


def structure_problem(compiled, words):
    """Step 7 (issue 402 D4, D16): read at the furthest point any form reached, ties
    to table order; None when every word matched a form."""
    best = None
    for form in compiled.forms:
        walk = walk_form(form.elements, words, compiled.flags)
        if walk.expected is None and walk.position == len(words):
            return None
        if best is None or walk.position > best.position:
            best = walk
    found = words[best.position] if best.position < len(words) else None
    if best.expected is None:
        if found in compiled.flags:
            return f"{found} is out of place"
        return f"unexpected {found} at the end"
    expected = element_spelling(best.expected)
    if found is None:
        return f"missing {expected}"
    if (isinstance(best.expected, Literal) and not best.expected.word.startswith("-")
            and not found.startswith("-")):
        return f"expected {expected}, found {found}"
    if isinstance(best.expected, Slot) or best.expected.word not in words[best.position:]:
        return f"missing {expected}"
    return f"{found} is out of place"


def form_problem(operation, compiled, text):
    """The first problem (issue 402 D4) of `text`, which `match_form` refused."""
    label = OPERATION_LABELS[operation]
    try:
        words, quoting = shlex.split(text), None
    except ValueError as error:
        words, quoting = None, f"invalid command quoting: {error}"
    start = None
    if words is not None and compiled.program in words:
        start = words.index(compiled.program)
    before = words[:start] if start else []
    if before and (before[0] in ("unset", "env") or before[0].startswith("-")):
        if not compiled.scrub_prefix:
            return f"{label} takes no credential-scrub prefix"
        problem = f"unaccepted credential-scrub prefix `{' '.join(before)}`"
        if doubled_space_before(text, compiled.program):
            problem += " (doubled space)"
        return problem
    character = forbidden_character(text, anywhere=compiled.whole_text_characters)
    if character is not None:
        problem = f"forbidden character `{shown_character(character)}`"
        if character in ADVISED_CHARACTERS:
            problem += (f": run the {label} as its own Bash call and read its output "
                        "with a follow-up call")
        return problem
    if quoting is not None:
        return quoting
    if before:
        return f"unaccepted wrapper `{' '.join(before)}`"
    if start is None:
        return "does not match an accepted form"
    rest = words[start:]
    if compiled.program == "git" and len(rest) > 1 and rest[1].startswith("-"):
        if rest[1] == "-C":
            return "git -C takes one unquoted directory word followed by a single space"
        return f"git global option {rest[1]} is not accepted"
    for index, word in enumerate(rest):
        if index and rest[index - 1] in compiled.quoted_value_flags:
            continue
        if word.startswith("-") and word not in compiled.flags:
            return f"unknown flag {word}"
    problem = structure_problem(compiled, rest)
    if problem is not None:
        return problem
    if compiled.exact_spelling:
        return (f"spell the {label} exactly as the accepted form: single spaces, "
                "free text in double quotes")
    return "does not match an accepted form"


def prefix_clause():
    """`optional prefix: …`: the one-name scrub spellings of the first credential
    name, in SCRUB_PREFIXES order (issue 402 D8)."""
    name = GH_ENV_TOKEN_NAMES[0]
    spellings = [
        spelling.rstrip() for spelling in SCRUB_PREFIXES
        if spelling.split() in (["unset", name, "&&"], ["env", "-u", name])
    ]
    return "optional prefix: " + " | ".join(spellings)


def declared_integration(context):
    """The context's integration branch when it declares one distinct from its
    resolved default branch, else None (also with no context)."""
    if context is None or context.base_branch is None:
        return None
    integration = context.integration_bases.get(context.repository)
    if integration is None or integration == context.base_branch:
        return None
    return integration


def accepted_forms(compiled, context, form_ids=None):
    """The accepted forms a text refusal prints, in table order (issue 402 D6, D7).

    `form_ids` names the forms the refusal's facts admit; None means before any
    PR lookup: every form, a noted form only where `declared_integration` names
    a branch. `context` fills `<slug>`, `<base>` (one form per authorized base)
    and the note; None fills nothing.
    """
    integration = declared_integration(context)
    printed = []
    for form in compiled.forms:
        if form_ids is None:
            if form.note is not None and integration is None:
                continue
        elif form.id not in form_ids:
            continue
        text = form.template
        if context is not None and context.repository is not None:
            text = text.replace("<slug>", context.repository)
        texts = [text]
        if "<base>" in text and context is not None and context.base_branch is not None:
            texts = [
                text.replace("<base>", base)
                for base in sorted(authorized_bases(
                    context.repository, context.base_branch, context.integration_bases))
            ]
        note = ""
        if form.note is not None:
            note = " (" + form.note.replace("<integration>", integration).replace(
                "<default>", context.base_branch) + ")"
        printed.extend(text + note for text in texts)
    return printed


def refuse(operation, problem, forms=()):
    """Print `operation`'s refusal and return 2 (issue 402 D3).

    With `forms` (a text refusal) the message continues `; accepted: ` and the
    forms joined by `; or `, then the prefix clause for an operation that takes
    a scrub prefix; without them (a refusal of the repository or forge state)
    it names only the problem.
    """
    message = f"unsafe {OPERATION_LABELS[operation]}: {problem}"
    if forms:
        message += "; accepted: " + "; or ".join(forms)
        if FORM_TABLE[operation]["scrub_prefix"]:
            message += "; " + prefix_clause()
    return block(message)


def validate_branch_delete(text, git_bin, timeout, compiled):
    """Branch deletion is guarded in every repository, ownership aside."""
    match = match_form(compiled, text)
    if match is None:
        return refuse("branch", form_problem("branch", compiled, text),
                      accepted_forms(compiled, None))
    branch = match.values["branch"]
    if branch.startswith("-"):
        return refuse("branch", f"branch {shown_value(branch)} must not begin with a dash",
                      accepted_forms(compiled, None))
    try:
        ref_check = subprocess.run(
            [git_bin, "check-ref-format", "--branch", branch],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return refuse("branch", BRANCH_VALIDATION_TIMEOUT)
    if ref_check.returncode != 0:
        return refuse("branch", f"invalid branch name {shown_value(branch)}",
                      accepted_forms(compiled, None))
    return 0


def tag_problem(tag):
    """Why `tag` is not a vMAJOR.MINOR.PATCH release tag, or None."""
    if SEMVER_TAG.fullmatch(tag) is None:
        return f"tag {shown_value(tag)} is not a vMAJOR.MINOR.PATCH tag"
    return None


def validate_tag_push(tag, context, compiled):
    """The tag-push arm: `git push origin refs/tags/<vX.Y.Z>` of an existing annotated tag.

    The caller has judged the owner and the raw characters. The tag must exist
    locally as an annotated tag object (`git cat-file -t` prints `tag`), so a
    lightweight tag, a missing one or a branch of the same name never passes.
    """
    problem = tag_problem(tag)
    if problem is not None:
        return refuse("push", problem, accepted_forms(compiled, context))
    try:
        kind = subprocess.run(
            [context.git_bin, "cat-file", "-t", TAG_REF_PREFIX + tag],
            capture_output=True,
            text=True,
            timeout=context.timeout,
            check=False,
            cwd=context.cwd,
        )
    except subprocess.TimeoutExpired:
        return refuse("push", "tag lookup timed out")
    if kind.returncode != 0 or kind.stdout.strip() != "tag":
        return refuse("push", f"{tag} is not an existing annotated tag")
    return 0


def validate_push(text, context, compiled):
    problem = ownership_problem(context)
    if problem is not None:
        return refuse("push", problem)
    match = match_form(compiled, text)
    if match is None:
        return refuse("push", form_problem("push", compiled, text),
                      accepted_forms(compiled, context))
    if match.form.id == "tag":
        return validate_tag_push(match.values["vX.Y.Z"], context, compiled)
    if match.form.id != "branch":
        raise AssertionError(f"unhandled push form {match.form.id}")
    branch = match.values["branch"]
    reason = branch_name_problem(context.git_bin, branch, context.timeout)
    if reason == BRANCH_VALIDATION_TIMEOUT:
        return refuse("push", reason)
    if reason is not None:
        return refuse("push", reason, accepted_forms(compiled, context))
    if context.base_branch is None:
        return refuse("push", "cannot resolve the repository default branch")
    if branch == context.base_branch:
        return refuse("push", f"refusing to push the default branch {branch}")
    return 0


def validate_pr_create(text, context, compiled):
    problem = ownership_problem(context)
    if problem is not None:
        return refuse("pr-create", problem)
    match = match_form(compiled, text)
    if match is None:
        return refuse("pr-create", form_problem("pr-create", compiled, text),
                      accepted_forms(compiled, context))
    repository_argument = match.values["slug"]
    base = match.values["base"]
    head = match.values["branch"]
    title = match.values["title"]
    body = match.values["body"]
    if repository_argument != context.repository:
        return refuse(
            "pr-create",
            f"--repo {shown_value(repository_argument)} is not the current repository "
            f"{context.repository}",
            accepted_forms(compiled, context),
        )
    reason = branch_name_problem(context.git_bin, head, context.timeout)
    if reason == BRANCH_VALIDATION_TIMEOUT:
        return refuse("pr-create", f"head {reason}")
    if reason is not None:
        return refuse("pr-create", f"head {reason}", accepted_forms(compiled, context))
    for name, value, allow_newlines in (("title", title, False), ("body", body, True)):
        text_problem = free_text_problem(value, allow_newlines)
        if text_problem is not None:
            return refuse("pr-create", f"{name} {text_problem}",
                          accepted_forms(compiled, context))
    if context.base_branch is None:
        return refuse("pr-create", "cannot resolve the repository default branch")
    allowed_bases = authorized_bases(
        context.repository, context.base_branch, context.integration_bases
    )
    if base not in allowed_bases:
        return refuse(
            "pr-create",
            f"--base {shown_value(base)} is not one of " + ", ".join(sorted(allowed_bases)),
            accepted_forms(compiled, context),
        )
    if head == base:
        return refuse("pr-create", "head and base must differ")
    return 0


def release_slot_problem(values, repository):
    """Why a matched release creation's slots fail, in order, or None."""
    problem = tag_problem(values["vX.Y.Z"])
    if problem is not None:
        return problem
    if values["slug"] != repository:
        return (f"--repo {shown_value(values['slug'])} is not the current repository "
                f"{repository}")
    title_problem = free_text_problem(values["title"], False)
    if title_problem is not None:
        return f"title {title_problem}"
    path = values["path"]
    if (
        not os.path.isabs(path)
        or any(character in UNSAFE_BRANCH_CHARS or character.isspace() for character in path)
    ):
        return (f"--notes-file {shown_value(path)} is not an absolute path without "
                "whitespace or shell-active characters")
    return None


def validate_release(text, context, compiled):
    """Release creation is judged on the whole canonical command, like the merge."""
    problem = ownership_problem(context)
    if problem is not None:
        return refuse("release", problem)
    match = match_form(compiled, text)
    if match is None:
        return refuse("release", form_problem("release", compiled, text),
                      accepted_forms(compiled, context))
    problem = release_slot_problem(match.values, context.repository)
    if problem is not None:
        return refuse("release", problem, accepted_forms(compiled, context))
    return 0


def merge_slot_problem(values, repository):
    """Why a matched merge's `<n>`, `<slug>` and `<subject>` fail, in order, or None."""
    number = values["n"]
    if (
        not number
        or any(character < "0" or character > "9" for character in number)
        or int(number) <= 0
    ):
        return f"PR number {shown_value(number)} is not a positive decimal number"
    if values["slug"] != repository:
        return (f"--repo {shown_value(values['slug'])} is not the current repository "
                f"{repository}")
    subject = values.get("subject")
    subject_problem = None if subject is None else free_text_problem(subject, False)
    if subject_problem is not None:
        return f"subject {subject_problem}"
    return None


def validate_merge(text, context, compiled):
    problem = ownership_problem(context)
    if problem is not None:
        return refuse("merge", problem)
    repository = context.repository
    # `text` is the whole canonical command, its scrub prefix already
    # stripped, so the merge still tolerates no other chaining.
    match = match_form(compiled, text)
    if match is None:
        return refuse("merge", form_problem("merge", compiled, text),
                      accepted_forms(compiled, context))
    problem = merge_slot_problem(match.values, repository)
    if problem is not None:
        return refuse("merge", problem, accepted_forms(compiled, context))
    number = match.values["n"]
    head_commit = match.values.get("sha")
    if head_commit is not None and HEAD_COMMIT.fullmatch(head_commit) is None:
        return refuse(
            "merge",
            f"--match-head-commit {shown_value(head_commit)} is not 40 lowercase "
            "hexadecimal characters",
            accepted_forms(compiled, context),
        )
    if match.form.id == "feature":
        delete_branch = True
    elif match.form.id == "release":
        delete_branch = False
    else:
        raise AssertionError(f"unhandled merge form {match.form.id}")
    if context.base_branch is None:
        return refuse("merge", "cannot resolve the repository default branch")
    allowed_bases = authorized_bases(
        repository, context.base_branch, context.integration_bases
    )
    integration_base = context.integration_bases.get(repository)

    # The release arm — no `--delete-branch` — exists for one PR shape
    # only: the declared integration branch promoted into the default
    # branch, whose head must survive the merge. Where no such branch is
    # declared there is nothing to spare, so refuse before any lookup.
    if not delete_branch and integration_base is None:
        return refuse(
            "merge",
            "missing --delete-branch: it may be omitted only in a repository "
            "with a declared integration branch",
            accepted_forms(compiled, context, ["feature"]),
        )

    try:
        pr_lookup = subprocess.run(
            [
                context.gh_bin, "pr", "view", number, "--repo", repository,
                "--json", "state,baseRefName,headRefName,url,statusCheckRollup",
            ],
            capture_output=True,
            text=True,
            timeout=context.timeout,
            check=False,
            env=gh_lookup_env(),
        )
    except subprocess.TimeoutExpired:
        return block("PR lookup timed out")
    if pr_lookup.returncode != 0:
        return block_child_failure("PR lookup failed", pr_lookup)

    try:
        base_predicate = " or ".join(
            f'.baseRefName == "{candidate}"' for candidate in sorted(allowed_bases)
        )
        pr_predicate_query = (
            f'.state == "OPEN" and ({base_predicate}) and '
            f'(.url | startswith("https://github.com/{repository}/pull/"))'
        )
        pr_predicate = subprocess.run(
            [
                context.jq_bin,
                "-e",
                pr_predicate_query,
            ],
            input=pr_lookup.stdout,
            capture_output=True,
            text=True,
            timeout=context.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return block("PR predicate timed out")
    if pr_predicate.returncode != 0:
        return block_child_failure("PR predicate failed", pr_predicate)

    # Protection is demanded of the branch this PR actually targets, not of
    # the default branch. The predicate above already confined it to
    # `allowed_bases`, so this reads back one of those names.
    try:
        pr_facts = json.loads(pr_lookup.stdout)
        base = pr_facts["baseRefName"]
    except (ValueError, KeyError, TypeError):
        return refuse("merge", "cannot read the PR base branch")
    if base not in allowed_bases:
        return refuse("merge", f"PR base {base} is not an authorized base")

    if not delete_branch:
        return validate_release_merge(pr_facts, base, integration_base, context, compiled)

    # The feature arm deletes the PR's head branch, so the head must be
    # disposable: never the default branch, never the declared integration
    # branch (#116 D5). Judged before any protection lookup.
    head = pr_facts.get("headRefName")
    if not isinstance(head, str) or not head:
        return refuse("merge", "cannot read the PR head branch")
    if head in (context.base_branch, integration_base):
        permanent = f"--delete-branch would delete the permanent branch {head}"
        # The one permanent head an arm still admits is the integration branch
        # promoted into the default branch: the release form names it.
        if (
            head == integration_base
            and base == context.base_branch
            and declared_integration(context) is not None
        ):
            return refuse("merge", permanent, accepted_forms(compiled, context, ["release"]))
        return refuse("merge", permanent)

    # A declared integration branch is deliberately exempt from the
    # protection demand: it is the development-pace branch, and its CI
    # gate lives in the shipping flow's wait-for-checks (nodo's CI is
    # path-filtered, so no required check could report on every PR shape
    # anyway). The default branch keeps the full demand — even if it is
    # ever also declared as the integration base.
    if (
        integration_base is not None
        and base == integration_base
        and base != context.base_branch
    ):
        return 0

    try:
        protection_lookup = subprocess.run(
            [context.gh_bin, "api", f"repos/{repository}/branches/{base}/protection"],
            capture_output=True,
            text=True,
            timeout=context.timeout,
            check=False,
            env=gh_lookup_env(),
        )
    except subprocess.TimeoutExpired:
        return block("protection lookup timed out")
    if protection_lookup.returncode != 0:
        return block_child_failure("protection lookup failed", protection_lookup)

    try:
        protection_predicate = subprocess.run(
            [
                context.jq_bin,
                "-e",
                "(.required_status_checks.contexts | length) > 0 "
                "and .enforce_admins.enabled == true",
            ],
            input=protection_lookup.stdout,
            capture_output=True,
            text=True,
            timeout=context.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return block("protection predicate timed out")
    if protection_predicate.returncode != 0:
        return block_child_failure("protection predicate failed", protection_predicate)
    return 0


def validate_release_merge(pr_facts, base, integration_base, context, compiled):
    """The release arm: the integration branch promoted into the default branch.

    Its head is permanent, so the merge may omit `--delete-branch`, and in
    return exactly that PR shape is required. Forge protection is not
    consulted: with path-filtered CI no required-status-check rule on the
    default branch can stand in for the release PR's actual checks, so the
    guard reads the PR's own rollup and demands every check completed and
    green — a pending, failed, cancelled, or empty rollup blocks.
    """
    head = pr_facts.get("headRefName")
    if not isinstance(head, str) or not head:
        return refuse("merge", "cannot read the PR head branch")
    if head != integration_base or base != context.base_branch:
        mismatch = (
            f"it may be omitted only when merging {integration_base} into "
            f"{context.base_branch}; this PR merges {shown_value(head)} into "
            f"{shown_value(base)}"
        )
        # A feature head still fits the feature arm, which names the missing flag;
        # a permanent head fits no arm.
        if head not in (context.base_branch, integration_base):
            return refuse("merge", f"missing --delete-branch: {mismatch}",
                          accepted_forms(compiled, context, ["feature"]))
        return refuse("merge", f"--delete-branch {mismatch}")
    try:
        rollup_predicate = subprocess.run(
            [
                context.jq_bin,
                "-e",
                '(.statusCheckRollup | type) == "array" '
                "and (.statusCheckRollup | length) > 0 "
                "and all(.statusCheckRollup[]; "
                '(.__typename == "CheckRun" and .status == "COMPLETED" '
                'and (.conclusion == "SUCCESS" or .conclusion == "SKIPPED" '
                'or .conclusion == "NEUTRAL")) '
                'or (.__typename == "StatusContext" and .state == "SUCCESS"))',
            ],
            input=json.dumps(pr_facts),
            capture_output=True,
            text=True,
            timeout=context.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return block("check rollup predicate timed out")
    if rollup_predicate.returncode != 0:
        return block_child_failure(
            "unsafe merge: the PR's check rollup is not entirely green",
            rollup_predicate,
        )
    return 0


def main():
    table = compile_form_table(FORM_TABLE)
    started = time.monotonic()
    parser = argparse.ArgumentParser(prog="claude-bash-lifecycle-guard")
    parser.add_argument("--base-policy", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--derive-bin", required=True)
    parser.add_argument("--derive-timeout-seconds", type=float, default=15)
    parser.add_argument("--git-bin", default=None)
    parser.add_argument("--gh-bin", default=None)
    parser.add_argument("--jq-bin", default=None)
    parser.add_argument("--child-timeout-seconds", type=float, default=5)
    args = parser.parse_args()

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeError) as error:
        return block(f"invalid hook input: malformed JSON: {error}")

    if not isinstance(payload, dict):
        return block("invalid hook input: expected a JSON object")
    tool_input = payload.get("tool_input")
    if payload.get("tool_name") != "Bash" or not isinstance(tool_input, dict):
        return block("invalid hook input: expected a Bash tool call")
    command = tool_input.get("command")
    if not isinstance(command, str):
        return block("invalid hook input: expected tool_input.command to be a string")

    word = detaching_word(command)
    if word is not None:
        return block(f"detaching command `{word}` refused: {DETACHING_ROUTES}")

    base, reason = load_base_policy(args.base_policy)
    if base is None:
        return block(f"invalid policy: {reason}")
    if args.git_bin is None:
        args.git_bin = base.git_bin
    if args.gh_bin is None:
        args.gh_bin = base.gh_bin
    if args.jq_bin is None:
        args.jq_bin = base.jq_bin

    operations = guarded_operations(command)
    for operation, _segment, problem, _directory in operations:
        if operation == "label":
            return block(f"unsafe {OPERATION_LABELS[operation]}: {problem}")

    # One context per distinct target directory, all under one deadline.
    contexts = {}
    for operation, segment, problem, directory in operations:
        if time.monotonic() >= started + INVOCATION_DEADLINE_SECONDS:
            return refuse(operation, DEADLINE_REFUSAL)
        if problem is not None:
            return refuse(operation, problem, accepted_forms(table[operation], None))
        try:
            # Push and PR creation are judged per segment; the other verbs on the
            # whole command, so they tolerate no chaining.
            judged = segment if operation in ("push", "pr-create") else command
            text = canonical_text(operation, judged, directory)
            if operation == "branch":
                # Branch deletion is judged in every repository: it needs no
                # forge state.
                status = validate_branch_delete(
                    text, args.git_bin, args.child_timeout_seconds, table[operation]
                )
            else:
                target = target_directory(directory, payload.get("cwd"))
                context = contexts.get(target)
                if context is None:
                    context = contexts[target] = Context(
                        args, base, target,
                        started + INVOCATION_DEADLINE_SECONDS,
                    )
                if operation == "push":
                    status = validate_push(text, context, table[operation])
                elif operation == "pr-create":
                    status = validate_pr_create(text, context, table[operation])
                elif operation == "release":
                    status = validate_release(text, context, table[operation])
                else:
                    status = validate_merge(text, context, table[operation])
        except DeadlineExhausted:
            return refuse(operation, DEADLINE_REFUSAL)
        if status != 0:
            return status
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(
            f"lifecycle guard: unexpected failure: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        raise SystemExit(2)
